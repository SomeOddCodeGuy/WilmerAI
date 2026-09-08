import math
import re
from dataclasses import dataclass, field
from typing import Dict, Tuple
from urllib.parse import urlsplit

from Middleware.common import instance_global_variables
from Middleware.utilities import config_utils


_AUTHORIZATION_MODES = frozenset({"passthrough", "configured", "omit"})
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_FORBIDDEN_FORWARD_HEADERS = frozenset({
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})


@dataclass(frozen=True)
class WilmerProxyUpstreamConfig:
    """Validated connection and header policy for one upstream Wilmer instance."""

    name: str
    base_url: str
    authorization_mode: str
    api_key: str = field(default="", repr=False)
    forward_headers: Tuple[str, ...] = ("X-Idempotency-Key",)
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 14400.0
    verify_tls: bool = True


@dataclass(frozen=True)
class WilmerProxyModelConfig:
    """Maps one public model alias to an upstream and its exact target model."""

    public_name: str
    upstream: str
    target_model: str


@dataclass(frozen=True)
class WilmerProxyConfig:
    """Validated configuration for one WilmerProxy-mode Wilmer process."""

    name: str
    upstreams: Dict[str, WilmerProxyUpstreamConfig]
    models: Dict[str, WilmerProxyModelConfig]
    port: int = 5050
    use_file_logging: bool = False


