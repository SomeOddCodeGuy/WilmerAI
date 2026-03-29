# /Middleware/utilities/config_utils.py

import json
import logging
import os

from Middleware.common import instance_global_variables

logger = logging.getLogger(__name__)


def get_project_root_directory_path():
    """
    Retrieves the path to the project's root directory.

    This function calculates the path to the project's root directory
    by navigating up the file system from the location of the current script.

    Returns:
        str: The absolute path to the project's root directory.
    """
    util_dir = os.path.dirname(os.path.abspath(__file__))
    middleware_dir = os.path.dirname(util_dir)
    project_dir = os.path.dirname(middleware_dir)
    return project_dir


def load_config(config_file):
    """
    Loads a configuration file.

    This function opens and reads a JSON configuration file from the specified path.

    Args:
        config_file (str): The absolute path to the configuration file.

    Returns:
        dict: The loaded configuration data as a dictionary.
    """
    with open(config_file) as f:
        config_data = json.load(f)
    return config_data


def get_config_property_if_exists(config_property, config_data):
    """
    Retrieves a property from a configuration dictionary if it exists and is not empty.

    Args:
        config_property (str): The key for the property to retrieve.
        config_data (dict): The dictionary containing the configuration data.

    Returns:
        str or None: The value of the property if it exists and is not an empty string, otherwise None.
    """
    # Handle cases where config_data might be None
    if config_data is None:
        return None
    if config_data.get(config_property) and config_data.get(config_property) != "":
        return config_data.get(config_property)
    else:
        return None


def get_current_username():
    """
    Retrieves the current username from the application configuration.

    Checks the following in order:
    1. Request-scoped user (set from the model field for multi-user mode)
    2. USERS list has exactly one entry (single-user mode) -- return that entry
    3. USERS list has multiple entries but no request user -- raise RuntimeError
    4. USERS is None -- fall back to _current-user.json (legacy, no --User arg)

    Returns:
        str: The name of the current user.

    Raises:
        RuntimeError: If multiple users are configured but no request-scoped
            user has been set. This prevents silent cross-user data leaks.
    """
    request_user = instance_global_variables.get_request_user()
    if request_user:
        return request_user
    users = instance_global_variables.USERS
    if users is not None:
        if len(users) == 1:
            return users[0]
        raise RuntimeError(
            f"Multi-user mode active with {len(users)} users but no request-scoped user set. "
            f"This is a bug -- every request must identify a user. "
            f"Configured users: {users}"
        )
    config_dir = str(get_root_config_directory())
    config_file = os.path.join(config_dir, 'Users', '_current-user.json')
    with open(config_file) as file:
        data = json.load(file)
    return data['currentUser']


def get_user_config_for(username):
    """
    Retrieves the configuration for a specific user by name.

    Args:
        username (str): The username whose config to load.

    Returns:
        dict: The specified user's configuration data.
    """
    config_dir = str(get_root_config_directory())
    config_path = os.path.join(config_dir, 'Users', f'{username.lower()}.json')
    with open(config_path) as file:
        config_data = json.load(file)
    return config_data


def get_user_config():
    """
    Retrieves the configuration for the current user.

    This function determines the current user and loads their specific
    configuration JSON file from the 'Public/Configs/Users' directory.

    Returns:
        dict: The current user's configuration data.
    """
    return get_user_config_for(get_current_username())


def get_config_value(key):
    """
    Retrieves a specific configuration value from the user configuration.

    This function loads the current user's configuration and returns the
    value associated with the provided key.

    Args:
        key (str): The key of the configuration value to retrieve.

    Returns:
        Any: The value associated with the specified key.
    """
    main_config = get_user_config()
    return main_config.get(key)


def get_root_config_directory():
    """
    Gets the root directory of the `Configs` folder.

    This function checks for a globally set configuration directory. If it
    doesn't exist, it constructs the path to the `Public/Configs` directory
    based on the project's root.

    Returns:
        str: The absolute path to the root `Configs` directory.
    """
    if (instance_global_variables.CONFIG_DIRECTORY is None):
        project_dir = get_project_root_directory_path()
        config_file = os.path.join(project_dir, 'Public', 'Configs')
        return config_file
    else:
        config_file = os.path.join(instance_global_variables.CONFIG_DIRECTORY)
        return config_file


