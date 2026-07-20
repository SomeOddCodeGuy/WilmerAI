# Tests/workflows/tools/test_mcp_client_tool.py

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from Middleware.workflows.tools import mcp_client_tool
from Middleware.workflows.tools.mcp_client_tool import (
    MCPClient,
    MCPToolCallError,
    _flatten_content,
    _flatten_result,
)


# ---------------------------------------------------------------------------
# call_tool (high-level dispatch + error wrapping)
# ---------------------------------------------------------------------------


def test_call_tool_invalid_transport_raises(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "magic"},
    )
    with pytest.raises(MCPToolCallError, match="invalid or missing 'transport'"):
        MCPClient().call_tool("srv", "tool", {})


def test_call_tool_missing_transport_raises(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"command": "echo"},
    )
    with pytest.raises(MCPToolCallError, match="invalid or missing 'transport'"):
        MCPClient().call_tool("srv", "tool", {})


def test_call_tool_missing_config_file_raises_mcp_error(mocker):
    """A missing MCPServers/<name>.json surfaces as MCPToolCallError (not a raw
    FileNotFoundError), so the node's onError contract holds for a bad server name."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        side_effect=FileNotFoundError("no such file"),
    )
    with pytest.raises(MCPToolCallError, match="was not found"):
        MCPClient().call_tool("ghost-server", "tool", {})


def test_call_tool_malformed_config_raises_mcp_error(mocker):
    """A config file that exists but is not valid JSON is wrapped as MCPToolCallError."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        side_effect=json.JSONDecodeError("bad", "{", 0),
    )
    with pytest.raises(MCPToolCallError, match="could not be loaded"):
        MCPClient().call_tool("broken-server", "tool", {})


def test_call_tool_unreadable_config_raises_mcp_error(mocker):
    """A config file that exists but cannot be read (OSError) is wrapped as
    MCPToolCallError, same as a malformed one."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        side_effect=OSError("permission denied"),
    )
    with pytest.raises(MCPToolCallError, match="could not be loaded"):
        MCPClient().call_tool("locked-server", "tool", {})


def test_call_tool_loads_config_by_name(mocker):
    mock_load = mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        return "ok"

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    MCPClient().call_tool("my-server", "ping", {})

    mock_load.assert_called_once_with("my-server")


def test_call_tool_returns_flattened_result(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        return "hello world"

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    result = MCPClient().call_tool("srv", "tool", {"k": "v"})
    assert result == "hello world"


def test_call_tool_wraps_generic_exception(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        raise RuntimeError("boom")

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(MCPToolCallError, match="boom"):
        MCPClient().call_tool("srv", "tool", {})


def test_call_tool_preserves_mcp_error(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        raise MCPToolCallError("upstream failure")

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(MCPToolCallError, match="upstream failure"):
        MCPClient().call_tool("srv", "tool", {})


def test_call_tool_none_arguments_becomes_empty_dict(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )
    captured = {}

    async def fake_run_tool_call(server_config, server_name, tool_name, arguments, timeout):
        captured["arguments"] = arguments
        return "ok"

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    MCPClient().call_tool("srv", "tool", None)

    assert captured["arguments"] == {}


def test_call_tool_rejects_path_separators_in_server_name(mocker):
    """A server name with path separators must be rejected before any config lookup."""
    mock_load = mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
    )
    # Includes "C:evil"/"C:", the Windows drive-relative names that escape MCPServers/
    # because os.path.join(dir, "C:evil.json") returns "C:evil.json". "." and ".."
    # are the current/parent dir names the guard rejects by membership.
    for bad_name in ("../secrets", "dir/server", "dir\\server", ".", "..", "C:evil", "C:"):
        with pytest.raises(MCPToolCallError, match="path separators"):
            MCPClient().call_tool(bad_name, "tool", {})
    mock_load.assert_not_called()


def test_call_tool_times_out_when_handshake_hangs(mocker):
    """A server that connects but never finishes the handshake/call must not wedge the
    worker: asyncio.wait_for bounds the whole operation and surfaces a clear timeout error."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def hanging_run_tool_call(*args, **kwargs):
        await asyncio.sleep(10)
        return "never"

    mocker.patch.object(mcp_client_tool, "_run_tool_call", hanging_run_tool_call)

    with pytest.raises(MCPToolCallError, match="timed out"):
        MCPClient().call_tool("srv", "tool", {}, timeout=0.01)


# ---------------------------------------------------------------------------
# anyio task-group exception-group unwrapping
#
# The MCP SDK's transports run inside anyio task groups, so an exception raised in
# their scope (e.g. the clean MCPToolCallError from an isError tool result) reaches
# call_tool re-wrapped in an ExceptionGroup. Without unwrapping, the real reason
# is masked behind "unhandled errors in a TaskGroup (1 sub-exception)".
# ---------------------------------------------------------------------------


