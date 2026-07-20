# /Middleware/llmapis/handlers/base/base_api_transport.py

import logging
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.services.cancellation_service import cancellation_service
from Middleware.utilities.config_utils import get_connect_timeout

logger = logging.getLogger(__name__)


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
        """Aggressively closes the HTTP session (and any attached response) to
        interrupt the stream or prefill phase."""
        logger.info(f"Abort callback triggered ({self._mode_label}) for request_id: "
                    f"{self._request_id}. Starting session close procedure.")

        try:
            logger.info(f"Closing the entire session ({self._mode_label}) for request_id: {self._request_id}")
            # Clearing adapters forces urllib3 to dispose of the connection pool immediately.
            self._session.adapters.clear()
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
            suppress_retries (bool): If True, disables urllib3 5xx retries and shrinks
                the manual non-streaming retry loop to a single attempt. Set by
                LlmApiService when a backup endpoint is configured so failover
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
        if suppress_retries:
            retries = Retry(total=0)
        else:
            retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.connect_timeout = get_connect_timeout()

    def execute_non_streaming_post(self, url: str, payload: Dict[str, Any],
                                   request_id: Optional[str] = None) -> Optional[Dict]:
        """
        Sends a non-streaming POST with the full retry/cancellation skeleton.

        Behavior (moved verbatim from the pre-refactor LlmApiHandler.handle_non_streaming):
        pre-flight cancellation check, bounded retry loop, abort-callback
        registration per attempt, cancellation-aware error interpretation (a
        session closed by abort reads as cancelled, not as an error), clean
        passthrough of KeyboardInterrupt/SystemExit/GeneratorExit, and
        finally-block unregistration of the abort callback.

        Args:
            url (str): The full API endpoint URL.
            payload (Dict[str, Any]): The JSON payload to send.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            Optional[Dict]: The parsed JSON response body, or None if the request
            was cancelled before or during execution.

        Raises:
            requests.exceptions.RequestException: If a non-cancellation network
                error occurs and all retries are exhausted.
        """
        if request_id and cancellation_service.is_cancelled(request_id):
            logger.info(f"Request {request_id} was already cancelled before starting API request.")
            try:
                self.session.close()
            except Exception:
                pass
            return None

        retries = 1 if self.suppress_retries else 3

        for attempt in range(retries):
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Request {request_id} was cancelled before attempt {attempt + 1}.")
                return None

            abort_handle = _AbortHandle(self.session, request_id, "non-streaming")

            if request_id:
                cancellation_service.register_abort_callback(request_id, abort_handle.abort)

            try:
                # This call blocks. Closing the session will cause an exception here.
                response = self.session.post(url, headers=self.headers, json=payload,
                                             timeout=(self.connect_timeout, self.read_timeout))
                abort_handle.response = response

                response.raise_for_status()
                return response.json()
            except (requests.exceptions.RequestException, ConnectionError, OSError) as e:
                # Check if this was due to cancellation (session closed by abort_callback)
                if request_id and cancellation_service.is_cancelled(request_id):
                    logger.info(f"Request {request_id} was cancelled during non-streaming request. Connection closed.")
                    # Cleanup handled in finally
                    return None

                is_final = attempt == retries - 1
                logger.error(
                    f"Attempt {attempt + 1} of {retries} for {self.__class__.__name__} failed: {e}",
                    exc_info=is_final)
                if is_final:
                    # Cleanup handled in finally
                    raise

            except Exception as e:
                logger.error(f"Unexpected error in {self.__class__.__name__}: {e}", exc_info=True)
                # Cleanup handled in finally
                raise
            except (KeyboardInterrupt, SystemExit, GeneratorExit):
                # Normal control-flow / teardown (Ctrl-C, process shutdown, eventlet
                # GreenletExit arrives as GeneratorExit): re-raise cleanly without logging
                # an error-level traceback for what is not an error.
                raise
            except BaseException as e:
                logger.error(f"BaseException in {self.__class__.__name__} (request_id={request_id}): "
                             f"{type(e).__name__}: {e}", exc_info=True)
                raise
            finally:
                if request_id:
                    cancellation_service.unregister_abort_callbacks(request_id)

        return None

    def close(self):
        """Closes the HTTP session to release keep-alive connections."""
        try:
            self.session.close()
        except Exception:
            pass
