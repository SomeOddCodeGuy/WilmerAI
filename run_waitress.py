#!/usr/bin/env python
"""
Waitress launcher script for Windows.
Reads the port from WilmerAI config and starts the Waitress WSGI server.
"""

import sys
import argparse

# Parse arguments FIRST to set instance_global_variables before importing anything else
parser = argparse.ArgumentParser(description="Launch WilmerAI with Waitress (Windows)")
parser.add_argument("--ConfigDirectory", type=str, help="Custom path to the configuration directory")
parser.add_argument("--User", type=str, help="User to run Wilmer as")
parser.add_argument("--LoggingDirectory", type=str, default="logs", help="Directory for log files")
parser.add_argument("positional", nargs="*", help="Positional arguments for ConfigDirectory and User")
args = parser.parse_args()

# Set instance global variables BEFORE any other imports
from Middleware.common import instance_global_variables

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

# Import the server module which will configure logging
try:
    from server import application
    from waitress import serve
    from Middleware.utilities.config_utils import get_application_port

    # Get logger AFTER server.py has configured logging
    import logging
    logger = logging.getLogger(__name__)

    print(f"Config Directory: {instance_global_variables.CONFIG_DIRECTORY}")
    print(f"User: {instance_global_variables.USER}")
    print(f"Logging Directory: {instance_global_variables.LOGGING_DIRECTORY}")

    # Read the port from WilmerAI config
    try:
        port = get_application_port()
        logger.info(f"Read port {port} from WilmerAI configuration")
    except Exception as e:
        logger.warning(f"Could not read port from config: {e}. Using default port 5000")
        port = 5000

    # Configure Waitress
    # threads: Number of threads for handling requests
    # channel_timeout: Timeout for idle connections (set high for LLM requests)
    # url_scheme: Use http (https requires additional configuration)
    # asyncore_use_poll: Better performance on Windows

    logger.info(f"Starting WilmerAI with Waitress on 0.0.0.0:{port}")
    logger.info("Press Ctrl+C to stop the server")

    serve(
        application,
        host='0.0.0.0',
        port=port,
        threads=8,  # Number of worker threads
        channel_timeout=14400,  # 4 hours (matches LLM API timeout)
        asyncore_use_poll=True,  # Better performance on Windows
        url_scheme='http',
        expose_tracebacks=False,  # Don't expose tracebacks in production
        clear_untrusted_proxy_headers=True,  # Security
    )

except KeyboardInterrupt:
    logger.info("Server stopped by user")
    sys.exit(0)
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}")
    logger.error("Make sure waitress is installed: pip install waitress")
    sys.exit(1)
except Exception as e:
    logger.error(f"Failed to start Waitress: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
