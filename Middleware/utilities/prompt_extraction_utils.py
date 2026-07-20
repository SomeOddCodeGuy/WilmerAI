# /Middleware/utilities/prompt_extraction_utils.py

import json
import logging
import re
from typing import Dict, Tuple, List, Optional, Any

from Middleware.utilities.sensitive_logging_utils import sensitive_log
from Middleware.utilities.text_utils import escape_brackets_in_string, rough_estimate_token_length

logger = logging.getLogger(__name__)

template = {
    "Begin_Sys": "[Beg_Sys]",
    "Begin_User": "[Beg_User]",
    "Begin_Assistant": "[Beg_Assistant]",
    "Begin_SysMes": "[Beg_SysMes]"
}

discussion_identifiers = {
    "discussion_id_start": "[DiscussionId]",
    "discussion_id_end": "[/DiscussionId]"
}

_DISCUSSION_ID_RE = re.compile(
    f'{re.escape(discussion_identifiers["discussion_id_start"])}(.*?)'
    f'{re.escape(discussion_identifiers["discussion_id_end"])}'
)


def _filter_system_messages(messages: List[Dict[str, str]], include_sysmes: bool,
                            remove_all_systems_override: bool) -> List[Dict[str, str]]:
    """
    Applies the system-message filtering rules shared by the extract_last_* selectors.

    Args:
        messages (List[Dict[str, str]]): The conversation messages.
        include_sysmes (bool): When ``True``, only leading system messages are
            dropped; when ``False``, all system messages are dropped.
        remove_all_systems_override (bool): When ``True``, all system messages
            are dropped regardless of ``include_sysmes``.

    Returns:
        List[Dict[str, str]]: The filtered messages (a new list; input unchanged).
    """
    if remove_all_systems_override or not include_sysmes:
        return [message for message in messages if message["role"] != "system"]
    first_non_system_index = next(
        (i for i, message in enumerate(messages) if message["role"] != "system"), 0)
    return messages[first_non_system_index:]


def extract_last_n_turns(messages: List[Dict[str, str]], n: int, include_sysmes: bool = True,
                         remove_all_systems_override=False) -> List[Dict[str, str]]:
    """
    Extracts the last n messages from a list, with options to handle system messages.

    This function extracts a subset of messages from a conversation, ensuring
    that the system messages are handled according to the provided flags.
    It can be configured to include or exclude all system messages, or to
    only exclude leading system messages.

    Args:
        messages (List[Dict[str, str]]): The list of conversation messages. Each message
                                        is a dictionary with a 'role' and 'content'.
        n (int): The number of messages (turns) to extract from the end of the list.
        include_sysmes (bool, optional): If `True`, includes system messages in the
                                         extracted list, excluding only those at the
                                         very beginning of the conversation. If `False`,
                                         all system messages are excluded. Defaults to `True`.
        remove_all_systems_override (bool, optional): If `True`, overrides the
                                                       `include_sysmes` parameter and
                                                       removes all system messages.
                                                       Defaults to `False`.

    Returns:
        List[Dict[str, str]]: A list containing the last `n` messages based on the
                              specified system message handling rules.
    """
    if not messages or n == 0:
        return []

    filtered_messages = _filter_system_messages(messages, include_sysmes, remove_all_systems_override)
    return filtered_messages[-n:]


_ROLE_TAG_MAP = {
    "user": "User: ",
    "assistant": "Assistant: ",
    "system": "System: ",
    "tool": "Tool Result: ",
}


def _format_messages_to_string(messages: List[Dict[str, Any]], add_role_tags: bool = False,
                                separator: str = '\n') -> str:
    """
    Formats a list of message dicts into a single string.

    Args:
        messages (List[Dict[str, Any]]): The messages to format.
        add_role_tags (bool): If ``True``, prepends a role tag to each message
            based on its role: "User: ", "Assistant: ", "System: ", or
            "Tool Result: " (for tool-role messages).
        separator (str): The string used to join messages together.

    Returns:
        str: The formatted string.
    """
    formatted_lines = []
    for message in messages:
        content = message.get("content", "")
        if add_role_tags:
            role = message.get("role", "").lower()
            prefix = _ROLE_TAG_MAP.get(role, "")
            content = prefix + content
        formatted_lines.append(content)

    return separator.join(formatted_lines)