def get_config_path(sub_directory, file_name):
    """
    Constructs the file path for a given configuration file.

    This function builds the full path to a configuration file located within
    a subdirectory of the `Public/Configs` directory.

    Args:
        sub_directory (str): The subdirectory within the `Public/Configs` directory
                             (e.g., 'Routing', 'ApiTypes').
        file_name (str): The base name of the configuration file (without the `.json` extension).

    Returns:
        str: The full path to the configuration file.
    """
    config_dir = str(get_root_config_directory())
    config_file = os.path.join(config_dir, sub_directory, f'{file_name}.json')
    return config_file


def get_endpoint_config_path(sub_directory, file_name):
    """
    Constructs the file path for a given endpoint configuration file.

    This function builds the full path to an endpoint configuration file,
    using a provided subdirectory within the 'Endpoints' directory.

    Args:
        sub_directory (str): The subdirectory within the `Public/Configs/Endpoints` directory.
        file_name (str): The name of the endpoint configuration file.

    Returns:
        str: The full path to the endpoint configuration file.
    """
    return get_config_with_subdirectory("Endpoints", sub_directory, file_name)


def get_config_with_subdirectory(directory, sub_directory, file_name, secondary_subdirectory=None):
    """
    Constructs the file path for a configuration file, including one or two subdirectories.

    This function is a general utility for building file paths within the
    `Public/Configs` directory, allowing for one or two levels of subdirectories.

    Args:
        directory (str): The main subdirectory within the 'Public/Configs/' directory
                         (e.g., 'Presets', 'Workflows').
        sub_directory (str): The first level of subdirectory.
        file_name (str): The name of the configuration file (without the `.json` extension).
        secondary_subdirectory (str, optional): An optional second level of subdirectory.

    Returns:
        str: The full path to the configuration file.
    """
    config_dir = str(get_root_config_directory())
    if (not secondary_subdirectory):
        config_file = os.path.join(config_dir, directory, sub_directory, f'{file_name}.json')
    else:
        config_file = os.path.join(config_dir, directory, sub_directory, secondary_subdirectory, f'{file_name}.json')
    return config_file


def get_discussion_file_path(discussion_id, file_name, api_key_hash=None):
    """
    Constructs the file path for a discussion-related file.

    This function uses the discussion directory specified in the user config
    to build a file path for a specific discussion ID and file name. If the
    configured directory is empty, missing, or cannot be created on the
    current platform, it falls back to ``Public/DiscussionIds/`` under the
    project root.

    When ``api_key_hash`` is provided, files are stored under a per-user
    subdirectory::

        {discussionDirectory}/{api_key_hash}/{discussion_id}/{file_name}.json

    Without an API key hash, the layout is::

        {discussionDirectory}/{discussion_id}/{file_name}.json

    For backwards compatibility, if the nested file does not exist but a
    legacy flat file (``{discussionDirectory}/{discussion_id}_{file_name}.json``)
    does, the legacy path is returned instead. New files are always created
    in the nested structure.

    Args:
        discussion_id (str): The ID of the discussion.
        file_name (str): The base name of the file (e.g., 'memories', 'chat_summary').
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation. Defaults to None.

    Returns:
        str: The full path to the discussion file.

    Raises:
        ValueError: If discussion_id is None.
    """
    if discussion_id is None:
        raise ValueError("discussion_id is required for discussion file path construction")
    directory = get_config_value('discussionDirectory')
    if directory:
        if api_key_hash:
            discussion_dir = os.path.join(directory, api_key_hash, discussion_id)
        else:
            discussion_dir = os.path.join(directory, discussion_id)
        try:
            os.makedirs(discussion_dir, exist_ok=True)
        except OSError:
            logger.warning("Configured discussionDirectory '%s' could not be created, using default.", directory)
            directory = None

    if not directory:
        directory = os.path.join(get_project_root_directory_path(), 'Public', 'DiscussionIds')
        if api_key_hash:
            discussion_dir = os.path.join(directory, api_key_hash, discussion_id)
        else:
            discussion_dir = os.path.join(directory, discussion_id)
        os.makedirs(discussion_dir, exist_ok=True)

    nested_path = os.path.join(discussion_dir, f'{file_name}.json')
    if not os.path.exists(nested_path) and not api_key_hash:
        legacy_path = os.path.join(directory, f'{discussion_id}_{file_name}.json')
        if os.path.exists(legacy_path):
            logger.info("Using legacy discussion file: %s", legacy_path)
            return legacy_path

    return nested_path


