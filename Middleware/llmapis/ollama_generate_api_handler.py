import json
import logging
import time
import traceback
from typing import Dict, Generator, List, Optional

import requests

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import (
    get_is_chat_complete_add_user_assistant,
    get_is_chat_complete_add_missing_assistant, get_current_username
)
from Middleware.utilities.text_utils import return_brackets_in_string
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
        Handle streaming response for Ollama API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
                Not used in this API; prompt is constructed from system_prompt and prompt.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            Generator[str, None, None]: A generator yielding chunks of the response.
        """
        self.set_gen_input()

        full_prompt = prep_full_prompt(system_prompt, prompt)

        url = f"{self.base_url}/api/generate"
        data = {"model": self.model_name, "prompt": full_prompt, "stream": True,
                "raw": True, "options": self.gen_input or {}}

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        logger.info(f"Ollama Streaming flow!")
        logger.info(f"URL: {url}")
        logger.debug(f"Headers: {self.headers}")
        logger.debug(f"Sending request with data: {json.dumps(data, indent=2)}")

        output_format = instance_utils.API_TYPE

        def generate_sse_stream():
            try:
                with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                    logger.info(f"Response status code: {r.status_code}")
                    first_chunk_buffer = ""
                    first_chunk_processed = False
                    max_buffer_length = 20
                    start_time = time.time()
                    total_tokens = 0

                    for line in r.iter_lines(decode_unicode=True):
                        if not line.strip():
                            continue  # Skip empty lines

                        try:
                            chunk_data = json.loads(line.strip())
                            token = ""
                            finish_reason = None  # Default to None for intermediate payloads

                            # Extract token and finish_reason
                            if 'response' in chunk_data:
                                token = chunk_data['response']
                            finish_reason = chunk_data.get("done")

                            if not first_chunk_processed:
                                first_chunk_buffer += token

                                if self.strip_start_stop_line_breaks:
                                    first_chunk_buffer = first_chunk_buffer.lstrip()

                                if add_user_assistant and add_missing_assistant:
                                    # Check for "Assistant:" in the full buffer
                                    if "Assistant:" in first_chunk_buffer:
                                        # If it starts with "Assistant:", strip it
                                        first_chunk_buffer = api_utils.remove_assistant_prefix(
                                            first_chunk_buffer)
                                        # Mark as processed since we've handled the prefix
                                        first_chunk_processed = True
                                        token = first_chunk_buffer
                                    elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                        # If buffer is too large or stream finishes, pass it as is
                                        first_chunk_processed = True
                                        token = first_chunk_buffer
                                    else:
                                        # Keep buffering until we have more tokens
                                        continue
                                elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                    # If buffer is too large or stream finishes, pass it as is
                                    first_chunk_processed = True
                                    token = first_chunk_buffer
                                else:
                                    # Keep buffering until we have more tokens
                                    continue

                            # Handle stripping newlines
                            if self.strip_start_stop_line_breaks and not finish_reason:
                                token = token.rstrip("\n")

                            total_tokens += len(token.split())

                            # Generate response using ResponseBuilder
                            completion_json = api_utils.build_response_json(
                                token=token,
                                finish_reason=None,  # Intermediate payloads don't include "stop" or "done"
                                current_username=get_current_username()
                            )

                            yield api_utils.sse_format(completion_json, output_format)

                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse JSON: {e}")
                            continue

                    # Final message signaling end of stream
                    total_duration = int((time.time() - start_time) * 1e9)

                    final_completion_json = api_utils.build_response_json(
                        token="",
                        finish_reason="stop",  # Final payload explicitly includes "stop"
                        current_username=get_current_username()
                    )
                    logger.debug("Total duration: {}", total_duration)
                    yield api_utils.sse_format(final_completion_json, output_format)

                    if output_format not in ('ollamagenerate', 'ollamaapichat'):
                        logger.warning("End of stream reached, sending [DONE] signal.")
                        yield api_utils.sse_format("[DONE]", output_format)

            except requests.RequestException as e:
                logger.warning(f"Request failed: {e}")
                raise

        return generate_sse_stream()

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