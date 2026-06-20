# Middleware/llmapis/handlers/impl/litellm_api_handler.py

"""
LiteLLM API handler using the LiteLLM Python SDK.

Routes requests through litellm.completion() which supports 100+ LLM providers
(Anthropic, Bedrock, Vertex, Gemini, Cohere, Mistral, etc.) natively without
requiring a separate proxy server.
"""

import json
import logging
from typing import Any, Dict, Generator, List, Optional, Union

from Middleware.llmapis.handlers.base.base_llm_api_handler import LlmApiHandler

logger = logging.getLogger(__name__)


class LiteLLMApiHandler(LlmApiHandler):
    """
    Handles LLM interactions via the LiteLLM Python SDK.

    Uses litellm.completion() directly, supporting any model string LiteLLM
    understands (e.g. anthropic/claude-sonnet-4-6, bedrock/claude-3.5-sonnet,
    gpt-4o, gemini/gemini-2.5-pro, etc.).

    The api_key and base_url from WilmerAI endpoint config are forwarded to
    litellm. If no api_key is set, litellm reads provider-specific env vars
    (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            import litellm
            self._litellm = litellm
        except ImportError as exc:
            raise RuntimeError(
                "litellm package is required for the litellmChatCompletion handler. "
                "Install it with: pip install litellm"
            ) from exc

    def _get_api_endpoint_url(self) -> str:
        return self.base_url

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str], *, tools: Optional[List[Dict]] = None,
                         tool_choice: Optional[Any] = None) -> Dict:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation:
            messages.extend(conversation)
        if prompt:
            messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": self.stream,
            "drop_params": True,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if self.gen_input.get("temperature") is not None:
            payload["temperature"] = self.gen_input["temperature"]
        if self.api_key:
            payload["api_key"] = self.api_key
        if self.base_url:
            payload["base_url"] = self.base_url
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        return payload

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return None

        choices = data.get("choices", [])
        if not choices:
            return None

        choice = choices[0]
        delta = choice.get("delta", {})
        content = delta.get("content", "")
        finish_reason = choice.get("finish_reason")

        if content or finish_reason:
            return {"token": content or "", "finish_reason": finish_reason}
        return None

    def _parse_non_stream_response(self, response_json: Dict) -> Union[str, Dict[str, Any]]:
        choices = response_json.get("choices", [])
        if not choices:
            return ""

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls")
        finish_reason = choice.get("finish_reason")

        if tool_calls:
            return {
                "content": content or "",
                "tool_calls": tool_calls,
                "finish_reason": finish_reason,
            }
        return content or ""

    def handle_non_streaming(self, conversation=None, system_prompt=None, prompt=None,
                             request_id=None, tools=None, tool_choice=None):
        payload = self._prepare_payload(conversation, system_prompt, prompt,
                                        tools=tools, tool_choice=tool_choice)
        model = payload.pop("model")
        messages = payload.pop("messages")
        stream = payload.pop("stream", False)

        response = self._litellm.completion(model=model, messages=messages, stream=False, **payload)
        response_json = response.model_dump()
        return self._parse_non_stream_response(response_json)

    def handle_streaming(self, conversation=None, system_prompt=None, prompt=None,
                         request_id=None, tools=None, tool_choice=None):
        payload = self._prepare_payload(conversation, system_prompt, prompt,
                                        tools=tools, tool_choice=tool_choice)
        model = payload.pop("model")
        messages = payload.pop("messages")
        payload.pop("stream", None)

        response = self._litellm.completion(model=model, messages=messages, stream=True, **payload)
        for chunk in response:
            data = chunk.model_dump()
            choices = data.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta", {})
            content = delta.get("content", "")
            finish_reason = choice.get("finish_reason")
            if content or finish_reason:
                yield {"token": content or "", "finish_reason": finish_reason}
