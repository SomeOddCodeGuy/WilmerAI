# Middleware/services/response_builder_service.py

import hashlib
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from Middleware.api import api_helpers


class ResponseBuilderService:
    """
    Consolidates logic for creating API-specific JSON response payloads.

    This service acts as a single source of truth for all response formats
    (e.g., OpenAI, Ollama) for both streaming chunks and final non-streaming objects.
    """

    def _get_model_name(self) -> str:
        """
        Retrieves the model name from the API helper.

        Returns:
            str: The name of the model currently being used.
        """
        # This keeps the dependency on api_helpers local to the service
        return api_helpers.get_model_name()

    # --- OpenAI Compatible Responses ---

    def build_openai_models_response(self) -> Dict[str, Any]:
        """
        Builds the response payload for the OpenAI-compatible /v1/models endpoint.

        Returns:
            Dict[str, Any]: A dictionary representing the list of available models.
        """
        return {
            "object": "list",
            "data": [
                {
                    "id": self._get_model_name(),
                    "object": self._get_model_name(),
                    "created": int(time.time()),
                    "owned_by": "Wilmer"
                }
            ]
        }

    def build_openai_completion_response(self, full_text: str) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the OpenAI-compatible /v1/completions endpoint.

        Args:
            full_text (str): The complete generated text from the LLM.

        Returns:
            Dict[str, Any]: The complete, non-streaming response object.
        """
        current_time = int(time.time())
        return {
            "id": f"cmpl-{current_time}",
            "object": "text_completion",
            "created": current_time,
            "model": self._get_model_name(),
            "system_fingerprint": "wmr_123456789",
            "choices": [
                {
                    "text": full_text,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": "stop"
                }
            ],
            "usage": {}
        }

    def build_openai_chat_completion_response(self, full_text: str) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the OpenAI-compatible /v1/chat/completions endpoint.

        Args:
            full_text (str): The complete generated text from the LLM.

        Returns:
            Dict[str, Any]: The complete, non-streaming chat response object.
        """
        current_time = int(time.time())
        return {
            "id": f"chatcmpl-{current_time}",
            "object": "chat.completion",
            "created": current_time,
            "model": self._get_model_name(),
            "system_fingerprint": "wmr_123456789",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_text,
                    },
                    "logprobs": None,
                    "finish_reason": "stop"
                }
            ],
            "usage": {}
        }

    def build_openai_tool_call_response(self) -> Dict[str, Any]:
        """
        Builds an early response for an OpenAI-compatible tool selection request.

        Returns:
            Dict[str, Any]: A response object indicating a tool call is being made.
        """
        return {
            "id": f"chatcmpl-opnwui-tool-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self._get_model_name(),
            "system_fingerprint": "wmr_123456789",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": None, "tool_calls": []},
                    "logprobs": None,
                    "finish_reason": "tool_calls"
                }
            ],
            "usage": {}
        }

    # --- OpenAI Compatible Streaming Chunks ---

    def build_openai_completion_chunk(self, token: str, finish_reason: Optional[str]) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the OpenAI-compatible /v1/completions endpoint.

        Args:
            token (str): The token to include in the chunk's 'text' field.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.

        Returns:
            Dict[str, Any]: A dictionary representing a single text completion event stream chunk.
        """
        return {
            "id": f"cmpl-{uuid.uuid4()}",
            "object": "text_completion",
            "created": int(time.time()),
            "choices": [
                {
                    "text": token,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": finish_reason
                }
            ],
            "model": self._get_model_name(),
            "system_fingerprint": "fp_44709d6fcb",
        }

    def build_openai_chat_completion_chunk(self, token: str, finish_reason: Optional[str]) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the OpenAI-compatible /v1/chat/completions endpoint.

        Args:
            token (str): The token to include in the chunk's 'delta'.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.

        Returns:
            Dict[str, Any]: A dictionary representing a single chat completion event stream chunk.
        """
        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self._get_model_name(),
            "system_fingerprint": "fp_44709d6fcb",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token},
                    "logprobs": None,
                    "finish_reason": finish_reason
                }
            ]
        }

    # --- Ollama Compatible Responses ---

    def build_ollama_tags_response(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Builds the response payload for the Ollama-compatible /api/tags endpoint.

        Returns:
            Dict[str, List[Dict[str, Any]]]: A dictionary containing a list of available models.
        """
        model_name = self._get_model_name()
        return {
            "models": [
                {
                    "name": model_name,
                    "model": model_name + ":latest",
                    "modified_at": "2024-11-23T00:00:00Z",
                    "size": 1,
                    "digest": hashlib.sha256(model_name.encode('utf-8')).hexdigest(),
                    "details": {
                        "format": "gguf", "family": "wilmer", "families": None,
                        "parameter_size": "N/A", "quantization_level": "Q8"
                    }
                }
            ]
        }

    def build_ollama_version_response(self) -> Dict[str, str]:
        """
        Builds the response payload for the Ollama-compatible /api/version endpoint.

        Returns:
            Dict[str, str]: A dictionary containing the version string.
        """
        return {"version": "0.9"}

    def build_ollama_generate_response(self, full_text: str, model: str) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the Ollama-compatible /api/generate endpoint.

        Args:
            full_text (str): The complete generated text from the LLM.
            model (str): The name of the model that generated the response.

        Returns:
            Dict[str, Any]: The complete, non-streaming response object.
        """
        return {
            "id": f"gen-{int(time.time())}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": model,
            "response": full_text,
            "choices": [
                {
                    "text": full_text,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": "stop"
                }
            ],
            "usage": {}
        }

    def build_ollama_chat_response(self, full_text: str, model_name: str) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the Ollama-compatible /api/chat endpoint.

        Args:
            full_text (str): The complete generated text from the LLM.
            model_name (str): The name of the model that generated the response.

        Returns:
            Dict[str, Any]: The complete, non-streaming chat response object.
        """
        return {
            "model": model_name,
            "created_at": datetime.utcnow().isoformat() + 'Z',
            "message": {
                "role": "assistant",
                "content": full_text
            },
            "done_reason": "stop",
            "done": True,
            "total_duration": 4505727700, "load_duration": 23500100,
            "prompt_eval_count": 15, "prompt_eval_duration": 4000000,
            "eval_count": 392, "eval_duration": 4476000000
        }

    def build_ollama_tool_call_response(self, model_name: str) -> Dict[str, Any]:
        """
        Builds an early response for an Ollama-compatible tool selection request.

        Args:
            model_name (str): The name of the model handling the request.

        Returns:
            Dict[str, Any]: A response object indicating a tool call is being made.
        """
        return {
            "model": model_name,
            "created_at": datetime.utcnow().isoformat() + 'Z',
            "message": {"role": "assistant", "content": ""},
            "done_reason": "stop",
            "done": True, "total_duration": 0, "load_duration": 0,
            "prompt_eval_count": 0, "prompt_eval_duration": 0,
            "eval_count": 0, "eval_duration": 0
        }

    # --- Ollama Compatible Streaming Chunks ---

    def build_ollama_generate_chunk(self, token: str, finish_reason: Optional[str]) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the Ollama-compatible /api/generate endpoint.

        Args:
            token (str): The token to include in the chunk's 'response' field.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.

        Returns:
            Dict[str, Any]: A dictionary representing a single generate event stream chunk.
        """
        return {
            "model": self._get_model_name(),
            "created_at": datetime.utcnow().isoformat() + 'Z',
            "response": token,
            "done": finish_reason == "stop"
        }

    def build_ollama_chat_chunk(self, token: str, finish_reason: Optional[str]) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the Ollama-compatible /api/chat endpoint.

        Args:
            token (str): The token to include in the chunk's message content.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.

        Returns:
            Dict[str, Any]: A dictionary representing a single chat event stream chunk.
        """
        return {
            "model": self._get_model_name(),
            "created_at": datetime.utcnow().isoformat() + 'Z',
            "message": {
                "role": "assistant",
                "content": token
            },
            "done": finish_reason == "stop"
        }