def _require_object(value, label: str) -> dict:
    """Require a JSON object for a configuration section.

    Args:
        value (Any): Parsed configuration value.
        label (str): Field path used in validation errors.

    Returns:
        dict: The input object.

    Raises:
        ValueError: If the value is not a dictionary.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _reject_unknown_keys(value: dict, allowed: set, label: str) -> None:
    """Reject configuration fields outside a section schema.

    Args:
        value (dict): Configuration section to validate.
        allowed (set): Permitted field names.
        label (str): Section path used in validation errors.

    Raises:
        ValueError: If the section contains unknown fields.
    """
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unknown field(s): {', '.join(unknown)}.")


def _require_non_empty_string(value, label: str) -> str:
    """Require a non-blank configuration string.

    Args:
        value (Any): Parsed configuration value.
        label (str): Field path used in validation errors.

    Returns:
        str: Value with surrounding whitespace removed.

    Raises:
        ValueError: If the value is not a non-blank string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _positive_number(value, label: str, default: float) -> float:
    """Resolve an optional positive, finite numeric setting.

    Args:
        value (Any): Numeric value, or None to use the default.
        label (str): Field path used in validation errors.
        default (float): Value used when the setting is absent.

    Returns:
        float: Validated number or the supplied default.

    Raises:
        ValueError: If an explicit value is boolean, nonnumeric, non-finite, or nonpositive.
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be a number greater than zero.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number greater than zero.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number greater than zero.")
    return number


def _validate_base_url(value, label: str) -> str:
    """Validate an upstream HTTP base URL without credentials or query data.

    Args:
        value (Any): Configured base URL.
        label (str): Field path used in validation errors.

    Returns:
        str: Validated URL without surrounding whitespace or trailing slashes.

    Raises:
        ValueError: If the value is not a supported absolute URL.
    """
    base_url = _require_non_empty_string(value, label).rstrip("/")
    if any(character.isspace() or ord(character) < 32 for character in base_url):
        raise ValueError(f"{label} must not contain whitespace or control characters.")
    try:
        parsed = urlsplit(base_url)
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid URL: {exc}") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain embedded credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{label} must not contain a query string or fragment.")
    return base_url


def _validate_forward_headers(value, label: str) -> Tuple[str, ...]:
    """Validate optional headers that the proxy may forward from a client.

    Args:
        value (Any): List of header names, or None for X-Idempotency-Key.
        label (str): Field path used in validation errors.

    Returns:
        Tuple[str, ...]: Header names deduplicated without regard to case.

    Raises:
        ValueError: If a header is invalid or managed directly by the proxy.
    """
    if value is None:
        return ("X-Idempotency-Key",)
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array of header names.")

    result = []
    seen = set()
    for index, item in enumerate(value):
        header = _require_non_empty_string(item, f"{label}[{index}]")
        lowered = header.lower()
        if not _HEADER_NAME_RE.fullmatch(header):
            raise ValueError(f"{label}[{index}] is not a valid HTTP header name.")
        if lowered in _FORBIDDEN_FORWARD_HEADERS:
            raise ValueError(
                f"{label}[{index}] names '{header}', which is managed by WilmerProxy and cannot be forwarded here.")
        if lowered not in seen:
            seen.add(lowered)
            result.append(header)
    return tuple(result)


def _parse_upstream(name: str, raw_value) -> WilmerProxyUpstreamConfig:
    """Validate one upstream connection and authentication policy.

    Args:
        name (str): Upstream identifier used by model mappings.
        raw_value (Any): Parsed upstream configuration.

    Returns:
        WilmerProxyUpstreamConfig: Validated connection settings.

    Raises:
        ValueError: If the name or upstream settings are invalid.
    """
    if not config_utils._is_safe_flat_config_name(name):
        raise ValueError(f"WilmerProxy upstream name '{name}' is not a safe flat name.")
    value = _require_object(raw_value, f"upstreams.{name}")
    _reject_unknown_keys(
        value,
        {
            "baseUrl", "authorizationMode", "apiKey", "forwardHeaders",
            "connectTimeoutSeconds", "readTimeoutSeconds", "verifyTls",
        },
        f"upstreams.{name}",
    )

    authorization_mode = value.get("authorizationMode", "passthrough")
    if authorization_mode not in _AUTHORIZATION_MODES:
        choices = ", ".join(sorted(_AUTHORIZATION_MODES))
        raise ValueError(
            f"upstreams.{name}.authorizationMode must be one of: {choices}.")

    api_key = value.get("apiKey", "")
    if not isinstance(api_key, str):
        raise ValueError(f"upstreams.{name}.apiKey must be a string.")
    if authorization_mode == "configured" and not api_key:
        raise ValueError(
            f"upstreams.{name}.apiKey is required when authorizationMode is 'configured'.")
    if authorization_mode != "configured" and api_key:
        raise ValueError(
            f"upstreams.{name}.apiKey may only be set when authorizationMode is 'configured'.")

    verify_tls = value.get("verifyTls", True)
    if not isinstance(verify_tls, bool):
        raise ValueError(f"upstreams.{name}.verifyTls must be true or false.")

    return WilmerProxyUpstreamConfig(
        name=name,
        base_url=_validate_base_url(value.get("baseUrl"), f"upstreams.{name}.baseUrl"),
        authorization_mode=authorization_mode,
        api_key=api_key,
        forward_headers=_validate_forward_headers(
            value.get("forwardHeaders"), f"upstreams.{name}.forwardHeaders"),
        connect_timeout_seconds=_positive_number(
            value.get("connectTimeoutSeconds"),
            f"upstreams.{name}.connectTimeoutSeconds",
            10.0,
        ),
        read_timeout_seconds=_positive_number(
            value.get("readTimeoutSeconds"),
            f"upstreams.{name}.readTimeoutSeconds",
            14400.0,
        ),
        verify_tls=verify_tls,
    )


def _parse_model(public_name: str, raw_value,
                 upstreams: Dict[str, WilmerProxyUpstreamConfig]) -> WilmerProxyModelConfig:
    """Validate a public model alias and its upstream mapping.

    Args:
        public_name (str): Exact alias exposed to clients.
        raw_value (Any): Parsed model mapping.
        upstreams (Dict[str, WilmerProxyUpstreamConfig]): Validated upstreams available for
            selection.

    Returns:
        WilmerProxyModelConfig: Mapping to an existing upstream and target model.

    Raises:
        ValueError: If the alias, target, or upstream reference is invalid.
    """
    if not isinstance(public_name, str) or not public_name.strip():
        raise ValueError("Every WilmerProxy model alias must be a non-empty string.")
    if public_name != public_name.strip():
        raise ValueError(f"WilmerProxy model alias '{public_name}' must not have surrounding whitespace.")
    if len(public_name) > 256 or any(ord(character) < 32 for character in public_name):
        raise ValueError(f"WilmerProxy model alias '{public_name}' is not valid.")

    value = _require_object(raw_value, f"models.{public_name}")
    _reject_unknown_keys(value, {"upstream", "targetModel"}, f"models.{public_name}")
    upstream = _require_non_empty_string(value.get("upstream"), f"models.{public_name}.upstream")
    if upstream not in upstreams:
        raise ValueError(
            f"models.{public_name}.upstream references unknown upstream '{upstream}'.")
    target_model = _require_non_empty_string(
        value.get("targetModel"), f"models.{public_name}.targetModel")
    return WilmerProxyModelConfig(
        public_name=public_name, upstream=upstream, target_model=target_model)


def parse_wilmer_proxy_config(name: str, raw_value) -> WilmerProxyConfig:
    """Validates and converts a raw WilmerProxy configuration object.

    Args:
        name (str): Configuration file base name, used in diagnostics.
        raw_value: Parsed JSON value.

    Returns:
        WilmerProxyConfig: The validated immutable top-level configuration.
    """
    value = _require_object(raw_value, f"WilmerProxy config '{name}'")
    _reject_unknown_keys(
        value,
        {"port", "useFileLogging", "upstreams", "models"},
        f"WilmerProxy config '{name}'",
    )

    raw_upstreams = _require_object(value.get("upstreams"), "upstreams")
    if not raw_upstreams:
        raise ValueError("upstreams must define at least one upstream Wilmer instance.")
    upstreams = {
        upstream_name: _parse_upstream(upstream_name, upstream_value)
        for upstream_name, upstream_value in raw_upstreams.items()
    }

    raw_models = _require_object(value.get("models"), "models")
    if not raw_models:
        raise ValueError("models must define at least one public model alias.")
    models = {
        public_name: _parse_model(public_name, model_value, upstreams)
        for public_name, model_value in raw_models.items()
    }

    port = value.get("port", 5050)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 through 65535.")
    use_file_logging = value.get("useFileLogging", False)
    if not isinstance(use_file_logging, bool):
        raise ValueError("useFileLogging must be true or false.")

    return WilmerProxyConfig(
        name=name,
        upstreams=upstreams,
        models=models,
        port=port,
        use_file_logging=use_file_logging,
    )


def load_wilmer_proxy_config(name: str = None) -> WilmerProxyConfig:
    """Loads a named configuration from ``Public/Configs/WilmerProxy``.

    Args:
        name (str, optional): Config base name. Defaults to the CLI-selected name.

    Returns:
        WilmerProxyConfig: Validated WilmerProxy configuration.
    """
    config_name = name or instance_global_variables.WILMER_PROXY_CONFIG
    if not config_utils._is_safe_flat_config_name(config_name):
        raise ValueError(
            "A safe --WilmerProxyConfig name is required in WilmerProxy mode.")
    path = config_utils.get_config_path("WilmerProxy", config_name)
    try:
        raw_value = config_utils.load_config(path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"WilmerProxy configuration was not found: {path}") from exc
    except ValueError as exc:
        raise ValueError(
            f"WilmerProxy configuration is not valid JSON: {path}: {exc}") from exc
    return parse_wilmer_proxy_config(config_name, raw_value)
