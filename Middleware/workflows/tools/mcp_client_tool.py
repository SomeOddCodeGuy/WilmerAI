# /Middleware/workflows/tools/mcp_client_tool.py

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Coroutine, Dict, List, Optional

from Middleware.utilities.config_utils import load_mcp_server_config

logger = logging.getLogger(__name__)

_VALID_TRANSPORTS = ("stdio", "sse", "streamable_http")


class MCPToolCallError(RuntimeError):
    """Raised when an MCP tool invocation fails for any reason."""


def _timed_out_message(server_name: str, tool_name: str, timeout: float) -> str:
    """Builds the standard timeout error message for an MCP call.

    Args:
        server_name (str): The MCP server name, for the message.
        tool_name (str): The tool or operation name, for the message.
        timeout (float): The timeout, in seconds, that was exceeded.

    Returns:
        str: The formatted timeout error message.
    """
    return (
        f"MCP call to '{server_name}.{tool_name}' timed out after {timeout}s "
        f"(connect, initialize handshake, or tool call did not complete)."
    )


def _load_validated_server_config(server_name: str) -> Dict[str, Any]:
    """Validates an MCP server name and loads its config, checking the transport.

    Args:
        server_name (str): The name of an MCP server config under
            ``Public/Configs/MCPServers/``.

    Returns:
        Dict[str, Any]: The loaded server configuration.

    Raises:
        MCPToolCallError: If the name is not a bare identifier, the config file is
            missing or cannot be read/parsed, or the config has an invalid or
            missing 'transport'.
    """
    # Reject path separators, the parent/current dir, and a ":" (which on Windows
    # forms a drive-relative path like "C:foo" that os.path.join would NOT keep
    # inside MCPServers/). A server name is a bare identifier mapping to a filename.
    if "/" in server_name or "\\" in server_name or ":" in server_name or server_name in (".", ".."):
        raise MCPToolCallError(
            f"Invalid MCP server name {server_name!r}: must not contain path separators "
            f"or a drive-letter prefix."
        )

    try:
        server_config = load_mcp_server_config(server_name)
    except FileNotFoundError as exc:
        # Surface a missing registry file as the service's own error type so the
        # node's onError contract (and call_tool's documented Raises) hold for a
        # misconfigured server name, instead of leaking a bare FileNotFoundError.
        raise MCPToolCallError(
            f"MCP server config '{server_name}' was not found under Public/Configs/MCPServers/."
        ) from exc
    except (json.JSONDecodeError, OSError) as exc:
        # Same reasoning for a config file that exists but cannot be read or parsed.
        raise MCPToolCallError(
            f"MCP server config '{server_name}' could not be loaded: {exc}"
        ) from exc
    transport = server_config.get("transport")
    if transport not in _VALID_TRANSPORTS:
        raise MCPToolCallError(
            f"MCP server '{server_name}' has invalid or missing 'transport' "
            f"(must be one of {_VALID_TRANSPORTS}; got {transport!r})."
        )
    return server_config


def _run_mcp_operation(coro: Coroutine, server_name: str, op_name: str, timeout: float) -> Any:
    """Runs an async MCP operation with a timeout, unwrapping anyio's group wrapping.

    Args:
        coro (Coroutine): The operation coroutine (e.g. from ``_run_tool_call``).
        server_name (str): The MCP server name, for error messages.
        op_name (str): The tool or operation name, for error messages.
        timeout (float): Overall per-call timeout in seconds.

    Returns:
        Any: Whatever the coroutine returns.

    Raises:
        MCPToolCallError: If the operation times out or fails for any reason.
    """
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
    except MCPToolCallError:
        raise
    except asyncio.TimeoutError as exc:
        raise MCPToolCallError(_timed_out_message(server_name, op_name, timeout)) from exc
    except BaseExceptionGroup as exc:
        # anyio task groups (used by the MCP SDK transports) surface a failure wrapped
        # in a possibly-nested group that hides the real cause behind a generic
        # "unhandled errors in a TaskGroup" message.
        tool_error = exc.subgroup(MCPToolCallError)
        if tool_error is not None:
            while isinstance(tool_error, BaseExceptionGroup):
                tool_error = tool_error.exceptions[0]
            raise tool_error from None
        if exc.subgroup((asyncio.TimeoutError, TimeoutError)) is not None:
            raise MCPToolCallError(_timed_out_message(server_name, op_name, timeout)) from exc
        cause = exc
        while isinstance(cause, BaseExceptionGroup):
            cause = cause.exceptions[0]
        raise MCPToolCallError(
            f"MCP call to '{server_name}.{op_name}' failed: {cause}"
        ) from cause
    except Exception as exc:
        raise MCPToolCallError(
            f"MCP call to '{server_name}.{op_name}' failed: {exc}"
        ) from exc


