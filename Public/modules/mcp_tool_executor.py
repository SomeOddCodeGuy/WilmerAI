import json
import logging
import re
import requests
import os
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
import datetime
import sys

# Use absolute import
from Public.modules.mcp_service_discoverer import MCPServiceDiscoverer, DEFAULT_MCPO_URL
# Corrected relative import for mcp_prompt_utils
from .mcp_prompt_utils import _format_mcp_tools_for_llm_prompt, _integrate_tools_into_prompt

logger = logging.getLogger(__name__)

def Invoke(messages: List[Dict[str, str]], mcpo_url: str = DEFAULT_MCPO_URL, tool_execution_map: Dict = None) -> Dict:
    """
    Main entry point for the MCP Tool Executor module.
    
    This function:
    1. Extracts potential service names from the system prompt.
    2. Detects if LLM response contains a tool call.
    3. If it does, finds the correct service and executes the tool call.
    4. Returns the result.
    
    Args:
        messages: List of message dictionaries from the conversation.
        mcpo_url: Base URL for the MCPO server.
        tool_execution_map: Dictionary mapping operationId to execution details.
                            Example: { "opId": { "service": "svc", "path": "/p", "method": "post", ... } }
    
    Returns:
        Dict containing response, has_tool_call status, and tool_results if applicable.
    """
    logger.info(f"MCP Tool Executor invoked with {len(messages)} messages. MCPO URL: {mcpo_url}")
    
    # Note: Service name extraction and discovery are now part of prepare_system_prompt
    # We rely on the tool_execution_map being provided for execution.
    if not tool_execution_map:
         logger.warning("Invoke called without a tool_execution_map. Execution will fail if tool calls are present.")
         # Consider if we should *always* require a map or have a fallback discovery?
         # For now, we proceed but execution will likely error out if a call needs the map.

    assistant_message = None
    for message in reversed(messages):
        if message.get("role") == "assistant":
            assistant_message = message.get("content", "")
            logger.info(f"Found assistant message: {assistant_message[:500]}...")
            break
    
    if not assistant_message:
        logger.warning("No assistant message found in conversation")
        return {"response": "", "has_tool_call": False}
    
    logger.info("Checking for tool calls in assistant's response...")
    tool_calls = extract_tool_calls(assistant_message)
    
    if not tool_calls:
        logger.info("No tool calls found in assistant's response")
        return {"response": assistant_message, "has_tool_call": False}
    
    logger.info(f"Found {len(tool_calls)} tool calls")
    
    if not tool_execution_map:
        error_msg = "Tool calls found, but no tool_execution_map provided to execute them."
        logger.error(error_msg)
        # Return an error state, but acknowledge calls were *detected*
        # Set has_tool_call to True, as calls were indeed found, but signal error clearly.
        return {
            "response": assistant_message,
            "has_tool_call": True, # Calls were detected
            "tool_results": [], # No results could be generated
            "error": error_msg,
            "status": "execution_error" # Add a status for clarity
        }
    
    tool_results = []
    for idx, tool_call in enumerate(tool_calls):
        logger.info(f"Executing tool call {idx + 1}/{len(tool_calls)}: {tool_call.get('name', 'unknown')}")
        # Pass the provided mcpo_url and tool_execution_map
        result = execute_tool_call(tool_call, mcpo_url, tool_execution_map)
        tool_results.append({
            "tool_call": tool_call,
            "result": result
        })
        logger.info(f"Tool call {idx + 1} result: {result}")
    
    return {
        "response": assistant_message,
        "has_tool_call": True,
        "tool_results": tool_results
    }

