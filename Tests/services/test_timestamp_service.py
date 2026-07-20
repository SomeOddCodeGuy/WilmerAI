# We need the real datetime module/class for comparisons, internal logic, and functional implementations in mocks
from datetime import datetime as original_datetime, timedelta

import pytest

# Import the service, the new placeholder constant, and the module-level helper
from Middleware.services.timestamp_service import TimestampService, PLACEHOLDER_HASH, \
    _is_generation_prompt

# ##################################
# ##### Fixtures and Constants
# ##################################
# A fixed point in time for predictable tests
MOCK_NOW = original_datetime(2025, 9, 21, 12, 0, 0)
TS_FORMAT = "%A, %Y-%m-%d %H:%M:%S"


@pytest.fixture
def mock_dependencies(mocker):
    """Mocks all external dependencies for the TimestampService."""
    # Patching file system and hashing utilities
    mock_get_path = mocker.patch('Middleware.services.timestamp_service.get_discussion_timestamp_file_path')
    mock_load_file = mocker.patch('Middleware.services.timestamp_service.load_timestamp_file')
    mock_save_file = mocker.patch('Middleware.services.timestamp_service.save_timestamp_file')
    mock_hash = mocker.patch('Middleware.services.timestamp_service.hash_single_message')

    # Mocking datetime utilities with functional implementations for predictable logic
    def _format_dt(dt_obj):
        return "(" + dt_obj.strftime(TS_FORMAT) + ")"

    def _current_ts():
        return _format_dt(MOCK_NOW)

    def _parse_ts(ts_str):
        if not isinstance(ts_str, str) or not ts_str:
            return None
        try:
            return original_datetime.strptime(ts_str.strip("() "), TS_FORMAT)
        except ValueError:
            return None

    def _add_seconds_ts(ts_str, seconds):
        dt = _parse_ts(ts_str)
        if dt:
            return _format_dt(dt + timedelta(seconds=seconds))
        return ts_str

    # Patch the utilities used in the service
    mocker.patch('Middleware.services.timestamp_service.current_timestamp', side_effect=_current_ts)
    mock_format_relative_ago = mocker.patch('Middleware.services.timestamp_service.format_relative_time_ago')
    mock_format_relative_string = mocker.patch('Middleware.services.timestamp_service.format_relative_time_string')
    mocker.patch('Middleware.services.timestamp_service.parse_timestamp_string', side_effect=_parse_ts)
    mocker.patch('Middleware.services.timestamp_service.add_seconds_to_timestamp', side_effect=_add_seconds_ts)

    # Set a default return value for the path mock
    mock_get_path.return_value = "/mock/path/timestamps.json"

    return {
        "get_path": mock_get_path,
        "load_file": mock_load_file,
        "save_file": mock_save_file,
        "hash": mock_hash,
        "MOCK_NOW": MOCK_NOW,
        "format_ago": mock_format_relative_ago,
        "format_string": mock_format_relative_string,
    }


@pytest.fixture
def timestamp_service():
    """Provides a clean instance of TimestampService for each test."""
    return TimestampService()


# ##################################
# ##### Test Helper Functions
# ##################################
class TestTimestampHelpers:
    """Tests the standalone helper functions in the module."""

    @pytest.mark.parametrize("content, expected", [
        ("Roland:", True),
        ("Roland: ", True),
        ("  Roland:  ", True),
        (
                "A very long message that happens to end with a colon but is over 100 characters long........................................................:",
                False),
        ("Roland", False),
        ("", False),
    ])
    def test_is_generation_prompt(self, content, expected):
        message = {'content': content}
        assert _is_generation_prompt(message) == expected


