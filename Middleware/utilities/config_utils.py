import json
import logging
import os

from Middleware.utilities import instance_utils

logger = logging.getLogger(__name__)


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


def get_config_property_if_exists(config_property, config_data):
    if config_data.get(config_property) and config_data.get(config_property) != "":
        return config_data.get(config_property)
    else:
        return None


def get_current_username():
    """
    Retrieves the current username from the configuration.

    :return: The current username.
    """
    if (instance_utils.USER is None):
        config_dir = str(get_root_config_directory())
        config_file = os.path.join(config_dir, 'Users', '_current-user.json')
        with open(config_file) as file:
            data = json.load(file)
        return data['currentUser']
    else:
        return instance_utils.USER


def get_user_config():
    """
    Retrieves the configuration for the current user.

    :return: The current user's configuration data.
    """
    config_dir = str(get_root_config_directory())
    current_user_name = get_current_username()
    config_path = os.path.join(config_dir, 'Users', f'{current_user_name.lower()}.json')
    with open(config_path) as file:
        config_data = json.load(file)
    return config_data


def get_config_value(key):
    """
    Retrieves a specific configuration value from the user configuration.

    :param key: The key of the configuration value to retrieve.
    :return: The value associated with the specified key.
    """
    main_config = get_user_config()
    return main_config.get(key)


def get_root_config_directory():
    """
    Gets the root directory of the Configs folder
    :return: os path of the config directory.
    """
    if (instance_utils.CONFIG_DIRECTORY is None):
        project_dir = get_project_root_directory_path()
        config_file = os.path.join(project_dir, 'Public', 'Configs')
        return config_file
    else:
        config_file = os.path.join(instance_utils.CONFIG_DIRECTORY)
        return config_file


def get_config_path(sub_directory, file_name):
    """
    Constructs the file path for a given configuration file.

    :param sub_directory: The subdirectory within the 'Public/Configs' directory.
    :param file_name: The name of the configuration file.
    :return: The full path to the configuration file.
    """
    config_dir = str(get_root_config_directory())
    config_file = os.path.join(config_dir, sub_directory, f'{file_name}.json')
    return config_file


def get_endpoint_config_path(sub_directory, file_name):
    """
    Constructs the file path for a given endpoint configuration file. Pulls subdirectory
    from the user json
    :param sub_directory: Optional subdirectory within the 'Public/Configs/Endpoints' directory.
    :param file_name: Name of the endpoint configuration file.
    :return: path to the endpoint configuration file.
    """
    return get_config_with_subdirectory("Endpoints", sub_directory, file_name)


def get_config_with_subdirectory(directory, sub_directory, file_name, secondary_subdirectory=None):
    """
    Constructs the file path for a given configuration file when there is a subdirectory.
    :param directory: The subdirectory within the 'Public/Configs/' directory.
    :param sub_directory: Subdirectory within the directory.
    :param secondary_subdirectory: Optional secondary subdirectory to come after sub_directory
    :param file_name: The name of the configuration file.
    :return: The full path to the configuration file.
    """
    config_dir = str(get_root_config_directory())
    if (not secondary_subdirectory):
        config_file = os.path.join(config_dir, directory, sub_directory, f'{file_name}.json')
    else:
        config_file = os.path.join(config_dir, directory, sub_directory, secondary_subdirectory, f'{file_name}.json')
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


def get_discussion_timestamp_file_path(discussion_id):
    """
    Constructs the file path for a discussion-related file.

    :param discussion_id: The ID of the discussion.
    :param file_name: The base name of the file.
    :return: The full path to the discussion file.
    """
    directory = get_config_value('discussionDirectory')
    return os.path.join(directory, f'{discussion_id}_timestamps.json')


def get_custom_dblite_filepath():
    """
    Pulls the custom directory to put the dblite values, if specified.

    :return: The full path to the discussion file.
    """
    directory = get_config_value('sqlLiteDirectory')
    if (directory is None):
        return get_project_root_directory_path()
    else:
        return str(os.path.join(directory))


def get_application_port():
    """
    Retrieves the expected port for the application from the user configuration.

    :return: The port on which the API should run.
    """
    return get_config_value('port')


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


def get_discussion_id_workflow_name():
    """
    Retrieves the name of the discussion ID workflow.

    :return: The name of the discussion ID workflow.
    """
    return get_config_value('discussionIdMemoryFileWorkflowSettings')


