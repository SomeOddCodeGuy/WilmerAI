# /Middleware/utilities/prompt_template_utils.py

import re
from copy import deepcopy
from typing import List, Dict

from Middleware.utilities.config_utils import load_template_from_json
from Middleware.utilities.prompt_extraction_utils import (
    extract_last_turns_by_estimated_token_limit,
    extract_last_turns_with_min_messages_and_token_limit,
    separate_messages,
    template,
)

TAG_PATTERN = re.compile('|'.join(map(re.escape, template.values())))


def strip_tags(input_string: str) -> str:
    """
    Removes template tags from the input string.

    This function uses a precompiled regular expression to find and remove
    template tags defined in the `template` dictionary.

    Args:
        input_string (str): The string from which to strip the tags.

    Returns:
        str: The input string with all template tags removed.
    """
    return TAG_PATTERN.sub('', input_string)


def format_system_prompts(messages: List[Dict[str, str]], llm_handler, chat_prompt_template_name: str) -> dict:
    """
    Formats system and user prompts for different LLM types.

    This function separates system and other messages, then formats them using
    templates defined by the `chat_prompt_template_name` and the `llm_handler`.
    It accounts for whether the LLM takes a message collection or a single
    string for its prompts.

    Args:
        messages (List[Dict[str, str]]): The conversation history, a list of
            dictionaries with 'role' and 'content' keys.
        llm_handler: An object containing information about the LLM API,
            including whether it takes a message collection and its template
            file name.
        chat_prompt_template_name (str): The name of the chat prompt
            template file.

    Returns:
        dict: A dictionary containing formatted system and user prompts
            for both chat-based and templated LLM APIs.
    """
    system_prompt, other_messages = separate_messages(messages, llm_handler.takes_message_collection)
    chat_user_prompt = format_messages_with_template(other_messages, chat_prompt_template_name,
                                                     llm_handler.takes_message_collection)
    templates_user_prompt = format_messages_with_template(other_messages, llm_handler.prompt_template_file_name
                                                          , llm_handler.takes_message_collection)

    chat_user_prompt_content = [message["content"] for message in chat_user_prompt if
                                message["role"] != "system"]
    template_user_prompt_content = [message["content"] for message in templates_user_prompt if
                                    message["role"] != "system"]

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
    Formats a list of messages using a specified template and returns them
    as a single concatenated string.

    Args:
        messages (List[Dict[str, str]]): A list of messages with 'role' and
            'content' keys.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: A single string containing all formatted messages concatenated.
    """
    formatted_messages = format_messages_with_template(messages, template_file_name, isChatCompletion)
    formatted_strings = [message["content"] for message in formatted_messages]
    return ''.join(formatted_strings)


def format_messages_with_template(messages: List[Dict[str, str]], template_file_name: str
                                  , isChatCompletion: bool) -> List[Dict[str, str]]:
    """
    Formats a list of messages using a specified template.

    Args:
        messages (List[Dict[str, str]]): A list of messages with 'role' and
            'content' keys.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        List[Dict[str, str]]: A list of formatted messages.
    """
    prompt_template = load_template_from_json(template_file_name)
    message_copy = deepcopy(messages)
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
    Formats a single user turn using a specified template.

    Args:
        user_turn (str): The user's message to be formatted.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: The formatted user turn.
    """
    if isChatCompletion:
        return strip_tags(user_turn)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateUserPrefix']}{user_turn}{prompt_template['promptTemplateUserSuffix']}"
    return strip_tags(formatted_turn)