def extract_last_n_turns_as_string(messages: List[Dict[str, Any]], n: int, include_sysmes: bool = True,
                                   remove_all_systems_override=False, add_role_tags: bool = False,
                                   separator: str = '\n') -> str:
    """
    Extracts and joins the content of the last n messages into a single string.

    This function leverages `extract_last_n_turns` to get a filtered list of
    messages and then concatenates their content into a single string,
    separated by the given separator. The handling of system messages is delegated
    to the helper function.

    Args:
        messages (List[Dict[str, Any]]): The list of conversation messages.
                                          Each message is a dictionary with a 'role' and 'content'.
        n (int): The number of messages (turns) to extract.
        include_sysmes (bool, optional): Controls the inclusion of system messages.
                                         See `extract_last_n_turns` for details. Defaults to `True`.
        remove_all_systems_override (bool, optional): If `True`, all system messages
                                                       are removed. See `extract_last_n_turns`
                                                       for details. Defaults to `False`.
        add_role_tags (bool, optional): If `True`, prepends "User: ", "Assistant: ",
                                        "System: ", or "Tool Result: " to each message
                                        based on its role. Defaults to `False`.
        separator (str, optional): The string used to join messages together.
                                    Defaults to ``'\\n'``.

    Returns:
        str: The content of the last `n` messages joined as a single string.
             Returns an empty string if the input messages list is empty.
    """
    if not messages:
        return ""

    last_n_messages = extract_last_n_turns(
        messages, n, include_sysmes, remove_all_systems_override
    )

    return _format_messages_to_string(last_n_messages, add_role_tags, separator)


def extract_last_turns_by_estimated_token_limit(messages: List[Dict[str, str]], token_limit: int,
                                                 include_sysmes: bool = True,
                                                 remove_all_systems_override=False) -> List[Dict[str, str]]:
    """
    Extracts as many recent messages as fit within an estimated token budget.

    This function iterates from the most recent message backwards, accumulating
    estimated token counts until adding the next message would exceed the limit.
    It always returns at least one message, even if that single message exceeds
    the token limit.

    Token estimation uses ``rough_estimate_token_length``, which intentionally
    overestimates to stay safe when enforcing limits.

    Args:
        messages (List[Dict[str, str]]): The list of conversation messages.
        token_limit (int): The maximum estimated token budget.
        include_sysmes (bool, optional): If ``True``, includes system messages
            (excluding leading ones). If ``False``, all system messages are
            excluded. Defaults to ``True``.
        remove_all_systems_override (bool, optional): If ``True``, removes all
            system messages regardless of ``include_sysmes``. Defaults to ``False``.

    Returns:
        List[Dict[str, str]]: Messages fitting within the token budget, in
            chronological order. Always contains at least one message if the
            input is non-empty.
    """
    if not messages:
        return []

    filtered_messages = _filter_system_messages(messages, include_sysmes, remove_all_systems_override)
    if not filtered_messages:
        return []

    accumulated_tokens = 0
    selected = []

    for message in reversed(filtered_messages):
        message_tokens = rough_estimate_token_length(message.get("content") or "")
        if not selected:
            # Always include at least one message
            selected.append(message)
            accumulated_tokens += message_tokens
        elif accumulated_tokens + message_tokens <= token_limit:
            selected.append(message)
            accumulated_tokens += message_tokens
        else:
            break

    return list(reversed(selected))