def get_discussion_timestamp_file_path(discussion_id, api_key_hash=None):
    """
    Constructs the file path for a discussion's timestamp file.

    This function delegates to ``get_discussion_file_path`` so that
    timestamps benefit from the same per-user directory isolation and
    legacy-fallback logic as all other discussion files.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation. Defaults to None.

    Returns:
        str: The full path to the discussion's timestamp file.
    """
    return get_discussion_file_path(discussion_id, 'timestamps', api_key_hash=api_key_hash)


def get_custom_dblite_filepath():
    """
    Retrieves the custom directory path for SQLite databases.

    This function checks the user configuration for a custom SQLite directory.
    If none is specified, it returns the project's root directory.

    Returns:
        str: The absolute path to the directory for SQLite databases.
    """
    directory = get_config_value('sqlLiteDirectory')
    if (directory is None):
        return get_project_root_directory_path()
    else:
        return str(os.path.join(directory))


def get_application_port():
    """
    Retrieves the port on which the application should run.

    This function retrieves the 'port' setting from the current user's
    configuration.

    Returns:
        int: The port number for the API server.
    """
    return get_config_value('port')


def get_custom_workflow_is_active():
    """
    Determines if a custom workflow override is enabled.

    This function checks the 'customWorkflowOverride' setting in the user
    configuration.

    Returns:
        bool: True if a custom workflow is active, False otherwise.
    """
    return get_config_value('customWorkflowOverride')


def get_allow_shared_workflows() -> bool:
    """
    Determines if shared workflows should be listed in the models API endpoints.

    When enabled, the /v1/models and /api/tags endpoints return workflow folders
    from _shared/ as selectable models. When disabled (the default), only the
    username is returned as a model.

    Returns:
        bool: True if shared workflows should be listed, False otherwise.
    """
    value = get_config_value('allowSharedWorkflows')
    return bool(value) if value is not None else False


def get_default_parallel_processor_name():
    """
    Retrieves the name of the default parallel processor workflow.

    This function gets the 'defaultParallelProcessWorkflow' setting from the
    user configuration.

    Returns:
        str: The name of the default parallel processor workflow.
    """
    return get_config_value('defaultParallelProcessWorkflow')


def get_discussion_id_workflow_name():
    """
    Retrieves the name of the discussion ID workflow.

    This function gets the 'discussionIdMemoryFileWorkflowSettings' setting
    from the user configuration.

    Returns:
        str: The name of the discussion ID workflow.
    """
    return get_config_value('discussionIdMemoryFileWorkflowSettings')


def get_chat_template_name():
    """
    Retrieves the name of the active chat prompt template.

    This function gets the 'chatPromptTemplateName' setting from the
    user configuration.

    Returns:
        str: The name of the active chat prompt template.
    """
    return get_config_value('chatPromptTemplateName')


def get_active_categorization_workflow_name():
    """
    Retrieves the name of the active categorization workflow.

    This function gets the 'categorizationWorkflow' setting from the
    user configuration.

    Returns:
        str: The name of the active categorization workflow.
    """
    return get_config_value('categorizationWorkflow')


def get_active_custom_workflow_name():
    """
    Retrieves the name of the active custom workflow.

    This function gets the 'customWorkflow' setting from the user
    configuration.

    Returns:
        str: The name of the active custom workflow.
    """
    return get_config_value('customWorkflow')


