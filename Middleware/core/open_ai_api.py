import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Union, List, Generator

from flask import Flask, jsonify, request, Response
from flask.views import MethodView

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import get_custom_workflow_is_active, \
    get_active_custom_workflow_name, get_application_port, get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from Middleware.utilities.prompt_extraction_utils import parse_conversation, extract_discussion_id
from Middleware.utilities.text_utils import replace_brackets_in_list
from Middleware.workflows.categorization.prompt_categorizer import PromptCategorizer
from Middleware.workflows.managers.workflow_manager import WorkflowManager

app = Flask(__name__)

logger = logging.getLogger(__name__)


class ModelsAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Provides a list of available models. Currently hardcoded to return "WilmerAI".

        :return: A Flask Response object containing the JSON response with model information.
        """
        current_time = int(time.time())
        response = {
            "object": "list",
            "data": [
                {
                    "id": api_utils.get_model_name(),
                    "object": api_utils.get_model_name(),
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
        Handles POST requests for OpenAI compatible v1/Completions. It processes the incoming data and returns a response.
        https://platform.openai.com/docs/api-reference/batch

        :return: A JSON response if streaming is disabled, or a streaming response if enabled.
        """
        instance_utils.API_TYPE = "openaicompletion"
        logger.info("CompletionsAPI request received")
        data: Dict[str, Any] = request.json
        logger.debug(f"CompletionsAPI request received: {json.dumps(data)}")
        prompt: str = data.get("prompt", "")

        logger.debug("CompletionsAPI Processing Data")

        stream: bool = data.get("stream", False)
        messages = parse_conversation(prompt)

        if stream:
            return Response(WilmerApi.handle_user_prompt(messages, True), content_type='application/json')
        else:
            return_response: str = WilmerApi.handle_user_prompt(messages, False)
            current_time: int = int(time.time())
            response = {
                "id": f"cmpl-{current_time}",
                "object": "text_completion",
                "created": current_time,
                "model": api_utils.get_model_name(),
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
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for OpenAI Compatible chat/completions. It processes the incoming data and returns a response.
        https://platform.openai.com/docs/api-reference/batch

        :return: A JSON response if streaming is disabled, or a streaming response if enabled.
        """
        instance_utils.API_TYPE = "openaichatcompletion"
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        request_data: Dict[str, Any] = request.get_json()
        logger.info(f"ChatCompletionsAPI request received: {json.dumps(request_data)}")

        stream: bool = request_data.get("stream", False)

        # Validate the presence of the 'messages' field
        if 'messages' not in request_data:
            raise ValueError("The 'messages' field is required.")

        # Validate the structure of the messages
        messages: List[Dict[str, str]] = request_data["messages"]
        for message in messages:
            if "role" not in message or "content" not in message:
                raise ValueError("Each message must have 'role' and 'content' fields.")

        # Transform the messages while preserving their order
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

        # Check if the last message is not from assistant and add an assistant message if needed
        if add_missing_assistant:
            if add_user_assistant and messages and messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": "Assistant: "})
            elif messages and messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": ""})

        if stream:
            return Response(
                WilmerApi.handle_user_prompt(transformed_messages, stream),
                mimetype='text/event-stream'
            )
        else:
            return_response = WilmerApi.handle_user_prompt(transformed_messages, stream=False)
            current_time = int(time.time())
            response = {
                "id": f"chatcmpl-{current_time}",
                "object": "chat.completion",
                "created": current_time,
                "model": api_utils.get_model_name(),
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


class GenerateAPI(MethodView):
    @staticmethod
    def post() -> Union[Response, Dict[str, Any]]:
        """
        Handles POST requests for the generate endpoint, matching Ollama's API.
        https://github.com/ollama/ollama/blob/main/docs/api.md#request-json-mode
        :return: A JSON response if streaming is disabled, or a streaming response if enabled.
        """
        instance_utils.API_TYPE = "ollamagenerate"
        logger.debug("GenerateAPI request received")

        # Parse the JSON request
        data: Dict[str, Any] = request.get_json()
        logger.debug(f"GenerateAPI request received: {json.dumps(data)}")

        # Extract required parameters
        model: str = data.get("model")
        if not model:
            return jsonify({"error": "The 'model' field is required."}), 400

        # Extract optional parameters
        prompt: str = data.get("prompt", "")
        suffix: str = data.get("suffix", "")
        system: str = data.get("system", "")
        # Ollama is backwards: If stream isn't in the payload, it's true
        stream: bool = data.get("stream", True)

        if system:
            prompt = system + prompt

        # Parse the conversation from the prompt
        messages = parse_conversation(prompt)

        # Handle the "images" array
        images = data.get("images", [])
        if images:
            for image_base64 in images:
                # Add each image with a role of "images" to the messages collection
                messages.append({
                    "role": "images",
                    "content": image_base64
                })

        logger.debug("GenerateAPI Processing Data")
        logger.debug(f"Messages: {json.dumps(messages)}")

        # Generate and return the appropriate response
        if stream:
            return Response(WilmerApi.handle_user_prompt(messages, stream=True), content_type='application/json')
        else:
            return_response: str = WilmerApi.handle_user_prompt(messages, stream=False)
            current_time: int = int(time.time())
            response = {
                "id": f"gen-{current_time}",
                "object": "text_completion",
                "created": current_time,
                "model": model,
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
    def post() -> Response:
        """
        Handles POST requests for Ollama's /api/chat endpoint.
        https://github.com/ollama/ollama/blob/main/docs/api.md#request-json-mode
        """
        instance_utils.API_TYPE = "ollamaapichat"
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        # Try to parse JSON even if Content-Type is not 'application/json'
        try:
            request_data: Dict[str, Any] = request.get_json(force=True)
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return jsonify({"error": "Invalid JSON data"}), 400

        logger.info(f"ApiChatAPI request received: {json.dumps(request_data)}")

        # Validate 'model' and 'messages' fields
        if 'model' not in request_data or 'messages' not in request_data:
            return jsonify({"error": "Both 'model' and 'messages' fields are required."}), 400

        messages: List[Dict[str, Any]] = request_data["messages"]
        transformed_messages: List[Dict[str, Any]] = []

        for message in messages:
            # Validate that each message has 'role' and 'content'
            if "role" not in message or "content" not in message:
                return jsonify({"error": "Each message must have 'role' and 'content' fields."}), 400

            role = message["role"]
            content = message["content"]

            # Process the 'images' field if it exists
            if "images" in message and isinstance(message["images"], list):
                for image_base64 in message["images"]:
                    # Add each image as its own message with the role "images"
                    transformed_messages.append({
                        "role": "images",
                        "content": image_base64
                    })

            # Add the original message to the collection
            transformed_message = {"role": role, "content": content}
            transformed_messages.append(transformed_message)

        # Add assistant response if necessary
        if add_user_assistant:
            if transformed_messages and transformed_messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": "Assistant: "})
        elif add_missing_assistant:
            if transformed_messages and transformed_messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": ""})

        # Process the response
        stream = request_data.get("stream", True)
        if isinstance(stream, str):
            stream = stream.lower() == 'true'

        response_data = WilmerApi.handle_user_prompt(transformed_messages, stream)

        if stream:
            return Response(response_data, mimetype='text/event-stream')
        else:
            try:
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
                    "total_duration": 4505727700,  # TODO: Replace with calculated or real values
                    "load_duration": 23500100,  # TODO: Replace with calculated or real values
                    "prompt_eval_count": 15,  # TODO: Replace with calculated or real values
                    "prompt_eval_duration": 4000000,  # TODO: Replace with calculated or real values
                    "eval_count": 392,  # TODO: Replace with calculated or real values
                    "eval_duration": 4476000000  # TODO: Replace with calculated or real values
                }
                return jsonify(response)
            except Exception as e:
                logger.error(f"Failed to process non-streaming response: {e}")
                return jsonify({"error": "Invalid response from model"}), 500


class TagsAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests for the /api/tags endpoint.
        """
        models = [
            {
                "name": api_utils.get_model_name(),
                "model": api_utils.get_model_name() + ":latest",
                "modified_at": "2024-11-23T00:00:00Z",
                "size": 1,
                "digest": hashlib.sha256((api_utils.get_model_name()).encode('utf-8')).hexdigest(),
                "details": {
                    "format": "gguf",
                    "family": "wilmer",
                    "families": None,
                    "parameter_size": "N/A",
                    "quantization_level": "Q8"
                }
            }
        ]
        response = {
            "models": models
        }
        return jsonify(response)


class VersionAPI(MethodView):
    @staticmethod
    def get() -> Response:
        """
        Handles GET requests for the /api/version endpoint.
        """
        response = {"version": "0.9"}
        return jsonify(response)


class WilmerApi:
    def __init__(self) -> None:
        self.request_routing_service: PromptCategorizer = PromptCategorizer()
        self.stream: bool = True

    @staticmethod
    def run_api(debug: bool) -> None:
        """
        Initializes the Flask app with the defined API endpoints and starts the server.
        """
        port = get_application_port()
        app.add_url_rule('/v1/models', view_func=ModelsAPI.as_view('v1_models_api'))
        app.add_url_rule('/v1/completions', view_func=CompletionsAPI.as_view('v1_completions_api'))
        app.add_url_rule('/models', view_func=ModelsAPI.as_view('models_api'))
        app.add_url_rule('/completions', view_func=CompletionsAPI.as_view('completions_api'))
        app.add_url_rule('/chat/completions', view_func=ChatCompletionsAPI.as_view('chat_completions_api'))
        app.add_url_rule('/api/generate', view_func=GenerateAPI.as_view('api_generate'))
        app.add_url_rule('/api/chat', view_func=ApiChatAPI.as_view('api_chat'))  # New endpoint
        app.add_url_rule('/api/tags', view_func=TagsAPI.as_view('api_tags'))  # Existing endpoint
        app.add_url_rule('/api/version', view_func=VersionAPI.as_view('api_version'))  # Existing endpoint
        app.run(host='0.0.0.0', port=port, debug=debug)

    @staticmethod
    def handle_user_prompt(prompt_collection: List[Dict[str, Any]], stream: bool) -> Union[
        str, Generator[str, None, None]]:
        """
        Processes the user prompt by applying the appropriate workflow and returns the result.

        :param prompt_collection: A list of dictionaries containing the prompt messages.
        :param stream: A boolean indicating whether the response should be streamed.
        :return: The processed prompt response.
        """
        request_id = str(uuid.uuid4())
        discussion_id = extract_discussion_id(prompt_collection)
        prompt = replace_brackets_in_list(prompt_collection)

        logger.debug("Handle user prompt discussion_id: {}".format(discussion_id))

        if not get_custom_workflow_is_active():
            request_routing_service: PromptCategorizer = PromptCategorizer()
            return request_routing_service.get_prompt_category(prompt, stream, request_id, discussion_id)
        else:
            logger.info("handle_user_prompt workflow exists")
            workflow_manager: WorkflowManager = WorkflowManager(get_active_custom_workflow_name())
            return workflow_manager.run_workflow(prompt_collection, request_id, stream=stream,
                                                 discussionId=discussion_id)
