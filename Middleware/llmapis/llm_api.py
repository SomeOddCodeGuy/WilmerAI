# /Middleware/llmapis/llm_api.py

import json
import logging
import os
import traceback
from copy import deepcopy
from typing import Dict, Generator, List, Optional, Union, Any

from Middleware.llmapis.handlers.base.base_llm_api_handler import LlmApiHandler
from Middleware.llmapis.handlers.impl.claude_api_handler import ClaudeApiHandler
from Middleware.llmapis.handlers.impl.koboldcpp_api_handler import KoboldCppApiHandler
from Middleware.llmapis.handlers.impl.ollama_chat_api_handler import OllamaChatHandler
from Middleware.llmapis.handlers.impl.ollama_generate_api_handler import OllamaGenerateApiHandler
from Middleware.llmapis.handlers.impl.openai_api_handler import OpenAiApiHandler
from Middleware.llmapis.handlers.impl.openai_completions_api_handler import OpenAiCompletionsApiHandler
from Middleware.utilities.config_utils import (
    get_openai_preset_path,
    get_endpoint_config,
    get_api_type_config,
)

logger = logging.getLogger(__name__)


class LlmApiService:
    """
    Orchestrates interactions with various LLM API backends.

    This service loads endpoint and preset configurations to instantiate a specific
    API handler, which is then used to send requests and receive responses.
    """

    def __init__(self, endpoint: str, presetname: str, max_tokens: int, stream: bool = False):
        """
        Initializes the LlmApiService instance.

        Loads configurations, sets up connection parameters, and instantiates the
        appropriate API handler based on the endpoint configuration.

        Args:
            endpoint (str): The name of the endpoint configuration to use.
            presetname (str): The name of the generation preset to apply.
            max_tokens (int): The maximum number of tokens to generate.
            stream (bool): A flag indicating whether to use streaming responses.
        """
        self.max_tokens = max_tokens
        self.endpoint_file = get_endpoint_config(endpoint)
        self.api_type_config = get_api_type_config(self.endpoint_file.get("apiTypeConfigFileName", ""))
        llm_type = self.api_type_config["type"]
        preset_type = self.api_type_config.get("presetType", "")
        logger.debug(f"API type: {llm_type}, Preset type: {preset_type}, Preset name: {presetname}")
        preset_file = get_openai_preset_path(presetname, preset_type, True)
        logger.info("Loading preset at {}".format(preset_file))

        if not os.path.exists(preset_file):
            logger.warning(f"No preset file found at {preset_file}. Trying fallback without user subdirectory.")
            preset_file = get_openai_preset_path(presetname, preset_type)
            logger.debug(f"Fallback preset path: {preset_file}")
            if not os.path.exists(preset_file):
                raise FileNotFoundError(f"The preset file {preset_file} does not exist.")

        with open(preset_file) as file:
            preset = json.load(file)

        self.api_key = self.endpoint_file.get("apiKey", "")
        self.endpoint_url = self.endpoint_file["endpoint"]
        self.model_name = self.endpoint_file.get("modelNameToSendToAPI", "")
        self.dont_include_model = self.endpoint_file.get("dontIncludeModel", False)
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
        Creates and returns the appropriate API handler based on the configuration.

        This method acts as a factory, selecting the correct handler class based
        on the 'llm_type' specified in the API type configuration file.

        Returns:
            LlmApiHandler: An instance of a concrete handler for the specified LLM type.
        """
        common_args = {
            "base_url": self.endpoint_url,
            "api_key": self.api_key,
            "gen_input": self._gen_input,
            "model_name": self.model_name,
            "headers": self.headers,
            "stream": self.stream,
            "api_type_config": self.api_type_config,
            "endpoint_config": self.endpoint_file,
            "max_tokens": self.max_tokens,
        }

        # Note: ImageSpecific types are deprecated. The regular handlers now support images
        # when passed via the ImageProcessor node. These mappings are kept for backwards
        # compatibility with existing configurations.
        if self.llm_type in ("openAIChatCompletion", "openAIApiChatImageSpecific"):
            return OpenAiApiHandler(**common_args, dont_include_model=self.dont_include_model)
        elif self.llm_type == "claudeMessages":
            return ClaudeApiHandler(**common_args, dont_include_model=self.dont_include_model)
        elif self.llm_type in ("koboldCppGenerate", "koboldCppGenerateImageSpecific"):
            return KoboldCppApiHandler(**common_args)
        elif self.llm_type == "openAIV1Completion":
            return OpenAiCompletionsApiHandler(**common_args)
        elif self.llm_type in ("ollamaApiChat", "ollamaApiChatImageSpecific"):
            return OllamaChatHandler(**common_args)
        elif self.llm_type == "ollamaApiGenerate":
            return OllamaGenerateApiHandler(**common_args)
        else:
            raise ValueError(f"Unsupported LLM type: {self.llm_type}")

    def get_response_from_llm(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None,
            llm_takes_images: bool = False,
            request_id: Optional[str] = None,
    ) -> Union[Generator[Dict[str, Any], None, None], str]:
        """
        Sends a prompt or conversation to the LLM and returns the raw response.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The conversation history.
            system_prompt (Optional[str]): The system prompt.
            prompt (Optional[str]): The user prompt.
            llm_takes_images (bool): Flag indicating if the LLM can process images.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            Union[Generator[Dict[str, Any], None, None], str]: A generator yielding raw data
            dictionaries if streaming, otherwise the complete raw response string.
        """
        self.is_busy_flag = True
        try:
            conversation_copy = deepcopy(conversation) if conversation else None
            system_prompt_to_pass = system_prompt
            prompt_to_pass = prompt

            add_start_system = self.endpoint_file.get("addTextToStartOfSystem", False)
            text_start_system = self.endpoint_file.get("textToAddToStartOfSystem", "")
            add_start_prompt = self.endpoint_file.get("addTextToStartOfPrompt", False)
            text_start_prompt = self.endpoint_file.get("textToAddToStartOfPrompt", "")

            if add_start_system and text_start_system:
                system_prompt_to_pass = text_start_system + (system_prompt_to_pass or "")
            if add_start_prompt and text_start_prompt:
                prompt_to_pass = text_start_prompt + (prompt_to_pass or "")

            logger.debug("llm_api - Stream is: %s", self.stream)
            logger.debug("llm_api - System prompt: %s", system_prompt_to_pass)
            logger.debug("llm_api - Prompt: %s", prompt_to_pass)

            if not llm_takes_images:
                logger.debug("llm_api does not take images. Removing images from the collection.")
                if conversation_copy:
                    conversation_copy = [msg for msg in conversation_copy if msg.get("role") != "images"]
            else:
                logger.debug("llm_api takes images. Leaving images in place.")

            if self.stream:
                def stream_wrapper() -> Generator[Dict[str, Any], None, None]:
                    try:
                        yield from self._api_handler.handle_streaming(
                            conversation=conversation_copy,
                            system_prompt=system_prompt_to_pass,
                            prompt=prompt_to_pass,
                            request_id=request_id,
                        )
                    finally:
                        self.is_busy_flag = False
                        self.close()

                return stream_wrapper()
            else:
                try:
                    response = self._api_handler.handle_non_streaming(
                        conversation=conversation_copy,
                        system_prompt=system_prompt_to_pass,
                        prompt=prompt_to_pass,
                        request_id=request_id,
                    )
                    return response
                finally:
                    self.is_busy_flag = False
                    self.close()
        except Exception as e:
            self.is_busy_flag = False
            logger.error("Exception in get_response_from_llm: %s", e)
            traceback.print_exc()
            raise

    def close(self):
        """Closes the underlying API handler's HTTP session."""
        if self._api_handler:
            self._api_handler.close()

    def is_busy(self) -> bool:
        """
        Checks if the service is currently processing a request.

        Returns:
            bool: True if a request is in progress, otherwise False.
        """
        return self.is_busy_flag
