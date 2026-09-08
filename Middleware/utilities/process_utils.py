"""Lifecycle ownership for configured subprocesses with bounded pipe readers."""

import subprocess
import sys
import threading

from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)


def run_process_readers(process, timeout: float, readers) -> bool:
    """Wait for a child while draining its pipes and clean up every exit path.

    Args:
        process: Owned Popen child with stdout and stderr pipes.
        timeout (float): Maximum ordinary wait time in seconds.
        readers: Iterable of (callable, arguments) pairs for bounded pipe readers.

    Returns:
        bool: True when the ordinary process wait timed out.

    Raises:
        BaseException: Original startup/wait interruption, after stopping the child.
    """
    threads = []
    completed = False
    timed_out = False
    try:
        for target, args in readers:
            thread = threading.Thread(target=target, args=args, daemon=True)
            threads.append(thread)
            thread.start()
        try:
            process.wait(timeout=timeout)
            completed = True
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        original_error = sys.exc_info()[1]
        cleanup_errors = []

        def cleanup(action):
            """Attempt cleanup without masking an interruption already in flight.

            Args:
                action (Callable[[], None]): Cleanup operation; errors other than ProcessLookupError
                    are collected for later handling.
            """
            try:
                action()
            except ProcessLookupError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)

        if not completed:
            cleanup(process.kill)
            cleanup(lambda: process.wait(timeout=1))
        for thread in threads:
            if thread.ident is not None:
                cleanup(lambda: thread.join(timeout=1))
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                cleanup(pipe.close)
        if cleanup_errors:
            if original_error is None:
                raise cleanup_errors[0]
            logger.debug("Subprocess cleanup failed while propagating an interruption.")
    return timed_out
