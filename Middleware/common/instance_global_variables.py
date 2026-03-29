# Middleware/common/instance_global_variables

import threading
import uuid

INSTANCE_ID = str(uuid.uuid4())
CONFIG_DIRECTORY = None
USERS = None
LOGGING_DIRECTORY = "logs"
FILE_LOGGING = None  # None = check user's config (single-user) or default off (multi-user); True/False = explicit CLI flag
CONCURRENCY_LIMIT = 1
CONCURRENCY_TIMEOUT = 900
PORT = None  # None = resolve from user config (single-user) or default (multi-user)
LISTEN_ADDRESS = "127.0.0.1"  # Bind address; use --listen to expose on network (0.0.0.0)
_request_semaphore = None


def initialize_request_semaphore(n: int):
    """Creates a BoundedSemaphore if n > 0. Called once at startup."""
    global _request_semaphore
    if n > 0:
        _request_semaphore = threading.BoundedSemaphore(n)


def get_request_semaphore():
    """Returns the semaphore, or None if concurrency limiting is disabled."""
    return _request_semaphore


# Request-scoped state stored in thread-local (greenlet-local under eventlet)
# so that concurrent requests don't clobber each other's values.
_request_context = threading.local()


def get_api_type() -> str:
    """Returns the API type for the current request, defaulting to 'openai'."""
    return getattr(_request_context, 'api_type', 'openai')


def set_api_type(value: str) -> None:
    """Sets the API type for the current request."""
    _request_context.api_type = value


def get_workflow_override():
    """Returns the workflow override for the current request, or None."""
    return getattr(_request_context, 'workflow_override', None)


def set_workflow_override(value) -> None:
    """Sets the workflow override for the current request."""
    _request_context.workflow_override = value


def clear_api_type() -> None:
    """Resets the API type for the current request to the default."""
    _request_context.api_type = 'openai'


def clear_workflow_override() -> None:
    """Clears the workflow override for the current request."""
    _request_context.workflow_override = None


def get_request_user():
    """Returns the request-scoped user for the current request, or None."""
    return getattr(_request_context, 'request_user', None)


def set_request_user(value) -> None:
    """Sets the request-scoped user for the current request."""
    _request_context.request_user = value


def clear_request_user() -> None:
    """Clears the request-scoped user for the current request."""
    _request_context.request_user = None