def test_call_tool_unwraps_mcp_error_from_task_group(mocker):
    """A clean MCPToolCallError wrapped in a task-group ExceptionGroup keeps its message."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [MCPToolCallError("MCP tool 'add' reported an error: Tool add not found")],
        )

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(MCPToolCallError) as excinfo:
        MCPClient().call_tool("srv", "add", {})
    assert "Tool add not found" in str(excinfo.value)
    assert "TaskGroup" not in str(excinfo.value)


def test_call_tool_unwraps_generic_error_from_task_group(mocker):
    """A real transport error wrapped in a task group surfaces its own message."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup", [ConnectionError("connection refused")]
        )

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(MCPToolCallError) as excinfo:
        MCPClient().call_tool("srv", "tool", {})
    assert "connection refused" in str(excinfo.value)
    assert "TaskGroup" not in str(excinfo.value)


def test_call_tool_unwraps_nested_task_group(mocker):
    """A group nested inside a group is peeled all the way to the real cause."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        inner = ExceptionGroup("inner", [MCPToolCallError("deep reason")])
        raise ExceptionGroup("outer", [inner])

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(MCPToolCallError, match="deep reason"):
        MCPClient().call_tool("srv", "tool", {})


def test_call_tool_unwraps_timeout_from_task_group(mocker):
    """A timeout wrapped in a task group still produces the standard timeout message."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_tool_call(*args, **kwargs):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [TimeoutError("read timed out")])

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(MCPToolCallError, match="timed out"):
        MCPClient().call_tool("srv", "tool", {})


def test_call_tool_does_not_swallow_bare_base_exception(mocker):
    """A non-group BaseException (control-flow) must propagate untouched."""
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    class _Sentinel(BaseException):
        pass

    async def fake_run_tool_call(*args, **kwargs):
        raise _Sentinel("control flow")

    mocker.patch.object(mcp_client_tool, "_run_tool_call", fake_run_tool_call)

    with pytest.raises(_Sentinel):
        MCPClient().call_tool("srv", "tool", {})


# ---------------------------------------------------------------------------
# Flatten helpers
# ---------------------------------------------------------------------------


def test_flatten_result_prefers_structured_content():
    result = SimpleNamespace(structuredContent={"answer": 42}, content=[])
    assert json.loads(_flatten_result(result)) == {"answer": 42}


def test_flatten_result_concatenates_text_content_when_no_structured():
    item1 = SimpleNamespace(text="hello ")
    item2 = SimpleNamespace(text="world")
    result = SimpleNamespace(structuredContent=None, content=[item1, item2])
    assert _flatten_result(result) == "hello world"


def test_flatten_result_handles_empty_content():
    result = SimpleNamespace(structuredContent=None, content=[])
    assert _flatten_result(result) == ""


def test_flatten_content_falls_back_to_model_dump():
    item = MagicMock()
    item.text = None
    item.model_dump.return_value = {"type": "image", "data": "..."}
    assert json.loads(_flatten_content([item])) == {"type": "image", "data": "..."}


def test_flatten_content_falls_back_to_str_when_no_model_dump():
    plain = SimpleNamespace(text=None)
    out = _flatten_content([plain])
    # Without text and without model_dump, the block contributes exactly str(item).
    assert out == str(plain)


# ---------------------------------------------------------------------------
# _run_tool_call: transport dispatch
#
# The MCP SDK uses async context managers for transport setup and session
# lifecycle. The tests below replace each transport entry point and ClientSession
# with fakes that record what they were called with, then run _run_tool_call
# directly via asyncio.run.
# ---------------------------------------------------------------------------


class _FakeSession:
    """Drop-in stand-in for `mcp.ClientSession` exercising the same async-context-manager
    + initialize + call_tool surface our code calls. The most recent instance is kept on
    the class so tests can assert what actually reached session.call_tool."""

    last_instance = None

    def __init__(self, read_stream, write_stream):
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.initialized = False
        self.call_args = None
        self.result = SimpleNamespace(
            structuredContent=None,
            content=[SimpleNamespace(text="hi")],
            isError=False,
        )
        _FakeSession.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        self.initialized = True

    async def call_tool(self, name, arguments=None, read_timeout_seconds=None):
        assert self.initialized, "call_tool called before initialize()"
        self.call_args = {
            "name": name,
            "arguments": arguments,
            "read_timeout_seconds": read_timeout_seconds,
        }
        return self.result


def _make_fake_transport(record):
    @asynccontextmanager
    async def fake(*args, **kwargs):
        record["args"] = args
        record["kwargs"] = kwargs
        read = MagicMock(name="read_stream")
        write = MagicMock(name="write_stream")
        yield read, write

    return fake


def _make_fake_streamable_transport(record):
    @asynccontextmanager
    async def fake(*args, **kwargs):
        record["args"] = args
        record["kwargs"] = kwargs
        read = MagicMock(name="read_stream")
        write = MagicMock(name="write_stream")
        terminate = MagicMock(name="terminate")
        yield read, write, terminate

    return fake


