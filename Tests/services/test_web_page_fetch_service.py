import gzip
from dataclasses import replace
import threading
import zlib

import pytest
import requests

from Middleware.services.web_page_fetch_service import (
    WEB_PAGE_ROBOTS_TOKEN,
    WebPageFetchError,
    WebPageFetchPolicy,
    WebPageFetchService,
    get_default_web_page_fetch_service,
)


@pytest.mark.parametrize("changed", [
    {"verify": False}, {"proxies": {"https": "http://127.0.0.1:8080"}},
    {"allowed_hosts": frozenset({"example.com"})}, {"allow_redirects": False},
    {"max_transfer_bytes": 200},
])
def test_robots_permission_is_scoped_to_fetch_policy(changed):
    service, factory, _ = make_service(robots(), page(), robots(b"User-agent: *\nDisallow: /\n"))
    base = policy(enable_domain_pacing=False)
    service.fetch("https://example.com/one", replace(base, **changed))
    with pytest.raises(WebPageFetchError, match="disallowed"):
        service.fetch("https://example.com/two", base)
    assert len(factory.calls) == 3


def test_disabled_redirects_also_apply_to_robots():
    service, factory, _ = make_service(robots(status=302, Location="/rules"))
    with pytest.raises(WebPageFetchError, match="robots permission"):
        service.fetch("https://example.com/", policy(allow_redirects=False))
    assert len(factory.calls) == 1
    assert factory.sessions[0].closed


@pytest.mark.parametrize("body", [b"", b"late"])
def test_deadline_rechecked_after_final_raw_read(body):
    clock = FakeClock()
    raw = FakeRaw(body, on_read=lambda: clock.advance(2))
    service, factory, _ = make_service(
        FakeResponse(headers={"Content-Type": "text/html"}, raw=raw), clock=clock)
    with pytest.raises(WebPageFetchError, match="total timeout"):
        service.fetch("https://example.com/", policy(respect_robots=False, timeout=1))
    assert factory.sessions[0].closed


def test_pacing_lock_queue_is_bounded():
    service, factory, clock = make_service()
    lane = service._domain_lane("example.com")
    lane.lock.acquire()
    try:
        with pytest.raises(WebPageFetchError, match="maxPacingWaitSeconds"):
            service.fetch("https://example.com/", policy(respect_robots=False, max_pacing_wait_seconds=1))
    finally:
        lane.lock.release()
    assert clock.monotonic() == pytest.approx(101)
    assert not factory.calls


def test_pacing_cancellation_releases_lane_without_request():
    from Middleware.services.cancellation_service import cancellation_service
    from Middleware.exceptions.early_termination_exception import EarlyTerminationException

    service, factory, clock = make_service()
    service._domain_lane("example.com").next_allowed_at = clock.monotonic() + 5
    original_sleep = service._sleep

    def cancel_after_sleep(seconds):
        original_sleep(seconds)
        cancellation_service.request_cancellation("page-cancel-test")

    service._sleep = cancel_after_sleep
    try:
        with pytest.raises(EarlyTerminationException):
            service.fetch("https://example.com/", policy(respect_robots=False), request_id="page-cancel-test")
        assert clock.sleeps == [0.1]
        assert not factory.calls
        assert service._domain_lane("example.com").lock.acquire(blocking=False)
        service._domain_lane("example.com").lock.release()
    finally:
        cancellation_service.acknowledge_cancellation("page-cancel-test")


