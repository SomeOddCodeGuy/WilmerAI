# Tests/llmapis/handlers/impl/test_koboldcpp_api_handler.py

import copy
from unittest.mock import MagicMock

import pytest
import requests

from Middleware.llmapis.handlers.impl.koboldcpp_api_handler import KoboldCppApiHandler


# A fixture to provide the basic arguments needed to initialize the handler.
# This avoids repeating the same dictionary in every test.
@pytest.fixture
def base_handler_args():
    """Provides a dictionary of base arguments for initializing the handler."""
    return {
        "base_url": "http://localhost:5001",
        "api_key": "fake_api_key",
        "gen_input": {"temperature": 0.5, "top_p": 0.9},
        "model_name": "test-model",
        "headers": {"Authorization": "Bearer fake_api_key"},
        "api_type_config": {
            "type": "koboldCppGenerate",
            "maxNewTokensPropertyName": "max_length",
            "streamPropertyName": "stream",
        },
        "endpoint_config": {
            "endpoint": "http://localhost:5001",
            "addTextToStartOfCompletion": False,
        },
        "max_tokens": 150,
    }


def test_get_api_endpoint_url(base_handler_args):
    """
    Verifies that the correct API endpoint URL is generated for both
    streaming and non-streaming modes.
    """
    # Test non-streaming URL
    handler_non_stream = KoboldCppApiHandler(**base_handler_args, stream=False)
    assert handler_non_stream._get_api_endpoint_url() == "http://localhost:5001/api/v1/generate"

    # Test streaming URL
    handler_stream = KoboldCppApiHandler(**base_handler_args, stream=True)
    assert handler_stream._get_api_endpoint_url() == "http://localhost:5001/api/extra/generate/stream"


def test_handler_properties(base_handler_args):
    """
    Tests the static properties of the handler to ensure they are set correctly
    for KoboldCpp's SSE stream format.
    """
    handler = KoboldCppApiHandler(**base_handler_args, stream=True)
    assert not handler._iterate_by_lines, "KoboldCpp uses standard SSE, not line-delimited JSON."
    assert handler._required_event_name == "message", "KoboldCpp stream events should be filtered by name 'message'."


def test_prepare_payload_basic(base_handler_args):
    """
    Verifies that the payload is correctly structured with the combined prompt
    and all generation parameters, including those added by set_gen_input.
    """
    # Arrange
    handler = KoboldCppApiHandler(**base_handler_args, stream=False)
    system_prompt = "You are a helpful assistant. "
    user_prompt = "What is the capital of France?"
    expected_full_prompt = "You are a helpful assistant. What is the capital of France?"

    # Act
    payload = handler._prepare_payload(conversation=None, system_prompt=system_prompt, prompt=user_prompt)

    # Assert
    expected_payload = {
        "prompt": expected_full_prompt,
        "temperature": 0.5,
        "top_p": 0.9,
        "max_length": 150,
        "stream": False,
    }
    assert payload == expected_payload


def test_prepare_payload_with_completion_text(base_handler_args):
    """
    Ensures that when 'addTextToStartOfCompletion' is enabled, the specified
    text is correctly appended to the end of the final prompt string.
    """
    # Arrange: Create a deep copy and modify the endpoint config for this specific test
    handler_args = copy.deepcopy(base_handler_args)
    handler_args["endpoint_config"]["addTextToStartOfCompletion"] = True
    handler_args["endpoint_config"]["textToAddToStartOfCompletion"] = "\nAssistant:"

    handler = KoboldCppApiHandler(**handler_args, stream=False)
    full_prompt = "User: Hello"

    # Act
    payload = handler._prepare_payload(conversation=None, system_prompt="", prompt=full_prompt)

    # Assert
    assert payload["prompt"] == "User: Hello\nAssistant:", "Completion text should be appended to the prompt."


@pytest.mark.parametrize(
    "data_str, expected_output",
    [
        ('{"token": "Hello"}', {'token': 'Hello', 'finish_reason': None}),
        ('{"token": ""}', {'token': '', 'finish_reason': None}),
        ('{}', {'token': '', 'finish_reason': None}),
        ('{"other_key": "value"}', {'token': '', 'finish_reason': None}),
        ("not a json string", None),
        ("", None),
    ],
    ids=["valid_token", "empty_token", "empty_json", "missing_token_key", "invalid_json", "empty_string"]
)
def test_process_stream_data(base_handler_args, data_str, expected_output):
    """
    Tests the parsing of individual data chunks from a streaming response.
    """
    handler = KoboldCppApiHandler(**base_handler_args, stream=True)
    assert handler._process_stream_data(data_str) == expected_output


