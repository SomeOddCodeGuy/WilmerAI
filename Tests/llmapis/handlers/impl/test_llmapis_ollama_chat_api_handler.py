import json

import pytest

from Middleware.llmapis.handlers.impl.ollama_chat_api_handler import OllamaChatHandler


@pytest.fixture
def mock_handler_config():
    """
    Provides a common dictionary of mock configuration arguments for instantiating the handler.
    This fixture reduces code duplication across tests.
    """
    return {
        "base_url": "http://localhost:11434",
        "api_key": "ollama-key",
        "gen_input": {"temperature": 0.7, "top_p": 0.9, "num_predict": 512},
        "model_name": "llama3:latest",
        "headers": {"Content-Type": "application/json"},
        "api_type_config": {},
        "endpoint_config": {},
        "max_tokens": 512,
        "dont_include_model": False
    }


class TestOllamaChatHandler:
    """
    Test suite for the OllamaChatHandler class.
    """

    def test_iterate_by_lines_property(self, mock_handler_config):
        """
        Verifies that the _iterate_by_lines property correctly returns True,
        as Ollama uses a line-delimited JSON streaming format.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)

        assert handler._iterate_by_lines is True, "The handler should be configured to iterate by lines for Ollama streams."

    def test_get_api_endpoint_url(self, mock_handler_config):
        """
        Ensures the correct API endpoint URL is constructed for the /api/chat endpoint.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        expected_url = f"{mock_handler_config['base_url']}/api/chat"

        actual_url = handler._get_api_endpoint_url()

        assert actual_url == expected_url

    def test_prepare_payload_non_streaming(self, mock_handler_config, mocker):
        """
        Tests that for non-streaming requests, the payload is correctly structured
        with generation parameters in a nested 'options' object and includes "stream": False.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        mock_messages = [{"role": "user", "content": "Hello"}]
        # We mock the parent method to isolate the test to only the logic in this class
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hello")

        assert payload["model"] == mock_handler_config["model_name"]
        assert payload["messages"] == mock_messages
        assert payload["options"] == mock_handler_config["gen_input"]
        assert payload.get(
            "stream") is False, "Payload must explicitly include 'stream: False' for non-streaming calls."

    def test_prepare_payload_streaming(self, mock_handler_config, mocker):
        """
        Tests that for streaming requests, the 'stream' key is omitted from the payload,
        as streaming is the default behavior for the Ollama /api/chat endpoint.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        mock_messages = [{"role": "user", "content": "Hello"}]
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hello")

        assert "stream" not in payload, "The 'stream' key should be omitted for streaming calls to use the API default."
        assert payload["model"] == mock_handler_config["model_name"]
        assert payload["messages"] == mock_messages
        assert payload["options"] == mock_handler_config["gen_input"]

    def test_prepare_payload_exact_options_dict(self, mock_handler_config, mocker):
        """
        Asserts the exact contents of the payload and its nested 'options' dict,
        including the injected max-tokens and context-truncation fields.
        """
        mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", return_value=30)
        config = dict(mock_handler_config)
        config["gen_input"] = {"temperature": 0.7, "top_p": 0.9}
        config["api_type_config"] = {
            "maxNewTokensPropertyName": "num_predict",
            "truncateLengthPropertyName": "num_ctx",
        }
        config["endpoint_config"] = {"maxContextTokenSize": 4096}
        handler = OllamaChatHandler(**config, stream=False)
        mock_messages = [{"role": "user", "content": "Hello"}]
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hello")

        assert payload == {
            "model": "llama3:latest",
            "messages": mock_messages,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 512,
                "num_ctx": 4096,
            },
            "stream": False,
        }

    def test_prepare_payload_realistic_config_keeps_stream_out_of_options(self, mock_handler_config, mocker):
        """With the shipped config (streamPropertyName: "stream"), the injected stream
        key must not leak into 'options'; non-streaming sets stream only top-level."""
        mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", return_value=30)
        config = dict(mock_handler_config)
        config["gen_input"] = {"temperature": 0.7, "top_p": 0.9}
        config["api_type_config"] = {
            "maxNewTokensPropertyName": "num_predict",
            "truncateLengthPropertyName": "num_ctx",
            "streamPropertyName": "stream",
        }
        config["endpoint_config"] = {"maxContextTokenSize": 4096}
        handler = OllamaChatHandler(**config, stream=False)
        mock_messages = [{"role": "user", "content": "Hello"}]
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hello")

        assert payload == {
            "model": "llama3:latest",
            "messages": mock_messages,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 512,
                "num_ctx": 4096,
            },
            "stream": False,
        }

    def test_prepare_payload_realistic_config_streaming_no_stream_anywhere(self, mock_handler_config, mocker):
        """Streaming with the shipped config: no 'stream' key top-level (API default)
        and none inside 'options'."""
        mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", return_value=30)
        config = dict(mock_handler_config)
        config["gen_input"] = {"temperature": 0.7}
        config["api_type_config"] = {"streamPropertyName": "stream",
                                     "maxNewTokensPropertyName": "num_predict"}
        handler = OllamaChatHandler(**config, stream=True)
        mocker.patch.object(handler, '_build_messages_from_conversation',
                            return_value=[{"role": "user", "content": "Hi"}])

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hi")

        assert "stream" not in payload
        assert "stream" not in payload["options"]

    @pytest.mark.parametrize("data_str, expected_output", [
        # Standard token chunk
        (json.dumps({
            "message": {"role": "assistant", "content": "The sky"},
            "done": False
        }), {'token': 'The sky', 'finish_reason': None}),
        # Final chunk with content and done flag
        (json.dumps({
            "message": {"role": "assistant", "content": "."},
            "done": True
        }), {'token': '.', 'finish_reason': 'stop'}),
        # Final chunk with no content, only the done flag
        (json.dumps({
            "message": {"role": "assistant", "content": ""},
            "done": True
        }), {'token': '', 'finish_reason': 'stop'}),
    ])
    def test_process_stream_data_valid(self, mock_handler_config, data_str, expected_output):
        """
        Tests the parsing of various valid stream data chunks from Ollama.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        result = handler._process_stream_data(data_str)
        assert result == expected_output

    @pytest.mark.parametrize("data_str", [
        "",  # Empty string
        "{'invalid': 'json'}",  # Invalid JSON format that will raise a decode error
        "123",  # JSON that parses to a non-dict
        json.dumps({"message": 5}),  # Non-dict 'message' value
        json.dumps({"message": {"tool_calls": 5}}),  # Non-iterable tool_calls
    ])
    def test_process_stream_data_unparsable(self, mock_handler_config, data_str):
        """
        Ensures that unparsable, empty, or wrongly-shaped stream data correctly
        returns None instead of escaping as TypeError/AttributeError.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        result = handler._process_stream_data(data_str)
        assert result is None

    @pytest.mark.parametrize("data_str, expected_output", [
        # Malformed JSON: Missing 'message' key
        (json.dumps({"key": "value"}), {'token': '', 'finish_reason': None}),
        # Malformed JSON: Missing 'content' inside 'message'
        (json.dumps({"message": {}}), {'token': '', 'finish_reason': None}),
        # Malformed JSON: Missing 'done' key, but otherwise valid
        (json.dumps({"message": {"content": "test"}}), {'token': 'test', 'finish_reason': None}),
    ])
    def test_process_stream_data_malformed(self, mock_handler_config, data_str, expected_output):
        """
        Ensures that malformed but parsable JSON chunks are handled gracefully
        by returning a default "empty token" dictionary.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        result = handler._process_stream_data(data_str)
        assert result == expected_output

    def test_parse_non_stream_response_success(self, mock_handler_config):
        """
        Verifies that the text content is correctly extracted from a successful,
        complete non-streaming JSON response.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        response_json = {
            "message": {
                "role": "assistant",
                "content": "A complete and valid response."
            },
            "done": True
        }
        result = handler._parse_non_stream_response(response_json)
        assert result == "A complete and valid response."

    @pytest.mark.parametrize("response_json", [
        {},  # Empty dictionary
        {"message": {}},  # 'message' object is empty
        {"wrong_key": "value"},  # Missing 'message' key entirely
        {"message": {"content": None}},  # 'content' key is None
        {"message": "not-a-dict"},  # Non-dict 'message' value
    ])
    def test_parse_non_stream_response_key_error(self, mock_handler_config, response_json):
        """
        Ensures graceful failure (returns an empty string) when parsing malformed
        or incomplete non-streaming responses.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        result = handler._parse_non_stream_response(response_json)
        assert result == ""


class TestBuildMessagesFromConversation:
    """
    Tests the _build_messages_from_conversation method for the Ollama chat handler.
    """

    def test_images_key_passes_through(self, mock_handler_config):
        """
        Messages with an 'images' key should pass through unchanged.
        The Ollama API natively uses this format, so no conversion is needed.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "First", "images": ["base64data1"]},
            {"role": "assistant", "content": "I see."},
            {"role": "user", "content": "Second", "images": ["base64data2", "base64data3"]},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert len(result) == 3
        assert result[0]["images"] == ["base64data1"]
        assert "images" not in result[1]
        assert result[2]["images"] == ["base64data2", "base64data3"]

    def test_messages_without_images_unchanged(self, mock_handler_config):
        """Messages without images key pass through as normal text messages."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert len(result) == 2
        assert result[0]["content"] == "Hello"
        assert result[1]["content"] == "Hi"
        assert "images" not in result[0]
        assert "images" not in result[1]

    def test_add_text_to_start_of_system_applied(self, mock_handler_config):
        """The ollamaApiChat handler must honor addTextToStartOfSystem like the base
        chat builder does (regression: the override previously skipped injections)."""
        config = {**mock_handler_config,
                  "endpoint_config": {"addTextToStartOfSystem": True,
                                      "textToAddToStartOfSystem": "[PREFIX] "}}
        handler = OllamaChatHandler(**config, stream=False)
        conversation = [{"role": "system", "content": "You are an assistant."},
                        {"role": "user", "content": "Hi"}]
        result = handler._build_messages_from_conversation(conversation, None, None)
        assert result[0]["content"] == "[PREFIX] You are an assistant."

    def test_add_completion_text_applied(self, mock_handler_config):
        """addTextToStartOfCompletion must be appended for ollamaApiChat too."""
        config = {**mock_handler_config,
                  "endpoint_config": {"addTextToStartOfCompletion": True,
                                      "textToAddToStartOfCompletion": " /no_think"}}
        handler = OllamaChatHandler(**config, stream=False)
        conversation = [{"role": "user", "content": "Final prompt"}]
        result = handler._build_messages_from_conversation(conversation, None, None)
        assert result[-1]["content"].endswith(" /no_think")

    def test_injection_and_images_coexist(self, mock_handler_config):
        """Injections and per-message image handling both apply in one pass."""
        config = {**mock_handler_config,
                  "endpoint_config": {"addTextToStartOfSystem": True,
                                      "textToAddToStartOfSystem": "[SYS] "}}
        handler = OllamaChatHandler(**config, stream=False)
        conversation = [{"role": "system", "content": "Base."},
                        {"role": "user", "content": "Look", "images": ["data:image/png;base64,ABC"]}]
        result = handler._build_messages_from_conversation(conversation, None, None)
        assert result[0]["content"] == "[SYS] Base."
        # Image normalization (data-URI prefix stripped) still occurred.
        assert result[1]["images"] == ["ABC"]

    def test_systemmes_role_corrected_with_images(self, mock_handler_config):
        """The systemMes -> system role correction preserves the images key."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "systemMes", "content": "System note"},
            {"role": "user", "content": "Look", "images": ["img_data"]},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["role"] == "system"
        assert result[1]["images"] == ["img_data"]

    def test_images_stripped_from_non_user_messages(self, mock_handler_config):
        """Images key on assistant/system messages should be stripped."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Look at this", "images": ["user_img"]},
            {"role": "assistant", "content": "I see", "images": ["stray_data"]},
            {"role": "system", "content": "Note", "images": ["system_img"]},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["images"] == ["user_img"]
        assert "images" not in result[1]
        assert "images" not in result[2]

    def test_data_uri_prefix_stripped_from_user_images(self, mock_handler_config):
        """
        Data URIs on user messages are converted to the raw base64 that the
        Ollama API expects, while assistant-message images are stripped entirely.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Look", "images": ["data:image/png;base64,XXX"]},
            {"role": "assistant", "content": "I see", "images": ["data:image/png;base64,YYY"]},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["images"] == ["XXX"]
        assert "images" not in result[1]

    def test_raw_base64_user_images_left_unchanged(self, mock_handler_config):
        """Images without a data URI prefix pass through untouched."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Look", "images": ["rawbase64data"]},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["images"] == ["rawbase64data"]

    def test_trailing_empty_assistant_message_removed(self, mock_handler_config):
        """A trailing assistant message with empty content is dropped from the list."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": ""},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result == [{"role": "user", "content": "Hello"}]

    def test_trailing_empty_assistant_with_tool_calls_kept(self, mock_handler_config):
        """A trailing assistant message with empty content but tool_calls is the
        model's tool invocation, not the add_missing_assistant filler, and must
        not be dropped."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "calc", "arguments": "{}"}}]},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert len(result) == 2
        assert result[-1]["tool_calls"][0]["id"] == "call_1"

    def test_trailing_assistant_message_with_content_kept(self, mock_handler_config):
        """A trailing assistant message that has content is preserved."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

    def test_conversation_none_builds_from_system_and_prompt(self, mock_handler_config):
        """
        When conversation is None, the message list is constructed from the
        system_prompt and prompt arguments.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)

        result = handler._build_messages_from_conversation(None, "You are a bot.", "Hello!")

        assert result == [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hello!"},
        ]

    def test_conversation_none_with_prompt_only(self, mock_handler_config):
        """When conversation is None and only a prompt is given, no system message is added."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)

        result = handler._build_messages_from_conversation(None, None, "Hello!")

        assert result == [{"role": "user", "content": "Hello!"}]

    def test_wilmer_curly_sentinels_restored(self, mock_handler_config):
        """The Ollama override calls return_brackets itself (it does not share the
        base builder's call), so the WILMER curly sentinels must be restored to
        literal braces in this path too."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        conversation = [
            {"role": "user",
             "content": "Print __WILMER_L_CURLY__x__WILMER_R_CURLY__ please"},
        ]
        result = handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["content"] == "Print {x} please"


class TestProcessStreamDataToolCalls:
    """
    Tests for tool call extraction and OpenAI format conversion in streaming
    for the Ollama handler.
    """

    def test_stream_tool_calls_converted_to_openai_format(self, mock_handler_config, mocker):
        """
        Ollama tool calls (function.arguments as dict) should be converted to
        OpenAI format (arguments as JSON string, with id, type: "function", index).
        """
        fake_hex = "a1b2c3d4e5f6a1b2c3d4e5f6"
        mock_uuid = mocker.MagicMock()
        mock_uuid.hex = fake_hex
        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     return_value=mock_uuid)

        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        data_str = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "London"}
                    }
                }]
            },
            "done": False
        })
        result = handler._process_stream_data(data_str)
        assert 'tool_calls' in result
        tc = result['tool_calls'][0]
        assert tc['index'] == 0
        assert tc['id'] == f"call_{fake_hex[:24]}"
        assert tc['type'] == 'function'
        assert tc['function']['name'] == 'get_weather'
        assert tc['function']['arguments'] == json.dumps({"city": "London"})

    def test_stream_multiple_tool_calls(self, mock_handler_config, mocker):
        """
        Multiple tool calls in one chunk should all be converted with
        sequential indices.
        """
        hex_values = ["aaaa1111bbbb2222cccc3333", "dddd4444eeee5555ffff6666"]
        call_count = {"n": 0}

        def fake_uuid4():
            mock_u = mocker.MagicMock()
            mock_u.hex = hex_values[call_count["n"]]
            call_count["n"] += 1
            return mock_u

        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     side_effect=fake_uuid4)

        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        data_str = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "func_a", "arguments": {"x": 1}}},
                    {"function": {"name": "func_b", "arguments": {"y": 2}}}
                ]
            },
            "done": False
        })
        result = handler._process_stream_data(data_str)
        assert len(result['tool_calls']) == 2
        assert result['tool_calls'][0]['index'] == 0
        assert result['tool_calls'][0]['function']['name'] == 'func_a'
        assert result['tool_calls'][1]['index'] == 1
        assert result['tool_calls'][1]['function']['name'] == 'func_b'

    def test_stream_tool_calls_in_separate_chunks_get_distinct_indices(self, mock_handler_config):
        """Indices must continue across chunks within one stream: index-keyed
        delta accumulation (ours and OpenAI clients') would otherwise merge two
        distinct calls arriving in separate chunks into one garbled call."""
        handler = OllamaChatHandler(**mock_handler_config, stream=True)

        first = handler._process_stream_data(json.dumps({
            "message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "func_a", "arguments": {"x": 1}}}]},
            "done": False
        }))
        second = handler._process_stream_data(json.dumps({
            "message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "func_b", "arguments": {"y": 2}}}]},
            "done": False
        }))

        assert first['tool_calls'][0]['index'] == 0
        assert second['tool_calls'][0]['index'] == 1

    def test_stream_tool_calls_with_empty_arguments(self, mock_handler_config, mocker):
        """
        Empty arguments dict should become '{}' JSON string.
        """
        mock_uuid = mocker.MagicMock()
        mock_uuid.hex = "abcdef1234567890abcdef12"
        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     return_value=mock_uuid)

        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        data_str = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": "no_args_func", "arguments": {}}
                }]
            },
            "done": False
        })
        result = handler._process_stream_data(data_str)
        assert result['tool_calls'][0]['function']['arguments'] == '{}'

    def test_stream_done_chunk_with_tool_calls(self, mock_handler_config, mocker):
        """
        A single chunk carrying both 'done': true and tool_calls should yield
        finish_reason 'stop' AND the converted tool calls together.
        """
        fake_hex = "0011223344556677889900aa"
        mock_uuid = mocker.MagicMock()
        mock_uuid.hex = fake_hex
        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     return_value=mock_uuid)

        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        data_str = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "London"}
                    }
                }]
            },
            "done": True
        })
        result = handler._process_stream_data(data_str)

        assert result['finish_reason'] == 'stop'
        assert result['token'] == ''
        assert result['tool_calls'] == [{
            "index": 0,
            "id": f"call_{fake_hex[:24]}",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": json.dumps({"city": "London"})
            }
        }]

    def test_stream_no_tool_calls_no_key(self, mock_handler_config):
        """
        Normal chunks without tool_calls should NOT have 'tool_calls' key in result.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=True)
        data_str = json.dumps({
            "message": {"role": "assistant", "content": "Hello"},
            "done": False
        })
        result = handler._process_stream_data(data_str)
        assert 'tool_calls' not in result
        assert result['token'] == 'Hello'