def test_received_cooldown_blocks_a_concurrent_pacing_waiter(monkeypatch):
    waiting = threading.Event()
    recorded = threading.Event()
    request_started = threading.Event()
    service, factory, clock = make_service(response(status=429, headers={'Retry-After': '60'}), page())
    original_request = FakeSession.request
    original_record = service._record_response_cooldown
    results = {}

    def request(session, **kwargs):
        if not request_started.is_set():
            request_started.set()
            assert waiting.wait(2), 'Second request never reached pacing'
        return original_request(session, **kwargs)

    def record(*args):
        try:
            return original_record(*args)
        finally:
            recorded.set()

    def sleep(seconds):
        if threading.current_thread().name == 'pacing-waiter':
            waiting.set()
            assert recorded.wait(2), 'Publisher cooldown could not be recorded'
        clock.advance(seconds)

    monkeypatch.setattr(FakeSession, 'request', request)
    monkeypatch.setattr(service, '_record_response_cooldown', record)
    service._sleep = sleep

    def fetch(name):
        try:
            results[name] = service.fetch('https://example.com/page', policy(respect_robots=False))
        except Exception as exc:
            results[name] = exc

    first = threading.Thread(target=fetch, args=('first',), name='publisher-response')
    second = threading.Thread(target=fetch, args=('second',), name='pacing-waiter')
    first.start()
    try:
        assert request_started.wait(2)
        second.start()
        first.join(3)
        second.join(3)
        assert not first.is_alive() and not second.is_alive()
        assert isinstance(results['first'], WebPageFetchError)
        assert isinstance(results['second'], WebPageFetchError)
        assert 'cooling down' in str(results['second'])
        assert len(factory.calls) == 1
        assert all(session.closed for session in factory.sessions)
    finally:
        waiting.set()
        recorded.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)


def test_session_is_closed_when_response_acquisition_is_interrupted():
    service, factory, _ = make_service(GeneratorExit())
    with pytest.raises(GeneratorExit):
        service.fetch('https://example.com/', policy(respect_robots=False))
    assert factory.sessions[0].closed


def test_policy_state_is_bounded_without_forgetting_cooldowns(monkeypatch):
    import Middleware.services.web_page_fetch_service as module

    monkeypatch.setattr(module, "_DOMAIN_LANE_COUNT", 1)
    monkeypatch.setattr(module, "_ORIGIN_LOCK_COUNT", 1)
    monkeypatch.setattr(module, "_CACHE_CAPACITY", 2)
    service, factory, _ = make_service(robots(), page(), robots(), page(), robots(), page())
    for host in ("one.test", "two.test", "three.test"):
        service.fetch(f"https://{host}/", policy(enable_domain_pacing=False))
    assert len(service._robots_cache) == 2
    assert len(service._origin_locks) == len(service._domain_lanes) == 1
    service._set_cooldown("one.test", 100, "HTTP 403")
    with pytest.raises(WebPageFetchError, match="cooling down"):
        service.fetch("https://four.test/", policy(respect_robots=False))
    assert len(factory.calls) == 6


class FakeClock:
    def __init__(self, monotonic=100.0, wall=1_700_000_000.0):
        self.now = monotonic
        self.wall = wall
        self.sleeps = []

    def monotonic(self):
        return self.now

    def time(self):
        return self.wall

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds)

    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds


class FakeRaw:
    def __init__(self, body=b"", *, chunks=None, error=None, on_read=None):
        self.chunks = list(chunks if chunks is not None else ([body] if body else []))
        self.error = error
        self.on_read = on_read
        self.read_count = 0

    def read(self, size=-1, decode_content=True):
        assert decode_content is False
        self.read_count += 1
        if self.on_read is not None:
            self.on_read()
        if self.error is not None:
            raise self.error
        if self.chunks:
            return self.chunks.pop(0)
        return b""


class FakeCookies:
    def __init__(self):
        self.clear_count = 0

    def clear(self):
        self.clear_count += 1


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"", *, raw=None):
        self.status_code = status
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.raw = raw or FakeRaw(body)
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, factory):
        self.factory = factory
        self.headers = {"Requests-Default": "must-be-cleared"}
        self.cookies = FakeCookies()
        self.trust_env = True
        self.closed = False

    def request(self, **kwargs):
        self.factory.calls.append((self, kwargs))
        item = self.factory.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


class SessionFactory:
    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls = []
        self.sessions = []
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            session = FakeSession(self)
            self.sessions.append(session)
            return session


def make_service(*responses, checker=None, clock=None):
    factory = SessionFactory(*responses)
    clock = clock or FakeClock()
    service = WebPageFetchService(
        session_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        wall_time=clock.time,
        url_checker=checker or (lambda url, block, hosts: None),
    )
    return service, factory, clock


