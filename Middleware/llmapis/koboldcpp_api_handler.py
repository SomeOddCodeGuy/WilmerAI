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


class KoboldCppApiHandler(LlmApiHandler):
    """
    Handler for the KoboldCpp API.
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for KoboldCpp API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            Generator[str, None, None]: A generator yielding chunks of the response.
        """
        self.set_gen_input()

        full_prompt = prep_full_prompt(system_prompt, prompt)

        url = f"{self.base_url}/api/extra/generate/stream"
        data = {"prompt": full_prompt, **(self.gen_input or {})}

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        logger.info(f"KoboldCpp Streaming flow!")
        logger.info(f"URL: {url}")
        logger.info(f"Headers: {self.headers}")
        logger.info(f"Sending request with data: {json.dumps(data, indent=2)}")

        output_format = instance_utils.API_TYPE

        def generate_sse_stream():
            try:
                with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                    logger.info(f"Response status code: {r.status_code}")
                    buffer = ""
                    first_chunk_buffer = ""
                    first_chunk_processed = False
                    max_buffer_length = 20
                    start_time = time.time()
                    total_tokens = 0

                    # Variables to track the current event type
                    current_event = None

                    for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()

                            if line.startswith("event:"):
                                # Extract the event type
                                current_event = line[len("event:"):].strip()
                                continue  # Move to the next line

                            if line.startswith("data:"):
                                data_str = line[len("data:"):].strip()
                                if current_event == "message":
                                    try:
                                        if data_str == '[DONE]':
                                            break
                                        chunk_data = json.loads(data_str)

                                        token = chunk_data.get("token", "")
                                        finish_reason = chunk_data.get("finish_reason", "")

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

                                        total_tokens += len(token.split())

                                        completion_json = api_utils.build_response_json(
                                            token=token,
                                            finish_reason=None,  # Don't add "stop" or "done" yet
                                            current_username=get_current_username()
                                        )

                                        yield api_utils.sse_format(completion_json, output_format)

                                        if finish_reason == "stop":
                                            break

                                    except json.JSONDecodeError as e:
                                        logger.warning(f"Failed to parse JSON: {e}")
                                        continue

                    total_duration = int((time.time() - start_time) * 1e9)

                    # Send the final payload with "done" and "stop"
                    final_completion_json = api_utils.build_response_json(
                        token="",
                        finish_reason="stop",
                        current_username=get_current_username(),
                    )
                    logger.debug("Total duration: {}", total_duration)
                    yield api_utils.sse_format(final_completion_json, output_format)

                    if output_format not in ('ollamagenerate', 'ollamaapichat'):
                        logger.debug("End of stream reached, sending [DONE] signal.")
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
        Handle non-streaming response for KoboldCpp API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            str: The complete response as a string.
        """
        self.set_gen_input()

        full_prompt = prep_full_prompt(system_prompt, prompt)

        url = f"{self.base_url}/api/v1/generate"
        data = {"prompt": full_prompt, **(self.gen_input or {})}

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"KoboldCpp Non-Streaming flow! Attempt: {attempt + 1}")
                logger.info(f"URL: {url}")
                logger.debug("Headers: ")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data: ")
                logger.debug(json.dumps(data, indent=2))
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()

                payload = response.json()
                logger.debug("Response: %s", response)
                logger.debug("Payload: %s", json.dumps(payload, indent=2))

                if 'results' in payload and len(payload['results']) > 0 and 'text' in payload['results'][0]:
                    result_text = payload['results'][0]['text']

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
        if self.stream_property_name:
            self.gen_input[self.stream_property_name] = self.stream
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