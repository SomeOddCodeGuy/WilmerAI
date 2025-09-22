# Tests/utilities/test_text_utils.py

from copy import deepcopy

import pytest

from Middleware.utilities.text_utils import (
    rough_estimate_token_length,
    reduce_text_to_token_limit,
    split_into_tokenized_chunks,
    chunk_messages_by_token_size,
    messages_into_chunked_text_of_token_size,
    messages_to_text_block,
    get_message_chunks,
    clear_out_user_assistant_from_chunks,
    replace_brackets_in_list,
    return_brackets,
    replace_characters_in_collection,
    return_brackets_in_string,
    replace_characters_in_string,
    tokenize,
    replace_delimiter_in_file,
)

# Test data to be used across multiple tests
MESSAGES_FIXTURE = [
    {"role": "user", "content": "This is message one."},
    {"role": "assistant", "content": "This is a slightly longer message two."},
    {"role": "user", "content": "Here is message three, which is even longer."},
    {"role": "assistant", "content": "Finally, message four is the longest of them all, a true epic."},
]


@pytest.mark.parametrize(
    "text, expected_tokens",
    [
        ("Hello world", 3),
        ("a b c d e", 7),
        ("antidisestablishmentarianism", 8),
        ("", 0),
        ("  ", 0),
    ]
)
def test_rough_estimate_token_length(text, expected_tokens):
    """
    Tests the token estimation logic with various inputs.
    """
    assert rough_estimate_token_length(text) == expected_tokens


@pytest.mark.parametrize(
    "text, token_limit, expected_text",
    [
        ("one two three four five", 5, ""),
        ("one two three four five", 4, "two three four five"),
        ("one two three four five", 100, ""),
        ("one two three four five", 0, ""),
        ("", 10, ""),
    ]
)
def test_reduce_text_to_token_limit(text, token_limit, expected_text):
    """
    Tests reducing text from the end to fit a token limit.
    """
    assert reduce_text_to_token_limit(text, token_limit) == expected_text


@pytest.mark.parametrize(
    "text, chunk_size, expected_chunks",
    [
        ("one two three four five six", 4, ["one two three four", "five six"]),
        ("one two three", 10, ["one two three"]),
        ("a b c d e f", 1, ["a", "b", "c", "d", "e", "f"]),
        ("", 10, []),
    ]
)
def test_split_into_tokenized_chunks(text, chunk_size, expected_chunks):
    """
    Tests splitting text into chunks of a specified token size.
    """
    assert split_into_tokenized_chunks(text, chunk_size) == expected_chunks


def test_chunk_messages_by_token_size():
    """
    Tests that messages are chunked correctly based on token size, preserving order.
    """
    messages = deepcopy(MESSAGES_FIXTURE)
    chunks = chunk_messages_by_token_size(messages, 20, 0)
    assert len(chunks) == 3
    assert chunks[0] == [messages[0], messages[1]]
    assert chunks[1] == [messages[2]]
    assert chunks[2] == [messages[3]]


def test_chunk_messages_by_token_size_with_max_messages_filter():
    """
    Tests the max_messages_before_chunk logic, which filters out small final chunks.
    """
    messages = [
        {"role": "user", "content": "a b c d e f g h i j"},
        {"role": "user", "content": "k"},
    ]
    chunks = chunk_messages_by_token_size(messages, 20, max_messages_before_chunk=2)
    assert len(chunks) == 1
    assert chunks[0] == messages


def test_chunk_messages_fits_in_one_chunk():
    """
    Tests that no chunking occurs if all messages fit within the chunk size.
    """
    messages = deepcopy(MESSAGES_FIXTURE)
    chunks = chunk_messages_by_token_size(messages, 100, 0)
    assert len(chunks) == 1
    assert chunks[0] == messages


def test_messages_into_chunked_text_of_token_size(mocker):
    """
    Tests the conversion of messages into formatted text blocks.
    """
    mocker.patch(
        "Middleware.utilities.text_utils.chunk_messages_by_token_size",
        return_value=[
            [{"role": "user", "content": "Hello"}],
            [{"role": "assistant", "content": "Hi there!"}],
        ],
    )
    text_blocks = messages_into_chunked_text_of_token_size([], 100, 0)
    assert text_blocks == ["Hello", "Hi there!"]