def response(status=200, body=b"", headers=None):
    return FakeResponse(status, headers, body)


def page(body=b"page", **headers):
    return response(200, body, {"Content-Type": "text/html; charset=utf-8", **headers})


def robots(body=b"User-agent: *\nDisallow:\n", status=200, **headers):
    return response(status, body, headers)


def policy(**overrides):
    values = {
        "block_private_addresses": False,
    }
    values.update(overrides)
    return WebPageFetchPolicy(**values)


def test_policy_defaults_are_publisher_cautious():
    defaults = WebPageFetchPolicy()

    assert WEB_PAGE_ROBOTS_TOKEN == requests.utils.default_user_agent().split("/", 1)[0]
    assert defaults.respect_robots is True
    assert defaults.fail_closed_on_robots_error is True
    assert defaults.block_private_addresses is True
    assert defaults.restrict_ports is True
    assert defaults.enable_domain_pacing is True
    assert defaults.honor_crawl_delay is True
    assert defaults.honor_request_rate is True
    assert defaults.honor_retry_after is True
    assert defaults.honor_forbidden_cooldown is True
    assert defaults.allow_redirects is True
    assert defaults.enforce_content_type is True
    assert defaults.minimum_delay_seconds == 5
    assert defaults.max_redirects == 5
    assert defaults.max_header_bytes == 128 * 1024
    assert defaults.max_transfer_bytes == 5 * 1024 * 1024
    assert defaults.max_decoded_bytes == 25 * 1024 * 1024


def test_cold_fetch_checks_robots_paces_and_uses_stateless_identity():
    robots_response = robots()
    page_response = page(b"hello", **{"Set-Cookie": "secret=1", "X-Test": "ok"})
    service, factory, clock = make_service(robots_response, page_response)

    result = service.fetch("https://docs.example.com/start#fragment", policy())

    assert result.body == b"hello"
    assert result.text == "hello"
    assert result.url == "https://docs.example.com/start"
    assert result.headers["X-Test"] == "ok"
    assert all(name.lower() != "set-cookie" for name in result.headers)
    assert clock.sleeps == [5]
    assert [call[1]["url"] for call in factory.calls] == [
        "https://docs.example.com/robots.txt",
        "https://docs.example.com/start",
    ]
    for session, request_args in factory.calls:
        assert session.trust_env is False
        assert session.headers == requests.utils.default_headers()
        assert session.cookies.clear_count == 1
        assert session.closed is True
        assert request_args["method"] == "GET"
        assert "User-Agent" not in request_args["headers"]
        assert "Authorization" not in request_args["headers"]
        assert "Cookie" not in request_args["headers"]
        assert "Referer" not in request_args["headers"]
        assert request_args["allow_redirects"] is False
        assert request_args["stream"] is True
    assert robots_response.closed is True
    assert page_response.closed is True


def test_robots_allow_disallow_crawl_delay_and_request_rate():
    rules = robots(
        b"User-agent: *\n"
        b"Disallow: /private\n"
        b"Allow: /private/public\n"
        b"Crawl-delay: 10\n"
        b"Request-rate: 2/30\n"
    )
    service, factory, clock = make_service(rules, page(b"allowed"))

    result = service.fetch("https://www.example.com/private/public", policy())

    assert result.body == b"allowed"
    assert clock.sleeps == [15]
    with pytest.raises(WebPageFetchError, match="disallowed"):
        service.fetch("https://www.example.com/private/blocked", policy())
    assert len(factory.calls) == 2


def test_absent_robots_is_cached_and_page_requests_still_share_pacing_lane():
    service, factory, clock = make_service(
        robots(status=404),
        page(b"one"),
        page(b"two"),
    )

    assert service.fetch("https://a.example.com/one", policy()).body == b"one"
    assert service.fetch("https://a.example.com/two", policy()).body == b"two"

    assert [call[1]["url"] for call in factory.calls] == [
        "https://a.example.com/robots.txt",
        "https://a.example.com/one",
        "https://a.example.com/two",
    ]
    assert clock.sleeps == [5, 5]


