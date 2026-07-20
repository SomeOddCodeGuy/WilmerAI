# /Middleware/utilities/config_utils.py

import json
import logging
import os
from typing import Optional

from Middleware.common import instance_global_variables

logger = logging.getLogger(__name__)


def _expand_user_path(path):
    """
    Expands a leading ``~`` in an operator-supplied path to the user's home.

    Applied to the path-valued roots that come from outside the install (the CLI
    directory flags and the path-valued user-config settings) so a ``~``/``~user``
    prefix resolves to the home directory instead of a literal ``~`` folder under
    the process working directory. Every other config path is derived from these
    roots via ``os.path.join``, so expanding here covers the whole tree.
    ``os.path.expanduser`` only rewrites a leading ``~`` and returns the string
    unchanged when no home directory can be resolved, so absolute and relative
    paths pass through untouched and home-less environments keep prior behavior.

    Args:
        path: The raw path string, or any falsy value.

    Returns:
        The path with a leading ``~`` expanded, or the input unchanged when it is
        falsy or has no ``~`` prefix.
    """
    return os.path.expanduser(path) if path else path


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
        str or None: The value of the property if it is present and truthy, otherwise None.
    """
    if config_data is None:
        return None
    return config_data.get(config_property) or None


def get_current_username():
    """
    Retrieves the current username from the application configuration.

    Checks the following in order:
    1. Request-scoped user (set from the model field for multi-user mode)
    2. USERS list has exactly one entry (single-user mode): return that entry
    3. USERS list has multiple entries but no request user: raise RuntimeError
    4. USERS is None: fall back to _current-user.json (legacy, no --User arg)

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
            f"This is a bug: every request must identify a user. "
            f"Configured users: {users}"
        )
    config_dir = get_root_config_directory()
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
    config_dir = get_root_config_directory()
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


def get_liveness_tool_call():
    """
    Retrieves the user's liveness tool call configuration, if any.

    Agentic frontends end their autonomous loop whenever a response arrives
    with no tool call in it. When Wilmer is mid-way through a multi-turn task,
    a response that is words alone therefore strands the task until a human
    types something. The ``livenessToolCall`` user setting names a harmless
    tool call (valid for the user's frontend) that the streaming response
    handler injects into such responses so the frontend calls back and the
    task keeps moving.

    Expected shape in the user config::

        "livenessToolCall": {
            "toolName": "bash",
            "arguments": {"command": "echo '[Wilmer] task in progress'"}
        }

    Returns:
        dict or None: The validated configuration, or None if unset or malformed
        (a malformed value is logged and treated as disabled rather than raised,
        because liveness injection is an enhancement that must never break the
        response path).
    """
    value = get_config_value('livenessToolCall')
    if not value:
        return None
    if not isinstance(value, dict) or not isinstance(value.get('toolName'), str) or not value.get('toolName').strip():
        logger.warning("livenessToolCall config is malformed (need at least a non-empty 'toolName' string); ignoring it")
        return None
    return value


def get_root_public_directory():
    """
    Gets the root directory of the ``Public`` folder.

    This is the parent directory that holds ``Configs`` (user/endpoint/workflow
    config files) alongside runtime-data siblings such as ``DiscussionIds``,
    ``SqlLiteDBs``, and ``logs``. Resolving it in one place lets every
    runtime-data default derive from a single base path.

    Resolution order:

    1. ``--PublicDirectory`` CLI flag
       (``instance_global_variables.PUBLIC_DIRECTORY``).
    2. ``{project_root}/Public`` (the default for local/dev runs).

    Returns:
        str: The absolute path to the ``Public`` root directory.
    """
    if instance_global_variables.PUBLIC_DIRECTORY:
        return _expand_user_path(instance_global_variables.PUBLIC_DIRECTORY)
    return os.path.join(get_project_root_directory_path(), 'Public')


