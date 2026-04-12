def test_get_models(client, mocker):
    """Tests the /v1/models endpoint."""
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_models_response.return_value = {"data": [{"id": "test-model"}]}

    response = client.get('/v1/models')
    assert response.status_code == 200
    assert response.json["data"][0]["id"] == "test-model"


def test_chat_completions_non_streaming(client, mocker):
    """Tests the /v1/chat/completions endpoint with stream=False."""
    # Mock the configuration functions to ensure predictable behavior
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=True)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=True)

    # Mock the backend gateway and response builder
    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "This is a test response."
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "chatcmpl-123"}

    # Define the original payload
    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False
    }

    # Define the expected transformed messages that the handler will create
    expected_transformed_messages = [
        {"role": "user", "content": "User: Hello"},
        {"role": "assistant", "content": "Assistant:"}
    ]

    # Make the request
    response = client.post('/chat/completions', json=payload)

    # Assertions
    assert response.status_code == 200
    assert response.json["id"] == "chatcmpl-123"

    # Check that handle_user_prompt was called with request_id and correct arguments
    assert mock_handle_prompt.call_count == 1
    call_args = mock_handle_prompt.call_args[0]
    assert isinstance(call_args[0], str)  # First arg is request_id (UUID string)
    assert call_args[1] == expected_transformed_messages
    assert mock_handle_prompt.call_args[1] == {'stream': False, 'api_key': None, 'tools': None, 'tool_choice': None}

    mock_builder.build_openai_chat_completion_response.assert_called_once_with("This is a test response.")


def test_chat_completions_streaming(client, mocker):
    """Tests the /v1/chat/completions endpoint with stream=True."""
    # Mock the configuration functions
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=True)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=True)

    def stream_generator():
        yield "data: chunk1\n\n"
        yield "data: chunk2\n\n"

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }

    # Define the expected transformed messages
    expected_transformed_messages = [
        {"role": "user", "content": "User: Hello"},
        {"role": "assistant", "content": "Assistant:"}
    ]

    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert 'text/event-stream' in response.content_type
    # The response may include keep-alive newlines from the watchdog
    assert b"data: chunk1" in response.data
    assert b"data: chunk2" in response.data

    # Check that handle_user_prompt was called with request_id and correct arguments
    assert mock_handle_prompt.call_count == 1
    call_args = mock_handle_prompt.call_args[0]
    assert isinstance(call_args[0], str)  # First arg is request_id (UUID string)
    assert call_args[1] == expected_transformed_messages
    assert call_args[2] == True  # stream=True


def test_chat_completions_streaming_has_connection_close(client, mocker):
    """Tests that streaming /chat/completions responses include Connection: close header."""
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    def stream_generator():
        yield "data: chunk1\n\n"

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert response.headers.get('Connection') == 'close'


def test_completions_streaming_has_connection_close(client, mocker):
    """Tests that streaming /v1/completions responses include Connection: close header."""

    def stream_generator():
        yield "data: chunk1\n\n"

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"prompt": "Test prompt", "stream": True}
    response = client.post('/v1/completions', json=payload)

    assert response.status_code == 200
    assert response.headers.get('Connection') == 'close'


