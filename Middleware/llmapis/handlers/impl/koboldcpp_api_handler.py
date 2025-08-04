# middleware/llmapis/handlers/impl/koboldcpp_api_handler.py
import json
import logging
from typing import Dict, Optional, Any

from Middleware.llmapis.handlers.base.base_completions_handler import BaseCompletionsHandler

logger = logging.getLogger(__name__)


class KoboldCppApiHandler(BaseCompletionsHandler):
    """
    Handles interactions with the KoboldCpp API.

    This class extends `BaseCompletionsHandler` to manage requests to KoboldCpp's
    generation endpoints. It implements the logic required for both streaming and
    non-streaming modes, correctly parsing KoboldCpp's specific Server-Sent Event (SSE)
    format and standard JSON responses.
    """

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the KoboldCpp request.

        This method dynamically selects the appropriate endpoint based on whether
        streaming is enabled, switching between the streaming and non-streaming
        generation endpoints provided by KoboldCpp.

        Returns:
            str: The complete URL for the KoboldCpp API endpoint.
        """
        return f"{self.base_url}/api/extra/generate/stream" if self.stream else f"{self.base_url}/api/v1/generate"

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; False for standard Server-Sent Events.

        KoboldCpp uses the standard SSE format (e.g., 'event: message', 'data: {...}')
        rather than a simple line-delimited JSON stream. This property tells the base
        streaming handler to look for 'data:' prefixes.

        Returns:
            bool: Returns False to disable line-by-line JSON processing.
        """
        return False

    @property
    def _required_event_name(self) -> Optional[str]:
        """
        Specifies an SSE event name to filter for.

        KoboldCpp's streaming endpoint can send multiple event types. This ensures
        that only events named 'message', which contain the text tokens, are processed.

        Returns:
            str: The required event name 'message'.
        """
        return "message"

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single chunk of data from a KoboldCpp streaming response.

        This method is called for each 'data:' line received from the stream that
        has a matching event name. It loads the JSON string and extracts the token.

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing the 'token', or None
            if the chunk is empty or cannot be parsed.
        """
        try:
            if not data_str:
                return None
            chunk_data = json.loads(data_str)
            token = chunk_data.get("token", "")
            return {'token': token, 'finish_reason': None}
        except json.JSONDecodeError:
            logger.warning(f"Could not parse KoboldCpp stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming KoboldCpp API response.

        This method navigates the JSON structure of a complete KoboldCpp response
        to find and return the main generated text content.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content, or an empty string if not found.
        """
        try:
            return response_json['results'][0]['text'] or ""
        except (KeyError, IndexError, TypeError):
            logger.error(f"Could not find text in KoboldCpp response: {response_json}")
            return ""