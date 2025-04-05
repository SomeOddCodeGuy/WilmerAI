import json
import logging
import time
import uuid
from typing import Dict, Any, Optional

from Middleware.utilities import instance_utils
from Middleware.utilities.config_utils import get_current_username

logger = logging.getLogger(__name__)


def build_response_json(
        token: str,
        finish_reason: Optional[str] = None,
        current_username: Optional[str] = None,
        additional_fields: Optional[Dict[str, Any]] = None
) -> str:
    """
    Constructs the response JSON payload based on the API type.

    Args:
        token (str): The token string to include in the response.
        finish_reason (str, optional): The reason for finishing the response. Defaults to None.
        current_username (str, optional): The current username. If None, it fetches using get_current_username(). Defaults to None.
        additional_fields (Dict[str, Any], optional): Additional fields to include in the response. Defaults to None.

    Returns:
        str: The JSON string of the response payload.
    """
    if current_username is None:
        current_username = get_current_username()

    api_type = instance_utils.API_TYPE
    timestamp = int(time.time())
    created_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    response = {}

    if api_type == "ollamagenerate":
        response = {
            "model": get_model_name(),
            "created_at": created_at_iso,
            "response": token,
            "done": finish_reason == "stop"
        }

    elif api_type == "ollamaapichat":
        response = {
            "model": get_model_name(),
            "created_at": created_at_iso,
            "message": {
                "role": "assistant",
                "content": token
            },
            "done": finish_reason == "stop"
        }

    elif api_type == "openaicompletion":
        response = {
            "id": f"cmpl-{uuid.uuid4()}",
            "object": "text_completion",
            "created": timestamp,
            "choices": [
                {
                    "text": token,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": finish_reason if finish_reason else None
                }
            ],
            "model": get_model_name(),
            "system_fingerprint": "fp_44709d6fcb",
        }

    elif api_type == "openaichatcompletion":
        response = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion.chunk",
            "created": timestamp,
            "model": get_model_name(),
            "system_fingerprint": "fp_44709d6fcb",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token},
                    "logprobs": None,
                    "finish_reason": finish_reason if finish_reason else None
                }
            ]
        }

    else:
        raise ValueError(f"Unsupported API type: {api_type}")

    # Incorporate additional fields if provided
    if additional_fields:
        response.update(additional_fields)

    return json.dumps(response)


def extract_text_from_chunk(chunk) -> str:
    """Extract text content from a chunk, handling various data types.
    
    Args:
        chunk: The chunk to process, can be dict, string, int, or other types
        
    Returns:
        str: The extracted text content or empty string if no valid content found
    """
    try:
        # If chunk is None, return empty string
        if chunk is None:
            return ""
            
        # If chunk is a string, handle SSE data format
        if isinstance(chunk, str):
            if chunk.startswith('data:'):
                try:
                    chunk_json = json.loads(chunk.replace('data:', '').strip())
                    if isinstance(chunk_json, dict):
                        return chunk_json.get('message', {}).get('content', '')
                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse JSON: %s", str(e))
                    return ""
            return ""  # Return empty string for plain strings
            
        # If chunk is a dict, extract content from message
        if isinstance(chunk, dict):
            message = chunk.get('message')
            if isinstance(message, dict):
                return message.get('content', '')
            return ""
            
        # For numbers or other types, return empty string
        return ""
            
    except Exception as e:
        logger.warning("Error extracting text from chunk: %s", str(e))
        return ""


def get_model_name():
    return f"{get_current_username()}"


def sse_format(data: str, output_format: str) -> str:
    if output_format == 'ollamagenerate' or output_format == 'ollamaapichat':
        return f"{data}\n"
    else:
        return f"data: {data}\n\n"


def remove_assistant_prefix(response_text: str) -> str:
    """
    Remove the 'Assistant:' prefix from a response text if it exists.

    Args:
        response_text (str): The response text to process.

    Returns:
        str: The response text with 'Assistant:' removed, if it was present.
    """
    # Strip leading whitespace first to normalize
    response_text = response_text.lstrip()

    # Check if it starts with "Assistant:" and remove it
    if response_text.startswith("Assistant:"):
        response_text = response_text[len("Assistant:"):].lstrip()

    return response_text