def get_root_config_directory():
    """
    Gets the root directory of the ``Configs`` folder.

    Resolution order:

    1. ``--ConfigDirectory`` CLI flag
       (``instance_global_variables.CONFIG_DIRECTORY``). Kept for
       backwards compatibility; when set it wins regardless of
       ``--PublicDirectory``.
    2. ``{get_root_public_directory()}/Configs``.

    Returns:
        str: The absolute path to the root ``Configs`` directory.
    """
    if instance_global_variables.CONFIG_DIRECTORY:
        return _expand_user_path(instance_global_variables.CONFIG_DIRECTORY)
    return os.path.join(get_root_public_directory(), 'Configs')


def _is_safe_flat_config_name(name) -> bool:
    """True when ``name`` is a plain config-file base name with no path traversal.

    Names that index a file inside Public/Configs (endpoint names, MCP server names,
    etc.) must be a single path component. Reject path separators, a Windows drive
    colon, and the current/parent directory so a crafted name cannot escape its
    intended directory.

    Args:
        name (str): The candidate config base name; non-str values are rejected.

    Returns:
        bool: True if ``name`` is a safe single path component with no traversal.
    """
    return (
        isinstance(name, str)
        and name not in ("", ".", "..")
        and "/" not in name
        and "\\" not in name
        and ":" not in name
    )


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
    config_dir = get_root_config_directory()
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
    config_dir = get_root_config_directory()
    if secondary_subdirectory:
        return os.path.join(config_dir, directory, sub_directory, secondary_subdirectory, f'{file_name}.json')
    return os.path.join(config_dir, directory, sub_directory, f'{file_name}.json')


def _resolve_discussions_root():
    """
    Returns the target root directory for per-discussion data.

    Resolution order:

    1. ``--DiscussionDirectory`` CLI flag
       (``instance_global_variables.DISCUSSION_DIRECTORY``).
    2. ``discussionDirectory`` user config setting.
    3. ``{get_root_public_directory()}/DiscussionIds``.

    Discussion data is a sibling of ``Configs`` under the ``Public`` root,
    not a child of ``Configs``; resolving from
    :func:`get_root_public_directory` keeps configs and runtime data
    separated even when a shared install overrides only
    ``--PublicDirectory``.

    The returned path is a *target* location. Callers are expected to apply
    legacy-folder stickiness (see :func:`get_discussion_folder_path`) so that
    pre-refactor installations keep writing to their original location until
    the user migrates them manually.

    Returns:
        str: Absolute or relative path to the discussions root directory.
    """
    cli_override = instance_global_variables.DISCUSSION_DIRECTORY
    if cli_override:
        return _expand_user_path(cli_override)
    config_override = get_config_value('discussionDirectory')
    if config_override:
        return _expand_user_path(config_override)
    return os.path.join(get_root_public_directory(), 'DiscussionIds')


def _legacy_discussions_root():
    """
    Returns the pre-refactor default root directory for per-discussion data.

    Discussions created before the path-resolution refactor lived at
    ``{project_root}/Public/DiscussionIds/``. Legacy-stickiness logic checks
    this location so that existing data keeps being read and written in
    place.

    Returns:
        str: The legacy discussions root directory.
    """
    return os.path.join(get_project_root_directory_path(), 'Public', 'DiscussionIds')


