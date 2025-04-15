import json
import logging
import time
import traceback
from typing import Dict, Generator, List, Optional, Tuple

import requests

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.api_utils import handle_sse_and_json_stream
from Middleware.utilities.config_utils import (
    get_is_chat_complete_add_user_assistant,
    get_is_chat_complete_add_missing_assistant, get_current_username
)
from Middleware.utilities.text_utils import return_brackets_in_string
from .llm_api_handler import LlmApiHandler

logger = logging.getLogger(__name__)


class OpenAiCompletionsApiHandler(LlmApiHandler):
    """
    Handler for the OpenAI Completions API (v1/completions endpoint).
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for OpenAI Completions API using the common utility.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
                Not used in this API; prompt is constructed from system_prompt and prompt.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Yields:
            str: Server-Sent Event formatted strings.
        """
        self.set_gen_input()

        full_prompt = prep_full_prompt(system_prompt, prompt)

        url = f"{self.base_url}/v1/completions"
        data = {"prompt": full_prompt, "model": self.model_name, **(self.gen_input or {})}
        data['stream'] = True

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        logger.info(f"OpenAI Completions Streaming flow!")
        logger.info(f"URL: {url}")
        logger.debug(f"Headers: {self.headers}")
        logger.debug(f"Sending request with data: {repr(data)}")

        output_format = instance_utils.API_TYPE

        # Define the specific content extractor for OpenAI Completions API
        def extract_openai_completions_content(chunk_data: dict) -> Tuple[str, Optional[str]]:
            token = ""
            finish_reason = None
            if 'choices' in chunk_data and chunk_data['choices']:
                choice = chunk_data['choices'][0]
                token = choice.get("text", "") # Completions API uses 'text'
                finish_reason = choice.get("finish_reason")
            return token, finish_reason

        try:
            logger.info(f"Initiating streaming request to {url}")
            with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                logger.info(f"Response status code: {r.status_code}")
                r.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

                # Use the utility function with the specific extractor
                yield from handle_sse_and_json_stream(
                    response=r,
                    extract_content_callback=extract_openai_completions_content,
                    output_format=output_format,
                    strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                    add_user_assistant=add_user_assistant,
                    add_missing_assistant=add_missing_assistant
                    # max_buffer_length can use default or be passed if needed
                )

        except requests.RequestException as e:
            logger.error(f"Request failed during OpenAI Completions streaming: {e}")
            logger.error(traceback.format_exc())
            # Yield an error message in SSE format
            error_json = api_utils.build_response_json(
                token=f"Error communicating with API: {e}",
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_format)
            # Also send DONE signal after error if necessary
            if output_format not in ('ollamagenerate', 'ollamaapichat'):
                yield api_utils.sse_format("[DONE]", output_format)

        except Exception as e:
            logger.error(f"An unexpected error occurred during OpenAI Completions streaming: {e}")
            logger.error(traceback.format_exc())
            # Yield an error message in SSE format
            error_json = api_utils.build_response_json(
                token=f"An unexpected error occurred: {e}",
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_format)
            # Also send DONE signal after error
            if output_format not in ('ollamagenerate', 'ollamaapichat'):
                yield api_utils.sse_format("[DONE]", output_format)

    def handle_non_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> str:
        """
        Handle non-streaming response for OpenAI Completions API.

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

        url = f"{self.base_url}/v1/completions"
        data = {"prompt": full_prompt, "model": self.model_name, **(self.gen_input or {})}

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"OpenAI Completions Non-Streaming flow! Attempt: {attempt + 1}")
                logger.info(f"URL: {url}")
                logger.debug("Headers:")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data:")
                logger.debug(json.dumps(data, indent=2))
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()

                payload = response.json()

                if 'choices' in payload and payload['choices'][0] and 'text' in payload['choices'][0]:
                    result_text = payload['choices'][0]['text']

                    if self.strip_start_stop_line_breaks:
                        result_text = result_text.lstrip()

                    if "Assistant:" in result_text:
                        result_text = api_utils.remove_assistant_prefix(result_text)

                    logger.info("\n\n*****************************************************************************\n")
                    logger.info("\n\nOutput from the LLM: %s", result_text)
                    logger.info("\n*****************************************************************************\n\n")

                    return result_text
                elif 'content' in payload:
                    result_text = payload['content']
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