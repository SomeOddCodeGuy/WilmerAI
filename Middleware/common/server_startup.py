# server_startup.py
# Startup helpers shared by the server entry point. Lives outside server.py so
# it can be imported (e.g. by tests) without triggering server.py's
# module-level application initialization, which configures logging and
# touches the lock database.

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from Middleware.common import instance_global_variables
from Middleware.utilities import config_utils


class UserInjectionFilter(logging.Filter):
    """Injects the current request-scoped username into every log record.

    Adds a ``wilmer_user`` attribute that defaults to ``"system"`` when no
    request context is active (e.g. during startup or background tasks).
    """

    def filter(self, record):
        user = instance_global_variables.get_request_user()
        record.wilmer_user = user if user else "system"
        return True


class UserRoutingFileHandler(logging.Handler):
    """Routes log records to per-user RotatingFileHandler instances.

    In multi-user mode, maintains one RotatingFileHandler per user plus a
    ``system`` handler for startup and background logs::

        {log_directory}/
            wilmerai.log              <- system/startup logs
            bob/wilmerai.log          <- Bob's request logs
            jill/wilmerai.log         <- Jill's request logs

    Records are routed based on ``record.wilmer_user`` (set by
    ``UserInjectionFilter``).
    """

    def __init__(self, log_directory, max_bytes=1048576 * 3, backup_count=7):
        super().__init__()
        self._log_directory = log_directory
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handlers = {}

    def _get_handler(self, user):
        if user not in self._handlers:
            if user == "system":
                log_path = os.path.join(self._log_directory, "wilmerai.log")
            else:
                user_dir = os.path.join(self._log_directory, user)
                os.makedirs(user_dir, exist_ok=True)
                log_path = os.path.join(user_dir, "wilmerai.log")
            handler = RotatingFileHandler(
                log_path,
                maxBytes=self._max_bytes,
                backupCount=self._backup_count,
            )
            handler.setFormatter(self.formatter)
            self._handlers[user] = handler
        return self._handlers[user]

    def emit(self, record):
        user = getattr(record, 'wilmer_user', 'system')
        handler = self._get_handler(user)
        handler.emit(record)

    def close(self):
        for handler in self._handlers.values():
            handler.close()
        self._handlers.clear()
        super().close()


_MULTI_USER_DEFAULT_PORT = 5050


def resolve_port():
    """Resolve the port to listen on.

    Priority:
    1. CLI ``--port`` flag (stored in ``instance_global_variables.PORT``).
    2. Single-user mode: read from the user's config file (backwards compatible).
    3. Multi-user mode: default to 5050 with a warning that per-user port
       settings do not apply.

    Returns:
        int: The resolved port number.
    """
    if instance_global_variables.PORT is not None:
        return instance_global_variables.PORT

    users = instance_global_variables.USERS or []
    is_multi_user = len(users) > 1

    if is_multi_user:
        print(
            f"WARNING: Per-user 'port' config settings are ignored in multi-user mode. "
            f"Use --port to specify a port. Defaulting to {_MULTI_USER_DEFAULT_PORT}.",
            file=sys.stderr,
        )
        return _MULTI_USER_DEFAULT_PORT

    # Single-user or no-user: read from user config (backwards compatible)
    try:
        if users:
            return config_utils.get_user_config_for(users[0]).get('port', 5000)
        return config_utils.get_application_port() or 5000
    except Exception as e:
        print(f"Could not read port from user config: {e}. Using default 5000.", file=sys.stderr)
        return 5000


def resolve_file_logging():
    """Resolve whether file logging is enabled.

    Priority:
    1. CLI ``--file-logging`` flag (stored in ``instance_global_variables.FILE_LOGGING``).
    2. Single-user mode: the user's ``useFileLogging`` config setting.
    3. Legacy mode (no ``--User`` arg): ``useFileLogging`` from the
       ``_current-user.json`` user's config.
    4. Multi-user mode: off unless the flag is passed.

    Config read failures degrade to ``False`` rather than blocking startup.

    Returns:
        bool: True when file logging should be enabled.
    """
    if instance_global_variables.FILE_LOGGING is not None:
        return instance_global_variables.FILE_LOGGING

    users = instance_global_variables.USERS or []
    if len(users) == 1:
        try:
            return config_utils.get_user_config_for(users[0]).get('useFileLogging', False)
        except Exception:
            return False
    if not users:
        try:
            return config_utils.get_user_config().get('useFileLogging', False)
        except Exception:
            return False
    # Multi-user without --file-logging flag: default off
    return False
