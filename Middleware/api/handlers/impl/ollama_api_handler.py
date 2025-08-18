# Middleware/api/handlers/impl/ollama_api_handler.py

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
        instance_global_variables.API_TYPE = "ollamagenerate"
        logger.debug("GenerateAPI request received")
        data: Dict[str, Any] = request.get_json()
        logger.debug(f"GenerateAPI request received: {json.dumps(_sanitize_log_data(data))}")

        model: str = data.get("model")
        if not model:
            return jsonify({"error": "The 'model' field is required."}), 400

        prompt: str = data.get("prompt", "")
        system: str = data.get("system", "")
        stream: bool = data.get("stream", True)

        if system:
            prompt = system + prompt

        messages = parse_conversation(prompt)
        images = data.get("images", [])
        if images:
            for image_base64 in images:
                messages.append({"role": "images", "content": image_base64})

        if stream:
            return Response(handle_user_prompt(messages, stream=True), content_type='application/json')
        else:
            return_response: str = handle_user_prompt(messages, stream=False)
            response = response_builder.build_ollama_generate_response(return_response, model=model)
            return jsonify(response)


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
        instance_global_variables.API_TYPE = "ollamaapichat"
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        try:
            request_data: Dict[str, Any] = request.get_json(force=True)
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return jsonify({"error": "Invalid JSON data"}), 400

        logger.info(f"ApiChatAPI request received: {json.dumps(_sanitize_log_data(request_data))}")

        if 'model' not in request_data or 'messages' not in request_data:
            return jsonify({"error": "Both 'model' and 'messages' fields are required."}), 400

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

            if add_user_assistant:
                if role == "user":
                    content = "User: " + content
                elif role == "assistant":
                    content = "Assistant: " + content
            transformed_messages.append({"role": role, "content": content})

        if add_missing_assistant:
            if add_user_assistant and transformed_messages and transformed_messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": "Assistant:"})
            elif transformed_messages and transformed_messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": ""})

        stream = request_data.get("stream", True)
        if isinstance(stream, str):
            stream = stream.lower() == 'true'

        response_data = handle_user_prompt(transformed_messages, stream)

        if stream:
            return Response(response_data, mimetype='text/event-stream')
        else:
            model_name = request_data.get("model", "llama3.2")
            response = response_builder.build_ollama_chat_response(response_data, model_name=model_name)
            return jsonify(response)


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
        app_instance.add_url_rule('/api/generate', view_func=GenerateAPI.as_view('api_generate'))
        app_instance.add_url_rule('/api/chat', view_func=ApiChatAPI.as_view('api_chat'))
        app_instance.add_url_rule('/api/tags', view_func=TagsAPI.as_view('api_tags'))
        app_instance.add_url_rule('/api/version', view_func=VersionAPI.as_view('api_version'))
