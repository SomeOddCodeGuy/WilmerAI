# Tests/llmapis/handlers/impl/test_llmapis_claude_api_handler.py

import json
import logging

import pytest

from Middleware.llmapis.handlers.impl.claude_api_handler import ClaudeApiHandler


@pytest.fixture
def mock_configs():
    """Provides mock configuration dictionaries for the handler."""
    return {
        "api_type_config": {
            "type": "claudeMessages",
            "presetType": "OpenAiCompatibleApis",
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "max_tokens"
        },
        "endpoint_config": {
            "endpoint": "https://api.anthropic.com",
            "apiTypeConfigFileName": "Claude",
        }
    }


@pytest.fixture
def claude_handler(mock_configs):
    """Creates an instance of ClaudeApiHandler with mocked configurations."""
    handler = ClaudeApiHandler(
        base_url="https://api.anthropic.com",
        api_key="test_api_key",
        gen_input={"temperature": 0.7, "top_p": 0.9},
        model_name="claude-3-5-sonnet-20241022",
        headers={},  # Headers will be overridden by ClaudeApiHandler.__init__
        stream=False,
        api_type_config=mock_configs["api_type_config"],
        endpoint_config=mock_configs["endpoint_config"],
        max_tokens=256,
        dont_include_model=False,
    )
    return handler


def test_get_api_endpoint_url(claude_handler):
    """
    Verifies that the correct API endpoint URL is constructed.
    """
    expected_url = "https://api.anthropic.com/v1/messages"
    assert claude_handler._get_api_endpoint_url() == expected_url


def test_get_api_endpoint_url_with_trailing_slash(mock_configs):
    """
    Verifies that trailing slashes in base_url are handled correctly.
    """
    handler = ClaudeApiHandler(
        base_url="https://api.anthropic.com/",  # Note trailing slash
        api_key="test_api_key",
        gen_input={},
        model_name="claude-3-5-sonnet-20241022",
        headers={},
        stream=False,
        api_type_config=mock_configs["api_type_config"],
        endpoint_config=mock_configs["endpoint_config"],
        max_tokens=100,
        dont_include_model=False
    )
    # Should not have double slashes
    expected_url = "https://api.anthropic.com/v1/messages"
    assert handler._get_api_endpoint_url() == expected_url


def test_iterate_by_lines_property(claude_handler):
    """
    Verifies that the handler is configured for standard SSE streaming (not line-by-line).
    """
    assert not claude_handler._iterate_by_lines


def test_required_event_name_property(claude_handler):
    """
    Verifies that the handler filters for 'content_block_delta' events.
    """
    assert claude_handler._required_event_name == "content_block_delta"


def test_claude_headers_set_correctly(claude_handler):
    """
    Verifies that Claude-specific headers are set correctly.
    Claude API requires x-api-key and anthropic-version headers.
    """
    assert "x-api-key" in claude_handler.headers
    assert claude_handler.headers["x-api-key"] == "test_api_key"
    assert "anthropic-version" in claude_handler.headers
    assert claude_handler.headers["anthropic-version"] == "2023-06-01"
    assert "Content-Type" in claude_handler.headers
    assert claude_handler.headers["Content-Type"] == "application/json"
    # Should NOT have Authorization header (that's for OpenAI)
    assert "Authorization" not in claude_handler.headers


class TestPreparePayload:
    """
    Tests the _prepare_payload method, which relies on the base class implementation.
    """

    def test_basic_payload_structure(self, claude_handler):
        """
        Verifies that the payload is correctly structured with the model name,
        messages, and all generation parameters at the top level.
        """
        conversation = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hi!"}
        ]
        payload = claude_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None)
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        # Claude uses messages for conversation, system prompt goes in separate field
        assert "messages" in payload
        assert payload["temperature"] == 0.7
        assert payload["top_p"] == 0.9
        assert payload["max_tokens"] == 256
        assert payload["stream"] is False

    def test_payload_omits_model_when_configured(self, mock_configs):
        """
        Tests that the 'model' key is correctly omitted from the payload when
        the 'dont_include_model' flag is set to True.
        """
        handler = ClaudeApiHandler(
            base_url="https://api.anthropic.com",
            api_key="test_api_key",
            gen_input={},
            model_name="claude-3-5-sonnet-20241022",
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

    def test_system_message_extraction(self, claude_handler):
        """
        Tests that system messages are extracted from the messages array and
        placed in a separate 'system' parameter as required by Claude API.
        """
        conversation = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
        payload = claude_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None)

        # System message should be in separate 'system' parameter
        assert "system" in payload
        assert payload["system"] == "You are a helpful assistant."

        # Messages array should only contain user and assistant messages
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "Hello!"

    def test_multiple_system_messages_combined(self, claude_handler):
        """
        Tests that multiple system messages are combined into a single system parameter.
        """
        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi!"},
            {"role": "system", "content": "Be concise."}
        ]
        payload = claude_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None)

        # Multiple system messages should be combined
        assert "system" in payload
        assert payload["system"] == "You are helpful.\n\nBe concise."

        # Messages should only contain the user message
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    def test_no_system_message(self, claude_handler):
        """
        Tests that payload works correctly when there are no system messages.
        """
        conversation = [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ]
        payload = claude_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None)

        # Should not have a system parameter
        assert "system" not in payload

        # All messages should be in the messages array
        assert len(payload["messages"]) == 3


