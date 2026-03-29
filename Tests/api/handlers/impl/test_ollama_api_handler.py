def test_generate_non_streaming(client, mocker):
    """Tests the /api/generate endpoint with stream=False."""
    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Ollama response."

    mock_builder = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.response_builder')
    mock_builder.build_ollama_generate_response.return_value = {"response": "Ollama response."}

    payload = {"model": "test-model", "prompt": "Why is the sky blue?", "stream": False}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert response.json["response"] == "Ollama response."
    mock_handle_prompt.assert_called_once()
    # Verifying the transformed messages list (now the second argument after request_id)
    called_request_id = mock_handle_prompt.call_args[0][0]
    called_messages = mock_handle_prompt.call_args[0][1]
    assert isinstance(called_request_id, str)  # Should be a UUID string
    assert called_messages == [{'role': 'user', 'content': 'Why is the sky blue?'}]


def test_chat_streaming(client, mocker):
    """Tests the /api/chat endpoint with stream=True."""

    def stream_generator():
        yield '{"content": "chunk1"}\n'
        yield '{"content": "chunk2"}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert 'application/x-ndjson' in response.content_type
    # The watchdog implementation may add keep-alive newlines
    assert b'{"content": "chunk1"}' in response.data
    assert b'{"content": "chunk2"}' in response.data


def test_get_tags(client, mocker):
    """Tests the /api/tags endpoint."""
    mock_builder = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.response_builder')
    mock_builder.build_ollama_tags_response.return_value = {"models": [{"name": "test-model"}]}

    response = client.get('/api/tags')
    assert response.status_code == 200
    assert response.json["models"][0]["name"] == "test-model"


def test_generate_streaming(client, mocker):
    """Tests the /api/generate endpoint with stream=True."""

    def stream_generator():
        yield '{"response": "chunk1"}'
        yield '{"response": "chunk2"}'

    # Mock the gateway to return a generator
    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Why is the sky blue?", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    # Note: The Ollama /generate endpoint now uses 'application/x-ndjson' for streaming line-delimited JSON
    assert 'application/x-ndjson' in response.content_type
    assert b'{"response": "chunk1"}{"response": "chunk2"}' in response.data
    mock_handle_prompt.assert_called_once()


def test_chat_non_streaming(client, mocker):
    """Tests the /api/chat endpoint with stream=False."""
    # Mock the gateway to return a single string
    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "Final Ollama chat response."

    # Mock the response builder for the final object
    mock_builder = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.response_builder')
    mock_builder.build_ollama_chat_response.return_value = {"message": {"content": "Final Ollama chat response."}}

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": False
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert response.json["message"]["content"] == "Final Ollama chat response."
    mock_handle_prompt.assert_called_once()
    mock_builder.build_ollama_chat_response.assert_called_once()


def test_chat_message_transformation_logic(client, mocker):
    """Tests the conditional User/Assistant prefixing in the /api/chat handler."""
    mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.get_is_chat_complete_add_user_assistant',
                 return_value=True)
    mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.get_is_chat_complete_add_missing_assistant',
                 return_value=True)

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = "response"

    payload = {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ],
        "stream": False
    }
    client.post('/api/chat', json=payload)

    # Now the first argument is request_id, second is messages
    called_request_id = mock_handle_prompt.call_args[0][0]
    called_messages = mock_handle_prompt.call_args[0][1]
    assert isinstance(called_request_id, str)  # Should be a UUID string
    expected_messages = [
        {'role': 'user', 'content': 'User: Hello'},
        {'role': 'assistant', 'content': 'Assistant: Hi there!'},
        {'role': 'user', 'content': 'User: How are you?'},
        {'role': 'assistant', 'content': 'Assistant:'}
    ]
    assert called_messages == expected_messages


def test_generate_with_images(client, mocker):
    """Tests that the /api/generate handler correctly processes images."""
    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt',
                                      return_value="")

    payload = {
        "model": "llava-model",
        "prompt": "What's in this image?",
        "images": ["base64_encoded_string_1", "base64_encoded_string_2"],
        "stream": False
    }
    client.post('/api/generate', json=payload)

    # Now the first argument is request_id, second is messages
    called_request_id = mock_handle_prompt.call_args[0][0]
    called_messages = mock_handle_prompt.call_args[0][1]
    assert isinstance(called_request_id, str)  # Should be a UUID string
    expected_messages = [
        {'role': 'user', 'content': "What's in this image?",
         'images': ['base64_encoded_string_1', 'base64_encoded_string_2']},
    ]
    assert called_messages == expected_messages


def test_get_version(client, mocker):
    """Tests the /api/version endpoint."""
    mock_builder = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.response_builder')
    mock_builder.build_ollama_version_response.return_value = {"version": "0.9"}

    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.json["version"] == "0.9"


def test_generate_streaming_has_connection_close(client, mocker):
    """Tests that streaming /api/generate responses include Connection: close header."""

    def stream_generator():
        yield '{"response": "chunk1"}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert response.headers.get('Connection') == 'close'


def test_chat_streaming_has_connection_close(client, mocker):
    """Tests that streaming /api/chat responses include Connection: close header."""

    def stream_generator():
        yield '{"content": "chunk1"}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert response.headers.get('Connection') == 'close'


