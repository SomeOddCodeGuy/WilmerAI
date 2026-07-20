# tests/api/handlers/impl/test_api_idempotency.py

import logging

import pytest
from unittest.mock import patch
from flask import Flask

from Middleware.api.handlers.base import base_streaming
from Middleware.api.handlers.impl.openai_api_handler import ChatCompletionsAPI, CompletionsAPI
from Middleware.services.cancellation_service import cancellation_service
from Middleware.services.idempotency_service import idempotency_service


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
    """A bare Flask app; the view classes are invoked directly under its context."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def reset_services():
    """Clear the idempotency and cancellation singletons around each test."""
    idempotency_service.clear()
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)
    yield
    idempotency_service.clear()
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)


def _fixed_uuid(monkeypatch_target, value):
    """Patch uuid.uuid4 in the handler module to a fixed request id."""
    return patch('Middleware.api.handlers.impl.openai_api_handler.uuid.uuid4', return_value=value)


class TestIdempotencyWiringNonStreaming:
    """Non-streaming admission registers the key and releases it on completion."""

    @patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_registers_during_flight_and_releases_after(self, mock_globals, mock_handle, mock_builder,
                                                         app, reset_services):
        seen = {}

        def capture(*args, **kwargs):
            # Prove the key is bound to THIS request while the workflow runs.
            # Keys are stored scoped; no Authorization header => "anon" scope.
            seen['bound'] = idempotency_service.get_request_id_for_key('anon:key-N')
            return "done"

        mock_handle.side_effect = capture
        mock_builder.build_openai_chat_completion_response.return_value = {"id": "chatcmpl-1"}

        with _fixed_uuid('openai', 'req-N'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-N'},
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False},
            ):
                ChatCompletionsAPI().post()

        assert seen['bound'] == 'req-N', "key must be bound to the request while it runs"
        assert idempotency_service.get_request_id_for_key('anon:key-N') is None, \
            "non-streaming completion must release the key in the view finally"

    @patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_legacy_client_without_header_registers_nothing(self, mock_globals, mock_handle, mock_builder,
                                                            app, reset_services):
        mock_handle.return_value = "done"
        mock_builder.build_openai_chat_completion_response.return_value = {"id": "chatcmpl-1"}

        with _fixed_uuid('openai', 'req-L'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False},
            ):
                ChatCompletionsAPI().post()

        # No header => nothing tracked, behaves exactly as a legacy client.
        assert idempotency_service.get_request_id_for_key('req-L') is None


    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_non_streaming_error_still_releases(self, mock_globals, mock_handle, app, reset_services):
        """A workflow failure on the non-streaming path must not leave the key
        registered: the view's finally releases it even when dispatch raises."""
        mock_handle.side_effect = RuntimeError("workflow blew up")

        with _fixed_uuid('openai', 'req-F'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-F'},
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False},
            ):
                with pytest.raises(RuntimeError):
                    ChatCompletionsAPI().post()

        assert idempotency_service.get_request_id_for_key('anon:key-F') is None, \
            "the view finally must release the key when dispatch raises"


