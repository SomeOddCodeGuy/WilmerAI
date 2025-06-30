from typing import Any, Dict, Generator, List, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.utilities.config_utils import get_config_property_if_exists


class LlmApiHandler:
    """
    Base class for handling specific LLM API interactions.
    """

    def __init__(
            self,
            base_url: str,
            api_key: str,
            gen_input: Dict[str, Any],
            model_name: str,
            headers: Dict[str, str],
            strip_start_stop_line_breaks: bool,
            stream: bool,
            api_type_config,
            endpoint_config,
            max_tokens,
            dont_include_model: bool = False,
    ):
        """
        Initialize the handler with common API configuration.

        Args:
            base_url (str): The base URL of the API.
            api_key (str): The API key.
            gen_input (Dict[str, Any]): The generation input parameters.
            model_name (str): The model name to use.
            headers (Dict[str, str]): The headers to use for requests.
            strip_start_stop_line_breaks (bool): Whether to strip line breaks at start and end.
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

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Union[Generator[str, None, None], str]:
        """
        Handle streaming responses (to be implemented by subclasses).

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            Union[Generator[str, None, None], str]: A generator yielding chunks of the response if streaming, otherwise the complete response.
        """
        raise NotImplementedError

    def handle_non_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Union[str, Dict[str, Any]]:
        """
        Handle non-streaming responses (to be implemented by subclasses).

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            Union[str, Dict[str, Any]]: The complete response as a string or dictionary.
        """
        raise NotImplementedError
