# middleware/llmapis/handlers/base/base_llm_api_handler.py
import logging
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import (
    get_config_property_if_exists, get_current_username,
    get_is_chat_complete_add_user_assistant, get_is_chat_complete_add_missing_assistant
)
from Middleware.utilities.streaming_utils import StreamingThinkRemover, remove_thinking_from_text

logger = logging.getLogger(__name__)


class LlmApiHandler(ABC):
    """
    Abstract base class for handling interactions with a specific LLM API.

    This class provides a template for sending requests and processing responses,
    with concrete implementations provided by subclasses for different API types
    (e.g., OpenAI, Ollama). It supports both streaming and non-streaming modes.
    """

    def __init__(self, base_url: str, api_key: str, gen_input: Dict[str, Any], model_name: str, headers: Dict[str, str],
                 strip_start_stop_line_breaks: bool, stream: bool, api_type_config, endpoint_config, max_tokens,
                 dont_include_model: bool = False):
        """
        Initializes the LlmApiHandler.

        Args:
            base_url (str): The base URL for the LLM API endpoint.
            api_key (str): The API key for authentication.
            gen_input (Dict[str, Any]): A dictionary of generation parameters for the LLM.
            model_name (str): The name of the model to be used.
            headers (Dict[str, str]): HTTP headers to be sent with the request.
            strip_start_stop_line_breaks (bool): If True, strips leading/trailing line breaks from the response.
            stream (bool): If True, enables streaming mode.
            api_type_config: Configuration specific to the API type (e.g., 'openai', 'ollama').
            endpoint_config: Configuration specific to the particular endpoint being used.
            max_tokens: The maximum number of tokens to generate in the response.
            dont_include_model (bool): If True, the model name will not be included in the request payload.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.gen_input = gen_input
        self.model_name = model_name
        self.headers = headers
        self.strip_start_stop_line_breaks = strip_start_stop_line_breaks
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

    @abstractmethod
    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the request.

        This method must be implemented by subclasses to provide the specific
        URL path for the desired API action (e.g., '/v1/chat/completions').

        Returns:
            str: The complete URL for the API endpoint.
        """
        raise NotImplementedError

    @abstractmethod
    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the final data payload for the API request.

        This method must be implemented by subclasses to transform the generic
        conversation and prompt data into the specific JSON format required
        by the target LLM API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Returns:
            Dict: The JSON payload ready to be sent to the API.
        """
        raise NotImplementedError

    @abstractmethod
    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single chunk of data from a streaming response.

        This method must be implemented by subclasses to handle the specific
        format of streaming data from the target API (e.g., JSON objects,
        SSE data fields).

        Args:
            data_str (str): A string containing a single data chunk from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing the extracted 'token' and
            an optional 'finish_reason', or None if the chunk is empty or cannot be parsed.
        """
        raise NotImplementedError

    @abstractmethod
    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming API response.

        This method must be implemented by subclasses to navigate the JSON
        structure of a complete API response and extract the main content.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content.
        """
        raise NotImplementedError

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format. True for line-delimited JSON, False for standard SSE.
        """
        return False

    @property
    def _required_event_name(self) -> Optional[str]:
        """
        Specifies an SSE event name to filter for. If set, only data from matching events is processed.
        """
        return None

    def handle_streaming(self, conversation: Optional[List[Dict[str, str]]] = None, system_prompt: Optional[str] = None,
                         prompt: Optional[str] = None) -> Generator[str, None, None]:
        """
        Handles the streaming generation of responses from the LLM API.

        This generator function sends a request and then yields formatted chunks of the
        response as they are received. It adapts its parsing logic based on the
        `_iterate_by_lines` property to handle both standard Server-Sent Events (SSE)
        and line-delimited JSON objects.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Yields:
            Generator[str, None, None]: Server-Sent Event (SSE) formatted strings suitable for
            streaming to a client.
        """
        payload = self._prepare_payload(conversation, system_prompt, prompt)
        url = self._get_api_endpoint_url()
        output_format = instance_utils.API_TYPE
        remover = StreamingThinkRemover(self.endpoint_config)
        start_time = time.time()
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        try:
            with self.session.post(url, headers=self.headers, json=payload, stream=True) as r:
                r.raise_for_status()
                logger.info(f"Streaming response status code: {r.status_code} from {self.__class__.__name__}")
                r.encoding = "utf-8"

                first_chunk_buffer = ""
                first_chunk_processed = False
                max_buffer_length = 20
                current_event = None

                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue

                    line = line.strip()
                    data_str = None

                    if self._iterate_by_lines:
                        data_str = line
                    else:
                        if line.startswith("event:"):
                            current_event = line.split(":", 1)[1].strip()
                            continue

                        if line.startswith("data:"):
                            if self._required_event_name and current_event != self._required_event_name:
                                continue
                            data_str = line.split(":", 1)[1].strip()

                    if data_str is None:
                        continue

                    if data_str == '[DONE]':
                        break

                    processed_data = self._process_stream_data(data_str)
                    if not processed_data:
                        continue

                    content_delta = processed_data.get("token", "")
                    finish_reason = processed_data.get("finish_reason")
                    content_to_yield = remover.process_delta(content_delta)

                    if content_to_yield:
                        final_content_for_this_chunk = None
                        if not first_chunk_processed:
                            first_chunk_buffer += content_to_yield

                            if self.strip_start_stop_line_breaks:
                                first_chunk_buffer = first_chunk_buffer.lstrip()

                            condition_to_process = len(first_chunk_buffer) > max_buffer_length or finish_reason

                            if add_user_assistant and add_missing_assistant and "Assistant:" in first_chunk_buffer:
                                first_chunk_buffer = api_utils.remove_assistant_prefix(first_chunk_buffer)
                                first_chunk_processed = True
                                final_content_for_this_chunk = first_chunk_buffer
                            elif condition_to_process:
                                first_chunk_processed = True
                                final_content_for_this_chunk = first_chunk_buffer
                        else:
                            final_content_for_this_chunk = content_to_yield

                        if final_content_for_this_chunk is not None:
                            completion_json = api_utils.build_response_json(
                                token=final_content_for_this_chunk,
                                finish_reason=None,
                                current_username=get_current_username()
                            )
                            yield api_utils.sse_format(completion_json, output_format)

                    if finish_reason == 'stop':
                        break

                final_content = remover.finalize()
                if final_content:
                    content = (
                            first_chunk_buffer + final_content).lstrip() if not first_chunk_processed else final_content
                    completion_json = api_utils.build_response_json(token=content, finish_reason=None,
                                                                    current_username=get_current_username())
                    yield api_utils.sse_format(completion_json, output_format)

                final_completion_json = api_utils.build_response_json(token="", finish_reason="stop",
                                                                      current_username=get_current_username())
                yield api_utils.sse_format(final_completion_json, output_format)

                if output_format not in ('ollamagenerate', 'ollamaapichat'):
                    yield api_utils.sse_format("[DONE]", output_format)

        except requests.RequestException as e:
            logger.error(f"Request failed in {self.__class__.__name__}: {e}")
            traceback.print_exc()
            raise

    def handle_non_streaming(self, conversation: Optional[List[Dict[str, str]]] = None,
                             system_prompt: Optional[str] = None, prompt: Optional[str] = None) -> str:
        """
        Handles the non-streaming generation of a complete response from the LLM API.

        This function sends a request and waits for the full response before parsing it.
        It includes retry logic for transient network errors.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Returns:
            str: The complete, post-processed text response from the LLM.

        Raises:
            requests.exceptions.RequestException: If the request fails after all retries.
        """
        payload = self._prepare_payload(conversation, system_prompt, prompt)
        url = self._get_api_endpoint_url()
        retries = 3
        for attempt in range(retries):
            try:
                response = self.session.post(url, headers=self.headers, json=payload, timeout=14400)
                response.raise_for_status()
                response_json = response.json()
                result_text = self._parse_non_stream_response(response_json)

                if not result_text:
                    return ""

                result_text = remove_thinking_from_text(result_text, self.endpoint_config)
                if self.strip_start_stop_line_breaks:
                    result_text = result_text.lstrip()
                if "Assistant:" in result_text:
                    result_text = api_utils.remove_assistant_prefix(result_text)

                logger.info("\n\n*****************************************************************************\n")
                logger.info("\n\nOutput from the LLM: %s", result_text)
                logger.info("\n*****************************************************************************\n\n")

                return result_text
            except requests.exceptions.RequestException as e:
                logger.error(f"Attempt {attempt + 1} for {self.__class__.__name__} failed: {e}")
                if attempt == retries - 1:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error in {self.__class__.__name__}: {e}")
                traceback.print_exc()
                raise
        return ""

    def set_gen_input(self):
        """
        Updates the generation input dictionary with dynamic, configuration-based values.

        This method populates keys in the `self.gen_input` dictionary (which is used in
        the payload) based on property names defined in the endpoint configuration.
        This allows for dynamically setting parameters like `max_tokens` or `stream`.
        """
        if self.truncate_property_name:
            self.gen_input[self.truncate_property_name] = self.endpoint_config.get("maxContextTokenSize", None)
        if self.stream_property_name:
            self.gen_input[self.stream_property_name] = self.stream
        if self.max_token_property_name:
            self.gen_input[self.max_token_property_name] = self.max_tokens