def test_chat_streaming_stops_after_done_true(client, mocker):
    """Tests that the streaming generator stops yielding after a done:true chunk.

    Simulates a workflow where post-stream chunks follow the done:true message
    (e.g., from non-responding workflow nodes executing after the stream completes).
    The generator must stop after done:true to prevent heartbeats or stale data
    from being sent to the client.
    """

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        # These chunks simulate post-stream workflow processing that the
        # backend_reader would encounter. They must NOT reach the client.
        yield '{"message":{"role":"assistant","content":"ghost"},"done":false}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_generate_streaming_stops_after_done_true(client, mocker):
    """Tests that the /api/generate streaming generator stops after done:true."""

    def stream_generator():
        yield '{"response":"Hello","done":false}'
        yield '{"response":"","done": true}'
        yield '{"response":"ghost","done":false}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_chat_streaming_stops_after_compact_done_true(client, mocker):
    """Tests stream-complete detection with compact JSON (no space in "done":true).

    The response_builder uses json.dumps which produces "done": true (with space),
    but third-party backends may produce "done":true (compact). Both formats must
    be detected.
    """

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hi"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done":true}\n'
        yield '{"message":{"role":"assistant","content":"ghost"},"done":false}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"done":true' in response.data
    assert b'ghost' not in response.data


def test_generate_streaming_stops_after_compact_done_true(client, mocker):
    """Tests /api/generate stream-complete detection with compact JSON ("done":true)."""

    def stream_generator():
        yield '{"response":"Hi","done":false}'
        yield '{"response":"","done":true}'
        yield '{"response":"ghost","done":false}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert b'"done":true' in response.data
    assert b'ghost' not in response.data


def test_chat_streaming_delivers_all_chunks_before_done(client, mocker):
    """Tests that all content chunks before done:true are delivered to the client.

    Ensures the stream-complete detection only stops AFTER yielding the done:true
    chunk, not before it. All preceding content must reach the client intact.
    """

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":" world"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":"!"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        yield '{"message":{"role":"assistant","content":"ghost"},"done":false}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"content":"Hello"' in response.data
    assert b'"content":" world"' in response.data
    assert b'"content":"!"' in response.data
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_generate_streaming_delivers_all_chunks_before_done(client, mocker):
    """Tests that all content chunks before done:true are delivered for /api/generate."""

    def stream_generator():
        yield '{"response":"The ","done":false}'
        yield '{"response":"sky ","done":false}'
        yield '{"response":"is blue.","done":false}'
        yield '{"response":"","done": true}'
        yield '{"response":"ghost","done":false}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert b'"response":"The "' in response.data
    assert b'"response":"sky "' in response.data
    assert b'"response":"is blue."' in response.data
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_chat_streaming_immediate_done(client, mocker):
    """Tests a stream that sends done:true as the very first chunk (immediate completion).

    Some backends may send a single done:true chunk with no content, for example
    when the model generates an empty response.
    """

    def stream_generator():
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        yield '{"message":{"role":"assistant","content":"ghost"},"done":false}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_generate_streaming_immediate_done(client, mocker):
    """Tests /api/generate with done:true as the first and only real chunk."""

    def stream_generator():
        yield '{"response":"","done": true}'
        yield '{"response":"ghost","done":false}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_chat_streaming_excludes_multiple_ghost_chunks(client, mocker):
    """Tests that ALL chunks after done:true are excluded, not just the first one.

    In practice, post-stream workflow processing may produce many chunks as
    non-responding nodes execute and the workflow processor performs cleanup.
    """

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hi"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        yield '{"message":{"role":"assistant","content":"ghost1"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":"ghost2"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":"ghost3"},"done":false}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"content":"Hi"' in response.data
    assert b'"done": true' in response.data
    assert b'ghost1' not in response.data
    assert b'ghost2' not in response.data
    assert b'ghost3' not in response.data


def test_chat_streaming_handles_bytes_input(client, mocker):
    """Tests that the stream-complete detection works when the generator yields bytes.

    The handler encodes str chunks to bytes but passes bytes through as-is.
    Both paths must trigger the done:true detection.
    """

    def stream_generator():
        yield b'{"message":{"role":"assistant","content":"Hi"},"done":false}\n'
        yield b'{"message":{"role":"assistant","content":""},"done": true}\n'
        yield b'{"message":{"role":"assistant","content":"ghost"},"done":false}\n'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_generate_streaming_handles_bytes_input(client, mocker):
    """Tests /api/generate stream-complete detection with bytes input from the generator."""

    def stream_generator():
        yield b'{"response":"Hi","done":false}'
        yield b'{"response":"","done": true}'
        yield b'{"response":"ghost","done":false}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data
    assert b'ghost' not in response.data


def test_generate_missing_model_error(client):
    """Tests for a 400 error when 'model' is missing in /api/generate."""
    payload = {"prompt": "Why is the sky blue?", "stream": False}
    response = client.post('/api/generate', json=payload)
    assert response.status_code == 400
    assert "error" in response.json
    assert "'model' field is required" in response.json["error"]
