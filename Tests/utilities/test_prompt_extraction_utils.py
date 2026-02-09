# Tests/utilities/test_prompt_extraction_utils.py

import pytest

from Middleware.utilities.prompt_extraction_utils import (
    extract_last_n_turns,
    extract_last_n_turns_as_string,
    extract_last_turns_by_estimated_token_limit,
    extract_last_turns_by_estimated_token_limit_as_string,
    extract_last_turns_with_min_messages_and_token_limit,
    extract_last_turns_with_min_messages_and_token_limit_as_string,
    extract_discussion_id,
    remove_discussion_id_tag,
    remove_discussion_id_tag_from_string,
    separate_messages,
    parse_conversation,
    extract_initial_system_prompt,
    process_remaining_string,
    template
)

# Test Data
MESSAGES_FIXTURE = [
    {'role': 'system', 'content': 'Initial System Prompt.'},
    {'role': 'user', 'content': 'Hello'},
    {'role': 'assistant', 'content': 'Hi there!'},
    {'role': 'images', 'content': 'image_data_here'},
    {'role': 'system', 'content': 'Mid-conversation System Prompt.'},
    {'role': 'user', 'content': 'How are you?'},
    {'role': 'assistant', 'content': 'I am well.'}
]


class TestExtractLastNTurns:
    """Tests for the extract_last_n_turns function."""

    @pytest.mark.parametrize(
        "n, include_sysmes, remove_all_systems, expected_indices",
        [
            # Basic cases
            (3, True, False, [3, 4, 5]),  # Gets last 3 non-image, includes mid-convo system
            (5, True, False, [1, 2, 3, 4, 5]),  # Gets last 5, excludes leading system
            (10, True, False, [1, 2, 3, 4, 5]),  # n > messages, gets all non-leading-system
            (2, False, False, [4, 5]),  # n=2, exclude all system messages
            (4, False, False, [1, 2, 4, 5]),  # n=4, exclude all system messages
            (2, True, True, [4, 5]),  # remove_all_systems override ignores include_sysmes
            (1, True, False, [5]),  # Get just the last message
            (0, True, False, []),  # Get zero messages
        ],
        ids=[
            "n=3_include_sysmes",
            "n=5_include_sysmes_strips_leading",
            "n_greater_than_messages",
            "n=2_exclude_sysmes",
            "n=4_exclude_sysmes",
            "remove_all_systems_override",
            "get_last_one",
            "get_zero"
        ]
    )
    def test_extract_last_n_turns(self, n, include_sysmes, remove_all_systems, expected_indices):
        """
        Tests various scenarios for slicing the last N turns from a conversation,
        including handling of system and image messages.
        """
        # Filter out the image message for expected result comparison as the function does
        expected_messages = [msg for msg in MESSAGES_FIXTURE if msg['role'] != 'images']
        expected = [expected_messages[i] for i in expected_indices]

        result = extract_last_n_turns(MESSAGES_FIXTURE, n, include_sysmes, remove_all_systems)
        assert result == expected

    def test_extract_from_empty_list(self):
        """Tests that an empty message list returns an empty list."""
        assert extract_last_n_turns([], 5) == []


class TestExtractLastNTurnsAsString:
    """Tests for the extract_last_n_turns_as_string function."""

    def test_extract_as_string_success(self, mocker):
        """
        Verifies that the function calls the extractor and joins the content correctly.
        """
        # Arrange
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_n_turns',
            return_value=[
                {'role': 'user', 'content': 'Line 1'},
                {'role': 'assistant', 'content': 'Line 2'}
            ]
        )
        # Act
        result = extract_last_n_turns_as_string(MESSAGES_FIXTURE, 2)
        # Assert
        assert result == "Line 1\nLine 2"

    def test_extract_as_string_empty_list(self):
        """Tests that an empty message list returns an empty string."""
        assert extract_last_n_turns_as_string([], 5) == ""


