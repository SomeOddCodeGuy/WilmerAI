# Tests/api/test_workflow_gateway.py

import pytest

from Middleware.api.app import app
from Middleware.api.workflow_gateway import (
    handle_user_prompt,
    _sanitize_log_data,
    check_openwebui_tool_request
)

# Define the pattern here for reuse
TOOL_PATTERN = "Your task is to choose and return the correct tool(s) from the list of available tools based on the query"


@pytest.fixture
def mock_dependencies(mocker):
    """Mocks all external dependencies for workflow_gateway."""
    # Mock config utils and CAPTURE the mock object
    mock_get_is_active = mocker.patch('Middleware.api.workflow_gateway.get_custom_workflow_is_active')
    mock_get_name = mocker.patch('Middleware.api.workflow_gateway.get_active_custom_workflow_name')

    # Mock utility functions
    mocker.patch('Middleware.api.workflow_gateway.extract_discussion_id', return_value='test-discussion-id')
    mocker.patch('Middleware.api.workflow_gateway.replace_brackets_in_list', side_effect=lambda x: x)  # Passthrough

    # Mock services and managers
    mock_prompt_cat_service = mocker.patch('Middleware.api.workflow_gateway.PromptCategorizationService')
    mock_workflow_manager = mocker.patch('Middleware.api.workflow_gateway.WorkflowManager')

    # Return the captured MOCKS, not the original functions
    return {
        'get_custom_workflow_is_active': mock_get_is_active,
        'get_active_custom_workflow_name': mock_get_name,
        'PromptCategorizationService': mock_prompt_cat_service,
        'WorkflowManager': mock_workflow_manager
    }


# --- Tests for handle_user_prompt ---

def test_handle_user_prompt_uses_categorization_when_custom_workflow_is_inactive(mock_dependencies):
    """
    Verify PromptCategorizationService is used when custom workflow override is off.
    """
    # Arrange
    mock_dependencies['get_custom_workflow_is_active'].return_value = False
    mock_service_instance = mock_dependencies['PromptCategorizationService'].return_value
    mock_service_instance.get_prompt_category.return_value = "categorized_response"

    request_id = "test-request-id-123"
    messages = [{"role": "user", "content": "Hello"}]

    # Act
    result = handle_user_prompt(request_id, messages, stream=False)

    # Assert
    mock_dependencies['PromptCategorizationService'].assert_called_once()
    mock_service_instance.get_prompt_category.assert_called_once()
    # Check that correct arguments were passed
    call_args = mock_service_instance.get_prompt_category.call_args[1]
    assert call_args['messages'] == messages
    assert call_args['stream'] is False
    assert call_args['request_id'] == request_id
    assert call_args['discussion_id'] == 'test-discussion-id'
    assert result == "categorized_response"
    mock_dependencies['WorkflowManager'].run_custom_workflow.assert_not_called()


def test_handle_user_prompt_uses_custom_workflow_when_active(mock_dependencies):
    """
    Verify WorkflowManager.run_custom_workflow is called when the override is active.
    """
    # Arrange
    mock_dependencies['get_custom_workflow_is_active'].return_value = True
    mock_dependencies['get_active_custom_workflow_name'].return_value = 'TestCustomWorkflow'
    mock_dependencies['WorkflowManager'].run_custom_workflow.return_value = "custom_workflow_response"
    request_id = "test-request-id-456"
    messages = [{"role": "user", "content": "Hi there"}]

    # Act
    result = handle_user_prompt(request_id, messages, stream=True)

    # Assert
    mock_dependencies['WorkflowManager'].run_custom_workflow.assert_called_once()
    # Check that correct arguments were passed
    call_args = mock_dependencies['WorkflowManager'].run_custom_workflow.call_args[1]
    assert call_args['workflow_name'] == 'TestCustomWorkflow'
    assert call_args['request_id'] == request_id
    assert call_args['messages'] == messages
    assert call_args['is_streaming'] is True
    assert call_args['discussion_id'] == 'test-discussion-id'
    assert result == "custom_workflow_response"
    mock_dependencies['PromptCategorizationService'].assert_not_called()


