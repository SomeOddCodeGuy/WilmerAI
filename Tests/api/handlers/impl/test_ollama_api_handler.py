# Tests/api/handlers/impl/test_ollama_api_handler.py

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
        {'role': 'user', 'content': "What's in this image?"},
        {'role': 'images', 'content': 'base64_encoded_string_1'},
        {'role': 'images', 'content': 'base64_encoded_string_2'},
    ]
    assert called_messages == expected_messages


def test_get_version(client, mocker):
    """Tests the /api/version endpoint."""
    mock_builder = mocker.patch('Middleware.api.handlers.impl.ollama_api_handler.response_builder')
    mock_builder.build_ollama_version_response.return_value = {"version": "0.9"}

    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.json["version"] == "0.9"


def test_generate_missing_model_error(client):
    """Tests for a 400 error when 'model' is missing in /api/generate."""
    payload = {"prompt": "Why is the sky blue?", "stream": False}
    response = client.post('/api/generate', json=payload)
    assert response.status_code == 400
    assert "error" in response.json
    assert "'model' field is required" in response.json["error"]