# ##################################
# ##### Test Class
# ##################################
class TestTimestampService:
    """Test suite for the TimestampService."""

    # ##########################################
    # ##### Tests for placeholder methods
    # ##########################################
    def test_save_placeholder_timestamp(self, timestamp_service, mock_dependencies):
        """Verifies that a placeholder timestamp is correctly saved."""
        mock_dependencies["load_file"].return_value = {}
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"

        timestamp_service.save_placeholder_timestamp("id")

        expected_saved_data = {PLACEHOLDER_HASH: T_NOW_STR}
        mock_dependencies["save_file"].assert_called_once_with(
            mock_dependencies["get_path"].return_value,
            expected_saved_data,
            encryption_key=None
        )

    def test_commit_assistant_response_success(self, timestamp_service, mock_dependencies):
        """Tests that a placeholder is correctly committed to a new content hash."""
        T_PLACEHOLDER = "(Placeholder_Time)"
        mock_dependencies["load_file"].return_value = {PLACEHOLDER_HASH: T_PLACEHOLDER}
        mock_dependencies["hash"].return_value = "new_hash"
        content = "Final response"

        timestamp_service.commit_assistant_response("id", content)

        expected_saved_data = {"new_hash": T_PLACEHOLDER}
        mock_dependencies["save_file"].assert_called_once_with(
            mock_dependencies["get_path"].return_value,
            expected_saved_data,
            encryption_key=None
        )

    def test_commit_assistant_response_no_placeholder(self, timestamp_service, mock_dependencies):
        """Tests fallback behavior: commit saves with current time if no placeholder exists."""
        mock_dependencies["load_file"].return_value = {}
        mock_dependencies["hash"].return_value = "new_hash"
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"

        timestamp_service.commit_assistant_response("id", "content")

        expected_saved_data = {"new_hash": T_NOW_STR}
        mock_dependencies["save_file"].assert_called_once_with(
            mock_dependencies["get_path"].return_value,
            expected_saved_data,
            encryption_key=None
        )

    def test_commit_assistant_response_empty_content(self, timestamp_service, mock_dependencies):
        """Tests that an empty response clears the placeholder without creating a new hash."""
        mock_dependencies["load_file"].return_value = {PLACEHOLDER_HASH: "(Some_Time)"}

        timestamp_service.commit_assistant_response("id", "")

        mock_dependencies["hash"].assert_not_called()
        # The file is saved, but it's now empty.
        mock_dependencies["save_file"].assert_called_once_with(
            mock_dependencies["get_path"].return_value, {},
            encryption_key=None
        )

    def test_commit_assistant_response_empty_content_no_placeholder_no_save(self, timestamp_service,
                                                                            mock_dependencies):
        """Empty content with no pending placeholder writes nothing at all."""
        mock_dependencies["load_file"].return_value = {"hash1": "(T_Old)"}

        timestamp_service.commit_assistant_response("id", "")

        mock_dependencies["hash"].assert_not_called()
        mock_dependencies["save_file"].assert_not_called()

    # ##########################################
    # ##### Tests for resolve_and_track_history
    # ##########################################
    def test_resolve_and_track_history_resolves_orphaned_placeholder(self, timestamp_service, mock_dependencies):
        """Tests that resolve_and_track_history correctly applies a leftover placeholder."""
        T_PLACEHOLDER = f"({(MOCK_NOW - timedelta(minutes=10)).strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Previous message'},
            {'role': 'assistant', 'content': 'Response that crashed'}
        ]
        mock_dependencies["load_file"].return_value = {PLACEHOLDER_HASH: T_PLACEHOLDER}
        # Phase 0: hash for assistant message resolution, Phase 1: backward iteration (assistant, then user)
        mock_dependencies["hash"].side_effect = ['crashed_hash', 'crashed_hash', 'user_hash']

        timestamp_service.resolve_and_track_history(messages, "convo")

        # The file should be saved with the resolved placeholder and the backfilled user message
        final_saved_data = {
            'crashed_hash': T_PLACEHOLDER,
            'user_hash': f"({(original_datetime.strptime(T_PLACEHOLDER.strip('() '), TS_FORMAT) - timedelta(seconds=1)).strftime(TS_FORMAT)})"
        }
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == final_saved_data

    def test_resolve_and_track_new_conversation(self, timestamp_service, mock_dependencies):
        """Tests chronological backfill for a brand new conversation."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        T_NOW_M1S = f"({(MOCK_NOW - timedelta(seconds=1)).strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Msg1'},
            {'role': 'assistant', 'content': 'Msg2'}
        ]
        mock_dependencies["load_file"].return_value = {}
        mock_dependencies["hash"].side_effect = ['hash2', 'hash1']  # Hashed backwards during Phase 1

        timestamp_service.resolve_and_track_history(messages, "convo")

        expected_saved_data = {"hash1": T_NOW_M1S, "hash2": T_NOW_STR}
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_resolve_and_track_generation_prompt_skip(self, timestamp_service, mock_dependencies):
        """Tests that a generation prompt as the final message is skipped."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Msg1_New'},
            {'role': 'assistant', 'content': "Character:"}
        ]
        mock_dependencies["load_file"].return_value = {}
        mock_dependencies["hash"].side_effect = ['hash1']  # Only called once for user message

        timestamp_service.resolve_and_track_history(messages, "convo")

        assert mock_dependencies["hash"].call_count == 1
        expected_saved_data = {"hash1": T_NOW_STR}
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_resolve_and_track_cleans_legacy_placeholder(self, timestamp_service, mock_dependencies):
        """Ensures a legacy placeholder is removed, forcing a save even with no new messages."""
        T_OLD = f"({(MOCK_NOW - timedelta(days=1)).strftime(TS_FORMAT)})"
        messages = [{'role': 'user', 'content': 'Msg1'}]
        mock_dependencies["load_file"].return_value = {"hash1": T_OLD, PLACEHOLDER_HASH: "(T_Stale)"}
        mock_dependencies["hash"].return_value = 'hash1'

        timestamp_service.resolve_and_track_history(messages, "convo")

        expected_saved_data = {"hash1": T_OLD}
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_resolve_and_track_ignores_system_messages(self, timestamp_service, mock_dependencies):
        """Ensures system messages are neither hashed nor timestamped."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [
            {'role': 'system', 'content': 'System instruction'},
            {'role': 'user', 'content': 'User message'}
        ]
        mock_dependencies["load_file"].return_value = {}
        mock_dependencies["hash"].return_value = 'hash_user'

        timestamp_service.resolve_and_track_history(messages, "convo")

        mock_dependencies["hash"].assert_called_once_with(messages[1])
        expected_saved_data = {"hash_user": T_NOW_STR}
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_resolve_and_track_mixed_known_unknown_anchor_adoption(self, timestamp_service, mock_dependencies):
        """
        Backward iteration must adopt a known message's timestamp as the anchor:
        an unknown message OLDER than a known one gets known_time - 1s, not
        now - 2s.
        """
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        T_MID = f"({(MOCK_NOW - timedelta(minutes=10)).strftime(TS_FORMAT)})"
        T_MID_M1S = f"({(MOCK_NOW - timedelta(minutes=10, seconds=1)).strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Untracked old message'},
            {'role': 'assistant', 'content': 'Tracked middle message'},
            {'role': 'user', 'content': 'Untracked new message'}
        ]
        mock_dependencies["load_file"].return_value = {'hash_mid': T_MID}
        # Phase 1 iterates newest-to-oldest.
        mock_dependencies["hash"].side_effect = ['hash_new', 'hash_mid', 'hash_old']

        timestamp_service.resolve_and_track_history(messages, "convo")

        expected_saved_data = {
            'hash_new': T_NOW_STR,  # Anchored to "now"
            'hash_mid': T_MID,  # Already known, unchanged; becomes the new anchor
            'hash_old': T_MID_M1S,  # Adopts the known anchor minus one second
        }
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_resolve_placeholder_unresolvable_without_assistant_message(self, timestamp_service, mock_dependencies,
                                                                         mocker):
        """
        When a placeholder is pending but no assistant message exists in the
        history, a warning is logged, the placeholder is removed, and the file
        is still saved.
        """
        mock_warning = mocker.patch('Middleware.services.timestamp_service.logger.warning')
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [
            {'role': 'system', 'content': 'System instruction'},
            {'role': 'user', 'content': 'Hello'}
        ]
        mock_dependencies["load_file"].return_value = {PLACEHOLDER_HASH: "(T_Stale)"}
        mock_dependencies["hash"].return_value = 'hash_user'

        timestamp_service.resolve_and_track_history(messages, "convo")

        mock_warning.assert_called_once()
        assert "Could not find a suitable assistant message" in mock_warning.call_args[0][0]
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert PLACEHOLDER_HASH not in args[1]
        assert args[1] == {'hash_user': T_NOW_STR}

    # ##########################################
    # ##### Tests for format_messages_with_timestamps
    # ##########################################
    def test_format_messages_basic(self, timestamp_service, mock_dependencies):
        """Tests basic message formatting with timestamps."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        T_NOW_M1S = f"({(MOCK_NOW - timedelta(seconds=1)).strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Msg1'},
            {'role': 'assistant', 'content': 'Msg2'}
        ]
        mock_dependencies["load_file"].return_value = {
            "hash1": T_NOW_M1S,
            "hash2": T_NOW_STR
        }
        mock_dependencies["hash"].side_effect = ['hash1', 'hash2']

        result = timestamp_service.format_messages_with_timestamps(messages, "convo")

        assert result[0]['content'] == f"{T_NOW_M1S} Msg1"
        assert result[1]['content'] == f"{T_NOW_STR} Msg2"

    def test_format_messages_with_relative_time(self, timestamp_service, mock_dependencies):
        """Verifies that format_relative_time_ago is used when requested."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [{'role': 'user', 'content': 'Hello again'}]
        mock_dependencies["load_file"].return_value = {"user_hash": T_NOW_STR}
        mock_dependencies["hash"].return_value = 'user_hash'
        mock_dependencies["format_ago"].return_value = "[Sent just now]"

        result = timestamp_service.format_messages_with_timestamps(messages, "convo", use_relative_time=True)

        mock_dependencies["format_ago"].assert_called_with(T_NOW_STR)
        assert result[0]['content'] == "[Sent just now] Hello again"

    def test_format_messages_prevents_double_prepend(self, timestamp_service, mock_dependencies):
        """Ensures a timestamp is not added to content that already has it."""
        T_OLD = f"({(MOCK_NOW - timedelta(days=1)).strftime(TS_FORMAT)})"
        messages = [{'role': 'user', 'content': f'{T_OLD} Msg1'}]
        mock_dependencies["load_file"].return_value = {"hash1": T_OLD}
        mock_dependencies["hash"].return_value = 'hash1'

        result = timestamp_service.format_messages_with_timestamps(messages, "convo")

        assert result[0]['content'] == f"{T_OLD} Msg1"  # Unchanged

    def test_format_messages_skips_generation_prompt(self, timestamp_service, mock_dependencies):
        """Tests that a generation prompt as the final message is not formatted."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Msg1'},
            {'role': 'assistant', 'content': "Character:"}
        ]
        mock_dependencies["load_file"].return_value = {"hash1": T_NOW_STR}
        mock_dependencies["hash"].side_effect = ['hash1']

        result = timestamp_service.format_messages_with_timestamps(messages, "convo")

        assert result[0]['content'] == f"{T_NOW_STR} Msg1"
        assert result[1]['content'] == "Character:"  # Unchanged

    @pytest.mark.parametrize("system_role", ["system", "systemMes"])
    def test_format_messages_skips_system_messages(self, timestamp_service, mock_dependencies, system_role):
        """System messages are never timestamp-prefixed and never even hashed,
        matching the write-path skip in resolve_and_track_history."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [
            {'role': system_role, 'content': 'System instruction'},
            {'role': 'user', 'content': 'Msg1'}
        ]
        mock_dependencies["load_file"].return_value = {"hash_user": T_NOW_STR}
        mock_dependencies["hash"].return_value = 'hash_user'

        result = timestamp_service.format_messages_with_timestamps(messages, "convo")

        assert result[0]['content'] == 'System instruction'  # Unchanged
        mock_dependencies["hash"].assert_called_once_with(messages[1])
        assert result[1]['content'] == f"{T_NOW_STR} Msg1"

    def test_format_messages_untracked_hash_left_unformatted(self, timestamp_service, mock_dependencies):
        """A message whose hash is absent from the timestamp file is left untouched."""
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        messages = [
            {'role': 'user', 'content': 'Tracked message'},
            {'role': 'assistant', 'content': 'Untracked message'}
        ]
        mock_dependencies["load_file"].return_value = {"hash_tracked": T_NOW_STR}
        mock_dependencies["hash"].side_effect = ['hash_tracked', 'hash_untracked']

        result = timestamp_service.format_messages_with_timestamps(messages, "convo")

        assert result[0]['content'] == f"{T_NOW_STR} Tracked message"
        assert result[1]['content'] == "Untracked message"  # Unchanged

    # ##########################################
    # ##### Tests for save_specific_timestamp
    # ##########################################
    def test_save_specific_timestamp_success_new(self, timestamp_service, mock_dependencies):
        """Verifies that a new timestamp is correctly saved."""
        discussion_id = "id"
        content = "Response."
        timestamp = "(T_Now)"
        mock_dependencies["load_file"].return_value = {}
        mock_dependencies["hash"].return_value = "new_hash"

        timestamp_service.save_specific_timestamp(discussion_id, content, timestamp)

        expected_saved_data = {"new_hash": "(T_Now)"}
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_save_specific_timestamp_update_existing(self, timestamp_service, mock_dependencies):
        """Ensures the method updates a timestamp if the hash exists but the timestamp differs."""
        content = "Response."
        mock_dependencies["hash"].return_value = "existing_hash"
        mock_dependencies["load_file"].return_value = {"existing_hash": "(T_Old)"}

        timestamp_service.save_specific_timestamp("id", content, "(T_New)")

        expected_saved_data = {"existing_hash": "(T_New)"}
        mock_dependencies["save_file"].assert_called_once()
        args, _ = mock_dependencies["save_file"].call_args
        assert args[1] == expected_saved_data

    def test_save_specific_timestamp_no_change(self, timestamp_service, mock_dependencies):
        """Ensures the method does not save if the hash and timestamp already match."""
        content = "Response."
        mock_dependencies["hash"].return_value = "existing_hash"
        mock_dependencies["load_file"].return_value = {"existing_hash": "(T_Now)"}

        timestamp_service.save_specific_timestamp("id", content, "(T_Now)")

        mock_dependencies["save_file"].assert_not_called()

    def test_save_specific_timestamp_preserves_placeholder(self, timestamp_service, mock_dependencies):
        """Ensures that placeholders in the file are preserved (cleanup is handled elsewhere)."""
        content = "Response."
        mock_dependencies["hash"].return_value = "new_hash"
        mock_dependencies["load_file"].return_value = {PLACEHOLDER_HASH: "(T_Stale)"}

        timestamp_service.save_specific_timestamp("id", content, "(T_New)")

        # Placeholder remains; only the new hash is added
        expected_saved_data = {PLACEHOLDER_HASH: "(T_Stale)", "new_hash": "(T_New)"}
        mock_dependencies["save_file"].assert_called_once_with(
            mock_dependencies["get_path"].return_value,
            expected_saved_data,
            encryption_key=None
        )

    def test_save_specific_timestamp_no_save_when_hash_and_ts_match(
            self, timestamp_service, mock_dependencies
    ):
        """Ensures the file is NOT saved when the hash and timestamp already match."""
        content = "Response."
        mock_dependencies["hash"].return_value = "existing_hash"
        mock_dependencies["load_file"].return_value = {
            "existing_hash": "(T1)",
            PLACEHOLDER_HASH: "(T_Stale)"
        }

        timestamp_service.save_specific_timestamp("id", content, "(T1)")

        mock_dependencies["save_file"].assert_not_called()

    @pytest.mark.parametrize("discussion_id, content, timestamp", [
        (None, "content", "(TS)"), ("", "content", "(TS)"),
        ("id", None, "(TS)"), ("id", "", "(TS)"),
        ("id", "content", None), ("id", "content", ""),
    ])
    def test_save_specific_timestamp_invalid_inputs(
            self, timestamp_service, mock_dependencies, discussion_id, content, timestamp
    ):
        """Ensures the method exits gracefully if any input is missing."""
        timestamp_service.save_specific_timestamp(discussion_id, content, timestamp)

        mock_dependencies["get_path"].assert_not_called()
        mock_dependencies["hash"].assert_not_called()
        mock_dependencies["save_file"].assert_not_called()

    # ##########################################
    # ##### Tests for get_time_context_summary
    # ##########################################
    def test_get_time_context_summary_success(self, timestamp_service, mock_dependencies):
        """Tests that a correct time context summary is generated from multiple timestamps."""
        timestamps = {
            "hash1": "(Monday, 2025-09-22 10:00:00)",
            "hash2": "(Monday, 2025-09-22 12:30:00)"
        }
        mock_dependencies["load_file"].return_value = timestamps
        mock_dependencies["format_string"].side_effect = ["2 hours, 30 minutes", "5 minutes"]

        summary = timestamp_service.get_time_context_summary("test-discussion")

        expected_summary = (
            "[Time Context: This conversation started 2 hours, 30 minutes ago. "
            "The most recent message was sent 5 minutes ago.]"
        )
        assert summary == expected_summary
        assert mock_dependencies["format_string"].call_count == 2

    def test_get_time_context_summary_single_timestamp(self, timestamp_service, mock_dependencies):
        """Tests that a correct summary is generated when only one timestamp exists."""
        timestamps = {"hash1": "(Monday, 2025-09-22 10:00:00)"}
        mock_dependencies["load_file"].return_value = timestamps
        mock_dependencies["format_string"].return_value = "10 minutes"

        summary = timestamp_service.get_time_context_summary("test-discussion")

        expected_summary = "[Time Context: The conversation started 10 minutes ago.]"
        assert summary == expected_summary
        assert mock_dependencies["format_string"].call_count == 2

    def test_get_time_context_summary_ignores_legacy_placeholder(self, timestamp_service, mock_dependencies):
        """Ensures the summary ignores the legacy placeholder hash."""
        timestamps = {
            "hash1": "(Monday, 2025-09-22 10:00:00)",
            PLACEHOLDER_HASH: "(Monday, 2025-09-22 15:00:00)"
        }
        mock_dependencies["load_file"].return_value = timestamps
        mock_dependencies["format_string"].return_value = "5 hours"

        summary = timestamp_service.get_time_context_summary("test-discussion")

        expected_summary = "[Time Context: The conversation started 5 hours ago.]"
        assert summary == expected_summary
        assert mock_dependencies["format_string"].call_count == 2

    @pytest.mark.parametrize("discussion_id, loaded_data", [
        (None, {}), ("", {}), ("test-id", {}),
        ("test-id", {"hash1": "invalid-timestamp-format"}),
        ("test-id", {PLACEHOLDER_HASH: "(Monday, 2025-09-22 10:00:00)"}),
        ("test-id", {"hash1": None})
    ])
    def test_get_time_context_summary_edge_cases(
            self, timestamp_service, mock_dependencies, discussion_id, loaded_data
    ):
        """Tests edge cases, ensuring an empty string is returned for invalid or empty data."""
        mock_dependencies["load_file"].return_value = loaded_data

        summary = timestamp_service.get_time_context_summary(discussion_id)

        assert summary == ""

    # ##########################################
    # ##### Integration Tests for Complete Flows
    # ##########################################
    def test_workflow_with_group_chat_logic_enabled(self, timestamp_service, mock_dependencies):
        """Tests the complete flow when useGroupChatTimestampLogic is true (behavior C)."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Roland:'}  # Generation prompt
        ]
        # Stateful load/save backed by a shared dict so the placeholder written by
        # save_placeholder_timestamp is actually found by commit_assistant_response.
        file_state = {}

        def _load_file(path, encryption_key=None):
            return dict(file_state)

        def _save_file(path, data, encryption_key=None):
            file_state.clear()
            file_state.update(data)

        mock_dependencies["load_file"].side_effect = _load_file
        mock_dependencies["save_file"].side_effect = _save_file
        mock_dependencies["hash"].side_effect = ['hash1', 'hash2']
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"

        timestamp_service.resolve_and_track_history(messages, "convo")
        timestamp_service.save_placeholder_timestamp("convo")

        # The placeholder must be present in the persisted state before commit.
        assert file_state[PLACEHOLDER_HASH] == T_NOW_STR

        assistant_response = "Hi there! How can I help?"
        timestamp_service.commit_assistant_response("convo", assistant_response)

        # Saved three times: history tracking, placeholder save, and commit.
        assert mock_dependencies["save_file"].call_count == 3
        # The commit consumed the placeholder and bound its time to the response hash.
        assert PLACEHOLDER_HASH not in file_state
        assert file_state['hash2'] == T_NOW_STR
        # The user message tracked during history resolution is still present.
        assert file_state['hash1'] == T_NOW_STR

    def test_workflow_with_group_chat_logic_disabled(self, timestamp_service, mock_dependencies):
        """Tests the complete flow when useGroupChatTimestampLogic is false (behavior B)."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'}
        ]
        mock_dependencies["load_file"].return_value = {}
        mock_dependencies["hash"].side_effect = ['hash2', 'hash1']
        T_NOW_STR = f"({MOCK_NOW.strftime(TS_FORMAT)})"
        T_NOW_M1S = f"({(MOCK_NOW - timedelta(seconds=1)).strftime(TS_FORMAT)})"

        timestamp_service.resolve_and_track_history(messages, "convo")
        timestamp_service.save_placeholder_timestamp("convo")

        # Reset for next user turn
        mock_dependencies["load_file"].return_value = {
            'hash1': T_NOW_M1S,
            'hash2': T_NOW_STR,
            PLACEHOLDER_HASH: T_NOW_STR
        }

        new_messages = messages + [{'role': 'user', 'content': 'Thanks!'}]
        # Phase 0: hash for assistant (to resolve placeholder), Phase 1: backward iteration
        mock_dependencies["hash"].side_effect = ['hash2', 'hash3', 'hash2', 'hash1']
        timestamp_service.resolve_and_track_history(new_messages, "convo")

        # Placeholder should have been resolved
        assert PLACEHOLDER_HASH not in mock_dependencies["save_file"].call_args_list[-1][0][1]

    def test_methods_are_noop_without_discussion_id(self, timestamp_service, mock_dependencies):
        """All service entry points are no-ops without a discussion_id: nothing is loaded or saved."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi'}
        ]

        timestamp_service.resolve_and_track_history(messages, None)
        timestamp_service.format_messages_with_timestamps(messages, None)
        timestamp_service.save_placeholder_timestamp(None)
        timestamp_service.commit_assistant_response(None, "content")

        mock_dependencies["load_file"].assert_not_called()
        mock_dependencies["save_file"].assert_not_called()

    def test_multiple_regenerations_do_not_replace_placeholder(self, timestamp_service, mock_dependencies):
        """Tests behavior B: regenerations don't replace the placeholder until next user turn."""
        initial_messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'First response'}
        ]
        T_PLACEHOLDER = f"({MOCK_NOW.strftime(TS_FORMAT)})"

        # Setup: Create initial state with placeholder
        mock_dependencies["load_file"].return_value = {
            'hash1': "(Old_Time)",
            'hash2': "(Old_Time2)",
            PLACEHOLDER_HASH: T_PLACEHOLDER
        }

        regen_messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Regenerated response'}
        ]
        # Phase 0: hash for assistant (to resolve placeholder), Phase 1: backward iteration
        mock_dependencies["hash"].side_effect = ['hash3', 'hash3', 'hash1']
        timestamp_service.resolve_and_track_history(regen_messages, "convo")

        last_save_call = mock_dependencies["save_file"].call_args_list[-1][0][1]
        assert PLACEHOLDER_HASH not in last_save_call  # Placeholder was consumed
        assert 'hash3' in last_save_call  # New response was assigned the placeholder time
        assert last_save_call['hash3'] == T_PLACEHOLDER  # Verify it got the placeholder timestamp

    def test_placeholder_resolution_with_generation_prompt_last(self, timestamp_service, mock_dependencies):
        """Tests behavior E: placeholder resolution when the last message is a generation prompt."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Previous response'},
            {'role': 'user', 'content': 'Another question'},
            {'role': 'assistant', 'content': 'Character:'}  # Generation prompt
        ]
        T_PLACEHOLDER = f"({(MOCK_NOW - timedelta(minutes=5)).strftime(TS_FORMAT)})"

        # Only hash1 and hash3 are already tracked; hash2 (assistant response) is NOT tracked
        # This simulates a scenario where the assistant responded but wasn't tracked yet
        mock_dependencies["load_file"].return_value = {
            'hash1': "(Old1)",
            'hash3': "(Old3)",
            PLACEHOLDER_HASH: T_PLACEHOLDER
        }

        # Phase 0: Looking backwards for last valid assistant message (skips Character:, finds 'Previous response')
        # hash2 is not in timestamps, so it gets the placeholder
        # Phase 1: Backward iteration skips Character:, processes hash3, hash2, hash1
        mock_dependencies["hash"].side_effect = ['hash2', 'hash3', 'hash2', 'hash1']

        timestamp_service.resolve_and_track_history(messages, "convo")

        # The placeholder should have been applied to the previous assistant message (not the generation prompt)
        last_save_call = mock_dependencies["save_file"].call_args_list[-1][0][1]
        assert PLACEHOLDER_HASH not in last_save_call
        assert last_save_call['hash2'] == T_PLACEHOLDER  # Previous assistant message got the placeholder
        assert last_save_call['hash1'] == "(Old1)"
        assert last_save_call['hash3'] == "(Old3)"
