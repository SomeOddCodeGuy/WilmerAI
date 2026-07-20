# Middleware/api/workflow_gateway.py

import json
import logging
import os
from typing import Any, Dict, List, Generator, Optional, Union

from flask import jsonify, Response

from Middleware.api import api_helpers
from Middleware.services.prompt_categorization_service import PromptCategorizationService
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities import config_utils
from Middleware.utilities.config_utils import get_custom_workflow_is_active, get_active_custom_workflow_name, \
    get_shared_workflows_folder
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id
from Middleware.utilities.text_utils import replace_brackets_in_list
from Middleware.workflows.managers.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()

# Machinery-injected turns must be one-shot: the model sees them exactly once,
# as the trailing exchange of the request immediately following the
# injection, where they act as corrective feedback ("your last reply had no
# tool call"), and they are stripped from every conversation in which they
# sit buried, so a small model never sees them as a repeatable pattern it
# could adopt. Without the trailing visibility the model gets no signal that
# anything happened and repeats the tool-less reply; with more than one
# occurrence visible it starts imitating the injection as its own action
# (run-5 failure mode). Genuine injections carry this tool-call id prefix;
# the marker substring in tool-call arguments identifies machinery turns more
# broadly, including model-emitted imitations of an earlier injection.
MACHINERY_TOOL_CALL_ID_PREFIX = "wilmer_liveness_"
MACHINERY_MARKER = "[Wilmer]"