def test_messages_to_text_block():
    """
    Tests that a list of messages is correctly formatted into a single string.
    """
    messages = [{"role": "user", "content": "Line 1"}, {"role": "assistant", "content": "Line 2"}]
    assert messages_to_text_block(messages) == "Line 1\nLine 2"


@pytest.mark.parametrize(
    "lookback, expected_slice",
    [(2, slice(-2, None)), (0, slice(None, -1)), (100, slice(-100, None))]
)
def test_get_message_chunks(mocker, lookback, expected_slice):
    """
    Tests the message slicing logic of get_message_chunks.
    """
    mock_chunker = mocker.patch("Middleware.utilities.text_utils.messages_into_chunked_text_of_token_size")
    messages = deepcopy(MESSAGES_FIXTURE)
    get_message_chunks(messages, lookbackStartTurn=lookback, chunk_size=100)
    mock_chunker.assert_called_once()
    called_with_messages = mock_chunker.call_args[0][0]
    assert called_with_messages == messages[expected_slice]


@pytest.mark.parametrize(
    "input_chunks, expected_chunks",
    [
        (["User: Hello", "ASSISTANT: Hi", "systemMes: Booting up", "Just text"],
         ["Hello", "Hi", "Booting up", "Just text"]),
        ([None, "USER: Test"], ["Test"]),
        ([], []),
    ]
)
def test_clear_out_user_assistant_from_chunks(input_chunks, expected_chunks):
    """
    Tests the removal of role prefixes from strings.
    """
    assert clear_out_user_assistant_from_chunks(input_chunks) == expected_chunks


def test_replace_and_return_brackets_in_list():
    """
    Tests both replacing and restoring brackets in a list of dictionaries.
    """
    original_list = [{"role": "user", "content": "A {test} string."}]
    replaced_list = replace_brackets_in_list(deepcopy(original_list))
    assert replaced_list[0]['content'] == "A |{{|test|}}| string."
    returned_list = return_brackets(deepcopy(replaced_list))
    assert returned_list[0]['content'] == "A {test} string."


def test_replace_and_return_brackets_in_string():
    """
    Tests both replacing and restoring brackets in a simple string.
    """
    original_string = "Another {test} string."
    bracket_dict = {r'{': r'|{{|', r'}': r'|}}|'}
    replaced_string = replace_characters_in_string(original_string, bracket_dict)
    assert replaced_string == "Another |{{|test|}}| string."
    returned_string = return_brackets_in_string(replaced_string)
    assert returned_string == "Another {test} string."


def test_replace_characters_in_collection():
    """
    Tests the generic character replacement utility for collections.
    """
    input_list = [{"role": "user", "content": "abc"}, {"role": "other", "content": "def"}]
    char_map = {"a": "x", "d": "y"}
    result = replace_characters_in_collection(deepcopy(input_list), char_map)
    assert result[0]['content'] == "xbc"
    assert result[1]['content'] == "yef"


def test_tokenize():
    """
    Tests the custom tokenizer.
    """
    text = "User: Hello, world! Another:"
    assert tokenize(text) == ["User", "Hello", "world", "Another"]


def test_replace_delimiter_in_file_success(mocker):
    """
    Tests successful delimiter replacement by mocking the file system.
    """
    mock_file = mocker.patch("builtins.open", mocker.mock_open(read_data="line1--line2--line3"))
    result = replace_delimiter_in_file("dummy/path.txt", "--", "\n")
    mock_file.assert_called_once_with("dummy/path.txt", encoding='utf-8')
    assert result == "line1\nline2\nline3"


def test_replace_delimiter_in_file_not_found(mocker):
    """
    Tests that FileNotFoundError is correctly raised.
    """
    mocker.patch("builtins.open", side_effect=FileNotFoundError)
    with pytest.raises(FileNotFoundError):
        replace_delimiter_in_file("nonexistent/path.txt", ",", " ")


def test_replace_delimiter_in_file_io_error(mocker):
    """
    Tests that IOError is correctly raised.
    """
    mocker.patch("builtins.open", side_effect=IOError)
    with pytest.raises(IOError):
        replace_delimiter_in_file("bad/path.txt", ",", " ")
