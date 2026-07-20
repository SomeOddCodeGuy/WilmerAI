import pytest

_HANDLER = 'Middleware.api.handlers.impl.ollama_api_handler'


@pytest.fixture(autouse=True)
def isolate_user_config(mocker):
    """Pin the per-user config reads to benign defaults so these endpoint tests
    cannot be broken (or silently repurposed) by edits to the repo's
    Public/Configs user files, which the handler would otherwise read for the
    _current-user.json user. Tests that need other values re-patch locally."""
    mocker.patch(f'{_HANDLER}.get_is_chat_complete_add_user_assistant', return_value=False)
    mocker.patch(f'{_HANDLER}.get_is_chat_complete_add_missing_assistant', return_value=False)
    mocker.patch(f'{_HANDLER}.get_encrypt_using_api_key', return_value=False)
    mocker.patch(f'{_HANDLER}.get_redact_log_output', return_value=False)
    mocker.patch(f'{_HANDLER}.check_openwebui_tool_request', return_value=None)


def test_eventlet_path_runs_post_return_nodes_to_completion(app, mocker):
    """Direct test of the Ollama Eventlet streaming path (ISS-035 + ISS-026).

    Mirrors the OpenAI version: the generator sleeps between the done:true terminator and a
    post-return chunk so the client-facing generator returns first. With the ISS-026 fix the
    generator does not send stop_signal on natural completion, so the reader keeps draining and
    the post-return node runs. Under the old behavior the post-return node would never execute.
    """
    eventlet = pytest.importorskip("eventlet")
    from Middleware.api.handlers.base import base_streaming
    from Middleware.api.handlers.impl import ollama_api_handler as h

    executed = []

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hi"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        eventlet.sleep(0.1)
        yield '{"message":{"role":"assistant","content":"post"},"done":false}\n'
        executed.append("post_return_ran")

    mocker.patch.object(h, 'handle_user_prompt', return_value=stream_generator())

    with app.test_request_context('/api/chat'):
        response = base_streaming.stream_with_eventlet_optimized(
            h._CHAT_STREAMING_CONFIG, h.handle_user_prompt,
            'req-evt', [{"role": "user", "content": "hi"}], True)
        client_chunks = list(response.response)

    for _ in range(200):
        if executed:
            break
        eventlet.sleep(0.01)

    joined = b"".join(c if isinstance(c, bytes) else c.encode("utf-8") for c in client_chunks)
    assert b'"done": true' in joined
    assert b'"post"' not in joined
    assert executed == ["post_return_ran"]


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


def test_chat_streaming_runs_post_return_nodes_after_done(client, mocker):
    """Post-returnToUser nodes must run to completion after a done:true chunk.

    The fix keeps the backend generator being driven past the done:true sentinel
    so non-responding post-return nodes execute, even though their output is not
    delivered to the client. This asserts the backend is fully drained (the side
    effect fires), not merely that post-done ghost chunks are excluded.
    """
    executed = []

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        executed.append("post_return_node_ran")
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
    body = response.data
    assert b'"done": true' in body
    assert b'ghost' not in body
    assert executed == ["post_return_node_ran"]


def test_generate_streaming_runs_post_return_nodes_after_done(client, mocker):
    """The /api/generate fallback path also drives post-return nodes past done:true."""
    executed = []

    def stream_generator():
        yield '{"response":"Hello","done":false}'
        yield '{"response":"","done": true}'
        executed.append("post_return_node_ran")
        yield '{"response":"ghost","done":false}'

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {"model": "test-model", "prompt": "Test", "stream": True}
    response = client.post('/api/generate', json=payload)

    assert response.status_code == 200
    body = response.data
    assert b'"done": true' in body
    assert b'ghost' not in body
    assert executed == ["post_return_node_ran"]


