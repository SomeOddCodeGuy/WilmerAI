import pytest

# NOTE: Imports from Middleware.* assume the pytest.ini configuration (pythonpath = .)
# is correctly applied in the environment where these tests are executed.
from Middleware.utilities.streaming_utils import (
    StreamingThinkRemover,
    post_process_llm_output,
    remove_thinking_from_text,
    stream_static_content,
    strip_leading_response_prefixes,
)

# A base configuration for reusability in tests
BASE_ENDPOINT_CONFIG = {
    "removeThinking": True,
    "startThinkTag": "<think>",
    "endThinkTag": "</think>",
    "expectOnlyClosingThinkTag": False,
    "openingTagGracePeriod": 50,
    "removeCustomTextFromResponseStartEndpointWide": False,
    "responseStartTextToRemoveEndpointWide": [],
    "trimBeginningAndEndLineBreaks": False
}

BASE_WORKFLOW_CONFIG = {
    "removeCustomTextFromResponseStart": False,
    "responseStartTextToRemove": [],
    "addDiscussionIdTimestampsForLLM": False
}

# Configuration for Scenarios A and C (Complex Tags)
COMPLEX_TAG_CONFIG = {
    **BASE_ENDPOINT_CONFIG,
    "startThinkTag": "<|channel|>analysis<|message|>",
    "endThinkTag": "<|start|>assistant<|channel|>final<|message|>",
    "openingTagGracePeriod": 100,  # Increased grace period for longer tags
}


def process_stream_in_chunks(remover, text, chunk_size=1):
    """Helper to simulate processing a stream chunk by chunk."""
    output = ""
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        output += remover.process_delta(chunk)
    output += remover.finalize()
    return output


class TestStreamStaticContent:
    """Tests for the stream_static_content generator."""

    def test_token_sequence_preserves_whitespace(self, mocker):
        """Words and whitespace runs are yielded as separate tokens, in order."""
        mock_sleep = mocker.patch('time.sleep')
        content = "a\n\nb  c"

        chunks = list(stream_static_content(content))

        assert chunks == [
            {'token': 'a', 'finish_reason': None},
            {'token': '\n\n', 'finish_reason': None},
            {'token': 'b', 'finish_reason': None},
            {'token': '  ', 'finish_reason': None},
            {'token': 'c', 'finish_reason': None},
            {'token': '', 'finish_reason': 'stop'},
        ]
        # Reassembling the streamed tokens must reproduce the input exactly.
        assert "".join(chunk['token'] for chunk in chunks) == content
        # The pacing sleep fires only for the three word tokens, never for whitespace.
        assert mock_sleep.call_count == 3

    def test_terminal_chunk_signals_stop(self, mocker):
        mocker.patch('time.sleep')

        chunks = list(stream_static_content("hello world"))

        assert chunks[-1] == {'token': '', 'finish_reason': 'stop'}
        assert all(chunk['finish_reason'] is None for chunk in chunks[:-1])

    def test_empty_content_yields_only_terminal_chunk(self, mocker):
        mocker.patch('time.sleep')

        chunks = list(stream_static_content(""))

        assert chunks == [{'token': '', 'finish_reason': 'stop'}]

    def test_delay_budget_caps_total_sleeping_for_large_payloads(self, mocker):
        """
        The artificial pacing delay is capped at a total budget (5 s at 20 ms per
        word = ~250 sleeps); once the budget is spent the remaining tokens stream
        with no delay. A large static payload (big WebFetch body etc.) must not
        sleep once per word unbounded.
        """
        mock_sleep = mocker.patch('time.sleep')
        word_count = 400
        content = " ".join(["word"] * word_count)

        chunks = list(stream_static_content(content))

        # Every word is still yielded (the cap skips sleeps, not tokens).
        word_tokens = [c for c in chunks if c['token'] and not c['token'].isspace()]
        assert len(word_tokens) == word_count
        # Budget: 5.0 s / 0.02 s = 250 sleeps. Allow a tiny float-accumulation
        # margin; without the cap this would be 400.
        assert 245 <= mock_sleep.call_count <= 255


