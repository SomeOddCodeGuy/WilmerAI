# middleware/llmapis/handlers/impl/openai_api_handler.py
import json
import logging
from typing import Dict, Optional, Any, List

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler

logger = logging.getLogger(__name__)


class OpenAiApiHandler(BaseChatCompletionsHandler):
    """
    Handles interactions with any OpenAI-compatible Chat Completions API.

    This class extends `BaseChatCompletionsHandler` and is designed for APIs
    that follow the standard OpenAI request and response schema. It relies on
    the base class's payload preparation and primarily overrides methods to
    specify the correct API endpoint and to parse the specific structure of
    OpenAI's streaming and non-streaming responses.
    """

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; False for standard Server-Sent Events (SSE).

        OpenAI-compatible APIs use the standard SSE format where each message is
        prefixed with 'data: '. This property tells the base streaming handler not
        to treat each line as a standalone JSON object.

        Returns:
            bool: Returns False to disable line-by-line JSON stream processing.
        """
        return False

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the OpenAI chat request.

        Returns:
            str: The complete URL for the standard `/v1/chat/completions` endpoint.
        """
        return f"{self.base_url}/v1/chat/completions"

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON data chunk from an OpenAI-compatible stream.

        This method is called for each 'data: ' line in the SSE stream. It loads
        the JSON string and extracts the content token and finish reason from
        the `choices` array.

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary with 'token' and 'finish_reason'
            keys, or None if the chunk is empty or cannot be parsed.
        """
        try:
            if not data_str:
                return None

            chunk_data = json.loads(data_str)
            choice = chunk_data.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            token = delta.get("content", "")
            finish_reason = choice.get("finish_reason")

            return {'token': token, 'finish_reason': finish_reason}
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Could not parse OpenAI stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming OpenAI-compatible API response.

        This method navigates the JSON structure of a complete OpenAI response
        to find and return the main message content.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content from `choices[0].message.content`,
            or an empty string if not found.
        """
        try:
            return response_json['choices'][0]['message']['content'] or ""
        except (KeyError, IndexError, TypeError):
            logger.error(f"Could not find content in OpenAI response: {response_json}")
            return ""