def format_assistant_turn_with_template(assistant_turn: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Formats a single assistant turn using a specified template, without
    an ending tag, for the purpose of forcing a completion.

    Args:
        assistant_turn (str): The assistant's message to be formatted.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: The formatted user turn.
    """
    if isChatCompletion:
        return strip_tags(assistant_turn)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateAssistantPrefix']}{assistant_turn}"
    return strip_tags(formatted_turn)


def format_system_prompt_with_template(system_prompt: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Formats a system prompt using a specified template.

    Args:
        system_prompt (str): The system message to be formatted.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: The formatted system prompt.
    """
    if isChatCompletion:
        return strip_tags(system_prompt)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateSystemPrefix']}{system_prompt}{prompt_template['promptTemplateSystemSuffix']}"
    return strip_tags(formatted_turn)


def add_assistant_end_token_to_user_turn(user_turn: str, template_file_name: str, isChatCompletion: bool) -> str:
    """
    Appends the assistant's end token to a user turn using a specified template.

    Args:
        user_turn (str): The user's message to which the end token will
            be appended.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: The user turn with the assistant's end token appended.
    """
    if isChatCompletion:
        return strip_tags(user_turn)

    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{user_turn}{prompt_template['promptTemplateAssistantPrefix']}{prompt_template['promptTemplateEndToken']}"
    return strip_tags(formatted_turn)


def format_templated_prompt(prompt: str, llm_handler, prompt_template_file_name) -> str:
    """
    Formats a given text using a specified LLM handler and prompt template.

    This function calls `format_user_turn_with_template` to apply the
    appropriate template.

    Args:
        prompt (str): The text to be formatted.
        llm_handler: An object containing information about the LLM API,
            including whether it takes a message collection.
        prompt_template_file_name (str): The name of the template config file
            to use for formatting.

    Returns:
        str: The formatted prompt.
    """
    return format_user_turn_with_template(user_turn=prompt, template_file_name=prompt_template_file_name,
                                          isChatCompletion=llm_handler.takes_message_collection)


def format_templated_system_prompt(prompt: str, llm_handler, prompt_template_file_name) -> str:
    """
    Formats a system prompt using a specified LLM handler and prompt template.

    If the LLM handler supports chat completions, the prompt is returned
    as-is. Otherwise, `format_system_prompt_with_template` is called.

    Args:
        prompt (str): The system message to be formatted.
        llm_handler: An object containing information about the LLM API,
            including whether it takes a message collection.
        prompt_template_file_name (str): The name of the template config file
            to use for formatting.

    Returns:
        str: The formatted system prompt.
    """
    if llm_handler.takes_message_collection:
        return prompt

    return format_system_prompt_with_template(system_prompt=prompt, template_file_name=prompt_template_file_name,
                                              isChatCompletion=llm_handler.takes_message_collection)


def get_formatted_last_n_turns_as_string(messages: List[Dict[str, str]], n: int, template_file_name: str,
                                         isChatCompletion: bool) -> str:
    """
    Retrieves and formats the last 'n' user turns as a single concatenated
    string.

    Args:
        messages (List[Dict[str, str]]): A list of messages with 'role' and
            'content' keys.
        n (int): The number of turns to retrieve and format.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: A single string with the last 'n' user turns concatenated
            and formatted.
    """

    filtered_messages = [message for message in messages if message["role"] != "system"]
    trimmed_messages = filtered_messages[-n:]
    return_message = format_messages_with_template(trimmed_messages, template_file_name, isChatCompletion)
    return ''.join([message["content"] for message in return_message])


def get_formatted_last_turns_by_estimated_token_limit_as_string(messages: List[Dict[str, str]], token_limit: int,
                                                                 template_file_name: str,
                                                                 isChatCompletion: bool) -> str:
    """
    Retrieves and formats recent messages that fit within an estimated token
    budget as a single concatenated string.

    This function drops all ``system`` messages, selects recent messages via
    ``extract_last_turns_by_estimated_token_limit`` (always at least one), and
    formats the selection using the LLM's chat template.

    Args:
        messages (List[Dict[str, str]]): A list of messages with 'role' and
            'content' keys.
        token_limit (int): The maximum estimated token budget.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.

    Returns:
        str: A single string with the selected messages concatenated and
            formatted.
    """
    selected = extract_last_turns_by_estimated_token_limit(messages, token_limit, include_sysmes=False)
    if not selected:
        return ""
    return_message = format_messages_with_template(selected, template_file_name, isChatCompletion)
    return ''.join([message["content"] for message in return_message])


def get_formatted_last_turns_with_min_messages_and_token_limit_as_string(messages: List[Dict[str, str]],
                                                                          min_messages: int, token_limit: int,
                                                                          template_file_name: str,
                                                                          isChatCompletion: bool,
                                                                          budget_overrides_min: bool = False) -> str:
    """
    Retrieves and formats recent messages with a minimum count floor and token
    budget ceiling as a single concatenated string.

    This function drops all ``system`` messages, selects recent messages via
    ``extract_last_turns_with_min_messages_and_token_limit`` (at least
    ``min_messages``, expanding up to ``token_limit``), and formats the
    selection using the LLM's chat template.

    Args:
        messages (List[Dict[str, str]]): A list of messages with 'role' and
            'content' keys.
        min_messages (int): The minimum number of messages to always include.
        token_limit (int): The maximum estimated token budget for expansion
            beyond the minimum message count.
        template_file_name (str): The name of the template config file to use
            for formatting.
        isChatCompletion (bool): A flag indicating if the LLM supports
            chat completions.
        budget_overrides_min (bool, optional): When ``True``, the ``min_messages``
            floor yields to ``token_limit`` (whole messages dropped, never content,
            keeping at least the most-recent message) so a floored variable cannot
            overflow the endpoint window. Defaults to ``False`` (hard floor).

    Returns:
        str: A single string with the selected messages concatenated and
            formatted.
    """
    selected = extract_last_turns_with_min_messages_and_token_limit(
        messages, min_messages, token_limit, include_sysmes=False,
        budget_overrides_min=budget_overrides_min)
    if not selected:
        return ""
    return_message = format_messages_with_template(selected, template_file_name, isChatCompletion)
    return ''.join([message["content"] for message in return_message])
