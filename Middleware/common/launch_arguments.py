# /Middleware/common/launch_arguments.py
#
# Shared CLI argument handling for the three entry points (server.py,
# run_eventlet.py, run_waitress.py). All three accept the same arguments and
# stamp them onto instance_global_variables; only the --help description
# differs. This module deliberately imports nothing heavier than config_utils
# so run_eventlet.py can import it right after eventlet.monkey_patch() and
# before server.py (which initializes the whole app at import time).

import argparse
import os
import sys

from Middleware.common import instance_global_variables
from Middleware.utilities import config_utils


def resolve_logging_directory_user_token():
    """Resolve the ``<user>`` token in LOGGING_DIRECTORY at startup.

    - Single-user: replace ``<user>`` with ``USERS[0]`` (backward compatible).
    - Multi-user: warn and strip ``<user>`` from the path.
    - Legacy mode (no --User flag): replace with the ``_current-user.json``
      username; if that cannot be resolved, warn and strip the token rather
      than leave a literal ``<user>`` directory in the path.
    """
    log_dir = instance_global_variables.LOGGING_DIRECTORY
    if "<user>" not in log_dir:
        return
    users = instance_global_variables.USERS
    if users and len(users) == 1:
        instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", users[0])
    elif users and len(users) > 1:
        print(
            "WARNING: <user> token in --LoggingDirectory is not supported in multi-user mode. "
            "Stripping token. Per-user log files are created automatically.",
            file=sys.stderr,
        )
        instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", "").rstrip(os.sep)
    else:
        try:
            username = config_utils.get_current_username()
            instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", username)
        except Exception as e:
            print(
                f"WARNING: could not resolve the <user> token in --LoggingDirectory "
                f"({e}). Stripping token.",
                file=sys.stderr,
            )
            instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", "").rstrip(os.sep)


def parse_and_apply_launch_arguments(description):
    """Parses the shared launcher CLI arguments and stamps them onto
    instance_global_variables, resolving the logging directory and its
    ``<user>`` token.

    Args:
        description (str): The argparse description shown by --help.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--ConfigDirectory", type=str, help="Custom path to the configuration directory (typically the Public/Configs subfolder). Kept for backwards compatibility; new installations should prefer --PublicDirectory.")
    parser.add_argument("--PublicDirectory", type=str, help="Custom path to the Public/ root (the parent of Configs, DiscussionIds, SqlLiteDBs, and logs). When set, all runtime data defaults to subfolders under this path unless overridden individually.")
    parser.add_argument("--User", action='append', help="User to run Wilmer as (can be repeated for multi-user)")
    parser.add_argument("--LoggingDirectory", type=str, default=None,
                        help="Directory for log files. Defaults to {PublicDirectory}/logs when "
                             "--PublicDirectory is set, otherwise {install_dir}/Public/logs (install-pinned; "
                             "does not depend on the current working directory).")
    parser.add_argument("--UserLevelSqlLiteDirectory", type=str, default=None,
                        help="Override directory for per-user SQLite databases (workflow locks). "
                             "Takes precedence over the sqlLiteDirectory user config setting.")
    parser.add_argument("--DiscussionDirectory", type=str, default=None,
                        help="Override directory for per-discussion data files (memories, "
                             "summaries, vector DBs). Takes precedence over the discussionDirectory "
                             "user config setting.")
    parser.add_argument("--file-logging", action='store_true', default=None,
                        help="Enable file logging. In single-user mode, falls back to the "
                             "user's useFileLogging config setting. In multi-user mode, "
                             "defaults to off.")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on. In single-user mode, falls back to the user's "
                             "config. In multi-user mode, defaults to 5050.")
    parser.add_argument("--listen", nargs='?', const='0.0.0.0', default=None,
                        help="Listen on the network. With no value, binds to 0.0.0.0 "
                             "(all interfaces). Optionally accepts a specific address.")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Max concurrent requests. 0 = no limit (default: %(default)s)")
    parser.add_argument("--concurrency-timeout", type=int, default=900,
                        help="Seconds to wait for a concurrency slot before returning 503 "
                             "(default: %(default)s)")
    parser.add_argument("--concurrency-level", type=str, choices=["wilmer", "endpoint"], default="wilmer",
                        help="Where the concurrency gate is enforced. 'wilmer' (default) gates "
                             "at the WSGI front door: only --concurrency requests run at a time. "
                             "'endpoint' lifts the request-level gate and instead serializes only "
                             "outbound LLM API calls, allowing reentrant requests (e.g. a Wilmer "
                             "workflow that calls another service which calls back into Wilmer) "
                             "to make progress without deadlocking.")
    parser.add_argument("positional", nargs="*", help="Positional arguments for ConfigDirectory and User")
    args = parser.parse_args()

    if args.concurrency < 0:
        parser.error("--concurrency must be >= 0")
    if args.concurrency_timeout <= 0:
        parser.error("--concurrency-timeout must be > 0")

    if len(args.positional) > 0 and args.positional[0].strip():
        instance_global_variables.CONFIG_DIRECTORY = args.positional[0].strip().rstrip('/\\')
    if len(args.positional) > 1 and args.positional[1].strip():
        instance_global_variables.USERS = [args.positional[1].strip()]

    if args.ConfigDirectory and args.ConfigDirectory.strip():
        instance_global_variables.CONFIG_DIRECTORY = args.ConfigDirectory.strip().rstrip('/\\')
    if args.PublicDirectory and args.PublicDirectory.strip():
        instance_global_variables.PUBLIC_DIRECTORY = args.PublicDirectory.strip().rstrip('/\\')
    if args.User:
        users = [u.strip() for u in args.User if u.strip()]
        if users:
            instance_global_variables.USERS = users

    if args.LoggingDirectory and args.LoggingDirectory.strip():
        instance_global_variables.LOGGING_DIRECTORY = args.LoggingDirectory.strip()
    else:
        # No explicit --LoggingDirectory: resolve via get_root_public_directory()
        # so the default is install-pinned (not cwd-relative). Picks up
        # --PublicDirectory when set, otherwise {install_dir}/Public/.
        instance_global_variables.LOGGING_DIRECTORY = os.path.join(
            config_utils.get_root_public_directory(), 'logs'
        )

    resolve_logging_directory_user_token()

    if args.UserLevelSqlLiteDirectory and args.UserLevelSqlLiteDirectory.strip():
        instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY = args.UserLevelSqlLiteDirectory.strip().rstrip('/\\')
    if args.DiscussionDirectory and args.DiscussionDirectory.strip():
        instance_global_variables.DISCUSSION_DIRECTORY = args.DiscussionDirectory.strip().rstrip('/\\')

    if args.file_logging is not None:
        instance_global_variables.FILE_LOGGING = args.file_logging

    if args.port is not None:
        instance_global_variables.PORT = args.port
    if args.listen is not None:
        instance_global_variables.LISTEN_ADDRESS = args.listen.strip()

    instance_global_variables.CONCURRENCY_LIMIT = args.concurrency
    instance_global_variables.CONCURRENCY_TIMEOUT = args.concurrency_timeout
    instance_global_variables.CONCURRENCY_LEVEL = args.concurrency_level
