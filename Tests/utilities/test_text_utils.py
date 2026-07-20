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
    escape_brackets_in_string,
    return_brackets_in_string,
    replace_characters_in_string,
    tokenize,
    replace_delimiter_in_file,
    redact_sensitive_data,
    strip_data_uri_prefix,
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
        # Unbroken CJK text has no spaces: word ratio sees 1 word (1.35), the
        # char ratio dominates. 7 chars / 3.5 = 2.0, * 1.10 margin = 2.2 -> 2.
        ("こんにちは世界", 2),
    ]
)
def test_rough_estimate_token_length(text, expected_tokens):
    """
    Tests the token estimation logic with various inputs.
    """
    assert rough_estimate_token_length(text) == expected_tokens


def test_rough_estimate_token_length_custom_safety_margin():
    """
    Tests that custom safety_margin values produce different results.
    Uses a text where the margin changes the int() truncation result.
    """
    # "one two three four five" = 5 words, 23 chars
    # word_est = 5 * 1.35 = 6.75
    # char_est = 23 / 3.5 = 6.571
    # max = 6.75
    text = "one two three four five"

    # With safety_margin=1.0: int(6.75 * 1.0) = 6
    assert rough_estimate_token_length(text, safety_margin=1.0) == 6

    # With default safety_margin=1.10: int(6.75 * 1.10) = int(7.425) = 7
    assert rough_estimate_token_length(text, safety_margin=1.10) == 7

    # With safety_margin=2.0: int(6.75 * 2.0) = int(13.5) = 13
    assert rough_estimate_token_length(text, safety_margin=2.0) == 13


def test_rough_estimate_default_margin_distinguishable_from_no_margin():
    """
    Tests that the default safety margin is exactly 1.10: for this input the
    raw estimate is 6.75, so int(6.75 * 1.10) = 7 while a default of 1.0 would
    give 6 and 1.20 would give 8. Pins the documented default, not just "some
    margin exists".
    """
    # "one two three four five" has word_est=6.75, char_est=6.571
    text = "one two three four five"
    result_with_margin = rough_estimate_token_length(text)       # 1.10 default
    result_no_margin = rough_estimate_token_length(text, safety_margin=1.0)
    assert result_with_margin > result_no_margin
    assert result_with_margin == 7  # int(6.75 * 1.10); default must be 1.10
    assert result_no_margin == 6    # int(6.75 * 1.00)