def test_chat_completions_streaming_stops_after_done(client, mocker):
    """Tests that the streaming generator stops yielding after the [DONE] sentinel.

    Simulates a workflow where post-stream chunks follow [DONE] (e.g., from
    non-responding workflow nodes executing after the stream completes).
    The generator must stop after [DONE] to prevent the connection from
    staying open during post-stream workflow processing.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    def stream_generator():
        yield 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield 'data: [DONE]\n\n'
        # This chunk simulates post-stream workflow processing and must NOT reach the client.
        yield 'data: {"choices":[{"delta":{"content":"ghost"}}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_completions_streaming_stops_after_done(client, mocker):
    """Tests that the /v1/completions streaming generator stops after [DONE]."""

    def stream_generator():
        yield 'data: {"choices":[{"text":"Hello"}]}\n\n'
        yield 'data: [DONE]\n\n'
        yield 'data: {"choices":[{"text":"ghost"}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"prompt": "Test prompt", "stream": True}
    response = client.post('/v1/completions', json=payload)

    assert response.status_code == 200
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_chat_completions_streaming_delivers_all_chunks_before_done(client, mocker):
    """Tests that all content chunks before [DONE] are delivered to the client.

    Ensures the stream-complete detection only stops AFTER yielding the [DONE]
    chunk, not before it. All preceding content must reach the client intact.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    def stream_generator():
        yield 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{"content":"!"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield 'data: [DONE]\n\n'
        yield 'data: {"choices":[{"delta":{"content":"ghost"}}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert b'"content":"Hello"' in response.data
    assert b'"content":" world"' in response.data
    assert b'"content":"!"' in response.data
    assert b'"finish_reason":"stop"' in response.data
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_completions_streaming_delivers_all_chunks_before_done(client, mocker):
    """Tests that all content chunks before [DONE] are delivered for /v1/completions."""

    def stream_generator():
        yield 'data: {"choices":[{"text":"The "}]}\n\n'
        yield 'data: {"choices":[{"text":"sky "}]}\n\n'
        yield 'data: {"choices":[{"text":"is blue."}]}\n\n'
        yield 'data: [DONE]\n\n'
        yield 'data: {"choices":[{"text":"ghost"}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"prompt": "Test prompt", "stream": True}
    response = client.post('/v1/completions', json=payload)

    assert response.status_code == 200
    assert b'"text":"The "' in response.data
    assert b'"text":"sky "' in response.data
    assert b'"text":"is blue."' in response.data
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_chat_completions_streaming_immediate_done(client, mocker):
    """Tests a stream that sends [DONE] as the very first chunk (immediate completion).

    Some backends may send [DONE] immediately with no content chunks, for example
    when the model generates an empty response or encounters a stop sequence.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    def stream_generator():
        yield 'data: [DONE]\n\n'
        yield 'data: {"choices":[{"delta":{"content":"ghost"}}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_completions_streaming_immediate_done(client, mocker):
    """Tests /v1/completions with [DONE] as the first and only chunk."""

    def stream_generator():
        yield 'data: [DONE]\n\n'
        yield 'data: {"choices":[{"text":"ghost"}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"prompt": "Test prompt", "stream": True}
    response = client.post('/v1/completions', json=payload)

    assert response.status_code == 200
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_chat_completions_streaming_excludes_multiple_ghost_chunks(client, mocker):
    """Tests that ALL chunks after [DONE] are excluded, not just the first one.

    In practice, post-stream workflow processing may produce many chunks as
    non-responding nodes execute and the workflow processor performs cleanup.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    def stream_generator():
        yield 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        yield 'data: [DONE]\n\n'
        yield 'data: {"choices":[{"delta":{"content":"ghost1"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{"content":"ghost2"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{"content":"ghost3"}}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert b'"content":"Hi"' in response.data
    assert b'[DONE]' in response.data
    assert b'ghost1' not in response.data
    assert b'ghost2' not in response.data
    assert b'ghost3' not in response.data


def test_chat_completions_streaming_handles_bytes_input(client, mocker):
    """Tests that stream-complete detection works when the generator yields bytes.

    The handler encodes str chunks to bytes but passes bytes through as-is.
    Both paths must trigger the [DONE] detection.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    def stream_generator():
        yield b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        yield b'data: [DONE]\n\n'
        yield b'data: {"choices":[{"delta":{"content":"ghost"}}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    response = client.post('/chat/completions', json=payload)

    assert response.status_code == 200
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data


def test_completions_streaming_handles_bytes_input(client, mocker):
    """Tests /v1/completions stream-complete detection with bytes input from the generator."""

    def stream_generator():
        yield b'data: {"choices":[{"text":"Hi"}]}\n\n'
        yield b'data: [DONE]\n\n'
        yield b'data: {"choices":[{"text":"ghost"}]}\n\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"prompt": "Test prompt", "stream": True}
    response = client.post('/v1/completions', json=payload)

    assert response.status_code == 200
    assert b'[DONE]' in response.data
    assert b'ghost' not in response.data



def test_chat_completions_with_openai_multimodal_images(client, mocker):
    """
    Tests that OpenAI multimodal format (content as list with image_url parts)
    is correctly parsed into text content + images key.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What's in this image?"},
                    {"type": "image_url", "image_url": {"url": "https://example.local/cat.jpg"}}
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert len(called_messages) == 1
    assert called_messages[0]["role"] == "user"
    assert called_messages[0]["content"] == "What's in this image?"
    assert called_messages[0]["images"] == ["https://example.local/cat.jpg"]


def test_chat_completions_with_claude_multimodal_images(client, mocker):
    """
    Tests that Claude multimodal format (content as list with image parts
    containing source objects) is correctly parsed.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": "iVBORw0KGgoAAAANSUhEUg=="
                        }
                    }
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert len(called_messages) == 1
    assert called_messages[0]["content"] == "Describe this image"
    assert called_messages[0]["images"] == ["data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUg=="]


def test_chat_completions_with_claude_url_image(client, mocker):
    """
    Tests that Claude multimodal format with URL-based image source is parsed correctly.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.local/photo.png"
                        }
                    }
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages[0]["images"] == ["https://example.local/photo.png"]


