# Tests/services/test_response_builder_service.py

import pytest

from Middleware.common import instance_global_variables
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
    Tests that the models endpoint uses username only, not username:workflow,
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
    assert message["content"] == ""
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
