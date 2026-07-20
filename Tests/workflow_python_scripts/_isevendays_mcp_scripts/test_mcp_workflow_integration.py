# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_mcp_workflow_integration.py

import json

import pytest

from Middleware.workflows.tools.dynamic_module_loader import DynamicModuleError
from Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration import (
    Invoke,
    MCPConfigurationError,
    MCPIntegrationError,
    MCPMessageParsingError,
    MCPToolExecutionError,
    _parse_messages_input_static,
    _parse_tool_execution_map_static,
    format_results_only,
    parse_string_messages,
    validate_node_type,
)

MCPO_URL = "http://localhost:8889"


def _execution_map():
    return {
        "get_current_time": {
            "service": "time",
            "path": "/current",
            "method": "post",
            "openapi_params": [],
        }
    }


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_integration_errors_subclass_loader_dynamic_module_error():
    """
    Tests that the module's exceptions derive from the loader's
    DynamicModuleError so run_dynamic_module reports them properly
    (the same class it catches, not a lookalike fallback).
    """
    err = MCPConfigurationError("bad config")
    assert isinstance(err, DynamicModuleError)
    assert isinstance(err, MCPIntegrationError)
    assert err.module_name == "mcp_workflow_integration"


# ---------------------------------------------------------------------------
# Input parsing helpers
# ---------------------------------------------------------------------------


def test_parse_string_messages_extracts_role_prefix():
    assert parse_string_messages("assistant: hello") == [
        {"role": "assistant", "content": "hello"}
    ]
    assert parse_string_messages("just some text") == [
        {"role": "user", "content": "just some text"}
    ]


def test_validate_node_type():
    assert validate_node_type("PythonModule") is True
    assert validate_node_type("NotARealNodeType") is False


def test_parse_tool_execution_map_accepts_dict_and_json_string():
    raw = _execution_map()
    assert _parse_tool_execution_map_static(raw) == raw
    assert _parse_tool_execution_map_static(json.dumps(raw)) == raw


def test_parse_tool_execution_map_rejects_bad_input():
    with pytest.raises(MCPConfigurationError):
        _parse_tool_execution_map_static("not valid json {")
    with pytest.raises(MCPConfigurationError):
        _parse_tool_execution_map_static('["a", "list"]')
    with pytest.raises(MCPConfigurationError):
        _parse_tool_execution_map_static(12345)


def test_parse_messages_input_accepts_list_and_json_string():
    messages = [{"role": "user", "content": "hi"}]
    assert _parse_messages_input_static(messages) == messages
    assert _parse_messages_input_static(json.dumps(messages)) == messages
    assert _parse_messages_input_static(None) == []


def test_parse_messages_input_falls_back_to_single_message_string():
    assert _parse_messages_input_static("user: hello") == [
        {"role": "user", "content": "hello"}
    ]


def test_parse_messages_input_rejects_invalid_structures():
    with pytest.raises(MCPMessageParsingError):
        _parse_messages_input_static([{"role": "user"}])  # missing content
    with pytest.raises(MCPMessageParsingError):
        _parse_messages_input_static(12345)


# ---------------------------------------------------------------------------
# format_results_only (result formatting)
# ---------------------------------------------------------------------------


def test_format_results_only_formats_success_and_error_results():
    """
    Tests that successful results are rendered with their JSON payload and
    error results include the error/status fields.
    """
    # Arrange
    tool_results = [
        {
            "tool_call": {"name": "get_current_time", "parameters": {"timezone": "UTC"}},
            "result": {"time": "12:00"},
        },
        {
            "tool_call": {"name": "broken_tool", "parameters": {}},
            "result": {"error": "boom", "status": "error", "timestamp": "t"},
        },
    ]

    # Act
    formatted = format_results_only(tool_results)

    # Assert
    assert formatted.startswith("Tool Results:")
    assert "Name: get_current_time" in formatted
    assert '"time": "12:00"' in formatted
    assert "Error: boom" in formatted
    assert "Status: error" in formatted


def test_format_results_only_empty_list_returns_empty_string():
    assert format_results_only([]) == ""


# ---------------------------------------------------------------------------
# Invoke (end-to-end orchestration with the executor mocked)
# ---------------------------------------------------------------------------