class TestStreamingThinkRemover:
    """Tests for the stateful StreamingThinkRemover class."""

    def test_init_disables_feature_if_flag_is_false(self):
        config = {**BASE_ENDPOINT_CONFIG, "removeThinking": False}
        remover = StreamingThinkRemover(config)
        assert not remover.remove_thinking

    def test_init_disables_feature_if_tags_are_missing(self):
        config = {**BASE_ENDPOINT_CONFIG, "startThinkTag": ""}
        remover = StreamingThinkRemover(config)
        assert not remover.remove_thinking

    def test_feature_disabled_passes_through_text(self):
        config = {**BASE_ENDPOINT_CONFIG, "removeThinking": False}
        remover = StreamingThinkRemover(config)
        text = "This is <think>some</think> text."
        assert process_stream_in_chunks(remover, text) == text

    # --- Standard Mode Tests ---

    def test_standard_mode_removes_block_correctly(self):
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        text = "Prefix. <think>This should be removed.</think> Suffix."
        expected = "Prefix.  Suffix."
        assert process_stream_in_chunks(remover, text) == expected

    # Scenario A: Complex Tags (Streaming)
    def test_scenario_a_complex_tags_streaming(self):
        """Scenario A: Ensure complex tags are correctly removed during streaming."""
        remover = StreamingThinkRemover(COMPLEX_TAG_CONFIG)
        text = (
            "<|channel|>analysis<|message|>The user just spoke to me. I'll say hi."
            "<|start|>assistant<|channel|>final<|message|>Hello there!"
        )
        expected = "Hello there!"
        # Process in small chunks to ensure buffering handles the long tags correctly across boundaries
        assert process_stream_in_chunks(remover, text, chunk_size=5) == expected

    def test_standard_mode_is_case_insensitive(self):
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        text = "Hello <THINK>stuff</think> world."
        expected = "Hello  world."
        assert process_stream_in_chunks(remover, text) == expected

    def test_standard_mode_handles_tags_split_across_deltas(self):
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        text = "A<think>B</think>C"
        expected = "AC"
        assert process_stream_in_chunks(remover, text, chunk_size=1) == expected

    def test_standard_mode_ignores_tag_outside_grace_period(self):
        # Grace period is 50
        text = (" " * 51) + "<think>This should NOT be removed.</think>"
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        assert process_stream_in_chunks(remover, text) == text

    def test_standard_mode_passes_through_text_if_grace_period_exceeded(self):
        text = (" " * 51) + "Some text after grace period."
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        assert process_stream_in_chunks(remover, text) == text

    @pytest.mark.parametrize("chunk_size", [1, 5, 1000])
    def test_grace_window_straddling_tag_is_removed_streaming(self, chunk_size):
        """
        Reconciled grace-window semantics: an opening tag qualifies when it
        STARTS at index <= openingTagGracePeriod, even if it ends beyond the
        window. The remover holds its buffer until openingTagGracePeriod +
        len(startThinkTag) characters have arrived, so the outcome is the same
        at every chunk size (previously a per-character feed crossed the window
        with only a partial tag buffered and passed everything through).
        """
        # Grace period is 50; "<think>" starts at index 48 and ends at 55.
        text = ("x" * 48) + "<think>hidden</think>visible"
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)

        assert process_stream_in_chunks(remover, text, chunk_size) == ("x" * 48) + "visible"

    def test_standard_mode_removes_only_first_think_block(self):
        """
        Only the first qualifying think block is removed; later tags pass
        through untouched, matching remove_thinking_from_text.
        """
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        text = "<think>a</think>mid<think>b</think>end"
        expected = "mid<think>b</think>end"
        assert process_stream_in_chunks(remover, text) == expected

    def test_single_large_delta_with_tag_beyond_grace_window_passes_through(self):
        """
        A single delta whose opening tag starts beyond the grace window hits the
        found-but-outside-window branch: tag checks are disabled and the entire
        buffer is yielded unchanged from that one process_delta call.
        """
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        # Grace period is 50; the tag starts at index 51.
        text = (" " * 51) + "<think>x</think>"

        assert remover.process_delta(text) == text
        assert remover.finalize() == ""

    def test_standard_mode_finalize_flushes_unterminated_block(self):
        remover = StreamingThinkRemover(BASE_ENDPOINT_CONFIG)
        text = "Here is <think>some unterminated text"
        # On finalize, it should return the opening tag plus the buffered content
        expected = "Here is <think>some unterminated text"
        assert process_stream_in_chunks(remover, text) == expected

    # --- Expect Only Closing Tag Mode Tests ---

    def test_closing_only_mode_removes_preceding_text(self):
        config = {**BASE_ENDPOINT_CONFIG, "expectOnlyClosingThinkTag": True}
        remover = StreamingThinkRemover(config)
        text = "This text should be removed.</think>This should be kept."
        expected = "This should be kept."
        assert process_stream_in_chunks(remover, text) == expected

    def test_closing_only_mode_handles_split_tag(self):
        config = {**BASE_ENDPOINT_CONFIG, "expectOnlyClosingThinkTag": True}
        remover = StreamingThinkRemover(config)
        text = "Junk</think>Real"
        expected = "Real"
        assert process_stream_in_chunks(remover, text, chunk_size=1) == expected

    def test_closing_only_mode_returns_buffer_if_no_tag_found(self):
        config = {**BASE_ENDPOINT_CONFIG, "expectOnlyClosingThinkTag": True}
        remover = StreamingThinkRemover(config)
        text = "This text should be returned in full."
        expected = "This text should be returned in full."
        assert process_stream_in_chunks(remover, text) == expected


