
import hashlib
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from Middleware.workflows.handlers.impl.context_compactor_handler import (
    ContextCompactorHandler,
    _get_compactor_lock,
    _compactor_locks,
    _compactor_locks_guard,
    _MAX_COMPACTOR_LOCKS,
)
from Middleware.workflows.models.execution_context import ExecutionContext


def _hash(content):
    """Helper to generate SHA-256 hash matching the handler's implementation."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _make_messages(count, token_size_per_msg=100):
    """
    Creates a list of alternating user/assistant messages.
    Each message has content of roughly the specified token size
    (using repeated words to control rough_estimate_token_length).
    """
    messages = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        # Each word ~1.35 tokens, so N words ~N*1.35*1.1 tokens after safety margin
        # For 100 tokens, ~67 words needed
        word_count = int(token_size_per_msg / 1.485) + 1
        content = " ".join([f"word{i}_{w}" for w in range(word_count)])
        messages.append({"role": role, "content": content})
    return messages


@pytest.fixture
def mock_variable_service():
    """Provides a mock WorkflowVariableManager."""
    return MagicMock()


@pytest.fixture
def handler(mock_variable_service):
    """Provides an instance of ContextCompactorHandler with mocked dependencies."""
    h = ContextCompactorHandler(
        workflow_manager=MagicMock(),
        workflow_variable_service=mock_variable_service,
    )
    return h


@pytest.fixture
def base_context(mock_variable_service):
    """Provides a basic ExecutionContext."""
    return ExecutionContext(
        request_id="req-test",
        workflow_id="wf-test",
        discussion_id="disc-test",
        config={"type": "ContextCompactor"},
        messages=[],
        stream=False,
        workflow_variable_service=mock_variable_service,
    )


@pytest.fixture
def sample_settings():
    """Standard settings dict for testing."""
    return {
        "endpointName": "test-endpoint",
        "preset": "test-preset",
        "maxResponseSizeInTokens": 500,
        "recentContextTokens": 300,
        "oldContextTokens": 300,
        "lookbackStartTurn": 2,
        "oldSectionSystemPrompt": "Summarize old section.",
        "oldSectionPrompt": "Messages: [MESSAGES_TO_SUMMARIZE]\nRecent: [RECENT_MESSAGES]",
        "neutralSummarySystemPrompt": "Summarize neutrally.",
        "neutralSummaryPrompt": "Messages: [MESSAGES_TO_SUMMARIZE]",
        "oldestUpdateSystemPrompt": "Update oldest summary.",
        "oldestUpdatePrompt": "Existing: [EXISTING_SUMMARY]\nNew: [NEW_CONTENT]",
    }


class TestCalculateBoundaries:
    """Tests for the _calculate_boundaries method."""

    def test_all_messages_fit_in_recent(self, handler):
        """When all messages fit within recentContextTokens, everything is recent."""
        messages = _make_messages(3, token_size_per_msg=50)
        boundaries = handler._calculate_boundaries(messages, 10000, 10000)
        assert boundaries["recent_start_idx"] == 0
        assert boundaries["old_start_idx"] == 0

    def test_messages_split_into_recent_and_old(self, handler):
        """When messages exceed recentContextTokens, they split into recent and old."""
        messages = _make_messages(10, token_size_per_msg=200)
        boundaries = handler._calculate_boundaries(messages, 400, 400)
        assert boundaries["recent_start_idx"] > 0
        assert boundaries["old_start_idx"] < boundaries["recent_start_idx"]

    def test_messages_split_into_three_sections(self, handler):
        """When messages exceed both windows, all three sections exist."""
        messages = _make_messages(30, token_size_per_msg=300)
        # Use windows large enough to hold a few messages each, but small enough
        # that not all messages fit. Each message's rough token estimate is ~500-700
        # due to character-based estimation on longer word strings.
        boundaries = handler._calculate_boundaries(messages, 2000, 2000)
        assert boundaries["old_start_idx"] > 0
        assert boundaries["recent_start_idx"] > boundaries["old_start_idx"]

    def test_empty_messages(self, handler):
        """Empty message list returns zero indices."""
        boundaries = handler._calculate_boundaries([], 1000, 1000)
        assert boundaries["recent_start_idx"] == 0
        assert boundaries["old_start_idx"] == 0


class TestShouldCompact:
    """Tests for the _should_compact method."""

    def test_first_run_no_existing_state(self, handler):
        """First run (no existing state) should trigger compaction."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 0, "recent_start_idx": 3}
        should, shifted = handler._should_compact(messages, boundaries, [])
        assert should is True
        assert shifted is False

    def test_nothing_in_old_window(self, handler):
        """When old_start_idx >= recent_start_idx, no compaction needed."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 3, "recent_start_idx": 3}
        should, shifted = handler._should_compact(messages, boundaries, [])
        assert should is False
        assert shifted is False

    def test_boundary_shifted(self, handler):
        """When the stored boundary hash differs from current, should compact with shift."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 1, "recent_start_idx": 3}
        old_state = [("old summary", "different_hash_1"), ("__boundary__", "different_hash_2")]
        should, shifted = handler._should_compact(messages, boundaries, old_state)
        assert should is True
        assert shifted is True

    def test_recent_hash_changed(self, handler):
        """When the recent boundary hash changes (new messages in Old window), should compact."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 1, "recent_start_idx": 3}
        old_boundary_hash = _hash(messages[1].get("content", ""))
        old_state = [("old summary", "different_recent_hash"), ("__boundary__", old_boundary_hash)]
        should, shifted = handler._should_compact(messages, boundaries, old_state)
        assert should is True
        assert shifted is False

    def test_no_changes_needed(self, handler):
        """When all hashes match, no compaction needed."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 1, "recent_start_idx": 3}
        old_boundary_hash = _hash(messages[1].get("content", ""))
        recent_boundary_hash = _hash(messages[2].get("content", ""))
        old_state = [("old summary", recent_boundary_hash), ("__boundary__", old_boundary_hash)]
        should, shifted = handler._should_compact(messages, boundaries, old_state)
        assert should is False
        assert shifted is False

    def test_no_changes_with_index_hash_format(self, handler):
        """When stored boundary uses idx:hash format and hash matches, no compaction needed."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 1, "recent_start_idx": 3}
        old_boundary_hash = _hash(messages[1].get("content", ""))
        recent_boundary_hash = _hash(messages[2].get("content", ""))
        old_state = [
            ("old summary", recent_boundary_hash),
            ("__boundary__", f"1:{old_boundary_hash}"),
        ]
        should, shifted = handler._should_compact(messages, boundaries, old_state)
        assert should is False
        assert shifted is False

    def test_boundary_shifted_with_index_hash_format(self, handler):
        """When stored boundary uses idx:hash format but hash differs, should compact with shift."""
        messages = _make_messages(5)
        boundaries = {"old_start_idx": 1, "recent_start_idx": 3}
        recent_boundary_hash = _hash(messages[2].get("content", ""))
        old_state = [
            ("old summary", recent_boundary_hash),
            ("__boundary__", f"1:different_hash"),
        ]
        should, shifted = handler._should_compact(messages, boundaries, old_state)
        assert should is True
        assert shifted is True


class TestHandle:
    """Tests for the main handle method."""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_no_settings_returns_empty(self, mock_load, mock_path, handler, base_context):
        """When settings can't be loaded, returns empty string."""
        mock_path.side_effect = Exception("No settings")
        result = handler.handle(base_context)
        assert result == ""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_no_discussion_id_returns_empty(self, mock_load, mock_path, handler, base_context, sample_settings):
        """When no discussion_id, returns empty string."""
        mock_load.return_value = sample_settings
        base_context.discussion_id = None
        result = handler.handle(base_context)
        assert result == ""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_too_short_conversation_returns_empty(self, mock_load, mock_path,
                                                  mock_read, handler, base_context, sample_settings):
        """Conversation too short after lookback returns empty/cached."""
        mock_load.return_value = sample_settings
        mock_read.return_value = []
        base_context.messages = _make_messages(3)
        result = handler.handle(base_context)
        assert result == ""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.update_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_first_compaction_creates_old_section(self, mock_load_config, mock_path,
                                                  mock_read, mock_update,
                                                  handler, base_context, sample_settings):
        """First-time compaction with enough messages creates Old section only."""
        mock_load_config.return_value = sample_settings
        mock_read.side_effect = [
            [],
            [],
            [("Old summary result", "hash1"), ("__boundary__", "hash2")],
            [],
        ]

        messages = _make_messages(15, token_size_per_msg=100)
        base_context.messages = messages

        with patch.object(handler, '_call_llm', return_value="Old summary result"):
            result = handler.handle(base_context)

        assert "<context_compactor_old>" in result
        assert "Old summary result" in result
        assert mock_update.call_count >= 1

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.update_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_no_compaction_returns_cached(self, mock_load_config, mock_path,
                                         mock_read, mock_update,
                                         handler, base_context, sample_settings):
        """When no compaction is triggered, returns cached summaries without LLM calls."""
        mock_load_config.return_value = sample_settings
        messages = _make_messages(15, token_size_per_msg=100)
        base_context.messages = messages

        working_messages = messages[:-2]
        boundaries = handler._calculate_boundaries(working_messages, 300, 300)

        old_idx = boundaries["old_start_idx"]
        recent_idx = boundaries["recent_start_idx"]

        old_boundary_hash = _hash(working_messages[old_idx].get("content", ""))
        recent_boundary_hash = _hash(working_messages[recent_idx - 1].get("content", ""))

        cached_old = [("Cached old summary", recent_boundary_hash), ("__boundary__", old_boundary_hash)]
        cached_oldest = [("Cached oldest summary", "some_hash")]

        mock_read.side_effect = [
            cached_old,
            cached_oldest,
            cached_old,
            cached_oldest,
        ]

        with patch.object(handler, '_call_llm') as mock_llm:
            result = handler.handle(base_context)
            mock_llm.assert_not_called()

        assert "Cached old summary" in result
        assert "Cached oldest summary" in result
        assert mock_update.call_count == 0


