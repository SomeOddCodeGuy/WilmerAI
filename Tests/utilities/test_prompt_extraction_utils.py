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
    _format_messages_to_string,
    _summarize_tool_arguments,
    format_tool_calls_as_text,
    enrich_messages_with_tool_calls
)

# Test Data
MESSAGES_FIXTURE = [
    {'role': 'system', 'content': 'Initial System Prompt.'},
    {'role': 'user', 'content': 'Hello'},
    {'role': 'assistant', 'content': 'Hi there!'},
    {'role': 'user', 'content': 'Look at this', 'images': ['image_data_here']},
    {'role': 'system', 'content': 'Mid-conversation System Prompt.'},
    {'role': 'user', 'content': 'How are you?'},
    {'role': 'assistant', 'content': 'I am well.'}
]


class TestExtractLastNTurns:
    """Tests for the extract_last_n_turns function."""

    @pytest.mark.parametrize(
        "n, include_sysmes, remove_all_systems, expected_indices",
        [
            # Basic cases (7 messages total, images are now a key on regular messages)
            (3, True, False, [4, 5, 6]),  # Gets last 3, includes mid-convo system
            (6, True, False, [1, 2, 3, 4, 5, 6]),  # Gets last 6, excludes leading system
            (10, True, False, [1, 2, 3, 4, 5, 6]),  # n > messages, gets all non-leading-system
            (2, False, False, [5, 6]),  # n=2, exclude all system messages
            (5, False, False, [1, 2, 3, 5, 6]),  # n=5, exclude all system messages
            (2, True, True, [5, 6]),  # remove_all_systems override ignores include_sysmes
            (1, True, False, [6]),  # Get just the last message
            (0, True, False, []),  # Get zero messages
        ],
        ids=[
            "n=3_include_sysmes",
            "n=6_include_sysmes_strips_leading",
            "n_greater_than_messages",
            "n=2_exclude_sysmes",
            "n=5_exclude_sysmes",
            "remove_all_systems_override",
            "get_last_one",
            "get_zero"
        ]
    )
    def test_extract_last_n_turns(self, n, include_sysmes, remove_all_systems, expected_indices):
        """
        Tests various scenarios for slicing the last N turns from a conversation.
        Messages with 'images' key are normal messages and participate in turn counting.
        """
        expected = [MESSAGES_FIXTURE[i] for i in expected_indices]

        result = extract_last_n_turns(MESSAGES_FIXTURE, n, include_sysmes, remove_all_systems)
        assert result == expected

    def test_extract_from_empty_list(self):
        """Tests that an empty message list returns an empty list."""
        assert extract_last_n_turns([], 5) == []


