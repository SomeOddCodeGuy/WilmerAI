from typing import Dict, Any, Optional

from Middleware.utilities.config_utils import get_chat_template_name
from Middleware.utilities.prompt_extraction_utils import extract_pairs_and_system_prompt_from_wilmer_templated_string, \
    extract_last_n_turns
from Middleware.utilities.prompt_template_utils import \
    add_assistant_end_token_to_user_turn, format_system_prompts, format_templated_prompt, format_user_turn_with_template


class WorkflowVariableManager:
    @staticmethod
    def process_conversation_turn_variables(prompt_configurations: Dict[str, str], llm_handler: Any) -> Dict[str, str]:
        """
        Applies prompt templates to the user turn variables generated, based on the prompt configurations.

        :param prompt_configurations: A dictionary containing prompt configurations.
        :param llm_handler: The LLM (Language Model Manager) handler.
        :return: A dictionary containing processed prompts.
        """
        processed_prompts = {}
        for key, text in prompt_configurations.items():
            if llm_handler is not None:
                template_file = (get_chat_template_name()) if "chat" in key else llm_handler.prompt_template_file_name
            else:
                template_file = (get_chat_template_name())

            processed_prompts[key] = format_templated_prompt(text, llm_handler, llm_handler.prompt_template_file_name)
        return processed_prompts

    def __init__(self, **kwargs):
        self.category_list = None
        self.categoriesSeparatedByOr = None
        self.category_colon_descriptions = None
        self.category_descriptions = None
        self.categories = None
        self.chatPromptTemplate = get_chat_template_name()
        self.set_categories_from_kwargs(**kwargs)

    def apply_variables(self, prompt: str, llm_handler: Any, unaltered_prompt: Optional[str] = None,
                        agent_outputs: Optional[Dict[str, Any]] = None,
                        do_not_apply_prompt_template: bool = False) -> str:
        """
        Applies the generated variables to the prompt and formats it using the specified template.

        :param prompt: The original prompt string.
        :param llm_handler: The LLM handler.
        :param unaltered_prompt: The unaltered prompt, if available.
        :param agent_outputs: A dictionary of outputs from agent processing.
        :param do_not_apply_prompt_template: A flag indicating whether to skip prompt template application.
        :return: The formatted prompt string.
        """
        variables = self.generate_variables(llm_handler, unaltered_prompt, agent_outputs)

        formatted_prompt = prompt.format(**variables)

        if not do_not_apply_prompt_template:
            formatted_prompt = (format_user_turn_with_template(formatted_prompt, llm_handler.prompt_template_file_name))
            formatted_prompt = (
                add_assistant_end_token_to_user_turn(formatted_prompt, llm_handler.prompt_template_file_name))
        print("\n************************************************")
        print("Formatted_Prompt:", formatted_prompt)
        print("************************************************")
        return formatted_prompt

    # Generates all the variables utilities by the workflow prompts.
    def generate_variables(self, llm_handler: Any, unaltered_prompt: Optional[str] = None,
                           agent_outputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generates all the variables utilized by the workflow prompts.

        :param llm_handler: The LLM handler.
        :param unaltered_prompt: The unaltered prompt, if available.
        :param agent_outputs: A dictionary of outputs from agent processing.
        :return: A dictionary of generated variables.
        """
        variables = {}

        if unaltered_prompt:
            prompt_configurations = self.generate_conversation_turn_variables(unaltered_prompt)
            variables.update(self.process_conversation_turn_variables(prompt_configurations, llm_handler))

            system_prompt, pairs = (extract_pairs_and_system_prompt_from_wilmer_templated_string(unaltered_prompt))
            variables.update(format_system_prompts(system_prompt,
                                                   pairs,
                                                   llm_handler,
                                                   get_chat_template_name()))

        # Merge any agent outputs
        variables.update(agent_outputs or {})

        # Handle additional attributes
        variables.update(self.extract_additional_attributes())

        return variables

    def extract_additional_attributes(self) -> Dict[str, Any]:
        """
        Extracts additional attributes from the instance that may be used in variable generation.

        :return: A dictionary of additional attributes.
        """
        attributes = {}
        attribute_list = ["category_list", "category_descriptions", "category_colon_descriptions",
                          "categoriesSeparatedByOr"]
        for attribute in attribute_list:
            if hasattr(self, attribute) and getattr(self, attribute) is not None:
                attributes[attribute] = getattr(self, attribute)
        return attributes

    def set_categories_from_kwargs(self, **kwargs: Any):
        """
        Sets category-related attributes based on the provided keyword arguments.
        """
        if 'category_descriptions' in kwargs:
            self.category_descriptions = kwargs['category_descriptions']
        if 'category_colon_descriptions' in kwargs:
            print("Found in kwargs")
            self.category_colon_descriptions = kwargs['category_colon_descriptions']
        if 'categoriesSeparatedByOr' in kwargs:
            self.categoriesSeparatedByOr = kwargs['categoriesSeparatedByOr']
        if 'category_list' in kwargs:
            self.category_list = kwargs['category_list']

    @staticmethod
    def generate_conversation_turn_variables(unaltered_prompt: str) -> Dict[str, Any]:
        """
        Generates a dictionary of variables based on the conversation turns in the unaltered prompt.

        :param unaltered_prompt: The original prompt string containing conversation turns.
        :return: A dictionary of variables for user prompts at different turn lengths.
        """
        return {"templated_user_prompt": unaltered_prompt, "chat_user_prompt": unaltered_prompt,
                "templated_user_prompt_last_ten": extract_last_n_turns(unaltered_prompt, 10),
                "chat_user_prompt_last_ten": extract_last_n_turns(unaltered_prompt, 10),
                "templated_user_prompt_last_five": extract_last_n_turns(unaltered_prompt, 5),
                "chat_user_prompt_last_five": extract_last_n_turns(unaltered_prompt, 5),
                "templated_user_prompt_last_four": extract_last_n_turns(unaltered_prompt, 4),
                "chat_user_prompt_last_four": extract_last_n_turns(unaltered_prompt, 4),
                "templated_user_prompt_last_three": extract_last_n_turns(unaltered_prompt, 3),
                "chat_user_prompt_last_three": extract_last_n_turns(unaltered_prompt, 3),
                "templated_user_prompt_last_two": extract_last_n_turns(unaltered_prompt, 2),
                "chat_user_prompt_last_two": extract_last_n_turns(unaltered_prompt, 2),
                "templated_user_prompt_last_one": extract_last_n_turns(unaltered_prompt, 1),
                "chat_user_prompt_last_one": extract_last_n_turns(unaltered_prompt, 1)}
