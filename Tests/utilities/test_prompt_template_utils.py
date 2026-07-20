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
    {"role": "user", "content": "Look at this", "images": ["base64_image_data"]},
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
        # The token-budget selectors live in prompt_extraction_utils; patching there
        # controls the estimates for the get_formatted_last_turns_* delegation paths.
        'estimate_tokens': mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length'),
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
    but tags are still stripped. Messages with 'images' key are preserved.
    """
    messages = [
        {"role": "user", "content": "Hello [Beg_User]", "images": ["imageData"]},
        {"role": "assistant", "content": "Hi"}
    ]

    result = prompt_template_utils.format_messages_with_template(messages, "any_template.json", isChatCompletion=True)

    mock_dependencies['load_template'].assert_called_once_with('any_template.json')

    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "Hello "
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

    mock_dependencies['load_template'].assert_called_once_with("test_template.json")

    assert len(result) == 2
    assert result[0]["content"] == "<USER>Hello</USER>"
    # Last assistant message should NOT have a suffix
    assert result[1]["content"] == "<ASST>Hi there"


def test_format_messages_with_template_suffix_present_when_last_is_user(mock_dependencies):
    """
    The suffix-omission special case applies only when the LAST message is an
    assistant turn. When the conversation ends in a user message, every message
    (including the final user turn) keeps its suffix.
    """
    messages = [
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "Hello"},
    ]

    result = prompt_template_utils.format_messages_with_template(messages, "test_template.json",
                                                                 isChatCompletion=False)

    # The assistant turn is not last, so it keeps its suffix too.
    assert result[0]["content"] == "<ASST>Hi there</ASST>"
    assert result[1]["content"] == "<USER>Hello</USER>"


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


def test_format_assistant_turn_with_template_chat(mock_dependencies):
    """For chat completions the assistant formatter only strips tags: no prefix
    is applied and the template file is never loaded."""
    result = prompt_template_utils.format_assistant_turn_with_template(
        "reply [Beg_Assistant]", "template.json", isChatCompletion=True)
    assert result == "reply "
    mock_dependencies['load_template'].assert_not_called()


def test_format_system_prompt_with_template_chat(mock_dependencies):
    """For chat completions the system formatter only strips tags: no
    prefix/suffix is applied and the template file is never loaded."""
    result = prompt_template_utils.format_system_prompt_with_template(
        "[Beg_Sys]be helpful", "template.json", isChatCompletion=True)
    assert result == "be helpful"
    mock_dependencies['load_template'].assert_not_called()


## Test for add_assistant_end_token_to_user_turn

def test_add_assistant_end_token_to_user_turn(mock_dependencies):
    """Tests adding the assistant prefix and end token for completions."""
    result = prompt_template_utils.add_assistant_end_token_to_user_turn("user text", "template.json",
                                                                        isChatCompletion=False)
    expected = "user text<ASST><END>"
    assert result == expected


def test_add_assistant_end_token_to_user_turn_chat(mock_dependencies):
    """For chat completions no end token is appended: tags are stripped and the
    template file is never loaded."""
    result = prompt_template_utils.add_assistant_end_token_to_user_turn(
        "user text [Beg_User]", "template.json", isChatCompletion=True)
    assert result == "user text "
    mock_dependencies['load_template'].assert_not_called()


## Tests for format_templated_prompt

def test_format_templated_prompt_completions_mode(mock_dependencies, mock_llm_handler):
    """format_templated_prompt applies the user-turn template when the handler
    does not take a message collection (completions mode)."""
    mock_llm_handler.takes_message_collection = False
    result = prompt_template_utils.format_templated_prompt(
        "some prompt", mock_llm_handler, "template.json")
    assert result == "<USER>some prompt</USER>"


def test_format_templated_prompt_chat_mode(mock_dependencies, mock_llm_handler):
    """format_templated_prompt passes the text through (tags stripped only)
    when the handler takes a message collection (chat mode)."""
    mock_llm_handler.takes_message_collection = True
    result = prompt_template_utils.format_templated_prompt(
        "some prompt [Beg_User]", mock_llm_handler, "template.json")
    assert result == "some prompt "
    mock_dependencies['load_template'].assert_not_called()


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
    Tests the main orchestrator function `format_system_prompts`, including the
    name-to-output-key wiring: the chat template name must drive the chat_* keys
    and the handler's prompt_template_file_name must drive the templated_* keys.
    """
    # Setup mocks
    other_messages = [{"role": "user", "content": "user prompt"}]
    mock_dependencies['separate_messages'].return_value = ("system prompt", other_messages)
    mock_message_formatter = mocker.patch(
        'Middleware.utilities.prompt_template_utils.format_messages_with_template', side_effect=[
            [{"role": "user", "content": "formatted chat prompt"}],
            [{"role": "user", "content": "formatted template prompt"}]
        ])
    mock_system_formatter = mocker.patch(
        'Middleware.utilities.prompt_template_utils.format_templated_system_prompt', side_effect=[
            "formatted chat system",
            "formatted template system"
        ])

    result = prompt_template_utils.format_system_prompts([], mock_llm_handler, "chat_template.json")

    # First formatter call must receive the chat template name, second the
    # handler's own prompt_template_file_name; both get the non-system messages.
    assert mock_message_formatter.call_args_list[0].args == (
        other_messages, "chat_template.json", mock_llm_handler.takes_message_collection)
    assert mock_message_formatter.call_args_list[1].args == (
        other_messages, "test_template.json", mock_llm_handler.takes_message_collection)

    # The system prompt formatter mirrors the same wiring.
    assert mock_system_formatter.call_args_list[0].args == (
        "system prompt", mock_llm_handler, "chat_template.json")
    assert mock_system_formatter.call_args_list[1].args == (
        "system prompt", mock_llm_handler, "test_template.json")

    assert result["chat_system_prompt"] == "formatted chat system"
    assert result["templated_system_prompt"] == "formatted template system"
    assert result["chat_user_prompt_without_system"] == "formatted chat prompt"
    assert result["templated_user_prompt_without_system"] == "formatted template prompt"


