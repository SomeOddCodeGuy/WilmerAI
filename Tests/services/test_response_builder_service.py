# Tests/services/test_response_builder_service.py

import pytest

from Middleware.services.response_builder_service import ResponseBuilderService


@pytest.fixture
def service(mocker):
    """Provides an instance of ResponseBuilderService with mocked dependencies."""
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value="test-model")
    return ResponseBuilderService()


def test_build_openai_models_response(service):
    response = service.build_openai_models_response()
    assert response["object"] == "list"
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
    assert response["models"][0]["name"] == "test-model"
