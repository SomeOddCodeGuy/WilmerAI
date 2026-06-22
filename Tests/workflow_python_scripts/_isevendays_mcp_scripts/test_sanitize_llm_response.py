# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_sanitize_llm_response.py

from Public.workflow_python_scripts._isevendays_mcp_scripts.sanitize_llm_response import Invoke, sanitize_json_markers


def test_sanitize_json_markers_restores_escaped_braces():
    """
    Tests that the sentinel tokens Wilmer uses to escape curly braces
    (__WILMER_L_CURLY__ / __WILMER_R_CURLY__) are restored to real braces.
    """
    # Arrange: a valid tool-call payload with its braces escaped to sentinels.
    valid = '{"tool_calls": [{"name": "get_time", "parameters": {}}]}'
    text = valid.replace("{", "__WILMER_L_CURLY__").replace("}", "__WILMER_R_CURLY__")

    # Act
    cleaned = sanitize_json_markers(text)

    # Assert: the sentinels are gone and the original JSON is restored.
    assert "__WILMER_L_CURLY__" not in cleaned
    assert "__WILMER_R_CURLY__" not in cleaned
    assert cleaned == valid


def test_sanitize_json_markers_strips_leading_whitespace():
    """
    Tests that surrounding whitespace is stripped so downstream JSON
    parsing is not broken by leading newlines.
    """
    assert sanitize_json_markers('\n  {"tool_calls": []}  \n') == '{"tool_calls": []}'


def test_sanitize_json_markers_no_change_for_clean_text():
    """
    Tests that text without markers passes through unchanged.
    """
    text = '{"tool_calls": []}'
    assert sanitize_json_markers(text) == text


def test_invoke_sanitizes_plain_string():
    """
    Tests the module's Invoke entry point with a plain string input.
    """
    result = Invoke('__WILMER_L_CURLY__"tool_calls": []__WILMER_R_CURLY__')
    assert result == '{"tool_calls": []}'


def test_invoke_aggregates_generator_input_before_sanitizing():
    """
    Tests that a generator input (from an upstream streaming node) is
    aggregated to a string before sanitization.
    """
    # Arrange: Generator yielding the response in chunks.
    def response_chunks():
        yield '__WILMER_L_CURLY__"tool_calls"'
        yield ': []__WILMER_R_CURLY__'

    # Act
    result = Invoke(response_chunks())

    # Assert
    assert result == '{"tool_calls": []}'


def test_invoke_returns_empty_string_for_invalid_input():
    """
    Tests that non-string, non-generator input results in an empty string
    rather than an exception.
    """
    assert Invoke(None) == ""
    assert Invoke(12345) == ""
