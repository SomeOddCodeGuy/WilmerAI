# Tests/utilities/test_prompt_template_utils.py

from unittest.mock import MagicMock

import pytest

# The module to be tested
from Middleware.utilities import prompt_template_utils

# Mock template data to be returned by the mocked load_template_from_json
MOCK_TEMPLATE_DATA = {
    "promptTemplateSystemPrefix": "<SYS>",
    "promptTemplateSystemSuffix": "</SYS>",
    "promptTemplateUserPrefix": "<USER>",
    "promptTemplateUserSuffix": "</USER>",
    "promptTemplateAssistantPrefix": "<ASST>",
    "promptTemplateAssistantSuffix": "</ASST>",
    "promptTemplateEndToken": "<END>",
}

# Sample conversation history for testing
SAMPLE_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi there."},
    {"role": "images", "content": "base64_image_data"},
    {"role": "user", "content": "How are you?"}
]


@pytest.fixture
def mock_dependencies(mocker):
    """
    Mocks all external dependencies for prompt_template_utils.
    """
    mocks = {
        'load_template': mocker.patch('Middleware.utilities.prompt_template_utils.load_template_from_json',
                                      return_value=MOCK_TEMPLATE_DATA),
        'separate_messages': mocker.patch('Middleware.utilities.prompt_template_utils.separate_messages'),
        'estimate_tokens': mocker.patch('Middleware.utilities.prompt_template_utils.rough_estimate_token_length'),
    }
    return mocks


@pytest.fixture
def mock_llm_handler():
    """Creates a mock LLM handler object."""
    handler = MagicMock()
    handler.takes_message_collection = False
    handler.prompt_template_file_name = "test_template.json"
    return handler


# # # # # # # # # # # # # # # # # # # # # #
#        Unit Tests Start Here          #
# # # # # # # # # # # # # # # # # # # # # #

## Tests for strip_tags

@pytest.mark.parametrize("input_string, expected_output", [
    ("Hello [Beg_User] some text [Beg_Assistant]", "Hello  some text "),
    ("No tags here", "No tags here"),
    ("[Beg_Sys]System prompt", "System prompt"),
    ("", ""),
    ("[Beg_User][Beg_Assistant]", "")
])
def test_strip_tags(input_string, expected_output):
    """
    Tests that strip_tags correctly removes predefined tags completely.
    """
    assert prompt_template_utils.strip_tags(input_string) == expected_output


## Tests for format_messages_with_template

def test_format_messages_with_template_as_chat_completion(mock_dependencies):
    """
    Tests that when isChatCompletion is True, no template formatting is applied,
    but tags are still stripped and 'images' roles are removed.
    """
    messages = [
        {"role": "user", "content": "Hello [Beg_User]"},
        {"role": "images", "content": "imageData"},
        {"role": "assistant", "content": "Hi"}
    ]

    result = prompt_template_utils.format_messages_with_template(messages, "any_template.json", isChatCompletion=True)

    mock_dependencies['load_template'].assert_called_once_with('any_template.json')

    # Assert 'images' role is filtered out and content is stripped
    assert len(result) == 2
    assert result[0] == {"role": "user", "content": "Hello "}
    assert result[1] == {"role": "assistant", "content": "Hi"}


def test_format_messages_with_template_as_completions_api(mock_dependencies):
    """
    Tests that when isChatCompletion is False, the prompt template is correctly applied.
    It also checks the special case for the last assistant message (no suffix).
    """
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]

    result = prompt_template_utils.format_messages_with_template(messages, "test_template.json", isChatCompletion=False)

    # Assert template was loaded
    mock_dependencies['load_template'].assert_called_once_with("test_template.json")

    # Assert formatting is correct
    assert len(result) == 2
    assert result[0]["content"] == "<USER>Hello</USER>"
    # Last assistant message should NOT have a suffix
    assert result[1]["content"] == "<ASST>Hi there"


def test_format_messages_with_template_handles_missing_template_keys(mock_dependencies):
    """
    Tests graceful handling when a role in the message does not have a corresponding
    prefix/suffix in the template file. It should default to empty strings.
    """
    mock_dependencies['load_template'].return_value = {
        "promptTemplateUserPrefix": "<USER>",
        # Missing other keys
    }
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]

    result = prompt_template_utils.format_messages_with_template(messages, "sparse_template.json",
                                                                 isChatCompletion=False)

    assert result[0]["content"] == "<USER>Hello"
    assert result[1]["content"] == "Hi"


## Tests for format_messages_with_template_as_string

def test_format_messages_with_template_as_string(mocker):
    """
    Tests that the wrapper function correctly calls the formatter and joins the content.
    """
    # Mock the core formatter to control its output
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [
        {"role": "user", "content": "Formatted User"},
        {"role": "assistant", "content": "Formatted Assistant"}
    ]

    result = prompt_template_utils.format_messages_with_template_as_string([], "template.json", False)

    assert result == "Formatted UserFormatted Assistant"
    mock_formatter.assert_called_once()


## Tests for single-turn formatters

@pytest.mark.parametrize("formatter_func, role_key", [
    (prompt_template_utils.format_user_turn_with_template, "User"),
    (prompt_template_utils.format_system_prompt_with_template, "System"),
])
def test_single_turn_formatters_completions(mock_dependencies, formatter_func, role_key):
    """Tests user and system formatters for the completions case."""
    prefix = MOCK_TEMPLATE_DATA[f'promptTemplate{role_key}Prefix']
    suffix = MOCK_TEMPLATE_DATA[f'promptTemplate{role_key}Suffix']
    expected = f"{prefix}test content{suffix}"

    result = formatter_func("test content", "template.json", isChatCompletion=False)

    assert result == expected
    mock_dependencies['load_template'].assert_called_once()


