import json
import string

from Middleware.utilities.config_utils import get_active_categorization_workflow_name, get_categories_config
from Middleware.workflows.managers.workflow_manager import WorkflowManager, logger


class PromptCategorizer:
    """
    A class to categorize incoming prompts and route them to the appropriate workflow.
    """

    @staticmethod
    def conversational_method(prompt, request_id, discussion_id: str = None, stream=False):
        """
        Run the default conversational workflow.

        Args:
            prompt (str): The input prompt to categorize.
            stream (bool): Whether to stream the output. Default is False.

        Returns:
            str: The result of the workflow execution.
        """
        return WorkflowManager(workflow_config_name='_DefaultWorkflow').run_workflow(prompt, request_id,
                                                                                     discussionId=discussion_id,
                                                                                     stream=stream)

    @staticmethod
    def _configure_workflow_manager(category_data):
        """
        Configure a WorkflowManager with the active categorization workflow name and category data.

        Args:
            category_data (dict): The category data to pass to the WorkflowManager.

        Returns:
            WorkflowManager: Configured WorkflowManager instance.
        """
        return WorkflowManager(workflow_config_name=get_active_categorization_workflow_name(), **category_data)

    def __init__(self):
        """
        Initialize a PromptCategorizer instance.
        """
        self.routes = {}
        self.categories = {}
        self.initialize()

    def initialize(self):
        """
        Initialize the categorizer with categories from the configuration file.
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

    def get_prompt_category(self, prompt, stream, request_id, discussion_id: str = None):
        """
        Get the category of the prompt and run the appropriate workflow.

        Args:
            prompt: The input prompt to categorize.
            stream: Whether to stream the output. Default is False.

        Returns:
            str: The result of the workflow execution.
        """
        category = self._categorize_request(prompt, request_id)
        logger.info("Category: %s", category)

        if category in self.categories:
            logger.debug("Response initiated")
            workflow_name = self.categories[category]['workflow']
            workflow = WorkflowManager(workflow_config_name=workflow_name)
            return workflow.run_workflow(prompt, request_id, discussionId=discussion_id, stream=stream)
        else:
            logger.debug("Default response initiated")
            return self.conversational_method(prompt, request_id, discussion_id, stream)

    def _initialize_categories(self):
        """
        Initialize and return the category data.

        Returns:
            dict: A dictionary containing category descriptions and lists.
        """
        category_colon_description = [f"{cat}: {info['description']}" for cat, info in self.categories.items()]
        category_descriptions = [info['description'] for info in self.categories.values()]
        category_list = list(self.categories.keys())

        return {
            'category_colon_descriptions': '; '.join(category_colon_description),
            'categoriesSeparatedByOr': ' or '.join(category_list),
            'category_list': category_list,
            'category_descriptions': category_descriptions
        }

    def _match_category(self, processed_input):
        """
        Match the processed input to a category.

        Args:
            processed_input (str): The processed input string.

        Returns:
            str or None: The matched category or None if no match is found.
        """
        for word in processed_input.split():
            for key in self.categories.keys():
                if key.upper() in word.upper():
                    return key
        return None

    def _categorize_request(self, user_request, request_id):
        """
        Categorize the user's request by running the categorization workflow.

        Args:
            user_request (str): The user's request to categorize.

        Returns:
            str: The matched category or 'UNKNOWN' if no match is found.
        """
        logger.info("Categorizing request")
        category_data = self._initialize_categories()
        workflow_manager = self._configure_workflow_manager(category_data)
        attempts = 0

        while attempts < 4:
            category = workflow_manager.run_workflow(user_request, request_id, nonResponder=True).strip()
            logger.info(
                "\n\n*****************************************************************************\n")
            logger.info("\n\nOutput from the LLM: %s", category)
            logger.info(
                "\n*****************************************************************************\n\n")
            logger.debug(self.categories)
            category = category.translate(str.maketrans('', '', string.punctuation))
            matched_category = self._match_category(category)

            if matched_category is not None:
                return matched_category
            attempts += 1

        return "UNKNOWN"

    def _add_category(self, category, workflow_name, description):
        """
        Add a category to the categorizer.

        Args:
            category (str): The category name.
            workflow_name (str): The workflow associated with the category.
            description (str): The description of the category.
        """
        self.categories[category] = {"workflow": workflow_name, "description": description}