def extract_last_turns_by_estimated_token_limit_as_string(messages: List[Dict[str, Any]], token_limit: int,
                                                           include_sysmes: bool = True,
                                                           remove_all_systems_override=False,
                                                           add_role_tags: bool = False,
                                                           separator: str = '\n') -> str:
    """
    Extracts recent messages within an estimated token budget and joins them
    into a single string.

    This function leverages ``extract_last_turns_by_estimated_token_limit`` to
    select messages, then concatenates their content with the given separator.

    Args:
        messages (List[Dict[str, Any]]): The list of conversation messages.
        token_limit (int): The maximum estimated token budget.
        include_sysmes (bool, optional): Controls system message inclusion.
            Defaults to ``True``.
        remove_all_systems_override (bool, optional): If ``True``, all system
            messages are removed. Defaults to ``False``.
        add_role_tags (bool, optional): If ``True``, prepends role prefixes
            to each message. Defaults to ``False``.
        separator (str, optional): The string used to join messages together.
            Defaults to ``'\\n'``.

    Returns:
        str: The content of the selected messages joined as a single string.
            Returns an empty string if the input is empty.
    """
    if not messages:
        return ""

    selected_messages = extract_last_turns_by_estimated_token_limit(
        messages, token_limit, include_sysmes, remove_all_systems_override
    )

    return _format_messages_to_string(selected_messages, add_role_tags, separator)


def extract_last_turns_with_min_messages_and_token_limit(messages: List[Dict[str, str]], min_messages: int,
                                                          token_limit: int, include_sysmes: bool = True,
                                                          remove_all_systems_override=False,
                                                          budget_overrides_min: bool = False) -> List[Dict[str, str]]:
    """
    Extracts recent messages up to a minimum count, then expanding up to a token budget.

    This function always includes at least ``min_messages`` messages (counted from
    the most recent backwards).  After that minimum is satisfied, it continues
    adding older messages as long as the cumulative estimated token count does not
    exceed ``token_limit``.  If the minimum messages alone already exceed the
    token limit, the minimum messages are still returned (the message-count floor
    takes precedence), UNLESS ``budget_overrides_min`` is set, in which case the
    floor yields to ``token_limit`` (keeping at least the most-recent message) so
    the selection can never overflow the caller's window.

    Token estimation uses ``rough_estimate_token_length``, which intentionally
    overestimates to stay safe when enforcing limits.

    Args:
        messages (List[Dict[str, str]]): The list of conversation messages.
        min_messages (int): The minimum number of messages to always include.
        token_limit (int): The maximum estimated token budget for expansion
            beyond the minimum message count.
        include_sysmes (bool, optional): If ``True``, includes system messages
            (excluding leading ones). If ``False``, all system messages are
            excluded. Defaults to ``True``.
        remove_all_systems_override (bool, optional): If ``True``, removes all
            system messages regardless of ``include_sysmes``. Defaults to ``False``.
        budget_overrides_min (bool, optional): When ``True``, the ``min_messages``
            floor yields to ``token_limit`` instead of overriding it: whole
            messages are dropped (never content) until the selection fits, but the
            single most-recent message is always kept. Used by the context-window
            clamp so a floored conversation variable cannot overflow the endpoint.
            Defaults to ``False`` (hard floor, the historical behavior).

    Returns:
        List[Dict[str, str]]: Selected messages in chronological order.  Contains
            at least ``min_messages`` messages (or all available), except when
            ``budget_overrides_min`` is set and the budget is smaller, where it may
            contain fewer (down to the single most-recent message).
    """
    if not messages:
        return []

    filtered_messages = _filter_system_messages(messages, include_sysmes, remove_all_systems_override)
    if not filtered_messages:
        return []

    accumulated_tokens = 0
    selected = []

    for message in reversed(filtered_messages):
        message_tokens = rough_estimate_token_length(message.get("content") or "")

        if len(selected) < min_messages:
            # Phase 1: the message-count floor. By default it is a HARD floor: the
            # minimum messages are included even when their tokens exceed the limit.
            # When budget_overrides_min is set (the context-window clamp is on) the
            # floor instead YIELDS to the budget: once an additional floor message
            # would push the total over token_limit we stop, so the selection cannot
            # overflow the caller's window. The single most-recent message is always
            # kept (``selected`` is still empty on the first iteration); only whole
            # messages are dropped, content is never truncated.
            if budget_overrides_min and selected and accumulated_tokens + message_tokens > token_limit:
                break
            selected.append(message)
            accumulated_tokens += message_tokens
        elif accumulated_tokens + message_tokens <= token_limit:
            # Phase 2: expand beyond min_messages while within token budget
            selected.append(message)
            accumulated_tokens += message_tokens
        else:
            break

    return list(reversed(selected))