def test_format_system_prompts_filters_system_role_from_user_prompts(mocker, mock_dependencies, mock_llm_handler):
    """
    System-role messages returned by the formatter must not leak into the
    *_user_prompt_without_system outputs.
    """
    mock_dependencies['separate_messages'].return_value = (
        "system prompt", [{"role": "user", "content": "user prompt"}])
    mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template', side_effect=[
        [{"role": "system", "content": "CHAT_SYS_LEAK"},
         {"role": "user", "content": "formatted chat prompt"}],
        [{"role": "system", "content": "TEMPLATE_SYS_LEAK"},
         {"role": "user", "content": "formatted template prompt"}]
    ])
    mocker.patch('Middleware.utilities.prompt_template_utils.format_templated_system_prompt', side_effect=[
        "formatted chat system",
        "formatted template system"
    ])

    result = prompt_template_utils.format_system_prompts([], mock_llm_handler, "chat_template.json")

    assert result["chat_user_prompt_without_system"] == "formatted chat prompt"
    assert "CHAT_SYS_LEAK" not in result["chat_user_prompt_without_system"]
    assert result["templated_user_prompt_without_system"] == "formatted template prompt"
    assert "TEMPLATE_SYS_LEAK" not in result["templated_user_prompt_without_system"]


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
        {"role": "user", "content": "turn 3", "images": ["image"]},
        {"role": "user", "content": "turn 4"},
    ]

    # Mock the formatter
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [
        {"content": "formatted turn 3"},
        {"content": "formatted turn 4"},
    ]

    result = prompt_template_utils.get_formatted_last_n_turns_as_string(messages_with_sys, 2, "template.json", False)

    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 2
    assert formatter_call_args[0]['content'] == 'turn 3'
    assert formatter_call_args[1]['content'] == 'turn 4'

    assert result == "formatted turn 3formatted turn 4"


## Tests for get_formatted_last_turns_by_estimated_token_limit_as_string

def test_get_formatted_last_turns_by_estimated_token_limit_basic(mocker, mock_dependencies):
    """
    Tests that messages are selected by token budget, formatted, and concatenated.
    """
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
    ]

    # Each turn is 50 tokens, budget is 120
    # So turn 3 (50) + turn 2 (50) = 100, turn 1 (50) would make 150 > 120
    mock_dependencies['estimate_tokens'].side_effect = lambda text: 50

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [
        {"content": "formatted turn 2"},
        {"content": "formatted turn 3"},
    ]

    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        messages, 120, "template.json", False
    )

    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 2
    assert formatter_call_args[0]['content'] == 'turn 2'
    assert formatter_call_args[1]['content'] == 'turn 3'
    assert result == "formatted turn 2formatted turn 3"