class TestExtractLastTurnsByEstimatedTokenLimit:
    """Tests for the token-limited message extraction functions."""

    def test_basic_extraction_within_budget(self, mocker):
        """Tests that messages fitting within the token budget are all returned."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: len(text)  # Simple: 1 token per char
        )
        messages = [
            {'role': 'user', 'content': 'short'},       # 5 tokens
            {'role': 'assistant', 'content': 'also'},    # 4 tokens
            {'role': 'user', 'content': 'hi'},           # 2 tokens
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 20)
        assert len(result) == 3
        assert result[0]['content'] == 'short'
        assert result[2]['content'] == 'hi'

    def test_extraction_stops_at_budget(self, mocker):
        """Tests that extraction stops when adding the next message would exceed the budget."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 100, 'msg3': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # Budget of 200: msg3 (100) + msg2 (100) = 200, msg1 would make 300
        result = extract_last_turns_by_estimated_token_limit(messages, 200)
        assert len(result) == 2
        assert result[0]['content'] == 'msg2'
        assert result[1]['content'] == 'msg3'

    def test_always_includes_at_least_one_message(self, mocker):
        """Tests that at least one message is returned even if it exceeds the budget."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10000
        )
        messages = [
            {'role': 'user', 'content': 'very long message'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 50)
        assert len(result) == 1
        assert result[0]['content'] == 'very long message'

    def test_at_least_one_when_most_recent_exceeds_budget(self, mocker):
        """Tests that only the most recent message is returned when it alone exceeds the budget."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'small': 10, 'huge': 6000}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'small'},
            {'role': 'assistant', 'content': 'huge'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 5000)
        assert len(result) == 1
        assert result[0]['content'] == 'huge'

    def test_empty_messages_returns_empty(self):
        """Tests that an empty message list returns an empty list."""
        assert extract_last_turns_by_estimated_token_limit([], 1000) == []

    def test_images_role_excluded(self, mocker):
        """Tests that messages with role 'images' are filtered out."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'hello'},
            {'role': 'images', 'content': 'image_data'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000)
        assert len(result) == 2
        assert all(m['role'] != 'images' for m in result)

    def test_system_messages_excluded_when_include_sysmes_false(self, mocker):
        """Tests that system messages are excluded when include_sysmes is False."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys prompt'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'system', 'content': 'mid sys'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000, include_sysmes=False)
        assert all(m['role'] != 'system' for m in result)
        assert len(result) == 2

    def test_remove_all_systems_override(self, mocker):
        """Tests that remove_all_systems_override removes all system messages."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys1'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'system', 'content': 'sys2'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_by_estimated_token_limit(
            messages, 1000, include_sysmes=True, remove_all_systems_override=True
        )
        assert all(m['role'] != 'system' for m in result)
        assert len(result) == 2

    def test_chronological_order_preserved(self, mocker):
        """Tests that returned messages are in chronological order."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'second'},
            {'role': 'user', 'content': 'third'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000)
        assert [m['content'] for m in result] == ['first', 'second', 'third']


