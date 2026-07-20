# Middleware/api/handlers/impl/openai_api_handler.py

import json
import logging
import uuid

from typing import Any, Dict, Optional, Union, List

from flask import jsonify, request, Response, g
from flask.views import MethodView

from Middleware.api import api_helpers
from Middleware.api.app import app
from Middleware.api.handlers.base import base_streaming
from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
from Middleware.api.workflow_gateway import handle_user_prompt, _sanitize_log_data, check_openwebui_tool_request
from Middleware.common import instance_global_variables
from Middleware.services.cancellation_service import cancellation_service
from Middleware.services.idempotency_service import idempotency_service
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant, get_encrypt_using_api_key, get_redact_log_output
from Middleware.utilities.encryption_utils import get_api_key_hash_if_available
from Middleware.common.instance_global_variables import clear_api_type
from Middleware.utilities.prompt_extraction_utils import parse_conversation
from Middleware.utilities.sensitive_logging_utils import (
    set_encryption_context, clear_encryption_context, sensitive_log_lazy,
)

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()


def _chunk_signals_done(encoded: bytes) -> bool:
    """Reports whether an encoded SSE chunk IS the [DONE] terminator.

    This must be an exact match against the terminator event, not a substring
    check: each chunk is one SSE event, and a model that writes the literal
    text "[DONE]" in its response (e.g. explaining the SSE protocol) would
    otherwise terminate the client stream mid-response.

    Args:
        encoded (bytes): One encoded response chunk.

    Returns:
        bool: True when the chunk signals stream completion.
    """
    return encoded.strip() == b'data: [DONE]'


# The heartbeat is an SSE comment line: it keeps the TCP connection alive for
# disconnect detection without delivering any content to the client.
_STREAMING_CONFIG = base_streaming.StreamingApiConfig(
    api_label="OpenAI",
    heartbeat_message=b':\n\n',
    mimetype='text/event-stream',
    chunk_signals_done=_chunk_signals_done,
)


def _handle_streaming_request(request_id: str, messages: List[Dict], stream: bool, api_key: str = None,
                              tools: list = None, tool_choice=None) -> Response:
    """
    Streams the workflow response using the shared API streaming machinery.

    handle_user_prompt is passed at call time so tests can patch it on this module.

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
    return base_streaming.handle_streaming_request(_STREAMING_CONFIG, handle_user_prompt, request_id,
                                                   messages, stream, api_key=api_key,
                                                   tools=tools, tool_choice=tool_choice)


def _admit_idempotency_key(request_id: str, api_key: Optional[str]) -> Optional[str]:
    """
    Registers this request under its client idempotency key and cancels any
    still-in-flight original that reused the same key.

    The chat client sends the same ``X-Idempotency-Key`` across every retry of
    one logical request, and only retries after an attempt failed before its
    response began. So when the incoming key is already bound to an in-flight
    request, that original's client is gone by definition: its downstream work
    is cancelled immediately (rather than waiting for the streaming layer to
    notice the dead socket) and the new arrival is served fresh.

    Registry entries are scoped per client API key (by hash, never the raw
    key) so two independent clients that happen to reuse the same idempotency
    key value cannot cancel each other's requests. Clients that send no API
    key share a single anonymous scope.

    Args:
        request_id (str): The unique identifier generated for this request.
        api_key (Optional[str]): The client's Bearer API key, when supplied.

    Returns:
        Optional[str]: The idempotency key when the client supplied one (so the
        caller knows an entry was registered and must be released), or None for
        a legacy client that sent no key.
    """
    idempotency_key = api_helpers.extract_idempotency_key()
    if not idempotency_key:
        return None

    scope = get_api_key_hash_if_available(api_key) or "anon"
    logger.info(f"Request {request_id} admitted with idempotency key {idempotency_key}")
    displaced = idempotency_service.register(f"{scope}:{idempotency_key}", request_id)
    if displaced:
        logger.info(
            f"Idempotency key {idempotency_key} was already in flight as request {displaced}; "
            f"cancelling the orphan and serving {request_id} fresh.")
        cancellation_service.request_cancellation(displaced)
    return idempotency_key


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

        # Idempotency bookkeeping. For a streaming response the registry entry is
        # released by the streaming teardown (which owns the full backend
        # lifetime); for a non-streaming response it is released in this finally.
        idempotency_key: Optional[str] = None
        handed_to_stream = False

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
            # Deliberate deviation from the OpenAI spec (whose default is false):
            # the legacy front-ends this endpoint serves assume streaming and do
            # not always send the flag. Changing this default would break them.
            stream: bool = data.get("stream", True)
            messages = parse_conversation(prompt)

            idempotency_key = _admit_idempotency_key(request_id, api_key)

            if stream:
                response = _handle_streaming_request(request_id, messages, stream, api_key=api_key)
                handed_to_stream = True
                return response
            else:
                return_response: str = handle_user_prompt(request_id, messages, False, api_key=api_key)
                response = response_builder.build_openai_completion_response(return_response)
                return jsonify(response)
        finally:
            # Streaming releases in its own teardown; only the non-streaming and
            # error-before-dispatch paths release here (a no-op when no key).
            if idempotency_key and not handed_to_stream:
                idempotency_service.release(request_id)
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
                                             JSON object. Payload validation
                                             failures (missing 'messages',
                                             'role', or 'content'/'tool_calls')
                                             return a 400 error response.
        """
        # Generate Request ID immediately and store it in the context
        request_id = str(uuid.uuid4())
        g.current_request_id = request_id

        # Idempotency bookkeeping. For a streaming response the registry entry is
        # released by the streaming teardown (which owns the full backend
        # lifetime); for a non-streaming response it is released in this finally.
        idempotency_key: Optional[str] = None
        handed_to_stream = False

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

            idempotency_key = _admit_idempotency_key(request_id, api_key)

            if stream:
                logger.info(f"ChatCompletionsAPI starting streaming response for request_id: {request_id}")
                response = _handle_streaming_request(request_id, transformed_messages, stream, api_key=api_key,
                                                     tools=tools, tool_choice=tool_choice)
                handed_to_stream = True
                return response
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
            # Streaming releases in its own teardown; only the non-streaming and
            # error-before-dispatch paths release here (a no-op when no key).
            if idempotency_key and not handed_to_stream:
                idempotency_service.release(request_id)
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
