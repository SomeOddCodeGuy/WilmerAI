# /Middleware/workflows/handlers/impl/web_fetch_handler.py

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from html.parser import HTMLParser
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from Middleware.utilities.network_security_utils import check_url_allowed
from Middleware.utilities.process_utils import run_process_readers
from Middleware.utilities.redirect_policy import (
    SENSITIVE_HEADERS, should_strip_credentials, request_without_redirects,
    redirect_method_and_body, resolve_redirect_url,
)
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.handlers.impl.extension_node_helpers import (
    maybe_stream, resolve_allowed_hosts, validate_bool, validate_max_bytes, validate_timeout,
)
from Middleware.workflows.models.execution_context import ExecutionContext

from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 10
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_VALID_OUTPUT_FORMATS = ("text", "json", "full", "html-stripped")
_VALID_ON_ERROR = ("raise", "return")
_VALID_TRANSPORTS = ("requests", "curl")
_CURL_RESPONSE_TOO_LARGE_EXIT_CODE = 63
_CURL_TIMEOUT_EXIT_CODE = 28
_CURL_READ_CHUNK_SIZE = 65536
_HTTP_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_CROSS_HOST_SENSITIVE_HEADERS = SENSITIVE_HEADERS


class _ResponseTooLargeError(Exception):
    """Raised when a fetched response body exceeds the configured byte cap."""


class _AddressNotAllowedError(requests.exceptions.RequestException):
    """Raised when a request target violates the configured SSRF address policy.

    Subclasses ``RequestException`` so it flows through the handler's existing
    request-failure path and is honored by ``onError`` like any other fetch failure.
    """


_HTML_STRIP_SKIP_TAGS = frozenset({"script", "style", "head", "noscript", "iframe"})


