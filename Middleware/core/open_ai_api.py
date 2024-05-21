import time
from typing import Any, Dict, Union

from flask import Flask, jsonify, request, Response
from flask.views import MethodView

from Middleware.utilities.config_utils import get_user_config, get_custom_workflow_is_active, \
    get_active_custom_workflow_name
from Middleware.utilities.text_utils import replace_brackets
from Middleware.workflows.categorization.prompt_categorizer import PromptCategorizer
from Middleware.workflows.managers.workflow_manager import WorkflowManager

app = Flask(__name__)


def get_stream() -> bool:
    """
    Retrieves the stream configuration setting.

    :return: The stream setting from the user configuration.
    """
    data = get_user_config()
    return data['stream']


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
                    "owned_by": "SomeOddCodeGuy"
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
        prompt: str = data.get("prompt", "")

        print("CompletionsAPI Processing Data")
        stream: bool = get_stream()

        if stream:
            return Response(WilmerApi.handle_user_prompt(prompt, True), content_type='application/json')
        else:
            return_response: str = WilmerApi.handle_user_prompt(prompt, False)
            current_time: int = int(time.time())
            response = {
                "id": f"cmpl-{current_time}",
                "object": "text_completion",
                "created": current_time,
                "model": "gpt-3.5-turbo-instruct",
                "system_fingerprint": "wmr_123456789",
                "choices": [
                    {
                        "text": f"\n\n{return_response}",
                        "index": 0,
                        "logprobs": None,
                        "finish_reason": "length"
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": len(return_response.split()),
                    "total_tokens": len(prompt.split()) + len(return_response.split())
                }
            }
            return jsonify(response)


class WilmerApi:

    def __init__(self) -> None:
        self.request_routing_service: PromptCategorizer = PromptCategorizer()
        self.stream: bool = True

    @staticmethod
    def run_api() -> None:
        """
        Initializes the Flask app with the defined API endpoints and starts the server.
        """
        app.add_url_rule('/v1/models', view_func=ModelsAPI.as_view('models_api'))
        app.add_url_rule('/v1/completions', view_func=CompletionsAPI.as_view('completions_api'))
        app.run(host='0.0.0.0', port=5002, debug=False)

    @staticmethod
    def handle_user_prompt(prompt: str, stream: bool) -> str:
        """
        Processes the user prompt by applying the appropriate workflow and returns the result.

        :param prompt: The prompt text received from the API request.
        :param stream: A boolean indicating whether the response should be streamed.
        :return: The processed prompt response.
        """
        if not get_custom_workflow_is_active():
            prompt = replace_brackets(prompt)
            request_routing_service: PromptCategorizer = PromptCategorizer()
            return request_routing_service.get_prompt_category(prompt, stream)
        else:
            workflow_manager: WorkflowManager = WorkflowManager(get_active_custom_workflow_name())
            return workflow_manager.run_workflow(prompt, stream)
