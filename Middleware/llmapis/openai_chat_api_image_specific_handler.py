import json
import logging
import time
import traceback
import base64
import re
import os
from typing import Dict, Generator, List, Optional
from urllib.parse import urlparse

import requests

from Middleware.utilities import api_utils, instance_utils
from .llm_api_handler import LlmApiHandler
from ..utilities.config_utils import get_current_username, get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant

logger = logging.getLogger(__name__)


class OpenAIApiChatImageSpecificHandler(LlmApiHandler):
    """
    Handler for the OpenAI Image Specific API Handler. This only is for sending images as a node in workflows.
    """

    def handle_streaming(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None,
            current_username: str = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for OpenAI API with image support.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.
            current_username (str): The current username.

        Returns:
            Generator[str, None, None]: A generator yielding chunks of the response.
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
            
            # Use a simplified conversation without images
            corrected_conversation = []
            if system_prompt:
                corrected_conversation.append({"role": "system", "content": system_prompt})
            
            # Add non-image messages from the original conversation
            if conversation:
                for msg in conversation:
                    if msg["role"] != "images":
                        corrected_conversation.append(msg)
            
            # Add the prompt if provided, or an error message
            if prompt:
                corrected_conversation.append({"role": "user", "content": prompt})
            elif not any(msg["role"] == "user" for msg in corrected_conversation):
                corrected_conversation.append({
                    "role": "user", 
                    "content": "There was an error processing the image. Please provide assistance without the image and state that you are unable to process the image."
                })

        url = f"{self.base_url}/v1/chat/completions"
        data = {
            "model": self.model_name,
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
            try:
                logger.info(f"Streaming flow!")
                logger.info(f"URL: {url}")
                logger.debug("Headers: ")
                logger.debug(json.dumps(self.headers, indent=2))
                logger.debug("Data: ")
                logger.debug(data)
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
                                            current_username=current_username
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
                        current_username=current_username,
                    )
                    logger.debug("Total duration: {}", total_duration)
                    yield api_utils.sse_format(final_completion_json, output_format)

                    # Always send [DONE] for OpenAI API format
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
        Handle non-streaming response for OpenAI API with image support.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

        Returns:
            str: The complete response as a string.
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
            
            # Use a simplified conversation without images
            corrected_conversation = []
            if system_prompt:
                corrected_conversation.append({"role": "system", "content": system_prompt})
            
            # Add non-image messages from the original conversation
            if conversation:
                for msg in conversation:
                    if msg["role"] != "images":
                        corrected_conversation.append(msg)
            
            # Add the prompt if provided, or an error message
            if prompt:
                corrected_conversation.append({"role": "user", "content": prompt})
            elif not any(msg["role"] == "user" for msg in corrected_conversation):
                corrected_conversation.append({
                    "role": "user", 
                    "content": "There was an error processing the image. Please provide assistance without the image and state that you are unable to process the image."
                })

        url = f"{self.base_url}/v1/chat/completions"
        data = {
            "model": self.model_name,
            "messages": corrected_conversation,
            "stream": False,
            **(self.gen_input or {})
        }

        retries: int = 3
        for attempt in range(retries):
            try:
                logger.info(f"OpenAI Chat Completions with Image Non-Streaming flow! Attempt: {attempt + 1}")
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
                
                if 'choices' in payload and payload['choices'] and 'message' in payload['choices'][0]:
                    result_text = payload['choices'][0]['message'].get('content', '')

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
    
    # Check for base64 pattern
    base64_pattern = r'^[A-Za-z0-9+/]+={0,2}$'
    return bool(re.match(base64_pattern, s))


def is_file_url(url):
    """
    Check if the URL is a file URL.
    """
    try:
        result = urlparse(url)
        return result.scheme == 'file'
    except:
        return False


def convert_to_data_uri(file_path, mime_type=None):
    """
    Convert a file to a data URI.
    
    Args:
        file_path (str): Path to the file
        mime_type (str, optional): The MIME type. If None, it's guessed from the file extension.
        
    Returns:
        str: The data URI
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if mime_type is None:
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp'
        }
        mime_type = mime_map.get(ext, 'application/octet-stream')
    
    with open(file_path, 'rb') as f:
        encoded = base64.b64encode(f.read()).decode('utf-8')
    
    return f"data:{mime_type};base64,{encoded}"


def prep_corrected_conversation(conversation, system_prompt, prompt):
    """
    Prepare a corrected conversation for the OpenAI API with enhanced image handling.
    
    Supports:
    - HTTP/HTTPS URLs with proper protocol
    - Base64-encoded images (with or without data URI prefix)
    - File URLs (converted to data URIs)
    """
    if conversation is None:
        conversation = []

    # Add system prompt and user prompt to the conversation if provided
    if system_prompt:
        conversation.append({"role": "system", "content": system_prompt})
    if prompt:
        conversation.append({"role": "user", "content": prompt})

    # Collect all image contents and filter them with enhanced processing
    image_contents = []
    for msg in conversation:
        if msg["role"] == "images":
            content = msg["content"]
            
            # If it looks like base64 data
            if content.startswith('data:image/'):
                # It's already a data URI
                logger.debug("Processing data URI image")
                image_contents.append({
                    "type": "image_url",
                    "image_url": {"url": content}
                })
                continue
                
            elif ';base64,' in content:
                # Base64 data that might need the prefix
                if not content.startswith('data:'):
                    logger.debug("Adding data URI prefix to base64 image data")
                    content = f"data:image/jpeg;base64,{content.split(';base64,', 1)[1]}"
                image_contents.append({
                    "type": "image_url",
                    "image_url": {"url": content}
                })
                continue
                
            elif is_base64_image(content):
                # Looks like raw base64, add proper data URI prefix
                logger.debug("Converting raw base64 to data URI")
                content = f"data:image/jpeg;base64,{content}"
                image_contents.append({
                    "type": "image_url",
                    "image_url": {"url": content}
                })
                continue
                
            # Handle file URLs
            elif content.startswith('file://'):
                try:
                    # Convert file URL to data URI
                    logger.debug("Converting file URL to data URI")
                    file_path = content[7:]  # Strip "file://"
                    data_uri = convert_to_data_uri(file_path)
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                    continue
                except Exception as e:
                    logger.error(f"Error converting file URL to data URI: {e}")
                    # Skip further processing for this failed file URL
                    continue
            
            # Process as URL strings - might be multiple URLs separated by whitespace
            for image_url in content.split():
                if not image_url.strip():
                    continue
                    
                # Clean and validate URL
                image_url = image_url.strip()
                
                # Ensure URL has proper protocol
                if not image_url.startswith(('http://', 'https://')):
                    # Add https:// prefix if missing
                    if image_url.startswith('//'):
                        image_url = 'https:' + image_url
                    else:
                        image_url = 'https://' + image_url
                        
                # Final validation - check BEFORE appending
                if is_valid_http_url(image_url):
                    logger.debug(f"Adding HTTP image URL: {image_url}")
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    })
                else:
                    logger.warning(f"Invalid image URL skipped: {image_url}")
    
    # Filter out image messages from conversation
    conversation = [msg for msg in conversation if msg["role"] != "images"]

    # Format conversation for OpenAI API with images
    # Find the last user message and append images if there are any
    if image_contents:
        for msg in reversed(conversation):
            if msg["role"] == "user":
                # For OpenAI API, content needs to be a list when images are present
                if isinstance(msg["content"], str):
                    # Convert content to a list with text as the first item
                    msg["content"] = [
                        {"type": "text", "text": msg["content"]},
                        *image_contents
                    ]
                break
        
        # If no user message found, add one with the images
        if not any(msg["role"] == "user" for msg in conversation):
            conversation.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please describe this image."},
                    *image_contents
                ]
            })

    # Convert roles for OpenAI API format
    corrected_conversation = [
        {**msg, "role": "system" if msg["role"] == "systemMes" else msg["role"]}
        for msg in conversation
    ]

    # Remove empty assistant messages
    if corrected_conversation and corrected_conversation[-1]["role"] == "assistant" and (
            corrected_conversation[-1]["content"] == "" or not corrected_conversation[-1]["content"]):
        corrected_conversation.pop()

    return corrected_conversation 