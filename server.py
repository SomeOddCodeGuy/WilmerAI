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


def parse_arguments():
    """Parse command-line arguments for configuration."""
    parser = argparse.ArgumentParser(description="Process configuration directory and user arguments.")
    parser.add_argument("--ConfigDirectory", type=str, help="Custom path to the configuration directory")
    parser.add_argument("--User", type=str, help="User to run Wilmer as")
    parser.add_argument("--LoggingDirectory", type=str, default="logs", help="Directory for log files")
    parser.add_argument("positional", nargs="*", help="Positional arguments for ConfigDirectory and User")
    args = parser.parse_args()

    if len(args.positional) > 0 and args.positional[0].strip():
        instance_global_variables.CONFIG_DIRECTORY = args.positional[0].strip().rstrip('/\\')
    if len(args.positional) > 1 and args.positional[1].strip():
        instance_global_variables.USER = args.positional[1].strip()

    if args.ConfigDirectory and args.ConfigDirectory.strip():
        instance_global_variables.CONFIG_DIRECTORY = args.ConfigDirectory.strip().rstrip('/\\')
    if args.User and args.User.strip():
        instance_global_variables.USER = args.User.strip()

    if args.LoggingDirectory and args.LoggingDirectory.strip():
        instance_global_variables.LOGGING_DIRECTORY = args.LoggingDirectory.strip()

    if "<user>" in instance_global_variables.LOGGING_DIRECTORY:
        instance_global_variables.LOGGING_DIRECTORY = instance_global_variables.LOGGING_DIRECTORY.replace(
            "<user>", instance_global_variables.USER
        )


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

    locking_service = LockingService()

    handlers = [logging.StreamHandler()]
    if config_utils.get_use_file_logging():
        log_directory = instance_global_variables.LOGGING_DIRECTORY
        os.makedirs(log_directory, exist_ok=True)
        handlers.append(RotatingFileHandler(
            os.path.join(log_directory, "wilmerai.log"),
            maxBytes=1048576 * 3,
            backupCount=7,
        ))

    logging.basicConfig(
        handlers=handlers,
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info(f"Config Directory: {instance_global_variables.CONFIG_DIRECTORY}")
    logger.info(f"User: {instance_global_variables.USER}")
    logger.info(f"Logging Directory: {instance_global_variables.LOGGING_DIRECTORY}")

    logger.info(
        f"Deleting old locks that do not belong to Wilmer Instance_Id: '{instance_global_variables.INSTANCE_ID}'"
    )
    locking_service.delete_old_locks(instance_global_variables.INSTANCE_ID)

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
    logger.info("Starting Flask development server (use Eventlet/Waitress for production)")
    # Set debug=True to enable auto-reloading if desired.
    server.run(debug=False)