def get_active_conversational_memory_tool_name():
    """
    Retrieves the name of the active conversational memory tool workflow.

    This function gets the 'conversationMemoryToolWorkflow' setting from the
    user configuration.

    Returns:
        str: The name of the active conversational memory tool workflow.
    """
    return get_config_value('conversationMemoryToolWorkflow')


def get_endpoint_subdirectory():
    """
    Retrieves the subdirectory for the user's endpoints.

    This function retrieves the `endpointConfigsSubDirectory` from the user
    configuration. It returns an empty string if the setting is not found.

    Returns:
        str: The name of the subdirectory for endpoint configurations, or an empty string.
    """
    sub_directory = get_config_value('endpointConfigsSubDirectory')
    if sub_directory:
        return sub_directory
    else:
        return ""


def get_preset_subdirectory_override():
    """
    Retrieves the subdirectory override for preset configurations.

    This function gets the 'presetConfigsSubDirectoryOverride' from the
    user configuration. If the setting is not found, it returns the current
    username as the default subdirectory.

    Returns:
        str: The name of the preset subdirectory, or the current username.
    """
    sub_directory = get_config_value('presetConfigsSubDirectoryOverride')
    if sub_directory:
        return sub_directory
    else:
        return get_current_username()


def get_active_recent_memory_tool_name():
    """
    Retrieves the name of the active recent memory tool workflow.

    This function gets the 'recentMemoryToolWorkflow' setting from the
    user configuration.

    Returns:
        str: The name of the active recent memory tool workflow.
    """
    return get_config_value('recentMemoryToolWorkflow')


def get_workflow_subdirectory_override():
    """
    Retrieves the subdirectory override for workflow configurations.

    This function gets the 'workflowConfigsSubDirectoryOverride' from the
    user configuration. If set, it returns '_overrides/<override>' to load
    workflows from a subfolder within the overrides folder.
    If not set, it returns the current username as the default subdirectory.

    Returns:
        str: The path to the workflow subdirectory ('_overrides/<override>' or username).
    """
    sub_directory = get_config_value('workflowConfigsSubDirectoryOverride')
    if sub_directory:
        return os.path.join('_overrides', sub_directory)
    else:
        return get_current_username()


def get_file_memory_tool_name():
    """
    Retrieves the name of the active file memory tool workflow.

    This function gets the 'fileMemoryToolWorkflow' setting from the
    user configuration.

    Returns:
        str: The name of the active file memory tool workflow.
    """
    return get_config_value('fileMemoryToolWorkflow')


def get_chat_summary_tool_workflow_name():
    """
    Retrieves the name of the active chat summary tool workflow.

    This function gets the 'chatSummaryToolWorkflow' setting from the
    user configuration.

    Returns:
        str: The name of the active chat summary tool workflow.
    """
    return get_config_value('chatSummaryToolWorkflow')


def get_categories_config():
    """
    Retrieves the categories configuration.

    This function gets the `routingConfig` setting from the user configuration
    and uses it to load the corresponding categories JSON file from the
    'Public/Configs/Routing' directory.

    Returns:
        dict: The loaded categories configuration data.
    """
    routing_config = get_config_value('routingConfig')
    config_path = get_config_path('Routing', routing_config)
    return load_config(config_path)


def get_openai_preset_path(config_name, type="OpenAiCompatibleApis", use_subdirectory=False):
    """
    Retrieves the file path to a preset configuration file.

    This function builds the path to a preset configuration, optionally
    including a subdirectory override.

    Args:
        config_name (str): The name of the preset configuration.
        type (str, optional): The subdirectory within `Presets`, generally named
                              by the API type. Defaults to "OpenAiCompatibleApis".
        use_subdirectory (bool, optional): Specifies whether to use a user-specific
                                           subdirectory override. Defaults to False.

    Returns:
        str: The full path to the preset configuration file.
    """
    if (use_subdirectory):
        subdirectory = get_preset_subdirectory_override()
        return get_config_with_subdirectory("Presets", type, config_name, subdirectory)
    else:
        return get_config_with_subdirectory("Presets", type, config_name)


