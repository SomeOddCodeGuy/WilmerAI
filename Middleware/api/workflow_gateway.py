# Middleware/api/workflow_gateway.py

import copy
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Generator, Optional, Union
from functools import wraps

from flask import jsonify, Response, request

from Middleware.api import api_helpers
from Middleware.utilities.config_utils import get_custom_workflow_is_active, get_active_custom_workflow_name
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id
from Middleware.utilities.text_utils import replace_brackets_in_list
from Middleware.services.prompt_categorization_service import PromptCategorizationService
from Middleware.workflows.managers.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)

def handle_user_prompt(prompt_collection: List[Dict[str, Any]], stream: bool) -> Union[str, Generator[str, None, None]]:
    """
    Processes the user's prompt by applying the appropriate workflow and returns the result.

    This function serves as the core entry point for handling user requests. It
    first determines whether a custom workflow is active. If so, it invokes
    the `WorkflowManager` to run the specified workflow. Otherwise, it uses
    the `PromptCategorizationService` to route the prompt based on its
    category.

    Args:
        prompt_collection (List[Dict[str, Any]]): A list of dictionaries
                                                 containing the prompt messages,
                                                 structured as
                                                 `{'role': str, 'content': str}`.
        stream (bool): A boolean indicating whether the response should be
                       streamed back to the user.

    Returns:
        Union[str, Generator[str, None, None]]: The processed prompt response as a
                                                string or a generator for streaming responses.
    """
    request_id = str(uuid.uuid4())
    discussion_id = extract_discussion_id(prompt_collection)
    prompt = replace_brackets_in_list(prompt_collection)

    logger.debug(f"Handle user prompt discussion_id: {discussion_id}")

    if not get_custom_workflow_is_active():
        request_routing_service = PromptCategorizationService()
        return request_routing_service.get_prompt_category(prompt, stream, request_id, discussion_id)
    else:
        logger.info("Custom workflow is active, running workflow.")
        workflow_manager = WorkflowManager(get_active_custom_workflow_name())
        return workflow_manager.run_workflow(prompt_collection, request_id, stream=stream, discussionId=discussion_id)

def _sanitize_log_data(data: Any, max_len: int = 200, head_tail_len: int = 50) -> Any:
    """
    Recursively sanitizes data for logging by truncating long strings.

    This function is used to prevent excessively long data, such as base64-encoded
    images, from cluttering logs. It creates a deep copy of the input data and
    truncates any strings that exceed a specified maximum length, replacing the
    middle portion with an ellipsis.

    Args:
        data (Any): The data structure (dict, list, or string) to sanitize.
        max_len (int): The maximum length for a string before it is truncated.
                       Defaults to 200.
        head_tail_len (int): The number of characters to preserve at the beginning
                             and end of a truncated string. Defaults to 50.

    Returns:
        Any: A sanitized deep copy of the input data.
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
                    pass  # Return original string if slicing fails
            elif len(item) > (max_len * 5):
                safe_head_tail = min(head_tail_len * 2, len(item) // 2)
                return f"{item[:safe_head_tail]}...[truncated]...{item[-safe_head_tail:]}"
            return item
        else:
            return item

    return _sanitize_recursive(data_copy)


def _check_and_handle_openwebui_tool_request(request_data: Dict[str, Any], api_type: str) -> Optional[Response]:
    """
    Checks for OpenWebUI tool selection requests and returns an early response.

    This function inspects incoming API requests for a specific system prompt
    pattern used by OpenWebUI for tool selection. If the pattern is detected,
    it generates a predefined, immediate JSON response that signals tool
    selection without engaging the full workflow, improving efficiency and
    compatibility with OpenWebUI's prompt engineering.

    Args:
        request_data (Dict[str, Any]): The JSON payload of the incoming request.
                                       This is expected to contain a 'messages'
                                       key with the conversation history.
        api_type (str): The type of API being used, such as 'openaichatcompletion'
                        or 'ollamaapichat', which determines the structure of
                        the response payload.

    Returns:
        Optional[Response]: A Flask `Response` object containing the early
                            response if the tool selection pattern is found,
                            otherwise `None`.
    """
    openwebui_tool_pattern = "Your task is to choose and return the correct tool(s) from the list of available tools based on the query"
    if 'messages' in request_data:
        for message in request_data['messages']:
            if message.get('role') == 'system' and openwebui_tool_pattern in message.get('content', ''):
                logger.info(f"Detected OpenWebUI tool selection request via {api_type}. Returning early.")
                if api_type == 'openaichatcompletion':
                    response = {
                        "id": f"chatcmpl-opnwui-tool-{int(time.time())}", "object": "chat.completion",
                        "created": int(time.time()), "model": api_helpers.get_model_name(),
                        "system_fingerprint": "wmr_123456789", "choices": [
                            {"index": 0,
                             "message": {"role": "assistant", "content": None, "tool_calls": []},
                             "logprobs": None, "finish_reason": "tool_calls"}], "usage": {}}
                    return jsonify(response)
                elif api_type == 'ollamaapichat':
                    current_time = datetime.utcnow().isoformat() + 'Z'
                    response_json = {"model": request_data.get("model", api_helpers.get_model_name()),
                                     "created_at": current_time,
                                     "message": {"role": "assistant", "content": ""}, "done_reason": "stop",
                                     "done": True, "total_duration": 0, "load_duration": 0, "prompt_eval_count": 0,
                                     "prompt_eval_duration": 0, "eval_count": 0, "eval_duration": 0}
                    return jsonify(response_json)
                else:
                    logger.warning(f"Unknown api_type '{api_type}' for OpenWebUI tool request handling.")
                    return None
    return None


def handle_openwebui_tool_check(api_type: str):
    """
    A decorator to check for and handle OpenWebUI tool selection requests.

    This decorator wraps API handler functions to preemptively check for a
    specific prompt format from OpenWebUI. If the prompt indicates a tool
    selection task, the decorator short-circuits the normal workflow execution
    and returns a hardcoded response, allowing OpenWebUI to proceed with
    its tool-calling logic. If the prompt does not match the pattern,
    the original function is executed.

    Args:
        api_type (str): The type of API being handled by the decorated function.
                        This is passed to the internal checking function to
                        determine the correct response format.

    Returns:
        Callable: The decorator itself, which wraps the decorated function
                  with the tool-check logic.
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