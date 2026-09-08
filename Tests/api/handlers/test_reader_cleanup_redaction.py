"""Actual Eventlet reader teardown must retain privacy and request ownership."""
import logging
from unittest.mock import Mock

import eventlet
from eventlet.corolocal import local
from flask import Flask
import pytest

from Middleware.api.handlers.base import base_streaming as streaming
from Middleware.services.cancellation_service import cancellation_service
from Middleware.services.idempotency_service import idempotency_service
from Middleware.utilities import sensitive_logging_utils as privacy


@pytest.mark.parametrize('redacted', [True, False])
@pytest.mark.parametrize('disconnect', [False, True])
def test_reader_close_failure_keeps_redaction_and_releases_request(monkeypatch, capsys, caplog,
                                                                 redacted, disconnect):
    # Production patches threading.local before application imports.
    monkeypatch.setattr(privacy, '_request_context', local())
    previous = streaming._capture_request_context()
    released = Mock()
    monkeypatch.setattr(idempotency_service, 'release', released)
    started = eventlet.event.Event()
    closed = Mock()
    marker = 'synthetic-private-cleanup-message'
    request_id = 'reader-cleanup-test'

    class Source:
        def __iter__(self):
            return self

        def __next__(self):
            started.send(True)
            if disconnect:
                eventlet.event.Event().wait()
            raise StopIteration

        def close(self):
            closed()
            raise ValueError(marker)

    app = Flask('reader-cleanup-test')
    config = streaming.StreamingApiConfig('test', b':\n\n', 'text/plain', lambda _: False)
    caplog.set_level(logging.ERROR)
    response = None
    try:
        with app.test_request_context('/'):
            privacy.set_encryption_context(redacted)
            response = streaming.stream_with_eventlet_optimized(
                config, lambda *args, **kwargs: Source(), request_id, [], True)
            privacy.clear_encryption_context()
            eventlet.sleep(0)
            assert started.ready()
            if not disconnect:
                assert list(response.response) == []
            response.close()
            with eventlet.Timeout(1):
                while not released.called:
                    eventlet.sleep(0)
            response.close()
            assert not privacy.is_encryption_active()
        closed.assert_called_once()
        released.assert_called_once_with(request_id)
        assert not cancellation_service.is_cancelled(request_id)
        output = capsys.readouterr().err + caplog.text
        assert (marker in output) is (not redacted)
        if redacted:
            assert '[Redacted]' in output
    finally:
        if response is not None:
            response.close()
        cancellation_service.acknowledge_cancellation(request_id)
        streaming._restore_request_context(previous)
