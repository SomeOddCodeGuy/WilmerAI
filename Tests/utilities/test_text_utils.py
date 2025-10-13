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
    redact_sensitive_data,
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


class TestRedactSensitiveData:
    """
    Tests for the redact_sensitive_data function.
    """

    def test_redact_api_key(self):
        """
        Tests that API keys are redacted in dictionaries.
        """
        data = {
            'apiKey': 'secret123',
            'endpoint': 'https://api.example.com'
        }
        result = redact_sensitive_data(data)
        assert result['apiKey'] == '***REDACTED***'
        assert result['endpoint'] == 'https://api.example.com'

    def test_redact_multiple_sensitive_fields(self):
        """
        Tests that multiple sensitive fields are redacted.
        """
        data = {
            'apiKey': 'secret123',
            'password': 'mypassword',
            'token': 'token123',
            'username': 'user',
            'endpoint': 'https://api.example.com'
        }
        result = redact_sensitive_data(data)
        assert result['apiKey'] == '***REDACTED***'
        assert result['password'] == '***REDACTED***'
        assert result['token'] == '***REDACTED***'
        assert result['username'] == 'user'
        assert result['endpoint'] == 'https://api.example.com'

    def test_redact_case_insensitive(self):
        """
        Tests that redaction works case-insensitively.
        """
        data = {
            'ApiKey': 'secret123',
            'API_KEY': 'secret456',
            'PASSWORD': 'mypassword',
            'endpoint': 'https://api.example.com'
        }
        result = redact_sensitive_data(data)
        assert result['ApiKey'] == '***REDACTED***'
        assert result['API_KEY'] == '***REDACTED***'
        assert result['PASSWORD'] == '***REDACTED***'
        assert result['endpoint'] == 'https://api.example.com'

    def test_redact_nested_dict(self):
        """
        Tests that redaction works recursively in nested dictionaries.
        """
        data = {
            'config': {
                'apiKey': 'secret123',
                'endpoint': 'https://api.example.com'
            },
            'username': 'user'
        }
        result = redact_sensitive_data(data)
        assert result['config']['apiKey'] == '***REDACTED***'
        assert result['config']['endpoint'] == 'https://api.example.com'
        assert result['username'] == 'user'

    def test_redact_list_of_dicts(self):
        """
        Tests that redaction works on lists containing dictionaries.
        """
        data = [
            {'apiKey': 'secret1', 'name': 'config1'},
            {'apiKey': 'secret2', 'name': 'config2'}
        ]
        result = redact_sensitive_data(data)
        assert result[0]['apiKey'] == '***REDACTED***'
        assert result[0]['name'] == 'config1'
        assert result[1]['apiKey'] == '***REDACTED***'
        assert result[1]['name'] == 'config2'

    def test_redact_mixed_nested_structure(self):
        """
        Tests redaction on complex nested structures.
        """
        data = {
            'servers': [
                {
                    'name': 'server1',
                    'credentials': {
                        'apiKey': 'secret123',
                        'secret': 'mysecret'
                    }
                },
                {
                    'name': 'server2',
                    'credentials': {
                        'password': 'pass456',
                        'endpoint': 'https://api.example.com'
                    }
                }
            ]
        }
        result = redact_sensitive_data(data)
        assert result['servers'][0]['credentials']['apiKey'] == '***REDACTED***'
        assert result['servers'][0]['credentials']['secret'] == '***REDACTED***'
        assert result['servers'][0]['name'] == 'server1'
        assert result['servers'][1]['credentials']['password'] == '***REDACTED***'
        assert result['servers'][1]['credentials']['endpoint'] == 'https://api.example.com'

    def test_redact_custom_text(self):
        """
        Tests that custom redaction text can be used.
        """
        data = {'apiKey': 'secret123', 'endpoint': 'https://api.example.com'}
        result = redact_sensitive_data(data, redaction_text='[HIDDEN]')
        assert result['apiKey'] == '[HIDDEN]'
        assert result['endpoint'] == 'https://api.example.com'

    def test_redact_empty_dict(self):
        """
        Tests that an empty dictionary is returned unchanged.
        """
        data = {}
        result = redact_sensitive_data(data)
        assert result == {}

    def test_redact_no_sensitive_data(self):
        """
        Tests that dictionaries without sensitive data are unchanged.
        """
        data = {
            'name': 'test',
            'endpoint': 'https://api.example.com',
            'timeout': 30
        }
        result = redact_sensitive_data(data)
        assert result == data

    def test_redact_primitive_types(self):
        """
        Tests that primitive types are returned unchanged.
        """
        assert redact_sensitive_data('string') == 'string'
        assert redact_sensitive_data(123) == 123
        assert redact_sensitive_data(True) is True
        assert redact_sensitive_data(None) is None

    def test_redact_tuple(self):
        """
        Tests that redaction works on tuples.
        """
        data = ({'apiKey': 'secret123'}, {'password': 'pass456'})
        result = redact_sensitive_data(data)
        assert isinstance(result, tuple)
        assert result[0]['apiKey'] == '***REDACTED***'
        assert result[1]['password'] == '***REDACTED***'

    def test_redact_all_sensitive_key_variations(self):
        """
        Tests that all documented sensitive key variations are redacted.
        """
        data = {
            'api_key': 'secret1',
            'apikey': 'secret2',
            'password': 'secret3',
            'passwd': 'secret4',
            'pwd': 'secret5',
            'token': 'secret6',
            'access_token': 'secret7',
            'refresh_token': 'secret8',
            'auth_token': 'secret9',
            'bearer_token': 'secret10',
            'secret': 'secret11',
            'client_secret': 'secret12',
            'api_secret': 'secret13',
            'authorization': 'secret14',
            'auth': 'secret15',
            'private_key': 'secret16',
            'privatekey': 'secret17'
        }
        result = redact_sensitive_data(data)
        for key in data.keys():
            assert result[key] == '***REDACTED***', f"Key '{key}' was not redacted"
