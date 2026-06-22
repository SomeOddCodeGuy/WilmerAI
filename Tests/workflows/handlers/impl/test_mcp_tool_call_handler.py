# tests/workflows/handlers/impl/test_mcp_tool_call_handler.py

import types

import pytest

from Middleware.workflows.tools.mcp_client_tool import MCPClient, MCPToolCallError
from Middleware.workflows.handlers.impl.mcp_tool_call_handler import MCPToolCallHandler
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.fixture
def mcp_handler(mocker):
    mock_workflow_manager = mocker.MagicMock()
    mock_variable_service = mocker.MagicMock()
    mock_variable_service.apply_variables.side_effect = lambda template, context: template
    return MCPToolCallHandler(
        workflow_manager=mock_workflow_manager,
        workflow_variable_service=mock_variable_service,
    )


def _make_context(config, stream=False):
    return ExecutionContext(
        request_id="req-1",
        workflow_id="wf-1",
        discussion_id=None,
        config=config,
        messages=[],
        stream=stream,
    )


def test_missing_server_raises(mcp_handler):
    context = _make_context({"type": "MCPToolCall", "tool": "read_file"})
    with pytest.raises(ValueError, match="'server'"):
        mcp_handler.handle(context)


def test_missing_tool_raises(mcp_handler):
    context = _make_context({"type": "MCPToolCall", "server": "filesystem"})
    with pytest.raises(ValueError, match="'tool'"):
        mcp_handler.handle(context)


def test_invalid_on_error_raises(mcp_handler):
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "onError": "swallow",
    })
    with pytest.raises(ValueError, match="onError"):
        mcp_handler.handle(context)


def test_non_numeric_timeout_raises(mcp_handler, mocker):
    """A non-numeric timeout raises the node's own clear ValueError before any MCP call."""
    mock_call = mocker.patch.object(
        MCPClient, "call_tool",
        return_value="ok",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "timeout": "soon",
    })
    with pytest.raises(ValueError, match="timeout"):
        mcp_handler.handle(context)
    mock_call.assert_not_called()


def test_non_positive_timeout_raises(mcp_handler):
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "timeout": 0,
    })
    with pytest.raises(ValueError, match="timeout"):
        mcp_handler.handle(context)


def test_arguments_must_be_object(mcp_handler):
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "arguments": "path=/etc",
    })
    with pytest.raises(ValueError, match="arguments"):
        mcp_handler.handle(context)


def test_happy_path_invokes_call_mcp_tool(mcp_handler, mocker):
    mock_call = mocker.patch.object(
        MCPClient, "call_tool",
        return_value="file contents",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "arguments": {"path": "/etc/hostname"},
    })

    result = mcp_handler.handle(context)

    assert result == "file contents"
    mock_call.assert_called_once_with(
        server_name="filesystem",
        tool_name="read_file",
        arguments={"path": "/etc/hostname"},
        timeout=30,
    )


def test_custom_timeout_passed_through(mcp_handler, mocker):
    mock_call = mocker.patch.object(
        MCPClient, "call_tool",
        return_value="ok",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "arguments": {},
        "timeout": 5,
    })

    mcp_handler.handle(context)

    assert mock_call.call_args.kwargs["timeout"] == 5


def test_no_arguments_defaults_to_empty_dict(mcp_handler, mocker):
    mock_call = mocker.patch.object(
        MCPClient, "call_tool",
        return_value="pong",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "ping",
        "tool": "ping",
    })

    mcp_handler.handle(context)

    assert mock_call.call_args.kwargs["arguments"] == {}


def test_variable_substitution_on_server_tool_and_arguments(mcp_handler, mocker):
    sub_map = {
        "{ServerVar}": "filesystem",
        "{ToolVar}": "read_file",
        "/data/{userId}.txt": "/data/42.txt",
    }
    mcp_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mock_call = mocker.patch.object(
        MCPClient, "call_tool",
        return_value="ok",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "{ServerVar}",
        "tool": "{ToolVar}",
        "arguments": {"path": "/data/{userId}.txt", "lines": 10},
    })

    mcp_handler.handle(context)

    mock_call.assert_called_once_with(
        server_name="filesystem",
        tool_name="read_file",
        arguments={"path": "/data/42.txt", "lines": 10},
        timeout=30,
    )


def test_variable_substitution_recurses_into_nested_structures(mcp_handler, mocker):
    sub_map = {"{name}": "alice", "/home/{name}": "/home/alice"}
    mcp_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mock_call = mocker.patch.object(
        MCPClient, "call_tool",
        return_value="ok",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "fs",
        "tool": "do",
        "arguments": {
            "user": "{name}",
            "paths": ["/home/{name}", "/tmp"],
            "meta": {"requestedBy": "{name}"},
        },
    })

    mcp_handler.handle(context)

    assert mock_call.call_args.kwargs["arguments"] == {
        "user": "alice",
        "paths": ["/home/alice", "/tmp"],
        "meta": {"requestedBy": "alice"},
    }


def test_mcp_failure_raises_by_default(mcp_handler, mocker):
    mocker.patch.object(
        MCPClient, "call_tool",
        side_effect=MCPToolCallError("connect failed"),
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
    })

    with pytest.raises(MCPToolCallError, match="connect failed"):
        mcp_handler.handle(context)


def test_mcp_failure_returns_message_when_on_error_return(mcp_handler, mocker):
    mocker.patch.object(
        MCPClient, "call_tool",
        side_effect=MCPToolCallError("server unreachable"),
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
        "onError": "return",
    })

    result = mcp_handler.handle(context)
    assert "server unreachable" in result


def test_streaming_response_returns_generator(mcp_handler, mocker):
    mocker.patch.object(
        MCPClient, "call_tool",
        return_value="hello",
    )
    context = _make_context({
        "type": "MCPToolCall",
        "server": "filesystem",
        "tool": "read_file",
    }, stream=True)

    result = mcp_handler.handle(context)

    assert isinstance(result, types.GeneratorType)
    chunks = list(result)
    joined = "".join(c["token"] for c in chunks)
    assert joined == "hello"