class TestParseNonStreamResponseToolCalls:
    """
    Tests for non-streaming tool call extraction and conversion for Ollama.
    """

    def test_non_stream_tool_calls_converted_to_openai_format(self, mock_handler_config, mocker):
        """
        Non-streaming tool calls should be converted from Ollama format
        (arguments as dict) to OpenAI format (arguments as JSON string).
        """
        fake_hex = "112233445566778899aabbcc"
        mock_uuid = mocker.MagicMock()
        mock_uuid.hex = fake_hex
        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     return_value=mock_uuid)

        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        response_json = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Paris"}
                    }
                }]
            },
            "done": True
        }
        result = handler._parse_non_stream_response(response_json)
        assert isinstance(result, dict)
        tc = result['tool_calls'][0]
        assert tc['index'] == 0
        assert tc['id'] == f"call_{fake_hex[:24]}"
        assert tc['type'] == 'function'
        assert tc['function']['name'] == 'get_weather'
        assert tc['function']['arguments'] == json.dumps({"city": "Paris"})

    def test_non_stream_multiple_tool_calls(self, mock_handler_config, mocker):
        """
        Multiple tool calls should each get a unique id and sequential index.
        """
        hex_values = ["aaa111bbb222ccc333ddd444", "eee555fff666aaa777bbb888"]
        call_count = {"n": 0}

        def fake_uuid4():
            mock_u = mocker.MagicMock()
            mock_u.hex = hex_values[call_count["n"]]
            call_count["n"] += 1
            return mock_u

        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     side_effect=fake_uuid4)

        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        response_json = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "func_x", "arguments": {"a": 1}}},
                    {"function": {"name": "func_y", "arguments": {"b": 2}}}
                ]
            },
            "done": True
        }
        result = handler._parse_non_stream_response(response_json)
        assert len(result['tool_calls']) == 2
        assert result['tool_calls'][0]['index'] == 0
        assert result['tool_calls'][0]['id'] == f"call_{hex_values[0][:24]}"
        assert result['tool_calls'][1]['index'] == 1
        assert result['tool_calls'][1]['id'] == f"call_{hex_values[1][:24]}"

    def test_non_stream_tool_calls_finish_reason_is_tool_calls(self, mock_handler_config, mocker):
        """
        finish_reason should be "tool_calls" when tool calls are present.
        """
        mock_uuid = mocker.MagicMock()
        mock_uuid.hex = "deadbeefdeadbeefdeadbeef"
        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     return_value=mock_uuid)

        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        response_json = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": "some_func", "arguments": {}}
                }]
            },
            "done": True
        }
        result = handler._parse_non_stream_response(response_json)
        assert result['finish_reason'] == 'tool_calls'

    def test_non_stream_tool_calls_with_content(self, mock_handler_config, mocker):
        """
        Both content text and tool calls should be present in the returned dict.
        """
        mock_uuid = mocker.MagicMock()
        mock_uuid.hex = "cafe0123456789abcdef0123"
        mocker.patch("Middleware.llmapis.handlers.impl.ollama_chat_api_handler.uuid.uuid4",
                     return_value=mock_uuid)

        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        response_json = {
            "message": {
                "role": "assistant",
                "content": "Let me look that up.",
                "tool_calls": [{
                    "function": {"name": "search", "arguments": {"query": "test"}}
                }]
            },
            "done": True
        }
        result = handler._parse_non_stream_response(response_json)
        assert isinstance(result, dict)
        assert result['content'] == 'Let me look that up.'
        assert len(result['tool_calls']) == 1
        assert result['tool_calls'][0]['function']['name'] == 'search'

    def test_non_stream_no_tool_calls_returns_string(self, mock_handler_config):
        """
        Normal response without tool calls returns a plain string.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        response_json = {
            "message": {
                "role": "assistant",
                "content": "A normal text response."
            },
            "done": True
        }
        result = handler._parse_non_stream_response(response_json)
        assert isinstance(result, str)
        assert result == "A normal text response."


class TestPreparePayloadTools:
    """
    Tests for the Ollama handler's _prepare_payload method with tools parameter.
    """

    def test_tools_included_in_payload(self, mock_handler_config, mocker):
        """
        When tools param is provided, payload should have "tools" key.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        mock_messages = [{"role": "user", "content": "Hello"}]
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
                }
            }
        ]
        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hello", tools=tools)
        assert "tools" in payload
        assert payload["tools"] == tools

    def test_tools_not_included_when_none(self, mock_handler_config, mocker):
        """
        When tools is None, payload should NOT have "tools" key.
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        mock_messages = [{"role": "user", "content": "Hello"}]
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hello", tools=None)
        assert "tools" not in payload

    def test_tool_choice_ignored(self, mock_handler_config, mocker):
        """
        tool_choice should NOT appear in payload (Ollama doesn't support it).
        """
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        mock_messages = [{"role": "user", "content": "Hello"}]
        mocker.patch.object(handler, '_build_messages_from_conversation', return_value=mock_messages)

        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        payload = handler._prepare_payload(
            conversation=[], system_prompt=None, prompt="Hello",
            tools=tools, tool_choice="auto"
        )
        assert "tool_choice" not in payload
        assert "tools" in payload


class TestOllamaChatThinkParameter:
    """
    Ollama reads the reasoning toggle as a top-level 'think' field, not inside
    'options'. A preset's 'think' key must be lifted out of options to the top level.
    """

    @staticmethod
    def _config_with_think(base_config, think_value):
        config = dict(base_config)
        config["gen_input"] = {"temperature": 0.7, "think": think_value}
        return config

    def test_think_false_hoisted_to_top_level(self, mock_handler_config, mocker):
        """A 'think': false preset key becomes a top-level payload field, not an options field."""
        handler = OllamaChatHandler(**self._config_with_think(mock_handler_config, False), stream=False)
        mocker.patch.object(handler, '_build_messages_from_conversation',
                            return_value=[{"role": "user", "content": "Hi"}])

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hi")

        assert payload["think"] is False
        assert "think" not in payload["options"]
        assert payload["options"]["temperature"] == 0.7

    def test_think_true_hoisted_to_top_level(self, mock_handler_config, mocker):
        """A 'think': true preset key is hoisted the same way."""
        handler = OllamaChatHandler(**self._config_with_think(mock_handler_config, True), stream=True)
        mocker.patch.object(handler, '_build_messages_from_conversation',
                            return_value=[{"role": "user", "content": "Hi"}])

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hi")

        assert payload["think"] is True
        assert "think" not in payload["options"]

    def test_no_think_key_means_no_top_level_think(self, mock_handler_config, mocker):
        """When no preset sets 'think', the payload omits it entirely (Ollama default behavior)."""
        handler = OllamaChatHandler(**mock_handler_config, stream=False)
        mocker.patch.object(handler, '_build_messages_from_conversation',
                            return_value=[{"role": "user", "content": "Hi"}])

        payload = handler._prepare_payload(conversation=[], system_prompt=None, prompt="Hi")

        assert "think" not in payload
