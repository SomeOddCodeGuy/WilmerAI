# /Middleware/llmapis/handlers/base/base_api_transport.py

import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from urllib3.exceptions import MaxRetryError, NewConnectionError

from Middleware.exceptions.invalid_llm_response_error import InvalidLlmResponseError
from Middleware.services.cancellation_service import cancellation_service
from Middleware.utilities.config_utils import get_connect_timeout
from Middleware.utilities.redirect_policy import protect_session_redirects

from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)


class _AbortHandle:
    """Cancellation state shared between a request and the CancellationService.

    The abort() method is registered with the CancellationService and may run on
    a different greenlet/thread at any time. The request code attaches the
    in-flight response once the POST returns so abort() can close that too.
    """

    def __init__(self, session: requests.Session, request_id: Optional[str], mode_label: str):
        """
        Args:
            session (requests.Session): The session to close on abort.
            request_id (Optional[str]): The request ID, used in log messages.
            mode_label (str): "streaming" or "non-streaming", used in log messages.
        """
        self._session = session
        self._request_id = request_id
        self._mode_label = mode_label
        self.response = None

    def abort(self) -> None:
        """Close owned pools and any attached response during cancellation.

        Session closure alone does not guarantee interruption before a response
        is attached; transport timeouts still bound that blocking operation.
        """
        logger.info(f"Abort callback triggered ({self._mode_label}) for request_id: "
                    f"{self._request_id}. Starting session close procedure.")

        try:
            logger.info(f"Closing the entire session ({self._mode_label}) for request_id: {self._request_id}")
            self._session.close()
            logger.info(f"Session closed successfully ({self._mode_label}) for request_id: {self._request_id}")
        except Exception as e:
            logger.error(f"Error closing session in abort callback ({self._mode_label}) "
                         f"for request_id {self._request_id}: {e}")

        if self.response is not None:
            try:
                logger.debug(f"Closing response object ({self._mode_label}) for request_id: {self._request_id}")
                self.response.close()
            except Exception as e:
                logger.debug(f"Error closing response object in abort callback ({self._mode_label}): {e}")
            self.response = None


