"""Offline regressions for fetch ownership and shared workflow error boundaries."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from Middleware.services.web_page_fetch_service import WebPageFetchError
from Middleware.workflows.handlers.impl.web_fetch_handler import WebFetchHandler
from Tests.services.test_web_page_fetch_service import make_service, policy, page, response


@pytest.mark.parametrize('status', [403, 429, 503])
@pytest.mark.parametrize('for_robots', [True, False])
def test_received_cooldown_survives_rejected_headers(status, for_robots):
    service, factory, _ = make_service(
        response(status=status, headers={'Retry-After': '60', 'X-Explanation': 'ordinary header value'}), page())
    settings = policy(respect_robots=for_robots, fail_closed_on_robots_error=False, max_header_bytes=30)
    with pytest.raises(WebPageFetchError, match='cooling down' if for_robots else 'maxHeaderBytes'):
        service.fetch('https://example.com/page', settings)
    with pytest.raises(WebPageFetchError, match='cooling down'):
        service.fetch('https://example.com/page', settings)
    assert len(factory.calls) == 1


@pytest.mark.parametrize('failure', ['read', 'format', 'status', 'interruption'])
def test_webfetch_always_closes_final_response(monkeypatch, failure):
    result = requests.Response()
    result.status_code = 400 if failure == 'status' else 200
    result._content = b'ok'
    result._content_consumed = True
    result.close = Mock()
    variables = Mock()
    variables.apply_variables.side_effect = lambda value, context: value
    handler = WebFetchHandler(Mock(), variables)
    monkeypatch.setattr(handler, '_request_with_guard', Mock(return_value=result))
    expected = requests.HTTPError if failure == 'status' else RuntimeError
    if failure in ('read', 'interruption'):
        expected = GeneratorExit if failure == 'interruption' else requests.RequestException
        monkeypatch.setattr(result, 'iter_content', Mock(side_effect=expected('synthetic read failure')))
    elif failure == 'format':
        monkeypatch.setattr(handler, '_format_response', Mock(side_effect=RuntimeError('synthetic format failure')))
    with pytest.raises(expected):
        handler.handle(SimpleNamespace(config={'url': 'https://example.com'}, stream=False))
    result.close.assert_called_once()


@pytest.mark.parametrize('status,cap', [(200, 0), (400, 0), (200, 100)])
def test_webfetch_closes_owned_session(monkeypatch, status, cap):
    from Middleware.utilities import redirect_policy
    result = requests.Response()
    result.status_code = status
    result.url = 'https://example.com/api'
    result._content = b'ordinary response'
    result._content_consumed = True
    session = Mock()
    session.request.return_value = result
    monkeypatch.setattr(redirect_policy.requests.sessions, 'Session', lambda: session)
    variables = Mock()
    variables.apply_variables.side_effect = lambda value, context: value
    handler = WebFetchHandler(Mock(), variables)
    context = SimpleNamespace(config={'url': result.url, 'maxResponseBytes': cap, 'onError': 'return'}, stream=False)
    handler.handle(context)
    session.close.assert_called_once()


def test_curl_control_flow_interruption_kills_child(monkeypatch):
    from Middleware.workflows.handlers.impl import web_fetch_handler as module
    process = Mock()
    process.wait.side_effect = [GeneratorExit(), None]
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/synthetic/curl')
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(module.threading, 'Thread', Mock())
    handler = WebFetchHandler(Mock(), Mock())
    with pytest.raises(GeneratorExit):
        handler._request_with_curl(method='GET', url='https://example.com/', headers={}, data=None,
                                  timeout=30, proxies=None, verify=True, max_bytes=100)
    process.kill.assert_called_once()


def test_curlcommand_control_flow_interruption_kills_child(monkeypatch):
    from Middleware.workflows.handlers.impl import curl_command_handler as module
    process = Mock()
    process.wait.side_effect = [GeneratorExit(), None]
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(module.threading, 'Thread', Mock())
    handler = module.CurlCommandHandler(Mock(), Mock())
    with pytest.raises(GeneratorExit):
        handler._execute(['/synthetic/curl'], 30, 100, 'raise', 'stdout', SimpleNamespace(stream=False))
    process.kill.assert_called_once()


def test_webfetch_same_origin_redirect_keeps_response_cookie(monkeypatch):
    from email.message import Message
    from Tests.services.test_fetch_transport_boundaries import MemoryAdapter, session_factory

    class CookieAdapter(MemoryAdapter):
        def send(self, request, **kwargs):
            result = super().send(request, **kwargs)
            if result.status_code == 302:
                result.headers['Set-Cookie'] = 'flow=synthetic; Path=/; Secure'
                headers = Message()
                headers['Set-Cookie'] = result.headers['Set-Cookie']
                result.raw._original_response = SimpleNamespace(msg=headers)
            return result

    reference = CookieAdapter()
    with session_factory(reference)() as session:
        session.get('https://example.com/start').close()
    assert reference.calls[-1].headers.get('Cookie') == 'flow=synthetic'

    adapter = CookieAdapter()
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    handler = WebFetchHandler(Mock(), Mock())
    result = handler._request_with_guard(method='GET', url='https://example.com/start', headers={}, data=None,
        timeout=1, proxies=None, verify=True, allow_redirects=True, stream=True, block_private=False,
        allowed_hosts=frozenset(), transport='requests', max_bytes=100)
    result.close()
    assert adapter.calls[-1].headers.get('Cookie') == 'flow=synthetic'


def test_redacted_webfetch_error_stays_redacted_through_workflow(monkeypatch, tmp_path, caplog):
    import json
    import logging
    from Middleware.common import instance_global_variables as globals_
    from Middleware.utilities.sensitive_logging_utils import set_encryption_context, clear_encryption_context
    from Middleware.workflows.managers.workflow_manager import WorkflowManager

    for path in ['Middleware.workflows.managers.workflow_manager.LockingService',
                 'Middleware.workflows.handlers.impl.specialized_node_handler.LockingService',
                 'Middleware.workflows.processors.workflows_processor.LockingService']:
        monkeypatch.setattr(path, Mock())
    monkeypatch.setattr(globals_, 'USERS', ['chat-ui-cot-v2'])
    globals_.set_request_user('chat-ui-cot-v2')
    marker = 'synthetic-private-workflow-content'
    config = tmp_path / 'workflow.json'
    config.write_text(json.dumps([{'type': 'WebFetch', 'url': 'https://example.com/api'}]))
    monkeypatch.setattr(WebFetchHandler, '_request_with_guard', Mock(side_effect=requests.RequestException(marker)))
    caplog.set_level(logging.ERROR)
    set_encryption_context(True)
    try:
        manager = WorkflowManager('review', path_finder_func=lambda _: str(config))
        with pytest.raises(requests.RequestException):
            manager.run_workflow([], 'review-redaction', stream=False)
        assert marker not in caplog.text
    finally:
        clear_encryption_context()
        globals_.clear_request_user()


def test_webfetch_closes_real_adapter_pools_after_success(monkeypatch):
    from Tests.services.test_fetch_transport_boundaries import MemoryAdapter, session_factory
    adapter = MemoryAdapter()
    adapter.close = Mock()
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    variables = Mock()
    variables.apply_variables.side_effect = lambda value, context: value
    handler = WebFetchHandler(Mock(), variables)
    context = SimpleNamespace(config={'url': 'https://example.com/end'}, stream=False)
    assert handler.handle(context) == 'ok'
    adapter.close.assert_called_once()


@pytest.mark.parametrize('cookie,location,expected', [
    ('flow=synthetic; Path=/; Secure', '/end', 'flow=synthetic'),
    ('flow=synthetic; Path=/other; Secure', '/end', None),
    ('flow=synthetic; Path=/; Max-Age=0; Secure', '/end', None),
    ('flow=synthetic; Domain=example.com; Path=/; Secure', 'https://example.com:444/end', None),
    ('flow=synthetic; Domain=example.com; Path=/; Secure', 'https://other.example.com/end', None),
])
def test_redirect_cookie_rules_and_operation_isolation(monkeypatch, cookie, location, expected):
    from email.message import Message
    from Tests.services.test_fetch_transport_boundaries import MemoryAdapter, session_factory

    class CookieAdapter(MemoryAdapter):
        def send(self, request, **kwargs):
            result = super().send(request, **kwargs)
            if result.status_code == 302:
                result.headers['Location'] = location
                result.headers['Set-Cookie'] = cookie
                headers = Message()
                headers['Set-Cookie'] = cookie
                result.raw._original_response = SimpleNamespace(msg=headers)
            return result

    adapter = CookieAdapter()
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    variables = Mock()
    variables.apply_variables.side_effect = lambda value, context: value
    handler = WebFetchHandler(Mock(), variables)
    handler.handle(SimpleNamespace(config={'url': 'https://example.com/start'}, stream=False))
    assert adapter.calls[-1].headers.get('Cookie') == expected
    handler.handle(SimpleNamespace(config={'url': 'https://example.com/end'}, stream=False))
    assert adapter.calls[-1].headers.get('Cookie') is None
