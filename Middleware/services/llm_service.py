# Middleware/services/llm_service.py

import logging

from Middleware.llmapis.llm_api import LlmApiService
from Middleware.models.llm_handler import LlmHandler
from Middleware.utilities.config_utils import get_chat_template_name, \
    get_endpoint_config, get_api_type_config
from Middleware.utilities.text_utils import redact_sensitive_data

logger = logging.getLogger(__name__)


class LlmHandlerService:
    """
    A service for initializing and managing LLM handlers.

    This service provides methods to load LLM configurations from files
    and create `LlmHandler` instances, which abstract the interaction
    with different LLM backends.
    """

    def __init__(self):
        """
        Initializes the LlmHandlerService.
        This service is stateless.
        """
        pass

    def initialize_llm_handler(self, config_data, preset, endpoint, stream, truncate_length, max_tokens,
                               addGenerationPrompt=None):
        """
        Initializes an `LlmHandler` instance with the provided configuration.

        This method takes configuration data and other parameters to create
        and set up an `LlmHandler` for a specific LLM endpoint. It determines
        the LLM type, sets up the `LlmApiService`, and configures the prompt
        template before creating the final handler object.

        Args:
            config_data (dict): The configuration data for the endpoint, typically
                                from an endpoint config file.
            preset (str): The name of the preset config to use.
            endpoint (str): The name of the endpoint config to use.
            stream (bool): Flag to indicate if the response should be streamed.
            truncate_length (int): The maximum length for truncating messages.
            max_tokens (int): The maximum number of tokens to generate.
            addGenerationPrompt (bool, optional): Flag to add a generation prompt.
                                                  If None, it defaults to the value
                                                  in the config data.

        Returns:
            LlmHandler: The newly created and initialized `LlmHandler` instance.
        """
        logger.info("Initialize llm handler config_data: {}".format(redact_sensitive_data(config_data)))
        if (addGenerationPrompt is None):
            logger.debug("Add generation prompt is None")
            add_generation_prompt = config_data.get("addGenerationPrompt", False)
            logger.debug("Add_generation_prompt: {}".format(add_generation_prompt))
        else:
            logger.debug("Add generation prompt is {}".format(addGenerationPrompt))
            logger.info("Stream is {}".format(stream))
            add_generation_prompt = addGenerationPrompt

        api_type_config = get_api_type_config(config_data["apiTypeConfigFileName"])
        llm_type = api_type_config["type"]
        logger.info(f'Attempting to load {llm_type} endpoint: %s', endpoint)
        llm = LlmApiService(endpoint=endpoint, presetname=preset,
                            stream=stream,
                            max_tokens=max_tokens)

        prompt_template = config_data["promptTemplate"]
        if prompt_template is not None:
            prompt_template_filepath = prompt_template
        else:
            prompt_template_filepath = get_chat_template_name()

        # Create a new handler instance and return it directly.
        llm_handler = LlmHandler(llm, prompt_template_filepath, add_generation_prompt, llm_type)

        return llm_handler

    def load_model_from_config(self, config_name, preset, stream=False, truncate_length=4096, max_tokens=400,
                               addGenerationPrompt=None):
        """
        Loads and initializes an LLM handler from an endpoint config file.

        This function reads an endpoint configuration file and passes the
        data to `initialize_llm_handler` to create a new `LlmHandler`.
        It handles potential exceptions during the loading process.

        Args:
            config_name (str): The name of the endpoint configuration file.
            preset (str): The name of the preset config to use.
            stream (bool, optional): Flag to indicate if the response should be streamed.
                                     Defaults to False.
            truncate_length (int, optional): The maximum length for truncating messages.
                                             Defaults to 4096.
            max_tokens (int, optional): The maximum number of tokens to generate.
                                        Defaults to 400.
            addGenerationPrompt (bool, optional): Flag to add a generation prompt.
                                                  Defaults to None.

        Returns:
            LlmHandler: The initialized `LlmHandler` instance.

        Raises:
            Exception: If an error occurs while loading the model from the config.
        """
        try:
            logger.info("Loading model from: %s", config_name)
            config_file = get_endpoint_config(config_name)
            return self.initialize_llm_handler(config_file, preset, config_name, stream, truncate_length, max_tokens,
                                               addGenerationPrompt)
        except Exception as e:
            logger.error(f"Error loading model from config.")
            raise