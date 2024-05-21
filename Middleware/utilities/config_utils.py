import json
import os


def get_project_root_directory_path():
    """
    Retrieves the path to the project's root directory.

    :return: The path to the project's root directory.
    """
    util_dir = os.path.dirname(os.path.abspath(__file__))
    middleware_dir = os.path.dirname(util_dir)
    project_dir = os.path.dirname(middleware_dir)
    return project_dir


def load_config(config_file):
    """
    Loads a configuration file.

    :param config_file: The path to the configuration file.
    :return: The loaded configuration data.
    """
    with open(config_file) as f:
        config_data = json.load(f)
    return config_data


def get_user_config():
    """
    Retrieves the configuration for the current user.

    :return: The current user's configuration data.
    """
    project_dir = get_project_root_directory_path()
    config_file = os.path.join(project_dir, 'Public', 'Configs', 'Users', '_current-user.json')
    with open(config_file) as file:
        data = json.load(file)
    current_user_name = data['currentUser']
    config_path = os.path.join(project_dir, 'Public', 'Configs', 'Users', f'{current_user_name.lower()}.json')
    with open(config_path) as file:
        config_data = json.load(file)
    return config_data


def get_config_value(key):
    """
    Retrieves a specific configuration value from the WilmerAI configuration.

    :param key: The key of the configuration value to retrieve.
    :return: The value associated with the specified key.
    """
    main_config = get_user_config()
    return main_config.get(key)


def get_config_path(sub_directory, file_name):
    """
    Constructs the file path for a given configuration file.

    :param sub_directory: The subdirectory within the 'Public/Configs' directory.
    :param file_name: The name of the configuration file.
    :return: The full path to the configuration file.
    """
    project_dir = get_project_root_directory_path()
    config_file = os.path.join(project_dir, 'Public', 'Configs', sub_directory, f'{file_name}.json')
    return config_file


def get_preset_config_path(sub_directory, file_name):
    """
    Constructs the file path for a given preset configuration file.

    :param sub_directory: The subdirectory within the 'Public/Configs/Presets' directory.
    :param file_name: The name of the configuration file.
    :return: The full path to the configuration file.
    """
    project_dir = get_project_root_directory_path()
    config_file = os.path.join(project_dir, 'Public', 'Configs', 'Presets', sub_directory, f'{file_name}.json')
    return config_file


def get_discussion_file_path(discussion_id, file_name):
    """
    Constructs the file path for a discussion-related file.

    :param discussion_id: The ID of the discussion.
    :param file_name: The base name of the file.
    :return: The full path to the discussion file.
    """
    directory = get_config_value('discussionDirectory')
    return os.path.join(directory, f'{discussion_id}_{file_name}.json')


# The following functions are now simplified using the above helper functions.

def get_custom_workflow_is_active():
    """
    Determines if the custom workflow override is active.

    :return: True if the custom workflow is active, False otherwise.
    """
    return get_config_value('customWorkflowOverride')


def get_default_parallel_processor_name():
    """
    Retrieves the name of the default parallel processor workflow.

    :return: The name of the default parallel processor workflow.
    """
    return get_config_value('defaultParallelProcessWorkflow')


def get_oversized_prompt_workflow_name():
    """
    Retrieves the name of the workflow for oversized prompts.

    :return: The name of the oversized prompt workflow.
    """
    return get_config_value('oversizedPromptWorkflow')


def get_chat_template_name():
    """
    Retrieves the name of the active chat prompt template_name.

    :return: The name of the active chat prompt template_name.
    """
    return get_config_value('chatPromptTemplateName')


def get_active_categorization_workflow_name():
    """
    Retrieves the name of the active categorization workflow.

    :return: The name of the active categorization workflow.
    """
    return get_config_value('categorizationWorkflow')


def get_active_custom_workflow_name():
    """
    Retrieves the name of the active custom workflow.

    :return: The name of the active custom workflow.
    """
    return get_config_value('customWorkflow')


