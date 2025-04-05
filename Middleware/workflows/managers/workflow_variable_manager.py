import logging
from copy import deepcopy
from typing import Dict, Any, Optional, List

import jinja2

from Middleware.utilities.config_utils import get_chat_template_name
from Middleware.utilities.memory_utils import handle_get_current_summary_from_file, gather_chat_summary_memories
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns_as_string
from Middleware.utilities.prompt_template_utils import (
    format_system_prompts, format_templated_prompt, get_formatted_last_n_turns_as_string
)

logger = logging.getLogger(__name__)


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
                template_file = get_chat_template_name() if "chat" in key else llm_handler.prompt_template_file_name
            else:
                template_file = get_chat_template_name()
            processed_prompts[key] = format_templated_prompt(text, llm_handler, template_file)
        return processed_prompts

    def __init__(self, **kwargs):
        """
        Initializes the WorkflowVariableManager with optional category-related attributes.

        :param kwargs: Optional keyword arguments to set category-related attributes.
        """
        self.category_list = None
        self.categoriesSeparatedByOr = None
        self.category_colon_descriptions = None
        self.category_colon_descriptions_newline_bulletpoint = None
        self.categoryNameBulletpoints = None
        self.category_descriptions = None
        self.categories = None
        self.chatPromptTemplate = get_chat_template_name()
        self.set_categories_from_kwargs(**kwargs)

    def apply_variables(self, prompt: str, llm_handler: Any, messages: List[Dict[str, str]],
                        agent_outputs: Optional[Dict[str, Any]] = None,
                        remove_all_system_override=None,
                        config: Dict = None) -> str:
        """
        Applies the generated variables to the prompt and formats it using the specified template.

        :param prompt: The original prompt string.
        :param llm_handler: The LLM handler.
        :param messages: A list of message dictionaries.
        :param agent_outputs: A dictionary of outputs from agent processing.
        :return: The formatted prompt string.
        """
        variables = self.generate_variables(llm_handler, messages, agent_outputs, remove_all_system_override)
        if config is not None and config.get('jinja2', False):
            environment = jinja2.Environment()
            template = environment.from_string(prompt)
            variables['messages'] = messages
            return template.render(**variables)
        else:
            return prompt.format(**variables)

    def generate_variables(self, llm_handler: Any, messages: List[Dict[str, str]],
                           agent_outputs: Optional[Dict[str, Any]] = None, remove_all_system_override=None) -> Dict[
        str, Any]:
        """
        Generates all the variables utilized by the workflow prompts.

        :param llm_handler: The LLM handler.
        :param messages: A list of message dictionaries.
        :param agent_outputs: A dictionary of outputs from agent processing.
        :return: A dictionary of generated variables.
        """
        variables = {}

        if messages:
            logger.debug("Inside generate variables")
            prompt_configurations = self.generate_conversation_turn_variables(messages, llm_handler,
                                                                              remove_all_system_override)
            variables.update(prompt_configurations)
            variables.update(format_system_prompts(messages, llm_handler, get_chat_template_name()))

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
                          "categoriesSeparatedByOr", "category_colon_descriptions_newline_bulletpoint",
                          "categoryNameBulletpoints"]
        for attribute in attribute_list:
            if hasattr(self, attribute) and getattr(self, attribute) is not None:
                attributes[attribute] = getattr(self, attribute)
        return attributes

    def set_categories_from_kwargs(self, **kwargs: Any):
        """
        Sets category-related attributes based on the provided keyword arguments.

        :param kwargs: A dictionary of keyword arguments.
        """
        if 'category_descriptions' in kwargs:
            self.category_descriptions = kwargs['category_descriptions']
        if 'category_colon_descriptions' in kwargs:
            self.category_colon_descriptions = kwargs['category_colon_descriptions']
        if 'categoriesSeparatedByOr' in kwargs:
            self.categoriesSeparatedByOr = kwargs['categoriesSeparatedByOr']
        if 'category_colon_descriptions_newline_bulletpoint' in kwargs:
            self.category_colon_descriptions_newline_bulletpoint = kwargs[
                'category_colon_descriptions_newline_bulletpoint']
        if 'categoryNameBulletpoints' in kwargs:
            self.categoryNameBulletpoints = kwargs['categoryNameBulletpoints']
        if 'category_list' in kwargs:
            self.category_list = kwargs['category_list']

    @staticmethod
    def generate_conversation_turn_variables(originalMessages: List[Dict[str, str]], llm_handler: Any,
                                             remove_all_system_override) -> Dict[
        str, str]:
        """
        Generates a dictionary of variables based on the conversation turns in the unaltered prompt.

        :param originalMessages: The conversation turns.
        :param llm_handler: The LLM handler.
        :return: A dictionary of variables for user prompts at different turn lengths.
        """
        include_sysmes = llm_handler.takes_message_collection

        messages = deepcopy(originalMessages)

        return {
            "templated_user_prompt_last_twenty": get_formatted_last_n_turns_as_string(
                messages, 20, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_twenty": extract_last_n_turns_as_string(messages, 20,
                                                                           include_sysmes, remove_all_system_override),
            "templated_user_prompt_last_ten": get_formatted_last_n_turns_as_string(
                messages, 10, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_ten": extract_last_n_turns_as_string(messages, 10,
                                                                        include_sysmes, remove_all_system_override),
            "templated_user_prompt_last_five": get_formatted_last_n_turns_as_string(
                messages, 5, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_five": extract_last_n_turns_as_string(messages, 5,
                                                                         include_sysmes, remove_all_system_override),
            "templated_user_prompt_last_four": get_formatted_last_n_turns_as_string(
                messages, 4, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_four": extract_last_n_turns_as_string(messages, 4,
                                                                         include_sysmes, remove_all_system_override),
            "templated_user_prompt_last_three": get_formatted_last_n_turns_as_string(
                messages, 3, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_three": extract_last_n_turns_as_string(messages, 3,
                                                                          include_sysmes, remove_all_system_override),
            "templated_user_prompt_last_two": get_formatted_last_n_turns_as_string(
                messages, 2, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_two": extract_last_n_turns_as_string(messages, 2,
                                                                        include_sysmes, remove_all_system_override),
            "templated_user_prompt_last_one": get_formatted_last_n_turns_as_string(
                messages, 1, template_file_name=llm_handler.prompt_template_file_name,
                isChatCompletion=llm_handler.takes_message_collection),
            "chat_user_prompt_last_one": last_user_message_content
        }

    @staticmethod
    def generate_chat_summary_variables(messages, discussion_id) -> Dict[str, str]:
        """
        Generates the variables used for pulling the chat summary.

        :param originalMessages: The conversation turns.
        :param llm_handler: The LLM handler.
        :return: A dictionary of variables for user prompts at different turn lengths.
        """
        return {
            "newest_chat_summary_memories": gather_chat_summary_memories(messages,
                                                                         discussion_id),
            "current_chat_summary": handle_get_current_summary_from_file(discussion_id)
        }