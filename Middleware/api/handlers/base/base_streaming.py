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

logger = logging.getLogger(__name__)

# Configuration for the heartbeat mechanism
# 1 second was chosen because Wilmer won't react to an abort from the front-end until the next interval.
# In an attempt to save the user some tokens, we want that reaction as fast as possible so we dont risk
# kicking off another workflow node and processing another prompt.
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


def _build_streaming_response(body, mimetype: str) -> Response:
    """Wraps an iterable of encoded chunks in a streaming Response with shared headers.

    Args:
        body: The chunk iterable to stream to the client.
        mimetype (str): Content type of the response.

    Returns:
        Response: The configured Flask streaming response.
    """
    response = Response(
        body,
        mimetype=mimetype,
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Force connection teardown after streaming completes. Some front-ends (notably Node.js-based apps)
    # can have their HTTP connection pool corrupted by keep-alive connections that outlive a streaming response.
    response.headers['Connection'] = 'close'
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

    def backend_reader():
        """Background greenlet that reads from the backend and queues chunks."""
        _restore_request_context(request_context)
        try:
            for chunk in backend(request_id, messages, stream, api_key=api_key,
                                 tools=tools, tool_choice=tool_choice):
                if stop_signal.ready():
                    break
                event_queue.put(("data", chunk))
        except EarlyTerminationException:
            # The workflow's node-boundary cancellation check raised this after
            # acknowledging the cancellation (which clears the is_cancelled flag),
            # so it must be caught before the generic handler below: routine
            # teardown, not an application failure.
            logger.info(f"Backend workflow terminated early for request_id {request_id} (cancellation).")
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                logger.error(f"Error in backend reader greenlet for request_id {request_id}: {e}", exc_info=True)
                event_queue.put(("error", e))
        except GreenletExit:
            # Routine teardown: the streaming generator kills this reader on client
            # disconnect/error, so a GreenletExit here is expected lifecycle, not an
            # application failure. Log quietly and let the greenlet exit.
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
            if not stop_signal.ready():
                stop_signal.send(True)
            # The backend is done (naturally, by error, or by kill): this is the
            # last point that always runs for the request, so an unacknowledged
            # cancellation is cleared here. Without this, cancelling during the
            # final responder node (the common case) left the id in the registry
            # forever, since no later node boundary ran to acknowledge it.
            if request_id and cancellation_service.is_cancelled(request_id):
                cancellation_service.acknowledge_cancellation(request_id)
            # Release the idempotency entry for this request now that its backend
            # work is fully done. Guarded release is a no-op when the request was
            # never registered (legacy client) or when its key was already rebound
            # to a newer duplicate that displaced this one.
            idempotency_service.release(request_id)

    reader_greenlet = eventlet.spawn(backend_reader)

    def streaming_generator():
        """Main generator consumed by Eventlet WSGI."""
        should_kill_reader = False
        # Instrumentation for the pre-response window: once any byte (data chunk
        # or heartbeat) is yielded, the WSGI server has written the HTTP response
        # headers, so a later teardown is a mid-stream disconnect. A teardown
        # while this is still False closed the connection before any response
        # line was sent, the failure class the client observes as a bare
        # "server disconnected without sending a response".
        first_output_sent = False
        backend_produced_data = False
        try:
            while not stop_signal.ready() or not event_queue.empty():
                try:
                    # Wait for data with timeout (enables heartbeat during prefill)
                    msg_type, data = event_queue.get(timeout=HEARTBEAT_INTERVAL)

                    if msg_type == "error":
                        raise data
                    elif msg_type == "data":
                        backend_produced_data = True
                        if isinstance(data, str):
                            encoded = data.encode('utf-8')
                        else:
                            encoded = data
                        yield encoded
                        first_output_sent = True

                        # If this chunk carries the stream terminator, return
                        # immediately. The backend_reader greenlet continues running
                        # so that post-returnToUser workflow nodes can finish.
                        if config.chunk_signals_done(encoded):
                            return

                        # Force immediate socket write
                        eventlet.sleep(0)

                except EventletQueueEmpty:
                    # Timeout: no data from backend, send heartbeat
                    if not stop_signal.ready():
                        yield config.heartbeat_message
                        first_output_sent = True
                        eventlet.sleep(0)

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
            if request_id and not cancellation_service.is_cancelled(request_id):
                cancellation_service.request_cancellation(request_id)
            should_kill_reader = True
            raise
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                if not first_output_sent:
                    # This is the ~5% pre-response failure surfacing: the backend
                    # errored before the first chunk, so the response headers were
                    # never written and the client sees a connection reset with no
                    # HTTP response. Logged distinctly (with request_id and cause)
                    # so the root cause can be found from the logs.
                    logger.warning(
                        f"{config.api_label} request {request_id} failed before any response bytes were "
                        f"sent (pre-response server error); the client will see a connection reset with "
                        f"no HTTP response. Phase: "
                        f"{'awaiting-backend' if not backend_produced_data else 'backend-data-buffered'}. "
                        f"Cause: {type(e).__name__}: {e}")
                logger.error(f"Unexpected error in {config.api_label} streaming generator: {e}", exc_info=True)
            should_kill_reader = True
            raise
        finally:
            # Only stop the backend reader when tearing it down due to a client
            # disconnect or error. On natural completion (we returned at the stream
            # terminator) the reader is left running so post-returnToUser nodes
            # finish; it sends stop_signal itself from its own finally. Signaling
            # here on natural completion would cut off a future post-return node
            # that yields.
            if should_kill_reader:
                if not stop_signal.ready():
                    stop_signal.send(True)
                if reader_greenlet:
                    eventlet.spawn(reader_greenlet.kill)

    return _build_streaming_response(streaming_generator(), config.mimetype)


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

    def streaming_generator():
        _restore_request_context(request_context)
        logger.debug(f"{config.api_label} Fallback Generator starting for request_id: {request_id}")
        # See the eventlet path: False until the first byte is yielded, at which
        # point the HTTP response headers have been written. A teardown before
        # then is a pre-response close (no HTTP response reaches the client).
        first_output_sent = False
        try:
            done_sent = False
            for chunk in backend(request_id, messages, stream, api_key=api_key,
                                 tools=tools, tool_choice=tool_choice):
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
            # The workflow's node-boundary cancellation check raised this after
            # acknowledging the cancellation (which clears the is_cancelled flag),
            # so it must be caught before the generic handler below: routine
            # teardown, not an application failure.
            logger.info(f"Backend workflow terminated early for request_id {request_id} (cancellation).")
            return
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(
                    f"Backend streaming stopped due to cancellation for request_id {request_id}. Exiting generator.")
                return
            if done_sent:
                # The client already received the stream terminator; a failure in a
                # post-returnToUser node must not propagate out of the WSGI generator
                # (it would corrupt connection teardown after a visually-complete
                # stream). Log and swallow, mirroring the eventlet reader's handling.
                logger.error(
                    f"Post-stream node failed after the stream terminator in {config.api_label} fallback "
                    f"streaming for request_id {request_id}: {e}", exc_info=True)
                return
            if not first_output_sent:
                # Pre-response server-side failure: the backend errored before the
                # first chunk, so no HTTP response was ever written and the client
                # sees a connection reset. Logged distinctly for root-cause hunting.
                logger.warning(
                    f"{config.api_label} (Fallback) request {request_id} failed before any response bytes "
                    f"were sent (pre-response server error); the client will see a connection reset with no "
                    f"HTTP response. Cause: {type(e).__name__}: {e}")
            logger.error(f"Unexpected error in {config.api_label} streaming response: {e}", exc_info=True)
            raise
        finally:
            # This generator's teardown is the last point that always runs for the
            # request in fallback mode, so an unacknowledged cancellation is
            # cleared here (see the eventlet reader's finally for the rationale).
            if request_id and cancellation_service.is_cancelled(request_id):
                cancellation_service.acknowledge_cancellation(request_id)
            # Release the idempotency entry now that the backend work is done.
            # Guarded release is a no-op for unregistered requests and for a
            # displaced original whose key was already rebound to a newer request.
            idempotency_service.release(request_id)

    return _build_streaming_response(stream_with_context(streaming_generator()), config.mimetype)


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
