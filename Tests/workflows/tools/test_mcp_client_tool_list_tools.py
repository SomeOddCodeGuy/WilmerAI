# Tests/workflows/tools/test_mcp_client_tool_list_tools.py

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from Middleware.workflows.tools import mcp_client_tool
from Middleware.workflows.tools.mcp_client_tool import MCPClient, MCPToolCallError


def _tool(name=None, description=None, input_schema=None):
    return SimpleNamespace(name=name, description=description, inputSchema=input_schema)


# ---------------------------------------------------------------------------
# list_tools (high-level dispatch + normalization)
# ---------------------------------------------------------------------------


def test_list_tools_invalid_server_name_raises():
    with pytest.raises(MCPToolCallError, match="must not contain path separators"):
        MCPClient().list_tools("../evil")


def test_list_tools_invalid_transport_raises(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "magic"},
    )
    with pytest.raises(MCPToolCallError, match="invalid or missing 'transport'"):
        MCPClient().list_tools("srv")


def test_list_tools_normalizes_to_llm_schema_shape(mocker):
    """
    Tests that the SDK's tool list is normalized to the
    {tool_name: {"llm_schema": {...}}} shape the prompt formatter expects.
    """
    # Arrange
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )
    schema = {"type": "object", "properties": {"timezone": {"type": "string"}}}

    async def fake_run_list_tools(*args, **kwargs):
        return [_tool("get_current_time", "Get the time", schema)]

    mocker.patch.object(mcp_client_tool, "_run_list_tools", fake_run_list_tools)

    # Act
    tools = MCPClient().list_tools("time-server")

    # Assert
    assert tools == {
        "get_current_time": {
            "llm_schema": {
                "type": "function",
                "name": "get_current_time",
                "description": "Get the time",
                "parameters": schema,
            }
        }
    }


def test_list_tools_defaults_missing_description_and_schema(mocker):
    """
    Tests that tools lacking a description or inputSchema get usable defaults,
    and tools without a name are skipped entirely.
    """
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def fake_run_list_tools(*args, **kwargs):
        return [_tool("bare_tool"), _tool(None, "nameless", {})]

    mocker.patch.object(mcp_client_tool, "_run_list_tools", fake_run_list_tools)

    tools = MCPClient().list_tools("srv")

    assert set(tools.keys()) == {"bare_tool"}
    llm_schema = tools["bare_tool"]["llm_schema"]
    assert llm_schema["description"] == "Execute bare_tool"
    assert llm_schema["parameters"] == {"type": "object", "properties": {}}


def test_list_tools_timeout_raises_clean_error(mocker):
    """
    Tests that a hung list_tools call is bounded by the timeout and surfaces
    a clean MCPToolCallError naming the operation.
    """
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def hanging_run_list_tools(*args, **kwargs):
        await asyncio.sleep(30)

    mocker.patch.object(mcp_client_tool, "_run_list_tools", hanging_run_list_tools)

    with pytest.raises(MCPToolCallError, match="timed out after 0.05s"):
        MCPClient().list_tools("srv", timeout=0.05)


def test_list_tools_wraps_transport_errors(mocker):
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.load_mcp_server_config",
        return_value={"transport": "stdio"},
    )

    async def failing_run_list_tools(*args, **kwargs):
        raise RuntimeError("connection refused")

    mocker.patch.object(mcp_client_tool, "_run_list_tools", failing_run_list_tools)

    with pytest.raises(MCPToolCallError, match="srv.list_tools.*connection refused"):
        MCPClient().list_tools("srv")


# ---------------------------------------------------------------------------
# _run_list_tools: transport dispatch (stdio exercised end-to-end with fakes)
# ---------------------------------------------------------------------------


class _FakeListSession:
    """Stand-in for `mcp.ClientSession` exercising the initialize + list_tools surface."""

    def __init__(self, read_stream, write_stream):
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        assert self.initialized, "list_tools called before initialize()"
        return SimpleNamespace(tools=[_tool("ping", "Ping it", {"type": "object"})])


def test_run_list_tools_stdio_dispatch(mocker):
    record = {}

    @asynccontextmanager
    async def fake_stdio(*args, **kwargs):
        record["args"] = args
        yield MagicMock(name="read"), MagicMock(name="write")

    import mcp
    import mcp.client.stdio as stdio_module

    mocker.patch.object(stdio_module, "stdio_client", fake_stdio)
    mocker.patch.object(mcp, "ClientSession", _FakeListSession)

    server_config = {"transport": "stdio", "command": "echo", "args": []}

    tools = asyncio.run(
        mcp_client_tool._run_list_tools(server_config, "srv", timeout=5.0)
    )

    assert len(tools) == 1
    assert tools[0].name == "ping"
    assert record["args"][0].command == "echo"


def test_run_list_tools_result_without_tools_attr_returns_empty(mocker):
    """A list_tools result object with no .tools attribute normalizes to an empty list."""

    class _NoToolsSession(_FakeListSession):
        async def list_tools(self):
            assert self.initialized, "list_tools called before initialize()"
            return SimpleNamespace()  # no .tools attribute at all

    @asynccontextmanager
    async def fake_stdio(*args, **kwargs):
        yield MagicMock(name="read"), MagicMock(name="write")

    import mcp
    import mcp.client.stdio as stdio_module

    mocker.patch.object(stdio_module, "stdio_client", fake_stdio)
    mocker.patch.object(mcp, "ClientSession", _NoToolsSession)

    server_config = {"transport": "stdio", "command": "echo", "args": []}

    tools = asyncio.run(
        mcp_client_tool._run_list_tools(server_config, "srv", timeout=5.0)
    )

    assert tools == []


def test_run_list_tools_sse_missing_url_raises(mocker):
    with pytest.raises(MCPToolCallError, match="requires a 'url' field"):
        asyncio.run(
            mcp_client_tool._run_list_tools({"transport": "sse"}, "srv", timeout=5.0)
        )
