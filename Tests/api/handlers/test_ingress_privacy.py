"""Exercise privacy activation through actual Flask API entry points, offline."""
import logging

from flask import Flask
import pytest

from Middleware.api.handlers.impl import openai_api_handler as openai
from Middleware.api.handlers.impl import ollama_api_handler as ollama
from Middleware.api.handlers.base import base_streaming
from Middleware.common import instance_global_variables as globals_
from Middleware.utilities import config_utils
from Middleware.utilities.sensitive_logging_utils import (
    clear_encryption_context, is_encryption_active, protect_flask_error_logging,
)

MARKER = 'synthetic-private-ingress-content'


@pytest.mark.parametrize('module,view,is_chat', [
    pytest.param(openai, openai.ChatCompletionsAPI, True, id='openai-chat'),
    pytest.param(openai, openai.CompletionsAPI, False, id='openai-completions'),
    pytest.param(ollama, ollama.ApiChatAPI, True, id='ollama-chat'),
    pytest.param(ollama, ollama.GenerateAPI, False, id='ollama-generate'),
])
@pytest.mark.parametrize('policy', ['redaction', 'encryption', 'ordinary'])
def test_ingress_payload_respects_selected_user_policy(monkeypatch, caplog, module, view,
                                                       is_chat, policy):
    previous = base_streaming._capture_request_context()
    clear_encryption_context()
    globals_.clear_request_user()
    globals_.clear_workflow_override()
    monkeypatch.setattr(globals_, 'USERS', ['private-user', 'ordinary-user'])
    configs = {
        'private-user': {'redactLogOutput': policy == 'redaction',
                         'encryptUsingApiKey': policy == 'encryption'},
        'ordinary-user': {},
    }
    for config in configs.values():
        config.update(chatCompleteAddUserAssistant=False, chatCompletionAddMissingAssistantGenerator=False)
    monkeypatch.setattr(config_utils, 'get_user_config_for', lambda user: configs[user])
    observed = []

    def backend(*args, **kwargs):
        observed.append((globals_.get_request_user(), is_encryption_active()))
        return 'ordinary response'

    monkeypatch.setattr(module, 'handle_user_prompt', backend)
    app = Flask('ingress-privacy-review')
    app.config['TESTING'] = True
    app.add_url_rule('/review', view_func=view.post, methods=['POST'])
    caplog.set_level(logging.INFO if is_chat else logging.DEBUG)
    client = app.test_client()
    try:
        payload = {'model': 'private-user', 'stream': False}
        payload.update({'messages': [{'role': 'user', 'content': MARKER}]} if is_chat
                       else {'prompt': MARKER})
        headers = {'Authorization': 'Bearer synthetic-review-key'} if policy == 'encryption' else {}
        response = client.post('/review', json=payload, headers=headers)
        assert response.status_code == 200
        assert observed == [('private-user', policy != 'ordinary')]
        assert not is_encryption_active()
        private_log = caplog.text
        caplog.clear()
        payload['model'] = 'ordinary-user'
        assert client.post('/review', json=payload).status_code == 200
        assert observed[-1] == ('ordinary-user', False)
        assert MARKER in caplog.text
        assert not is_encryption_active()
        assert (MARKER in private_log) is (policy == 'ordinary'), private_log
    finally:
        base_streaming._restore_request_context(previous)