def test_post_done_exception_is_swallowed_in_fallback(client, mocker):
    """A post-terminator node failure must not propagate out of the WSGI generator.

    The client already received a visually-complete stream; re-raising would corrupt
    connection teardown. The fallback path logs and swallows it instead.
    """

    def stream_generator():
        yield '{"message":{"role":"assistant","content":"Hi"},"done":false}\n'
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'
        raise RuntimeError("post-return node blew up")

    mock_handle_prompt = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.handle_user_prompt')
    mock_handle_prompt.return_value = stream_generator()

    payload = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert b'"done": true' in response.data


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


def test_chat_invalid_json_returns_400(client):
    """POST /api/chat with an unparsable body is a 400, not a crash."""
    response = client.post('/api/chat', data='not valid json', content_type='application/json')
    assert response.status_code == 400
    assert "Invalid JSON" in response.json["error"]


def test_chat_missing_model_returns_400(client, mocker):
    """POST /api/chat requires both 'model' and 'messages'."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt')

    response = client.post('/api/chat', json={"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 400
    assert "required" in response.json["error"]
    mock_handle_prompt.assert_not_called()


def test_chat_missing_messages_returns_400(client, mocker):
    """POST /api/chat without 'messages' is rejected before dispatch."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt')

    response = client.post('/api/chat', json={"model": "test-model"})

    assert response.status_code == 400
    assert "required" in response.json["error"]
    mock_handle_prompt.assert_not_called()


def test_chat_message_missing_role_returns_400(client, mocker):
    """Each /api/chat message must carry a 'role'."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt')

    payload = {"model": "test-model", "messages": [{"content": "hi"}], "stream": False}
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 400
    assert "role" in response.json["error"]
    mock_handle_prompt.assert_not_called()


def test_chat_message_missing_content_and_tool_calls_returns_400(client, mocker):
    """A message with neither 'content' nor 'tool_calls' is a 400."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt')

    payload = {"model": "test-model", "messages": [{"role": "user"}], "stream": False}
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 400
    assert "content" in response.json["error"]
    mock_handle_prompt.assert_not_called()