def extract_tool_calls(text: str) -> List[Dict]:
    """
    Extract tool calls from LLM response text, robustly handling JSON embedded
    within other text, even without markdown fences.
    
    Args:
        text: The text to extract tool calls from
    
    Returns:
        List of tool call dictionaries
    """
    logger.info(f"Attempting to extract tool calls from text below: \n\n\n {text}\n\n\n")
    
    # Skip if text contains unsubstituted variables
    if re.search(r'\{\{[a-zA-Z0-9_]+\}\}', text):
        logger.warning("Text contains unsubstituted variables, skipping tool call extraction")
        return []
    
    cleaned_text = text
    if "|{{|" in text or "|}}|" in text or "|}}}|" in text:
        logger.warning("Found malformed JSON markers in text, cleaning up")
        cleaned_text = text.replace("|{{|", "{").replace("|}}}|", "}").replace("|}}|", "}")
        logger.info(f"Cleaned text: {cleaned_text[:100]}...")

    markdown_match = re.search(r"```json\s*({.*?})\s*```", cleaned_text, re.DOTALL)
    json_str = None
    if markdown_match:
        json_str = markdown_match.group(1).strip()
        logger.info("Extracted JSON content from markdown code fence.")
    else:
        # If no markdown fence, find the JSON object boundaries manually
        # Search for the start pattern: '{' potentially followed by whitespace, then '"tool_calls":'
        start_match = re.search(r'\{\s*"tool_calls"\s*:', cleaned_text)
        if start_match:
            start_index = start_match.start()
            logger.info(f"Found potential JSON start at index {start_index}")
            brace_level = 0
            end_index = -1
            for i in range(start_index, len(cleaned_text)):
                char = cleaned_text[i]
                if char == '{':
                    brace_level += 1
                elif char == '}':
                    brace_level -= 1
                    if brace_level == 0:
                        end_index = i + 1
                        break
            
            if end_index != -1:
                json_str = cleaned_text[start_index:end_index].strip()
                logger.info(f"Extracted potential JSON object by brace matching: {json_str[:200]}...")
            else:
                logger.warning("Found JSON start but could not find matching closing brace.")
        else:
            # Fallback: If start pattern not found, check if the entire cleaned text is the JSON object
            potential_json = cleaned_text.strip()
            if potential_json.startswith('{') and potential_json.endswith('}'):
                 try:
                     temp_obj = json.loads(potential_json)
                     if isinstance(temp_obj, dict) and "tool_calls" in temp_obj:
                         json_str = potential_json
                         logger.info("Assuming entire cleaned text is the JSON object after validation.")
                     else:
                         logger.info("Entire text is JSON, but lacks 'tool_calls'.")
                 except json.JSONDecodeError:
                     logger.info("Entire text looked like JSON but failed to parse.")

    if json_str is None:
        logger.info(f"Could not find valid JSON tool call structure in the assistant's response: {text[:500]}...")
        return []

    try:
        logger.info(f"Attempting json.loads on extracted string: {json_str[:200]}...")
        json_obj = json.loads(json_str)
        
        if isinstance(json_obj, dict) and "tool_calls" in json_obj and isinstance(json_obj["tool_calls"], list):
            validated_calls = []
            for call in json_obj["tool_calls"]:
                if isinstance(call, dict) and "name" in call and "parameters" in call:
                    validated_calls.append(call)
                else:
                    logger.warning(f"Invalid tool call object found in list: {call}")
            if validated_calls:
                 logger.info(f"Successfully parsed and validated {len(validated_calls)} tool calls.")
                 return validated_calls
            else:
                 logger.warning("Parsed JSON but found no valid tool calls in the 'tool_calls' list.")
                 return []
        else:
            logger.warning("Parsed JSON does not match expected structure: {'tool_calls': [...]}")
            return []
            
    except json.JSONDecodeError as e:
        logger.error(f"Final json.loads failed after extraction: {e}")
        return []

def format_error_response(error: str) -> Dict:
    """
    Format an error response in a consistent way.
    
    Args:
        error: Error message
    
    Returns:
        Dict containing formatted error
    """
    return {
        "error": error,
        "status": "error",
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat()
    }

