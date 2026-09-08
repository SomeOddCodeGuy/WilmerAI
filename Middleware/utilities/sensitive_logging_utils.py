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
        begin_request_privacy, resolve_request_privacy, clear_encryption_context,
    )

    try:
        begin_request_privacy()
        api_key = api_helpers.extract_api_key()
        ...  # Identify the request's user before reading that user's policy.
        resolve_request_privacy(
            (bool(api_key) and get_encrypt_using_api_key()) or get_redact_log_output()
        )
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

from flask import g, has_request_context

_request_context = threading.local()

_REDACTION_MARKER = "[Redacted]"


def set_encryption_context(active: bool) -> None:
    """Set log redaction for the current thread or greenlet.

    Args:
        active (bool): Whether request diagnostics require encryption-related or explicit
            log redaction.
    """
    _request_context.encryption_active = active
    if active and has_request_context():
        # Flask logs unhandled view exceptions after the view clears thread state.
        g._wilmer_redact_request_errors = True


def begin_request_privacy() -> None:
    """Redact ingress diagnostics until the request's user policy is resolved."""
    set_encryption_context(True)


def resolve_request_privacy(active: bool) -> None:
    """Replace provisional ingress privacy with the selected user's policy.

    Args:
        active (bool): Whether encryption or explicit log redaction is enabled.
    """
    set_encryption_context(active)
    if has_request_context():
        # Only policy resolution may clear the provisional Flask error marker.
        g._wilmer_redact_request_errors = bool(active)


class _RequestErrorFilter(logging.Filter):
    """Retain request error redaction until Flask finishes handling the request."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact Flask error records under the active request policy.

        Args:
            record (logging.LogRecord): Record updated in place when redaction is required.

        Returns:
            bool: Always True so the redacted or original record is emitted.
        """
        if has_request_context() and getattr(g, '_wilmer_redact_request_errors', False):
            record.msg = _REDACTION_MARKER
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def protect_flask_error_logging(app) -> None:
    """Install request-scoped redaction on Flask's own exception logger.

    Args:
        app: Flask application whose view exceptions must honor redaction.
    """
    if not any(isinstance(item, _RequestErrorFilter) for item in app.logger.filters):
        app.logger.addFilter(_RequestErrorFilter())


def clear_encryption_context() -> None:
    """Clear the encryption context for the current thread/greenlet."""
    _request_context.encryption_active = False


def is_encryption_active() -> bool:
    """Check the current thread or greenlet log-redaction policy.

    Returns:
        bool: Whether sensitive request diagnostics must be redacted.
    """
    return getattr(_request_context, 'encryption_active', False)


def sensitive_log(logger: logging.Logger, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
    """Emit a log message or the current request redaction placeholder.

    Args:
        logger (logging.Logger): Destination logger.
        level (int): Logging severity.
        msg (str): Message or format string.
        *args (Any): Message-formatting values, omitted under redaction.
        **kwargs (Any): Logging options; exception and stack details are removed under
            redaction.
    """
    if is_encryption_active():
        kwargs.pop('exc_info', None)
        kwargs.pop('stack_info', None)
        logger.log(level, _REDACTION_MARKER, **kwargs)
    else:
        logger.log(level, msg, *args, **kwargs)


class _SensitiveLogger(logging.LoggerAdapter):
    """Apply request redaction to built-in module and extension diagnostics."""

    def log(self, level, msg, *args, **kwargs):
        """Log through the shared redaction boundary, including exception details.

        Args:
            level (int): Logging severity for the message.
            msg (str): Message or format string, replaced when redaction is active.
            *args: Message-formatting values, omitted when redaction is active.
            **kwargs: Logging options; exception and stack details are removed
                when redaction is active.
        """
        sensitive_log(self.logger, level, msg, *args, **kwargs)


def get_sensitive_logger(name: str) -> logging.LoggerAdapter:
    """Return a logger that applies the current request's redaction policy.

    Args:
        name (str): Logger namespace for the calling module.

    Returns:
        logging.LoggerAdapter: Context-aware logger with the ordinary logging methods.
    """
    return _SensitiveLogger(logging.getLogger(name), {})


def sensitive_log_lazy(logger: logging.Logger, level: int, msg: str, *arg_fns: Callable[[], Any]) -> None:
    """Evaluate log values only when request redaction is inactive.

    Args:
        logger (logging.Logger): Destination logger.
        level (int): Logging severity.
        msg (str): Message format string.
        *arg_fns (Callable[[], Any]): Deferred formatting values; never invoked under
            redaction.
    """
    if is_encryption_active():
        logger.log(level, _REDACTION_MARKER)
    else:
        logger.log(level, msg, *(fn() for fn in arg_fns))


def log_prompt_content(logger: logging.Logger, label: str, content: str) -> None:
    """Log labeled prompt content with separators, or a redacted label.

    Args:
        logger (logging.Logger): Destination logger.
        label (str): Public diagnostic label retained under redaction.
        content (str): Prompt or model output omitted under redaction.
    """
    if is_encryption_active():
        logger.info("[%s redacted]", label)
    else:
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\n%s: %s", label, content)
        logger.info("\n*****************************************************************************\n\n")