class TestIdempotencyDuplicateCancellation:
    """A duplicate in-flight key cancels the orphaned original and rebinds fresh."""

    @patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_duplicate_key_cancels_original(self, mock_globals, mock_handle, mock_builder, app, reset_services):
        # Original request A is still in flight under key K (anon scope: the
        # duplicate below sends no Authorization header).
        idempotency_service.register('anon:key-K', 'req-A')

        rebound = {}

        def capture(*args, **kwargs):
            rebound['bound'] = idempotency_service.get_request_id_for_key('anon:key-K')
            return "done"

        mock_handle.side_effect = capture
        mock_builder.build_openai_chat_completion_response.return_value = {"id": "chatcmpl-2"}

        with _fixed_uuid('openai', 'req-B'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-K'},
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False},
            ):
                with patch.object(cancellation_service, 'request_cancellation',
                                  wraps=cancellation_service.request_cancellation) as spy:
                    ChatCompletionsAPI().post()

        # The orphaned original was cancelled by the duplicate's admission.
        spy.assert_called_once_with('req-A')
        # The key was rebound to the new request while it ran.
        assert rebound['bound'] == 'req-B'

    def test_displaced_original_teardown_preserves_new_binding(self, app, reset_services):
        """base_streaming's guarded release for a displaced original must not
        remove the newer request's live binding."""
        idempotency_service.register('key-K', 'req-A')
        idempotency_service.register('key-K', 'req-B')  # req-A displaced by req-B

        config = base_streaming.StreamingApiConfig(
            api_label="Test", heartbeat_message=b':\n\n', mimetype='text/event-stream',
            chunk_signals_done=lambda encoded: False)

        # req-A's stream tears down late (it was the orphan). Its teardown must
        # be a no-op for the key, which now belongs to req-B.
        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            yield 'data: tok\n\n'

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_response_fallback(
                config, backend, 'req-A', [{"role": "user", "content": "hi"}], True)
            list(response.response)

        assert idempotency_service.get_request_id_for_key('key-K') == 'req-B', \
            "displaced original's teardown must not clobber the newer binding"


class TestIdempotencyKeyScoping:
    """Registry entries are scoped per client API key (by hash) so independent
    clients reusing the same idempotency key value cannot displace each other."""

    @patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_same_key_different_api_keys_do_not_cancel(self, mock_globals, mock_handle, mock_builder,
                                                       app, reset_services):
        from Middleware.utilities.encryption_utils import get_api_key_hash_if_available
        scope_a = get_api_key_hash_if_available('client-a-secret')
        # Client A's request is in flight under its own scope.
        idempotency_service.register(f'{scope_a}:key-1', 'req-A')

        mock_handle.return_value = "done"
        mock_builder.build_openai_chat_completion_response.return_value = {"id": "chatcmpl-3"}

        with _fixed_uuid('openai', 'req-B'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-1',
                         'Authorization': 'Bearer client-b-secret'},
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False},
            ):
                with patch.object(cancellation_service, 'request_cancellation',
                                  wraps=cancellation_service.request_cancellation) as spy:
                    ChatCompletionsAPI().post()

        spy.assert_not_called()
        assert idempotency_service.get_request_id_for_key(f'{scope_a}:key-1') == 'req-A', \
            "client A's in-flight binding must survive client B reusing the same key value"

    @patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_same_key_same_api_key_still_cancels(self, mock_globals, mock_handle, mock_builder,
                                                 app, reset_services):
        from Middleware.utilities.encryption_utils import get_api_key_hash_if_available
        scope = get_api_key_hash_if_available('client-a-secret')
        idempotency_service.register(f'{scope}:key-1', 'req-A')

        mock_handle.return_value = "done"
        mock_builder.build_openai_chat_completion_response.return_value = {"id": "chatcmpl-4"}

        with _fixed_uuid('openai', 'req-B'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-1',
                         'Authorization': 'Bearer client-a-secret'},
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': False},
            ):
                with patch.object(cancellation_service, 'request_cancellation',
                                  wraps=cancellation_service.request_cancellation) as spy:
                    ChatCompletionsAPI().post()

        # A true retry (same client, same key) still displaces and cancels.
        spy.assert_called_once_with('req-A')


