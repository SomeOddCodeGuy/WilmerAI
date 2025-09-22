# Tests/utilities/test_prompt_extraction_utils.py

import pytest

from Middleware.utilities.prompt_extraction_utils import (
    extract_last_n_turns,
    extract_last_n_turns_as_string,
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