def test_run_tool_call_stdio_constructs_params_and_calls_tool(mocker):
    record = {}
    fake_stdio = _make_fake_transport(record)

    import mcp
    import mcp.client.stdio as stdio_module

    mocker.patch.object(stdio_module, "stdio_client", fake_stdio)
    mocker.patch.object(mcp, "ClientSession", _FakeSession)

    server_config = {
        "transport": "stdio",
        "command": "echo",
        "args": ["hello"],
        "env": {"FOO": "1"},
        "cwd": "/tmp",
    }

    _FakeSession.last_instance = None
    result = asyncio.run(mcp_client_tool._run_tool_call(
        server_config, "srv", "ping", {"x": 1}, timeout=12.0
    ))

    assert result == "hi"
    # The stdio entry point was passed a StdioServerParameters built from the config.
    params = record["args"][0]
    assert params.command == "echo"
    assert params.args == ["hello"]
    assert params.env == {"FOO": "1"}
    assert params.cwd == "/tmp"
    # The session received the exact tool name, arguments, and read timeout.
    assert _FakeSession.last_instance.call_args == {
        "name": "ping",
        "arguments": {"x": 1},
        "read_timeout_seconds": timedelta(seconds=12.0),
    }


def test_run_tool_call_sse_passes_url_headers_timeout(mocker):
    record = {}
    fake_sse = _make_fake_transport(record)

    import mcp
    import mcp.client.sse as sse_module

    mocker.patch.object(sse_module, "sse_client", fake_sse)
    mocker.patch.object(mcp, "ClientSession", _FakeSession)

    server_config = {
        "transport": "sse",
        "url": "http://localhost:5050/sse",
        "headers": {"Authorization": "Bearer abc"},
    }

    _FakeSession.last_instance = None
    result = asyncio.run(mcp_client_tool._run_tool_call(
        server_config, "srv", "ping", {}, timeout=7.5
    ))

    assert result == "hi"
    assert record["args"][0] == "http://localhost:5050/sse"
    assert record["kwargs"]["headers"] == {"Authorization": "Bearer abc"}
    assert record["kwargs"]["timeout"] == 7.5
    assert _FakeSession.last_instance.call_args == {
        "name": "ping",
        "arguments": {},
        "read_timeout_seconds": timedelta(seconds=7.5),
    }


def test_run_tool_call_sse_missing_url_raises(mocker):
    server_config = {"transport": "sse"}
    with pytest.raises(MCPToolCallError, match="requires a 'url'"):
        asyncio.run(mcp_client_tool._run_tool_call(
            server_config, "srv", "ping", {}, timeout=1.0
        ))


def test_run_tool_call_streamable_http_passes_url_headers_timeout(mocker):
    record = {}
    fake_http = _make_fake_streamable_transport(record)

    import mcp
    import mcp.client.streamable_http as streamable_module

    mocker.patch.object(streamable_module, "streamablehttp_client", fake_http)
    mocker.patch.object(mcp, "ClientSession", _FakeSession)

    server_config = {
        "transport": "streamable_http",
        "url": "http://localhost:5050/mcp",
        "headers": {"X-Auth": "token"},
    }

    _FakeSession.last_instance = None
    result = asyncio.run(mcp_client_tool._run_tool_call(
        server_config, "srv", "ping", {}, timeout=15.0
    ))

    assert result == "hi"
    assert record["args"][0] == "http://localhost:5050/mcp"
    assert record["kwargs"]["headers"] == {"X-Auth": "token"}
    assert record["kwargs"]["timeout"] == 15.0
    assert _FakeSession.last_instance.call_args == {
        "name": "ping",
        "arguments": {},
        "read_timeout_seconds": timedelta(seconds=15.0),
    }


def test_run_tool_call_streamable_http_missing_url_raises():
    server_config = {"transport": "streamable_http"}
    with pytest.raises(MCPToolCallError, match="requires a 'url'"):
        asyncio.run(mcp_client_tool._run_tool_call(
            server_config, "srv", "ping", {}, timeout=1.0
        ))


def test_call_tool_in_session_raises_when_tool_reports_error(mocker):
    import mcp
    import mcp.client.stdio as stdio_module

    class ErrorSession(_FakeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.result = SimpleNamespace(
                structuredContent=None,
                content=[SimpleNamespace(text="bad path")],
                isError=True,
            )

    mocker.patch.object(stdio_module, "stdio_client", _make_fake_transport({}))
    mocker.patch.object(mcp, "ClientSession", ErrorSession)

    server_config = {"transport": "stdio", "command": "true", "args": [], "env": None, "cwd": None}

    with pytest.raises(MCPToolCallError, match="bad path"):
        asyncio.run(mcp_client_tool._run_tool_call(
            server_config, "srv", "ping", {}, timeout=1.0
        ))
