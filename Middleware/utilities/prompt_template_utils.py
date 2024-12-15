from copy import deepcopy
from typing import List, Dict

from Middleware.utilities.config_utils import load_template_from_json
from Middleware.utilities.prompt_extraction_utils import separate_messages
from Middleware.utilities.prompt_utils import strip_tags
from Middleware.utilities.text_utils import rough_estimate_token_length


def format_system_prompts(messages: List[Dict[str, str]], llm_handler, chat_prompt_template_name: str) -> dict:
    """
    Formats system prompts and user prompts using the provided LLM handler and chat prompt template.

    Parameters:
    - messages (List[Dict[str, str]]): A list of messages with roles and content.
    - llm_handler: An object containing information and methods for interacting with an LLM.
    - chat_prompt_template_name (str): The name of the chat prompt template file.

    Returns:
    - dict: A dictionary containing formatted system and user prompts.
    """
    system_prompt, other_messages = separate_messages(messages, llm_handler.takes_message_collection)
    chat_user_prompt = format_messages_with_template(other_messages, chat_prompt_template_name,
                                                     llm_handler.takes_message_collection)
    templates_user_prompt = format_messages_with_template(other_messages, llm_handler.prompt_template_file_name
                                                          , llm_handler.takes_message_collection)

    chat_user_prompt_content = [message["content"] for message in chat_user_prompt if
                                message["role"] not in {"images", "system"}]
    template_user_prompt_content = [message["content"] for message in templates_user_prompt if
                                    message["role"] not in {"images", "system"}]

    return {
        "chat_system_prompt": format_templated_system_prompt(system_prompt, llm_handler, chat_prompt_template_name),
        "templated_system_prompt": format_templated_system_prompt(system_prompt, llm_handler,
                                                                  llm_handler.prompt_template_file_name),
        "templated_user_prompt_without_system": ''.join(template_user_prompt_content),
        "chat_user_prompt_without_system": ''.join(chat_user_prompt_content)
    }


def format_messages_with_template_as_string(messages: List[Dict[str, str]], template_file_name: str
                                            , isChatCompletion: bool) -> str:
    """
    Formats messages using the specified template and returns them as a single concatenated string.

    Parameters:
    - messages (List[Dict[str, str]]): A list of messages with roles and content.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: A single string with all formatted messages concatenated.
    """
    formatted_messages = format_messages_with_template(messages, template_file_name, isChatCompletion)
    formatted_strings = [message["content"] for message in formatted_messages]
    return ''.join(formatted_strings)


def format_messages_with_template(messages: List[Dict[str, str]], template_file_name: str
                                  , isChatCompletion: bool) -> List[Dict[str, str]]:
    """
    Formats messages using the specified template.

    Parameters:
    - messages (List[Dict[str, str]]): A list of messages with roles and content.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - List[Dict[str, str]]: A list of formatted messages.
    """
    prompt_template = load_template_from_json(template_file_name)
    message_copy = deepcopy(messages)
    message_copy = [message for message in message_copy if message["role"] != "images"]
    formatted_messages = []

    for i, message in enumerate(message_copy):
        if not isChatCompletion:
            prefix = prompt_template.get(f"promptTemplate{message['role'].capitalize()}Prefix", '')
            suffix = '' if i == len(message_copy) - 1 and message['role'] == 'assistant' else prompt_template.get(
                f"promptTemplate{message['role'].capitalize()}Suffix", '')
            formatted_message = f"{prefix}{message['content']}{suffix}"
        else:
            formatted_message = message['content']
        message['content'] = strip_tags(formatted_message)
        formatted_messages.append(message)

    return formatted_messages


