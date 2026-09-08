"""Offline redirect compatibility checks at the Requests preparation boundary."""

import io
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from Middleware.services.web_page_fetch_service import WebPageFetchPolicy, WebPageFetchService
from Middleware.workflows.handlers.impl.web_fetch_handler import WebFetchHandler


class Body(io.BytesIO):
    def read(self, size=-1, **kwargs):
        return super().read(size)

    def read1(self, size=-1, **kwargs):
        return self.read(size)


class RedirectAdapter(requests.adapters.BaseAdapter):
    def __init__(self, location, cookie=None, redirect_path='/start'):
        self.location = location
        self.cookie = cookie
        self.redirect_path = redirect_path
        self.calls = []
        self.bodies = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = 302 if request.url.endswith(self.redirect_path) else 200
        response.headers['Content-Type'] = 'text/plain'
        response.raw = Body(b'')
        self.bodies.append(response.raw)
        if response.status_code == 302:
            response.headers['Location'] = self.location
            if self.cookie:
                response.headers['Set-Cookie'] = self.cookie
                headers = Message()
                headers['Set-Cookie'] = self.cookie
                response.raw._original_response = SimpleNamespace(msg=headers)
        return response

    def close(self):
        pass


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr('socket.socket.connect', Mock(side_effect=AssertionError('Network forbidden')))
    monkeypatch.setattr('socket.getaddrinfo', Mock(side_effect=AssertionError('DNS forbidden')))


def session_factory(adapter):
    session_class = requests.Session

    def factory():
        session = session_class()
        session.trust_env = False
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    return factory


def fetch(handler, headers=None, transport='requests', url='https://example.test/start'):
    return handler._request_with_guard(
        method='GET', url=url, headers=headers or {}, data=None,
        timeout=1, proxies=None, verify=True, allow_redirects=True, stream=True,
        block_private=False, allowed_hosts=frozenset(), transport=transport, max_bytes=64)


def test_requests_redirect_decodes_utf8_location(monkeypatch):
    adapter = RedirectAdapter('/café'.encode('utf-8').decode('latin-1'))
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    response = fetch(WebFetchHandler(Mock(), Mock()))
    response.close()
    assert [request.url for request in adapter.calls] == [
        'https://example.test/start', 'https://example.test/caf%C3%A9']
    assert all(body.closed for body in adapter.bodies)


def test_page_redirect_decodes_utf8_before_destination_checks():
    adapter = RedirectAdapter('/café'.encode('utf-8').decode('latin-1'))
    checked = []
    service = WebPageFetchService(
        session_factory=session_factory(adapter), url_checker=lambda url, *args: checked.append(url))
    result = service.fetch('https://example.test/start', WebPageFetchPolicy(
        respect_robots=False, enable_domain_pacing=False))
    assert result.url == 'https://example.test/caf%C3%A9'
    assert checked == [request.url for request in adapter.calls]
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('path,encoded_path', [
    ('/café', '/caf%C3%A9'),
    ('/Åland', '/%C3%85land'),
    ('/voilà', '/voil%C3%A0'),
])
def test_curl_header_adapter_decodes_utf8_redirect(monkeypatch, tmp_path, path, encoded_path):
    handler = WebFetchHandler(Mock(), Mock())
    headers_path = tmp_path / 'response-headers'
    calls = []

    def curl(**kwargs):
        calls.append(kwargs['url'])
        headers_path.write_bytes(
            b'HTTP/1.1 302 Found\r\nLocation: ' + path.encode('utf-8') + b'\r\n\r\n'
            if len(calls) == 1 else b'HTTP/1.1 200 OK\r\n\r\n')
        return handler._build_curl_response(
            url=kwargs['url'], method=kwargs['method'],
            response_headers_path=str(headers_path), body=b'')

    monkeypatch.setattr(handler, '_request_with_curl', curl)
    response = fetch(handler, transport='curl')
    response.close()
    assert calls == ['https://example.test/start', 'https://example.test' + path]
    assert response.request.url == 'https://example.test' + encoded_path


