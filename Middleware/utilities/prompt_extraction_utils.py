import re
from copy import deepcopy
from typing import Dict, Tuple, List, Optional

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


def extract_last_n_turns(messages: List[Dict[str, str]], n: int) -> List[Dict[str, str]]:
    """
    Extract the last n user and assistant messages, excluding system messages.

    Parameters:
    messages (List[Dict[str, str]]): The list of messages.
    n (int): The number of messages to extract.

    Returns:
    List[Dict[str, str]]: The last n user and assistant messages.
    """
    filtered_messages = [message for message in messages if message["role"] != "system"]
    return filtered_messages[-n:]


def extract_last_n_turns_as_string(messages: List[Dict[str, str]], n: int) -> str:
    """
    Extract the last n user and assistant messages as a single string, excluding system messages.

    Parameters:
    messages (List[Dict[str, str]]): The list of messages.
    n (int): The number of messages to extract.

    Returns:
    str: The last n user and assistant messages as a single string.
    """
    filtered_messages = [message for message in messages if message["role"] != "system"]
    return_messages = deepcopy(filtered_messages[-n:])
    return '\n'.join(message["content"] for message in return_messages)


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
    pattern = f'{re.escape(discussion_identifiers["discussion_id_start"])}\\d+{re.escape(discussion_identifiers["discussion_id_end"])}'
    return re.sub(pattern, '', message)


def separate_messages(messages: List[Dict[str, str]], isVariable=False) -> Tuple[str, List[Dict[str, str]]]:
    """
    Extracts the system prompt and remaining messages from the messages list.

    Parameters:
    messages (List[Dict[str, str]]): A list of messages with roles and content.
    isVariable (bool): A flag indicating if the system prompt is variable. Default is False.

    Returns:
    Tuple[str, List[Dict[str, str]]]: The system prompt and the remaining messages.
    """
    system_prompt_list = []
    conversation = []
    for message in messages:
        role = message.get('role', '').lower()
        if role == 'system':
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
    print("Parse conversation result: ", conversation)
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
