# /Middleware/utilities/prompt_extraction_utils.py

import logging
import re
from typing import Dict, Tuple, List, Optional, Any

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

    if not messages:
        return []

    filtered_messages = [message for message in messages if message["role"] != "images"]

    # If remove_all_systems_override is True, filter out all system messages
    if remove_all_systems_override:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
        return filtered_messages[-n:]  # Return the last n non-system messages

    # If include_sysmes is False, filter out all system messages
    if not include_sysmes:
        filtered_messages = [message for message in filtered_messages if message["role"] != "system"]
    else:
        # Find the first non-system message and slice from that point to exclude leading system messages
        first_non_system_index = next((i for i, message in enumerate(filtered_messages) if message["role"] != "system"),
                                      0)
        filtered_messages = filtered_messages[
                            first_non_system_index:]  # Slice from the first non-system message onwards

    # Return only the last n messages from the filtered list
    return filtered_messages[-n:]


def extract_last_n_turns_as_string(messages: List[Dict[str, Any]], n: int, include_sysmes: bool = True,
                                   remove_all_systems_override=False) -> str:
    """
    Extracts and joins the content of the last n messages into a single string.

    This function leverages `extract_last_n_turns` to get a filtered list of
    messages and then concatenates their content into a single string,
    separated by newlines. The handling of system messages is delegated
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

    Returns:
        str: The content of the last `n` messages joined as a single string.
             Returns an empty string if the input messages list is empty.
    """
    if not messages:
        return ""

    # Use the existing helper to get the correct list subset based on system message handling
    last_n_messages = extract_last_n_turns(
        messages, n, include_sysmes, remove_all_systems_override
    )

    # Format the extracted messages by joining their content
    formatted_lines = []
    for message in last_n_messages:
        content = message.get("content", "")
        formatted_lines.append(content)

    return '\n'.join(formatted_lines)


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

    # Regex pattern to extract role and content
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
    logger.debug("Parse conversation result: %s", conversation)
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
    start_index = input_string.find(begin_sys)
    if start_index != -1:
        system_prompt = input_string[start_index + len(begin_sys):].strip()
        remaining_string = input_string[start_index:].replace(system_prompt, "", 1).strip()
    else:
        system_prompt = ""
        remaining_string = input_string
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
    return remaining_string.replace(template["Begin_Sys"], "", 1).strip()