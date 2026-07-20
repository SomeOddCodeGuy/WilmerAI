# /Middleware/utilities/text_utils.py

import logging
import re
from typing import List, Dict

logger = logging.getLogger(__name__)

# Lower-cased key names whose values redact_sensitive_data() masks in log output.
_SENSITIVE_KEYS = frozenset({
    'apikey', 'api_key',
    'password', 'passwd', 'pwd',
    'token', 'access_token', 'refresh_token', 'auth_token', 'bearer_token',
    'secret', 'client_secret', 'api_secret',
    'authorization', 'auth',
    'private_key', 'privatekey',
})


# Originally based on ruby_coder's approach on the OpenAI forums:
# https://community.openai.com/t/what-is-the-openai-algorithm-to-calculate-tokens/58237/4
# Ratios have since been recalibrated.
#
# The word ratio (1.35 tokens/word) is based on the commonly cited ~0.75 words/token
# heuristic for English, with a small upward buffer.
#
# The character ratio (3.5 chars/token) is a compromise between code (modern BPE
# tokenizers with 100k-200k vocab sizes average 2.8-3.5 chars/token on code) and
# English prose (~4.0 chars/token). It errs toward overestimation on prose. It is
# not specifically calibrated for either content type alone.
#
# The safety_margin parameter (default 1.10) provides deliberate additional
# overestimation to prevent context window overflow. The effective combined rate
# after margin is ~1.485 tokens/word.
#
# This estimate is conservative by design: it must never under-count for any
# model (an under-count risks a hard context-overflow rejection), so it is
# calibrated for the worst case (dense/code text on small-vocab tokenizers). On
# efficient large-vocab models it can run ~1.85x high. The algorithm is left as
# the safe worst case on purpose; the per-endpoint wilmerContextEstimationLevel
# (see config_utils.get_estimation_level_multiplier) is the calibration knob that
# reclaims the wasted headroom for endpoints whose model packs tokens efficiently.
def rough_estimate_token_length(text: str, safety_margin: float = 1.10) -> int:
    """Estimates the token length of a prompt, overestimating slightly.

    This function splits the text into words and characters to estimate the
    number of tokens. It is designed to overestimate to ensure that the token
    limit is not exceeded when interfacing with language models.

    Args:
        text (str): The text to estimate the token length for.
        safety_margin (float): Multiplier applied to the raw estimate to provide
            deliberate overestimation. Default is 1.10, meaning 10% above the
            raw heuristic estimate.

    Returns:
        int: The estimated token length.
    """
    words = text.split()
    word_count = len(words)
    char_count = len(text)

    tokens_word_est = word_count * 1.35
    tokens_char_est = char_count / 3.5

    return int(max(tokens_word_est, tokens_char_est) * safety_margin)


def reduce_text_to_token_limit(text: str, num_tokens: int) -> str:
    """Reduces text from the end to fit within a token limit.

    This function iterates over the words in reverse order, accumulating
    token estimates until the specified token limit is reached. It then returns
    the text that fits within the limit, preserving full words.

    Args:
        text (str): The text to be reduced.
        num_tokens (int): The target number of tokens.

    Returns:
        str: The reduced text that fits within the token limit.
    """
    words = text.split()
    cumulative_tokens = 0
    # When the whole text fits within the limit the loop below never breaks, so
    # the start index must default to 0 (keep everything), not len(words).
    start_index = 0

    for i in range(len(words) - 1, -1, -1):
        word = words[i]
        cumulative_tokens += rough_estimate_token_length(word + ' ')
        if cumulative_tokens > num_tokens:
            start_index = i + 1
            break

    return ' '.join(words[start_index:])


def split_into_tokenized_chunks(text: str, chunk_size: int) -> List[str]:
    """Splits text into chunks of a specified token size.

    This function breaks the text into chunks where each chunk is below
    the specified token size. It ensures that chunks do not split sentences or
    other meaningful units of text.

    Args:
        text (str): The text to be split into chunks.
        chunk_size (int): The target size for each chunk, in tokens.

    Returns:
        List[str]: A list of text chunks, each below the specified token size.
    """
    words = text.split()
    chunks = []
    current_chunk = []
    current_chunk_size = 0

    for word in words:
        word_size = rough_estimate_token_length(word)
        if current_chunk_size + word_size > chunk_size:
            chunks.append(' '.join(current_chunk))
            current_chunk = []
            current_chunk_size = 0
        current_chunk.append(word)
        current_chunk_size += word_size

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks


