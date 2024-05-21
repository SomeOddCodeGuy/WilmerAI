from typing import List, Tuple

from Middleware.utilities.config_utils import load_template_from_json
from Middleware.utilities.prompt_extraction_utils import extract_pairs_and_system_prompt_from_wilmer_templated_string
from Middleware.utilities.prompt_utils import strip_tags
from Middleware.utilities.text_utils import reduce_pairs_to_fit_token_limit


def format_system_prompts(system_prompt: str, pairs: List[Tuple[str, str]], llm_handler,
                          chat_prompt_template_name: str) -> dict:
    """
    Formats system prompts and user prompts using the provided LLM handler and chat prompt template.

    Parameters:
    - system_prompt (str): The system prompt extracted from the incoming user's message.
    - pairs (List[Tuple[str, str]]): A list of user-assistant message pairs.
    - llm_handler: An object containing information and methods for interacting with an LLM.
    - chat_prompt_template_name (str): The name of the chat prompt template file.

    Returns:
    - dict: A dictionary containing formatted system and user prompts.
    """
    return {
        "chat_system_prompt": system_prompt,
        "templated_system_prompt": format_templated_prompt(system_prompt,
                                                           llm_handler,
                                                           llm_handler.prompt_template_file_name),
        "templated_user_prompt_without_system": format_pairs_with_template('', pairs,
                                                                           llm_handler.prompt_template_file_name),
        "chat_user_prompt_without_system": format_pairs_with_template('', pairs, chat_prompt_template_name)
    }


def format_pairs_with_template(system_prompt: str, pairs: List[Tuple[str, str]], template_file_name: str) -> str:
    """
    Applies a template to a list of message pairs and a system prompt.

    Parameters:
    - system_prompt (str): The system prompt to be formatted.
    - pairs (List[Tuple[str, str]]): A list of user-assistant message pairs.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: A formatted string containing the system prompt and message pairs.
    """
    prompt_template = load_template_from_json(template_file_name)
    formatted_system_prompt = f"{prompt_template['promptTemplateSystemPrefix']}{system_prompt}{prompt_template['promptTemplateSystemSuffix']}"

    formatted_pairs = []
    for user, assistant in pairs:
        user_formatted = f"{prompt_template['promptTemplateUserPrefix']}{user}{prompt_template['promptTemplateUserSuffix']}" if user else ''
        assistant_formatted = f"{prompt_template['promptTemplateAssistantPrefix']}{assistant}"
        if pairs.index((user, assistant)) < len(pairs) - 1:
            assistant_formatted += prompt_template['promptTemplateAssistantSuffix']
        formatted_pairs.append(user_formatted + assistant_formatted)

    formatted_chat = formatted_system_prompt + ''.join(formatted_pairs)
    formatted_chat = strip_tags(formatted_chat)
    return formatted_chat


def format_user_turn_with_template(user_turn: str, template_file_name: str) -> str:
    """
    Formats a single user turn using the specified template.

    Parameters:
    - user_turn (str): The user's message to be formatted.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted user turn.
    """
    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{prompt_template['promptTemplateUserPrefix']}{user_turn}{prompt_template['promptTemplateUserSuffix']}"
    formatted_turn = strip_tags(formatted_turn)
    return formatted_turn


def add_assistant_end_token_to_user_turn(user_turn: str, template_file_name: str) -> str:
    """
    Appends the assistant's end token to a user turn using the specified template.

    Parameters:
    - user_turn (str): The user's message to which the end token will be appended.
    - template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The user turn with the assistant's end token appended.
    """
    prompt_template = load_template_from_json(template_file_name)
    formatted_turn = f"{user_turn}{prompt_template['promptTemplateAssistantPrefix']}{prompt_template['promptTemplateEndToken']}"
    formatted_turn = strip_tags(formatted_turn)
    return formatted_turn


def generate_templated_string(prompt, template_file_name, truncation_length=0, max_new_tokens=0):
    """
    Generates a templated string from the given prompt, applying truncation if necessary.

    Parameters:
    - prompt (str): The original prompt message.
    - template_file_name (str): The name of the template file to use for formatting.
    - truncation_length (int, optional): The maximum length of the prompt after truncation. Defaults to 0 (no truncation).
    - max_new_tokens (int, optional): The maximum number of new tokens to be generated. Defaults to 0 (no limit).

    Returns:
    - str: The generated templated string.
    """
    system_prompt, prompt_pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(prompt)

    if truncation_length > 0 and 0 < max_new_tokens < truncation_length:
        true_truncate_length = (truncation_length - max_new_tokens) * 0.8
        prompt_pairs = reduce_pairs_to_fit_token_limit(system_prompt, prompt_pairs, true_truncate_length)

    return format_pairs_with_template(system_prompt=system_prompt, pairs=prompt_pairs,
                                      template_file_name=template_file_name)


def format_templated_prompt(text: str, llm_handler, prompt_template_file_name) -> str:
    """
    Formats a given text using the specified LLM handler and prompt template.

    Parameters:
    - text (str): The text to be formatted.
    - llm_handler: An object containing information and methods for interacting with an LLM.
    - prompt_template_file_name (str): The name of the template file to use for formatting.

    Returns:
    - str: The formatted prompt.
    """
    return generate_templated_string(prompt=text, template_file_name=prompt_template_file_name,
                                     truncation_length=llm_handler.truncate_length,
                                     max_new_tokens=llm_handler.max_new_tokens)
