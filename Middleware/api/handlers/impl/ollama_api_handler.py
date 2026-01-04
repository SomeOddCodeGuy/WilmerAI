# Middleware/api/handlers/impl/ollama_api_handler.py

import json
import logging
import uuid

# Dynamic eventlet imports
try:
    import eventlet
    # Import Queue and Empty specifically from eventlet.queue
    from eventlet.queue import Queue as EventletQueue, Empty as EventletQueueEmpty

    EVENTLET_AVAILABLE = True
except ImportError:
    EVENTLET_AVAILABLE = False
    # Fallback for non-Eventlet environments (like Waitress or Flask dev server)
    import queue

    Queue = queue.Queue
    # Use standard queue.Empty for fallback type compatibility, assign it to the Eventlet name for unified handling
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
# Heartbeat must be valid NDJSON to avoid breaking frontend parsers
# Use an empty content message that frontends will safely ignore
HEARTBEAT_MESSAGE = b'{"message":{"role":"assistant","content":""},"done":false}\n'


def _stream_with_eventlet_optimized(request_id: str, messages: List[Dict], stream: bool) -> Response:
    """
    Optimized streaming implementation for Eventlet with disconnect detection during prefill.

    Uses a queue-based approach where a background greenlet reads from handle_user_prompt()
    and the main generator uses timeouts to detect when heartbeats are needed.
    """
    logger.info(f"Ollama starting Eventlet optimized streaming for request_id: {request_id}")
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

    # Start the backend reader greenlet
    reader_greenlet = eventlet.spawn(backend_reader)

    def streaming_generator():
        """Main generator consumed by Eventlet WSGI."""
        try:
            while not stop_signal.ready() or not event_queue.empty():
                try:
                    # Wait for data with timeout (enables heartbeat during prefill)
                    msg_type, data = event_queue.get(timeout=HEARTBEAT_INTERVAL)

                    if msg_type == "error":
                        raise data
                    elif msg_type == "data":
                        # Ensure bytes for WSGI compliance
                        if isinstance(data, str):
                            yield data.encode('utf-8')
                        else:
                            yield data

                        # Force immediate socket write
                        eventlet.sleep(0)

                except EventletQueueEmpty:
                    # Timeout - no data from backend, send heartbeat
                    if not stop_signal.ready():
                        yield HEARTBEAT_MESSAGE
                        eventlet.sleep(0)

        except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError) as e:
            # Client disconnected - trigger cancellation
            logger.info(f"Client disconnected from Ollama streaming request {request_id}. Error: {type(e).__name__}.")
            if request_id and not cancellation_service.is_cancelled(request_id):
                cancellation_service.request_cancellation(request_id)
            raise
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(f"Backend streaming stopped due to cancellation for request_id {request_id}.")
            else:
                logger.error(f"Unexpected error in Ollama streaming generator: {e}", exc_info=True)
            raise
        finally:
            # Stop the backend greenlet
            if not stop_signal.ready():
                stop_signal.send(True)
            if reader_greenlet:
                reader_greenlet.kill()

    response = Response(
        streaming_generator(),
        mimetype='application/x-ndjson',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Remove hop-by-hop headers that violate WSGI/PEP 3333
    response.headers.pop('Connection', None)
    return response


# Helper function for simplified streaming (Fallback for non-Eventlet environments)
def _stream_response_fallback(request_id: str, messages: List[Dict], stream: bool) -> Response:
    # (Implementation remains the same, ensuring bytes are yielded and logging is present)
    logger.info(f"Ollama starting fallback (synchronous) streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service  # Import inside function

    # Capture workflow override before creating generator, since the finally block
    # in the calling function will clear it before the generator runs
    captured_workflow_override = api_helpers.get_active_workflow_override()

    def streaming_generator():
        # Restore the workflow override that was captured before creating the generator
        instance_global_variables.WORKFLOW_OVERRIDE = captured_workflow_override
        logger.debug(f"Ollama Fallback Generator starting for request_id: {request_id}")
        try:
            for chunk in handle_user_prompt(request_id, messages, stream):
                # Explicitly encode to bytes for WSGI compliance
                if isinstance(chunk, str):
                    yield chunk.encode('utf-8')
                else:
                    yield chunk
        except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError) as e:
            if request_id:
                if not cancellation_service.is_cancelled(request_id):
                    logger.warning(
                        f"Client disconnected from Ollama (Fallback) streaming request {request_id}. Error: {type(e).__name__}. Cancellation might be delayed during prefill.")
                    cancellation_service.request_cancellation(request_id)
            raise
        except Exception as e:
            if request_id and cancellation_service.is_cancelled(request_id):
                logger.info(
                    f"Backend streaming stopped due to cancellation for request_id {request_id}. Exiting generator.")
                return
            logger.error(f"Unexpected error in Ollama streaming response: {e}", exc_info=True)
            raise

    response = Response(
        stream_with_context(streaming_generator()),
        mimetype='application/x-ndjson',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Remove hop-by-hop headers that violate WSGI/PEP 3333
    response.headers.pop('Connection', None)
    return response


# Main entry point for streaming, dynamically choosing the implementation
def _handle_streaming_request(request_id: str, messages: List[Dict], stream: bool) -> Response:
    # Check if Eventlet is available AND if monkey-patching is active
    # We must check eventlet.patcher dynamically as it's only available if EVENTLET_AVAILABLE is True
    is_eventlet_active = EVENTLET_AVAILABLE and eventlet.patcher.is_monkey_patched('socket')

    if is_eventlet_active:
        # Call the optimized version
        return _stream_with_eventlet_optimized(request_id, messages, stream)
    else:
        # Provide warnings if Eventlet is expected but not active
        if not EVENTLET_AVAILABLE:
            logger.warning(
                "Eventlet not installed. Falling back to synchronous streaming. Disconnect detection during prefill may be unreliable.")
        else:
            # This case handles running under Gunicorn/Waitress/Flask Dev Server
            logger.debug(
                "Eventlet installed but monkey patching is not active (not running via run_eventlet.py). Falling back to synchronous streaming.")
        return _stream_response_fallback(request_id, messages, stream)


class GenerateAPI(MethodView):
    @staticmethod
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for the /api/generate endpoint.

        This method processes the request, transforms the prompt and images into the
        internal message format, and calls the workflow engine. It returns a response
        that mimics the Ollama generate API format.

        Returns:
            Union[Response, Dict[str, Any]]: A Flask Response object for a streaming
                                            response, or a dictionary for a non-streaming
                                            response.
        """
        # Generate Request ID immediately and store it in the context
        request_id = str(uuid.uuid4())
        g.current_request_id = request_id

        instance_global_variables.API_TYPE = "ollamagenerate"
        logger.debug(f"GenerateAPI request received (ID: {request_id})")

        # Use force=True and silent=True for robustness
        data: Dict[str, Any] = request.get_json(force=True, silent=True)
        if data is None:
            logger.error("Failed to parse JSON in GenerateAPI")
            return jsonify({"error": "Invalid JSON data"}), 400

        logger.debug(f"GenerateAPI request data (ID: {request_id}): {json.dumps(_sanitize_log_data(data))}")

        model: str = data.get("model")
        if not model:
            return jsonify({"error": "The 'model' field is required."}), 400

        # Set workflow override from model field if applicable
        api_helpers.set_workflow_override(model)

        try:
            prompt: str = data.get("prompt", "")
            system: str = data.get("system", "")
            stream: bool = data.get("stream", True)

            # Combine system and user prompt for processing
            full_prompt = prompt
            if system:
                # Keep behavior consistent with previous implementation
                full_prompt = system + prompt

            # Attempt to parse tagged conversation format
            messages = parse_conversation(full_prompt)

            # Ensure messages is initialized even if empty
            if not messages and full_prompt:
                messages = [{"role": "user", "content": full_prompt}]
            elif not messages:
                messages = []

            images = data.get("images", [])
            if images:
                for image_base64 in images:
                    messages.append({"role": "images", "content": image_base64})

            if stream:
                # Use the dynamic streaming handler selection
                return _handle_streaming_request(request_id, messages, stream)
            else:
                # Pass request_id. Use the model name from api_helpers to get username:workflow format
                return_response: str = handle_user_prompt(request_id, messages, stream=False)
                response_model = api_helpers.get_model_name()
                response = response_builder.build_ollama_generate_response(return_response, model=response_model,
                                                                           request_id=request_id)
                return jsonify(response)
        finally:
            api_helpers.clear_workflow_override()


class ApiChatAPI(MethodView):
    @staticmethod
    @handle_openwebui_tool_check('ollamaapichat')
    def post() -> Response:
        """
        Handles POST requests for the /api/chat endpoint.

        This method extracts the conversation history from the request, transforms
        it into the internal message format, and calls the workflow engine. It
        returns a response that matches the Ollama /api/chat format.

        Returns:
            Response: A Flask Response object for either a streaming or a
                      non-streaming JSON response.
        """
        # Generate Request ID immediately and store it in the context
        request_id = str(uuid.uuid4())
        g.current_request_id = request_id

        instance_global_variables.API_TYPE = "ollamaapichat"
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        try:
            # Use force=True to ensure content-type is ignored if necessary
            request_data: Dict[str, Any] = request.get_json(force=True)
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return jsonify({"error": "Invalid JSON data"}), 400

        logger.info(f"ApiChatAPI request received (ID: {request_id}): {json.dumps(_sanitize_log_data(request_data))}")

        if 'model' not in request_data or 'messages' not in request_data:
            return jsonify({"error": "Both 'model' and 'messages' fields are required."}), 400

        # Set workflow override from model field if applicable
        model_from_request = request_data.get("model")
        api_helpers.set_workflow_override(model_from_request)

        try:
            messages: List[Dict[str, Any]] = request_data["messages"]
            transformed_messages: List[Dict[str, Any]] = []

            for message in messages:
                if "role" not in message or "content" not in message:
                    return jsonify({"error": "Each message must have 'role' and 'content' fields."}), 400

                role = message["role"]
                content = message["content"]

                if "images" in message and isinstance(message["images"], list):
                    for image_base64 in message["images"]:
                        transformed_messages.append({"role": "images", "content": image_base64})

                # Handle content modification safely
                content_str = str(content) if content is not None else ""

                if add_user_assistant:
                    if role == "user":
                        content_str = "User: " + content_str
                    elif role == "assistant":
                        content_str = "Assistant: " + content_str

                transformed_messages.append({"role": role, "content": content_str})

            if add_missing_assistant:
                if add_user_assistant and transformed_messages and transformed_messages[-1]["role"] != "assistant":
                    transformed_messages.append({"role": "assistant", "content": "Assistant:"})
                elif transformed_messages and transformed_messages[-1]["role"] != "assistant":
                    transformed_messages.append({"role": "assistant", "content": ""})

            stream = request_data.get("stream", True)
            if isinstance(stream, str):
                stream = stream.lower() == 'true'

            if stream:
                # Use the dynamic streaming handler selection
                return _handle_streaming_request(request_id, transformed_messages, stream)
            else:
                # Pass request_id. Use the model name from api_helpers to get username:workflow format
                response_data = handle_user_prompt(request_id, transformed_messages, stream)
                response_model = api_helpers.get_model_name()
                response = response_builder.build_ollama_chat_response(response_data, model_name=response_model,
                                                                       request_id=request_id)
                return jsonify(response)
        finally:
            api_helpers.clear_workflow_override()


class TagsAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests for the /api/tags endpoint.

        This method returns a list of available models, formatted to be compatible
        with the Ollama /api/tags endpoint.

        Returns:
            Response: A JSON response containing a list of available models.
        """
        response = response_builder.build_ollama_tags_response()
        return jsonify(response)


class VersionAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests for the /api/version endpoint.

        This method returns the application version, mimicking the Ollama
        /api/version endpoint.

        Returns:
            Response: A JSON response containing the version number.
        """
        return jsonify(response_builder.build_ollama_version_response())


class CancelChatAPI(MethodView):
    @staticmethod
    def delete() -> Response:
        """
        Handles DELETE requests for the /api/chat endpoint to cancel a request.

        This is a WilmerAI-specific extension to handle request cancellation
        in a multi-request environment. Clients should send a request_id in
        the JSON body to identify which request to cancel.

        Returns:
            Response: A JSON response confirming cancellation.
        """
        from Middleware.services.cancellation_service import cancellation_service

        try:
            request_data: Dict[str, Any] = request.get_json(force=True)
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return jsonify({"error": "Invalid JSON data"}), 400

        request_id = request_data.get("request_id")
        if not request_id:
            return jsonify({"error": "The 'request_id' field is required."}), 400

        cancellation_service.request_cancellation(request_id)
        logger.info(f"Cancellation requested for request_id: {request_id}")

        return jsonify({"status": "cancelled", "request_id": request_id}), 200


class CancelGenerateAPI(MethodView):
    @staticmethod
    def delete() -> Response:
        """
        Handles DELETE requests for the /api/generate endpoint to cancel a request.

        This is a WilmerAI-specific extension to handle request cancellation
        in a multi-request environment. Clients should send a request_id in
        the JSON body to identify which request to cancel.

        Returns:
            Response: A JSON response confirming cancellation.
        """
        from Middleware.services.cancellation_service import cancellation_service

        try:
            request_data: Dict[str, Any] = request.get_json(force=True)
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return jsonify({"error": "Invalid JSON data"}), 400

        request_id = request_data.get("request_id")
        if not request_id:
            return jsonify({"error": "The 'request_id' field is required."}), 400

        cancellation_service.request_cancellation(request_id)
        logger.info(f"Cancellation requested for request_id: {request_id}")

        return jsonify({"status": "cancelled", "request_id": request_id}), 200


class OllamaApiHandler(BaseApiHandler):
    """
    Registers all API endpoints that conform to the Ollama API specification.
    """

    def register_routes(self, app_instance: app) -> None:
        """
        Registers the Ollama API-compatible routes with the Flask app.

        Args:
            app_instance (app): The Flask application instance.
        """
        app_instance.add_url_rule('/api/generate', view_func=GenerateAPI.as_view('api_generate'), methods=['POST'])
        app_instance.add_url_rule('/api/generate', view_func=CancelGenerateAPI.as_view('api_generate_cancel'),
                                  methods=['DELETE'])
        app_instance.add_url_rule('/api/chat', view_func=ApiChatAPI.as_view('api_chat'), methods=['POST'])
        app_instance.add_url_rule('/api/chat', view_func=CancelChatAPI.as_view('api_chat_cancel'), methods=['DELETE'])
        app_instance.add_url_rule('/api/tags', view_func=TagsAPI.as_view('api_tags'))
        app_instance.add_url_rule('/api/version', view_func=VersionAPI.as_view('api_version'))