class TestRunCompaction:
    """Tests for the _run_compaction method."""

    def test_compaction_without_boundary_shift(self, handler, base_context, sample_settings):
        """When boundary hasn't shifted, only LLM call 1 runs."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 2, "recent_start_idx": 6}

        with patch.object(handler, '_call_llm', return_value="Summary") as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[], oldest_state=[],
                has_boundary_shifted=False, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 1
            mock_save.assert_called_once()
            assert mock_save.call_args[0][1] == "old"

    def test_compaction_with_boundary_shift(self, handler, base_context, sample_settings):
        """When boundary has shifted, all 3 LLM calls run.
        The old_state boundary hash must match a real message so the handler
        can locate the previous boundary position."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 3, "recent_start_idx": 7}
        prev_boundary_hash = _hash(messages[1].get("content", ""))

        with patch.object(handler, '_call_llm', return_value="Summary") as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[("old", "hash"), ("__boundary__", prev_boundary_hash)],
                oldest_state=[("oldest", "hash")],
                has_boundary_shifted=True, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 3
            assert mock_save.call_count == 2
            save_sections = [c[0][1] for c in mock_save.call_args_list]
            assert "old" in save_sections
            assert "oldest" in save_sections

    def test_compaction_shifted_messages_are_only_newly_shifted(self, handler, base_context, sample_settings):
        """Verify that only messages between the previous and current boundary are sent to the neutral summary."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 5, "recent_start_idx": 8}
        prev_boundary_hash = _hash(messages[2].get("content", ""))

        captured_shifted = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_shifted.append(prompt)
            return "Summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm), \
             patch.object(handler, '_save_state'):
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[("old", "hash"), ("__boundary__", prev_boundary_hash)],
                oldest_state=[("oldest", "hash")],
                has_boundary_shifted=True, discussion_id="disc-test"
            )

        neutral_prompt = captured_shifted[1]
        assert messages[2]["content"] in neutral_prompt
        assert messages[3]["content"] in neutral_prompt
        assert messages[4]["content"] in neutral_prompt
        assert messages[0]["content"] not in neutral_prompt

    def test_compaction_with_shift_but_no_oldest_messages(self, handler, base_context, sample_settings):
        """When boundary shifted but old_start_idx is 0, no shifted messages to process."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 0, "recent_start_idx": 5}

        with patch.object(handler, '_call_llm', return_value="Summary") as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[], oldest_state=[],
                has_boundary_shifted=True, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 1

    def test_compaction_with_index_hash_fast_lookup(self, handler, base_context, sample_settings):
        """When stored index:hash matches the message at that index, uses fast path."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 3, "recent_start_idx": 7}
        prev_boundary_hash = _hash(messages[1].get("content", ""))

        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "Summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm) as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[("old", "hash"), ("__boundary__", f"1:{prev_boundary_hash}")],
                oldest_state=[("oldest", "hash")],
                has_boundary_shifted=True, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 3
            # The neutral summary (call 2) should include messages from index 1 to 3
            neutral_prompt = captured_prompts[1]
            assert messages[1]["content"] in neutral_prompt
            assert messages[2]["content"] in neutral_prompt
            assert messages[0]["content"] not in neutral_prompt

    def test_compaction_with_index_hash_stale_index(self, handler, base_context, sample_settings):
        """When stored index is out of range but hash exists in messages, falls back to scan."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 5, "recent_start_idx": 8}
        # Hash of message at index 2, but stored index is 99 (out of range)
        target_hash = _hash(messages[2].get("content", ""))

        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "Summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm) as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[("old", "hash"), ("__boundary__", f"99:{target_hash}")],
                oldest_state=[("oldest", "hash")],
                has_boundary_shifted=True, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 3
            # Scan should find message 2, so shifted messages are index 2..4
            neutral_prompt = captured_prompts[1]
            assert messages[2]["content"] in neutral_prompt
            assert messages[3]["content"] in neutral_prompt
            assert messages[4]["content"] in neutral_prompt
            assert messages[0]["content"] not in neutral_prompt
            assert messages[1]["content"] not in neutral_prompt

    def test_compaction_with_index_hash_content_mismatch(self, handler, base_context, sample_settings):
        """When stored index points to a different message, falls back to scan and finds the right one."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 5, "recent_start_idx": 8}
        # Hash of message 3, but stored at index 1 (which has different content)
        target_hash = _hash(messages[3].get("content", ""))

        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "Summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm) as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[("old", "hash"), ("__boundary__", f"1:{target_hash}")],
                oldest_state=[("oldest", "hash")],
                has_boundary_shifted=True, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 3
            # Scan should find message 3, so shifted messages are index 3..4
            neutral_prompt = captured_prompts[1]
            assert messages[3]["content"] in neutral_prompt
            assert messages[4]["content"] in neutral_prompt
            assert messages[0]["content"] not in neutral_prompt
            assert messages[1]["content"] not in neutral_prompt
            assert messages[2]["content"] not in neutral_prompt

    def test_compaction_with_index_hash_parse_failure(self, handler, base_context, sample_settings):
        """When stored index is not an integer, exercises ValueError catch and falls back to scan."""
        messages = _make_messages(10, token_size_per_msg=100)
        boundaries = {"old_start_idx": 4, "recent_start_idx": 7}
        # The stored value has a colon but the index part is not a valid int.
        # In the ValueError handler, it scans for stored_value (the full string
        # "notanint:hash") which won't match any message hash, so prev_old_start_idx stays 0.
        stored_value = f"notanint:{_hash(messages[2].get('content', ''))}"

        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "Summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm) as mock_llm, \
             patch.object(handler, '_save_state') as mock_save:
            handler._run_compaction(
                context=base_context, settings=sample_settings,
                messages=messages, boundaries=boundaries,
                old_state=[("old", "hash"), ("__boundary__", stored_value)],
                oldest_state=[("oldest", "hash")],
                has_boundary_shifted=True, discussion_id="disc-test"
            )
            assert mock_llm.call_count == 3
            # ValueError handler scans for stored_value (the full "notanint:hash"
            # string) against message hashes. No message hash equals the full
            # stored_value, so prev_old_start_idx remains 0.
            # Shifted messages: index 0..3
            neutral_prompt = captured_prompts[1]
            assert messages[0]["content"] in neutral_prompt
            assert messages[1]["content"] in neutral_prompt
            assert messages[2]["content"] in neutral_prompt
            assert messages[3]["content"] in neutral_prompt


class TestGenerateOldSection:
    """Tests for _generate_old_section."""

    def test_placeholder_replacement(self, handler, base_context, sample_settings):
        """Verifies that [MESSAGES_TO_SUMMARIZE] and [RECENT_MESSAGES] placeholders are replaced."""
        old_messages = [{"role": "user", "content": "old msg"}]
        recent_messages = [{"role": "user", "content": "recent msg"}]

        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm):
            handler._generate_old_section(old_messages, recent_messages, sample_settings, base_context)

        assert len(captured_prompts) == 1
        assert "old msg" in captured_prompts[0]
        assert "recent msg" in captured_prompts[0]
        assert "[MESSAGES_TO_SUMMARIZE]" not in captured_prompts[0]
        assert "[RECENT_MESSAGES]" not in captured_prompts[0]


class TestGenerateNeutralSummary:
    """Tests for _generate_neutral_summary."""

    def test_placeholder_replacement(self, handler, base_context, sample_settings):
        """Verifies [MESSAGES_TO_SUMMARIZE] is replaced."""
        shifted_messages = [{"role": "assistant", "content": "shifted content"}]

        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "neutral summary"

        with patch.object(handler, '_call_llm', side_effect=capture_llm):
            handler._generate_neutral_summary(shifted_messages, sample_settings, base_context)

        assert "shifted content" in captured_prompts[0]
        assert "[MESSAGES_TO_SUMMARIZE]" not in captured_prompts[0]


class TestUpdateOldestSection:
    """Tests for _update_oldest_section."""

    def test_placeholder_replacement(self, handler, base_context, sample_settings):
        """Verifies [EXISTING_SUMMARY] and [NEW_CONTENT] are replaced."""
        captured_prompts = []

        def capture_llm(system_prompt, prompt, settings, context):
            captured_prompts.append(prompt)
            return "updated oldest"

        with patch.object(handler, '_call_llm', side_effect=capture_llm):
            handler._update_oldest_section("existing text", "new text", sample_settings, base_context)

        assert "existing text" in captured_prompts[0]
        assert "new text" in captured_prompts[0]
        assert "[EXISTING_SUMMARY]" not in captured_prompts[0]
        assert "[NEW_CONTENT]" not in captured_prompts[0]


class TestCallLlm:
    """Tests for _call_llm."""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.LlmHandlerService")
    def test_calls_llm_with_message_collection(self, mock_service_class, base_context, sample_settings):
        """When LLM takes message collections, sends system+user messages."""
        mock_llm = MagicMock()
        mock_llm.takes_message_collection = True
        mock_llm.llm.get_response_from_llm.return_value = "response"

        mock_service_instance = MagicMock()
        mock_service_instance.load_model_from_config.return_value = mock_llm
        mock_service_class.return_value = mock_service_instance

        handler = ContextCompactorHandler(
            workflow_manager=MagicMock(),
            workflow_variable_service=MagicMock(),
        )
        result = handler._call_llm("sys prompt", "user prompt", sample_settings, base_context)

        assert result == "response"
        call_args = mock_llm.llm.get_response_from_llm.call_args
        collection = call_args[0][0]
        assert len(collection) == 2
        assert collection[0]["role"] == "system"
        assert collection[1]["role"] == "user"

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.LlmHandlerService")
    def test_calls_llm_without_message_collection(self, mock_service_class, base_context, sample_settings):
        """When LLM doesn't take message collections, sends system_prompt and prompt."""
        mock_llm = MagicMock()
        mock_llm.takes_message_collection = False
        mock_llm.llm.get_response_from_llm.return_value = "response"

        mock_service_instance = MagicMock()
        mock_service_instance.load_model_from_config.return_value = mock_llm
        mock_service_class.return_value = mock_service_instance

        handler = ContextCompactorHandler(
            workflow_manager=MagicMock(),
            workflow_variable_service=MagicMock(),
        )
        result = handler._call_llm("sys prompt", "user prompt", sample_settings, base_context)

        assert result == "response"
        mock_llm.llm.get_response_from_llm.assert_called_once_with(
            system_prompt="sys prompt",
            prompt="user prompt",
            llm_takes_images=False,
            request_id="req-test"
        )


