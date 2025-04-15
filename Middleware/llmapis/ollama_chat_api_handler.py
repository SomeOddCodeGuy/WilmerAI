import json
import logging
import time
import traceback
from typing import Dict, Generator, List, Optional, Tuple

import requests

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import (
    get_is_chat_complete_add_user_assistant,
    get_is_chat_complete_add_missing_assistant, get_current_username
)
from Middleware.utilities.api_utils import handle_sse_and_json_stream
from .llm_api_handler import LlmApiHandler

logger = logging.getLogger(__name__)


class OllamaChatHandler(LlmApiHandler):
    """
    Handler for the Ollama API.
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for Ollama API using the common utility.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Yields:
            str: Server-Sent Event formatted strings.
        """
        self.set_gen_input()

        corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model_name,
            "messages": corrected_conversation,
            "stream": True,
            "options": self.gen_input or {}
        }

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        # Capture the intended API type for this request context
        request_api_type = instance_utils.API_TYPE
        logger.info(f"Ollama Chat Streaming flow! API Type: {request_api_type}")
        logger.debug(f"Sending request to {url} with data: {json.dumps(data, indent=2)}")

        # Define the specific content extractor for Ollama Chat API
        def extract_ollama_chat_content(chunk_data: dict) -> Tuple[str, Optional[str]]:
            token = ""
            finish_reason = None
            if 'message' in chunk_data and isinstance(chunk_data['message'], dict):
                token = chunk_data['message'].get("content", "")
            if chunk_data.get("done") == True:
                # Although 'done' signifies the end, we let the main loop handle the final payload
                # We don't return 'stop' here as finish_reason, handle_sse_and_json_stream checks for it
                pass
            return token, None

        try:
            logger.info(f"Initiating streaming request to {url}")
            with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                logger.info(f"Response status code: {r.status_code}")
                r.raise_for_status()

                # Use the utility function with the specific extractor
                yield from handle_sse_and_json_stream(
                    response=r,
                    extract_content_callback=extract_ollama_chat_content,
                    intended_api_type=request_api_type,
                    strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                    add_user_assistant=add_user_assistant,
                    add_missing_assistant=add_missing_assistant
                )

        except requests.RequestException as e:
            logger.error(f"Request failed during Ollama Chat streaming: {e}")
            logger.error(traceback.format_exc())
            error_json = api_utils.build_response_json(
                token=f"Error communicating with API: {e}",
                api_type=request_api_type,
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, request_api_type)

        except Exception as e:
            logger.error(f"An unexpected error occurred during Ollama Chat streaming: {e}")
            logger.error(traceback.format_exc())
            error_json = api_utils.build_response_json(
                token=f"An unexpected error occurred: {e}",
                api_type=request_api_type,
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, request_api_type)

    def handle_non_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> str:
        """
        Handle non-streaming response for Ollama API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            str: The complete response as a string.
        """
        self.set_gen_input()

        corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model_name,
            "messages": corrected_conversation,
            "stream": False,
            "options": self.gen_input or {}
        }

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"Non-Streaming flow! Attempt: {attempt + 1}")
                logger.info(f"URL: {url}")
                logger.debug("Headers: ")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data: ")
                logger.debug(data)
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                logger.debug("Response:")
                logger.debug(response.text)
                response.raise_for_status()
                payload = response.json()
                result_text = ""
                if 'message' in payload:
                    message = payload['message']
                    if message is not None:
                        result_text = message.get('content', '')

                        if self.strip_start_stop_line_breaks:
                            result_text = result_text.lstrip()

                        if "Assistant:" in result_text:
                            result_text = api_utils.remove_assistant_prefix(result_text)

                    logger.info("\n\n*****************************************************************************\n")
                    logger.info("\n\nOutput from the LLM: %s", result_text)
                    logger.info("\n*****************************************************************************\n\n")

                    return result_text
                else:
                    return ''
            except requests.exceptions.RequestException as e:
                logger.error(f"Attempt {attempt + 1} failed with error: {e}")
                if attempt == retries - 1:
                    raise
            except Exception as e:
                logger.error("Unexpected error: %s", e)
                traceback.print_exc()
                raise

    def set_gen_input(self):
        if self.truncate_property_name:
            self.gen_input[self.truncate_property_name] = self.endpoint_config.get("maxContextTokenSize", None)
        if self.max_token_property_name:
            self.gen_input[self.max_token_property_name] = self.max_tokens


def prep_corrected_conversation(conversation, system_prompt, prompt):
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

    full_prompt = "\n".join(msg["content"] for msg in corrected_conversation)
    logger.info("\n\n*****************************************************************************\n")
    logger.info("\n\nFormatted_Prompt: %s", full_prompt)
    logger.info("\n*****************************************************************************\n\n")

    return corrected_conversation