def test_invoke_returns_original_response_when_no_tool_call(mocker):
    """
    Tests that when the executor detects no tool call, the original LLM
    response is returned unchanged.
    """
    # Arrange
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration.mcp_tool_executor.Invoke",
        return_value={"response": "Just a normal answer.", "has_tool_call": False},
    )

    # Act
    result = Invoke(
        messages=[{"role": "user", "content": "hi"}],
        original_response="Just a normal answer.",
        tool_execution_map=_execution_map(),
    )

    # Assert
    assert result == "Just a normal answer."


def test_invoke_formats_tool_results_when_tool_call_executed(mocker):
    """
    Tests that detected-and-executed tool calls are returned as the
    formatted results block, and that the original response was appended to
    the messages handed to the executor.
    """
    # Arrange
    mock_executor = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration.mcp_tool_executor.Invoke",
        return_value={
            "response": "raw",
            "has_tool_call": True,
            "tool_results": [
                {
                    "tool_call": {"name": "get_current_time", "parameters": {}},
                    "result": {"time": "12:00"},
                }
            ],
        },
    )
    original_response = '{"tool_calls": [{"name": "get_current_time", "parameters": {}}]}'

    # Act
    result = Invoke(
        messages=[{"role": "user", "content": "what time is it?"}],
        original_response=original_response,
        tool_execution_map=_execution_map(),
    )

    # Assert
    assert "Tool Results:" in result
    assert "Name: get_current_time" in result
    _, kwargs = mock_executor.call_args
    assert kwargs["messages"][-1] == {"role": "assistant", "content": original_response}
    assert kwargs["tool_execution_map"] == _execution_map()


def test_invoke_with_validation_returns_error_message_on_tool_failure(mocker):
    """
    Tests that with validate_execution=True, tool results containing errors
    surface as a 'Tool execution failed' message string (the
    MCPToolExecutionError is caught and formatted by Invoke).
    """
    # Arrange
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration.mcp_tool_executor.Invoke",
        return_value={
            "response": "raw",
            "has_tool_call": True,
            "tool_results": [
                {
                    "tool_call": {"name": "get_current_time", "parameters": {}},
                    "result": {"error": "boom", "status": "error"},
                }
            ],
        },
    )

    # Act
    result = Invoke(
        messages=[{"role": "user", "content": "hi"}],
        original_response="resp",
        tool_execution_map=_execution_map(),
        validate_execution=True,
    )

    # Assert
    assert result.startswith("Tool execution failed")
    assert "boom" in result


def test_invoke_returns_error_string_when_tool_call_detected_with_empty_map(mocker):
    """
    Tests that when the executor reports a detected tool call but the handler's
    tool_execution_map is empty, execute_tools returns the integration error
    string (a resilient string return, not a raised exception).
    """
    # Arrange: Executor says a tool call was detected but could not execute it.
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration.mcp_tool_executor.Invoke",
        return_value={
            "response": "raw",
            "has_tool_call": True,
            "tool_results": [],
            "error": "Tool calls found, but no tool_execution_map provided to execute them.",
            "status": "execution_error",
        },
    )

    # Act
    result = Invoke(
        messages=[{"role": "user", "content": "what time is it?"}],
        original_response='{"tool_calls": [{"name": "get_current_time", "parameters": {}}]}',
        tool_execution_map={},
    )

    # Assert: The exact error string is returned, not raised.
    assert result == (
        "MCP Integration Error: Tool calls were detected, but the tool "
        "execution map is empty. Cannot execute tools."
    )


def test_invoke_raises_configuration_error_for_missing_map():
    """
    Tests that a missing tool_execution_map raises MCPConfigurationError
    (propagated for run_dynamic_module to report).
    """
    with pytest.raises(MCPConfigurationError):
        Invoke(messages=[{"role": "user", "content": "hi"}], original_response="x")


def test_invoke_parses_stringified_inputs(mocker):
    """
    Tests that Invoke accepts the JSON-string forms of messages and
    tool_execution_map produced by workflow Jinja2 templating.
    """
    # Arrange
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration.mcp_tool_executor.Invoke",
        return_value={"response": "ok", "has_tool_call": False},
    )

    # Act
    result = Invoke(
        json.dumps([{"role": "user", "content": "hi"}]),
        original_response="ok",
        tool_execution_map=json.dumps(_execution_map()),
    )

    # Assert
    assert result == "ok"