def _perform_http_request(method: str, url: str, query_params: Dict, body_params: Optional[Dict], timeout: int = 900) -> Dict:
    """
    Performs the actual HTTP request and handles responses/errors.

    Args:
        method: HTTP method (get, post, put, delete, patch).
        url: The target URL.
        query_params: Dictionary of query parameters.
        body_params: Optional dictionary of body parameters (used for POST, PUT, PATCH).
        timeout: Request timeout in seconds. Default is 15 minutes, because some tools can take a long time to execute like LLM calls.

    Returns:
        A dictionary containing the result (parsed JSON or raw text) or an error structure.
    """
    logger.info(f"Executing {method.upper()} request to: {url} with query_params={query_params}, body_params={body_params}")
    
    try:
        supported_methods = ["get", "post", "put", "delete", "patch", "head", "options"]
        if method.lower() not in supported_methods:
            return format_error_response(f"Unsupported HTTP method '{method}'")

        response = requests.request(
            method=method, 
            url=url, 
            params=query_params, 
            json=body_params, 
            timeout=timeout
        )

        response.raise_for_status()

        try:
            result_json = response.json()
            logger.info(f"Tool executed successfully, received JSON response: {str(result_json)[:200]}...")
            return result_json
        except json.JSONDecodeError:
            response_text = response.text
            logger.warning(f"Tool executed, but response was not valid JSON. Returning raw text: {response_text[:200]}...")
            return {"status": "success_raw_text", "response_text": response_text}

    except requests.exceptions.Timeout:
        error_msg = f"Tool execution timed out after {timeout}s for {method.upper()} {url}"
        logger.error(error_msg)
        return format_error_response(error_msg)
    except requests.exceptions.HTTPError as e:
        error_detail = str(e)
        try:
             error_detail += f" - Response Body: {e.response.text[:500]}"
        except Exception:
            pass
        logger.error(f"Tool execution failed with HTTPError: {error_detail}")
        return format_error_response(f"Tool execution failed: {error_detail}")
    except requests.exceptions.RequestException as e:
        error_detail = str(e)
        logger.error(f"Tool execution failed with RequestException: {error_detail}")
        return format_error_response(f"Tool execution failed: {error_detail}")
    except Exception as e:
        # Catch unexpected errors during the request itself
        logger.exception(f"Unexpected error during HTTP request for {method.upper()} {url}")
        return format_error_response(f"Unexpected error during HTTP request: {str(e)}")

def _normalize_param_name(name: str) -> str:
    """Normalize parameter name for comparison (lowercase, remove underscores)."""
    return name.lower().replace("_", "")

def _build_tool_url(base_url: str, service: str, path: str) -> str:
    """
    Constructs the full URL for a tool endpoint.

    Args:
        base_url: The base MCPO URL (e.g., http://localhost:8889).
        service: The service name (e.g., time).
        path: The endpoint path (e.g., /current or /{userId}/info).

    Returns:
        The fully constructed URL string.
    """
    # Ensure no double slashes between mcpo_url and service name if mcpo_url ends with /
    clean_base_url = base_url.rstrip('/')
    # Ensure service name doesn't start with /
    clean_service = service.lstrip('/')
    # Ensure endpoint path starts with / if it's not empty
    clean_path = path if not path or path.startswith('/') else f'/{path}'
    
    # Handle case where service might be empty (e.g., root endpoint)
    if clean_service:
        return f"{clean_base_url}/{clean_service}{clean_path}"
    else:
        return f"{clean_base_url}{clean_path}"

