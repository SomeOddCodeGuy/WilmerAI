#!/usr/bin/env python
"""
Waitress launcher script for Windows.
Reads the port from WilmerAI config and starts the Waitress WSGI server.
"""

import sys
import argparse
import os

# Parse arguments FIRST to set instance_global_variables before importing anything else
parser = argparse.ArgumentParser(description="Launch WilmerAI with Waitress (Windows)")
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

# Set instance global variables BEFORE any other imports
from Middleware.common import instance_global_variables

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

# Resolve <user> token
log_dir = instance_global_variables.LOGGING_DIRECTORY
if "<user>" in log_dir:
    u = instance_global_variables.USERS
    if u and len(u) == 1:
        instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", u[0])
    elif u and len(u) > 1:
        print(
            f"WARNING: <user> token in --LoggingDirectory is not supported in multi-user mode. "
            f"Stripping token. Per-user log files are created automatically.",
            file=sys.stderr,
        )
        instance_global_variables.LOGGING_DIRECTORY = log_dir.replace("<user>", "").rstrip(os.sep)

if args.file_logging is not None:
    instance_global_variables.FILE_LOGGING = args.file_logging

if args.port is not None:
    instance_global_variables.PORT = args.port
if args.listen is not None:
    instance_global_variables.LISTEN_ADDRESS = args.listen.strip()

instance_global_variables.CONCURRENCY_LIMIT = args.concurrency
instance_global_variables.CONCURRENCY_TIMEOUT = args.concurrency_timeout

# Import the server module which will configure logging
try:
    from server import application, resolve_port
    from waitress import serve

    # Get logger AFTER server.py has configured logging
    import logging
    logger = logging.getLogger(__name__)

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
        print(f"\n\033[32mUPDATE: WilmerAI now defaults to 127.0.0.1 (localhost")
        print(f"only). It previously defaulted to 0.0.0.0. To listen on")
        print(f"all interfaces, use: --listen\033[0m\n")
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
