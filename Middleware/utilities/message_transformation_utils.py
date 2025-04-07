"""
Utility functions for message transformation and standardization across different API endpoints.
This helps centralize logic for message formatting, prefixing, and special handling.
"""

import logging
import re # Import regex module
from copy import deepcopy
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Removed complex regex - we will use string searching instead
# FINAL_QUERY_REGEX = re.compile(r"^.*History:.*Query:\s*(.*)$", re.DOTALL | re.MULTILINE)

# --- Private Helper Functions for Individual Transformations ---

def _extract_final_query(content: str) -> str | None:
    """Extracts final query if content matches 'History:...Query:...' format."""
    history_marker = "History:"
    query_marker = "Query:"
    history_turn_markers = ["USER:", "ASSISTANT:", "USER: \"\"\"", "ASSISTANT: \"\"\""]

    last_query_index = content.rfind(query_marker)
    if last_query_index != -1:
        content_before_last_query = content[:last_query_index]
        if history_marker in content_before_last_query:
            start_extraction_index = last_query_index + len(query_marker)
            potential_final_query = content[start_extraction_index:].strip()
            if potential_final_query and not any(marker in potential_final_query for marker in history_turn_markers):
                return potential_final_query
    return None

def _apply_openwebui_workaround(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Applies workaround for OpenWebUI sending history embedded in the last message."""
    if not messages:
        return messages

    messages_copy = deepcopy(messages)
    last_message_index = len(messages_copy) - 1
    last_message = messages_copy[last_message_index]

    if last_message.get("role") == "user" and isinstance(last_message.get("content"), str):
        extracted_query = _extract_final_query(last_message["content"])
        if extracted_query:
            messages_copy[last_message_index]["content"] = extracted_query
            logger.debug(f"Applied OpenWebUI workaround, extracted query: '{extracted_query}'")

    return messages_copy

def _process_images(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expands messages containing images into separate user and image messages."""
    processed_list = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        images_to_add = message.get("images")

        if role == "user" and isinstance(images_to_add, list):
            # Append user message part (without images key)
            user_part = {"role": "user", "content": content}
            processed_list.append(user_part)
            # Append separate image messages
            for img_data in images_to_add:
                processed_list.append({"role": "images", "content": img_data})
        else:
            # Append non-image messages or non-user messages as is
            processed_list.append(deepcopy(message))
    return processed_list

def _apply_role_prefixes(messages: List[Dict[str, Any]], add_user_assistant: bool) -> List[Dict[str, Any]]:
    """Adds 'User: ' and 'Assistant: ' prefixes if add_user_assistant is True."""
    if not add_user_assistant:
        return messages

    prefixed_list = []
    for message in messages:
        message_copy = deepcopy(message)
        role = message_copy.get("role")
        content = message_copy.get("content", "")
        if role == "user":
            message_copy["content"] = f"User: {content}"
        elif role == "assistant":
            message_copy["content"] = f"Assistant: {content}"
        prefixed_list.append(message_copy)
    return prefixed_list

def _add_placeholder_assistant(messages: List[Dict[str, Any]], add_user_assistant: bool, add_missing_assistant: bool) -> List[Dict[str, Any]]:
    """Appends an empty assistant message if the list ends with a user message and flag is set."""
    if not add_missing_assistant:
        return messages

    messages_copy = deepcopy(messages)
    if messages_copy and messages_copy[-1].get("role") != "assistant":
        placeholder_content = "Assistant: " if add_user_assistant else ""
        messages_copy.append({"role": "assistant", "content": placeholder_content})
        logger.debug("Added placeholder assistant turn.")

    return messages_copy

# --- Public Transformation Function ---

def transform_messages(
    messages: List[Dict[str, Any]],
    add_user_assistant: bool = False,
    add_missing_assistant: bool = False
) -> List[Dict[str, Any]]:
    """
    Applies a sequence of standard transformations to a message list:
    1. Apply OpenWebUI embedded history workaround.
    2. Expand messages with images.
    3. Apply role prefixes (User:/Assistant:).
    4. Add a placeholder assistant turn if needed.

    Args:
        messages: The original list of messages to transform.
        add_user_assistant: Whether to add "User: " and "Assistant: " prefixes.
        add_missing_assistant: Whether to add an empty assistant message if needed.

    Returns:
        A new list with all transformations applied.
    """
    if not messages:
        return []

    # Apply transformations sequentially
    # Use deepcopy initially to prevent modifying the original input list
    processed_messages = deepcopy(messages)

    processed_messages = _apply_openwebui_workaround(processed_messages)
    processed_messages = _process_images(processed_messages)
    processed_messages = _apply_role_prefixes(processed_messages, add_user_assistant)
    processed_messages = _add_placeholder_assistant(processed_messages, add_user_assistant, add_missing_assistant)

    return processed_messages 