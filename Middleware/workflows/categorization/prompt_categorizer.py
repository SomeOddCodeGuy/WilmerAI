import json
import string

from Middleware.utilities.config_utils import get_active_categorization_workflow_name, get_categories_config
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns
from Middleware.workflows.managers.workflow_manager import WorkflowManager


class PromptCategorizer:
    @staticmethod
    def conversational_method(prompt, stream=False):
        return WorkflowManager(workflow_config_name='_DefaultWorkflow').run_workflow(prompt, stream=stream)

    @staticmethod
    def _configure_workflow_manager(category_data):
        return WorkflowManager(workflow_config_name=get_active_categorization_workflow_name(), **category_data)

    def __init__(self):
        self.routes = {}
        self.categories = {}
        self.initialize()

    def initialize(self):
        try:
            routing_config = get_categories_config()

            for category, info in routing_config.items():
                workflow_name = info['workflow']
                description = info['description']
                self._add_category(category, workflow_name, description)

        except FileNotFoundError:
            print("Routing configuration file not found.")
        except json.JSONDecodeError:
            print("Error decoding JSON from routing configuration file.")

    def get_prompt_category(self, prompt, stream):
        # Let's grab the last 2 user/assistant pair turns
        # to ask the LLM to categorize the request on. That amount
        # of history should be enough
        most_recent_turns = extract_last_n_turns(prompt, 2)

        category = self._categorize_request(most_recent_turns)
        print("Category: ", category)

        # Now that we have the category (hopefully?) we can send them off
        # to the appropriate workflow!
        if category in self.categories:
            print("Response initiated")
            workflow_name = self.categories[category]['workflow']  # Extract the workflow name
            workflow = WorkflowManager(workflow_config_name=workflow_name)
            return workflow.run_workflow(prompt, stream=stream)
        else:
            print("Default response initiated")
            return self.conversational_method(prompt, stream)

    def _initialize_categories(self):
        category_colon_description = [f"{cat}: {info['description']}" for cat, info in self.categories.items()]
        category_descriptions = [info['description'] for info in self.categories.values()]
        category_list = list(self.categories.keys())

        return {'category_colon_descriptions': '; '.join(category_colon_description),
                'categoriesSeparatedByOr': ' or '.join(category_list), 'category_list': category_list,
                'category_descriptions': category_descriptions}

    def _match_category(self, processed_input):
        for word in processed_input.split():
            for key in self.categories.keys():
                if key.upper() in word.upper():
                    return key
        return None

    def _categorize_request(self, user_request):
        category_data = self._initialize_categories()
        workflow_manager = self._configure_workflow_manager(category_data)
        attempts = 0

        while attempts < 4:
            category = workflow_manager.run_workflow(user_request).strip()
            print("Output from the LLM: " + category)
            print(self.categories)
            category = category.translate(str.maketrans('', '', string.punctuation))
            matched_category = self._match_category(category)

            if matched_category is not None:
                return matched_category
            attempts += 1

        return "UNKNOWN"

    def _add_category(self, category, workflow_name, description):
        self.categories[category] = {"workflow": workflow_name, "description": description}

    def _remove_category(self, category):
        if category in self.categories:
            del self.categories[category]
