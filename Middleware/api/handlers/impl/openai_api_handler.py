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
from Middleware.api.workflow_gateway import handle_user_prompt, _sanitize_log_data, check_openwebui_tool_request
from Middleware.common import instance_global_variables
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant, get_encrypt_using_api_key, get_redact_log_output
from Middleware.common.instance_global_variables import clear_api_type
from Middleware.utilities.prompt_extraction_utils import parse_conversation
from Middleware.utilities.sensitive_logging_utils import (
    set_encryption_context, clear_encryption_context, is_encryption_active, sensitive_log_lazy,
)

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()

# Configuration for the heartbeat mechanism
# 1 second was chosen because Wilmer won't react to an abort from the front-end until the next interval.
# In an attempt to save the user some tokens, we want that reaction as fast as possible so we dont risk
# kicking off another workflow node and processing another prompt.
HEARTBEAT_INTERVAL = 1  # seconds
HEARTBEAT_MESSAGE = b':\n\n'


def _stream_with_eventlet_optimized(request_id: str, messages: List[Dict], stream: bool, api_key: str = None,
                                    tools: list = None, tool_choice=None) -> Response:
    """
    Optimized streaming implementation for Eventlet with disconnect detection during prefill.

    Uses a queue-based approach where a background greenlet reads from handle_user_prompt()
    and the main generator uses timeouts to detect when heartbeats are needed.

    Args:
        request_id (str): The unique identifier for this request.
        messages (List[Dict]): The conversation history in the internal message format.
        stream (bool): Whether streaming mode is active.
        api_key (str, optional): The API key for encryption context scoping.
        tools (list, optional): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Response: A Flask streaming Response with SSE (text/event-stream) content type.
    """
    logger.info(f"OpenAI starting Eventlet optimized streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service

    # Capture request-scoped state before spawning greenlet, since the finally
    # block in the calling function will clear them before the greenlet runs
    captured_workflow_override = api_helpers.get_active_workflow_override()
    captured_api_type = instance_global_variables.get_api_type()
    captured_encryption_active = is_encryption_active()
    captured_request_user = instance_global_variables.get_request_user()

    event_queue = EventletQueue()
    stop_signal = eventlet.event.Event()
    reader_greenlet = None

    def backend_reader():
        """Background greenlet that reads from handle_user_prompt and queues chunks."""
        instance_global_variables.set_workflow_override(captured_workflow_override)
        instance_global_variables.set_api_type(captured_api_type)
        instance_global_variables.set_request_user(captured_request_user)
        set_encryption_context(captured_encryption_active)
        try:
            for chunk in handle_user_prompt(request_id, messages, stream, api_key=api_key,
                                            tools=tools, tool_choice=tool_choice):
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
                            encoded = data.encode('utf-8')
                        else:
                            encoded = data
                        yield encoded

                        # If this chunk is the SSE stream terminator, return immediately.
                        # Without this, post-stream workflow processing keeps the generator
                        # alive, holding the connection open unnecessarily.
                        if b'[DONE]' in encoded:
                            return

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
                # Kill the reader asynchronously to avoid blocking HTTP response
                # finalization. A blocking kill() here would delay the chunked TE
                # terminator and TCP close, since the generator's finally block runs
                # before the WSGI server can finalize the response.
                eventlet.spawn(reader_greenlet.kill)

    response = Response(
        streaming_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )
    # Force connection teardown after streaming completes. Some front-ends (notably Node.js-based apps)
    # can have their HTTP connection pool corrupted by keep-alive connections that outlive a streaming response.
    response.headers['Connection'] = 'close'
    return response


def _stream_response_fallback(request_id: str, messages: List[Dict], stream: bool, api_key: str = None,
                              tools: list = None, tool_choice=None) -> Response:
    """
    Fallback streaming implementation for non-Eventlet environments.

    Used when Eventlet is not installed or monkey-patching is not active (e.g., when
    running under Waitress, Gunicorn, or the Flask development server). Disconnect
    detection during the LLM prefill phase is unreliable in this mode because the
    generator is driven synchronously by the WSGI server without a heartbeat mechanism.

    Args:
        request_id (str): The unique identifier for this request.
        messages (List[Dict]): The conversation history in the internal message format.
        stream (bool): Whether streaming mode is active.
        api_key (str, optional): The API key for encryption context scoping.
        tools (list, optional): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Response: A Flask streaming Response with SSE (text/event-stream) content type.
    """
    logger.info(f"OpenAI starting fallback (synchronous) streaming for request_id: {request_id}")
    from Middleware.services.cancellation_service import cancellation_service

    # Capture request-scoped state before creating generator, since the finally
    # block in the calling function will clear them before the generator runs
    captured_workflow_override = api_helpers.get_active_workflow_override()
    captured_api_type = instance_global_variables.get_api_type()
    captured_encryption_active = is_encryption_active()
    captured_request_user = instance_global_variables.get_request_user()

    def streaming_generator():
        instance_global_variables.set_workflow_override(captured_workflow_override)
        instance_global_variables.set_api_type(captured_api_type)
        instance_global_variables.set_request_user(captured_request_user)
        set_encryption_context(captured_encryption_active)
        logger.debug(f"OpenAI Fallback Generator starting for request_id: {request_id}")
        try:
            for chunk in handle_user_prompt(request_id, messages, stream, api_key=api_key,
                                            tools=tools, tool_choice=tool_choice):
                if isinstance(chunk, str):
                    encoded = chunk.encode('utf-8')
                else:
                    encoded = chunk
                yield encoded
                # Stop after stream terminator to prevent the generator from staying
                # alive during post-stream workflow processing.
                if b'[DONE]' in encoded:
                    return
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
    # Force connection teardown after streaming completes. Some front-ends (notably Node.js-based apps)
    # can have their HTTP connection pool corrupted by keep-alive connections that outlive a streaming response.
    response.headers['Connection'] = 'close'
    return response


def _handle_streaming_request(request_id: str, messages: List[Dict], stream: bool, api_key: str = None,
                              tools: list = None, tool_choice=None) -> Response:
    """
    Selects and invokes the appropriate streaming implementation.

    Checks whether Eventlet is both installed and actively monkey-patching the
    socket layer. If so, uses the optimized queue-based Eventlet implementation
    which supports heartbeats and disconnect detection during LLM prefill. Otherwise,
    falls back to synchronous streaming.

    Args:
        request_id (str): The unique identifier for this request.
        messages (List[Dict]): The conversation history in the internal message format.
        stream (bool): Whether streaming mode is active.
        api_key (str, optional): The API key for encryption context scoping.
        tools (list, optional): Tool definitions from the incoming request.
        tool_choice: Tool selection policy from the incoming request.

    Returns:
        Response: A Flask streaming Response with SSE (text/event-stream) content type.
    """
    is_eventlet_active = EVENTLET_AVAILABLE and eventlet.patcher.is_monkey_patched('socket')

    if is_eventlet_active:
        return _stream_with_eventlet_optimized(request_id, messages, stream, api_key=api_key,
                                               tools=tools, tool_choice=tool_choice)
    else:
        if not EVENTLET_AVAILABLE:
            logger.warning(
                "Eventlet not installed. Falling back to synchronous streaming. Disconnect detection during prefill may be unreliable.")
        else:
            logger.debug(
                "Eventlet installed but monkey patching is not active (not running via run_eventlet.py). Falling back to synchronous streaming.")
        return _stream_response_fallback(request_id, messages, stream, api_key=api_key,
                                          tools=tools, tool_choice=tool_choice)


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

        try:
            instance_global_variables.set_api_type("openaicompletion")
            api_key = api_helpers.extract_api_key()

            logger.info(f"CompletionsAPI request received (ID: {request_id})")

            data: Dict[str, Any] = request.get_json(force=True, silent=True)
            if data is None:
                logger.error("Failed to parse JSON in CompletionsAPI")
                return jsonify({"error": "Invalid JSON data"}), 400

            sensitive_log_lazy(logger, logging.DEBUG,
                               "CompletionsAPI request data (ID: %s): %s",
                               lambda: request_id,
                               lambda: json.dumps(_sanitize_log_data(data)))

            # Set workflow override from model field if applicable.
            # This must happen before reading per-user config values like
            # encryptUsingApiKey, because it determines which user's config to load.
            model_name = data.get("model")
            api_helpers.set_workflow_override(model_name)
            rejection = api_helpers.require_identified_user()
            if rejection:
                return jsonify({"error": rejection}), 400

            set_encryption_context((bool(api_key) and get_encrypt_using_api_key()) or get_redact_log_output())

            prompt: str = data.get("prompt", "")
            stream: bool = data.get("stream", True)
            messages = parse_conversation(prompt)

            if stream:
                return _handle_streaming_request(request_id, messages, stream, api_key=api_key)
            else:
                return_response: str = handle_user_prompt(request_id, messages, False, api_key=api_key)
                response = response_builder.build_openai_completion_response(return_response)
                return jsonify(response)
        finally:
            api_helpers.clear_workflow_override()
            clear_encryption_context()
            clear_api_type()


class ChatCompletionsAPI(MethodView):
    @staticmethod
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

        try:
            instance_global_variables.set_api_type("openaichatcompletion")
            api_key = api_helpers.extract_api_key()

            request_data: Dict[str, Any] = request.get_json(force=True, silent=True)
            if request_data is None:
                logger.error("Failed to parse JSON in ChatCompletionsAPI")
                return jsonify({"error": "Invalid JSON data"}), 400

            logger.info(f"ChatCompletionsAPI request received (ID: {request_id})")
            sensitive_log_lazy(logger, logging.INFO,
                               "ChatCompletionsAPI request data (ID: %s): %s",
                               lambda: request_id,
                               lambda: json.dumps(_sanitize_log_data(request_data)))
            logger.info(f"ChatCompletionsAPI.post() called - stream={request_data.get('stream', False)}")

            # Set workflow override from model field if applicable.
            # This must happen before reading per-user config values like
            # addUserAssistant, because it determines which user's config to load.
            model_name = request_data.get("model")
            api_helpers.set_workflow_override(model_name)
            rejection = api_helpers.require_identified_user()
            if rejection:
                return jsonify({"error": rejection}), 400

            set_encryption_context((bool(api_key) and get_encrypt_using_api_key()) or get_redact_log_output())

            # Intercept OpenWebUI tool-selection requests if the user has opted in
            tool_response = check_openwebui_tool_request(request_data, 'openaichatcompletion')
            if tool_response:
                return tool_response

            add_user_assistant = get_is_chat_complete_add_user_assistant()
            add_missing_assistant = get_is_chat_complete_add_missing_assistant()

            stream: bool = request_data.get("stream", False)
            if 'messages' not in request_data:
                return jsonify({"error": "The 'messages' field is required."}), 400
            messages: List[Dict[str, Any]] = request_data["messages"]
            for message in messages:
                if "role" not in message:
                    return jsonify({"error": "Each message must have a 'role' field."}), 400
                # Allow content to be absent or null for assistant messages with tool_calls
                if "content" not in message and "tool_calls" not in message:
                    return jsonify({"error": "Each message must have 'content' or 'tool_calls'."}), 400

            tools: list = request_data.get("tools")
            tool_choice = request_data.get("tool_choice")

            transformed_messages: List[Dict[str, Any]] = []
            for message in messages:
                role = message["role"]
                raw_content = message.get("content")
                images = []

                if isinstance(raw_content, list):
                    text_parts = []
                    for part in raw_content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                url = part.get("image_url", {}).get("url", "")
                                if url:
                                    images.append(url)
                            elif part.get("type") == "image":
                                source = part.get("source", {})
                                source_type = source.get("type", "")
                                if source_type == "base64":
                                    data = source.get("data", "")
                                    media_type = source.get("media_type", "image/png")
                                    if data:
                                        images.append(f"data:{media_type};base64,{data}")
                                elif source_type == "url":
                                    url = source.get("url", "")
                                    if url:
                                        images.append(url)
                    content = "\n".join(text_parts)
                else:
                    content = raw_content if raw_content is not None else ""

                if add_user_assistant:
                    if role == "user":
                        content = "User: " + content
                    elif role == "assistant":
                        content = "Assistant: " + content

                msg = {"role": role, "content": content}
                if images:
                    msg["images"] = images
                if "tool_calls" in message:
                    msg["tool_calls"] = message["tool_calls"]
                if "tool_call_id" in message:
                    msg["tool_call_id"] = message["tool_call_id"]
                if "name" in message:
                    msg["name"] = message["name"]
                transformed_messages.append(msg)

            if add_missing_assistant:
                if add_user_assistant and messages and messages[-1]["role"] != "assistant":
                    transformed_messages.append({"role": "assistant", "content": "Assistant:"})
                elif messages and messages[-1]["role"] != "assistant":
                    transformed_messages.append({"role": "assistant", "content": ""})

            if stream:
                logger.info(f"ChatCompletionsAPI starting streaming response for request_id: {request_id}")
                return _handle_streaming_request(request_id, transformed_messages, stream, api_key=api_key,
                                                  tools=tools, tool_choice=tool_choice)
            else:
                return_response = handle_user_prompt(request_id, transformed_messages, stream=False, api_key=api_key,
                                                     tools=tools, tool_choice=tool_choice)
                if isinstance(return_response, dict):
                    response = response_builder.build_openai_chat_completion_response(
                        full_text=return_response.get('content', ''),
                        tool_calls=return_response.get('tool_calls'),
                    )
                else:
                    response = response_builder.build_openai_chat_completion_response(return_response)
                return jsonify(response)
        finally:
            api_helpers.clear_workflow_override()
            clear_encryption_context()
            clear_api_type()


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
        app_instance.add_url_rule('/v1/chat/completions', view_func=ChatCompletionsAPI.as_view('v1_chat_completions_api'))
        # Add non-versioned aliases for broader compatibility
        app_instance.add_url_rule('/chat/completions', view_func=ChatCompletionsAPI.as_view('chat_completions_api'))
        app_instance.add_url_rule('/models', view_func=ModelsAPI.as_view('models_api'))
        app_instance.add_url_rule('/completions', view_func=CompletionsAPI.as_view('completions_api'))
