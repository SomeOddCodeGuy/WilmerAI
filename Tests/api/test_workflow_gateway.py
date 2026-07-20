# Tests/api/test_workflow_gateway.py

import os

import pytest

from Middleware.api.app import app
from Middleware.api.workflow_gateway import (
    handle_user_prompt,
    _sanitize_log_data,
    check_openwebui_tool_request,
    strip_machinery_turns,
    collapse_duplicate_tool_calls
)

# Define the pattern here for reuse
TOOL_PATTERN = "Your task is to choose and return the correct tool(s) from the list of available tools based on the query"


@pytest.fixture
def mock_dependencies(mocker):
    """Mocks all external dependencies for workflow_gateway."""
    # Mock config utils and CAPTURE the mock object
    mock_get_is_active = mocker.patch('Middleware.api.workflow_gateway.get_custom_workflow_is_active')
    mock_get_name = mocker.patch('Middleware.api.workflow_gateway.get_active_custom_workflow_name')

    # Default to no workflow override so the standard-path tests are immune to
    # thread-local override state leaked by other tests.
    mock_get_override = mocker.patch(
        'Middleware.api.workflow_gateway.api_helpers.get_active_workflow_override',
        return_value=None
    )
    mock_get_shared_folder = mocker.patch(
        'Middleware.api.workflow_gateway.get_shared_workflows_folder',
        return_value=os.path.join('/configs', 'Workflows', '_shared')
    )

    # Mock utility functions
    mocker.patch('Middleware.api.workflow_gateway.extract_discussion_id', return_value='test-discussion-id')
    mocker.patch('Middleware.api.workflow_gateway.replace_brackets_in_list', side_effect=lambda x: x)  # Passthrough

    # Machinery passes are gated on livenessToolCall; default to unset (off)
    mock_liveness = mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_liveness_tool_call',
        return_value=None
    )

    # Mock services and managers
    mock_prompt_cat_service = mocker.patch('Middleware.api.workflow_gateway.PromptCategorizationService')
    mock_workflow_manager = mocker.patch('Middleware.api.workflow_gateway.WorkflowManager')

    # Return the captured MOCKS, not the original functions
    return {
        'get_custom_workflow_is_active': mock_get_is_active,
        'get_active_custom_workflow_name': mock_get_name,
        'get_active_workflow_override': mock_get_override,
        'get_shared_workflows_folder': mock_get_shared_folder,
        'PromptCategorizationService': mock_prompt_cat_service,
        'WorkflowManager': mock_workflow_manager,
        'get_liveness_tool_call': mock_liveness
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
    tools = [{"type": "function", "function": {"name": "lookup"}}]

    # Act
    result = handle_user_prompt(request_id, messages, stream=False, api_key="key-abc",
                                tools=tools, tool_choice="none")

    # Assert
    mock_dependencies['PromptCategorizationService'].assert_called_once()
    mock_service_instance.get_prompt_category.assert_called_once()
    # Check that correct arguments were passed
    call_args = mock_service_instance.get_prompt_category.call_args[1]
    assert call_args['messages'] == messages
    assert call_args['stream'] is False
    assert call_args['request_id'] == request_id
    assert call_args['discussion_id'] == 'test-discussion-id'
    assert call_args['api_key'] == "key-abc"
    assert call_args['tools'] == tools
    assert call_args['tool_choice'] == "none"
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
    tools = [{"type": "function", "function": {"name": "search"}}]

    # Act
    result = handle_user_prompt(request_id, messages, stream=True, api_key="key-def",
                                tools=tools, tool_choice="auto")

    # Assert
    mock_dependencies['WorkflowManager'].run_custom_workflow.assert_called_once()
    # Check that correct arguments were passed
    call_args = mock_dependencies['WorkflowManager'].run_custom_workflow.call_args[1]
    assert call_args['workflow_name'] == 'TestCustomWorkflow'
    assert call_args['request_id'] == request_id
    assert call_args['messages'] == messages
    assert call_args['is_streaming'] is True
    assert call_args['discussion_id'] == 'test-discussion-id'
    assert call_args['api_key'] == "key-def"
    assert call_args['tools'] == tools
    assert call_args['tool_choice'] == "auto"
    assert result == "custom_workflow_response"
    mock_dependencies['PromptCategorizationService'].assert_not_called()


def test_handle_user_prompt_workflow_override_runs_default_workflow(mock_dependencies):
    """
    Verify the priority-1 routing path: an active workflow folder override from
    the API model field runs _DefaultWorkflow from _shared/<folder> with the
    folder passed as workflow_user_folder_override.
    """
    # Arrange
    mock_dependencies['get_active_workflow_override'].return_value = 'opencode'
    mock_dependencies['WorkflowManager'].run_custom_workflow.return_value = "override_response"

    request_id = "test-request-id-789"
    messages = [{"role": "user", "content": "Hello"}]
    tools = [{"type": "function", "function": {"name": "write_file"}}]

    # Act
    result = handle_user_prompt(request_id, messages, stream=True, api_key="key-123",
                                tools=tools, tool_choice="auto")

    # Assert: exact contract of the override branch
    expected_folder = os.path.join('/configs', 'Workflows', '_shared', 'opencode')
    mock_dependencies['WorkflowManager'].run_custom_workflow.assert_called_once_with(
        workflow_name="_DefaultWorkflow",
        request_id=request_id,
        discussion_id='test-discussion-id',
        messages=messages,
        is_streaming=True,
        workflow_user_folder_override=expected_folder,
        api_key="key-123",
        tools=tools,
        tool_choice="auto"
    )
    assert result == "override_response"


def test_handle_user_prompt_workflow_override_takes_priority_over_config(mock_dependencies):
    """
    Verify the override branch returns before the custom-workflow config or
    categorization paths are even consulted.
    """
    # Arrange: config says a custom workflow is active, but the override wins
    mock_dependencies['get_active_workflow_override'].return_value = 'some_folder'
    mock_dependencies['get_custom_workflow_is_active'].return_value = True
    mock_dependencies['get_active_custom_workflow_name'].return_value = 'ShouldNotRun'
    mock_dependencies['WorkflowManager'].run_custom_workflow.return_value = "override_response"

    # Act
    result = handle_user_prompt("req-1", [{"role": "user", "content": "Hi"}], stream=False)

    # Assert
    assert result == "override_response"
    call_args = mock_dependencies['WorkflowManager'].run_custom_workflow.call_args[1]
    assert call_args['workflow_name'] == "_DefaultWorkflow"
    mock_dependencies['get_custom_workflow_is_active'].assert_not_called()
    mock_dependencies['get_active_custom_workflow_name'].assert_not_called()
    mock_dependencies['PromptCategorizationService'].assert_not_called()


def test_handle_user_prompt_routes_sanitized_messages_not_raw(mock_dependencies, mocker):
    """
    Every routing path must forward the output of replace_brackets_in_list,
    not the raw ingested collection. (The fixture's passthrough mock cannot
    distinguish the two, so this test substitutes a distinct sentinel list.)
    """
    sanitized = [{"role": "user", "content": "sanitized-marker"}]
    mocker.patch('Middleware.api.workflow_gateway.replace_brackets_in_list',
                 return_value=sanitized)
    raw = [{"role": "user", "content": "{{raw}}"}]

    # Path 1: workflow folder override
    mock_dependencies['get_active_workflow_override'].return_value = 'folder'
    handle_user_prompt("req-a", raw, stream=False)
    assert mock_dependencies['WorkflowManager'].run_custom_workflow.call_args[1]['messages'] is sanitized

    # Path 2: custom workflow from config
    mock_dependencies['get_active_workflow_override'].return_value = None
    mock_dependencies['get_custom_workflow_is_active'].return_value = True
    mock_dependencies['get_active_custom_workflow_name'].return_value = 'AnyWorkflow'
    handle_user_prompt("req-b", raw, stream=False)
    assert mock_dependencies['WorkflowManager'].run_custom_workflow.call_args[1]['messages'] is sanitized

    # Path 3: categorization routing
    mock_dependencies['get_custom_workflow_is_active'].return_value = False
    handle_user_prompt("req-c", raw, stream=False)
    mock_service_instance = mock_dependencies['PromptCategorizationService'].return_value
    assert mock_service_instance.get_prompt_category.call_args[1]['messages'] is sanitized


# --- Tests for _sanitize_log_data ---

def test_sanitize_log_data_short_string():
    """Test that short strings are unchanged."""
    data = "This is a short string."
    assert _sanitize_log_data(data) == data


def test_sanitize_log_data_long_string():
    """Test that long non-image strings are truncated correctly."""
    # Length 1100 > max_len * 5 (1000); head/tail kept = head_tail_len * 2 (100)
    long_string = "a" * 100 + "b" * 900 + "c" * 100
    sanitized = _sanitize_log_data(long_string)
    assert sanitized == "a" * 100 + "...[truncated]..." + "c" * 100


def test_sanitize_log_data_boundary_length_passes_through():
    """Strings exactly at max_len * 5 are not truncated (truncation is strictly greater-than)."""
    boundary_string = "a" * 1000  # max_len (200) * 5
    assert _sanitize_log_data(boundary_string) == boundary_string


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
    assert result.get_json() == {"status": "openai_tool_called"}
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
    assert result.get_json() == {"status": "ollama_tool_called"}
    mock_builder.build_ollama_tool_call_response.assert_called_once_with("test-model-from-request")


def test_check_openwebui_tool_request_ollama_without_model_falls_back(client, mocker):
    """
    When the Ollama payload has no 'model' key, the model name comes from
    api_helpers.get_model_name().
    """
    mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_intercept_openwebui_tool_requests',
        return_value=True
    )
    mock_builder = mocker.patch('Middleware.api.workflow_gateway.response_builder')
    mock_builder.build_ollama_tool_call_response.return_value = {"status": "ollama_tool_called"}
    mocker.patch('Middleware.api.workflow_gateway.api_helpers.get_model_name', return_value='fallback-model')
    payload = {"messages": [{"role": "system", "content": TOOL_PATTERN}]}

    with app.test_request_context():
        result = check_openwebui_tool_request(payload, 'ollamaapichat')

    assert result is not None
    mock_builder.build_ollama_tool_call_response.assert_called_once_with("fallback-model")