def test_chat_stream_string_false_is_non_streaming(client, mocker):
    """Ollama clients may send stream as the string "false"; it must be coerced
    to the non-streaming path (a truthy non-empty string would otherwise stream)."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt', return_value="resp")
    mock_builder = mocker.patch(f'{_HANDLER}.response_builder')
    mock_builder.build_ollama_chat_response.return_value = {"message": {"content": "resp"}}

    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}],
               "stream": "false"}
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert 'application/json' in response.content_type
    # Positional stream argument reached the gateway as False.
    assert mock_handle_prompt.call_args[0][2] is False
    mock_builder.build_ollama_chat_response.assert_called_once()


def test_chat_stream_string_true_is_streaming(client, mocker):
    """The string "true" must select the streaming path."""

    def stream_generator():
        yield '{"message":{"role":"assistant","content":""},"done": true}\n'

    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt',
                                      return_value=stream_generator())

    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}],
               "stream": "true"}
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    assert 'application/x-ndjson' in response.content_type


def test_generate_combines_system_and_prompt(client, mocker):
    """/api/generate prepends the 'system' field to the prompt before parsing."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt', return_value="")
    mock_builder = mocker.patch(f'{_HANDLER}.response_builder')
    mock_builder.build_ollama_generate_response.return_value = {"response": ""}

    payload = {"model": "test-model", "system": "SYS ", "prompt": "hello", "stream": False}
    client.post('/api/generate', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages == [{"role": "user", "content": "SYS hello"}]


def test_generate_images_without_user_message_creates_one(client, mocker):
    """Images on a prompt that parses to no user message must not be silently
    dropped; a user message is created to carry them."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt', return_value="")
    mock_builder = mocker.patch(f'{_HANDLER}.response_builder')
    mock_builder.build_ollama_generate_response.return_value = {"response": ""}

    payload = {"model": "llava-model", "prompt": "", "images": ["b64data"], "stream": False}
    client.post('/api/generate', json=payload)

    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages == [{"role": "user", "content": "", "images": ["b64data"]}]


def test_chat_non_streaming_dict_result_builds_tool_call_response(client, mocker):
    """A dict result from the gateway (tool-call surface) must be unpacked into
    full_text + tool_calls for the Ollama chat response builder, with the model
    name resolved through api_helpers.get_model_name()."""
    tool_calls = [{"function": {"name": "lookup", "arguments": {"q": "x"}}}]
    mocker.patch(f'{_HANDLER}.handle_user_prompt',
                 return_value={"content": "the answer", "tool_calls": tool_calls})
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value='alice:wf')
    mock_builder = mocker.patch(f'{_HANDLER}.response_builder')
    mock_builder.build_ollama_chat_response.return_value = {"message": {"content": "the answer"}}

    payload = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}],
               "stream": False}
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    kwargs = mock_builder.build_ollama_chat_response.call_args[1]
    assert kwargs["full_text"] == "the answer"
    assert kwargs["tool_calls"] == tool_calls
    assert kwargs["model_name"] == "alice:wf"
    assert isinstance(kwargs["request_id"], str)


def test_generate_non_streaming_uses_model_name_from_helpers(client, mocker):
    """The non-streaming /api/generate response reports the model as
    api_helpers.get_model_name() (username:workflow when an override is active)."""
    mocker.patch(f'{_HANDLER}.handle_user_prompt', return_value="resp")
    mocker.patch('Middleware.api.api_helpers.get_model_name', return_value='alice:wf')
    mock_builder = mocker.patch(f'{_HANDLER}.response_builder')
    mock_builder.build_ollama_generate_response.return_value = {"response": "resp"}

    response = client.post('/api/generate',
                           json={"model": "test-model", "prompt": "hi", "stream": False})

    assert response.status_code == 200
    args, kwargs = mock_builder.build_ollama_generate_response.call_args
    assert args[0] == "resp"
    assert kwargs["model"] == "alice:wf"
    assert isinstance(kwargs["request_id"], str)


def test_chat_preserves_images_and_tool_fields_per_message(client, mocker):
    """/api/chat must carry per-message images and the tool-call fields
    (tool_calls, tool_call_id, name) through into the internal format."""
    mock_handle_prompt = mocker.patch(f'{_HANDLER}.handle_user_prompt', return_value="ok")
    mock_builder = mocker.patch(f'{_HANDLER}.response_builder')
    mock_builder.build_ollama_chat_response.return_value = {"message": {"content": "ok"}}

    tool_calls = [{"function": {"name": "get_weather", "arguments": {"city": "Oslo"}}}]
    payload = {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "look", "images": ["imgdata"]},
            {"role": "assistant", "tool_calls": tool_calls},
            {"role": "tool", "content": "12C", "tool_call_id": "call_1", "name": "get_weather"},
        ],
        "stream": False,
    }
    response = client.post('/api/chat', json=payload)

    assert response.status_code == 200
    called_messages = mock_handle_prompt.call_args[0][1]
    assert called_messages[0] == {"role": "user", "content": "look", "images": ["imgdata"]}
    assert called_messages[1] == {"role": "assistant", "content": "", "tool_calls": tool_calls}
    assert called_messages[2] == {"role": "tool", "content": "12C",
                                  "tool_call_id": "call_1", "name": "get_weather"}


class TestOllamaStreamingConfigShapes:
    """/api/chat and /api/generate use different chunk shapes; each route's
    heartbeat must be parseable as a chunk of ITS protocol."""

    def test_chat_heartbeat_is_message_shaped(self):
        import json
        from Middleware.api.handlers.impl.ollama_api_handler import _CHAT_STREAMING_CONFIG
        heartbeat = json.loads(_CHAT_STREAMING_CONFIG.heartbeat_message)
        assert heartbeat["message"] == {"role": "assistant", "content": ""}
        assert heartbeat["done"] is False
        assert "response" not in heartbeat

    def test_generate_heartbeat_is_response_shaped(self):
        import json
        from Middleware.api.handlers.impl.ollama_api_handler import _GENERATE_STREAMING_CONFIG
        heartbeat = json.loads(_GENERATE_STREAMING_CONFIG.heartbeat_message)
        assert heartbeat["response"] == ""
        assert heartbeat["done"] is False
        assert "message" not in heartbeat
