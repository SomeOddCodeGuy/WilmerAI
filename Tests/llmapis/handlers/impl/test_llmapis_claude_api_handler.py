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
            "endpoint": "https://api.anthropic.local",
            "apiTypeConfigFileName": "Claude",
        }
    }


@pytest.fixture
def claude_handler(mock_configs):
    """Creates an instance of ClaudeApiHandler with mocked configurations."""
    handler = ClaudeApiHandler(
        base_url="https://api.anthropic.local",
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
    expected_url = "https://api.anthropic.local/v1/messages"
    assert claude_handler._get_api_endpoint_url() == expected_url


def test_get_api_endpoint_url_with_trailing_slash(mock_configs):
    """
    Verifies that trailing slashes in base_url are handled correctly.
    """
    handler = ClaudeApiHandler(
        base_url="https://api.anthropic.local/",  # Note trailing slash
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
    expected_url = "https://api.anthropic.local/v1/messages"
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
            base_url="https://api.anthropic.local",
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


class TestProcessSingleImageSource:
    """
    Tests the _process_single_image_source static method, which converts
    various image source formats into Claude API image content blocks.
    """

    def test_data_uri_png(self):
        """A PNG data URI is parsed into a Claude base64 image block."""
        source = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "iVBORw0KGgoAAAANSUhEUg==",
            }
        }

    def test_data_uri_jpeg(self):
        """A JPEG data URI is parsed correctly."""
        source = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result["source"]["media_type"] == "image/jpeg"
        assert result["source"]["data"] == "/9j/4AAQSkZJRg=="

    def test_data_uri_webp(self):
        """A WebP data URI is parsed correctly."""
        source = "data:image/webp;base64,UklGRlYA"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result["source"]["media_type"] == "image/webp"
        assert result["source"]["data"] == "UklGRlYA"

    def test_data_uri_gif(self):
        """A GIF data URI is parsed correctly."""
        source = "data:image/gif;base64,R0lGODlhAQ=="
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result["source"]["media_type"] == "image/gif"

    def test_data_uri_svg_xml(self):
        """A data URI with image/svg+xml MIME type is parsed correctly."""
        source = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0i"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is not None
        assert result["source"]["media_type"] == "image/svg+xml"
        assert result["source"]["data"] == "PHN2ZyB4bWxucz0i"

    def test_data_uri_vnd_mime(self):
        """A data URI with a vendor MIME subtype containing dots is parsed correctly."""
        source = "data:image/vnd.microsoft.icon;base64,AAABAAEAEBAAAAEAIAAo"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is not None
        assert result["source"]["media_type"] == "image/vnd.microsoft.icon"

    def test_data_uri_malformed_returns_none(self):
        """A data URI that doesn't match the expected pattern returns None."""
        source = "data:image/png;notbase64,somedata"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is None

    def test_https_url(self):
        """An HTTPS URL is converted to a Claude URL source block."""
        source = "https://example.local/photo.jpg"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result == {
            "type": "image",
            "source": {
                "type": "url",
                "url": "https://example.local/photo.jpg",
            }
        }

    def test_http_url(self):
        """An HTTP URL is converted to a Claude URL source block."""
        source = "http://example.local/photo.jpg"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result == {
            "type": "image",
            "source": {
                "type": "url",
                "url": "http://example.local/photo.jpg",
            }
        }

    def test_raw_base64_string(self):
        """A long raw base64 string is detected and wrapped as JPEG."""
        source = "A" * 200
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": source,
            }
        }

    def test_raw_base64_with_padding(self):
        """A base64 string with padding chars is handled correctly."""
        source = "A" * 198 + "=="
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is not None
        assert result["source"]["data"] == source

    def test_short_string_returns_none(self):
        """A string shorter than 100 chars is not treated as base64."""
        source = "AAAA"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is None

    def test_invalid_base64_chars_returns_none(self):
        """A long string with invalid base64 characters returns None."""
        source = "!" * 200
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is None

    def test_non_mod4_length_returns_none(self):
        """A string whose length is not a multiple of 4 returns None."""
        source = "A" * 201  # 201 % 4 != 0
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is None

    def test_empty_string_returns_none(self):
        """An empty string returns None."""
        result = ClaudeApiHandler._process_single_image_source("")
        assert result is None

    def test_file_uri_returns_none(self):
        """File URIs are not supported by the Claude handler and return None."""
        source = "file:///path/to/image.png"
        result = ClaudeApiHandler._process_single_image_source(source)
        assert result is None