class TestParseNonStreamResponse:
    """
    Tests the _parse_non_stream_response method for handling complete, non-streaming responses.
    """

    def test_success_path(self, claude_handler):
        """
        Tests successful extraction of content from a valid response structure.
        """
        response_json = {
            'content': [{
                'type': 'text',
                'text': 'This is the expected response.'
            }]
        }
        result = claude_handler._parse_non_stream_response(response_json)
        assert result == 'This is the expected response.'

    def test_multiple_text_blocks(self, claude_handler):
        """
        Tests handling of a response with multiple text content blocks.
        """
        response_json = {
            'content': [
                {'type': 'text', 'text': 'First part. '},
                {'type': 'text', 'text': 'Second part.'}
            ]
        }
        result = claude_handler._parse_non_stream_response(response_json)
        assert result == 'First part. Second part.'

    def test_empty_content(self, claude_handler):
        """
        Tests handling of a response where the content array is empty.
        """
        response_json = {
            'content': []
        }
        result = claude_handler._parse_non_stream_response(response_json)
        assert result == ""

    def test_missing_content_key(self, claude_handler, mocker):
        """
        Tests handling of a response missing the 'content' key.
        """
        mock_logger_error = mocker.patch.object(
            logging.getLogger('Middleware.llmapis.handlers.impl.claude_api_handler'), 'error')

        response_json = {'id': 'msg_123'}
        result = claude_handler._parse_non_stream_response(response_json)

        assert result == ""
        mock_logger_error.assert_called_once()
        assert f"Could not find content in Claude response: {response_json}" in mock_logger_error.call_args[0][0]


class TestProcessStreamData:
    """
    Tests the _process_stream_data method for handling individual SSE data chunks.
    """

    def test_valid_data_chunk_with_content(self, claude_handler):
        """
        Tests parsing a standard streaming chunk that contains a text token.
        """
        data_str = json.dumps({
            "delta": {
                "type": "text_delta",
                "text": "Hello"
            }
        })
        expected = {'token': 'Hello', 'finish_reason': None}
        assert claude_handler._process_stream_data(data_str) == expected

    def test_data_chunk_with_empty_text(self, claude_handler):
        """
        Tests parsing a chunk with an empty text field.
        """
        data_str = json.dumps({
            "delta": {
                "type": "text_delta",
                "text": ""
            }
        })
        expected = {'token': '', 'finish_reason': None}
        assert claude_handler._process_stream_data(data_str) == expected

    def test_empty_data_string_input(self, claude_handler):
        """
        Tests that an empty data string returns None without error.
        """
        assert claude_handler._process_stream_data("") is None

    def test_invalid_json_string(self, claude_handler, mocker):
        """
        Tests that a non-JSON string is handled gracefully.
        """
        mock_logger_warning = mocker.patch.object(
            logging.getLogger('Middleware.llmapis.handlers.impl.claude_api_handler'), 'warning')
        data_str = "this is not json"
        result = claude_handler._process_stream_data(data_str)
        assert result is None
        mock_logger_warning.assert_called_once()
        assert f"Could not parse Claude stream data string: {data_str}" in mock_logger_warning.call_args[0][0]

    def test_json_missing_delta_key(self, claude_handler):
        """
        Tests that JSON missing the 'delta' key returns a default empty chunk
        due to the handler's defensive .get() calls.
        """
        malformed_json_str = '{"some_other_key": "value"}'
        expected_result = {'token': '', 'finish_reason': None}
        result = claude_handler._process_stream_data(malformed_json_str)
        assert result == expected_result

    def test_delta_missing_text_key(self, claude_handler):
        """
        Tests that a delta object missing the 'text' key returns an empty token.
        """
        data_str = json.dumps({
            "delta": {
                "type": "text_delta"
            }
        })
        expected_result = {'token': '', 'finish_reason': None}
        result = claude_handler._process_stream_data(data_str)
        assert result == expected_result
