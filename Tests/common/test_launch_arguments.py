import os
from unittest.mock import patch

import pytest

from Middleware.common import instance_global_variables
from Middleware.common.launch_arguments import parse_and_apply_launch_arguments

_STAMPED_ATTRIBUTES = [
    "CONFIG_DIRECTORY", "PUBLIC_DIRECTORY", "USERS", "LOGGING_DIRECTORY",
    "USER_LEVEL_SQLITE_DIRECTORY", "DISCUSSION_DIRECTORY", "FILE_LOGGING",
    "PORT", "LISTEN_ADDRESS", "CONCURRENCY_LIMIT", "CONCURRENCY_TIMEOUT",
    "CONCURRENCY_LEVEL",
]


class TestParseAndApplyLaunchArguments:
    """Tests for the shared entry-point argument parser and global stamping."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Save and restore every stamped global around each test."""
        saved = {name: getattr(instance_global_variables, name) for name in _STAMPED_ATTRIBUTES}
        yield
        for name, value in saved.items():
            setattr(instance_global_variables, name, value)

    def _parse(self, mocker, *argv):
        mocker.patch("sys.argv", ["prog", *argv])
        mocker.patch(
            "Middleware.utilities.config_utils.get_root_public_directory",
            return_value=os.path.join("install", "Public"),
        )
        parse_and_apply_launch_arguments("test launcher")

    def test_positional_arguments_set_config_directory_and_user(self, mocker):
        self._parse(mocker, "some/config/dir/", "alice")
        assert instance_global_variables.CONFIG_DIRECTORY == "some/config/dir"
        assert instance_global_variables.USERS == ["alice"]

    def test_flags_override_positionals(self, mocker):
        self._parse(mocker, "pos/dir", "pos-user",
                    "--ConfigDirectory", "flag/dir/", "--User", "bob")
        assert instance_global_variables.CONFIG_DIRECTORY == "flag/dir"
        assert instance_global_variables.USERS == ["bob"]

    def test_repeated_user_flag_builds_multi_user_list(self, mocker):
        self._parse(mocker, "--User", "alice", "--User", "bob")
        assert instance_global_variables.USERS == ["alice", "bob"]

    def test_default_logging_directory_is_install_pinned(self, mocker):
        self._parse(mocker)
        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("install", "Public", "logs")

    def test_explicit_logging_directory_wins(self, mocker):
        self._parse(mocker, "--LoggingDirectory", "my/logs")
        assert instance_global_variables.LOGGING_DIRECTORY == "my/logs"

    def test_user_token_resolved_for_single_user(self, mocker):
        self._parse(mocker, "--User", "alice", "--LoggingDirectory", os.path.join("logs", "<user>"))
        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("logs", "alice")

    def test_user_token_resolved_in_legacy_mode(self, mocker):
        """The legacy no---User branch (previously missing from the launchers'
        inline copies, leaving a literal '<user>' directory) resolves via
        get_current_username()."""
        mocker.patch(
            "Middleware.utilities.config_utils.get_current_username",
            return_value="legacy-user",
        )
        self._parse(mocker, "--LoggingDirectory", os.path.join("logs", "<user>"))
        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("logs", "legacy-user")

    def test_directory_overrides_and_flags_are_stamped(self, mocker):
        self._parse(mocker,
                    "--PublicDirectory", "pub/dir/",
                    "--UserLevelSqlLiteDirectory", "sql/dir/",
                    "--DiscussionDirectory", "disc/dir/",
                    "--file-logging",
                    "--port", "6001",
                    "--listen",
                    "--concurrency", "4",
                    "--concurrency-timeout", "30",
                    "--concurrency-level", "endpoint")
        assert instance_global_variables.PUBLIC_DIRECTORY == "pub/dir"
        assert instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY == "sql/dir"
        assert instance_global_variables.DISCUSSION_DIRECTORY == "disc/dir"
        assert instance_global_variables.FILE_LOGGING is True
        assert instance_global_variables.PORT == 6001
        assert instance_global_variables.LISTEN_ADDRESS == "0.0.0.0"
        assert instance_global_variables.CONCURRENCY_LIMIT == 4
        assert instance_global_variables.CONCURRENCY_TIMEOUT == 30
        assert instance_global_variables.CONCURRENCY_LEVEL == "endpoint"

    def test_listen_accepts_explicit_address(self, mocker):
        self._parse(mocker, "--listen", "192.168.1.5")
        assert instance_global_variables.LISTEN_ADDRESS == "192.168.1.5"

    def test_absent_flags_leave_prior_globals_untouched(self, mocker):
        """Absent optional flags must NOT overwrite what a launcher (or module
        default) already stamped. FILE_LOGGING is a load-bearing tri-state:
        None means 'fall back to the user's useFileLogging config', so a parser
        default of False here would silently disable that fallback. PORT=None
        likewise means 'resolve from user config / multi-user default' in
        resolve_port(). Concurrency settings are always stamped to their
        documented defaults, and LOGGING_DIRECTORY is always re-resolved to the
        install-pinned default."""
        instance_global_variables.CONFIG_DIRECTORY = "prior/config"
        instance_global_variables.PUBLIC_DIRECTORY = "prior/public"
        instance_global_variables.USERS = ["prior-user"]
        instance_global_variables.FILE_LOGGING = True
        instance_global_variables.PORT = 4242
        instance_global_variables.LISTEN_ADDRESS = "10.0.0.1"
        instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY = "prior/sql"
        instance_global_variables.DISCUSSION_DIRECTORY = "prior/disc"

        self._parse(mocker)

        assert instance_global_variables.CONFIG_DIRECTORY == "prior/config"
        assert instance_global_variables.PUBLIC_DIRECTORY == "prior/public"
        assert instance_global_variables.USERS == ["prior-user"]
        assert instance_global_variables.FILE_LOGGING is True
        assert instance_global_variables.PORT == 4242
        assert instance_global_variables.LISTEN_ADDRESS == "10.0.0.1"
        assert instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY == "prior/sql"
        assert instance_global_variables.DISCUSSION_DIRECTORY == "prior/disc"
        # Always stamped regardless of flags:
        assert instance_global_variables.CONCURRENCY_LIMIT == 1
        assert instance_global_variables.CONCURRENCY_TIMEOUT == 900
        assert instance_global_variables.CONCURRENCY_LEVEL == "wilmer"
        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("install", "Public", "logs")

    def test_blank_flag_values_are_ignored(self, mocker):
        """Whitespace-only values must not clobber prior globals, and a
        whitespace-only --User must not put an empty username into USERS.
        A blank --LoggingDirectory falls through to the install-pinned default."""
        instance_global_variables.CONFIG_DIRECTORY = "prior/config"
        instance_global_variables.PUBLIC_DIRECTORY = "prior/public"
        instance_global_variables.USERS = ["prior-user"]
        instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY = "prior/sql"
        instance_global_variables.DISCUSSION_DIRECTORY = "prior/disc"

        self._parse(mocker,
                    "--ConfigDirectory", "   ",
                    "--PublicDirectory", "   ",
                    "--User", "   ",
                    "--LoggingDirectory", "   ",
                    "--UserLevelSqlLiteDirectory", "   ",
                    "--DiscussionDirectory", "   ")

        assert instance_global_variables.CONFIG_DIRECTORY == "prior/config"
        assert instance_global_variables.PUBLIC_DIRECTORY == "prior/public"
        assert instance_global_variables.USERS == ["prior-user"]
        assert instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY == "prior/sql"
        assert instance_global_variables.DISCUSSION_DIRECTORY == "prior/disc"
        assert instance_global_variables.LOGGING_DIRECTORY == os.path.join("install", "Public", "logs")

    def test_negative_concurrency_is_rejected(self, mocker):
        mocker.patch("sys.argv", ["prog", "--concurrency", "-1"])
        with pytest.raises(SystemExit):
            parse_and_apply_launch_arguments("test launcher")

    def test_non_positive_concurrency_timeout_is_rejected(self, mocker):
        mocker.patch("sys.argv", ["prog", "--concurrency-timeout", "0"])
        with pytest.raises(SystemExit):
            parse_and_apply_launch_arguments("test launcher")
