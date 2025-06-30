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
# New Imports for abstracted logic
from Middleware.utilities.streaming_utils import StreamingThinkRemover, remove_thinking_from_text
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
            # Instantiate the remover class to handle all thinking block logic
            remover = StreamingThinkRemover(self.endpoint_config)

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
                            continue

                        try:
                            chunk_data = json.loads(line.strip())
                            token_from_llm = chunk_data.get('response', '')
                            finish_reason = chunk_data.get("done")

                            # Process the raw token through the remover
                            content_to_process = remover.process_delta(token_from_llm)

                            if not content_to_process and not finish_reason:
                                continue

                            # Feed the processed content into the prefix-stripping logic
                            token = ""
                            if not first_chunk_processed:
                                first_chunk_buffer += content_to_process

                                if self.strip_start_stop_line_breaks:
                                    first_chunk_buffer = first_chunk_buffer.lstrip()

                                if add_user_assistant and add_missing_assistant:
                                    if "Assistant:" in first_chunk_buffer:
                                        first_chunk_buffer = api_utils.remove_assistant_prefix(first_chunk_buffer)
                                        first_chunk_processed = True
                                        token = first_chunk_buffer
                                    elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                        first_chunk_processed = True
                                        token = first_chunk_buffer
                                    else:
                                        continue
                                elif len(first_chunk_buffer) > max_buffer_length or finish_reason:
                                    first_chunk_processed = True
                                    token = first_chunk_buffer
                                else:
                                    continue
                            else:
                                token = content_to_process

                            if self.strip_start_stop_line_breaks and not finish_reason:
                                token = token.rstrip("\n")

                            total_tokens += len(token.split())
                            completion_json = api_utils.build_response_json(
                                token=token,
                                finish_reason=None,
                                current_username=get_current_username()
                            )
                            yield api_utils.sse_format(completion_json, output_format)

                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse JSON: {e}")
                            continue

                    # After loop, finalize the remover to flush any remaining buffer
                    final_content = remover.finalize()
                    if final_content:
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