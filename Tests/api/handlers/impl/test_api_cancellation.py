# tests/api/handlers/impl/test_api_cancellation.py

import pytest
from unittest.mock import MagicMock, patch, Mock
from flask import Flask, g
from werkzeug.exceptions import ClientDisconnected

from Middleware.api.handlers.impl.ollama_api_handler import CancelChatAPI, CancelGenerateAPI
from Middleware.api.handlers.impl.openai_api_handler import ChatCompletionsAPI, CompletionsAPI
from Middleware.services.cancellation_service import cancellation_service


@pytest.fixture
def app():
    """Create and configure a test Flask app."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create a test client for the Flask app."""
    return app.test_client()


@pytest.fixture
def setup_cancellation_service():
    """Clear cancellation service before each test."""
    # Clear any existing cancellations
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)
    yield
    # Clear again after test
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)


class TestOllamaAPICancellation:
    """Test suite for Ollama API DELETE endpoints for cancellation."""

    def test_cancel_chat_api_success(self, app, client, setup_cancellation_service):
        """Test successful cancellation via DELETE /api/chat."""
        request_id = "test_chat_request_123"

        with app.test_request_context(
            '/api/chat',
            method='DELETE',
            json={'request_id': request_id}
        ):
            response = CancelChatAPI.delete()

            assert response[1] == 200, "Should return 200 status code"
            assert response[0].json['status'] == 'cancelled'
            assert response[0].json['request_id'] == request_id
            assert cancellation_service.is_cancelled(request_id), "Request should be cancelled"

    def test_cancel_chat_api_missing_request_id(self, app, client):
        """Test DELETE /api/chat without request_id field."""
        with app.test_request_context(
            '/api/chat',
            method='DELETE',
            json={}
        ):
            response = CancelChatAPI.delete()

            assert response[1] == 400, "Should return 400 status code"
            assert 'error' in response[0].json

    def test_cancel_chat_api_invalid_json(self, app, client):
        """Test DELETE /api/chat with invalid JSON."""
        with app.test_request_context(
            '/api/chat',
            method='DELETE',
            data='not valid json',
            content_type='application/json'
        ):
            response = CancelChatAPI.delete()

            assert response[1] == 400, "Should return 400 status code"

    def test_cancel_generate_api_success(self, app, client, setup_cancellation_service):
        """Test successful cancellation via DELETE /api/generate."""
        request_id = "test_generate_request_456"

        with app.test_request_context(
            '/api/generate',
            method='DELETE',
            json={'request_id': request_id}
        ):
            response = CancelGenerateAPI.delete()

            assert response[1] == 200, "Should return 200 status code"
            assert response[0].json['status'] == 'cancelled'
            assert response[0].json['request_id'] == request_id
            assert cancellation_service.is_cancelled(request_id), "Request should be cancelled"

    def test_cancel_generate_api_missing_request_id(self, app, client):
        """Test DELETE /api/generate without request_id field."""
        with app.test_request_context(
            '/api/generate',
            method='DELETE',
            json={}
        ):
            response = CancelGenerateAPI.delete()

            assert response[1] == 400, "Should return 400 status code"
            assert 'error' in response[0].json


