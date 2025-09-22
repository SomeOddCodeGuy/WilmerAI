# Tests/utilities/test_prompt_manipulation_utils.py

import pytest

from Middleware.utilities.prompt_manipulation_utils import (
    combine_initial_system_prompts,
    get_messages_within_index,
    reduce_messages_down_to_wilmer_acceptable_length,
    reduce_messages_to_fit_token_limit
)

# A common fixture for conversation history used across multiple tests
MESSAGES_FIXTURE = [
    {'role': 'system', 'content': 'You are a helpful assistant.'},
    {'role': 'system', 'content': 'Your name is Wilmer.'},
    {'role': 'user', 'content': 'Hello, who are you?'},
    {'role': 'assistant', 'content': 'I am Wilmer, a helpful assistant.'},
    {'role': 'user', 'content': 'What can you do?'},
    {'role': 'assistant', 'content': 'I can answer questions.'}
]


class TestCombineInitialSystemPrompts:
    """Tests for the combine_initial_system_prompts function."""

    def test_combines_multiple_initial_system_prompts(self):
        """Should concatenate multiple consecutive system prompts at the beginning."""
        messages = [
            {'role': 'system', 'content': 'First part.'},
            {'role': 'system', 'content': 'Second part.'},
            {'role': 'user', 'content': 'User message.'}
        ]
        result = combine_initial_system_prompts(messages, "", "")
        assert result == "First part. Second part."

    def test_handles_single_initial_system_prompt(self):
        """Should handle a single system prompt correctly."""
        messages = [
            {'role': 'system', 'content': 'The only system prompt.'},
            {'role': 'user', 'content': 'User message.'}
        ]
        result = combine_initial_system_prompts(messages, "", "")
        assert result == "The only system prompt."

    def test_returns_empty_if_no_initial_system_prompts(self):
        """Should return an empty string (plus pre/suffix) if the conversation starts with a user."""
        messages = [
            {'role': 'user', 'content': 'User message.'},
            {'role': 'system', 'content': 'This should be ignored.'}
        ]
        result = combine_initial_system_prompts(messages, "PRE>", "<SUF")
        assert result == "PRE><SUF"

    def test_ignores_system_prompt_after_user_prompt(self):
        """Should not include a system prompt that appears after a user message."""
        messages = [
            {'role': 'system', 'content': 'Initial prompt.'},
            {'role': 'user', 'content': 'User message.'},
            {'role': 'system', 'content': 'This should be ignored.'}
        ]
        result = combine_initial_system_prompts(messages, "", "")
        assert result == "Initial prompt."

    def test_handles_empty_message_list(self):
        """Should return just the prefix and suffix for an empty list."""
        result = combine_initial_system_prompts([], "PRE>", "<SUF")
        assert result == "PRE><SUF"

    def test_applies_prefix_and_suffix_correctly(self):
        """Should correctly prepend the prefix and append the suffix."""
        messages = [{'role': 'system', 'content': 'System message.'}]
        result = combine_initial_system_prompts(messages, "START_BLOCK\n", "\nEND_BLOCK")
        assert result == "START_BLOCK\nSystem message.\nEND_BLOCK"


class TestGetMessagesWithinIndex:
    """Tests for the get_messages_within_index function."""

    @pytest.mark.parametrize("index_count, expected_length, expected_first_content", [
        (3, 3, 'Hello, who are you?'),
        (1, 1, 'What can you do?'),
        (10, 5, 'You are a helpful assistant.'),
        (5, 5, 'You are a helpful assistant.'),
    ])
    def test_retrieves_correct_subset(self, index_count, expected_length, expected_first_content):
        """Should retrieve the correct number of recent messages, excluding the last one."""
        subset = get_messages_within_index(MESSAGES_FIXTURE, index_count)
        assert len(subset) == expected_length
        assert subset[0]['content'] == expected_first_content
        assert subset[-1]['content'] == 'What can you do?'

    @pytest.mark.parametrize("index_count", [0, -1, -100])
    def test_returns_empty_list_for_zero_or_negative_index(self, index_count):
        """Should return an empty list if index_count is not a positive integer."""
        subset = get_messages_within_index(MESSAGES_FIXTURE, index_count)
        assert subset == []

    def test_handles_short_list(self):
        """Should correctly handle lists shorter than the index count."""
        short_list = [{'role': 'user', 'content': 'Hello'}, {'role': 'assistant', 'content': 'Hi'}]
        subset = get_messages_within_index(short_list, 5)
        assert len(subset) == 1
        assert subset[0]['content'] == 'Hello'

    def test_handles_single_message_list(self):
        """Should return an empty list when there is only one message."""
        single_message_list = [{'role': 'user', 'content': 'Hello'}]
        subset = get_messages_within_index(single_message_list, 1)
        assert subset == []

    def test_handles_empty_list(self):
        """Should return an empty list if the input list is empty."""
        subset = get_messages_within_index([], 5)
        assert subset == []


