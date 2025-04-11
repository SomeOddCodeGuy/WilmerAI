import json
import logging
import os
import traceback
import requests
from copy import deepcopy
from typing import Dict, Generator, List, Optional, Union

from Middleware.utilities.config_utils import (
    get_openai_preset_path,
    get_endpoint_config,
    get_api_type_config,
)
from .koboldcpp_api_handler import KoboldCppApiHandler
from .llm_api_handler import LlmApiHandler
from .ollama_chat_api_handler import OllamaChatHandler
from .ollama_chat_api_image_specific_handler import OllamaApiChatImageSpecificHandler
from .ollama_generate_api_handler import OllamaGenerateHandler
from .openai_api_handler import OpenAiApiHandler
from .openai_chat_api_image_specific_handler import OpenAIApiChatImageSpecificHandler
from .openai_completions_api_handler import OpenAiCompletionsApiHandler

logger = logging.getLogger(__name__)


class LlmApiService:
    """
    A generic service class for interacting with multiple LLM backends.
    """

    def __init__(self, endpoint: str, presetname: str, max_tokens: int, stream: bool = False):
        """
        Initialize the LlmApiService with common configuration.

        Args:
            endpoint (str): The API endpoint name (key to look up in config).
            presetname (str): The name of the preset file containing API parameters.
            max_tokens (int): The max number of tokens to generate.
            stream (bool): Whether to use streaming or not.
            llm_type (str): The LLM type to use.
        """
        self.max_tokens = max_tokens
        self.endpoint_file = get_endpoint_config(endpoint)
        self.api_type_config = get_api_type_config(self.endpoint_file.get("apiTypeConfigFileName", ""))
        llm_type = self.api_type_config["type"]
        preset_type = self.api_type_config.get("presetType", "")
        preset_file = get_openai_preset_path(presetname, preset_type, True)
        logger.info("Loading preset at {}".format(preset_file))

        if not os.path.exists(preset_file):
            logger.debug("No preset file found at {}. Pulling preset file without username".format(preset_file))
            preset_file = get_openai_preset_path(presetname, preset_type)
            if not os.path.exists(preset_file):
                raise FileNotFoundError(f"The preset file {preset_file} does not exist.")

        with open(preset_file) as file:
            preset = json.load(file)

        self.api_key = self.endpoint_file.get("apiKey", "")
        self.endpoint_url = self.endpoint_file["endpoint"]
        self.model_name = self.endpoint_file.get("modelNameToSendToAPI", "")
        self.strip_start_stop_line_breaks = self.endpoint_file.get("trimBeginningAndEndLineBreaks", False)
        self.is_busy_flag: bool = False

        self._gen_input = preset

        self.stream = stream
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key
        }
        self.llm_type = llm_type
        self._api_handler = self.create_api_handler()

    def create_api_handler(self) -> LlmApiHandler:
        """
        Create the API-specific handler based on llm_type.

        Returns:
            LlmApiHandler: An instance of the appropriate API handler.
        """
        if self.llm_type == "openAIChatCompletion":
            return OpenAiApiHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        elif self.llm_type == "koboldCppGenerate":
            return KoboldCppApiHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        elif self.llm_type == "openAIV1Completion":
            return OpenAiCompletionsApiHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        elif self.llm_type == "ollamaApiChat":
            return OllamaChatHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        elif self.llm_type == "ollamaApiGenerate":
            return OllamaGenerateHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        elif self.llm_type == "ollamaApiChatImageSpecific":
            return OllamaApiChatImageSpecificHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        elif self.llm_type == "openAIApiChatImageSpecific":
            return OpenAIApiChatImageSpecificHandler(
                base_url=self.endpoint_url,
                api_key=self.api_key,
                gen_input=self._gen_input,
                model_name=self.model_name,
                headers=self.headers,
                strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                stream=self.stream,
                api_type_config=self.api_type_config,
                endpoint_config=self.endpoint_file,
                max_tokens=self.max_tokens
            )
        else:
            raise ValueError(f"Unsupported LLM type: {self.llm_type}")

    def get_response_from_llm(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None,
            llm_takes_images: bool = False,
    ) -> Union[Generator[str, None, None], str]:
        """
        Sends a prompt or conversation to the LLM and returns the response.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of dictionaries containing the conversation with roles and content.
            system_prompt (Optional[str]): The system prompt to send to the LLM.
            prompt (Optional[str]): The user prompt to send to the LLM.

        Returns:
            Union[Generator[str, None, None], str]: A generator yielding chunks of the response if streaming, otherwise the complete response.
        """
        try:
            conversation_copy = deepcopy(conversation) if conversation else None

            self.is_busy_flag = True
            logger.debug("llm_api - Stream is: %s", self.stream)
            logger.debug("llm_api - System prompt: %s", system_prompt)
            logger.debug("llm_api - Prompt: %s", prompt)

            # Handle the presence of images in the conversation based on LLM capability
            if not llm_takes_images:
                logger.debug("llm_api does not take images. Removing images from the collection.")
                if conversation_copy:
                    conversation_copy = [
                        message for message in conversation_copy if message.get("role") != "images"
                    ]
            else:
                logger.debug("llm_api takes images. Leaving images in place.")

            if self.stream:
                return self._api_handler.handle_streaming(
                    conversation=conversation_copy,
                    system_prompt=system_prompt,
                    prompt=prompt
                )
            else:
                return self._api_handler.handle_non_streaming(
                    conversation=conversation_copy,
                    system_prompt=system_prompt,
                    prompt=prompt
                )
        except Exception as e:
            logger.error("Exception in get_response_from_llm: %s", e)
            # Add more detailed error information
            logger.error(f"LLM Type: {self.llm_type}")
            logger.error(f"Endpoint URL: {self.endpoint_url}")
            logger.error(f"Model: {self.model_name}")
            logger.error(f"Connection Parameters: Base URL = {self.endpoint_url}, API Type = {self.llm_type}")
            if isinstance(e, requests.exceptions.HTTPError):
                logger.error(f"HTTP Status Code: {e.response.status_code}")
                logger.error(f"Response Text: {e.response.text if hasattr(e.response, 'text') else 'No response text'}")
            traceback.print_exc()
            raise
        finally:
            self.is_busy_flag = False

    def is_busy(self) -> bool:
        """
        Check if the service is busy.

        Returns:
            bool: True if busy, False otherwise.
        """
        return self.is_busy_flag