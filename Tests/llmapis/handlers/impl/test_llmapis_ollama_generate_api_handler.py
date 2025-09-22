# Tests/llmapis/handlers/impl/test_ollama_generate_api_handler.py

import logging

import pytest

from Middleware.llmapis.handlers.impl.ollama_generate_api_handler import OllamaGenerateApiHandler

# Configure logging for test output
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_configs():
    """Provides mock configuration dictionaries for the handler."""
    return {
        "api_type_config": {
            "type": "ollamaApiGenerate",
            "presetType": "Ollama",
            "maxNewTokensPropertyName": "num_predict",
            "streamPropertyName": "stream"
        },
        "endpoint_config": {
            "endpoint": "http://localhost:11434",
            "maxContextTokenSize": 4096
            # other endpoint-specific fields can be added here if needed
        }
    }


@pytest.fixture
def ollama_generate_handler(mock_configs):
    """Fixture to create a standard instance of OllamaGenerateApiHandler."""
    return OllamaGenerateApiHandler(
        base_url="http://localhost:11434",
        api_key="",
        gen_input={"temperature": 0.8, "top_p": 0.9},
        model_name="test-model:latest",
        headers={"Content-Type": "application/json"},
        stream=False,  # Default to non-streaming
        api_type_config=mock_configs["api_type_config"],
        endpoint_config=mock_configs["endpoint_config"],
        max_tokens=1024
    )


def test_get_api_endpoint_url(ollama_generate_handler):
    """
    Verifies that the correct API endpoint URL is constructed.
    """
    # GIVEN an initialized handler
    handler = ollama_generate_handler

    # WHEN the endpoint URL is requested
    url = handler._get_api_endpoint_url()

    # THEN the URL should be the base URL plus the specific '/api/generate' path
    assert url == "http://localhost:11434/api/generate"


def test_iterate_by_lines_property(ollama_generate_handler):
    """
    Verifies that the handler is configured to process streams line-by-line.
    Ollama's streaming format is line-delimited JSON, so this must be True.
    """
    # GIVEN an initialized handler
    handler = ollama_generate_handler

    # WHEN the _iterate_by_lines property is accessed
    # THEN it should always return True
    assert handler._iterate_by_lines is True


def test_prepare_payload_non_streaming(ollama_generate_handler, mocker):
    """
    Tests the payload creation for a non-streaming request.
    It should include the correct model, a flattened prompt, stream=False, raw=True,
    and generation parameters nested under 'options'.
    """
    # GIVEN a handler configured for non-streaming
    handler = ollama_generate_handler
    handler.stream = False

    # GIVEN the prompt building method returns a known string
    mock_build_prompt = mocker.patch(
        'Middleware.llmapis.handlers.impl.ollama_generate_api_handler.OllamaGenerateApiHandler._build_prompt_from_conversation',
        return_value="System: You are a bot.\nUser: Hello!"
    )

    # WHEN the payload is prepared
    payload = handler._prepare_payload(None, "System: You are a bot.", "User: Hello!")

    # THEN the payload should be correctly structured for Ollama's /generate endpoint
    assert payload["model"] == "test-model:latest"
    assert payload["prompt"] == "System: You are a bot.\nUser: Hello!"
    assert payload["stream"] is False  # Explicitly False for non-streaming
    assert payload["raw"] is True  # Should always be raw
    assert "temperature" in payload["options"]
    assert "top_p" in payload["options"]
    assert "num_predict" in payload["options"]
    assert payload["options"]["num_predict"] == 1024

    mock_build_prompt.assert_called_once_with("System: You are a bot.", "User: Hello!")


def test_prepare_payload_streaming(ollama_generate_handler, mocker):
    """
    Tests the payload creation for a streaming request.
    The structure should be identical to non-streaming, but with 'stream' set to True.
    """
    # GIVEN a handler configured for streaming
    handler = ollama_generate_handler
    handler.stream = True

    # GIVEN the prompt building method returns a known string
    mock_build_prompt = mocker.patch(
        'Middleware.llmapis.handlers.impl.ollama_generate_api_handler.OllamaGenerateApiHandler._build_prompt_from_conversation',
        return_value="System: You are a bot.\nUser: Hello!"
    )

    # WHEN the payload is prepared
    payload = handler._prepare_payload(None, "System: You are a bot.", "User: Hello!")

    # THEN the 'stream' key in the payload should be True
    assert payload["stream"] is True
    assert payload["model"] == "test-model:latest"
    assert payload["prompt"] == "System: You are a bot.\nUser: Hello!"
    assert payload["raw"] is True
    assert "temperature" in payload["options"]


@pytest.mark.parametrize("input_str, expected_output", [
    # Test case 1: Standard streaming chunk
    (
            '{"response": "Hello", "done": false}',
            {'token': 'Hello', 'finish_reason': None}
    ),
    # Test case 2: Final streaming chunk
    (
            '{"response": " world.", "done": true}',
            {'token': ' world.', 'finish_reason': 'stop'}
    ),
    # Test case 3: Chunk with no text content
    (
            '{"response": "", "done": false}',
            {'token': '', 'finish_reason': None}
    ),
    # Test case 4: Malformed JSON string
    (
            '{"response": "unterminated string',
            None
    ),
    # Test case 5: Empty string input
    (
            "",
            None
    ),
    # Test case 6: JSON with missing 'response' key
    (
            '{"done": false}',
            {'token': '', 'finish_reason': None}
    ),
    # Test case 7: JSON with missing 'done' key (should be treated as not done)
    (
            '{"response": "more text"}',
            {'token': 'more text', 'finish_reason': None}
    ),
])
def test_process_stream_data(ollama_generate_handler, caplog, input_str, expected_output):
    """
    Tests the parsing of individual JSON chunks from a streaming response.
    It covers valid data, end-of-stream signals, and various error conditions.
    """
    # GIVEN a handler and a mock logging setup
    handler = ollama_generate_handler
    caplog.set_level(logging.WARNING)

    # WHEN a single data string from the stream is processed
    result = handler._process_stream_data(input_str)

    # THEN the output should match the expected standardized dictionary
    assert result == expected_output

    # AND if the input was invalid JSON, a warning should be logged
    if input_str and "unterminated" in input_str:
        assert "Could not parse Ollama stream data string" in caplog.text


@pytest.mark.parametrize("response_json, expected_text", [
    # Test case 1: Standard successful response
    (
            {
                "model": "llama3",
                "created_at": "2023-10-26T14:30:00.123Z",
                "response": "The sky is blue due to Rayleigh scattering.",
                "done": True
            },
            "The sky is blue due to Rayleigh scattering."
    ),
    # Test case 2: Response where the 'response' key is missing
    (
            {
                "model": "llama3",
                "done": True
            },
            ""
    ),
    # Test case 3: Response where the 'response' value is empty
    (
            {
                "response": ""
            },
            ""
    ),
    # Test case 4: An empty JSON object
    (
            {},
            ""
    )
])
def test_parse_non_stream_response(ollama_generate_handler, caplog, response_json, expected_text):
    """
    Tests the parsing of a complete, non-streaming JSON response.
    It should correctly extract the text content from the 'response' key
    and handle cases where the key is missing or the content is empty.
    """
    # GIVEN a handler and a mock logging setup
    handler = ollama_generate_handler
    caplog.set_level(logging.ERROR)

    # WHEN the full JSON response is parsed
    result = handler._parse_non_stream_response(response_json)

    # THEN the extracted text should be correct
    assert result == expected_text

    # AND if the 'response' key was missing, an error should be logged
    if 'response' not in response_json:
        assert "Could not find 'response' key in Ollama generate response" in caplog.text
