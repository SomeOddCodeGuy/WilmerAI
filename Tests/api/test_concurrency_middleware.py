import json
import threading
from unittest.mock import MagicMock

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

    # Read first chunk — semaphore still held
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

    try:
        _call_middleware(mw)
    except RuntimeError:
        pass

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

    try:
        next(body)
    except ValueError:
        pass

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

    # Give t3 a moment — it should NOT have entered the app
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

    sem.release()  # cleanup


def test_no_middleware_when_semaphore_is_none(mocker):
    """When get_request_semaphore returns None, wsgi_app is not wrapped."""
    mocker.patch(
        "Middleware.common.instance_global_variables.get_request_semaphore",
        return_value=None,
    )

    from Middleware.api.api_server import ApiServer
    mocker.patch.object(ApiServer, "_discover_and_register_handlers")

    mock_app = MagicMock()
    original_wsgi_app = mock_app.wsgi_app

    server = ApiServer(app_instance=mock_app)

    # wsgi_app should be unchanged
    assert mock_app.wsgi_app is original_wsgi_app


def test_get_request_bypasses_semaphore():
    """GET requests (model lists, version) should pass through without acquiring the semaphore."""
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust the semaphore

    app = _make_simple_app([b"models response"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    # A POST would block and 503, but a GET should pass straight through
    captured, body = _call_middleware(mw, method="GET")
    assert captured["status"] == "200 OK"
    assert list(body) == [b"models response"]

    sem.release()  # cleanup


def test_delete_request_bypasses_semaphore():
    """DELETE requests (cancellation) should pass through without acquiring the semaphore."""
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust the semaphore

    app = _make_simple_app([b"cancelled"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    captured, body = _call_middleware(mw, method="DELETE")
    assert captured["status"] == "200 OK"
    assert list(body) == [b"cancelled"]

    sem.release()  # cleanup


def test_post_request_still_acquires_semaphore():
    """POST requests must still go through the semaphore."""
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # exhaust the semaphore

    app = _make_simple_app([b"should not reach"])
    mw = ConcurrencyLimitMiddleware(app, sem, acquire_timeout=0.1)

    captured, body = _call_middleware(mw, method="POST")
    assert captured["status"] == "503 Service Unavailable"

    sem.release()  # cleanup
