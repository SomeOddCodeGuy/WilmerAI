import hashlib
import re
from typing import List, Dict, Tuple, Optional

from Middleware.utilities.prompt_extraction_utils import template
from Middleware.utilities.text_utils import chunk_messages_by_token_size, messages_to_text_block

# Centralized tag replacement logic
TAG_REPLACEMENTS = {re.escape(k): ' ' for k in template.values()}
TAG_PATTERN = re.compile('|'.join(TAG_REPLACEMENTS.keys()))


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


def chunk_messages_with_hashes(messages: List[Dict[str, str]], chunk_size: int = 500) -> List[Tuple[str, str]]:
    """
    Chunk messages into blocks of a maximum token size and hash the last message.

    This function chunks the messages into blocks that do not exceed the specified token size.
    Each chunk is then converted into a single text block, and the last message in the chunk is hashed
    for easy identification and tracking.

    Parameters:
    messages (List[Dict[str, str]]): A list of message dictionaries.
    chunk_size (int): The maximum number of tokens allowed in a chunk.

    Returns:
    List[Tuple[str, str]]: A list of tuples, each containing a text block and the hash of the last message.
    """
    print("In chunk messages with hash")
    chunked_messages = chunk_messages_by_token_size(messages, chunk_size)
    return [(messages_to_text_block(chunk), hash_single_message(chunk[-1])) for chunk in chunked_messages if chunk]


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
    print("Hashing message: " + message['content'])
    print("Hash is: " + str(hash))
    print("***************************************")
    return hash


def find_last_matching_hash_message(messagesOriginal: List[Dict[str, str]],
                                    hashed_chunks_original: List[Tuple[str, str]]) -> int:
    """
    Find the index of the last message in the list of messages that matches any hash in the hashed chunks,
    starting from the third-to-last item and working backwards.

    Parameters:
    messagesOriginal (List[Dict[str, str]]): A list of message dictionaries.
    hashed_chunks_original (List[Tuple[str, str]]): A list of tuples, each containing a text block and a hash.

    Returns:
    int: The number of items it had to go back to find a match, or the start index (18) if it had to go back
    the entire list, or -1 if no match is found.
    """
    print("Searching for hashes")
    current_message_hashes = [hash_single_message(message) for message in messagesOriginal]

    start_index = len(current_message_hashes) - 3  # Start at the third-to-last item

    for i in range(start_index, -1, -1):
        message_hash = current_message_hashes[i]
        print("Searching for Hash " + str(i) + ": " + message_hash)
        if message_hash in (hash_tuple[1] for hash_tuple in hashed_chunks_original):
            return start_index - i

    return start_index


def find_last_matching_memory_hash(hashed_summary_chunk: Optional[List[Tuple[str, str]]],
                                   hashed_memory_chunks: List[Tuple[str, str]]) -> int:
    """
    Find the index of the last hashed summary chunk that matches any hash in the hashed memory chunks.

    Parameters:
    hashed_summary_chunk (Optional[List[Tuple[str, str]]]): A list of tuples representing the hashed summary chunk, or None.
    hashed_memory_chunks (List[Tuple[str, str]]): A list of tuples representing the hashed memory chunks.

    Returns:
    int: The index of the last matching memory hash, or -1 if no match is found.
    """
    if not hashed_summary_chunk or not hashed_memory_chunks:
        return -1
    summary_hash = hashed_summary_chunk[0][1]
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
