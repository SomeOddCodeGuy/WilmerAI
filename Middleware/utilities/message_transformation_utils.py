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

def _extract_final_query(content: str) -> tuple[str | None, list | None]:
    """
    Extracts final query and conversation history if content matches 'History:...Query:...' format.
    
    Returns:
        A tuple containing (final_query, history_messages) where:
        - final_query is the extracted query or None if not found
        - history_messages is a list of message dictionaries or None if not found
    """
    history_marker = "History:"
    query_marker = "Query:"
    
    # Check for the format markers
    last_query_index = content.rfind(query_marker)
    if last_query_index == -1:
        return None, None
        
    content_before_last_query = content[:last_query_index]
    history_marker_index = content_before_last_query.find(history_marker)
    if history_marker_index == -1:
        return None, None
    
    # Extract the final query
    start_extraction_index = last_query_index + len(query_marker)
    final_query = content[start_extraction_index:].strip()
    
    # Extract the history section
    history_content = content_before_last_query[history_marker_index + len(history_marker):].strip()
    
    # Parse the history into messages
    history_messages = []
    
    # Split the history by message markers
    user_markers = ["USER:", "USER: \"\"\""]
    assistant_markers = ["ASSISTANT:", "ASSISTANT: \"\"\""]
    
    # Find all user and assistant segments
    current_index = 0
    while current_index < len(history_content):
        # Find the next user marker
        user_start = -1
        user_marker_used = None
        for marker in user_markers:
            pos = history_content.find(marker, current_index)
            if pos != -1 and (user_start == -1 or pos < user_start):
                user_start = pos
                user_marker_used = marker
        
        if user_start == -1:
            break  # No more user messages
            
        current_index = user_start + len(user_marker_used)
        
        # Find the next assistant marker
        assistant_start = -1
        for marker in assistant_markers:
            pos = history_content.find(marker, current_index)
            if pos != -1 and (assistant_start == -1 or pos < assistant_start):
                assistant_start = pos
                
        # Find the next user marker to determine the end of this user's message
        next_user_start = -1
        for marker in user_markers:
            pos = history_content.find(marker, current_index)
            if pos != -1 and (next_user_start == -1 or pos < next_user_start):
                next_user_start = pos
        
        # Extract user message content
        user_end = assistant_start if assistant_start != -1 else next_user_start
        if user_end == -1:
            user_end = len(history_content)
            
        user_content = history_content[current_index:user_end].strip()
        # Remove triple quotes if present
        if user_content.startswith('"""') and user_content.endswith('"""'):
            user_content = user_content[3:-3]
        history_messages.append({"role": "user", "content": user_content})
        
        if assistant_start == -1:
            break  # No assistant response after this user message
            
        current_index = assistant_start + len(assistant_markers[0])  # Use the shorter marker for extraction
        
        # Find the end of assistant message (next user message or end of history)
        assistant_end = next_user_start if next_user_start != -1 else len(history_content)
        
        assistant_content = history_content[current_index:assistant_end].strip()
        # Remove triple quotes if present
        if assistant_content.startswith('"""') and assistant_content.endswith('"""'):
            assistant_content = assistant_content[3:-3]
        history_messages.append({"role": "assistant", "content": assistant_content})
        
        current_index = assistant_end
    
    if final_query and history_messages:
        return final_query, history_messages
    return None, None

def _apply_openwebui_workaround(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Applies workaround for OpenWebUI sending history embedded in the last message.
    
    If the last user message contains an embedded conversation history in the format:
    "Query: History:\\n USER: ... ASSISTANT: ... Query: final_query"
    
    This function will:
    1. Extract the conversation history and final query
    2. Preserve all non-last messages from the original list
    3. Insert the extracted history messages
    4. Append the final extracted query as a new user message at the end
    """
    if not messages:
        return messages

    result_messages = []
    
    # Copy all messages except the last one
    for i in range(len(messages) - 1):
        result_messages.append(deepcopy(messages[i]))
    
    # Process the last message
    last_message = messages[-1]
    
    if last_message.get("role") == "user" and isinstance(last_message.get("content"), str):
        extracted_query, history_messages = _extract_final_query(last_message["content"])
        if extracted_query and history_messages:
            logger.debug(f"_apply_openwebui_workaround: SUCCESS - Extracted query='{extracted_query}', history_len={len(history_messages)}")
            # Add all extracted history messages
            result_messages.extend(history_messages)
            # Add the final query as the last user message
            result_messages.append({"role": "user", "content": extracted_query})
            return result_messages
        else:
            logger.debug(f"_apply_openwebui_workaround: FAILED extraction. Query='{extracted_query}', History='{history_messages is not None}'")
    else:
        logger.debug(f"_apply_openwebui_workaround: SKIPPED - Last message not user/string. Role='{last_message.get('role')}'")

    # If no extraction happened or extraction failed, just add the last message as is
    logger.debug("_apply_openwebui_workaround: Returning UNMODIFIED (or failed extraction) list.")
    result_messages.append(deepcopy(last_message))
    return result_messages

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

    # Corrected Order:
    processed_messages = _process_images(processed_messages)
    processed_messages = _apply_role_prefixes(processed_messages, add_user_assistant)
    processed_messages = _apply_openwebui_workaround(processed_messages) # Run workaround BEFORE placeholder
    processed_messages = _add_placeholder_assistant(processed_messages, add_user_assistant, add_missing_assistant)

    return processed_messages 