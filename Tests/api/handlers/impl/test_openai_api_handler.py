# Tests/api/handlers/impl/test_openai_api_handler.py

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

    mock_handle_prompt.assert_called_once_with(expected_transformed_messages, stream=False)

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
    assert b"data: chunk1\n\ndata: chunk2\n\n" in response.data
    # Assert that the gateway was called with the TRANSFORMED messages
    mock_handle_prompt.assert_called_once_with(expected_transformed_messages, True)
