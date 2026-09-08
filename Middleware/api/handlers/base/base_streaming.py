# Middleware/api/handlers/base/base_streaming.py
#
# Shared streaming machinery for the API handlers. The OpenAI and Ollama handlers
# stream identically except for four values (log label, heartbeat bytes, mimetype,
# and the stream-terminator predicate), which each handler supplies through a
# StreamingApiConfig. The base_ filename prefix keeps this module out of the
# ApiServer's handler discovery walk.

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List

try:
    import eventlet
    from eventlet.queue import Queue as EventletQueue, Empty as EventletQueueEmpty
    # greenlet is a hard dependency of eventlet; only needed on the eventlet path
    from greenlet import GreenletExit

    EVENTLET_AVAILABLE = True
except ImportError:
    EVENTLET_AVAILABLE = False
    import queue

    EventletQueueEmpty = queue.Empty

from flask import Response, stream_with_context
from werkzeug.exceptions import ClientDisconnected

from Middleware.api import api_helpers
from Middleware.common import instance_global_variables
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.utilities.sensitive_logging_utils import set_encryption_context, is_encryption_active

from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)

# Frequent heartbeats expose disconnects during prefill before more workflow work starts.
HEARTBEAT_INTERVAL = 1  # seconds


@dataclass(frozen=True)
class StreamingApiConfig:
    """The per-API values that differentiate the shared streaming implementations.

    Attributes:
        api_label (str): API name used as the prefix in operator-facing log
                         messages (e.g. "OpenAI", "Ollama").
        heartbeat_message (bytes): Encoded keep-alive chunk sent while the
                                   backend is idle.
        mimetype (str): Content type of the streaming HTTP response.
        chunk_signals_done (Callable[[bytes], bool]): Predicate that reports
            whether an encoded chunk carries the API's stream terminator.
    """
    api_label: str
    heartbeat_message: bytes
    mimetype: str
    chunk_signals_done: Callable[[bytes], bool]


def _capture_request_context() -> tuple:
    """Snapshots request-scoped state for later restoration off the request thread.

    The calling view's finally block clears these values before the streaming
    generator (or backend greenlet) first runs, so they must be captured while
    the request context is still intact.

    Returns:
        tuple: An opaque snapshot for _restore_request_context.
    """
    return (
        api_helpers.get_active_workflow_override(),
        instance_global_variables.get_api_type(),
        is_encryption_active(),
        instance_global_variables.get_request_user(),
    )


def _restore_request_context(snapshot: tuple) -> None:
    """Restores request-scoped state captured by _capture_request_context.

    Args:
        snapshot (tuple): The value returned by _capture_request_context.
    """
    workflow_override, api_type, encryption_active, request_user = snapshot
    instance_global_variables.set_workflow_override(workflow_override)
    instance_global_variables.set_api_type(api_type)
    instance_global_variables.set_request_user(request_user)
    set_encryption_context(encryption_active)


class _RequestContextIterator:
    """Restore request state only while WSGI advances or closes the owned iterator."""

    def __init__(self, body, snapshot, on_close):
        """Bind response iteration and cleanup to a captured request context.

        Args:
            body: Iterable of encoded response chunks.
            snapshot (tuple): Request state captured by _capture_request_context.
            on_close (Optional[Callable]): Cleanup callback, including when iteration never
                starts.
        """
        self._body = iter(body)
        self._snapshot = snapshot
        self._on_close = on_close
        self._closed = False

    def __iter__(self):
        """Expose the response iterator to WSGI.

        Returns:
            _RequestContextIterator: This iterator.
        """
        return self

    def _call(self, callback):
        """Run an iterator operation under its request state, then restore the caller state.

        Args:
            callback (Callable): Zero-argument iterator or cleanup operation.

        Returns:
            Any: Value returned by the callback.

        Raises:
            RuntimeError: Redacted replacement for callback errors under a private request.
            Exception: Original callback error when redaction is inactive; StopIteration always
                propagates.
        """
        previous = _capture_request_context()
        _restore_request_context(self._snapshot)
        try:
            return callback()
        except StopIteration:
            raise
        except Exception:
            if is_encryption_active():
                # WSGI servers can print escaping exceptions outside our loggers.
                raise RuntimeError("Streaming request failed. [Redacted]") from None
            raise
        finally:
            _restore_request_context(previous)

    def __next__(self):
        """Advance the body under the captured request context.

        Returns:
            bytes: Next encoded response chunk.

        Raises:
            StopIteration: When the body is exhausted.
        """
        return self._call(lambda: next(self._body))

    def close(self):
        """Close the body and run response cleanup at most once under the request context."""
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._body, 'close', None)
            if callable(close):
                self._call(close)
        finally:
            if self._on_close is not None:
                self._call(self._on_close)


