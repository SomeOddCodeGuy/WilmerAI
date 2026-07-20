# /Middleware/workflows/handlers/impl/extension_node_helpers.py
#
# Helpers shared by the extension-node handlers (CurlCommand, WebFetch,
# MCPToolCall). Each function that raises takes the node name so its error
# message matches what the node previously raised on its own.

from typing import Any, FrozenSet

from Middleware.utilities.streaming_utils import stream_static_content
from Middleware.workflows.models.execution_context import ExecutionContext


def validate_timeout(value: Any, node_name: str) -> float:
    """Coerces a configured timeout to a positive number of seconds.

    Mirrors the nodes' other up-front field validations so a non-numeric or
    non-positive value raises a clear ``ValueError`` instead of an opaque
    ``TypeError`` from deeper in the call.

    Args:
        value (Any): The configured ``timeout`` value to coerce.
        node_name (str): The node name used in the error message (e.g. "WebFetch").

    Returns:
        float: The timeout as a positive number of seconds.

    Raises:
        ValueError: If ``value`` is a boolean, non-numeric, or non-positive.
    """
    if isinstance(value, bool):
        raise ValueError(f"{node_name} 'timeout' must be a number of seconds; got {value!r}.")
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{node_name} 'timeout' must be a number of seconds; got {value!r}.")
    if value <= 0:
        raise ValueError(f"{node_name} 'timeout' must be a positive number of seconds; got {value!r}.")
    return value


def validate_bool(value: Any, field: str, node_name: str) -> bool:
    """Validates a boolean config field.

    Args:
        value (Any): The configured value to validate.
        field (str): The config field name, used in the error message.
        node_name (str): The node name used in the error message (e.g. "WebFetch").

    Returns:
        bool: The validated boolean value.

    Raises:
        ValueError: If ``value`` is not a boolean.
    """
    if not isinstance(value, bool):
        raise ValueError(f"{node_name} '{field}' must be a boolean (true/false); got {value!r}.")
    return value


def validate_max_bytes(value: Any, node_name: str) -> int:
    """Coerces the configured response-size cap to an integer number of bytes.

    ``0`` (or any non-positive value) disables the cap. A non-numeric value
    raises a clear ``ValueError`` rather than failing deep in the download path.

    Args:
        value (Any): The configured ``maxResponseBytes`` value to coerce.
        node_name (str): The node name used in the error message (e.g. "WebFetch").

    Returns:
        int: The cap as an integer number of bytes (non-positive disables it).

    Raises:
        ValueError: If ``value`` is a boolean or cannot be parsed as an integer.
    """
    if isinstance(value, bool):
        raise ValueError(f"{node_name} 'maxResponseBytes' must be an integer; got {value!r}.")
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{node_name} 'maxResponseBytes' must be an integer; got {value!r}.")
    return value


def resolve_allowed_hosts(allowed_hosts_template: Any, context: ExecutionContext,
                          variable_service: Any, node_name: str) -> FrozenSet[str]:
    """Resolves the optional ``allowedHosts`` allowlist to a set of lowercased hosts.

    Absent (``None``) means no allowlist (empty set). Each entry supports variable
    substitution so an allowlist can be sourced from a workflow variable.

    Args:
        allowed_hosts_template (Any): The raw ``allowedHosts`` config (``None`` or a list).
        context (ExecutionContext): The runtime context used for variable substitution.
        variable_service (Any): The handler's workflow variable service.
        node_name (str): The node name used in the error message (e.g. "WebFetch").

    Returns:
        FrozenSet[str]: The resolved, lowercased, non-empty host entries.

    Raises:
        ValueError: If ``allowedHosts`` is provided but is not a list, or if it is a
            list that yields no usable entries: empty, or every entry resolving to
            empty (fail closed rather than silently drop the host restriction).
    """
    if allowed_hosts_template is None:
        return frozenset()
    if not isinstance(allowed_hosts_template, list):
        raise ValueError(f"{node_name} 'allowedHosts' must be a JSON list of host strings.")
    resolved = set()
    for entry in allowed_hosts_template:
        value = variable_service.apply_variables(str(entry), context).strip().lower()
        if value:
            resolved.add(value)
    if not resolved:
        # The operator supplied an allowlist but it has no usable entries (an empty
        # list, or every entry resolved to empty, for example an unset variable).
        # Returning an empty set would read as "no allowlist" downstream and
        # silently permit every host, a fail-open. Fail closed instead: a
        # configured-but-ineffective allowlist is a configuration error.
        raise ValueError(
            f"{node_name} 'allowedHosts' was configured but contains no usable host "
            f"entries; refusing to run with no effective host restriction.")
    return frozenset(resolved)


def maybe_stream(payload: str, context: ExecutionContext) -> Any:
    """Wraps the payload in a streaming generator when the node is streaming.

    Args:
        payload (str): The fully formed result string.
        context (ExecutionContext): The runtime context whose ``stream`` flag is checked.

    Returns:
        Any: A streaming generator over ``payload`` when ``context.stream`` is True,
            otherwise ``payload`` unchanged.
    """
    if context.stream:
        return stream_static_content(payload)
    return payload
