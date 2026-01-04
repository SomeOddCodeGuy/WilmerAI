# /Middleware/workflows/managers/workflow_variable_manager.py

import logging
from copy import deepcopy
from datetime import datetime
from typing import Dict, Any, List

import jinja2

from Middleware.services.memory_service import MemoryService
from Middleware.services.timestamp_service import TimestampService
from Middleware.utilities.config_utils import get_chat_template_name
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns_as_string
from Middleware.utilities.prompt_template_utils import (
    format_system_prompts, format_templated_prompt, get_formatted_last_n_turns_as_string
)
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class WorkflowVariableManager:
    """
    Manages the substitution of dynamic placeholders in workflow prompts.

    This class is responsible for collecting all available variables from the
    ExecutionContext (e.g., date/time, conversation history, custom workflow
    values) and applying them to a given string, supporting both standard
    .format() and Jinja2 templating.
    """

    @staticmethod
    def process_conversation_turn_variables(prompt_configurations: Dict[str, str], llm_handler: Any) -> Dict[str, str]:
        """
        Applies LLM-specific chat templates to raw conversation strings.

        Args:
            prompt_configurations (Dict[str, str]): A dictionary of conversation turn variables
                                                    (e.g., {'chat_user_prompt_last_one': 'Hello'}).
            llm_handler (Any): The LLM handler instance, used to find the correct template.

        Returns:
            Dict[str, str]: A dictionary with the same keys but with formatted string values.
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
        Initializes the WorkflowVariableManager and its services.

        Args:
            **kwargs: Keyword arguments, potentially containing category information
                      to be set as instance attributes.
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
        self.timestamp_service = TimestampService()

    def apply_early_variables(self, prompt: str, agent_inputs: Dict[str, Any] = None,
                              workflow_config: Dict[str, Any] = None) -> str:
        """
        Applies only early-available variables to a prompt string.

        This method is used for early substitution of endpointName and preset fields,
        where only agent inputs and static workflow variables are available.
        Does NOT require or use llm_handler, avoiding the need for conversation variables.

        Args:
            prompt (str): The prompt string containing placeholders.
            agent_inputs (Dict[str, Any]): Agent input variables from parent workflows.
            workflow_config (Dict[str, Any]): Static workflow configuration variables.

        Returns:
            str: The resolved prompt string with early variables substituted.
        """
        variables = {}

        # Add workflow config variables first (excluding nodes)
        if workflow_config:
            for key, value in workflow_config.items():
                if key != "nodes":
                    variables[key] = value

        # Add agent inputs after, so they override workflow config if there are duplicates
        if agent_inputs:
            variables.update(agent_inputs)

        # Apply simple string formatting with partial substitution support
        try:
            return prompt.format(**variables)
        except KeyError as e:
            # Handle partial substitution - try to substitute what we can
            import re
            result = prompt
            for key, value in variables.items():
                # Replace both {key} and {{key}} patterns
                result = re.sub(r'\{' + re.escape(key) + r'\}', str(value), result)
            if result != prompt:
                # Some variables were substituted
                missing_vars = re.findall(r'\{([^}]+)\}', result)
                if missing_vars:
                    logger.warning(f"Variables not available for early substitution: {missing_vars}")
            else:
                logger.warning(f"No variables could be substituted. Available: {list(variables.keys())}")
            return result
        except Exception as e:
            logger.warning(f"Error during early variable substitution: {e}")
            return prompt

    def apply_variables(self, prompt: str, context: ExecutionContext,
                        remove_all_system_override=None) -> str:
        """
        Applies all available variables to a prompt string.

        This method resolves all dynamic placeholders in the prompt using either
        Jinja2 templating (if enabled in the node config) or standard Python
        string formatting.

        Args:
            prompt (str): The prompt string containing placeholders.
            context (ExecutionContext): The central object with all runtime data.
            remove_all_system_override (Any): An override flag for system message removal logic.

        Returns:
            str: The fully resolved prompt string.
        """
        variables = self.generate_variables(context, remove_all_system_override)

        if context.config is not None and context.config.get('jinja2', False):
            environment = jinja2.Environment()
            template = environment.from_string(prompt)
            variables['messages'] = context.messages
            return template.render(**variables)
        else:
            variables['messages'] = context.messages
            # Using str.format() can error if the prompt contains unused jinja syntax
            # This is a simple safeguard.
            try:
                return prompt.format(**variables)
            except KeyError as e:
                logger.warning(f"A key error occurred during prompt formatting. This can happen if a prompt "
                               f"contains curly braces not intended for variables. Error: {e}")
                return prompt

    def generate_variables(self, context: ExecutionContext, remove_all_system_override=None) -> Dict[str, Any]:
        """
        Gathers all available dynamic variables into a single dictionary.

        This method aggregates variables from multiple sources: date/time, custom
        values from the workflow's JSON config, conversation history, inter-node
        inputs/outputs, and other contextual data.

        Args:
            context (ExecutionContext): The central object with all runtime data.
            remove_all_system_override (Any): An override flag for system message removal logic.

        Returns:
            Dict[str, Any]: A dictionary of all resolved key-value variables.
        """
        variables = {}
        now = datetime.now()

        # --- Date and time variables ---
        variables['todays_date_pretty'] = now.strftime('%B %d, %Y')
        variables['todays_date_iso'] = now.strftime('%Y-%m-%d')
        variables['YYYY_MM_DD'] = now.strftime('%Y_%m_%d')
        variables['current_time_12h'] = now.strftime('%I:%M %p').lstrip('0')
        variables['current_time_24h'] = now.strftime('%H:%M')
        variables['current_month_full'] = now.strftime('%B')
        variables['current_day_of_week'] = now.strftime('%A')
        variables['current_day_of_month'] = now.strftime('%d')

        # --- Custom top-level variables from workflow JSON ---
        if context.workflow_config:
            for key, value in context.workflow_config.items():
                if key != "nodes":
                    variables[key] = value

        # --- Context-specific variables ---
        if context.discussion_id:
            variables['Discussion_Id'] = context.discussion_id
            variables['time_context_summary'] = self.timestamp_service.get_time_context_summary(context.discussion_id)
        else:
            variables['Discussion_Id'] = ''
            variables['time_context_summary'] = ''

        # --- Conversation history variables ---
        if context.messages:
            prompt_configurations = self.generate_conversation_turn_variables(
                originalMessages=context.messages,
                llm_handler=context.llm_handler,
                remove_all_system_override=remove_all_system_override
            )
            variables.update(prompt_configurations)

            variables.update(format_system_prompts(
                messages=context.messages,
                llm_handler=context.llm_handler,
                chat_prompt_template_name=get_chat_template_name()
            ))

        # --- Inter-node variables ({agentXInput} and {agentXOutput}) ---
        variables.update(context.agent_outputs or {})

        # --- Inter-node input variables ({agentXInput}) ---
        if context.agent_inputs:
            variables.update(context.agent_inputs)

        # --- Other dynamic attributes ---
        variables.update(self.extract_additional_attributes())

        return variables

    def extract_additional_attributes(self) -> Dict[str, Any]:
        """
        Extracts a predefined list of category attributes from the instance.

        Returns:
            Dict[str, Any]: A dictionary of category-related attributes.
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
        Sets category-related instance attributes from keyword arguments.

        Args:
            **kwargs (Any): The keyword arguments passed to the constructor.
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
                                             remove_all_system_override) -> Dict[str, str]:
        """
        Generates variables for different slices of the conversation history.

        Creates both raw string versions and LLM-templated versions for the
        last 1, 2, 3, 4, 5, 10, and 20 turns of the conversation.

        Args:
            originalMessages (List[Dict[str, str]]): The conversation history.
            llm_handler (Any): The LLM handler instance for templating.
            remove_all_system_override (Any): Override flag for system message removal.

        Returns:
            Dict[str, str]: A dictionary of all generated conversation turn variables.
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
            "chat_user_prompt_last_one": extract_last_n_turns_as_string(messages, 1,
                                                                        include_sysmes,
                                                                        remove_all_system_override)
        }

    def generate_chat_summary_variables(self, messages, discussion_id) -> Dict[str, str]:
        """
        Generates variables related to the chat summary from the MemoryService.

        Args:
            messages (List[Dict[str, str]]): The current conversation history.
            discussion_id (str): The unique ID for the current discussion.

        Returns:
            Dict[str, str]: A dictionary containing chat summary variables.
        """
        return {
            "newest_chat_summary_memories": self.memory_service.get_chat_summary_memories(messages,
                                                                                          discussion_id),
            "current_chat_summary": self.memory_service.get_current_summary(discussion_id)
        }