def test_format_assistant_turn_with_template_completions(mock_dependencies):
    """Tests the assistant formatter, which should omit the suffix."""
    prefix = MOCK_TEMPLATE_DATA['promptTemplateAssistantPrefix']
    expected = f"{prefix}test content"

    result = prompt_template_utils.format_assistant_turn_with_template("test content", "template.json",
                                                                       isChatCompletion=False)

    assert result == expected


def test_single_turn_formatters_chat(mock_dependencies):
    """Tests that for chat completions, formatters only strip tags."""
    result = prompt_template_utils.format_user_turn_with_template("hello [Beg_User]", "template.json",
                                                                  isChatCompletion=True)
    assert result == "hello "
    mock_dependencies['load_template'].assert_not_called()


## Test for add_assistant_end_token_to_user_turn

def test_add_assistant_end_token_to_user_turn(mock_dependencies):
    """Tests adding the assistant prefix and end token for completions."""
    result = prompt_template_utils.add_assistant_end_token_to_user_turn("user text", "template.json",
                                                                        isChatCompletion=False)
    expected = "user text<ASST><END>"
    assert result == expected


## Tests for higher-level orchestrators

def test_format_templated_system_prompt(mock_dependencies, mock_llm_handler):
    """
    Tests the wrapper for formatting system prompts based on the llm_handler.
    """
    # Case 1: Chat model
    mock_llm_handler.takes_message_collection = True
    result_chat = prompt_template_utils.format_templated_system_prompt("prompt", mock_llm_handler, "template.json")
    assert result_chat == "prompt"
    mock_dependencies['load_template'].assert_not_called()

    # Case 2: Completions model
    mock_llm_handler.takes_message_collection = False
    result_compl = prompt_template_utils.format_templated_system_prompt("prompt", mock_llm_handler, "template.json")
    assert result_compl == "<SYS>prompt</SYS>"
    mock_dependencies['load_template'].assert_called_once()


def test_format_system_prompts(mocker, mock_dependencies, mock_llm_handler):
    """
    Tests the main orchestrator function `format_system_prompts`.
    """
    # Setup mocks
    mock_dependencies['separate_messages'].return_value = (
        "system prompt", [{"role": "user", "content": "user prompt"}])
    mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template', side_effect=[
        [{"role": "user", "content": "formatted chat prompt"}],
        [{"role": "user", "content": "formatted template prompt"}]
    ])
    mocker.patch('Middleware.utilities.prompt_template_utils.format_templated_system_prompt', side_effect=[
        "formatted chat system",
        "formatted template system"
    ])

    result = prompt_template_utils.format_system_prompts([], mock_llm_handler, "chat_template.json")

    # Assertions
    assert result["chat_system_prompt"] == "formatted chat system"
    assert result["templated_system_prompt"] == "formatted template system"
    assert result["chat_user_prompt_without_system"] == "formatted chat prompt"
    assert result["templated_user_prompt_without_system"] == "formatted template prompt"


## Test for reduce_messages_to_fit_token_limit

def test_reduce_messages_to_fit_token_limit(mock_dependencies):
    """
    Tests that messages are correctly trimmed from the beginning to fit the token limit.
    """
    system_prompt = "system"
    messages = [
        {"role": "user", "content": "msg1"},
        {"role": "user", "content": "msg2"},
        {"role": "user", "content": "msg3"},
    ]
    max_tokens = 100

    # Mock token counts
    mock_dependencies['estimate_tokens'].side_effect = lambda text: {
        "system": 40,
        "msg1": 30,
        "msg2": 30,
        "msg3": 30,
    }.get(text, 0)

    result = prompt_template_utils.reduce_messages_to_fit_token_limit(system_prompt, messages, max_tokens)

    assert len(result) == 2
    assert result[0]['content'] == "msg2"
    assert result[1]['content'] == "msg3"


def test_reduce_messages_all_fit(mock_dependencies):
    """Tests the case where all messages fit within the token limit."""
    system_prompt = "system"
    messages = [{"role": "user", "content": "msg1"}, {"role": "user", "content": "msg2"}]
    max_tokens = 200
    mock_dependencies['estimate_tokens'].return_value = 10

    result = prompt_template_utils.reduce_messages_to_fit_token_limit(system_prompt, messages, max_tokens)

    assert result == messages


## Test for get_formatted_last_n_turns_as_string

def test_get_formatted_last_n_turns_as_string(mocker):
    """
    Tests that the function correctly selects the last N turns, formats them,
    and returns a concatenated string.
    """
    messages_with_sys = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "images", "content": "image"},
        {"role": "user", "content": "turn 3"},
    ]

    # Mock the formatter
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [
        {"content": "formatted turn 2"},
        {"content": "formatted turn 3"},
    ]

    # Get last 2 non-system/image turns
    result = prompt_template_utils.get_formatted_last_n_turns_as_string(messages_with_sys, 2, "template.json", False)

    # Assert the correct slice of messages was passed to the formatter
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 2
    assert formatter_call_args[0]['content'] == 'turn 2'
    assert formatter_call_args[1]['content'] == 'turn 3'

    # Assert the final output is correct
    assert result == "formatted turn 2formatted turn 3"
