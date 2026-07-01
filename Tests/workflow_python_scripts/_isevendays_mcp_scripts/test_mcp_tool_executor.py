# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_mcp_tool_executor.py

import json

import pytest
import requests

from Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor import (
    Invoke,
    _build_tool_url,
    _perform_http_request,
    _prepare_request_params,
    execute_tool_call,
    extract_tool_calls,
    validate_tool_call_format,
)
from Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_workflow_integration import MCPConfigurationError

MCPO_URL = "http://localhost:8889"


def _time_execution_map():
    return {
        "get_current_time": {
            "service": "time",
            "path": "/current",
            "method": "post",
            "request_body_schema": {"$ref": "#/components/schemas/TimeForm"},
            "openapi_params": [],
        }
    }


# ---------------------------------------------------------------------------
# extract_tool_calls (tool-call detection)
# ---------------------------------------------------------------------------


def test_extract_tool_calls_from_plain_json():
    """
    Tests that a bare JSON object with a tool_calls array is detected.
    """
    text = '{"tool_calls": [{"name": "get_current_time", "parameters": {"timezone": "UTC"}}]}'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_current_time"
    assert calls[0]["parameters"] == {"timezone": "UTC"}


def test_extract_tool_calls_from_markdown_fence():
    """
    Tests that a tool call wrapped in a ```json fence is extracted.
    """
    text = (
        "Sure, calling the tool now:\n"
        "```json\n"
        '{"tool_calls": [{"name": "get_current_time", "parameters": {}}]}\n'
        "```"
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_current_time"


def test_extract_tool_calls_embedded_in_surrounding_text():
    """
    Tests that a tool-call JSON object embedded in conversational text
    (no fence) is found by brace matching.
    """
    text = (
        "I will check the time.\n"
        '{"tool_calls": [{"name": "get_current_time", "parameters": {"timezone": "UTC"}}]}\n'
        "Done."
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1


def test_extract_tool_calls_restores_escaped_braces():
    """
    Tests that braces escaped to Wilmer's sentinel tokens
    (__WILMER_L_CURLY__ / __WILMER_R_CURLY__) are restored before parsing.
    """
    valid = '{"tool_calls": [{"name": "get_current_time", "parameters": {}}]}'
    text = valid.replace("{", "__WILMER_L_CURLY__").replace("}", "__WILMER_R_CURLY__")
    # The brace restoration turns this back into valid JSON braces.
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_current_time"


def test_extract_tool_calls_empty_list_and_plain_text_return_no_calls():
    """
    Tests that an explicit empty tool_calls array and ordinary prose both
    yield no tool calls.
    """
    assert extract_tool_calls('{"tool_calls": []}') == []
    assert extract_tool_calls("The current time in UTC is 12:00.") == []


def test_extract_tool_calls_skips_unsubstituted_template_variables():
    """
    Tests that text still containing {{variable}} placeholders is skipped
    entirely (workflow substitution failed upstream).
    """
    text = '{"tool_calls": [{"name": "{{toolName}}", "parameters": {}}]}'
    assert extract_tool_calls(text) == []


def test_extract_tool_calls_ignores_invalid_call_objects():
    """
    Tests that tool_calls entries missing 'name' or 'parameters' are dropped.
    """
    text = '{"tool_calls": [{"name": "no_params"}, {"parameters": {}}]}'
    assert extract_tool_calls(text) == []


# ---------------------------------------------------------------------------
# Invoke (top-level detection + execution flow)
# ---------------------------------------------------------------------------


def test_invoke_requires_tool_execution_map():
    """
    Tests that Invoke raises MCPConfigurationError when no
    tool_execution_map is provided.
    """
    with pytest.raises(MCPConfigurationError):
        Invoke(messages=[{"role": "assistant", "content": "hi"}])


def test_invoke_no_assistant_message_returns_empty():
    """
    Tests that a conversation without an assistant message yields an empty
    response with no tool call flag.
    """
    result = Invoke(
        messages=[{"role": "user", "content": "hello"}],
        mcpo_url=MCPO_URL,
        tool_execution_map=_time_execution_map(),
    )
    assert result == {"response": "", "has_tool_call": False}


def test_invoke_no_tool_call_returns_assistant_message():
    """
    Tests that an assistant message without a tool call is passed through.
    """
    result = Invoke(
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        mcpo_url=MCPO_URL,
        tool_execution_map=_time_execution_map(),
    )
    assert result == {"response": "Hi there!", "has_tool_call": False}


def test_invoke_executes_detected_tool_call(mocker):
    """
    Tests the full happy path: a tool call in the last assistant message is
    detected and executed via an HTTP request to the MCPO server (mocked).
    """
    # Arrange: Mock the HTTP layer to return a tool result.
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = {"time": "2024-01-01T00:00:00Z"}
    mock_request = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor.requests.request",
        return_value=mock_response,
    )
    assistant_content = (
        '{"tool_calls": [{"name": "get_current_time", "parameters": {"timezone": "UTC"}}]}'
    )

    # Act
    result = Invoke(
        messages=[
            {"role": "user", "content": "what time is it?"},
            {"role": "assistant", "content": assistant_content},
        ],
        mcpo_url=MCPO_URL,
        tool_execution_map=_time_execution_map(),
    )

    # Assert: Tool call detected, executed against the right URL, result formatted.
    assert result["has_tool_call"] is True
    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["result"] == {"time": "2024-01-01T00:00:00Z"}
    assert result["tool_results"][0]["tool_call"]["name"] == "get_current_time"
    _, kwargs = mock_request.call_args
    assert kwargs["url"] == f"{MCPO_URL}/time/current"
    assert kwargs["method"] == "post"
    assert kwargs["json"] == {"timezone": "UTC"}


# ---------------------------------------------------------------------------
# execute_tool_call (execution-detail lookup + error paths)
# ---------------------------------------------------------------------------


def test_execute_tool_call_unknown_operation_id_returns_error():
    """
    Tests that a tool call whose operationId is not in the execution map
    returns a formatted error response.
    """
    result = execute_tool_call(
        {"name": "nonexistent", "parameters": {}}, MCPO_URL, _time_execution_map()
    )
    assert result["status"] == "error"
    assert "nonexistent" in result["error"]


def test_execute_tool_call_missing_path_parameter_returns_error():
    """
    Tests that a path template with a placeholder not satisfied by the
    call's parameters yields an error instead of a malformed request.
    """
    execution_map = {
        "get_user": {
            "service": "users",
            "path": "/users/{userId}",
            "method": "get",
            "openapi_params": [
                {"name": "userId", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
        }
    }
    result = execute_tool_call({"name": "get_user", "parameters": {}}, MCPO_URL, execution_map)
    assert result["status"] == "error"
    assert "userId" in result["error"]


def test_execute_tool_call_substitutes_path_parameters(mocker):
    """
    Tests that path parameters are substituted into the URL template using
    the schema-defined names.
    """
    # Arrange
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_request = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor.requests.request",
        return_value=mock_response,
    )
    execution_map = {
        "get_user": {
            "service": "users",
            "path": "/users/{userId}",
            "method": "get",
            "openapi_params": [
                {"name": "userId", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
        }
    }

    # Act
    result = execute_tool_call(
        {"name": "get_user", "parameters": {"userId": "42"}}, MCPO_URL, execution_map
    )

    # Assert
    assert result == {"ok": True}
    _, kwargs = mock_request.call_args
    assert kwargs["url"] == f"{MCPO_URL}/users/users/42"


# ---------------------------------------------------------------------------
# Native MCP SDK execution path (transport == "mcp")
# ---------------------------------------------------------------------------


def _native_execution_map():
    return {
        "get_current_time": {
            "service": "time-server",
            "transport": "mcp",
            "llm_schema": {
                "type": "function",
                "name": "get_current_time",
                "description": "Get the time",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    }


def test_execute_tool_call_routes_native_entries_through_sdk(mocker):
    """
    Tests that execution-map entries tagged transport="mcp" are executed via
    MCPClient.call_tool against the registry server, not the MCPO HTTP path, and
    that a JSON string result is parsed back to a dict.
    """
    # Arrange
    mock_call = mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.MCPClient.call_tool",
        return_value='{"time": "12:00"}',
    )
    mock_request = mocker.patch("Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor.requests.request")

    # Act
    result = execute_tool_call(
        {"name": "get_current_time", "parameters": {"timezone": "UTC"}},
        MCPO_URL,
        _native_execution_map(),
    )

    # Assert
    assert result == {"time": "12:00"}
    mock_call.assert_called_once_with("time-server", "get_current_time", {"timezone": "UTC"}, timeout=900)
    mock_request.assert_not_called()


def test_execute_tool_call_native_wraps_plain_text_result(mocker):
    """
    Tests that a non-JSON flattened SDK result is wrapped the same way the
    legacy path wraps raw text responses.
    """
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.MCPClient.call_tool",
        return_value="It is noon.",
    )
    result = execute_tool_call(
        {"name": "get_current_time", "parameters": {}}, MCPO_URL, _native_execution_map()
    )
    assert result == {"status": "success_raw_text", "response_text": "It is noon."}


def test_execute_tool_call_native_failure_returns_error_dict(mocker):
    """
    Tests that an MCPToolCallError from the SDK surfaces as a formatted
    error result rather than an exception.
    """
    from Middleware.workflows.tools.mcp_client_tool import MCPToolCallError

    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.MCPClient.call_tool",
        side_effect=MCPToolCallError("server unreachable"),
    )
    result = execute_tool_call(
        {"name": "get_current_time", "parameters": {}}, MCPO_URL, _native_execution_map()
    )
    assert result["status"] == "error"
    assert "server unreachable" in result["error"]


# ---------------------------------------------------------------------------
# _perform_http_request (HTTP layer, mocked requests)
# ---------------------------------------------------------------------------


def test_perform_http_request_returns_raw_text_for_non_json(mocker):
    """
    Tests that a non-JSON tool response is wrapped in a raw-text result
    instead of failing.
    """
    mock_response = mocker.MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
    mock_response.text = "plain text result"
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor.requests.request",
        return_value=mock_response,
    )
    result = _perform_http_request("get", f"{MCPO_URL}/time/current", {}, None)
    assert result == {"status": "success_raw_text", "response_text": "plain text result"}


def test_perform_http_request_timeout_returns_error(mocker):
    """
    Tests that a request timeout is converted into a formatted error result.
    """
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor.requests.request",
        side_effect=requests.exceptions.Timeout,
    )
    result = _perform_http_request("post", f"{MCPO_URL}/time/current", {}, {})
    assert result["status"] == "error"
    assert "timed out" in result["error"]


def test_perform_http_request_http_error_returns_error(mocker):
    """
    Tests that an HTTP error status is converted into a formatted error result.
    """
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_tool_executor.requests.request",
        return_value=mock_response,
    )
    result = _perform_http_request("post", f"{MCPO_URL}/time/current", {}, {})
    assert result["status"] == "error"
    assert "Tool execution failed" in result["error"]


