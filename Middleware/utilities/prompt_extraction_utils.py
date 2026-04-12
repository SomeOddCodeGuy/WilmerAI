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

    filtered_messages = list(messages)

    if remove_all_systems_override:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
        return filtered_messages[-n:]

    if not include_sysmes:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
    else:
        first_non_system_index = next((i for i, message in enumerate(filtered_messages) if message["role"] != "system"),
                                      0)
        filtered_messages = filtered_messages[first_non_system_index:]

    return filtered_messages[-n:]


_ROLE_TAG_MAP = {
    "user": "User: ",
    "assistant": "Assistant: ",
    "system": "System: ",
}


def _format_messages_to_string(messages: List[Dict[str, Any]], add_role_tags: bool = False,
                                separator: str = '\n') -> str:
    """
    Formats a list of message dicts into a single string.

    Args:
        messages (List[Dict[str, Any]]): The messages to format.
        add_role_tags (bool): If ``True``, prepends "User: ", "Assistant: ", or
            "System: " to each message based on its role.
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
        add_role_tags (bool, optional): If `True`, prepends "User: ", "Assistant: ", or
                                        "System: " to each message based on its role.
                                        Defaults to `False`.
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

    filtered_messages = list(messages)

    if remove_all_systems_override:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
    elif not include_sysmes:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
    else:
        first_non_system_index = next(
            (i for i, message in enumerate(filtered_messages) if message["role"] != "system"), 0
        )
        filtered_messages = filtered_messages[first_non_system_index:]

    if not filtered_messages:
        return []

    accumulated_tokens = 0
    selected = []

    for message in reversed(filtered_messages):
        message_tokens = rough_estimate_token_length(message.get("content", ""))
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
                                                          remove_all_systems_override=False) -> List[Dict[str, str]]:
    """
    Extracts recent messages up to a minimum count, then expanding up to a token budget.

    This function always includes at least ``min_messages`` messages (counted from
    the most recent backwards).  After that minimum is satisfied, it continues
    adding older messages as long as the cumulative estimated token count does not
    exceed ``token_limit``.  If the minimum messages alone already exceed the
    token limit, the minimum messages are still returned (the message-count floor
    takes precedence).

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

    Returns:
        List[Dict[str, str]]: Selected messages in chronological order.  Always
            contains at least ``min_messages`` messages (or all available messages
            if fewer exist).
    """
    if not messages:
        return []

    filtered_messages = list(messages)

    if remove_all_systems_override:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
    elif not include_sysmes:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
    else:
        first_non_system_index = next(
            (i for i, message in enumerate(filtered_messages) if message["role"] != "system"), 0
        )
        filtered_messages = filtered_messages[first_non_system_index:]

    if not filtered_messages:
        return []

    accumulated_tokens = 0
    selected = []

    for message in reversed(filtered_messages):
        message_tokens = rough_estimate_token_length(message.get("content", ""))

        if len(selected) < min_messages:
            # Phase 1: always include up to min_messages
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
                                                                    separator: str = '\n') -> str:
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

    Returns:
        str: The content of the selected messages joined as a single string.
            Returns an empty string if the input is empty.
    """
    if not messages:
        return ""

    selected_messages = extract_last_turns_with_min_messages_and_token_limit(
        messages, min_messages, token_limit, include_sysmes, remove_all_systems_override
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
    pattern = f'{re.escape(discussion_identifiers["discussion_id_start"])}(.*?){re.escape(discussion_identifiers["discussion_id_end"])}'
    for message in messages:
        match = re.search(pattern, message['content'])
        if match:
            return match.group(1)
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
    pattern = f'{re.escape(discussion_identifiers["discussion_id_start"])}.*?{re.escape(discussion_identifiers["discussion_id_end"])}'
    return re.sub(pattern, '', message)


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


def extract_initial_system_prompt(input_string: str, begin_sys: str) -> Tuple[str, str]:
    """
    Extracts the initial system prompt and the rest of the string.

    This function searches for a specific system prompt tag at the beginning of
    a string. If found, it separates the system prompt content from the rest of
    the string and returns both parts.

    Args:
        input_string (str): The full input string, potentially containing a
                            system prompt.
        begin_sys (str): The starting tag that marks the beginning of the
                         system prompt.

    Returns:
        Tuple[str, str]: A tuple containing:
                         - `str`: The extracted system prompt content.
                         - `str`: The remaining part of the string after the
                                  system prompt and its tag have been removed.
    """
    if not input_string.startswith(begin_sys):
        return "", input_string

    # Find the end of the system prompt, which is the start of the next tag or the end of the string
    rest_of_string = input_string[len(begin_sys):]
    next_tag_match = re.search(r'\[Beg_\w+\]', rest_of_string)

    if next_tag_match:
        split_index = next_tag_match.start()
        system_prompt = rest_of_string[:split_index].strip()
        remaining_string = rest_of_string[split_index:].strip()
    else:
        system_prompt = rest_of_string.strip()
        remaining_string = ""

    return system_prompt, remaining_string


def process_remaining_string(remaining_string: str, template: Dict[str, str]) -> str:
    """
    Removes the initial system prompt tag from a string.

    This is a helper function that specifically removes the `Begin_Sys` tag
    from the beginning of a given string.

    Args:
        remaining_string (str): The string to process, from which the tag
                                should be removed.
        template (Dict[str, str]): A dictionary containing the tag definitions.

    Returns:
        str: The processed string with the `Begin_Sys` tag removed.
    """
    if remaining_string.startswith(template["Begin_Sys"]):
        return remaining_string[len(template["Begin_Sys"]):].strip()
    return remaining_string.strip()


def _summarize_tool_arguments(arguments_str: str) -> str:
    """
    Extracts a brief summary from a tool call's arguments JSON string.

    Parses the JSON and returns the value of the first string-typed field,
    truncated to 200 characters.  If parsing fails or no string field exists,
    returns the raw arguments string truncated to 200 characters.

    Args:
        arguments_str (str): The raw JSON string of tool call arguments.

    Returns:
        str: A short summary of the arguments.
    """
    try:
        args = json.loads(arguments_str)
        if isinstance(args, dict):
            for value in args.values():
                if isinstance(value, str):
                    return value[:200]
    except (json.JSONDecodeError, TypeError):
        pass
    return (arguments_str or "")[:200]


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
        func = call.get("function", {})
        name = func.get("name", "unknown")
        args_str = func.get("arguments", "")
        summary = _summarize_tool_arguments(args_str)
        parts.append(f"[Tool Call: {name}] {summary}")
    return "\n".join(parts)


def enrich_messages_with_tool_calls(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Returns a shallow copy of messages with tool call text injected into
    assistant message content.

    For each assistant message that has a ``tool_calls`` field, the formatted
    tool call text is appended to (or used as) the message content. Messages
    without tool calls are returned unchanged.

    Args:
        messages (List[Dict[str, Any]]): The conversation messages.

    Returns:
        List[Dict[str, Any]]: A new list of message dicts.  Only messages
            that needed enrichment are copied; others are passed through
            as-is.
    """
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
        else:
            result.append(message)
    return result
