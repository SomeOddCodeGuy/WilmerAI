import pytest

# NOTE: Imports from Middleware.* assume the pytest.ini configuration (pythonpath = .)
# is correctly applied in the environment where these tests are executed.
from Middleware.utilities.streaming_utils import (
    StreamingThinkRemover,
    post_process_llm_output,
    remove_thinking_from_text,
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

    @pytest.mark.parametrize("text_input, config_override, expected_output", [
        # Standard mode, successful removal
        ("Prefix <think>block</think> Suffix", {}, "Prefix  Suffix"),
        # Standard mode, case-insensitive
        ("Hello <THINK>block</THINK> world", {}, "Hello  world"),
        # Standard mode, no closing tag (should not remove)
        ("Data <think>is incomplete", {}, "Data <think>is incomplete"),
        # Standard mode, opening tag outside grace period (should not remove)
        (" " * 101 + "<think>block</think>", {"openingTagGracePeriod": 100}, " " * 101 + "<think>block</think>"),
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


class TestPostProcessLlmOutput:
    """Tests for the main cleaning orchestrator function post_process_llm_output."""

    def test_full_processing_order(self, mocker):
        """Verify all rules are applied in the correct sequence."""
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        mock_remove_prefix = mocker.patch('Middleware.api.api_helpers.remove_assistant_prefix',
                                          return_value="Final Text \n")
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
        mock_remove_prefix.assert_called_once_with("Assistant: Final Text \n")

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
        mocker.patch('Middleware.api.api_helpers.remove_assistant_prefix',
                     side_effect=lambda x: x[len("Assistant:"):].lstrip())
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
        mocker.patch('Middleware.api.api_helpers.remove_assistant_prefix',
                     side_effect=lambda x: x[len("Assistant:"):].lstrip())
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

    def test_assistant_prefix_removal_calls_helper(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        mock_helper = mocker.patch('Middleware.api.api_helpers.remove_assistant_prefix', return_value="Cleaned Text")
        text = "Assistant: Some text"
        result = post_process_llm_output(text, BASE_ENDPOINT_CONFIG, BASE_WORKFLOW_CONFIG)
        assert result == "Cleaned Text"
        mock_helper.assert_called_once_with("Assistant: Some text")

    def test_assistant_prefix_not_removed_if_settings_off(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_user_assistant', return_value=False)
        mocker.patch('Middleware.utilities.config_utils.get_is_chat_complete_add_missing_assistant', return_value=True)
        mock_remove_prefix = mocker.patch('Middleware.api.api_helpers.remove_assistant_prefix')
        text = "Assistant: Some text"
        result = post_process_llm_output(text, BASE_ENDPOINT_CONFIG, BASE_WORKFLOW_CONFIG)
        assert result == "Assistant: Some text"
        mock_remove_prefix.assert_not_called()

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
