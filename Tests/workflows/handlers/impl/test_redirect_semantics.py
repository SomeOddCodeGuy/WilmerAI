"""Compare the two WebFetch branches using memory-only real Requests sessions."""
import io
from unittest.mock import Mock

import pytest
import requests

from Middleware.workflows.handlers.impl.web_fetch_handler import WebFetchHandler


class RedirectAdapter(requests.adapters.BaseAdapter):
    def __init__(self, status):
        self.status = status
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = self.status if request.url.endswith('/start') else 200
        response.raw = io.BytesIO(b'')
        if request.url.endswith('/start'):
            response.headers['Location'] = '/end'
        return response

    def close(self):
        pass


@pytest.mark.parametrize('method,status,expected', [
    ('PUT', 301, ('PUT', None)), ('GET', 302, ('GET', None)),
    ('POST', 303, ('GET', None)), ('POST', 307, ('POST', 'synthetic-body')),
    ('PUT', 308, ('PUT', 'synthetic-body')),
])
def test_credentials_do_not_change_redirect_method_or_body(monkeypatch, method, status, expected):
    original_session = requests.Session
    observed = []
    for authenticated in (False, True):
        adapter = RedirectAdapter(status)

        def factory():
            session = original_session()
            session.trust_env = False
            session.mount('https://', adapter)
            return session

        monkeypatch.setattr(requests.sessions, 'Session', factory)
        handler = WebFetchHandler(Mock(), Mock())
        response = handler._request_with_guard(
            method=method, url='https://example.com/start',
            headers={'Authorization': 'Bearer synthetic-review'} if authenticated else {},
            data='synthetic-body', timeout=1, proxies=None, verify=True,
            allow_redirects=True, stream=True, block_private=False,
            allowed_hosts=frozenset(), transport='requests', max_bytes=64)
        response.close()
        assert len(adapter.calls) == 2
        observed.append((adapter.calls[1].method, adapter.calls[1].body))
    assert observed[0] == observed[1]
    assert observed[0] == expected
