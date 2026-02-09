# /Middleware/llmapis/handlers/base/base_llm_api_handler.py

import logging
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

try:
    import eventlet
    EVENTLET_AVAILABLE = True
except ImportError:
    EVENTLET_AVAILABLE = False


from Middleware.services.cancellation_service import cancellation_service
from Middleware.utilities.config_utils import get_config_property_if_exists, get_connect_timeout

logger = logging.getLogger(__name__)


class LlmApiHandler(ABC):
    """
    Defines the abstract interface and shared HTTP logic for all LLM API handlers.

    Provides the core functionality for sending HTTP requests and processing responses
    in both streaming and non-streaming modes. Concrete subclasses must implement
    API-specific logic for payload creation and response parsing.
    """

    def __init__(self, base_url: str, api_key: str, gen_input: Dict[str, Any], model_name: str, headers: Dict[str, str],
                 stream: bool, api_type_config, endpoint_config, max_tokens, dont_include_model: bool = False):
        """
        Initializes the API handler and a persistent requests session.

        Args:
            base_url (str): The base URL of the LLM API.
            api_key (str): The API key for authentication.
            gen_input (Dict[str, Any]): Base generation parameters for the LLM.
            model_name (str): The name of the specific model to use.
            headers (Dict[str, str]): HTTP headers for the request.
            stream (bool): A flag indicating if streaming mode is enabled.
            api_type_config: Configuration object for the API type.
            endpoint_config: Configuration object for the specific endpoint.
            max_tokens: The maximum number of tokens to generate.
            dont_include_model (bool): If True, omits the model name from the payload.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.gen_input = gen_input
        self.model_name = model_name
        self.headers = headers
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.stream = stream
        self.endpoint_config = endpoint_config
        self.api_type_config = api_type_config
        self.max_tokens = max_tokens
        self.truncate_property_name = get_config_property_if_exists("truncateLengthPropertyName", api_type_config)
        self.stream_property_name = get_config_property_if_exists("streamPropertyName", api_type_config)
        self.max_token_property_name = get_config_property_if_exists("maxNewTokensPropertyName", api_type_config)
        self.dont_include_model = dont_include_model
        self.connect_timeout = get_connect_timeout()

    @abstractmethod
    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full URL for the target LLM API endpoint.

        Returns:
            str: The complete API endpoint URL.
        """
        raise NotImplementedError

    @abstractmethod
    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Creates the JSON payload for the LLM API request.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The conversational history.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            Dict: The formatted request payload as a dictionary.
        """
        raise NotImplementedError

    @abstractmethod
    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single data chunk from a streaming response.

        Args:
            data_str (str): A raw string chunk received from the stream.

        Returns:
            Optional[Dict[str, Any]]: A standardized dictionary containing the parsed
            data (e.g., token, finish_reason), or None if the chunk is empty.
        """
        raise NotImplementedError

    @abstractmethod
    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Parses the complete JSON response from a non-streaming API call.

        Args:
            response_json (Dict): The JSON response body as a dictionary.

        Returns:
            str: The extracted, complete generated text from the response.
        """
        raise NotImplementedError

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Determines the streaming protocol: line-delimited JSON vs. SSE.

        Returns:
            bool: True for line-delimited JSON, False for Server-Sent Events (SSE).
        """
        return False

    @property
    def _required_event_name(self) -> Optional[str]:
        """
        Specifies an event name to filter for in an SSE stream, if applicable.

        Returns:
            Optional[str]: The required event name, or None if no filter is needed.
        """
        return None

    def handle_streaming(self, conversation: Optional[List[Dict[str, str]]] = None, system_prompt: Optional[str] = None,
                         prompt: Optional[str] = None, request_id: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Manages a streaming request to the LLM API.
        When running under Eventlet, relies on monkey-patching for cooperative I/O.
        """
        payload = self._prepare_payload(conversation, system_prompt, prompt)
        logger.debug(f"Payload being sent to LLM API: {payload}")
        url = self._get_api_endpoint_url()

        # Check if already cancelled
        if request_id and cancellation_service.is_cancelled(request_id):
            logger.info(f"Request {request_id} was already cancelled before starting LLM request.")
            try:
                self.session.close()
            except Exception:
                pass
            return

        # Check if Eventlet is active for logging purposes
        is_eventlet_active = EVENTLET_AVAILABLE and eventlet.patcher.is_monkey_patched('socket')
        if is_eventlet_active:
            logger.info(f"Using Eventlet monkey-patched requests for streaming request_id: {request_id}")
        else:
            logger.info(f"Using standard synchronous streaming for request_id: {request_id}")

        # --- Abort Callback Setup ---
        response_to_abort = None

        def abort_callback():
            """Aggressively closes the HTTP session to interrupt the stream or prefill phase."""
            nonlocal response_to_abort
            logger.info(f"Abort callback triggered for request_id: {request_id}. Starting session close procedure.")

            # Primary Mechanism: Close the session aggressively.
            try:
                logger.info(f"Closing the entire session for request_id: {request_id}")
                self.session.adapters.clear()
                self.session.close()
                logger.info(f"Session closed successfully for request_id: {request_id}")
            except Exception as e:
                logger.error(f"Error closing session in abort callback for request_id {request_id}: {e}")

            # Secondary cleanup
            if response_to_abort is not None:
                try:
                    logger.debug(f"Closing response object for request_id: {request_id}")
                    response_to_abort.close()
                except Exception as e:
                    logger.debug(f"Error closing response object in abort callback: {e}")
                response_to_abort = None

        if request_id:
            logger.info(f"Registering abort callback for request_id: {request_id}")
            cancellation_service.register_abort_callback(request_id, abort_callback)

        # --- Streaming Logic ---
        # When Eventlet is active, session.post() is monkey-patched to be cooperative
        # The heartbeat mechanism in ollama_api_handler detects disconnects during prefill
        try:
            logger.info(f"Starting POST request for streaming request_id: {request_id}")
            # This call is cooperative when Eventlet is active (monkey-patched)
            with self.session.post(url, headers=self.headers, json=payload, stream=True, timeout=(self.connect_timeout, 14400)) as response:
                response_to_abort = response

                # Check for errors and capture the response body before raising
                if response.status_code >= 400:
                    error_body = response.text
                    logger.error(f"HTTP {response.status_code} error from {self.__class__.__name__}")
                    logger.error(f"Response body: {error_body}")
                    response.raise_for_status()

                logger.debug(f"Streaming response status code: {response.status_code} from {self.__class__.__name__}")
                response.encoding = "utf-8"

                current_event = None

                line_count = 0
                for line in response.iter_lines(decode_unicode=True):
                    # Check for cancellation before processing each line
                    if request_id and cancellation_service.is_cancelled(request_id):
                        logger.info(f"Request {request_id} cancelled. Stopping LLM stream.")
                        break

                    if is_eventlet_active and request_id and len(line.strip()) > 0:
                        line_count += 1
                        if line_count <= 3 or line_count % 20 == 0:
                            logger.debug(f"LLM handler received line #{line_count} ({len(line)} chars) for {request_id}")

                    # --- Line Processing Logic ---
                    if not line:
                        continue

                    line = line.strip()
                    data_str = None

                    if self._iterate_by_lines:
                        data_str = line
                    else:
                        # SSE parsing logic
                        if line.startswith("event:"):
                            try:
                                current_event = line.split(":", 1)[1].strip()
                            except IndexError:
                                pass
                            continue
                        if line.startswith("data:"):
                            if self._required_event_name and current_event != self._required_event_name:
                                continue
                            try:
                                data_str = line.split(":", 1)[1].strip()
                            except IndexError:
                                pass

                    if data_str is None or data_str == '[DONE]':
                        continue

                    processed_data = self._process_stream_data(data_str)
                    if processed_data:
                        yield processed_data
                        if processed_data.get("finish_reason"):
                            if is_eventlet_active:
                                logger.debug(f"LLM handler completed normally after {line_count} lines for {request_id}")
                            return

                if is_eventlet_active and line_count > 0:
                    logger.debug(f"LLM handler exited loop after {line_count} lines for {request_id}")

        # Catch exceptions that occur during the request
        except (requests.exceptions.RequestException, ConnectionError, OSError) as e:
            # Check if the error occurred because we cancelled the request
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Request {request_id} encountered expected error due to cancellation. Exiting gracefully. (Error: {type(e).__name__})")
                return
            else:
                # Genuine error - details already logged above if it was an HTTP error
                logger.error(f"Error during streaming: {e}")
                traceback.print_exc()
                raise e
        except Exception as e:
            logger.error(f"Unexpected error during streaming: {e}")
            traceback.print_exc()
            raise e
        finally:
            # Clean up the abort callback
            if request_id:
                cancellation_service.unregister_abort_callbacks(request_id)

    def handle_non_streaming(self, conversation: Optional[List[Dict[str, str]]] = None,
                             system_prompt: Optional[str] = None, prompt: Optional[str] = None,
                             request_id: Optional[str] = None) -> str:
        """
        Manages a non-streaming request to the LLM API to get a complete response.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            str: The complete, raw text generated by the LLM.
        """
        # Check if already cancelled before making the request
        if request_id and cancellation_service.is_cancelled(request_id):
            logger.info(f"Request {request_id} was already cancelled before starting LLM request.")
            try:
                self.session.close()
            except Exception:
                pass
            return ""

        payload = self._prepare_payload(conversation, system_prompt, prompt)
        url = self._get_api_endpoint_url()
        retries = 3

        for attempt in range(retries):
            # Check for cancellation before each retry
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Request {request_id} was cancelled before attempt {attempt + 1}.")
                return ""

            response_to_abort = None

            def abort_callback():
                """Aggressively closes the HTTP connection to interrupt the request."""
                nonlocal response_to_abort
                logger.info(f"Abort callback invoked (non-streaming) for request_id: {request_id}. Forcefully closing the session.")

                # Primary Mechanism: Close the session aggressively.
                try:
                    logger.info(f"Closing the entire session (non-streaming) for request_id: {request_id}")
                    # Clearing adapters forces urllib3 to dispose of the connection pool immediately.
                    self.session.adapters.clear()
                    self.session.close()
                    logger.info(f"Session closed successfully (non-streaming) for request_id: {request_id}")
                except Exception as e:
                    logger.error(f"Error closing session in abort callback (non-streaming): {e}")

                # Secondary cleanup: Close the specific response object if it exists.
                if response_to_abort is not None:
                    try:
                        logger.debug(f"Closing response object (non-streaming) for request_id: {request_id}")
                        response_to_abort.close()
                    except Exception as e:
                        logger.debug(f"Error closing response object in abort callback (non-streaming): {e}")
                    response_to_abort = None

            # Register the abort callback if we have a request_id
            if request_id:
                cancellation_service.register_abort_callback(request_id, abort_callback)

            try:
                # This call blocks. Closing the session will cause an exception here.
                response = self.session.post(url, headers=self.headers, json=payload, timeout=(self.connect_timeout, 14400))
                response_to_abort = response

                response.raise_for_status()
                response_json = response.json()
                result_text = self._parse_non_stream_response(response_json)

                logger.info("\n\n*****************************************************************************\n")
                logger.info("\n\nRaw output from the LLM: %s", result_text)
                logger.info("\n*****************************************************************************\n\n")

                return result_text or ""
            except (requests.exceptions.RequestException, ConnectionError, OSError) as e:
                # Check if this was due to cancellation (session closed by abort_callback)
                if request_id and cancellation_service.is_cancelled(request_id):
                    logger.info(f"Request {request_id} was cancelled during non-streaming request. Connection closed.")
                    # Cleanup handled in finally
                    return ""

                logger.error(
                    f"Attempt {attempt + 1} of {retries} for {self.__class__.__name__} failed: {e}")
                if attempt == retries - 1:
                    traceback.print_exc()
                    # Cleanup handled in finally
                    raise

            except Exception as e:
                logger.error(f"Unexpected error in {self.__class__.__name__}: {e}")
                traceback.print_exc()
                # Cleanup handled in finally
                raise
            finally:
                # Ensure cleanup happens after every attempt (success or failure)
                if request_id:
                    cancellation_service.unregister_abort_callbacks(request_id)

        return ""

    def set_gen_input(self):
        """
        Updates the generation parameters with values from configuration files.
        """
        if self.truncate_property_name:
            self.gen_input[self.truncate_property_name] = self.endpoint_config.get("maxContextTokenSize", None)
        if self.stream_property_name:
            self.gen_input[self.stream_property_name] = self.stream
        if self.max_token_property_name:
            self.gen_input[self.max_token_property_name] = self.max_tokens
            logger.debug(f"Added {self.max_token_property_name}={self.max_tokens} to gen_input")
        else:
            logger.warning(f"max_token_property_name is not set, max_tokens will not be included in payload")

    def close(self):
        """Closes the HTTP session to release keep-alive connections."""
        try:
            self.session.close()
        except Exception:
            pass
