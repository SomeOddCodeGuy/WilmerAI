from Middleware.llmapis.open_ai_llm_chat_completions_api import OpenAiLlmChatCompletionsApiService
from Middleware.llmapis.open_ai_llm_completions_api import OpenAiLlmCompletionsApiService
from Middleware.models.llm_handler import LlmHandler
from Middleware.utilities.config_utils import get_chat_template_name, \
    get_endpoint_config, get_api_type_config


class LlmHandlerService:

    def __init__(self):
        self.llm_handler = None

    def initialize_llm_handler(self, config_data, preset, endpoint, stream, truncate_length, max_tokens):
        print("Initialize llm hander config_data: {}".format(config_data))
        add_generation_prompt = config_data.get("addGenerationPrompt", False)
        api_type_config = get_api_type_config(config_data["apiTypeConfigFileName"])
        llm_type = api_type_config["type"]
        if llm_type == "openAIV1Completion":
            print('Loading v1 Completions endpoint: ' + endpoint)
            llm = OpenAiLlmCompletionsApiService(endpoint=endpoint, presetname=preset,
                                                 stream=stream, api_type_config=api_type_config,
                                                 max_tokens=max_tokens)
        elif llm_type == "openAIChatCompletion":
            print('Loading chat Completions endpoint: ' + endpoint)
            llm = OpenAiLlmChatCompletionsApiService(endpoint=endpoint, presetname=preset,
                                                     stream=stream, api_type_config=api_type_config,
                                                     max_tokens=max_tokens)
        else:
            raise ValueError(f"Unsupported LLM type: {llm_type}")

        prompt_template = config_data["promptTemplate"]
        if prompt_template is not None:
            prompt_template_filepath = prompt_template
        else:
            prompt_template_filepath = get_chat_template_name()

        self.llm_handler = LlmHandler(llm, prompt_template_filepath, add_generation_prompt, llm_type)

        return self.llm_handler

    def load_model_from_config(self, config_name, preset, stream=False, truncate_length=4096, max_tokens=400):
        try:
            print("Loading model from: " + config_name)
            config_file = get_endpoint_config(config_name)
            return self.initialize_llm_handler(config_file, preset, config_name, stream, truncate_length, max_tokens)
        except Exception as e:
            print(f"Error loading model from config: ", e)
