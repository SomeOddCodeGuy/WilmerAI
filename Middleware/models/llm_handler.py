class LlmHandler:

    def __init__(self, llm, prompt_template_filepath, add_generation_prompt, llm_type, api_key=""):
        self.llm = llm
        self.prompt_template_file_name = prompt_template_filepath
        self.add_generation_prompt = add_generation_prompt
        self.api_key = api_key

        if llm_type == "openAIV1Completion" or llm_type == "koboldCppGenerate" or llm_type == "ollamaApiGenerate":
            self.takes_message_collection = False
        else:
            self.takes_message_collection = True