@pytest.fixture(params=[
    (openai, openai.ChatCompletionsAPI, True),
    (openai, openai.CompletionsAPI, False),
    (ollama, ollama.ApiChatAPI, True),
    (ollama, ollama.GenerateAPI, False),
], ids=['openai-chat', 'openai-completions', 'ollama-chat', 'ollama-generate'])
def ingress(request, monkeypatch, caplog):
    module, view, is_chat = request.param
    previous = base_streaming._capture_request_context()
    clear_encryption_context()
    globals_.clear_request_user()
    globals_.clear_workflow_override()
    monkeypatch.setattr(globals_, 'USERS', [MARKER, 'ordinary-user'])
    config = {'redactLogOutput': True, 'chatCompleteAddUserAssistant': False,
              'chatCompletionAddMissingAssistantGenerator': False}
    monkeypatch.setattr(config_utils, 'get_user_config_for', lambda user: config)
    app = Flask('ingress-boundaries')
    app.config.update(TESTING=True)
    filters = list(app.logger.filters)
    protect_flask_error_logging(app)
    app.add_url_rule('/review', view_func=view.post, methods=['POST'])
    payload = {'model': MARKER, 'stream': False}
    payload.update({'messages': [{'role': 'user', 'content': MARKER}]} if is_chat
                   else {'prompt': MARKER})
    caplog.set_level(logging.DEBUG)
    try:
        yield module, app, config, payload
    finally:
        app.logger.filters[:] = filters
        base_streaming._restore_request_context(previous)


@pytest.mark.parametrize('rejection', ['unknown-user', 'shared-workflow-required'])
def test_rejected_ingress_never_evaluates_payload_diagnostics(ingress, monkeypatch, caplog, rejection):
    module, app, config, payload = ingress
    if rejection == 'unknown-user':
        payload['model'] = 'unknown-' + MARKER
    else:
        config['allowSharedWorkflows'] = True

    def unexpected(*args, **kwargs):
        pytest.fail('Rejected requests must not execute workflows or serialize payload diagnostics')

    monkeypatch.setattr(module, '_sanitize_log_data', unexpected)
    monkeypatch.setattr(module, 'handle_user_prompt', unexpected)
    assert app.test_client().post('/review', json=payload).status_code == 400
    assert MARKER not in caplog.text
    assert not is_encryption_active()


@pytest.mark.parametrize('private', [True, False])
def test_stream_admission_uses_selected_privacy_and_preserves_lazy_logging(ingress, monkeypatch, caplog, private):
    module, app, config, payload = ingress
    config['redactLogOutput'] = private
    payload['stream'] = True
    seen, serialized = [], []

    def sanitize(value):
        serialized.append(value)
        assert not private, 'Private payload diagnostics must remain unevaluated'
        return value

    def streaming(*args, **kwargs):
        seen.append(is_encryption_active())

        def body():
            seen.append(is_encryption_active())
            yield b'response'

        return base_streaming._build_streaming_response(body(), 'text/plain')

    monkeypatch.setattr(module, '_sanitize_log_data', sanitize)
    monkeypatch.setattr(module, '_handle_streaming_request', streaming)
    response = app.test_client().post('/review', json=payload, buffered=True)
    try:
        assert response.status_code == 200 and response.data == b'response'
        assert seen == [private, private]
        assert bool(serialized) is (not private)
        assert (MARKER in caplog.text) is (not private)
        assert not is_encryption_active()
    finally:
        response.close()


@pytest.mark.parametrize('failure_policy', ['pending', 'private', 'ordinary'])
def test_ingress_flask_errors_retain_pending_or_selected_policy(ingress, monkeypatch, caplog, failure_policy):
    module, app, config, payload = ingress
    config['redactLogOutput'] = failure_policy != 'ordinary'
    app.config['PROPAGATE_EXCEPTIONS'] = False

    def fail(*args, **kwargs):
        raise ValueError(MARKER)

    if failure_policy == 'pending':
        monkeypatch.setattr(config_utils, 'get_user_config_for', fail)
    else:
        monkeypatch.setattr(module, 'handle_user_prompt', fail)
    response = app.test_client().post('/review', json=payload)
    assert response.status_code == 500
    assert MARKER not in response.get_data(as_text=True)
    assert (MARKER in caplog.text) is (failure_policy == 'ordinary')
    framework_errors = [record for record in caplog.records
                        if record.name == app.logger.name and record.levelno == logging.ERROR]
    assert len(framework_errors) == 1
    error = framework_errors[0]
    if failure_policy == 'ordinary':
        assert error.exc_info is not None and str(error.exc_info[1]) == MARKER
    else:
        assert error.getMessage() == '[Redacted]' and error.exc_info is None
    assert not is_encryption_active()