class TestExtractLastTurnsByEstimatedTokenLimitAsString:
    """Tests for the string version of token-limited extraction."""

    def test_returns_newline_joined_content(self, mocker):
        """Tests that extracted messages are joined with newlines."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_by_estimated_token_limit',
            return_value=[
                {'role': 'user', 'content': 'Line 1'},
                {'role': 'assistant', 'content': 'Line 2'}
            ]
        )
        result = extract_last_turns_by_estimated_token_limit_as_string(
            [{'role': 'user', 'content': 'dummy'}], 1000
        )
        assert result == "Line 1\nLine 2"

    def test_empty_messages_returns_empty_string(self):
        """Tests that an empty message list returns an empty string."""
        assert extract_last_turns_by_estimated_token_limit_as_string([], 1000) == ""


class TestDiscussionIdFunctions:
    """Tests for discussion ID extraction and removal."""

    def test_extract_discussion_id_found(self):
        """Tests that a discussion ID is correctly extracted."""
        messages = [{'role': 'user', 'content': 'Hello [DiscussionId]12345[/DiscussionId]'}]
        assert extract_discussion_id(messages) == "12345"

    def test_extract_discussion_id_not_found(self):
        """Tests that None is returned when no ID is found."""
        messages = [{'role': 'user', 'content': 'Hello there'}]
        assert extract_discussion_id(messages) is None

    def test_remove_discussion_id_tag_from_string(self):
        """Tests removing the tag from a single string."""
        content = "Some text [DiscussionId]abc-def[/DiscussionId] more text."
        expected = "Some text  more text."
        assert remove_discussion_id_tag_from_string(content) == expected

    def test_remove_discussion_id_tag_from_messages(self):
        """Tests removing the tag from a list of message dictionaries."""
        messages = [
            {'role': 'user', 'content': 'Message 1 [DiscussionId]xyz[/DiscussionId]'},
            {'role': 'assistant', 'content': 'Message 2'}
        ]
        expected = [
            {'role': 'user', 'content': 'Message 1 '},
            {'role': 'assistant', 'content': 'Message 2'}
        ]
        result = remove_discussion_id_tag(messages)
        assert result == expected


class TestSeparateMessages:
    """Tests for the separate_messages function."""

    def test_separate_sysmes_false(self):
        """Tests default behavior where all system messages are combined."""
        messages = [
            {'role': 'system', 'content': 'Sys1.'},
            {'role': 'user', 'content': 'User1.'},
            {'role': 'system', 'content': 'Sys2.'}
        ]
        system_prompt, conversation = separate_messages(messages, separate_sysmes=False)
        assert system_prompt == "Sys1. Sys2."
        assert conversation == [{'role': 'user', 'content': 'User1.'}]

    def test_separate_sysmes_true(self):
        """Tests behavior where only leading system messages are separated."""
        messages = [
            {'role': 'system', 'content': 'Sys1.'},
            {'role': 'user', 'content': 'User1.'},
            {'role': 'system', 'content': 'Sys2.'}
        ]
        system_prompt, conversation = separate_messages(messages, separate_sysmes=True)
        assert system_prompt == "Sys1."
        assert conversation == [
            {'role': 'user', 'content': 'User1.'},
            {'role': 'system', 'content': 'Sys2.'}
        ]

    def test_missing_key_raises_error(self):
        """Tests that a message missing a required key raises a ValueError."""
        messages = [{'role': 'user'}]  # Missing 'content'
        with pytest.raises(ValueError, match="Message is missing the 'role' or 'content' key."):
            separate_messages(messages)


class TestParseConversation:
    """Tests for the parse_conversation function."""

    @pytest.mark.parametrize("input_str, expected", [
        (
                "[Beg_Sys]You are a bot.[Beg_User]Hello![Beg_Assistant]Hi!",
                [
                    {"role": "system", "content": "You are a bot."},
                    {"role": "user", "content": "Hello!"},
                    {"role": "assistant", "content": "Hi!"}
                ]
        ),
        (
                "[Beg_Sys]First sys.[Beg_Sys]Second sys.[Beg_User]User.",
                [
                    {"role": "system", "content": "First sys."},
                    {"role": "systemMes", "content": "Second sys."},
                    {"role": "user", "content": "User."}
                ]
        ),
        (
                "No tags here.",
                []
        ),
        (
                "",
                []
        ),
    ], ids=["standard", "multiple_system", "no_tags", "empty_string"])
    def test_parse_conversation(self, input_str, expected):
        """Tests parsing of various tagged string formats."""
        assert parse_conversation(input_str) == expected


class TestLegacyParsingHelpers:
    """Tests for extract_initial_system_prompt and process_remaining_string."""

    def test_extract_initial_system_prompt_found(self):
        """Tests extraction when the system prompt tag is present."""
        input_str = "[Beg_Sys]System content.[Beg_User]User content."
        sys_prompt, remaining = extract_initial_system_prompt(input_str, template["Begin_Sys"])
        assert sys_prompt == "System content."
        assert remaining == "[Beg_User]User content."

    def test_extract_initial_system_prompt_not_found(self):
        """Tests extraction when the system prompt tag is not present."""
        input_str = "[Beg_User]User content."
        sys_prompt, remaining = extract_initial_system_prompt(input_str, template["Begin_Sys"])
        assert sys_prompt == ""
        assert remaining == "[Beg_User]User content."

    def test_extract_initial_system_prompt_only_system(self):
        """Tests when the entire string is just the system prompt."""
        input_str = "[Beg_Sys]System content only."
        sys_prompt, remaining = extract_initial_system_prompt(input_str, template["Begin_Sys"])
        assert sys_prompt == "System content only."
        assert remaining == ""

    def test_process_remaining_string(self):
        """Tests the removal of the Begin_Sys tag."""
        input_str = "[Beg_Sys]System stuff to remove. [Beg_User]Keep this."
        expected = "System stuff to remove. [Beg_User]Keep this."
        assert process_remaining_string(input_str, template) == expected


class TestExtractLastTurnsWithMinMessagesAndTokenLimit:
    """Tests for the min-messages + token-limit combo extraction function."""

    def test_min_messages_returned_even_if_exceeds_token_limit(self, mocker):
        """Tests that min_messages are always returned even if their tokens exceed the limit."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 200, 'msg3': 300}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # min_messages=3, token_limit=50: all 3 returned despite exceeding limit
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 3, 50)
        assert len(result) == 3

    def test_expands_beyond_min_when_within_token_budget(self, mocker):
        """Tests that messages beyond min_messages are added while within the token budget."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 100, 'msg3': 100, 'msg4': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
            {'role': 'assistant', 'content': 'msg4'},
        ]
        # min_messages=2, token_limit=500: msg4 (100) + msg3 (100) = 200, then
        # msg2 fits (300), msg1 fits (400), all within 500
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 500)
        assert len(result) == 4

    def test_stops_expansion_when_token_limit_reached(self, mocker):
        """Tests that expansion stops when the next message would exceed the token budget."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 300, 'msg2': 100, 'msg3': 100, 'msg4': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
            {'role': 'assistant', 'content': 'msg4'},
        ]
        # min_messages=2: msg4 (100) + msg3 (100) = 200.
        # token_limit=350: msg2 would make 300, still fits.
        # msg1 would make 600, exceeds 350. Stop.
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 350)
        assert len(result) == 3
        assert result[0]['content'] == 'msg2'
        assert result[1]['content'] == 'msg3'
        assert result[2]['content'] == 'msg4'

    def test_empty_messages_returns_empty(self):
        """Tests that empty messages returns empty list."""
        assert extract_last_turns_with_min_messages_and_token_limit([], 5, 1000) == []

    def test_images_excluded(self, mocker):
        """Tests that messages with role 'images' are filtered out."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'hello'},
            {'role': 'images', 'content': 'image_data'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 1000)
        assert len(result) == 2
        assert all(m['role'] != 'images' for m in result)

    def test_system_messages_excluded_when_include_sysmes_false(self, mocker):
        """Tests that system messages are excluded when include_sysmes is False."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys prompt'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'system', 'content': 'mid sys'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 2, 1000, include_sysmes=False
        )
        assert all(m['role'] != 'system' for m in result)
        assert len(result) == 2

    def test_remove_all_systems_override(self, mocker):
        """Tests that remove_all_systems_override removes all system messages."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys1'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'system', 'content': 'sys2'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 2, 1000, include_sysmes=True, remove_all_systems_override=True
        )
        assert all(m['role'] != 'system' for m in result)
        assert len(result) == 2

    def test_chronological_order_preserved(self, mocker):
        """Tests that returned messages are in chronological order."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'second'},
            {'role': 'user', 'content': 'third'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 1000)
        assert [m['content'] for m in result] == ['first', 'second', 'third']

    def test_fewer_messages_than_min(self, mocker):
        """Tests that all messages are returned when fewer than min_messages exist."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'only one'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 5, 1000)
        assert len(result) == 1
        assert result[0]['content'] == 'only one'

    def test_exact_token_boundary(self, mocker):
        """Tests behavior when the next message would fit exactly at the token limit."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 100, 'msg3': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # min_messages=1: msg3 (100). token_limit=300: msg2 (200) fits, msg1 (300) fits exactly.
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 1, 300)
        assert len(result) == 3


