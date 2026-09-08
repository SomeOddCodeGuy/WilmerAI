"""Small offline checks of literal and percent-encoded path separators."""
import pytest

from Tests.services.test_web_page_fetch_robots_rules import Adapter, make_service
from Middleware.services.web_page_fetch_service import WebPageFetchError, WebPageFetchPolicy, WebPageFetchService


@pytest.mark.parametrize('rules,path,permitted', [
    pytest.param('Disallow: /private\nAllow: /private/public',
                 '/private%2Fpublic', False, id='encoded-separator-does-not-match-literal-allow'),
    pytest.param('Disallow: /private\nAllow: /private%2Fpublic',
                 '/private/public', False, id='literal-separator-does-not-match-encoded-allow'),
    pytest.param('Disallow: /private\nAllow: /private/public',
                 '/private/public', True, id='literal-allow-control'),
    pytest.param('Disallow: /private\nAllow: /private%2Fpublic',
                 '/private%2Fpublic', True, id='encoded-allow-control'),
    pytest.param('Disallow: /private\nAllow: /private/~public',
                 '/private/%7Epublic', True, id='unreserved-escape-control'),
    pytest.param('Disallow: /private', '/private%2Fpublic', False,
                 id='ordinary-prefix-denial-control'),
    pytest.param('Disallow: /private\nAllow: /private/public',
                 '/private%2fpublic', False, id='lowercase-reserved-escape'),
    pytest.param('Disallow: /private\nAllow: /private%252Fpublic',
                 '/private%2Fpublic', False, id='encoded-percent-is-not-double-decoded'),
    pytest.param('Disallow: /private\nAllow: /private%2Fpublic',
                 '/private%252Fpublic', False, id='encoded-percent-does-not-collide'),
    pytest.param('Disallow: /private\nAllow: /private?item=public',
                 '/private%3Fitem=public', False, id='encoded-query-separator'),
    pytest.param('Disallow: /private\nAllow: /private?item=public&mode=read',
                 '/private?item=public%26mode=read', False, id='encoded-query-ampersand'),
    pytest.param('Disallow: /private\nAllow: /private?item=public',
                 '/private?item%3Dpublic', False, id='encoded-query-equals'),
    pytest.param('Disallow: /private\nAllow: /private?item=public',
                 '/private?item=public', True, id='literal-query-control'),
    pytest.param('Disallow: /private\nAllow: /private%2fpublic$',
                 '/private%2Fpublic', True, id='encoded-anchor-control'),
    pytest.param('Disallow: /private\nAllow: /private%2Fpublic*',
                 '/private/public-extra', False, id='wildcard-preserves-encoded-separator'),
    pytest.param('Disallow: /private\nAllow: /private/*',
                 '/private%2Fpublic', False, id='wildcard-does-not-invent-separator'),
    pytest.param('Disallow: /private\nAllow: /private:public',
                 '/private%3Apublic', True, id='ordinary-encoded-path-data-control'),
    pytest.param('Disallow:', '/public', True, id='empty-denial-allows-control'),
    pytest.param('Disallow: /\nAllow:', '/public', False, id='empty-allow-keeps-specific-denial'),
])
def test_reserved_separator_permission(rules, path, permitted):
    adapter = Adapter('User-agent: *\n' + rules + '\n')
    service = make_service(adapter)
    result, error = None, None
    try:
        result = service.fetch('https://example.com' + path,
                               WebPageFetchPolicy(enable_domain_pacing=False))
    except WebPageFetchError as exc:
        error = exc
    assert adapter.closes == len(adapter.calls)
    assert all(body.closed for body in adapter.bodies)
    if permitted:
        assert error is None
        assert result.body == b'ordinary page'
        assert len(adapter.calls) == 2
        assert adapter.calls[-1] == result.url
    else:
        assert adapter.calls == ['https://example.com/robots.txt'], adapter.calls
        assert isinstance(error, WebPageFetchError)
        assert 'disallowed' in str(error)


@pytest.mark.parametrize('cross_origin', [False, True])
def test_redirect_and_cached_policy_keep_encoded_separator(cross_origin):
    origin = 'https://other.example.com' if cross_origin else 'https://example.com'
    adapter = Adapter('User-agent: *\nDisallow: /private\nAllow: /private/public\n',
                      redirect=origin + '/private%2Fpublic')
    service = make_service(adapter)
    policy = WebPageFetchPolicy(enable_domain_pacing=False)
    with pytest.raises(WebPageFetchError, match='disallowed'):
        service.fetch('https://example.com/start', policy)
    expected = ['https://example.com/robots.txt', 'https://example.com/start']
    if cross_origin:
        expected.append(origin + '/robots.txt')
    assert adapter.calls == expected
    with pytest.raises(WebPageFetchError, match='disallowed'):
        service.fetch(origin + '/private%2Fpublic', policy)
    assert adapter.calls == expected
    assert adapter.closes == len(expected) and all(body.closed for body in adapter.bodies)


def test_group_mapping_preserves_raw_paths_and_pacing_without_global_mutation():
    from urllib import robotparser

    original = robotparser.normalize
    parser = WebPageFetchService._parse_robots(
        b'User-agent: OtherBot\nAllow: /\n'
        b'User-agent: Python-Requests\nDisallow: /private\nCrawl-delay: 7\n'
        b'User-agent: python-requests\nAllow: /private%2Fpublic\nRequest-rate: 2/20\n')
    assert parser.can_fetch('OtherBot', 'https://example.com/private/public')
    assert not parser.can_fetch('Python-Requests', 'https://example.com/private/public')
    assert parser.can_fetch('Python-Requests', 'https://example.com/private%2Fpublic')
    assert parser.crawl_delay('Python-Requests') == 7
    assert parser.request_rate('Python-Requests') == (2, 20)
    assert 'Allow: /private%2Fpublic' in str(parser)
    second = WebPageFetchService._parse_robots(b'User-agent: *\nDisallow: /\n')
    assert not second.can_fetch('Python-Requests', 'https://example.com/private%2Fpublic')
    assert robotparser.normalize is original


def test_invalid_rule_anchor_follows_robots_failure_policy():
    adapter = Adapter('User-agent: *\nDisallow: /private$extra\n')
    service = make_service(adapter)
    with pytest.raises(WebPageFetchError, match='could not establish robots permission'):
        service.fetch('https://example.com/private', WebPageFetchPolicy(enable_domain_pacing=False))
    assert adapter.calls == ['https://example.com/robots.txt']
    assert adapter.closes == 1 and all(body.closed for body in adapter.bodies)