def chunk_messages_by_token_size(messages: List[Dict[str, str]], chunk_size: int) -> \
        List[List[Dict[str, str]]]:
    """Chunks messages based on a specified token size, starting from the end of the list,
    but keeps the order of messages intact within each chunk.

    This function groups messages into chunks where each chunk is below the
    specified token size. It allows for a slight overflow to avoid splitting
    messages and ensures that the newest messages are at the end of each chunk.

    Args:
        messages (List[Dict[str, str]]): The list of messages.
        chunk_size (int): The target size for each chunk, in tokens.

    Returns:
        List[List[Dict[str, str]]]: A list of chunks, each containing messages
                                    and each below the specified token size.
    """
    chunks = []
    current_chunk = []
    current_chunk_size = 0
    logger.debug("Chunk size: %s", chunk_size)

    for message in reversed(messages):
        message_token_count = rough_estimate_token_length(message.get('content', ''))

        # The 0.8 (80%) threshold provides headroom so that the final message
        # added to a chunk doesn't cause the rendered text block to exceed the
        # chunk_size target after formatting overhead (newlines, role labels, etc.).
        if not current_chunk or (current_chunk_size + message_token_count <= chunk_size * 0.8):
            current_chunk.insert(0, message)
            current_chunk_size += message_token_count
        else:
            logger.debug("Finalizing chunk. Size: %s", current_chunk_size)
            chunks.insert(0, current_chunk)
            current_chunk = [message]
            current_chunk_size = message_token_count

    # After the loop, add the last remaining chunk if it's not empty. The final
    # chunk (the oldest messages) is always included; discarding it would
    # permanently lose the beginning of conversations.
    if current_chunk:
        logger.debug("Adding final remaining chunk.")
        chunks.insert(0, current_chunk)

    return chunks


def messages_into_chunked_text_of_token_size(messages: List[Dict[str, str]], chunk_size: int) -> List[str]:
    """Converts messages into chunked text of a specified token size.

    This function chunks the messages into specified token sizes and then converts these chunks into formatted text blocks.

    Args:
        messages (List[Dict[str, str]]): The list of messages.
        chunk_size (int): The target size for each chunk, in tokens.

    Returns:
        List[str]: A list of text blocks, each corresponding to a chunk of messages.
    """
    chunked_messages = chunk_messages_by_token_size(messages, chunk_size)
    text_blocks = [messages_to_text_block(chunk) for chunk in chunked_messages]
    return text_blocks


def messages_to_text_block(messages: List[Dict[str, str]]) -> str:
    """Converts messages to a plain text block.

    This function joins the content of each message with newlines. Roles are
    not included; only the message contents appear in the output.

    Args:
        messages (List[Dict[str, str]]): The list of messages.

    Returns:
        str: The message contents joined by newlines.
    """
    chunk = "\n".join(message['content'] for message in messages)
    logger.debug("***************************************")
    logger.debug("Chunk created: %s", chunk)
    return chunk


def get_message_chunks(messages: List[Dict[str, str]], lookbackStartTurn: int, chunk_size: int) -> List[str]:
    """
    Break down the conversation into chunks of a specified size for processing.

    Args:
        messages (List[Dict[str, str]]): The list of message dictionaries for the discussion.
        lookbackStartTurn (int): The number of turns to look back in the conversation.
            A value of 0 uses all messages except the last one.
        chunk_size (int): The maximum size of each chunk in tokens.

    Returns:
        List[str]: The list of message chunks as formatted text blocks.
    """
    if lookbackStartTurn > 0:
        pairs = messages[-lookbackStartTurn:]
    elif len(messages) > 1:
        pairs = messages[:-1]
    else:
        pairs = []

    return messages_into_chunked_text_of_token_size(pairs, chunk_size)


