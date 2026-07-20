"""Tests for UserInjectionFilter, UserRoutingFileHandler, and resolve_port in
Middleware/common/server_startup.py (imported without server.py's module-level
application initialization)."""

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
        from Middleware.common.server_startup import UserInjectionFilter
        f = UserInjectionFilter()
        record = self._make_record()

        instance_global_variables.clear_request_user()
        result = f.filter(record)

        assert result is True
        assert record.wilmer_user == "system"

    def test_uses_request_user(self):
        """When a request user is set, wilmer_user is that user."""
        from Middleware.common.server_startup import UserInjectionFilter
        f = UserInjectionFilter()
        record = self._make_record()

        instance_global_variables.set_request_user("alice")
        result = f.filter(record)

        assert result is True
        assert record.wilmer_user == "alice"


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
        """System log is created at {log_dir}/wilmerai.log and receives the record."""
        from Middleware.common.server_startup import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        try:
            handler.emit(self._make_record("system"))
            log_path = os.path.join(str(tmp_path), "wilmerai.log")
            assert os.path.isfile(log_path)
            with open(log_path) as f:
                assert "test message" in f.read()
        finally:
            handler.close()

    def test_creates_user_subdirectory_log(self, tmp_path):
        """User log is created at {log_dir}/{user}/wilmerai.log and receives the record."""
        from Middleware.common.server_startup import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        try:
            handler.emit(self._make_record("alice"))
            expected = os.path.join(str(tmp_path), "alice", "wilmerai.log")
            assert os.path.isfile(expected)
            with open(expected) as f:
                assert "test message" in f.read()
        finally:
            handler.close()

    def test_routes_to_correct_file(self, tmp_path):
        """Records for different users go to different files."""
        from Middleware.common.server_startup import UserRoutingFileHandler
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

            # The "user: " prefix proves the parent handler's formatter was
            # propagated to the lazily created per-user handlers; the bare
            # message would appear even with no formatter at all.
            with open(alice_log) as f:
                content = f.read()
                assert "alice: alice message" in content
                assert "bob message" not in content

            with open(bob_log) as f:
                content = f.read()
                assert "bob: bob message" in content
                assert "alice message" not in content
        finally:
            handler.close()

    def test_same_user_reuses_cached_handler(self, tmp_path):
        """Repeated records for one user reuse a single cached file handler
        (no handler-per-record leak) and append to the same file."""
        from Middleware.common.server_startup import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        try:
            first = self._make_record("alice")
            first.msg = "first message"
            second = self._make_record("alice")
            second.msg = "second message"

            handler.emit(first)
            handler.emit(second)

            assert len(handler._handlers) == 1
            with open(os.path.join(str(tmp_path), "alice", "wilmerai.log")) as f:
                content = f.read()
            assert "first message" in content
            assert "second message" in content
        finally:
            handler.close()

    def test_close_cleans_up_handlers(self, tmp_path):
        """close() cleans up all internal handlers."""
        from Middleware.common.server_startup import UserRoutingFileHandler
        handler = UserRoutingFileHandler(str(tmp_path))
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(self._make_record("alice"))
        assert len(handler._handlers) == 1

        handler.close()
        assert len(handler._handlers) == 0

    def test_missing_wilmer_user_defaults_to_system(self, tmp_path):
        """Records without wilmer_user attribute go to system log."""
        from Middleware.common.server_startup import UserRoutingFileHandler
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
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = 9999
        instance_global_variables.USERS = ["alice"]
        assert resolve_port() == 9999

    def test_cli_port_takes_precedence_multi_user(self):
        """--port flag overrides the default in multi-user mode."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = 8080
        instance_global_variables.USERS = ["alice", "bob"]
        assert resolve_port() == 8080

    def test_multi_user_defaults_to_5050(self, capsys):
        """Multi-user mode without --port defaults to 5050 and warns on stderr."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice", "bob"]
        assert resolve_port() == 5050

        captured = capsys.readouterr()
        assert "ignored in multi-user mode" in captured.err
        assert "5050" in captured.err

    def test_single_user_reads_from_config(self):
        """Single-user mode without --port reads from user config."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for", return_value={"port": 7777}):
            assert resolve_port() == 7777

    def test_single_user_config_missing_port_key_defaults_to_5000(self):
        """A readable user config with no 'port' key yields the documented 5000 default."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for", return_value={}):
            assert resolve_port() == 5000

    def test_single_user_config_error_falls_back_to_5000(self):
        """If user config can't be read, fall back to 5000."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for", side_effect=FileNotFoundError("no config")):
            assert resolve_port() == 5000

    def test_no_users_reads_from_config(self):
        """No --User arg reads port from _current-user.json config."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = None
        with patch("Middleware.common.server_startup.config_utils.get_application_port", return_value=6060):
            assert resolve_port() == 6060

    def test_no_users_none_application_port_falls_back_to_5000(self):
        """get_application_port() returning None (config present, port unset)
        falls through the `or 5000` branch to the documented default."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = None
        with patch("Middleware.common.server_startup.config_utils.get_application_port", return_value=None):
            assert resolve_port() == 5000

    def test_no_users_config_error_falls_back_to_5000(self):
        """If no --User and config fails, fall back to 5000."""
        from Middleware.common.server_startup import resolve_port
        instance_global_variables.PORT = None
        instance_global_variables.USERS = None
        with patch("Middleware.common.server_startup.config_utils.get_application_port", side_effect=FileNotFoundError("no config")):
            assert resolve_port() == 5000


class TestResolveFileLogging:
    """Tests for the resolve_file_logging() precedence table."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Save and restore FILE_LOGGING and USERS around each test."""
        orig_file_logging = instance_global_variables.FILE_LOGGING
        orig_users = instance_global_variables.USERS
        yield
        instance_global_variables.FILE_LOGGING = orig_file_logging
        instance_global_variables.USERS = orig_users

    def test_cli_flag_true_wins_over_config(self):
        """--file-logging beats a config that says off; config is never read."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = True
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for") as mock_cfg:
            assert resolve_file_logging() is True
            mock_cfg.assert_not_called()

    def test_cli_flag_false_wins_over_config_true(self):
        """An explicit False flag is not 'absent': it overrides a config that
        enables file logging. This pins the tri-state None/False distinction."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = False
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for",
                   return_value={"useFileLogging": True}) as mock_cfg:
            assert resolve_file_logging() is False
            mock_cfg.assert_not_called()

    def test_single_user_reads_config_true(self):
        """Absent flag + single user: the user's useFileLogging setting decides."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = None
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for",
                   return_value={"useFileLogging": True}):
            assert resolve_file_logging() is True

    def test_single_user_config_missing_key_defaults_off(self):
        """A readable config with no useFileLogging key means off."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = None
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for", return_value={}):
            assert resolve_file_logging() is False

    def test_single_user_config_error_defaults_off(self):
        """A config read failure degrades to off instead of blocking startup."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = None
        instance_global_variables.USERS = ["alice"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for",
                   side_effect=FileNotFoundError("no config")):
            assert resolve_file_logging() is False

    def test_no_users_legacy_reads_current_user_config(self):
        """Absent flag + no --User: legacy mode reads _current-user.json's config."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = None
        instance_global_variables.USERS = None
        with patch("Middleware.common.server_startup.config_utils.get_user_config",
                   return_value={"useFileLogging": True}):
            assert resolve_file_logging() is True

    def test_no_users_config_error_defaults_off(self):
        """Legacy-mode config failure degrades to off."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = None
        instance_global_variables.USERS = None
        with patch("Middleware.common.server_startup.config_utils.get_user_config",
                   side_effect=FileNotFoundError("no config")):
            assert resolve_file_logging() is False

    def test_multi_user_defaults_off_without_consulting_configs(self):
        """Absent flag + multiple users: off, and per-user configs are never read
        (a config-enabled user must not force file logging on a shared instance)."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = None
        instance_global_variables.USERS = ["alice", "bob"]
        with patch("Middleware.common.server_startup.config_utils.get_user_config_for") as mock_for, \
                patch("Middleware.common.server_startup.config_utils.get_user_config") as mock_legacy:
            assert resolve_file_logging() is False
            mock_for.assert_not_called()
            mock_legacy.assert_not_called()

    def test_multi_user_cli_flag_enables(self):
        """--file-logging turns file logging on in multi-user mode."""
        from Middleware.common.server_startup import resolve_file_logging
        instance_global_variables.FILE_LOGGING = True
        instance_global_variables.USERS = ["alice", "bob"]
        assert resolve_file_logging() is True


