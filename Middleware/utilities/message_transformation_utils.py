"""
Utility functions for message transformation and standardization across different API endpoints.
This helps centralize logic for message formatting, prefixing, and special handling.
"""

import logging
import re # Import regex module
from copy import deepcopy
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Markers for the history block
HISTORY_START_MARKER = "History:\n"
QUERY_MARKER = "\nQuery: "


def _parse_history_block(history_block: str) -> List[Dict[str, str]]:
    """
    Parses the raw history block string into a list of message dictionaries.
    The input block is expected to be in reverse chronological order.
    """
    messages = []
    # Split by USER: and ASSISTANT:, keeping delimiters
    parts = re.split(r'(USER:|ASSISTANT:)', history_block)
    # Filter out empty strings resulting from split
    parts = [p.strip() for p in parts if p and p.strip()]

    role = None
    content = ""
    for part in parts:
        if part == "USER:":
            if role: # Save previous message
                # Clean up triple quotes and surrounding whitespace/newlines
                cleaned_content = re.sub(r'^"""|"""$', '', content).strip()
                messages.append({"role": role.lower(), "content": cleaned_content})
            role = "user"
            content = ""
        elif part == "ASSISTANT:":
            if role: # Save previous message
                cleaned_content = re.sub(r'^"""|"""$', '', content).strip()
                messages.append({"role": role.lower(), "content": cleaned_content})
            role = "assistant"
            content = ""
        else:
            # Append content, preserving internal structure
            content += part + "\n" # Correctly add newline

    # Add the last message
    if role and content:
        cleaned_content = re.sub(r'^"""|"""$', '', content).strip()
        messages.append({"role": role.lower(), "content": cleaned_content})

    # The parsed messages are naturally in reverse chronological order based on the block
    return messages


def _format_history_for_prompt(history_messages: List[Dict[str, str]]) -> str:
    """
    Formats the parsed history messages into a string suitable for the system prompt,
    maintaining the original order (newest first).
    """
    formatted_lines = []
    # Process directly in the existing order (newest first)
    for message in history_messages:
        role = message.get("role", "unknown").upper()
        content = message.get("content", "")
        # Use triple quotes for content, escaping internal ones if needed
        formatted_lines.append(f'{role}:\n"""{content}"""')

    # Join with newlines and prepend header
    return "" + "\n".join(formatted_lines)


def _find_and_extract_history(content: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts history block and final query from content string."""
    history_start_index = content.find(HISTORY_START_MARKER)
    query_start_index = content.rfind(QUERY_MARKER)

    if history_start_index != -1 and query_start_index != -1 and query_start_index > history_start_index:
        history_block_start = history_start_index + len(HISTORY_START_MARKER)
        history_block = content[history_block_start:query_start_index]
        final_query = content[query_start_index + len(QUERY_MARKER):]
        # Remove the initial 'User: Query: ' part if present
        if final_query.startswith("User: Query: "):
             final_query = final_query[len("User: Query: "):]
        elif content.startswith("User: Query: "): # Handle case where it might only be at the start
             prefix_len = len("User: Query: ")
             history_block_start = content.find(HISTORY_START_MARKER, prefix_len) + len(HISTORY_START_MARKER)
             query_start_index = content.rfind(QUERY_MARKER, prefix_len)
             if history_start_index != -1 and query_start_index != -1 and query_start_index > history_start_index:
                 history_block = content[history_block_start:query_start_index]
                 final_query = content[query_start_index + len(QUERY_MARKER):]


        return history_block.strip(), final_query.strip()
    return None, None


def _apply_openwebui_workaround(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Applies the OpenWebUI workaround:
    Finds a user message with embedded 'History:' and 'Query:', extracts them,
    parses the history, formats it into a system message, and replaces the
    original user message with the history system message and a final query user message.
    """
    processed_messages = []
    history_applied = False

    for i, message in enumerate(messages):
        if not history_applied and message.get("role") == "user":
            content = message.get("content", "")
            history_block, final_query = _find_and_extract_history(content)

            if history_block is not None and final_query is not None:
                logger.debug("Applying OpenWebUI history workaround.")
                history_messages = _parse_history_block(history_block)
                if not history_messages:
                     logger.warning("Could not parse history block, skipping workaround.")
                     processed_messages.append(deepcopy(message)) # Add original if parse fails
                     continue

                formatted_history = _format_history_for_prompt(history_messages)

                # Add the new system message with history
                processed_messages.append({
                    "role": "system",
                    "content": formatted_history
                })
                # Add the new user message with the final query
                processed_messages.append({
                    "role": "user",
                    "content": final_query
                })
                history_applied = True
                # Skip adding the original message as it's been replaced
            else:
                # Not the target message or format doesn't match, add as is
                processed_messages.append(deepcopy(message))
        else:
            # Add other messages (system, assistant, or user messages after the target)
             processed_messages.append(deepcopy(message))


    if not history_applied:
         logger.debug("OpenWebUI history markers not found or format mismatch, returning original messages.")


    return processed_messages

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
    1. Expand messages with images.
    2. Apply role prefixes (User:/Assistant:).
    3. Apply OpenWebUI embedded history workaround.
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

    # Corrected Order: Apply workaround *after* potential prefixing but *before* placeholder
    processed_messages = _process_images(processed_messages)
    processed_messages = _apply_role_prefixes(processed_messages, add_user_assistant) # Prefixes might exist in history block input, handle this? - current parse cleans them
    processed_messages = _apply_openwebui_workaround(processed_messages) # Handles history extraction
    processed_messages = _add_placeholder_assistant(processed_messages, add_user_assistant, add_missing_assistant)

    return processed_messages 