def get_discussion_folder_path(discussion_id, api_key_hash=None):
    """
    Returns the folder where all files for a given discussion are stored.

    Resolution applies the standard hierarchy (CLI flag, user config,
    ``{get_root_public_directory()}/DiscussionIds/``). If the target folder
    does not yet exist but the same discussion folder exists at the legacy
    location (``{project_root}/Public/DiscussionIds/``), the legacy folder
    is returned so that existing data continues to be used in place for the
    lifespan of that discussion (no automatic migration).

    The returned folder is created on disk if it does not already exist.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.

    Returns:
        str: The path to the discussion folder.

    Raises:
        ValueError: If ``discussion_id`` is None.
    """
    if discussion_id is None:
        raise ValueError("discussion_id is required for discussion folder path construction")

    # Defense in depth: the id is normally sanitized at extraction, but any caller
    # that constructs one from elsewhere must not be able to escape the discussions
    # root (or a per-api-key isolation subdir) via a separator, drive colon, or '..'.
    # An empty id is left to the pre-existing behavior (it is guarded by truthiness
    # checks at the call sites); only a non-empty traversal value is rejected here.
    if discussion_id and not _is_safe_flat_config_name(discussion_id):
        raise ValueError("discussion_id contains path-unsafe characters")

    target_root = _resolve_discussions_root()
    legacy_root = _legacy_discussions_root()

    if api_key_hash:
        target_folder = os.path.join(target_root, api_key_hash, discussion_id)
        legacy_folder = os.path.join(legacy_root, api_key_hash, discussion_id)
    else:
        target_folder = os.path.join(target_root, discussion_id)
        legacy_folder = os.path.join(legacy_root, discussion_id)

    if os.path.abspath(target_folder) == os.path.abspath(legacy_folder):
        try:
            os.makedirs(target_folder, exist_ok=True)
        except OSError:
            logger.warning("Could not create discussion folder at %s", target_folder)
        # When target == legacy there is no alternate location to fall back to,
        # so the target path is returned even if creation failed; the caller's
        # subsequent open() will surface a clearer, operation-specific error.
        return target_folder

    if not os.path.exists(target_folder) and os.path.exists(legacy_folder):
        return legacy_folder

    try:
        os.makedirs(target_folder, exist_ok=True)
        return target_folder
    except OSError:
        logger.warning(
            "Could not create target discussion folder at '%s'; falling back to legacy location.",
            target_folder,
        )
        os.makedirs(legacy_folder, exist_ok=True)
        return legacy_folder


def get_discussion_file_path(discussion_id, file_name, api_key_hash=None):
    """
    Constructs the file path for a discussion-related JSON file.

    The file lives inside the discussion folder returned by
    :func:`get_discussion_folder_path`, which applies the standard path
    resolution hierarchy (CLI flag, user config,
    ``{get_root_public_directory()}/DiscussionIds/``) plus legacy-folder
    stickiness for pre-refactor data.

    When ``api_key_hash`` is provided, files are stored under a per-user
    subdirectory::

        {discussions_root}/{api_key_hash}/{discussion_id}/{file_name}.json

    Without an API key hash, the layout is::

        {discussions_root}/{discussion_id}/{file_name}.json

    For backwards compatibility, if the nested file does not exist but a
    legacy flat file
    (``{discussions_root}/{discussion_id}_{file_name}.json``) does, the
    legacy path is returned instead. New files are always created in the
    nested structure.

    Args:
        discussion_id (str): The ID of the discussion.
        file_name (str): The base name of the file (e.g. 'memories', 'chat_summary').
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation. Defaults to None.

    Returns:
        str: The full path to the discussion file.

    Raises:
        ValueError: If ``discussion_id`` is None.
    """
    if discussion_id is None:
        raise ValueError("discussion_id is required for discussion file path construction")

    discussion_dir = get_discussion_folder_path(discussion_id, api_key_hash=api_key_hash)

    nested_path = os.path.join(discussion_dir, f'{file_name}.json')
    if not os.path.exists(nested_path) and not api_key_hash:
        parent = os.path.dirname(discussion_dir)
        legacy_flat_path = os.path.join(parent, f'{discussion_id}_{file_name}.json')
        if os.path.exists(legacy_flat_path):
            logger.info("Using legacy discussion file: %s", legacy_flat_path)
            return legacy_flat_path

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
    Returns the target directory for per-user SQLite databases.

    Resolution order:

    1. ``--UserLevelSqlLiteDirectory`` CLI flag
       (``instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY``).
    2. ``sqlLiteDirectory`` user config setting.
    3. ``{get_root_public_directory()}/SqlLiteDBs``.

    SQLite databases live alongside ``Configs`` and ``DiscussionIds`` under
    the ``Public`` root, not inside ``Configs``; resolving from
    :func:`get_root_public_directory` keeps configs and runtime data
    separated.

    This function only returns the *target* write directory. Callers
    (see :class:`LockingService`) apply legacy-path stickiness separately:
    if a database file already exists at either pre-refactor default
    location (the current working directory or the project root), that
    existing file keeps being used so no automatic migration is performed.

    Returns:
        str: Path to the directory where SQLite databases should be created.
    """
    cli_override = instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY
    if cli_override:
        return _expand_user_path(cli_override)

    config_override = get_config_value('sqlLiteDirectory')
    if config_override:
        return _expand_user_path(config_override)

    return os.path.join(get_root_public_directory(), 'SqlLiteDBs')


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
    return get_config_value('endpointConfigsSubDirectory') or ""


def get_preset_subdirectory_override():
    """
    Retrieves the subdirectory override for preset configurations.

    This function gets the 'presetConfigsSubDirectoryOverride' from the
    user configuration. If the setting is not found, it returns the current
    username as the default subdirectory.

    Returns:
        str: The name of the preset subdirectory, or the current username.
    """
    return get_config_value('presetConfigsSubDirectoryOverride') or get_current_username()


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
    user configuration. If set, it returns that value directly, loading
    workflows from 'Workflows/<override>/'. If not set, it returns the
    current username as the default subdirectory.

    Returns:
        str: The name of the workflow subdirectory (the override value or username).
    """
    sub_directory = get_config_value('workflowConfigsSubDirectoryOverride')
    if sub_directory:
        return sub_directory
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


