# server.py
# NOTE: When using Eventlet, monkey-patching is handled by run_eventlet.py
# Do NOT monkey-patch here as it must happen before ANY imports

import sys
import argparse
import logging
import os
from logging.handlers import RotatingFileHandler

# The main import is now the ApiServer, not WilmerApi
from Middleware.api.api_server import ApiServer
from Middleware.services.locking_service import LockingService
from Middleware.utilities import config_utils
from Middleware.common import instance_global_variables

logger = logging.getLogger(__name__)


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


def _resolve_logging_directory():
    """Resolve the ``<user>`` token in LOGGING_DIRECTORY at startup.

    - Single-user: replace ``<user>`` with ``USERS[0]`` (backward compatible).
    - Multi-user: warn and strip ``<user>`` from the path.
    """
    log_dir = instance_global_variables.LOGGING_DIRECTORY
    if "<user>" not in log_dir:
        return
    users = instance_global_variables.USERS
    if users and len(users) == 1:
        instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", users[0])
    elif users and len(users) > 1:
        print(
            f"WARNING: <user> token in --LoggingDirectory is not supported in multi-user mode. "
            f"Stripping token. Per-user log files are created automatically.",
            file=sys.stderr,
        )
        instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", "").rstrip(os.sep)


def parse_arguments():
    """Parse command-line arguments for configuration."""
    parser = argparse.ArgumentParser(description="Process configuration directory and user arguments.")
    parser.add_argument("--ConfigDirectory", type=str, help="Custom path to the configuration directory")
    parser.add_argument("--User", action='append', help="User to run Wilmer as (can be repeated for multi-user)")
    parser.add_argument("--LoggingDirectory", type=str, default="logs", help="Directory for log files")
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
    if args.User:
        users = [u.strip() for u in args.User if u.strip()]
        if users:
            instance_global_variables.USERS = users

    if args.LoggingDirectory and args.LoggingDirectory.strip():
        instance_global_variables.LOGGING_DIRECTORY = args.LoggingDirectory.strip()

    _resolve_logging_directory()

    if args.file_logging is not None:
        instance_global_variables.FILE_LOGGING = args.file_logging

    if args.port is not None:
        instance_global_variables.PORT = args.port
    if args.listen is not None:
        instance_global_variables.LISTEN_ADDRESS = args.listen.strip()

    instance_global_variables.CONCURRENCY_LIMIT = args.concurrency
    instance_global_variables.CONCURRENCY_TIMEOUT = args.concurrency_timeout


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


def initialize_app():
    """
    Initialize the application: configure logging, clean up locks, and create ApiServer.
    This function is called at module level so WSGI servers can import the initialized app.

    Note: When run via WSGI server (Eventlet/Waitress), the launcher script sets
    instance_global_variables before importing this module. When run directly,
    parse_arguments() sets them.
    """
    # Parse arguments if running directly
    if __name__ == '__main__':
        parse_arguments()

    # Validate that all configured users have config files
    users = instance_global_variables.USERS or []
    if users:
        config_dir = config_utils.get_root_config_directory()
        for user in users:
            user_config_path = os.path.join(str(config_dir), 'Users', f'{user.lower()}.json')
            if not os.path.isfile(user_config_path):
                print(f"ERROR: Config file not found for user '{user}': {user_config_path}", file=sys.stderr)
                sys.exit(1)

    # Determine file logging: CLI flag takes precedence.
    # Single-user: falls back to the user's useFileLogging config setting.
    # Multi-user: defaults to off (requires explicit --file-logging flag).
    if instance_global_variables.FILE_LOGGING is not None:
        use_file_logging = instance_global_variables.FILE_LOGGING
    elif users and len(users) == 1:
        try:
            first_user_config = config_utils.get_user_config_for(users[0])
            use_file_logging = first_user_config.get('useFileLogging', False)
        except Exception:
            use_file_logging = False
    elif not users:
        # Legacy mode (no --User arg, uses _current-user.json)
        try:
            legacy_config = config_utils.get_user_config()
            use_file_logging = legacy_config.get('useFileLogging', False)
        except Exception:
            use_file_logging = False
    else:
        # Multi-user without --file-logging flag: default off
        use_file_logging = False

    user_filter = UserInjectionFilter()
    log_format = "[%(asctime)s] %(levelname)s [%(wilmer_user)s] [%(name)s.%(funcName)s:%(lineno)d] %(message)s"
    log_formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    handlers = [logging.StreamHandler()]
    for h in handlers:
        h.addFilter(user_filter)

    is_multi_user = users and len(users) > 1

    if use_file_logging:
        log_directory = instance_global_variables.LOGGING_DIRECTORY
        os.makedirs(log_directory, exist_ok=True)
        if is_multi_user:
            file_handler = UserRoutingFileHandler(log_directory)
            file_handler.setFormatter(log_formatter)
            file_handler.addFilter(user_filter)
            handlers.append(file_handler)
        else:
            file_handler = RotatingFileHandler(
                os.path.join(log_directory, "wilmerai.log"),
                maxBytes=1048576 * 3,
                backupCount=7,
            )
            file_handler.addFilter(user_filter)
            handlers.append(file_handler)

    logging.basicConfig(
        handlers=handlers,
        level=logging.INFO,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info(f"Config Directory: {instance_global_variables.CONFIG_DIRECTORY}")
    if is_multi_user:
        logger.info(f"Users: {', '.join(users)}")
    elif users:
        logger.info(f"User: {users[0]}")
    logger.info(f"Logging Directory: {instance_global_variables.LOGGING_DIRECTORY}")

    logger.info(
        f"Deleting old locks that do not belong to Wilmer Instance_Id: '{instance_global_variables.INSTANCE_ID}'"
    )
    lock_users = users if users else [None]
    for lock_user in lock_users:
        if lock_user:
            instance_global_variables.set_request_user(lock_user)
        try:
            locking_service = LockingService()
            locking_service.delete_old_locks(instance_global_variables.INSTANCE_ID)
        finally:
            instance_global_variables.clear_request_user()

    instance_global_variables.initialize_request_semaphore(instance_global_variables.CONCURRENCY_LIMIT)
    if instance_global_variables.CONCURRENCY_LIMIT > 0:
        logger.info(f"Concurrency limit: {instance_global_variables.CONCURRENCY_LIMIT}")
    else:
        logger.info("No concurrency limit")

    logger.info("Initializing API Server")

    # Instantiate the new ApiServer
    server = ApiServer()
    return server


# Initialize the server at module level
# When imported by WSGI servers (Eventlet/Waitress), this creates the Flask app
server = initialize_app()

# Expose the Flask app for WSGI servers
# WSGI servers (Eventlet, Waitress, etc.) will import this 'application' object
application = server.app


def get_application():
    """
    Returns the initialized Flask application.
    This function is used by waitress-serve on Windows with the --call flag.

    Returns:
        Flask: The initialized Flask application instance.
    """
    return application


if __name__ == '__main__':
    # When run directly (not via Eventlet/Waitress), start the Flask development server
    port = resolve_port()
    host = instance_global_variables.LISTEN_ADDRESS
    logger.info(f"Starting Flask development server on {host}:{port} (use Eventlet/Waitress for production)")
    if host == "127.0.0.1":
        print(f"\n\033[32mUPDATE: WilmerAI now defaults to 127.0.0.1 (localhost")
        print(f"only). It previously defaulted to 0.0.0.0. To listen on")
        print(f"all interfaces, use: --listen\033[0m\n")
    server.app.run(host=host, port=port, debug=False)
