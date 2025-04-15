import json
import logging
import time
import traceback
from typing import Dict, Generator, List, Optional, Tuple

import requests

from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.api_utils import handle_sse_and_json_stream, extract_openai_chat_content
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
        Handle streaming response for OpenAI API using the common utility.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Yields:
            str: Server-Sent Event formatted strings.
        """
        self.set_gen_input()

        corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

        url = f"{self.base_url}/v1/chat/completions"
        data = {"model": self.model_name, "messages": corrected_conversation, **(self.gen_input or {})}
        data['stream'] = True

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        logger.info(f"OpenAI Chat Completions Streaming flow!")
        logger.info(f"URL: {url}")
        logger.debug(f"Headers: {self.headers}")
        logger.debug(f"Sending request with data: {repr(data)}")

        output_format = instance_utils.API_TYPE
        logger.info(f"Instance API_TYPE for SSE formatting: {output_format}")

        try:
            logger.info(f"Initiating streaming request to {url}")
            with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                logger.info(f"Response status code: {r.status_code}")
                r.raise_for_status()

                yield from handle_sse_and_json_stream(
                    response=r,
                    extract_content_callback=extract_openai_chat_content,
                    output_format=output_format,
                    strip_start_stop_line_breaks=self.strip_start_stop_line_breaks,
                    add_user_assistant=add_user_assistant,
                    add_missing_assistant=add_missing_assistant
                )

        except requests.RequestException as e:
            logger.error(f"Request failed during OpenAI streaming: {e}")
            logger.error(traceback.format_exc())
            error_json = api_utils.build_response_json(
                token=f"Error communicating with API: {e}",
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_format)
            if output_format not in ('ollamagenerate', 'ollamaapichat'):
                yield api_utils.sse_format("[DONE]", output_format)

        except Exception as e:
            logger.error(f"An unexpected error occurred during OpenAI streaming: {e}")
            logger.error(traceback.format_exc())
            error_json = api_utils.build_response_json(
                token=f"An unexpected error occurred: {e}",
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_format)
            if output_format not in ('ollamagenerate', 'ollamaapichat'):
                yield api_utils.sse_format("[DONE]", output_format)

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
        delay: int = 1  # Initial delay in seconds
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
                logger.info(f"Waiting {delay} seconds before next attempt...")
                time.sleep(delay)  # Wait before the next retry attempt
                delay *= 2  # Exponential backoff
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