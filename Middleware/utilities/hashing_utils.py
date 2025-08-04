# /Middleware/utilities/hashing_utils.py
import hashlib
import logging
from typing import List, Dict, Tuple
from Middleware.utilities.text_utils import chunk_messages_by_token_size, messages_to_text_block

logger = logging.getLogger(__name__)

def chunk_messages_with_hashes(messages: List[Dict[str, str]], chunk_size: int = 500,
                               use_first_message_hash: bool = False, max_messages_before_chunk: int = 0) -> List[
    Tuple[str, str]]:
    """
    Chunk messages and generate a hash for each chunk based on the first or last message.

    This function chunks a list of conversational messages into smaller blocks
    that do not exceed a specified token size. For each chunk, it generates a
    hash from either the first or the last message in that chunk. This is
    useful for memory services that need to track and identify chunks of a
    conversation.

    Args:
        messages (List[Dict[str, str]]): A list of message dictionaries representing a conversation.
        chunk_size (int): The maximum token size for each chunk.
        use_first_message_hash (bool): If True, the hash is generated from the first message
                                       of the chunk. If False, it's from the last message.
        max_messages_before_chunk (int): The maximum number of messages allowed before
                                         the chunking process begins.

    Returns:
        List[Tuple[str, str]]: A list of tuples, where each tuple contains a text block
                               (the chunked messages as a single string) and the
                               corresponding hash.
    """
    logger.debug("In chunk messages with hash")
    logger.debug("max_messages_before_chunk: %s", str(max_messages_before_chunk))
    chunked_messages = chunk_messages_by_token_size(messages, chunk_size, max_messages_before_chunk)

    # Adjust whether we hash the first or last message based on the boolean flag
    return [(messages_to_text_block(chunk), hash_single_message(chunk[0] if use_first_message_hash else chunk[-1]))
            for chunk in chunked_messages if chunk]


def extract_text_blocks_from_hashed_chunks(chunked_texts_and_hashes: List[Tuple[str, str]]) -> List[str]:
    """
    Extracts only the text blocks from a list of hashed message chunks.

    This function iterates through a list of tuples, where each tuple contains
    a text block and its corresponding hash, and returns a new list containing
    only the text blocks.

    Args:
        chunked_texts_and_hashes (List[Tuple[str, str]]): A list of tuples, each containing a
                                                          text block and its SHA-256 hash.

    Returns:
        List[str]: A list of strings, where each string is a text block from the input.
    """
    text_blocks = []
    for text_block, _ in chunked_texts_and_hashes:
        text_blocks.append(text_block)
    return text_blocks


def hash_single_message(message: Dict[str, str]) -> str:
    """
    Generates a SHA-256 hash for the content of a single message.

    This function takes a message dictionary, extracts the 'content' field,
    and returns its SHA-256 hash.

    Args:
        message (Dict[str, str]): A message dictionary containing at least a 'content' key.

    Returns:
        str: The SHA-256 hash of the message content as a hexadecimal string.
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
    Finds the number of messages since the last one that matches a known hash.

    This function is used to determine how many recent messages need to be
    processed for conversation history or memory recall. It compares the hashes
    of recent messages with a set of pre-calculated hashes. The search starts
    from a specified number of messages from the end and moves backward.

    Args:
        messagesOriginal (List[Dict[str, str]]): The full list of message dictionaries in the conversation.
        hashed_chunks_original (List[Tuple[str, str]]): A list of tuples containing previously stored
                                                        text blocks and their corresponding hashes.
        skip_system (bool): If True, 'system' role messages will be ignored during the hash comparison.
        turns_to_skip_looking_back (int): The number of recent messages to skip before starting the hash search.

    Returns:
        int: The number of messages that have occurred since the last matching hash was found.
             If no match is found, it returns the total number of messages searched.
    """
    logger.debug("Searching for hashes")

    # Conditionally filter out system messages if skip_system is True
    filtered_messages = [message for message in messagesOriginal if
                         message["role"] != "system"] if skip_system else messagesOriginal

    filtered_messages = [message for message in filtered_messages if message["role"] != "images"]

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


# Helper functions to be used internally
def _hash_message(content: str) -> str:
    """
    Generates a SHA-256 hash for a given string.

    This is an internal helper function used to generate a unique hash for
    message content.

    Args:
        content (str): The string content to be hashed.

    Returns:
        str: The SHA-256 hash of the input string as a hexadecimal string.
    """
    encoded_content = content.encode('utf-8')
    hash_object = hashlib.sha256(encoded_content)
    return hash_object.hexdigest()