@pytest.mark.parametrize(
    "response_json, expected_text",
    [
        ({"results": [{"text": "This is the response."}]}, "This is the response."),
        ({"results": [{"text": ""}]}, ""),
        ({"results": [{}]}, ""),
        ({"results": []}, ""),
        ({}, ""),
    ],
    ids=["valid_response", "empty_text", "missing_text_key", "empty_results_list", "missing_results_key"]
)
def test_parse_non_stream_response(base_handler_args, response_json, expected_text):
    """
    Tests the parsing of a complete, non-streaming JSON response object.
    It also checks that error handling for malformed responses works correctly.
    """
    handler = KoboldCppApiHandler(**base_handler_args, stream=False)
    assert handler._parse_non_stream_response(response_json) == expected_text


def test_handle_non_streaming_success(mocker, base_handler_args):
    """
    Tests a successful end-to-end non-streaming request, verifying that
    the HTTP call is made with the correct payload and the response is parsed correctly.
    """
    # Arrange
    handler = KoboldCppApiHandler(**base_handler_args, stream=False)
    mock_session = mocker.patch.object(handler, 'session', spec=requests.Session)
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": [{"text": "Success!"}]}
    mock_session.post.return_value = mock_response

    # Act
    result = handler.handle_non_streaming(prompt="Test prompt")

    # Assert
    assert result == "Success!"
    mock_session.post.assert_called_once()
    call_args, call_kwargs = mock_session.post.call_args

    # Verify URL and payload
    assert call_args[0] == "http://localhost:5001/api/v1/generate"
    expected_payload = {
        "prompt": "Test prompt",
        "temperature": 0.5,
        "top_p": 0.9,
        "max_length": 150,
        "stream": False,
    }
    assert call_kwargs['json'] == expected_payload


def test_handle_streaming_success(mocker, base_handler_args):
    """
    Tests a successful end-to-end streaming request. It verifies the correct
    HTTP call and ensures the SSE stream is parsed and yielded correctly.
    """
    # Arrange
    handler = KoboldCppApiHandler(**base_handler_args, stream=True)
    mock_session = mocker.patch.object(handler, 'session', spec=requests.Session)

    # Mock the response from iter_lines to simulate an SSE stream
    mock_stream_response = [
        "event: message",
        'data: {"token": "Hello"}',
        "",
        "event: other_event",
        'data: {"token": "ignored"}',
        "",
        "event: message",
        'data: {"token": " World"}',
    ]

    # Mock the context manager for `with session.post(...)`
    mock_response = MagicMock()
    mock_response.iter_lines.return_value = iter(mock_stream_response)
    mock_context_manager = MagicMock()
    mock_context_manager.__enter__.return_value = mock_response
    mock_context_manager.__exit__.return_value = None
    mock_session.post.return_value = mock_context_manager

    # Act
    generator = handler.handle_streaming(prompt="Test prompt")
    results = list(generator)

    # Assert
    assert results == [
        {'token': 'Hello', 'finish_reason': None},
        {'token': ' World', 'finish_reason': None},
    ]

    mock_session.post.assert_called_once()
    call_args, call_kwargs = mock_session.post.call_args

    # Verify URL, stream=True flag, and payload
    assert call_args[0] == "http://localhost:5001/api/extra/generate/stream"
    assert call_kwargs['stream'] is True
    expected_payload = {
        "prompt": "Test prompt",
        "temperature": 0.5,
        "top_p": 0.9,
        "max_length": 150,
        "stream": True,
    }
    assert call_kwargs['json'] == expected_payload


def test_handle_non_streaming_http_error(mocker, base_handler_args):
    """
    Ensures that an HTTP request failure is correctly propagated as an exception.
    """
    # Arrange
    handler = KoboldCppApiHandler(**base_handler_args, stream=False)
    mock_session = mocker.patch.object(handler, 'session', spec=requests.Session)
    mock_session.post.side_effect = requests.exceptions.RequestException("Connection failed")

    # Act & Assert
    with pytest.raises(requests.exceptions.RequestException, match="Connection failed"):
        handler.handle_non_streaming(prompt="Test prompt")