class TestFormatOutput:
    """Tests for _format_output."""

    def test_both_sections(self):
        """Output includes both sections when both have content."""
        result = ContextCompactorHandler._format_output("old text", "oldest text")
        assert "<context_compactor_old>old text</context_compactor_old>" in result
        assert "<context_compactor_oldest>oldest text</context_compactor_oldest>" in result

    def test_old_section_only(self):
        """Output includes only old section when oldest is empty."""
        result = ContextCompactorHandler._format_output("old text", "")
        assert "<context_compactor_old>" in result
        assert "<context_compactor_oldest>" not in result

    def test_oldest_section_only(self):
        """Output includes only oldest section when old is empty."""
        result = ContextCompactorHandler._format_output("", "oldest text")
        assert "<context_compactor_old>" not in result
        assert "<context_compactor_oldest>" in result

    def test_both_empty(self):
        """Output is empty when both sections are empty."""
        result = ContextCompactorHandler._format_output("", "")
        assert result == ""


class TestMessagesToText:
    """Tests for _messages_to_text."""

    def test_converts_messages(self):
        """Converts messages to role: content format."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = ContextCompactorHandler._messages_to_text(messages)
        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_empty_messages(self):
        """Returns empty string for empty list."""
        result = ContextCompactorHandler._messages_to_text([])
        assert result == ""


class TestHashMessageContent:
    """Tests for _hash_message_content."""

    def test_consistent_hashing(self):
        """Same content always produces same hash."""
        hash1 = ContextCompactorHandler._hash_message_content("test content")
        hash2 = ContextCompactorHandler._hash_message_content("test content")
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Different content produces different hashes."""
        hash1 = ContextCompactorHandler._hash_message_content("content A")
        hash2 = ContextCompactorHandler._hash_message_content("content B")
        assert hash1 != hash2