class TestBuildMessagesFromConversation:
    """
    Tests the _build_messages_from_conversation method, which processes
    per-message image data into Claude's multimodal content format.
    """

    def test_no_images_returns_standard_messages(self, claude_handler):
        """Messages without images key pass through as standard text messages."""
        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there."},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)
        assert len(result) == 3
        assert all(isinstance(msg["content"], str) for msg in result)

    def test_single_image_on_user_message(self, claude_handler, mocker):
        """A single image on a user message creates multimodal content."""
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            return_value={"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc123"}}
        )

        conversation = [
            {"role": "user", "content": "Describe this", "images": ["some_base64_data"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        # Images should come BEFORE text (Claude recommendation)
        assert result[0]["content"][0]["type"] == "image"
        assert result[0]["content"][0]["source"]["data"] == "abc123"
        assert result[0]["content"][1] == {"type": "text", "text": "Describe this"}

    def test_multiple_images_on_single_message(self, claude_handler, mocker):
        """Multiple images on a single message all get attached."""
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            side_effect=[
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "img1"}},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "img2"}},
            ]
        )

        conversation = [
            {"role": "user", "content": "Two images", "images": ["data1", "data2"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 3
        assert result[0]["content"][0]["type"] == "image"
        assert result[0]["content"][1]["type"] == "image"
        assert result[0]["content"][2]["type"] == "text"

    def test_images_on_multiple_messages(self, claude_handler, mocker):
        """Images on different messages are attached to their originating messages."""
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            side_effect=[
                {"type": "image", "source": {"type": "url", "url": "https://example.local/1.png"}},
                {"type": "image", "source": {"type": "url", "url": "https://example.local/2.png"}},
            ]
        )

        conversation = [
            {"role": "user", "content": "First", "images": ["https://example.local/1.png"]},
            {"role": "assistant", "content": "I see."},
            {"role": "user", "content": "Second", "images": ["https://example.local/2.png"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["source"]["url"] == "https://example.local/1.png"
        assert result[0]["content"][1]["text"] == "First"

        assert result[1]["content"] == "I see."

        assert isinstance(result[2]["content"], list)
        assert result[2]["content"][0]["source"]["url"] == "https://example.local/2.png"
        assert result[2]["content"][1]["text"] == "Second"

    def test_images_stripped_from_non_user_messages(self, claude_handler, mocker):
        """Images key on assistant messages should be stripped, not converted."""
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            return_value={"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}}
        )

        conversation = [
            {"role": "user", "content": "Look", "images": ["img_data"]},
            {"role": "assistant", "content": "I see", "images": ["stray_data"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert "images" not in result[1]
        assert result[1]["content"] == "I see"

    def test_invalid_image_source_skipped(self, claude_handler, mocker):
        """When _process_single_image_source returns None, that image is skipped."""
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            side_effect=[None, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "ok"}}]
        )

        conversation = [
            {"role": "user", "content": "Mixed", "images": ["bad_source", "good_source"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0]["type"] == "image"
        assert result[0]["content"][1]["type"] == "text"

    def test_all_image_sources_invalid_keeps_string_content(self, claude_handler, mocker):
        """When all image sources fail, content stays as a plain string."""
        mocker.patch.object(ClaudeApiHandler, '_process_single_image_source', return_value=None)

        conversation = [
            {"role": "user", "content": "Look at this", "images": ["bad1", "bad2"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["content"] == "Look at this"
        assert "images" not in result[0]

    def test_data_uri_image_end_to_end(self, claude_handler):
        """End-to-end test: a data URI is converted to Claude's base64 format."""
        conversation = [
            {"role": "user", "content": "What is this?",
             "images": ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        img_block = result[0]["content"][0]
        assert img_block["type"] == "image"
        assert img_block["source"]["type"] == "base64"
        assert img_block["source"]["media_type"] == "image/png"
        assert img_block["source"]["data"] == "iVBORw0KGgoAAAANSUhEUg=="

    def test_url_image_end_to_end(self, claude_handler):
        """End-to-end test: an HTTPS URL is converted to Claude's URL source format."""
        conversation = [
            {"role": "user", "content": "Describe",
             "images": ["https://example.local/photo.jpg"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], list)
        img_block = result[0]["content"][0]
        assert img_block["type"] == "image"
        assert img_block["source"]["type"] == "url"
        assert img_block["source"]["url"] == "https://example.local/photo.jpg"

    def test_error_during_processing_falls_back_to_text(self, claude_handler, mocker):
        """If image processing raises an exception, messages fall back to text-only."""
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            side_effect=RuntimeError("unexpected error")
        )

        conversation = [
            {"role": "user", "content": "Look", "images": ["some_data"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert "images" not in result[0]
        assert isinstance(result[0]["content"], str)

    def test_images_before_text_ordering(self, claude_handler, mocker):
        """
        Claude recommends placing images before text in content blocks.
        Verify that image blocks precede the text block.
        """
        mocker.patch.object(
            ClaudeApiHandler, '_process_single_image_source',
            side_effect=[
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "a"}},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "b"}},
            ]
        )

        conversation = [
            {"role": "user", "content": "Describe both", "images": ["img1", "img2"]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        content = result[0]["content"]
        assert content[0]["type"] == "image"
        assert content[1]["type"] == "image"
        assert content[2]["type"] == "text"
        assert content[2]["text"] == "Describe both"

    def test_empty_images_list_no_conversion(self, claude_handler):
        """An empty images list should not trigger multimodal conversion."""
        conversation = [
            {"role": "user", "content": "Hello", "images": []},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert result[0]["content"] == "Hello"
        assert "images" not in result[0]

    def test_mixed_valid_and_empty_images(self, claude_handler):
        """
        Messages with images alongside messages without images are handled correctly.
        """
        conversation = [
            {"role": "user", "content": "No image here"},
            {"role": "user", "content": "Image here",
             "images": ["data:image/jpeg;base64,/9j/4AAQSkZJRg=="]},
        ]
        result = claude_handler._build_messages_from_conversation(conversation, None, None)

        assert isinstance(result[0]["content"], str)
        assert isinstance(result[1]["content"], list)
        assert result[1]["content"][0]["type"] == "image"