# --- Tests for _sanitize_log_data ---

def test_sanitize_log_data_short_string():
    """Test that short strings are unchanged."""
    data = "This is a short string."
    assert _sanitize_log_data(data) == data


def test_sanitize_log_data_long_string():
    """Test that long non-image strings are truncated correctly."""
    long_string = "a" * 1001
    sanitized = _sanitize_log_data(long_string)
    assert "..." in sanitized
    assert len(sanitized) < len(long_string)


def test_sanitize_log_data_base64_image():
    """Test that base64 image strings are truncated while preserving the prefix."""
    prefix = "data:image/png;base64,"
    data = prefix + "a" * 500
    sanitized = _sanitize_log_data(data)
    assert sanitized.startswith(prefix)
    assert "..." in sanitized
    assert sanitized.endswith("a" * 50)


def test_sanitize_log_data_nested_structure():
    """Test that truncation works in nested dictionaries and lists."""
    data = {
        "key1": "short value",
        "key2": ["a" * 1001, "b" * 20],
        "nested": {
            "image": "data:image/jpeg;base64," + "c" * 300
        }
    }
    sanitized = _sanitize_log_data(data)
    assert sanitized["key1"] == "short value"
    assert "..." in sanitized["key2"][0]
    assert sanitized["key2"][1] == "b" * 20
    assert sanitized["nested"]["image"].startswith("data:image/jpeg;base64,")
    assert "..." in sanitized["nested"]["image"]


# --- Tests for check_openwebui_tool_request ---

def test_check_openwebui_tool_request_returns_none_when_config_disabled(mocker):
    """
    When interceptOpenWebUIToolRequests is False (default), tool requests pass through.
    """
    mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_intercept_openwebui_tool_requests',
        return_value=False
    )
    payload = {"messages": [{"role": "system", "content": TOOL_PATTERN}]}
    result = check_openwebui_tool_request(payload, 'openaichatcompletion')
    assert result is None


def test_check_openwebui_tool_request_returns_none_when_no_match(mocker):
    """
    Even when interception is enabled, non-tool requests pass through.
    """
    mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_intercept_openwebui_tool_requests',
        return_value=True
    )
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    result = check_openwebui_tool_request(payload, 'openaichatcompletion')
    assert result is None


def test_check_openwebui_tool_request_intercepts_openai(client, mocker):
    """
    When interception is enabled and a tool pattern is detected, returns an OpenAI response.
    """
    mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_intercept_openwebui_tool_requests',
        return_value=True
    )
    mock_builder = mocker.patch('Middleware.api.workflow_gateway.response_builder')
    mock_builder.build_openai_tool_call_response.return_value = {"status": "openai_tool_called"}
    payload = {"messages": [{"role": "system", "content": TOOL_PATTERN}]}

    with app.test_request_context():
        result = check_openwebui_tool_request(payload, 'openaichatcompletion')

    assert result is not None
    mock_builder.build_openai_tool_call_response.assert_called_once()


def test_check_openwebui_tool_request_intercepts_ollama(client, mocker):
    """
    When interception is enabled and a tool pattern is detected, returns an Ollama response.
    """
    mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_intercept_openwebui_tool_requests',
        return_value=True
    )
    mock_builder = mocker.patch('Middleware.api.workflow_gateway.response_builder')
    mock_builder.build_ollama_tool_call_response.return_value = {"status": "ollama_tool_called"}
    mocker.patch('Middleware.api.workflow_gateway.api_helpers.get_model_name', return_value='test-model')
    payload = {
        "model": "test-model-from-request",
        "messages": [{"role": "system", "content": TOOL_PATTERN}]
    }

    with app.test_request_context():
        result = check_openwebui_tool_request(payload, 'ollamaapichat')

    assert result is not None
    mock_builder.build_ollama_tool_call_response.assert_called_once_with("test-model-from-request")
