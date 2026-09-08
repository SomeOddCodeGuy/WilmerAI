"""Privacy checks at framework and shared workflow error boundaries."""
import logging
import traceback
from unittest.mock import Mock

from flask import Flask
import pytest

from Middleware.api.handlers.base import base_streaming
from Middleware.utilities.sensitive_logging_utils import (
    clear_encryption_context, is_encryption_active, protect_flask_error_logging,
    set_encryption_context,
)

MARKER = 'synthetic-private-error-content'


@pytest.fixture(autouse=True)
def restore_context():
    previous = base_streaming._capture_request_context()
    clear_encryption_context()
    yield
    base_streaming._restore_request_context(previous)


@pytest.mark.parametrize('redacted', [True, False])
def test_flask_error_after_view_cleanup_and_next_request(caplog, redacted):
    app = Flask('request-error-redaction')
    old_filters = list(app.logger.filters)
    protect_flask_error_logging(app)

    @app.get('/failure/<mode>')
    def failure(mode):
        set_encryption_context(mode == 'private')
        try:
            raise ValueError(MARKER)
        finally:
            clear_encryption_context()

    caplog.set_level(logging.ERROR)
    try:
        result = app.test_client().get('/failure/' + ('private' if redacted else 'ordinary'))
        assert result.status_code == 500
        assert MARKER not in result.get_data(as_text=True)
        assert (MARKER in caplog.text) is (not redacted)
        assert not is_encryption_active()
        caplog.clear()
        assert app.test_client().get('/failure/ordinary').status_code == 500
        assert MARKER in caplog.text
    finally:
        app.logger.filters[:] = old_filters


@pytest.mark.parametrize('mode', ['fallback', 'eventlet'])
@pytest.mark.parametrize('redacted', [True, False])
def test_stream_error_logs_and_escaping_traceback_honor_context(caplog, mode, redacted):
    app = Flask(__name__)
    config = base_streaming.StreamingApiConfig('redaction', b':\n\n', 'text/event-stream', lambda _: False)

    def backend(*args, **kwargs):
        yield b'first'
        raise ValueError(MARKER)

    factory = (base_streaming.stream_response_fallback if mode == 'fallback'
               else base_streaming.stream_with_eventlet_optimized)
    caplog.set_level(logging.ERROR)
    with app.test_request_context('/'):
        set_encryption_context(redacted)
        response = factory(config, backend, 'redaction-stream', [], True)
        clear_encryption_context()
        try:
            assert next(response.response) == b'first'
            assert not is_encryption_active()
            with pytest.raises(RuntimeError if redacted else ValueError):
                try:
                    next(response.response)
                except Exception:
                    rendered = traceback.format_exc()
                    assert (MARKER in rendered) is (not redacted)
                    raise
            assert (MARKER in caplog.text) is (not redacted)
        finally:
            response.close()
        assert not is_encryption_active()


def test_stream_close_error_still_releases_owner_and_restores_context():
    class Source:
        close = Mock(side_effect=ValueError(MARKER))

        def __iter__(self):
            return self

        def __next__(self):
            raise StopIteration

    source = Source()
    released = Mock()
    set_encryption_context(True)
    response = base_streaming._build_streaming_response(source, 'text/plain', released)
    clear_encryption_context()
    with pytest.raises(RuntimeError, match='Redacted'):
        response.close()
    response.close()
    source.close.assert_called_once()
    released.assert_called_once()
    assert not is_encryption_active()


@pytest.mark.parametrize('redacted', [True, False])
def test_dynamic_module_error_uses_request_redaction(tmp_path, caplog, redacted):
    from Middleware.workflows.tools.dynamic_module_loader import run_dynamic_module
    module = tmp_path / 'synthetic_module.py'
    module.write_text("def Invoke():\n    raise RuntimeError('synthetic-private-error-content')\n")
    caplog.set_level(logging.ERROR)
    set_encryption_context(redacted)
    result = run_dynamic_module(str(module))
    assert 'unexpected error' in result
    assert (MARKER in caplog.text) is (not redacted)


@pytest.mark.parametrize('redacted', [True, False])
def test_base_transport_failure_does_not_leak_to_logs_or_stderr(monkeypatch, caplog, capsys, redacted):
    from Middleware.llmapis.handlers.base.base_api_transport import BaseApiTransport
    transport = BaseApiTransport('https://example.com', '', {})
    monkeypatch.setattr(transport.session, 'post', Mock(side_effect=ValueError(MARKER)))
    caplog.set_level(logging.ERROR)
    set_encryption_context(redacted)
    try:
        with pytest.raises(ValueError):
            transport.execute_non_streaming_post('https://example.com', {})
    finally:
        transport.close()
    assert (MARKER in caplog.text) is (not redacted)
    if redacted:
        assert MARKER not in capsys.readouterr().err


@pytest.mark.parametrize('stream', [True, False])
@pytest.mark.parametrize('redacted', [True, False])
def test_llm_failover_error_respects_request_redaction(monkeypatch, caplog, capsys, stream, redacted):
    from Middleware.llmapis import llm_api
    service = object.__new__(llm_api.LlmApiService)
    service.endpoint_file = {}
    service.stream = stream
    service._endpoint_name = 'synthetic-primary'
    service._backup_endpoint_name = 'synthetic-backup'
    service._has_backup = True
    service._api_handler = Mock()
    service._api_handler.handle_non_streaming.side_effect = ValueError(MARKER)
    service._api_handler.handle_streaming.side_effect = ValueError(MARKER)
    backup = Mock()
    backup.get_response_from_llm.return_value = iter(['ok']) if stream else 'ok'
    monkeypatch.setattr(service, '_build_backup_service', lambda: backup)
    monkeypatch.setattr(llm_api, '_acquire_endpoint_gate', lambda: False)
    caplog.set_level(logging.WARNING)
    set_encryption_context(redacted)
    value = service.get_response_from_llm(conversation=[])
    assert (list(value) if stream else value) == (['ok'] if stream else 'ok')
    assert (MARKER in caplog.text) is (not redacted)
    assert MARKER not in capsys.readouterr().err
