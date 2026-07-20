import json
import threading

import pytest

from Middleware.api.concurrency_middleware import (
    ConcurrencyLimitMiddleware,
    _SemaphoreReleasingIterator,
)


def _make_simple_app(body_chunks):
    """Returns a WSGI app that yields the given chunks."""
    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return iter(body_chunks)
    return app


def _make_streaming_app(chunks):
    """Returns a WSGI app that yields chunks from a generator."""
    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/event-stream")])
        def generate():
            for chunk in chunks:
                yield chunk
        return generate()
    return app


def _call_middleware(middleware, method="POST"):
    """Calls the middleware with a dummy environ and captures the response."""
    captured = {}
    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers
    body = middleware({"REQUEST_METHOD": method}, start_response)
    return captured, body


def test_non_streaming_acquire_and_release():
    """Semaphore acquired once, released once after response consumed."""
    sem = threading.BoundedSemaphore(1)
    app = _make_simple_app([b"hello", b" world"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=5)

    captured, body = _call_middleware(mw)
    assert captured["status"] == "200 OK"

    # Semaphore is held while iterating
    assert not sem.acquire(blocking=False)

    # Consume the response
    chunks = list(body)
    assert chunks == [b"hello", b" world"]

    # Semaphore released after exhaustion
    assert sem.acquire(blocking=False)
    sem.release()


def test_streaming_held_across_chunks():
    """Semaphore held across all streaming chunks, released after exhaustion."""
    sem = threading.BoundedSemaphore(1)
    app = _make_streaming_app([b"chunk1", b"chunk2", b"chunk3"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=5)

    captured, body = _call_middleware(mw)

    # Read first chunk; semaphore still held
    first = next(body)
    assert first == b"chunk1"
    assert not sem.acquire(blocking=False)

    # Read remaining
    rest = list(body)
    assert rest == [b"chunk2", b"chunk3"]

    # Now released
    assert sem.acquire(blocking=False)
    sem.release()


def test_inner_app_exception_releases_semaphore():
    """If the inner WSGI app raises, semaphore is released."""
    sem = threading.BoundedSemaphore(1)

    def failing_app(environ, start_response):
        raise RuntimeError("boom")

    mw = ConcurrencyLimitMiddleware(failing_app, sem, acquire_timeout=5)

    with pytest.raises(RuntimeError, match="boom"):
        _call_middleware(mw)

    # Semaphore should be released
    assert sem.acquire(blocking=False)
    sem.release()


def test_mid_iteration_exception_releases_semaphore():
    """If iteration raises mid-stream, semaphore is released."""
    sem = threading.BoundedSemaphore(1)

    def exploding_generator():
        yield b"ok"
        raise ValueError("mid-stream error")

    def app(environ, start_response):
        start_response("200 OK", [])
        return exploding_generator()

    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=5)
    captured, body = _call_middleware(mw)

    first = next(body)
    assert first == b"ok"

    with pytest.raises(ValueError, match="mid-stream error"):
        next(body)

    # Semaphore released
    assert sem.acquire(blocking=False)
    sem.release()


def test_close_before_exhaustion_releases_exactly_once():
    """close() releases the semaphore; no double-release error from BoundedSemaphore."""
    sem = threading.BoundedSemaphore(1)
    app = _make_streaming_app([b"a", b"b", b"c"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=5)

    captured, body = _call_middleware(mw)
    next(body)  # consume one chunk

    # Close before exhaustion
    body.close()

    # Semaphore released exactly once
    assert sem.acquire(blocking=False)
    sem.release()

    # Calling close again should not raise (already released, guard prevents double-release)
    body.close()


def test_close_delegates_to_underlying_iterable():
    """close() calls the underlying iterable's close() after releasing the semaphore."""
    sem = threading.BoundedSemaphore(1)
    inner_closed = False

    def generator():
        nonlocal inner_closed
        try:
            yield b"chunk"
        finally:
            inner_closed = True

    wrapper = _SemaphoreReleasingIterator(generator(), sem)
    sem.acquire()  # simulate the middleware having acquired

    next(wrapper)
    wrapper.close()

    assert inner_closed
    # Semaphore was released by close()
    assert sem.acquire(blocking=False)
    sem.release()


def test_concurrency_two_allows_two_blocks_third():
    """With concurrency=2, two requests proceed and a third blocks until one finishes."""
    sem = threading.BoundedSemaphore(2)
    entered_count = threading.Semaphore(0)
    release_event = threading.Event()
    results = {"r1": None, "r2": None, "r3": None}

    def blocking_app(environ, start_response):
        start_response("200 OK", [])
        entered_count.release()  # signal that this request entered the app
        release_event.wait(timeout=5)
        return [b"done"]

    mw = ConcurrencyLimitMiddleware(blocking_app, sem, acquire_timeout=5)

    def run_request(name):
        captured, body = _call_middleware(mw)
        results[name] = list(body)

    t1 = threading.Thread(target=run_request, args=("r1",))
    t2 = threading.Thread(target=run_request, args=("r2",))
    t1.start()
    t2.start()

    # Wait for both to enter the app (past acquire)
    assert entered_count.acquire(timeout=5)
    assert entered_count.acquire(timeout=5)

    # Third request: semaphore is exhausted, should block on acquire
    third_entered_app = threading.Event()

    def blocking_app_third(environ, start_response):
        start_response("200 OK", [])
        third_entered_app.set()
        return [b"done"]

    mw_third = ConcurrencyLimitMiddleware(blocking_app_third, sem, acquire_timeout=5)

    def run_third():
        captured, body = _call_middleware(mw_third)
        results["r3"] = list(body)

    t3 = threading.Thread(target=run_third)
    t3.start()

    # Give t3 a moment; it should NOT have entered the app
    assert not third_entered_app.wait(timeout=0.3)

    # Release the first two
    release_event.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # Now third should proceed
    assert third_entered_app.wait(timeout=5)
    t3.join(timeout=5)

    assert results["r1"] == [b"done"]
    assert results["r2"] == [b"done"]
    assert results["r3"] == [b"done"]


def test_acquire_timeout_returns_503():
    """When semaphore cannot be acquired within timeout, returns 503 JSON."""
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust the semaphore

    app = _make_simple_app([b"should not reach"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    captured, body = _call_middleware(mw)
    assert captured["status"] == "503 Service Unavailable"

    response_body = b"".join(body)
    parsed = json.loads(response_body)
    assert parsed["error"]["message"] == "Server busy, concurrency limit reached"
    assert parsed["error"]["type"] == "server_error"
    assert parsed["error"]["code"] == 503

    # The 503 must carry correct headers so clients can parse the JSON body.
    headers = dict(captured["headers"])
    assert headers["Content-Type"] == "application/json"
    assert headers["Content-Length"] == str(len(response_body))

    sem.release()  # cleanup


def test_exhaust_then_close_releases_exactly_once():
    """WSGI servers call close() after consuming the iterator. The release that
    already happened at exhaustion must not repeat; BoundedSemaphore would
    raise ValueError on a second release."""
    sem = threading.BoundedSemaphore(1)
    app = _make_streaming_app([b"a", b"b"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=5)

    captured, body = _call_middleware(mw)
    assert list(body) == [b"a", b"b"]

    body.close()  # must not raise via a second semaphore.release()

    # Released exactly once: the slot is free again.
    assert sem.acquire(blocking=False)
    sem.release()


@pytest.mark.parametrize("method,expects_gate", [
    # Only POST dispatches to LLM workflows and is throttled; every other method
    # (and there are only GET/DELETE metadata endpoints today) bypasses the gate.
    ("GET", False),
    ("POST", True),
    ("PUT", False),
    ("PATCH", False),
    ("DELETE", False),
    # A missing REQUEST_METHOD defaults to POST, i.e. fail-closed into the gate.
    (None, True),
])
def test_request_method_semaphore_gating(method, expects_gate):
    """Pins _requires_concurrency_limit: which methods acquire the semaphore."""
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust; gated methods must 503, bypassing methods succeed

    app = _make_simple_app([b"body"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    environ = {} if method is None else {"REQUEST_METHOD": method}
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = mw(environ, start_response)

    if expects_gate:
        assert captured["status"] == "503 Service Unavailable"
    else:
        assert captured["status"] == "200 OK"
        assert list(body) == [b"body"]

    sem.release()  # cleanup


def test_endpoint_level_short_circuits_middleware(mocker):
    """When CONCURRENCY_LEVEL == 'endpoint', the WSGI middleware passes through
    without acquiring the semaphore. The gate is enforced inside LlmApiService
    instead, allowing many requests to be in flight simultaneously.
    """
    mocker.patch(
        "Middleware.common.instance_global_variables.CONCURRENCY_LEVEL",
        "endpoint",
    )
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust; would block in wilmer mode

    app = _make_simple_app([b"passthrough"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    captured, body = _call_middleware(mw, method="POST")
    assert captured["status"] == "200 OK"
    assert list(body) == [b"passthrough"]

    # Semaphore was never touched by the middleware
    assert not sem.acquire(blocking=False)
    sem.release()


def test_wilmer_level_default_still_acquires_semaphore(mocker):
    """Explicit confirmation that the default CONCURRENCY_LEVEL ('wilmer')
    preserves the request-level gate semantics."""
    mocker.patch(
        "Middleware.common.instance_global_variables.CONCURRENCY_LEVEL",
        "wilmer",
    )
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust

    app = _make_simple_app([b"should not reach"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    captured, body = _call_middleware(mw, method="POST")
    assert captured["status"] == "503 Service Unavailable"

    sem.release()