@pytest.mark.parametrize(
    "robots_response, message",
    [
        (robots(status=500), "HTTP 500"),
        (robots(b"not a directive"), "malformed"),
        (robots(b"\xff"), "valid UTF-8"),
        (robots(b"Disallow: /\n"), "before a User-agent"),
        (robots(b"User-agent:\n"), "empty User-agent"),
        (robots(b"User-agent: *\nCrawl-delay: 1.5\n"), "invalid Crawl-delay"),
        (robots(b"User-agent: *\nRequest-rate: x/y\n"), "invalid Request-rate"),
    ],
)
def test_robots_failures_are_closed_and_not_retried(robots_response, message):
    service, factory, _ = make_service(robots_response)

    with pytest.raises(WebPageFetchError, match=message):
        service.fetch("https://example.com/page", policy())

    assert len(factory.calls) == 1


def test_robots_failure_can_be_explicitly_failed_open():
    service, factory, clock = make_service(robots(status=500), page(b"allowed"))

    result = service.fetch(
        "https://example.com/page",
        policy(fail_closed_on_robots_error=False),
    )

    assert result.body == b"allowed"
    assert len(factory.calls) == 2
    assert clock.sleeps == [5]


@pytest.mark.parametrize("status", [401, 403])
def test_refused_robots_is_denied_even_when_general_fail_closed_is_disabled(status):
    service, factory, _ = make_service(robots(status=status))

    with pytest.raises(WebPageFetchError, match="denied by robots policy"):
        service.fetch(
            "https://example.com/page",
            policy(fail_closed_on_robots_error=False),
        )

    assert len(factory.calls) == 1


def test_robots_redirect_is_manual_validated_and_bounded():
    checked = []

    def checker(url, block, hosts):
        checked.append(url)
        return None

    service, factory, clock = make_service(
        response(302, headers={"Location": "https://policy.example.net/rules"}),
        robots(),
        page(b"ok"),
        checker=checker,
    )

    result = service.fetch("https://example.com/page", policy())

    assert result.body == b"ok"
    assert [call[1]["url"] for call in factory.calls] == [
        "https://example.com/robots.txt",
        "https://policy.example.net/rules",
        "https://example.com/page",
    ]
    assert checked == [
        "https://example.com/page",
        "https://example.com/robots.txt",
        "https://policy.example.net/rules",
    ]
    assert clock.sleeps == [5]


def test_page_cross_domain_redirect_gets_fresh_robots_decision():
    service, factory, clock = make_service(
        robots(status=404),
        response(302, headers={"Location": "https://target.example.net/final"}),
        robots(status=404),
        page(b"final"),
    )

    result = service.fetch("https://source.example.com/start", policy())

    assert result.url == "https://target.example.net/final"
    assert [call[1]["url"] for call in factory.calls] == [
        "https://source.example.com/robots.txt",
        "https://source.example.com/start",
        "https://target.example.net/robots.txt",
        "https://target.example.net/final",
    ]
    assert clock.sleeps == [5, 5]


def test_redirect_policy_errors_close_response_and_do_not_read_body():
    redirect = response(302, body=b"must not read", headers={"Location": "/next"})
    service, factory, _ = make_service(redirect)

    with pytest.raises(WebPageFetchError, match="redirects are disabled"):
        service.fetch(
            "https://example.com/start",
            policy(respect_robots=False, enable_domain_pacing=False, allow_redirects=False),
        )

    assert len(factory.calls) == 1
    assert redirect.raw.read_count == 0
    assert redirect.closed is True


def test_redirect_without_location_and_redirect_cap_are_errors():
    service, _, _ = make_service(response(302))
    with pytest.raises(WebPageFetchError, match="without a Location"):
        service.fetch(
            "https://example.com/start",
            policy(respect_robots=False, enable_domain_pacing=False),
        )

    service, factory, _ = make_service(
        response(301, headers={"Location": "/two"}),
        response(301, headers={"Location": "/three"}),
    )
    with pytest.raises(WebPageFetchError, match="maximum of 1 redirects"):
        service.fetch(
            "https://example.com/one",
            policy(respect_robots=False, enable_domain_pacing=False, max_redirects=1),
        )
    assert len(factory.calls) == 2


