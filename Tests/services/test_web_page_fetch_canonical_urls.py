"""Robots authorization must cover the URL actually prepared by Requests."""
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests

from Middleware.services.web_page_fetch_service import (
    WebPageFetchError, WebPageFetchPolicy, WebPageFetchService,
)


class Body(io.BytesIO):
    def read(self, size=-1, **kwargs):
        return super().read(size)

    def read1(self, size=-1, **kwargs):
        return self.read(size, **kwargs)


class Adapter(requests.adapters.BaseAdapter):
    def __init__(self, redirect):
        self.calls = []
        self.bodies = []
        self.redirect = redirect

    def send(self, request, **kwargs):
        self.calls.append(request.url)
        response = requests.Response()
        response.url, response.request = request.url, request
        response.status_code = 200
        response.headers['Content-Type'] = 'text/plain'
        path = urlsplit(request.url).path
        if path == '/robots.txt':
            data = b'User-agent: *\nDisallow: /private\n'
        elif path == '/start':
            response.status_code = 302
            response.headers['Location'] = self.redirect
            data = b''
        else:
            data = b'ordinary page'
        response.raw = Body(data)
        self.bodies.append(response.raw)
        return response

    def close(self):
        pass


@pytest.mark.parametrize('via_redirect', [False, True])
@pytest.mark.parametrize('target,permitted', [
    ('/public/../private', False),
    ('/public/%2e%2e/private', False),
    ('/private', False),
    ('/public/page', True),
])
def test_robots_checks_prepared_target(via_redirect, target, permitted):
    adapter = Adapter('https://example.com' + target)
    sessions = []

    def factory():
        session = requests.Session()
        session.mount('https://', adapter)
        sessions.append(session)
        return session

    service = WebPageFetchService(session_factory=factory, url_checker=lambda *args: None)
    policy = WebPageFetchPolicy(enable_domain_pacing=False)
    url = 'https://example.com' + ('/start' if via_redirect else target)
    result, error = None, None
    try:
        result = service.fetch(url, policy)
    except WebPageFetchError as exc:
        error = exc
    assert all(body.closed for body in adapter.bodies)
    if permitted:
        assert error is None
        assert result.body == b'ordinary page'
    else:
        assert 'https://example.com/private' not in adapter.calls, adapter.calls
        assert isinstance(error, WebPageFetchError)
        assert 'disallowed' in str(error)


@pytest.mark.parametrize('target,canonical', [
    ('https://EXAMPLE.com/public/../allowed#section', 'https://example.com/allowed'),
    ('https://example.com/public/%2e%2e/allowed%7e?q=%7e', 'https://example.com/allowed~?q=~'),
])
def test_authorized_url_sent_url_and_result_metadata_agree(target, canonical):
    adapter = Adapter(None)
    checked = []

    def factory():
        session = requests.Session()
        session.mount('https://', adapter)
        return session

    def checker(url, *args):
        checked.append(url)

    service = WebPageFetchService(session_factory=factory, url_checker=checker)
    result = service.fetch(target, WebPageFetchPolicy(enable_domain_pacing=False))
    assert checked == [canonical, 'https://example.com/robots.txt']
    assert adapter.calls == ['https://example.com/robots.txt', canonical]
    assert result.url == canonical
    assert result.body == b'ordinary page'
    assert all(body.closed for body in adapter.bodies)


def test_robots_redirect_is_canonical_before_address_check_and_transport():
    class RobotsRedirectAdapter(Adapter):
        def send(self, request, **kwargs):
            response = super().send(request, **kwargs)
            if urlsplit(request.url).path == '/robots.txt':
                response.status_code = 302
                response.headers['Location'] = '/policy/../rules'
            elif urlsplit(request.url).path == '/rules':
                response.raw.close()
                response.raw = Body(b'User-agent: *\nDisallow: /private\n')
                self.bodies.append(response.raw)
            return response

    adapter = RobotsRedirectAdapter(None)
    checked = []

    def factory():
        session = requests.Session()
        session.mount('https://', adapter)
        return session

    service = WebPageFetchService(session_factory=factory,
        url_checker=lambda url, *args: checked.append(url))
    with pytest.raises(WebPageFetchError, match='disallowed'):
        service.fetch('https://example.com/private', WebPageFetchPolicy(enable_domain_pacing=False))
    assert adapter.calls == ['https://example.com/robots.txt', 'https://example.com/rules']
    assert checked == ['https://example.com/private', *adapter.calls]
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('failure', ['error', 'unstable'])
def test_preparation_failure_is_bounded_and_prevents_io(monkeypatch, failure):
    calls = []

    def prepare(request, url, params):
        calls.append(url)
        if failure == 'error':
            raise requests.exceptions.InvalidURL('synthetic preparation failure')
        request.url = url + '/next'

    monkeypatch.setattr(requests.PreparedRequest, 'prepare_url', prepare)
    service = WebPageFetchService(session_factory=lambda: pytest.fail('Unexpected transport'),
        url_checker=lambda *args: pytest.fail('Policy ran on unprepared URL'))
    with pytest.raises(WebPageFetchError, match='prepared|stabilize'):
        service.fetch('https://example.com/page', WebPageFetchPolicy())
    assert len(calls) == (1 if failure == 'error' else 3)


@pytest.mark.parametrize('on_error', ['raise', 'return'])
def test_page_preparation_failure_honors_handler_error_policy(monkeypatch, on_error):
    from Middleware.workflows.handlers.impl.web_page_fetch_handler import WebPageFetchHandler

    def fail(*args):
        raise requests.exceptions.InvalidURL('synthetic preparation failure')

    monkeypatch.setattr(requests.PreparedRequest, 'prepare_url', fail)
    service = WebPageFetchService(session_factory=lambda: pytest.fail('Unexpected transport'),
        url_checker=lambda *args: pytest.fail('Unexpected address check'))
    variables = Mock()
    variables.apply_variables.side_effect = lambda value, context: value
    handler = WebPageFetchHandler(Mock(), variables, web_page_fetch_service=service)
    context = SimpleNamespace(config={'url': 'https://example.com/page',
        'onError': on_error, 'outputFormat': 'full'}, request_id=None, stream=False)
    if on_error == 'raise':
        with pytest.raises(WebPageFetchError, match='prepared'):
            handler.handle(context)
    else:
        payload = json.loads(handler.handle(context))
        assert 'prepared' in payload['error'] and payload['body'] is None


@pytest.mark.parametrize('fail_closed', [True, False])
def test_robots_preparation_failure_honors_permission_policy(monkeypatch, fail_closed):
    prepare = requests.PreparedRequest.prepare_url

    def fail_robots(request, url, params):
        if url.endswith('/robots.txt'):
            raise requests.exceptions.InvalidURL('synthetic robots preparation failure')
        return prepare(request, url, params)

    monkeypatch.setattr(requests.PreparedRequest, 'prepare_url', fail_robots)
    adapter = Adapter(None)

    def factory():
        session = requests.Session()
        session.mount('https://', adapter)
        return session

    service = WebPageFetchService(session_factory=factory, url_checker=lambda *args: None)
    policy = WebPageFetchPolicy(enable_domain_pacing=False, fail_closed_on_robots_error=fail_closed)
    if fail_closed:
        with pytest.raises(WebPageFetchError, match='robots permission'):
            service.fetch('https://example.com/page', policy)
        assert adapter.calls == []
    else:
        assert service.fetch('https://example.com/page', policy).body == b'ordinary page'
        assert adapter.calls == ['https://example.com/page']
    assert all(body.closed for body in adapter.bodies)