class TestIdempotencyStreamingRelease:
    """Streaming defers the release to the stream teardown, not the view finally."""

    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_streaming_release_deferred_to_teardown(self, mock_globals, mock_handle, app, reset_services):
        def gen():
            yield "data: chunk1\n\n"

        mock_handle.return_value = gen()

        with _fixed_uuid('openai', 'req-S'):
            with app.test_request_context(
                '/v1/chat/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-S'},
                json={'messages': [{'role': 'user', 'content': 'hi'}], 'stream': True},
            ):
                response = ChatCompletionsAPI().post()

                # The view has returned the streaming Response but has NOT yet
                # consumed it: the key must still be in flight (release deferred).
                assert idempotency_service.get_request_id_for_key('anon:key-S') == 'req-S'

                # Consuming the stream runs the teardown, which releases the key.
                list(response.response)

        assert idempotency_service.get_request_id_for_key('anon:key-S') is None

    def test_eventlet_stream_releases_idempotency_on_teardown(self, app, reset_services):
        eventlet = pytest.importorskip("eventlet")

        idempotency_service.register('key-EV', 'req-EV')

        config = base_streaming.StreamingApiConfig(
            api_label="Test", heartbeat_message=b':\n\n', mimetype='text/event-stream',
            chunk_signals_done=lambda encoded: False)

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            yield 'data: tok\n\n'

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_with_eventlet_optimized(
                config, backend, 'req-EV', [{"role": "user", "content": "hi"}], True)
            list(response.response)

        # The reader greenlet's finally may run just after the client generator
        # finishes; give it a moment (mirrors the cancellation teardown test).
        for _ in range(200):
            if idempotency_service.get_request_id_for_key('key-EV') is None:
                break
            eventlet.sleep(0.01)

        assert idempotency_service.get_request_id_for_key('key-EV') is None


class TestPreResponseInstrumentation:
    """Pre-response disconnects/failures are logged with the request id so the
    root cause of connection-reset-before-response can be found from the logs."""

    @staticmethod
    def _config():
        return base_streaming.StreamingApiConfig(
            api_label="Test", heartbeat_message=b':\n\n', mimetype='text/event-stream',
            chunk_signals_done=lambda encoded: False)

    def test_fallback_pre_response_server_error_logged_and_released(self, app, reset_services, caplog):
        idempotency_service.register('key-E', 'req-E')

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            raise RuntimeError("backend blew up before first token")
            yield  # pragma: no cover (makes this a generator)

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_response_fallback(
                self._config(), backend, 'req-E', [{"role": "user", "content": "hi"}], True)
            with caplog.at_level(logging.WARNING, logger='Middleware.api.handlers.base.base_streaming'):
                with pytest.raises(RuntimeError):
                    list(response.response)

        assert 'pre-response server error' in caplog.text
        assert 'req-E' in caplog.text
        # The registry entry must be released even on a pre-response failure.
        assert idempotency_service.get_request_id_for_key('key-E') is None

    def test_fallback_pre_response_client_disconnect_logged(self, app, reset_services, caplog):
        from werkzeug.exceptions import ClientDisconnected

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            raise ClientDisconnected()
            yield  # pragma: no cover (makes this a generator)

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_response_fallback(
                self._config(), backend, 'req-D', [{"role": "user", "content": "hi"}], True)
            with patch.object(cancellation_service, 'request_cancellation',
                              wraps=cancellation_service.request_cancellation) as spy:
                with caplog.at_level(logging.WARNING, logger='Middleware.api.handlers.base.base_streaming'):
                    with pytest.raises(ClientDisconnected):
                        list(response.response)

        assert 'pre-response client disconnect' in caplog.text
        assert 'req-D' in caplog.text
        # A pre-response client disconnect must still request downstream cancellation.
        spy.assert_called_once_with('req-D')


class TestCompletionsEndpointIdempotency:
    """The legacy /v1/completions endpoint honors the same contract."""

    @patch('Middleware.api.handlers.impl.openai_api_handler.parse_conversation')
    @patch('Middleware.api.handlers.impl.openai_api_handler.response_builder')
    @patch('Middleware.api.handlers.impl.openai_api_handler.handle_user_prompt')
    @patch('Middleware.api.handlers.impl.openai_api_handler.instance_global_variables')
    def test_completions_non_streaming_releases(self, mock_globals, mock_handle, mock_builder, mock_parse,
                                                app, reset_services):
        mock_parse.return_value = [{"role": "user", "content": "hi"}]
        mock_handle.return_value = "done"
        mock_builder.build_openai_completion_response.return_value = {"id": "cmpl-1"}

        with _fixed_uuid('openai', 'req-C'):
            with app.test_request_context(
                '/v1/completions', method='POST',
                headers={'X-Idempotency-Key': 'key-C'},
                json={'prompt': 'hi', 'stream': False},
            ):
                CompletionsAPI().post()

        assert idempotency_service.get_request_id_for_key('key-C') is None