class TestReduceMessagesToFitTokenLimit:
    """Tests for the reduce_messages_to_fit_token_limit function."""

    def test_all_messages_fit(self, mocker):
        """Should return the original list if total tokens are under the limit."""
        mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [{'role': 'user', 'content': 'a'}, {'role': 'assistant', 'content': 'b'}]
        system_prompt = "system"
        result = reduce_messages_to_fit_token_limit(system_prompt, messages, 100)
        assert result == messages

    def test_some_messages_fit(self, mocker):
        """Should return the most recent messages that fit within the token limit."""
        token_estimates = {
            "System instruction": 50,
            "Old message": 20,
            "Recent message": 30,
            "Latest message": 25,
        }
        mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.rough_estimate_token_length',
            side_effect=lambda text: token_estimates[text]
        )
        system_prompt = "System instruction"
        messages = [
            {'role': 'user', 'content': 'Old message'},
            {'role': 'assistant', 'content': 'Recent message'},
            {'role': 'user', 'content': 'Latest message'}
        ]
        max_tokens = 105

        result = reduce_messages_to_fit_token_limit(system_prompt, messages, max_tokens)

        assert len(result) == 2
        assert result[0]['content'] == 'Recent message'
        assert result[1]['content'] == 'Latest message'

    def test_no_messages_fit(self, mocker):
        """Should return an empty list if no messages can fit with the system prompt."""
        mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.rough_estimate_token_length',
            return_value=50
        )
        system_prompt = "system"
        messages = [{'role': 'user', 'content': 'message'}]
        result = reduce_messages_to_fit_token_limit(system_prompt, messages, 99)
        assert result == []

    def test_system_prompt_alone_exceeds_limit(self, mocker):
        """Should return an empty list if the system prompt itself is over the limit."""
        mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.rough_estimate_token_length',
            return_value=100
        )
        system_prompt = "very long system prompt"
        messages = [{'role': 'user', 'content': 'message'}]
        result = reduce_messages_to_fit_token_limit(system_prompt, messages, 99)
        assert result == []

    def test_handles_empty_messages_list(self, mocker):
        """Should return an empty list when given an empty list of messages."""
        mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.rough_estimate_token_length',
            return_value=10
        )
        result = reduce_messages_to_fit_token_limit("system", [], 100)
        assert result == []


class TestReduceMessagesDownToWilmerAcceptableLength:
    """Tests for the reduce_messages_down_to_wilmer_acceptable_length wrapper function."""

    def test_truncation_is_applied_when_conditions_met(self, mocker):
        """Should calculate a new token limit and call the reduction function."""
        mock_reduce = mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.reduce_messages_to_fit_token_limit'
        )
        mock_reduce.return_value = [{'role': 'user', 'content': 'reduced'}]

        system_prompt = "system"
        messages = [{'role': 'user', 'content': 'original'}]
        truncate_length = 2000
        max_new_tokens = 500

        expected_new_limit = 1200

        result = reduce_messages_down_to_wilmer_acceptable_length(
            system_prompt, messages, truncate_length, max_new_tokens
        )

        mock_reduce.assert_called_once_with(system_prompt, messages, expected_new_limit)

        assert result == [{'role': 'user', 'content': 'reduced'}]

    @pytest.mark.parametrize("truncate_length, max_new_tokens", [
        (1000, 1000),
        (1000, 1200),
        (1000, 0),
        (1000, -100),
        (0, 500)
    ])
    def test_no_truncation_when_conditions_not_met(self, mocker, truncate_length, max_new_tokens):
        """Should return the original messages without modification if conditions aren't met."""
        mock_reduce = mocker.patch(
            'Middleware.utilities.prompt_manipulation_utils.reduce_messages_to_fit_token_limit'
        )

        system_prompt = "system"
        original_messages = [{'role': 'user', 'content': 'original'}]

        result = reduce_messages_down_to_wilmer_acceptable_length(
            system_prompt, original_messages, truncate_length, max_new_tokens
        )

        mock_reduce.assert_not_called()

        assert result == original_messages