def test_perform_http_request_rejects_unsupported_method():
    """
    Tests that an unsupported HTTP method is rejected without any request.
    """
    result = _perform_http_request("teapot", f"{MCPO_URL}/x", {}, None)
    assert result["status"] == "error"
    assert "Unsupported HTTP method" in result["error"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_build_tool_url_normalizes_slashes():
    assert _build_tool_url("http://host:1/", "/svc", "path") == "http://host:1/svc/path"
    assert _build_tool_url("http://host:1", "svc", "/path") == "http://host:1/svc/path"
    assert _build_tool_url("http://host:1", "", "/path") == "http://host:1/path"


def test_prepare_request_params_routes_by_location():
    """
    Tests that parameters are routed to query/path/body buckets based on the
    OpenAPI parameter definitions, with normalized name matching.
    """
    # Arrange: Schema defines a query param and a path param; an extra LLM
    # param should fall through to the request body.
    execution_details = {
        "openapi_params": [
            {"name": "user_id", "in": "path", "schema": {"type": "string"}},
            {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
        ],
        "request_body_schema": {"type": "object"},
    }
    parameters = {"userId": "42", "verbose": True, "note": "hi"}

    # Act
    query_params, body_params, path_params = _prepare_request_params(
        parameters, execution_details
    )

    # Assert: 'userId' matched 'user_id' via normalization and used the schema name.
    assert path_params == {"user_id": "42"}
    assert query_params == {"verbose": True}
    assert body_params == {"note": "hi"}


def test_validate_tool_call_format():
    assert validate_tool_call_format({"name": "t", "parameters": {}}) is True
    assert validate_tool_call_format({"name": "t"}) is False
    assert validate_tool_call_format({"parameters": {}}) is False
    assert validate_tool_call_format({"name": "", "parameters": {}}) is False
    assert validate_tool_call_format({"name": "t", "parameters": []}) is False
    assert validate_tool_call_format("not a dict") is False