@pytest.mark.parametrize('newline', ['\r\n', '\n'])
def test_curl_headers_preserve_utf8_when_unfolding(newline):
    raw = newline.join([
        'HTTP/1.1 100 Continue', '',
        'HTTP/2 200 OK',
        'X-Title: \tÅland \t',
        ' \tvoilà \t', '', '',
    ]).encode('utf-8')
    status, reason, headers = WebFetchHandler._parse_curl_headers(raw)
    assert status == 200
    assert reason == 'OK'
    assert headers['X-Title'].encode('latin-1').decode('utf-8') == 'Åland voilà'


def test_robots_redirect_decodes_utf8_before_fetching_policy():
    adapter = RedirectAdapter('/café'.encode('utf-8').decode('latin-1'), redirect_path='/robots.txt')
    service = WebPageFetchService(session_factory=session_factory(adapter), url_checker=lambda *args: None)
    service.fetch('https://example.test/page', WebPageFetchPolicy(enable_domain_pacing=False))
    assert [request.url for request in adapter.calls] == [
        'https://example.test/robots.txt', 'https://example.test/caf%C3%A9', 'https://example.test/page']
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('location,cookie,expected', [
    ('/end', 'session=renewed; Path=/; Secure', 'session=renewed'),
    ('/end', 'session=; Max-Age=0; Path=/', None),
    ('/end', 'session=renewed; Path=/private; Secure', None),
    ('https://other.test/end', 'session=renewed; Path=/; Secure', None),
])
def test_redirect_rebuilds_explicit_cookie_from_response(monkeypatch, location, cookie, expected):
    adapter = RedirectAdapter(location, cookie)
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    headers = {'cOoKiE': 'session=original'}
    response = fetch(WebFetchHandler(Mock(), Mock()), headers)
    response.close()
    assert adapter.calls[0].headers['Cookie'] == 'session=original'
    assert adapter.calls[-1].headers.get('Cookie') == expected
    assert headers == {'cOoKiE': 'session=original'}
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('scheme,location,retain_auth', [
    ('https', '/end', True),
    ('https', 'https://example.test/end', True),
    ('https', 'https://example.test:443/end', True),
    ('http', 'https://example.test/end', True),
    ('https', 'https://other.test/end', False),
    ('https', 'http://example.test/end', False),
    ('https', 'https://example.test:8443/end', False),
])
def test_url_basic_auth_respects_redirect_boundary(monkeypatch, scheme, location, retain_auth):
    adapter = RedirectAdapter(location)
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    headers = {'X-Trace': 'fixture'}
    response = fetch(WebFetchHandler(Mock(), Mock()), headers,
                     url=f'{scheme}://fixture-user:fixture-password@example.test/start')
    response.close()
    authorization = requests.auth._basic_auth_str('fixture-user', 'fixture-password')
    assert adapter.calls[0].headers['Authorization'] == authorization
    assert adapter.calls[-1].headers.get('Authorization') == (authorization if retain_auth else None)
    assert adapter.calls[-1].headers['X-Trace'] == 'fixture'
    assert headers == {'X-Trace': 'fixture'}
    assert all(body.closed for body in adapter.bodies)


def test_redirect_retains_effective_auth_when_url_overrides_authored_header(monkeypatch):
    adapter = RedirectAdapter('https://example.test/end')
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    headers = {'aUtHoRiZaTiOn': 'Bearer fixture-header'}
    response = fetch(WebFetchHandler(Mock(), Mock()), headers,
                     url='https://fixture-user:fixture-password@example.test/start')
    response.close()
    authorization = requests.auth._basic_auth_str('fixture-user', 'fixture-password')
    assert [request.headers['Authorization'] for request in adapter.calls] == [authorization, authorization]
    assert headers == {'aUtHoRiZaTiOn': 'Bearer fixture-header'}
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('destination,retain_auth', [('example.test', True), ('other.test', False)])
def test_url_auth_across_multiple_redirects(monkeypatch, destination, retain_auth):
    class ChainAdapter(RedirectAdapter):
        def send(self, request, **kwargs):
            response = super().send(request, **kwargs)
            if len(self.calls) == 2:
                response.status_code = 302
                response.headers['Location'] = 'https://example.test/done'
            return response

    adapter = ChainAdapter(f'https://{destination}/end')
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    response = fetch(WebFetchHandler(Mock(), Mock()),
                     url='https://fixture-user:fixture-password@example.test/start')
    response.close()
    authorization = requests.auth._basic_auth_str('fixture-user', 'fixture-password')
    assert len(adapter.calls) == 3
    assert [request.headers.get('Authorization') for request in adapter.calls] == [
        authorization, authorization if retain_auth else None, authorization if retain_auth else None]
    assert all(body.closed for body in adapter.bodies)