def test_chat_completions_with_mixed_image_and_text_messages(client, mocker):
    """
    Tests that a conversation with some messages having images and some
    without preserves per-message image association correctly.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this"},
                    {"type": "image_url", "image_url": {"url": "https://example.local/img.jpg"}}
                ]
            },
            {"role": "assistant", "content": "I see it"},
            {"role": "user", "content": "What do you think?"},
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert len(called_messages) == 5

    assert called_messages[0]["content"] == "Hello"
    assert "images" not in called_messages[0]

    assert called_messages[2]["content"] == "Look at this"
    assert called_messages[2]["images"] == ["https://example.local/img.jpg"]

    assert called_messages[4]["content"] == "What do you think?"
    assert "images" not in called_messages[4]


def test_chat_completions_with_images_and_add_user_assistant(client, mocker):
    """
    Tests that the "User:" prefix is applied to the extracted text content,
    not the raw list, when add_user_assistant is enabled.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=True)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {"type": "image_url", "image_url": {"url": "https://example.local/img.jpg"}}
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages[0]["content"] == "User: Describe this"
    assert called_messages[0]["images"] == ["https://example.local/img.jpg"]


def test_chat_completions_with_no_text_in_image_message(client, mocker):
    """
    Tests edge case where a multimodal message has only image_url parts
    and no text part. Content should be an empty string.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.local/img.jpg"}}
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages[0]["content"] == ""
    assert called_messages[0]["images"] == ["https://example.local/img.jpg"]


def test_chat_completions_with_multiple_text_parts(client, mocker):
    """
    Tests that multiple text parts in a multimodal message are joined with newlines.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Line one"},
                    {"type": "text", "text": "Line two"},
                    {"type": "image_url", "image_url": {"url": "https://example.local/img.jpg"}}
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages[0]["content"] == "Line one\nLine two"
    assert called_messages[0]["images"] == ["https://example.local/img.jpg"]


def test_chat_completions_claude_image_empty_data_skipped(client, mocker):
    """
    Tests that a Claude-format image with empty data is skipped.
    """
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Response"
    mock_builder = mocker.patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    mock_builder.build_openai_chat_completion_response.return_value = {"id": "test"}

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": ""
                        }
                    }
                ]
            }
        ],
        "stream": False
    }

    client.post('/chat/completions', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages[0]["content"] == "Hello"
    assert "images" not in called_messages[0]


def test_chat_completions_returns_400_on_empty_body(client, mocker):
    """Tests that /v1/chat/completions returns 400 when the request body is empty."""
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=False)
    mocker.patch('Middleware.api.handlers.impl.openai_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=False)

    response = client.post('/chat/completions', data=b'', content_type='application/json')
    assert response.status_code == 400
    assert "Invalid JSON" in response.json["error"]


def test_completions_returns_400_on_empty_body(client, mocker):
    """Tests that /v1/completions returns 400 when the request body is empty."""
    response = client.post('/completions', data=b'', content_type='application/json')
    assert response.status_code == 400
    assert "Invalid JSON" in response.json["error"]
