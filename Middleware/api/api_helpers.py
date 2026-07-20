# /Middleware/api/api_helpers.py

import json
import logging
import os
from typing import Dict, Any, List, Optional, Tuple

from flask import request as flask_request

from Middleware.common import instance_global_variables
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities.config_utils import get_current_username, workflow_exists_in_shared_folder, \
    get_config_property_if_exists, get_user_config_for, get_root_config_directory, _is_safe_flat_config_name

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()


def build_response_json(
        token: str,
        finish_reason: Optional[str] = None,
        additional_fields: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Constructs a response JSON payload based on the API type using the ResponseBuilderService.

    Args:
        token (str): The text content (token) to include in the response.
        finish_reason (Optional[str]): The reason for the response termination (e.g., 'stop').
        additional_fields (Optional[Dict[str, Any]]): Extra fields to merge into the final JSON response.
        request_id (Optional[str]): The unique identifier for the request.
        tool_calls (Optional[List[Dict[str, Any]]]): Tool call objects to include in the response.

    Returns:
        str: A JSON string representing the formatted response payload.
    """
    api_type = instance_global_variables.get_api_type()
    response = {}

    if api_type == "ollamagenerate":
        response = response_builder.build_ollama_generate_chunk(token, finish_reason, request_id)
    elif api_type == "ollamaapichat":
        response = response_builder.build_ollama_chat_chunk(token, finish_reason, request_id, tool_calls=tool_calls)
    elif api_type == "openaicompletion":
        response = response_builder.build_openai_completion_chunk(token, finish_reason)
    elif api_type == "openaichatcompletion":
        response = response_builder.build_openai_chat_completion_chunk(token, finish_reason, tool_calls=tool_calls)
    else:
        raise ValueError(f"Unsupported API type for streaming: {api_type}")

    if additional_fields:
        response.update(additional_fields)

    return json.dumps(response, ensure_ascii=False)


def get_model_name():
    """
    Retrieves the current model name based on the username and active workflow.

    If a workflow override is active, returns "username:workflow".
    Otherwise, returns just the username.

    Returns:
        str: The model identifier in format "username" or "username:workflow".
    """
    username = get_current_username()
    workflow = instance_global_variables.get_workflow_override()
    if workflow:
        return f"{username}:{workflow}"
    return username


def parse_model_field(model_value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses the model field from an API request and extracts user and workflow.

    In multi-user mode (USERS is set with multiple entries), the model field
    can specify a target user and optionally a shared workflow:
    - "username" -> matches configured user, returns (username, None)
    - "username:workflow" -> matches configured user + shared workflow
    - "workflow" (if in shared folder for current/default user) -> (None, workflow)
    - Anything else -> (None, None)

    In single-user mode (USERS is None or has one entry), the behavior matches
    the legacy logic: only workflow matching is attempted.

    Args:
        model_value (Optional[str]): The model field value from the request.

    Returns:
        Tuple[Optional[str], Optional[str]]: (user, workflow); either or both
            may be None.
    """
    if not model_value:
        return None, None

    # Strip any :latest suffix that Ollama might add
    if model_value.endswith(':latest'):
        model_value = model_value[:-7]

    configured_users = instance_global_variables.USERS
    is_multi_user = configured_users and len(configured_users) > 1

    # Check for "username:workflow" format
    if ':' in model_value:
        candidate_user, workflow_name = model_value.split(':', 1)

        if is_multi_user and candidate_user in configured_users:
            if workflow_name and _workflow_exists_for_user(workflow_name, candidate_user):
                return candidate_user, workflow_name
            # User matched but workflow didn't; still route to the user
            return candidate_user, None

        # In single-user mode, try legacy workflow matching.
        # In multi-user mode, a bare or unrecognised user:workflow is invalid:
        # skip the shared-folder check (it would crash because no request user
        # is set yet) and let require_identified_user() return a clean 400.
        if not is_multi_user and workflow_exists_in_shared_folder(workflow_name):
            return None, workflow_name

    # In multi-user mode, check if model_value is a configured username
    if is_multi_user and model_value in configured_users:
        return model_value, None

    # Check if the model value itself is a workflow name (single-user only).
    # In multi-user mode every request must specify a recognised user, so a
    # bare workflow name is invalid.
    if not is_multi_user and workflow_exists_in_shared_folder(model_value):
        return None, model_value

    return None, None


def _workflow_exists_for_user(workflow_name: str, username: str) -> bool:
    """
    Checks whether a workflow folder exists in the shared workflows folder
    for a specific user.

    Loads the user's config to determine their shared workflows folder,
    then checks if the workflow subfolder exists there.

    Args:
        workflow_name (str): The workflow folder name to check.
        username (str): The username whose config determines the shared folder.

    Returns:
        bool: True if the workflow folder exists for that user.
    """
    # The workflow name comes from the request model field ("user:workflow"); a
    # traversal/absolute value must not resolve outside the user's shared folder.
    if not _is_safe_flat_config_name(workflow_name):
        return False

    try:
        user_config = get_user_config_for(username)
        shared_override = get_config_property_if_exists('sharedWorkflowsSubDirectoryOverride', user_config)
        shared_folder = shared_override if shared_override else '_shared'
    except Exception:
        shared_folder = '_shared'

    config_dir = str(get_root_config_directory())
    folder_path = os.path.join(config_dir, 'Workflows', shared_folder, workflow_name)
    return os.path.isdir(folder_path)


def set_request_context_from_model(model_value: Optional[str]) -> None:
    """
    Parses the model field and sets request-scoped user and workflow override.

    This should be called at the start of request processing.

    Args:
        model_value (Optional[str]): The model field value from the request.
    """
    user, workflow = parse_model_field(model_value)
    # Always set request_user (even to None) to clear any stale value left by
    # a previous streaming generator on the same thread.  Under Eventlet each
    # greenlet has fresh thread-local storage so this is a no-op, but under
    # thread-pool servers (Waitress) the thread-local can survive across requests.
    instance_global_variables.set_request_user(user)
    if user:
        logger.info(f"Request user set from model field: {user}")
    instance_global_variables.set_workflow_override(workflow)
    if workflow:
        logger.info(f"Workflow override set from model field: {workflow}")


def require_identified_user() -> Optional[str]:
    """
    In multi-user mode, validates that a request user was identified.

    When multiple users are configured, every incoming request must specify
    a recognised user in the model field (either ``username`` or
    ``username:workflow``).  If the model field did not resolve to a
    configured user, this function returns an error message suitable for
    returning to the caller as a 400 response.

    In single-user mode this always returns None (no error).

    Returns:
        Optional[str]: An error description if validation fails, None if OK.
    """
    configured_users = instance_global_variables.USERS
    is_multi_user = configured_users and len(configured_users) > 1
    if is_multi_user and not instance_global_variables.get_request_user():
        return (
            f"Multi-user mode is active. The model field must specify a "
            f"configured user (or user:workflow). "
            f"Available users: {', '.join(configured_users)}"
        )
    return None


def clear_request_context() -> None:
    """
    Clears both workflow override and request user.

    This should be called at the end of request processing to clean up.
    """
    instance_global_variables.clear_workflow_override()
    instance_global_variables.clear_request_user()


def set_workflow_override(model_value: Optional[str]) -> None:
    """
    Parses the model field and sets request context (user + workflow override).

    This is an alias for set_request_context_from_model() for backwards compatibility.

    Args:
        model_value (Optional[str]): The model field value from the request.
    """
    set_request_context_from_model(model_value)


def clear_workflow_override() -> None:
    """
    Clears request context (workflow override + request user).

    This is an alias for clear_request_context() for backwards compatibility.
    """
    clear_request_context()


def get_active_workflow_override() -> Optional[str]:
    """
    Gets the currently active workflow override.

    Returns:
        Optional[str]: The workflow name if override is active, None otherwise.
    """
    return instance_global_variables.get_workflow_override()


def sse_format(data: str, output_format: str) -> str:
    """
    Formats a data string for Server-Sent Events (SSE).

    Args:
        data (str): The data string to format.
        output_format (str): The format of the API response (e.g., 'ollamagenerate').

    Returns:
        str: The formatted SSE string.
    """
    if output_format == 'ollamagenerate' or output_format == 'ollamaapichat':
        return f"{data}\n"
    else:
        return f"data: {data}\n\n"


def extract_api_key() -> Optional[str]:
    """
    Extracts the API key from the Authorization: Bearer header, if present.

    Returns:
        Optional[str]: The API key string, or None if not present or empty.
    """
    auth = flask_request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        key = auth[7:].strip()
        return key if key else None
    return None


# The client contract specifies an opaque idempotency-key string of at most
# this length. A longer or empty value is treated as no key (legacy client),
# so a malformed header cannot bloat the in-flight registry or change behavior.
MAX_IDEMPOTENCY_KEY_LENGTH = 128


def extract_idempotency_key() -> Optional[str]:
    """
    Extracts the client-supplied idempotency key from the request headers.

    The chat client sends ``X-Idempotency-Key`` with the same value across every
    retry of one logical request. HTTP header names are case-insensitive, which
    Flask's header lookup already honors. A missing, empty, or over-long value is
    reported as absent so the caller behaves exactly as it would for a legacy
    client that sends no key.

    Returns:
        Optional[str]: The idempotency key, or None when it is absent, empty, or
        longer than MAX_IDEMPOTENCY_KEY_LENGTH.
    """
    value = flask_request.headers.get('X-Idempotency-Key', '')
    value = value.strip()
    if not value or len(value) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return None
    return value