def get_openai_preset_path(config_name, preset_type="OpenAiCompatibleApis", use_subdirectory=False):
    """
    Retrieves the file path to a preset configuration file.

    This function builds the path to a preset configuration, optionally
    including a subdirectory override.

    Args:
        config_name (str): The name of the preset configuration.
        preset_type (str, optional): The subdirectory within `Presets`, generally named
                                     by the API type. Defaults to "OpenAiCompatibleApis".
        use_subdirectory (bool, optional): Specifies whether to use a user-specific
                                           subdirectory override. Defaults to False.

    Returns:
        str: The full path to the preset configuration file.
    """
    if use_subdirectory:
        return get_config_with_subdirectory("Presets", preset_type, config_name, get_preset_subdirectory_override())
    return get_config_with_subdirectory("Presets", preset_type, config_name)


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


def try_get_endpoint_config(endpoint: str) -> Optional[dict]:
    """
    Loads an endpoint configuration if it exists, returning None when it does not.

    Unlike get_endpoint_config (which lets load_config raise FileNotFoundError),
    this probes whether a name refers to an endpoint at all. The preset-resolution
    path uses it to check if a node's preset name is actually an endpoint carrying
    an embedded presetSamplers block; a missing file is an expected, non-exceptional
    outcome there (the name is simply not an endpoint), so it is reported as None.

    Args:
        endpoint (str): The name of the endpoint configuration to probe.

    Returns:
        Optional[dict]: The loaded endpoint configuration, or None if absent.
    """
    # A name with path separators is never a real endpoint; treat it as absent rather
    # than letting it probe a file outside the Endpoints directory.
    if not _is_safe_flat_config_name(endpoint):
        return None
    sub_directory = get_endpoint_subdirectory()
    config_path = get_endpoint_config_path(sub_directory, endpoint)
    if not os.path.exists(config_path):
        return None
    return load_config(config_path)


# Per-endpoint estimation level (wilmerContextEstimationLevel). Wilmer's token
# estimator (rough_estimate_token_length) is deliberately conservative; on
# large-vocab models it can overestimate a prompt's real token count by ~1.85x.
# Each level maps to a budget multiplier applied to the real (window - response)
# portion of every endpoint-derived token budget, reclaiming context the
# conservative estimate would otherwise waste. The multiplier is the minimum
# estimate-to-real inflation at which the level stays safe: 'conservative' (1.0)
# is safe for any model (the estimator never under-counts); higher levels assume
# the model's tokenizer is at least that efficient and so are opt-in per endpoint.
# This value only tunes Wilmer's internal budgeting; it is never sent to the
# inference engine.
ESTIMATION_LEVEL_KEY = "wilmerContextEstimationLevel"
DEFAULT_ESTIMATION_LEVEL = "conservative"
ESTIMATION_LEVEL_MULTIPLIERS = {
    "conservative": 1.0,
    "balanced": 1.25,
    "aggressive": 1.5,
    "xaggressive": 1.85,
}


