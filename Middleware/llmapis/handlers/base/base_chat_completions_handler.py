# middleware/llmapis/handlers/base/base_chat_completions_handler.py
import json
import logging
from typing import Dict, Optional, List

from .base_llm_api_handler import LlmApiHandler
from Middleware.utilities.text_utils import return_brackets

logger = logging.getLogger(__name__)


class BaseChatCompletionsHandler(LlmApiHandler):
    """
    Abstract base class for handlers that send a list of messages
    to a '/chat/completions' style endpoint.
    """

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the final data payload for the API request.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The historical conversation, a list of message dictionaries.
            system_prompt (Optional[str]): The system prompt to guide the LLM's behavior.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            Dict: The payload dictionary ready to be sent to the LLM API.
        """
        self.set_gen_input()

        messages = self._build_messages_from_conversation(conversation, system_prompt, prompt)

        payload = {
            **({"model": self.model_name} if not self.dont_include_model else {}),
            "messages": messages,
            **(self.gen_input or {})
        }

        logger.info(f"Payload prepared for {self.__class__.__name__}")
        logger.debug(f"URL: {self.base_url}, Payload: {json.dumps(payload, indent=2)}")
        return payload

    def _build_messages_from_conversation(self, conversation: Optional[List[Dict[str, str]]],
                                          system_prompt: Optional[str], prompt: Optional[str]) -> List[Dict[str, str]]:
        """
        Constructs and sanitizes the list of messages from the conversation history, system prompt, and user prompt.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The historical conversation, a list of message dictionaries.
            system_prompt (Optional[str]): The system prompt to guide the LLM's behavior.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            List[Dict[str, str]]: The formatted and cleaned list of messages for the API payload.
        """
        if conversation is None:
            conversation = []
            if system_prompt:
                conversation.append({"role": "system", "content": system_prompt})
            if prompt:
                conversation.append({"role": "user", "content": prompt})

        corrected_conversation = [
            {**msg, "role": "system" if msg["role"] == "systemMes" else msg["role"]}
            for msg in conversation
        ]

        if corrected_conversation and corrected_conversation[-1]["role"] == "assistant" and corrected_conversation[-1][
            "content"] == "":
            corrected_conversation.pop()

        if corrected_conversation:
            corrected_conversation = [item for item in corrected_conversation if item["role"] != "images"]

        return_brackets(corrected_conversation)

        full_prompt_log = "\n".join(msg["content"] for msg in corrected_conversation)
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\nFormatted_Prompt: %s", full_prompt_log)
        logger.info("\n*****************************************************************************\n\n")

        return corrected_conversation