def test_check_openwebui_tool_request_unknown_api_type_returns_none(mocker):
    """
    A matched tool request on an api_type without a tool-call response
    (e.g. 'ollamagenerate') is logged and passed through as None.
    """
    mocker.patch(
        'Middleware.api.workflow_gateway.config_utils.get_intercept_openwebui_tool_requests',
        return_value=True
    )
    mock_builder = mocker.patch('Middleware.api.workflow_gateway.response_builder')
    mocker.patch('Middleware.api.workflow_gateway.api_helpers.get_model_name', return_value='fallback-model')
    payload = {"messages": [{"role": "system", "content": TOOL_PATTERN}]}

    result = check_openwebui_tool_request(payload, 'ollamagenerate')

    assert result is None
    mock_builder.build_openai_tool_call_response.assert_not_called()
    mock_builder.build_ollama_tool_call_response.assert_not_called()


# --- Tests for strip_machinery_turns ---

def _machinery_call(call_id="wilmer_liveness_ab12cd34",
                    command="echo '[Wilmer] No tool call in the last reply; auto-continuing.'"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "bash", "arguments": f'{{"command": "{command}"}}'},
    }


def _genuine_call(call_id="call_real_1", command="ls -la /workspace"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "bash", "arguments": f'{{"command": "{command}"}}'},
    }


