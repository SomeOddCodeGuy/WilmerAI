"""Small offline lifecycle checks using real WSGI close behavior."""
from unittest.mock import Mock

from flask import Flask
import pytest
from werkzeug.test import EnvironBuilder

from Middleware.api.handlers.base import base_streaming
from Middleware.services.idempotency_service import idempotency_service
from Middleware.services.cancellation_service import cancellation_service


CONFIG = base_streaming.StreamingApiConfig('review', b':\n\n', 'text/event-stream', lambda b: b == b'done')


@pytest.fixture(autouse=True)
def restore_request_context():
    snapshot = base_streaming._capture_request_context()
    yield
    base_streaming._restore_request_context(snapshot)


def test_fallback_close_before_iteration_releases_request():
    app = Flask(__name__)
    backend = Mock(return_value=iter([b'done']))
    request_id = 'review-preclose-fallback'
    key = 'review-preclose-fallback-key'
    idempotency_service.register(key, request_id)
    try:
        with app.test_request_context('/'):
            response = base_streaming.stream_response_fallback(CONFIG, backend, request_id, [], True)
            iterable = response(EnvironBuilder().get_environ(), lambda *a: None)
            iterable.close()
        backend.assert_not_called()
        assert idempotency_service.get_request_id_for_key(key) is None
    finally:
        idempotency_service.release(request_id)


def test_eventlet_close_before_iteration_stops_reader(monkeypatch):
    pytest.importorskip('eventlet')
    app = Flask(__name__)
    reader = Mock()
    spawn = Mock(return_value=reader)
    monkeypatch.setattr(base_streaming.eventlet, 'spawn', spawn)
    with app.test_request_context('/'):
        response = base_streaming.stream_with_eventlet_optimized(CONFIG, Mock(), 'review-preclose-eventlet', [], True)
        iterable = response(EnvironBuilder().get_environ(), lambda *a: None)
        iterable.close()
    assert reader.kill.called or any(call.args and call.args[0] == reader.kill for call in spawn.call_args_list)


@pytest.mark.parametrize('start_reader', [False, True])
def test_real_eventlet_pre_iteration_close_releases_ownership(start_reader):
    eventlet = pytest.importorskip('eventlet')
    app = Flask(__name__)
    entered, closed = [], []
    gate = eventlet.event.Event()
    request_id = 'ownership-preclose'
    key = 'ownership-preclose-key'

    def backend(*args, **kwargs):
        entered.append(True)
        try:
            gate.wait()
            yield b'done'
        finally:
            closed.append(True)

    idempotency_service.register(key, request_id)
    try:
        with app.test_request_context('/'):
            response = base_streaming.stream_with_eventlet_optimized(
                CONFIG, backend, request_id, [], True)
            if start_reader:
                eventlet.sleep(0)
            iterable = response(EnvironBuilder().get_environ(), lambda *args: None)
            iterable.close()
            iterable.close()
            eventlet.sleep(0)
            eventlet.sleep(0)
        assert bool(entered) is start_reader
        assert bool(closed) is start_reader
        assert idempotency_service.get_request_id_for_key(key) is None
        assert not cancellation_service.is_cancelled(request_id)
    finally:
        if not gate.ready():
            gate.send(True)
        eventlet.sleep(0)
        idempotency_service.release(request_id)
        cancellation_service.acknowledge_cancellation(request_id)


def test_eventlet_close_after_terminal_chunk_keeps_post_response_work():
    eventlet = pytest.importorskip('eventlet')
    app = Flask(__name__)
    gate = eventlet.event.Event()
    post_work = []
    request_id, key = 'ownership-terminal', 'ownership-terminal-key'

    def backend(*args, **kwargs):
        yield b'done'
        gate.wait()
        post_work.append(True)

    idempotency_service.register(key, request_id)
    try:
        with app.test_request_context('/'):
            response = base_streaming.stream_with_eventlet_optimized(CONFIG, backend, request_id, [], True)
            iterable = response(EnvironBuilder().get_environ(), lambda *args: None)
            assert next(iterable) == b'done'
            iterable.close()
            eventlet.sleep(0)
            assert not cancellation_service.is_cancelled(request_id)
            assert idempotency_service.get_request_id_for_key(key) == request_id
            gate.send(True)
            eventlet.sleep(0)
        assert post_work == [True]
        assert idempotency_service.get_request_id_for_key(key) is None
    finally:
        if not gate.ready():
            gate.send(True)
        eventlet.sleep(0)
        idempotency_service.release(request_id)
        cancellation_service.acknowledge_cancellation(request_id)


@pytest.mark.parametrize('consume_all', [False, True])
def test_fallback_closes_upstream_and_preserves_normal_completion(consume_all):
    app = Flask(__name__)
    closed, post_work = [], []

    def backend(*args, **kwargs):
        try:
            yield b'first'
            yield b'done'
            post_work.append(True)
        finally:
            closed.append(True)

    with app.test_request_context('/'):
        response = base_streaming.stream_response_fallback(CONFIG, backend, 'ownership-fallback', [], True)
        iterable = response(EnvironBuilder().get_environ(), lambda *args: None)
        assert next(iterable) == b'first'
        if consume_all:
            assert list(iterable) == [b'done']
        iterable.close()
        iterable.close()
    assert closed == [True]
    assert bool(post_work) is consume_all
    assert not cancellation_service.is_cancelled('ownership-fallback')