def _build_streaming_response(body, mimetype: str, on_close: Callable = None) -> Response:
    """Wraps an iterable of encoded chunks in a streaming Response with shared headers.

    Args:
        body: The chunk iterable to stream to the client.
        mimetype (str): Content type of the response.
        on_close (Callable): Optional response-owned cleanup, including before iteration.

    Returns:
        Response: The configured Flask streaming response.
    """
    response = Response(
        _RequestContextIterator(body, _capture_request_context(), on_close),
        mimetype=mimetype,
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Connection headers belong to the WSGI server; Waitress rejects them from applications.
    return response


def stream_with_eventlet_optimized(config: StreamingApiConfig, backend: Callable, request_id: str,
                                   messages: List[Dict], stream: bool, api_key: str = None,
                                   tools: list = None, tool_choice=None) -> Response:
    """
    Optimized streaming implementation for Eventlet with disconnect detection during prefill.

    Uses a queue-based approach where a background greenlet reads from the backend
    and the main generator uses timeouts to detect when heartbeats are needed.

    Args:
        config (StreamingApiConfig): The API-specific streaming values.
        backend (Callable): The gateway callable that yields response chunks
                            (handle_user_prompt).
        request_id (str): The unique identifier for this request.
        messages (List[Dict]): The conversation history in the internal message format.
        stream (bool): Whether streaming mode is active.
        api_key (str, optional): The API key for encryption context scoping.
        tools (list, optional): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Response: A Flask streaming Response using the API's streaming content type.
    """
    logger.info(f"{config.api_label} starting Eventlet optimized streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service
    from Middleware.services.idempotency_service import idempotency_service

    request_context = _capture_request_context()

    event_queue = EventletQueue()
    stop_signal = eventlet.event.Event()
    reader_greenlet = None
    reader_started = False
    reader_finished = False
    response_complete = False
    teardown_requested = False

    def release_request():
        """Release cancellation and idempotency registrations after backend completion."""
        if request_id and cancellation_service.is_cancelled(request_id):
            cancellation_service.acknowledge_cancellation(request_id)
        idempotency_service.release(request_id)

    def abort_reader():
        """Cancel an unfinished backend while allowing post-response nodes to finish normally."""
        nonlocal teardown_requested
        if teardown_requested or response_complete or reader_finished:
            return
        teardown_requested = True
        if request_id and not cancellation_service.is_cancelled(request_id):
            cancellation_service.request_cancellation(request_id)
        if not stop_signal.ready():
            stop_signal.send(True)
        if not reader_started:
            # Killing a scheduled greenlet need not enter its finally block.
            release_request()
        if reader_greenlet is not None:
            eventlet.spawn(reader_greenlet.kill)

    def backend_reader():
        """Background greenlet that reads from the backend and queues chunks."""
        nonlocal reader_started, reader_finished
        reader_started = True
        source = None
        previous_context = _capture_request_context()
        _restore_request_context(request_context)
        try:
            if teardown_requested:
                return
            source = iter(backend(request_id, messages, stream, api_key=api_key,
                                  tools=tools, tool_choice=tool_choice))
            for chunk in source:
                if stop_signal.ready():
                    break
                event_queue.put(("data", chunk))
        except EarlyTerminationException:
            # Node-boundary cancellation clears its flag before raising this exception.
            logger.info(f"Backend workflow terminated early for request_id {request_id} (cancellation).")
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                logger.error(f"Error in backend reader greenlet for request_id {request_id}: {e}", exc_info=True)
                event_queue.put(("error", e))
        except GreenletExit:
            # Disconnect cleanup kills this greenlet as part of normal teardown.
            logger.info(f"Backend reader greenlet for request_id {request_id} was killed during stream teardown.")
            raise
        except (KeyboardInterrupt, SystemExit):
            # Process-level signals (Ctrl-C / interpreter shutdown) must propagate,
            # not be swallowed as a reader error.
            raise
        except BaseException as e:
            logger.error(f"BaseException in backend_reader for request_id {request_id}: "
                         f"{type(e).__name__}: {e}", exc_info=True)
        finally:
            try:
                close_source = getattr(source, 'close', None)
                if callable(close_source):
                    close_source()
            except Exception:
                # Cleanup runs outside the response iterator's WSGI error boundary.
                logger.exception("Backend stream cleanup failed for request_id %s", request_id)
            finally:
                try:
                    reader_finished = True
                    if not stop_signal.ready():
                        stop_signal.send(True)
                    release_request()
                finally:
                    _restore_request_context(previous_context)

    reader_greenlet = eventlet.spawn(backend_reader)

    def streaming_generator():
        """Deliver queued backend output and idle heartbeats to WSGI.

        Yields:
            bytes: Encoded API events or heartbeat chunks.
        """
        nonlocal response_complete
        # Distinguish failures before output from disconnects during a response.
        first_output_sent = False
        backend_produced_data = False
        try:
            while not stop_signal.ready() or not event_queue.empty():
                try:
                    msg_type, data = event_queue.get(timeout=HEARTBEAT_INTERVAL)

                    if msg_type == "error":
                        raise data
                    elif msg_type == "data":
                        backend_produced_data = True
                        if isinstance(data, str):
                            encoded = data.encode('utf-8')
                        else:
                            encoded = data
                        terminal_chunk = config.chunk_signals_done(encoded)
                        if terminal_chunk:
                            response_complete = True
                        yield encoded
                        first_output_sent = True

                        # The reader remains active so post-returnToUser nodes can finish.
                        if terminal_chunk:
                            return

                        # Yield to Eventlet so the socket writer can flush this chunk.
                        eventlet.sleep(0)

                except EventletQueueEmpty:
                    if not stop_signal.ready():
                        yield config.heartbeat_message
                        first_output_sent = True
                        eventlet.sleep(0)

            response_complete = True

        except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError) as e:
            if not first_output_sent:
                logger.warning(
                    f"{config.api_label} request {request_id} closed before any response bytes were "
                    f"sent (pre-response client disconnect). Phase: "
                    f"{'awaiting-backend' if not backend_produced_data else 'backend-data-buffered'}. "
                    f"Error: {type(e).__name__}.")
            else:
                logger.info(f"Client disconnected from {config.api_label} streaming request {request_id}. "
                            f"Error: {type(e).__name__}.")
            raise
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                if not first_output_sent:
                    logger.warning(
                        f"{config.api_label} request {request_id} failed before any response bytes were "
                        f"sent (pre-response server error); the client will see a connection reset with "
                        f"no HTTP response. Phase: "
                        f"{'awaiting-backend' if not backend_produced_data else 'backend-data-buffered'}. "
                        f"Cause: {type(e).__name__}: {e}")
                logger.error(f"Unexpected error in {config.api_label} streaming generator: {e}", exc_info=True)
            raise
        finally:
            abort_reader()

    return _build_streaming_response(streaming_generator(), config.mimetype, abort_reader)


def stream_response_fallback(config: StreamingApiConfig, backend: Callable, request_id: str,
                             messages: List[Dict], stream: bool, api_key: str = None,
                             tools: list = None, tool_choice=None) -> Response:
    """
    Fallback streaming implementation for non-Eventlet environments.

    Used when Eventlet is not installed or monkey-patching is not active (e.g., when
    running under Waitress, Gunicorn, or the Flask development server). Disconnect
    detection during the LLM prefill phase is unreliable in this mode because the
    generator is driven synchronously by the WSGI server without a heartbeat mechanism.

    Args:
        config (StreamingApiConfig): The API-specific streaming values.
        backend (Callable): The gateway callable that yields response chunks
                            (handle_user_prompt).
        request_id (str): The unique identifier for this request.
        messages (List[Dict]): The conversation history in the internal message format.
        stream (bool): Whether streaming mode is active.
        api_key (str, optional): The API key for encryption context scoping.
        tools (list, optional): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Response: A Flask streaming Response using the API's streaming content type.
    """
    logger.info(f"{config.api_label} starting fallback (synchronous) streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service
    from Middleware.services.idempotency_service import idempotency_service

    request_context = _capture_request_context()

    def release_request():
        """Release cancellation and idempotency registrations after synchronous streaming."""
        if request_id and cancellation_service.is_cancelled(request_id):
            cancellation_service.acknowledge_cancellation(request_id)
        idempotency_service.release(request_id)

    def streaming_generator():
        """Stream backend events synchronously and retain cleanup ownership.

        Yields:
            bytes: Encoded API events through the stream terminator.
        """
        _restore_request_context(request_context)
        logger.debug(f"{config.api_label} Fallback Generator starting for request_id: {request_id}")
        # Distinguish failures before output from disconnects during a response.
        first_output_sent = False
        source = None
        try:
            done_sent = False
            source = iter(backend(request_id, messages, stream, api_key=api_key,
                                  tools=tools, tool_choice=tool_choice))
            for chunk in source:
                if isinstance(chunk, str):
                    encoded = chunk.encode('utf-8')
                else:
                    encoded = chunk
                if done_sent:
                    # After the stream terminator, consume remaining chunks without
                    # yielding so post-returnToUser workflow nodes can finish.
                    continue
                yield encoded
                first_output_sent = True
                if config.chunk_signals_done(encoded):
                    done_sent = True
        except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError) as e:
            if request_id:
                if not cancellation_service.is_cancelled(request_id):
                    if not first_output_sent:
                        logger.warning(
                            f"{config.api_label} (Fallback) request {request_id} closed before any response "
                            f"bytes were sent (pre-response client disconnect). Error: {type(e).__name__}. "
                            f"Cancellation might be delayed during prefill.")
                    else:
                        logger.warning(
                            f"Client disconnected from {config.api_label} (Fallback) streaming request "
                            f"{request_id}. Error: {type(e).__name__}. Cancellation might be delayed during prefill.")
                    cancellation_service.request_cancellation(request_id)
            raise
        except EarlyTerminationException:
            # Node-boundary cancellation clears its flag before raising this exception.
            logger.info(f"Backend workflow terminated early for request_id {request_id} (cancellation).")
            return
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(
                    f"Backend streaming stopped due to cancellation for request_id {request_id}. Exiting generator.")
                return
            if done_sent:
                # Post-response node failures must not disrupt an already completed stream.
                logger.error(
                    f"Post-stream node failed after the stream terminator in {config.api_label} fallback "
                    f"streaming for request_id {request_id}: {e}", exc_info=True)
                return
            if not first_output_sent:
                logger.warning(
                    f"{config.api_label} (Fallback) request {request_id} failed before any response bytes "
                    f"were sent (pre-response server error); the client will see a connection reset with no "
                    f"HTTP response. Cause: {type(e).__name__}: {e}")
            logger.error(f"Unexpected error in {config.api_label} streaming response: {e}", exc_info=True)
            raise
        finally:
            try:
                close_source = getattr(source, 'close', None)
                if callable(close_source):
                    close_source()
            finally:
                release_request()

    return _build_streaming_response(
        stream_with_context(streaming_generator()), config.mimetype, release_request)


def handle_streaming_request(config: StreamingApiConfig, backend: Callable, request_id: str,
                             messages: List[Dict], stream: bool, api_key: str = None,
                             tools: list = None, tool_choice=None) -> Response:
    """
    Selects and invokes the appropriate streaming implementation.

    Checks whether Eventlet is both installed and actively monkey-patching the
    socket layer. If so, uses the optimized queue-based Eventlet implementation
    which supports heartbeats and disconnect detection during LLM prefill. Otherwise,
    falls back to synchronous streaming.

    Args:
        config (StreamingApiConfig): The API-specific streaming values.
        backend (Callable): The gateway callable that yields response chunks
                            (handle_user_prompt).
        request_id (str): The unique identifier for this request.
        messages (List[Dict]): The conversation history in the internal message format.
        stream (bool): Whether streaming mode is active.
        api_key (str, optional): The API key for encryption context scoping.
        tools (list, optional): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Response: A Flask streaming Response using the API's streaming content type.
    """
    is_eventlet_active = EVENTLET_AVAILABLE and eventlet.patcher.is_monkey_patched('socket')

    if is_eventlet_active:
        return stream_with_eventlet_optimized(config, backend, request_id, messages, stream,
                                              api_key=api_key, tools=tools, tool_choice=tool_choice)
    else:
        if not EVENTLET_AVAILABLE:
            logger.warning(
                "Eventlet not installed. Falling back to synchronous streaming. Disconnect detection during prefill may be unreliable.")
        else:
            logger.debug(
                "Eventlet installed but monkey patching is not active (not running via run_eventlet.py). Falling back to synchronous streaming.")
        return stream_response_fallback(config, backend, request_id, messages, stream,
                                        api_key=api_key, tools=tools, tool_choice=tool_choice)