class TestLookbackSkipping:
    """Tests for lookback start turn skipping behavior."""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_lookback_skips_last_n_messages(self, mock_load_config, mock_path,
                                           mock_read, handler, base_context):
        """Verifies that lookbackStartTurn skips the last N messages."""
        settings = {
            "endpointName": "test-endpoint",
            "preset": "test-preset",
            "maxResponseSizeInTokens": 500,
            "recentContextTokens": 100,
            "oldContextTokens": 100,
                "lookbackStartTurn": 3,
        }
        mock_load_config.return_value = settings
        mock_read.return_value = []

        messages = _make_messages(5, token_size_per_msg=50)
        base_context.messages = messages

        with patch.object(handler, '_calculate_boundaries', wraps=handler._calculate_boundaries) as mock_calc:
            with patch.object(handler, '_should_compact', return_value=(False, False)):
                with patch.object(handler, '_return_cached_output', return_value=""):
                    handler.handle(base_context)
                    assert mock_calc.called
                    called_messages = mock_calc.call_args[0][0]
                    assert len(called_messages) == 2

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_context_compactor_settings_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.load_config")
    def test_lookback_zero_uses_all_messages(self, mock_load_config, mock_path,
                                            mock_read, handler, base_context):
        """When lookbackStartTurn is 0, all messages are used."""
        settings = {
            "endpointName": "test-endpoint",
            "preset": "test-preset",
            "maxResponseSizeInTokens": 500,
            "recentContextTokens": 100,
            "oldContextTokens": 100,
                "lookbackStartTurn": 0,
        }
        mock_load_config.return_value = settings
        mock_read.return_value = []

        messages = _make_messages(5, token_size_per_msg=50)
        base_context.messages = messages

        with patch.object(handler, '_calculate_boundaries', wraps=handler._calculate_boundaries) as mock_calc:
            with patch.object(handler, '_should_compact', return_value=(False, False)):
                with patch.object(handler, '_return_cached_output', return_value=""):
                    handler.handle(base_context)
                    assert mock_calc.called
                    called_messages = mock_calc.call_args[0][0]
                    assert len(called_messages) == 5


