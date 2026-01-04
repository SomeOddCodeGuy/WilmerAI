# Middleware/api/workflow_gateway.py

import copy
import logging
import os
from functools import wraps
from typing import Any, Dict, List, Generator, Optional, Union

from flask import jsonify, Response, request

from Middleware.api import api_helpers
from Middleware.services.prompt_categorization_service import PromptCategorizationService
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities.config_utils import get_custom_workflow_is_active, get_active_custom_workflow_name, \
    get_shared_workflows_folder
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id
from Middleware.utilities.text_utils import replace_brackets_in_list
from Middleware.workflows.managers.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()


def handle_user_prompt(request_id: str, prompt_collection: List[Dict[str, Any]], stream: bool) -> Union[str, Generator[str, None, None]]:
    """
    Processes a user prompt by routing it to the appropriate workflow.

    The workflow is determined by the following priority:
    1. Workflow override from API model field (if set via api_helpers.set_workflow_override)
    2. Custom workflow from user config (if get_custom_workflow_is_active is True)
    3. Dynamic routing via PromptCategorizationService

    Args:
        request_id (str): The unique identifier for this request.
        prompt_collection (List[Dict[str, Any]]): The list of messages representing the conversation.
        stream (bool): A flag indicating whether to return a streaming response.

    Returns:
        Union[str, Generator[str, None, None]]: The complete response string or a generator for streaming chunks.
    """
    discussion_id = extract_discussion_id(prompt_collection)

    sanitized_messages = replace_brackets_in_list(prompt_collection)

    logger.debug(f"Handle user prompt discussion_id: {discussion_id}")

    # Check for workflow folder override from API model field
    # When set, this specifies a folder within _shared/ containing workflows.
    # We run _DefaultWorkflow.json from that folder, and all nested workflow
    # calls will also use that folder.
    workflow_folder_override = api_helpers.get_active_workflow_override()
    logger.debug(f"Workflow folder override value: {workflow_folder_override}")
    if workflow_folder_override:
        # Build the full folder path: _shared/<folder_name>
        folder_path = os.path.join(get_shared_workflows_folder(), workflow_folder_override)
        logger.info(f"Using workflow folder override from model field: {folder_path}")
        return WorkflowManager.run_custom_workflow(
            workflow_name="_DefaultWorkflow",
            request_id=request_id,
            discussion_id=discussion_id,
            messages=sanitized_messages,
            is_streaming=stream,
            workflow_user_folder_override=folder_path
        )

    if not get_custom_workflow_is_active():
        request_routing_service = PromptCategorizationService()

        # The categorization workflow requires the full conversation context.
        return request_routing_service.get_prompt_category(
            messages=sanitized_messages,
            request_id=request_id,
            discussion_id=discussion_id,
            stream=stream
        )
    else:
        logger.info("Custom workflow is active, running workflow.")

        return WorkflowManager.run_custom_workflow(
            workflow_name=get_active_custom_workflow_name(),
            request_id=request_id,
            discussion_id=discussion_id,
            messages=sanitized_messages,
            is_streaming=stream
        )


def _sanitize_log_data(data: Any, max_len: int = 200, head_tail_len: int = 50) -> Any:
    """
    Recursively sanitizes data for logging by truncating long strings.

    Args:
        data (Any): The data to be sanitized (e.g., a dictionary, list, or string).
        max_len (int): The maximum length for strings before truncation.
        head_tail_len (int): The number of characters to keep at the beginning and end of a truncated string.

    Returns:
        Any: The sanitized data with long strings truncated.
    """
    data_copy = copy.deepcopy(data)

    def _sanitize_recursive(item):
        if isinstance(item, dict):
            return {k: _sanitize_recursive(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [_sanitize_recursive(elem) for elem in item]
        elif isinstance(item, str):
            is_potential_image_data = item.startswith("data:image") and "base64," in item
            if is_potential_image_data and len(item) > max_len:
                try:
                    prefix_end = item.find("base64,") + len("base64,")
                    prefix = item[:prefix_end]
                    encoded_data = item[prefix_end:]
                    if len(encoded_data) > (max_len - prefix_end):
                        return f"{prefix}{encoded_data[:head_tail_len]}...[truncated]...{encoded_data[-head_tail_len:]}"
                except Exception:
                    # Return original string if slicing fails
                    pass
            elif len(item) > (max_len * 5):
                safe_head_tail = min(head_tail_len * 2, len(item) // 2)
                return f"{item[:safe_head_tail]}...[truncated]...{item[-safe_head_tail:]}"
            return item
        else:
            return item

    return _sanitize_recursive(data_copy)


def _check_and_handle_openwebui_tool_request(request_data: Dict[str, Any], api_type: str) -> Optional[Response]:
    """
    Checks for OpenWebUI tool selection requests and returns an early response if detected.

    Args:
        request_data (Dict[str, Any]): The incoming request JSON payload.
        api_type (str): The API compatibility type (e.g., 'openaichatcompletion').

    Returns:
        Optional[Response]: A Flask Response object if a tool selection request is detected, otherwise None.
    """
    openwebui_tool_pattern = "Your task is to choose and return the correct tool(s) from the list of available tools based on the query"
    if 'messages' in request_data:
        for message in request_data['messages']:
            if message.get('role') == 'system' and openwebui_tool_pattern in message.get('content', ''):
                logger.info(f"Detected OpenWebUI tool selection request via {api_type}. Returning early.")
                if api_type == 'openaichatcompletion':
                    response = response_builder.build_openai_tool_call_response()
                    return jsonify(response)
                elif api_type == 'ollamaapichat':
                    model_name = request_data.get("model", api_helpers.get_model_name())
                    response_json = response_builder.build_ollama_tool_call_response(model_name)
                    return jsonify(response_json)
                else:
                    logger.warning(f"Unknown api_type '{api_type}' for OpenWebUI tool request handling.")
                    return None
    return None


def handle_openwebui_tool_check(api_type: str):
    """
    Creates a decorator to intercept and handle OpenWebUI tool selection requests.

    Args:
        api_type (str): The API compatibility type to handle (e.g., 'openaichatcompletion').

    Returns:
        A decorator function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            request_data = request.get_json(force=True, silent=True)
            if request_data is None:
                logger.warning(f"Request to {func.__name__} did not contain valid JSON.")
                return func(*args, **kwargs)
            early_response = _check_and_handle_openwebui_tool_request(request_data, api_type)
            if early_response:
                return early_response
            return func(*args, **kwargs)

        return wrapper

    return decorator
