import json
import logging
import time
import traceback
import base64
import re
import os
import mimetypes
import binascii
import io
from typing import Dict, Generator, List, Optional
from urllib.parse import urlparse
from copy import deepcopy

import requests
from PIL import Image

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
            prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Handle streaming response for OpenAI API with image support.

        Args:
            conversation (Optional[List[Dict[str, str]]]): A list of messages in the conversation.
            system_prompt (Optional[str]): The system prompt to use.
            prompt (Optional[str]): The user prompt to use.

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
                                # Yield a formatted error message
                                error_token = f"Error during streaming processing: {e}"
                                error_json = api_utils.build_response_json(
                                    token=error_token,
                                    finish_reason="stop",
                                    current_username=get_current_username()
                                )
                                yield api_utils.sse_format(error_json, output_format)
                                # Stop processing after yielding the error
                                raise StopIteration # Use StopIteration to signal generator end cleanly after error

                    total_duration = int((time.time() - start_time) * 1e9)

                    # Send the final payload with "done" and "stop"
                    final_completion_json = api_utils.build_response_json(
                        token="",
                        finish_reason="stop",
                        current_username=get_current_username(),
                    )
                    logger.debug("Total duration: %s", total_duration)
                    yield api_utils.sse_format(final_completion_json, output_format)

                    # Always send [DONE] for OpenAI API format
                    logger.info("End of stream reached, sending [DONE] signal.")
                    yield api_utils.sse_format("[DONE]", output_format)

            except requests.RequestException as e:
                logger.warning(f"Request failed: {e}")
                raise
            # Add a general exception catch block here
            except Exception as e:
                logger.error(f"Unexpected error during streaming request setup or iteration: {e}", exc_info=True)
                # Yield a formatted error message if possible
                try:
                    error_token = f"Error during streaming processing: {e}"
                    error_json = api_utils.build_response_json(
                        token=error_token,
                        finish_reason="stop",
                        current_username=get_current_username()
                    )
                    yield api_utils.sse_format(error_json, output_format)
                except Exception as inner_e:
                    logger.error(f"Failed to yield formatted error message: {inner_e}")
                # Stop the generator cleanly after yielding the error (or attempting to)
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

    Skips invalid URLs or images that fail processing.
    """
    if conversation is None:
        conversation = []

    # Create a deep copy to avoid modifying the original list
    current_conversation = deepcopy(conversation)

    # Add system prompt and user prompt to the copied conversation if provided
    if system_prompt:
        current_conversation.append({"role": "system", "content": system_prompt})
    if prompt:
        current_conversation.append({"role": "user", "content": prompt})

    # Collect all image contents and filter them with enhanced processing
    image_contents = []
    image_messages_present = False # Flag to track if 'images' role existed

    # Process image messages separately first
    potential_images = []
    temp_conversation = []
    for msg in current_conversation:
        if msg["role"] == "images":
            image_messages_present = True
            content = msg.get("content", "")
            if isinstance(content, str): # Handle potential list content safely
                potential_images.extend(content.split())
            elif isinstance(content, list):
                 # If content is already a list (e.g., from previous processing?), extract strings
                 for item in content:
                      if isinstance(item, str):
                           potential_images.extend(item.split())
                      # Silently ignore non-string items in list for now
            # else: Silently ignore non-string/non-list content
        else:
            temp_conversation.append(msg)

    # Update conversation to remove the original 'images' role messages
    current_conversation = temp_conversation

    # Process the collected potential image strings
    for image_url_or_data in potential_images:
        content = image_url_or_data.strip()
        if not content:
            continue

        processed = False
        # Handle data URIs first
        if content.startswith('data:image/'):
            logger.debug("Processing data URI image")
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": content}
            })
            processed = True
        # Handle base64 that might need prefix
        elif ';base64,' in content:
            if not content.startswith('data:'):
                logger.debug("Adding data URI prefix to base64 image data")
                try:
                     # Extract actual base64 part after the first ;base64,
                     b64_data = content.split(';base64,', 1)[1]
                     # Simple check if it resembles base64
                     if is_base64_image(b64_data): # Check the data part
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
            else: # Already has data: prefix but wasn't image?
                 logger.warning(f"Skipping non-image data URI: {content[:50]}...")

        # Handle raw base64
        elif is_base64_image(content):
            logger.debug("Decoding raw base64 to determine image type using Pillow")
            try:
                # Decode the base64 string
                decoded_data = base64.b64decode(content)
                
                # Use Pillow to open the image data from bytes
                image = Image.open(io.BytesIO(decoded_data))
                
                # Get the image format (e.g., 'JPEG', 'PNG')
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

        # Handle file URLs
        elif content.startswith('file://'):
            try:
                logger.debug("Converting file URL to data URI")
                parsed_uri = urlparse(content)
                file_path = parsed_uri.path # Use urlparse to handle file paths correctly
                # Handle different OS path representations from file URI
                if os.name == 'nt': # Windows: file:///C:/path -> /C:/path
                     if file_path.startswith('/'):
                          file_path = file_path[1:]
                     file_path = file_path.replace('/', '\\') # Convert to backslashes
                # Other OS might need specific handling if paths aren't standard
                
                # Security: Validate that the file is an image based on MIME type
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type and mime_type.startswith('image/'):
                    data_uri = convert_to_data_uri(file_path)
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    })
                    processed = True
                else:
                    logger.warning(f"Skipping non-image file specified by file URI: {content}")
                    # 'processed' remains False, so it will be logged as an unrecognized source later
                    
            except FileNotFoundError:
                logger.error(f"File not found for URL: {content}, Path: {file_path}")
            except Exception as e:
                logger.error(f"Error converting file URL {content} to data URI: {e}")
            # If file conversion fails, processed remains False

        # Handle HTTP/HTTPS URLs last
        if not processed and is_valid_http_url(content):
            # Use the already validated content as the URL
            image_url = content
            logger.debug(f"Adding HTTP image URL: {image_url}")
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": image_url}
            })
            processed = True
            # Removed the potentially problematic auto-prefixing logic
            # else:
            #     logger.warning(f"Invalid or non-HTTP/S image URL skipped: {content}")

        # If after all checks, it wasn't processed, log a warning
        if not processed:
            logger.warning(f"Skipping unrecognized image source: {content[:100]}...")

    # Now, modify the *last* user message to include the *valid* images, if any
    if image_contents:
        last_user_msg_index = -1
        for i in range(len(current_conversation) - 1, -1, -1):
            if current_conversation[i]["role"] == "user":
                last_user_msg_index = i
                break

        if last_user_msg_index != -1:
            user_msg = current_conversation[last_user_msg_index]
            if isinstance(user_msg["content"], str):
                # Convert content to a list with text as the first item
                user_msg["content"] = [
                    {"type": "text", "text": user_msg["content"]},
                    *image_contents # Add only the valid images
                ]
            elif isinstance(user_msg["content"], list):
                 # If already a list, assume it might have text/image structure,
                 # append new valid images carefully.
                 # This assumes the original list structure is [{'type':'text', ...}, ...]
                 # Filter out any pre-existing image_url types before adding new ones
                 # to avoid duplicates if function is called multiple times?
                 # For simplicity now, just append if not already present by URL.
                 existing_urls = {item['image_url']['url'] for item in user_msg['content'] if item.get('type') == 'image_url'}
                 for img_item in image_contents:
                      if img_item['image_url']['url'] not in existing_urls:
                           user_msg['content'].append(img_item)
            # else: handle case where content is neither str nor list? (ignore for now)

        else:
            # If no user message found, add one with the images
            current_conversation.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please describe the image(s)."}, # Generic text
                    *image_contents
                ]
            })
    elif image_messages_present and not image_contents:
         # If original message had 'images' role but none were valid,
         # ensure the last user message content remains a simple string.
         # This addresses the test failures where they expected string content.
         last_user_msg_index = -1
         for i in range(len(current_conversation) - 1, -1, -1):
             if current_conversation[i]["role"] == "user":
                 last_user_msg_index = i
                 break
         if last_user_msg_index != -1:
              user_msg = current_conversation[last_user_msg_index]
              if isinstance(user_msg.get("content"), list):
                   # Find the text part and revert content to just that string
                   text_content = ""
                   for item in user_msg["content"]:
                        if item.get("type") == "text":
                             text_content = item.get("text", "")
                             break
                   user_msg["content"] = text_content
                   logger.debug(f"Reverted user message content to string as no valid images were found.")

    # Final pass for role conversion and cleanup
    final_conversation = []
    for msg in current_conversation:
        # Convert systemMes role
        if msg["role"] == "systemMes":
            msg["role"] = "system"
        # Skip empty assistant messages at the end
        if not (msg == current_conversation[-1] and msg["role"] == "assistant" and not msg.get("content")):
             final_conversation.append(msg)

    return final_conversation 