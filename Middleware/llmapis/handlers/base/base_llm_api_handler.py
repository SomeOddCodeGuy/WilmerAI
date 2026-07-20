# /Middleware/llmapis/handlers/base/base_llm_api_handler.py

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional, Union

import requests

try:
    import eventlet
    EVENTLET_AVAILABLE = True
except ImportError:
    EVENTLET_AVAILABLE = False


from Middleware.llmapis.handlers.base.base_api_transport import BaseApiTransport, _AbortHandle
from Middleware.llmapis.sampler_translation import normalize_gen_input
from Middleware.services.cancellation_service import cancellation_service
from Middleware.utilities.config_utils import get_config_property_if_exists
from Middleware.utilities.sensitive_logging_utils import sensitive_log, log_prompt_content
from Middleware.utilities.structured_output_utils import get_structured_output_config

logger = logging.getLogger(__name__)


class LlmApiHandler(BaseApiTransport, ABC):
    """
    Defines the abstract interface and shared generation logic for all LLM API handlers.

    Inherits HTTP transport concerns (session lifecycle, retry policy, timeouts,
    and the cancellation-aware non-streaming POST skeleton) from BaseApiTransport,
    and layers generation-specific behavior on top: streaming, prompt/payload
    preparation, and sampler injection. Concrete subclasses must implement
    API-specific logic for payload creation and response parsing.
    """

    def __init__(self, base_url: str, api_key: str, gen_input: Dict[str, Any], model_name: str, headers: Dict[str, str],
                 stream: bool, api_type_config, endpoint_config, max_tokens, dont_include_model: bool = False,
                 suppress_retries: bool = False):
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
            suppress_retries (bool): If True, disables urllib3 5xx retries and shrinks the
                manual non-streaming retry loop to a single attempt. Set by LlmApiService
                when a backup endpoint is configured so failover happens on first failure.
        """
        super().__init__(base_url=base_url, api_key=api_key, headers=headers,
                         suppress_retries=suppress_retries)
        self.gen_input = gen_input
        self.model_name = model_name
        self.stream = stream
        self.endpoint_config = endpoint_config
        self.api_type_config = api_type_config
        self.max_tokens = max_tokens
        self.truncate_property_name = get_config_property_if_exists("truncateLengthPropertyName", api_type_config)
        self.stream_property_name = get_config_property_if_exists("streamPropertyName", api_type_config)
        self.max_token_property_name = get_config_property_if_exists("maxNewTokensPropertyName", api_type_config)
        self.dont_include_model = dont_include_model

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
                         prompt: Optional[str], *, tools: Optional[List[Dict]] = None,
                         tool_choice: Optional[Any] = None,
                         structured_output_schema: Optional[Dict] = None) -> Dict:
        """
        Creates the JSON payload for the LLM API request.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The conversational history.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt.
            tools (Optional[List[Dict]]): Tool definitions in OpenAI format.
            tool_choice (Optional[Any]): Tool selection policy.
            structured_output_schema (Optional[Dict]): JSON schema to constrain
                the response with, when the API type supports it.

        Returns:
            Dict: The formatted request payload as a dictionary.
        """
        raise NotImplementedError

    def _attach_structured_output(self, payload: Dict, structured_output_schema: Optional[Dict]) -> None:
        """
        Attaches a structured-output constraint to a payload, per the API type.

        The ApiType's "structuredOutput" block is declarative (like "thinking"
        and "samplerFieldMap"): "field" names the payload key the schema is
        written to, dotted for nesting (e.g. "structured_outputs.json"),
        and "style" names the wrapper shape ("openaiJsonSchema" or "raw").
        When the API type declares no valid block the payload is left unchanged
        and a warning is logged; callers must not assume the response will be
        constrained (and should post-parse-check it regardless: some backends
        accept a constraint field and silently fail to enforce it).

        Args:
            payload (Dict): The request payload to mutate.
            structured_output_schema (Optional[Dict]): The JSON schema, or None
                to do nothing.
        """
        if not structured_output_schema:
            return
        so_config = get_structured_output_config(self.api_type_config)
        if not so_config:
            logger.warning(
                "Structured output was requested but this endpoint's API type "
                "declares no valid structuredOutput block; sending the request "
                "unconstrained.")
            return
        if so_config["style"] == "openaiJsonSchema":
            value = {
                "type": "json_schema",
                "json_schema": {
                    "name": "wilmer_structured_output",
                    "strict": so_config["strict"],
                    "schema": structured_output_schema,
                },
            }
        else:  # "raw"
            value = structured_output_schema
        target = payload
        *parents, leaf = so_config["field"].split(".")
        for key in parents:
            nxt = target.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                target[key] = nxt
            target = nxt
        if leaf in target:
            logger.warning(
                "Structured output is overwriting the existing payload field '%s' "
                "(preset- or sampler-supplied); the schema constraint wins.",
                so_config["field"])
        target[leaf] = value

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
    def _parse_non_stream_response(self, response_json: Dict) -> Union[str, Dict[str, Any]]:
        """
        Parses the complete JSON response from a non-streaming API call.

        Args:
            response_json (Dict): The JSON response body as a dictionary.

        Returns:
            Union[str, Dict[str, Any]]: The extracted generated text as a string,
            or a dictionary containing 'content', 'tool_calls', and 'finish_reason'
            keys when the response includes tool calls.
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
                         prompt: Optional[str] = None, request_id: Optional[str] = None,
                         tools: Optional[List[Dict]] = None,
                         tool_choice: Optional[Any] = None,
                         structured_output_schema: Optional[Dict] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Manages a streaming request to the LLM API.

        Sends the prepared payload and iterates over the response, yielding standardized
        token dictionaries as they arrive. Supports cancellation via the abort callback
        registered with the CancellationService. When running under Eventlet, the
        underlying socket I/O is cooperative via monkey-patching.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The conversation history.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt.
            request_id (Optional[str]): The request ID for cancellation tracking.
            tools (Optional[List[Dict]]): Tool definitions in OpenAI format.
            tool_choice (Optional[Any]): Tool selection policy.

        Yields:
            Dict[str, Any]: Standardized token dictionaries with 'token' and
                'finish_reason' keys, as returned by `_process_stream_data`.

        Raises:
            requests.exceptions.RequestException: If a non-cancellation network error
                occurs and all retries are exhausted.
        """
        payload = self._prepare_payload(conversation, system_prompt, prompt, tools=tools, tool_choice=tool_choice,
                                        structured_output_schema=structured_output_schema)
        sensitive_log(logger, logging.DEBUG, "Payload being sent to LLM API: %s", payload)
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
        abort_handle = _AbortHandle(self.session, request_id, "streaming")

        if request_id:
            logger.info(f"Registering abort callback for request_id: {request_id}")
            cancellation_service.register_abort_callback(request_id, abort_handle.abort)

        # --- Streaming Logic ---
        # When Eventlet is active, session.post() is monkey-patched to be cooperative
        # The heartbeat mechanism in ollama_api_handler detects disconnects during prefill
        try:
            logger.info(f"Starting POST request for streaming request_id: {request_id}")
            # This call is cooperative when Eventlet is active (monkey-patched)
            with self.session.post(url, headers=self.headers, json=payload, stream=True, timeout=(self.connect_timeout, 14400)) as response:
                abort_handle.response = response

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
                        # SSE parsing. startswith guarantees the ":" separator, so
                        # split(":", 1)[1] cannot raise.
                        if line.startswith("event:"):
                            current_event = line.split(":", 1)[1].strip()
                            continue
                        if line.startswith("data:"):
                            if self._required_event_name and current_event != self._required_event_name:
                                continue
                            data_str = line.split(":", 1)[1].strip()

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
                # Genuine error; details already logged above if it was an HTTP error
                logger.error(f"Error during streaming: {e}", exc_info=True)
                raise
        except Exception as e:
            logger.error(f"Unexpected error during streaming: {e}", exc_info=True)
            raise
        finally:
            # Clean up the abort callback
            if request_id:
                cancellation_service.unregister_abort_callbacks(request_id)

    def handle_non_streaming(self, conversation: Optional[List[Dict[str, str]]] = None,
                             system_prompt: Optional[str] = None, prompt: Optional[str] = None,
                             request_id: Optional[str] = None,
                             tools: Optional[List[Dict]] = None,
                             tool_choice: Optional[Any] = None,
                             structured_output_schema: Optional[Dict] = None) -> Union[str, Dict[str, Any]]:
        """
        Manages a non-streaming request to the LLM API to get a complete response.

        The HTTP transport (retry loop, cancellation handling, abort callbacks)
        is delegated to BaseApiTransport.execute_non_streaming_post; this method
        contributes the generation-specific payload preparation and response
        parsing around it.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.
            request_id (Optional[str]): The request ID for cancellation tracking.
            tools (Optional[List[Dict]]): Tool definitions in OpenAI format.
            tool_choice (Optional[Any]): Tool selection policy.

        Returns:
            Union[str, Dict[str, Any]]: The complete, raw text generated by the LLM,
            or a dictionary with 'content', 'tool_calls', and 'finish_reason' keys
            when the response includes tool calls.
        """
        # Check if already cancelled before making the request. The transport
        # repeats this check, but doing it here first avoids preparing a payload
        # for a request that will never be sent.
        if request_id and cancellation_service.is_cancelled(request_id):
            logger.info(f"Request {request_id} was already cancelled before starting LLM request.")
            try:
                self.session.close()
            except Exception:
                pass
            return ""

        payload = self._prepare_payload(conversation, system_prompt, prompt, tools=tools, tool_choice=tool_choice,
                                        structured_output_schema=structured_output_schema)
        url = self._get_api_endpoint_url()

        response_json = self.execute_non_streaming_post(url, payload, request_id=request_id)
        if response_json is None:
            # The request was cancelled before or during execution.
            return ""

        try:
            result = self._parse_non_stream_response(response_json)
        except Exception as e:
            logger.error(f"Unexpected error in {self.__class__.__name__}: {e}", exc_info=True)
            raise

        if isinstance(result, dict):
            log_prompt_content(logger, "Raw output from the LLM", result.get('content', ''))
            return result
        log_prompt_content(logger, "Raw output from the LLM", result)
        return result or ""

    def set_gen_input(self):
        """
        Injects the structurally-managed generation fields, then normalizes.

        `stream` is always set, since whether the request streams is a transport
        decision rather than a user-tunable value. The max-tokens and
        context-truncation fields are injected from the node/endpoint, but an
        explicit `null` already present for either (for example from an
        append-preset override) is honored as a request to omit that field rather
        than overwritten. Context truncation is only injected when the endpoint
        actually defines `maxContextTokenSize`; this also avoids the prior behavior
        of leaking a `null` into the payload when it was absent. Finally the whole
        gen_input is normalized so omitted (`null`) keys are dropped and the
        literal-null sentinel is resolved.
        """
        if self.stream_property_name:
            self.gen_input[self.stream_property_name] = self.stream

        if self.truncate_property_name:
            explicitly_omitted = (self.truncate_property_name in self.gen_input
                                  and self.gen_input[self.truncate_property_name] is None)
            max_context = self.endpoint_config.get("maxContextTokenSize", None)
            if not explicitly_omitted and max_context is not None:
                self.gen_input[self.truncate_property_name] = max_context

        if self.max_token_property_name:
            explicitly_omitted = (self.max_token_property_name in self.gen_input
                                  and self.gen_input[self.max_token_property_name] is None)
            if explicitly_omitted:
                logger.debug(f"{self.max_token_property_name} omitted by explicit null in preset; not injecting.")
            else:
                self.gen_input[self.max_token_property_name] = self.max_tokens
                logger.debug(f"Added {self.max_token_property_name}={self.max_tokens} to gen_input")
        else:
            logger.warning("max_token_property_name is not set, max_tokens will not be included in payload")

        self.gen_input = normalize_gen_input(self.gen_input)
