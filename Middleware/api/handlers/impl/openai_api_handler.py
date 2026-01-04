# Middleware/api/handlers/impl/openai_api_handler.py

import json
import logging
import uuid

# Dynamic eventlet imports
try:
    import eventlet
    from eventlet.queue import Queue as EventletQueue, Empty as EventletQueueEmpty

    EVENTLET_AVAILABLE = True
except ImportError:
    EVENTLET_AVAILABLE = False
    import queue

    Queue = queue.Queue
    EventletQueueEmpty = queue.Empty

from typing import Any, Dict, Union, List

from flask import jsonify, request, Response, g, stream_with_context
from flask.views import MethodView
from werkzeug.exceptions import ClientDisconnected

from Middleware.api import api_helpers
from Middleware.api.app import app
from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
from Middleware.api.workflow_gateway import handle_user_prompt, _sanitize_log_data, handle_openwebui_tool_check
from Middleware.common import instance_global_variables
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from Middleware.utilities.prompt_extraction_utils import parse_conversation

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()

# Configuration for the heartbeat mechanism
# 1 second was chosen because Wilmer won't react to an abort from the front-end until the next interval.
# In an attempt to save the user some tokens, we want that reaction as fast as possible so we dont risk
# kicking off another workflow node and processing another prompt. No guarantee this will work, but we
# want to try
HEARTBEAT_INTERVAL = 1  # seconds
HEARTBEAT_MESSAGE = b':\n\n'