def get_estimation_level_multiplier(endpoint_config) -> float:
    """
    Returns the budget multiplier for an endpoint's estimation level.

    Reads ``wilmerContextEstimationLevel`` from the endpoint config and maps it
    to the multiplier applied to that endpoint's real (window - response) token
    budget everywhere Wilmer budgets tokens for it (the pre-send clamp, the
    conversation-variable ceilings, and any other endpoint-derived budget).
    Unknown, missing, or non-string values fall back to ``conservative`` (1.0,
    no scaling). This value only tunes Wilmer's internal budgeting; it is never
    sent to the inference engine.

    Args:
        endpoint_config (dict): The resolved endpoint configuration.

    Returns:
        float: The multiplier for the real (window - response) budget.
    """
    if not isinstance(endpoint_config, dict):
        return ESTIMATION_LEVEL_MULTIPLIERS[DEFAULT_ESTIMATION_LEVEL]
    level = endpoint_config.get(ESTIMATION_LEVEL_KEY)
    if level is None:
        return ESTIMATION_LEVEL_MULTIPLIERS[DEFAULT_ESTIMATION_LEVEL]
    if not isinstance(level, str):
        logger.warning(
            "%s must be a string (one of %s); got %r. Using '%s'.",
            ESTIMATION_LEVEL_KEY, sorted(ESTIMATION_LEVEL_MULTIPLIERS), level,
            DEFAULT_ESTIMATION_LEVEL,
        )
        return ESTIMATION_LEVEL_MULTIPLIERS[DEFAULT_ESTIMATION_LEVEL]
    multiplier = ESTIMATION_LEVEL_MULTIPLIERS.get(level.strip().lower())
    if multiplier is None:
        logger.warning(
            "Unknown %s %r; expected one of %s. Using '%s'.",
            ESTIMATION_LEVEL_KEY, level, sorted(ESTIMATION_LEVEL_MULTIPLIERS),
            DEFAULT_ESTIMATION_LEVEL,
        )
        return ESTIMATION_LEVEL_MULTIPLIERS[DEFAULT_ESTIMATION_LEVEL]
    return multiplier


# Master switch for context-window awareness (clampPromptToContextWindow). When on
# for a node, Wilmer bounds every feasible estimated budget to the node's endpoint
# window and the endpoint estimation level (above) becomes active; when off, Wilmer
# makes no window-based budgeting decisions and the level is inert. OFF by default so
# upgrading never silently trims an existing config; shipped user configs opt in.
# Resolved per node: node config > endpoint config > user config > default OFF. Lives
# here (not in dispatch) so dispatch and the workflow variable manager resolve it
# identically and cannot drift.
CONTEXT_CLAMP_KEY = "clampPromptToContextWindow"
DEFAULT_CONTEXT_CLAMP_ENABLED = False


