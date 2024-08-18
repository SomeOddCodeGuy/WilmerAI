import re
from typing import List, Dict


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


def chunk_messages_by_token_size(messages: List[Dict[str, str]], chunk_size: int) -> List[List[Dict[str, str]]]:
    """Chunks messages based on a specified token size.

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

    for message in messages:
        message_token_count = rough_estimate_token_length(message['content'])

        if message_token_count > chunk_size:
            if current_chunk_size + message_token_count <= chunk_size * 1.1:
                current_chunk.append(message)
                current_chunk_size += message_token_count
                continue
            elif current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_chunk_size = 0

        if current_chunk_size + message_token_count > chunk_size:
            chunks.append(current_chunk)
            current_chunk = []
            current_chunk_size = 0

        current_chunk.append(message)
        current_chunk_size += message_token_count

    if current_chunk:
        chunks.append(current_chunk)

    for i in range(len(chunks)):
        chunks[i] = chunks[i][::-1]

    return chunks


def reduce_messages_to_fit_token_limit(system_prompt: str, messages: List[Dict[str, str]], max_tokens: int) -> List[
    Dict[str, str]]:
    """Reduces messages to fit within a maximum token limit.

    This function processes messages in reverse order, accumulating token
    estimates until the specified maximum token limit is reached. It ensures
    that full messages are included without exceeding the token limit.

    Args:
        system_prompt (str): The system prompt to be prepended to the messages.
        messages (List[Dict[str, str]]): The list of messages.
        max_tokens (int): The maximum number of tokens allowed.

    Returns:
        List[Dict[str, str]]: The list of messages that fit within the token limit.
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
    """Reduces messages to an acceptable length for Wilmer.

    This function adjusts the target token limit for reducing messages based on
    the maximum number of new tokens that can be generated by the model. It ensures
    that the reduced messages are within the acceptable length for processing by
    the Wilmer middleware.

    Args:
        system_prompt (str): The system prompt to be prepended to the messages.
        messages (List[Dict[str, str]]): The list of messages.
        truncate_length (int): The target token length for truncation.
        max_new_tokens (int): The maximum number of new tokens the model can generate.

    Returns:
        List[Dict[str, str]]: The reduced list of messages that fit within the acceptable length.
    """
    if 0 < max_new_tokens < truncate_length:
        true_truncate_length = int((truncate_length - max_new_tokens) * 0.8)
        messages = reduce_messages_to_fit_token_limit(system_prompt, messages, true_truncate_length)
    return messages


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
    """Converts messages to a formatted text block.

    This function takes a list of messages and formats them into a text block with
    proper labels for each role (system, user, assistant).

    Args:
        messages (List[Dict[str, str]]): The list of messages.

    Returns:
        str: A formatted text block representing the conversation.
    """
    formatted_messages = [f"{message['content']}" for message in messages]
    chunk = "\n".join(formatted_messages)
    print("***************************************")
    print("Chunk created: " + str(chunk))
    return chunk


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
    bracket_dict = {r'{': r'|{{|', r'}': r'|}}|'}
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
    bracket_dict = {r'|{{|': r'{', r'|}}|': r'}'}
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
        for bracket, replacement in characters_to_replace.items():
            content = re.sub(re.escape(bracket), replacement, content)
        item['content'] = content
    return input_list


def return_brackets_in_string(input: str) -> str:
    """Replaces escaped brackets in a string.

    This function replaces specific patterns of escaped brackets in the input string.

    Args:
        input (str): The string to be processed.

    Returns:
        str: The string with replaced brackets.
    """
    bracket_dict = {r'|{{|': r'{', r'|}}|': r'}'}
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
    for bracket, replacement in characters_to_replace.items():
        content = re.sub(re.escape(bracket), replacement, content)
    return content


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
        print(f"Error: The file at {filepath} was not found.")
        raise
    except IOError:
        print(f"Error: An IOError occurred while reading the file at {filepath}.")
        raise
