"""Publisher rule specificity through real Requests preparation without network I/O."""
import io
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
    def __init__(self, rules, redirect=None):
        self.rules = rules.encode()
        self.redirect = redirect
        self.calls = []
        self.requests = []
        self.bodies = []
        self.closes = 0

    def send(self, request, **kwargs):
        self.calls.append(request.url)
        self.requests.append(request)
        response = requests.Response()
        response.status_code = 200
        response.request, response.url = request, request.url
        response.headers['Content-Type'] = 'text/plain'
        path = urlsplit(request.url).path
        body = self.rules if path == '/robots.txt' else b'ordinary page'
        if path == '/start' and self.redirect:
            response.status_code = 302
            response.headers['Location'] = self.redirect
            body = b''
        response.raw = Body(body)
        self.bodies.append(response.raw)
        return response

    def close(self):
        self.closes += 1


def make_service(adapter):
    def factory():
        session = requests.Session()
        session.mount('https://', adapter)
        return session

    return WebPageFetchService(session_factory=factory, url_checker=lambda *args: None)


def test_library_user_agent_and_matching_robots_rules_across_redirects():
    token = requests.utils.default_user_agent().split('/', 1)[0]
    rules = f'User-agent: *\nDisallow: /\n\nUser-agent: {token}\nAllow: /\n'
    adapter = Adapter(rules, redirect='https://other.example.com/final')
    service = make_service(adapter)

    result = service.fetch('https://example.com/start',
                           WebPageFetchPolicy(enable_domain_pacing=False))

    assert result.body == b'ordinary page'
    assert adapter.calls == [
        'https://example.com/robots.txt', 'https://example.com/start',
        'https://other.example.com/robots.txt', 'https://other.example.com/final',
    ]
    for request in adapter.requests:
        assert request.headers == {
            'User-Agent': requests.utils.default_user_agent(),
            'Accept': ('text/plain' if request.url.endswith('/robots.txt') else
                       'text/html, application/xhtml+xml, text/plain;q=0.9'),
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'close',
        }
    assert adapter.closes == len(adapter.calls)
    assert all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('rules,path,permitted', [
    pytest.param('Allow: /\nDisallow: /private', '/private', False,
                 id='specific-denial-after-broad-allow'),
    pytest.param('Disallow: /private\nAllow: /', '/private', False,
                 id='specific-denial-first-control'),
    pytest.param('Disallow: /\nAllow: /public', '/public', True,
                 id='specific-allow-after-broad-denial'),
    pytest.param('Disallow: /private', '/public', True, id='ordinary-allowed-control'),
    pytest.param('Disallow: /private/*', '/private/page', False, id='wildcard-denial'),
    pytest.param('Disallow: /private$', '/private', False, id='end-anchor-denial'),
    pytest.param('Disallow: /private$', '/private-extra', True,
                 id='end-anchor-allowed-control'),
    pytest.param('Allow: /*\nDisallow: /private', '/private/page', False,
                 id='wildcard-allow-specific-denial'),
    pytest.param('Disallow: /private\nAllow: /*', '/private/page', False,
                 id='wildcard-allow-specific-denial-reordered'),
    pytest.param('Allow: /*/file\nDisallow: /private/reports', '/private/reports/file', False,
                 id='internal-wildcard-allow'),
    pytest.param('Disallow: /*/file\nAllow: /public/reports', '/public/reports/file', True,
                 id='internal-wildcard-denial'),
    pytest.param('Allow: /*/page\nDisallow: /private/*', '/private/reports/page', False,
                 id='competing-wildcards'),
    pytest.param('Disallow: /\nAllow: /$', '/', True, id='anchor-specificity'),
    pytest.param('Allow: /private\nDisallow: /private$', '/private', False,
                 id='anchor-specific-denial'),
    pytest.param('Allow: /*$\nDisallow: /private', '/private/page', False,
                 id='anchored-wildcard-allow'),
    pytest.param('Disallow: /private/*\nAllow: /private/*', '/private/page', True,
                 id='equal-rules-allow-wins'),
    pytest.param('Allow: /private/*\nDisallow: /private/*', '/private/page', True,
                 id='equal-rules-allow-wins-reordered'),
    pytest.param('Allow: /private\nDisallow: /private*', '/private/page', True,
                 id='trailing-star-equivalence-tie'),
    pytest.param('Allow: /*\nDisallow: /caf%C3%A9/', '/caf%C3%A9/page', False,
                 id='encoded-rule-specificity'),
    pytest.param('Allow: /*\nDisallow: /caf\u00e9/', '/caf%C3%A9/page', False,
                 id='unicode-rule-specificity'),
    pytest.param('Allow: /*\nDisallow: /safe/%7E', '/safe/~page', False,
                 id='unreserved-escape-specificity'),
    pytest.param('Disallow: /literal/%2A', '/literal/word', True,
                 id='encoded-star-is-literal-control'),
    pytest.param('Disallow: /literal/%2A', '/literal/%2A', False,
                 id='encoded-star-matches-literal'),
])
def test_publisher_rules_at_transport_boundary(rules, path, permitted):
    adapter = Adapter('User-agent: *\n' + rules + '\n')
    service = make_service(adapter)
    result, error = None, None
    try:
        result = service.fetch('https://example.com' + path,
                               WebPageFetchPolicy(enable_domain_pacing=False))
    except WebPageFetchError as exc:
        error = exc
    assert all(body.closed for body in adapter.bodies)
    assert adapter.closes == len(adapter.calls)
    if permitted:
        assert error is None, str(error)
        assert result.body == b'ordinary page'
        assert adapter.calls == ['https://example.com/robots.txt', 'https://example.com' + path]
    else:
        assert adapter.calls == ['https://example.com/robots.txt'], adapter.calls
        assert isinstance(error, WebPageFetchError)
        assert 'disallowed' in str(error)


