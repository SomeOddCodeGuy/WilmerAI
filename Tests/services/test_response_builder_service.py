# Tests/services/test_response_builder_service.py

import pytest

from Middleware.services.response_builder_service import ResponseBuilderService


@pytest.fixture
def service(mocker):
    """Provides an instance of ResponseBuilderService with mocked dependencies and shared workflows enabled."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=True)
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['Coding_Workflow', 'General_Workflow'])
    return ResponseBuilderService()


@pytest.fixture
def service_no_workflows(mocker):
    """Provides an instance of ResponseBuilderService with shared workflows disabled (default behavior)."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-model")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=False)
    return ResponseBuilderService()


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
    even when there's an active workflow override. This prevents model names
    like 'user:old_workflow:new_workflow' from being returned.
    """
    # Simulate an active workflow override - get_model_name would return "test-user:active-workflow"
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-user:active-workflow")
    # But get_current_username returns just the username
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-user")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=True)
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['Workflow_A', 'Workflow_B'])

    service = ResponseBuilderService()
    response = service.build_openai_models_response()

    # Model names should be "test-user:Workflow_A", NOT "test-user:active-workflow:Workflow_A"
    assert len(response["data"]) == 2
    assert response["data"][0]["id"] == "test-user:Workflow_A"
    assert response["data"][1]["id"] == "test-user:Workflow_B"
    # Verify no concatenated workflow names
    assert "active-workflow" not in response["data"][0]["id"]
    assert "active-workflow" not in response["data"][1]["id"]


def test_build_ollama_tags_response_ignores_active_workflow_override(mocker):
    """
    Tests that the tags endpoint uses username only, not username:workflow,
    even when there's an active workflow override. This prevents model names
    like 'user:old_workflow:new_workflow' from being returned.
    """
    # Simulate an active workflow override - get_model_name would return "test-user:active-workflow"
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-user:active-workflow")
    # But get_current_username returns just the username
    mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value="test-user")
    mocker.patch('Middleware.utilities.config_utils.get_allow_shared_workflows', return_value=True)
    mocker.patch('Middleware.utilities.config_utils.get_available_shared_workflows',
                 return_value=['Workflow_A', 'Workflow_B'])

    service = ResponseBuilderService()
    response = service.build_ollama_tags_response()

    # Model names should be "test-user:Workflow_A", NOT "test-user:active-workflow:Workflow_A"
    assert len(response["models"]) == 2
    assert response["models"][0]["name"] == "test-user:Workflow_A"
    assert response["models"][1]["name"] == "test-user:Workflow_B"
    assert response["models"][0]["model"] == "test-user:Workflow_A:latest"
    # Verify no concatenated workflow names
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

    service = ResponseBuilderService()
    response = service.build_openai_models_response()

    # Should return just the username, not username:active-workflow
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

    service = ResponseBuilderService()
    response = service.build_ollama_tags_response()

    # Should return just the username, not username:active-workflow
    assert len(response["models"]) == 1
    assert response["models"][0]["name"] == "test-user"
    assert response["models"][0]["model"] == "test-user:latest"
