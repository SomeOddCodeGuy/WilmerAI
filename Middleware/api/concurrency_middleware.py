import json
import logging

logger = logging.getLogger(__name__)

_503_BODY = json.dumps({
    "error": {
        "message": "Server busy, concurrency limit reached",
        "type": "server_error",
        "code": 503,
    }
}).encode("utf-8")

_503_HEADERS = [
    ("Content-Type", "application/json"),
    ("Content-Length", str(len(_503_BODY))),
]


class _SemaphoreReleasingIterator:
    """Wraps a WSGI response iterable and releases a semaphore exactly once
    when the response is fully consumed, closed, or errors out."""

    def __init__(self, iterable, semaphore):
        self._iterable = iter(iterable)
        self._semaphore = semaphore
        self._released = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._iterable)
        except BaseException:
            self._release()
            raise

    def close(self):
        self._release()
        close_fn = getattr(self._iterable, "close", None)
        if close_fn is not None:
            close_fn()

    def _release(self):
        if not self._released:
            self._released = True
            self._semaphore.release()


class ConcurrencyLimitMiddleware:
    """WSGI middleware that limits concurrent requests using a semaphore.

    The semaphore is held for the full response lifecycle, including streaming,
    because Flask's teardown_request fires before the WSGI server consumes the
    response iterator.
    """

    def __init__(self, app, semaphore, acquire_timeout=900):
        self._app = app
        self._semaphore = semaphore
        self._acquire_timeout = acquire_timeout

    def __call__(self, environ, start_response):
        acquired = self._semaphore.acquire(timeout=self._acquire_timeout)
        if not acquired:
            logger.warning(
                "Request rejected: concurrency limit reached "
                "(timed out after %ss)", self._acquire_timeout
            )
            start_response("503 Service Unavailable", _503_HEADERS)
            return [_503_BODY]

        try:
            response = self._app(environ, start_response)
        except BaseException:
            self._semaphore.release()
            raise

        return _SemaphoreReleasingIterator(response, self._semaphore)