class TestOpenAIAPIDisconnectHandling:
    """Test suite for OpenAI API client disconnect handling."""

    @patch('Middleware.api.handlers.impl.openai_api_handler.uuid.uuid4')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_chat_completions_streaming_disconnect(self, mock_globals, mock_handle_prompt, mock_uuid, app, setup_cancellation_service):
        """Test that client disconnect during streaming triggers cancellation."""
        request_id = "test_openai_stream_123"
        mock_uuid.return_value = request_id  # Mock uuid to return our expected request_id

        def mock_generator():
            """Mock generator that raises ClientDisconnected."""
            yield "data: chunk1\n\n"
            raise ClientDisconnected()

        mock_handle_prompt.return_value = mock_generator()

        with app.test_request_context(
            '/chat/completions',
            method='POST',
            json={
                'messages': [{'role': 'user', 'content': 'test'}],
                'stream': True
            }
        ):
            # Create an instance of the API class
            api_instance = ChatCompletionsAPI()

            # Call the post method and consume the generator
            response = api_instance.post()

            # Try to iterate through the response and expect the ClientDisconnected exception
            with pytest.raises(ClientDisconnected):
                for chunk in response.response:
                    pass

            # Verify cancellation was requested
            assert cancellation_service.is_cancelled(request_id), "Request should be cancelled after disconnect"

    @patch('Middleware.api.handlers.impl.openai_api_handler.uuid.uuid4')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_chat_completions_streaming_broken_pipe(self, mock_globals, mock_handle_prompt, mock_uuid, app, setup_cancellation_service):
        """Test that BrokenPipeError during streaming triggers cancellation."""
        request_id = "test_openai_broken_pipe_456"
        mock_uuid.return_value = request_id  # Mock uuid to return our expected request_id

        def mock_generator():
            """Mock generator that raises BrokenPipeError."""
            yield "data: chunk1\n\n"
            raise BrokenPipeError()

        mock_handle_prompt.return_value = mock_generator()

        with app.test_request_context(
            '/chat/completions',
            method='POST',
            json={
                'messages': [{'role': 'user', 'content': 'test'}],
                'stream': True
            }
        ):
            api_instance = ChatCompletionsAPI()
            response = api_instance.post()

            with pytest.raises(BrokenPipeError):
                for chunk in response.response:
                    pass

            assert cancellation_service.is_cancelled(request_id), "Request should be cancelled after broken pipe"

    @patch('Middleware.api.handlers.impl.openai_api_handler.uuid.uuid4')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_chat_completions_streaming_generator_exit(self, mock_globals, mock_handle_prompt, mock_uuid, app, setup_cancellation_service):
        """Test that GeneratorExit during streaming triggers cancellation."""
        request_id = "test_openai_gen_exit_789"
        mock_uuid.return_value = request_id  # Mock uuid to return our expected request_id

        def mock_generator():
            """Mock generator that raises GeneratorExit."""
            yield "data: chunk1\n\n"
            raise GeneratorExit()

        mock_handle_prompt.return_value = mock_generator()

        with app.test_request_context(
            '/chat/completions',
            method='POST',
            json={
                'messages': [{'role': 'user', 'content': 'test'}],
                'stream': True
            }
        ):
            api_instance = ChatCompletionsAPI()
            response = api_instance.post()

            with pytest.raises(GeneratorExit):
                for chunk in response.response:
                    pass

            assert cancellation_service.is_cancelled(request_id), "Request should be cancelled after GeneratorExit"

    @patch('Middleware.api.handlers.impl.openai_api_handler.uuid.uuid4')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_completions_streaming_disconnect(self, mock_globals, mock_handle_prompt, mock_uuid, app, setup_cancellation_service):
        """Test that client disconnect during completions streaming triggers cancellation."""
        request_id = "test_completions_disconnect_123"
        mock_uuid.return_value = request_id  # Mock uuid to return our expected request_id

        def mock_generator():
            """Mock generator that raises ClientDisconnected."""
            yield "data: chunk1\n\n"
            raise ClientDisconnected()

        mock_handle_prompt.return_value = mock_generator()

        with app.test_request_context(
            '/v1/completions',
            method='POST',
            json={
                'prompt': 'test prompt',
                'stream': True
            }
        ):
            api_instance = CompletionsAPI()
            response = api_instance.post()

            with pytest.raises(ClientDisconnected):
                for chunk in response.response:
                    pass

            assert cancellation_service.is_cancelled(request_id), "Request should be cancelled after disconnect"

    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_no_request_id_in_context(self, mock_globals, mock_handle_prompt, app, setup_cancellation_service):
        """Test that disconnect without request_id in context logs warning but doesn't crash."""
        def mock_generator():
            """Mock generator that raises ClientDisconnected."""
            yield "data: chunk1\n\n"
            raise ClientDisconnected()

        mock_handle_prompt.return_value = mock_generator()

        with app.test_request_context(
            '/chat/completions',
            method='POST',
            json={
                'messages': [{'role': 'user', 'content': 'test'}],
                'stream': True
            }
        ):
            # Deliberately don't set g.current_request_id

            api_instance = ChatCompletionsAPI()
            response = api_instance.post()

            # Should not crash, just log a warning
            with pytest.raises(ClientDisconnected):
                for chunk in response.response:
                    pass
