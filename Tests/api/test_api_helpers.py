# Tests/api/test_api_helpers.py

import json

import pytest

from Middleware.api import api_helpers


@pytest.mark.parametrize("api_type, expected_method", [
    ("openaichatcompletion", "build_openai_chat_completion_chunk"),
    ("openaicompletion", "build_openai_completion_chunk"),
    ("ollamagenerate", "build_ollama_generate_chunk"),
    ("ollamaapichat", "build_ollama_chat_chunk"),
])
def test_build_response_json_dispatcher(mocker, monkeypatch, api_type, expected_method):
    """Tests that build_response_json calls the correct service method based on API_TYPE."""
    mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
    monkeypatch.setattr('Middleware.common.instance_global_variables.API_TYPE', api_type)

    mock_method = getattr(mock_response_builder, expected_method)
    mock_method.return_value = {"status": "ok"}

    result = api_helpers.build_response_json("test_token", "stop")

    # Ollama methods now accept request_id as third parameter (defaults to None)
    if api_type in ("ollamagenerate", "ollamaapichat"):
        mock_method.assert_called_once_with("test_token", "stop", None)
    else:
        mock_method.assert_called_once_with("test_token", "stop")
    assert json.loads(result) == {"status": "ok"}


def test_build_response_json_unsupported_type(monkeypatch):
    """Tests that a ValueError is raised for an unsupported API type."""
    monkeypatch.setattr('Middleware.common.instance_global_variables.API_TYPE', "unsupported_api")
    with pytest.raises(ValueError, match="Unsupported API type for streaming: unsupported_api"):
        api_helpers.build_response_json("token")


@pytest.mark.parametrize("chunk, expected_text", [
    # OpenAI Chat SSE
    ('data: {"choices": [{"delta": {"content": "Hello"}}]}', "Hello"),
    # OpenAI Legacy Completion SSE
    ('data: {"choices": [{"text": " World"}]}', " World"),
    # Ollama Generate plain JSON string
    ('{"response": "Ollama"}', "Ollama"),
    # Ollama Chat plain JSON string
    ('{"message": {"content": " Chat"}}', " Chat"),
    # Direct dictionary
    ({"choices": [{"delta": {"content": "Dict"}}]}, "Dict"),
    # SSE Done signal
    ('data: [DONE]', ""),
    # Empty/None values
    (None, ""),
    ("", ""),
    ("  ", ""),
    # Malformed JSON
    ('data: {"bad": json', ""),
])
def test_extract_text_from_chunk(chunk, expected_text):
    assert api_helpers.extract_text_from_chunk(chunk) == expected_text


@pytest.mark.parametrize("input_text, expected_output", [
    ("Assistant: Hello", "Hello"),
    ("  Assistant:  Hi there", "Hi there"),
    ("No prefix here", "No prefix here"),
    ("Assistant:", ""),
])
def test_remove_assistant_prefix(input_text, expected_output):
    assert api_helpers.remove_assistant_prefix(input_text) == expected_output