@pytest.mark.parametrize(
    "text, token_limit, expected_text",
    [
        # Text fully within the limit is returned unchanged.
        ("one two three four five", 5, "one two three four five"),
        ("one two three four five", 4, "two three four five"),
        ("one two three four five", 100, "one two three four five"),
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
        # Exact-fit boundary: each single-letter word estimates to 1 token, and
        # the split condition is strictly greater-than, so a chunk that lands
        # exactly on chunk_size is NOT split...
        ("a b", 2, ["a b"]),
        # ...but one more word past the exact boundary starts a new chunk.
        ("a b c", 2, ["a b", "c"]),
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
    chunks = chunk_messages_by_token_size(messages, 20)
    assert len(chunks) == 4
    assert chunks[0] == [messages[0]]
    assert chunks[1] == [messages[1]]
    assert chunks[2] == [messages[2]]
    assert chunks[3] == [messages[3]]


def test_chunk_messages_single_oversized_message_still_admitted():
    """
    A message whose estimated size exceeds chunk_size is still admitted when the
    current chunk is empty: messages are never split or dropped, so an oversized
    message forms its own chunk.
    """
    messages = [
        {"role": "user", "content": "this message is far larger than the tiny chunk size"},
    ]
    chunks = chunk_messages_by_token_size(messages, 1)
    assert chunks == [messages]


def test_chunk_messages_fits_in_one_chunk():
    """
    Tests that no chunking occurs if all messages fit within the chunk size.
    """
    messages = deepcopy(MESSAGES_FIXTURE)
    chunks = chunk_messages_by_token_size(messages, 100)
    assert len(chunks) == 1
    assert chunks[0] == messages


# Three messages that each estimate to exactly 4 tokens: one 14-char "word",
# so char ratio dominates -> int(max(1.35, 14/3.5) * 1.10) = int(4.4) = 4.
# With chunk_size=10 the 80% headroom threshold is 8: the newest two messages
# together hit the threshold exactly (4+4=8 <= 8, admitted), while the third
# would overflow it (8+4=12 > 8) and starts an older chunk.
FOUR_TOKEN_MESSAGES = [
    {"role": "user", "content": "aaaaaaaaaaaaaa"},
    {"role": "assistant", "content": "bbbbbbbbbbbbbb"},
    {"role": "user", "content": "cccccccccccccc"},
]


def test_chunk_messages_exact_80_percent_boundary_is_inclusive():
    """
    A message landing exactly on the 80% headroom threshold is admitted to the
    current chunk (the comparison is <=, not <). Breaking either the 0.8 factor
    or the inclusive comparison changes the grouping and fails this test.
    """
    messages = deepcopy(FOUR_TOKEN_MESSAGES)
    chunks = chunk_messages_by_token_size(messages, 10)
    assert chunks == [[messages[0]], [messages[1], messages[2]]]


def test_messages_into_chunked_text_of_token_size():
    """
    End-to-end: messages are chunked by the real chunker and rendered into
    newline-joined text blocks, oldest chunk first, roles omitted.
    """
    messages = deepcopy(FOUR_TOKEN_MESSAGES)
    text_blocks = messages_into_chunked_text_of_token_size(messages, 10)
    assert text_blocks == [
        "aaaaaaaaaaaaaa",
        "bbbbbbbbbbbbbb\ncccccccccccccc",
    ]


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


def test_get_message_chunks_single_message_lookback_zero_returns_empty():
    """
    With lookbackStartTurn=0 and only one message there is nothing to chunk
    (the last message is always excluded in the lookback=0 path): the result
    is an empty list, not a chunk containing the sole message.
    """
    messages = [{"role": "user", "content": "only message"}]
    assert get_message_chunks(messages, lookbackStartTurn=0, chunk_size=100) == []


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
    assert replaced_list[0]['content'] == "A __WILMER_L_CURLY__test__WILMER_R_CURLY__ string."
    returned_list = return_brackets(deepcopy(replaced_list))
    assert returned_list[0]['content'] == "A {test} string."


def test_replace_and_return_brackets_in_string():
    """
    Tests both replacing and restoring brackets in a simple string.
    """
    original_string = "Another {test} string."
    bracket_dict = {r'{': r'__WILMER_L_CURLY__', r'}': r'__WILMER_R_CURLY__'}
    replaced_string = replace_characters_in_string(original_string, bracket_dict)
    assert replaced_string == "Another __WILMER_L_CURLY__test__WILMER_R_CURLY__ string."
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


class TestEscapeBracketsInString:
    """Tests for escape_brackets_in_string and its round-trip with return_brackets_in_string."""

    def test_simple_json(self):
        """A simple JSON object should have all braces replaced with sentinels."""
        result = escape_brackets_in_string('{"name": "test"}')
        assert "{" not in result
        assert "}" not in result
        assert "__WILMER_L_CURLY__" in result

    def test_nested_json(self):
        """Deeply nested JSON should have every brace escaped."""
        original = '{"a": {"b": {"c": [1, 2, {"d": true}]}}}'
        escaped = escape_brackets_in_string(original)
        assert escaped.count("__WILMER_L_CURLY__") == original.count("{")
        assert escaped.count("__WILMER_R_CURLY__") == original.count("}")

    def test_empty_braces(self):
        """Empty brace pair should become a sentinel pair."""
        assert escape_brackets_in_string("{}") == "__WILMER_L_CURLY____WILMER_R_CURLY__"

    def test_no_braces(self):
        """Strings without braces pass through unchanged."""
        assert escape_brackets_in_string("hello world") == "hello world"

    def test_empty_string(self):
        """Empty string passes through unchanged."""
        assert escape_brackets_in_string("") == ""

    def test_mixed_content(self):
        """Text mixed with JSON should only escape the brace characters."""
        result = escape_brackets_in_string('prefix {"key": "val"} suffix')
        assert result.startswith("prefix ")
        assert result.endswith(" suffix")
        assert "{" not in result

    def test_round_trip_simple_json(self):
        """escape then return should reproduce the original string exactly."""
        original = '{"key": "value"}'
        assert return_brackets_in_string(escape_brackets_in_string(original)) == original

    def test_round_trip_nested_json(self):
        """Round-trip on complex nested JSON."""
        original = '{"tools": [{"type": "function", "function": {"name": "bash", "parameters": {"command": "ls"}}}]}'
        assert return_brackets_in_string(escape_brackets_in_string(original)) == original

    def test_round_trip_python_code(self):
        """Round-trip on a Python code snippet with braces."""
        original = 'def foo():\n    return {"status": True}'
        assert return_brackets_in_string(escape_brackets_in_string(original)) == original

    def test_round_trip_single_open_brace(self):
        """A lone open brace should survive the round-trip."""
        original = "incomplete { brace"
        assert return_brackets_in_string(escape_brackets_in_string(original)) == original

    def test_round_trip_single_close_brace(self):
        """A lone close brace should survive the round-trip."""
        original = "incomplete } brace"
        assert return_brackets_in_string(escape_brackets_in_string(original)) == original

    def test_return_on_already_plain_string_is_noop(self):
        """return_brackets_in_string on a string with no sentinels is a no-op."""
        plain = "Hello, this has no sentinels."
        assert return_brackets_in_string(plain) == plain

    def test_escape_on_already_escaped_is_idempotent_for_sentinels(self):
        """Escaping a string that already has sentinel tokens should not double-escape,
        because the sentinels themselves contain no curly braces."""
        original = '{"key": "val"}'
        once = escape_brackets_in_string(original)
        twice = escape_brackets_in_string(once)
        # No braces remain after either pass
        assert "{" not in once
        assert "{" not in twice
        # Single return restores both levels since sentinels don't nest
        assert return_brackets_in_string(once) == original


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
            'endpoint': 'https://api.example.local'
        }
        result = redact_sensitive_data(data)
        assert result['apiKey'] == '***REDACTED***'
        assert result['endpoint'] == 'https://api.example.local'

    def test_redact_multiple_sensitive_fields(self):
        """
        Tests that multiple sensitive fields are redacted.
        """
        data = {
            'apiKey': 'secret123',
            'password': 'mypassword',
            'token': 'token123',
            'username': 'user',
            'endpoint': 'https://api.example.local'
        }
        result = redact_sensitive_data(data)
        assert result['apiKey'] == '***REDACTED***'
        assert result['password'] == '***REDACTED***'
        assert result['token'] == '***REDACTED***'
        assert result['username'] == 'user'
        assert result['endpoint'] == 'https://api.example.local'

    def test_redact_case_insensitive(self):
        """
        Tests that redaction works case-insensitively.
        """
        data = {
            'ApiKey': 'secret123',
            'API_KEY': 'secret456',
            'PASSWORD': 'mypassword',
            'endpoint': 'https://api.example.local'
        }
        result = redact_sensitive_data(data)
        assert result['ApiKey'] == '***REDACTED***'
        assert result['API_KEY'] == '***REDACTED***'
        assert result['PASSWORD'] == '***REDACTED***'
        assert result['endpoint'] == 'https://api.example.local'

    def test_redact_nested_dict(self):
        """
        Tests that redaction works recursively in nested dictionaries.
        """
        data = {
            'config': {
                'apiKey': 'secret123',
                'endpoint': 'https://api.example.local'
            },
            'username': 'user'
        }
        result = redact_sensitive_data(data)
        assert result['config']['apiKey'] == '***REDACTED***'
        assert result['config']['endpoint'] == 'https://api.example.local'
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
                        'endpoint': 'https://api.example.local'
                    }
                }
            ]
        }
        result = redact_sensitive_data(data)
        assert result['servers'][0]['credentials']['apiKey'] == '***REDACTED***'
        assert result['servers'][0]['credentials']['secret'] == '***REDACTED***'
        assert result['servers'][0]['name'] == 'server1'
        assert result['servers'][1]['credentials']['password'] == '***REDACTED***'
        assert result['servers'][1]['credentials']['endpoint'] == 'https://api.example.local'

    def test_redact_custom_text(self):
        """
        Tests that custom redaction text can be used.
        """
        data = {'apiKey': 'secret123', 'endpoint': 'https://api.example.local'}
        result = redact_sensitive_data(data, redaction_text='[HIDDEN]')
        assert result['apiKey'] == '[HIDDEN]'
        assert result['endpoint'] == 'https://api.example.local'

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
            'endpoint': 'https://api.example.local',
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

    def test_redact_does_not_mutate_input(self):
        """
        Tests that the input structure is not modified; a redacted copy is returned.
        """
        data = {
            'apiKey': 'secret123',
            'servers': [{'credentials': {'password': 'pass456'}, 'name': 'server1'}],
            'endpoint': 'https://api.example.local'
        }
        original = deepcopy(data)
        redact_sensitive_data(data)
        assert data == original