def extract_last_turns_with_min_messages_and_token_limit_as_string(messages: List[Dict[str, Any]], min_messages: int,
                                                                    token_limit: int, include_sysmes: bool = True,
                                                                    remove_all_systems_override=False,
                                                                    add_role_tags: bool = False,
                                                                    separator: str = '\n',
                                                                    budget_overrides_min: bool = False) -> str:
    """
    Extracts recent messages with a minimum count floor and token budget ceiling,
    then joins them into a single string.

    This function leverages ``extract_last_turns_with_min_messages_and_token_limit``
    to select messages, then concatenates their content with the given separator.

    Args:
        messages (List[Dict[str, Any]]): The list of conversation messages.
        min_messages (int): The minimum number of messages to always include.
        token_limit (int): The maximum estimated token budget for expansion
            beyond the minimum message count.
        include_sysmes (bool, optional): Controls system message inclusion.
            Defaults to ``True``.
        remove_all_systems_override (bool, optional): If ``True``, all system
            messages are removed. Defaults to ``False``.
        add_role_tags (bool, optional): If ``True``, prepends role prefixes
            to each message. Defaults to ``False``.
        separator (str, optional): The string used to join messages together.
            Defaults to ``'\\n'``.
        budget_overrides_min (bool, optional): Forwarded to
            ``extract_last_turns_with_min_messages_and_token_limit``; when ``True``
            the ``min_messages`` floor yields to ``token_limit``. Defaults to
            ``False``.

    Returns:
        str: The content of the selected messages joined as a single string.
            Returns an empty string if the input is empty.
    """
    if not messages:
        return ""

    selected_messages = extract_last_turns_with_min_messages_and_token_limit(
        messages, min_messages, token_limit, include_sysmes, remove_all_systems_override,
        budget_overrides_min=budget_overrides_min
    )

    return _format_messages_to_string(selected_messages, add_role_tags, separator)


def extract_discussion_id(messages: List[Dict[str, str]]) -> Optional[str]:
    """
    Extracts the discussion ID from a list of messages.

    This function iterates through a list of messages to find a specific
    discussion ID enclosed within predefined start and end tags. It returns
    the first ID found.

    Args:
        messages (List[Dict[str, str]]): The list of messages, where each message
                                          is a dictionary containing a 'content' key.

    Returns:
        Optional[str]: The extracted discussion ID as a string if found, otherwise `None`.
    """
    from Middleware.utilities.config_utils import _is_safe_flat_config_name

    for message in messages:
        match = _DISCUSSION_ID_RE.search(message['content'])
        if match:
            discussion_id = match.group(1)
            # The discussion id is joined into filesystem paths (discussion folder,
            # cursor files, vision cache, {Discussion_Id} templates). A value with a
            # path separator, drive colon, or '..' could escape the intended folder,
            # so reject it here at the single point of extraction and treat the request
            # as stateless rather than propagate an unsafe path component downstream.
            # An empty tag (already falsy/stateless downstream) is left untouched.
            if discussion_id and not _is_safe_flat_config_name(discussion_id):
                logger.warning(
                    "Ignoring DiscussionId containing path-unsafe characters; "
                    "processing request without a discussion id."
                )
                return None
            return discussion_id
    return None


