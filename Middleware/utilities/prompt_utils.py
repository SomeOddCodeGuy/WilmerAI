import hashlib
import logging
import re
from typing import List, Dict, Tuple, Optional

from Middleware.utilities.prompt_extraction_utils import template
from Middleware.utilities.text_utils import chunk_messages_by_token_size, messages_to_text_block

# Centralized tag replacement logic
TAG_REPLACEMENTS = {re.escape(k): ' ' for k in template.values()}
TAG_PATTERN = re.compile('|'.join(TAG_REPLACEMENTS.keys()))

logger = logging.getLogger(__name__)


def combine_initial_system_prompts(messages: List[Dict[str, str]], prefix: str, suffix: str) -> str:
    """
    Combine the initial system messages into a single system prompt string.

    Parameters:
    messages (List[Dict[str, str]]): The list of message dictionaries.
    prefix (str): The prefix to be added to the combined system messages.
    suffix (str): The suffix to be added to the combined system messages.

    Returns:
    str: The combined system prompt string.
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


def strip_tags(input_string: str) -> str:
    """
    Remove template tags from the input string.

    This function uses a precompiled regular expression to find and replace
    template tags with spaces. The tags are defined in the `template` dictionary
    from `prompt_extraction_utils`.

    Parameters:
    input_string (str): The string from which to strip the tags.

    Returns:
    str: The input string with all template tags removed.
    """
    return TAG_PATTERN.sub(lambda match: TAG_REPLACEMENTS[match.group(0)], input_string)


def chunk_messages_with_hashes(messages: List[Dict[str, str]], chunk_size: int = 500,
                               use_first_message_hash: bool = False, max_messages_before_chunk: int = 0) -> List[
    Tuple[str, str]]:
    """
    Chunk messages into blocks of a maximum token size and hash either the last or first message.

    This function chunks the messages into blocks that do not exceed the specified token size.
    Each chunk is then converted into a single text block, and either the first or last message
    in the chunk is hashed for easy identification and tracking, based on the `use_first_message_hash` flag.

    Parameters:
    messages (List[Dict[str, str]]): A list of message dictionaries.
    chunk_size (int): The maximum number of tokens allowed in a chunk.
    use_first_message_hash (bool): If True, hash the first message in the chunk.
                                   If False, hash the last message (default behavior).

    Returns:
    List[Tuple[str, str]]: A list of tuples, each containing a text block and the hash of the first/last message.
    """
    logger.debug("In chunk messages with hash")
    logger.debug("max_messages_before_chunk: %s", str(max_messages_before_chunk))
    chunked_messages = chunk_messages_by_token_size(messages, chunk_size, max_messages_before_chunk)

    # Adjust whether we hash the first or last message based on the boolean flag
    return [(messages_to_text_block(chunk), hash_single_message(chunk[0] if use_first_message_hash else chunk[-1]))
            for chunk in chunked_messages if chunk]


def extract_text_blocks_from_hashed_chunks(chunked_texts_and_hashes: List[Tuple[str, str]]) -> List[str]:
    """
    Extract text blocks from a list of tuples containing text blocks and their corresponding hashes.

    Parameters:
    chunked_texts_and_hashes (List[Tuple[str, str]]): A list of tuples, each containing a text block and a hash.

    Returns:
    List[str]: A list of text blocks extracted from the tuples.
    """
    text_blocks = []
    for text_block, _ in chunked_texts_and_hashes:
        text_blocks.append(text_block)
    return text_blocks


def hash_single_message(message: Dict[str, str]) -> str:
    """
    Generate a SHA-256 hash for a single message.

    Parameters:
    message (Dict[str, str]): A dictionary containing the message.

    Returns:
    str: The SHA-256 hash of the message content.
    """
    hash = _hash_message(message['content'])
    logger.debug("Hashing message: %s", message['content'])
    logger.debug("Hash is: %s", str(hash))
    logger.debug("***************************************")
    return hash


def find_last_matching_hash_message(messagesOriginal: List[Dict[str, str]],
                                    hashed_chunks_original: List[Tuple[str, str]],
                                    skip_system: bool = False, turns_to_skip_looking_back=4) -> int:
    """
    Find the number of messages since the last matching hash, starting from the third-to-last message.

    Parameters:
    messagesOriginal (List[Dict[str, str]]): A list of message dictionaries.
    hashed_chunks_original (List[Tuple[str, str]]): A list of tuples, each containing a text block and a hash.
    skip_system (bool): If True, skip system messages in the search.

    Returns:
    int: The number of messages since the last matching hash, or the length of filtered_messages if no match is found.
    """
    logger.debug("Searching for hashes")

    # Conditionally filter out system messages if skip_system is True
    filtered_messages = [message for message in messagesOriginal if
                         message["role"] != "system"] if skip_system else messagesOriginal

    current_message_hashes = [hash_single_message(message) for message in filtered_messages]

    start_index = len(current_message_hashes) - turns_to_skip_looking_back

    # Iterate from the third-to-last message backwards
    for i in range(start_index, -1, -1):
        message_hash = current_message_hashes[i]
        logger.debug(f"Searching for Hash {i}: {message_hash}")

        # Compare hashes with the existing memory hashes
        if message_hash in (hash_tuple[1] for hash_tuple in hashed_chunks_original):
            return len(current_message_hashes) - i  # Return the number of messages since the last memory

    return len(current_message_hashes)  # If no match found, return the total number of messages


def find_how_many_new_memories_since_last_summary(hashed_summary_chunk: Optional[List[Tuple[str, str]]],
                                                  hashed_memory_chunks: List[Tuple[str, str]]) -> int:
    """
    Find the index of the last hashed summary chunk that matches any hash in the hashed memory chunks.

    Parameters:
    hashed_summary_chunk (Optional[List[Tuple[str, str]]]): A list of tuples representing the hashed summary chunk, or None.
    hashed_memory_chunks (List[Tuple[str, str]]): A list of tuples representing the hashed memory chunks.

    Returns:
    int: The index of the last matching memory hash, or -1 if no match is found.
    """
    if not hashed_memory_chunks:
        return -1

    if not hashed_summary_chunk:
        return len(hashed_memory_chunks)

    summary_hash = hashed_summary_chunk[-1][1]

    memory_hashes = [hash_tuple[1] for hash_tuple in hashed_memory_chunks]

    return memory_hashes[::-1].index(summary_hash) if summary_hash in memory_hashes else -1


def get_messages_within_index(messages: List[Dict[str, str]], index_count: int) -> List[Dict[str, str]]:
    """
    Retrieve a subset of messages from the end of the list up to a specified index count,
    excluding the very last message.

    Parameters:
    messages (List[Dict[str, str]]): The full list of message dictionaries.
    index_count (int): The number of messages to retrieve from the end of the list.

    Returns:
    List[Dict[str, str]]: A list of messages starting from the specified index count from the end,
    excluding the very last message.
    """
    if index_count < 1:
        return []
    subset = messages[-(index_count + 1):-1] if index_count + 1 <= len(messages) else messages[:-1]
    return subset


# Helper functions to be used internally
def _hash_message(content: str) -> str:
    """
    Generate a SHA-256 hash for a message content.

    Parameters:
    content (str): The content of the message.

    Returns:
    str: The SHA-256 hash of the message content.
    """
    encoded_content = content.encode('utf-8')
    hash_object = hashlib.sha256(encoded_content)
    return hash_object.hexdigest()
