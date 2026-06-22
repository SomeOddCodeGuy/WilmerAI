# /Middleware/workflows/handlers/impl/web_fetch_handler.py

import json
import logging
import os
from html.parser import HTMLParser
from typing import Any, Dict, FrozenSet, List, Optional
from urllib.parse import urljoin, urlsplit

import requests

from Middleware.utilities.network_security_utils import check_url_allowed
from Middleware.utilities.streaming_utils import stream_static_content
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30
# Redirect status codes followed when the (opt-in) address guard is active and we
# follow redirects manually so each hop's host can be validated before connecting.
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 10
# Default body-size cap (bytes). A reasonable default that prevents a huge or
# chunked-infinite response from being buffered into memory, while remaining
# generous for normal text/JSON/HTML payloads. Set `maxResponseBytes` to 0 (or
# a negative number) on the node to disable the cap.
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_VALID_OUTPUT_FORMATS = ("text", "json", "full", "html-stripped")
_VALID_ON_ERROR = ("raise", "return")
# Credential-bearing headers that must not be carried to a different host across a
# redirect (mirrors requests/browser behavior). The manual-redirect path is only
# active under the address guard, where requests is not following redirects itself,
# so this stripping has to be done here.
_CROSS_HOST_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


class _ResponseTooLargeError(Exception):
    """Raised when a fetched response body exceeds the configured byte cap."""


class _AddressNotAllowedError(requests.exceptions.RequestException):
    """Raised when a request target violates the configured SSRF address policy.

    Subclasses ``RequestException`` so it flows through the handler's existing
    request-failure path and is honored by ``onError`` like any other fetch failure.
    """


_HTML_STRIP_SKIP_TAGS = frozenset({"script", "style", "head", "noscript", "iframe"})


class _HtmlTextExtractor(HTMLParser):
    """A minimal stdlib-only HTML→text extractor.

    Skips content inside non-visible container tags (script/style/head/noscript/iframe)
    and collects everything else as text, one non-empty chunk per text-bearing element.
    Character entities are decoded automatically by the parser (Python 3's HTMLParser
    has `convert_charrefs=True` by default).

    Notes:
    - Self-closing/void elements like <meta> and <link> are inside <head>, which we
      already skip entirely, so they need no special handling.
    - Real-world HTML can be malformed; HTMLParser is lenient and won't raise. The
      output may include extra junk on broken pages, which is preferable to silently
      dropping the request.
    """

    def __init__(self) -> None:
        """Initializes the extractor with a clean skip-depth counter and parts buffer."""
        super().__init__()
        self._skip_depth: int = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List) -> None:
        """Enters skip mode when a start tag opens a non-visible container.

        Args:
            tag (str): The lowercased name of the start tag.
            attrs (List): The tag's attributes as (name, value) pairs (unused).
        """
        if tag in _HTML_STRIP_SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        """Exits skip mode when a non-visible container's end tag closes.

        Args:
            tag (str): The lowercased name of the end tag.
        """
        if tag in _HTML_STRIP_SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        """Collects a non-empty text chunk unless currently inside a skipped container.

        Args:
            data (str): The text content of the current element.
        """
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def get_text(self) -> str:
        """Joins the collected text chunks into a single newline-separated string.

        Returns:
            str: The accumulated visible text, one chunk per line.
        """
        return "\n".join(self._parts)


def _strip_html(html: str) -> str:
    """Runs the stdlib stripper over an HTML string and returns the visible text.

    Args:
        html (str): The HTML source to extract visible text from.

    Returns:
        str: The visible text content with non-visible container tags stripped.
    """
    extractor = _HtmlTextExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.get_text()