class BaseApiTransport:
    """
    Shared HTTP transport for API handlers: session lifecycle, retry policy,
    timeouts, and the cancellation-aware non-streaming POST skeleton.

    Holds no generation-specific state. LlmApiHandler layers streaming and
    payload/prompt concerns on top of this; EmbeddingApiHandler uses it as-is.
    """

    def __init__(self, base_url: str, api_key: str, headers: Dict[str, str],
                 suppress_retries: bool = False, read_timeout: int = 14400):
        """
        Initializes the transport state and a persistent requests session.

        Args:
            base_url (str): The base URL of the target API.
            api_key (str): The API key for authentication.
            headers (Dict[str, str]): HTTP headers for requests.
            suppress_retries (bool): If True, limits the shared POST policy to
                a single attempt. Set by LlmApiService when a backup is configured so failover
                happens on first failure.
            read_timeout (int): Per-request read timeout in seconds. The default
                accommodates multi-hour LLM generations; short-turnaround callers
                (embeddings) pass a smaller value so a wedged server cannot stall
                a workflow node for hours.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.headers = headers
        self.suppress_retries = suppress_retries
        self.read_timeout = read_timeout
        self.session = requests.Session()
        protect_session_redirects(self.session)
        # One application retry budget prevents adapter retries multiplying attempts.
        retries = Retry(total=0)
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.connect_timeout = get_connect_timeout()

    @staticmethod
    def _is_retryable_failure(error: requests.exceptions.RequestException) -> bool:
        """Identify failures eligible for another POST to the same endpoint.

        Args:
            error (requests.exceptions.RequestException): The failed POST's error.

        Returns:
            bool: True for connection establishment failures or selected 5xx statuses.
        """
        if isinstance(error, requests.exceptions.HTTPError):
            return error.response is not None and error.response.status_code in (500, 502, 503, 504)
        if isinstance(error, requests.exceptions.ConnectTimeout):
            return True
        if isinstance(error, requests.exceptions.ConnectionError):
            reason = error.args[0] if error.args else None
            if isinstance(reason, MaxRetryError):
                reason = reason.reason
            # A generic ConnectionError can also mean the POST was already sent.
            return isinstance(reason, NewConnectionError)
        return False

    @staticmethod
    def _wait_before_retry(attempt: int, request_id: Optional[str]) -> bool:
        """Wait briefly between attempts, polling cancellation during backoff.

        Args:
            attempt (int): Zero-based index of the failed attempt.
            request_id (Optional[str]): Request cancellation identifier.

        Returns:
            bool: False if cancelled; True when the backoff has elapsed.
        """
        deadline = time.monotonic() + 0.25 * (2 ** attempt)
        while True:
            if request_id and cancellation_service.is_cancelled(request_id):
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.05, remaining))

    def _post_with_retries(self, url: str, payload: Dict[str, Any], abort_handle: _AbortHandle,
                           request_id: Optional[str], stream: bool = False) -> Optional[requests.Response]:
        """Open a POST response under the single shared retry budget.

        Response decoding and stream iteration happen after this method returns,
        so neither can replay a submitted generation through this retry loop.

        Args:
            url (str): Destination URL.
            payload (Dict[str, Any]): Prepared JSON request body.
            abort_handle (_AbortHandle): Registered cancellation handle owned by the caller.
            request_id (Optional[str]): Request cancellation identifier.
            stream (bool): Whether to leave the response body for streaming iteration.

        Returns:
            Optional[requests.Response]: Successful response, owned by the caller,
                or None on cancellation. Failed responses are closed here.

        Raises:
            requests.exceptions.RequestException: On a non-retryable failure or exhaustion.
        """
        attempts = 1 if self.suppress_retries else 3
        for attempt in range(attempts):
            if request_id and cancellation_service.is_cancelled(request_id):
                return None
            response = None
            try:
                response = self.session.post(
                    url, headers=self.headers, json=payload,
                    timeout=(self.connect_timeout, self.read_timeout),
                    **({"stream": True} if stream else {}))
                abort_handle.response = response
                response.raise_for_status()
            except requests.exceptions.RequestException as error:
                if response is not None:
                    response.close()
                    abort_handle.response = None
                if request_id and cancellation_service.is_cancelled(request_id):
                    return None
                if attempt == attempts - 1 or not self._is_retryable_failure(error):
                    raise
                logger.warning("Retrying %s after %s (attempt %d of %d).",
                               self.__class__.__name__, type(error).__name__, attempt + 1, attempts)
                if not self._wait_before_retry(attempt, request_id):
                    return None
            else:
                if request_id and cancellation_service.is_cancelled(request_id):
                    response.close()
                    abort_handle.response = None
                    return None
                return response
        return None

    def execute_non_streaming_post(self, url: str, payload: Dict[str, Any],
                                   request_id: Optional[str] = None) -> Optional[Dict]:
        """
        Sends a non-streaming POST with the full retry/cancellation skeleton.

        Registers cancellation across connection attempts and backoff, delegates
        HTTP retries to _post_with_retries, and decodes JSON once. Invalid JSON
        propagates without repeating the POST. Responses and callbacks are cleaned
        on success, failure, cancellation, and generator/process teardown.

        Args:
            url (str): The full API endpoint URL.
            payload (Dict[str, Any]): The JSON payload to send.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            Optional[Dict]: The parsed JSON response body, or None if the request
            was cancelled before or during execution.

        Raises:
            requests.exceptions.RequestException: If a non-cancellation network
                error is non-retryable or retries are exhausted, or JSON decoding fails.
            InvalidLlmResponseError: If the body is JSON null, which would otherwise
                be confused with cancellation.
        """
        if request_id and cancellation_service.is_cancelled(request_id):
            logger.info(f"Request {request_id} was already cancelled before starting API request.")
            try:
                self.session.close()
            except Exception:
                pass
            return None

        abort_handle = _AbortHandle(self.session, request_id, "non-streaming")
        if request_id:
            cancellation_service.register_abort_callback(request_id, abort_handle.abort)
        try:
            response = self._post_with_retries(url, payload, abort_handle, request_id)
            if response is None:
                return None
            result = response.json()
            if result is None:
                # None is reserved for cancellation by generation and embedding callers.
                raise InvalidLlmResponseError("API response body must not be JSON null.")
            return result
        except (requests.exceptions.RequestException, ConnectionError, OSError):
            if request_id and cancellation_service.is_cancelled(request_id):
                return None
            logger.error("Non-streaming request failed in %s.", self.__class__.__name__, exc_info=True)
            raise
        except Exception:
            logger.error("Unexpected error in %s.", self.__class__.__name__, exc_info=True)
            raise
        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except BaseException:
            logger.error("BaseException in %s (request_id=%s).",
                         self.__class__.__name__, request_id, exc_info=True)
            raise
        finally:
            try:
                response = abort_handle.response
                abort_handle.response = None
                if response is not None:
                    response.close()
            finally:
                if request_id:
                    cancellation_service.unregister_abort_callbacks(request_id)

    def close(self):
        """Closes the HTTP session to release keep-alive connections."""
        try:
            self.session.close()
        except Exception:
            pass
