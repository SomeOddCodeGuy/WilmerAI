# Tests/services/test_response_builder_service.py

import pytest

from Middleware.common import instance_global_variables
from Middleware.services import response_builder_service as rbs_module
from Middleware.services.response_builder_service import ResponseBuilderService


@pytest.fixture
def service(mocker):
    """Provides an instance of ResponseBuilderService with mocked dependencies and shared workflows enabled."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=True)
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['Coding_Workflow', 'General_Workflow'])
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={'allowSharedWorkflows': True})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 return_value=True)
    return ResponseBuilderService()


@pytest.fixture
def service_no_workflows(mocker):
    """Provides an instance of ResponseBuilderService with shared workflows disabled (default behavior)."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=False)
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={'allowSharedWorkflows': False})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 return_value=False)
    return ResponseBuilderService()


@pytest.fixture(autouse=True)
def reset_users_global():
    """Reset USERS global to None before each test."""
    original = instance_global_variables.USERS
    instance_global_variables.USERS = None
    yield
    instance_global_variables.USERS = original


def test_build_openai_models_response(service):
    response = service.build_openai_models_response()
    assert response["object"] == "list"
    assert len(response["data"]) == 2
    assert response["data"][0]["id"] == "test-model:Coding_Workflow"
    assert response["data"][1]["id"] == "test-model:General_Workflow"
    assert response["data"][0]["object"] == "model"
    assert response["data"][0]["owned_by"] == "Wilmer"


def test_build_openai_models_response_no_workflows(service_no_workflows):
    """Tests that models endpoint returns username when no workflows available."""
    response = service_no_workflows.build_openai_models_response()
    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == "test-model"


def test_build_openai_chat_completion_response(service):
    response = service.build_openai_chat_completion_response("Hello, world!")
    assert response["object"] == "chat.completion"
    assert response["model"] == "test-model"
    assert response["choices"][0]["message"]["content"] == "Hello, world!"
    assert response["choices"][0]["finish_reason"] == "stop"


def test_build_openai_chat_completion_chunk(service):
    response = service.build_openai_chat_completion_chunk("Hello", "stop")
    assert response["object"] == "chat.completion.chunk"
    assert response["choices"][0]["delta"]["content"] == "Hello"
    assert response["choices"][0]["finish_reason"] == "stop"


def test_build_ollama_generate_response(service):
    response = service.build_ollama_generate_response("Test output", model="test-ollama-model")
    assert response["model"] == "test-ollama-model"
    assert response["response"] == "Test output"
    assert response["done"] is True
    assert response["done_reason"] == "stop"


def test_build_ollama_chat_response(service):
    response = service.build_ollama_chat_response("Ollama says hi", "ollama-chat")
    assert response["model"] == "ollama-chat"
    assert response["message"]["content"] == "Ollama says hi"
    assert response["done"] is True


def test_build_ollama_chat_chunk(service):
    response = service.build_ollama_chat_chunk("token", finish_reason=None)
    assert response["model"] == "test-model"
    assert response["message"]["content"] == "token"
    assert response["done"] is False


def test_build_ollama_tags_response(service):
    response = service.build_ollama_tags_response()
    assert len(response["models"]) == 2
    assert response["models"][0]["name"] == "test-model:Coding_Workflow"
    assert response["models"][1]["name"] == "test-model:General_Workflow"
    assert response["models"][0]["model"] == "test-model:Coding_Workflow:latest"


def test_build_ollama_tags_response_no_workflows(service_no_workflows):
    """Tests that tags endpoint returns username when no workflows available."""
    response = service_no_workflows.build_ollama_tags_response()
    assert len(response["models"]) == 1
    assert response["models"][0]["name"] == "test-model"


def test_build_openai_models_response_ignores_active_workflow_override(mocker):
    """
    Tests that the models endpoint derives its ids from the username and shared
    workflow list, ignoring any active workflow override in get_model_name().
    """
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-user:active-workflow")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-user")
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['Workflow_A', 'Workflow_B'])
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={'allowSharedWorkflows': True})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 return_value=True)

    service = ResponseBuilderService()
    response = service.build_openai_models_response()

    assert len(response["data"]) == 2
    assert response["data"][0]["id"] == "test-user:Workflow_A"
    assert response["data"][1]["id"] == "test-user:Workflow_B"
    assert "active-workflow" not in response["data"][0]["id"]
    assert "active-workflow" not in response["data"][1]["id"]


