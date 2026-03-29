"""
Thread-safe logging utilities for protecting sensitive content.

The module provides a thread-local (greenlet-local under Eventlet) context
that tracks whether the current request should have its log output redacted.
Redaction activates when the user has encryption enabled (``encryptUsingApiKey``)
or when ``redactLogOutput`` is set to ``true`` in the user config. Log helper
functions check this context and either emit the message normally or replace
it with a short redacted placeholder.

Usage at request entry points (API handlers)::

    from Middleware.utilities.sensitive_logging_utils import (
        set_encryption_context, clear_encryption_context, is_encryption_active,
    )

    api_key = api_helpers.extract_api_key()
    set_encryption_context(
        (bool(api_key) and get_encrypt_using_api_key()) or get_redact_log_output()
    )
    try:
        ...
    finally:
        clear_encryption_context()

For eventlet greenlets / streaming generators that run outside the original
request context, capture and re-set::

    captured_encryption = is_encryption_active()

    def backend_reader():
        set_encryption_context(captured_encryption)
        ...

Usage at logging sites::

    from Middleware.utilities.sensitive_logging_utils import (
        sensitive_log, log_prompt_content,
    )

    # For general sensitive content:
    sensitive_log(logger, logging.DEBUG, "Payload: %s", payload)

    # For the common "Formatted_Prompt" / "Raw output from the LLM" pattern:
    log_prompt_content(logger, "Formatted_Prompt", full_prompt_log)
"""

import logging
import threading
from typing import Any, Callable

_request_context = threading.local()

_REDACTION_MARKER = "[Redacted]"


def set_encryption_context(active: bool) -> None:
    """Mark the current thread/greenlet as handling an encrypted user's request."""
    _request_context.encryption_active = active


def clear_encryption_context() -> None:
    """Clear the encryption context for the current thread/greenlet."""
    _request_context.encryption_active = False


def is_encryption_active() -> bool:
    """Check whether the current request belongs to an encrypted user."""
    return getattr(_request_context, 'encryption_active', False)


def sensitive_log(logger: logging.Logger, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
    """Log *msg* if encryption is not active, otherwise emit a redacted placeholder.

    Accepts the same positional/keyword arguments as ``logger.log()``.
    """
    if is_encryption_active():
        logger.log(level, _REDACTION_MARKER, **kwargs)
    else:
        logger.log(level, msg, *args, **kwargs)


def sensitive_log_lazy(logger: logging.Logger, level: int, msg: str, *arg_fns: Callable[[], Any]) -> None:
    """Like ``sensitive_log`` but accepts zero-arg callables instead of values.

    Each callable in *arg_fns* is only invoked when encryption is inactive,
    avoiding expensive serialization (e.g. ``json.dumps``) when the result
    would be redacted anyway.

    Example::

        sensitive_log_lazy(logger, logging.DEBUG,
                           "Request data (ID: %s): %s",
                           lambda: request_id,
                           lambda: json.dumps(_sanitize_log_data(data)))
    """
    if is_encryption_active():
        logger.log(level, _REDACTION_MARKER)
    else:
        logger.log(level, msg, *(fn() for fn in arg_fns))


def log_prompt_content(logger: logging.Logger, label: str, content: str) -> None:
    """Log prompt or LLM output with separator lines, or redact when encrypted.

    This replaces the repeated pattern::

        logger.info("\\n\\n*****...\\n")
        logger.info("\\n\\nFormatted_Prompt: %s", content)
        logger.info("\\n*****...\\n\\n")

    When encryption is active the three lines are replaced by a single
    redacted marker so that the log flow is still visible without leaking
    user content.
    """
    if is_encryption_active():
        logger.info("[%s redacted]", label)
    else:
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\n%s: %s", label, content)
        logger.info("\n*****************************************************************************\n\n")
