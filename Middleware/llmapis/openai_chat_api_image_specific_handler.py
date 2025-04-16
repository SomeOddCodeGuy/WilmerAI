import json
import logging
import time
import traceback
import base64
import re
import os
from typing import Dict, Generator, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from Middleware.utilities import api_utils, instance_utils
from Middleware.utilities.api_utils import handle_sse_and_json_stream, extract_openai_chat_content
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
        # Use repr for logging to avoid issues with non-serializable mock objects
        logger.debug(f"Sending request to {url} with data: {repr(data)}")

        # Since this handler is specific to OpenAI, the output format is fixed.
        output_format = 'openai'

        try:
            logger.info(f"Initiating streaming request to {url}")
            with self.session.post(url, headers=self.headers, json=data, stream=True) as r:
                logger.info(f"Response status code: {r.status_code}")
                r.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

                # Use the imported utility function
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
            # Yield an error message in SSE format
            error_json = api_utils.build_response_json(
                token=f"Error communicating with OpenAI API: {e}",
                finish_reason="stop",
                current_username=get_current_username()
            )
            yield api_utils.sse_format(error_json, output_format)
            # Also send DONE signal after error if necessary (OpenAI format expects it)
            yield api_utils.sse_format("[DONE]", output_format)
            # Note: We yield an error and DONE instead of raising,
            # as raising would terminate the generator consumer abruptly.

        except Exception as e:
             logger.error(f"An unexpected error occurred during OpenAI streaming: {e}")
             logger.error(traceback.format_exc())
             # Yield an error message in SSE format
             error_json = api_utils.build_response_json(
                 token=f"An unexpected error occurred: {e}",
                 finish_reason="stop",
                 current_username=get_current_username()
             )
             yield api_utils.sse_format(error_json, output_format)
             # Also send DONE signal after error
             yield api_utils.sse_format("[DONE]", output_format)

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
    Includes a basic length check to avoid short false positives.
    """
    if s.startswith('data:image/'):
        return True
    
    # Check for base64 pattern and minimum length (e.g., > 10 chars)
    min_len = 10
    base64_pattern = r'^[A-Za-z0-9+/]+={0,2}$'
    return len(s) > min_len and bool(re.match(base64_pattern, s))


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
    - Multiple image sources per message, separated by whitespace.
    """
    if conversation is None:
        conversation = []

    # Add system prompt and user prompt to the conversation if provided
    if system_prompt:
        conversation.append({"role": "system", "content": system_prompt})
    if prompt:
        conversation.append({"role": "user", "content": prompt})

    # --- Refactored Image Processing ---    
    image_contents = []
    original_conversation = conversation # Keep a copy before filtering
    conversation = [] # Build the new conversation without image messages yet

    for msg in original_conversation:
        if msg["role"] == "images":
            content_str = msg["content"]
            if not isinstance(content_str, str): # Skip if content is not a string
                logger.warning(f"Skipping non-string image content: {content_str}")
                continue
                
            # Always split the content first
            parts = content_str.split()
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                    
                processed = False
                # 1. Check for data URI
                if part.startswith('data:image/'):
                    logger.debug("Processing data URI image")
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": part}
                    })
                    processed = True
                    
                # 2. Check for file URL
                elif part.startswith('file://'):
                    try:
                        logger.debug(f"Converting file URL to data URI: {part}")
                        file_path = urlparse(part).path # Get path reliably
                        if not file_path:
                             raise ValueError("Invalid file URL path")
                        data_uri = convert_to_data_uri(file_path)
                        image_contents.append({
                            "type": "image_url",
                            "image_url": {"url": data_uri}
                        })
                        processed = True
                    except Exception as e:
                        logger.error(f"Error converting file URL '{part}' to data URI: {e}")
                        # Skip this part if conversion fails
                        processed = True # Mark as processed to avoid fallback, DON'T add to image_contents
                
                # 3. Check for base64 (raw or with partial prefix)
                elif is_base64_image(part) or (';base64,' in part and len(part.split(';base64,',1)[1]) > 10): # Add length check here too
                    logger.debug(f"Processing potential base64 image part: {part[:30]}...")
                    try:
                        # Ensure it has the full data URI prefix
                        if ';base64,' in part and not part.startswith('data:'):
                             b64_data = part.split(';base64,', 1)[1]
                             part = f"data:image/jpeg;base64,{b64_data}"
                             logger.debug("Added data URI prefix to base64 data")
                        elif not part.startswith('data:image/'):
                            # Assume raw base64, add default prefix
                            part = f"data:image/jpeg;base64,{part}"
                            logger.debug("Converted raw base64 to data URI")
                        
                        # Basic validation: check if prefix is correct
                        if part.startswith('data:image/'):
                            image_contents.append({
                                "type": "image_url",
                                "image_url": {"url": part}
                            })
                            processed = True
                        else:
                             logger.warning(f"Skipping malformed base64 part: {part[:30]}...")
                             processed = True # Mark as processed to avoid fallback
                    except Exception as e:
                         logger.error(f"Error processing base64 part '{part[:30]}...': {e}")
                         processed = True # Mark as processed to avoid fallback

                # 4. Fallback to check as HTTP/HTTPS URL
                if not processed:
                    original_url = part # Keep original for logging if invalid
                    is_valid = is_valid_http_url(part)
                    if not is_valid:
                        # Try adding https:// prefix if missing, but only if it looks like a URL
                        looks_like_url = ('.' in part or '/' in part) or part.startswith('//')
                        if looks_like_url:
                            if part.startswith('//'):
                                part = 'https:' + part
                            elif not part.startswith(('http://', 'https://')):
                                part = 'https://' + part
                            is_valid = is_valid_http_url(part) # Re-check validity
                            
                    # Add if valid, otherwise skip and warn
                    if is_valid:
                        logger.debug(f"Adding HTTP/S image URL: {part}")
                        image_contents.append({
                            "type": "image_url",
                            "image_url": {"url": part}
                        })
                    else:
                        logger.warning(f"Invalid image source skipped: {original_url}")
        else:
            # If it's not an image message, add it to the filtered conversation
            conversation.append(msg)
    # --- End Refactored Image Processing ---

    # Format conversation for OpenAI API with images
    # Find the last user message and append images if there are any
    if image_contents:
        # Find the index of the last user message
        last_user_msg_index = -1
        for i in range(len(conversation) - 1, -1, -1):
            if conversation[i]["role"] == "user":
                last_user_msg_index = i
                break

        if last_user_msg_index != -1:
            msg = conversation[last_user_msg_index]
            # Ensure content is a list
            if isinstance(msg["content"], str):
                msg["content"] = [{"type": "text", "text": msg["content"]}]
            elif not isinstance(msg["content"], list):
                logger.warning(f"Unexpected content type for user message: {type(msg['content'])}. Resetting.")
                msg["content"] = [{"type": "text", "text": ""}]
            
            # Append images if not already present (avoids duplication if called multiple times)
            existing_urls = {item['image_url']['url'] for item in msg["content"] if item['type'] == 'image_url'}
            for img_item in image_contents:
                if img_item['image_url']['url'] not in existing_urls:
                    msg["content"].append(img_item)
        else:
            # If no user message found, add one with a default text and the images
            conversation.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please describe the image(s)."}, # Adjusted default text
                    *image_contents
                ]
            })

    # Convert roles for OpenAI API format
    corrected_conversation = [
        {**msg, "role": "system" if msg["role"] == "systemMes" else msg["role"]}
        for msg in conversation
    ]

    # Remove empty final assistant messages
    if corrected_conversation and corrected_conversation[-1]["role"] == "assistant" and (
            corrected_conversation[-1]["content"] == "" or not corrected_conversation[-1]["content"]):
        corrected_conversation.pop()

    return corrected_conversation 