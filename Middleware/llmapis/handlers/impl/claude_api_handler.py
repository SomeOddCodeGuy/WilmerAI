# middleware/llmapis/handlers/impl/claude_api_handler.py
import base64 as base64_module
import io
import json
import logging
import re
import traceback
from typing import Dict, Optional, Any, List

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler
from Middleware.utilities.sensitive_logging_utils import sensitive_log

logger = logging.getLogger(__name__)


class ClaudeApiHandler(BaseChatCompletionsHandler):
    """
    Handles interactions with Anthropic's Claude API.

    This class extends `BaseChatCompletionsHandler` and is designed for the
    Anthropic Messages API. It handles the specific request and response schema
    for Claude, including streaming and non-streaming responses.
    """

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; False for standard Server-Sent Events (SSE).

        Claude API uses the standard SSE format where each message is
        prefixed with 'event: ' and 'data: '. This property tells the base
        streaming handler not to treat each line as a standalone JSON object.

        Returns:
            bool: Returns False to disable line-by-line JSON stream processing.
        """
        return False

    @property
    def _required_event_name(self) -> Optional[str]:
        """
        Returns None so all SSE event types pass through to _process_stream_data.

        Claude sends tool call data across multiple event types (content_block_start,
        content_block_delta, message_delta), so we cannot filter to a single event.
        All filtering is handled inside _process_stream_data instead.

        Returns:
            Optional[str]: None to disable event filtering.
        """
        return None

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the Claude Messages API.

        Returns:
            str: The complete URL for the `/v1/messages` endpoint.
        """
        return f"{self.base_url.rstrip('/')}/v1/messages"

    def __init__(self, base_url: str, api_key: str, gen_input: Dict[str, Any], model_name: str,
                 headers: Dict[str, str], stream: bool, api_type_config, endpoint_config,
                 max_tokens, dont_include_model: bool = False):
        super().__init__(
            base_url=base_url, api_key=api_key, gen_input=gen_input, model_name=model_name,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            },
            stream=stream, api_type_config=api_type_config, endpoint_config=endpoint_config,
            max_tokens=max_tokens, dont_include_model=dont_include_model
        )
        self._tool_call_index = 0
        self._active_tool_call_id = None

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON data chunk from a Claude API stream.

        Handles all Claude SSE event types: content_block_start, content_block_delta,
        content_block_stop, and message_delta. Text deltas produce tokens; tool_use
        blocks are converted to OpenAI-format tool_calls.

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary with 'token', 'finish_reason',
            and optionally 'tool_calls' keys, or None if the event should be skipped.
        """
        try:
            if not data_str:
                return None

            chunk_data = json.loads(data_str)
            chunk_type = chunk_data.get("type", "")

            if chunk_type == "content_block_start":
                block = chunk_data.get("content_block", {})
                if block.get("type") == "tool_use":
                    self._active_tool_call_id = block.get("id")
                    return {
                        'token': '',
                        'finish_reason': None,
                        'tool_calls': [{
                            'index': self._tool_call_index,
                            'id': self._active_tool_call_id,
                            'type': 'function',
                            'function': {
                                'name': block.get("name", ""),
                                'arguments': ''
                            }
                        }]
                    }
                return None

            if chunk_type == "content_block_delta":
                delta = chunk_data.get("delta", {})
                delta_type = delta.get("type", "")
                if delta_type == "text_delta":
                    return {'token': delta.get("text", ""), 'finish_reason': None}
                if delta_type == "input_json_delta":
                    return {
                        'token': '',
                        'finish_reason': None,
                        'tool_calls': [{
                            'index': self._tool_call_index,
                            'function': {'arguments': delta.get("partial_json", "")}
                        }]
                    }
                return None

            if chunk_type == "content_block_stop":
                if self._active_tool_call_id:
                    self._tool_call_index += 1
                    self._active_tool_call_id = None
                return None

            if chunk_type == "message_delta":
                stop_reason = chunk_data.get("delta", {}).get("stop_reason")
                if stop_reason:
                    finish = "tool_calls" if stop_reason == "tool_use" else stop_reason
                    return {'token': '', 'finish_reason': finish}
                return None

            return None
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"Could not parse Claude stream data string: {data_str}")
            return None

    @staticmethod
    def _convert_tools_to_claude_format(openai_tools: List[Dict]) -> List[Dict]:
        """
        Converts tool definitions from OpenAI format to Claude format.

        OpenAI format:
            {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        Claude format:
            {"name": "...", "description": "...", "input_schema": {...}}

        Args:
            openai_tools (List[Dict]): Tool definitions in OpenAI format.

        Returns:
            List[Dict]: Tool definitions in Claude format.
        """
        claude_tools = []
        for tool in openai_tools:
            func = tool.get("function", {})
            claude_tool = {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
            }
            params = func.get("parameters")
            if params:
                claude_tool["input_schema"] = params
            claude_tools.append(claude_tool)
        return claude_tools

    @staticmethod
    def _convert_tool_choice_to_claude_format(openai_tool_choice):
        """
        Converts a tool_choice value from OpenAI format to Claude format.

        OpenAI: "auto", "none", "required", or {"type":"function","function":{"name":"..."}}
        Claude: {"type":"auto"}, {"type":"any"}, or {"type":"tool","name":"..."}

        Args:
            openai_tool_choice (Union[str, Dict, None]): Tool choice in OpenAI format.

        Returns:
            Optional[Dict]: Tool choice in Claude format, or None if no conversion applies.
        """
        if openai_tool_choice is None:
            return None
        if isinstance(openai_tool_choice, str):
            mapping = {
                "auto": {"type": "auto"},
                "none": None,  # Claude has no "none"; omit tool_choice and tools instead
                "required": {"type": "any"},
            }
            return mapping.get(openai_tool_choice)
        if isinstance(openai_tool_choice, dict):
            func = openai_tool_choice.get("function", {})
            name = func.get("name")
            if name:
                return {"type": "tool", "name": name}
        return None

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str], *, tools: Optional[list] = None,
                         tool_choice=None) -> Dict:
        """
        Prepares the payload for Claude API with proper system message handling.

        Claude requires system messages to be sent as a separate 'system' parameter,
        not in the messages array. This method extracts system messages and formats
        them correctly. It also filters out unsupported parameters. Tool definitions
        are converted from OpenAI format to Claude's native format.

        Args:
            conversation: The conversation history
            system_prompt: The system prompt
            prompt: The user prompt
            tools: Tool definitions in OpenAI format (converted to Claude format).
            tool_choice: Tool selection policy in OpenAI format (converted to Claude format).

        Returns:
            Dict: The properly formatted payload for Claude API
        """
        # First get the standard payload from the parent
        payload = super()._prepare_payload(conversation, system_prompt, prompt,
                                           tools=None, tool_choice=None)

        # Claude API supported parameters (as of 2025)
        # Ref: https://docs.anthropic.com/en/api/messages
        SUPPORTED_PARAMS = {
            'model', 'messages', 'max_tokens', 'system', 'temperature',
            'top_p', 'top_k', 'stream', 'stop_sequences', 'metadata', 'thinking',
            'tools', 'tool_choice'
        }

        # Filter out unsupported parameters
        unsupported = set(payload.keys()) - SUPPORTED_PARAMS
        if unsupported:
            logger.warning(f"Removing unsupported Claude API parameters: {unsupported}")
            for param in unsupported:
                payload.pop(param)

        # Extract system messages from the messages array
        messages = payload.get('messages', [])
        system_messages = []
        non_system_messages = []

        for msg in messages:
            if msg.get('role') == 'system':
                system_messages.append(msg.get('content', ''))
            else:
                non_system_messages.append(msg)

        # Combine all system messages into a single system parameter
        if system_messages:
            payload['system'] = '\n\n'.join(system_messages)

        # Update messages to only include user and assistant messages
        payload['messages'] = non_system_messages

        # Ensure messages array starts with a user message (Claude requirement)
        if non_system_messages and non_system_messages[0].get('role') != 'user':
            logger.warning("Claude API requires messages to start with a 'user' message")

        # Claude supports prefilling - trailing assistant messages are allowed and intentional
        # They guide Claude's response format (e.g., forcing JSON with "{")
        if non_system_messages and non_system_messages[-1].get('role') == 'assistant':
            prefill_content = non_system_messages[-1].get('content', '')
            sensitive_log(logger, logging.DEBUG, "Claude prefill detected: '%s...'", prefill_content[:100])
            # Validate: prefill cannot end with trailing whitespace
            if prefill_content != prefill_content.rstrip():
                sensitive_log(logger, logging.WARNING,
                             "Claude prefill content ends with whitespace, which may cause API errors. "
                             "Trimming whitespace from: '%s'", prefill_content)
                non_system_messages[-1]['content'] = prefill_content.rstrip()

        if tools:
            payload['tools'] = self._convert_tools_to_claude_format(tools)
            claude_tool_choice = self._convert_tool_choice_to_claude_format(tool_choice)
            if claude_tool_choice is not None:
                payload['tool_choice'] = claude_tool_choice

        return payload

    def _build_messages_from_conversation(self, conversation: Optional[List[Dict[str, str]]],
                                          system_prompt: Optional[str], prompt: Optional[str]) -> List[Dict[str, Any]]:
        """
        Overrides the base message building to convert per-message images into
        Claude's multimodal content block format.

        Claude expects images as content blocks with type "image" and a source
        object containing the base64 data and media type. This differs from
        the OpenAI format which uses "image_url" blocks with data URIs.

        Args:
            conversation: The historical conversation.
            system_prompt: The system prompt.
            prompt: The latest user prompt.

        Returns:
            List[Dict[str, Any]]: Messages with images converted to Claude's format.
        """
        messages = super()._build_messages_from_conversation(conversation, system_prompt, prompt)

        try:
            if not any("images" in msg for msg in messages):
                return messages

            for msg in messages:
                if msg.get("role") == "user" and "images" in msg:
                    image_list = msg.pop("images")
                    image_blocks = []
                    for img_source in image_list:
                        img_block = self._process_single_image_source(img_source)
                        if img_block:
                            image_blocks.append(img_block)

                    if image_blocks:
                        if isinstance(msg["content"], str):
                            msg["content"] = [{"type": "text", "text": msg["content"]}]
                        # Claude recommends images before text for best results
                        msg["content"] = image_blocks + msg["content"]

            for msg in messages:
                msg.pop("images", None)

            return messages

        except Exception as e:
            logger.error(f"Critical error during Claude image processing: {e}\n{traceback.format_exc()}")
            for msg in messages:
                msg.pop("images", None)
                if msg["role"] == "user" and isinstance(msg.get("content"), list):
                    text_content = next(
                        (item.get("text", "") for item in msg["content"] if item.get("type") == "text"), "")
                    msg["content"] = text_content
            if messages and messages[-1].get("role") == "user":
                messages[-1]["content"] += "\n\n[System note: There was an error processing the provided image(s). I will respond based on the text alone.]"
            else:
                messages.append({"role": "user", "content": "[System note: There was an error processing the provided image(s). Please respond based on prior text.]"})
            return messages

    @staticmethod
    def _process_single_image_source(content: str) -> Optional[Dict]:
        """
        Converts a single image source string into a Claude API image content block.

        Claude's format:
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}

        Supported input formats:
        - Data URIs: "data:image/png;base64,iVBOR..."
        - Raw base64 strings (media type inferred as image/jpeg)
        - HTTP/HTTPS URLs: passed as URL source type

        Args:
            content: The string representing the image source.

        Returns:
            A Claude image content block dict, or None if unrecognized.
        """
        if content.startswith('data:image/'):
            match = re.match(r'^data:(image/[a-zA-Z0-9.+\-]+);base64,(.+)$', content)
            if match:
                media_type = match.group(1)
                data = match.group(2)
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data,
                    }
                }
            logger.warning("Could not parse data URI for Claude image block. Skipping.")
            return None

        if content.startswith('http://') or content.startswith('https://'):
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": content,
                }
            }

        # Treat the string as raw base64 if it looks structurally valid.
        # len >= 100 avoids false positives on short strings that happen to be
        # all alphanumeric. The character-set regex validates the base64 alphabet
        # and optional trailing padding (=, ==). % 4 == 0 is required because
        # base64 encodes groups of 3 bytes into 4 characters; any valid base64
        # string (padded) has a length that is a multiple of 4.
        if isinstance(content, str) and len(content) >= 100:
            if bool(re.match(r'^[A-Za-z0-9+/]+={0,2}$', content)) and len(content) % 4 == 0:
                media_type = "image/jpeg"
                try:
                    decoded_data = base64_module.b64decode(content)
                    from PIL import Image
                    with Image.open(io.BytesIO(decoded_data)) as image:
                        if image.format:
                            media_type = f"image/{image.format.lower()}"
                except Exception:
                    pass  # Fall back to image/jpeg default
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": content,
                    }
                }

        logger.warning(f"Skipping unrecognized image source for Claude: {content[:100]}...")
        return None

    def _parse_non_stream_response(self, response_json: Dict):
        """
        Extracts the generated text (and tool calls, if any) from a non-streaming
        Claude API response. Tool_use content blocks are converted to OpenAI format.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            Union[str, Dict[str, Any]]: Plain text string for text-only responses,
            or a dict with 'content', 'tool_calls', and 'finish_reason' keys when
            tool calls are present.
        """
        try:
            content_blocks = response_json.get('content')
            if content_blocks is None:
                raise KeyError("Missing 'content' key in response")

            if not content_blocks:
                return ""

            text_parts = []
            tool_calls = []
            for block in content_blocks:
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif block.get('type') == 'tool_use':
                    tool_calls.append({
                        'id': block.get('id', ''),
                        'type': 'function',
                        'function': {
                            'name': block.get('name', ''),
                            'arguments': json.dumps(block.get('input', {}))
                        }
                    })

            content = ''.join(text_parts)
            if tool_calls:
                stop_reason = response_json.get('stop_reason', 'tool_use')
                finish = "tool_calls" if stop_reason == "tool_use" else stop_reason
                return {
                    'content': content,
                    'tool_calls': tool_calls,
                    'finish_reason': finish
                }
            return content
        except (KeyError, TypeError):
            logger.error(f"Could not find content in Claude response: {response_json}")
            return ""