def test_merged_groups_keep_specificity_and_pacing_directives():
    rules = ('User-agent: Python-Requests\nAllow: /*\nCrawl-delay: 7\n\n'
             'User-agent: python-requests\nDisallow: /private\nRequest-rate: 2/20\n')
    adapter = Adapter(rules)
    service = make_service(adapter)
    policy = WebPageFetchPolicy(enable_domain_pacing=False)
    with pytest.raises(WebPageFetchError, match='disallowed'):
        service.fetch('https://example.com/private/page', policy)
    record = service._cached_robots('https://example.com', policy)
    assert record.parser.crawl_delay('Python-Requests') == 7
    assert record.parser.request_rate('Python-Requests') == (2, 20)
    assert 'Disallow: /private' in str(record.parser)
    assert adapter.calls == ['https://example.com/robots.txt']
    assert adapter.closes == 1 and all(body.closed for body in adapter.bodies)


@pytest.mark.parametrize('cross_origin', [False, True])
def test_redirect_destination_uses_specific_rule_before_page_request(cross_origin):
    target = 'https://' + ('other.example.com' if cross_origin else 'example.com')
    rules = 'User-agent: *\nAllow: /*\nDisallow: /private\n'
    adapter = Adapter(rules, redirect=target + '/section/../private/page')
    service = make_service(adapter)
    with pytest.raises(WebPageFetchError, match='disallowed'):
        service.fetch('https://example.com/start', WebPageFetchPolicy(enable_domain_pacing=False))
    expected = ['https://example.com/robots.txt', 'https://example.com/start']
    if cross_origin:
        expected.append(target + '/robots.txt')
    assert adapter.calls == expected
    assert adapter.closes == len(expected) and all(body.closed for body in adapter.bodies)


def test_specificity_adapter_does_not_change_global_parser():
    from urllib import robotparser

    original = robotparser.RuleLine.applies_to
    service = WebPageFetchService()
    first = service._parse_robots(b'User-agent: *\nAllow: /*\nDisallow: /private\n')
    second = service._parse_robots(b'User-agent: *\nAllow: /private\n')
    assert robotparser.RuleLine.applies_to is original
    assert not first.can_fetch('Python-Requests', 'https://example.com/private/page')
    assert second.can_fetch('Python-Requests', 'https://example.com/private/page')
