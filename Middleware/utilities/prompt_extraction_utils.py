import logging
import re
from copy import deepcopy
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
    Extract the last n messages, including system messages if include_sysmes is True.
    When include_sysmes is True, only system messages at the very beginning of the list are excluded.

    Parameters:
    messages (List[Dict[str, str]]): The list of messages.
    n (int): The number of messages to extract.
    include_sysmes (bool, optional): Whether to include system messages that are not at the start of the list. Defaults to True.
    Returns:
    List[Dict[str, str]]: The last n messages, with system messages included as specified.
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
    Extract the last n messages as a single string, including system messages if include_sysmes is True.
    If include_sysmes is False, all system messages are excluded.
    Parameters:
    messages (List[Dict[str, Any]]): The list of messages.
    n (int): The number of messages to extract.
    include_sysmes (bool, optional): Whether to include system messages in the output. Defaults to True.
    Returns:
    str: The last n messages as a single string.
    """
    message_copy = deepcopy(messages)
    message_copy = [message for message in message_copy if message["role"] != "images"]

    if remove_all_systems_override:
        filtered_messages = [message for message in message_copy if message["role"] != "system"]
        return '\n'.join(message["content"] for message in filtered_messages)

    index_of_first_non_system_message = next(
        (i for i, message in enumerate(message_copy) if message["role"] != "system"),
        None)

    if include_sysmes and index_of_first_non_system_message is not None:
        message_copy = message_copy[index_of_first_non_system_message:]

    if not include_sysmes:
        message_copy = [message for message in message_copy if message["role"] not in {"system", "sysmes"}]

    return '\n'.join(message["content"] for message in message_copy[-n:])


def extract_discussion_id(messages: List[Dict[str, str]]) -> Optional[str]:
    """
    Extracts the discussion ID from the input messages.

    This function searches for the discussion ID enclosed within specific start and end tags
    and returns the numeric ID.

    Parameters:
    messages (List[Dict[str, str]]): The list of messages containing the discussion ID.

    Returns:
    Optional[str]: The extracted numeric discussion ID, or None if not found.
    """
    pattern = f'{re.escape(discussion_identifiers["discussion_id_start"])}(.*?){re.escape(discussion_identifiers["discussion_id_end"])}'
    for message in messages:
        match = re.search(pattern, message['content'])
        if match:
            return match.group(1)
    return None


def remove_discussion_id_tag(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Removes the discussion ID tag from the input messages.

    This function identifies and removes the discussion ID and its surrounding tags
    from the content of each message.

    Parameters:
    messages (List[Dict[str, str]]): The list of messages containing the discussion ID tag.

    Returns:
    List[Dict[str, str]]: The list of messages with the discussion ID tag removed.
    """
    for message in messages:
        message['content'] = remove_discussion_id_tag_from_string(message['content'])
    return messages


def remove_discussion_id_tag_from_string(message: str) -> str:
    """
    Removes the discussion ID tag from a single message string.

    This function identifies and removes the discussion ID and its surrounding tags
    from the content of the message.

    Parameters:
    message (str): The message string containing the discussion ID tag.

    Returns:
    str: The message string with the discussion ID tag removed.
    """
    pattern = f'{re.escape(discussion_identifiers["discussion_id_start"])}.*?{re.escape(discussion_identifiers["discussion_id_end"])}'
    return re.sub(pattern, '', message)


def separate_messages(messages: List[Dict[str, str]], separate_sysmes: bool = False) -> Tuple[
    str, List[Dict[str, str]]]:
    """
    Processes a list of messages to extract system prompts and organize the conversation.

    Parameters:
    - messages (List[Dict[str, str]]): A list of messages with roles ('system', 'user', 'assistant') and content.
    - separate_sysmes (bool, optional): If True, only the system messages at the start of the messages list are extracted into the system prompt. Subsequent system messages are included in the conversation. If False, all system messages are extracted into the system prompt, and other roles are included in the conversation. Defaults to False.

    Returns:
    - Tuple[str, List[Dict[str, str]]]: A tuple containing the system prompt and the remaining conversation messages.
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
    Parses a conversation string into a list of messages with roles and content.

    Parameters:
    input_string (str): The input string containing the conversation.

    Returns:
    List[Dict[str, str]]: The parsed list of messages.
    """
    tags = {
        "Sys": "system",
        "SysMes": "systemMes",
        "User": "user",
        "Assistant": "assistant"
    }
    conversation = []
    beg_sys_message = None
    parts = input_string.split('[Beg_')
    for part in parts[1:]:
        if ']' in part:
            role_key, content = part.split(']', 1)
            role = tags.get(role_key)
            if role:
                message = {"role": role, "content": content.strip()}
                if role_key == "Sys":
                    beg_sys_message = message
                else:
                    conversation.append(message)
    if beg_sys_message:
        conversation.insert(0, beg_sys_message)
    logger.debug("Parse conversation result: %s", conversation)
    return conversation


def extract_initial_system_prompt(input_string: str, begin_sys: str) -> Tuple[str, str]:
    """
    Extracts the initial system prompt from the input string.

    Parameters:
    input_string (str): The input string containing the system prompt.
    begin_sys (str): The starting tag of the system prompt.

    Returns:
    Tuple[str, str]: The extracted system prompt and the remaining string.
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
    Processes the remaining string by removing the initial system prompt tag.

    Parameters:
    remaining_string (str): The remaining string after extracting the system prompt.
    template (Dict[str, str]): The template containing the tags.

    Returns:
    str: The processed remaining string.
    """
    return remaining_string.replace(template["Begin_Sys"], "", 1).strip()