class TestExtractLastNTurnsAsString:
    """Tests for the extract_last_n_turns_as_string function."""

    def test_extract_as_string_success(self, mocker):
        """
        Verifies that the function forwards n, include_sysmes, and
        remove_all_systems_override to the extractor and joins the content correctly.
        """
        mock_extract = mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_n_turns',
            return_value=[
                {'role': 'user', 'content': 'Line 1'},
                {'role': 'assistant', 'content': 'Line 2'}
            ]
        )

        result = extract_last_n_turns_as_string(
            MESSAGES_FIXTURE, 2, include_sysmes=False, remove_all_systems_override=True
        )

        assert result == "Line 1\nLine 2"
        mock_extract.assert_called_once_with(MESSAGES_FIXTURE, 2, False, True)

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

    def test_stops_at_first_overflow_does_not_skip_huge_message(self, mocker):
        """The selection loop BREAKS at the first message that overflows the budget:
        an older message that would individually fit is still excluded (the
        documented stop-at-first-overflow contract), keeping the window contiguous."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'small': 10, 'HUGE': 1000, 'recent': 10}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'small'},
            {'role': 'assistant', 'content': 'HUGE'},
            {'role': 'user', 'content': 'recent'},
        ]
        # Budget 100: recent (10) fits; HUGE (1010 total) overflows and stops the loop.
        # small (20 total) would fit if the loop skipped HUGE, but must not be selected.
        result = extract_last_turns_by_estimated_token_limit(messages, 100)
        assert [m['content'] for m in result] == ['recent']

    def test_empty_messages_returns_empty(self):
        """Tests that an empty message list returns an empty list."""
        assert extract_last_turns_by_estimated_token_limit([], 1000) == []

    def test_none_content_does_not_crash(self):
        """A message with content=None (common for tool-call assistant turns) is treated as
        empty rather than crashing the token estimator (uses the real estimator, no mock)."""
        messages = [
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 't1'}]},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 100000)
        assert [m.get('content') for m in result] == ['hello', None]

    def test_messages_with_images_key_included(self, mocker):
        """Tests that messages with 'images' key are included normally."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'hello', 'images': ['image_data']},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000)
        assert len(result) == 2
        assert result[0]['content'] == 'hello'

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

    def test_extract_discussion_id_first_match_wins(self):
        """When multiple messages contain IDs, the first one found is returned."""
        messages = [
            {'role': 'user', 'content': 'no id here'},
            {'role': 'assistant', 'content': '[DiscussionId]first-id[/DiscussionId]'},
            {'role': 'user', 'content': '[DiscussionId]second-id[/DiscussionId]'},
        ]
        assert extract_discussion_id(messages) == "first-id"

    def test_extract_discussion_id_empty_tag_returns_empty_string(self):
        """An empty [DiscussionId][/DiscussionId] pair returns "" (found), not None."""
        messages = [{'role': 'user', 'content': 'Hello [DiscussionId][/DiscussionId]'}]
        result = extract_discussion_id(messages)
        assert result == ""
        assert result is not None

    @pytest.mark.parametrize("unsafe_id", [
        "../evil",
        "a/b",
        "a\\b",
        "C:evil",
        ".",
        "..",
    ], ids=["dotdot_slash", "fwd_slash", "back_slash", "drive_colon", "dot", "dotdot"])
    def test_extract_discussion_id_path_unsafe_returns_none(self, unsafe_id):
        """The discussion id is joined into filesystem paths downstream; an id
        containing a path separator, drive colon, or traversal component is
        rejected at extraction and the request is treated as stateless (None)."""
        messages = [{'role': 'user', 'content': f'[DiscussionId]{unsafe_id}[/DiscussionId]'}]
        assert extract_discussion_id(messages) is None

    def test_extract_discussion_id_unsafe_first_match_stops_search(self):
        """An unsafe id in the first matching message returns None outright; a
        safe id in a LATER message is not consulted (the request goes stateless
        rather than trusting a mixed-signal conversation)."""
        messages = [
            {'role': 'user', 'content': '[DiscussionId]../evil[/DiscussionId]'},
            {'role': 'user', 'content': '[DiscussionId]safe-id[/DiscussionId]'},
        ]
        assert extract_discussion_id(messages) is None

    def test_extract_discussion_id_safe_characters_accepted(self):
        """Hyphens, underscores, and dots inside a name are safe and accepted."""
        messages = [{'role': 'user', 'content': '[DiscussionId]conv-42_test.v2[/DiscussionId]'}]
        assert extract_discussion_id(messages) == "conv-42_test.v2"

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

    def test_role_matching_is_case_insensitive(self):
        """A 'System'/'SYSTEM' role is recognized as system (roles are lowercased
        before comparison)."""
        messages = [
            {'role': 'System', 'content': 'Cap sys.'},
            {'role': 'user', 'content': 'User1.'},
            {'role': 'SYSTEM', 'content': 'Upper sys.'},
        ]
        system_prompt, conversation = separate_messages(messages, separate_sysmes=False)
        assert system_prompt == "Cap sys. Upper sys."
        assert conversation == [{'role': 'user', 'content': 'User1.'}]


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
        (
                "[Beg_SysMes]Mid-conversation system note.",
                [{"role": "systemMes", "content": "Mid-conversation system note."}]
        ),
        (
                "[Beg_User]Hello![Beg_Foo]Should be dropped.[Beg_Assistant]Hi!",
                [
                    {"role": "user", "content": "Hello!"},
                    {"role": "assistant", "content": "Hi!"}
                ]
        ),
        (
                # Legacy clients end the prompt with a bare [Beg_Assistant] to
                # request a completion: the empty segment still yields a message.
                "[Beg_User]Hello![Beg_Assistant]",
                [
                    {"role": "user", "content": "Hello!"},
                    {"role": "assistant", "content": ""}
                ]
        ),
        (
                # Whitespace around segment content is stripped.
                "[Beg_User]  padded  [Beg_Assistant]\n\nnewlines\n",
                [
                    {"role": "user", "content": "padded"},
                    {"role": "assistant", "content": "newlines"}
                ]
        ),
    ], ids=["standard", "multiple_system", "no_tags", "empty_string",
            "sysmes_tag_maps_to_systemMes", "unrecognized_tag_skipped",
            "trailing_empty_assistant_segment", "whitespace_stripped"])
    def test_parse_conversation(self, input_str, expected):
        """Tests parsing of various tagged string formats."""
        assert parse_conversation(input_str) == expected


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

    def test_stops_at_first_overflow_does_not_skip_huge_message(self, mocker):
        """Phase 2 BREAKS at the first message that overflows the budget: an older
        message that would individually fit is still excluded (the documented
        stop-at-first-overflow contract), keeping the window contiguous."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'small': 10, 'HUGE': 1000, 'recent': 10}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'small'},
            {'role': 'assistant', 'content': 'HUGE'},
            {'role': 'user', 'content': 'recent'},
        ]
        # min=1: recent (10) satisfies the floor. Budget 100: HUGE (1010 total)
        # overflows and stops the loop. small (20 total) would fit if the loop
        # skipped HUGE, but must not be selected.
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 1, 100)
        assert [m['content'] for m in result] == ['recent']

    def test_empty_messages_returns_empty(self):
        """Tests that empty messages returns empty list."""
        assert extract_last_turns_with_min_messages_and_token_limit([], 5, 1000) == []

    def test_messages_with_images_key_included(self, mocker):
        """Tests that messages with 'images' key are included normally."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'hello', 'images': ['image_data']},
            {'role': 'assistant', 'content': 'hi'},
        ]
        result = extract_last_turns_with_min_messages_and_token_limit(messages, 2, 1000)
        assert len(result) == 2
        assert result[0]['content'] == 'hello'

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

    def test_forwards_budget_overrides_min_to_selector(self, mocker):
        """The string wrapper forwards budget_overrides_min to the underlying selector."""
        mock_base = mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_with_min_messages_and_token_limit',
            return_value=[{'role': 'user', 'content': 'A'}]
        )
        extract_last_turns_with_min_messages_and_token_limit_as_string(
            [{'role': 'user', 'content': 'dummy'}], 5, 1000, budget_overrides_min=True
        )
        assert mock_base.call_args.kwargs['budget_overrides_min'] is True


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

    def test_messages_with_only_images_key_still_returned(self, mocker):
        """Tests that messages with images key are returned (they are regular user messages)."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'look at this', 'images': ['img1']},
            {'role': 'user', 'content': 'and this', 'images': ['img2']},
        ]
        result = extract_last_turns_by_estimated_token_limit(messages, 1000)
        assert len(result) == 2

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

    # --- budget_overrides_min: the count floor yields to the token budget ----------
    # (used by the context-window clamp so a floored conversation variable on an
    # authored-prompt node cannot build an over-window prompt the backend rejects)

    def test_budget_overrides_min_drops_below_floor(self, mocker):
        """With budget_overrides_min=True the floor yields to token_limit: only the
        most-recent messages that fit are kept, fewer than min_messages."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 100, 'msg3': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # min=3, token_limit=150: a hard floor keeps all 3 (300 tok); yielding keeps
        # only msg3 (100); msg2 would make 200 > 150, so it stops.
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 3, 150, budget_overrides_min=True)
        assert [m['content'] for m in result] == ['msg3']

    def test_budget_overrides_min_keeps_partial_floor(self, mocker):
        """The floor yields only as far as the budget requires: it keeps as many
        recent whole messages as fit, not just one."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'a': 100, 'b': 100, 'c': 100, 'd': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'a'},
            {'role': 'assistant', 'content': 'b'},
            {'role': 'user', 'content': 'c'},
            {'role': 'assistant', 'content': 'd'},
        ]
        # min=4, token_limit=250: d(100)+c(100)=200 fit; b would make 300 > 250, stop.
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 4, 250, budget_overrides_min=True)
        assert [m['content'] for m in result] == ['c', 'd']

    def test_budget_overrides_min_always_keeps_most_recent(self, mocker):
        """Even when the single most-recent message alone exceeds the budget, at
        least that one message is returned (we can never send nothing)."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'small': 10, 'huge': 5000}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'small'},
            {'role': 'assistant', 'content': 'huge'},
        ]
        # min=2, token_limit=100: huge(5000) alone exceeds the budget but is still
        # kept as the single floor message; small is dropped.
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 2, 100, budget_overrides_min=True)
        assert [m['content'] for m in result] == ['huge']

    def test_budget_overrides_min_noop_when_floor_fits(self, mocker):
        """When the floor already fits, the flag changes nothing: the full floor
        plus any phase-2 expansion is returned, exactly as the hard floor would."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        messages = [
            {'role': 'user', 'content': 'm1'},
            {'role': 'assistant', 'content': 'm2'},
            {'role': 'user', 'content': 'm3'},
        ]
        # min=2, token_limit=1000: floor fits and phase 2 expands to all 3.
        result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 2, 1000, budget_overrides_min=True)
        assert len(result) == 3

    def test_budget_overrides_min_false_keeps_hard_floor(self, mocker):
        """Regression guard: the default (False) preserves the historical hard floor,
        so min_messages are returned even when they exceed the token limit."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            side_effect=lambda text: {'msg1': 100, 'msg2': 100, 'msg3': 100}.get(text, 0)
        )
        messages = [
            {'role': 'user', 'content': 'msg1'},
            {'role': 'assistant', 'content': 'msg2'},
            {'role': 'user', 'content': 'msg3'},
        ]
        # Same inputs as the drop-below-floor test; without the flag all 3 survive.
        default_result = extract_last_turns_with_min_messages_and_token_limit(messages, 3, 150)
        explicit_result = extract_last_turns_with_min_messages_and_token_limit(
            messages, 3, 150, budget_overrides_min=False)
        assert len(default_result) == 3
        assert default_result == explicit_result


