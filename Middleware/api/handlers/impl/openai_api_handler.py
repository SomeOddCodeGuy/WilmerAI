# Middleware/api/handlers/impl/openai_api_handler.py

import json
import logging
from typing import Any, Dict, Union, List

from flask import jsonify, request, Response
from flask.views import MethodView

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
        instance_global_variables.API_TYPE = "openaicompletion"
        logger.info("CompletionsAPI request received")
        data: Dict[str, Any] = request.json
        logger.debug(f"CompletionsAPI request received: {json.dumps(_sanitize_log_data(data))}")
        prompt: str = data.get("prompt", "")
        stream: bool = data.get("stream", True)
        messages = parse_conversation(prompt)

        if stream:
            return Response(handle_user_prompt(messages, True), content_type='application/json')
        else:
            return_response: str = handle_user_prompt(messages, False)
            response = response_builder.build_openai_completion_response(return_response)
            return jsonify(response)


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
            response = response_builder.build_openai_chat_completion_response(return_response)
            return jsonify(response)


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
