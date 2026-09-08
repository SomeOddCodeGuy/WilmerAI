"""Workflow handler for publisher-cautious public webpage retrieval."""

import json
import math
import os
import re
from typing import Any, Dict, FrozenSet, Optional

from Middleware.services.web_page_fetch_service import (
    WebPageFetchError,
    WebPageFetchPolicy,
    WebPageFetchResult,
    WebPageFetchService,
    get_default_web_page_fetch_service,
)
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.handlers.impl.extension_node_helpers import (
    maybe_stream,
    resolve_allowed_hosts,
    validate_bool,
    validate_timeout,
)
from Middleware.workflows.handlers.impl.web_fetch_handler import _strip_html
from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)

_VALID_OUTPUT_FORMATS = ("text", "html-stripped", "full")
_VALID_ON_ERROR = ("raise", "return")
_DEFAULT_CONTENT_TYPES = frozenset({
    "text/html",
    "application/xhtml+xml",
    "text/plain",
})
_MEDIA_TYPE_PATTERN = re.compile(
    r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$"
)


class WebPageFetchHandler(BaseHandler):
    """Handles the `WebPageFetch` node through a shared policy service."""

    def __init__(
        self,
        workflow_manager: Any,
        workflow_variable_service: Any,
        *,
        web_page_fetch_service: Optional[WebPageFetchService] = None,
        **kwargs: Any,
    ) -> None:
        """Connect workflow execution to the shared page-fetch service.

        Args:
            workflow_manager (Any): Manager coordinating node execution.
            workflow_variable_service (Any): Service resolving node templates.
            web_page_fetch_service (Optional[WebPageFetchService]): Fetch service override;
                defaults to the process-wide instance.
            **kwargs (Any): Additional dependencies accepted by BaseHandler.
        """
        super().__init__(workflow_manager, workflow_variable_service, **kwargs)
        self.web_page_fetch_service = (
            web_page_fetch_service or get_default_web_page_fetch_service()
        )

    def handle(self, context: ExecutionContext) -> Any:
        """Fetches and formats a public page according to default-on policy controls.

        Args:
            context (ExecutionContext): Node configuration, workflow variables,
                request identifier, and streaming state for this execution.

        Returns:
            Any: Formatted page or error text, including a JSON string for full
                output, optionally wrapped as a generator for streaming execution.

        Raises:
            ValueError: If the node configuration is invalid.
            WebPageFetchError: If retrieval fails and onError is set to raise.
        """
        config = context.config
        url_template = config.get("url")
        if not isinstance(url_template, str) or not url_template:
            raise ValueError("WebPageFetch node requires a non-empty 'url' string.")

        method = config.get("method", "GET")
        if not isinstance(method, str) or method.upper() != "GET":
            raise ValueError("WebPageFetch supports only the GET method.")
        if config.get("body") is not None:
            raise ValueError("WebPageFetch does not accept a request body.")
        if config.get("headers"):
            raise ValueError(
                "WebPageFetch does not accept caller-defined headers, authentication, "
                "cookies, Referer, or User-Agent values."
            )
        transport = config.get("transport", "requests")
        if not isinstance(transport, str) or transport.lower() != "requests":
            raise ValueError(
                "WebPageFetch currently uses the Requests transport so it can inspect "
                "headers before reading the body."
            )

        output_format = config.get("outputFormat", "html-stripped")
        on_error = config.get("onError", "raise")
        if output_format not in _VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"WebPageFetch 'outputFormat' must be one of {_VALID_OUTPUT_FORMATS}; "
                f"got {output_format!r}."
            )
        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"WebPageFetch 'onError' must be one of {_VALID_ON_ERROR}; got {on_error!r}."
            )

        url = self.workflow_variable_service.apply_variables(url_template, context)
        policy = self._build_policy(config, context)
        try:
            result = self.web_page_fetch_service.fetch(url, policy, request_id=context.request_id)
            payload = self._format_success(result, output_format)
        except WebPageFetchError as exc:
            logger.warning("WebPageFetch failed: %s", exc)
            if on_error == "raise":
                raise
            payload = self._format_error(exc, output_format)
        return maybe_stream(payload, context)

    def _build_policy(
        self,
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> WebPageFetchPolicy:
        """Validate node settings and resolve templates into a fetch policy.

        Args:
            config (Dict[str, Any]): WebPageFetch node configuration.
            context (ExecutionContext): Workflow values used to resolve templates.

        Returns:
            WebPageFetchPolicy: Validated publisher, destination, and transport controls.

        Raises:
            ValueError: If a setting or resolved CA bundle is invalid.
        """
        timeout = validate_timeout(config.get("timeout", 30), "WebPageFetch")
        if not math.isfinite(float(timeout)):
            raise ValueError("WebPageFetch 'timeout' must be a finite positive number.")
        proxies = self._resolve_proxies(config.get("proxy"), context)
        verify = self._resolve_verify(config.get("verify", True), config.get("caBundle"), context)
        allowed_hosts = resolve_allowed_hosts(
            config.get("allowedHosts"),
            context,
            self.workflow_variable_service,
            "WebPageFetch",
        )
        return WebPageFetchPolicy(
            timeout=timeout,
            proxies=proxies,
            verify=verify,
            respect_robots=self._bool(config, "respectRobots", True),
            fail_closed_on_robots_error=self._bool(
                config, "failClosedOnRobotsError", True
            ),
            block_private_addresses=self._bool(
                config, "blockPrivateAddresses", True
            ),
            allowed_hosts=allowed_hosts,
            restrict_ports=self._bool(config, "restrictPorts", True),
            allowed_ports=self._allowed_ports(config.get("allowedPorts")),
            enable_domain_pacing=self._bool(config, "enableDomainPacing", True),
            minimum_delay_seconds=self._nonnegative_number(
                config, "minimumDelaySeconds", 5
            ),
            max_pacing_wait_seconds=self._nonnegative_number(
                config, "maxPacingWaitSeconds", 300
            ),
            honor_crawl_delay=self._bool(config, "honorCrawlDelay", True),
            honor_request_rate=self._bool(config, "honorRequestRate", True),
            honor_retry_after=self._bool(config, "honorRetryAfter", True),
            honor_forbidden_cooldown=self._bool(
                config, "honorForbiddenCooldown", True
            ),
            robots_cache_seconds=self._nonnegative_number(
                config, "robotsCacheSeconds", 86400
            ),
            robots_failure_cache_seconds=self._nonnegative_number(
                config, "robotsFailureCacheSeconds", 300
            ),
            forbidden_cooldown_seconds=self._nonnegative_number(
                config, "forbiddenCooldownSeconds", 604800
            ),
            retry_after_fallback_seconds=self._nonnegative_number(
                config, "retryAfterFallbackSeconds", 60
            ),
            allow_redirects=self._bool(config, "allowRedirects", True),
            max_redirects=self._max_redirects(config.get("maxRedirects", 5)),
            enforce_content_type=self._bool(config, "enforceContentType", True),
            allowed_content_types=self._allowed_content_types(
                config.get("allowedContentTypes")
            ),
            max_header_bytes=self._positive_integer(
                config, "maxHeaderBytes", 128 * 1024
            ),
            max_transfer_bytes=self._positive_integer(
                config, "maxTransferBytes", 5 * 1024 * 1024
            ),
            max_decoded_bytes=self._positive_integer(
                config, "maxDecodedBytes", 25 * 1024 * 1024
            ),
        )

    @staticmethod
    def _bool(config: Dict[str, Any], field: str, default: bool) -> bool:
        """Read a strictly boolean node setting.

        Args:
            config (Dict[str, Any]): Node configuration.
            field (str): Setting name.
            default (bool): Value used when the setting is absent.

        Returns:
            bool: Validated setting.

        Raises:
            ValueError: If the value is not a boolean.
        """
        return validate_bool(config.get(field, default), field, "WebPageFetch")

    @staticmethod
    def _nonnegative_number(
        config: Dict[str, Any],
        field: str,
        default: float,
    ) -> float:
        """Read a finite, nonnegative numeric node setting.

        Args:
            config (Dict[str, Any]): Node configuration.
            field (str): Setting name.
            default (float): Value used when the setting is absent.

        Returns:
            float: Parsed numeric value.

        Raises:
            ValueError: If the value is boolean, nonnumeric, non-finite, or negative.
        """
        value = config.get(field, default)
        if isinstance(value, bool):
            raise ValueError(f"WebPageFetch '{field}' must be a non-negative number.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"WebPageFetch '{field}' must be a non-negative number."
            ) from exc
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"WebPageFetch '{field}' must be a non-negative number.")
        return number

    @staticmethod
    def _positive_integer(
        config: Dict[str, Any],
        field: str,
        default: int,
    ) -> int:
        """Read a positive integer node setting without fractional coercion.

        Args:
            config (Dict[str, Any]): Node configuration.
            field (str): Setting name.
            default (int): Value used when the setting is absent.

        Returns:
            int: Parsed positive integer.

        Raises:
            ValueError: If the value is not a positive integer or its decimal string.
        """
        value = config.get(field, default)
        if isinstance(value, bool):
            raise ValueError(f"WebPageFetch '{field}' must be a positive integer.")
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"WebPageFetch '{field}' must be a positive integer."
            ) from exc
        if number <= 0 or str(number) != str(value).strip():
            raise ValueError(f"WebPageFetch '{field}' must be a positive integer.")
        return number

    @staticmethod
    def _max_redirects(value: Any) -> int:
        """Validate the bounded redirect count.

        Args:
            value (Any): Configured redirect count or decimal string.

        Returns:
            int: Redirect limit from zero through five.

        Raises:
            ValueError: If the value is not an integer in the permitted range.
        """
        if isinstance(value, bool):
            raise ValueError("WebPageFetch 'maxRedirects' must be an integer from 0 to 5.")
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "WebPageFetch 'maxRedirects' must be an integer from 0 to 5."
            ) from exc
        if number < 0 or number > 5 or str(number) != str(value).strip():
            raise ValueError("WebPageFetch 'maxRedirects' must be an integer from 0 to 5.")
        return number

    @staticmethod
    def _allowed_ports(value: Any) -> FrozenSet[int]:
        """Validate explicitly permitted non-default destination ports.

        Args:
            value (Any): Port list, or None for no extra ports.

        Returns:
            FrozenSet[int]: Validated, deduplicated ports.

        Raises:
            ValueError: If the value is not a list of ports from 1 through 65535.
        """
        if value is None:
            return frozenset()
        if not isinstance(value, list):
            raise ValueError("WebPageFetch 'allowedPorts' must be a JSON list of ports.")
        ports = set()
        for entry in value:
            if isinstance(entry, bool):
                raise ValueError("WebPageFetch 'allowedPorts' entries must be integers.")
            try:
                port = int(entry)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "WebPageFetch 'allowedPorts' entries must be integers."
                ) from exc
            if port < 1 or port > 65535 or str(port) != str(entry).strip():
                raise ValueError(
                    "WebPageFetch 'allowedPorts' entries must be between 1 and 65535."
                )
            ports.add(port)
        return frozenset(ports)

    @staticmethod
    def _allowed_content_types(value: Any) -> FrozenSet[str]:
        """Validate response media types without parameters.

        Args:
            value (Any): Media-type list, or None for the default text types.

        Returns:
            FrozenSet[str]: Lowercase, deduplicated media types.

        Raises:
            ValueError: If the list is empty or contains invalid media types.
        """
        if value is None:
            return _DEFAULT_CONTENT_TYPES
        if not isinstance(value, list) or not value:
            raise ValueError(
                "WebPageFetch 'allowedContentTypes' must be a non-empty JSON list."
            )
        content_types = set()
        for entry in value:
            if (
                not isinstance(entry, str)
                or not _MEDIA_TYPE_PATTERN.fullmatch(entry.strip())
            ):
                raise ValueError(
                    "WebPageFetch 'allowedContentTypes' entries must be media types "
                    "without parameters."
                )
            content_types.add(entry.strip().lower())
        return frozenset(content_types)

    def _resolve_proxies(
        self,
        proxy_template: Any,
        context: ExecutionContext,
    ) -> Optional[Dict[str, str]]:
        """Resolve a proxy template for HTTP and HTTPS requests.

        Args:
            proxy_template (Any): Optional configured proxy URL template.
            context (ExecutionContext): Workflow values used to resolve the template.

        Returns:
            Optional[Dict[str, str]]: Requests proxy mapping, or None for no proxy.

        Raises:
            ValueError: If an explicit proxy template is not a string.
        """
        if proxy_template is None:
            return None
        if not isinstance(proxy_template, str):
            raise ValueError("WebPageFetch 'proxy' must be a string URL.")
        proxy = self.workflow_variable_service.apply_variables(proxy_template, context)
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def _resolve_verify(
        self,
        verify_value: Any,
        ca_bundle_template: Any,
        context: ExecutionContext,
    ) -> Any:
        """Resolve TLS verification and an optional CA bundle template.

        Args:
            verify_value (Any): Boolean verification setting.
            ca_bundle_template (Any): Optional path template used when verification is enabled.
            context (ExecutionContext): Workflow values used to resolve the path.

        Returns:
            Union[bool, str]: Verification flag or path to an existing CA bundle.

        Raises:
            ValueError: If verification is not boolean or an enabled CA bundle is invalid.
        """
        verify = validate_bool(verify_value, "verify", "WebPageFetch")
        if not verify:
            logger.warning("WebPageFetch TLS certificate verification is disabled.")
            return False
        if ca_bundle_template is None:
            return True
        if not isinstance(ca_bundle_template, str):
            raise ValueError("WebPageFetch 'caBundle' must be a string path.")
        path = self.workflow_variable_service.apply_variables(ca_bundle_template, context)
        if not path:
            return True
        if not os.path.isfile(path):
            raise ValueError(f"WebPageFetch 'caBundle' file not found: {path!r}.")
        return path

    @staticmethod
    def _format_success(result: WebPageFetchResult, output_format: str) -> str:
        """Format a successful page result for node output.

        Args:
            result (WebPageFetchResult): Complete page response.
            output_format (str): Validated text, html-stripped, or full output mode.

        Returns:
            str: Body text, extracted HTML text, or JSON response metadata and body.
        """
        body = result.text
        if output_format == "html-stripped":
            return _strip_html(body)
        if output_format == "text":
            return body
        return json.dumps({
            "status_code": result.status_code,
            "headers": result.headers,
            "body": body,
            "url": result.url,
        })

    @staticmethod
    def _format_error(exc: WebPageFetchError, output_format: str) -> str:
        """Format a retrieval error for onError=return.

        Args:
            exc (WebPageFetchError): Failure and available response metadata.
            output_format (str): Validated node output mode.

        Returns:
            str: JSON error metadata for full mode, otherwise the failure message.
        """
        if output_format == "full":
            return json.dumps({
                "error": str(exc),
                "status_code": exc.status_code,
                "headers": exc.headers,
                "body": None,
                "url": exc.url,
            })
        return str(exc)
