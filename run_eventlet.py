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

    # Resolve <user> token -- delegate to server._resolve_logging_directory at import time.
    # For now, handle it inline to avoid importing server.py too early.
    import os
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

    return instance_global_variables

# Initialize globals
globals_vars = initialize_globals()

# Import the Flask app (server.py will now run with patched stdlib and configure logging)
# We must import this after all initialization.
from server import application, resolve_port

try:
    port = resolve_port()
    print(f"Listening port: {port}")
    print(f"Config Directory: {globals_vars.CONFIG_DIRECTORY}")
    if globals_vars.USERS and len(globals_vars.USERS) > 1:
        print(f"Users: {', '.join(globals_vars.USERS)}")
    elif globals_vars.USERS:
        print(f"User: {globals_vars.USERS[0]}")
    print(f"Logging Directory: {globals_vars.LOGGING_DIRECTORY}")
    # Confirmation log
    if eventlet.patcher.is_monkey_patched('socket'):
        print("Eventlet monkey patching confirmed active.")
    else:
        print("CRITICAL WARNING: Eventlet monkey patching failed. Streaming and cancellation may be unreliable.")

except Exception as e:
    print(f"Error resolving port: {e}")
    traceback.print_exc()
    print("Using default port 5000")
    port = 5000

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


host = globals_vars.LISTEN_ADDRESS

print(f"\n{'=' * 60}")
print(f"Starting WilmerAI with Eventlet WSGI Server")
print(f"Listening on {host}:{port}")
print(f"TCP_NODELAY wrapper installed (applied per connection)")
if host == "127.0.0.1":
    print(f"\n\033[32mUPDATE: WilmerAI now defaults to 127.0.0.1 (localhost")
    print(f"only). It previously defaulted to 0.0.0.0. To listen on")
    print(f"all interfaces, use: --listen\033[0m")
print(f"{'=' * 60}\n")

try:
    # Start Eventlet WSGI server
    import eventlet.wsgi

    # Configure the listener socket
    listener = eventlet.listen((host, port))

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
        # Disable HTTP keep-alive to force connection teardown after every response.
        # Without this, some front-ends (notably Node.js-based apps like SillyTavern)
        # can have their HTTP connection pool corrupted by keep-alive connections that
        # outlive a streaming response. This ensures the server sends Connection: close
        # at the protocol level and closes the socket after the response completes.
        keepalive=False,
        # Safety net: time out idle client sockets after 60 seconds. Prevents zombie
        # connections from accumulating if a client fails to close its end.
        socket_timeout=60,
    )
except KeyboardInterrupt:
    print("\nServer stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"Eventlet server failed: {e}")
    traceback.print_exc()
    sys.exit(1)