def get_endpoint_config(endpoint):
    """
    Retrieves the endpoint configuration based on the endpoint name.

    This function gets the `endpointConfigsSubDirectory` from the user config
    and uses it to load the corresponding endpoint configuration JSON file.

    Args:
        endpoint (str): The name of the endpoint configuration.

    Returns:
        dict: The loaded endpoint configuration data.
    """
    sub_directory = get_endpoint_subdirectory()
    config = get_endpoint_config_path(sub_directory, endpoint)
    return load_config(config)


def get_api_type_config(api_type):
    """
    Retrieves the API type configuration based on the API type name.

    This function loads the API type configuration JSON file from the
    'Public/Configs/ApiTypes' directory.

    Args:
        api_type (str): The name of the API type configuration.

    Returns:
        dict: The loaded API type configuration data.
    """
    api_type_file = get_config_path('ApiTypes', api_type)
    return load_config(api_type_file)


def get_template_config_path(template_file_name):
    """
    Constructs the file path for a prompt template configuration file.

    This function builds the full path to a prompt template configuration file
    located within the 'Public/Configs/PromptTemplates' directory.

    Args:
        template_file_name (str): The base name of the prompt template configuration file.

    Returns:
        str: The full path to the prompt template configuration file.
    """
    return get_config_path('PromptTemplates', template_file_name)


def get_default_tool_prompt_path():
    """
    Constructs the file path for the default tool prompt file.

    This function builds the full path to the `default_tool_prompt.txt` file
    located in the root of the `Public/Configs` directory.

    Returns:
        str: The full path to the default tool prompt file.
    """
    config_dir = str(get_root_config_directory())
    config_file = os.path.join(config_dir, 'default_tool_prompt.txt')
    return config_file


def load_template_from_json(template_file_name):
    """
    Loads a prompt template from a JSON configuration file.

    This function first gets the file path for the specified prompt template
    and then loads the JSON data from that file.

    Args:
        template_file_name (str): The base name of the prompt template configuration file.

    Returns:
        dict: The loaded prompt template data.
    """
    config_path = get_template_config_path(template_file_name)
    return load_config(config_path)


def get_workflow_path(workflow_name, user_folder_override=None):
    """
    Retrieves the file path to a workflow configuration file.

    This function constructs the path to a workflow JSON file, located in a
    user-specific subdirectory within `Public/Configs/Workflows`.

    Args:
        workflow_name (str): The name of the workflow configuration.
        user_folder_override (str, optional): If provided, uses this folder name
                                            instead of the user's configured default. Defaults to None.

    Returns:
        str: The full path to the workflow configuration file.
    """
    if user_folder_override:
        user_name = user_folder_override
    else:
        user_name = get_workflow_subdirectory_override()
    config_dir = str(get_root_config_directory())
    config_file = os.path.join(config_dir, 'Workflows', user_name, f'{workflow_name}.json')
    return config_file


def get_shared_workflows_folder():
    """
    Retrieves the name of the shared workflows folder.

    This function checks for the 'sharedWorkflowsSubDirectoryOverride' setting
    in the user configuration. If set, returns that value. Otherwise, returns
    '_shared' as the default folder for shared workflows.

    Workflows listed by the models API endpoint and selected via the API
    model field are loaded from this folder.

    Returns:
        str: The name of the shared workflows folder (override value or '_shared').
    """
    override = get_config_value('sharedWorkflowsSubDirectoryOverride')
    if override:
        return override
    return '_shared'


def get_available_shared_workflow_folders(shared_folder_override=None):
    """
    Retrieves a list of available workflow folder names from the shared workflows folder.

    This function scans the shared workflows directory and returns a list of
    subfolder names that can be used as model identifiers in API requests.
    Each folder should contain a DefaultWorkflow.json as the entry point.

    Args:
        shared_folder_override (str, optional): If provided, uses this folder name
            instead of resolving via the current user's config. Used by multi-user
            model aggregation to list workflows for a specific user.

    Returns:
        list: A list of folder names available in the shared folder.
    """
    config_dir = str(get_root_config_directory())
    shared_folder = shared_folder_override if shared_folder_override else get_shared_workflows_folder()
    workflows_path = os.path.join(config_dir, 'Workflows', shared_folder)

    folders = []
    try:
        if os.path.isdir(workflows_path):
            for item in os.listdir(workflows_path):
                item_path = os.path.join(workflows_path, item)
                # Only include directories that don't start with _
                if os.path.isdir(item_path) and not item.startswith('_'):
                    folders.append(item)
    except OSError as e:
        logger.warning(f"Failed to list shared workflow folders from {workflows_path}: {e}")

    return sorted(folders)


