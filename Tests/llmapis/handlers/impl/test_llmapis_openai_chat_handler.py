# Tests/llmapis/handlers/impl/test_openai_api_handler.py

import json
import logging

import pytest

from Middleware.llmapis.handlers.impl.openai_api_handler import OpenAiApiHandler


@pytest.fixture
def mock_configs():
    """Provides mock configuration dictionaries for the handler."""
    return {
        "api_type_config": {
            "type": "openAIChatCompletion",
            "presetType": "OpenAI",
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "max_tokens"
        },
        "endpoint_config": {
            "endpoint": "http://localhost:8080",
            "apiTypeConfigFileName": "Open-AI-API",
        }
    }


@pytest.fixture
def openai_handler(mock_configs):
    """Creates an instance of OpenAiApiHandler with mocked configurations."""
    handler = OpenAiApiHandler(
        base_url="http://localhost:8080",
        api_key="test_api_key",
        gen_input={"temperature": 0.7, "top_p": 0.9},
        model_name="test-model",
        headers={"Authorization": "Bearer test_api_key"},
        stream=False,
        api_type_config=mock_configs["api_type_config"],
        endpoint_config=mock_configs["endpoint_config"],
        max_tokens=256,
        dont_include_model=False,
    )
    return handler


def test_get_api_endpoint_url(openai_handler):
    """
    Verifies that the correct API endpoint URL is constructed.
    """
    expected_url = "http://localhost:8080/v1/chat/completions"
    assert openai_handler._get_api_endpoint_url() == expected_url


def test_iterate_by_lines_property(openai_handler):
    """
    Verifies that the handler is configured for standard SSE streaming (not line-by-line).
    """
    assert not openai_handler._iterate_by_lines


class TestPreparePayload:
    """
    Tests the _prepare_payload method, which relies on the base class implementation.
    """

    def test_basic_payload_structure(self, openai_handler):
        """
        Verifies that the payload is correctly structured with the model name,
        messages, and all generation parameters at the top level.
        """
        conversation = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hi!"}
        ]
        payload = openai_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None)
        assert payload["model"] == "test-model"
        assert payload["messages"] == conversation
        assert payload["temperature"] == 0.7
        assert payload["top_p"] == 0.9
        assert payload["max_tokens"] == 256
        assert payload["stream"] is False

    def test_payload_omits_model_when_configured(self, mock_configs):
        """
        Tests that the 'model' key is correctly omitted from the payload when
        the 'dont_include_model' flag is set to True.
        """
        handler = OpenAiApiHandler(
            base_url="http://localhost:8080",
            api_key="test_api_key",
            gen_input={},
            model_name="test-model",
            headers={},
            stream=False,
            api_type_config=mock_configs["api_type_config"],
            endpoint_config=mock_configs["endpoint_config"],
            max_tokens=100,
            dont_include_model=True
        )
        conversation = [{"role": "user", "content": "Hi!"}]
        payload = handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None)
        assert "model" not in payload, "The 'model' key should not be in the payload."
        assert "messages" in payload


class TestParseNonStreamResponse:
    """
    Tests the _parse_non_stream_response method for handling complete, non-streaming responses.
    """

    def test_success_path(self, openai_handler):
        """
        Tests successful extraction of content from a valid response structure.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': 'This is the expected response.'
                }
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert result == 'This is the expected response.'

    def test_null_content(self, openai_handler):
        """
        Tests handling of a response where the content field is null.
        The `or ""` clause should prevent an error and return an empty string.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': None
                }
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert result == ""

    @pytest.mark.parametrize("malformed_response, error_msg", [
        ({}, "response with missing 'choices' key"),
        ({'choices': []}, "response with empty 'choices' list"),
        ({'choices': [{}]}, "response with choice missing 'message' key"),
        ({'choices': [{'message': {}}]}, "response with message missing 'content' key")
    ])
    def test_malformed_responses(self, openai_handler, malformed_response, error_msg, mocker):
        """
        Tests various malformed response structures to ensure they are handled gracefully.
        """
        mock_logger_error = mocker.patch.object(
            logging.getLogger('Middleware.llmapis.handlers.impl.openai_api_handler'), 'error')

        result = openai_handler._parse_non_stream_response(malformed_response)

        assert result == ""
        mock_logger_error.assert_called_once()
        assert f"Could not find content in OpenAI response: {malformed_response}" in mock_logger_error.call_args[0][0]


class TestProcessStreamData:
    """
    Tests the _process_stream_data method for handling individual SSE data chunks.
    """

    def test_valid_data_chunk_with_content(self, openai_handler):
        """
        Tests parsing a standard streaming chunk that contains a text token.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {"content": "Hello"},
                "finish_reason": None
            }]
        })
        expected = {'token': 'Hello', 'finish_reason': None}
        assert openai_handler._process_stream_data(data_str) == expected

    def test_valid_data_chunk_with_finish_reason(self, openai_handler):
        """
        Tests parsing the final streaming chunk that contains a finish reason.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {},
                "finish_reason": "stop"
            }]
        })
        expected = {'token': '', 'finish_reason': 'stop'}
        assert openai_handler._process_stream_data(data_str) == expected

    def test_initial_chunk_with_empty_delta_content(self, openai_handler):
        """
        Tests parsing the initial chunk which often has an empty content field.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": None
            }]
        })
        expected = {'token': '', 'finish_reason': None}
        assert openai_handler._process_stream_data(data_str) == expected

    def test_empty_data_string_input(self, openai_handler):
        """
        Tests that an empty data string returns None without error.
        """
        assert openai_handler._process_stream_data("") is None

    def test_invalid_json_string(self, openai_handler, mocker):
        """
        Tests that a non-JSON string is handled gracefully.
        """
        mock_logger_warning = mocker.patch.object(
            logging.getLogger('Middleware.llmapis.handlers.impl.openai_api_handler'), 'warning')
        data_str = "this is not json"
        result = openai_handler._process_stream_data(data_str)
        assert result is None
        mock_logger_warning.assert_called_once()
        assert f"Could not parse OpenAI stream data string: {data_str}" in mock_logger_warning.call_args[0][0]

    def test_json_missing_choices_key(self, openai_handler):
        """
        Tests that JSON missing the 'choices' key returns a default empty chunk
        due to the handler's defensive .get() calls.
        """
        malformed_json_str = '{"some_other_key": "value"}'
        expected_result = {'token': '', 'finish_reason': None}
        result = openai_handler._process_stream_data(malformed_json_str)
        assert result == expected_result

    def test_json_with_empty_choices_list(self, openai_handler, mocker):
        """
        Tests that JSON with an empty 'choices' list correctly triggers an
        IndexError and returns None.
        """
        mock_logger_warning = mocker.patch.object(
            logging.getLogger('Middleware.llmapis.handlers.impl.openai_api_handler'), 'warning')
        malformed_json_str = '{"choices": []}'
        result = openai_handler._process_stream_data(malformed_json_str)
        assert result is None
        mock_logger_warning.assert_called_once()
        assert f"Could not parse OpenAI stream data string: {malformed_json_str}" in mock_logger_warning.call_args[0][0]
