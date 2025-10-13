# middleware/llmapis/handlers/impl/claude_api_handler.py
import json
import logging
from typing import Dict, Optional, Any, List

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler

logger = logging.getLogger(__name__)


class ClaudeApiHandler(BaseChatCompletionsHandler):
    """
    Handles interactions with Anthropic's Claude API.

    This class extends `BaseChatCompletionsHandler` and is designed for the
    Anthropic Messages API. It handles the specific request and response schema
    for Claude, including streaming and non-streaming responses.
    """

    def __init__(self, base_url: str, api_key: str, gen_input: Dict[str, Any], model_name: str,
                 headers: Dict[str, str], stream: bool, api_type_config, endpoint_config,
                 max_tokens, dont_include_model: bool = False):
        """
        Initializes the Claude API handler with Claude-specific headers.

        Claude API requires different headers than OpenAI:
        - x-api-key instead of Authorization: Bearer
        - anthropic-version header is required
        """
        # Override headers with Claude-specific format
        claude_headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }

        # Call parent constructor with Claude-specific headers
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            gen_input=gen_input,
            model_name=model_name,
            headers=claude_headers,
            stream=stream,
            api_type_config=api_type_config,
            endpoint_config=endpoint_config,
            max_tokens=max_tokens,
            dont_include_model=dont_include_model
        )

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
        Specifies the SSE event name to filter for during streaming.

        Claude API sends multiple event types during streaming. We're interested
        in the 'content_block_delta' events which contain the actual text tokens.

        Returns:
            Optional[str]: The event name 'content_block_delta' to filter for.
        """
        return "content_block_delta"

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the Claude Messages API.

        Returns:
            str: The complete URL for the `/v1/messages` endpoint.
        """
        return f"{self.base_url.rstrip('/')}/v1/messages"

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON data chunk from a Claude API stream.

        This method is called for each 'data: ' line in the SSE stream that matches
        the 'content_block_delta' event. It loads the JSON string and extracts the
        text token from the delta structure.

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

            # Claude streaming sends different event types
            # content_block_delta events contain the actual text
            delta = chunk_data.get("delta", {})
            token = delta.get("text", "")

            # Claude doesn't send finish_reason in delta events
            # The stream ends with a message_stop event
            return {'token': token, 'finish_reason': None}
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"Could not parse Claude stream data string: {data_str}")
            return None

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the payload for Claude API with proper system message handling.

        Claude requires system messages to be sent as a separate 'system' parameter,
        not in the messages array. This method extracts system messages and formats
        them correctly. It also filters out unsupported parameters.

        Args:
            conversation: The conversation history
            system_prompt: The system prompt
            prompt: The user prompt

        Returns:
            Dict: The properly formatted payload for Claude API
        """
        # First get the standard payload from the parent
        payload = super()._prepare_payload(conversation, system_prompt, prompt)

        # Claude API supported parameters (as of 2025)
        # Ref: https://docs.anthropic.com/en/api/messages
        SUPPORTED_PARAMS = {
            'model', 'messages', 'max_tokens', 'system', 'temperature',
            'top_p', 'top_k', 'stream', 'stop_sequences', 'metadata', 'thinking'
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
            logger.debug(f"Claude prefill detected: '{prefill_content[:100]}...'")
            # Validate: prefill cannot end with trailing whitespace
            if prefill_content != prefill_content.rstrip():
                logger.warning(f"Claude prefill content ends with whitespace, which may cause API errors. "
                             f"Trimming whitespace from: '{prefill_content}'")
                non_system_messages[-1]['content'] = prefill_content.rstrip()

        return payload

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        """
        Extracts the generated text from a non-streaming Claude API response.

        This method navigates the JSON structure of a complete Claude response
        to find and return the main message content.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            str: The extracted text content from the content blocks,
            or an empty string if not found.
        """
        try:
            # Claude returns content as an array of content blocks
            # Each block has a "type" and "text" field
            content_blocks = response_json.get('content')
            if content_blocks is None:
                raise KeyError("Missing 'content' key in response")

            if not content_blocks:
                return ""

            # Concatenate all text blocks
            text_parts = []
            for block in content_blocks:
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))

            return ''.join(text_parts)
        except (KeyError, TypeError):
            logger.error(f"Could not find content in Claude response: {response_json}")
            return ""
