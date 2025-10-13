# In middleware/llmapis/handlers/impl/openai_completions_api_handler.py
import json
import logging
from typing import Dict, Optional, Any, List

from Middleware.llmapis.handlers.base.base_completions_handler import BaseCompletionsHandler

logger = logging.getLogger(__name__)


class OpenAiCompletionsApiHandler(BaseCompletionsHandler):
    """
    Handles interactions with the legacy OpenAI Completions API (`/v1/completions`).

    This class extends `BaseCompletionsHandler` to adapt the single-string prompt
    logic for the specific requirements of the OpenAI Completions endpoint. It
    overrides methods to construct the correct API URL, add the 'model' parameter
    to the payload, and parse the standard Server-Sent Event (SSE) stream format.
    """

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the OpenAI Completions request.

        Returns:
            str: The complete URL for the `/v1/completions` endpoint.
        """
        return f"{self.base_url.rstrip('/')}/v1/completions"

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the OpenAI-specific payload for the API request.

        This method first calls the parent implementation to build the base payload
        containing the formatted prompt and generation parameters. It then adds the
        `model` name as a top-level key, which is required by the OpenAI
        Completions API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The historical conversation (unused in this handler).
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Returns:
            Dict: The JSON payload ready to be sent to the OpenAI Completions API.
        """
        payload = super()._prepare_payload(conversation, system_prompt, prompt)

        if not self.dont_include_model:
            payload["model"] = self.model_name

        return payload

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; False for standard Server-Sent Events (SSE).

        The OpenAI Completions API uses the standard SSE format where each message
        is prefixed with 'data: '. This property tells the base streaming handler
        not to treat each line as a separate JSON object.

        Returns:
            bool: Returns False to disable line-by-line JSON processing.
        """
        return False

    @property
    def _required_event_name(self) -> Optional[str]:
        """
        Specifies an SSE event name to filter for.

        This API does not use named events, so no filtering is necessary.

        Returns:
            Optional[str]: Returns None as no specific event is required.
        """
        return None

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON object from an OpenAI Completions 'data:' line.

        This method loads the JSON string from a standard SSE `data:` field and
        extracts the content token and finish reason from the 'choices' array.

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary with 'token' and 'finish_reason'
            keys, or None if parsing fails or the structure is invalid.
        """
        try:
            if not data_str:
                return None

            chunk_data = json.loads(data_str)
            # Use direct access to raise IndexError/KeyError on malformed data
            choice = chunk_data['choices'][0]
            token = choice.get("text", "")
            finish_reason = choice.get("finish_reason")
            return {'token': token, 'finish_reason': finish_reason}
        # Add KeyError to the list of caught exceptions
        except (json.JSONDecodeError, IndexError, KeyError):
            logger.warning(f"Could not parse OpenAI Completions stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming OpenAI Completions response.

        This method navigates the JSON structure of a complete API response
        to find and return the main text content from the 'choices' array.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content, or an empty string if not found.
        """
        try:
            return response_json['choices'][0]['text'] or ""
        except (KeyError, IndexError):
            logger.error(f"Could not find text in OpenAI Completions response: {response_json}")
            return ""