@pytest.mark.parametrize(
    "url, message",
    [
        ("", "non-empty"),
        ("example.com", "absolute"),
        ("ftp://example.com/a", "absolute"),
        ("https:///missing", "hostname"),
        ("https://user:pass@example.com/", "embedded credentials"),
        ("https://example.com:bad/", "invalid port"),
        ("https://example.com:444/", "does not permit port"),
        ("https://example.com/a b", "invalid whitespace"),
        ("https://example.com\\evil", "invalid whitespace or delimiters"),
        ("http://[fe80::1%25eth0]/", "invalid hostname"),
    ],
)
def test_url_validation_rejects_invalid_targets_before_a_request(url, message):
    service, factory, _ = make_service()

    with pytest.raises(WebPageFetchError, match=message):
        service.fetch(url, policy(respect_robots=False, enable_domain_pacing=False))

    assert factory.calls == []


def test_port_exception_and_address_checker_apply_to_every_page_hop():
    checked = []

    def checker(url, block, hosts):
        checked.append((url, block, hosts))
        if "blocked.example.net" in url:
            return "test rejection"
        return None

    service, factory, _ = make_service(
        response(302, headers={"Location": "https://blocked.example.net/final"}),
        checker=checker,
    )
    fetch_policy = policy(
        respect_robots=False,
        enable_domain_pacing=False,
        block_private_addresses=True,
        allowed_hosts=frozenset({"example.com"}),
        allowed_ports=frozenset({444}),
    )

    with pytest.raises(WebPageFetchError, match="test rejection"):
        service.fetch("https://example.com:444/start", fetch_policy)

    assert len(factory.calls) == 1
    assert checked == [
        ("https://example.com:444/start", True, frozenset({"example.com"})),
        ("https://blocked.example.net/final", True, frozenset({"example.com"})),
    ]


def test_default_address_guard_blocks_private_ip_without_opening_session(mocker):
    resolve = mocker.patch(
        "Middleware.utilities.network_security_utils.socket.getaddrinfo",
        side_effect=AssertionError("IP literal validation must not perform DNS resolution"),
    )
    factory = SessionFactory()
    service = WebPageFetchService(session_factory=factory)

    with pytest.raises(WebPageFetchError, match="private address"):
        service.fetch(
            "http://192.168.1.14/page",
            WebPageFetchPolicy(respect_robots=False, enable_domain_pacing=False),
        )

    resolve.assert_not_called()
    assert factory.sessions == []
    assert factory.calls == []


def test_content_type_is_checked_before_body_and_can_be_disabled():
    rejected = response(200, b"binary", {"Content-Type": "application/octet-stream"})
    service, _, _ = make_service(rejected)
    with pytest.raises(WebPageFetchError, match="Content-Type"):
        service.fetch(
            "https://example.com/file",
            policy(respect_robots=False, enable_domain_pacing=False),
        )
    assert rejected.raw.read_count == 0

    missing = response(200, b"plain")
    service, _, _ = make_service(missing)
    with pytest.raises(WebPageFetchError, match="missing"):
        service.fetch(
            "https://example.com/file",
            policy(respect_robots=False, enable_domain_pacing=False),
        )

    service, _, _ = make_service(response(200, b"binary"))
    result = service.fetch(
        "https://example.com/file",
        policy(
            respect_robots=False,
            enable_domain_pacing=False,
            enforce_content_type=False,
        ),
    )
    assert result.body == b"binary"


def test_custom_content_type_allowlist_is_used_case_insensitively():
    service, _, _ = make_service(
        response(200, b"xml", {"Content-Type": "Application/XML; charset=UTF-8"})
    )

    result = service.fetch(
        "https://example.com/file",
        policy(
            respect_robots=False,
            enable_domain_pacing=False,
            allowed_content_types=frozenset({"application/xml"}),
        ),
    )

    assert result.body == b"xml"


