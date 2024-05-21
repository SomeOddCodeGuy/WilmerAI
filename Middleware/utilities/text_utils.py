import re
from typing import List, Tuple


# Based on this response from ruby_coder on OpenAI forums:
# https://community.openai.com/t/what-is-the-openai-algorithm-to-calculate-tokens/58237/4
# This roughly estimates the token length of a prompt
# Modified to overestimate the number of tokens, which
# We want to do in order to be safe on the truncation
# until I swap to something better
# Right now Im trying to avoid pulling a model in if I can help it
# probably will give in eventually, though...
def rough_estimate_token_length(text: str) -> int:
    """Estimates the token length of a prompt, overestimating slightly.

    This function splits the text into words and characters to estimate the
    number of tokens. It is designed to overestimate to ensure that the token
    limit is not exceeded when interfacing with language models.

    Args:
        text (str): The text to estimate the token length for.

    Returns:
        int: The estimated token length.
    """
    words = text.split()
    word_count = len(words)
    char_count = len(text)

    tokens_word_est = word_count / 0.65
    tokens_char_est = char_count / 3.5

    return int(max(tokens_word_est, tokens_char_est))


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
    start_index = len(words)

    for i in range(len(words) - 1, -1, -1):
        word = words[i]
        cumulative_tokens += rough_estimate_token_length(word + ' ')
        if cumulative_tokens > num_tokens:
            start_index = i + 1
            break

    return ' '.join(words[start_index:])


def reduce_pairs_to_fit_token_limit(system_prompt: str, pairs: List[Tuple[str, str]], max_tokens: int) -> List[
    Tuple[str, str]]:
    """Reduces pairs to fit within a maximum token limit.

    This function processes user/assistant turn pairs in reverse order,
    accumulating token estimates until the specified maximum token limit
    is reached. It ensures that full pairs are included without exceeding
    the token limit.

    Args:
        system_prompt (str): The system prompt to be prepended to the pairs.
        pairs (List[Tuple[str, str]]): The list of user/assistant turn pairs.
        max_tokens (int): The maximum number of tokens allowed.

    Returns:
        List[Tuple[str, str]]: The list of pairs that fit within the token limit.
    """
    current_token_count = rough_estimate_token_length(system_prompt)
    fitting_pairs = []

    for user_text, assistant_text in reversed(pairs):
        pair_text = f"{user_text} {assistant_text}"
        pair_token_count = rough_estimate_token_length(pair_text)

        if current_token_count + pair_token_count <= max_tokens:
            fitting_pairs.append((user_text, assistant_text))
            current_token_count += pair_token_count
        else:
            break

    return list(reversed(fitting_pairs))


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


def chunk_pairs_by_token_size(pairs: List[Tuple[str, str]], chunk_size: int) -> List[List[Tuple[str, str]]]:
    """Chunks pairs based on a specified token size.

    This function groups user/assistant turn pairs into chunks where each
    chunk is below the specified token size. It allows for a slight overflow
    to avoid splitting pairs and ensures that the newest messages are at
    the end of each chunk.

    Args:
        pairs (List[Tuple[str, str]]): The list of user/assistant turn pairs.
        chunk_size (int): The target size for each chunk, in tokens.

    Returns:
        List[List[Tuple[str, str]]]: A list of chunks, each containing pairs and
                                      each below the specified token size.
    """
    chunks = []
    current_chunk = []
    current_chunk_size = 0

    for user_text, assistant_text in pairs:
        user_token_count = rough_estimate_token_length(user_text)
        assistant_token_count = rough_estimate_token_length(assistant_text)
        pair_size = user_token_count + assistant_token_count

        if pair_size > chunk_size:
            if current_chunk_size + pair_size <= chunk_size * 1.1:
                current_chunk.append((user_text, assistant_text))
                current_chunk_size += pair_size
                continue
            elif current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_chunk_size = 0

        if current_chunk_size + pair_size > chunk_size:
            chunks.append(current_chunk)
            current_chunk = []
            current_chunk_size = 0

        current_chunk.append((user_text, assistant_text))
        current_chunk_size += pair_size

    if current_chunk:
        chunks.append(current_chunk)

    for i in range(len(chunks)):
        chunks[i] = chunks[i][::-1]

    return chunks


def reduce_turn_pairs_down_to_wilmer_acceptable_length(system_prompt: str, pairs: List[Tuple[str, str]],
                                                       truncate_length: int, max_new_tokens: int) -> List[
    Tuple[str, str]]:
    """Reduces turn pairs to an acceptable length for Wilmer.

    This function adjusts the target token limit for reducing pairs based on
    the maximum number of new tokens that can be generated by the model. It ensures
    that the reduced pairs are within the acceptable length for processing by
    the Wilmer middleware.

    Args:
        system_prompt (str): The system prompt to be prepended to the pairs.
        pairs (List[Tuple[str, str]]): The list of user/assistant turn pairs.
        truncate_length (int): The target token length for truncation.
        max_new_tokens (int): The maximum number of new tokens the model can generate.

    Returns:
        List[Tuple[str, str]]: The reduced list of pairs that fit within the acceptable length.
    """
    if 0 < max_new_tokens < truncate_length:
        true_truncate_length = int((truncate_length - max_new_tokens) * 0.8)
        pairs = reduce_pairs_to_fit_token_limit(system_prompt, pairs, true_truncate_length)
    return pairs


def turn_pairs_into_chunked_text_of_token_size(pairs: List[Tuple[str, str]], chunk_size: int) -> List[str]:
    """Converts turn pairs into chunked text of a specified token size.

    This function chunks the user/assistant turn pairs into specified token sizes
    and then converts these chunks into formatted text blocks.

    Args:
        pairs (List[Tuple[str, str]]): The list of user/assistant turn pairs.
        chunk_size (int): The target size for each chunk, in tokens.

    Returns:
        List[str]: A list of text blocks, each corresponding to a chunk of pairs.
    """
    chunked_pairs = chunk_pairs_by_token_size(pairs, chunk_size)
    text_blocks = [pairs_to_text_block(chunk) for chunk in chunked_pairs]
    return text_blocks


def pairs_to_text_block(pairs: List[Tuple[str, str]]) -> str:
    """Converts pairs to a formatted text block.

    This function takes a list of user/assistant turn pairs and formats them into
    a text block with proper labels for user and assistant messages.

    Args:
        pairs (List[Tuple[str, str]]): The list of user/assistant turn pairs.

    Returns:
        str: A formatted text block representing the conversation.
    """
    formatted_pairs = [f"User: {user_text}\nAssistant: {assistant_text}\n" for user_text, assistant_text in pairs]
    return "\n".join(formatted_pairs)


def replace_brackets(input_string: str) -> str:
    """Replaces brackets to escape them.

    This function replaces specific patterns of brackets to ensure they are
    properly escaped and do not interfere with text processing.

    Args:
        input_string (str): The string containing brackets to be replaced.

    Returns:
        str: The string with replaced brackets.
    """
    bracket_dict = {r'{': '{{', r'}': '}}'}
    for bracket, replacement in bracket_dict.items():
        input_string = re.sub(bracket, replacement, input_string)
    return input_string


def tokenize(text: str) -> List[str]:
    """Tokenizes text while excluding words followed directly by a colon.

    This function tokenizes the input text, excluding tokens that are immediately
    followed by a colon, which are typically used as labels or identifiers.

    Args:
        text (str): The text to be tokenized.

    Returns:
        List[str]: A list of tokens extracted from the text.
    """
    return re.findall(r'\b\w+\b(?<!:)', text)