class WebFetchHandler(BaseHandler):
    """
    Handles the execution of 'WebFetch' nodes.

    Issues an HTTP request to a user-configured URL using the `requests` library
    and returns the response in the configured output format. All string fields
    (url, header values, body) support workflow variable substitution.
    """

    def handle(self, context: ExecutionContext) -> Any:
        """
        Executes an HTTP request as configured on the node and returns the result.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: A string payload (text/JSON-serialized), or a streaming generator
                 wrapping that payload when `context.stream` is True.

        Raises:
            ValueError: If required config is missing, an enum field has an invalid
                value, `timeout`/`maxResponseBytes` is not numeric, `timeout` is
                non-positive, `allowRedirects`/`verify` is not a boolean, or `caBundle`
                is set but is not a string or points at a file that does not exist.
            requests.exceptions.RequestException: When `onError` is "raise" and the
                request fails (connection error, timeout, or HTTP 4xx/5xx).
            _ResponseTooLargeError: When `onError` is "raise" and the response body
                exceeds `maxResponseBytes`.
        """
        config = context.config

        url_template = config.get("url")
        if not url_template:
            raise ValueError("WebFetch node requires a 'url' field.")

        method = str(config.get("method", "GET")).upper()
        timeout = self._validate_timeout(config.get("timeout", _DEFAULT_TIMEOUT_SECONDS))
        output_format = config.get("outputFormat", "text")
        on_error = config.get("onError", "raise")
        proxy_template = config.get("proxy")
        allow_redirects = self._validate_bool(config.get("allowRedirects", True), "allowRedirects")
        max_bytes = self._validate_max_bytes(config.get("maxResponseBytes", _DEFAULT_MAX_RESPONSE_BYTES))
        block_private = self._validate_bool(config.get("blockPrivateAddresses", False), "blockPrivateAddresses")
        allowed_hosts = self._resolve_allowed_hosts(config.get("allowedHosts"), context)

        if output_format not in _VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"WebFetch 'outputFormat' must be one of {_VALID_OUTPUT_FORMATS}; got {output_format!r}."
            )
        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"WebFetch 'onError' must be one of {_VALID_ON_ERROR}; got {on_error!r}."
            )

        url = self.workflow_variable_service.apply_variables(url_template, context)

        headers = self._resolve_headers(config.get("headers"), context)

        body_template = config.get("body")
        body: Optional[str] = None
        if body_template is not None:
            body = self.workflow_variable_service.apply_variables(str(body_template), context)

        proxies = self._resolve_proxies(proxy_template, context)
        verify = self._resolve_verify(config.get("verify", True), config.get("caBundle"), context)

        logger.debug("WebFetch issuing %s %s (timeout=%s, outputFormat=%s, proxy=%s, verify=%s)",
                     method, url, timeout, output_format, bool(proxies), verify)

        cap_enabled = max_bytes > 0
        try:
            response = self._request_with_guard(
                method=method,
                url=url,
                headers=headers,
                data=body,
                timeout=timeout,
                proxies=proxies,
                verify=verify,
                allow_redirects=allow_redirects,
                stream=cap_enabled,
                block_private=block_private,
                allowed_hosts=allowed_hosts,
            )
            response.raise_for_status()
            if cap_enabled:
                self._load_capped_content(response, max_bytes)
        except (requests.exceptions.RequestException, _ResponseTooLargeError) as exc:
            logger.warning("WebFetch request failed: %s", exc)
            if on_error == "raise":
                # Don't read the (possibly huge) error body, but close the streamed
                # response so its socket/connection isn't held open until GC.
                if cap_enabled:
                    err_response = getattr(exc, "response", None)
                    if err_response is not None:
                        err_response.close()
                raise
            if cap_enabled:
                # The error return path renders response.text below; for a streamed
                # response that would lazily pull the ENTIRE error body off the socket
                # with no limit, defeating maxResponseBytes when a hostile endpoint
                # answers with a multi-gigabyte/chunked-infinite error body. Bound it.
                err_response = getattr(exc, "response", None)
                if err_response is not None:
                    self._load_capped_error_body(err_response, max_bytes)
            result = self._format_error(exc, output_format)
            return self._maybe_stream(result, context)

        try:
            result = self._format_response(response, output_format)
        except ValueError as exc:
            # outputFormat:"json" calls response.json(), which raises a
            # JSONDecodeError (a ValueError subclass) on a non-JSON 200 body.
            # Honor onError just like a transport/HTTP failure rather than
            # letting the decode error escape uncaught. Pass the response so the
            # decoded body is returned per the onError table ("response body if
            # available"); JSONDecodeError carries no .response of its own.
            logger.warning("WebFetch could not format response as %s: %s", output_format, exc)
            if on_error == "raise":
                raise
            result = self._format_error(exc, output_format, response=response)
        return self._maybe_stream(result, context)

    def _request_with_guard(
        self,
        *,
        method: str,
        url: str,
        headers: Dict[str, str],
        data: Optional[str],
        timeout: float,
        proxies: Optional[Dict[str, str]],
        verify: Any,
        allow_redirects: bool,
        stream: bool,
        block_private: bool,
        allowed_hosts: FrozenSet[str],
    ):
        """Issues the request, enforcing the SSRF address policy on every hop.

        When neither ``blockPrivateAddresses`` nor ``allowedHosts`` is set the guard is
        inert and ``requests`` handles redirects itself (the node's original behavior).
        When the guard is active, redirects are followed manually so each hop's host is
        validated BEFORE the connection is made; an out-of-policy target raises
        ``_AddressNotAllowedError`` (honored by ``onError`` like any other failure).

        Args:
            method (str): The HTTP method to use.
            url (str): The fully resolved request URL.
            headers (Dict[str, str]): The request headers (sent only if non-empty).
            data (Optional[str]): The request body, or None.
            timeout (float): The per-request timeout in seconds.
            proxies (Optional[Dict[str, str]]): The proxy mapping for requests, or None.
            verify (Any): The TLS-verification setting (True, False, or a CA bundle path).
            allow_redirects (bool): Whether to follow redirects.
            stream (bool): Whether to stream the response body (cap enabled).
            block_private (bool): Whether to block private/internal addresses.
            allowed_hosts (FrozenSet[str]): The lowercased host allowlist (empty = no allowlist).

        Returns:
            requests.Response: The response from the final (non-redirect) hop.

        Raises:
            _AddressNotAllowedError: When a hop's target violates the SSRF address policy.
            requests.exceptions.TooManyRedirects: When the redirect chain exceeds the limit.
        """
        guard_active = block_private or bool(allowed_hosts)
        if not guard_active:
            return requests.request(
                method=method,
                url=url,
                headers=headers if headers else None,
                data=data,
                timeout=timeout,
                proxies=proxies,
                verify=verify,
                allow_redirects=allow_redirects,
                stream=stream,
            )

        current_url, current_method, current_data, current_headers = url, method, data, headers
        for _ in range(_MAX_REDIRECTS + 1):
            reason = check_url_allowed(current_url, block_private, allowed_hosts)
            if reason:
                raise _AddressNotAllowedError(
                    f"WebFetch blocked a request to a disallowed address: {reason}."
                )
            response = requests.request(
                method=current_method,
                url=current_url,
                headers=current_headers if current_headers else None,
                data=current_data,
                timeout=timeout,
                proxies=proxies,
                verify=verify,
                allow_redirects=False,
                stream=stream,
            )
            if not allow_redirects or response.status_code not in _REDIRECT_STATUS:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            next_url = urljoin(current_url, location)
            # Mirror browser/requests redirect semantics: 301/302/303 demote a non-GET/HEAD
            # to GET and drop the request body; 307/308 preserve both.
            if response.status_code in (301, 302, 303) and current_method not in ("GET", "HEAD"):
                current_method = "GET"
                current_data = None
                current_headers = {
                    k: v for k, v in (current_headers or {}).items()
                    if k.lower() not in ("content-length", "content-type")
                }
            if not self._same_host(current_url, next_url):
                # Don't leak credentials to a different host on a redirect. requests
                # does this for its own redirects; the manual path must do it too.
                current_headers = {
                    k: v for k, v in (current_headers or {}).items()
                    if k.lower() not in _CROSS_HOST_SENSITIVE_HEADERS
                }
            response.close()
            current_url = next_url
        raise requests.exceptions.TooManyRedirects(
            f"WebFetch exceeded the maximum of {_MAX_REDIRECTS} redirects."
        )

    @staticmethod
    def _same_host(url_a: str, url_b: str) -> bool:
        """Reports whether two URLs share the same host (case-insensitive).

        Args:
            url_a (str): The first URL to compare.
            url_b (str): The second URL to compare.

        Returns:
            bool: True when both URLs resolve to the same hostname.
        """
        return (urlsplit(url_a).hostname or "").lower() == (urlsplit(url_b).hostname or "").lower()

    def _resolve_allowed_hosts(
        self,
        allowed_hosts_template: Any,
        context: ExecutionContext,
    ) -> FrozenSet[str]:
        """Resolves the optional ``allowedHosts`` allowlist to a set of lowercased hosts.

        Absent (``None``) means no allowlist (empty set). Each entry supports variable
        substitution so an allowlist can be sourced from a workflow variable.

        Args:
            allowed_hosts_template (Any): The configured allowlist (None or a list of host strings).
            context (ExecutionContext): The runtime context used for variable substitution.

        Returns:
            FrozenSet[str]: The lowercased, substituted host allowlist (empty when absent).

        Raises:
            ValueError: When ``allowedHosts`` is set but is not a list.
        """
        if allowed_hosts_template is None:
            return frozenset()
        if not isinstance(allowed_hosts_template, list):
            raise ValueError("WebFetch 'allowedHosts' must be a JSON list of host strings.")
        resolved = set()
        for entry in allowed_hosts_template:
            value = self.workflow_variable_service.apply_variables(str(entry), context).strip().lower()
            if value:
                resolved.add(value)
        return frozenset(resolved)

    def _resolve_proxies(
        self,
        proxy_template: Any,
        context: ExecutionContext,
    ) -> Optional[Dict[str, str]]:
        """Resolves the optional ``proxy`` URL into a requests proxy mapping.

        Absent (``None``) or an empty resolved value means no proxy. The URL supports
        variable substitution and is applied to both the http and https schemes.

        Args:
            proxy_template (Any): The configured proxy value (None or a string URL).
            context (ExecutionContext): The runtime context used for variable substitution.

        Returns:
            Optional[Dict[str, str]]: A {http, https} proxy mapping, or None when unset.

        Raises:
            ValueError: When ``proxy`` is set but is not a string.
        """
        if proxy_template is None:
            return None
        if not isinstance(proxy_template, str):
            raise ValueError(
                "WebFetch 'proxy' must be a string URL (e.g., 'socks5://host:1080')."
            )
        resolved = self.workflow_variable_service.apply_variables(proxy_template, context)
        if not resolved:
            return None
        return {"http": resolved, "https": resolved}

    def _resolve_verify(
        self,
        verify_value: Any,
        ca_bundle_template: Any,
        context: ExecutionContext,
    ):
        """Resolves the TLS-verification setting for the request.

        Both controls are strictly OPT-IN: the defaults (``verify`` absent ->
        True, ``caBundle`` absent -> None) reproduce the node's original
        always-on certifi verification byte-for-byte, so existing nodes are
        unaffected.

        The returned value is suitable for ``requests``' ``verify`` parameter:
        - ``True``  -> default verification against the bundled certifi CA store.
        - a path    -> verify against a custom CA bundle (PEM) the author supplies
                       via ``caBundle`` (e.g. a private/internal CA). Verification
                       stays ON; this just adds trust for that CA.
        - ``False`` -> verification disabled (only when the author explicitly sets
                       ``verify: false``).

        Precedence: an explicit ``verify: false`` disables verification and
        ``caBundle`` is ignored. Otherwise a non-empty ``caBundle`` is used.

        Args:
            verify_value (Any): The configured ``verify`` flag (a boolean).
            ca_bundle_template (Any): The configured ``caBundle`` path (None or a string).
            context (ExecutionContext): The runtime context used for variable substitution.

        Returns:
            Any: True, False, or a resolved CA bundle path, per the precedence above.

        Raises:
            ValueError: When ``verify`` is not a boolean, ``caBundle`` is set but is not
                a string, or the resolved ``caBundle`` path does not point at a file.
        """
        verify = self._validate_bool(verify_value, "verify")
        if not verify:
            logger.warning(
                "WebFetch TLS certificate verification is DISABLED (verify=false). The "
                "connection is exposed to man-in-the-middle attacks; use only for trusted hosts."
            )
            return False
        if ca_bundle_template is None:
            return True
        if not isinstance(ca_bundle_template, str):
            raise ValueError(
                "WebFetch 'caBundle' must be a string path to a CA bundle (PEM) file."
            )
        resolved = self.workflow_variable_service.apply_variables(ca_bundle_template, context)
        if not resolved:
            return True
        if not os.path.isfile(resolved):
            raise ValueError(f"WebFetch 'caBundle' file not found: {resolved!r}.")
        return resolved

    def _resolve_headers(
        self,
        headers_template: Optional[Dict[str, Any]],
        context: ExecutionContext,
    ) -> Dict[str, str]:
        """Resolves the optional ``headers`` object into a flat string-to-string mapping.

        Absent or empty means no headers. Each value supports variable substitution; both
        names and resolved values are coerced to strings.

        Args:
            headers_template (Optional[Dict[str, Any]]): The configured headers object, or None.
            context (ExecutionContext): The runtime context used for variable substitution.

        Returns:
            Dict[str, str]: The resolved header name/value pairs (empty when unset).

        Raises:
            ValueError: When ``headers`` is set but is not a dict.
        """
        if not headers_template:
            return {}
        if not isinstance(headers_template, dict):
            raise ValueError("WebFetch 'headers' must be a JSON object.")
        resolved: Dict[str, str] = {}
        for name, value in headers_template.items():
            resolved_value = self.workflow_variable_service.apply_variables(str(value), context)
            resolved[str(name)] = resolved_value
        return resolved

    @staticmethod
    def _validate_timeout(value: Any) -> float:
        """Coerces the configured timeout to a positive number of seconds.

        Mirrors the node's other up-front field validations so a non-numeric
        or non-positive value raises a clear ``ValueError`` instead of an
        opaque ``TypeError`` from deep inside ``requests``.

        Args:
            value (Any): The configured ``timeout`` value to validate and coerce.

        Returns:
            float: The validated timeout as a positive number of seconds.

        Raises:
            ValueError: When the value is a boolean, non-numeric, or not positive.
        """
        if isinstance(value, bool):
            raise ValueError(f"WebFetch 'timeout' must be a number of seconds; got {value!r}.")
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"WebFetch 'timeout' must be a number of seconds; got {value!r}.")
        if value <= 0:
            raise ValueError(f"WebFetch 'timeout' must be a positive number of seconds; got {value!r}.")
        return value

    @staticmethod
    def _validate_bool(value: Any, field: str) -> bool:
        """Validates a boolean config field, mirroring the node's other field validations.

        Args:
            value (Any): The configured value to validate.
            field (str): The field name, used in the error message.

        Returns:
            bool: The validated boolean value.

        Raises:
            ValueError: When the value is not a boolean.
        """
        if not isinstance(value, bool):
            raise ValueError(f"WebFetch '{field}' must be a boolean (true/false); got {value!r}.")
        return value

    @staticmethod
    def _validate_max_bytes(value: Any) -> int:
        """Coerces the configured response cap to an integer number of bytes.

        ``0`` (or any non-positive value) disables the cap. A non-numeric value
        raises a clear ``ValueError`` rather than failing deep in the read loop.

        Args:
            value (Any): The configured ``maxResponseBytes`` value to validate and coerce.

        Returns:
            int: The validated cap in bytes (non-positive disables the cap).

        Raises:
            ValueError: When the value is a boolean or cannot be coerced to an integer.
        """
        if isinstance(value, bool):
            raise ValueError(f"WebFetch 'maxResponseBytes' must be an integer; got {value!r}.")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"WebFetch 'maxResponseBytes' must be an integer; got {value!r}.")
        return value

    @staticmethod
    def _load_capped_content(response: requests.Response, max_bytes: int) -> None:
        """Reads a streamed response body up to ``max_bytes`` and populates ``response.content``.

        Reading incrementally with a running total prevents a huge or
        chunked-infinite response from being buffered entirely into memory.
        Raises ``_ResponseTooLargeError`` (and closes the connection) once the
        cap is exceeded.

        Args:
            response (requests.Response): The streamed response to read and populate.
            max_bytes (int): The maximum number of bytes to buffer before failing.

        Raises:
            _ResponseTooLargeError: When the body exceeds ``max_bytes``.
        """
        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                response.close()
                raise _ResponseTooLargeError(
                    f"WebFetch response exceeded the {max_bytes}-byte cap (maxResponseBytes)."
                )
            chunks.append(chunk)
        # Populate the response so .text/.json() work normally downstream. This sets
        # `requests.Response` private internals (_content/_content_consumed) — the
        # standard idiom for a manually-streamed read, valid against the pinned
        # `requests` version; revisit here if that pin is ever bumped.
        response._content = b"".join(chunks)
        response._content_consumed = True

    @staticmethod
    def _load_capped_error_body(response: requests.Response, max_bytes: int) -> None:
        """Reads at most ``max_bytes`` of a failed streamed response, then closes it.

        Mirrors ``_load_capped_content`` but, because the request has already
        failed and the body is only needed for the error payload, it truncates at
        the cap instead of raising ``_ResponseTooLargeError``. This keeps the
        ``onError:"return"`` path bounded by ``maxResponseBytes`` so a hostile or
        oversized error body cannot be buffered in full via ``response.text``.

        Args:
            response (requests.Response): The failed streamed response to read and close.
            max_bytes (int): The maximum number of bytes to retain from the body.
        """
        chunks: List[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                remaining = max_bytes - total
                if remaining <= 0:
                    break
                piece = chunk[:remaining]
                chunks.append(piece)
                total += len(piece)
                if total >= max_bytes:
                    break
        except requests.exceptions.RequestException as exc:
            # Already on the error path; if the bounded re-read itself fails, keep
            # whatever was captured rather than masking the original failure.
            logger.debug("WebFetch bounded error-body read failed: %s", exc)
        finally:
            response.close()
        response._content = b"".join(chunks)
        response._content_consumed = True

    @staticmethod
    def _format_response(response: requests.Response, output_format: str) -> str:
        """Renders a successful response into the configured output format.

        Args:
            response (requests.Response): The successful response to render.
            output_format (str): One of "text", "json", "html-stripped", or "full".

        Returns:
            str: The rendered payload (raw text, JSON-serialized, stripped HTML, or a
                JSON-serialized status/headers/body object).
        """
        if output_format == "text":
            return response.text
        if output_format == "json":
            return json.dumps(response.json())
        if output_format == "html-stripped":
            return _strip_html(response.text)
        return json.dumps({
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text,
        })

    @staticmethod
    def _format_error(exc: Exception, output_format: str, response: Optional[requests.Response] = None) -> str:
        """Renders a failed request into the configured output format for the return path.

        Args:
            exc (Exception): The exception describing the failure.
            output_format (str): One of "text", "json", "html-stripped", or "full".
            response (Optional[requests.Response]): The response to render, if available;
                falls back to ``exc.response`` when None.

        Returns:
            str: The rendered error payload (a JSON object for "full", the response body
                or stripped HTML when a response exists, otherwise the exception string).
        """
        if response is None:
            response = getattr(exc, "response", None)
        if output_format == "full":
            payload = {
                "error": str(exc),
                "status_code": response.status_code if response is not None else None,
                "headers": dict(response.headers) if response is not None else None,
                "body": response.text if response is not None else None,
            }
            return json.dumps(payload)
        if response is not None:
            if output_format == "html-stripped":
                return _strip_html(response.text)
            return response.text
        return str(exc)

    @staticmethod
    def _maybe_stream(payload: str, context: ExecutionContext) -> Any:
        """Returns the payload as a streaming generator when streaming is enabled.

        Args:
            payload (str): The already-rendered string payload to return or stream.
            context (ExecutionContext): The runtime context whose ``stream`` flag is checked.

        Returns:
            Any: A streaming generator wrapping the payload when ``context.stream`` is True,
                otherwise the payload string unchanged.
        """
        if context.stream:
            return stream_static_content(payload)
        return payload
