import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Generator, Tuple

from Middleware.utilities import instance_utils
from Middleware.utilities.config_utils import get_current_username
import requests

logger = logging.getLogger(__name__)


def build_response_json(
        token: str,
        api_type: str,
        finish_reason: Optional[str] = None,
        current_username: Optional[str] = None,
        additional_fields: Optional[Dict[str, Any]] = None
) -> str:
    """
    Constructs the response JSON payload based on the explicitly provided API type.

    Args:
        token (str): The token string to include in the response.
        api_type (str): The API type identifier (e.g., 'ollamaapichat', 'openaichatcompletion').
        finish_reason (str, optional): The reason for finishing the response. Defaults to None.
        current_username (str, optional): The current username. If None, it fetches using get_current_username(). Defaults to None.
        additional_fields (Dict[str, Any], optional): Additional fields to include in the response. Defaults to None.

    Returns:
        str: The JSON string of the response payload.
    """
    if current_username is None:
        current_username = get_current_username()

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
        # # Add timing/eval info ONLY to the final chunk
        # if finish_reason == "stop":
        #     response["total_duration"] = 5000000000 # Placeholder
        #     response["load_duration"] = 3000000    # Placeholder
        #     response["prompt_eval_count"] = 10       # Placeholder
        #     response["prompt_eval_duration"] = 300000000 # Placeholder
        #     response["eval_count"] = 5         # Placeholder
        #     response["eval_duration"] = 200000000  # Placeholder

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
        if finish_reason == "stop":
            response["total_duration"] = 5000000000
            response["load_duration"] = 3000000
            response["prompt_eval_count"] = 10
            response["prompt_eval_duration"] = 300000000
            response["eval_count"] = 5
            response["eval_duration"] = 200000000

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

    return json.dumps(response, ensure_ascii=False)


# === Helper Function for Content Extraction ===
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
# === End Helper Function ===

# === New Function for OpenAI Chat Extraction ===
def extract_openai_chat_content(chunk_data: dict) -> Tuple[str, Optional[str]]:
    """Extracts content and finish_reason specifically for OpenAI Chat Completion streams."""
    content = ""
    finish_reason = None
    choices = chunk_data.get("choices", [])
    if choices and isinstance(choices, list) and len(choices) > 0:
        delta = choices[0].get('delta', {})
        if isinstance(delta, dict):
            content = delta.get('content', '')
        finish_reason = choices[0].get("finish_reason") # Get potential finish_reason
    return content, finish_reason
# === End New Function ===

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


def sse_format(data: str, intended_api_type: str) -> str:
    """
    Formats the data string for Server-Sent Events based on the intended API type.
    OpenAI uses 'data: {json}\n\n'
    Ollama uses '{json}\n'
    """
    if intended_api_type in ['ollamagenerate', 'ollamaapichat']:
        # Ollama format: Just the JSON payload followed by a newline
        return f"{data}\n"
    else:
        # Default/OpenAI format: Standard SSE
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