def get_active_conversational_memory_tool_name():
    """
    Retrieves the name of the active conversational memory tool workflow.

    :return: The name of the active conversational memory tool workflow.
    """
    return get_config_value('conversationMemoryToolWorkflow')


def get_active_recent_memory_tool_name():
    """
    Retrieves the name of the active recent memory tool workflow.

    :return: The name of the active recent memory tool workflow.
    """
    return get_config_value('recentMemoryToolWorkflow')


def get_file_memory_tool_name():
    """
    Retrieves the name of the active file memory tool workflow.

    :return: The name of the active file memory tool workflow.
    """
    return get_config_value('fileMemoryToolWorkflow')


def get_chat_summary_tool_workflow_name():
    """
    Retrieves the name of the active chat summary tool workflow.

    :return: The name of the active chat summary tool workflow.
    """
    return get_config_value('chatSummaryToolWorkflow')


def get_categories_config():
    """
    Retrieves the categories configuration.

    :return: The categories configuration data.
    """
    routing_config = get_config_value('routingConfig')
    config_path = get_config_path('Routing', routing_config)
    return load_config(config_path)


def get_model_config_path(config_name):
    """
    Retrieves the file path to a model configuration file based on the endpoint name.

    :param config_name: The name of the endpoint configuration.
    :return: The full path to the model configuration file.
    """
    endpoint_config = get_config_path('Endpoints', config_name)
    endpoint_data = load_config(endpoint_config)
    model_config_path = get_config_path('ModelsConfigs', endpoint_data['modelName'])
    return model_config_path


def get_openai_preset_path(config_name):
    """
    Retrieves the file path to a preset configuration file.

    :param config_name: The name of the preset configuration.
    :return: The full path to the preset configuration file.
    """

    return get_preset_config_path("OpenAiCompatibleApis", config_name)


def get_endpoint_config(endpoint):
    """
    Retrieves the endpoint configuration based on the endpoint name.

    :param endpoint: The name of the endpoint configuration.
    :return: The full path to the endpoint configuration file.
    """
    endpoint_file = get_config_path('Endpoints', endpoint)
    return load_config(endpoint_file)


def get_template_config_path(template_file_name):
    """
    Constructs the file path for a prompt template_name configuration file.

    :param template_file_name: The base name of the prompt template_name configuration file.
    :return: The full path to the prompt template_name configuration file.
    """
    project_root = get_project_root_directory_path()
    config_file = get_config_path('PromptTemplates', template_file_name)
    return config_file


def load_template_from_json(template_file_name):
    """
    Loads a prompt template_name from a JSON configuration file.

    :param template_file_name: The base name of the prompt template_name configuration file.
    :return: The loaded prompt template_name data.
    """
    config_path = get_template_config_path(template_file_name)
    return load_config(config_path)


def get_workflow_path(workflow_name):
    """
    Retrieves the file path to a workflow configuration file.

    :param workflow_name: The name of the workflow configuration.
    :return: The full path to the workflow configuration file.
    """
    return get_config_path('Workflows', workflow_name)


def get_autoremove_strings():
    """
    Retrieves the list of strings to be automatically removed from prompts.

    :return: A list of autoremove strings.
    """
    return get_config_value('autoremove_strings')


def get_stop_strings():
    """
    Retrieves the list of stop strings for LLM processing.

    :return: A list of stop strings.
    """
    return get_config_value('stop_strings')


def get_discussion_memory_file_path(discussion_id):
    """
    Retrieves the file path for a discussion's memory file.

    :param discussion_id: The ID of the discussion.
    :return: The full path to the discussion's memory file.
    """
    return get_discussion_file_path(discussion_id, 'memories')


def get_discussion_chat_summary_file_path(discussion_id):
    """
    Retrieves the file path for a discussion's chat summary file.

    :param discussion_id: The ID of the discussion.
    :return: The full path to the discussion's chat summary file.
    """
    return get_discussion_file_path(discussion_id, 'chat_summary')


def get_routing_config():
    routing_config = get_categories_config()
