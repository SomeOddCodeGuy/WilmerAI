"""Tests for UserInjectionFilter, UserRoutingFileHandler, and resolve_port in server.py."""

import logging
import os
from unittest.mock import patch

import pytest

from Middleware.common import instance_global_variables


class TestUserInjectionFilter:
    """Tests for the UserInjectionFilter logging filter."""

    @pytest.fixture(autouse=True)
    def reset_request_user(self):
        yield
        instance_global_variables.clear_request_user()

    def _make_record(self):
        return logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )

    def test_defaults_to_system(self):
        """When no request user is set, wilmer_user defaults to 'system'."""
        from server import UserInjectionFilter
        f = UserInjectionFilter()
        record = self._make_record()

        instance_global_variables.clear_request_user()
        result = f.filter(record)

        assert result is True
        assert record.wilmer_user == "system"

    def test_uses_request_user(self):
        """When a request user is set, wilmer_user is that user."""
        from server import UserInjectionFilter
        f = UserInjectionFilter()
        record = self._make_record()

        instance_global_variables.set_request_user("alice")
        result = f.filter(record)

        assert result is True
        assert record.wilmer_user == "alice"

    def test_always_returns_true(self):
        """Filter should never suppress records."""
        from server import UserInjectionFilter
        f = UserInjectionFilter()
        record = self._make_record()

        assert f.filter(record) is True


class TestUserRoutingFileHandler:
    """Tests for the UserRoutingFileHandler logging handler."""

    def _make_record(self, user="system"):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.wilmer_user = user
        return record

    def test_creates_system_log(self, tmp_path):
        """System log is created at {log_dir}/wilmerai.log."""
        from server import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        try:
            handler.emit(self._make_record("system"))
            assert os.path.isfile(os.path.join(str(tmp_path), "wilmerai.log"))
        finally:
            handler.close()

    def test_creates_user_subdirectory_log(self, tmp_path):
        """User log is created at {log_dir}/{user}/wilmerai.log."""
        from server import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        try:
            handler.emit(self._make_record("alice"))
            expected = os.path.join(str(tmp_path), "alice", "wilmerai.log")
            assert os.path.isfile(expected)
        finally:
            handler.close()

    def test_routes_to_correct_file(self, tmp_path):
        """Records for different users go to different files."""
        from server import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(wilmer_user)s: %(message)s"))

        try:
            record_alice = self._make_record("alice")
            record_alice.msg = "alice message"
            record_bob = self._make_record("bob")
            record_bob.msg = "bob message"

            handler.emit(record_alice)
            handler.emit(record_bob)

            alice_log = os.path.join(str(tmp_path), "alice", "wilmerai.log")
            bob_log = os.path.join(str(tmp_path), "bob", "wilmerai.log")

            with open(alice_log) as f:
                content = f.read()
                assert "alice message" in content
                assert "bob message" not in content

            with open(bob_log) as f:
                content = f.read()
                assert "bob message" in content
                assert "alice message" not in content
        finally:
            handler.close()

    def test_close_cleans_up_handlers(self, tmp_path):
        """close() cleans up all internal handlers."""
        from server import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("alice"))
        assert len(handler._handlers) == 1

        handler.close()
        assert len(handler._handlers) == 0

    def test_missing_wilmer_user_defaults_to_system(self, tmp_path):
        """Records without wilmer_user attribute go to system log."""
        from server import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="no user", args=(), exc_info=None,
            )
            # Don't set wilmer_user attribute
            handler.emit(record)
            assert os.path.isfile(os.path.join(str(tmp_path), "wilmerai.log"))
        finally:
            handler.close()


class TestResolvePort:
    """Tests for the resolve_port() function."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Save and restore PORT and USERS around each test."""
        orig_port = instance_global_variables.PORT
        orig_users = instance_global_variables.USERS
        yield
        instance_global_variables.PORT = orig_port
        instance_global_variables.USERS = orig_users

    def test_cli_port_takes_precedence_single_user(self):
        """--port flag overrides user config in single-user mode."""
        from server import resolve_port
        instance_global_variables.PORT = 9999
        instance_global_variables.USERS = ["alice"]
        assert resolve_port() == 9999

    def test_cli_port_takes_precedence_multi_user(self):
        """--port flag overrides the default in multi-user mode."""
        from server import resolve_port
        instance_global_variables.PORT = 8080
        instance_global_variables.USERS = ["alice", "bob"]
        assert resolve_port() == 8080

    def test_multi_user_defaults_to_5050(self):
        """Multi-user mode without --port defaults to 5050."""
        from server import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice", "bob"]
        assert resolve_port() == 5050

    def test_single_user_reads_from_config(self):
        """Single-user mode without --port reads from user config."""
        from server import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice"]
        with patch("server.config_utils.get_user_config_for", return_value={"port": 7777}):
            assert resolve_port() == 7777

    def test_single_user_config_error_falls_back_to_5000(self):
        """If user config can't be read, fall back to 5000."""
        from server import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice"]
        with patch("server.config_utils.get_user_config_for", side_effect=FileNotFoundError("no config")):
            assert resolve_port() == 5000

    def test_no_users_reads_from_config(self):
        """No --User arg reads port from _current-user.json config."""
        from server import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = None
        with patch("server.config_utils.get_application_port", return_value=6060):
            assert resolve_port() == 6060

    def test_no_users_config_error_falls_back_to_5000(self):
        """If no --User and config fails, fall back to 5000."""
        from server import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = None
        with patch("server.config_utils.get_application_port", side_effect=FileNotFoundError("no config")):
            assert resolve_port() == 5000