class TestFilePersistence:
    """Tests for file persistence round-trip."""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.update_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_save_state_old(self, mock_oldest_path, mock_old_path, mock_update, handler):
        """Saving old state writes to the correct file path."""
        mock_old_path.return_value = "/path/to/disc_context_compactor_old.json"
        chunks = [("summary", "hash123")]
        handler._save_state("disc-test", "old", chunks)
        mock_update.assert_called_once_with(
            chunks,
            "/path/to/disc_context_compactor_old.json",
            mode="overwrite",
            encryption_key=None
        )

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.update_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_save_state_oldest(self, mock_oldest_path, mock_old_path, mock_update, handler):
        """Saving oldest state writes to the correct file path."""
        mock_oldest_path.return_value = "/path/to/disc_context_compactor_oldest.json"
        chunks = [("oldest summary", "hash456")]
        handler._save_state("disc-test", "oldest", chunks)
        mock_update.assert_called_once_with(
            chunks,
            "/path/to/disc_context_compactor_oldest.json",
            mode="overwrite",
            encryption_key=None
        )

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_load_state_old(self, mock_oldest_path, mock_old_path, mock_read, handler):
        """Loading old state reads from the correct file path."""
        mock_old_path.return_value = "/path/to/disc_context_compactor_old.json"
        mock_read.return_value = [("summary", "hash")]
        result = handler._load_state("disc-test", "old")
        mock_read.assert_called_once_with("/path/to/disc_context_compactor_old.json", encryption_key=None)
        assert result == [("summary", "hash")]

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_load_state_oldest(self, mock_oldest_path, mock_old_path, mock_read, handler):
        """Loading oldest state reads from the correct file path."""
        mock_oldest_path.return_value = "/path/to/disc_context_compactor_oldest.json"
        mock_read.return_value = [("oldest summary", "hash")]
        result = handler._load_state("disc-test", "oldest")
        mock_read.assert_called_once_with("/path/to/disc_context_compactor_oldest.json", encryption_key=None)
        assert result == [("oldest summary", "hash")]


