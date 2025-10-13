#!/usr/bin/env python
"""
Eventlet launcher for WilmerAI.
Reads configuration from WilmerAI config files and launches Eventlet WSGI server.
"""

# CRITICAL: Monkey-patch MUST happen before ANY other standard library imports (like sys, argparse, logging).
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    print("Error: Eventlet is not installed. Please install it via pip install eventlet.")
    import sys
    sys.exit(1)

import sys
import argparse
import logging
# Import socket AFTER monkey_patch
import socket
import traceback

# Define a function to parse arguments and set globals
def initialize_globals():
    # Now we can safely import instance_global_variables as stdlib is patched
    # We must import this inside the function scope.
    from Middleware.common import instance_global_variables

    parser = argparse.ArgumentParser(description="Launch WilmerAI with Eventlet")
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
    return instance_global_variables

# Initialize globals
globals_vars = initialize_globals()

# Now we can import config_utils and read the port (stdlib is patched)
# We must import this after initialize_globals().
from Middleware.utilities.config_utils import get_application_port

try:
    port = get_application_port()
    print(f"Read port {port} from WilmerAI user configuration")
    print(f"Config Directory: {globals_vars.CONFIG_DIRECTORY}")
    print(f"User: {globals_vars.USER}")
    print(f"Logging Directory: {globals_vars.LOGGING_DIRECTORY}")
    # Confirmation log
    if eventlet.patcher.is_monkey_patched('socket'):
        print("Eventlet monkey patching confirmed active.")
    else:
        print("CRITICAL WARNING: Eventlet monkey patching failed. Streaming and cancellation may be unreliable.")

except Exception as e:
    print(f"Error reading port from configuration: {e}")
    traceback.print_exc()
    print("Using default port 5000")
    port = 5000

# Import the Flask app (server.py will now run with patched stdlib and configure logging)
# We must import this after all initialization.
from server import application

# Get logger AFTER server.py has configured logging
logger = logging.getLogger(__name__)


class TCPNoDelayListener:
    """
    Wrapper for Eventlet listener that sets TCP_NODELAY on each accepted connection.
    This ensures low-latency streaming by disabling Nagle's algorithm per connection.
    """
    def __init__(self, listener):
        self._listener = listener

    def accept(self):
        """Accept a connection and immediately set TCP_NODELAY on the socket."""
        conn, addr = self._listener.accept()
        try:
            # Eventlet wraps sockets in GreenSocket. Access the underlying socket if needed.
            if hasattr(conn, '_sock'):
                # GreenSocket: set on the wrapped socket
                sock = conn._sock
            else:
                # Regular socket
                sock = conn

            # Set TCP_NODELAY to disable Nagle's algorithm (reduces latency)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            # Reduce send buffer to minimize OS-level buffering
            # This prevents the OS from batching small packets
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)

            logger.debug(f"TCP_NODELAY set on connection from {addr}")
        except Exception as e:
            # Best-effort: log but don't fail the connection
            logger.warning(f"Could not set TCP_NODELAY on connection from {addr}: {e}")
        return conn, addr

    def __getattr__(self, name):
        """Delegate all other methods/attributes to the wrapped listener."""
        return getattr(self._listener, name)


print(f"\n{'=' * 60}")
print(f"Starting WilmerAI with Eventlet WSGI Server")
print(f"Listening on 0.0.0.0:{port}")
# TCP_NODELAY confirmation
print(f"TCP_NODELAY wrapper installed (applied per connection)")
print(f"{'=' * 60}\n")

try:
    # Start Eventlet WSGI server
    import eventlet.wsgi

    # Configure the listener socket
    listener = eventlet.listen(('0.0.0.0', port))

    # Wrap listener to set TCP_NODELAY on each accepted connection
    listener = TCPNoDelayListener(listener)

    eventlet.wsgi.server(
        listener,
        application,
        log_output=False,  # Disable WSGI access logs
        debug=False,
        # Note: max_size in eventlet.wsgi.server refers to the maximum number of concurrent connections.
        max_size=100,
        # CRITICAL: Set minimum_chunk_size to 1 to disable WSGI-level batching
        # This ensures individual tokens are sent immediately instead of being buffered
        minimum_chunk_size=1,
    )
except KeyboardInterrupt:
    print("\nServer stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"Eventlet server failed: {e}")
    traceback.print_exc()
    sys.exit(1)