def test_build_ollama_tags_response_ignores_active_workflow_override(mocker):
    """
    Tests that the tags endpoint uses username only, not username:workflow,
    even when there's an active workflow override.
    """
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-user:active-workflow")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-user")
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['Workflow_A', 'Workflow_B'])
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={'allowSharedWorkflows': True})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 return_value=True)

    service = ResponseBuilderService()
    response = service.build_ollama_tags_response()

    assert len(response["models"]) == 2
    assert response["models"][0]["name"] == "test-user:Workflow_A"
    assert response["models"][1]["name"] == "test-user:Workflow_B"
    assert response["models"][0]["model"] == "test-user:Workflow_A:latest"
    assert "active-workflow" not in response["models"][0]["name"]
    assert "active-workflow" not in response["models"][1]["name"]


def test_build_openai_models_response_disabled_with_active_override(mocker):
    """
    Tests that when allowSharedWorkflows is disabled, only the username is returned
    even when there's an active workflow override.
    """
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-user:active-workflow")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-user")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=False)
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 return_value=None)

    service = ResponseBuilderService()
    response = service.build_openai_models_response()

    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == "test-user"


def test_build_ollama_tags_response_disabled_with_active_override(mocker):
    """
    Tests that when allowSharedWorkflows is disabled, only the username is returned
    even when there's an active workflow override.
    """
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-user:active-workflow")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-user")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=False)
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 return_value=None)

    service = ResponseBuilderService()
    response = service.build_ollama_tags_response()

    assert len(response["models"]) == 1
    assert response["models"][0]["name"] == "test-user"
    assert response["models"][0]["model"] == "test-user:latest"


