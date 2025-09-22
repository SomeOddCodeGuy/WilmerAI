# middleware/llmapis/handlers/impl/openai_chat_api_image_specific_handler.py
import base64
import binascii
import io
import logging
import os
import re
import traceback
from copy import deepcopy
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from PIL import Image

from .openai_api_handler import OpenAiApiHandler

logger = logging.getLogger(__name__)


class OpenAIApiChatImageSpecificHandler(OpenAiApiHandler):
    """
    Handles interactions with OpenAI-compatible vision models that accept image data.

    This class extends the standard `OpenAiApiHandler`. It intercepts the
    conversation building process to find, process, and correctly format
    image data (from URLs, base64 strings, or file URIs) into the message list.
    It delegates all other payload creation and response parsing to its parent classes.
    """

    def _build_messages_from_conversation(self, conversation: Optional[List[Dict[str, str]]],
                                          system_prompt: Optional[str], prompt: Optional[str]) -> List[Dict[str, Any]]:
        """
        Overrides the base message building to process and inject image data.

        This method first calls the parent implementation to get a standard, clean
        conversation list. It then inspects the original conversation for messages with the
        special role "images". It extracts all image sources (URLs, base64, file URIs),
        processes them into the format required by vision APIs, and injects them into
        the content of the last user message.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The historical conversation.
            system_prompt (Optional[str]): The system prompt.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            List[Dict[str, Any]]: The final list of messages, potentially containing
            multimodal content with formatted image data, ready for the API payload.
        """
        messages = super()._build_messages_from_conversation(conversation, system_prompt, prompt)

        try:
            original_convo = deepcopy(conversation) or []
            if prompt:
                original_convo.append({"role": "user", "content": prompt})

            if not any(msg.get("role") == "images" for msg in original_convo):
                return messages

            image_contents = []
            potential_images = []
            for msg in original_convo:
                if msg.get("role") == "images":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        potential_images.extend(content.split())
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, str):
                                potential_images.extend(item.split())

            for image_url_or_data in potential_images:
                content = image_url_or_data.strip()
                if not content:
                    continue
                img_dict = self._process_single_image_source(content)
                if img_dict:
                    image_contents.append(img_dict)

            if image_contents:
                last_user_msg_index = next(
                    (i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"), -1)

                if last_user_msg_index != -1:
                    user_msg = messages[last_user_msg_index]
                    if isinstance(user_msg["content"], str):
                        user_msg["content"] = [{"type": "text", "text": user_msg["content"]}]

                    existing_urls = {item['image_url']['url'] for item in user_msg.get('content', []) if
                                     item.get('type') == 'image_url'}
                    for img_item in image_contents:
                        if img_item['image_url']['url'] not in existing_urls:
                            user_msg['content'].append(img_item)
                else:
                    messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": "Please describe the image(s)."}, *image_contents]
                    })

            return messages

        except Exception as e:
            logger.error(f"Critical error during image processing: {e}\n{traceback.format_exc()}")
            return self._build_fallback_conversation(messages)

    @staticmethod
    def _build_fallback_conversation(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Creates a safe, text-only conversation when image processing fails.

        This method cleans up any partially modified multimodal messages, reverting them
        to simple text. It then appends a system note to the last user message,
        informing the user that the image could not be processed.

        Args:
            messages (List[Dict[str, Any]]): The message list, possibly in a corrupted
                multimodal state.

        Returns:
            List[Dict[str, Any]]: A cleaned, text-only message list with an error notification.
        """
        for msg in messages:
            if msg["role"] == "user" and isinstance(msg.get("content"), list):
                text_content = next((item.get("text", "") for item in msg["content"] if item.get("type") == "text"), "")
                msg["content"] = text_content

        if messages and messages[-1].get("role") == "user":
            messages[-1][
                "content"] += "\n\n[System note: There was an error processing the provided image(s). I will respond based on the text alone.]"
        else:
            messages.append({
                "role": "user",
                "content": "There was an error processing an image. Please assist based on prior text, and state that you were unable to see the image."
            })
        return messages

    @staticmethod
    def _process_single_image_source(content: str) -> Optional[Dict]:
        """
        Processes a single image source string into an API-compatible dictionary.

        This method identifies if the string is a data URI, a raw base64 string,
        a file URI, or an HTTP(S) URL. It converts file URIs and raw base64
        into data URIs and wraps the result in the dictionary format required by
        the OpenAI API's multimodal endpoints.

        Args:
            content (str): The string representing the image source.

        Returns:
            Optional[Dict]: A dictionary formatted for the API (e.g.,
            `{'type': 'image_url', 'image_url': {'url': 'data:...'}}`), or
            None if the source format is unrecognized or invalid.
        """
        if content.startswith('data:image/'):
            return {"type": "image_url", "image_url": {"url": content}}

        if OpenAIApiChatImageSpecificHandler.is_base64_image(content):
            try:
                decoded_data = base64.b64decode(content)
                with Image.open(io.BytesIO(decoded_data)) as image:
                    image_format = image.format.lower() if image.format else 'jpeg'
                data_uri = f"data:image/{image_format};base64,{content}"
                return {"type": "image_url", "image_url": {"url": data_uri}}
            except (binascii.Error, ValueError, Image.UnidentifiedImageError):
                logger.warning(f"Pillow could not identify image from base64 data. Skipping.")
                return None

        if content.startswith('file://'):
            data_uri = OpenAIApiChatImageSpecificHandler.convert_to_data_uri(content)
            if data_uri:
                return {"type": "image_url", "image_url": {"url": data_uri}}
            return None

        if OpenAIApiChatImageSpecificHandler.is_valid_http_url(content):
            return {"type": "image_url", "image_url": {"url": content}}

        logger.warning(f"Skipping unrecognized image source: {content[:100]}...")
        return None

    @staticmethod
    def is_valid_http_url(url: str) -> bool:
        """
        Validates if a string is a well-formed HTTP or HTTPS URL.

        Args:
            url (str): The string to validate.

        Returns:
            bool: True if the URL has a valid HTTP/HTTPS scheme and network location,
            False otherwise.
        """
        try:
            result = urlparse(url)
            return all([result.scheme in ('http', 'https'), result.netloc])
        except:
            return False

    @staticmethod
    def is_base64_image(s: str) -> bool:
        """
        Provides a heuristic check to see if a string is likely base64 encoded.

        This check uses a regex and a length modulus check, which is a reliable
        indicator but not a guarantee of valid base64 image data.

        Args:
            s (str): The string to check.

        Returns:
            bool: True if the string resembles a base64 encoding, False otherwise.
        """
        if not isinstance(s, str) or not s:
            return False
        return bool(re.match(r'^[A-Za-z0-9+/]+={0,2}$', s)) and len(s) % 4 == 0

    @staticmethod
    def convert_to_data_uri(uri: str) -> Optional[str]:
        """
        Converts a local file URI (e.g., 'file:///path/to/image.png') to a data URI.

        This method resolves the local file path, opens the image to determine its
        MIME type, reads the file bytes, base64 encodes them, and constructs a
        full data URI string suitable for API transmission.

        Args:
            uri (str): The 'file://' URI of the local image.

        Returns:
            Optional[str]: The complete data URI (e.g.,
            'data:image/png;base64,...'), or None if the file is not found, is not a
            valid image, or another error occurs.
        """
        try:
            parsed_uri = urlparse(uri)
            if parsed_uri.scheme != 'file': return None

            actual_path = os.path.abspath(os.path.join(parsed_uri.netloc, parsed_uri.path))
            with Image.open(actual_path) as img:
                image_format = img.format.lower() if img.format else 'jpeg'
                mime_type = f"image/{image_format}"

            with open(actual_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return f"data:{mime_type};base64,{encoded_string}"
        except (FileNotFoundError, Image.UnidentifiedImageError, ValueError, OSError) as e:
            logger.warning(f"Could not process file URI {uri}: {e}. The file will not be sent.")
            return None