class TestRemoveThinkingFromText:
    """Tests for the stateless remove_thinking_from_text function."""

    # Scenario A: Complex Tags (Non-Streaming)
    def test_scenario_a_complex_tags_non_streaming(self):
        """Scenario A: Ensure complex tags are correctly removed from a complete string."""
        text = (
            "<|channel|>analysis<|message|>The user just spoke to me. I'll say hi."
            "<|start|>assistant<|channel|>final<|message|>Hello there!"
        )
        expected = "Hello there!"
        assert remove_thinking_from_text(text, COMPLEX_TAG_CONFIG) == expected

    def test_grace_window_straddling_tag_is_removed_non_streaming(self):
        """
        Reconciled grace-window semantics: the opening tag qualifies when it
        STARTS at index <= openingTagGracePeriod; it may end beyond the window.
        This matches StreamingThinkRemover (see
        TestStreamingThinkRemover.test_grace_window_straddling_tag_is_removed_streaming).
        """
        # Grace period is 50; "<think>" starts at index 48 and ends at 55.
        text = ("x" * 48) + "<think>hidden</think>visible"

        assert remove_thinking_from_text(text, BASE_ENDPOINT_CONFIG) == ("x" * 48) + "visible"

    @pytest.mark.parametrize("text_input, config_override, expected_output", [
        # Standard mode, successful removal
        ("Prefix <think>block</think> Suffix", {}, "Prefix  Suffix"),
        # Standard mode, case-insensitive
        ("Hello <THINK>block</THINK> world", {}, "Hello  world"),
        # Standard mode, no closing tag (should not remove)
        ("Data <think>is incomplete", {}, "Data <think>is incomplete"),
        # Standard mode, opening tag outside grace period (should not remove)
        (" " * 101 + "<think>block</think>", {"openingTagGracePeriod": 100}, " " * 101 + "<think>block</think>"),
        # Standard mode, opening tag starting exactly at the window boundary (removed)
        ("x" * 50 + "<think>block</think>tail", {}, "x" * 50 + "tail"),
        # Standard mode, opening tag starting one past the window boundary (kept)
        ("x" * 51 + "<think>block</think>tail", {}, "x" * 51 + "<think>block</think>tail"),
        # Standard mode, only the first think block is removed
        ("<think>a</think>mid<think>b</think>end", {}, "mid<think>b</think>end"),
        # Closing only mode, successful removal
        ("Junk text</think>Real text", {"expectOnlyClosingThinkTag": True}, "Real text"),
        # Closing only mode, no closing tag (should return original text)
        ("Junk text without a tag", {"expectOnlyClosingThinkTag": True}, "Junk text without a tag"),
        # Feature disabled via config
        ("Text <think>block</think>", {"removeThinking": False}, "Text <think>block</think>"),
        # Feature disabled due to missing tags
        ("Text <think>block</think>", {"endThinkTag": ""}, "Text <think>block</think>"),
        # Empty input text
        ("", {}, ""),
    ])
    def test_various_scenarios(self, text_input, config_override, expected_output):
        config = {**BASE_ENDPOINT_CONFIG, **config_override}
        assert remove_thinking_from_text(text_input, config) == expected_output