def test_redirect_auth_allows_destination_netrc_precedence(monkeypatch):
    adapter = RedirectAdapter('https://example.test/end')
    private_factory = session_factory(adapter)

    def factory():
        session = private_factory()
        session.trust_env = True
        return session

    monkeypatch.setattr(requests.sessions, 'Session', factory)
    monkeypatch.setattr(requests.sessions, 'get_netrc_auth',
                        lambda url: ('destination-user', 'fixture-password') if url.endswith('/end') else None)
    monkeypatch.setattr(requests.sessions, 'get_environ_proxies', lambda *args, **kwargs: {})
    response = fetch(WebFetchHandler(Mock(), Mock()),
                     url='https://fixture-user:fixture-password@example.test/start')
    response.close()
    assert adapter.calls[0].headers['Authorization'] == requests.auth._basic_auth_str(
        'fixture-user', 'fixture-password')
    assert adapter.calls[-1].headers['Authorization'] == requests.auth._basic_auth_str(
        'destination-user', 'fixture-password')
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('initial_url,location,expected_url,retain_auth', [
    ('https://bücher.test/start', 'https://xn--bcher-kva.test/end',
     'https://xn--bcher-kva.test/end', True),
    ('https://xn--bcher-kva.test/start', 'https://bücher.test/end',
     'https://xn--bcher-kva.test/end', True),
    ('https://bücher.test/start', '/end', 'https://xn--bcher-kva.test/end', True),
    ('https://bücher.test/start', 'https://xn--bcher-kva.test:443/end',
     'https://xn--bcher-kva.test:443/end', True),
    ('http://bücher.test/start', 'https://xn--bcher-kva.test/end',
     'https://xn--bcher-kva.test/end', True),
    ('https://bücher.test/start', 'https://other.test/end', 'https://other.test/end', False),
    ('https://bücher.test/start', 'http://xn--bcher-kva.test/end',
     'http://xn--bcher-kva.test/end', False),
    ('https://bücher.test/start', 'https://xn--bcher-kva.test:8443/end',
     'https://xn--bcher-kva.test:8443/end', False),
])
def test_idna_redirect_uses_transport_credential_boundary(
        monkeypatch, initial_url, location, expected_url, retain_auth):
    adapter = RedirectAdapter(location.encode('utf-8').decode('latin-1'),
                              cookie='session=fixture; Path=/')
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    headers = {'Authorization': 'Bearer fixture-token', 'X-Api-Key': 'fixture-key',
               'X-Trace': 'fixture'}
    response = fetch(WebFetchHandler(Mock(), Mock()), headers, url=initial_url)
    response.close()
    assert len(adapter.calls) == 2
    redirected = adapter.calls[-1]
    assert redirected.url == expected_url
    assert redirected.headers.get('Authorization') == ('Bearer fixture-token' if retain_auth else None)
    assert redirected.headers.get('X-Api-Key') == ('fixture-key' if retain_auth else None)
    assert redirected.headers.get('Cookie') == ('session=fixture' if retain_auth else None)
    assert redirected.headers['X-Trace'] == 'fixture'
    assert headers['Authorization'] == 'Bearer fixture-token'
    assert headers['X-Api-Key'] == 'fixture-key'
    assert all(body.closed for body in adapter.bodies)


def test_relative_redirect_uses_prepared_source_path(monkeypatch):
    adapter = RedirectAdapter('end')
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    response = fetch(WebFetchHandler(Mock(), Mock()),
                     url='https://bücher.test/base/%2e%2e/start')
    response.close()
    assert [request.url for request in adapter.calls] == [
        'https://xn--bcher-kva.test/base/../start', 'https://xn--bcher-kva.test/end']
    assert all(body.closed for body in adapter.bodies)