class TestStripDataUriPrefix:
    """
    Tests for strip_data_uri_prefix, used by the KoboldCpp/Ollama handlers to
    convert data URIs into the raw base64 those backends require.
    """

    def test_strips_png_data_uri_prefix(self):
        assert strip_data_uri_prefix("data:image/png;base64,iVBORw0KGgo=") == "iVBORw0KGgo="

    def test_strips_jpeg_data_uri_prefix(self):
        assert strip_data_uri_prefix("data:image/jpeg;base64,/9j/4AAQ") == "/9j/4AAQ"

    def test_plain_base64_unchanged(self):
        """Raw base64 without a data URI prefix passes through untouched."""
        assert strip_data_uri_prefix("iVBORw0KGgo=") == "iVBORw0KGgo="

    def test_data_prefix_without_base64_marker_unchanged(self):
        """A data: URI that is not base64-encoded (no ';base64,') is left alone."""
        assert strip_data_uri_prefix("data:text/plain,hello") == "data:text/plain,hello"

    def test_base64_marker_without_data_prefix_unchanged(self):
        """';base64,' inside a non-data string must not trigger stripping."""
        assert strip_data_uri_prefix("junk;base64,AAAA") == "junk;base64,AAAA"

    def test_only_first_marker_is_split(self):
        """Splitting uses maxsplit=1: a ';base64,' sequence inside the payload
        survives intact."""
        assert strip_data_uri_prefix("data:image/png;base64,AAA;base64,BBB") == "AAA;base64,BBB"

    def test_empty_string_unchanged(self):
        assert strip_data_uri_prefix("") == ""