def format_user_turn_with_template(user_turn: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Formats a single user turn using the specified template.

    Parameters:
    - user_turn (str): The user's message to be formatted.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted user turn.
    """
    if (isChatCompletion):
        return strip_tags(user_turn)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateUserPrefix']}{user_turn}{prompt_template['promptTemplateUserSuffix']}"
    return strip_tags(formatted_turn)


def format_assistant_turn_with_template(assistant_turn: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Formats a single assistant turn using the specified template, but without an ending tag. This is
    for forcing a completion.

    Parameters:
    - assistant_turn (str): The assistant's message to be formatted and completed.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted user turn.
    """
    if (isChatCompletion):
        return strip_tags(assistant_turn)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateAssistantPrefix']}{assistant_turn}"
    return strip_tags(formatted_turn)


def format_system_prompt_with_template(system_prompt: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Formats a system prompt using the specified template.

    Parameters:
    - system_prompt (str): The system message to be formatted.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted system prompt.
    """
    if (isChatCompletion):
        return strip_tags(system_prompt)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateSystemPrefix']}{system_prompt}{prompt_template['promptTemplateSystemSuffix']}"
    return strip_tags(formatted_turn)


def add_assistant_end_token_to_user_turn(user_turn: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Appends the assistant's end token to a user turn using the specified template.

    Parameters:
    - user_turn (str): The user's message to which the end token will be appended.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The user turn with the assistant's end token appended.
    """
    if (isChatCompletion):
        return strip_tags(user_turn)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{user_turn}{prompt_template['promptTemplateAssistantPrefix']}{prompt_template['promptTemplateEndToken']}"
    return strip_tags(formatted_turn)


def format_templated_prompt(prompt: str, llm_handler, prompt_template_file_name) -> str:
    """
    Formats a given text using the specified LLM handler and prompt template.

    Parameters:
    - prompt (str): The text to be formatted.
    - llm_handler: An object containing information and methods for interacting with an LLM.
    - prompt_template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted prompt.
    """
    return format_user_turn_with_template(user_turn=prompt, template_file_name=prompt_template_file_name,
                                          isChatCompletion=llm_handler.takes_message_collection)


def format_templated_system_prompt(prompt: str, llm_handler, prompt_template_file_name) -> str:
    """
    Formats a system prompt using the specified LLM handler and prompt template.

    Parameters:
    - prompt (str): The system message to be formatted.
    - llm_handler: An object containing information and methods for interacting with an LLM.
    - prompt_template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted system prompt.
    """
    if llm_handler.takes_message_collection:
        return prompt

    return format_system_prompt_with_template(system_prompt=prompt, template_file_name=prompt_template_file_name,
                                              isChatCompletion=llm_handler.takes_message_collection)


def reduce_messages_to_fit_token_limit(system_prompt: str, messages: List[Dict[str, str]], max_tokens: int) -> List[
    Dict[str, str]]:
    """
    Reduces messages to fit within a maximum token limit.

    This function processes messages in reverse order, accumulating token
    estimates until the specified maximum token limit is reached. It ensures
    that full messages are included without exceeding the token limit.

    Parameters:
    - system_prompt (str): The system prompt to be prepended to the messages.
    - messages (List[Dict[str, str]]): The list of messages.
    - max_tokens (int): The maximum number of tokens allowed.

    Returns:
    - List[Dict[str, str]]: The list of messages that fit within the token limit.
    """
    current_token_count = rough_estimate_token_length(system_prompt)
    fitting_messages = []

    for message in reversed(messages):
        message_token_count = rough_estimate_token_length(message['content'])

        if current_token_count + message_token_count <= max_tokens:
            fitting_messages.append(message)
            current_token_count += message_token_count
        else:
            break

    return list(reversed(fitting_messages))


def get_formatted_last_n_turns_as_string(messages: List[Dict[str, str]], n: int, template_file_name: str,
                                         isChatCompletion: bool) -> str:
    """
    Retrieves and formats the last n user turns as a single concatenated string.

    Parameters:
    - messages (List[Dict[str, str]]): A list of messages with roles and content.
    - n (int): The number of turns to retrieve and format.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: A single string with the last n user turns concatenated and formatted.
    """

    filtered_messages = [message for message in messages if message["role"] not in {"images", "system"}]
    trimmed_messages = deepcopy(filtered_messages[-n:])
    return_message = format_messages_with_template(trimmed_messages, template_file_name, isChatCompletion)
    return ''.join([message["content"] for message in return_message])
