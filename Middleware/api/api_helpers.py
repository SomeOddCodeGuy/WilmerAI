# /Middleware/api/api_helpers.py

import json
import logging
from typing import Dict, Any, Optional, Tuple

from Middleware.common import instance_global_variables
from Middleware.services.response_builder_service import ResponseBuilderService
from Middleware.utilities.config_utils import get_current_username, workflow_exists_in_shared_folder

logger = logging.getLogger(__name__)
response_builder = ResponseBuilderService()


def build_response_json(
        token: str,
        finish_reason: Optional[str] = None,
        current_username: Optional[str] = None,
        additional_fields: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
) -> str:
    """
    Constructs a response JSON payload based on the API type using the ResponseBuilderService.

    Args:
        token (str): The text content (token) to include in the response.
        finish_reason (Optional[str]): The reason for the response termination (e.g., 'stop').
        current_username (Optional[str]): Deprecated and not used.
        additional_fields (Optional[Dict[str, Any]]): Extra fields to merge into the final JSON response.
        request_id (Optional[str]): The unique identifier for the request.

    Returns:
        str: A JSON string representing the formatted response payload.
    """
    api_type = instance_global_variables.API_TYPE
    response = {}

    if api_type == "ollamagenerate":
        response = response_builder.build_ollama_generate_chunk(token, finish_reason, request_id)
    elif api_type == "ollamaapichat":
        response = response_builder.build_ollama_chat_chunk(token, finish_reason, request_id)
    elif api_type == "openaicompletion":
        response = response_builder.build_openai_completion_chunk(token, finish_reason)
    elif api_type == "openaichatcompletion":
        response = response_builder.build_openai_chat_completion_chunk(token, finish_reason)
    else:
        raise ValueError(f"Unsupported API type for streaming: {api_type}")

    if additional_fields:
        response.update(additional_fields)

    return json.dumps(response, ensure_ascii=False)


def _extract_content_from_parsed_json(parsed_json: dict) -> str:
    """
    Extracts text content from a parsed JSON dictionary.

    Args:
        parsed_json (dict): The parsed JSON dictionary from a streaming chunk.

    Returns:
        str: The extracted text content, or an empty string if not found.
    """
    if not isinstance(parsed_json, dict):
        return ""

    content = ""
    # 1. Try OpenAI format (choices[0].delta.content or choices[0].text)
    choices = parsed_json.get('choices', [])
    if choices and isinstance(choices, list) and len(choices) > 0:
        # First try delta.content (chat completion format)
        delta = choices[0].get('delta', {})
        if isinstance(delta, dict):
            content = delta.get('content', '')

        # If no content found, try text field (legacy completion format)
        if not content:
            content = choices[0].get('text', '')

    # 2. If not found, try Ollama /generate format (response)
    if not content:
        content = parsed_json.get('response', '')

    # 3. If not found, try Ollama /chat format (message.content)
    if not content:
        message_data = parsed_json.get('message')
        if isinstance(message_data, dict):
            content = message_data.get('content', '')

    return content


def extract_text_from_chunk(chunk) -> str:
    """
    Extracts text content from a streaming response chunk.

    Args:
        chunk: The incoming data chunk, which can be a string, dictionary, or other type.

    Returns:
        str: The extracted text content from the chunk.
    """
    extracted = ""
    try:
        if chunk is None:
            return ""

        # Handle string chunks (potentially SSE or plain JSON)
        elif isinstance(chunk, str):
            parsed_json = None
            # Handle SSE data format ("data: {...}")
            if chunk.startswith('data:'):
                try:
                    json_content = chunk.replace('data:', '').strip()
                    # Avoid parsing the SSE [DONE] terminator
                    if json_content != '[DONE]':
                        parsed_json = json.loads(json_content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse SSE JSON content '{json_content}': {e}")
            # Handle plain JSON string format
            else:
                try:
                    # Avoid parsing empty strings which might occur
                    if chunk.strip():
                        parsed_json = json.loads(chunk.strip())
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse plain JSON string: {e}")

            if parsed_json is not None:
                extracted = _extract_content_from_parsed_json(parsed_json)

        # Handle dictionary chunks directly
        elif isinstance(chunk, dict):
            extracted = _extract_content_from_parsed_json(chunk)

    except Exception as e:
        # Log unexpected errors during processing
        logger.warning(f"Error processing chunk of type {type(chunk)}: {e}", exc_info=True)
        extracted = ""

    return extracted


def get_model_name():
    """
    Retrieves the current model name based on the username and active workflow.

    If a workflow override is active, returns "username:workflow".
    Otherwise, returns just the username.

    Returns:
        str: The model identifier in format "username" or "username:workflow".
    """
    username = get_current_username()
    workflow = instance_global_variables.WORKFLOW_OVERRIDE
    if workflow:
        return f"{username}:{workflow}"
    return username


def parse_model_field(model_value: Optional[str]) -> Optional[str]:
    """
    Parses the model field from an API request and extracts the workflow name.

    Handles the following formats:
    - "username:workflow" -> returns "workflow"
    - "workflow" (if it exists in shared folder) -> returns "workflow"
    - Anything else -> returns None (use normal routing)

    Args:
        model_value (Optional[str]): The model field value from the request.

    Returns:
        Optional[str]: The workflow name if found, None otherwise.
    """
    if not model_value:
        return None

    # Strip any :latest suffix that Ollama might add
    if model_value.endswith(':latest'):
        model_value = model_value[:-7]

    # Check for "username:workflow" format
    if ':' in model_value:
        parts = model_value.split(':', 1)
        if len(parts) == 2:
            workflow_name = parts[1]
            if workflow_exists_in_shared_folder(workflow_name):
                return workflow_name

    # Check if the model value itself is a workflow name
    if workflow_exists_in_shared_folder(model_value):
        return model_value

    return None


def set_workflow_override(model_value: Optional[str]) -> None:
    """
    Parses the model field and sets the workflow override global variable.

    This should be called at the start of request processing to set up
    the workflow override for the current request.

    Args:
        model_value (Optional[str]): The model field value from the request.
    """
    workflow = parse_model_field(model_value)
    instance_global_variables.WORKFLOW_OVERRIDE = workflow
    if workflow:
        logger.info(f"Workflow override set from model field: {workflow}")


def clear_workflow_override() -> None:
    """
    Clears the workflow override global variable.

    This should be called at the end of request processing to clean up.
    """
    instance_global_variables.WORKFLOW_OVERRIDE = None


def get_active_workflow_override() -> Optional[str]:
    """
    Gets the currently active workflow override.

    Returns:
        Optional[str]: The workflow name if override is active, None otherwise.
    """
    return instance_global_variables.WORKFLOW_OVERRIDE


def sse_format(data: str, output_format: str) -> str:
    """
    Formats a data string for Server-Sent Events (SSE).

    Args:
        data (str): The data string to format.
        output_format (str): The format of the API response (e.g., 'ollamagenerate').

    Returns:
        str: The formatted SSE string.
    """
    if output_format == 'ollamagenerate' or output_format == 'ollamaapichat':
        return f"{data}\n"
    else:
        return f"data: {data}\n\n"


def remove_assistant_prefix(response_text: str) -> str:
    """
    Removes the 'Assistant:' prefix from a response string.

    Args:
        response_text (str): The response text to be processed.

    Returns:
        str: The cleaned response text.
    """
    # Strip leading whitespace first to normalize
    response_text = response_text.lstrip()

    if response_text.startswith("Assistant:"):
        response_text = response_text[len("Assistant:"):].lstrip()

    return response_text
