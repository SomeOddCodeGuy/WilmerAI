import base64
import binascii
import io
import json
import logging
import os
import re
import time
import traceback
from copy import deepcopy
from typing import Dict, Generator, List, Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from Middleware.utilities import api_utils, instance_utils
# New Imports for abstracted logic
from Middleware.utilities.streaming_utils import StreamingThinkRemover, remove_thinking_from_text
from .llm_api_handler import LlmApiHandler
from ..utilities.config_utils import get_current_username, get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from ..utilities.text_utils import return_brackets

logger = logging.getLogger(__name__)


class OpenAIApiChatImageSpecificHandler(LlmApiHandler):
    """
    Handler for the OpenAI Image Specific API Handler. This only is for sending images as a node in workflows.
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for OpenAI API with image support.
        """
        self.set_gen_input()

        try:
            corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

            logger.debug("Formatted conversation with images:")
            for msg in corrected_conversation:
                if isinstance(msg.get("content"), list):
                    logger.debug(f"Message role: {msg['role']}")
                    text_items = [item for item in msg['content'] if item.get('type') == 'text']
                    logger.debug(f"Text content: {text_items}")
                    image_count = len([item for item in msg['content'] if item.get('type') == 'image_url'])
                    logger.debug(f"Number of images: {image_count}")
                else:
                    logger.debug(f"Message role: {msg['role']}, content: {msg.get('content', '')[:100]}...")
        except Exception as e:
            logger.error(f"Error preprocessing images: {e}")
            logger.error(traceback.format_exc())
            # Create a fallback conversation if preprocessing fails
            corrected_conversation = []
            if system_prompt:
                corrected_conversation.append({"role": "system", "content": system_prompt})

            if conversation:
                for msg in conversation:
                    if msg["role"] != "images":
                        corrected_conversation.append(msg)

            if prompt:
                corrected_conversation.append({"role": "user", "content": prompt})
            elif not any(msg["role"] == "user" for msg in corrected_conversation):
                corrected_conversation.append({
                    "role": "user",
                    "content": "There was an error processing the image. Please provide assistance without the image and state that you are unable to process the image."
                })

        url = f"{self.base_url}/v1/chat/completions"
        data = {
            **({"model": self.model_name} if not self.dont_include_model else {}),
            "messages": corrected_conversation,
            "stream": True,
            **(self.gen_input or {})
        }

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        logger.info(f"OpenAI Chat Completions with Image Streaming flow!")
        logger.debug(f"Sending request to {url} with data: {json.dumps(data, indent=2)}")

        output_format = instance_utils.API_TYPE

        def generate_sse_stream():
            # Instantiate the remover class to handle thinking block logic
            remover = StreamingThinkRemover(self.endpoint_config)

            try:
                with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                    logger.info(f"Response status code: {r.status_code}")
                    r.encoding = "utf-8"
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
                                    content_delta = choice.get("delta", {}).get("content", "")
                                    finish_reason = choice.get("finish_reason", "")

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

                                if chunk_data.get("done_reason") == "stop" or chunk_data.get("done"):
                                    break

                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse JSON: {e}")
                                continue
                            except Exception as e:
                                logger.error(f"Error during streaming processing: {e}", exc_info=True)
                                error_token = f"Error during streaming processing: {e}"
                                error_json = api_utils.build_response_json(
                                    token=error_token, finish_reason="stop", current_username=get_current_username()
                                )
                                yield api_utils.sse_format(error_json, output_format)
                                raise StopIteration

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

                    total_duration = int((time.time() - start_time) * 1e9)
                    final_completion_json = api_utils.build_response_json(
                        token="", finish_reason="stop", current_username=get_current_username()
                    )
                    logger.debug("Total duration: %s", total_duration)
                    yield api_utils.sse_format(final_completion_json, output_format)

                    logger.info("End of stream reached, sending [DONE] signal.")
                    yield api_utils.sse_format("[DONE]", output_format)

            except requests.RequestException as e:
                logger.warning(f"Request failed: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error during streaming request setup or iteration: {e}", exc_info=True)
                try:
                    error_token = f"Error during streaming processing: {e}"
                    error_json = api_utils.build_response_json(
                        token=error_token, finish_reason="stop", current_username=get_current_username()
                    )
                    yield api_utils.sse_format(error_json, output_format)
                except Exception as inner_e:
                    logger.error(f"Failed to yield formatted error message: {inner_e}")
                raise StopIteration from e

        return generate_sse_stream()

    def handle_non_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None
    ) -> str:
        """
        Handle non-streaming response for OpenAI API with image support.
        """
        self.set_gen_input()

        try:
            corrected_conversation = prep_corrected_conversation(conversation, system_prompt, prompt)

            # Log the formatted conversation for debugging (excluding actual image data)
            logger.debug("Formatted conversation with images:")
            for msg in corrected_conversation:
                if isinstance(msg.get("content"), list):
                    # This is a message with images
                    logger.debug(f"Message role: {msg['role']}")
                    text_items = [item for item in msg['content'] if item.get('type') == 'text']
                    logger.debug(f"Text content: {text_items}")
                    image_count = len([item for item in msg['content'] if item.get('type') == 'image_url'])
                    logger.debug(f"Number of images: {image_count}")
                else:
                    logger.debug(f"Message role: {msg['role']}, content: {msg.get('content', '')[:100]}...")
        except Exception as e:
            logger.error(f"Error preprocessing images: {e}")
            logger.error(traceback.format_exc())
            # Create a fallback conversation
            corrected_conversation = []
            if system_prompt:
                corrected_conversation.append({"role": "system", "content": system_prompt})
            if conversation:
                for msg in conversation:
                    if msg["role"] != "images":
                        corrected_conversation.append(msg)
            if prompt:
                corrected_conversation.append({"role": "user", "content": prompt})
            elif not any(msg["role"] == "user" for msg in corrected_conversation):
                corrected_conversation.append({
                    "role": "user",
                    "content": "There was an error processing the image. Please provide assistance without the image and state that you are unable to process the image."
                })

        return_brackets(corrected_conversation)

        url = f"{self.base_url}/v1/chat/completions"
        data = {
            **({"model": self.model_name} if not self.dont_include_model else {}),
            "messages": corrected_conversation,
            "stream": False,
            **(self.gen_input or {})
        }

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"OpenAI Chat Completions with Image Non-Streaming flow! Attempt: {attempt + 1}")
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()
                payload = response.json()

                if 'choices' in payload and payload['choices'] and 'message' in payload['choices'][0]:
                    result_text = payload['choices'][0]['message'].get('content', '')

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
        """Sets up generation input parameters."""
        if self.truncate_property_name:
            self.gen_input[self.truncate_property_name] = self.endpoint_config.get("maxContextTokenSize", None)
        if self.stream_property_name:
            self.gen_input[self.stream_property_name] = self.stream
        if self.max_token_property_name:
            model_supports_thinking = self.endpoint_config.get("modelSupportsThinking", False)
            if not model_supports_thinking:
                self.gen_input[self.max_token_property_name] = self.max_tokens


