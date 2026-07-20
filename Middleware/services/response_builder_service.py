# Middleware/services/response_builder_service.py

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from Middleware.common import instance_global_variables
from Middleware.utilities import config_utils

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Returns the current UTC time in Ollama's ISO format with a Z suffix.

    Returns:
        str: The current UTC timestamp, e.g. ``2024-11-23T00:00:00.000000Z``.
    """
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


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
        # Lazy import to break circular dependency with api_helpers
        from Middleware.api import api_helpers
        return api_helpers.get_model_name()

    # --- OpenAI Compatible Responses ---

    def _get_configured_users(self) -> list:
        """
        Returns the list of configured users, falling back to the current username.

        Returns:
            list: List of username strings.
        """
        users = instance_global_variables.USERS
        if users:
            return list(users)
        return [config_utils.get_current_username()]

    def _get_shared_folder_for_user(self, user_config) -> str:
        """
        Resolves the shared workflows folder name from a specific user's config.

        Args:
            user_config (dict): The loaded user configuration dictionary.

        Returns:
            str: The shared workflows folder name for that user.
        """
        override = config_utils.get_config_property_if_exists('sharedWorkflowsSubDirectoryOverride', user_config)
        return override if override else '_shared'

    def _enumerate_model_ids(self) -> List[str]:
        """
        Lists the model ids Wilmer advertises, aggregated across configured users.

        For each user, if allowSharedWorkflows is enabled, their shared workflows
        are listed as ``username:workflow``; otherwise (including when the user's
        config cannot be loaded, which is logged) the bare username is listed.

        Returns:
            List[str]: The advertised model id strings.
        """
        model_ids = []
        for username in self._get_configured_users():
            user_ids = []
            try:
                user_config = config_utils.get_user_config_for(username)
                allow_shared = config_utils.get_config_property_if_exists('allowSharedWorkflows', user_config)
                if allow_shared:
                    shared_folder = self._get_shared_folder_for_user(user_config)
                    workflows = config_utils.get_available_shared_workflows(shared_folder_override=shared_folder)
                    user_ids = [f"{username}:{workflow}" for workflow in workflows]
            except Exception as e:
                logger.warning(f"Could not load config for user '{username}': {e}")

            model_ids.extend(user_ids if user_ids else [username])
        return model_ids

    def build_openai_models_response(self) -> Dict[str, Any]:
        """
        Builds the response payload for the OpenAI-compatible /v1/models endpoint.

        In multi-user mode, aggregates models from all configured users.
        For each user, if allowSharedWorkflows is enabled, lists their shared
        workflows as username:workflow. Otherwise lists just the username.

        Returns:
            Dict[str, Any]: A dictionary representing the list of available models.
        """
        current_time = int(time.time())
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": current_time,
                    "owned_by": "Wilmer"
                }
                for model_id in self._enumerate_model_ids()
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

    def build_openai_chat_completion_response(self, full_text: str, tool_calls=None) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the OpenAI-compatible /v1/chat/completions endpoint.

        Args:
            full_text (str): The complete generated text from the LLM.
            tool_calls: Optional list of tool call objects to include in the message.

        Returns:
            Dict[str, Any]: The complete, non-streaming chat response object.
        """
        current_time = int(time.time())
        message = {
            "role": "assistant",
            "content": full_text,
        }
        finish_reason = "stop"
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
            if not full_text:
                message["content"] = None
        return {
            "id": f"chatcmpl-{current_time}",
            "object": "chat.completion",
            "created": current_time,
            "model": self._get_model_name(),
            "system_fingerprint": "wmr_123456789",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "logprobs": None,
                    "finish_reason": finish_reason
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

    def build_openai_chat_completion_chunk(self, token: str, finish_reason: Optional[str],
                                              tool_calls=None) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the OpenAI-compatible /v1/chat/completions endpoint.

        Args:
            token (str): The token to include in the chunk's 'delta'.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.
            tool_calls: Optional list of tool call objects to include in the delta.

        Returns:
            Dict[str, Any]: A dictionary representing a single chat completion event stream chunk.
        """
        delta = {}
        if token:
            delta["content"] = token
        if tool_calls is not None:
            delta["tool_calls"] = tool_calls
        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self._get_model_name(),
            "system_fingerprint": "fp_44709d6fcb",
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "logprobs": None,
                    "finish_reason": finish_reason
                }
            ]
        }

    # --- Ollama Compatible Responses ---

    def build_ollama_tags_response(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Builds the response payload for the Ollama-compatible /api/tags endpoint.

        In multi-user mode, aggregates models from all configured users.
        For each user, if allowSharedWorkflows is enabled, lists their shared
        workflows as username:workflow. Otherwise lists just the username.

        Returns:
            Dict[str, List[Dict[str, Any]]]: A dictionary containing a list of available models.
        """
        return {
            "models": [
                {
                    "name": model_id,
                    "model": model_id + ":latest",
                    "modified_at": "2024-11-23T00:00:00Z",
                    "size": 1,
                    "digest": hashlib.sha256(model_id.encode('utf-8')).hexdigest(),
                    "details": {
                        "format": "gguf", "family": "wilmer", "families": None,
                        "parameter_size": "N/A", "quantization_level": "Q8"
                    }
                }
                for model_id in self._enumerate_model_ids()
            ]
        }

    def build_ollama_version_response(self) -> Dict[str, str]:
        """
        Builds the response payload for the Ollama-compatible /api/version endpoint.

        Returns:
            Dict[str, str]: A dictionary containing the version string.
        """
        return {"version": "0.9"}

    def build_ollama_generate_response(self, full_text: str, model: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the Ollama-compatible /api/generate endpoint.

        Args:
            full_text (str): The complete generated text from the LLM.
            model (str): The name of the model that generated the response.
            request_id (Optional[str]): The unique identifier for the request.

        Returns:
            Dict[str, Any]: The complete, non-streaming response object.
        """
        response = {
            "id": f"gen-{int(time.time())}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": model,
            "response": full_text,
            "done_reason": "stop",
            "done": True,
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
        if request_id:
            response["request_id"] = request_id
        return response

    @staticmethod
    def _convert_tool_calls_to_ollama_format(tool_calls: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """
        Converts tool calls to Ollama's native wire shape.

        Wilmer's internal tool-call format is OpenAI's ({"id", "type", "index",
        "function": {"name", "arguments": "<json string>"}}); Ollama clients
        expect {"function": {"name", "arguments": {...}}} with arguments as a
        JSON object. Entries already in native shape pass through unchanged, so
        the conversion is idempotent. Unparseable argument strings degrade to an
        empty object with a warning rather than failing the response.

        Args:
            tool_calls (Optional[List[Dict[str, Any]]]): Tool calls in OpenAI or
                Ollama-native format, or None.

        Returns:
            Optional[List[Dict[str, Any]]]: Ollama-native tool calls; None when
            the input is None, an empty list when it is empty.
        """
        if not tool_calls:
            return tool_calls
        converted = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments) if arguments.strip() else {}
                    arguments = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    logger.warning("Tool-call arguments were not valid JSON; sending empty "
                                   "arguments to the Ollama client.")
                    arguments = {}
            elif not isinstance(arguments, dict):
                arguments = {}
            converted.append({"function": {"name": function.get("name", ""), "arguments": arguments}})
        return converted

    def build_ollama_chat_response(self, full_text: str, model_name: str, request_id: Optional[str] = None,
                                       tool_calls=None) -> Dict[str, Any]:
        """
        Builds the final, non-streaming response for the Ollama-compatible /api/chat endpoint.

        Tool calls are converted to Ollama's native shape (arguments as a JSON
        object, no OpenAI envelope) before being attached to the message.

        Args:
            full_text (str): The complete generated text from the LLM.
            model_name (str): The name of the model that generated the response.
            request_id (Optional[str]): The unique identifier for the request.
            tool_calls: Optional list of tool call objects to include in the message.

        Returns:
            Dict[str, Any]: The complete, non-streaming chat response object.
        """
        message = {
            "role": "assistant",
            "content": full_text
        }
        if tool_calls is not None:
            message["tool_calls"] = self._convert_tool_calls_to_ollama_format(tool_calls)
        response = {
            "model": model_name,
            "created_at": _utc_now_iso(),
            "message": message,
            "done_reason": "stop",
            "done": True,
            "total_duration": 4505727700, "load_duration": 23500100,
            "prompt_eval_count": 15, "prompt_eval_duration": 4000000,
            "eval_count": 392, "eval_duration": 4476000000
        }
        if request_id:
            response["request_id"] = request_id
        return response

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
            "created_at": _utc_now_iso(),
            "message": {"role": "assistant", "content": ""},
            "done_reason": "stop",
            "done": True, "total_duration": 0, "load_duration": 0,
            "prompt_eval_count": 0, "prompt_eval_duration": 0,
            "eval_count": 0, "eval_duration": 0
        }

    # --- Ollama Compatible Streaming Chunks ---

    @staticmethod
    def _map_ollama_done_reason(finish_reason: Optional[str]) -> Optional[str]:
        """
        Maps an internal finish_reason to Ollama's done_reason vocabulary.

        Ollama only reports "stop" and "length" for completed generations, so
        every other terminal reason (e.g. "tool_calls") maps to "stop".

        Args:
            finish_reason (Optional[str]): The internal finish reason.

        Returns:
            Optional[str]: The Ollama done_reason, or None when the stream has
            not finished.
        """
        if finish_reason is None:
            return None
        return "length" if finish_reason == "length" else "stop"

    def build_ollama_generate_chunk(self, token: str, finish_reason: Optional[str], request_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the Ollama-compatible /api/generate endpoint.

        Any terminal finish_reason ("stop", "length", "tool_calls", ...) marks the
        chunk done; Ollama clients read the stream until they see done: true, so
        a stream that ends on a token cap or tool call must still signal done.

        Args:
            token (str): The token to include in the chunk's 'response' field.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.
            request_id (Optional[str]): The unique identifier for the request.

        Returns:
            Dict[str, Any]: A dictionary representing a single generate event stream chunk.
        """
        done = finish_reason is not None
        response = {
            "model": self._get_model_name(),
            "created_at": _utc_now_iso(),
            "response": token,
            "done": done
        }
        if done:
            response["done_reason"] = self._map_ollama_done_reason(finish_reason)
        if request_id:
            response["request_id"] = request_id
        return response

    def build_ollama_chat_chunk(self, token: str, finish_reason: Optional[str], request_id: Optional[str] = None,
                                   tool_calls=None) -> Dict[str, Any]:
        """
        Builds a single streaming chunk for the Ollama-compatible /api/chat endpoint.

        Any terminal finish_reason ("stop", "length", "tool_calls", ...) marks the
        chunk done; Ollama clients read the stream until they see done: true, so
        a stream that ends on a token cap or tool call must still signal done.

        Args:
            token (str): The token to include in the chunk's message content.
            finish_reason (Optional[str]): The reason the stream ended, if applicable.
            request_id (Optional[str]): The unique identifier for the request.
            tool_calls: Optional list of tool call objects to include in the message.

        Returns:
            Dict[str, Any]: A dictionary representing a single chat event stream chunk.
        """
        message = {
            "role": "assistant",
            "content": token
        }
        if tool_calls is not None:
            message["tool_calls"] = self._convert_tool_calls_to_ollama_format(tool_calls)
        done = finish_reason is not None
        response = {
            "model": self._get_model_name(),
            "created_at": _utc_now_iso(),
            "message": message,
            "done": done
        }
        if done:
            response["done_reason"] = self._map_ollama_done_reason(finish_reason)
        if request_id:
            response["request_id"] = request_id
        return response
