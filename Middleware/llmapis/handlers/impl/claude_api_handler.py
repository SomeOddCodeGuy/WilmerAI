# middleware/llmapis/handlers/impl/claude_api_handler.py
import base64
import io
import json
import logging
import re
from typing import Dict, Optional, Any, List

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler
from Middleware.llmapis.handlers.base.image_injection import inject_images_into_messages
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
                 max_tokens, dont_include_model: bool = False, suppress_retries: bool = False):
        super().__init__(
            base_url=base_url, api_key=api_key, gen_input=gen_input, model_name=model_name,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            },
            stream=stream, api_type_config=api_type_config, endpoint_config=endpoint_config,
            max_tokens=max_tokens, dont_include_model=dont_include_model,
            suppress_retries=suppress_retries
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
        except (json.JSONDecodeError, AttributeError):
            # AttributeError covers a data line whose JSON parses to a non-dict
            # (e.g. "data: 123"); every dict access above uses .get, so KeyError
            # cannot occur. Malformed chunks are skipped, not fatal.
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
    def _parse_tool_arguments(arguments) -> Dict[str, Any]:
        """
        Parses tool-call arguments into the object Claude requires as tool_use input.

        Args:
            arguments: The arguments value from an OpenAI-format tool call; a JSON
                string in OpenAI's wire format, but a dict is accepted as-is.

        Returns:
            Dict[str, Any]: The parsed arguments object; empty on missing or
            unparseable input (logged), since Claude rejects non-object input.
        """
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str) and arguments.strip():
            try:
                parsed = json.loads(arguments)
                if isinstance(parsed, dict):
                    return parsed
                logger.warning("Tool-call arguments parsed to a non-object; sending empty input to Claude.")
            except json.JSONDecodeError:
                logger.warning("Tool-call arguments were not valid JSON; sending empty input to Claude.")
        return {}

    @staticmethod
    def _convert_tool_messages_for_claude(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Converts OpenAI-format tool-calling turns into Claude's native structure.

        The ingestion side of Wilmer keeps tool traffic in OpenAI's format: an
        assistant message carries a ``tool_calls`` list and each result arrives as
        a ``role: "tool"`` message. The Anthropic Messages API accepts neither;
        it wants tool calls as ``tool_use`` content blocks on the assistant turn
        and results as ``tool_result`` blocks at the start of the following user
        turn. Without this conversion the second request of any tool loop (the
        one that replays the call and its result) is rejected with a 400.

        Conversions applied:
        - assistant + ``tool_calls`` -> assistant whose content is a block list:
          existing text first, then one ``tool_use`` block per call.
        - ``role: "tool"`` -> user message holding a ``tool_result`` block;
          consecutive results merge into one user turn.
        - a plain user message immediately following tool results merges into
          that same user turn (results must lead the turn), keeping roles
          alternating.

        All other messages pass through untouched.

        Args:
            messages (List[Dict[str, Any]]): Messages in the internal (OpenAI-style)
                format.

        Returns:
            List[Dict[str, Any]]: Messages restructured for the Claude API.
        """

        def _previous_tool_result_turn():
            previous = converted[-1] if converted else None
            if (isinstance(previous, dict) and previous.get("role") == "user"
                    and isinstance(previous.get("content"), list)
                    and any(isinstance(block, dict) and block.get("type") == "tool_result"
                            for block in previous["content"])):
                return previous
            return None

        converted: List[Dict[str, Any]] = []
        for message_index, msg in enumerate(messages):
            if not isinstance(msg, dict):
                converted.append(msg)
                continue
            role = msg.get("role")
            tool_calls = msg.get("tool_calls")

            if role == "assistant" and "tool_calls" in msg \
                    and not (isinstance(tool_calls, list) and tool_calls):
                # An empty/None tool_calls key is OpenAI-format residue some
                # clients emit on every assistant turn. It carries no calls to
                # convert, but Claude rejects unknown message fields, so the
                # key must be stripped rather than passed through.
                converted.append({k: v for k, v in msg.items() if k != "tool_calls"})
                continue

            if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
                blocks = []
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    blocks.extend(content)
                for call_index, tool_call in enumerate(tool_calls):
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") or {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tool_call.get("id") or f"toolcall_{message_index}_{call_index}",
                        "name": function.get("name", ""),
                        "input": ClaudeApiHandler._parse_tool_arguments(function.get("arguments")),
                    })
                converted.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                content = msg.get("content")
                block = {
                    "type": "tool_result",
                    "tool_use_id": str(msg.get("tool_call_id") or "unknown"),
                    "content": content if isinstance(content, str) else str(content or ""),
                }
                existing_turn = _previous_tool_result_turn()
                if existing_turn is not None:
                    # Anthropic requires tool_result blocks to lead the user
                    # turn; a merged plain-user text block may already sit in
                    # this turn (tool -> user -> tool interleave), so insert
                    # before the first non-tool_result block rather than append.
                    content_blocks = existing_turn["content"]
                    insert_at = next(
                        (i for i, existing_block in enumerate(content_blocks)
                         if not (isinstance(existing_block, dict)
                                 and existing_block.get("type") == "tool_result")),
                        len(content_blocks))
                    content_blocks.insert(insert_at, block)
                else:
                    converted.append({"role": "user", "content": [block]})
                continue

            if role == "user":
                existing_turn = _previous_tool_result_turn()
                if existing_turn is not None:
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        existing_turn["content"].append({"type": "text", "text": content})
                    elif isinstance(content, list):
                        existing_turn["content"].extend(content)
                    continue

            converted.append(msg)
        return converted

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
                         tool_choice=None, structured_output_schema: Optional[Dict] = None) -> Dict:
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

        # Convert OpenAI-format tool turns (assistant tool_calls / role "tool")
        # into Claude's tool_use / tool_result blocks. Must happen before the
        # role-based system extraction below so the converted turns are what
        # gets sent.
        messages = self._convert_tool_messages_for_claude(payload.get('messages', []))

        # Extract system messages from the messages array
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

        # Claude supports prefilling: trailing assistant messages are allowed and intentional
        # They guide Claude's response format (e.g., forcing JSON with "{")
        # Only string content is a prefill; a trailing assistant turn whose content
        # is a block list (e.g. converted tool_use blocks) is not.
        if non_system_messages and non_system_messages[-1].get('role') == 'assistant' \
                and isinstance(non_system_messages[-1].get('content'), str):
            prefill_content = non_system_messages[-1].get('content', '')
            sensitive_log(logger, logging.DEBUG, "Claude prefill detected: '%s...'", prefill_content[:100])
            # Validate: prefill cannot end with trailing whitespace
            if prefill_content != prefill_content.rstrip():
                sensitive_log(logger, logging.WARNING,
                             "Claude prefill content ends with whitespace, which may cause API errors. "
                             "Trimming whitespace from: '%s'", prefill_content)
                non_system_messages[-1]['content'] = prefill_content.rstrip()

        # tool_choice "none" means the client forbids tool use. Claude has no "none"
        # option, so the only way to honor it is to send neither tools nor tool_choice:
        # sending the tools would let Claude default to "auto" and call a tool the
        # client explicitly disallowed.
        if tools and tool_choice != "none":
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
        return inject_images_into_messages(
            messages,
            to_image_block=self._process_single_image_source,
            # Claude recommends images before text for best results
            images_first=True,
            api_label="Claude",
            missing_user_fallback_text=(
                "[System note: There was an error processing the provided image(s). "
                "Please respond based on prior text.]"
            ),
        )

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
        if len(content) >= 100 and len(content) % 4 == 0 and re.match(r'^[A-Za-z0-9+/]+={0,2}$', content):
            media_type = "image/jpeg"
            try:
                decoded_data = base64.b64decode(content)
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
        except (KeyError, TypeError, AttributeError):
            # AttributeError covers malformed content blocks that are not dicts
            # (e.g. a list of strings), which .get access would otherwise escape.
            logger.error(f"Could not find content in Claude response: {response_json}")
            return ""