def remove_discussion_id_tag(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Removes the discussion ID tag from the content of all messages in a list.

    This function iterates through each message in the provided list and
    removes the discussion ID and its surrounding tags from the message's
    'content' string.

    Args:
        messages (List[Dict[str, str]]): The list of messages that may contain
                                          the discussion ID tag.

    Returns:
        List[Dict[str, str]]: The original list of messages with the discussion
                              ID tag removed from their content.
    """
    for message in messages:
        message['content'] = remove_discussion_id_tag_from_string(message['content'])
    return messages


def remove_discussion_id_tag_from_string(message: str) -> str:
    """
    Removes the discussion ID tag from a single message string.

    This function uses a regular expression to find and remove the
    discussion ID and its surrounding tags from a given string.

    Args:
        message (str): The string content of a message that may contain the
                       discussion ID tag.

    Returns:
        str: The message string with the discussion ID tag removed.
    """
    return _DISCUSSION_ID_RE.sub('', message)


def separate_messages(messages: List[Dict[str, str]], separate_sysmes: bool = False) -> Tuple[
    str, List[Dict[str, str]]]:
    """
    Separates a list of messages into a system prompt and a conversation list.

    This function processes a list of messages, extracting content with the
    'system' role into a single system prompt string and placing all
    other messages into a separate conversation list. The behavior for
    system messages is conditional on the `separate_sysmes` flag.

    Args:
        messages (List[Dict[str, str]]): A list of messages, where each message
                                          is a dictionary with a 'role' and 'content'.
        separate_sysmes (bool, optional): If `True`, only initial system messages
                                          are extracted into the system prompt. Subsequent
                                          system messages are treated as part of the
                                          conversation. If `False`, all system messages
                                          are concatenated into the system prompt.
                                          Defaults to `False`.

    Returns:
        Tuple[str, List[Dict[str, str]]]: A tuple containing:
                                           - `str`: The concatenated system prompt.
                                           - `List[Dict[str, str]]`: The remaining conversation messages.

    Raises:
        ValueError: If a message in the input list is missing the 'role' or 'content' key.
    """
    system_prompt_list = []
    conversation = []
    for message in messages:
        if 'role' not in message or 'content' not in message:
            raise ValueError("Message is missing the 'role' or 'content' key.")

        role = message['role'].lower()
        if role == 'system' and (not separate_sysmes or not conversation):
            system_prompt_list.append(message['content'])
        else:
            conversation.append(message)
    system_prompt = ' '.join(system_prompt_list)
    return system_prompt, conversation


def parse_conversation(input_string: str) -> List[Dict[str, str]]:
    """
    Parses a conversation string with custom tags into a list of messages.

    This function uses a regular expression to identify and extract messages
    from a string formatted with specific tags (e.g., `[Beg_Sys]`, `[Beg_User]`).
    It then organizes the extracted content into a list of dictionaries, where
    each dictionary represents a message with a 'role' and 'content'.

    Args:
        input_string (str): The string containing the tagged conversation content.

    Returns:
        List[Dict[str, str]]: The parsed list of messages.
    """
    tags = {
        "Sys": "system",
        "SysMes": "systemMes",
        "User": "user",
        "Assistant": "assistant"
    }

    pattern = r'\[Beg_(\w+)\](.*?)(?=\[Beg_\w+\]|$)'
    matches = re.findall(pattern, input_string, flags=re.DOTALL)

    conversation = []
    sys_count = 0

    for role_key, content in matches:
        content = content.strip()

        if role_key == "Sys":
            sys_count += 1
            role = "system" if sys_count == 1 else "systemMes"
        else:
            role = tags.get(role_key)

        if role:
            conversation.append({"role": role, "content": content})
    sensitive_log(logger, logging.DEBUG, "Parse conversation result: %s", conversation)
    return conversation


def _summarize_tool_arguments(arguments: Any) -> str:
    """
    Extracts a brief summary from a tool call's arguments.

    Accepts either the OpenAI-style JSON string form or the Ollama-native dict
    form. Returns the value of the first string-typed field, truncated to 200
    characters. If no string field exists (or the value cannot be parsed as a
    dict), returns a truncated string rendering of the raw arguments.

    Args:
        arguments (Any): The tool call arguments: a JSON string, a dict, or
            any other value a backend might supply.

    Returns:
        str: A short summary of the arguments.
    """
    parsed = arguments
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, str):
                return value[:200]
    # No string field found, or the arguments were neither a JSON object string
    # nor a dict: fall back to a truncated string form of whatever was passed.
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments[:200]
    return str(arguments)[:200]


def format_tool_calls_as_text(tool_calls: List[Dict[str, Any]]) -> str:
    """
    Converts a list of tool call objects into a human-readable text block.

    Each tool call is rendered as ``[Tool Call: {name}] {summary}``, where
    the summary is the first string-valued argument (or the raw arguments
    truncated to 200 characters).

    Args:
        tool_calls (List[Dict[str, Any]]): A list of tool call dicts, each
            containing a ``function`` key with ``name`` and ``arguments``.

    Returns:
        str: One line per tool call, joined by newlines.
    """
    parts = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        func = call.get("function")
        if not isinstance(func, dict):
            func = {}
        name = func.get("name", "unknown")
        args_str = func.get("arguments", "")
        summary = _summarize_tool_arguments(args_str)
        parts.append(f"[Tool Call: {name}] {summary}")
    return "\n".join(parts)


def _tool_call_label_map(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Builds a lookup from each assistant tool-call ``id`` to a short label of the
    form ``"{name} {summary}"`` (the same summary used for ``[Tool Call: ...]``).

    Tool-result messages (``role == "tool"``) typically carry only a
    ``tool_call_id`` referencing the assistant call, not the tool name itself.
    This map lets a result be labeled with the tool that produced it and the
    target it acted on (for example the file a ``read`` returned or a ``write``
    landed on) instead of an opaque ``unknown_tool``.

    Args:
        messages (List[Dict[str, Any]]): The conversation messages.

    Returns:
        Dict[str, str]: Mapping of tool-call id to its rendered label. Calls
            without an id are skipped.
    """
    label_by_call_id: Dict[str, str] = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id:
                continue
            func = call.get("function")
            if not isinstance(func, dict):
                func = {}
            name = func.get("name", "unknown")
            summary = _summarize_tool_arguments(func.get("arguments", ""))
            label_by_call_id[call_id] = f"{name} {summary}" if summary else name
    return label_by_call_id


def enrich_messages_with_tool_calls(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Returns a shallow copy of messages with tool-related text injected into
    message content for assistant and tool-result messages.

    For each assistant message that has a ``tool_calls`` field, the formatted
    tool call text (``[Tool Call: {name}] {summary}``) is appended to (or
    used as) the message content.

    For each tool-result message (``role == "tool"``), a ``[Tool Result: {name}]``
    prefix is prepended to the content so downstream consumers can identify
    which tool produced the output. Because a result usually carries only a
    ``tool_call_id`` and not the tool name, the name (and its argument summary,
    e.g. the file path) is recovered from the originating assistant call via
    that id; it falls back to an explicit ``name`` field and then to
    ``unknown_tool``.

    Messages that do not need enrichment are passed through as-is.

    Args:
        messages (List[Dict[str, Any]]): The conversation messages.

    Returns:
        List[Dict[str, Any]]: A new list of message dicts.  Only messages
            that needed enrichment are copied; others are passed through
            as-is.
    """
    label_by_call_id = _tool_call_label_map(messages)

    result = []
    for message in messages:
        tool_calls = message.get("tool_calls")
        if tool_calls and message.get("role") == "assistant":
            msg = dict(message)
            tool_text = format_tool_calls_as_text(tool_calls)
            # Tool call text may contain raw curly braces (e.g., JSON
            # arguments).  Escape them with the same sentinel tokens used at
            # the gateway for message content so that downstream
            # str.format() in apply_variables() does not misinterpret them.
            tool_text = escape_brackets_in_string(tool_text)
            content = msg.get("content") or ""
            if content:
                msg["content"] = content + "\n" + tool_text
            else:
                msg["content"] = tool_text
            result.append(msg)
        elif message.get("role") == "tool":
            msg = dict(message)
            # Attribute the result to the call that produced it: results usually
            # carry only a tool_call_id, so recover the tool name (and its
            # argument summary, e.g. the file path) from the originating call.
            # Fall back to an explicit name, then a constant.
            call_id = message.get("tool_call_id")
            tool_name = label_by_call_id.get(call_id) if isinstance(call_id, str) else None
            if not tool_name:
                tool_name = message.get("name") or "unknown_tool"
            content = msg.get("content") or ""
            # Escape both the tool name and the content: a tool name containing
            # raw curly braces would otherwise survive to the downstream
            # str.format() pass in apply_variables() and could raise.
            tool_name = escape_brackets_in_string(tool_name)
            content = escape_brackets_in_string(content)
            msg["content"] = f"[Tool Result: {tool_name}] {content}"
            result.append(msg)
        else:
            result.append(message)
    return result