def _stream_with_eventlet_optimized(request_id: str, messages: List[Dict], stream: bool) -> Response:
    """
    Optimized streaming implementation for Eventlet with disconnect detection during prefill.

    Uses a queue-based approach where a background greenlet reads from handle_user_prompt()
    and the main generator uses timeouts to detect when heartbeats are needed.
    """
    logger.info(f"OpenAI starting Eventlet optimized streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service

    # Capture workflow override before spawning greenlet, since the finally block
    # in the calling function will clear it before the greenlet runs
    captured_workflow_override = api_helpers.get_active_workflow_override()

    event_queue = EventletQueue()
    stop_signal = eventlet.event.Event()
    reader_greenlet = None

    def backend_reader():
        """Background greenlet that reads from handle_user_prompt and queues chunks."""
        # Restore the workflow override that was captured before spawning
        instance_global_variables.WORKFLOW_OVERRIDE = captured_workflow_override
        try:
            for chunk in handle_user_prompt(request_id, messages, stream):
                if stop_signal.ready():
                    break
                event_queue.put(("data", chunk))
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                logger.error(f"Error in backend reader greenlet for request_id {request_id}: {e}", exc_info=True)
                event_queue.put(("error", e))
        finally:
            if not stop_signal.ready():
                stop_signal.send(True)

    reader_greenlet = eventlet.spawn(backend_reader)

    def streaming_generator():
        """Main generator consumed by Eventlet WSGI."""
        try:
            while not stop_signal.ready() or not event_queue.empty():
                try:
                    msg_type, data = event_queue.get(timeout=HEARTBEAT_INTERVAL)

                    if msg_type == "error":
                        raise data
                    elif msg_type == "data":
                        if isinstance(data, str):
                            yield data.encode('utf-8')
                        else:
                            yield data

                        eventlet.sleep(0)

                except EventletQueueEmpty:
                    if not stop_signal.ready():
                        yield HEARTBEAT_MESSAGE
                        eventlet.sleep(0)

        except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError) as e:
            logger.info(f"Client disconnected from OpenAI streaming request {request_id}. Error: {type(e).__name__}.")
            if request_id and not cancellation_service.is_cancelled(request_id):
                cancellation_service.request_cancellation(request_id)
            raise
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                logger.error(f"Unexpected error in OpenAI streaming generator: {e}", exc_info=True)
            raise
        finally:
            if not stop_signal.ready():
                stop_signal.send(True)
            if reader_greenlet:
                reader_greenlet.kill()

    response = Response(
        streaming_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Remove hop-by-hop headers that violate WSGI/PEP 3333
    response.headers.pop('Connection', None)
    return response


def _stream_response_fallback(request_id: str, messages: List[Dict], stream: bool) -> Response:
    """Fallback streaming for non-Eventlet environments."""
    logger.info(f"OpenAI starting fallback (synchronous) streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service

    # Capture workflow override before creating generator, since the finally block
    # in the calling function will clear it before the generator runs
    captured_workflow_override = api_helpers.get_active_workflow_override()

    def streaming_generator():
        # Restore the workflow override that was captured before creating the generator
        instance_global_variables.WORKFLOW_OVERRIDE = captured_workflow_override
        logger.debug(f"OpenAI Fallback Generator starting for request_id: {request_id}")
        try:
            for chunk in handle_user_prompt(request_id, messages, stream):
                if isinstance(chunk, str):
                    yield chunk.encode('utf-8')
                else:
                    yield chunk
        except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError) as e:
            if request_id:
                if not cancellation_service.is_cancelled(request_id):
                    logger.warning(
                        f"Client disconnected from OpenAI (Fallback) streaming request {request_id}. Error: {type(e).__name__}. Cancellation might be delayed during prefill.")
                    cancellation_service.request_cancellation(request_id)
            raise
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(
                    f"Backend streaming stopped due to cancellation for request_id {request_id}. Exiting generator.")
                return
            logger.error(f"Unexpected error in OpenAI streaming response: {e}", exc_info=True)
            raise

    response = Response(
        stream_with_context(streaming_generator()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Remove hop-by-hop headers that violate WSGI/PEP 3333
    response.headers.pop('Connection', None)
    return response


def _handle_streaming_request(request_id: str, messages: List[Dict], stream: bool) -> Response:
    """Main entry point for streaming, dynamically choosing the implementation."""
    is_eventlet_active = EVENTLET_AVAILABLE and eventlet.patcher.is_monkey_patched('socket')

    if is_eventlet_active:
        return _stream_with_eventlet_optimized(request_id, messages, stream)
    else:
        if not EVENTLET_AVAILABLE:
            logger.warning(
                "Eventlet not installed. Falling back to synchronous streaming. Disconnect detection during prefill may be unreliable.")
        else:
            logger.debug(
                "Eventlet installed but monkey patching is not active (not running via run_eventlet.py). Falling back to synchronous streaming.")
        return _stream_response_fallback(request_id, messages, stream)


class ModelsAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests to provide a list of available models.

        Returns:
            Response: A Flask JSON response containing the model list.
        """
        response = response_builder.build_openai_models_response()
        return jsonify(response)


class CompletionsAPI(MethodView):
    @staticmethod
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for OpenAI-compatible text completions.

        This method processes requests to the legacy completions endpoints. It
        extracts the prompt, determines if the request is for streaming, and
        dispatches it to the workflow engine.

        Returns:
            Union[Response, Dict[str, Any]]: A Flask response, which is either a
                                             streaming response or a single JSON
                                             object.
        """
        # Generate Request ID immediately and store it in the context
        request_id = str(uuid.uuid4())
        g.current_request_id = request_id

        instance_global_variables.API_TYPE = "openaicompletion"
        logger.info(f"CompletionsAPI request received (ID: {request_id})")
        data: Dict[str, Any] = request.json
        logger.debug(f"CompletionsAPI request received (ID: {request_id}): {json.dumps(_sanitize_log_data(data))}")

        # Set workflow override from model field if applicable
        model_name = data.get("model")
        api_helpers.set_workflow_override(model_name)

        try:
            prompt: str = data.get("prompt", "")
            stream: bool = data.get("stream", True)
            messages = parse_conversation(prompt)

            if stream:
                return _handle_streaming_request(request_id, messages, stream)
            else:
                return_response: str = handle_user_prompt(request_id, messages, False)
                response = response_builder.build_openai_completion_response(return_response)
                return jsonify(response)
        finally:
            api_helpers.clear_workflow_override()


class ChatCompletionsAPI(MethodView):
    @staticmethod
    @handle_openwebui_tool_check('openaichatcompletion')
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for OpenAI-compatible chat completions.

        This method processes requests to the `/chat/completions` endpoint. It
        transforms the incoming `messages` payload into the internal standardized
        format and dispatches it to the workflow engine, supporting both
        streaming and non-streaming modes.

        Returns:
            Union[Response, Dict[str, Any]]: A Flask response containing the
                                             chat completion result, which is
                                             either a streaming response or a
                                             JSON object.

        Raises:
            ValueError: If the request payload lacks a 'messages' field, or if
                        any message is missing 'role' or 'content'.
        """
        # Generate Request ID immediately and store it in the context
        request_id = str(uuid.uuid4())
        g.current_request_id = request_id

        instance_global_variables.API_TYPE = "openaichatcompletion"
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        request_data: Dict[str, Any] = request.get_json()
        logger.info(
            f"ChatCompletionsAPI request received (ID: {request_id}): {json.dumps(_sanitize_log_data(request_data))}")
        logger.info(f"ChatCompletionsAPI.post() called - stream={request_data.get('stream', False)}")

        # Set workflow override from model field if applicable
        model_name = request_data.get("model")
        api_helpers.set_workflow_override(model_name)

        try:
            stream: bool = request_data.get("stream", False)
            if 'messages' not in request_data:
                raise ValueError("The 'messages' field is required.")
            messages: List[Dict[str, str]] = request_data["messages"]
            for message in messages:
                if "role" not in message or "content" not in message:
                    raise ValueError("Each message must have 'role' and 'content' fields.")

            transformed_messages: List[Dict[str, str]] = []
            for message in messages:
                role = message["role"]
                content = message["content"]
                if add_user_assistant:
                    if role == "user":
                        content = "User: " + content
                    elif role == "assistant":
                        content = "Assistant: " + content
                transformed_messages.append({"role": role, "content": content})

            if add_missing_assistant:
                if add_user_assistant and messages and messages[-1]["role"] != "assistant":
                    transformed_messages.append({"role": "assistant", "content": "Assistant:"})
                elif messages and messages[-1]["role"] != "assistant":
                    transformed_messages.append({"role": "assistant", "content": ""})

            if stream:
                logger.info(f"ChatCompletionsAPI starting streaming response for request_id: {request_id}")
                return _handle_streaming_request(request_id, transformed_messages, stream)
            else:
                return_response = handle_user_prompt(request_id, transformed_messages, stream=False)
                response = response_builder.build_openai_chat_completion_response(return_response)
                return jsonify(response)
        finally:
            api_helpers.clear_workflow_override()


class OpenAIApiHandler(BaseApiHandler):
    """
    Registers all OpenAI-compatible API routes with the Flask application.

    This handler is automatically discovered by the `ApiServer` and is
    responsible for setting up all endpoints that conform to the OpenAI
    API specification, such as `/v1/models` and `/chat/completions`.
    """

    def register_routes(self, app_instance: app) -> None:
        """
        Registers the OpenAI-compatible API routes with the Flask application.

        Args:
            app_instance (app): The Flask application instance to which the routes
                                will be added.
        """
        app_instance.add_url_rule('/v1/models', view_func=ModelsAPI.as_view('v1_models_api'))
        app_instance.add_url_rule('/v1/completions', view_func=CompletionsAPI.as_view('v1_completions_api'))
        app_instance.add_url_rule('/chat/completions', view_func=ChatCompletionsAPI.as_view('chat_completions_api'))
        # Add non-versioned aliases for broader compatibility
        app_instance.add_url_rule('/models', view_func=ModelsAPI.as_view('models_api'))
        app_instance.add_url_rule('/completions', view_func=CompletionsAPI.as_view('completions_api'))