def test_get_formatted_last_turns_by_estimated_token_limit_at_least_one(mocker, mock_dependencies):
    """
    Tests that at least one message is returned even if it exceeds the token budget.
    """
    messages = [
        {"role": "user", "content": "huge message"},
    ]

    mock_dependencies['estimate_tokens'].return_value = 10000

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "formatted huge"}]

    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        messages, 50, "template.json", False
    )

    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 1
    assert result == "formatted huge"


def test_get_formatted_last_turns_by_estimated_token_limit_empty(mock_dependencies):
    """Tests that an empty message list returns an empty string."""
    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        [], 1000, "template.json", False
    )
    assert result == ""


def test_get_formatted_last_turns_by_estimated_token_limit_only_system(mock_dependencies):
    """Tests that a list with only system messages returns an empty string."""
    messages = [
        {"role": "system", "content": "sys"},
    ]
    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        messages, 1000, "template.json", False
    )
    assert result == ""


def test_get_formatted_token_limit_exact_boundary(mocker, mock_dependencies):
    """Tests that token limit exact equality includes the message."""
    messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
    ]
    # Each message is 50 tokens, budget is 100: turn 3 (50) + turn 2 (50) = 100 == limit
    mock_dependencies['estimate_tokens'].side_effect = lambda text: 50

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f2"}, {"content": "f3"}]

    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        messages, 100, "template.json", False
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 2


def test_get_formatted_token_limit_does_not_mutate_originals(mock_dependencies):
    """Tests that the original messages survive the full select-and-format path.

    Runs the REAL format_messages_with_template (which owns the copy-before-mutate
    responsibility) with a template whose prefixes rewrite every content string, so
    a regression that drops the formatter's internal deepcopy fails here.
    """
    from copy import deepcopy
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    original_copy = deepcopy(messages)
    mock_dependencies['estimate_tokens'].return_value = 10

    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        messages, 1000, "template.json", False
    )
    assert "<USER>hello</USER>" in result
    assert messages == original_copy


## Tests for get_formatted_last_turns_with_min_messages_and_token_limit_as_string

def test_get_formatted_combo_basic(mocker, mock_dependencies):
    """Tests basic operation of the min-messages + token-limit formatted function."""
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
    ]
    # min_messages=1, budget=120, each 50 tokens
    # Phase 1: turn 3 (50). Phase 2: turn 2 (100) fits, turn 1 (150 > 120) stops
    mock_dependencies['estimate_tokens'].return_value = 50

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f2"}, {"content": "f3"}]

    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 1, 120, "template.json", False
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 2
    assert result == "f2f3"


def test_get_formatted_combo_empty_input(mock_dependencies):
    """Tests that an empty message list returns an empty string."""
    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        [], 5, 1000, "template.json", False
    )
    assert result == ""


def test_get_formatted_combo_all_system(mock_dependencies):
    """Tests that all system messages returns empty string."""
    messages = [
        {"role": "system", "content": "sys"},
    ]
    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 5, 1000, "template.json", False
    )
    assert result == ""


def test_get_formatted_combo_min_messages_exceeds_available(mocker, mock_dependencies):
    """Tests that when min_messages exceeds available, all messages are returned."""
    messages = [
        {"role": "user", "content": "only one"},
    ]
    mock_dependencies['estimate_tokens'].return_value = 10

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "formatted one"}]

    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 10, 1000, "template.json", False
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 1
    assert result == "formatted one"


def test_get_formatted_combo_min_floor_overrides_token_ceiling(mocker, mock_dependencies):
    """Tests that min_messages floor takes precedence over token ceiling."""
    messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
    ]
    # Each is 500 tokens, min=3, budget=100: all 3 returned despite 1500 > 100
    mock_dependencies['estimate_tokens'].return_value = 500

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f1"}, {"content": "f2"}, {"content": "f3"}]

    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 3, 100, "template.json", False
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 3


