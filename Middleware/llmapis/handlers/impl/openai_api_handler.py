# middleware/llmapis/handlers/impl/openai_api_handler.py
import base64
import binascii
import io
import json
import logging
import re
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urlparse

from PIL import Image

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler
from Middleware.llmapis.handlers.base.image_injection import inject_images_into_messages

logger = logging.getLogger(__name__)


class OpenAiApiHandler(BaseChatCompletionsHandler):
    """
    Handles interactions with any OpenAI-compatible Chat Completions API.

    This class extends `BaseChatCompletionsHandler` and is designed for APIs
    that follow the standard OpenAI request and response schema. It relies on
    the base class's payload preparation and primarily overrides methods to
    specify the correct API endpoint and to parse the specific structure of
    OpenAI's streaming and non-streaming responses.

    This handler also supports multimodal conversations including images.
    When image messages are present, they are processed (from URLs, base64
    strings, or file URIs) and formatted into the message list as required
    by OpenAI-compatible vision APIs.
    """

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; False for standard Server-Sent Events (SSE).

        OpenAI-compatible APIs use the standard SSE format where each message is
        prefixed with 'data: '. This property tells the base streaming handler not
        to treat each line as a standalone JSON object.

        Returns:
            bool: Returns False to disable line-by-line JSON stream processing.
        """
        return False

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the OpenAI chat request.

        Returns:
            str: The complete URL for the standard `/v1/chat/completions` endpoint.
        """
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON data chunk from an OpenAI-compatible stream.

        This method is called for each 'data: ' line in the SSE stream. It loads
        the JSON string and extracts the content token and finish reason from
        the `choices` array.

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary with 'token' and 'finish_reason'
            keys, or None if the chunk is empty or cannot be parsed.
        """
        try:
            if not data_str:
                return None

            chunk_data = json.loads(data_str)
            choice = chunk_data.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            token = delta.get("content", "")
            finish_reason = choice.get("finish_reason")

            result = {'token': token, 'finish_reason': finish_reason}
            tool_calls_delta = delta.get("tool_calls")
            # Only attach real tool-call deltas. Some OpenAI-compatible backends put
            # an empty "tool_calls": [] on ordinary text deltas; forwarding that would
            # make the streaming handler treat plain text as a tool-call chunk.
            if tool_calls_delta:
                result['tool_calls'] = tool_calls_delta
            return result
        except (json.JSONDecodeError, IndexError, TypeError, AttributeError):
            # TypeError/AttributeError cover chunks whose JSON parses to a non-dict,
            # or whose 'choices' entries are not dicts; malformed chunks are skipped,
            # not fatal to the stream.
            logger.warning(f"Could not parse OpenAI stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> Union[str, Dict[str, Any]]:
        """
        Extracts the generated text from a non-streaming OpenAI-compatible API response.

        This method navigates the JSON structure of a complete OpenAI response
        to find and return the main message content. When tool calls are present,
        returns a dictionary with content, tool_calls, and finish_reason.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            Union[str, Dict[str, Any]]: The extracted text content from
            `choices[0].message.content`, or a dictionary with 'content',
            'tool_calls', and 'finish_reason' keys when tool calls are present,
            or an empty string if not found.
        """
        try:
            message = response_json['choices'][0]['message']
            content = message.get('content') or ""
            tool_calls = message.get('tool_calls')
            if tool_calls:
                return {
                    'content': content,
                    'tool_calls': tool_calls,
                    'finish_reason': response_json['choices'][0].get('finish_reason', 'tool_calls')
                }
            return content
        except (KeyError, IndexError, TypeError, AttributeError):
            # AttributeError covers a non-dict 'message' entry, which .get access
            # would otherwise escape.
            logger.error(f"Could not find content in OpenAI response: {response_json}")
            return ""

    def _build_messages_from_conversation(self, conversation: Optional[List[Dict[str, str]]],
                                          system_prompt: Optional[str], prompt: Optional[str]) -> List[Dict[str, Any]]:
        """
        Overrides the base message building to process and inject image data.

        This method first calls the parent implementation to get a standard, clean
        conversation list, then runs the shared image-injection traversal with the
        OpenAI block format (images appended after the text block). On failure the
        conversation is reverted to text-only with an error note.

        Assistant messages carrying an empty or null ``tool_calls`` key (residue
        from clients replaying history) have the key stripped, because the OpenAI
        API rejects an assistant message whose ``tool_calls`` is an empty array.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The historical conversation.
            system_prompt (Optional[str]): The system prompt.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            List[Dict[str, Any]]: The final list of messages, potentially containing
            multimodal content with formatted image data, ready for the API payload.
        """
        messages = super()._build_messages_from_conversation(conversation, system_prompt, prompt)
        messages = [
            {k: v for k, v in msg.items() if k != "tool_calls"}
            if msg.get("role") == "assistant" and "tool_calls" in msg
               and not (isinstance(msg.get("tool_calls"), list) and msg.get("tool_calls"))
            else msg
            for msg in messages
        ]
        return inject_images_into_messages(
            messages,
            to_image_block=self._process_single_image_source,
            images_first=False,
            api_label="OpenAI",
            missing_user_fallback_text=(
                "There was an error processing an image. Please assist based on prior text, "
                "and state that you were unable to see the image."
            ),
        )

    @staticmethod
    def _process_single_image_source(content: str) -> Optional[Dict]:
        """
        Processes a single image source string into an API-compatible dictionary.

        This method identifies if the string is a data URI, a raw base64 string,
        or an HTTP(S) URL. It converts raw base64 into data URIs and wraps the
        result in the dictionary format required by the OpenAI API's multimodal
        endpoints. File URIs (file://) are rejected for security reasons.

        Args:
            content (str): The string representing the image source.

        Returns:
            Optional[Dict]: A dictionary formatted for the API (e.g.,
            `{'type': 'image_url', 'image_url': {'url': 'data:...'}}`), or
            None if the source format is unrecognized or invalid.
        """
        if content.startswith('data:image/'):
            return {"type": "image_url", "image_url": {"url": content}}

        if OpenAiApiHandler.is_base64_image(content):
            try:
                decoded_data = base64.b64decode(content)
                with Image.open(io.BytesIO(decoded_data)) as image:
                    image_format = image.format.lower() if image.format else 'jpeg'
                data_uri = f"data:image/{image_format};base64,{content}"
                return {"type": "image_url", "image_url": {"url": data_uri}}
            except (binascii.Error, ValueError, Image.UnidentifiedImageError):
                logger.warning("Pillow could not identify image from base64 data. Skipping.")
                return None

        if content.startswith('file://'):
            logger.warning("file:// URIs are not supported for security reasons. Skipping.")
            return None

        if OpenAiApiHandler.is_valid_http_url(content):
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
        except Exception:
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
        if not isinstance(s, str) or len(s) < 100:
            return False
        return bool(re.match(r'^[A-Za-z0-9+/]+={0,2}$', s)) and len(s) % 4 == 0