def clear_out_user_assistant_from_chunks(search_result_chunks):
    """
    Strips role prefixes from each chunk in the given search result chunks.

    Removes 'User: ', 'Assistant: ', and 'systemMes: ' prefixes (in their
    title-case and upper-case spellings) from each chunk so that only the raw
    message content remains. None entries are dropped.

    Args:
        search_result_chunks: A list of chunks, each representing a segment of
            conversation text that may contain role prefixes.

    Returns:
        list: A new list of chunks with role prefixes removed.
    """
    role_prefixes = ('User: ', 'USER: ', 'Assistant: ', 'ASSISTANT: ', 'systemMes: ', 'SYSTEMMES: ')
    new_chunks = []
    for chunk in search_result_chunks:
        if chunk is not None:
            for prefix in role_prefixes:
                chunk = chunk.replace(prefix, '')
            new_chunks.append(chunk)
    return new_chunks


def replace_brackets_in_list(input_list: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Replaces brackets in the 'content' element of each dictionary in the list.

    This function iterates over a list of dictionaries and replaces specific
    patterns of brackets in the 'content' element to ensure they are properly
    escaped and do not interfere with text processing.

    Args:
        input_list (List[Dict[str, str]]): The list of dictionaries containing
                                          'content' with brackets to be replaced.

    Returns:
        List[Dict[str, str]]: The list of dictionaries with replaced brackets
                              in the 'content' element.
    """
    # Literal curly braces in user content would be misinterpreted as format
    # placeholders by str.format(). We replace them with sentinel tokens that
    # are unlikely to appear in natural text and that contain no curly braces
    # themselves (to avoid being mangled by str.format()), then restore them
    # after formatting is complete (see return_brackets).
    bracket_dict = {r'{': r'__WILMER_L_CURLY__', r'}': r'__WILMER_R_CURLY__'}
    return replace_characters_in_collection(input_list, bracket_dict)


def return_brackets(input_list: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Replaces escaped brackets in the 'content' element of each dictionary in the list.

    This function iterates over a list of dictionaries and replaces specific patterns
    of brackets within the 'content' value to ensure they are properly escaped and
    do not interfere with text processing.

    Args:
        input_list (List[Dict[str, str]]): The list of dictionaries containing 'content'
                                          to be replaced.

    Returns:
        List[Dict[str, str]]: The list of dictionaries with replaced brackets in 'content'.
    """
    bracket_dict = {r'__WILMER_L_CURLY__': r'{', r'__WILMER_R_CURLY__': r'}'}
    return replace_characters_in_collection(input_list, bracket_dict)


def replace_characters_in_collection(input_list: List[Dict[str, str]], characters_to_replace: Dict[str, str]) -> List[
    Dict[str, str]]:
    """Replaces specific characters in the 'content' element of each dictionary in the list.

    This function iterates over a list of dictionaries and replaces specified patterns
    of characters within the 'content' value.

    Args:
        input_list (List[Dict[str, str]]): The list of dictionaries containing 'content'
                                           to be processed.
        characters_to_replace (Dict[str, str]): The dictionary with characters to be replaced
                                                as keys and their replacements as values.

    Returns:
        List[Dict[str, str]]: The list of dictionaries with replaced characters in 'content'.
    """
    for item in input_list:
        content = item.get('content', '')
        for target, replacement in characters_to_replace.items():
            content = content.replace(target, replacement)
        item['content'] = content
    return input_list


def escape_brackets_in_string(input: str) -> str:
    """Replaces literal curly braces with sentinel tokens.

    This is the string-level counterpart of ``replace_brackets_in_list``.
    It converts ``{`` and ``}`` into ``__WILMER_L_CURLY__`` and
    ``__WILMER_R_CURLY__`` so that the string is safe to pass through
    ``str.format()`` without misinterpreting the braces as placeholders.
    Use ``return_brackets_in_string`` to restore them afterwards.

    Args:
        input (str): The string to be processed.

    Returns:
        str: The string with curly braces replaced by sentinel tokens.
    """
    bracket_dict = {r'{': r'__WILMER_L_CURLY__', r'}': r'__WILMER_R_CURLY__'}
    return replace_characters_in_string(input, bracket_dict)


def return_brackets_in_string(input: str) -> str:
    """Replaces escaped brackets in a string.

    This function replaces specific patterns of escaped brackets in the input string.

    Args:
        input (str): The string to be processed.

    Returns:
        str: The string with replaced brackets.
    """
    bracket_dict = {r'__WILMER_L_CURLY__': r'{', r'__WILMER_R_CURLY__': r'}'}
    return replace_characters_in_string(input, bracket_dict)


def replace_characters_in_string(input: str, characters_to_replace: Dict[str, str]) -> str:
    """Replaces specific characters in a string.

    This function replaces specified patterns of characters in the input string.

    Args:
        input (str): The string to be processed.
        characters_to_replace (Dict[str, str]): The dictionary with characters to be replaced
                                                as keys and their replacements as values.

    Returns:
        str: The string with replaced characters.
    """
    content = input
    for target, replacement in characters_to_replace.items():
        content = content.replace(target, replacement)
    return content


def tokenize(text: str) -> List[str]:
    r"""Extracts word tokens from text.

    Returns all word-boundary-delimited sequences of word characters.

    Args:
        text (str): The text to be tokenized.

    Returns:
        List[str]: A list of word tokens extracted from the text.
    """
    return re.findall(r'\b\w+\b', text)


def replace_delimiter_in_file(filepath: str, delimit_on: str, delimit_replacer: str) -> str:
    """Replaces a specified delimiter in a file with a new string.

    This function reads the content of a file, replaces all occurrences of a specified delimiter
    with a new string, and returns the modified text.

    Args:
        filepath (str): The complete path to the file.
        delimit_on (str): The delimiter to be replaced.
        delimit_replacer (str): The string to replace the delimiter with.

    Returns:
        str: The modified text with the delimiter replaced, or an error message if the file cannot be read.
    """
    try:
        with open(filepath, encoding='utf-8') as file:
            text = file.read()

        modified_text = text.replace(delimit_on, delimit_replacer)
        return modified_text

    except FileNotFoundError:
        logger.error(f"Error: The file at {filepath} was not found.")
        raise
    except IOError:
        logger.error(f"Error: An IOError occurred while reading the file at {filepath}.")
        raise


def redact_sensitive_data(data, redaction_text='***REDACTED***'):
    """Redacts sensitive information from data structures for safe logging.

    This function recursively processes dictionaries and lists to redact values
    associated with keys that typically contain sensitive information such as
    API keys, passwords, tokens, and secrets. The original data structure is
    not modified; a deep copy with redacted values is returned.

    Sensitive keys detected (case-insensitive, see _SENSITIVE_KEYS):
    - apiKey, api_key, apikey
    - password, passwd, pwd
    - token, access_token, refresh_token, auth_token, bearer_token
    - secret, client_secret, api_secret
    - authorization, auth
    - private_key, privateKey

    Args:
        data: The data structure to redact. Can be a dict, list, or any other type.
        redaction_text (str): The text to replace sensitive values with.
                             Defaults to '***REDACTED***'.

    Returns:
        The data structure with sensitive values redacted. For non-dict/list types,
        returns the original value unchanged.

    Example:
        >>> config = {'apiKey': 'secret123', 'endpoint': 'https://api.example.local'}
        >>> redact_sensitive_data(config)
        {'apiKey': '***REDACTED***', 'endpoint': 'https://api.example.local'}
    """

    def _redact_recursive(obj):
        """Recursively redact sensitive data in nested structures."""
        if isinstance(obj, dict):
            redacted = {}
            for key, value in obj.items():
                if key.lower() in _SENSITIVE_KEYS:
                    redacted[key] = redaction_text
                else:
                    redacted[key] = _redact_recursive(value)
            return redacted
        elif isinstance(obj, list):
            return [_redact_recursive(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(_redact_recursive(item) for item in obj)
        else:
            return obj

    return _redact_recursive(data)


def strip_data_uri_prefix(image_str: str) -> str:
    """
    Strips the ``data:...;base64,`` prefix from a data URI, returning raw base64.

    If the string does not start with a data URI prefix it is returned unchanged.
    Used by the llmapis handlers whose backends (KoboldCpp, Ollama) expect raw
    base64 image data rather than data URIs.

    Args:
        image_str (str): A base64 string or data URI.

    Returns:
        str: The raw base64 data with any data URI prefix removed.
    """
    if image_str.startswith("data:") and ";base64," in image_str:
        return image_str.split(";base64,", 1)[1]
    return image_str
