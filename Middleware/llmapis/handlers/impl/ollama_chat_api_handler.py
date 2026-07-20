# middleware/llmapis/handlers/impl/ollama_chat_api_handler.py
import json
import logging
import uuid
from typing import Dict, List, Optional, Any, Union

from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler
from Middleware.utilities.sensitive_logging_utils import sensitive_log_lazy, log_prompt_content
from Middleware.utilities.text_utils import return_brackets, strip_data_uri_prefix

logger = logging.getLogger(__name__)


class OllamaChatHandler(BaseChatCompletionsHandler):
    """
    Handles interactions with the Ollama Chat API.

    This class extends `BaseChatCompletionsHandler` to adapt the chat
    completion logic specifically for the Ollama API format. It overrides
    methods to handle Ollama's unique payload structure, which uses an
    'options' object for generation parameters, and its line-delimited JSON
    streaming format.

    This handler also supports multimodal conversations including images.
    When image messages are present, they are extracted and attached to the
    last user message under the `images` key as required by the Ollama API.
    """

    @property
    def _iterate_by_lines(self) -> bool:
        """
        Specifies the streaming format; True for line-delimited JSON.

        Ollama sends responses as a stream of JSON objects, one per line.
        This property tells the base streaming handler to iterate line-by-line.

        Returns:
            bool: Returns True to enable line-by-line stream processing.
        """
        return True

    def _get_api_endpoint_url(self) -> str:
        """
        Constructs the full API endpoint URL for the Ollama chat request.

        Returns:
            str: The complete URL for the Ollama `/api/chat` endpoint.
        """
        return f"{self.base_url.rstrip('/')}/api/chat"

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str], *, tools: Optional[list] = None,
                         tool_choice=None, structured_output_schema: Optional[Dict] = None) -> Dict:
        """
        Prepares the Ollama-specific payload for the API request.

        This method overrides the base implementation to structure the payload
        as required by the Ollama API. It moves generation parameters into a
        nested 'options' dictionary. For non-streaming requests, it also
        explicitly adds '"stream": False' to the payload.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation.
            system_prompt (Optional[str]): A system-level instruction for the LLM.
            prompt (Optional[str]): The latest user prompt to be processed.
            tools (Optional[list]): Tool definitions in OpenAI format (Ollama uses the same format).
            tool_choice: Ignored; Ollama does not support tool_choice.

        Returns:
            Dict: The JSON payload ready to be sent to the Ollama API.
        """
        self.set_gen_input()
        messages = self._build_messages_from_conversation(conversation, system_prompt, prompt)

        # Ollama reads the reasoning toggle as a top-level "think" field; every other
        # generation parameter belongs under "options". A preset can therefore set
        # "think": false (or true) and the handler lifts it out of options to the top level.
        # The stream flag injected by set_gen_input is likewise a top-level transport
        # field, not a valid Ollama option, so it must not ride along inside "options".
        options = dict(self.gen_input or {})
        think = options.pop("think", None)
        if self.stream_property_name:
            options.pop(self.stream_property_name, None)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "options": options
        }

        if think is not None:
            payload["think"] = think

        if not self.stream:
            payload["stream"] = False

        if tools:
            payload["tools"] = tools
        self._attach_structured_output(payload, structured_output_schema)

        logger.info(f"Payload prepared for {self.__class__.__name__}")
        sensitive_log_lazy(logger, logging.DEBUG, "URL: %s, Payload: %s",
                          lambda: self.base_url, lambda: json.dumps(payload, indent=2))
        return payload

    @staticmethod
    def _convert_tool_calls_to_openai_format(tool_calls_data: List[Dict[str, Any]],
                                             start_index: int = 0) -> List[Dict[str, Any]]:
        """
        Converts Ollama tool_calls entries to OpenAI-format tool call dicts.

        Ollama returns tool calls without ids or indexes; each converted entry
        gets a generated id and a list position as the index, with arguments
        JSON-serialized as OpenAI clients expect.

        Args:
            tool_calls_data (List[Dict[str, Any]]): The tool_calls list from an
                Ollama message.
            start_index (int): The index of the first converted entry. Streaming
                passes a running offset so distinct calls from different chunks
                never share an index; index-keyed delta accumulation (ours and
                OpenAI clients') would otherwise merge them into one garbled call.

        Returns:
            List[Dict[str, Any]]: The tool calls in OpenAI format.
        """
        openai_tool_calls = []
        for i, tc in enumerate(tool_calls_data):
            func = tc.get("function", {})
            openai_tool_calls.append({
                "index": start_index + i,
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": func.get("name", ""),
                    "arguments": json.dumps(func.get("arguments", {}))
                }
            })
        return openai_tool_calls

    def _build_messages_from_conversation(self,
                                          conversation: Optional[List[Dict[str, Any]]],
                                          system_prompt: Optional[str],
                                          prompt: Optional[str]) -> List[Dict[str, Any]]:
        """
        Constructs the message list, handling and embedding image data when present.

        This method overrides the base implementation to correctly format a
        conversation that includes images for the Ollama API. It checks each
        message for a per-message `images` key containing base64-encoded image
        data and preserves it on the corresponding message under the `images`
        key. This prepares the payload for a multimodal request.

        Image data is normalized via `strip_data_uri_prefix` so that data URIs
        ingested from the OpenAI endpoint are converted to the raw base64 that
        the Ollama API expects.

        Args:
            conversation (Optional[List[Dict[str, Any]]]): The historical conversation,
                which may include dictionaries representing images.
            system_prompt (Optional[str]): The system prompt to guide the LLM's behavior.
            prompt (Optional[str]): The latest user prompt.

        Returns:
            List[Dict[str, Any]]: The formatted list of messages, where the last
            user message may contain an `images` key with a list of image data.
        """
        if conversation is None:
            conversation = []
            if system_prompt:
                conversation.append({"role": "system", "content": system_prompt})
            if prompt:
                conversation.append({"role": "user", "content": prompt})

        corrected_conversation: List[Dict[str, Any]] = [
            {**msg, "role": "system" if msg["role"] == "systemMes" else msg["role"]}
            for msg in conversation
        ]

        # Apply the same addTextToStartOf{System,Prompt,Completion} /
        # ensureTextAddedToAssistantWhenChatCompletion injections the base builder
        # applies (and drop the empty trailing assistant marker) so these endpoint
        # options are honored on ollamaApiChat, not just OpenAI-chat.
        corrected_conversation = self._apply_prompt_injections(corrected_conversation)

        for msg in corrected_conversation:
            if msg.get("role") != "user":
                msg.pop("images", None)
            elif "images" in msg:
                msg["images"] = [strip_data_uri_prefix(img) for img in msg["images"]]

        return_brackets(corrected_conversation)

        full_prompt_log = "\n".join(
            str(msg.get("content", "")) for msg in corrected_conversation if msg.get("content")
        )
        log_prompt_content(logger, "Formatted_Prompt", full_prompt_log)

        return corrected_conversation

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses a single JSON object from the Ollama streaming response.

        Each line from the Ollama stream is a JSON string. This method loads
        that string and extracts the content token and finish reason.

        Args:
            data_str (str): A string containing a single JSON object from the stream.

        Returns:
            Optional[Dict[str, Any]]: A dictionary with 'token' and 'finish_reason'
            keys, or None if parsing fails.
        """
        try:
            if not data_str:
                return None

            chunk_data = json.loads(data_str)
            message = chunk_data.get("message", {})
            token = message.get("content", "")

            is_done = chunk_data.get("done", False)
            finish_reason = "stop" if is_done else None

            result = {'token': token, 'finish_reason': finish_reason}
            tool_calls_data = message.get("tool_calls")
            if tool_calls_data:
                offset = getattr(self, "_stream_tool_call_index_offset", 0)
                converted = self._convert_tool_calls_to_openai_format(tool_calls_data,
                                                                      start_index=offset)
                self._stream_tool_call_index_offset = offset + len(converted)
                result['tool_calls'] = converted
            return result
        except (json.JSONDecodeError, TypeError, AttributeError):
            # TypeError/AttributeError cover chunks whose JSON parses to a non-dict,
            # or malformed message/tool_calls entries; malformed chunks are skipped,
            # not fatal to the stream.
            logger.warning(f"Could not parse Ollama stream data string: {data_str}")
            return None

    def _parse_non_stream_response(self, response_json: Dict) -> Union[str, Dict[str, Any]]:
        """
        Extracts the generated text from a non-streaming Ollama API response.

        This method navigates the JSON structure of a complete Ollama response
        to find and return the main message content. When tool calls are present,
        converts them to OpenAI format and returns a dictionary.

        Args:
            response_json (Dict): The parsed JSON dictionary from the API response.

        Returns:
            Union[str, Dict[str, Any]]: The extracted text content, a dictionary
            with 'content', 'tool_calls', and 'finish_reason' keys when tool calls
            are present, or an empty string if not found.
        """
        try:
            message = response_json['message']
            content = message.get('content') or ""
            tool_calls_data = message.get('tool_calls')
            if tool_calls_data:
                return {
                    'content': content,
                    'tool_calls': self._convert_tool_calls_to_openai_format(tool_calls_data),
                    'finish_reason': 'tool_calls'
                }
            return content
        except (KeyError, TypeError, AttributeError):
            # AttributeError covers a non-dict 'message' value; nothing in the try
            # block indexes by position, so IndexError was unreachable.
            logger.error(f"Could not find content in Ollama response: {response_json}")
            return ""