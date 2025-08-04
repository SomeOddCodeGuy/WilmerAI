# middleware/llmapis/handlers/impl/ollama_generate_api_handler.py
import json
import logging
from typing import Dict, Optional, Any, List

from Middleware.llmapis.handlers.base.base_completions_handler import BaseCompletionsHandler

logger = logging.getLogger(__name__)


class OllamaGenerateApiHandler(BaseCompletionsHandler):
    """
    Handles interactions with the Ollama /api/generate endpoint.

    This class extends `BaseCompletionsHandler` to adapt the prompt
    completion logic for the Ollama `/api/generate` endpoint. It flattens the
    conversation into a single prompt string and handles Ollama's specific
    payload structure, which uses a nested 'options' object for generation
    parameters and its line-delimited JSON streaming format.
    """

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the Ollama generate request.

        Returns:
            str: The complete URL for the Ollama `/api/generate` endpoint.
        """
        return f"{self.base_url}/api/generate"

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the Ollama-specific payload for the /api/generate request.

        This method overrides the base implementation to structure the payload
        as required by the Ollama API. It combines the conversation history into
        a single prompt string and moves generation parameters into a nested
        'options' dictionary.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Returns:
            Dict: The JSON payload ready to be sent to the Ollama API.
        """
        self.set_gen_input()
        full_prompt = self._build_prompt_from_conversation(system_prompt, prompt)

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": self.stream,
            "raw": True,
            "options": self.gen_input or {}
        }

        logger.info(f"Payload prepared for {self.__class__.__name__}")
        logger.debug(f"URL: {self.base_url}, Payload: {json.dumps(payload, indent=2)}")
        return payload

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; True for line-delimited JSON.

        Ollama's /api/generate endpoint sends responses as a stream of JSON
        objects, one per line. This property directs the base streaming handler
        to iterate line-by-line.

        Returns:
            bool: Always returns True to enable line-by-line stream processing.
        """
        return True

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON object from the Ollama streaming response.

        Each line from the Ollama stream is a complete JSON string. This method
        loads that string and extracts the content token ("response") and the
        stream completion status ("done").

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary with 'token' and 'finish_reason'
            keys, or None if parsing fails.
        """
        try:
            if not data_str:
                return None
            chunk_data = json.loads(data_str)
            token = chunk_data.get("response", "")
            finish_reason = "stop" if chunk_data.get("done") else None
            return {'token': token, 'finish_reason': finish_reason}
        except json.JSONDecodeError:
            logger.warning(f"Could not parse Ollama stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming Ollama API response.

        This method navigates the JSON structure of a complete response from the
        /api/generate endpoint to find and return the main content.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content, or an empty string if not found.
        """
        response_text = response_json.get('response')
        if response_text is None:
            logger.error(f"Could not find 'response' key in Ollama generate response: {response_json}")
            return ""
        return response_text