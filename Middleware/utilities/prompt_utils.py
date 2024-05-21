import hashlib
import re
from typing import List, Tuple, Optional

from Middleware.utilities.config_utils import get_stop_strings
from Middleware.utilities.prompt_extraction_utils import template
from Middleware.utilities.text_utils import chunk_pairs_by_token_size, pairs_to_text_block

# Centralized tag replacement logic
TAG_REPLACEMENTS = {re.escape(k): ' ' for k in template.values()}
TAG_PATTERN = re.compile('|'.join(TAG_REPLACEMENTS.keys()))


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


def truncate_at_stop_string(input_string: str) -> str:
    """
    Truncate the input string at the first occurrence of a stop string.

    Stop strings are configured in the user's settings and are used to
    delimit the end of a message from an LLM when necessary.

    Parameters:
    input_string (str): The string to be truncated.

    Returns:
    str: The truncated string up to the first stop string encountered.
    """
    stop_strings = get_stop_strings()
    stop_pattern = re.compile('|'.join(map(re.escape, stop_strings)))
    match = stop_pattern.search(input_string)
    return input_string[:match.start() if match else len(input_string)]


def check_stream_chunk_for_stop_string(text: str) -> Optional[str]:
    """
    Check if a stream chunk contains any stop strings and return the text up to it.

    This function searches for any configured stop strings within the text chunk.
    If a stop string is found, the function returns the text up to that point.

    Parameters:
    text (str): The text chunk to be checked.

    Returns:
    Optional[str]: The text up to the first stop string, or None if no stop string is found.
    """
    stop_strings = get_stop_strings()
    for stop_string in stop_strings:
        index = text.find(stop_string)
        if index != -1:
            return text[:index]  # Return the text up to the stop string
    return None


def chunk_turns_with_hashes(pairs: List[Tuple[str, str]], chunk_size: int = 500) -> List[Tuple[str, str]]:
    """
    Chunk pairs of user/assistant turns into blocks of a maximum token size and hash the last pair.

    This function chunks the pairs into blocks that do not exceed the specified token size.
    Each chunk is then converted into a single text block, and the last pair in the chunk is hashed
    for easy identification and tracking.

    Parameters:
    pairs (List[Tuple[str, str]]): A list of tuples, each containing a user and assistant turn.
    chunk_size (int): The maximum number of tokens allowed in a chunk.

    Returns:
    List[Tuple[str, str]]: A list of tuples, each containing a text block and the hash of the last pair.
    """
    chunked_pairs = chunk_pairs_by_token_size(pairs, chunk_size)
    return [(pairs_to_text_block(chunk), hash_single_pair(chunk[-1])) for chunk in chunked_pairs if chunk]


def extract_text_blocks_from_hashed_chunks(chunked_texts_and_hashes: List[Tuple[str, str]]) -> List[str]:
    """
    Extract text blocks from a list of tuples containing text blocks and their corresponding hashes.

    Parameters:
    chunked_texts_and_hashes (List[Tuple[str, str]]): A list of tuples, each containing a text block and a hash.

    Returns:
    List[str]: A list of text blocks extracted from the tuples.
    """
    # Initialize an empty list to hold just the text blocks
    text_blocks = []

    # Iterate over the list of tuples
    for text_block, _ in chunked_texts_and_hashes:
        # Append only the text block to the list
        text_blocks.append(text_block)

    return text_blocks


def hash_single_pair(pair: Tuple[str, str]) -> str:
    """
    Generate a SHA-256 hash for a single pair of user/assistant turns.

    Parameters:
    pair (Tuple[str, str]): A tuple containing the user and assistant turns.

    Returns:
    str: The SHA-256 hash of the concatenated user and assistant turns.
    """
    user_text, assistant_text = pair
    return _hash_pair(user_text, assistant_text)


def find_last_matching_hash_pair(pairs: List[Tuple[str, str]], hashed_chunks: List[Tuple[str, str]]) -> int:
    """
    Find the index of the last pair in the list of pairs that matches any hash in the hashed chunks.

    Parameters:
    pairs (List[Tuple[str, str]]): A list of tuples, each containing a user and assistant turn.
    hashed_chunks (List[Tuple[str, str]]): A list of tuples, each containing a text block and a hash.

    Returns:
    int: The index of the last matching pair, or -1 if no match is found.
    """
    current_pair_hashes = [hash_single_pair(pair) for pair in pairs]
    for i, pair_hash in enumerate(reversed(current_pair_hashes)):
        if pair_hash in (hash_tuple[1] for hash_tuple in hashed_chunks):
            return len(current_pair_hashes) - i - 1
    return -1


def find_last_matching_memory_hash(hashed_summary_chunk: Optional[List[Tuple[str, str]]],
                                   hashed_memory_chunks: List[Tuple[str, str]]) -> int:
    """
    Find the index of the last hashed summary chunk that matches any hash in the hashed memory chunks.

    Parameters:
    hashed_summary_chunk (Optional[List[Tuple[str, str]]]]): A list of tuples representing the hashed summary chunk, or None.
    hashed_memory_chunks (List[Tuple[str, str]]): A list of tuples representing the hashed memory chunks.

    Returns:
    int: The index of the last matching memory hash, or -1 if no match is found.
    """
    if not hashed_summary_chunk or not hashed_memory_chunks:
        return -1
    summary_hash = hashed_summary_chunk[0][1]
    memory_hashes = [hash_tuple[1] for hash_tuple in hashed_memory_chunks]
    return memory_hashes[::-1].index(summary_hash)


def get_pairs_within_index(pairs: List[Tuple[str, str]], index_count: int) -> List[Tuple[str, str]]:
    """
    Retrieve a subset of pairs from the end of the list up to a specified index count.

    Parameters:
    pairs (List[Tuple[str, str]]): The full list of user/assistant turn pairs.
    index_count (int): The number of pairs to retrieve from the end of the list.

    Returns:
    List[Tuple[str, str]]: A list of pairs starting from the specified index count from the end.
    """
    return pairs[-index_count:] if index_count < len(pairs) else pairs


# Helper functions to be used internally
def _hash_pair(user_text: str, assistant_text: str) -> str:
    """
    Generate a SHA-256 hash for a pair of user/assistant turns.

    Parameters:
    user_text (str): The text from the user.
    assistant_text (str): The text from the assistant.

    Returns:
    str: The SHA-256 hash of the concatenated user and assistant turns, separated by a pipe character.
    """
    text_to_hash = f"{user_text}|{assistant_text}"
    encoded_text = text_to_hash.encode('utf-8')
    hash_object = hashlib.sha256(encoded_text)
    return hash_object.hexdigest()
