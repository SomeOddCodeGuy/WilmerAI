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
        The _build_fallback_conversation method should strip leftover
        images keys from all messages when cleaning up after an error.
        """
        messages = [
            {"role": "user", "content": "Hello", "images": ["leftover_data"]},
            {"role": "user", "content": "World"},
        ]
        result = openai_handler._build_fallback_conversation(messages)

        for msg in result:
            assert "images" not in msg

    def test_fallback_reverts_multimodal_content_to_string(self, openai_handler):
        """
        The _build_fallback_conversation method should revert partially converted
        multimodal content back to plain text strings.
        """
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "Original text"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
            ], "images": ["stray"]},
            {"role": "user", "content": "Follow-up"},
        ]
        result = openai_handler._build_fallback_conversation(messages)

        assert result[0]["content"] == "Original text"
        assert "images" not in result[0]
        assert "error processing" in result[1]["content"]