class TestResolveLoggingDirectory:
    """Tests for the resolve_logging_directory_user_token() <user> token handling."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Save and restore LOGGING_DIRECTORY and USERS around each test."""
        orig_dir = instance_global_variables.LOGGING_DIRECTORY
        orig_users = instance_global_variables.USERS
        yield
        instance_global_variables.LOGGING_DIRECTORY = orig_dir
        instance_global_variables.USERS = orig_users

    def test_single_user_replaces_token(self):
        """Single-user mode replaces <user> with the configured username."""
        from Middleware.common.launch_arguments import resolve_logging_directory_user_token
        instance_global_variables.USERS = ["alice"]
        instance_global_variables.LOGGING_DIRECTORY = os.path.join("logs", "<user>", "app")

        resolve_logging_directory_user_token()

        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("logs", "alice", "app")

    def test_multi_user_strips_token_and_warns(self, capsys):
        """Multi-user mode strips the token (and trailing separators) and warns on stderr."""
        from Middleware.common.launch_arguments import resolve_logging_directory_user_token
        instance_global_variables.USERS = ["alice", "bob"]
        instance_global_variables.LOGGING_DIRECTORY = os.path.join("logs", "<user>")

        resolve_logging_directory_user_token()

        assert instance_global_variables.LOGGING_DIRECTORY == "logs"
        captured = capsys.readouterr()
        assert "not supported in multi-user mode" in captured.err

    def test_no_users_resolves_via_current_username(self):
        """With USERS unset (legacy _current-user.json mode), the token resolves
        through get_current_username() rather than staying a literal <user>."""
        from Middleware.common.launch_arguments import resolve_logging_directory_user_token
        instance_global_variables.USERS = None
        instance_global_variables.LOGGING_DIRECTORY = os.path.join("logs", "<user>")

        with patch("Middleware.utilities.config_utils.get_current_username", return_value="legacy-user"):
            resolve_logging_directory_user_token()

        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("logs", "legacy-user")

    def test_no_users_username_failure_strips_token_and_warns(self, capsys):
        """If the legacy username lookup fails, the token is stripped with a warning
        instead of creating a literal '<user>' directory."""
        from Middleware.common.launch_arguments import resolve_logging_directory_user_token
        instance_global_variables.USERS = None
        instance_global_variables.LOGGING_DIRECTORY = os.path.join("logs", "<user>")

        with patch("Middleware.utilities.config_utils.get_current_username", side_effect=FileNotFoundError("no config")):
            resolve_logging_directory_user_token()

        assert instance_global_variables.LOGGING_DIRECTORY == "logs"
        assert "could not resolve the <user> token" in capsys.readouterr().err

    def test_no_token_is_noop(self, capsys):
        """Without a <user> token, the directory is untouched and nothing is printed."""
        from Middleware.common.launch_arguments import resolve_logging_directory_user_token
        instance_global_variables.USERS = ["alice", "bob"]
        instance_global_variables.LOGGING_DIRECTORY = "plain-logs"

        resolve_logging_directory_user_token()

        assert instance_global_variables.LOGGING_DIRECTORY == "plain-logs"
        assert capsys.readouterr().err == ""
