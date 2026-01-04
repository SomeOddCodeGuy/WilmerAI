class LlmHandler:

    def __init__(self, llm, prompt_template_filepath, add_generation_prompt, llm_type, api_key=""):
        self.llm = llm
        self.prompt_template_file_name = prompt_template_filepath
        self.add_generation_prompt = add_generation_prompt
        self.api_key = api_key

        # Completions-style APIs don't take message collections
        if llm_type in ("openAIV1Completion", "koboldCppGenerate", "ollamaApiGenerate"):
            self.takes_message_collection = False
        else:
            self.takes_message_collection = True