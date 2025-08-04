# /Middleware/utilities/prompt_manipulation_utils.py

import logging
from typing import List, Dict

from Middleware.utilities.text_utils import rough_estimate_token_length

logger = logging.getLogger(__name__)

def combine_initial_system_prompts(messages: List[Dict[str, str]], prefix: str, suffix: str) -> str:
    """
    Combines the initial system messages from a conversation into a single prompt.

    This function iterates through a list of message dictionaries and concatenates
    all consecutive system messages at the beginning of the list into a single string.
    A prefix and a suffix can be added to the final combined prompt.

    Args:
        messages (List[Dict[str, str]]): The list of message dictionaries representing the conversation history.
        prefix (str): A string to prepend to the combined system prompt.
        suffix (str): A string to append to the combined system prompt.

    Returns:
        str: The single, combined system prompt string.
    """
    system_prompt_parts = []
    for message in messages:
        if message['role'] == 'system' and not system_prompt_parts and not any(
                m['role'] == 'user' for m in messages[:messages.index(message)]):
            system_prompt_parts.append(message['content'])
        elif message['role'] == 'user' or message['role'] == 'assistant':
            break

    combined_system_prompt = ' '.join(system_prompt_parts)
    return f"{prefix}{combined_system_prompt}{suffix}"


def get_messages_within_index(messages: List[Dict[str, str]], index_count: int) -> List[Dict[str, str]]:
    """
    Retrieves a subset of recent messages from a conversation history.

    This function extracts a specified number of messages from the end of the list,
    excluding the very last message. This is useful for creating a context window
    for an LLM that needs to respond to the final message.

    Args:
        messages (List[Dict[str, str]]): The full list of message dictionaries.
        index_count (int): The number of messages to retrieve from the end of the list.

    Returns:
        List[Dict[str, str]]: A list of message dictionaries representing the subset of messages.
    """
    if index_count < 1:
        return []
    subset = messages[-(index_count + 1):-1] if index_count + 1 <= len(messages) else messages[:-1]
    return subset


def reduce_messages_to_fit_token_limit(system_prompt: str, messages: List[Dict[str, str]], max_tokens: int) -> List[
    Dict[str, str]]:
    """
    Reduces a list of conversation messages to fit within a maximum token limit.

    This function calculates a rough token estimate for each message and a system prompt.
    It then iterates backwards through the messages, including as many as possible
    without exceeding the total token limit. The function ensures that whole messages
    are kept or discarded, never truncated.

    Args:
        system_prompt (str): The system prompt string to be included in the token count.
        messages (List[Dict[str, str]]): The list of message dictionaries.
        max_tokens (int): The maximum number of tokens allowed for the combined context.

    Returns:
        List[Dict[str, str]]: The list of messages that fit within the token limit,
            ordered from oldest to newest.
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


def reduce_messages_down_to_wilmer_acceptable_length(system_prompt: str, messages: List[Dict[str, str]],
                                                     truncate_length: int, max_new_tokens: int) -> List[Dict[str, str]]:
    """
    Adjusts the conversation history to an acceptable length for Wilmer's processing.

    This function dynamically calculates a new token limit based on the model's
    maximum output length (max_new_tokens) and a predefined truncation length.
    It then calls `reduce_messages_to_fit_token_limit` with this adjusted
    limit to ensure that the input context is not too large for the model to
    generate a response within its constraints.

    Args:
        system_prompt (str): The system prompt string.
        messages (List[Dict[str, str]]): The list of message dictionaries.
        truncate_length (int): The total token length to aim for.
        max_new_tokens (int): The maximum number of new tokens the model is expected to generate.

    Returns:
        List[Dict[str, str]]: The reduced list of messages that fit within the adjusted token limit.
    """
    if 0 < max_new_tokens < truncate_length:
        true_truncate_length = int((truncate_length - max_new_tokens) * 0.8)
        messages = reduce_messages_to_fit_token_limit(system_prompt, messages, true_truncate_length)
    return messages