def test_strip_removes_genuine_liveness_injection_and_paired_result():
    """An injected turn (wilmer_liveness_ id) and its tool result are dropped."""
    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34",
         "content": "[Wilmer] No tool call in the last reply; auto-continuing."},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [
        {"role": "user", "content": "Review the repo."},
        {"role": "user", "content": "next"},
    ]


def test_strip_removes_model_imitation_by_marker():
    """A model-emitted imitation (frontend id, [Wilmer] in arguments) is dropped too."""
    imitation = _machinery_call(call_id="call_pi_generated_77")
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [imitation]},
        {"role": "tool", "tool_call_id": "call_pi_generated_77",
         "content": "[Wilmer] No tool call in the last reply; auto-continuing."},
        {"role": "user", "content": "continue"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [{"role": "user", "content": "continue"}]


def test_strip_matches_marker_with_old_wording():
    """The marker match keys on [Wilmer], not exact wording, so stale imitations are caught."""
    old_wording = _machinery_call(
        call_id="call_pi_9",
        command="echo '[Wilmer] Task in progress; continuing autonomously.'")
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [old_wording]},
        {"role": "tool", "tool_call_id": "call_pi_9", "content": "[Wilmer] Task in progress"},
        {"role": "user", "content": "continue"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [{"role": "user", "content": "continue"}]


def test_strip_leaves_genuine_turns_untouched():
    """Normal conversation, including real tool calls and results, passes through identically."""
    messages = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "", "tool_calls": [_genuine_call()]},
        {"role": "tool", "tool_call_id": "call_real_1", "content": "total 128\ndrwxr-xr-x ..."},
        {"role": "assistant", "content": "The listing shows 13 folders."},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_mixed_turn_keeps_genuine_call_drops_machinery():
    """A buried turn holding one genuine and one machinery call keeps only the genuine
    call; the machinery call's paired result is dropped by id, the genuine result kept."""
    messages = [
        {"role": "assistant", "content": "",
         "tool_calls": [_genuine_call(), _machinery_call(call_id="call_pi_echo_3")]},
        {"role": "tool", "tool_call_id": "call_real_1", "content": "total 128"},
        {"role": "tool", "tool_call_id": "call_pi_echo_3", "content": "[Wilmer] ..."},
        {"role": "user", "content": "continue"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [
        {"role": "assistant", "content": "", "tool_calls": [_genuine_call()]},
        {"role": "tool", "tool_call_id": "call_real_1", "content": "total 128"},
        {"role": "user", "content": "continue"},
    ]


def test_strip_keeps_assistant_content_when_dropping_its_only_call():
    """A buried machinery turn with real text content keeps the text, loses the
    tool_calls key."""
    messages = [
        {"role": "assistant", "content": "Continuing with item 2.",
         "tool_calls": [_machinery_call(call_id="call_pi_5")]},
        {"role": "tool", "tool_call_id": "call_pi_5", "content": "[Wilmer] ..."},
        {"role": "user", "content": "continue"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [
        {"role": "assistant", "content": "Continuing with item 2."},
        {"role": "user", "content": "continue"},
    ]


def test_strip_adjacent_idless_result_after_all_machinery_turn():
    """A role:tool result with no tool_call_id right after an all-machinery turn is dropped."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "content": "[Wilmer] No tool call in the last reply; auto-continuing."},
        {"role": "user", "content": "continue"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [{"role": "user", "content": "continue"}]


def test_strip_idless_result_not_dropped_without_adjacent_machinery_turn():
    """An id-less tool result following a genuine turn is retained."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [_genuine_call()]},
        {"role": "tool", "content": "total 128"},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_arguments_as_dict_marker_detected():
    """Arguments supplied as a dict (not a JSON string) are still checked for the marker."""
    call = {
        "id": "call_pi_dict",
        "type": "function",
        "function": {"name": "bash",
                     "arguments": {"command": "echo '[Wilmer] auto-continuing.'"}},
    }
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "call_pi_dict", "content": "[Wilmer] auto-continuing."},
        {"role": "user", "content": "continue"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [{"role": "user", "content": "continue"}]


def test_strip_tolerates_malformed_tool_calls():
    """Non-dict entries, missing function blocks, and odd argument types never raise
    and are treated as genuine (kept)."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": ["not-a-dict"]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": 42}]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "x", "function": "nope"}]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "y", "function": {"name": "bash", "arguments": 7}}]},
        {"role": "user", "content": "hello"},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_tolerates_non_dict_messages():
    """A non-dict entry in the collection passes through and resets adjacency."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        "stray-string-entry",
        {"role": "tool", "content": "[Wilmer] id-less but no longer adjacent"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [
        "stray-string-entry",
        {"role": "tool", "content": "[Wilmer] id-less but no longer adjacent"},
    ]


def test_strip_does_not_mutate_input():
    """The original message list and its dicts are left unmodified."""
    mixed_turn = {"role": "assistant", "content": "",
                  "tool_calls": [_genuine_call(), _machinery_call(call_id="call_pi_m")]}
    messages = [mixed_turn, {"role": "user", "content": "continue"}]

    strip_machinery_turns(messages)

    assert len(mixed_turn["tool_calls"]) == 2


# --- One-shot trailing visibility ---

def test_strip_keeps_trailing_machinery_exchange():
    """The exchange the frontend just executed (injection at the tail) is kept intact
    as one-shot corrective feedback."""
    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "Here is my plan..."},
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34",
         "content": "[Wilmer] No tool call in the last reply; auto-continuing."},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_keeps_trailing_exchange_while_stripping_buried_ones():
    """Only the trailing exchange survives; earlier machinery exchanges are removed."""
    buried = _machinery_call(call_id="wilmer_liveness_old1")
    trailing = _machinery_call(call_id="wilmer_liveness_new2")
    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "", "tool_calls": [buried]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_old1", "content": "[Wilmer] ..."},
        {"role": "assistant", "content": "Still planning..."},
        {"role": "assistant", "content": "", "tool_calls": [trailing]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_new2", "content": "[Wilmer] ..."},
    ]

    result = strip_machinery_turns(messages)

    assert result == [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "Still planning..."},
        {"role": "assistant", "content": "", "tool_calls": [trailing]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_new2", "content": "[Wilmer] ..."},
    ]


def test_strip_trailing_exchange_kept_despite_empty_assistant_filler():
    """An empty assistant filler appended after the exchange (add_missing_assistant)
    does not bury it."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34", "content": "[Wilmer] ..."},
        {"role": "assistant", "content": ""},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_trailing_exchange_kept_despite_assistant_prompt_filler():
    """The "Assistant:" filler appended when chatCompleteAddUserAssistant is
    enabled does not bury the trailing exchange either."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34", "content": "[Wilmer] ..."},
        {"role": "assistant", "content": "Assistant:"},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_trailing_exchange_with_idless_result_kept():
    """A trailing exchange whose tool result carries no id is still kept whole."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "content": "[Wilmer] No tool call in the last reply; auto-continuing."},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_buried_machinery_with_assistant_prompt_filler_content_is_dropped():
    """With chatCompleteAddUserAssistant, the API handler prepends "Assistant: "
    to echoed assistant content before the strip runs, so a buried machinery
    turn arrives with that filler as its only content. It must be dropped
    entirely, not kept as a ghost text-only turn."""
    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "Assistant: ", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34", "content": "[Wilmer] ..."},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages)

    assert result == [
        {"role": "user", "content": "Review the repo."},
        {"role": "user", "content": "next"},
    ]


LIVENESS_CONFIG_NO_MARKER = {"toolName": "noop", "arguments": {"reason": "keepalive"}}


def test_strip_idless_ollama_echo_matched_by_configured_call():
    """Ollama's wire format drops the wilmer_liveness_ id, and this config's
    arguments carry no [Wilmer] marker, so the echo is recognized only by
    name+arguments equality with the livenessToolCall configuration. The echo
    arrives with dict arguments (Ollama shape)."""
    echo = {"function": {"name": "noop", "arguments": {"reason": "keepalive"}}}
    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "", "tool_calls": [echo]},
        {"role": "tool", "content": "keepalive"},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages, LIVENESS_CONFIG_NO_MARKER)

    assert result == [
        {"role": "user", "content": "Review the repo."},
        {"role": "user", "content": "next"},
    ]


def test_strip_idless_echo_with_string_arguments_matched_by_configured_call():
    """The configured-call match also accepts JSON-string arguments (OpenAI
    wire shape re-sent without the original id)."""
    echo = {"function": {"name": "noop", "arguments": '{"reason": "keepalive"}'}}
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [echo]},
        {"role": "tool", "content": "keepalive"},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages, LIVENESS_CONFIG_NO_MARKER)

    assert result == [{"role": "user", "content": "next"}]


def test_strip_configured_call_match_requires_equal_arguments():
    """A genuine call to the same tool with different arguments is NOT machinery."""
    genuine = {"function": {"name": "noop", "arguments": {"reason": "user asked"}}}
    messages = [
        {"role": "user", "content": "Call noop with my reason."},
        {"role": "assistant", "content": "", "tool_calls": [genuine]},
        {"role": "tool", "content": "done"},
        {"role": "user", "content": "thanks"},
    ]

    result = strip_machinery_turns(messages, LIVENESS_CONFIG_NO_MARKER)

    assert result == messages


def test_strip_configured_call_match_treats_missing_arguments_as_empty():
    """Injection normalizes absent configured arguments to {}; an echo whose
    arguments key is missing must still match a config without arguments."""
    echo = {"function": {"name": "noop"}}
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [echo]},
        {"role": "tool", "content": "ok"},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages, {"toolName": "noop"})

    assert result == [{"role": "user", "content": "next"}]


def test_strip_dict_arguments_unserializable_treated_genuine():
    """Dict arguments that cannot be JSON-serialized never raise; the marker
    check is skipped and the call is treated as genuine (kept)."""
    call = {
        "id": "call_pi_unserializable",
        "type": "function",
        "function": {"name": "bash", "arguments": {"cmd": object()}},
    }
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "user", "content": "hello"},
    ]

    result = strip_machinery_turns(messages)

    assert result == messages


def test_strip_configured_call_different_tool_name_kept():
    """A call to a different tool than the configured liveness call is genuine
    even when its arguments happen to equal the configured arguments."""
    call = {"function": {"name": "bash", "arguments": {"reason": "keepalive"}}}
    messages = [
        {"role": "user", "content": "run it"},
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "content": "keepalive"},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages, LIVENESS_CONFIG_NO_MARKER)

    assert result == messages


def test_strip_configured_call_malformed_string_arguments_kept():
    """String arguments that fail json.loads cannot match the configured call;
    the turn is kept."""
    call = {"function": {"name": "noop", "arguments": "{not-json"}}
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "content": "keepalive"},
        {"role": "user", "content": "next"},
    ]

    result = strip_machinery_turns(messages, LIVENESS_CONFIG_NO_MARKER)

    assert result == messages


def test_strip_trailing_idless_ollama_echo_kept_as_corrective_feedback():
    """The configured-call match must feed the trailing-exchange detector too:
    a trailing id-less echo is kept intact as one-shot corrective feedback."""
    echo = {"function": {"name": "noop", "arguments": {"reason": "keepalive"}}}
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [echo]},
        {"role": "tool", "content": "keepalive"},
    ]

    result = strip_machinery_turns(messages, LIVENESS_CONFIG_NO_MARKER)

    assert result == messages


# --- Tests for collapse_duplicate_tool_calls ---

def _dup_exchange(command="git show cf76264 -- opencode_plans/project_root.txt", call_id="call_x",
                  result="(no output)", content=""):
    return [
        {"role": "assistant", "content": content,
         "tool_calls": [{"id": call_id, "type": "function",
                         "function": {"name": "bash", "arguments": f'{{"command": "{command}"}}'}}]},
        {"role": "tool", "tool_call_id": call_id, "content": result},
    ]


def test_collapse_run_of_three_identical_exchanges():
    """Three identical call/result pairs collapse to one pair with a corrective note."""
    messages = [{"role": "user", "content": "review the commit"}]
    for n in range(3):
        messages += _dup_exchange(call_id=f"call_{n}")
    messages.append({"role": "user", "content": "continue"})

    result = collapse_duplicate_tool_calls(messages)

    assert len(result) == 4
    assert result[0] == {"role": "user", "content": "review the commit"}
    assert result[1] == messages[1]
    assert "(no output)" in result[2]["content"]
    assert "3 consecutive times" in result[2]["content"]
    assert "Repeating it again will not change the outcome" in result[2]["content"]
    assert result[3] == {"role": "user", "content": "continue"}


def test_collapse_long_run_reports_count():
    """A ten-repeat run collapses and the note carries the real count."""
    messages = []
    for n in range(10):
        messages += _dup_exchange(call_id=f"call_{n}")

    result = collapse_duplicate_tool_calls(messages)

    assert len(result) == 2
    assert "10 consecutive times" in result[1]["content"]


def test_collapse_leaves_two_repeats_alone():
    """Two identical exchanges are a legitimate retry, not a loop."""
    messages = _dup_exchange(call_id="call_0") + _dup_exchange(call_id="call_1")

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_leaves_differing_results_alone():
    """Identical calls with changing results (polling) are not collapsed."""
    messages = (_dup_exchange(call_id="call_0", result="run 1 pending")
                + _dup_exchange(call_id="call_1", result="run 2 pending")
                + _dup_exchange(call_id="call_2", result="run 3 done"))

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_leaves_differing_arguments_alone():
    """Different commands never collapse."""
    messages = (_dup_exchange(command="ls -la", call_id="call_0")
                + _dup_exchange(command="ls -l", call_id="call_1")
                + _dup_exchange(command="ls", call_id="call_2"))

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_result_whitespace_normalized():
    """Results differing only in whitespace still count as identical."""
    messages = (_dup_exchange(call_id="call_0", result="total  128\n")
                + _dup_exchange(call_id="call_1", result="total 128")
                + _dup_exchange(call_id="call_2", result=" total 128 "))

    result = collapse_duplicate_tool_calls(messages)

    assert len(result) == 2
    assert "3 consecutive times" in result[1]["content"]


def test_collapse_interrupted_run_not_collapsed():
    """A non-tool message inside the run breaks it: no segment reaches threshold."""
    messages = (_dup_exchange(call_id="call_0")
                + _dup_exchange(call_id="call_1")
                + [{"role": "user", "content": "keep going"}]
                + _dup_exchange(call_id="call_2"))

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_multi_call_turns_ignored():
    """Assistant turns carrying more than one tool call never participate."""
    turn = {"role": "assistant", "content": "",
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "bash", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            ]}
    messages = [dict(turn), {"role": "tool", "tool_call_id": "a", "content": "x"}] * 3

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_trailing_unpaired_call_untouched():
    """A tool call at the end of the conversation with no result yet passes through."""
    messages = _dup_exchange(call_id="call_0") + [_dup_exchange(call_id="call_1")[0]]

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_does_not_mutate_input():
    """The collapsed result's note lands on a copy, not the caller's dict."""
    messages = []
    for n in range(3):
        messages += _dup_exchange(call_id=f"call_{n}")
    original_result_content = messages[1]["content"]

    collapse_duplicate_tool_calls(messages)

    assert messages[1]["content"] == original_result_content


@pytest.mark.parametrize("malformed_call", [
    "not-a-dict",                                                 # call entry not a dict
    {"id": "a", "function": "nope"},                              # function not a dict
    {"id": "a", "function": {"arguments": "{}"}},                 # name missing
    {"id": "a", "function": {"name": "bash", "arguments": 7}},    # arguments wrong type
])
def test_collapse_ignores_malformed_tool_calls(malformed_call):
    """Malformed single-call turns produce no signature and never collapse,
    even when repeated identically past the threshold."""
    messages = []
    for _ in range(3):
        messages += [
            {"role": "assistant", "content": "", "tool_calls": [malformed_call]},
            {"role": "tool", "content": "(no output)"},
        ]

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_dict_arguments_key_order_insensitive():
    """Ollama-shape dict arguments participate in collapsing, and key order
    differences do not defeat the signature (serialized with sort_keys)."""
    def exchange(args):
        return [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c", "type": "function",
                             "function": {"name": "bash", "arguments": args}}]},
            {"role": "tool", "content": "(no output)"},
        ]

    messages = (exchange({"a": 1, "b": 2})
                + exchange({"b": 2, "a": 1})
                + exchange({"a": 1, "b": 2}))

    result = collapse_duplicate_tool_calls(messages)

    assert len(result) == 2
    assert "3 consecutive times" in result[1]["content"]


def test_collapse_dict_arguments_unserializable_not_collapsed():
    """Arguments dicts that cannot be JSON-serialized produce no signature;
    the run passes through untouched instead of raising."""
    unserializable = {"cmd": object()}

    def exchange():
        return [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c", "type": "function",
                             "function": {"name": "bash", "arguments": unserializable}}]},
            {"role": "tool", "content": "(no output)"},
        ]

    messages = exchange() + exchange() + exchange()

    result = collapse_duplicate_tool_calls(messages)

    assert result == messages


def test_collapse_none_result_content_collapses_with_note():
    """Tool results whose content is None normalize to an empty signature and
    still collapse; the corrective note is appended onto an empty string."""
    messages = []
    for n in range(3):
        messages += [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": f"call_{n}", "type": "function",
                             "function": {"name": "bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"call_{n}", "content": None},
        ]

    result = collapse_duplicate_tool_calls(messages)

    assert len(result) == 2
    assert result[1]["content"].startswith("\n\n[Wilmer note:")
    assert "3 consecutive times" in result[1]["content"]


def test_handle_user_prompt_collapses_duplicates_before_routing(mock_dependencies):
    """With livenessToolCall configured, the collapse runs before categorization routing."""
    mock_dependencies['get_custom_workflow_is_active'].return_value = False
    mock_dependencies['get_liveness_tool_call'].return_value = {"toolName": "bash"}
    mock_service_instance = mock_dependencies['PromptCategorizationService'].return_value
    mock_service_instance.get_prompt_category.return_value = "ok"

    messages = [{"role": "user", "content": "review"}]
    for n in range(4):
        messages += _dup_exchange(call_id=f"call_{n}")

    handle_user_prompt("req-2", messages, stream=False)

    routed = mock_service_instance.get_prompt_category.call_args[1]['messages']
    assert len(routed) == 3
    assert "4 consecutive times" in routed[2]["content"]


def test_handle_user_prompt_strips_machinery_before_routing(mock_dependencies):
    """With livenessToolCall configured, the strip runs before categorization routing."""
    mock_dependencies['get_custom_workflow_is_active'].return_value = False
    mock_dependencies['get_liveness_tool_call'].return_value = {"toolName": "bash"}
    mock_service_instance = mock_dependencies['PromptCategorizationService'].return_value
    mock_service_instance.get_prompt_category.return_value = "ok"

    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34", "content": "[Wilmer] ..."},
        {"role": "user", "content": "continue"},
    ]

    handle_user_prompt("req-1", messages, stream=False)

    call_args = mock_service_instance.get_prompt_category.call_args[1]
    assert call_args['messages'] == [
        {"role": "user", "content": "Review the repo."},
        {"role": "user", "content": "continue"},
    ]


def test_handle_user_prompt_leaves_conversation_untouched_without_liveness_config(mock_dependencies):
    """Without livenessToolCall, neither machinery pass rewrites the conversation."""
    mock_dependencies['get_custom_workflow_is_active'].return_value = False
    mock_service_instance = mock_dependencies['PromptCategorizationService'].return_value
    mock_service_instance.get_prompt_category.return_value = "ok"

    messages = [
        {"role": "user", "content": "Review the repo."},
        {"role": "assistant", "content": "", "tool_calls": [_machinery_call()]},
        {"role": "tool", "tool_call_id": "wilmer_liveness_ab12cd34", "content": "[Wilmer] ..."},
    ]
    for n in range(4):
        messages += _dup_exchange(call_id=f"call_{n}")

    handle_user_prompt("req-3", messages, stream=False)

    routed = mock_service_instance.get_prompt_category.call_args[1]['messages']
    assert routed == messages
