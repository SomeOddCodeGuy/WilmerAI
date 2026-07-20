# server.py
# NOTE: When using Eventlet, monkey-patching is handled by run_eventlet.py
# Do NOT monkey-patch here as it must happen before ANY imports

import sys
import logging
import os
from logging.handlers import RotatingFileHandler

# The main import is now the ApiServer, not WilmerApi
from Middleware.api.api_server import ApiServer
from Middleware.common import instance_global_variables
from Middleware.common.launch_arguments import parse_and_apply_launch_arguments
from Middleware.common.server_startup import UserInjectionFilter, UserRoutingFileHandler, resolve_file_logging, \
    resolve_port
from Middleware.services.locking_service import LockingService
from Middleware.utilities import config_utils

logger = logging.getLogger(__name__)


def initialize_app():
    """
    Initialize the application: configure logging, clean up locks, and create ApiServer.
    This function is called at module level so WSGI servers can import the initialized app.

    Note: When run via WSGI server (Eventlet/Waitress), the launcher script sets
    instance_global_variables before importing this module. When run directly,
    the shared launch-argument parser sets them.
    """
    # Parse arguments if running directly
    if __name__ == '__main__':
        parse_and_apply_launch_arguments("Process configuration directory and user arguments.")

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
    use_file_logging = resolve_file_logging()

    user_filter = UserInjectionFilter()
    log_format = "[%(asctime)s] %(levelname)s [%(wilmer_user)s] [%(name)s.%(funcName)s:%(lineno)d] %(message)s"
    log_formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    handlers = [logging.StreamHandler()]
    for h in handlers:
        h.addFilter(user_filter)

    is_multi_user = users and len(users) > 1

    if use_file_logging:
        log_directory = os.path.expanduser(instance_global_variables.LOGGING_DIRECTORY)
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
        logger.info(
            f"Concurrency limit: {instance_global_variables.CONCURRENCY_LIMIT} "
            f"(level: {instance_global_variables.CONCURRENCY_LEVEL})"
        )
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
        print("\n\033[32mUPDATE: WilmerAI now defaults to 127.0.0.1 (localhost")
        print("only). It previously defaulted to 0.0.0.0. To listen on")
        print("all interfaces, use: --listen\033[0m\n")
    server.app.run(host=host, port=port, debug=False)