def is_valid_http_url(url):
    """
    Check if the URL is a valid HTTP(S) URL.
    """
    try:
        result = urlparse(url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except:
        return False


def is_base64_image(s):
    """
    Check if a string appears to be a base64 encoded image.
    """
    if s.startswith('data:image/'):
        return True

    base64_pattern = r'^[A-Za-z0-9+/]+={0,2}$'
    return bool(re.match(base64_pattern, s))


def is_file_url(url):
    """
    Checks if a string is a file URL.
    """
    return url.startswith('file://')


def convert_to_data_uri(uri):
    """
    Converts a local file URI (e.g., file:///path/to/image.jpg) to a data URI,
    using Pillow to validate the image. This acts as a security measure to
    ensure only valid image files are processed. Handles OS-specific path formats.
    """
    actual_path = ""
    try:
        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != 'file':
            logger.warning(f"URI is not a file URI, cannot convert: {uri}")
            return None

        if os.name == 'nt':
            if parsed_uri.netloc:
                actual_path = f"\\\\{parsed_uri.netloc}{parsed_uri.path}"
            else:
                actual_path = parsed_uri.path.lstrip('/')
            actual_path = actual_path.replace('/', '\\')
        else:
            actual_path = parsed_uri.path

        mime_type = None
        try:
            with Image.open(actual_path) as img:
                image_format = img.format
                if image_format:
                    mime_type = f"image/{image_format.lower()}"
                    logger.debug(f"Validated as image. Determined mime type as {mime_type} using Pillow.")
                else:
                    logger.warning(
                        f"Pillow could not determine image format for {actual_path}. The file will not be sent.")
                    return None
        except Image.UnidentifiedImageError:
            logger.warning(
                f"Pillow could not identify file as an image: {actual_path}. File will not be sent for security reasons.")
            return None
        except Exception as e:
            logger.warning(
                f"Could not validate image type with Pillow for {actual_path}: {e}. The file will not be sent.")
            return None

        if mime_type:
            with open(actual_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return f"data:{mime_type};base64,{encoded_string}"
        else:
            return None

    except FileNotFoundError:
        logger.error(f"File not found for URI: {uri}, attempted path: {actual_path}")
        return None
    except Exception as e:
        logger.error(f"Error converting file URI to data URI: {e}")
        logger.error(traceback.format_exc())
        return None


def prep_corrected_conversation(conversation, system_prompt, prompt):
    """
    Prepares the conversation list with image handling. It processes messages with role "images",
    """
    if conversation is None:
        conversation = []

    current_conversation = deepcopy(conversation)

    if system_prompt:
        current_conversation.append({"role": "system", "content": system_prompt})
    if prompt:
        current_conversation.append({"role": "user", "content": prompt})

    image_contents = []
    image_messages_present = False

    potential_images = []
    temp_conversation = []
    for msg in current_conversation:
        if msg["role"] == "images":
            image_messages_present = True
            content = msg.get("content", "")
            if isinstance(content, str):
                potential_images.extend(content.split())
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        potential_images.extend(item.split())
        else:
            temp_conversation.append(msg)

    current_conversation = temp_conversation

    for image_url_or_data in potential_images:
        content = image_url_or_data.strip()
        if not content:
            continue

        processed = False
        if content.startswith('data:image/'):
            logger.debug("Processing data URI image")
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": content}
            })
            processed = True
        elif ';base64,' in content:
            if not content.startswith('data:'):
                logger.debug("Adding data URI prefix to base64 image data")
                try:
                    b64_data = content.split(';base64,', 1)[1]
                    if is_base64_image(b64_data):
                        content = f"data:image/jpeg;base64,{b64_data}"
                        image_contents.append({
                            "type": "image_url",
                            "image_url": {"url": content}
                        })
                        processed = True
                    else:
                        logger.warning(f"Skipping invalid base64 data after ';base64,': {content[:50]}...")
                except IndexError:
                    logger.warning(f"Skipping malformed base64 string: {content[:50]}...")
            else:
                logger.warning(f"Skipping non-image data URI: {content[:50]}...")

        elif is_base64_image(content):
            logger.debug("Decoding raw base64 to determine image type using Pillow")
            try:
                decoded_data = base64.b64decode(content)
                image = Image.open(io.BytesIO(decoded_data))
                image_format = image.format.lower()

                if image_format:
                    mime_type = f"image/{image_format}"
                    logger.debug(f"Determined image type: {mime_type}. Creating data URI.")
                    data_uri = f"data:{mime_type};base64,{content}"
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                    processed = True
                else:
                    logger.warning("Could not determine image type using Pillow. Skipping.")

            except (binascii.Error, ValueError):
                logger.warning(f"Skipping malformed base64 string during type detection: {content[:50]}...")
            except Image.UnidentifiedImageError:
                logger.warning(f"Pillow could not identify image from base64 data. Skipping.")

        elif content.startswith('file://'):
            try:
                logger.debug("Converting file URL to data URI")
                data_uri = convert_to_data_uri(content)
                if data_uri:
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                    processed = True
                else:
                    logger.warning(
                        f"Skipping file specified by URI as it could not be validated as an image: {content}")
            except Exception as e:
                logger.error(f"Error processing file URL {content}: {e}")

        if not processed and is_valid_http_url(content):
            image_url = content
            logger.debug(f"Adding HTTP image URL: {image_url}")
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": image_url}
            })
            processed = True

        if not processed:
            logger.warning(f"Skipping unrecognized image source: {content[:100]}...")

    if image_contents:
        last_user_msg_index = -1
        for i in range(len(current_conversation) - 1, -1, -1):
            if current_conversation[i]["role"] == "user":
                last_user_msg_index = i
                break

        if last_user_msg_index != -1:
            user_msg = current_conversation[last_user_msg_index]
            if isinstance(user_msg["content"], str):
                user_msg["content"] = [
                    {"type": "text", "text": user_msg["content"]},
                    *image_contents
                ]
            elif isinstance(user_msg["content"], list):
                existing_urls = {item['image_url']['url'] for item in user_msg['content'] if
                                 item.get('type') == 'image_url'}
                for img_item in image_contents:
                    if img_item['image_url']['url'] not in existing_urls:
                        user_msg['content'].append(img_item)
        else:
            current_conversation.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please describe the image(s)."},
                    *image_contents
                ]
            })
    elif image_messages_present and not image_contents:
        last_user_msg_index = -1
        for i in range(len(current_conversation) - 1, -1, -1):
            if current_conversation[i]["role"] == "user":
                last_user_msg_index = i
                break
        if last_user_msg_index != -1:
            user_msg = current_conversation[last_user_msg_index]
            if isinstance(user_msg.get("content"), list):
                text_content = ""
                for item in user_msg["content"]:
                    if item.get("type") == "text":
                        text_content = item.get("text", "")
                        break
                user_msg["content"] = text_content
                logger.debug(f"Reverted user message content to string as no valid images were found.")

    final_conversation = []
    for msg in current_conversation:
        if msg["role"] == "systemMes":
            msg["role"] = "system"
        if not (msg == current_conversation[-1] and msg["role"] == "assistant" and not msg.get("content")):
            final_conversation.append(msg)

    return final_conversation