class TestReturnCachedOutput:
    """Tests for _return_cached_output."""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_returns_formatted_output(self, mock_oldest_path, mock_old_path, mock_read, handler):
        """Returns correctly formatted output when both sections have data."""
        mock_old_path.return_value = "/path/old.json"
        mock_oldest_path.return_value = "/path/oldest.json"
        mock_read.side_effect = [
            [("Old summary text", "h1"), ("__boundary__", "h2")],
            [("Oldest summary text", "h3")],
        ]
        result = handler._return_cached_output("disc-test")
        assert "<context_compactor_old>Old summary text</context_compactor_old>" in result
        assert "<context_compactor_oldest>Oldest summary text</context_compactor_oldest>" in result

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_returns_empty_when_no_data(self, mock_oldest_path, mock_old_path, mock_read, handler):
        """Returns empty string when no summaries exist."""
        mock_old_path.return_value = "/path/old.json"
        mock_oldest_path.return_value = "/path/oldest.json"
        mock_read.side_effect = [[], []]
        result = handler._return_cached_output("disc-test")
        assert result == ""

    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.read_chunks_with_hashes")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_old_file_path")
    @patch("Middleware.workflows.handlers.impl.context_compactor_handler.get_discussion_context_compactor_oldest_file_path")
    def test_skips_boundary_marker(self, mock_oldest_path, mock_old_path, mock_read, handler):
        """The __boundary__ marker is not included in the output summary."""
        mock_old_path.return_value = "/path/old.json"
        mock_oldest_path.return_value = "/path/oldest.json"
        mock_read.side_effect = [
            [("Real summary", "h1"), ("__boundary__", "h2")],
            [],
        ]
        result = handler._return_cached_output("disc-test")
        assert "__boundary__" not in result
        assert "Real summary" in result


