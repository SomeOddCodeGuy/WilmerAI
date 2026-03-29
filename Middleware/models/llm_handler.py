class LlmHandler:
    """
    Holds configuration for a specific LLM endpoint and how to interact with it.

    This model is constructed once per workflow node execution and carries the
    endpoint's LLM service wrapper, prompt template, and API type. It is consumed
    by LLMDispatchService to determine how to format and route prompts.

    Attributes:
        llm: The LLM service wrapper (e.g., LlmApiService) used to issue requests.
        prompt_template_file_name (str): Filename of the prompt template for this endpoint.
        add_generation_prompt (bool): Whether to append an assistant-turn token to the
            prompt before sending, priming the model to continue as the assistant.
        api_key (str): The API key for authenticating with this endpoint.
        takes_message_collection (bool): True if the API expects a list of messages
            (chat-completion style); False for single-string completion APIs.
    """

    def __init__(self, llm, prompt_template_filepath, add_generation_prompt, llm_type, api_key=""):
        """
        Initializes the LlmHandler.

        Args:
            llm: The LLM service wrapper instance (e.g., LlmApiService).
            prompt_template_filepath (str): Filename of the prompt template to use.
            add_generation_prompt (bool): Whether to append an assistant turn token.
            llm_type (str): The API type identifier (e.g., 'openAIV1Completion',
                'openAIV1ChatCompletion'). Determines whether the API takes a message
                collection or a single prompt string.
            api_key (str): The API key for authentication. Defaults to empty string.
        """
        self.llm = llm
        self.prompt_template_file_name = prompt_template_filepath
        self.add_generation_prompt = add_generation_prompt
        self.api_key = api_key

        # Completions-style APIs don't take message collections
        if llm_type in ("openAIV1Completion", "koboldCppGenerate", "ollamaApiGenerate"):
            self.takes_message_collection = False
        else:
            self.takes_message_collection = True