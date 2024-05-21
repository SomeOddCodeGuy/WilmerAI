from Middleware.llmapis.open_ai_compatible_api import OpenAiCompatibleApiService
from Middleware.models.llm_handler import LlmHandler
from Middleware.utilities.config_utils import get_chat_template_name, \
    load_config, get_model_config_path


class LlmHandlerService:

    def __init__(self):
        self.llm_handler = None

    def initialize_llm_handler(self, config_data, preset, endpoint, max_new_tokens, min_tokens=0, stream=False):
        llm_type = config_data["type"]
        if llm_type == "koboldCpp":
            print('Loading endpoint from Kobold...' + endpoint)
            llm = OpenAiCompatibleApiService(endpoint=endpoint, presetname=preset,
                                             max_truncate_length=config_data['truncation_length'],
                                             max_new_tokens=max_new_tokens,
                                             min_new_tokens=min_tokens, stream=stream)
        else:
            raise ValueError(f"Unsupported LLM type: {llm_type}")

        prompt_template = config_data["promptTemplate"]
        if prompt_template is not None:
            prompt_template_filepath = prompt_template
        else:
            prompt_template_filepath = get_chat_template_name()

        self.llm_handler = LlmHandler(llm, prompt_template_filepath, config_data['truncation_length'],
                                      max_new_tokens)

        return self.llm_handler

    def load_model_from_config(self, config_name, preset, max_new_tokens, min_tokens=0, stream=False):
        config_file = get_model_config_path(config_name)
        config_data = load_config(config_file)
        return self.initialize_llm_handler(config_data, preset, config_name, max_new_tokens, min_tokens, stream)
