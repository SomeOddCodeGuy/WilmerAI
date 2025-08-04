# Middleware/api/handlers/impl/ollama_api_handler.py

import hashlib
import json
import logging
import time
from datetime import datetime
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


class GenerateAPI(MethodView):
    @staticmethod
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for the generate endpoint, matching Ollama's API.

        This method processes incoming requests to the /api/generate endpoint,
        extracts the prompt and other parameters, and uses the workflow gateway
        to handle the request, returning either a streaming or a single-block
        response that mimics the Ollama generate API's format.

        Returns:
            Union[Response, Dict[str, Any]]: A Flask Response object for streaming,
                                             or a dictionary that will be JSONified
                                             for a single-block response.
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
        stream: bool = data.get("stream", True) # Ollama defaults to true if not present

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
            current_time: int = int(time.time())
            response = {
                "id": f"gen-{current_time}",
                "object": "text_completion",
                "created": current_time,
                "model": model,
                "response": f"{return_response}",
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


class ApiChatAPI(MethodView):
    @staticmethod
    @handle_openwebui_tool_check('ollamaapichat')
    def post() -> Response:
        """
        Handles POST requests for Ollama's /api/chat endpoint.

        This method processes incoming requests to the /api/chat endpoint,
        extracts the conversation history, and optionally modifies it based on
        user configuration. It then passes the messages to the workflow gateway
        and returns a streaming or a single-block response that matches
        the Ollama /api/chat format.

        Returns:
            Response: A Flask Response object for either streaming or
                      a single-block JSON response.
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
            current_time = datetime.utcnow().isoformat() + 'Z'
            response = {
                "model": request_data.get("model", "llama3.2"),
                "created_at": current_time,
                "message": {
                    "role": "assistant",
                    "content": response_data
                },
                "done_reason": "stop",
                "done": True,
                "total_duration": 4505727700, "load_duration": 23500100,
                "prompt_eval_count": 15, "prompt_eval_duration": 4000000,
                "eval_count": 392, "eval_duration": 4476000000
            }
            return jsonify(response)


class TagsAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests for the /api/tags endpoint.

        This method returns a list of available models, which in this
        implementation is a hardcoded list containing the model specified
        in the Endpoint config. The response is formatted to be compatible with
        the Ollama API's /api/tags endpoint.

        Returns:
            Response: A JSON response containing a list of available models.
        """
        model_name = api_helpers.get_model_name()
        models = [
            {
                "name": model_name,
                "model": model_name + ":latest",
                "modified_at": "2024-11-23T00:00:00Z",
                "size": 1,
                "digest": hashlib.sha256(model_name.encode('utf-8')).hexdigest(),
                "details": {
                    "format": "gguf", "family": "wilmer", "families": None,
                    "parameter_size": "N/A", "quantization_level": "Q8"
                }
            }
        ]
        return jsonify({"models": models})


class VersionAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests for the /api/version endpoint.

        This method returns the current version of the application as a
        JSON response, mimicking the Ollama API's /api/version endpoint.

        Returns:
            Response: A JSON response containing the version number.
        """
        return jsonify({"version": "0.9"})


class OllamaApiHandler(BaseApiHandler):
    """
    Handles API requests that follow the Ollama API schema.

    This class provides the entry points for different Ollama-compatible
    endpoints, such as /api/generate, /api/chat, /api/tags, and /api/version.
    It registers these routes with the Flask application instance.
    """
    def register_routes(self, app_instance: app) -> None:
        """
        Registers the Ollama API-compatible routes with the Flask app.

        Args:
            app_instance (app): The Flask application instance to which the routes
                                should be added.
        """
        app_instance.add_url_rule('/api/generate', view_func=GenerateAPI.as_view('api_generate'))
        app_instance.add_url_rule('/api/chat', view_func=ApiChatAPI.as_view('api_chat'))
        app_instance.add_url_rule('/api/tags', view_func=TagsAPI.as_view('api_tags'))
        app_instance.add_url_rule('/api/version', view_func=VersionAPI.as_view('api_version'))