class TestMultiUserModels:
    """Tests for multi-user model aggregation."""

    @pytest.fixture(autouse=True)
    def reset_users(self):
        original = instance_global_variables.USERS
        yield
        instance_global_variables.USERS = original

    def test_openai_models_multi_user_with_workflows(self, mocker):
        """Tests that models endpoint aggregates models from all configured users."""
        instance_global_variables.USERS = ['user-one', 'user-two']

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="user-one")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for', side_effect=[
            {'allowSharedWorkflows': True},
            {'allowSharedWorkflows': False},
        ])
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', side_effect=[
            True,   # user-one allowSharedWorkflows
            None,   # user-one sharedWorkflowsSubDirectoryOverride -> _shared
            None,   # user-two does not have shared workflows
        ])
        mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                     return_value=['coding', 'general'])

        service = ResponseBuilderService()
        response = service.build_openai_models_response()

        ids = [m["id"] for m in response["data"]]
        assert "user-one:coding" in ids
        assert "user-one:general" in ids
        assert "user-two" in ids
        assert len(ids) == 3

    def test_ollama_tags_multi_user_with_workflows(self, mocker):
        """Tests that tags endpoint aggregates models from all configured users."""
        instance_global_variables.USERS = ['user-one', 'user-two']

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="user-one")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for', side_effect=[
            {'allowSharedWorkflows': True},
            {},
        ])
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', side_effect=[
            True,   # user-one allowSharedWorkflows
            None,   # user-one sharedWorkflowsSubDirectoryOverride -> _shared
            None,   # user-two
        ])
        mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                     return_value=['coding'])

        service = ResponseBuilderService()
        response = service.build_ollama_tags_response()

        names = [m["name"] for m in response["models"]]
        assert "user-one:coding" in names
        assert "user-two" in names
        assert len(names) == 2

    def test_openai_models_multi_user_no_workflows(self, mocker):
        """Tests that all users appear as bare models when no shared workflows."""
        instance_global_variables.USERS = ['user-one', 'user-two', 'user-three']

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="user-one")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for', return_value={})
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', return_value=None)

        service = ResponseBuilderService()
        response = service.build_openai_models_response()

        ids = [m["id"] for m in response["data"]]
        assert ids == ['user-one', 'user-two', 'user-three']

    def test_single_user_fallback(self, mocker):
        """Tests that single-user mode falls back to get_current_username."""
        instance_global_variables.USERS = None

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="solo-user")
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="solo-user")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                     return_value={})
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', return_value=None)

        service = ResponseBuilderService()
        response = service.build_openai_models_response()

        assert len(response["data"]) == 1
        assert response["data"][0]["id"] == "solo-user"

    def test_models_handles_config_load_error(self, mocker):
        """Tests that a user with a broken config still shows as a bare model."""
        instance_global_variables.USERS = ['good-user', 'bad-user']

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="good-user")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for', side_effect=[
            {'allowSharedWorkflows': False},
            FileNotFoundError("No such file"),
        ])
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', return_value=None)

        service = ResponseBuilderService()
        response = service.build_openai_models_response()

        ids = [m["id"] for m in response["data"]]
        assert "good-user" in ids
        assert "bad-user" in ids

    def test_openai_models_per_user_shared_folder(self, mocker):
        """Tests that each user's shared workflows come from their own shared folder."""
        instance_global_variables.USERS = ['user-a', 'user-b']

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="user-a")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for', side_effect=[
            {'allowSharedWorkflows': True, 'sharedWorkflowsSubDirectoryOverride': 'folder_a'},
            {'allowSharedWorkflows': True, 'sharedWorkflowsSubDirectoryOverride': 'folder_b'},
        ])
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', side_effect=[
            True,       # user-a allowSharedWorkflows
            'folder_a', # user-a sharedWorkflowsSubDirectoryOverride
            True,       # user-b allowSharedWorkflows
            'folder_b', # user-b sharedWorkflowsSubDirectoryOverride
        ])
        mock_get_workflows = mocker.patch(
            'Middleware.utilities.config_utils.get_available_shared_workflows',
            side_effect=[
                ['wf-alpha', 'wf-beta'],  # user-a's folder
                ['wf-gamma'],             # user-b's folder
            ]
        )

        service = ResponseBuilderService()
        response = service.build_openai_models_response()

        # Verify each user's folder was passed correctly
        calls = mock_get_workflows.call_args_list
        assert calls[0].kwargs['shared_folder_override'] == 'folder_a'
        assert calls[1].kwargs['shared_folder_override'] == 'folder_b'

        ids = [m["id"] for m in response["data"]]
        assert ids == ['user-a:wf-alpha', 'user-a:wf-beta', 'user-b:wf-gamma']

    def test_ollama_tags_per_user_shared_folder(self, mocker):
        """Tests that each user's Ollama tags come from their own shared folder."""
        instance_global_variables.USERS = ['user-a', 'user-b']

        mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="user-a")
        mocker.patch('Middleware.utilities.config_utils.get_user_config_for', side_effect=[
            {'allowSharedWorkflows': True, 'sharedWorkflowsSubDirectoryOverride': 'folder_a'},
            {'allowSharedWorkflows': True, 'sharedWorkflowsSubDirectoryOverride': 'folder_b'},
        ])
        mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists', side_effect=[
            True,       # user-a allowSharedWorkflows
            'folder_a', # user-a sharedWorkflowsSubDirectoryOverride
            True,       # user-b allowSharedWorkflows
            'folder_b', # user-b sharedWorkflowsSubDirectoryOverride
        ])
        mock_get_workflows = mocker.patch(
            'Middleware.utilities.config_utils.get_available_shared_workflows',
            side_effect=[
                ['wf-alpha'],  # user-a's folder
                ['wf-gamma'],  # user-b's folder
            ]
        )

        service = ResponseBuilderService()
        response = service.build_ollama_tags_response()

        calls = mock_get_workflows.call_args_list
        assert calls[0].kwargs['shared_folder_override'] == 'folder_a'
        assert calls[1].kwargs['shared_folder_override'] == 'folder_b'

        names = [m["name"] for m in response["models"]]
        assert names == ['user-a:wf-alpha', 'user-b:wf-gamma']


# --- Tests for tool_calls passthrough in response builders ---

