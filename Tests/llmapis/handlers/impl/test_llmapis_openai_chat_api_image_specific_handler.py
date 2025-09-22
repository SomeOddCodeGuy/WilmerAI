# Tests/llmapis/handlers/impl/test_openai_chat_api_image_specific_handler.py

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, mock_open

import pytest

from Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler import OpenAIApiChatImageSpecificHandler

# A minimal valid base64 representation of a 1x1 black PNG for testing
FAKE_BASE64_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
FAKE_DATA_URI_PNG = f"data:image/png;base64,{FAKE_BASE64_PNG}"


@pytest.fixture
def handler():
    """Fixture to create a default OpenAIApiChatImageSpecificHandler instance."""
    return OpenAIApiChatImageSpecificHandler(
        base_url="http://localhost:8080",
        api_key="test_key",
        gen_input={},
        model_name="gpt-4-vision",
        headers={},
        stream=False,
        api_type_config={},
        endpoint_config={},
        max_tokens=100
    )


# ###############################################################
# Section 1: Tests for the core logic: _build_messages_from_conversation
# ###############################################################

def test_build_messages_no_images(handler):
    """
    Tests that a conversation with no images is processed correctly,
    behaving like its parent class.
    """
    conversation = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello there."},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)
    assert result == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello there."},
    ]
    assert all(isinstance(msg['content'], str) for msg in result)


def test_build_messages_with_http_url(handler):
    """
    Tests that a conversation with an HTTP image URL is correctly formatted
    into a multimodal message.
    """
    http_url = "https://example.com/image.jpg"
    conversation = [
        {"role": "user", "content": "What is in this image?"},
        {"role": "images", "content": http_url},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)

    assert len(result) == 1
    user_message = result[0]
    assert user_message["role"] == "user"
    assert isinstance(user_message["content"], list)
    assert user_message["content"] == [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": http_url}},
    ]


def test_build_messages_with_data_uri(handler):
    """
    Tests that a conversation with a data URI is passed through correctly.
    """
    conversation = [
        {"role": "user", "content": "Describe this embedded image."},
        {"role": "images", "content": FAKE_DATA_URI_PNG},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)

    assert len(result) == 1
    user_message = result[0]
    assert user_message["content"] == [
        {"type": "text", "text": "Describe this embedded image."},
        {"type": "image_url", "image_url": {"url": FAKE_DATA_URI_PNG}},
    ]


@patch('Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.Image.open')
def test_build_messages_with_base64_string(mock_image_open, handler):
    """
    Tests that a raw base64 string is correctly identified, processed, and
    formatted into a data URI.
    """
    mock_image = MagicMock()
    mock_image.format.lower.return_value = 'png'
    mock_image_open.return_value.__enter__.return_value = mock_image

    conversation = [
        {"role": "user", "content": "What about this base64 image?"},
        {"role": "images", "content": FAKE_BASE64_PNG},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)

    assert len(result) == 1
    user_message = result[0]
    assert user_message["content"] == [
        {"type": "text", "text": "What about this base64 image?"},
        {"type": "image_url", "image_url": {"url": FAKE_DATA_URI_PNG}},
    ]


@patch(
    'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler.convert_to_data_uri')
def test_build_messages_with_file_uri(mock_convert, handler):
    """
    Tests that a file URI is correctly passed to the conversion utility.
    """
    mock_convert.return_value = FAKE_DATA_URI_PNG
    file_uri = "file:///path/to/image.png"
    conversation = [
        {"role": "user", "content": "Check out this local file."},
        {"role": "images", "content": file_uri},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)

    mock_convert.assert_called_once_with(file_uri)
    assert result[0]["content"][1]["image_url"]["url"] == FAKE_DATA_URI_PNG


def test_build_messages_with_multiple_images(handler):
    """
    Tests that multiple image sources are all collected and appended to the
    last user message.
    """
    http_url = "http://example.com/a.jpg"
    conversation = [
        {"role": "user", "content": "Here are two images"},
        {"role": "images", "content": [http_url, FAKE_DATA_URI_PNG]}
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)

    assert len(result) == 1
    user_message_content = result[0]["content"]
    assert len(user_message_content) == 3
    assert user_message_content[0] == {"type": "text", "text": "Here are two images"}
    assert user_message_content[1] == {"type": "image_url", "image_url": {"url": http_url}}
    assert user_message_content[2] == {"type": "image_url", "image_url": {"url": FAKE_DATA_URI_PNG}}


def test_build_messages_attaches_to_correct_user_message(handler):
    """
    Ensures images are attached to the *last* user message, even if it's not
    the last message in the conversation.
    """
    conversation = [
        {"role": "user", "content": "First user message."},
        {"role": "assistant", "content": "An assistant response."},
        {"role": "user", "content": "Last user message, please describe."},
        {"role": "images", "content": FAKE_DATA_URI_PNG},
        {"role": "assistant", "content": ""},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)

    assert len(result) == 3
    last_user_msg = result[2]
    assert last_user_msg["role"] == "user"
    assert isinstance(last_user_msg["content"], list)
    assert len(last_user_msg["content"]) == 2
    assert last_user_msg["content"][1]["image_url"]["url"] == FAKE_DATA_URI_PNG