def _coerce_optional_bool(value):
    """Coerce a config value to a bool, or None when the value is absent.

    Accepts real JSON booleans (the expected form) and, defensively, common string
    spellings. Returns None when the value is None so callers can fall through to the
    next resolution level rather than treating absence as False.

    Args:
        value: The raw config value (bool, str, other, or None).

    Returns:
        Optional[bool]: The coerced boolean, or None when ``value`` is None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def is_context_clamp_enabled(node_config, endpoint_config) -> bool:
    """Resolve whether the context-window clamp is on for a node.

    Precedence: node config -> endpoint config -> user config -> default (OFF). The
    most specific setting wins, so an operator can force it off for a single node,
    for every node on an endpoint, or globally for a user. The clamp is the master
    switch for context-window awareness: with it off, Wilmer makes no window-based
    budgeting decisions and the endpoint estimation level is inert.

    Args:
        node_config (dict): The node configuration.
        endpoint_config (dict): The resolved endpoint configuration, or None when it
            is unavailable (e.g. a mocked handler in tests).

    Returns:
        bool: True if the clamp should run for this node.
    """
    for config in (node_config, endpoint_config):
        if isinstance(config, dict):
            resolved = _coerce_optional_bool(config.get(CONTEXT_CLAMP_KEY))
            if resolved is not None:
                return resolved
    try:
        user_config = get_user_config()
        if isinstance(user_config, dict):
            resolved = _coerce_optional_bool(user_config.get(CONTEXT_CLAMP_KEY))
            if resolved is not None:
                return resolved
    except Exception as e:
        logger.debug(
            "Context clamp: could not read user config for %s (%s); using default %s.",
            CONTEXT_CLAMP_KEY, e, DEFAULT_CONTEXT_CLAMP_ENABLED,
        )
    return DEFAULT_CONTEXT_CLAMP_ENABLED


# Tokens held back from every endpoint-window budget to cover chat-template framing
# (BOS/EOS, the trailing generation prompt, role headers) and estimation slack not
# captured by message content alone. Shared so the dispatch clamp and the variable
# manager reserve the same headroom.
CONTEXT_WINDOW_BUDGET_HEADROOM_TOKENS = 512


def compute_endpoint_window_budget(endpoint_config, n_predict, headroom_tokens) -> Optional[int]:
    """Compute the base conversation token budget for an endpoint window.

    ``budget = (maxContextTokenSize - n_predict) * estimation_level - headroom``

    This is the single source of truth for the window-derived budget, so the
    pre-send dispatch clamp and the workflow variable manager cannot drift on the
    basis. Dispatch subtracts the system prompt and tool schemas from this base;
    the variable manager (which does not know them at build time) uses it as-is.
    The estimation level is read from ``endpoint_config``; callers are responsible
    for only invoking this when the context clamp is enabled (the level is inert
    otherwise). The value is internal budgeting only; it is never sent to the engine.

    Args:
        endpoint_config (dict): The resolved endpoint configuration.
        n_predict (int): The node's response budget (``maxResponseSizeInTokens`` ->
            ``llm.max_tokens``). Non-numeric or negative values are treated as 0.
        headroom_tokens (int): Tokens to reserve for framing/estimation slack.

    Returns:
        Optional[int]: The base budget, or None when the endpoint window is unknown
        or invalid (in which case the caller leaves the conversation unbounded). The
        value may be <= 0 for a misconfigured node whose response budget alone
        approaches the window.
    """
    if not isinstance(endpoint_config, dict):
        return None
    window = endpoint_config.get("maxContextTokenSize")
    if not isinstance(window, (int, float)) or isinstance(window, bool) or window <= 0:
        return None
    if not isinstance(n_predict, (int, float)) or isinstance(n_predict, bool) or n_predict < 0:
        n_predict = 0
    multiplier = get_estimation_level_multiplier(endpoint_config)
    return int((int(window) - int(n_predict)) * multiplier) - int(headroom_tokens)


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


def load_mcp_server_config(server_name):
    """
    Loads the configuration for a named MCP server.

    MCP server configs live in 'Public/Configs/MCPServers/' and define how
    Wilmer should connect to a Model Context Protocol server: the transport
    (stdio, sse, or streamable_http), the command/URL, and any auth headers.

    Args:
        server_name (str): The base name of the MCP server config file (without `.json`).

    Returns:
        dict: The loaded server configuration data.

    Raises:
        ValueError: If ``server_name`` contains path separators, a drive colon, or
            is '.'/'..' (a defense-in-depth backstop against path traversal; the live
            MCP caller validates names before reaching here).
        FileNotFoundError: If no matching MCP server config file exists.
    """
    if not _is_safe_flat_config_name(server_name):
        raise ValueError(
            f"Invalid MCP server name {server_name!r}: must be a plain file name without "
            "path separators, a drive colon, or '.'/'..'."
        )
    server_file = get_config_path('MCPServers', server_name)
    return load_config(server_file)


def get_default_tool_prompt_path():
    """
    Constructs the file path for the default tool prompt file.

    This function builds the full path to the `default_tool_prompt.txt` file
    located in the root of the `Public/Configs` directory.

    Returns:
        str: The full path to the default tool prompt file.
    """
    config_dir = get_root_config_directory()
    config_file = os.path.join(config_dir, 'default_tool_prompt.txt')
    return config_file


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
    user_name = user_folder_override or get_workflow_subdirectory_override()
    config_dir = get_root_config_directory()
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
    return get_config_value('sharedWorkflowsSubDirectoryOverride') or '_shared'


def get_available_shared_workflows(shared_folder_override=None):
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
    config_dir = get_root_config_directory()
    shared_folder = shared_folder_override or get_shared_workflows_folder()
    workflows_path = os.path.join(config_dir, 'Workflows', shared_folder)

    folders = []
    try:
        if os.path.isdir(workflows_path):
            for item in os.listdir(workflows_path):
                item_path = os.path.join(workflows_path, item)
                if os.path.isdir(item_path) and not item.startswith('_'):
                    folders.append(item)
    except OSError as e:
        logger.warning(f"Failed to list shared workflow folders from {workflows_path}: {e}")

    return sorted(folders)


def workflow_exists_in_shared_folder(folder_name):
    """
    Checks if a workflow folder exists in the shared workflows folder.

    Args:
        folder_name (str): The name of the folder to check.

    Returns:
        bool: True if the folder exists, False otherwise.
    """
    # The folder name comes from the request model field and is used to select a
    # workflow folder (and thus which workflow, including PythonModule/CurlCommand
    # nodes, executes). Reject a traversal/absolute name before the isdir check so a
    # crafted value cannot resolve outside the shared workflows folder.
    if not _is_safe_flat_config_name(folder_name):
        return False

    config_dir = get_root_config_directory()
    shared_folder = get_shared_workflows_folder()
    folder_path = os.path.join(config_dir, 'Workflows', shared_folder, folder_name)
    return os.path.isdir(folder_path)


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


def get_discussion_state_document_file_path(discussion_id, api_key_hash=None):
    """
    Retrieves the file path for a discussion's state document.

    The state document is a single, continuously updated document holding the
    current ground-truth state of the conversation's subject matter (for
    example a user profile for an assistant persona, or world state for a
    roleplay). Unlike the other discussion artefacts it is stored as markdown
    (``state_document.md``) so users can read and hand-edit it directly when
    encryption is not active.

    Args:
        discussion_id (str): The ID of the discussion.
        api_key_hash (str, optional): Hash of the API key for per-user isolation.

    Returns:
        str: The full path to the discussion's state document file.
    """
    discussion_dir = get_discussion_folder_path(discussion_id, api_key_hash=api_key_hash)
    return os.path.join(discussion_dir, 'state_document.md')



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


def get_separate_conversation_in_variables() -> bool:
    """
    Retrieves the ``separateConversationInVariables`` setting from the user config.

    When ``True``, conversation variable strings (e.g. ``{chat_user_prompt_last_ten}``)
    use the delimiter from ``conversationSeparationDelimiter`` between messages
    instead of a plain newline.

    Returns:
        bool: ``True`` if custom separation is enabled, ``False`` otherwise.
              Defaults to ``False`` when the key is absent.
    """
    data = get_user_config()
    return data.get('separateConversationInVariables', False)


def get_conversation_separation_delimiter() -> str:
    """
    Retrieves the ``conversationSeparationDelimiter`` setting from the user config.

    This delimiter is inserted between messages in conversation variable strings
    when ``separateConversationInVariables`` is ``True``.

    Returns:
        str: The delimiter string. Defaults to ``'\\n'`` when the key is absent.
    """
    data = get_user_config()
    return data.get('conversationSeparationDelimiter', '\n')


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


