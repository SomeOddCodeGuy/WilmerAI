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
import logging
# Import socket AFTER monkey_patch
import socket
import traceback

# Define a function to parse arguments and set globals
def initialize_globals():
    # Safe only after monkey_patch: these pull in stdlib and
    # Middleware.common/utilities, but not server.py (which initializes the
    # whole app at import time).
    from Middleware.common import instance_global_variables
    from Middleware.common.launch_arguments import parse_and_apply_launch_arguments

    parse_and_apply_launch_arguments("Launch WilmerAI with Eventlet")
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
print("Starting WilmerAI with Eventlet WSGI Server")
print(f"Listening on {host}:{port}")
print("TCP_NODELAY wrapper installed (applied per connection)")
if host == "127.0.0.1":
    print("\n\033[32mUPDATE: WilmerAI now defaults to 127.0.0.1 (localhost")
    print("only). It previously defaulted to 0.0.0.0. To listen on")
    print("all interfaces, use: --listen\033[0m")
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
