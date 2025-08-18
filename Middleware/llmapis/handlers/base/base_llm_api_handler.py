# /Middleware/llmapis/handlers/base/base_llm_api_handler.py

import logging
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.utilities.config_utils import get_config_property_if_exists

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
                         prompt: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Manages a streaming request to the LLM API and yields parsed data chunks.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Yields:
            Dict[str, Any]: A dictionary containing the raw parsed data, typically
            in the format {'token': str, 'finish_reason': str|None}.
        """
        payload = self._prepare_payload(conversation, system_prompt, prompt)
        url = self._get_api_endpoint_url()

        try:
            with self.session.post(url, headers=self.headers, json=payload, stream=True, timeout=14400) as r:
                r.raise_for_status()
                logger.info(f"Streaming response status code: {r.status_code} from {self.__class__.__name__}")
                r.encoding = "utf-8"
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

                    if data_str is None or data_str == '[DONE]':
                        continue

                    processed_data = self._process_stream_data(data_str)
                    if processed_data:
                        yield processed_data
                        if processed_data.get("finish_reason"):
                            return

        except requests.RequestException as e:
            logger.error(f"Request failed in {self.__class__.__name__}: {e}")
            traceback.print_exc()
            raise

    def handle_non_streaming(self, conversation: Optional[List[Dict[str, str]]] = None,
                             system_prompt: Optional[str] = None, prompt: Optional[str] = None) -> str:
        """
        Manages a non-streaming request to the LLM API to get a complete response.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Returns:
            str: The complete, raw text generated by the LLM.
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

                logger.info("\n\n*****************************************************************************\n")
                logger.info("\n\nRaw output from the LLM: %s", result_text)
                logger.info("\n*****************************************************************************\n\n")

                return result_text or ""
            except requests.exceptions.RequestException as e:
                logger.error(
                    f"Attempt {attempt + 1} of {retries} for {self.__class__.__name__} failed: {e}")
                if attempt == retries - 1:
                    traceback.print_exc()
                    raise
            except Exception as e:
                logger.error(f"Unexpected error in {self.__class__.__name__}: {e}")
                traceback.print_exc()
                raise
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
