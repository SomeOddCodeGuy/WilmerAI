import json
import time
from typing import Any, Dict, Union, List

from flask import Flask, jsonify, request, Response
from flask.views import MethodView

from Middleware.utilities.config_utils import get_custom_workflow_is_active, \
    get_active_custom_workflow_name, get_application_port, get_is_streaming, get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from Middleware.utilities.prompt_extraction_utils import parse_conversation
from Middleware.utilities.text_utils import replace_brackets_in_list
from Middleware.workflows.categorization.prompt_categorizer import PromptCategorizer
from Middleware.workflows.managers.workflow_manager import WorkflowManager

app = Flask(__name__)


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
                    "id": "Wilmer-AI",
                    "object": "WilmerAI",
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
        Handles POST requests for completing prompts. It processes the incoming data and returns a response.

        :return: A JSON response if streaming is disabled, or a streaming response if enabled.
        """
        print("CompletionsAPI request received")
        data: Dict[str, Any] = request.json
        print("CompletionsAPI request received: " + json.dumps(data))
        prompt: str = data.get("prompt", "")

        print("CompletionsAPI Processing Data")
        stream: bool = get_is_streaming()
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
                "model": "Wilmer-AI",
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
    def post() -> Response:
        """
        Handles POST requests for chat completions. It processes the incoming data and returns a streaming response.

        :return: A streaming response containing the processed chat completion.
        """
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        request_data: Dict[str, Any] = request.get_json()
        print("ChatCompletionsAPI request received: " + json.dumps(request_data))

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
        if add_missing_assistant and add_user_assistant:
            if messages and messages[-1]["role"] != "assistant":
                transformed_messages.append({"role": "assistant", "content": "Assistant: "})

        return Response(WilmerApi.handle_user_prompt(transformed_messages, True), mimetype='text/event-stream')


class WilmerApi:
    def __init__(self) -> None:
        self.request_routing_service: PromptCategorizer = PromptCategorizer()
        self.stream: bool = True

    @staticmethod
    def run_api() -> None:
        """
        Initializes the Flask app with the defined API endpoints and starts the server.
        """
        port = get_application_port()
        app.add_url_rule('/v1/models', view_func=ModelsAPI.as_view('v1_models_api'))
        app.add_url_rule('/v1/completions', view_func=CompletionsAPI.as_view('v1_completions_api'))
        app.add_url_rule('/models', view_func=ModelsAPI.as_view('models_api'))
        app.add_url_rule('/completions', view_func=CompletionsAPI.as_view('completions_api'))
        app.add_url_rule('/chat/completions', view_func=ChatCompletionsAPI.as_view('chat_completions_api'))
        app.run(host='0.0.0.0', port=port, debug=False)

    @staticmethod
    def handle_user_prompt(prompt_collection: List[Dict[str, str]], stream: bool) -> str:
        """
        Processes the user prompt by applying the appropriate workflow and returns the result.

        :param prompt_collection: A list of dictionaries containing the prompt messages.
        :param stream: A boolean indicating whether the response should be streamed.
        :return: The processed prompt response.
        """
        if not get_custom_workflow_is_active():
            prompt = replace_brackets_in_list(prompt_collection)
            request_routing_service: PromptCategorizer = PromptCategorizer()
            return request_routing_service.get_prompt_category(prompt, stream)
        else:
            print("handle_user_prompt workflow exists")
            workflow_manager: WorkflowManager = WorkflowManager(get_active_custom_workflow_name())
            return workflow_manager.run_workflow(prompt_collection, stream, allow_generator=True)
