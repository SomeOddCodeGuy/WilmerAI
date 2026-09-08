"""Cancellation callbacks must preserve the owning generation's log policy."""
import logging
import threading
from unittest.mock import Mock

import eventlet
from eventlet.corolocal import local
from flask import Flask
import pytest

from Middleware.api.handlers.impl.ollama_api_handler import CancelChatAPI
from Middleware.llmapis.handlers.base.base_api_transport import _AbortHandle
from Middleware.services.cancellation_service import cancellation_service
from Middleware.utilities import sensitive_logging_utils as privacy


@pytest.mark.parametrize('private', [True, False])
@pytest.mark.parametrize('failure_source', ['session', 'response'])
def test_delete_cancellation_keeps_generation_privacy(monkeypatch, caplog, private, failure_source):
    monkeypatch.setattr(privacy, '_request_context', local())
    request_id = 'review-cancel-owner'
    marker = 'synthetic-generation-cleanup-detail'
    session, response = Mock(), Mock()
    (session if failure_source == 'session' else response).close.side_effect = OSError(marker)
    app = Flask('review-cancel')
    app.add_url_rule('/api/chat', view_func=CancelChatAPI.as_view('cancel'), methods=['DELETE'])
    caplog.set_level(logging.DEBUG)
    registered = eventlet.event.Event()
    finished = eventlet.event.Event()
    generation = None
    try:
        def register_from_generation():
            privacy.set_encryption_context(private)
            try:
                handle = _AbortHandle(session, request_id, 'streaming')
                handle.response = response
                cancellation_service.register_abort_callback(request_id, handle.abort)
                registered.send(True)
                finished.wait()
            finally:
                privacy.clear_encryption_context()
        generation = eventlet.spawn(register_from_generation)
        with eventlet.Timeout(1):
            registered.wait()
        assert not privacy.is_encryption_active()
        with app.test_client() as client:
            result = client.delete('/api/chat', json={'request_id': request_id})
        assert result.status_code == 200
        session.close.assert_called_once()
        response.close.assert_called_once()
        assert cancellation_service.is_cancelled(request_id)
        assert not privacy.is_encryption_active()
        assert (marker in caplog.text) is (not private)
    finally:
        if not finished.ready():
            finished.send(True)
        if generation is not None:
            with eventlet.Timeout(1):
                generation.wait()
        cancellation_service.acknowledge_cancellation(request_id)
        privacy.clear_encryption_context()


@pytest.mark.parametrize('owner_private', [True, False])
@pytest.mark.parametrize('caller_private', [True, False])
@pytest.mark.parametrize('outcome', ['success', 'error', 'interruption'])
def test_deferred_callback_and_service_diagnostics_keep_owner_policy(
        monkeypatch, caplog, owner_private, caller_private, outcome):
    monkeypatch.setattr(privacy, '_request_context', threading.local())
    request_id = 'review-owned-callback'
    marker = 'synthetic-callback-diagnostic'
    observed = []
    errors = []
    logger = privacy.get_sensitive_logger(__name__)
    caplog.set_level(logging.DEBUG)

    def callback():
        observed.append(privacy.is_encryption_active())
        logger.warning(marker)
        privacy.clear_encryption_context()
        if outcome == 'error':
            raise ValueError(marker)
        if outcome == 'interruption':
            raise GeneratorExit()

    def register():
        try:
            privacy.set_encryption_context(owner_private)
            cancellation_service.register_abort_callback(request_id, callback)
        except BaseException as exc:
            errors.append(exc)
        finally:
            privacy.clear_encryption_context()

    thread = threading.Thread(target=register)
    try:
        thread.start()
        thread.join(2)
        assert not thread.is_alive() and not errors
        privacy.set_encryption_context(caller_private)
        if outcome == 'interruption':
            with pytest.raises(GeneratorExit):
                cancellation_service.request_cancellation(request_id)
        else:
            cancellation_service.request_cancellation(request_id)
        assert observed == [owner_private or caller_private]
        assert privacy.is_encryption_active() is caller_private
        assert (marker in caplog.text) is (not (owner_private or caller_private))
    finally:
        thread.join(2)
        cancellation_service.acknowledge_cancellation(request_id)
        privacy.clear_encryption_context()


@pytest.mark.parametrize('private', [True, False])
@pytest.mark.parametrize('interrupted', [True, False])
def test_immediate_callback_errors_keep_policy_and_restore_context(caplog, private, interrupted):
    request_id = 'review-immediate-callback'
    marker = 'synthetic-immediate-diagnostic'
    caplog.set_level(logging.ERROR)

    def callback():
        assert privacy.is_encryption_active() is private
        privacy.clear_encryption_context()
        if interrupted:
            raise GeneratorExit()
        raise ValueError(marker)

    try:
        privacy.set_encryption_context(private)
        cancellation_service.request_cancellation(request_id)
        if interrupted:
            with pytest.raises(GeneratorExit):
                cancellation_service.register_abort_callback(request_id, callback)
        else:
            cancellation_service.register_abort_callback(request_id, callback)
            assert (marker in caplog.text) is (not private)
        assert privacy.is_encryption_active() is private
        assert request_id not in cancellation_service._abort_callbacks
    finally:
        cancellation_service.acknowledge_cancellation(request_id)
        privacy.clear_encryption_context()


def test_callback_policies_do_not_bleed_between_owners_or_nested_cancellation():
    parent, child = 'review-parent-callback', 'review-child-callback'
    observed = []
    try:
        privacy.clear_encryption_context()
        cancellation_service.register_abort_callback(
            child, lambda: observed.append(('child', privacy.is_encryption_active())))
        privacy.set_encryption_context(True)

        def private_parent():
            cancellation_service.request_cancellation(child)
            observed.append(('parent', privacy.is_encryption_active()))

        cancellation_service.register_abort_callback(parent, private_parent)
        privacy.clear_encryption_context()
        cancellation_service.register_abort_callback(
            parent, lambda: observed.append(('ordinary', privacy.is_encryption_active())))
        cancellation_service.request_cancellation(parent)
        assert observed == [('child', True), ('parent', True), ('ordinary', False)]
        assert not privacy.is_encryption_active()
    finally:
        cancellation_service.acknowledge_cancellation(parent)
        cancellation_service.acknowledge_cancellation(child)
        privacy.clear_encryption_context()
