import json
import logging
import re
import time
import traceback
from typing import Dict, Generator, List, Optional

import requests

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import (
    get_is_chat_complete_add_user_assistant,
    get_is_chat_complete_add_missing_assistant, get_current_username
)
# New Imports for abstracted logic
from Middleware.utilities.streaming_utils import StreamingThinkRemover, remove_thinking_from_text
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
        Handle streaming response for Ollama API.
        """
        self.set_gen_input()

        corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

        url = f"{self.base_url}/api/chat"
        data = {
            "model": self.model_name,
            "messages": corrected_conversation,
            "options": self.gen_input or {}
        }

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        logger.info(f"Streaming flow!")
        logger.debug(f"Sending request to {url} with data: {json.dumps(data, indent=2)}")

        output_format = instance_utils.API_TYPE

        def generate_sse_stream():
            # Instantiate the remover class to handle thinking block logic
            remover = StreamingThinkRemover(self.endpoint_config)

            try:
                logger.info(f"Streaming flow!")
                logger.info(f"URL: {url}")
                logger.debug("Headers: ")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data: ")
                logger.debug(data)
                with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                    logger.info(f"Response status code: {r.status_code}")
                    first_chunk_buffer = ""
                    first_chunk_processed = False
                    max_buffer_length = 20
                    start_time = time.time()
                    total_tokens = 0

                    for line in r.iter_lines(decode_unicode=True):
                        if line.strip():
                            try:
                                chunk_data = json.loads(line.strip())
                                if "message" in chunk_data and "content" in chunk_data["message"]:
                                    content_delta = chunk_data["message"]["content"]
                                    finish_reason = chunk_data.get("done", False)

                                    # Process delta through the remover
                                    content_to_yield = remover.process_delta(content_delta)

                                    if content_to_yield:
                                        if not first_chunk_processed:
                                            first_chunk_buffer += content_to_yield

                                            if self.strip_start_stop_line_breaks:
                                                first_chunk_buffer = first_chunk_buffer.lstrip()

                                            if add_user_assistant and add_missing_assistant:
                                                if "Assistant:" in first_chunk_buffer:
                                                    first_chunk_buffer = api_utils.remove_assistant_prefix(
                                                        first_chunk_buffer)
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                else:
                                                    continue
                                            elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                                first_chunk_processed = True
                                                content = first_chunk_buffer
                                            else:
                                                continue
                                        else:
                                            content = content_to_yield

                                        total_tokens += len(content.split())
                                        completion_json = api_utils.build_response_json(
                                            token=content,
                                            finish_reason=None,
                                            current_username=get_current_username()
                                        )
                                        yield api_utils.sse_format(completion_json, output_format)

                                if chunk_data.get("done"):
                                    break

                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse JSON: {e}")
                                continue

                    # After loop, finalize the remover to flush any remaining buffer
                    final_content = remover.finalize()
                    if final_content:
                        # Run final content through the first_chunk logic if nothing has been processed yet
                        if not first_chunk_processed:
                            content = (first_chunk_buffer + final_content).lstrip()
                        else:
                            content = final_content
                        completion_json = api_utils.build_response_json(
                            token=content, finish_reason=None, current_username=get_current_username()
                        )
                        yield api_utils.sse_format(completion_json, output_format)

                    # Standard end-of-stream payloads
                    total_duration = int((time.time() - start_time) * 1e9)
                    final_completion_json = api_utils.build_response_json(
                        token="",
                        finish_reason="stop",
                        current_username=get_current_username(),
                    )
                    logger.debug("Total duration: %s", total_duration)
                    yield api_utils.sse_format(final_completion_json, output_format)

                    if output_format not in ('ollamagenerate', 'ollamaapichat'):
                        logger.info("End of stream reached, sending [DONE] signal.")
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

                        # Replaced complex logic with a single call to the abstracted function
                        result_text = remove_thinking_from_text(result_text, self.endpoint_config)

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