def test_build_messages_fallback_on_processing_error(handler, mocker):
    """
    Tests that if image processing fails, the fallback mechanism is triggered,
    and a system note is appended.
    """
    mocker.patch(
        'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler._process_single_image_source',
        side_effect=Exception("mocked processing error")
    )
    conversation = [
        {"role": "user", "content": "This image will fail to process."},
        {"role": "images", "content": "bad-image-data"},
    ]
    result = handler._build_messages_from_conversation(conversation, None, None)
    expected_error_text = "\n\n[System note: There was an error processing the provided image(s). I will respond based on the text alone.]"

    assert len(result) == 1
    user_message = result[0]
    assert user_message["role"] == "user"
    assert isinstance(user_message["content"], str)
    assert user_message["content"].endswith(expected_error_text)


# ###############################################################
# Section 2: Tests for static helper methods
# ###############################################################

@pytest.mark.parametrize("url, expected", [
    ("http://example.com/image.png", True),
    ("https://example.com/path?query=1", True),
    ("ftp://example.com", False),
    ("not_a_url", False),
    ("http:/missing_slash.com", False),
    ("", False),
    (None, False)
])
def test_is_valid_http_url(url, expected):
    assert OpenAIApiChatImageSpecificHandler.is_valid_http_url(url) == expected


@pytest.mark.parametrize("s, expected", [
    (FAKE_BASE64_PNG, True),
    ("not-base64-string!", False),
    ("YWJjZA==", True),
    ("YWJjZ", False),
    (None, False),
    ("", False)
])
def test_is_base64_image(s, expected):
    assert OpenAIApiChatImageSpecificHandler.is_base64_image(s) == expected


def test_convert_to_data_uri_success(mocker):
    mocker.patch('os.path.abspath', return_value='/tmp/image.png')
    mocked_file_open = mock_open(read_data=b'fake-image-bytes')
    mocker.patch('builtins.open', mocked_file_open)
    mock_image = SimpleNamespace(format='PNG')
    mocked_image_open = mocker.patch('PIL.Image.open')
    mocked_image_open.return_value.__enter__.return_value = mock_image

    expected_data_uri = "data:image/png;base64,ZmFrZS1pbWFnZS1ieXRlcw=="
    result = OpenAIApiChatImageSpecificHandler.convert_to_data_uri("file:///tmp/image.png")
    assert result == expected_data_uri


def test_convert_to_data_uri_file_not_found(mocker):
    mocker.patch('os.path.abspath', return_value='/tmp/nonexistent.jpg')
    mocker.patch('PIL.Image.open', side_effect=FileNotFoundError)
    result = OpenAIApiChatImageSpecificHandler.convert_to_data_uri("file:///tmp/nonexistent.jpg")
    assert result is None


def test_process_single_image_source_http_url(mocker):
    """Tests processing of a valid HTTP URL."""
    source = "http://example.com/image.jpg"
    mocker.patch(
        'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler.is_base64_image',
        return_value=False)
    result = OpenAIApiChatImageSpecificHandler._process_single_image_source(source)
    assert result == {"type": "image_url", "image_url": {"url": source}}


def test_process_single_image_source_data_uri():
    """Tests processing of a valid data URI, which should pass through."""
    result = OpenAIApiChatImageSpecificHandler._process_single_image_source(FAKE_DATA_URI_PNG)
    assert result == {"type": "image_url", "image_url": {"url": FAKE_DATA_URI_PNG}}


def test_process_single_image_source_base64(mocker):
    """Tests processing of a valid base64 string."""
    mock_pil_open = mocker.patch('PIL.Image.open')
    mock_image = MagicMock()
    mock_image.format.lower.return_value = 'png'
    mock_pil_open.return_value.__enter__.return_value = mock_image

    result = OpenAIApiChatImageSpecificHandler._process_single_image_source(FAKE_BASE64_PNG)
    assert result == {"type": "image_url", "image_url": {"url": FAKE_DATA_URI_PNG}}


def test_process_single_image_source_file_uri(mocker):
    """Tests processing of a file URI."""
    source = "file:///path/to/img.png"
    mocker.patch(
        'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler.is_base64_image',
        return_value=False)
    mock_convert = mocker.patch(
        'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler.convert_to_data_uri',
        return_value=FAKE_DATA_URI_PNG)
    result = OpenAIApiChatImageSpecificHandler._process_single_image_source(source)
    mock_convert.assert_called_once_with(source)
    assert result == {"type": "image_url", "image_url": {"url": FAKE_DATA_URI_PNG}}


def test_process_single_image_source_invalid(mocker):
    """Tests that an invalid/unrecognized source returns None."""
    source = "this-is-not-a-valid-source"
    mocker.patch(
        'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler.is_base64_image',
        return_value=False)
    mocker.patch(
        'Middleware.llmapis.handlers.impl.openai_chat_api_image_specific_handler.OpenAIApiChatImageSpecificHandler.is_valid_http_url',
        return_value=False)
    result = OpenAIApiChatImageSpecificHandler._process_single_image_source(source)
    assert result is None