def _prepare_request_params(parameters: Dict, execution_details: Dict) -> Tuple[Dict, Optional[Dict], Dict]:
    """
    Separates parameters into query, body, and path dictionaries based on execution_details
    derived from the OpenAPI schema. Prioritizes explicitly defined path/query parameters.
    Uses normalization (lowercase, no underscores) to match LLM parameter names against
    schema-defined names, but uses the original schema-defined name for the final request.

    Args:
        parameters: The raw parameters dictionary from the tool call.
        execution_details: Dictionary containing OpenAPI schema info like
                           'openapi_params' (list of parameter objects) and
                           'request_body_schema' (schema object).

    Returns:
        A tuple containing (query_params, body_params, path_params).
        body_params will be None if no request body is expected or populated.
    """
    query_params = {}
    body_params = None
    path_params = {}
    
    # --- Normalize schema parameter names for matching ---
    normalized_schema_params = {}
    openapi_params = execution_details.get("openapi_params", [])
    if openapi_params:
        for param_info in openapi_params:
            schema_name = param_info.get("name")
            if schema_name:
                normalized_name = _normalize_param_name(schema_name)
                # Store original info keyed by normalized name
                normalized_schema_params[normalized_name] = param_info

    # --- Iterate through LLM parameters and try to match ---
    llm_param_names = set(parameters.keys())
    assigned_param_names = set()

    for llm_name, llm_value in parameters.items():
        normalized_llm_name = _normalize_param_name(llm_name)

        if normalized_llm_name in normalized_schema_params:
            # Found a match based on normalized names
            param_info = normalized_schema_params[normalized_llm_name]
            schema_name = param_info.get("name") # Get the original schema name
            param_location = param_info.get("in")

            if param_location == "query":
                query_params[schema_name] = llm_value
                assigned_param_names.add(llm_name)
                logger.info(f"Mapped LLM param '{llm_name}' to query parameter '{schema_name}' via normalization.")
            elif param_location == "path":
                path_params[schema_name] = llm_value
                assigned_param_names.add(llm_name)
                logger.info(f"Mapped LLM param '{llm_name}' to path parameter '{schema_name}' via normalization.")
            # Add handling for 'header', 'cookie' if needed here
            # else:
            #     logger.warning(f"LLM param '{llm_name}' matched schema param '{schema_name}' but location '{param_location}' is unhandled.")
        # else: # Parameter not found in schema via normalization
            # logger.debug(f"LLM param '{llm_name}' not found in schema via normalization.")
            # Pass # Will be handled later for potential body assignment

    # 2. Process request body with remaining UNASSIGNED parameters, if schema exists
    if execution_details.get("request_body_schema"):
        logger.info("Request body schema found. Assigning remaining UNASSIGNED parameters to body.")
        body_candidate_names = llm_param_names - assigned_param_names
        
        if body_candidate_names:
             body_params = {name: parameters[name] for name in body_candidate_names}
             assigned_param_names.update(body_candidate_names)
             logger.info(f"Assigned parameters {body_candidate_names} to request body.")
        else:
             # Body schema exists, but no unassigned parameters left.
             # Could mean body is optional or LLM didn't provide body params.
             # Set body_params to an empty dict if the schema implies it's required and empty?
             # For now, leave as None if no candidates, API might accept empty body implicitly.
             body_params = None
             logger.info("Request body schema exists, but no unassigned parameters were found to populate it.")
             
    # 3. Log any parameters provided by LLM that were not assigned anywhere
    unassigned_params = llm_param_names - assigned_param_names
    if unassigned_params:
        logger.warning(f"Unassigned parameters found in tool call (not in openapi_params or requestBody): {unassigned_params}.")

    return query_params, body_params, path_params

