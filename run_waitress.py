#!/usr/bin/env python
"""
Waitress launcher script for Windows.
Reads the port from WilmerAI config and starts the Waitress WSGI server.
"""

import logging
import sys

# Parse arguments and stamp instance_global_variables BEFORE importing server.py,
# which initializes the whole app at import time.
from Middleware.common import instance_global_variables
from Middleware.common.launch_arguments import parse_and_apply_launch_arguments

parse_and_apply_launch_arguments("Launch WilmerAI with Waitress (Windows)")

# Bound before the try block: the except handlers below must be able to log
# even when the server/waitress imports themselves fail. Records emitted
# before server.py configures logging fall back to Python's default handling.
logger = logging.getLogger(__name__)

# Import the server module which will configure logging
try:
    from server import application, resolve_port
    from waitress import serve

    print(f"Config Directory: {instance_global_variables.CONFIG_DIRECTORY}")
    if instance_global_variables.USERS and len(instance_global_variables.USERS) > 1:
        print(f"Users: {', '.join(instance_global_variables.USERS)}")
    elif instance_global_variables.USERS:
        print(f"User: {instance_global_variables.USERS[0]}")
    print(f"Logging Directory: {instance_global_variables.LOGGING_DIRECTORY}")

    port = resolve_port()
    host = instance_global_variables.LISTEN_ADDRESS

    # Configure Waitress
    # threads: Number of threads for handling requests
    # channel_timeout: Timeout for idle connections (set high for LLM requests)
    # url_scheme: Use http (https requires additional configuration)
    # asyncore_use_poll: Better performance on Windows

    logger.info(f"Starting WilmerAI with Waitress on {host}:{port}")
    if host == "127.0.0.1":
        print("\n\033[32mUPDATE: WilmerAI now defaults to 127.0.0.1 (localhost")
        print("only). It previously defaulted to 0.0.0.0. To listen on")
        print("all interfaces, use: --listen\033[0m\n")
    logger.info("Press Ctrl+C to stop the server")

    serve(
        application,
        host=host,
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