def handle_sse_and_json_stream(
        response: requests.Response,
        extract_content_callback: callable,
        intended_api_type: str,
        strip_start_stop_line_breaks: bool,
        add_user_assistant: bool,
        add_missing_assistant: bool,
        max_buffer_length: int = 20
) -> Generator[str, None, None]:
    """
    Handles a streaming response that might contain Server-Sent Events (SSE)
    formatted lines ('data: {...}') or raw JSON objects separated by newlines.

    Args:
        response: The requests.Response object with stream=True.
        extract_content_callback: A function that takes a parsed JSON dict
                                  from a chunk and returns the extracted text content (str)
                                  or a tuple (content: str, finish_reason: Optional[str]).
        intended_api_type: The API type identifier for formatting the output (e.g., 'ollamaapichat').
        strip_start_stop_line_breaks: Boolean flag for processing first chunk.
        add_user_assistant: Boolean flag for processing first chunk.
        add_missing_assistant: Boolean flag for processing first chunk.
        max_buffer_length: Max length for the first chunk buffer.

    Yields:
        str: Formatted SSE strings suitable for the client.
    """
    buffer = ""
    start_time = time.time()
    total_tokens = 0
    full_response_text = ""
    yielded_first_token = False

    try:
        # Iterate over bytes chunks and decode them explicitly
        for chunk_bytes in response.iter_content(chunk_size=1024):
            chunk_str = chunk_bytes.decode('utf-8', errors='replace')
            buffer += chunk_str
            while True:
                data_str = None
                finish_reason_from_chunk = None

                # Check for standard SSE format first
                if "data:" in buffer:
                    data_pos = buffer.find("data:")
                    # Find the *next* newline character after "data:"
                    end_pos = buffer.find("\n", data_pos)
                    if end_pos == -1: break # Need more data
                    data_str = buffer[data_pos + 5:end_pos].strip()
                    buffer = buffer[end_pos + 1:] # Consume up to and including the newline
                    if data_str == '[DONE]': continue # Handled later
                # Check for raw JSON lines if no "data:" found
                elif "\n" in buffer:
                    end_pos = buffer.find("\n")
                    potential_json = buffer[:end_pos].strip()
                    # Basic check if it looks like JSON before assigning
                    if potential_json.startswith('{') and potential_json.endswith('}'):
                         data_str = potential_json
                    buffer = buffer[end_pos + 1:] # Consume up to and including the newline
                    if not data_str: continue # Skip empty lines or non-JSON lines
                # Need more data if neither format detected
                else:
                    break

                # --- Common Processing for extracted data_str ---
                if data_str:
                    try:
                        chunk_data = json.loads(data_str)
                        extracted_info = extract_content_callback(chunk_data)

                        if isinstance(extracted_info, tuple) and len(extracted_info) == 2:
                            token, finish_reason_from_chunk = extracted_info
                        elif isinstance(extracted_info, str):
                            token = extracted_info
                        else:
                            logger.warning(f"Unexpected return type from callback: {type(extracted_info)}...")
                            token = ""
                        

                        # --- Simplified Yielding Logic ---
                        if token: # Only process if the token has content
                            original_token_for_accumulation = token # Store before modification
                            if not yielded_first_token: 
                                # Apply stripping ONLY to the first non-empty token
                                if strip_start_stop_line_breaks:
                                    token = token.lstrip()
                                    if not token: continue # Skip if stripping made it empty
                                
                                # Apply prefix removal ONLY to the first non-empty token
                                if add_user_assistant and add_missing_assistant:
                                    if "Assistant:" in token:
                                        token = remove_assistant_prefix(token)
                                        if not token: continue # Skip if prefix removal made it empty
                                
                                # Set flag only after successfully processing/yielding the first token
                                if token: 
                                    yielded_first_token = True 
                            
                            # Yield if token still has content after potential first-token processing
                            if token: 
                                total_tokens += len(original_token_for_accumulation.split()) # Accumulate original token length
                                full_response_text += original_token_for_accumulation # Accumulate original token

                                completion_json = build_response_json(
                                    token=token,
                                    api_type=intended_api_type,
                                    finish_reason=None,
                                    current_username=get_current_username()
                                )
                                formatted_sse = sse_format(completion_json, intended_api_type)
                                yield formatted_sse
                        else:
                            logger.debug(f"Token was empty, skipping yield.")

                        if finish_reason_from_chunk == "stop":
                            logger.debug("Finish reason 'stop' detected in chunk, breaking inner loop.")
                            break
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON payload '{data_str}': {e}")
                        continue # Try next line
                    except Exception as e:
                        logger.error(f"Error during stream processing callback or chunk handling: {e}", exc_info=True)
                        continue # Skip problematic chunk
                else:
                    logger.debug("No data_str extracted in this loop iteration.")
            # --- End While True loop ---
        # --- End For Chunk loop ---
        logger.debug("Finished iterating through response content.")

        # --- End of stream processing ---
        total_duration = int((time.time() - start_time) * 1e9)

        # Log the full accumulated text
        logger.info("\n\n*****************************************************************************\n")
        logger.info("\n\nOutput from the LLM (streaming): %s", full_response_text)
        logger.info("\n*****************************************************************************\n\n")

        # Final message signaling end of stream
        final_completion_json = build_response_json(
            token="",
            api_type=intended_api_type,
            finish_reason="stop",  # Final payload explicitly includes "stop"
            current_username=get_current_username()
        )
        logger.debug("Total duration: %s", total_duration)
        yield sse_format(final_completion_json, intended_api_type)

        # Send [DONE] signal ONLY for OpenAI compatible streams.
        # Ollama streams terminate with the last JSON object having "done": true.
        if intended_api_type not in ['ollamagenerate', 'ollamaapichat']:
            logger.debug("End of stream reached for OpenAI type, sending [DONE] signal.")
            yield sse_format("[DONE]", intended_api_type)
        else:
            logger.debug("End of stream reached for Ollama type, not sending [DONE] signal.")

    except requests.RequestException as e:
        logger.error(f"Request failed during streaming: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during streaming setup or iteration: {e}", exc_info=True)
        raise # Re-raise unexpected errors