class MCPClient:
    """
    A client for invoking tools on configured Model Context Protocol (MCP) servers.

    Mirrors the other external-service clients in this package (e.g.
    ``OfflineWikiApiClient``): a workflow handler instantiates one and calls it. The
    client is stateless -- the server is named per call and its connection settings are
    loaded from ``Public/Configs/MCPServers/`` at call time -- so a single instance can
    be reused across calls and servers. Each call opens a fresh connection via the
    official ``mcp`` Python SDK, dispatches on the server's configured transport
    (stdio, sse, or streamable_http), performs the operation, and closes the connection.
    """

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> str:
        """
        Invokes a single tool on a named MCP server and returns the result as a string.

        The CallToolResult is flattened into a string by concatenating its text content
        parts; structured or non-text content is JSON-serialized.

        Args:
            server_name (str): The name of an MCP server config under ``Public/Configs/MCPServers/``.
            tool_name (str): The MCP tool to invoke on that server.
            arguments (Optional[Dict[str, Any]]): The arguments to pass to the tool. ``None``
                is treated as an empty dict.
            timeout (float): Overall per-call timeout in seconds. Bounds the entire
                operation -- transport connect, ``session.initialize()`` handshake,
                and the ``session.call_tool`` call -- via ``asyncio.wait_for`` (and is
                also passed to ``call_tool`` as ``read_timeout_seconds``). A stdio
                server that spawns but never completes the MCP handshake therefore
                cannot block the calling worker indefinitely.

        Returns:
            str: The flattened tool result.

        Raises:
            MCPToolCallError: If the server config is invalid, the transport fails, the
                handshake or call times out, the tool reports an error, or any other
                failure occurs during the call.
        """
        server_config = _load_validated_server_config(server_name)
        return _run_mcp_operation(
            _run_tool_call(server_config, server_name, tool_name, arguments or {}, timeout),
            server_name,
            tool_name,
            timeout,
        )

    def list_tools(self, server_name: str, timeout: float = 30.0) -> Dict[str, Dict[str, Any]]:
        """
        Lists the tools exposed by a named MCP server, normalized for prompt formatting.

        Each tool is normalized to the ``{"llm_schema": {...}}`` shape that the agentic
        workflow's prompt formatter expects, keyed by tool name.

        Args:
            server_name (str): The name of an MCP server config under ``Public/Configs/MCPServers/``.
            timeout (float): Overall per-call timeout in seconds, bounding transport
                connect, the ``session.initialize()`` handshake, and the
                ``session.list_tools`` call.

        Returns:
            Dict[str, Dict[str, Any]]: A map of tool name to ``{"llm_schema": {...}}``,
                where the llm_schema is an OpenAI-style function schema built from the
                tool's name, description, and input schema.

        Raises:
            MCPToolCallError: If the server config is invalid, the transport fails, the
                handshake or call times out, or any other failure occurs.
        """
        server_config = _load_validated_server_config(server_name)
        tools = _run_mcp_operation(
            _run_list_tools(server_config, server_name, timeout),
            server_name,
            "list_tools",
            timeout,
        )

        normalized: Dict[str, Dict[str, Any]] = {}
        for tool in tools:
            name = getattr(tool, "name", None)
            if not name:
                logger.warning(f"MCP server '{server_name}' returned a tool without a name. Skipping.")
                continue
            description = getattr(tool, "description", None) or f"Execute {name}"
            parameters = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
            normalized[name] = {
                "llm_schema": {
                    "type": "function",
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                }
            }
        return normalized