def workflow_folder_exists_in_shared(folder_name):
    """
    Checks if a workflow folder exists in the shared workflows folder.

    Args:
        folder_name (str): The name of the folder to check.

    Returns:
        bool: True if the folder exists, False otherwise.
    """
    config_dir = str(get_root_config_directory())
    shared_folder = get_shared_workflows_folder()
    folder_path = os.path.join(config_dir, 'Workflows', shared_folder, folder_name)
    return os.path.isdir(folder_path)


# Backwards compatibility aliases
def get_available_shared_workflows(shared_folder_override=None):
    """
    Retrieves a list of available workflow folder names from the shared workflows folder.

    This is an alias for get_available_shared_workflow_folders().

    Args:
        shared_folder_override (str, optional): If provided, uses this folder name
            instead of resolving via the current user's config.

    Returns:
        list: A list of folder names available in the shared folder.
    """
    return get_available_shared_workflow_folders(shared_folder_override=shared_folder_override)


def workflow_exists_in_shared_folder(folder_name):
    """
    Checks if a workflow folder exists in the shared workflows folder.

    This is an alias for workflow_folder_exists_in_shared().

    Args:
        folder_name (str): The name of the folder to check.

    Returns:
        bool: True if the folder exists, False otherwise.
    """
    return workflow_folder_exists_in_shared(folder_name)


def get_discussion_id_workflow_path():
    """
    Retrieves the file path to the discussion ID workflow.

    This function gets the name of the discussion ID workflow from the user
    configuration and then returns its full file path.

    Returns:
        str: The full path to the discussion ID workflow file.
    """
    workflow_name = get_discussion_id_workflow_name()
    return get_workflow_path(workflow_name)


def get_discussion_memory_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's memory file.

    This function uses `get_discussion_file_path` to build the path for
    the `_memories.json` file associated with a given discussion ID.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's memory file.
    """
    result = get_discussion_file_path(discussion_id, 'memories', api_key_hash=api_key_hash)
    logger.debug("Getting discussion id path: %s", result)
    return result


def get_discussion_condensation_tracker_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's memory condensation tracker file.

    This function uses `get_discussion_file_path` to build the path for
    the `_condensation_tracker.json` file associated with a given discussion ID.
    The tracker stores the hash of the last memory that was included in a
    condensation pass, so the system knows which memories are "new" since
    the last condensation.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's condensation tracker file.
    """
    return get_discussion_file_path(discussion_id, 'condensation_tracker', api_key_hash=api_key_hash)


def get_discussion_vision_responses_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's vision response cache file.

    This function uses `get_discussion_file_path` to build the path for
    the `_vision_responses.json` file associated with a given discussion ID.
    The cache stores hashed message keys mapped to their vision LLM responses,
    so that identical images are not re-processed.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's vision response cache file.
    """
    return get_discussion_file_path(discussion_id, 'vision_responses', api_key_hash=api_key_hash)


def get_discussion_chat_summary_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's chat summary file.

    This function uses `get_discussion_file_path` to build the path for
    the `_chat_summary.json` file associated with a given discussion ID.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's chat summary file.
    """
    return get_discussion_file_path(discussion_id, 'chat_summary', api_key_hash=api_key_hash)



def get_is_chat_complete_add_user_assistant() -> bool:
    """
    Retrieves the chat completion configuration setting for adding user/assistant roles.

    This function gets the 'chatCompleteAddUserAssistant' setting from the
    user configuration.

    Returns:
        bool: The boolean value indicating whether to add user/assistant roles.
    """
    data = get_user_config()
    return data['chatCompleteAddUserAssistant']


