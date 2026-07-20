# Tests/api/handlers/test_base_streaming.py
#
# Direct tests for the shared streaming machinery in
# Middleware/api/handlers/base/base_streaming.py: the implementation selector,
# request-context capture/restore across the view's finally-clear, the Eventlet
# heartbeat, the Eventlet pre-response error path, and the Eventlet mid-stream
# disconnect teardown chain (cancel -> reader kill -> acknowledge -> release).
# The Flask test client never monkey-patches Eventlet, so the endpoint-level
# tests only exercise the fallback path; these tests cover the rest.

import logging

import pytest
from unittest.mock import patch
from werkzeug.exceptions import ClientDisconnected

from Middleware.api import api_helpers
from Middleware.api.handlers.base import base_streaming
from Middleware.common import instance_global_variables
from Middleware.services.cancellation_service import cancellation_service
from Middleware.services.idempotency_service import idempotency_service
from Middleware.utilities.sensitive_logging_utils import (
    set_encryption_context, clear_encryption_context, is_encryption_active,
)


def _sse_config():
    return base_streaming.StreamingApiConfig(
        api_label="Test", heartbeat_message=b':\n\n', mimetype='text/event-stream',
        chunk_signals_done=lambda encoded: encoded.strip() == b'data: [DONE]')


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


@pytest.fixture
def clean_request_context():
    """Clear all request-scoped thread-locals the streaming code restores."""
    yield
    instance_global_variables.clear_api_type()
    api_helpers.clear_request_context()
    clear_encryption_context()


class TestStreamingSelector:
    """handle_streaming_request must pick the Eventlet streamer only when
    Eventlet is installed AND actively monkey-patching the socket layer."""

    def test_uses_eventlet_streamer_when_monkey_patched(self, mocker):
        pytest.importorskip("eventlet")
        mocker.patch.object(base_streaming.eventlet.patcher, 'is_monkey_patched', return_value=True)
        optimized = mocker.patch.object(base_streaming, 'stream_with_eventlet_optimized',
                                        return_value='OPTIMIZED')
        fallback = mocker.patch.object(base_streaming, 'stream_response_fallback',
                                       return_value='FALLBACK')
        config = _sse_config()

        def backend(*args, **kwargs):
            yield 'data: tok\n\n'

        result = base_streaming.handle_streaming_request(
            config, backend, 'req-sel-1', [{"role": "user", "content": "hi"}], True,
            api_key='k', tools=[{"type": "function"}], tool_choice='auto')

        assert result == 'OPTIMIZED'
        optimized.assert_called_once_with(
            config, backend, 'req-sel-1', [{"role": "user", "content": "hi"}], True,
            api_key='k', tools=[{"type": "function"}], tool_choice='auto')
        fallback.assert_not_called()

    def test_falls_back_when_not_monkey_patched(self, mocker):
        pytest.importorskip("eventlet")
        mocker.patch.object(base_streaming.eventlet.patcher, 'is_monkey_patched', return_value=False)
        optimized = mocker.patch.object(base_streaming, 'stream_with_eventlet_optimized',
                                        return_value='OPTIMIZED')
        fallback = mocker.patch.object(base_streaming, 'stream_response_fallback',
                                       return_value='FALLBACK')
        config = _sse_config()

        def backend(*args, **kwargs):
            yield 'data: tok\n\n'

        result = base_streaming.handle_streaming_request(
            config, backend, 'req-sel-2', [{"role": "user", "content": "hi"}], True)

        assert result == 'FALLBACK'
        fallback.assert_called_once_with(
            config, backend, 'req-sel-2', [{"role": "user", "content": "hi"}], True,
            api_key=None, tools=None, tool_choice=None)
        optimized.assert_not_called()


class TestRequestContextRestoration:
    """The view's finally block clears the request-scoped thread-locals before
    the WSGI server consumes the streaming generator. The generator must run
    the backend under the context captured at call time, or every streaming
    request would lose its api_type / workflow override / request user /
    encryption flag mid-flight."""

    def test_fallback_generator_restores_context_cleared_by_view(self, app, clean_request_context):
        seen = {}

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            seen['api_type'] = instance_global_variables.get_api_type()
            seen['workflow'] = api_helpers.get_active_workflow_override()
            seen['user'] = instance_global_variables.get_request_user()
            seen['encryption'] = is_encryption_active()
            yield 'data: tok\n\n'

        with app.test_request_context('/v1/chat/completions'):
            instance_global_variables.set_api_type('openaichatcompletion')
            instance_global_variables.set_workflow_override('wf-1')
            instance_global_variables.set_request_user('alice')
            set_encryption_context(True)

            response = base_streaming.stream_response_fallback(
                _sse_config(), backend, 'req-ctx', [{"role": "user", "content": "hi"}], True)

            # Simulate the view's finally: everything is cleared before the
            # WSGI server pulls the first chunk.
            instance_global_variables.clear_api_type()
            api_helpers.clear_request_context()
            clear_encryption_context()

            list(response.response)

        assert seen == {
            'api_type': 'openaichatcompletion',
            'workflow': 'wf-1',
            'user': 'alice',
            'encryption': True,
        }


