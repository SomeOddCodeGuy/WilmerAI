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

def _extract_content_from_parsed_json(parsed_json: dict) -> str:
    """Extracts text content from a parsed JSON dictionary, checking known formats."""
    if not isinstance(parsed_json, dict):
        return ""
    
    content = ""
    # 1. Try OpenAI format (choices[0].delta.content)
    choices = parsed_json.get('choices', [])
    if choices and isinstance(choices, list) and len(choices) > 0:
        delta = choices[0].get('delta', {})
        if isinstance(delta, dict):
            content = delta.get('content', '')

    # 2. If not found, try Ollama format (response)
    if not content:
        content = parsed_json.get('response', '')

    # 3. If not found, try message format (message.content)
    if not content:
        message_data = parsed_json.get('message')
        if isinstance(message_data, dict):
            content = message_data.get('content', '')
            
    return content
    
def extract_text_from_chunk(chunk) -> str:
    """Extract text content from a chunk, handling various data types."""
    extracted = ""
    try:
        # Handle None
        if chunk is None:
            return ""
            
        # Handle string chunks (potentially SSE or plain JSON)
        elif isinstance(chunk, str):
            parsed_json = None
            # Handle SSE data format ("data: {...}")
            if chunk.startswith('data:'):
                try:
                    json_content = chunk.replace('data:', '').strip()
                    if json_content != '[DONE]': # Avoid parsing [DONE]
                        parsed_json = json.loads(json_content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse SSE JSON content '{json_content}': {e}")
            # Handle plain JSON string format ("({...}"))
            else:
                try:
                    # Avoid parsing empty strings which might occur
                    if chunk.strip(): 
                         parsed_json = json.loads(chunk.strip()) 
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse plain JSON string: {e}")
            
            # Extract content using the helper if JSON was parsed
            if parsed_json is not None:
                extracted = _extract_content_from_parsed_json(parsed_json)

        # Handle dictionary chunks directly
        elif isinstance(chunk, dict):
            extracted = _extract_content_from_parsed_json(chunk)
            
        # Other types (int, etc.) will result in the default empty string
            
    except Exception as e:
        # Log unexpected errors during processing
        logger.warning(f"Error processing chunk of type {type(chunk)}: {e}", exc_info=True)
        extracted = ""
    
    return extracted


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
