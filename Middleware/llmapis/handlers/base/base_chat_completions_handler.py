# middleware/llmapis/handlers/base/base_chat_completions_handler.py
import json
import logging
from typing import Dict, Optional, List

from Middleware.utilities.text_utils import return_brackets
from .base_llm_api_handler import LlmApiHandler

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

        # Get all config flags and text for prompt modifications
        add_start_system = self.endpoint_config.get("addTextToStartOfSystem", False)
        text_start_system = self.endpoint_config.get("textToAddToStartOfSystem", "")
        add_start_prompt = self.endpoint_config.get("addTextToStartOfPrompt", False)
        text_start_prompt = self.endpoint_config.get("textToAddToStartOfPrompt", "")

        add_completion_text = self.endpoint_config.get("addTextToStartOfCompletion", False)
        completion_text = self.endpoint_config.get("textToAddToStartOfCompletion", "")
        ensure_assistant = self.endpoint_config.get("ensureTextAddedToAssistantWhenChatCompletion", False)

        # 1. Apply text to start of the system message
        if add_start_system and text_start_system:
            system_msg_found = False
            for msg in corrected_conversation:
                if msg.get("role") == "system":
                    msg["content"] = text_start_system + msg.get("content", "")
                    system_msg_found = True
                    break
            if not system_msg_found:
                corrected_conversation.insert(0, {"role": "system", "content": text_start_system})

        # 2. Apply text to start of the last user message
        if add_start_prompt and text_start_prompt:
            last_user_idx = -1
            for i, msg in enumerate(corrected_conversation):
                if msg.get("role") == "user":
                    last_user_idx = i
            if last_user_idx != -1:
                corrected_conversation[last_user_idx]["content"] = text_start_prompt + corrected_conversation[
                    last_user_idx].get("content", "")
            else:
                corrected_conversation.append({"role": "user", "content": text_start_prompt})

        # 3. Apply text to the very end of the context (start of completion)
        if add_completion_text and completion_text:
            if not corrected_conversation:
                # If list is somehow empty, add an assistant message with the text
                corrected_conversation.append({"role": "assistant", "content": completion_text})
            elif ensure_assistant:
                # Override is ON: must end with an assistant turn.
                if corrected_conversation[-1].get("role") == "assistant":
                    corrected_conversation[-1]["content"] += completion_text
                else:
                    corrected_conversation.append({"role": "assistant", "content": completion_text})
            else:
                # Override is OFF: append to the content of the very last message.
                corrected_conversation[-1]["content"] += completion_text

        if corrected_conversation and corrected_conversation[-1]["role"] == "assistant" and corrected_conversation[-1][
            "content"] == "":
            corrected_conversation.pop()

        # Note: Image filtering is handled upstream in llm_api.py based on the llm_takes_images flag.
        # Handlers that support images (OpenAI, Ollama) override this method to process images.
        # Handlers that don't support images receive a pre-filtered conversation.

        return_brackets(corrected_conversation)

        full_prompt_log = "\n".join(msg["content"] for msg in corrected_conversation)
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\nFormatted_Prompt: %s", full_prompt_log)
        logger.info("\n*****************************************************************************\n\n")

        return corrected_conversation