class TestExtractLastTurnsWithMinMessagesAndTokenLimitAsString:
    """Tests for the string version of min-messages + token-limit extraction."""

    def test_returns_newline_joined_content(self, mocker):
        """Tests that extracted messages are joined with newlines."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_with_min_messages_and_token_limit',
            return_value=[
                {'role': 'user', 'content': 'Line 1'},
                {'role': 'assistant', 'content': 'Line 2'}
            ]
        )
        result = extract_last_turns_with_min_messages_and_token_limit_as_string(
            [{'role': 'user', 'content': 'dummy'}], 2, 1000
        )
        assert result == "Line 1\nLine 2"

    def test_empty_messages_returns_empty_string(self):
        """Tests that an empty message list returns an empty string."""
        assert extract_last_turns_with_min_messages_and_token_limit_as_string([], 5, 1000) == ""


class TestTokenLimitEdgeCases:
    """Additional edge case tests for token-limited extraction functions."""

    def test_include_sysmes_true_strips_leading_but_keeps_mid_conversation(self, mocker):
        """Tests that include_sysmes=True strips leading system messages but keeps mid-conversation ones."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'leading system'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'system', 'content': 'mid system'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000, include_sysmes=True)
        assert len(result) == 3
        assert result[0]['content'] == 'hello'
        assert result[1]['content'] == 'mid system'
        assert result[2]['content'] == 'hi'

    def test_token_limit_exact_equality_includes_message(self, mocker):
        """Tests that a message is included when accumulated + message == token_limit exactly."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 100, 'msg3': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # msg3 (100, always included) + msg2 (100) = 200 == limit, should include
        result = extract_last_turns_by_estimated_token_limit(messages, 200)
        assert len(result) == 2
        assert result[0]['content'] == 'msg2'
        assert result[1]['content'] == 'msg3'

    def test_token_limit_zero_returns_only_one_message(self, mocker):
        """Tests that token_limit=0 still returns at least one message."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=50
        )
        messages = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'second'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 0)
        assert len(result) == 1
        assert result[0]['content'] == 'second'

    def test_all_system_messages_with_include_sysmes_false_returns_empty(self, mocker):
        """Tests that all-system-message input with include_sysmes=False returns empty list."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys1'},
            {'role': 'system', 'content': 'sys2'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000, include_sysmes=False)
        assert result == []

    def test_all_image_messages_returns_empty(self, mocker):
        """Tests that all-image-message input returns empty list."""
        messages = [
            {'role': 'images', 'content': 'img1'},
            {'role': 'images', 'content': 'img2'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000)
        assert result == []

    def test_missing_content_key_handled_gracefully(self, mocker):
        """Tests that messages without 'content' key are handled via .get() default."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: 0 if text == '' else 10
        )
        messages = [
            {'role': 'user'},
            {'role': 'assistant', 'content': 'hello'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000)
        assert len(result) == 2

    def test_all_system_messages_with_include_sysmes_true(self, mocker):
        """Tests behavior when all messages are system with include_sysmes=True (default).

        When all messages have role='system', the next() call finds no non-system
        message and defaults to index 0, keeping all messages. This documents
        the current behavior.
        """
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys1'},
            {'role': 'system', 'content': 'sys2'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000, include_sysmes=True)
        # All system messages are included because the leading-strip logic defaults to index 0
        assert len(result) == 2

    def test_empty_string_content_counts_as_zero_tokens(self, mocker):
        """Tests that empty content messages count as zero tokens."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: 0 if text == '' else 100
        )
        messages = [
            {'role': 'user', 'content': ''},
            {'role': 'assistant', 'content': ''},
            {'role': 'user', 'content': 'real content'},
        ]
        # Budget is 150: real content (100) + '' (0) + '' (0) = 100, all fit
        result = extract_last_turns_by_estimated_token_limit(messages, 150)
        assert len(result) == 3


class TestComboExtractionEdgeCases:
    """Additional edge case tests for min-messages + token-limit combo extraction."""

    def test_include_sysmes_true_strips_leading_but_keeps_mid_conversation(self, mocker):
        """Tests that include_sysmes=True strips leading system messages but keeps mid-conversation ones."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'leading system'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'system', 'content': 'mid system'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 2, 1000, include_sysmes=True
        )
        assert len(result) == 3
        assert result[0]['content'] == 'hello'
        assert result[1]['content'] == 'mid system'
        assert result[2]['content'] == 'hi'

    def test_min_messages_exactly_equals_available(self, mocker):
        """Tests that when min_messages equals available messages, all are returned and phase 2 is skipped."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'second'},
            {'role': 'user', 'content': 'third'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 3, 1000)
        assert len(result) == 3
        assert result[0]['content'] == 'first'

    def test_min_messages_zero_with_budget_too_small(self, mocker):
        """Tests that min_messages=0 can result in no messages if budget is too small."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=100
        )
        messages = [
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        # min_messages=0, token_limit=10: phase 1 never runs, phase 2 can't fit 100-token message
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 0, 10)
        assert result == []

    def test_min_messages_zero_with_sufficient_budget(self, mocker):
        """Tests that min_messages=0 with sufficient budget returns messages based on tokens only."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=50
        )
        messages = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'second'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 0, 200)
        assert len(result) == 2

    def test_min_messages_one_with_token_expansion(self, mocker):
        """Tests min_messages=1 with budget allowing expansion to more messages."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 50, 'msg2': 50, 'msg3': 50}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # min=1 (msg3=50), budget=200: msg2 (100) fits, msg1 (150) fits
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 1, 200)
        assert len(result) == 3

    def test_phase2_token_limit_zero_returns_only_min_messages(self, mocker):
        """Tests that token_limit=0 after phase 1 returns exactly min_messages."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=100
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
            {'role': 'assistant', 'content': 'msg4'},
        ]
        # min=2, token_limit=0: phase 1 gets msg4+msg3 (200 tokens), phase 2 can't add anything
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 0)
        assert len(result) == 2
        assert result[0]['content'] == 'msg3'
        assert result[1]['content'] == 'msg4'

    def test_min_floor_override_verifies_actual_content(self, mocker):
        """Tests that min_messages override returns the correct messages in order."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'first': 100, 'second': 200, 'third': 300}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'second'},
            {'role': 'user', 'content': 'third'},
        ]
        # min=3, token_limit=50: all 3 returned despite 600 tokens > 50
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 3, 50)
        assert len(result) == 3
        assert result[0]['content'] == 'first'
        assert result[1]['content'] == 'second'
        assert result[2]['content'] == 'third'

    def test_all_system_messages_include_sysmes_false_returns_empty(self, mocker):
        """Tests that all-system-messages with include_sysmes=False returns empty."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'system', 'content': 'sys1'},
            {'role': 'system', 'content': 'sys2'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 5, 1000, include_sysmes=False
        )
        assert result == []

    def test_missing_content_key_handled_gracefully(self, mocker):
        """Tests that messages without 'content' key use default empty string."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: 0 if text == '' else 10
        )
        messages = [
            {'role': 'user'},
            {'role': 'assistant', 'content': 'hello'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 1000)
        assert len(result) == 2
