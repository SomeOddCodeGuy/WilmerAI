# Middleware/api/handlers/impl/openai_api_handler.py

import json
import logging
import time
from typing import Any, Dict, Union, List

from flask import jsonify, request, Response
from flask.views import MethodView

from Middleware.api import api_helpers
from Middleware.api.app import app
from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
from Middleware.api.workflow_gateway import handle_user_prompt, _sanitize_log_data, handle_openwebui_tool_check
from Middleware.common import instance_global_variables
from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from Middleware.utilities.prompt_extraction_utils import parse_conversation

logger = logging.getLogger(__name__)


class ModelsAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Provides a list of available models.

        This method handles GET requests to the `/v1/models` and `/models`
        endpoints, returning a list of available models. Currently, it is
        hardcoded to return only "WilmerAI".

        Returns:
            Response: A Flask JSON response containing the list of models.
        """
        current_time = int(time.time())
        response = {
            "object": "list",
            "data": [
                {
                    "id": api_helpers.get_model_name(),
                    "object": api_helpers.get_model_name(),
                    "created": current_time,
                    "owned_by": "Wilmer"
                }
            ]
        }
        return jsonify(response)


class CompletionsAPI(MethodView):
    @staticmethod
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for OpenAI compatible completions.

        This method processes incoming requests to the `/v1/completions` and
        `/completions` endpoints. It extracts the prompt and streaming
        preference from the request data and sends it to the workflow gateway.
        The response is then formatted to match the OpenAI completions API
        schema, either as a streaming response or a single JSON object.

        Returns:
            Union[Response, Dict[str, Any]]: A Flask response object containing
                                             the completion result, which is
                                             either a streaming response or
                                             a JSON object.
        """
        instance_global_variables.API_TYPE = "openaicompletion"
        logger.info("CompletionsAPI request received")
        data: Dict[str, Any] = request.json
        logger.debug(f"CompletionsAPI request received: {json.dumps(_sanitize_log_data(data))}")
        prompt: str = data.get("prompt", "")
        stream: bool = data.get("stream", False)
        messages = parse_conversation(prompt)

        if stream:
            return Response(handle_user_prompt(messages, True), content_type='application/json')
        else:
            return_response: str = handle_user_prompt(messages, False)
            current_time: int = int(time.time())
            response = {
                "id": f"cmpl-{current_time}",
                "object": "text_completion",
                "created": current_time,
                "model": api_helpers.get_model_name(),
                "system_fingerprint": "wmr_123456789",
                "choices": [
                    {
                        "text": f"{return_response}",
                        "index": 0,
                        "logprobs": None,
                        "finish_reason": "stop"
                    }
                ],
                "usage": {}
            }
            return jsonify(response)


class ChatCompletionsAPI(MethodView):
    @staticmethod
    @handle_openwebui_tool_check('openaichatcompletion')
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for OpenAI compatible chat completions.

        This method processes incoming requests to the `/chat/completions`
        endpoint. It prepares the incoming `messages` from the request
        to be compatible with the WilmerAI workflow engine, including
        handling streaming and non-streaming responses. It also includes
        logic for OpenWebUI tool checks and optional message formatting
        based on user configuration.

        Returns:
            Union[Response, Dict[str, Any]]: A Flask response object
                                             containing the chat completion
                                             result, which is either a
                                             streaming response or a JSON
                                             object.

        Raises:
            ValueError: If the request data does not contain the required
                        'messages' field or if any message is missing 'role'
                        or 'content' fields.
        """
        instance_global_variables.API_TYPE = "openaichatcompletion"
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        request_data: Dict[str, Any] = request.get_json()
        logger.info(f"ChatCompletionsAPI request received: {json.dumps(_sanitize_log_data(request_data))}")

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
            return Response(
                handle_user_prompt(transformed_messages, stream),
                mimetype='text/event-stream'
            )
        else:
            return_response = handle_user_prompt(transformed_messages, stream=False)
            current_time = int(time.time())
            response = {
                "id": f"chatcmpl-{current_time}",
                "object": "chat.completion",
                "created": current_time,
                "model": api_helpers.get_model_name(),
                "system_fingerprint": "wmr_123456789",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"{return_response}",
                        },
                        "logprobs": None,
                        "finish_reason": "stop"
                    }
                ],
                "usage": {}
            }
            return jsonify(response)


class OpenAIApiHandler(BaseApiHandler):
    """
    Handles API routes for OpenAI compatible endpoints.

    This class extends the `BaseApiHandler` to register specific routes
    that mimic the OpenAI API schema, including `/v1/models`, `/v1/completions`,
    and `/chat/completions`. It serves as the entry point for clients
    that expect an OpenAI-like API interface.

    Inherits:
        BaseApiHandler: The base class for all API handlers.
    """
    def register_routes(self, app_instance: app) -> None:
        """
        Registers the OpenAI-compatible API routes with the Flask application.

        Args:
            app_instance (app): The Flask application instance.
        """
        app_instance.add_url_rule('/v1/models', view_func=ModelsAPI.as_view('v1_models_api'))
        app_instance.add_url_rule('/v1/completions', view_func=CompletionsAPI.as_view('v1_completions_api'))
        app_instance.add_url_rule('/chat/completions', view_func=ChatCompletionsAPI.as_view('chat_completions_api'))
        # Add non-versioned aliases for broader compatibility
        app_instance.add_url_rule('/models', view_func=ModelsAPI.as_view('models_api'))
        app_instance.add_url_rule('/completions', view_func=CompletionsAPI.as_view('completions_api'))