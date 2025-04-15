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
from Middleware.utilities.text_utils import return_brackets_in_string
from Middleware.utilities.api_utils import handle_sse_and_json_stream
from .llm_api_handler import LlmApiHandler

logger = logging.getLogger(__name__)


class OllamaGenerateHandler(LlmApiHandler):
    """
    Handler for the Ollama API (api/generate endpoint).
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for Ollama Generate API using the common utility.

        Args:
            conversation (Optional[List[Dict[str, str]]]): Not used.
            system_prompt (Optional[str]): System prompt.
            prompt (Optional[str]): User prompt.

        Yields:
            str: Server-Sent Event formatted strings.
        """
        self.set_gen_input()

        full_prompt = prep_full_prompt(system_prompt, prompt)

        url = f"{self.base_url}/api/generate"
        data = {"model": self.model_name, "prompt": full_prompt, "stream": True,
                "raw": True, "options": self.gen_input or {}}

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        # This handler always produces Ollama Generate format
        output_api_type = "ollamagenerate"
        logger.info(f"Ollama Generate Streaming flow! Formatting as: {output_api_type}")
        logger.info(f"URL: {url}")
        logger.debug(f"Headers: {self.headers}")
        logger.debug(f"Sending request with data: {json.dumps(data, indent=2)}")

        def extract_ollama_generate_content(chunk_data: dict) -> Tuple[str, Optional[str]]:
            token = chunk_data.get("response", "")
            finish_reason = None
            if chunk_data.get("done") == True:
                pass
            return token, None

        try:
            logger.info(f"Initiating streaming request to {url}")
            with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                logger.info(f"Response status code: {r.status_code}")
                r.raise_for_status()

                yield from handle_sse_and_json_stream(
                    response=r,
                    extract_content_callback=extract_ollama_generate_content,
                    intended_api_type=output_api_type,
                    strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                    add_user_assistant=add_user_assistant,
                    add_missing_assistant=add_missing_assistant
                )

        except requests.RequestException as e:
            logger.warning(f"Request failed: {e}")
            error_json = api_utils.build_response_json(
                token=f"Error communicating with API: {e}",
                api_type=output_api_type,
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_api_type)
            if output_api_type not in ('ollamagenerate', 'ollamaapichat'):
                yield api_utils.sse_format("[DONE]", output_api_type)

        except Exception as e:
            logger.error("Unexpected error: %s", e)
            traceback.print_exc()
            error_json = api_utils.build_response_json(
                token=f"An unexpected error occurred: {e}",
                api_type=output_api_type,
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_api_type)
            if output_api_type not in ('ollamagenerate', 'ollamaapichat'):
                yield api_utils.sse_format("[DONE]", output_api_type)

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
                Not used in this API; prompt is constructed from system_prompt and prompt.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            str: The complete response as a string.
        """
        self.set_gen_input()

        full_prompt = prep_full_prompt(system_prompt, prompt)

        url = f"{self.base_url}/api/generate"
        data = {"model": self.model_name, "prompt": full_prompt, "stream": False,
                "options": self.gen_input or {}}

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"Ollama Non-Streaming flow! Attempt: {attempt + 1}")
                logger.info(f"URL: {url}")
                logger.debug("Headers:")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data:")
                logger.debug(json.dumps(data, indent=2))
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()

                payload = response.json()
                logger.debug("Response: %s", response)
                logger.debug("Payload: %s", json.dumps(payload, indent=2))

                if 'response' in payload:
                    result_text = payload['response']

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
                traceback.print_exc()
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


def prep_full_prompt(system_prompt, prompt):
    if system_prompt is None:
        system_prompt = ""
    if prompt is None:
        prompt = ""
    full_prompt = (system_prompt + prompt).strip()
    full_prompt = return_brackets_in_string(full_prompt)
    full_prompt = full_prompt.strip()

    logger.info("\n\n*****************************************************************************\n")
    logger.info("\n\nFormatted_Prompt: %s", full_prompt)
    logger.info("\n*****************************************************************************\n\n")

    return full_prompt