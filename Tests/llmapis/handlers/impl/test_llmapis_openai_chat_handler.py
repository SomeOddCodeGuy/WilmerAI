import base64
import io
import json
import logging

import pytest
from PIL import Image

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
        ({'choices': [{'message': 'not-a-dict'}]}, "response with a non-dict message"),
        ({'choices': 5}, "response with a non-list choices value"),
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

    def test_message_missing_content_key_returns_empty_string(self, openai_handler):
        """
        Tests that a message dict with no 'content' key returns an empty string
        without raising an error, since .get() handles the missing key gracefully.
        """
        response_json = {'choices': [{'message': {}}]}
        result = openai_handler._parse_non_stream_response(response_json)
        assert result == ""


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

    @pytest.mark.parametrize("non_dict_chunk", ["123", '["a"]', '{"choices": 5}', '{"choices": [5]}'])
    def test_non_dict_json_chunks_are_skipped_not_fatal(self, openai_handler, non_dict_chunk, mocker):
        """
        Tests that chunks whose JSON is not the expected dict shape are warned
        and skipped instead of escaping as TypeError/AttributeError.
        """
        mock_logger_warning = mocker.patch.object(
            logging.getLogger('Middleware.llmapis.handlers.impl.openai_api_handler'), 'warning')
        assert openai_handler._process_stream_data(non_dict_chunk) is None
        mock_logger_warning.assert_called_once()