def test_header_content_length_and_transfer_caps_are_independent():
    too_many_headers = page(b"", **{"X-Large": "abcdefghij"})
    service, _, _ = make_service(too_many_headers)
    with pytest.raises(WebPageFetchError, match="maxHeaderBytes"):
        service.fetch(
            "https://example.com/",
            policy(
                respect_robots=False,
                enable_domain_pacing=False,
                max_header_bytes=20,
            ),
        )
    assert too_many_headers.raw.read_count == 0

    announced_too_large = page(b"small", **{"Content-Length": "11"})
    service, _, _ = make_service(announced_too_large)
    with pytest.raises(WebPageFetchError, match="maxTransferBytes"):
        service.fetch(
            "https://example.com/",
            policy(
                respect_robots=False,
                enable_domain_pacing=False,
                max_transfer_bytes=10,
            ),
        )
    assert announced_too_large.raw.read_count == 0

    streamed_too_large = FakeResponse(
        200,
        {"Content-Type": "text/plain"},
        raw=FakeRaw(chunks=[b"123456", b"78901"]),
    )
    service, _, _ = make_service(streamed_too_large)
    with pytest.raises(WebPageFetchError, match="maxTransferBytes"):
        service.fetch(
            "https://example.com/",
            policy(
                respect_robots=False,
                enable_domain_pacing=False,
                max_transfer_bytes=10,
            ),
        )


def test_gzip_and_zlib_and_raw_deflate_are_decoded_under_separate_cap():
    content = b"decoded text" * 20
    encoded_variants = [
        ("gzip", gzip.compress(content)),
        ("deflate", zlib.compress(content)),
        ("deflate", zlib.compress(content)[2:-4]),
    ]

    for encoding, encoded in encoded_variants:
        service, _, _ = make_service(
            response(
                200,
                encoded,
                {"Content-Type": "text/plain", "Content-Encoding": encoding},
            )
        )
        result = service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False),
        )
        assert result.body == content

    split_raw = zlib.compress(content)[2:-4]
    service, _, _ = make_service(FakeResponse(
        200,
        {"Content-Type": "text/plain", "Content-Encoding": "deflate"},
        raw=FakeRaw(chunks=[split_raw[:1], split_raw[1:]]),
    ))
    assert service.fetch(
        "https://example.com/",
        policy(respect_robots=False, enable_domain_pacing=False),
    ).body == content


def test_decoded_cap_incomplete_compression_and_unknown_encoding_fail_once():
    compressed = gzip.compress(b"a" * 100)
    service, factory, _ = make_service(
        response(
            200,
            compressed,
            {"Content-Type": "text/plain", "Content-Encoding": "gzip"},
        )
    )
    with pytest.raises(WebPageFetchError, match="maxDecodedBytes"):
        service.fetch(
            "https://example.com/",
            policy(
                respect_robots=False,
                enable_domain_pacing=False,
                max_decoded_bytes=50,
            ),
        )
    assert len(factory.calls) == 1

    service, _, _ = make_service(
        response(
            200,
            compressed[:-3],
            {"Content-Type": "text/plain", "Content-Encoding": "gzip"},
        )
    )
    with pytest.raises(WebPageFetchError, match="complete compressed stream"):
        service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False),
        )

    service, _, _ = make_service(
        response(
            200,
            b"data",
            {"Content-Type": "text/plain", "Content-Encoding": "br"},
        )
    )
    with pytest.raises(WebPageFetchError, match="does not support Content-Encoding"):
        service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False),
        )

    service, _, _ = make_service(response(
        200,
        gzip.compress(b"one") + gzip.compress(b"two"),
        {"Content-Type": "text/plain", "Content-Encoding": "gzip"},
    ))
    with pytest.raises(WebPageFetchError, match="trailing compressed data"):
        service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False),
        )


def test_raw_read_error_and_total_timeout_are_not_retried():
    broken = FakeResponse(
        200,
        {"Content-Type": "text/plain"},
        raw=FakeRaw(error=OSError("read failed")),
    )
    service, factory, _ = make_service(broken)
    with pytest.raises(WebPageFetchError, match="read or decompress"):
        service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False),
        )
    assert len(factory.calls) == 1

    clock = FakeClock()
    slow_raw = FakeRaw(chunks=[b"chunk"], on_read=lambda: clock.advance(2))
    service, factory, _ = make_service(
        FakeResponse(200, {"Content-Type": "text/plain"}, raw=slow_raw),
        clock=clock,
    )
    with pytest.raises(WebPageFetchError, match="total timeout"):
        service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False, timeout=1),
        )
    assert len(factory.calls) == 1


