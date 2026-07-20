# tests/api/handlers/impl/test_api_cancellation.py

import pytest
from unittest.mock import patch
from flask import Flask
from werkzeug.exceptions import ClientDisconnected

from Middleware.api.handlers.impl.ollama_api_handler import CancelChatAPI, CancelGenerateAPI
from Middleware.api.handlers.impl.openai_api_handler import ChatCompletionsAPI, CompletionsAPI
from Middleware.services.cancellation_service import cancellation_service


_HANDLER = 'Middleware.api.handlers.impl.openai_api_handler'


@pytest.fixture(autouse=True)
def isolate_user_config(mocker):
    """Pin the per-user config reads to benign defaults so these view tests
    cannot be broken (or silently repurposed) by edits to the repo's
    Public/Configs user files."""
    mocker.patch(f'{_HANDLER}.get_is_chat_complete_add_user_assistant', return_value=False)
    mocker.patch(f'{_HANDLER}.get_is_chat_complete_add_missing_assistant', return_value=False)
    mocker.patch(f'{_HANDLER}.get_encrypt_using_api_key', return_value=False)
    mocker.patch(f'{_HANDLER}.get_redact_log_output', return_value=False)
    mocker.patch(f'{_HANDLER}.check_openwebui_tool_request', return_value=None)


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
            with patch.object(cancellation_service, 'request_cancellation',
                              wraps=cancellation_service.request_cancellation) as spy:
                with pytest.raises(ClientDisconnected):
                    for chunk in response.response:
                        pass

            # Verify cancellation was requested by the disconnect handler, and then
            # acknowledged (cleared) by the stream teardown so the id doesn't leak.
            spy.assert_called_once_with(request_id)
            assert not cancellation_service.is_cancelled(request_id), \
                "Stream teardown must acknowledge the cancellation it requested"

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

            with patch.object(cancellation_service, 'request_cancellation',
                              wraps=cancellation_service.request_cancellation) as spy:
                with pytest.raises(BrokenPipeError):
                    for chunk in response.response:
                        pass

            spy.assert_called_once_with(request_id)
            assert not cancellation_service.is_cancelled(request_id), \
                "Stream teardown must acknowledge the cancellation it requested"

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

            with patch.object(cancellation_service, 'request_cancellation',
                              wraps=cancellation_service.request_cancellation) as spy:
                with pytest.raises(GeneratorExit):
                    for chunk in response.response:
                        pass

            spy.assert_called_once_with(request_id)
            assert not cancellation_service.is_cancelled(request_id), \
                "Stream teardown must acknowledge the cancellation it requested"

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

            with patch.object(cancellation_service, 'request_cancellation',
                              wraps=cancellation_service.request_cancellation) as spy:
                with pytest.raises(ClientDisconnected):
                    for chunk in response.response:
                        pass

            spy.assert_called_once_with(request_id)
            assert not cancellation_service.is_cancelled(request_id), \
                "Stream teardown must acknowledge the cancellation it requested"

class TestCancellationAcknowledgedOnStreamTeardown:
    """A cancellation that lands during the final responder node has no later
    node boundary to acknowledge it; the streaming teardown must clear it so
    the registry cannot grow forever."""

    @staticmethod
    def _test_config():
        from Middleware.api.handlers.base import base_streaming
        return base_streaming.StreamingApiConfig(
            api_label="Test", heartbeat_message=b':\n\n', mimetype='text/event-stream',
            chunk_signals_done=lambda encoded: False)

    def test_fallback_stream_acknowledges_cancellation_on_teardown(self, app, setup_cancellation_service):
        from Middleware.api.handlers.base import base_streaming

        request_id = "req-teardown-fallback"

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            yield 'data: {"choices":[{"delta":{"content":"tok"}}]}\n\n'
            # Cancellation lands mid-stream and the backend stops without any
            # later node boundary running to acknowledge it.
            cancellation_service.request_cancellation(req_id)

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_response_fallback(
                self._test_config(), backend, request_id,
                [{"role": "user", "content": "hi"}], True)
            list(response.response)

        assert not cancellation_service.is_cancelled(request_id), \
            "Stream teardown must acknowledge the pending cancellation"

    def test_eventlet_stream_acknowledges_cancellation_on_teardown(self, app, setup_cancellation_service):
        eventlet = pytest.importorskip("eventlet")
        from Middleware.api.handlers.base import base_streaming

        request_id = "req-teardown-eventlet"

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            yield 'data: {"choices":[{"delta":{"content":"tok"}}]}\n\n'
            cancellation_service.request_cancellation(req_id)

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_with_eventlet_optimized(
                self._test_config(), backend, request_id,
                [{"role": "user", "content": "hi"}], True)
            list(response.response)

        # The reader greenlet's finally may run just after the client generator
        # finishes; give it a moment.
        for _ in range(200):
            if not cancellation_service.is_cancelled(request_id):
                break
            eventlet.sleep(0.01)

        assert not cancellation_service.is_cancelled(request_id), \
            "Reader teardown must acknowledge the pending cancellation"