# Battery of (case_id, text, config_overrides) inputs for the parity test below.
# Overrides are applied on top of BASE_ENDPOINT_CONFIG (grace period 50).
_COMPLEX_OVERRIDES = {
    "startThinkTag": "<|channel|>analysis<|message|>",
    "endThinkTag": "<|start|>assistant<|channel|>final<|message|>",
    "openingTagGracePeriod": 100,
}
PARITY_CASES = [
    # --- Standard mode ---
    ("plain_text_no_tags", "Just a plain answer with no tags at all.", {}),
    ("empty_string", "", {}),
    ("whitespace_only", " \n\t ", {}),
    ("block_at_start", "<think>reasoning</think>The answer.", {}),
    ("block_after_prefix", "Prefix. <think>hidden</think> Suffix.", {}),
    ("block_is_entire_text", "<think>only</think>", {}),
    ("mixed_case_tags", "<THINK>Reasoning</ThInK>Answer", {}),
    ("tag_straddles_window_end", ("x" * 48) + "<think>hidden</think>visible", {}),
    ("tag_starts_exactly_at_window", ("x" * 50) + "<think>h</think>v", {}),
    ("tag_starts_past_window", ("x" * 51) + "<think>h</think>v", {}),
    ("no_tag_text_longer_than_window", "w" * 200, {}),
    ("unterminated_block", "Intro <think>never closed", {}),
    ("unterminated_block_straddling_window", ("x" * 48) + "<think>never closed", {}),
    ("only_open_tag", "<think>", {}),
    ("multiple_blocks_only_first_removed", "<think>a</think>mid<think>b</think>end", {}),
    ("adjacent_blocks_only_first_removed", "<think>a</think><think>b</think>end", {}),
    ("stray_open_tag_inside_block", "<think>a<think>b</think>after", {}),
    ("stray_close_tag_without_open", "text with a stray </think> close tag", {}),
    ("long_block_content", "<think>" + ("y" * 300) + "</think>" + ("z" * 120), {}),
    # --- Standard mode, complex multi-character tags ---
    ("complex_tags_block_at_start",
     "<|channel|>analysis<|message|>The user just spoke to me. I'll say hi."
     "<|start|>assistant<|channel|>final<|message|>Hello there!",
     _COMPLEX_OVERRIDES),
    ("complex_tags_straddling_window",
     ("x" * 95) + "<|channel|>analysis<|message|>hidden<|start|>assistant<|channel|>final<|message|>done",
     _COMPLEX_OVERRIDES),
    # --- expectOnlyClosingThinkTag mode ---
    ("closing_only_removes_preamble", "junk reasoning</think>The real answer.",
     {"expectOnlyClosingThinkTag": True}),
    ("closing_only_no_tag", "no closing tag here at all", {"expectOnlyClosingThinkTag": True}),
    ("closing_only_tag_at_start", "</think>starts with close", {"expectOnlyClosingThinkTag": True}),
    ("closing_only_long_preamble", ("a" * 200) + "</think>tail", {"expectOnlyClosingThinkTag": True}),
    ("closing_only_mixed_case", "case </THINK>Kept", {"expectOnlyClosingThinkTag": True}),
    ("closing_only_multiple_closes_first_wins", "j1</think>mid</think>end",
     {"expectOnlyClosingThinkTag": True}),
    ("closing_only_empty_string", "", {"expectOnlyClosingThinkTag": True}),
]


