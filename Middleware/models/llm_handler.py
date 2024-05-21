class LlmHandler:

    def __init__(self, llm, prompt_template_filepath, truncate_length, max_new_tokens):
        self.llm = llm
        self.prompt_template_file_name = prompt_template_filepath
        self.truncate_length = truncate_length
        self.max_new_tokens = max_new_tokens