class TestGetCompactorLock:
    """Tests for the _get_compactor_lock module-level function."""

    def setup_method(self):
        """Clear the global lock dict before each test to ensure isolation."""
        with _compactor_locks_guard:
            _compactor_locks.clear()

    def teardown_method(self):
        """Clear the global lock dict after each test."""
        with _compactor_locks_guard:
            _compactor_locks.clear()

    def test_returns_lock_for_new_discussion(self):
        """A Lock is created and returned for a previously unseen discussion ID."""
        lock = _get_compactor_lock("disc-1")
        assert isinstance(lock, threading.Lock)

    def test_returns_same_lock_for_same_discussion(self):
        """Calling twice with the same ID returns the identical Lock object."""
        lock1 = _get_compactor_lock("disc-1")
        lock2 = _get_compactor_lock("disc-1")
        assert lock1 is lock2

    def test_returns_different_locks_for_different_discussions(self):
        """Different discussion IDs get different Lock objects."""
        lock1 = _get_compactor_lock("disc-1")
        lock2 = _get_compactor_lock("disc-2")
        assert lock1 is not lock2

    def test_cap_evicts_oldest_unlocked_entry_when_full(self):
        """When the dict reaches _MAX_COMPACTOR_LOCKS, the oldest unlocked entry is evicted."""
        # Fill to the cap
        for i in range(_MAX_COMPACTOR_LOCKS):
            _get_compactor_lock(f"disc-{i}")

        assert len(_compactor_locks) == _MAX_COMPACTOR_LOCKS

        # Adding one more should evict disc-0 (oldest) and stay at the cap
        _get_compactor_lock("disc-new")
        assert len(_compactor_locks) <= _MAX_COMPACTOR_LOCKS
        assert "disc-0" not in _compactor_locks
        assert "disc-new" in _compactor_locks

    def test_cap_does_not_evict_locked_entries(self):
        """An entry whose lock is currently held is not evicted."""
        for i in range(_MAX_COMPACTOR_LOCKS):
            _get_compactor_lock(f"disc-{i}")

        # Hold the oldest lock so it cannot be evicted
        oldest_lock = _compactor_locks["disc-0"]
        oldest_lock.acquire()
        try:
            _get_compactor_lock("disc-new")
            # disc-0 must still be present since it was locked
            assert "disc-0" in _compactor_locks
        finally:
            oldest_lock.release()