def get_is_chat_complete_add_missing_assistant() -> bool:
    """
    Retrieves the chat completion configuration setting for adding a missing assistant response.

    This function gets the 'chatCompletionAddMissingAssistantGenerator' setting
    from the user configuration.

    Returns:
        bool: The boolean value indicating whether to add a missing assistant response.
    """
    data = get_user_config()
    return data['chatCompletionAddMissingAssistantGenerator']


def get_connect_timeout() -> int:
    """
    Retrieves the `connectTimeoutInSeconds` configuration setting.

    This function returns the timeout in seconds for establishing an HTTP
    connection to an LLM endpoint. If the setting is not found, it defaults
    to 30 seconds.

    Returns:
        int: The connect timeout in seconds.
    """
    value = get_config_value('connectTimeoutInSeconds')
    return 30 if value is None else max(1, int(value))


def get_max_categorization_attempts() -> int:
    """
    Retrieves the `maxCategorizationAttempts` configuration setting.

    This function returns the maximum number of times the categorization
    workflow will run before falling back to the default workflow. If the
    setting is not found, it defaults to 1 (no retries).

    Returns:
        int: The maximum number of categorization attempts.
    """
    value = get_config_value('maxCategorizationAttempts')
    return 1 if value is None else max(1, int(value))


def get_encrypt_using_api_key() -> bool:
    """
    Retrieves the ``encryptUsingApiKey`` configuration setting.

    When True, discussion files are encrypted at rest using a key derived
    from the API key. When False (the default), API keys are still used
    for directory isolation but files remain plaintext.

    Returns:
        bool: Whether file encryption is enabled.
    """
    value = get_config_value('encryptUsingApiKey')
    return bool(value) if value is not None else False


def get_redact_log_output() -> bool:
    """
    Retrieves the ``redactLogOutput`` configuration setting.

    When True, all sensitive content (prompts, LLM responses, payloads)
    is redacted from console and file log output, regardless of whether
    encryption is enabled. When False (the default), log output is
    unredacted unless encryption-based redaction is active.

    Returns:
        bool: Whether log redaction is enabled.
    """
    value = get_config_value('redactLogOutput')
    return bool(value) if value is not None else False


def get_intercept_openwebui_tool_requests() -> bool:
    """
    Retrieves the ``interceptOpenWebUIToolRequests`` configuration setting.

    When True, OpenWebUI tool-selection requests (identifiable by a specific
    system prompt pattern) are intercepted and answered with an empty tool-call
    response, bypassing the workflow engine entirely. When False (the default),
    these requests are routed through the normal workflow pipeline like any
    other prompt.

    Returns:
        bool: Whether to intercept OpenWebUI tool requests.
    """
    value = get_config_value('interceptOpenWebUIToolRequests')
    return bool(value) if value is not None else False


def get_context_compactor_settings_name():
    """
    Retrieves the name of the context compactor settings file.

    This function gets the 'contextCompactorSettingsFile' setting from the
    user configuration.

    Returns:
        str or None: The name of the context compactor settings file, or None if not set.
    """
    return get_config_value('contextCompactorSettingsFile')


def get_context_compactor_settings_path():
    """
    Retrieves the file path to the context compactor settings file.

    This function gets the name of the context compactor settings file from the user
    configuration and then returns its full file path within the user's workflow folder.

    Returns:
        str: The full path to the context compactor settings file.
    """
    settings_name = get_context_compactor_settings_name()
    return get_workflow_path(settings_name)


def get_discussion_context_compactor_old_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's context compactor 'Old' section file.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's context compactor 'Old' file.
    """
    return get_discussion_file_path(discussion_id, 'context_compactor_old', api_key_hash=api_key_hash)


def get_discussion_context_compactor_oldest_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's context compactor 'Oldest' section file.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's context compactor 'Oldest' file.
    """
    return get_discussion_file_path(discussion_id, 'context_compactor_oldest', api_key_hash=api_key_hash)