class _HtmlTextExtractor(HTMLParser):
    """A minimal stdlib-only HTML-to-text extractor.

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

    Issues an HTTP request to a user-configured URL using the selected transport
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
        transport_value = config.get("transport", "requests")
        if not isinstance(transport_value, str):
            raise ValueError(
                f"WebFetch 'transport' must be one of {_VALID_TRANSPORTS}; "
                f"got {transport_value!r}."
            )
        transport = transport_value.lower()
        timeout = validate_timeout(config.get("timeout", _DEFAULT_TIMEOUT_SECONDS), "WebFetch")
        output_format = config.get("outputFormat", "text")
        on_error = config.get("onError", "raise")
        proxy_template = config.get("proxy")
        allow_redirects = validate_bool(config.get("allowRedirects", True), "allowRedirects", "WebFetch")
        max_bytes = validate_max_bytes(config.get("maxResponseBytes", _DEFAULT_MAX_RESPONSE_BYTES), "WebFetch")
        block_private = validate_bool(config.get("blockPrivateAddresses", False), "blockPrivateAddresses", "WebFetch")
        allowed_hosts = resolve_allowed_hosts(
            config.get("allowedHosts"), context, self.workflow_variable_service, "WebFetch"
        )

        if output_format not in _VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"WebFetch 'outputFormat' must be one of {_VALID_OUTPUT_FORMATS}; got {output_format!r}."
            )
        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"WebFetch 'onError' must be one of {_VALID_ON_ERROR}; got {on_error!r}."
            )
        if transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"WebFetch 'transport' must be one of {_VALID_TRANSPORTS}; got {transport_value!r}."
            )

        url = self.workflow_variable_service.apply_variables(url_template, context)

        headers = self._resolve_headers(config.get("headers"), context)

        body_template = config.get("body")
        body: Optional[str] = None
        if body_template is not None:
            body = self.workflow_variable_service.apply_variables(str(body_template), context)

        proxies = self._resolve_proxies(proxy_template, context)
        verify = self._resolve_verify(config.get("verify", True), config.get("caBundle"), context)

        logger.debug(
            "WebFetch issuing %s %s (transport=%s, timeout=%s, outputFormat=%s, "
            "proxy=%s, verify=%s)",
            method,
            url,
            transport,
            timeout,
            output_format,
            bool(proxies),
            verify,
        )

        cap_enabled = max_bytes > 0
        response = None
        error_response = None
        try:
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
                    transport=transport,
                    max_bytes=max_bytes,
                )
                response.raise_for_status()
                if cap_enabled:
                    self._load_capped_content(response, max_bytes)
            except (requests.exceptions.RequestException, _ResponseTooLargeError) as exc:
                error_response = getattr(exc, "response", None)
                logger.warning("WebFetch request failed: %s", exc)
                if on_error == "raise":
                    raise
                if cap_enabled and error_response is not None:
                    self._load_capped_error_body(error_response, max_bytes)
                return maybe_stream(self._format_error(exc, output_format), context)

            try:
                result = self._format_response(response, output_format)
            except ValueError as exc:
                logger.warning("WebFetch could not format response as %s: %s", output_format, exc)
                if on_error == "raise":
                    raise
                result = self._format_error(exc, output_format, response=response)
            return maybe_stream(result, context)
        finally:
            try:
                if error_response is not None and error_response is not response:
                    error_response.close()
            finally:
                if response is not None:
                    response.close()

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
        transport: str,
        max_bytes: int,
    ):
        """Issues the request, enforcing the SSRF address policy on every hop.

        Redirects are followed explicitly so each hop can be validated without
        implicitly draining its body. Requests cookies belong to this operation
        and are cleared when a redirect crosses the credential boundary.

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
            transport (str): The selected HTTP transport ("requests" or "curl").
            max_bytes (int): Maximum response body size, or a non-positive value for no cap.

        Returns:
            requests.Response: The response from the final (non-redirect) hop.

        Raises:
            _AddressNotAllowedError: When a hop's target violates the SSRF address policy.
            requests.exceptions.TooManyRedirects: When the redirect chain exceeds the limit.
        """
        guard_active = block_private or bool(allowed_hosts)
        cookie_jar = requests.cookies.RequestsCookieJar() if transport == "requests" else None
        current_url, current_method, current_data, current_headers = url, method, data, headers
        for _ in range(_MAX_REDIRECTS + 1):
            if guard_active:
                reason = check_url_allowed(current_url, block_private, allowed_hosts)
                if reason:
                    raise _AddressNotAllowedError(
                        f"WebFetch blocked a request to a disallowed address: {reason}."
                    )
            response = self._request_once(
                transport=transport,
                method=current_method,
                url=current_url,
                headers=current_headers,
                data=current_data,
                timeout=timeout,
                proxies=proxies,
                verify=verify,
                stream=stream,
                max_bytes=max_bytes,
                cookie_jar=cookie_jar,
            )
            if not allow_redirects or response.status_code not in _REDIRECT_STATUS:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            try:
                try:
                    prepared_request = getattr(response, 'request', None)
                    source_url = (prepared_request.url
                                  if cookie_jar is not None and prepared_request is not None
                                  else current_url)
                    next_url = resolve_redirect_url(source_url, location)
                    comparison_url = next_url
                    if cookie_jar is not None:
                        # Compare transport hostnames, including equivalent IDNA spellings.
                        destination = requests.PreparedRequest()
                        destination.prepare_url(next_url, None)
                        comparison_url = destination.url
                    strip_credentials = should_strip_credentials(source_url, comparison_url)
                except (ValueError, UnicodeError) as exc:
                    raise requests.exceptions.InvalidURL("Redirect URL could not be parsed") from exc
                current_method, current_data, current_headers = redirect_method_and_body(
                    current_method, current_data, current_headers, response.status_code)
                if cookie_jar is not None:
                    # Rebuild from response cookies, including renewal, expiry and path scope.
                    current_headers = {k: v for k, v in current_headers.items() if k.lower() != 'cookie'}
                    if not strip_credentials and prepared_request is not None:
                        # URL-derived authentication exists only on the prepared request.
                        authorization = prepared_request.headers.get('Authorization')
                        if authorization is not None:
                            current_headers = {k: v for k, v in current_headers.items()
                                               if k.lower() != 'authorization'}
                            current_headers['Authorization'] = authorization
                if strip_credentials:
                    if cookie_jar is not None:
                        cookie_jar.clear()
                    current_headers = {
                        k: v for k, v in current_headers.items()
                        if k.lower() not in _CROSS_HOST_SENSITIVE_HEADERS
                    }
            finally:
                response.close()
            current_url = next_url
        raise requests.exceptions.TooManyRedirects(
            f"WebFetch exceeded the maximum of {_MAX_REDIRECTS} redirects."
        )

    def _request_once(
        self,
        *,
        transport: str,
        method: str,
        url: str,
        headers: Dict[str, str],
        data: Optional[str],
        timeout: float,
        proxies: Optional[Dict[str, str]],
        verify: Any,
        stream: bool,
        max_bytes: int,
        cookie_jar=None,
    ) -> requests.Response:
        """Issues one non-redirecting request through the selected transport.

        Args:
            transport (str): Validated transport name, requests or curl.
            method (str): HTTP method for this hop.
            url (str): Resolved and validated destination URL.
            headers (Dict[str, str]): Request headers; empty uses client defaults.
            data (Optional[str]): Request body, or None for no body.
            timeout (float): Request timeout in seconds.
            proxies (Optional[Dict[str, str]]): Scheme-to-proxy mapping, or None.
            verify (Any): True, False, or a CA bundle path for TLS verification.
            stream (bool): Whether Requests defers reading the response body.
            max_bytes (int): Curl response cap; non-positive disables the cap.
                Requests body limits are enforced by the caller.
            cookie_jar (Optional[requests.cookies.RequestsCookieJar]): Cookies shared
                between Requests hops of this operation; unused by curl.

        Returns:
            requests.Response: Caller-owned response. Closing a Requests response
                also closes its private session; curl returns an already buffered body.
        """
        if transport == "requests":
            return request_without_redirects(
                cookie_jar=cookie_jar,
                method=method,
                url=url,
                headers=headers if headers else None,
                data=data,
                timeout=timeout,
                proxies=proxies,
                verify=verify,
                allow_redirects=False,
                stream=stream,
            )
        return self._request_with_curl(
            method=method,
            url=url,
            headers=headers,
            data=data,
            timeout=timeout,
            proxies=proxies,
            verify=verify,
            max_bytes=max_bytes,
        )

    def _request_with_curl(
        self,
        *,
        method: str,
        url: str,
        headers: Dict[str, str],
        data: Optional[str],
        timeout: float,
        proxies: Optional[Dict[str, str]],
        verify: Any,
        max_bytes: int,
    ) -> requests.Response:
        """Issues one request with curl and adapts the result to ``requests.Response``.

        Curl is passed an argument list with ``shell=False``. ``--disable`` prevents
        local curl configuration files from silently adding headers or credentials.
        No User-Agent option or header is added here; curl uses its generic default
        unless the workflow author explicitly supplies a ``User-Agent`` header.

        Args:
            method (str): HTTP method for this hop.
            url (str): Resolved and validated destination URL.
            headers (Dict[str, str]): Request headers written to a temporary input file.
            data (Optional[str]): Body encoded as UTF-8, or None for no body.
            timeout (float): Curl connection and total-operation timeout in seconds,
                also bounding the process wait.
            proxies (Optional[Dict[str, str]]): Scheme-to-proxy mapping, or None.
            verify (Any): True, False, or a CA bundle path for TLS verification.
            max_bytes (int): Response body and retained diagnostic byte cap;
                non-positive disables the cap.

        Returns:
            requests.Response: Caller-owned response with a buffered body after the
                subprocess and temporary files have been cleaned up.
        """
        curl_executable = shutil.which("curl")
        if curl_executable is None:
            raise requests.exceptions.RequestException(
                "WebFetch transport 'curl' requires a curl executable on PATH."
            )

        timeout_text = str(timeout)
        with tempfile.TemporaryDirectory(prefix="web-fetch-") as temp_directory:
            response_headers_path = os.path.join(temp_directory, "response-headers")
            command = [
                curl_executable,
                "--disable",
                "--globoff",
                "--silent",
                "--show-error",
                "--proto",
                "=http,https",
                "--request",
                method,
                "--connect-timeout",
                timeout_text,
                "--max-time",
                timeout_text,
                "--dump-header",
                response_headers_path,
            ]

            if headers:
                request_headers_path = os.path.join(temp_directory, "request-headers")
                self._write_curl_headers(request_headers_path, headers)
                command.extend(("--header", f"@{request_headers_path}"))
            if data is not None:
                request_body_path = os.path.join(temp_directory, "request-body")
                with open(request_body_path, "wb") as request_body_file:
                    request_body_file.write(data.encode("utf-8"))
                command.extend(("--data-binary", f"@{request_body_path}"))
            if proxies:
                scheme = (urlsplit(url).scheme or "http").lower()
                proxy = proxies.get(scheme) or proxies.get("http") or proxies.get("https")
                if proxy:
                    command.extend(("--proxy", proxy))
            if verify is False:
                command.append("--insecure")
            elif isinstance(verify, str):
                command.extend(("--cacert", verify))
            if max_bytes > 0:
                command.extend(("--max-filesize", str(max_bytes)))
            command.extend(("--url", url))

            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                )
            except OSError as exc:
                raise requests.exceptions.RequestException(
                    f"WebFetch could not start curl: {exc}."
                ) from exc

            cap = max_bytes if max_bytes > 0 else 0
            body_box: Dict[str, Any] = {}
            error_box: Dict[str, Any] = {}
            timed_out = run_process_readers(process, timeout, (
                (self._read_curl_body, (process, cap, body_box)),
                (self._read_curl_diagnostic, (process.stderr, cap, error_box)),
            ))

            if timed_out:
                raise requests.exceptions.Timeout(
                    f"WebFetch curl request exceeded the {timeout}-second timeout."
                )
            if body_box.get("truncated"):
                raise _ResponseTooLargeError(
                    f"WebFetch response exceeded the {max_bytes}-byte cap (maxResponseBytes)."
                )

            response = self._build_curl_response(
                url=url,
                method=method,
                response_headers_path=response_headers_path,
                body=body_box.get("data", b""),
            )
            if process.returncode == _CURL_RESPONSE_TOO_LARGE_EXIT_CODE:
                raise _ResponseTooLargeError(
                    f"WebFetch response exceeded the {max_bytes}-byte cap (maxResponseBytes)."
                )
            if process.returncode != 0:
                error_text = error_box.get("data", b"").decode(
                    "utf-8", errors="replace"
                ).strip()
                message = error_text or f"curl exited with status {process.returncode}"
                error_type = (
                    requests.exceptions.Timeout
                    if process.returncode == _CURL_TIMEOUT_EXIT_CODE
                    else requests.exceptions.RequestException
                )
                error_response = response if response.status_code > 0 else None
                raise error_type(
                    f"WebFetch curl request failed: {message}", response=error_response
                )
            if response.status_code == 0:
                raise requests.exceptions.RequestException(
                    "WebFetch curl request did not return a valid HTTP status."
                )
            return response

    @staticmethod
    def _read_curl_body(process: Any, cap: int, box: Dict[str, Any]) -> None:
        """Reads curl stdout incrementally and kills the process if it exceeds the cap.

        Args:
            process (Any): Curl subprocess with a readable stdout pipe.
            cap (int): Maximum retained bytes; non-positive disables the cap.
            box (Dict[str, Any]): Output mapping populated with data bytes and a
                truncated flag indicating whether the cap stopped the process.
        """
        chunks: List[bytes] = []
        total = 0
        truncated = False
        try:
            while True:
                chunk = process.stdout.read(_CURL_READ_CHUNK_SIZE)
                if not chunk:
                    break
                if cap > 0 and total + len(chunk) > cap:
                    chunks.append(chunk[:cap - total])
                    truncated = True
                    process.kill()
                    break
                chunks.append(chunk)
                total += len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            box["data"] = b"".join(chunks)
            box["truncated"] = truncated

    @staticmethod
    def _read_curl_diagnostic(stream: Any, cap: int, box: Dict[str, Any]) -> None:
        """Drains curl stderr while retaining at most the configured byte cap.

        Args:
            stream (Any): Readable stderr pipe to drain through EOF.
            cap (int): Maximum retained bytes; non-positive disables the cap.
            box (Dict[str, Any]): Output mapping populated with retained data bytes.
        """
        chunks: List[bytes] = []
        total = 0
        try:
            while True:
                chunk = stream.read(_CURL_READ_CHUNK_SIZE)
                if not chunk:
                    break
                if cap <= 0:
                    chunks.append(chunk)
                    continue
                remaining = cap - total
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                    total += min(len(chunk), remaining)
        except (OSError, ValueError):
            pass
        finally:
            box["data"] = b"".join(chunks)

    @staticmethod
    def _close_curl_stream(stream: Any) -> None:
        """Closes a curl pipe without masking the request result.

        Args:
            stream (Any): Pipe to close, or None when no pipe was opened.
        """
        try:
            if stream is not None:
                stream.close()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _write_curl_headers(path: str, headers: Dict[str, str]) -> None:
        """Writes validated request headers to a private temporary curl input file.

        Args:
            path (str): Destination file in the operation's private temporary directory.
            headers (Dict[str, str]): Header names and values to validate and serialize.

        Raises:
            ValueError: If a name is invalid or a value contains a forbidden delimiter.
            OSError: If the header file cannot be written.
        """
        lines = []
        for name, value in headers.items():
            if not _HTTP_HEADER_NAME_PATTERN.fullmatch(name):
                raise ValueError(f"WebFetch header name is invalid: {name!r}.")
            if any(character in value for character in ("\r", "\n", "\x00")):
                raise ValueError(f"WebFetch header {name!r} contains an invalid line break.")
            lines.append(f"{name}: {value}\n")
        with open(path, "w", encoding="utf-8", newline="") as header_file:
            header_file.writelines(lines)

    @classmethod
    def _build_curl_response(
        cls,
        *,
        url: str,
        method: str,
        response_headers_path: str,
        body: bytes,
    ) -> requests.Response:
        """Builds a Requests-compatible response from curl's output files.

        Args:
            url (str): URL of the completed request hop.
            method (str): HTTP method recorded on the prepared request.
            response_headers_path (str): Curl header-output file; missing means no headers.
            body (bytes): Already buffered response body.

        Returns:
            requests.Response: Buffered response with parsed metadata and text encoding.
                A zero status indicates that no valid HTTP status was parsed.
        """
        try:
            with open(response_headers_path, "rb") as header_file:
                raw_headers = header_file.read()
        except FileNotFoundError:
            raw_headers = b""

        status_code, reason, headers = cls._parse_curl_headers(raw_headers)

        response = requests.Response()
        response.status_code = status_code
        response.reason = reason
        response.headers = requests.structures.CaseInsensitiveDict(headers)
        response.url = url
        response.request = requests.Request(method=method, url=url).prepare()
        response._content = body
        response._content_consumed = True
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        return response

    @staticmethod
    def _parse_curl_headers(raw_headers: bytes) -> Tuple[int, Optional[str], Dict[str, str]]:
        """Parses the final HTTP header block emitted by curl.

        Args:
            raw_headers (bytes): Curl header output, possibly containing multiple blocks.

        Returns:
            Tuple[int, Optional[str], Dict[str, str]]: Status code, reason phrase, and
                headers from the final HTTP block. No block yields (0, None, {});
                an invalid status code yields zero.
        """
        text = raw_headers.decode("iso-8859-1", errors="replace")
        final_lines: List[str] = []
        # Unicode whitespace operations can discard UTF-8 continuation bytes decoded as Latin-1.
        for block in re.split(r"\r?\n\r?\n", text):
            lines = re.split(r"\r?\n", block)
            if lines and lines[0].startswith("HTTP/"):
                final_lines = lines
        if not final_lines:
            return 0, None, {}

        status_parts = final_lines[0].split(None, 2)
        try:
            status_code = int(status_parts[1])
        except (IndexError, ValueError):
            status_code = 0
        reason = status_parts[2] if len(status_parts) > 2 else None
        headers: Dict[str, str] = {}
        last_name: Optional[str] = None
        for line in final_lines[1:]:
            if line[:1] in (" ", "\t") and last_name is not None:
                value = line.strip(" \t")
                headers[last_name] = f"{headers[last_name]} {value}"
                continue
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            name = name.strip(" \t")
            value = value.strip(" \t")
            if name in headers:
                headers[name] = f"{headers[name]}, {value}"
            else:
                headers[name] = value
            last_name = name
        return status_code, reason, headers

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
        """Resolve TLS verification and the optional CA bundle.

        Args:
            verify_value (Any): Boolean verification flag; False takes precedence over caBundle.
            ca_bundle_template (Any): Optional CA bundle path template used when verification is
                enabled.
            context (ExecutionContext): Workflow values used to resolve the path.

        Returns:
            Union[bool, str]: True for transport-default verification, False to disable it, or
                the resolved CA bundle path.

        Raises:
            ValueError: If the flag is not boolean or an enabled CA bundle setting is invalid.
        """
        verify = validate_bool(verify_value, "verify", "WebFetch")
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
    def _load_capped_content(response: requests.Response, max_bytes: int) -> None:
        """Reads a streamed response body up to ``max_bytes`` and populates ``response.content``.

        Reading incrementally with a running total prevents a huge or
        chunked-infinite response from being buffered entirely into memory.
        Raises ``_ResponseTooLargeError`` once the cap is exceeded. The caller
        owns response cleanup across reading and formatting.

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
                raise _ResponseTooLargeError(
                    f"WebFetch response exceeded the {max_bytes}-byte cap (maxResponseBytes)."
                )
            chunks.append(chunk)
        # Requests text/JSON access must use the bounded body without reading again.
        response._content = b"".join(chunks)
        response._content_consumed = True

    @staticmethod
    def _load_capped_error_body(response: requests.Response, max_bytes: int) -> None:
        """Reads at most ``max_bytes`` of a failed response owned by the caller.

        Mirrors ``_load_capped_content`` but, because the request has already
        failed and the body is only needed for the error payload, it truncates at
        the cap instead of raising ``_ResponseTooLargeError``. This keeps the
        ``onError:"return"`` path bounded by ``maxResponseBytes`` so a hostile or
        oversized error body cannot be buffered in full via ``response.text``.

        Args:
            response (requests.Response): The caller-owned failed response to read.
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
