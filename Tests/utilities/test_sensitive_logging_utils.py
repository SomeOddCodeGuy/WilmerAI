
import logging
import threading
from unittest.mock import MagicMock

import pytest

from Middleware.utilities.sensitive_logging_utils import (
    set_encryption_context,
    clear_encryption_context,
    is_encryption_active,
    sensitive_log,
    sensitive_log_lazy,
    log_prompt_content,
    _REDACTION_MARKER,
    _request_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_context():
    """Ensure each test starts with a clean encryption context."""
    clear_encryption_context()
    yield
    clear_encryption_context()


def _make_logger():
    """Return a logger with a mock handler to inspect emitted records."""
    mock_logger = logging.getLogger(f"test.sensitive.{id(object())}")
    mock_logger.handlers.clear()
    mock_logger.setLevel(logging.DEBUG)
    handler = MagicMock(spec=logging.Handler)
    handler.level = logging.DEBUG
    mock_logger.addHandler(handler)
    return mock_logger, handler


# ---------------------------------------------------------------------------
# set / clear / is_encryption_active
# ---------------------------------------------------------------------------

class TestEncryptionContext:
    def test_default_is_false(self):
        assert is_encryption_active() is False

    def test_set_true(self):
        set_encryption_context(True)
        assert is_encryption_active() is True

    def test_set_false(self):
        set_encryption_context(True)
        set_encryption_context(False)
        assert is_encryption_active() is False

    def test_clear(self):
        set_encryption_context(True)
        clear_encryption_context()
        assert is_encryption_active() is False

    def test_thread_isolation(self):
        """Setting encryption in one thread must not affect another."""
        set_encryption_context(True)

        results = {}

        def check_other_thread():
            results["other"] = is_encryption_active()

        t = threading.Thread(target=check_other_thread)
        t.start()
        t.join()

        assert results["other"] is False
        assert is_encryption_active() is True


# ---------------------------------------------------------------------------
# sensitive_log
# ---------------------------------------------------------------------------

class TestSensitiveLog:
    def test_logs_normally_when_encryption_inactive(self):
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log(mock_logger, logging.INFO, "Hello %s", "world")
        mock_logger.log.assert_called_once_with(logging.INFO, "Hello %s", "world")

    def test_redacts_when_encryption_active(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log(mock_logger, logging.INFO, "Secret prompt: %s", "user data")
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0] == (logging.INFO, _REDACTION_MARKER)

    def test_respects_level(self):
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log(mock_logger, logging.DEBUG, "debug msg")
        mock_logger.log.assert_called_once_with(logging.DEBUG, "debug msg")

    def test_passes_kwargs(self):
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log(mock_logger, logging.WARNING, "msg", exc_info=True)
        mock_logger.log.assert_called_once_with(logging.WARNING, "msg", exc_info=True)

    def test_redacted_message_preserves_level(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log(mock_logger, logging.DEBUG, "debug secret")
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0] == (logging.DEBUG, _REDACTION_MARKER)

    def test_forwards_kwargs_when_redacted(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log(mock_logger, logging.ERROR, "secret error", exc_info=True)
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0] == (logging.ERROR, _REDACTION_MARKER)
        assert call_args[1] == {"exc_info": True}


# ---------------------------------------------------------------------------
# log_prompt_content
# ---------------------------------------------------------------------------

class TestLogPromptContent:
    def test_logs_with_separators_when_encryption_inactive(self):
        mock_logger = MagicMock(spec=logging.Logger)
        log_prompt_content(mock_logger, "Formatted_Prompt", "Hello user")
        calls = mock_logger.info.call_args_list
        assert len(calls) == 3
        assert "***" in calls[0].args[0]
        assert calls[1].args[0] == "\n\n%s: %s"
        assert calls[1].args[1] == "Formatted_Prompt"
        assert calls[1].args[2] == "Hello user"
        assert "***" in calls[2].args[0]

    def test_redacts_when_encryption_active(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        log_prompt_content(mock_logger, "Raw output from the LLM", "secret response text")
        calls = mock_logger.info.call_args_list
        assert len(calls) == 1
        assert "redacted" in calls[0].args[0].lower()
        assert "Raw output from the LLM" in calls[0].args[1]

    def test_different_labels(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        log_prompt_content(mock_logger, "Output from the LLM", "some content")
        assert "Output from the LLM" in mock_logger.info.call_args_list[0].args[1]

    def test_content_not_in_redacted_output(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        log_prompt_content(mock_logger, "Formatted_Prompt", "super secret data")
        all_call_args = str(mock_logger.info.call_args_list)
        assert "super secret data" not in all_call_args


# ---------------------------------------------------------------------------
# sensitive_log_lazy
# ---------------------------------------------------------------------------

class TestSensitiveLogLazy:
    def test_calls_lambdas_when_encryption_inactive(self):
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log_lazy(mock_logger, logging.INFO, "Data: %s %s",
                           lambda: "arg1", lambda: "arg2")
        mock_logger.log.assert_called_once_with(logging.INFO, "Data: %s %s", "arg1", "arg2")

    def test_skips_lambdas_when_encryption_active(self):
        set_encryption_context(True)
        mock_logger = MagicMock(spec=logging.Logger)
        call_tracker = {"called": False}

        def expensive_fn():
            call_tracker["called"] = True
            return "should not compute"

        sensitive_log_lazy(mock_logger, logging.INFO, "Data: %s", expensive_fn)
        mock_logger.log.assert_called_once_with(logging.INFO, _REDACTION_MARKER)
        assert call_tracker["called"] is False

    def test_no_args(self):
        mock_logger = MagicMock(spec=logging.Logger)
        sensitive_log_lazy(mock_logger, logging.DEBUG, "Simple message")
        mock_logger.log.assert_called_once_with(logging.DEBUG, "Simple message")


# ---------------------------------------------------------------------------
# Integration: context toggling during log calls
# ---------------------------------------------------------------------------

class TestContextToggling:
    def test_log_switches_with_context(self):
        mock_logger = MagicMock(spec=logging.Logger)

        sensitive_log(mock_logger, logging.INFO, "visible msg")
        assert mock_logger.log.call_args_list[-1] == ((logging.INFO, "visible msg"),)

        set_encryption_context(True)
        sensitive_log(mock_logger, logging.INFO, "hidden msg")
        assert mock_logger.log.call_args_list[-1][0] == (logging.INFO, _REDACTION_MARKER)

        clear_encryption_context()
        sensitive_log(mock_logger, logging.INFO, "visible again")
        assert mock_logger.log.call_args_list[-1] == ((logging.INFO, "visible again"),)