def _is_machinery_tool_call(tool_call: Any, liveness_config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Determines whether a single tool call is Wilmer machinery rather than a
    genuine model action.

    A tool call is machinery when its id carries the liveness-injection prefix,
    when its serialized arguments contain the machinery marker, or when it is
    exactly the user's configured liveness call (name plus arguments). The
    marker check also catches model-emitted imitations of an injected call,
    which must be stripped exactly like the genuine article. The configured-call
    match exists because Ollama's wire format carries no tool-call id: an echo
    of the injection loses the id prefix, and when the configured arguments
    also lack the marker, equality with the configuration is the only remaining
    signal.

    Args:
        tool_call (Any): One entry from an assistant message's ``tool_calls``
            list. Malformed entries are tolerated and reported as not machinery.
        liveness_config (Optional[Dict[str, Any]]): The user's validated
            ``livenessToolCall`` configuration, when available.

    Returns:
        bool: True when the tool call is machinery-injected or an imitation.
    """
    if not isinstance(tool_call, dict):
        return False
    call_id = tool_call.get("id")
    if isinstance(call_id, str) and call_id.startswith(MACHINERY_TOOL_CALL_ID_PREFIX):
        return True
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return False
    arguments = function.get("arguments")
    if isinstance(arguments, dict):
        try:
            arguments = json.dumps(arguments)
        except (TypeError, ValueError):
            arguments = None
    if isinstance(arguments, str) and MACHINERY_MARKER in arguments:
        return True
    return _matches_configured_liveness_call(tool_call, liveness_config)


def _matches_configured_liveness_call(tool_call: Dict[str, Any],
                                      liveness_config: Optional[Dict[str, Any]]) -> bool:
    """
    Checks whether a tool call is exactly the configured liveness call.

    Mirrors the injection side (response_handler._build_liveness_tool_calls):
    the tool name is compared stripped, missing/non-dict configured arguments
    count as ``{}``, and the call's arguments are accepted as either a dict
    (Ollama wire shape) or a JSON string (OpenAI wire shape).

    Args:
        tool_call (Dict[str, Any]): The tool call to test.
        liveness_config (Optional[Dict[str, Any]]): The user's validated
            ``livenessToolCall`` configuration, or None when unset.

    Returns:
        bool: True when name and arguments both match the configuration.
    """
    if not isinstance(liveness_config, dict):
        return False
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return False
    tool_name = liveness_config.get("toolName")
    if not isinstance(tool_name, str) or function.get("name") != tool_name.strip():
        return False
    expected = liveness_config.get("arguments")
    if not isinstance(expected, dict):
        expected = {}
    actual = function.get("arguments")
    if isinstance(actual, str):
        try:
            actual = json.loads(actual)
        except (TypeError, ValueError):
            return False
    if actual is None:
        actual = {}
    return actual == expected


def _trailing_machinery_indices(messages: List[Any],
                                liveness_config: Optional[Dict[str, Any]] = None) -> set:
    """
    Identifies the trailing machinery exchange of a conversation, if any.

    The trailing exchange is the conversation's final assistant tool-call turn
    plus the ``role: "tool"`` results that follow it, ignoring any assistant
    filler appended after them: empty content, or the bare "Assistant:"
    prompt used when chatCompleteAddUserAssistant is enabled. When that
    turn contains a machinery call, the exchange is the one the frontend just
    executed in direct response to a liveness injection, the single moment
    the model must see it as corrective feedback.

    Args:
        messages (List[Any]): The raw ingested conversation.

    Returns:
        set: Indices of the trailing exchange's messages when its assistant
        turn carries a machinery call; empty set otherwise.
    """
    idx = len(messages) - 1
    while idx >= 0:
        message = messages[idx]
        if not isinstance(message, dict) or message.get("role") != "assistant" \
                or message.get("tool_calls"):
            break
        content = message.get("content")
        stripped = content.strip() if isinstance(content, str) else ""
        if stripped and stripped != "Assistant:":
            break
        idx -= 1
    tool_indices = set()
    while idx >= 0:
        message = messages[idx]
        if isinstance(message, dict) and message.get("role") == "tool":
            tool_indices.add(idx)
            idx -= 1
            continue
        break
    if idx >= 0:
        message = messages[idx]
        if isinstance(message, dict) and message.get("role") == "assistant" \
                and isinstance(message.get("tool_calls"), list) \
                and any(_is_machinery_tool_call(tc, liveness_config) for tc in message["tool_calls"]):
            return tool_indices | {idx}
    return set()


def strip_machinery_turns(messages: List[Dict[str, Any]],
                          liveness_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Removes buried machinery no-op turns from an ingested conversation.

    The trailing machinery exchange (the injection the frontend executed
    immediately before this request) is kept intact as one-shot corrective
    feedback (see ``_trailing_machinery_indices``). Everywhere else, assistant
    turns whose tool calls are machinery (see ``_is_machinery_tool_call``) lose
    those calls; a turn left with no genuine tool calls and no content is
    dropped entirely. Paired ``role: "tool"`` result messages are dropped with
    them, matched by ``tool_call_id`` or, for results that carry no id, by
    immediate adjacency to a turn whose calls were all machinery. All other
    messages pass through untouched.

    Args:
        messages (List[Dict[str, Any]]): The raw ingested conversation.

    Returns:
        List[Dict[str, Any]]: The conversation with buried machinery turns
        removed.
    """
    trailing_keep = _trailing_machinery_indices(messages, liveness_config)
    stripped_ids = set()
    stripped_count = 0
    pending_adjacent_result_drops = 0
    result = []

    for index, message in enumerate(messages):
        if index in trailing_keep:
            result.append(message)
            continue

        if not isinstance(message, dict):
            pending_adjacent_result_drops = 0
            result.append(message)
            continue

        role = message.get("role")

        if role == "tool":
            tool_call_id = message.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id in stripped_ids:
                stripped_count += 1
                continue
            if tool_call_id is None and pending_adjacent_result_drops > 0:
                pending_adjacent_result_drops -= 1
                stripped_count += 1
                continue
            result.append(message)
            continue

        pending_adjacent_result_drops = 0

        tool_calls = message.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            kept_calls = []
            dropped_calls = 0
            for tool_call in tool_calls:
                if _is_machinery_tool_call(tool_call, liveness_config):
                    dropped_calls += 1
                    call_id = tool_call.get("id")
                    if isinstance(call_id, str) and call_id:
                        stripped_ids.add(call_id)
                else:
                    kept_calls.append(tool_call)

            if dropped_calls:
                stripped_count += 1
                if not kept_calls:
                    # Only an all-machinery turn allows adjacency matching for
                    # id-less results; with genuine calls kept, an id-less
                    # result cannot be attributed safely and is retained.
                    pending_adjacent_result_drops = dropped_calls
                content = message.get("content")
                stripped_content = content.strip() if isinstance(content, str) else ""
                # The bare "Assistant:" prompt is chatCompleteAddUserAssistant
                # filler the API handler prepends before this strip runs, not
                # genuine content (mirrors _trailing_machinery_indices).
                has_content = bool(stripped_content) and stripped_content != "Assistant:"
                if kept_calls or has_content:
                    kept_message = dict(message)
                    if kept_calls:
                        kept_message["tool_calls"] = kept_calls
                    else:
                        kept_message.pop("tool_calls", None)
                    result.append(kept_message)
                continue

        result.append(message)

    if stripped_count:
        logger.info(f"Stripped {stripped_count} machinery no-op turn(s) from ingested conversation")

    return result


def _tool_call_signature(message: Any) -> Optional[str]:
    """
    Produces a comparable signature for a single-tool-call assistant turn.

    Args:
        message (Any): A conversation message.

    Returns:
        Optional[str]: "name|arguments" when the message is an assistant turn
        carrying exactly one well-formed tool call; None otherwise (multi-call
        turns and malformed entries never participate in duplicate collapsing).
    """
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        return None
    call = tool_calls[0]
    if not isinstance(call, dict):
        return None
    function = call.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    arguments = function.get("arguments")
    if isinstance(arguments, dict):
        try:
            arguments = json.dumps(arguments, sort_keys=True)
        except (TypeError, ValueError):
            return None
    if not isinstance(name, str) or not isinstance(arguments, str):
        return None
    return f"{name}|{arguments}"


def _result_signature(message: Any) -> Optional[str]:
    """
    Produces a comparable signature for a tool-result message.

    Args:
        message (Any): A conversation message.

    Returns:
        Optional[str]: The whitespace-normalized result content when the
        message is a ``role: "tool"`` entry; None otherwise.
    """
    if not isinstance(message, dict) or message.get("role") != "tool":
        return None
    content = message.get("content")
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    return " ".join(content.split())


# A small model that repeats one tool call verbatim, turn after turn, has
# fallen into a repetition attractor: every copy of the exchange it sees in
# history reinforces the next repeat, and identical empty results get
# misread as tool failure. Collapsing the run removes the reinforcement and
# the note tells the model, at the exact place it looks (the tool result),
# that repeating the call is pointless. Three identical call/result pairs is
# already pathological; two can be a legitimate retry.
DUPLICATE_TOOL_CALL_COLLAPSE_THRESHOLD = 3


def collapse_duplicate_tool_calls(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collapses runs of identical tool-call exchanges in an ingested conversation.

    A run is DUPLICATE_TOOL_CALL_COLLAPSE_THRESHOLD or more consecutive
    exchanges (each an assistant turn making exactly one tool call followed
    by its single result) where every call and every result in the run is
    identical. The run is replaced by its first exchange, with a note appended
    to the kept result stating how many times the call was repeated and that
    further repeats will not change the outcome. Runs shorter than the
    threshold, multi-call turns, differing arguments, and differing results
    all pass through untouched.

    Args:
        messages (List[Dict[str, Any]]): The raw ingested conversation.

    Returns:
        List[Dict[str, Any]]: The conversation with duplicate runs collapsed.
    """
    result = []
    index = 0
    total = len(messages)
    while index < total:
        call_sig = _tool_call_signature(messages[index])
        result_sig = _result_signature(messages[index + 1]) if index + 1 < total else None
        if call_sig is None or result_sig is None:
            result.append(messages[index])
            index += 1
            continue

        run_length = 1
        probe = index + 2
        while probe + 1 < total \
                and _tool_call_signature(messages[probe]) == call_sig \
                and _result_signature(messages[probe + 1]) == result_sig:
            run_length += 1
            probe += 2

        if run_length >= DUPLICATE_TOOL_CALL_COLLAPSE_THRESHOLD:
            kept_call = messages[index]
            kept_result = dict(messages[index + 1])
            content = kept_result.get("content")
            if not isinstance(content, str):
                content = "" if content is None else str(content)
            kept_result["content"] = (
                f"{content}\n\n[Wilmer note: this exact tool call was made "
                f"{run_length} consecutive times and every result was identical. "
                f"Repeating it again will not change the outcome; take a different action.]"
            )
            result.append(kept_call)
            result.append(kept_result)
            logger.info(
                f"Collapsed a run of {run_length} identical tool-call exchanges from ingested conversation")
            index = probe
        else:
            result.append(messages[index])
            result.append(messages[index + 1])
            index += 2
    return result


def handle_user_prompt(request_id: str, prompt_collection: List[Dict[str, Any]], stream: bool, api_key: str = None,
                       tools: list = None, tool_choice=None) -> Union[str, Generator[str, None, None]]:
    """
    Processes a user prompt by routing it to the appropriate workflow.

    When the user has ``livenessToolCall`` configured, machinery no-op turns
    (liveness injections and any model imitations of them) are stripped from
    the conversation before routing, so internal nodes never see them, and
    runs of identical tool-call exchanges are collapsed (see
    strip_machinery_turns and collapse_duplicate_tool_calls). Users without
    that setting never have their conversation rewritten.

    The workflow is determined by the following priority:
    1. Workflow override from API model field (if set via api_helpers.set_workflow_override)
    2. Custom workflow from user config (if get_custom_workflow_is_active is True)
    3. Dynamic routing via PromptCategorizationService

    Args:
        request_id (str): The unique identifier for this request.
        prompt_collection (List[Dict[str, Any]]): The list of messages representing the conversation.
        stream (bool): A flag indicating whether to return a streaming response.
        api_key (str): The API key from the request, if present.
        tools (list): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Union[str, Generator[str, None, None]]: The complete response string or a generator for streaming chunks.
    """
    liveness_config = config_utils.get_liveness_tool_call()
    if liveness_config is not None:
        prompt_collection = strip_machinery_turns(prompt_collection, liveness_config)
        prompt_collection = collapse_duplicate_tool_calls(prompt_collection)

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
            workflow_user_folder_override=folder_path,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice
        )

    if not get_custom_workflow_is_active():
        request_routing_service = PromptCategorizationService()

        # The categorization workflow requires the full conversation context.
        return request_routing_service.get_prompt_category(
            messages=sanitized_messages,
            request_id=request_id,
            discussion_id=discussion_id,
            stream=stream,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice
        )
    else:
        logger.info("Custom workflow is active, running workflow.")

        return WorkflowManager.run_custom_workflow(
            workflow_name=get_active_custom_workflow_name(),
            request_id=request_id,
            discussion_id=discussion_id,
            messages=sanitized_messages,
            is_streaming=stream,
            api_key=api_key,
            tools=tools,
            tool_choice=tool_choice
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

    return _sanitize_recursive(data)


def check_openwebui_tool_request(request_data: Dict[str, Any], api_type: str) -> Optional[Response]:
    """
    Checks for OpenWebUI tool selection requests and returns an early response
    if the current user has ``interceptOpenWebUIToolRequests`` enabled.

    This must be called **after** request context is set (after
    ``set_workflow_override``), so that the correct user's config is read.

    When interception is disabled (the default), tool selection requests are
    routed through the normal workflow pipeline like any other request.

    Args:
        request_data (Dict[str, Any]): The incoming request JSON payload.
        api_type (str): The API compatibility type (e.g., 'openaichatcompletion').

    Returns:
        Optional[Response]: A Flask Response object if a tool selection request
            is detected and interception is enabled, otherwise None.
    """
    if not config_utils.get_intercept_openwebui_tool_requests():
        return None

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