def test_transport_exception_is_wrapped_and_never_retried():
    service, factory, _ = make_service(requests.exceptions.Timeout("late"))

    with pytest.raises(WebPageFetchError, match="before receiving a response"):
        service.fetch(
            "https://example.com/",
            policy(respect_robots=False, enable_domain_pacing=False),
        )

    assert len(factory.calls) == 1
    assert factory.sessions[0].closed is True


def test_robots_transport_exception_is_cached_as_a_failure():
    service, factory, _ = make_service(requests.exceptions.ConnectionError("offline"))

    for _ in range(2):
        with pytest.raises(WebPageFetchError, match="could not establish robots permission"):
            service.fetch("https://example.com/page", policy(enable_domain_pacing=False))

    assert len(factory.calls) == 1


def test_http_error_has_bounded_public_metadata_and_no_body_read():
    denied = response(
        418,
        b"large error",
        {"Content-Type": "text/plain", "Set-Cookie": "secret=1", "X-Test": "yes"},
    )
    service, _, _ = make_service(denied)

    with pytest.raises(WebPageFetchError) as raised:
        service.fetch(
            "https://example.com/teapot",
            policy(respect_robots=False, enable_domain_pacing=False),
        )

    assert raised.value.status_code == 418
    assert raised.value.url == "https://example.com/teapot"
    assert raised.value.headers == {"Content-Type": "text/plain", "X-Test": "yes"}
    assert denied.raw.read_count == 0


def test_403_sets_seven_day_default_cooldown_and_fails_future_call_fast():
    service, factory, clock = make_service(response(403))
    no_robots = policy(respect_robots=False, enable_domain_pacing=False)

    with pytest.raises(WebPageFetchError, match="HTTP status 403"):
        service.fetch("https://a.example.com/one", no_robots)
    with pytest.raises(WebPageFetchError, match="cooling down.*HTTP 403"):
        service.fetch("https://b.example.com/two", no_robots)

    assert len(factory.calls) == 1
    lane = service._domain_lane("a.example.com")
    assert lane.cooldown_until - clock.monotonic() == 604800


@pytest.mark.parametrize(
    "header, expected",
    [("120", 120), ("bad", 60), (None, 60)],
)
def test_retry_after_numeric_and_fallback_cooldowns(header, expected):
    headers = {"Retry-After": header} if header is not None else {}
    service, factory, clock = make_service(response(429, headers=headers))
    no_robots = policy(respect_robots=False, enable_domain_pacing=False)

    with pytest.raises(WebPageFetchError, match="HTTP status 429"):
        service.fetch("https://example.com/one", no_robots)
    with pytest.raises(WebPageFetchError, match="cooling down"):
        service.fetch("https://example.com/two", no_robots)

    assert len(factory.calls) == 1
    assert service._domain_lane("example.com").cooldown_until - clock.monotonic() == expected


def test_retry_after_http_date_and_disabled_cooldown_controls():
    clock = FakeClock(wall=1_700_000_000)
    service, _, _ = make_service(response(503, headers={"Retry-After": "Tue, 14 Nov 2023 22:15:20 GMT"}), clock=clock)
    no_robots = policy(respect_robots=False, enable_domain_pacing=False)
    with pytest.raises(WebPageFetchError, match="HTTP status 503"):
        service.fetch("https://example.com/", no_robots)
    assert service._domain_lane("example.com").cooldown_until - clock.monotonic() == 120

    service, factory, _ = make_service(response(403), response(200, b"ok", {"Content-Type": "text/plain"}))
    disabled = policy(
        respect_robots=False,
        enable_domain_pacing=False,
        honor_retry_after=False,
        honor_forbidden_cooldown=False,
    )
    with pytest.raises(WebPageFetchError, match="403"):
        service.fetch("https://example.com/one", disabled)
    assert service.fetch("https://example.com/two", disabled).body == b"ok"
    assert len(factory.calls) == 2