def execute_tool_call(tool_call: Dict, mcpo_url: str, tool_execution_map: Dict) -> Dict:
    """
    Execute a tool call by sending a request to the appropriate MCP server.
    Uses the pre-discovered tool_execution_map to find execution details and parameter locations.
    
    Args:
        tool_call: The tool call dictionary with name (operationId) and parameters.
        mcpo_url: Base URL for the MCPO server (used only for constructing final URL).
        tool_execution_map: Dictionary mapping operationId to execution details,
                            including OpenAPI parameter information.
                            Example: { "opId": { "service": "svc", "path": "/p/{param1}", "method": "post",
                                                "request_body_schema": {...}, "openapi_params": [...] } }
    
    Returns:
        Dict containing the tool execution result.
    """
    tool_name = "<unknown>"
    try:
        tool_name = tool_call.get("name", "") # This is the operationId
        parameters = tool_call.get("parameters", {})
        
        if not tool_name:
            return format_error_response("Tool name (operationId) is required in tool_call")
            
        logger.info(f"Attempting to execute tool call (operationId): {tool_name} with parameters: {parameters}")
        
        if not tool_execution_map:
             error_msg = "execute_tool_call requires a tool_execution_map, but it was None or empty."
             logger.error(error_msg)
             return format_error_response(error_msg)
        
        execution_details = tool_execution_map.get(tool_name)
        
        if not execution_details:
            error_msg = f"Execution details for operationId '{tool_name}' not found in provided map. Map keys: {list(tool_execution_map.keys())}"
            logger.error(error_msg)
            return format_error_response(error_msg)
            
        found_service = execution_details.get("service")
        endpoint_path_template = execution_details.get("path", "")
        http_method = execution_details.get("method")

        if not all([found_service is not None, endpoint_path_template is not None, http_method]):
             error_msg = f"Incomplete execution details found for operationId '{tool_name}': {execution_details}. Missing service, path, or method."
             logger.error(error_msg)
             return format_error_response(error_msg)

        logger.info(f"Found execution details: Service={found_service}, Path Template='{endpoint_path_template}', Method={http_method.upper()}")
        
        query_params, body_params, path_params = _prepare_request_params(parameters, execution_details)

        final_endpoint_path = endpoint_path_template
        required_placeholders = set(re.findall(r"\{(\w+)\}", endpoint_path_template))
        
        if required_placeholders:
            try:
                logger.debug(f"Attempting path substitution: template='{endpoint_path_template}', params={path_params}")
                provided_keys = set(path_params.keys())

                logger.info(f"Path template: '{endpoint_path_template}'")
                logger.info(f"Required placeholders found by regex: {required_placeholders}")
                logger.info(f"Provided path keys: {provided_keys}")

                if not required_placeholders.issubset(provided_keys):
                    missing_keys = required_placeholders - provided_keys
                    error_msg = f"Missing required path parameter(s) {missing_keys} for path template '{endpoint_path_template}' in tool call parameters: {parameters.keys()}"
                    logger.error(error_msg)
                    print(f"DEBUG: Returning error due to missing path params: {error_msg}")
                    return format_error_response(error_msg)
                
                final_endpoint_path = endpoint_path_template.format(**path_params)
                logger.info(f"Substituted path parameters: '{endpoint_path_template}' -> '{final_endpoint_path}'")

            except KeyError as e:
                 error_msg = f"Internal Error: KeyError '{e}' during path format for '{endpoint_path_template}'. Params: {path_params}"
                 logger.error(error_msg)
                 return format_error_response(error_msg)
            except Exception as e:
                 error_msg = f"Error substituting path parameters for '{endpoint_path_template}': {e}"
                 logger.exception(error_msg)
                 return format_error_response(error_msg)
        tool_url = _build_tool_url(mcpo_url, found_service, final_endpoint_path)

        result = _perform_http_request(
            method=http_method,
            url=tool_url,
            query_params=query_params,
            body_params=body_params
        )
        return result
            
    except Exception as e:
        logger.exception(f"Unexpected error during execute_tool_call setup for operationId '{tool_name}'")
        return format_error_response(f"Unexpected error preparing tool call '{tool_name}': {str(e)}")

def validate_tool_call_format(tool_call: Dict) -> bool:
    """
    Validate that a tool call dictionary has the basic required structure.
    (Checks for 'name' and 'parameters' keys).
    Note: This is a basic structural check, not validation against a specific schema.
    
    Args:
        tool_call: The tool call dictionary to validate.
        
    Returns:
        bool: True if the basic structure is valid, False otherwise.
    """
    if not isinstance(tool_call, dict):
        logger.warning(f"Invalid tool call format: Expected dict, got {type(tool_call)}.")
        return False
        
    if "name" not in tool_call:
        logger.warning("Invalid tool call format: Missing 'name' key.")
        return False
        
    if not isinstance(tool_call["name"], str) or not tool_call["name"]:
        logger.warning("Invalid tool call format: 'name' key must be a non-empty string.")
        return False
        
    if "parameters" not in tool_call:
        logger.warning(f"Invalid tool call format for tool '{tool_call['name']}': Missing 'parameters' key.")
        return False
        
    if not isinstance(tool_call["parameters"], dict):
        logger.warning(f"Invalid tool call format for tool '{tool_call['name']}': 'parameters' key must be a dict, got {type(tool_call['parameters'])}.")
        return False
        
    # Previous checks for tool_endpoint_ prefix and underscores are removed
    # as operationId is now used directly.

    logger.debug(f"Tool call format validation passed for '{tool_call['name']}'.")
    return True 