class TestFormatMessagesToString:
    """Tests for the _format_messages_to_string helper function."""

    def test_default_join_with_newline(self):
        """Tests that messages are joined with newline by default."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'}
        ]
        result = _format_messages_to_string(messages)
        assert result == "Hello\nHi there"

    def test_custom_separator(self):
        """Tests that a custom separator is used between messages."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'}
        ]
        result = _format_messages_to_string(messages, separator='\n---\n')
        assert result == "Hello\n---\nHi there"

    def test_add_role_tags(self):
        """Tests that role tags are prepended when add_role_tags is True."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'},
            {'role': 'system', 'content': 'System note'}
        ]
        result = _format_messages_to_string(messages, add_role_tags=True)
        assert result == "User: Hello\nAssistant: Hi there\nSystem: System note"

    def test_add_role_tags_with_custom_separator(self):
        """Tests role tags combined with a custom separator."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi'}
        ]
        result = _format_messages_to_string(messages, add_role_tags=True, separator='\n\n')
        assert result == "User: Hello\n\nAssistant: Hi"

    def test_tool_role_gets_prefix(self):
        """Tests that tool role messages get the 'Tool Result: ' prefix tag."""
        messages = [
            {'role': 'tool', 'content': 'Tool output'}
        ]
        result = _format_messages_to_string(messages, add_role_tags=True)
        assert result == "Tool Result: Tool output"

    def test_unknown_role_gets_no_prefix(self):
        """Tests that unknown roles do not get a prefix tag."""
        messages = [
            {'role': 'function', 'content': 'Function output'}
        ]
        result = _format_messages_to_string(messages, add_role_tags=True)
        assert result == "Function output"

    def test_empty_messages(self):
        """Tests that empty message list returns empty string."""
        result = _format_messages_to_string([])
        assert result == ""

    def test_missing_content_key_with_role_tags(self):
        """Tests that missing 'content' key defaults to empty string with role tags."""
        messages = [{'role': 'user'}]
        result = _format_messages_to_string(messages, add_role_tags=True)
        assert result == "User: "

    def test_role_tags_false_by_default(self):
        """Tests that role tags are not added when add_role_tags is False (default)."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi'}
        ]
        result = _format_messages_to_string(messages)
        assert "User: " not in result
        assert "Assistant: " not in result
        assert result == "Hello\nHi"


class TestAsStringRoleTagsAndSeparator:
    """Tests for the add_role_tags and separator parameters on all _as_string functions."""

    def test_extract_last_n_turns_as_string_with_role_tags(self, mocker):
        """Tests that extract_last_n_turns_as_string passes role tags through."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_n_turns',
            return_value=[
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi'}
            ]
        )
        result = extract_last_n_turns_as_string(MESSAGES_FIXTURE, 2, add_role_tags=True)
        assert result == "User: Hello\nAssistant: Hi"

    def test_extract_last_n_turns_as_string_with_custom_separator(self, mocker):
        """Tests that extract_last_n_turns_as_string uses a custom separator."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_n_turns',
            return_value=[
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi'}
            ]
        )
        result = extract_last_n_turns_as_string(MESSAGES_FIXTURE, 2, separator='\n***\n')
        assert result == "Hello\n***\nHi"

    def test_extract_last_n_turns_as_string_combined(self, mocker):
        """Tests role tags and custom separator together."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_n_turns',
            return_value=[
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi'}
            ]
        )
        result = extract_last_n_turns_as_string(
            MESSAGES_FIXTURE, 2, add_role_tags=True, separator='\n*** END MESSAGE ***\n'
        )
        assert result == "User: Hello\n*** END MESSAGE ***\nAssistant: Hi"

    def test_token_limit_as_string_with_role_tags(self, mocker):
        """Tests that token-limit string function supports role tags."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_by_estimated_token_limit',
            return_value=[
                {'role': 'user', 'content': 'Msg1'},
                {'role': 'assistant', 'content': 'Msg2'}
            ]
        )
        result = extract_last_turns_by_estimated_token_limit_as_string(
            MESSAGES_FIXTURE, 1000, add_role_tags=True
        )
        assert result == "User: Msg1\nAssistant: Msg2"

    def test_token_limit_as_string_with_custom_separator(self, mocker):
        """Tests that token-limit string function supports a custom separator."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_by_estimated_token_limit',
            return_value=[
                {'role': 'user', 'content': 'Msg1'},
                {'role': 'assistant', 'content': 'Msg2'}
            ]
        )
        result = extract_last_turns_by_estimated_token_limit_as_string(
            MESSAGES_FIXTURE, 1000, separator='\n\n'
        )
        assert result == "Msg1\n\nMsg2"

    def test_min_n_max_tokens_as_string_with_role_tags(self, mocker):
        """Tests that min-messages+token-limit string function supports role tags."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_with_min_messages_and_token_limit',
            return_value=[
                {'role': 'user', 'content': 'A'},
                {'role': 'assistant', 'content': 'B'}
            ]
        )
        result = extract_last_turns_with_min_messages_and_token_limit_as_string(
            MESSAGES_FIXTURE, 2, 1000, add_role_tags=True
        )
        assert result == "User: A\nAssistant: B"

    def test_min_n_max_tokens_as_string_with_custom_separator(self, mocker):
        """Tests that min-messages+token-limit string function supports a custom separator."""
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.extract_last_turns_with_min_messages_and_token_limit',
            return_value=[
                {'role': 'user', 'content': 'A'},
                {'role': 'assistant', 'content': 'B'}
            ]
        )
        result = extract_last_turns_with_min_messages_and_token_limit_as_string(
            MESSAGES_FIXTURE, 2, 1000, separator='\n---\n'
        )
        assert result == "A\n---\nB"


class TestSummarizeToolArguments:
    """Tests for _summarize_tool_arguments."""

    def test_returns_first_string_field(self):
        """The first string-valued field in the JSON object is returned."""
        result = _summarize_tool_arguments('{"command": "git status", "description": "Check status"}')
        assert result == "git status"

    def test_returns_first_string_field_skipping_non_strings(self):
        """Non-string fields are skipped; the first string field is returned."""
        result = _summarize_tool_arguments('{"count": 5, "name": "foo"}')
        assert result == "foo"

    def test_truncates_long_value(self):
        """String values longer than 200 characters are truncated."""
        long_val = "x" * 300
        result = _summarize_tool_arguments(f'{{"path": "{long_val}"}}')
        assert len(result) == 200
        assert result == long_val[:200]

    def test_no_string_fields_falls_back_to_raw(self):
        """If no string field exists, raw arguments are returned truncated."""
        result = _summarize_tool_arguments('{"count": 5, "flag": true}')
        assert result == '{"count": 5, "flag": true}'

    def test_invalid_json_falls_back_to_raw(self):
        """Invalid JSON is returned as raw text, truncated."""
        result = _summarize_tool_arguments("not json at all")
        assert result == "not json at all"

    def test_empty_string(self):
        """Empty arguments string returns empty string."""
        result = _summarize_tool_arguments("")
        assert result == ""

    def test_none_argument(self):
        """None is handled gracefully."""
        result = _summarize_tool_arguments(None)
        assert result == ""

    def test_raw_truncation_at_200(self):
        """Raw fallback is also truncated to 200 characters."""
        long_raw = "z" * 300
        result = _summarize_tool_arguments(long_raw)
        assert len(result) == 200

    def test_dict_arguments_return_first_string_field(self):
        """Ollama-native dict arguments (not a JSON string) are supported: the
        first string-valued field is returned."""
        result = _summarize_tool_arguments({"count": 3, "command": "git log"})
        assert result == "git log"

    def test_dict_arguments_without_string_field_fall_back_to_str(self):
        """A dict with no string values falls back to str(arguments), truncated."""
        result = _summarize_tool_arguments({"count": 3, "flag": True})
        assert result == str({"count": 3, "flag": True})

    def test_non_str_non_dict_arguments_fall_back_to_str(self):
        """Arguments that are neither a string nor a dict (e.g. a list) fall back
        to their str() rendering, truncated to 200 characters."""
        assert _summarize_tool_arguments([1, 2, 3]) == "[1, 2, 3]"
        long_list = list(range(200))
        assert _summarize_tool_arguments(long_list) == str(long_list)[:200]


class TestFormatToolCallsAsText:
    """Tests for format_tool_calls_as_text."""

    def test_single_tool_call(self):
        """A single tool call is formatted correctly."""
        calls = [{"function": {"name": "bash", "arguments": '{"command": "git status"}'}}]
        result = format_tool_calls_as_text(calls)
        assert result == "[Tool Call: bash] git status"

    def test_multiple_tool_calls(self):
        """Multiple tool calls produce one line each, joined by newlines."""
        calls = [
            {"function": {"name": "bash", "arguments": '{"command": "git status"}'}},
            {"function": {"name": "read", "arguments": '{"filePath": "/path/to/file.txt"}'}}
        ]
        result = format_tool_calls_as_text(calls)
        assert result == "[Tool Call: bash] git status\n[Tool Call: read] /path/to/file.txt"

    def test_missing_function_key(self):
        """A tool call without a function key falls back to 'unknown'."""
        calls = [{}]
        result = format_tool_calls_as_text(calls)
        assert result == "[Tool Call: unknown] "

    def test_empty_list(self):
        """An empty tool_calls list returns an empty string."""
        assert format_tool_calls_as_text([]) == ""

    def test_no_string_args_shows_raw(self):
        """When arguments have no string fields, raw JSON is shown."""
        calls = [{"function": {"name": "calc", "arguments": '{"value": 42}'}}]
        result = format_tool_calls_as_text(calls)
        assert result == '[Tool Call: calc] {"value": 42}'

    def test_non_dict_entries_skipped(self):
        """Malformed non-dict entries in the tool_calls list are skipped without
        crashing; the valid calls still render."""
        calls = [
            "garbage-string",
            None,
            {"function": {"name": "bash", "arguments": '{"command": "ls"}'}},
        ]
        result = format_tool_calls_as_text(calls)
        assert result == "[Tool Call: bash] ls"

    def test_non_dict_function_value_falls_back_to_unknown(self):
        """A call whose 'function' value is not a dict renders as unknown rather
        than crashing."""
        calls = [{"function": "not-a-dict"}]
        assert format_tool_calls_as_text(calls) == "[Tool Call: unknown] "


class TestEnrichMessagesWithToolCalls:
    """Tests for enrich_messages_with_tool_calls."""

    def test_assistant_with_tool_calls_and_empty_content(self):
        """An assistant message with tool_calls and no content gets tool text as content."""
        messages = [
            {"role": "user", "content": "Run a command"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls"}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Call: bash] ls"

    def test_assistant_with_tool_calls_and_null_content(self):
        """An assistant message with tool_calls and None content gets tool text."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "read", "arguments": '{"filePath": "/tmp/f.txt"}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0]["content"] == "[Tool Call: read] /tmp/f.txt"

    def test_assistant_with_tool_calls_and_existing_content(self):
        """Tool text is appended to existing content with a newline separator."""
        messages = [
            {"role": "assistant", "content": "Sure, let me check.", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "git diff"}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0]["content"] == "Sure, let me check.\n[Tool Call: bash] git diff"

    def test_user_messages_unaffected(self):
        """User messages are never enriched, even if they somehow have tool_calls."""
        messages = [
            {"role": "user", "content": "Hello", "tool_calls": [
                {"function": {"name": "test", "arguments": "{}"}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0]["content"] == "Hello"

    def test_messages_without_tool_calls_unchanged(self):
        """Messages without tool_calls pass through as-is."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0] is messages[0]
        assert result[1] is messages[1]

    def test_original_messages_not_mutated(self):
        """The original message dicts are not modified."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "pwd"}'}}
            ]}
        ]
        enrich_messages_with_tool_calls(messages)
        assert messages[0]["content"] == ""

    def test_empty_list(self):
        """An empty messages list returns an empty list."""
        assert enrich_messages_with_tool_calls([]) == []

    def test_multiple_tool_calls_in_one_message(self):
        """Multiple tool calls in a single message are all rendered, one line each,
        in order, joined by newlines with nothing else added."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls"}'}},
                {"function": {"name": "read", "arguments": '{"filePath": "/tmp/a.txt"}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0]["content"] == "[Tool Call: bash] ls\n[Tool Call: read] /tmp/a.txt"

    def test_assistant_without_tool_calls_key(self):
        """Assistant messages without tool_calls key are not modified."""
        messages = [{"role": "assistant", "content": "Normal reply"}]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0] is messages[0]
        assert result[0]["content"] == "Normal reply"

    def test_tool_call_braces_are_sentinel_escaped(self):
        """Tool call text containing curly braces is sentinel-escaped to prevent str.format() breakage."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "write", "arguments": '{"data": {"nested": true}}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        # The summary falls back to raw args since no string-valued field exists;
        # braces from the raw args JSON should be replaced with sentinel tokens
        assert "__WILMER_L_CURLY__" in content
        assert "__WILMER_R_CURLY__" in content
        assert "{" not in content
        assert "}" not in content

    def test_tool_call_string_arg_summary_has_no_braces(self):
        """When the summary is a string field value (no braces), no escaping is needed
        and the output should be plain text."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls -la"}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        # "ls -la" has no braces, so no sentinels should appear
        assert content == "[Tool Call: bash] ls -la"
        assert "__WILMER_L_CURLY__" not in content

    def test_tool_call_with_empty_json_args(self):
        """Empty JSON args '{}' should have braces escaped."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "noop", "arguments": '{}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        # The summary of '{}' is '' (empty dict, no string fields, fallback is empty)
        # but the tool name line itself is produced by the f-string, so no braces in output
        assert "[Tool Call: noop]" in content
        assert "{" not in content

    def test_tool_call_with_deeply_nested_json_fallback(self):
        """Tool call args with only non-string values fall back to raw JSON,
        which may have many braces. All should be escaped."""
        args = '{"config": {"retries": 3, "backoff": {"initial": 1, "max": 30}}}'
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "setup", "arguments": args}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        assert "{" not in content
        assert "}" not in content
        assert "setup" in content

    def test_existing_gateway_escaped_content_not_double_escaped(self):
        """If assistant content already has sentinel tokens (from gateway), and tool
        call text is appended, the existing sentinels should not be mangled."""
        messages = [
            {"role": "assistant",
             "content": "Data: __WILMER_L_CURLY__x__WILMER_R_CURLY__",
             "tool_calls": [
                 {"function": {"name": "bash", "arguments": '{"command": "pwd"}'}}
             ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        # Original content preserved
        assert "Data: __WILMER_L_CURLY__x__WILMER_R_CURLY__" in content
        # Tool call appended
        assert "[Tool Call: bash] pwd" in content

    def test_multiple_tool_calls_with_mixed_brace_presence(self):
        """Multiple tool calls: first has string args (no braces in summary),
        second has non-string args (braces in raw fallback)."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls"}'}},
                {"function": {"name": "config", "arguments": '{"timeout": 30, "retries": 3}'}}
            ]}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        # bash summary is "ls", no braces
        assert "bash" in content
        # config falls back to raw JSON, so braces should be escaped
        assert "config" in content
        assert "{" not in content
        assert "}" not in content

    def test_tool_result_message_enriched_with_name(self):
        """Tool result messages get a [Tool Result: name] prefix."""
        messages = [
            {"role": "tool", "content": "file contents here", "name": "read", "tool_call_id": "call_1"}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0]["content"] == "[Tool Result: read] file contents here"

    def test_tool_result_message_without_name(self):
        """Tool result messages without a name field use 'unknown_tool'."""
        messages = [
            {"role": "tool", "content": "some output", "tool_call_id": "call_1"}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0]["content"] == "[Tool Result: unknown_tool] some output"

    def test_tool_result_message_braces_escaped(self):
        """Curly braces in tool result content are sentinel-escaped."""
        messages = [
            {"role": "tool", "content": '{"key": "value"}', "name": "read", "tool_call_id": "call_1"}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        assert "[Tool Result: read]" in content
        assert "{" not in content
        assert "}" not in content
        assert "__WILMER_L_CURLY__" in content

    def test_tool_result_name_braces_escaped(self):
        """Curly braces in the tool NAME (not just the content) are sentinel-escaped.

        A brace-containing name would otherwise survive to the downstream
        str.format() pass in apply_variables() and could raise. The existing
        brace test only exercises the content, so this guards the separate
        name-escaping line.
        """
        messages = [
            {"role": "tool", "content": "ok", "name": "weird{name}", "tool_call_id": "call_1"}
        ]
        result = enrich_messages_with_tool_calls(messages)
        content = result[0]["content"]
        assert "weird__WILMER_L_CURLY__name__WILMER_R_CURLY__" in content
        assert "{" not in content
        assert "}" not in content

    def test_tool_result_original_not_mutated(self):
        """Original tool result message dicts are not modified."""
        messages = [
            {"role": "tool", "content": "output", "name": "bash", "tool_call_id": "call_1"}
        ]
        enrich_messages_with_tool_calls(messages)
        assert messages[0]["content"] == "output"

    def test_full_tool_call_sequence_enriched(self):
        """A complete tool call sequence (assistant + tool results) is fully enriched."""
        messages = [
            {"role": "user", "content": "Find files"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "glob", "arguments": '{"pattern": "*.py"}'}},
                {"function": {"name": "glob", "arguments": '{"pattern": "*.js"}'}}
            ]},
            {"role": "tool", "content": "file1.py\nfile2.py", "name": "glob", "tool_call_id": "call_1"},
            {"role": "tool", "content": "app.js", "name": "glob", "tool_call_id": "call_2"},
            {"role": "assistant", "content": "Found the files."}
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[0] is messages[0]
        assert "[Tool Call: glob]" in result[1]["content"]
        assert "[Tool Result: glob]" in result[2]["content"]
        assert "file1.py" in result[2]["content"]
        assert "[Tool Result: glob]" in result[3]["content"]
        assert "app.js" in result[3]["content"]
        assert result[4] is messages[4]

    def test_tool_result_attributed_via_tool_call_id(self):
        """A result carrying only a tool_call_id (no name) is labeled from the
        originating call's name AND argument summary, so the reader can tell
        which file the result is for."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_abc", "function": {
                    "name": "read", "arguments": '{"filePath": "/workspace/src/store.js"}'}}
            ]},
            {"role": "tool", "content": "'use strict';", "tool_call_id": "call_abc"},
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Result: read /workspace/src/store.js] 'use strict';"

    def test_tool_result_call_id_lookup_preferred_over_name(self):
        """When a result has both a matching tool_call_id and a bare name, the
        richer call-id label (name + target) wins."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "function": {
                    "name": "write", "arguments": '{"filePath": "/workspace/cli.js"}'}}
            ]},
            {"role": "tool", "content": "Wrote 17622 bytes", "name": "write", "tool_call_id": "call_1"},
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Result: write /workspace/cli.js] Wrote 17622 bytes"

    def test_tool_result_unmatched_call_id_falls_back_to_name(self):
        """A tool_call_id that matches no assistant call falls back to the
        result's own name rather than mislabeling."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "function": {"name": "read", "arguments": '{"filePath": "/a.txt"}'}}
            ]},
            {"role": "tool", "content": "data", "name": "bash", "tool_call_id": "call_999"},
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Result: bash] data"

    def test_label_is_name_only_when_arguments_empty(self):
        """A call with empty arguments produces a name-only label, with no trailing
        space from an empty summary."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "function": {"name": "status", "arguments": ""}}
            ]},
            {"role": "tool", "content": "ok", "tool_call_id": "call_1"},
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Result: status] ok"

    def test_label_map_skips_malformed_calls_without_crashing(self):
        """Non-dict entries, calls with no/blank/non-string ids, and calls with a
        non-dict function value are all skipped by the label map; a result whose
        id therefore has no label falls back to its own name."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                "junk-entry",
                {"function": {"name": "no_id", "arguments": '{"x": "y"}'}},
                {"id": "", "function": {"name": "blank_id", "arguments": "{}"}},
                {"id": 42, "function": {"name": "int_id", "arguments": "{}"}},
                {"id": "call_fn_bad", "function": "not-a-dict"},
            ]},
            {"role": "tool", "content": "out", "name": "fallback_tool", "tool_call_id": "call_x"},
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Result: fallback_tool] out"

    def test_result_with_call_id_to_function_less_call_labeled_unknown(self):
        """A result whose id maps to a call with a non-dict function gets the
        'unknown' name from the map (the id DID match), not unknown_tool."""
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "function": "not-a-dict"},
            ]},
            {"role": "tool", "content": "out", "tool_call_id": "call_1"},
        ]
        result = enrich_messages_with_tool_calls(messages)
        assert result[1]["content"] == "[Tool Result: unknown] out"