def get_chat_template_name():
    """
    Retrieves the name of the active chat prompt template.

    :return: The name of the active chat prompt template.
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


def get_endpoint_subdirectory():
    """
    Retrieves the subdirectory that the endpoints for this user are at

    :return: The name of the active chat prompt template.
    """
    sub_directory = get_config_value('endpointConfigsSubDirectory')
    if sub_directory:
        return sub_directory
    else:
        return ""


def get_preset_subdirectory_override():
    """
    Retrieves the name of the active chat prompt template.

    :return: The name of the active chat prompt template.
    """
    sub_directory = get_config_value('presetConfigsSubDirectoryOverride')
    if sub_directory:
        return sub_directory
    else:
        return get_current_username()


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


def get_openai_preset_path(config_name, type="OpenAiCompatibleApis", use_subdirectory=False):
    """
    Retrieves the file path to a preset configuration file.

    :param config_name: The name of the preset configuration.
    :param type: The subdirectory within presets, generally named by the ApiType
    :param use_subdirectory: Specifies whether to include one more sublevel of username after
    :return: The full path to the preset configuration file.
    """
    if (use_subdirectory):
        subdirectory = get_preset_subdirectory_override()
        return get_config_with_subdirectory("Presets", type, config_name, subdirectory)
    else:
        return get_config_with_subdirectory("Presets", type, config_name)


def get_endpoint_config(endpoint):
    """
    Retrieves the endpoint configuration based on the endpoint name.

    :param endpoint: The name of the endpoint configuration.
    :return: The full path to the endpoint configuration file.
    """
    sub_directory = get_endpoint_subdirectory()
    config = get_endpoint_config_path(sub_directory, endpoint)
    return load_config(config)


def get_api_type_config(api_type):
    """
    Retrieves the endpoint configuration based on the endpoint name.

    :param api_type: The name of the api_type configuration.
    :return: The full path to the endpoint configuration file.
    """
    api_type_file = get_config_path('ApiTypes', api_type)
    return load_config(api_type_file)


def get_template_config_path(template_file_name):
    """
    Constructs the file path for a prompt template configuration file.

    :param template_file_name: The base name of the prompt template configuration file.
    :return: The full path to the prompt template configuration file.
    """
    return get_config_path('PromptTemplates', template_file_name)


def load_template_from_json(template_file_name):
    """
    Loads a prompt template from a JSON configuration file.

    :param template_file_name: The base name of the prompt template configuration file.
    :return: The loaded prompt template data.
    """
    config_path = get_template_config_path(template_file_name)
    return load_config(config_path)


def get_workflow_path(workflow_name):
    """
    Retrieves the file path to a workflow configuration file.

    :param workflow_name: The name of the workflow configuration.
    :return: The full path to the workflow configuration file.
    """
    user_name = get_current_username()
    config_dir = str(get_root_config_directory())
    config_file = os.path.join(config_dir, 'Workflows', user_name, f'{workflow_name}.json')
    return config_file


def get_discussion_id_workflow_path():
    """
    Retrieves the file path to the discussion ID workflow.

    :return: The full path to the discussion ID workflow.
    """
    workflow_name = get_discussion_id_workflow_name()
    return get_workflow_path(workflow_name)


def get_discussion_memory_file_path(discussion_id):
    """
    Retrieves the file path for a discussion's memory file.

    :param discussion_id: The ID of the discussion.
    :return: The full path to the discussion's memory file.
    """
    result = get_discussion_file_path(discussion_id, 'memories')
    logger.debug("Getting discussion id path: %s", result)
    return result


def get_discussion_chat_summary_file_path(discussion_id):
    """
    Retrieves the file path for a discussion's chat summary file.

    :param discussion_id: The ID of the discussion.
    :return: The full path to the discussion's chat summary file.
    """
    return get_discussion_file_path(discussion_id, 'chat_summary')


def get_is_streaming() -> bool:
    """
    Retrieves the stream configuration setting.

    :return: The stream setting from the user configuration.
    """
    data = get_user_config()
    return data['stream']


def get_is_chat_complete_add_user_assistant() -> bool:
    """
    Retrieves the chat completion configuration setting.

    :return: The chat completion add user assistant setting from the user configuration.
    """
    data = get_user_config()
    return data['chatCompleteAddUserAssistant']


def get_is_chat_complete_add_missing_assistant() -> bool:
    """
    Retrieves the chat completion configuration setting.

    :return: The chat completion add missing assistant setting from the user configuration.
    """
    data = get_user_config()
    return data['chatCompletionAddMissingAssistantGenerator']


def get_use_file_logging() -> bool:
    """
    Retrieves the useFileLogging configuration setting.
    If true, Wilmer logs to a file in addition to the console.

    :return: The useFileLogging setting from the user configuration.
    """
    return get_config_value('useFileLogging')