def test_build_openai_chat_completion_response_with_tool_calls(service):
    """Verify that tool_calls appear in the message with finish_reason 'tool_calls' and content set to None."""
    tool_calls = [
        {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'}}
    ]
    response = service.build_openai_chat_completion_response("", tool_calls=tool_calls)
    message = response["choices"][0]["message"]
    assert message["tool_calls"] == tool_calls
    assert message["content"] is None
    assert response["choices"][0]["finish_reason"] == "tool_calls"


def test_build_openai_chat_completion_response_tool_calls_with_content(service):
    """When both tool_calls and content are present, both appear; finish_reason is 'tool_calls'."""
    tool_calls = [
        {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q":"test"}'}}
    ]
    response = service.build_openai_chat_completion_response("Here is the result.", tool_calls=tool_calls)
    message = response["choices"][0]["message"]
    assert message["tool_calls"] == tool_calls
    assert message["content"] == "Here is the result."
    assert response["choices"][0]["finish_reason"] == "tool_calls"


def test_build_openai_chat_completion_response_no_tool_calls(service):
    """Without tool_calls, message has no 'tool_calls' key and finish_reason is 'stop'."""
    response = service.build_openai_chat_completion_response("Hello!")
    message = response["choices"][0]["message"]
    assert "tool_calls" not in message
    assert response["choices"][0]["finish_reason"] == "stop"


def test_build_openai_chat_completion_chunk_with_tool_calls(service):
    """Streaming chunk delta includes tool_calls when provided."""
    tool_calls = [
        {"index": 0, "id": "call_1", "type": "function", "function": {"name": "f", "arguments": ""}}
    ]
    response = service.build_openai_chat_completion_chunk("", finish_reason=None, tool_calls=tool_calls)
    delta = response["choices"][0]["delta"]
    assert delta["tool_calls"] == tool_calls


def test_build_openai_chat_completion_chunk_no_tool_calls(service):
    """Streaming chunk delta does not have 'tool_calls' when none are provided."""
    response = service.build_openai_chat_completion_chunk("token", finish_reason=None)
    delta = response["choices"][0]["delta"]
    assert "tool_calls" not in delta


def test_build_ollama_chat_response_with_tool_calls(service):
    """Ollama chat response message includes tool_calls when provided."""
    tool_calls = [
        {"function": {"name": "do_thing", "arguments": {"key": "val"}}}
    ]
    response = service.build_ollama_chat_response("", model_name="ollama-model", tool_calls=tool_calls)
    message = response["message"]
    assert message["tool_calls"] == tool_calls
    assert message["role"] == "assistant"


def test_build_ollama_chat_response_no_tool_calls(service):
    """Ollama chat response message has no 'tool_calls' key when none provided."""
    response = service.build_ollama_chat_response("Hello", model_name="ollama-model")
    message = response["message"]
    assert "tool_calls" not in message
    assert message["content"] == "Hello"


def test_build_ollama_chat_chunk_with_tool_calls(service):
    """Ollama chat chunk message includes tool_calls when provided."""
    tool_calls = [
        {"function": {"name": "lookup", "arguments": {"id": 1}}}
    ]
    response = service.build_ollama_chat_chunk("", finish_reason=None, tool_calls=tool_calls)
    message = response["message"]
    assert message["tool_calls"] == tool_calls


def test_build_ollama_chat_chunk_no_tool_calls(service):
    """Ollama chat chunk message has no 'tool_calls' key when none provided."""
    response = service.build_ollama_chat_chunk("token", finish_reason=None)
    message = response["message"]
    assert "tool_calls" not in message
    assert message["content"] == "token"


class TestOllamaToolCallConversion:
    """Ollama clients expect {"function": {"name", "arguments": {...}}} with
    arguments as a JSON object; Wilmer's internal OpenAI shape (id/type/index
    envelope, arguments as a JSON string) must be converted at the builder."""

    def test_openai_format_converted_to_native(self, service):
        openai_calls = [{"index": 0, "id": "call_abc", "type": "function",
                         "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'}}]
        response = service.build_ollama_chat_response("", model_name="m", tool_calls=openai_calls)
        assert response["message"]["tool_calls"] == [
            {"function": {"name": "get_weather", "arguments": {"city": "Tokyo"}}}
        ]

    def test_chunk_converts_openai_format(self, service):
        openai_calls = [{"index": 0, "id": "call_abc", "type": "function",
                         "function": {"name": "lookup", "arguments": '{"id": 1}'}}]
        response = service.build_ollama_chat_chunk("", finish_reason=None, tool_calls=openai_calls)
        assert response["message"]["tool_calls"] == [
            {"function": {"name": "lookup", "arguments": {"id": 1}}}
        ]

    def test_native_format_passes_through_unchanged(self, service):
        native_calls = [{"function": {"name": "do_thing", "arguments": {"key": "val"}}}]
        response = service.build_ollama_chat_response("", model_name="m", tool_calls=native_calls)
        assert response["message"]["tool_calls"] == native_calls

    def test_unparseable_arguments_degrade_to_empty_object(self, service):
        bad_calls = [{"function": {"name": "broken", "arguments": '{"unterminated'}}]
        response = service.build_ollama_chat_response("", model_name="m", tool_calls=bad_calls)
        assert response["message"]["tool_calls"] == [
            {"function": {"name": "broken", "arguments": {}}}
        ]

    def test_empty_and_missing_arguments_become_empty_object(self, service):
        calls = [{"function": {"name": "no_args", "arguments": ""}},
                 {"function": {"name": "none_args"}}]
        response = service.build_ollama_chat_response("", model_name="m", tool_calls=calls)
        assert response["message"]["tool_calls"] == [
            {"function": {"name": "no_args", "arguments": {}}},
            {"function": {"name": "none_args", "arguments": {}}},
        ]


# --- Exact-schema tests for builders with pinned time/uuid/datetime ---
#
# These payload shapes are the client-facing API contract (OpenAI/Ollama
# clients parse them); each builder is asserted as a complete dict so any
# schema drift fails loudly.

FROZEN_TIME = 1234567890
FROZEN_UUID = "abcd1234-0000-0000-0000-000000000000"
FROZEN_CREATED_AT = "2024-01-01T00:00:00Z"


@pytest.fixture
def frozen_service(mocker):
    """ResponseBuilderService with model name, time, uuid, and datetime pinned."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-model")
    mock_time = mocker.patch.object(rbs_module, 'time')
    mock_time.time.return_value = FROZEN_TIME
    mock_uuid = mocker.patch.object(rbs_module, 'uuid')
    mock_uuid.uuid4.return_value = FROZEN_UUID
    mock_datetime = mocker.patch.object(rbs_module, 'datetime')
    mock_datetime.now.return_value.isoformat.return_value = "2024-01-01T00:00:00+00:00"
    return ResponseBuilderService()


def test_build_openai_completion_response_exact_schema(frozen_service):
    response = frozen_service.build_openai_completion_response("Full text")
    assert response == {
        "id": f"cmpl-{FROZEN_TIME}",
        "object": "text_completion",
        "created": FROZEN_TIME,
        "model": "test-model",
        "system_fingerprint": "wmr_123456789",
        "choices": [
            {
                "text": "Full text",
                "index": 0,
                "logprobs": None,
                "finish_reason": "stop"
            }
        ],
        "usage": {}
    }


def test_build_openai_chat_completion_response_exact_schema(frozen_service):
    response = frozen_service.build_openai_chat_completion_response("Hello, world!")
    assert response == {
        "id": f"chatcmpl-{FROZEN_TIME}",
        "object": "chat.completion",
        "created": FROZEN_TIME,
        "model": "test-model",
        "system_fingerprint": "wmr_123456789",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello, world!"},
                "logprobs": None,
                "finish_reason": "stop"
            }
        ],
        "usage": {}
    }


@pytest.mark.parametrize("finish_reason", ["stop", None])
def test_build_openai_completion_chunk_exact_schema(frozen_service, finish_reason):
    response = frozen_service.build_openai_completion_chunk("tok", finish_reason)
    assert response == {
        "id": f"cmpl-{FROZEN_UUID}",
        "object": "text_completion",
        "created": FROZEN_TIME,
        "choices": [
            {
                "text": "tok",
                "index": 0,
                "logprobs": None,
                "finish_reason": finish_reason
            }
        ],
        "model": "test-model",
        "system_fingerprint": "fp_44709d6fcb"
    }


def test_build_openai_chat_completion_chunk_exact_schema(frozen_service):
    response = frozen_service.build_openai_chat_completion_chunk("Hello", "stop")
    assert response == {
        "id": f"chatcmpl-{FROZEN_UUID}",
        "object": "chat.completion.chunk",
        "created": FROZEN_TIME,
        "model": "test-model",
        "system_fingerprint": "fp_44709d6fcb",
        "choices": [
            {
                "index": 0,
                "delta": {"content": "Hello"},
                "logprobs": None,
                "finish_reason": "stop"
            }
        ]
    }


def test_build_openai_chat_completion_chunk_empty_token_has_empty_delta(frozen_service):
    """An empty token with no tool_calls must produce an empty delta dict."""
    response = frozen_service.build_openai_chat_completion_chunk("", finish_reason="stop")
    assert response["choices"][0]["delta"] == {}


def test_build_openai_tool_call_response_exact_schema(frozen_service):
    response = frozen_service.build_openai_tool_call_response()
    assert response == {
        "id": f"chatcmpl-opnwui-tool-{FROZEN_TIME}",
        "object": "chat.completion",
        "created": FROZEN_TIME,
        "model": "test-model",
        "system_fingerprint": "wmr_123456789",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": []},
                "logprobs": None,
                "finish_reason": "tool_calls"
            }
        ],
        "usage": {}
    }


def test_build_ollama_version_response_exact_schema(frozen_service):
    assert frozen_service.build_ollama_version_response() == {"version": "0.9"}


def test_build_ollama_tool_call_response_exact_schema(frozen_service):
    response = frozen_service.build_ollama_tool_call_response("my-model")
    assert response == {
        "model": "my-model",
        "created_at": FROZEN_CREATED_AT,
        "message": {"role": "assistant", "content": ""},
        "done_reason": "stop",
        "done": True,
        "total_duration": 0,
        "load_duration": 0,
        "prompt_eval_count": 0,
        "prompt_eval_duration": 0,
        "eval_count": 0,
        "eval_duration": 0
    }


@pytest.mark.parametrize("finish_reason,expected_done,expected_done_reason", [
    ("stop", True, "stop"),
    (None, False, None),
    ("length", True, "length"),
    ("tool_calls", True, "stop"),
])
def test_build_ollama_generate_chunk_done_logic(frozen_service, finish_reason, expected_done, expected_done_reason):
    """'done' must be True for ANY terminal finish_reason (an Ollama client reads
    the stream until done: true, so a length cutoff or tool call must still
    terminate it), with done_reason mapped to Ollama's stop/length vocabulary."""
    response = frozen_service.build_ollama_generate_chunk("tok", finish_reason)
    expected = {
        "model": "test-model",
        "created_at": FROZEN_CREATED_AT,
        "response": "tok",
        "done": expected_done
    }
    if expected_done:
        expected["done_reason"] = expected_done_reason
    assert response == expected


@pytest.mark.parametrize("finish_reason,expected_done,expected_done_reason", [
    ("stop", True, "stop"),
    (None, False, None),
    ("length", True, "length"),
    ("tool_calls", True, "stop"),
])
def test_build_ollama_chat_chunk_done_logic(frozen_service, finish_reason, expected_done, expected_done_reason):
    """'done' must be True for ANY terminal finish_reason (an Ollama client reads
    the stream until done: true, so a length cutoff or tool call must still
    terminate it), with done_reason mapped to Ollama's stop/length vocabulary."""
    response = frozen_service.build_ollama_chat_chunk("tok", finish_reason)
    expected = {
        "model": "test-model",
        "created_at": FROZEN_CREATED_AT,
        "message": {"role": "assistant", "content": "tok"},
        "done": expected_done
    }
    if expected_done:
        expected["done_reason"] = expected_done_reason
    assert response == expected


# --- request_id passthrough across all Ollama builders ---

@pytest.mark.parametrize("builder,kwargs", [
    ("build_ollama_generate_response", {"full_text": "t", "model": "m"}),
    ("build_ollama_chat_response", {"full_text": "t", "model_name": "m"}),
    ("build_ollama_generate_chunk", {"token": "t", "finish_reason": None}),
    ("build_ollama_chat_chunk", {"token": "t", "finish_reason": None}),
])
def test_ollama_builders_include_request_id_when_provided(frozen_service, builder, kwargs):
    response = getattr(frozen_service, builder)(request_id="req-42", **kwargs)
    assert response["request_id"] == "req-42"


@pytest.mark.parametrize("builder,kwargs", [
    ("build_ollama_generate_response", {"full_text": "t", "model": "m"}),
    ("build_ollama_chat_response", {"full_text": "t", "model_name": "m"}),
    ("build_ollama_generate_chunk", {"token": "t", "finish_reason": None}),
    ("build_ollama_chat_chunk", {"token": "t", "finish_reason": None}),
])
def test_ollama_builders_omit_request_id_when_none(frozen_service, builder, kwargs):
    response = getattr(frozen_service, builder)(request_id=None, **kwargs)
    assert "request_id" not in response


def test_build_ollama_chat_response_exact_schema(frozen_service):
    """Pins the complete non-streaming /api/chat payload, including the fixed
    done/done_reason flags and the hardcoded duration/eval telemetry fields that
    Ollama clients parse."""
    response = frozen_service.build_ollama_chat_response(
        "Hi there", model_name="chat-model", request_id="req-7")
    assert response == {
        "model": "chat-model",
        "created_at": FROZEN_CREATED_AT,
        "message": {"role": "assistant", "content": "Hi there"},
        "done_reason": "stop",
        "done": True,
        "total_duration": 4505727700,
        "load_duration": 23500100,
        "prompt_eval_count": 15,
        "prompt_eval_duration": 4000000,
        "eval_count": 392,
        "eval_duration": 4476000000,
        "request_id": "req-7",
    }


def test_build_ollama_tags_model_entry_exact_schema(mocker):
    """Pins the complete /api/tags model entry: name, ':latest' model id, fixed
    modified_at/size, sha256-of-id digest (hardcoded literal, independently
    computed), and the details block Ollama clients display."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="solo-user")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="solo-user")
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={'allowSharedWorkflows': True})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 side_effect=[True, None])  # allowSharedWorkflows, then no folder override
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['wf'])

    service = ResponseBuilderService()
    response = service.build_ollama_tags_response()

    assert response == {
        "models": [
            {
                "name": "solo-user:wf",
                "model": "solo-user:wf:latest",
                "modified_at": "2024-11-23T00:00:00Z",
                "size": 1,
                "digest": "6c5450fd68ca66971c0bb924ff792de9ace0ae1c05d4423a57697cdbd9c5eaca",
                "details": {
                    "format": "gguf",
                    "family": "wilmer",
                    "families": None,
                    "parameter_size": "N/A",
                    "quantization_level": "Q8",
                },
            }
        ]
    }


def test_build_ollama_generate_response_exact_schema(frozen_service):
    response = frozen_service.build_ollama_generate_response("Test output", model="gen-model")
    assert response == {
        "id": f"gen-{FROZEN_TIME}",
        "object": "text_completion",
        "created": FROZEN_TIME,
        "model": "gen-model",
        "response": "Test output",
        "done_reason": "stop",
        "done": True,
        "choices": [
            {
                "text": "Test output",
                "index": 0,
                "logprobs": None,
                "finish_reason": "stop"
            }
        ],
        "usage": {}
    }


def test_shared_folder_defaults_to_underscore_shared(mocker):
    """When a user has no sharedWorkflowsSubDirectoryOverride, workflows are read from '_shared'."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="solo-user")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="solo-user")
    mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                 return_value={'allowSharedWorkflows': True})
    mocker.patch('Middleware.utilities.config_utils.get_config_property_if_exists',
                 side_effect=[True, None])  # allowSharedWorkflows, then no folder override
    mock_get_workflows = mocker.patch(
        'Middleware.utilities.config_utils.get_available_shared_workflows',
        return_value=['wf'])

    service = ResponseBuilderService()
    service.build_openai_models_response()

    assert mock_get_workflows.call_args.kwargs['shared_folder_override'] == '_shared'
