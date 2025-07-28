# middleware/llmapis/handlers/base/base_completions_handler.py

import json
import logging
from typing import Dict, Optional, List

from .base_llm_api_handler import LlmApiHandler
from Middleware.utilities.text_utils import return_brackets_in_string

logger = logging.getLogger(__name__)


class BaseCompletionsHandler(LlmApiHandler):
    """
    Abstract base class for handlers that send a single string prompt
    to a '/completions' or '/generate' style endpoint.
    """

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the final data payload for the API request.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The historical conversation (unused in this handler).
            system_prompt (Optional[str]): The system prompt to guide the LLM's behavior.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            Dict: The dictionary payload ready for the API request.
        """
        self.set_gen_input()

        full_prompt = self._build_prompt_from_conversation(system_prompt, prompt)

        # Get config for appending text to the end of the final prompt
        add_completion_text = self.endpoint_config.get("addTextToStartOfCompletion", False)
        completion_text = self.endpoint_config.get("textToAddToStartOfCompletion", "")

        # Append the text if configured. This happens at the last possible moment.
        if add_completion_text and completion_text:
            full_prompt += completion_text

        # Log the final, fully-formed prompt before creating the payload
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\nFormatted_Prompt: %s", full_prompt)
        logger.info("\n*****************************************************************************\n\n")

        payload = {
            "prompt": full_prompt,
            **(self.gen_input or {})
        }

        logger.info(f"Payload prepared for {self.__class__.__name__}")
        logger.debug(f"URL: {self.base_url}, Payload: {json.dumps(payload, indent=2)}")
        return payload

    def _build_prompt_from_conversation(self, system_prompt: Optional[str], prompt: Optional[str]) -> str:
        """
        Constructs a single string prompt from system and user prompts.

        Args:
            system_prompt (Optional[str]): The system prompt to guide the LLM's behavior.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            str: The combined and formatted single-string prompt.
        """
        if system_prompt is None:
            system_prompt = ""
        if prompt is None:
            prompt = ""

        # The logic from LlmApiService for adding text to the start of prompts has already run
        full_prompt = (system_prompt + prompt).strip()
        full_prompt = return_brackets_in_string(full_prompt)
        full_prompt = full_prompt.strip()

        # Logging was moved to _prepare_payload to show the final prompt
        return full_prompt