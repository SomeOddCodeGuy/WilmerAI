# /Middleware/services/prompt_categorization_service.py

import json
import string
from typing import List, Dict, Union, Generator

from Middleware.utilities.config_utils import get_active_categorization_workflow_name, get_categories_config
from Middleware.workflows.managers.workflow_manager import WorkflowManager, logger


class PromptCategorizationService:
    """
    Categorizes incoming prompts to route them to the appropriate workflow.
    """

    @staticmethod
    def conversational_method(messages: List[Dict[str, str]], request_id: str, discussion_id: str = None,
                              stream: bool = False) -> Union[
        Generator[str, None, None], str, None]:
        """
        Runs the default conversational workflow.

        Args:
            messages (List[Dict[str, str]]): The list of messages in the conversation.
            request_id (str): The unique identifier for the request.
            discussion_id (str): The identifier for the conversation.
            stream (bool): Flag indicating if the output should be streamed.

        Returns:
            Union[Generator[str, None, None], str, None]: The result of the workflow execution.
        """
        return WorkflowManager.run_custom_workflow(
            workflow_name='_DefaultWorkflow',
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            is_streaming=stream
        )

    @staticmethod
    def _configure_workflow_manager(category_data: Dict) -> WorkflowManager:
        """
        Configures a WorkflowManager with categorization data.

        This direct instantiation is necessary to inject category variables
        into the workflow via keyword arguments.

        Args:
            category_data (Dict): The category data to be injected.

        Returns:
            WorkflowManager: A configured instance of the WorkflowManager.
        """
        return WorkflowManager(workflow_config_name=get_active_categorization_workflow_name(), **category_data)

    def __init__(self):
        """
        Initializes the PromptCategorizationService instance.
        """
        self.routes = {}
        self.categories = {}
        self.initialize()

    def initialize(self):
        """
        Loads and initializes routing categories from the configuration file.
        """
        try:
            routing_config = get_categories_config()
            for category, info in routing_config.items():
                workflow_name = info['workflow']
                description = info['description']
                self._add_category(category, workflow_name, description)
        except FileNotFoundError:
            logger.warning("Routing configuration file not found.")
            raise
        except json.JSONDecodeError:
            logger.warning("Error decoding JSON from routing configuration file.")
            raise

    def get_prompt_category(self, messages: List[Dict[str, str]], request_id: str, discussion_id: str = None,
                            stream: bool = False) -> \
            Union[Generator[str, None, None], str, None]:
        """
        Gets the prompt category and executes the corresponding workflow.

        Args:
            messages (List[Dict[str, str]]): The conversation history to be categorized.
            request_id (str): The unique identifier for the request.
            discussion_id (str): The identifier for the conversation.
            stream (bool): Flag indicating if the output should be streamed.

        Returns:
            Union[Generator[str, None, None], str, None]: The result of the routed workflow execution.
        """
        category = self._categorize_request(messages, request_id)
        logger.info("Category: %s", category)

        if category in self.categories:
            logger.debug("Response initiated")
            workflow_name = self.categories[category]['workflow']
            workflow = WorkflowManager(workflow_config_name=workflow_name)
            return workflow.run_workflow(messages=messages, request_id=request_id, discussionId=discussion_id,
                                         stream=stream)
        else:
            logger.debug("Default response initiated")
            return self.conversational_method(messages, request_id, discussion_id, stream)

    def _initialize_categories(self) -> Dict[str, Union[str, List[str]]]:
        """
        Prepares category data for dynamic injection into workflow prompts.

        Returns:
            Dict[str, Union[str, List[str]]]: A dictionary of formatted strings and lists
            derived from the loaded category configurations.
        """
        category_colon_description = [f"{cat}: {info['description']}" for cat, info in self.categories.items()]
        category_descriptions = [info['description'] for info in self.categories.values()]
        category_list = list(self.categories.keys())

        return {
            'category_colon_descriptions': '; '.join(category_colon_description),
            'category_colon_descriptions_newline_bulletpoint': "\n- " + '\n- '.join(category_colon_description),
            'categoriesSeparatedByOr': ' or '.join(category_list),
            'categoryNameBulletpoints': "\n- " + '\n- '.join(category_list),
            'category_list': category_list,
            'category_descriptions': category_descriptions
        }

    def _match_category(self, processed_input: str) -> Union[str, None]:
        """
        Matches a processed string output from an LLM to a configured category.

        Args:
            processed_input (str): The cleaned output string from the categorization LLM.

        Returns:
            Union[str, None]: The matched category key, or None if no match is found.
        """
        for word in processed_input.split():
            for key in self.categories.keys():
                if key.upper() in word.upper():
                    return key
        return None

    def _categorize_request(self, messages: List[Dict[str, str]], request_id: str) -> str:
        """
        Determines the request category by executing the categorization workflow.

        This method runs the categorization workflow, processes the LLM's output,
        and attempts to match it to a known category, retrying on failure.

        Args:
            messages (List[Dict[str, str]]): The conversation history to be categorized.
            request_id (str): The unique identifier for the request.

        Returns:
            str: The matched category name, or 'UNKNOWN' if no match is found after retries.
        """
        logger.info("Categorizing request")
        category_data = self._initialize_categories()
        workflow_manager = self._configure_workflow_manager(category_data)
        attempts = 0

        while attempts < 4:
            workflow_result = workflow_manager.run_workflow(
                messages=messages,
                request_id=request_id,
                nonResponder=True,
                stream=False
            )
            raw_category_output = workflow_result

            if raw_category_output is None:
                logger.warning("Categorization workflow returned None. Assigning empty string.")
                category = "UNKNOWN"
            else:
                category = raw_category_output.strip()

            logger.info("\n\n*****************************************************************************\n")
            logger.info("\n\nOutput from the LLM: %s", category)
            logger.info("\n*****************************************************************************\n\n")
            logger.debug(self.categories)

            category = category.translate(str.maketrans('', '', string.punctuation))
            matched_category = self._match_category(category)

            if matched_category is not None:
                return matched_category
            attempts += 1

        return "UNKNOWN"

    def _add_category(self, category: str, workflow_name: str, description: str):
        """
        Adds a new category and its associated workflow and description.

        Args:
            category (str): The name of the category.
            workflow_name (str): The workflow to be run for this category.
            description (str): The category's description, used in prompts.
        """
        self.categories[category] = {"workflow": workflow_name, "description": description}
