"""Bounded transport checks with in-memory Requests adapters."""
import io
from unittest.mock import Mock

import pytest
import requests

from Middleware.services.web_page_fetch_service import WebPageFetchPolicy, WebPageFetchService
from Middleware.workflows.handlers.impl.web_fetch_handler import WebFetchHandler


class RecordingBody(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size=-1, **kwargs):
        result = super().read(size)
        self.bytes_read += len(result)
        return result

    def read1(self, size=-1, **kwargs):
        return self.read(size, **kwargs)


class MemoryAdapter(requests.adapters.BaseAdapter):
    def __init__(self):
        self.redirect_body = RecordingBody(b'r' * 32)
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = 302 if request.url.endswith('/start') else 200
        response.headers['Content-Type'] = 'text/plain'
        if response.status_code == 302:
            response.headers['Location'] = '/end'
            response.raw = self.redirect_body
        else:
            response.raw = RecordingBody(b'ok')
        return response

    def close(self):
        pass


def session_factory(adapter):
    original = requests.Session

    def factory():
        session = original()
        session.trust_env = False
        session.mount('https://', adapter)
        return session
    return factory


def test_page_redirect_body_is_not_read_before_policy_checks():
    adapter = MemoryAdapter()
    service = WebPageFetchService(session_factory=session_factory(adapter), url_checker=lambda *a: None)
    policy = WebPageFetchPolicy(respect_robots=False, enable_domain_pacing=False, max_transfer_bytes=8)
    result = service.fetch('https://example.com/start', policy)
    assert result.body == b'ok'
    assert adapter.redirect_body.bytes_read == 0


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer synthetic-review'}])
def test_webfetch_redirect_body_respects_cap(monkeypatch, headers):
    adapter = MemoryAdapter()
    monkeypatch.setattr(requests.sessions, 'Session', session_factory(adapter))
    handler = WebFetchHandler(Mock(), Mock())
    response = handler._request_with_guard(method='GET', url='https://example.com/start', headers=headers,
        data=None, timeout=1, proxies=None, verify=True, allow_redirects=True, stream=True,
        block_private=False, allowed_hosts=frozenset(), transport='requests', max_bytes=8)
    try:
        assert response.status_code == 200
        assert adapter.redirect_body.bytes_read <= 8
    finally:
        response.close()


def test_cooldown_can_be_recorded_while_another_request_is_pacing():
    service = WebPageFetchService(url_checker=lambda *a: None)
    lane = service._domain_lane('example.com')
    lane.lock.acquire()
    try:
        service._set_cooldown('example.com', 60, 'HTTP 429', wait_timeout=0)
    finally:
        lane.lock.release()
    assert lane.cooldown_until > service._monotonic()
