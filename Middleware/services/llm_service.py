from Middleware.llmapis.open_ai_llm_chat_completions_api import OpenAiLlmChatCompletionsApiService
from Middleware.llmapis.open_ai_llm_completions_api import OpenAiLlmCompletionsApiService
from Middleware.models.llm_handler import LlmHandler
from Middleware.utilities.config_utils import get_chat_template_name, \
    load_config, get_model_config_path


class LlmHandlerService:

    def __init__(self):
        self.llm_handler = None

    def initialize_llm_handler(self, config_data, preset, endpoint, stream=False):
        llm_type = config_data["type"]
        add_generation_prompt = config_data["addGenerationPrompt"]
        model_name = config_data["modelNameToSendToAPI"]
        if llm_type == "openAIV1Completion":
            print('Loading v1 Completions endpoint: ' + endpoint)
            llm = OpenAiLlmCompletionsApiService(endpoint=endpoint, model_name=model_name, presetname=preset,
                                                 stream=stream)
        elif llm_type == "openAIChatCompletion":
            print('Loading chat Completions endpoint: ' + endpoint)
            llm = OpenAiLlmChatCompletionsApiService(endpoint=endpoint, model_name=model_name, presetname=preset,
                                                     stream=stream)
        else:
            raise ValueError(f"Unsupported LLM type: {llm_type}")

        prompt_template = config_data["promptTemplate"]
        if prompt_template is not None:
            prompt_template_filepath = prompt_template
        else:
            prompt_template_filepath = get_chat_template_name()

        self.llm_handler = LlmHandler(llm, prompt_template_filepath, add_generation_prompt, llm_type)

        return self.llm_handler

    def load_model_from_config(self, config_name, preset, stream=False):
        try:
            config_file = get_model_config_path(config_name)
            config_data = load_config(config_file)
            return self.initialize_llm_handler(config_data, preset, config_name, stream)
        except Exception as e:
            print(f"Error loading model from config: ", e)
