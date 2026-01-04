# middleware/llmapis/handlers/impl/ollama_chat_api_handler.py
import json
import logging
from typing import Dict, List, Optional, Any

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler
from Middleware.utilities.text_utils import return_brackets

logger = logging.getLogger(__name__)


class OllamaChatHandler(BaseChatCompletionsHandler):
    """
    Handles interactions with the Ollama Chat API.

    This class extends `BaseChatCompletionsHandler` to adapt the chat
    completion logic specifically for the Ollama API format. It overrides
    methods to handle Ollama's unique payload structure, which uses an
    'options' object for generation parameters, and its line-delimited JSON
    streaming format.

    This handler also supports multimodal conversations including images.
    When image messages are present, they are extracted and attached to the
    last user message under the `images` key as required by the Ollama API.
    """

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; True for line-delimited JSON.

        Ollama sends responses as a stream of JSON objects, one per line.
        This property tells the base streaming handler to iterate line-by-line.

        Returns:
            bool: Returns True to enable line-by-line stream processing.
        """
        return True

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the Ollama chat request.

        Returns:
            str: The complete URL for the Ollama `/api/chat` endpoint.
        """
        return f"{self.base_url.rstrip('/')}/api/chat"

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the Ollama-specific payload for the API request.

        This method overrides the base implementation to structure the payload
        as required by the Ollama API. It moves generation parameters into a
        nested 'options' dictionary. For non-streaming requests, it also
        explicitly adds '"stream": False' to the payload.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.

        Returns:
            Dict: The JSON payload ready to be sent to the Ollama API.
        """
        self.set_gen_input()
        messages = self._build_messages_from_conversation(conversation, system_prompt, prompt)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "options": self.gen_input or {}
        }

        if not self.stream:
            payload["stream"] = False

        logger.info(f"Payload prepared for {self.__class__.__name__}")
        logger.debug(f"URL: {self.base_url}, Payload: {json.dumps(payload, indent=2)}")
        return payload

    def _build_messages_from_conversation(self,
                                          conversation: Optional[List[Dict[str, Any]]],
                                          system_prompt: Optional[str],
                                          prompt: Optional[str]) -> List[Dict[str, Any]]:
        """
        Constructs the message list, handling and embedding image data when present.

        This method overrides the base implementation to correctly format a
        conversation that includes images for the Ollama API. It identifies
        special messages with the role "images", extracts their content, and
        attaches this image data to the last user message in the history under
        the `images` key. This prepares the payload for a multimodal request.

        Args:
            conversation (Optional[List[Dict[str, Any]]]): The historical conversation,
                which may include dictionaries representing images.
            system_prompt (Optional[str]): The system prompt to guide the LLM's behavior.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            List[Dict[str, Any]]: The formatted list of messages, where the last
            user message may contain an `images` key with a list of image data.
        """
        if conversation is None:
            conversation = []
            if system_prompt:
                conversation.append({"role": "system", "content": system_prompt})
            if prompt:
                conversation.append({"role": "user", "content": prompt})

        corrected_conversation: List[Dict[str, Any]] = [
            {**msg, "role": "system" if msg["role"] == "systemMes" else msg["role"]}
            for msg in conversation
        ]

        # Extract image messages and remove them from the conversation
        image_contents = [msg["content"] for msg in corrected_conversation if msg["role"] == "images"]
        final_conversation = [msg for msg in corrected_conversation if msg["role"] != "images"]

        # If there are images, attach them to the last user message
        if image_contents:
            for msg in reversed(final_conversation):
                if msg["role"] == "user":
                    msg["images"] = image_contents
                    break

        # Remove empty trailing assistant messages
        if final_conversation and final_conversation[-1]["role"] == "assistant" and not final_conversation[-1].get(
                "content"):
            final_conversation.pop()

        return_brackets(final_conversation)

        full_prompt_log = "\n".join(
            str(msg.get("content", "")) for msg in final_conversation if msg.get("content")
        )
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\nFormatted_Prompt: %s", full_prompt_log)
        logger.info("\n*****************************************************************************\n\n")

        return final_conversation

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON object from the Ollama streaming response.

        Each line from the Ollama stream is a JSON string. This method loads
        that string and extracts the content token and finish reason.

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
            message = chunk_data.get("message", {})
            token = message.get("content", "")

            is_done = chunk_data.get("done", False)
            finish_reason = "stop" if is_done else None

            return {'token': token, 'finish_reason': finish_reason}
        except json.JSONDecodeError:
            logger.warning(f"Could not parse Ollama stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming Ollama API response.

        This method navigates the JSON structure of a complete Ollama response
        to find and return the main message content.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content, or an empty string if not found.
        """
        try:
            return response_json['message']['content'] or ""
        except (KeyError, IndexError, TypeError):
            logger.error(f"Could not find content in Ollama response: {response_json}")
            return ""