def test_get_formatted_combo_does_not_mutate_originals(mock_dependencies):
    """Tests that the original messages survive the full select-and-format path.

    Runs the REAL format_messages_with_template (which owns the copy-before-mutate
    responsibility) with a template whose prefixes rewrite every content string, so
    a regression that drops the formatter's internal deepcopy fails here.
    """
    from copy import deepcopy
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    original_copy = deepcopy(messages)
    mock_dependencies['estimate_tokens'].return_value = 10

    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 1, 1000, "template.json", False
    )
    assert "<USER>hello</USER>" in result
    assert messages == original_copy


def test_get_formatted_combo_token_expansion_stops(mocker, mock_dependencies):
    """Tests that expansion beyond min_messages stops when token budget exceeded."""
    messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
        {"role": "assistant", "content": "turn 4"},
    ]
    mock_dependencies['estimate_tokens'].return_value = 50

    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f3"}, {"content": "f4"}]
    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 2, 120, "template.json", False
    )
    # min=2: turn 4 (50) + turn 3 (50) = 100. Phase 2: turn 2 (50) = 150 > 120, stop.
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 2


def test_get_formatted_combo_budget_overrides_min_drops_below_floor(mocker, mock_dependencies):
    """With budget_overrides_min=True the min_messages floor yields to the token
    budget: fewer than min_messages are kept when they do not fit."""
    messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
    ]
    # Each 100 tokens, min=3, budget=150. A hard floor keeps all 3; yielding keeps
    # only turn 3 (turn 2 would make 200 > 150).
    mock_dependencies['estimate_tokens'].return_value = 100
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f3"}]
    prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 3, 150, "template.json", False, budget_overrides_min=True
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 1
    assert formatter_call_args[0]['content'] == 'turn 3'


def test_get_formatted_combo_budget_overrides_min_keeps_most_recent(mocker, mock_dependencies):
    """At least the most-recent message is kept even if it alone exceeds the budget."""
    messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
    ]
    mock_dependencies['estimate_tokens'].return_value = 5000
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f2"}]
    prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 2, 100, "template.json", False, budget_overrides_min=True
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 1
    assert formatter_call_args[0]['content'] == 'turn 2'


def test_get_formatted_combo_budget_overrides_min_false_keeps_hard_floor(mocker, mock_dependencies):
    """Regression guard: the default (False) preserves the historical hard floor."""
    messages = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
    ]
    mock_dependencies['estimate_tokens'].return_value = 100
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "f1"}, {"content": "f2"}, {"content": "f3"}]
    prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 3, 150, "template.json", False  # budget_overrides_min defaults to False
    )
    formatter_call_args = mock_formatter.call_args[0][0]
    assert len(formatter_call_args) == 3


## Regression: a tool-calling assistant message has content=None. The token estimate
## must treat it as empty rather than crashing on None.split(). These deliberately use
## the REAL rough_estimate_token_length (not the mocked one) so a regression back to
## message.get("content", "") -> None would actually fail here. This is the exact gap that the
## None-safe fix in prompt_extraction_utils was not originally mirrored into here.

def test_get_formatted_by_token_limit_handles_none_content(mocker):
    """get_formatted_last_turns_by_estimated_token_limit_as_string must not crash on a
    content=None message."""
    messages = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "ls"}}]},
        {"role": "tool", "name": "ls", "content": "file1\nfile2"},
    ]
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "ok"}]

    result = prompt_template_utils.get_formatted_last_turns_by_estimated_token_limit_as_string(
        messages, 1000, "template.json", False
    )
    assert result == "ok"


def test_get_formatted_combo_handles_none_content(mocker):
    """get_formatted_last_turns_with_min_messages_and_token_limit_as_string must not crash
    on a content=None message."""
    messages = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "ls"}}]},
        {"role": "tool", "name": "ls", "content": "result"},
    ]
    mock_formatter = mocker.patch('Middleware.utilities.prompt_template_utils.format_messages_with_template')
    mock_formatter.return_value = [{"content": "ok"}]

    result = prompt_template_utils.get_formatted_last_turns_with_min_messages_and_token_limit_as_string(
        messages, 2, 1000, "template.json", False
    )
    assert result == "ok"