class TestDisconnectWithoutRequestId:
    """base_streaming guards every cancellation call with `if request_id`; a
    caller passing request_id=None must not crash and must not request a
    cancellation for a bogus id."""

    def test_fallback_disconnect_with_none_request_id(self, app, reset_services):
        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            yield 'data: tok\n\n'
            raise ClientDisconnected()

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_response_fallback(
                _sse_config(), backend, None, [{"role": "user", "content": "hi"}], True)
            with patch.object(cancellation_service, 'request_cancellation') as spy:
                with pytest.raises(ClientDisconnected):
                    list(response.response)

        spy.assert_not_called()


class TestEventletHeartbeat:
    """While the backend is idle (prefill), the Eventlet streamer must emit the
    config's heartbeat bytes so the client connection stays alive and a dead
    socket is detected within one interval."""

    def test_heartbeats_emitted_while_backend_idle(self, app, monkeypatch, reset_services):
        eventlet = pytest.importorskip("eventlet")
        monkeypatch.setattr(base_streaming, 'HEARTBEAT_INTERVAL', 0.01)

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            eventlet.sleep(0.15)  # simulated prefill: no data for many intervals
            yield 'data: tok\n\n'
            yield 'data: [DONE]\n\n'

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_with_eventlet_optimized(
                _sse_config(), backend, 'req-hb', [{"role": "user", "content": "hi"}], True)
            chunks = list(response.response)

        heartbeats = [c for c in chunks if c == b':\n\n']
        assert len(heartbeats) >= 1, "idle backend must produce at least one heartbeat"
        assert b'data: tok\n\n' in chunks
        assert chunks[-1] == b'data: [DONE]\n\n', "stream must end at the terminator"
        # All heartbeats precede the first data chunk (none after the terminator).
        first_data = chunks.index(b'data: tok\n\n')
        assert all(c == b':\n\n' for c in chunks[:first_data])


class TestEventletPreResponseError:
    """A backend failure before the first chunk must propagate (the client sees
    a connection reset, which is what triggers its retry), be logged as a
    distinct pre-response WARNING with the request_id, and still release the
    request's idempotency entry."""

    def test_backend_error_before_first_chunk(self, app, reset_services, caplog):
        eventlet = pytest.importorskip("eventlet")
        idempotency_service.register('key-err', 'req-err')

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            raise RuntimeError("backend blew up before first token")
            yield  # pragma: no cover (makes this a generator)

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_with_eventlet_optimized(
                _sse_config(), backend, 'req-err', [{"role": "user", "content": "hi"}], True)
            with caplog.at_level(logging.WARNING, logger='Middleware.api.handlers.base.base_streaming'):
                with pytest.raises(RuntimeError):
                    list(response.response)

        assert 'pre-response server error' in caplog.text
        assert 'req-err' in caplog.text
        assert 'awaiting-backend' in caplog.text, \
            "no data was ever buffered, so the phase must be awaiting-backend"

        # The reader greenlet's finally releases the idempotency entry.
        for _ in range(200):
            if idempotency_service.get_request_id_for_key('key-err') is None:
                break
            eventlet.sleep(0.01)
        assert idempotency_service.get_request_id_for_key('key-err') is None


class TestEventletMidStreamDisconnect:
    """A client disconnect mid-stream on the Eventlet path must request
    cancellation, kill the reader greenlet, and the reader's teardown must
    acknowledge the cancellation and release the idempotency entry."""

    def test_disconnect_cancels_and_tears_down_reader(self, app, reset_services):
        eventlet = pytest.importorskip("eventlet")
        idempotency_service.register('key-dc', 'req-dc')

        def backend(req_id, messages, stream, api_key=None, tools=None, tool_choice=None):
            yield 'data: a\n\n'
            yield 'data: b\n\n'
            eventlet.sleep(5)  # blocked mid-generation when the client vanishes
            yield 'data: c\n\n'  # pragma: no cover (reader is killed first)

        with app.test_request_context('/v1/chat/completions'):
            response = base_streaming.stream_with_eventlet_optimized(
                _sse_config(), backend, 'req-dc', [{"role": "user", "content": "hi"}], True)
            gen = response.response
            assert next(gen) == b'data: a\n\n'
            assert next(gen) == b'data: b\n\n'
            # The WSGI server closes the generator when the client socket dies.
            with patch.object(cancellation_service, 'request_cancellation',
                              wraps=cancellation_service.request_cancellation) as spy:
                gen.close()

        spy.assert_called_once_with('req-dc')

        # The killed reader's finally must acknowledge the cancellation and
        # release the idempotency entry; give the hub time to run it.
        for _ in range(500):
            if (not cancellation_service.is_cancelled('req-dc')
                    and idempotency_service.get_request_id_for_key('key-dc') is None):
                break
            eventlet.sleep(0.01)

        assert not cancellation_service.is_cancelled('req-dc'), \
            "reader teardown must acknowledge the requested cancellation"
        assert idempotency_service.get_request_id_for_key('key-dc') is None, \
            "reader teardown must release the idempotency entry"