class TestStreamingNonStreamingParity:
    """
    The streaming (StreamingThinkRemover) and non-streaming
    (remove_thinking_from_text) paths must produce identical output for
    identical content; that is the reason both implementations exist. Every
    case runs through the stateless function and through a chunked remover at
    several chunk sizes (including 1-char) and the results must match exactly.
    """

    @pytest.mark.parametrize("chunk_size", [1, 3, 7, 50, 10000])
    @pytest.mark.parametrize("case_id, text, config_overrides", PARITY_CASES,
                             ids=[case[0] for case in PARITY_CASES])
    def test_streaming_matches_non_streaming(self, case_id, text, config_overrides, chunk_size):
        config = {**BASE_ENDPOINT_CONFIG, **config_overrides}

        non_streaming_result = remove_thinking_from_text(text, config)

        remover = StreamingThinkRemover(config)
        streaming_result = process_stream_in_chunks(remover, text, chunk_size)

        assert streaming_result == non_streaming_result


class TestPostProcessLlmOutput:
    """Tests for the main cleaning orchestrator function post_process_llm_output."""

    def test_full_processing_order(self, mocker):
        """Verify all rules are applied in the correct sequence."""
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        endpoint_config = {
            **BASE_ENDPOINT_CONFIG,
            "removeCustomTextFromResponseStartEndpointWide": True,
            "responseStartTextToRemoveEndpointWide": ["EndpointPrefix: "],
            "trimBeginningAndEndLineBreaks": True,
        }
        workflow_config = {
            **BASE_WORKFLOW_CONFIG,
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["WorkflowPrefix: "],
            "addDiscussionIdTimestampsForLLM": True,
        }
        raw_text = (
            " <think>foo</think> WorkflowPrefix: EndpointPrefix: "
            "[Sent less than a minute ago] Assistant: Final Text \n"
        )
        result = post_process_llm_output(raw_text, endpoint_config, workflow_config)
        assert result == "Final Text"

    # Scenario B (Non-Streaming)
    def test_scenario_b_endpoint_prefix_removal(self, mocker):
        """Scenario B: Remove specific text using responseStartTextToRemoveEndpointWide."""
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=False)
        endpoint_config = {
            **BASE_ENDPOINT_CONFIG,
            "removeThinking": False,
            "removeCustomTextFromResponseStartEndpointWide": True,
            "responseStartTextToRemoveEndpointWide": ["analysis<|message|>"],
        }
        text = "analysis<|message|>Hi how are you?"
        result = post_process_llm_output(text, endpoint_config, BASE_WORKFLOW_CONFIG)
        assert result == "Hi how are you?"

    # Scenario C (Non-Streaming)
    def test_scenario_c_complex_tags_plus_assistant_prefix(self, mocker):
        """Scenario C: Complex thinking tags followed by 'Assistant:' prefix."""
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        text = (
            "<|channel|>analysis<|message|>The user just spoke to me. I'll say hi."
            "<|start|>assistant<|channel|>final<|message|> Assistant: Hello there!"
        )
        result = post_process_llm_output(text, COMPLEX_TAG_CONFIG, BASE_WORKFLOW_CONFIG)
        assert result == "Hello there!"

    # Scenario D (Non-Streaming)
    def test_scenario_d_endpoint_prefix_plus_assistant_prefix(self, mocker):
        """Scenario D: Endpoint-wide prefix followed by 'Assistant:' prefix."""
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        endpoint_config = {
            **BASE_ENDPOINT_CONFIG,
            "removeThinking": False,
            "removeCustomTextFromResponseStartEndpointWide": True,
            "responseStartTextToRemoveEndpointWide": ["analysis<|message|>"],
        }
        text = "analysis<|message|> Assistant: Hi how are you?"
        result = post_process_llm_output(text, endpoint_config, BASE_WORKFLOW_CONFIG)
        assert result == "Hi how are you?"

    def test_workflow_custom_prefix_removal(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=False)
        workflow_config = {
            **BASE_WORKFLOW_CONFIG,
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["First: ", "Second: "],
        }
        text = "Second: This is the content."
        result = post_process_llm_output(text, BASE_ENDPOINT_CONFIG, workflow_config)
        assert result == "This is the content."

    def test_endpoint_custom_prefix_removal_handles_stripping(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=False)
        endpoint_config = {
            **BASE_ENDPOINT_CONFIG,
            "removeCustomTextFromResponseStartEndpointWide": True,
            "responseStartTextToRemoveEndpointWide": ["  PrefixToStrip  "],
        }
        text = " PrefixToStrip This is the content."
        result = post_process_llm_output(text, endpoint_config, BASE_WORKFLOW_CONFIG)
        assert result == "This is the content."

    def test_timestamp_removal(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=False)
        workflow_config = {**BASE_WORKFLOW_CONFIG, "addDiscussionIdTimestampsForLLM": True}
        text_with_space = "[Sent less than a minute ago] This has a space."
        result_with_space = post_process_llm_output(text_with_space, BASE_ENDPOINT_CONFIG, workflow_config)
        assert result_with_space == "This has a space."
        text_no_space = "[Sent less than a minute ago]This has no space."
        result_no_space = post_process_llm_output(text_no_space, BASE_ENDPOINT_CONFIG, workflow_config)
        assert result_no_space == "This has no space."

    def test_assistant_prefix_removal(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        text = "Assistant: Some text"
        result = post_process_llm_output(text, BASE_ENDPOINT_CONFIG, BASE_WORKFLOW_CONFIG)
        assert result == "Some text"

    def test_assistant_prefix_not_removed_if_settings_off(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        text = "Assistant: Some text"
        result = post_process_llm_output(text, BASE_ENDPOINT_CONFIG, BASE_WORKFLOW_CONFIG)
        assert result == "Assistant: Some text"

    def test_final_trimming(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=False)
        endpoint_config = {**BASE_ENDPOINT_CONFIG, "trimBeginningAndEndLineBreaks": True}
        text = " \n  Some content surrounded by whitespace. \t\n "
        result = post_process_llm_output(text, endpoint_config, BASE_WORKFLOW_CONFIG)
        assert result == "Some content surrounded by whitespace."

    def test_no_final_trimming(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=False)
        endpoint_config = {**BASE_ENDPOINT_CONFIG, "trimBeginningAndEndLineBreaks": False}
        text = " \n  Some content surrounded by whitespace. \t\n "
        expected = "Some content surrounded by whitespace. \t\n "
        result = post_process_llm_output(text, endpoint_config, BASE_WORKFLOW_CONFIG)
        assert result == expected


class TestStripLeadingResponsePrefixes:
    """Direct tests for the shared prefix-strip helper used by both the
    streaming buffer processor and the non-streaming post-processor."""

    @pytest.mark.parametrize("input_text, expected_output", [
        ("Assistant: Hello", "Hello"),
        ("  Assistant:  Hi there", "Hi there"),
        ("No prefix here", "No prefix here"),
        ("Assistant:", ""),
    ])
    def test_assistant_prefix_cases(self, input_text, expected_output):
        assert strip_leading_response_prefixes(input_text, {}, {}, remove_assistant=True) == expected_output

    def test_assistant_prefix_left_alone_when_disabled(self):
        result = strip_leading_response_prefixes("Assistant: Hello", {}, {}, remove_assistant=False)
        assert result == "Assistant: Hello"

    def test_workflow_custom_text_accepts_bare_string_config(self):
        """responseStartTextToRemove may be a bare string instead of an array;
        it must be treated as a single prefix, not iterated character by character."""
        workflow_config = {
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": "WF: ",
        }
        assert strip_leading_response_prefixes("WF: hello", workflow_config, {},
                                               remove_assistant=False) == "hello"

    def test_endpoint_custom_text_accepts_bare_string_config(self):
        """responseStartTextToRemoveEndpointWide may be a bare string; the entry
        is whitespace-stripped before matching, like the array form."""
        endpoint_config = {
            "removeCustomTextFromResponseStartEndpointWide": True,
            "responseStartTextToRemoveEndpointWide": "  EP:  ",
        }
        assert strip_leading_response_prefixes("EP: hello", {}, endpoint_config,
                                               remove_assistant=False) == "hello"