def test_pacing_limit_fails_fast_instead_of_waiting_too_long():
    service, factory, clock = make_service(page(b"one"), page(b"two"))
    paced = policy(
        respect_robots=False,
        minimum_delay_seconds=10,
        max_pacing_wait_seconds=3,
    )

    assert service.fetch("https://a.example.com/one", paced).body == b"one"
    with pytest.raises(WebPageFetchError, match="exceeds maxPacingWaitSeconds"):
        service.fetch("https://b.example.com/two", paced)

    assert len(factory.calls) == 1
    assert clock.sleeps == []


def test_success_and_failure_robots_cache_ttls_are_configurable():
    service, factory, clock = make_service(
        robots(status=404),
        page(b"one"),
        robots(status=404),
        page(b"two"),
    )
    short_cache = policy(
        enable_domain_pacing=False,
        robots_cache_seconds=1,
    )

    assert service.fetch("https://example.com/one", short_cache).body == b"one"
    clock.advance(2)
    assert service.fetch("https://example.com/two", short_cache).body == b"two"
    assert len(factory.calls) == 4

    service, factory, clock = make_service(robots(status=500), robots(status=500))
    short_failure = policy(
        enable_domain_pacing=False,
        robots_failure_cache_seconds=1,
    )
    with pytest.raises(WebPageFetchError):
        service.fetch("https://example.com/one", short_failure)
    with pytest.raises(WebPageFetchError):
        service.fetch("https://example.com/two", short_failure)
    assert len(factory.calls) == 1
    clock.advance(2)
    with pytest.raises(WebPageFetchError):
        service.fetch("https://example.com/three", short_failure)
    assert len(factory.calls) == 2


def test_concurrent_origin_misses_share_one_robots_request():
    robots_started = threading.Event()
    release_robots = threading.Event()
    second_caller_checked_cache = threading.Event()

    class BlockingSession(FakeSession):
        def request(self, **kwargs):
            if kwargs["url"].endswith("/robots.txt") and not robots_started.is_set():
                robots_started.set()
                assert release_robots.wait(2)
            return super().request(**kwargs)

    class BlockingFactory(SessionFactory):
        def __call__(self):
            with self.lock:
                session = BlockingSession(self)
                self.sessions.append(session)
                return session

    class ObservedService(WebPageFetchService):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache_checks = 0
            self.cache_check_lock = threading.Lock()

        def _cached_robots(self, origin, fetch_policy):
            with self.cache_check_lock:
                self.cache_checks += 1
                if self.cache_checks >= 3:
                    second_caller_checked_cache.set()
            return super()._cached_robots(origin, fetch_policy)

    factory = BlockingFactory(robots(status=404), page(b"one"), page(b"two"))
    service = ObservedService(
        session_factory=factory,
        url_checker=lambda url, block, hosts: None,
    )
    fetch_policy = policy(enable_domain_pacing=False)
    results = []
    errors = []

    def fetch(path):
        try:
            results.append(service.fetch(f"https://example.com/{path}", fetch_policy).body)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=fetch, args=("one",))
    second = threading.Thread(target=fetch, args=("two",))
    first.start()
    assert robots_started.wait(2)
    second.start()
    try:
        assert second_caller_checked_cache.wait(2)
    finally:
        release_robots.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert sorted(results) == [b"one", b"two"]
    assert [call[1]["url"] for call in factory.calls].count(
        "https://example.com/robots.txt"
    ) == 1


def test_domain_lane_key_is_conservative_and_singletons_are_stable():
    assert WebPageFetchService._registrable_domain_lane("www.example.com") == "example.com"
    assert WebPageFetchService._registrable_domain_lane("docs.example.com") == "example.com"
    assert WebPageFetchService._registrable_domain_lane("a.example.co.uk") == "co.uk"
    assert WebPageFetchService._registrable_domain_lane("203.0.113.10") == "203.0.113.10"
    assert get_default_web_page_fetch_service() is get_default_web_page_fetch_service()
