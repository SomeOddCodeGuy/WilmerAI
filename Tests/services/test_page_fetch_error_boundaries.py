"""Fetch errors cross the real page service/handler boundary without network I/O."""
import json
import logging
from unittest.mock import Mock

import pytest

from Middleware.services.web_page_fetch_service import WebPageFetchError
from Middleware.utilities import sensitive_logging_utils as privacy
from Middleware.workflows.handlers.impl.web_page_fetch_handler import WebPageFetchHandler
from Middleware.workflows.models.execution_context import ExecutionContext
from Tests.services.test_web_page_fetch_service import make_service, page, policy, response, robots


def make_handler(service, **config):
    variables = Mock()
    variables.apply_variables.side_effect = lambda value, context: value
    handler = WebPageFetchHandler(Mock(), variables, web_page_fetch_service=service)
    stream = config.pop('stream', False)
    context = ExecutionContext(request_id=None, workflow_id='test', discussion_id=None, messages=[],
        stream=stream, config={'url': 'https://example.com/page', 'enableDomainPacing': False, **config})
    return handler, context


@pytest.mark.parametrize('redacted', [True, False])
@pytest.mark.parametrize('source', ['content-type', 'robots-warning'])
def test_page_diagnostics_honor_request_redaction(caplog, redacted, source):
    marker = 'synthetic-private-fetch-content'
    if source == 'content-type':
        service, factory, _ = make_service(response(200, headers={'Content-Type': 'application/' + marker}))
        handler, context = make_handler(service, respectRobots=False, onError='return')
    else:
        service, factory, _ = make_service(robots(**{'Content-Encoding': marker}), page(b'ok'))
        handler, context = make_handler(service, failClosedOnRobotsError=False)
    previous = privacy.is_encryption_active()
    privacy.set_encryption_context(redacted)
    caplog.set_level(logging.WARNING)
    try:
        result = handler.handle(context)
        assert 'Content-Type' in result if source == 'content-type' else result == 'ok'
        assert (marker in caplog.text) is (not redacted)
        assert all(session.closed for session in factory.sessions)
    finally:
        privacy.set_encryption_context(previous)


@pytest.mark.parametrize('status,for_robots', [(429, False), (503, True)])
def test_invalid_retry_after_retains_fallback_cooldown(status, for_robots):
    received = response(status, headers={'Retry-After': '\u00b2'})
    service, factory, clock = make_service(received)
    settings = policy(respect_robots=for_robots, fail_closed_on_robots_error=False)
    with pytest.raises(WebPageFetchError):
        service.fetch('https://example.com/page', settings)
    assert service._domain_lane('example.com').cooldown_until == clock.monotonic() + 60
    with pytest.raises(WebPageFetchError, match='cooling down'):
        service.fetch('https://example.com/page', settings)
    assert len(factory.calls) == 1
    assert received.closed and factory.sessions[0].closed


@pytest.mark.parametrize('source,on_error,output,stream', [
    ('page', 'return', 'full', False),
    ('page', 'return', 'text', True),
    ('page', 'raise', 'text', False),
    ('robots', 'return', 'full', True),
    ('initial', 'return', 'full', False),
    ('initial', 'raise', 'text', False),
])
def test_malformed_url_obeys_fetch_error_contract(source, on_error, output, stream):
    redirect = response(302, headers={'Location': 'http://['})
    service, factory, _ = make_service(*([] if source == 'initial' else [redirect]))
    handler, context = make_handler(service, respectRobots=source == 'robots', onError=on_error,
        outputFormat=output, stream=stream, url='http://[' if source == 'initial' else 'https://example.com/page')
    if on_error == 'raise':
        with pytest.raises(WebPageFetchError, match='could not be parsed'):
            handler.handle(context)
    else:
        result = handler.handle(context)
        if stream:
            result = ''.join(chunk['token'] for chunk in result)
        if output == 'full':
            envelope = json.loads(result)
            assert envelope['body'] is None
            result = envelope['error']
        assert 'could not be parsed' in result
    assert len(factory.calls) == (0 if source == 'initial' else 1)
    assert all(session.closed for session in factory.sessions)
    if source != 'initial':
        assert redirect.closed


@pytest.mark.parametrize('location', ['http://[', 'https://example.com:invalid/rules', '/caf\u00e9'])
def test_invalid_robots_redirect_can_fail_open_and_is_cached(location):
    redirect = robots(status=302, Location=location)
    service, factory, _ = make_service(redirect, page(b'one'), page(b'two'))
    settings = policy(enable_domain_pacing=False, fail_closed_on_robots_error=False)
    assert service.fetch('https://example.com/one', settings).body == b'one'
    assert service.fetch('https://example.com/two', settings).body == b'two'
    assert [call[1]['url'] for call in factory.calls] == [
        'https://example.com/robots.txt', 'https://example.com/one', 'https://example.com/two']
    assert redirect.closed and all(session.closed for session in factory.sessions)


@pytest.mark.parametrize('directive', ['Crawl-delay: \u00b2', 'Request-rate: \u00b2/1',
                                      'Crawl-delay: ' + '9' * 400])
def test_robots_parser_errors_follow_failure_policy(directive):
    service, factory, _ = make_service(robots(('User-agent: *\n' + directive + '\n').encode()))
    settings = policy(enable_domain_pacing=False)
    for _ in range(2):
        with pytest.raises(WebPageFetchError, match='robots permission'):
            service.fetch('https://example.com/page', settings)
    assert len(factory.calls) == 1
    assert factory.sessions[0].closed


def test_non_ascii_content_length_does_not_escape_bounded_body_reader():
    service, factory, _ = make_service(page(b'ok', **{'Content-Length': '\u00b2'}))
    assert service.fetch('https://example.com/page', policy(respect_robots=False)).body == b'ok'
    assert factory.sessions[0].closed
