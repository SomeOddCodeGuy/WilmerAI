# middleware/llmapis/handlers/impl/ollama_chat_api_image_specific_handler.py
import logging
from typing import Dict, Any, Optional, List

from .ollama_chat_api_handler import OllamaChatHandler
from Middleware.utilities.text_utils import return_brackets

logger = logging.getLogger(__name__)


class OllamaApiChatImageSpecificHandler(OllamaChatHandler):
    """
    Extends `OllamaChatHandler` to support multimodal conversations including images.

    This specialized handler adapts the message-building process to accommodate
    image data. It intercepts messages with a role of "images", extracts the
    image content (e.g., base64 strings), and attaches them to the most recent
    user message in the conversation list, formatting the payload as required by
    the Ollama API for multimodal chat.
    """

    def _build_messages_from_conversation(self,
                                          conversation: Optional[List[Dict[str, Any]]],
                                          system_prompt: Optional[str],
                                          prompt: Optional[str]) -> List[Dict[str, Any]]:
        """
        Constructs the message list, additionally handling and embedding image data.

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

        image_contents = [msg["content"] for msg in corrected_conversation if msg["role"] == "images"]
        final_conversation = [msg for msg in corrected_conversation if msg["role"] != "images"]

        if image_contents:
            for msg in reversed(final_conversation):
                if msg["role"] == "user":
                    msg["images"] = image_contents
                    break

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