class TestBuildMessagesFromConversation:
    """
    Tests the _build_messages_from_conversation method, which processes
    per-message image data into OpenAI's multimodal content format.
    """

    def test_no_images_returns_standard_messages(self, openai_handler):
        """Messages without images key pass through as standard text messages."""
        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there."},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)
        assert len(result) == 3
        assert all(isinstance(msg["content"], str) for msg in result)

    def test_per_message_images_attached_to_originating_message(self, openai_handler, mocker):
        """
        Images on message 0 and message 2 should end up as multimodal content
        on those exact messages, not on the last user message.
        """
        mocker.patch.object(openai_handler, '_process_single_image_source',
                            side_effect=lambda src: {"type": "image_url", "image_url": {"url": src}})

        conversation = [
            {"role": "user", "content": "First image", "images": ["http://example.local/img1.png"]},
            {"role": "assistant", "content": "I see."},
            {"role": "user", "content": "Second image", "images": ["http://example.local/img2.png"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0] == {"type": "text", "text": "First image"}
        assert result[0]["content"][1] == {"type": "image_url", "image_url": {"url": "http://example.local/img1.png"}}

        assert result[1]["content"] == "I see."

        assert isinstance(result[2]["content"], list)
        assert result[2]["content"][0] == {"type": "text", "text": "Second image"}
        assert result[2]["content"][1] == {"type": "image_url", "image_url": {"url": "http://example.local/img2.png"}}

    def test_multiple_images_on_single_message(self, openai_handler, mocker):
        """Multiple images on a single message all get attached to that message."""
        mocker.patch.object(openai_handler, '_process_single_image_source',
                            side_effect=lambda src: {"type": "image_url", "image_url": {"url": src}})

        conversation = [
            {"role": "user", "content": "Two images",
             "images": ["http://example.local/a.png", "http://example.local/b.png"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 3
        assert result[0]["content"][0]["type"] == "text"
        assert result[0]["content"][1]["image_url"]["url"] == "http://example.local/a.png"
        assert result[0]["content"][2]["image_url"]["url"] == "http://example.local/b.png"

    def test_images_key_stripped_from_non_user_messages(self, openai_handler, mocker):
        """
        If a non-user message somehow has an images key, it should be stripped
        (not converted to multimodal format).
        """
        mocker.patch.object(openai_handler, '_process_single_image_source',
                            side_effect=lambda src: {"type": "image_url", "image_url": {"url": src}})

        conversation = [
            {"role": "user", "content": "Look", "images": ["http://example.local/img.png"]},
            {"role": "assistant", "content": "I see it", "images": ["stray_data"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert "images" not in result[1]
        assert result[1]["content"] == "I see it"

    def test_invalid_image_source_skipped(self, openai_handler, mocker):
        """
        When _process_single_image_source returns None for an image,
        that image is skipped but the message is still processed.
        """
        mocker.patch.object(openai_handler, '_process_single_image_source',
                            side_effect=[None, {"type": "image_url", "image_url": {"url": "valid"}}])

        conversation = [
            {"role": "user", "content": "Mixed", "images": ["bad_source", "good_source"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][1]["image_url"]["url"] == "valid"

    def test_all_image_sources_invalid_keeps_string_content(self, openai_handler, mocker):
        """
        When all image sources are invalid, content stays as a string
        since image_contents is empty.
        """
        mocker.patch.object(openai_handler, '_process_single_image_source', return_value=None)

        conversation = [
            {"role": "user", "content": "Look at this", "images": ["bad1", "bad2"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["content"] == "Look at this"
        assert "images" not in result[0]

    def test_data_uri_image_format(self, openai_handler):
        """A data URI image is passed through directly by _process_single_image_source."""
        conversation = [
            {"role": "user", "content": "Image here",
             "images": ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][1]["type"] == "image_url"
        assert result[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="

    def test_http_url_image_format(self, openai_handler):
        """An HTTP URL image is passed through directly."""
        conversation = [
            {"role": "user", "content": "Image here",
             "images": ["https://example.local/photo.jpg"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][1]["type"] == "image_url"
        assert result[0]["content"][1]["image_url"]["url"] == "https://example.local/photo.jpg"

    def test_fallback_strips_images_keys(self, openai_handler):
        """
        The shared text-only fallback should strip leftover
        images keys from all messages when cleaning up after an error.
        """
        from Middleware.llmapis.handlers.base.image_injection import build_text_only_fallback
        messages = [
            {"role": "user", "content": "Hello", "images": ["leftover_data"]},
            {"role": "user", "content": "World"},
        ]
        result = build_text_only_fallback(messages, "unused fallback text")

        for msg in result:
            assert "images" not in msg

    def test_fallback_reverts_multimodal_content_to_string(self, openai_handler):
        """
        The shared text-only fallback should revert partially converted
        multimodal content back to plain text strings.
        """
        from Middleware.llmapis.handlers.base.image_injection import build_text_only_fallback
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "Original text"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
            ], "images": ["stray"]},
            {"role": "user", "content": "Follow-up"},
        ]
        result = build_text_only_fallback(messages, "unused fallback text")

        assert result[0]["content"] == "Original text"
        assert "images" not in result[0]
        assert result[1]["content"] == (
            "Follow-up\n\n[System note: There was an error processing the provided image(s). "
            "I will respond based on the text alone.]"
        )

    def test_image_processing_error_routes_to_fallback(self, openai_handler, mocker):
        """
        When _process_single_image_source raises, _build_messages_from_conversation
        must route through the shared text-only fallback and return a text-only
        conversation with the system note appended to the last user message.
        """
        mocker.patch.object(openai_handler, '_process_single_image_source',
                            side_effect=RuntimeError("image processing exploded"))

        conversation = [
            {"role": "assistant", "content": "Earlier reply."},
            {"role": "user", "content": "Look at this", "images": ["data:image/png;base64,abc"]},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assert all(isinstance(msg["content"], str) for msg in result)
        assert all("images" not in msg for msg in result)
        assert result[-1]["content"] == (
            "Look at this\n\n[System note: There was an error processing the provided image(s). "
            "I will respond based on the text alone.]"
        )

    def test_assistant_empty_tool_calls_key_stripped(self, openai_handler):
        """
        Assistant messages replayed with an empty tool_calls array must have the
        key removed before hitting the payload: the OpenAI API rejects an
        assistant message whose tool_calls is []. Content is preserved.
        """
        conversation = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Earlier reply.", "tool_calls": []},
            {"role": "user", "content": "Continue"},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assistant = [m for m in result if m["role"] == "assistant"][0]
        assert "tool_calls" not in assistant
        assert assistant["content"] == "Earlier reply."

    def test_assistant_null_tool_calls_key_stripped(self, openai_handler):
        """A null tool_calls value on an assistant message is residue too, so it is stripped."""
        conversation = [
            {"role": "assistant", "content": "Earlier reply.", "tool_calls": None},
            {"role": "user", "content": "Continue"},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assistant = [m for m in result if m["role"] == "assistant"][0]
        assert "tool_calls" not in assistant

    def test_assistant_populated_tool_calls_preserved(self, openai_handler):
        """
        A populated tool_calls list is a real tool round-trip and must pass
        through untouched; stripping it would break tool-result replays.
        """
        tool_calls = [{"id": "call_1", "type": "function",
                       "function": {"name": "get_weather", "arguments": "{}"}}]
        conversation = [
            {"role": "assistant", "content": "", "tool_calls": tool_calls},
            {"role": "tool", "content": "72F", "tool_call_id": "call_1"},
            {"role": "user", "content": "Thanks"},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        assistant = [m for m in result if m["role"] == "assistant"][0]
        assert assistant["tool_calls"] == tool_calls

    def test_non_assistant_empty_tool_calls_untouched(self, openai_handler):
        """The strip is assistant-only; other roles pass through unmodified."""
        conversation = [
            {"role": "user", "content": "Hi", "tool_calls": []},
        ]
        result = openai_handler._build_messages_from_conversation(conversation, None, None)

        user = [m for m in result if m["role"] == "user"][0]
        assert user.get("tool_calls") == []


class TestProcessSingleImageSource:
    """
    Tests the _process_single_image_source static method, which converts
    various image source formats into OpenAI image_url content blocks.
    """

    def test_data_uri_passed_through(self):
        """A data URI is wrapped directly without re-encoding."""
        source = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
        result = OpenAiApiHandler._process_single_image_source(source)
        assert result == {"type": "image_url", "image_url": {"url": source}}

    def test_file_uri_returns_none(self):
        """File URIs are rejected for security reasons (no local file reads)."""
        result = OpenAiApiHandler._process_single_image_source("file:///etc/passwd")
        assert result is None

    def test_raw_base64_becomes_data_uri_with_detected_format(self):
        """
        A raw base64 image is decoded, its format detected via PIL, and wrapped
        in a data URI with the matching MIME type.
        """
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), color=(255, 0, 0)).save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        assert len(b64) >= 100, "Guard: source must be long enough to pass the base64 heuristic"

        result = OpenAiApiHandler._process_single_image_source(b64)

        assert result == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}

    def test_base64_that_is_not_an_image_returns_none(self):
        """Valid base64 that decodes to non-image bytes is skipped (PIL cannot identify it)."""
        source = "A" * 200
        result = OpenAiApiHandler._process_single_image_source(source)
        assert result is None

    def test_http_url_passed_through(self):
        """An HTTP URL is wrapped directly as an image_url block."""
        source = "http://example.local/photo.jpg"
        result = OpenAiApiHandler._process_single_image_source(source)
        assert result == {"type": "image_url", "image_url": {"url": source}}

    def test_https_url_passed_through(self):
        """An HTTPS URL is wrapped directly as an image_url block."""
        source = "https://example.local/photo.jpg"
        result = OpenAiApiHandler._process_single_image_source(source)
        assert result == {"type": "image_url", "image_url": {"url": source}}

    def test_short_string_returns_none(self):
        """A string shorter than 100 chars is not treated as base64."""
        result = OpenAiApiHandler._process_single_image_source("AAAA")
        assert result is None

    def test_invalid_base64_chars_returns_none(self):
        """A long string with invalid base64 characters is unrecognized."""
        result = OpenAiApiHandler._process_single_image_source("!" * 200)
        assert result is None

    def test_non_mod4_length_returns_none(self):
        """A string whose length is not a multiple of 4 fails the base64 heuristic."""
        result = OpenAiApiHandler._process_single_image_source("A" * 201)
        assert result is None


class TestPreparePayloadTools:
    """
    Tests that tools and tool_choice are included in the payload when set
    and absent when None.
    """

    def test_tools_and_tool_choice_included_when_set(self, openai_handler):
        conversation = [{"role": "user", "content": "Hi!"}]
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
        payload = openai_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None,
                                                  tools=tools, tool_choice="auto")
        assert payload["tools"] == tools
        assert payload["tool_choice"] == "auto"

    def test_tools_and_tool_choice_absent_when_none(self, openai_handler):
        conversation = [{"role": "user", "content": "Hi!"}]
        payload = openai_handler._prepare_payload(conversation=conversation, system_prompt=None, prompt=None,
                                                  tools=None, tool_choice=None)
        assert "tools" not in payload
        assert "tool_choice" not in payload


class TestProcessStreamDataToolCalls:
    """
    Tests for tool call extraction in streaming mode for the OpenAI backend handler.
    """

    def test_tool_call_initial_chunk(self, openai_handler):
        """
        A chunk with delta.tool_calls containing the initial tool call
        (index, id, type, function name) should include tool_calls in the result dict.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": ""}
                    }]
                },
                "finish_reason": None
            }]
        })
        result = openai_handler._process_stream_data(data_str)
        assert 'tool_calls' in result
        assert len(result['tool_calls']) == 1
        assert result['tool_calls'][0]['id'] == 'call_abc123'
        assert result['tool_calls'][0]['type'] == 'function'
        assert result['tool_calls'][0]['function']['name'] == 'get_weather'
        assert result['token'] == ''
        assert result['finish_reason'] is None

    def test_tool_call_argument_fragment(self, openai_handler):
        """
        A chunk with delta.tool_calls containing just an argument fragment
        should pass it through in the result.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": '{"loc'}
                    }]
                },
                "finish_reason": None
            }]
        })
        result = openai_handler._process_stream_data(data_str)
        assert 'tool_calls' in result
        assert result['tool_calls'][0]['function']['arguments'] == '{"loc'
        assert result['token'] == ''

    def test_tool_call_finish_reason_tool_calls(self, openai_handler):
        """
        When finish_reason is "tool_calls", it should be passed through in the result.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {},
                "finish_reason": "tool_calls"
            }]
        })
        result = openai_handler._process_stream_data(data_str)
        assert result['finish_reason'] == 'tool_calls'
        assert result['token'] == ''

    def test_tool_call_with_content(self, openai_handler):
        """
        A chunk with both content text AND tool_calls should include both in the result.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {
                    "content": "Let me check",
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_xyz",
                        "type": "function",
                        "function": {"name": "search", "arguments": ""}
                    }]
                },
                "finish_reason": None
            }]
        })
        result = openai_handler._process_stream_data(data_str)
        assert result['token'] == 'Let me check'
        assert 'tool_calls' in result
        assert result['tool_calls'][0]['function']['name'] == 'search'

    def test_no_tool_calls_key_in_normal_chunk(self, openai_handler):
        """
        Normal text chunks should NOT have a 'tool_calls' key in the result dict at all.
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {"content": "Hello world"},
                "finish_reason": None
            }]
        })
        result = openai_handler._process_stream_data(data_str)
        assert 'tool_calls' not in result
        assert result['token'] == 'Hello world'

    def test_empty_tool_calls_list_on_delta_not_forwarded(self, openai_handler):
        """
        Some OpenAI-compatible backends attach 'tool_calls': [] to ordinary text
        deltas. Forwarding the empty list would make the streaming layer treat
        plain text as a tool-call chunk, so it must be dropped and the text
        token kept (regression pin for the falsy-check in _process_stream_data).
        """
        data_str = json.dumps({
            "choices": [{
                "delta": {"content": "Hello", "tool_calls": []},
                "finish_reason": None
            }]
        })
        result = openai_handler._process_stream_data(data_str)
        assert result == {'token': 'Hello', 'finish_reason': None}
        assert 'tool_calls' not in result


class TestParseNonStreamResponseToolCalls:
    """
    Tests for tool call extraction in non-streaming mode for the OpenAI backend handler.
    """

    def test_tool_calls_present_returns_dict(self, openai_handler):
        """
        When response has tool_calls, should return a dict with 'content',
        'tool_calls', and 'finish_reason' keys.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': '',
                    'tool_calls': [
                        {
                            'id': 'call_abc',
                            'type': 'function',
                            'function': {'name': 'get_weather', 'arguments': '{"city": "London"}'}
                        }
                    ]
                },
                'finish_reason': 'tool_calls'
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert isinstance(result, dict)
        assert 'content' in result
        assert 'tool_calls' in result
        assert 'finish_reason' in result
        assert len(result['tool_calls']) == 1
        assert result['tool_calls'][0]['function']['name'] == 'get_weather'

    def test_tool_calls_with_content(self, openai_handler):
        """
        Tool calls response with both content text and tool_calls should
        include both in the returned dict.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': 'I will look that up for you.',
                    'tool_calls': [
                        {
                            'id': 'call_def',
                            'type': 'function',
                            'function': {'name': 'search', 'arguments': '{"q": "test"}'}
                        }
                    ]
                },
                'finish_reason': 'tool_calls'
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert isinstance(result, dict)
        assert result['content'] == 'I will look that up for you.'
        assert result['tool_calls'][0]['function']['name'] == 'search'

    def test_tool_calls_finish_reason_from_response(self, openai_handler):
        """
        finish_reason should come from the response JSON's choices[0].finish_reason.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': '',
                    'tool_calls': [
                        {
                            'id': 'call_ghi',
                            'type': 'function',
                            'function': {'name': 'calculate', 'arguments': '{"x": 1}'}
                        }
                    ]
                },
                'finish_reason': 'tool_calls'
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert result['finish_reason'] == 'tool_calls'

    def test_tool_calls_null_content(self, openai_handler):
        """
        When content is null but tool_calls are present, content should be empty string.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': None,
                    'tool_calls': [
                        {
                            'id': 'call_jkl',
                            'type': 'function',
                            'function': {'name': 'lookup', 'arguments': '{}'}
                        }
                    ]
                },
                'finish_reason': 'tool_calls'
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert isinstance(result, dict)
        assert result['content'] == ''
        assert len(result['tool_calls']) == 1

    def test_no_tool_calls_returns_string(self, openai_handler):
        """
        Normal text response without tool_calls returns a plain string,
        preserving existing behavior.
        """
        response_json = {
            'choices': [{
                'message': {
                    'content': 'Just a normal response.'
                },
                'finish_reason': 'stop'
            }]
        }
        result = openai_handler._parse_non_stream_response(response_json)
        assert isinstance(result, str)
        assert result == 'Just a normal response.'
