# Tests/llmapis/handlers/impl/test_llmapis_openai_completions_api_handler.py

import json

import pytest

from Middleware.llmapis.handlers.impl.openai_completions_api_handler import OpenAiCompletionsApiHandler


@pytest.fixture
def handler_config():
    """Provides a baseline configuration for instantiating the handler."""
    return {
        "base_url": "https://api.test.local",
        "api_key": "test-key-123",
        "gen_input": {"temperature": 0.7, "top_p": 0.9},
        "model_name": "gpt-3.5-turbo-instruct",
        "headers": {"Authorization": "Bearer test-key-123"},
        "stream": False,
        "api_type_config": {},
        "endpoint_config": {},
        "max_tokens": 150,
        "dont_include_model": False
    }


@pytest.fixture
def handler(handler_config):
    """Returns a non-streaming instance of the OpenAiCompletionsApiHandler."""
    return OpenAiCompletionsApiHandler(**handler_config)


@pytest.fixture
def streaming_handler(handler_config):
    """Returns a streaming instance of the OpenAiCompletionsApiHandler."""
    handler_config['stream'] = True
    return OpenAiCompletionsApiHandler(**handler_config)


class TestOpenAiCompletionsApiHandler:
    """
    Unit tests for the OpenAiCompletionsApiHandler class.
    """

    # ##################################
    # ##### Initialization & Properties
    # ##################################

    def test_get_api_endpoint_url(self, handler):
        """
        Verifies that the correct API endpoint URL is constructed.
        """
        assert handler._get_api_endpoint_url() == "https://api.test.local/v1/completions"

    def test_iterate_by_lines_property(self, handler):
        """
        Verifies that the handler is configured for standard SSE streaming (not line-delimited).
        """
        assert not handler._iterate_by_lines

    def test_required_event_name_property(self, handler):
        """
        Verifies that the handler does not filter for a specific SSE event name.
        """
        assert handler._required_event_name is None

    # ##################################
    # ##### Payload Preparation
    # ##################################

    def test_prepare_payload_includes_model_by_default(self, mocker, handler):
        """
        Tests that _prepare_payload correctly calls the parent method and adds
        the 'model' key to the payload when not configured otherwise.
        """
        mock_super_prepare = mocker.patch(
            'Middleware.llmapis.handlers.base.base_completions_handler.BaseCompletionsHandler._prepare_payload',
            return_value={"prompt": "This is a test prompt", "temperature": 0.7}
        )

        conversation_args = (None, "System prompt", "User prompt")

        payload = handler._prepare_payload(*conversation_args)

        mock_super_prepare.assert_called_once_with(*conversation_args)

        assert "model" in payload
        assert payload["model"] == "gpt-3.5-turbo-instruct"
        assert payload["prompt"] == "This is a test prompt"
        assert payload["temperature"] == 0.7

    def test_prepare_payload_omits_model_when_configured(self, mocker, handler_config):
        """
        Tests that _prepare_payload omits the 'model' key if 'dont_include_model' is True.
        """
        handler_config['dont_include_model'] = True
        handler = OpenAiCompletionsApiHandler(**handler_config)

        mocker.patch(
            'Middleware.llmapis.handlers.base.base_completions_handler.BaseCompletionsHandler._prepare_payload',
            return_value={"prompt": "This is a test prompt", "temperature": 0.7}
        )

        payload = handler._prepare_payload(None, "System prompt", "User prompt")

        assert "model" not in payload
        assert payload["prompt"] == "This is a test prompt"

    def test_prepare_payload_unmocked_exact_payload(self, mocker, handler_config):
        """
        Tests _prepare_payload end-to-end (no parent mocking) with a realistic
        api_type_config, asserting the exact payload: model, flattened prompt,
        injected stream flag, and injected max_tokens.
        """
        mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", return_value=30)
        handler_config["api_type_config"] = {
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "max_tokens",
        }
        handler = OpenAiCompletionsApiHandler(**handler_config)

        payload = handler._prepare_payload(None, "You are a bot. ", "Hello!")

        assert payload == {
            "model": "gpt-3.5-turbo-instruct",
            "prompt": "You are a bot. Hello!",
            "temperature": 0.7,
            "top_p": 0.9,
            "stream": False,
            "max_tokens": 150,
        }

    # ##################################
    # ##### Non-Streaming Response Parsing
    # ##################################

    def test_parse_non_stream_response_success(self, handler):
        """
        Tests parsing a valid, successful non-streaming response.
        """
        response_json = {
            "id": "cmpl-123",
            "choices": [
                {"text": "\n\nThis is a test response.", "index": 0, "finish_reason": "length"}
            ]
        }
        result = handler._parse_non_stream_response(response_json)
        assert result == "\n\nThis is a test response."

    def test_parse_non_stream_response_with_empty_text(self, handler):
        """
        Tests parsing a valid response where the generated text is an empty string.
        """
        response_json = {
            "choices": [{"text": "", "index": 0, "finish_reason": "stop"}]
        }
        result = handler._parse_non_stream_response(response_json)
        assert result == ""

    def test_parse_non_stream_response_with_null_text(self, handler):
        """
        Tests parsing a valid response where the generated text is null.
        """
        response_json = {
            "choices": [{"text": None, "index": 0, "finish_reason": "stop"}]
        }
        result = handler._parse_non_stream_response(response_json)
        assert result == ""

    @pytest.mark.parametrize("malformed_response", [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"data": "some other structure"},
        {"choices": 5},
        {"choices": [5]},
    ])
    def test_parse_non_stream_response_handles_malformed_data(self, handler, malformed_response, mocker):
        """
        Tests that malformed or unexpected JSON structures are handled gracefully
        without raising an exception, returning an empty string.
        """
        mock_logger = mocker.patch('Middleware.llmapis.handlers.impl.openai_completions_api_handler.logger.error')
        result = handler._parse_non_stream_response(malformed_response)
        assert result == ""
        mock_logger.assert_called_once()

    # ##################################
    # ##### Streaming Response Parsing
    # ##################################

    @pytest.mark.parametrize("chunk_str, expected_dict", [
        (
                json.dumps({"choices": [{"text": "Hello", "finish_reason": None}]}),
                {'token': 'Hello', 'finish_reason': None}),
        (json.dumps({"choices": [{"text": " world!", "finish_reason": "stop"}]}),
         {'token': ' world!', 'finish_reason': 'stop'}),
        (json.dumps({"choices": [{"text": ""}]}), {'token': '', 'finish_reason': None}),
        (json.dumps({"choices": [{"finish_reason": "length"}]}), {'token': '', 'finish_reason': 'length'}),
    ])
    def test_process_stream_data_success(self, streaming_handler, chunk_str, expected_dict):
        """
        Tests parsing various valid streaming data chunks.
        """
        result = streaming_handler._process_stream_data(chunk_str)
        assert result == expected_dict

    @pytest.mark.parametrize("invalid_chunk_str", [
        "",
        "not a json string",
        '{"malformed": "json"}',
        json.dumps({}),
        json.dumps({"choices": []}),
        "123",
        '{"choices": 5}',
        '{"choices": ["x"]}',
    ])
    def test_process_stream_data_handles_invalid_chunks(self, streaming_handler, invalid_chunk_str, mocker):
        """
        Tests that invalid or malformed stream chunks are handled gracefully.
        """
        mock_logger = mocker.patch('Middleware.llmapis.handlers.impl.openai_completions_api_handler.logger.warning')
        result = streaming_handler._process_stream_data(invalid_chunk_str)
        assert result is None
        if invalid_chunk_str:
            mock_logger.assert_called_once()

    # ##################################
    # ##### End-to-End Streaming
    # ##################################

    def test_handle_streaming_yields_tokens_and_skips_done_marker(self, mocker, handler_config):
        """
        Tests handle_streaming end-to-end against a mocked SSE response whose
        stream includes a 'data: [DONE]' terminator line. The token chunks are
        yielded in order and the [DONE] line is skipped without error.
        """
        mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", return_value=30)
        handler_config["stream"] = True
        handler_config["api_type_config"] = {
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "max_tokens",
        }
        handler = OpenAiCompletionsApiHandler(**handler_config)

        sse_lines = [
            "data: " + json.dumps({"choices": [{"text": "Hello", "finish_reason": None}]}),
            "",
            "data: " + json.dumps({"choices": [{"text": " world", "finish_reason": None}]}),
            "data: [DONE]",
        ]
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = iter(sse_lines)
        mock_post = mocker.patch.object(handler.session, "post")
        mock_post.return_value.__enter__.return_value = mock_response

        results = list(handler.handle_streaming(system_prompt="You are a bot. ", prompt="Hello!"))

        assert results == [
            {"token": "Hello", "finish_reason": None},
            {"token": " world", "finish_reason": None},
        ]
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["json"]["stream"] is True
        assert mock_post.call_args.args[0] == "https://api.test.local/v1/completions"
