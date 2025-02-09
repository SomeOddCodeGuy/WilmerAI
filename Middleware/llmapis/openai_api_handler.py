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
from .llm_api_handler import LlmApiHandler

logger = logging.getLogger(__name__)


class OpenAiApiHandler(LlmApiHandler):
    """
    Handler for the OpenAI API.
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for OpenAI API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            Generator[str, None, None]: A generator yielding chunks of the response.
        """
        self.set_gen_input()

        corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

        url = f"{self.base_url}/v1/chat/completions"
        data = {"model": self.model_name, "messages": corrected_conversation, **(self.gen_input or {})}

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        logger.info(f"OpenAI Chat Completions Streaming flow!")
        logger.info(f"URL: {url}")
        logger.debug(f"Headers: {self.headers}")
        logger.debug(f"Sending request with data: {json.dumps(data, indent=2)}")

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

                    for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                        buffer += chunk
                        while "data:" in buffer:
                            data_pos = buffer.find("data:")
                            end_pos = buffer.find("\n", data_pos)
                            if end_pos == -1:
                                break
                            data_str = buffer[data_pos + 5:end_pos].strip()
                            buffer = buffer[end_pos + 1:]
                            try:
                                if data_str == '[DONE]':
                                    break
                                chunk_data = json.loads(data_str)
                                for choice in chunk_data.get("choices", []):
                                    if "delta" in choice:
                                        content = choice["delta"].get("content", "")
                                        finish_reason = choice.get("finish_reason", "")

                                        if not first_chunk_processed:
                                            first_chunk_buffer += content

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
                                                    content = first_chunk_buffer
                                                elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                                    # If buffer is too large or stream finishes, pass it as is
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                else:
                                                    # Keep buffering until we have more tokens
                                                    continue
                                            elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                                # If buffer is too large or stream finishes, pass it as is
                                                first_chunk_processed = True
                                                content = first_chunk_buffer
                                            else:
                                                # Keep buffering until we have more tokens
                                                continue

                                        total_tokens += len(content.split())

                                        completion_json = api_utils.build_response_json(
                                            token=content,
                                            finish_reason=None,  # Don't add "stop" or "done" yet
                                            current_username=get_current_username()
                                        )

                                        yield api_utils.sse_format(completion_json, output_format)

                                if chunk_data.get("done_reason") == "stop" or chunk_data.get("done"):
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
                logger.info(f"Request failed: {e}")
                raise

        return generate_sse_stream()

    def handle_non_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> str:
        """
        Handle non-streaming response for OpenAI API.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            str: The complete response as a string.
        """
        self.set_gen_input()

        corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

        url = f"{self.base_url}/v1/chat/completions"
        data = {"model": self.model_name, "stream": False, "messages": corrected_conversation, **(self.gen_input or {})}

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"OpenAI Chat Completions Non-Streaming flow! Attempt: {attempt + 1}")
                logger.info(f"URL: {url}")
                logger.debug("Headers:")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data:")
                logger.debug(json.dumps(data, indent=2))
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()
                payload = response.json()
                if 'choices' in payload and payload['choices'][0] and 'message' in payload['choices'][
                    0] and 'content' in payload['choices'][0]['message']:
                    result_text = payload['choices'][0]['message']['content']
                    if result_text is None or result_text == '':
                        result_text = payload.get('content', '')

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
        if self.stream_property_name:
            self.gen_input[self.stream_property_name] = self.stream
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