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
    ])
    def test_process_stream_data_unparsable(self, mock_handler_config, data_str):
        """
        Ensures that unparsable or empty stream data correctly returns None.
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