@asynccontextmanager
async def _connect_streams(
    server_config: Dict[str, Any],
    server_name: str,
    timeout: float,
):
    """Async context manager that opens the configured transport and yields its streams.

    Dispatches on the config's 'transport' (stdio, sse, or streamable_http) and
    yields the ``(read_stream, write_stream)`` pair for a ClientSession.

    Args:
        server_config (Dict[str, Any]): The loaded MCP server configuration.
        server_name (str): The MCP server name, for error messages.
        timeout (float): Per-call timeout in seconds, passed to the sse/http transports.

    Yields:
        tuple: The ``(read_stream, write_stream)`` pair for the opened transport.

    Raises:
        MCPToolCallError: If an sse or streamable_http server config is missing its 'url'.
    """
    # Local imports keep the `mcp` package optional: callers that never invoke an
    # MCP node pay no import cost and can run Wilmer without the SDK installed.
    from mcp import StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client

    transport = server_config["transport"]

    if transport == "stdio":
        params = StdioServerParameters(
            command=server_config.get("command", ""),
            args=server_config.get("args", []) or [],
            env=server_config.get("env"),
            cwd=server_config.get("cwd"),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            yield read_stream, write_stream
        return

    if transport == "sse":
        url = server_config.get("url")
        if not url:
            raise MCPToolCallError(
                f"MCP server '{server_name}' (sse) requires a 'url' field."
            )
        async with sse_client(
            url,
            headers=server_config.get("headers"),
            timeout=timeout,
        ) as (read_stream, write_stream):
            yield read_stream, write_stream
        return

    # transport == "streamable_http"
    url = server_config.get("url")
    if not url:
        raise MCPToolCallError(
            f"MCP server '{server_name}' (streamable_http) requires a 'url' field."
        )
    async with streamablehttp_client(
        url,
        headers=server_config.get("headers"),
        timeout=timeout,
    ) as (read_stream, write_stream, _terminate):
        yield read_stream, write_stream


async def _run_tool_call(
    server_config: Dict[str, Any],
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: float,
) -> str:
    """Async helper that opens a transport, runs one tool call, and returns the flattened result.

    Args:
        server_config (Dict[str, Any]): The loaded MCP server configuration.
        server_name (str): The MCP server name, for error messages.
        tool_name (str): The MCP tool to invoke.
        arguments (Dict[str, Any]): The arguments to pass to the tool.
        timeout (float): Per-call timeout in seconds; also the per-tool read timeout.

    Returns:
        str: The flattened tool result.
    """
    read_timeout = timedelta(seconds=timeout)
    async with _connect_streams(server_config, server_name, timeout) as (read_stream, write_stream):
        return await _call_tool_in_session(
            read_stream, write_stream, tool_name, arguments, read_timeout
        )


async def _run_list_tools(
    server_config: Dict[str, Any],
    server_name: str,
    timeout: float,
) -> List[Any]:
    """Async helper that opens a transport, lists the server's tools, and returns them.

    Args:
        server_config (Dict[str, Any]): The loaded MCP server configuration.
        server_name (str): The MCP server name, for error messages.
        timeout (float): Per-call timeout in seconds.

    Returns:
        List[Any]: The raw tool objects reported by the server, or an empty list.
    """
    from mcp import ClientSession

    async with _connect_streams(server_config, server_name, timeout) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
    return getattr(result, "tools", []) or []


async def _call_tool_in_session(
    read_stream: Any,
    write_stream: Any,
    tool_name: str,
    arguments: Dict[str, Any],
    read_timeout: timedelta,
) -> str:
    """Initializes a ClientSession, calls one tool, and returns the flattened result.

    Args:
        read_stream (Any): The transport read stream for the session.
        write_stream (Any): The transport write stream for the session.
        tool_name (str): The MCP tool to invoke.
        arguments (Dict[str, Any]): The arguments to pass to the tool.
        read_timeout (timedelta): The per-tool read timeout for the call.

    Returns:
        str: The flattened tool result.

    Raises:
        MCPToolCallError: If the tool result is flagged as an error.
    """
    from mcp import ClientSession

    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        result = await session.call_tool(
            tool_name,
            arguments=arguments,
            read_timeout_seconds=read_timeout,
        )

    if getattr(result, "isError", False):
        raise MCPToolCallError(
            f"MCP tool '{tool_name}' reported an error: "
            f"{_flatten_content(getattr(result, 'content', []))}"
        )

    return _flatten_result(result)


def _flatten_result(result: Any) -> str:
    """Converts a CallToolResult into a plain string.

    Prefers ``structuredContent`` when present; otherwise concatenates the text
    parts of ``content``. Non-text content blocks are JSON-serialized.

    Args:
        result (Any): The CallToolResult to flatten.

    Returns:
        str: The flattened result as a string.
    """
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return json.dumps(structured)
    content = getattr(result, "content", []) or []
    return _flatten_content(content)


def _flatten_content(content: List[Any]) -> str:
    """Concatenates a list of content blocks into a single string.

    Text blocks contribute their text; other blocks are JSON-serialized via
    ``model_dump`` when available, otherwise their ``str()`` form.

    Args:
        content (List[Any]): The content blocks to flatten.

    Returns:
        str: The concatenated string of all content blocks.
    """
    parts: List[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        else:
            # Fall back to a JSON dump of whatever fields the content carries.
            dump = getattr(item, "model_dump", None)
            parts.append(json.dumps(dump(mode="json")) if callable(dump) else str(item))
    return "".join(parts)
