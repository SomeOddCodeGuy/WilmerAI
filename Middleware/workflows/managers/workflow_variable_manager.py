import logging
from copy import deepcopy
from typing import Dict, Any, Optional, List

import jinja2

from Middleware.utilities.config_utils import get_chat_template_name
from Middleware.services.memory_service import MemoryService
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns_as_string
from Middleware.utilities.prompt_template_utils import (
    format_system_prompts, format_templated_prompt, get_formatted_last_n_turns_as_string
)

logger = logging.getLogger(__name__)


class WorkflowVariableManager:
    @staticmethod
    def process_conversation_turn_variables(prompt_configurations: Dict[str, str], llm_handler: Any) -> Dict[str, str]:
        """
        Applies prompt templates to the user turn variables generated.

        This method iterates through a dictionary of prompt configurations and
        applies the appropriate chat or completions template to each prompt
        string based on the provided LLM handler.

        Args:
            prompt_configurations (Dict[str, str]): A dictionary containing prompt configurations.
            llm_handler (Any): The LLM handler containing information about the model and its capabilities.

        Returns:
            Dict[str, str]: A dictionary containing the processed and formatted prompts.
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
        Initializes the WorkflowVariableManager.

        This manager is responsible for generating and managing variables used
        in workflow prompts. It can be initialized with various category-related
        attributes via keyword arguments.

        Args:
            **kwargs: Optional keyword arguments to set category-related attributes.
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
        self.memory_service = MemoryService()

    def apply_variables(self, prompt: str, llm_handler: Any, messages: List[Dict[str, str]],
                        agent_outputs: Optional[Dict[str, Any]] = None,
                        remove_all_system_override=None,
                        config: Dict = None) -> str:
        """
        Applies generated variables to the prompt and formats it.

        This method first generates a set of variables from the conversation
        history and agent outputs. It then uses either a Jinja2 template engine
        or standard Python string formatting to inject these variables into
        the provided prompt string.

        Args:
            prompt (str): The original prompt string, potentially containing format placeholders.
            llm_handler (Any): The LLM handler.
            messages (List[Dict[str, str]]): A list of conversation turns.
            agent_outputs (Optional[Dict[str, Any]]): A dictionary of outputs from agent processing.
            remove_all_system_override (Optional[Any]): A flag to override system message removal.
            config (Dict): A dictionary containing configuration settings, including whether to use jinja2.

        Returns:
            str: The formatted prompt string with all variables applied.
        """
        variables = self.generate_variables(llm_handler, messages, agent_outputs, remove_all_system_override)
        if config is not None and config.get('jinja2', False):
            environment = jinja2.Environment()
            template = environment.from_string(prompt)
            variables['messages'] = messages
            return template.render(**variables)
        else:
            # Add messages to the variables dictionary for standard .format()
            variables['messages'] = messages
            # agent_outputs are already merged by generate_variables
            return prompt.format(**variables)

    def generate_variables(self, llm_handler: Any, messages: List[Dict[str, str]],
                           agent_outputs: Optional[Dict[str, Any]] = None, remove_all_system_override=None) -> Dict[
        str, Any]:
        """
        Generates all variables for the workflow prompts.

        This is a core method that orchestrates the creation of all variables
        required for a workflow prompt. It combines variables from conversation
        turns, system prompts, agent outputs, and instance attributes.

        Args:
            llm_handler (Any): The LLM handler.
            messages (List[Dict[str, str]]): A list of conversation turns.
            agent_outputs (Optional[Dict[str, Any]]): A dictionary of outputs from agent processing.
            remove_all_system_override (Optional[Any]): A flag to override system message removal.

        Returns:
            Dict[str, Any]: A dictionary of all generated variables.
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
        Extracts additional attributes from the instance.

        This method pulls specific, pre-defined attributes from the manager
        instance and returns them as a dictionary. These attributes often
        relate to prompt categorization.

        Returns:
            Dict[str, Any]: A dictionary of additional attributes.
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
        Sets category-related attributes based on keyword arguments.

        This method is used during initialization to configure the manager
        with specific category-related data, such as descriptions or lists.

        Args:
            **kwargs (Any): A dictionary of keyword arguments.
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
        Generates variables for conversation turns.

        This static method creates a dictionary of variables, each representing a
        different slice of the conversation history. It provides both templated
        and raw string versions for various numbers of turns (e.g., last 1, 5, 10 turns).

        Args:
            originalMessages (List[Dict[str, str]]): The conversation turns.
            llm_handler (Any): The LLM handler.
            remove_all_system_override (Any): A flag to override system message removal.

        Returns:
            Dict[str, str]: A dictionary of variables for user prompts at different turn lengths.
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
            # chat_user_prompt_last_one needs to get the content of the chronologically last message in the conversation,
            # regardless of its role (user or assistant). This is critical for features like group chat categorization
            # (e.g., WilmerAI/Public/Configs/Workflows/group-chat-example/CustomCategorizationWorkflow.json)
            # where an assistant's message (like the name of the next persona to speak) is used to determine workflow routing.
            "chat_user_prompt_last_one": extract_last_n_turns_as_string(messages, 1,
                                                                          include_sysmes,
                                                                          remove_all_system_override)
        }

    def generate_chat_summary_variables(self, messages, discussion_id) -> Dict[str, str]:
        """
        Generates variables related to the chat summary.

        This method retrieves and formats the conversation summary and
        newest chat summary memories from the MemoryService, making them
        available as variables for a prompt.

        Args:
            messages (List[Dict[str, str]]): The conversation turns.
            discussion_id (str): The unique identifier for the conversation.

        Returns:
            Dict[str, str]: A dictionary containing variables for memories and summary.
        """
        return {
            "newest_chat_summary_memories": self.memory_service.get_chat_summary_memories(messages,
                                                                         discussion_id),
            "current_chat_summary": self.memory_service.get_current_summary(discussion_id)
        }