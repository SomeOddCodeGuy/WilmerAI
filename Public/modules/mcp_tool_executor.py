import json
import logging
import re
import requests
import os
from typing import Dict, List, Any, Optional, Tuple, Union
import datetime

logger = logging.getLogger(__name__)

# Default MCPO server base URL
DEFAULT_MCPO_URL = os.environ.get("MCPO_URL", "http://localhost:8889")

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
    logger.info(f"MCP Tool Executor invoked with {len(messages)} messages")
    
    # Find system prompt and extract potential service names
    system_prompt = ""
    for msg in messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
            break
    
    service_names = extract_service_names_from_prompt(system_prompt)
    logger.info(f"Potential services based on system prompt: {service_names}")
    if not service_names:
        logger.warning("No service names could be extracted from the system prompt. Tool execution might fail if schemas are needed.")

    # Extract the last assistant message (LLM response)
    assistant_message = None
    for message in reversed(messages):
        if message.get("role") == "assistant":
            assistant_message = message.get("content", "")
            logger.info(f"Found assistant message: {assistant_message[:200]}...")
            break
    
    if not assistant_message:
        logger.warning("No assistant message found in conversation")
        return {"response": "", "has_tool_call": False}
    
    # Check for tool calls in the assistant's response
    logger.info("Checking for tool calls in assistant's response...")
    tool_calls = extract_tool_calls(assistant_message)
    
    if not tool_calls:
        logger.info("No tool calls found in assistant's response")
        return {"response": assistant_message, "has_tool_call": False}
    
    logger.info(f"Found {len(tool_calls)} tool calls")
    
    # Execute the tool calls and get results
    tool_results = []
    for idx, tool_call in enumerate(tool_calls):
        logger.info(f"Executing tool call {idx + 1}/{len(tool_calls)}: {tool_call.get('name', 'unknown')}")
        # Pass the tool_execution_map received by Invoke, not service_names
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
    Extract tool calls from LLM response text.
    
    Args:
        text: The text to extract tool calls from
    
    Returns:
        List of tool call dictionaries
    """
    logger.info("Attempting to extract tool calls from text...")
    
    # Skip if text contains unsubstituted variables
    if re.search(r'\{[a-zA-Z0-9_]+\}', text):
        logger.warning("Text contains unsubstituted variables, skipping tool call extraction")
        return []
    
    # First, clean up any malformed markers (fallback if sanitizer didn't run)
    cleaned_text = text
    if "|{{|" in text or "|}}|" in text or "|}}}|" in text:
        logger.warning("Found malformed JSON markers in text, cleaning up")
        cleaned_text = text.replace("|{{|", "{").replace("|}}}|", "}").replace("|}}|", "}")
        logger.info(f"Cleaned text: {cleaned_text[:100]}...")
    
    # Strip whitespace before trying to parse
    json_str = cleaned_text.strip()

    # If it doesn't look like JSON, return empty
    if not json_str.startswith('{') or not json_str.endswith('}'):
        logger.info("Cleaned text does not appear to be a JSON object.")
        return []

    try:
        # Assume input is clean JSON (after sanitizer/cleanup)
        logger.info(f"Attempting direct json.loads on: {json_str[:200]}...")
        json_obj = json.loads(json_str)
        
        # Validate the structure
        if isinstance(json_obj, dict) and "tool_calls" in json_obj and isinstance(json_obj["tool_calls"], list):
            validated_calls = []
            for call in json_obj["tool_calls"]:
                if isinstance(call, dict) and "name" in call and "parameters" in call:
                    validated_calls.append(call)
                else:
                    logger.warning(f"Invalid tool call object found in list: {call}")
            if validated_calls: # Only return if we found valid calls
                 logger.info(f"Successfully parsed and validated {len(validated_calls)} tool calls.")
                 return validated_calls
            else:
                 logger.warning("Parsed JSON but found no valid tool calls in the 'tool_calls' list.")
                 return []
        else:
            logger.warning("Parsed JSON does not match expected structure: {'tool_calls': [...]}")
            return []
            
    except json.JSONDecodeError as e:
        logger.error(f"Direct json.loads failed even after cleaning: {e}")
        # Could add more complex regex fallbacks here if needed, but relying on sanitizer for now.
        return []

def validate_tool_definition(tool: Dict) -> bool:
    """
    Validate that a tool definition has all required fields and correct types.
    
    Args:
        tool: Tool definition dictionary
    
    Returns:
        bool: True if valid, False otherwise
    """
    required_fields = ["type", "name", "description", "parameters"]
    if not all(field in tool for field in required_fields):
        logger.error(f"Tool missing required fields: {[f for f in required_fields if f not in tool]}")
        return False
        
    if tool["type"] != "function":
        logger.error(f"Invalid tool type: {tool['type']}")
        return False
        
    if not isinstance(tool["parameters"], dict):
        logger.error("Parameters must be a dictionary")
        return False
        
    return True

def validate_tool_schema(schema: Dict) -> bool:
    """
    Validate that an OpenAPI schema has required fields for tool discovery.
    
    Args:
        schema: OpenAPI schema dictionary
    
    Returns:
        bool: True if valid, False otherwise
    """
    if "paths" not in schema:
        logger.error("Schema missing paths")
        return False
        
    for path, methods in schema.get("paths", {}).items():
        for method, details in methods.items():
            if not details.get("operationId"):
                logger.warning(f"Missing operationId in {path} {method}")
                continue
                
            if not details.get("description") and not details.get("summary"):
                logger.warning(f"Missing description/summary in {path} {method}")
                
    return True

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
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

def execute_tool_call(tool_call: Dict, mcpo_url: str, tool_execution_map: Dict) -> Dict:
    """
    Execute a tool call by sending a request to the appropriate MCP server.
    Uses the pre-discovered tool_execution_map to find execution details.
    
    Args:
        tool_call: The tool call dictionary with name (operationId) and parameters.
        mcpo_url: Base URL for the MCPO server (used only for constructing final URL).
        tool_execution_map: Dictionary mapping operationId to execution details.
                            Example: { "opId": { "service": "svc", "path": "/p", "method": "post", ... } }
    
    Returns:
        Dict containing the tool execution result.
    """
    try:
        tool_name = tool_call.get("name", "") # This is the operationId
        parameters = tool_call.get("parameters", {})
        
        if not tool_name:
            return format_error_response("Tool name (operationId) is required in tool_call")
            
        logger.info(f"Attempting to execute tool call (operationId): {tool_name} with parameters: {parameters}")
        
        # Look up execution details in the map
        execution_details = tool_execution_map.get(tool_name)
        
        if not execution_details:
            error_msg = f"Execution details for operationId '{tool_name}' not found in provided map. Map keys: {list(tool_execution_map.keys())}"
            logger.error(error_msg)
            return format_error_response(error_msg)
            
        found_service = execution_details.get("service")
        endpoint_path = execution_details.get("path")
        http_method = execution_details.get("method")

        if not all([found_service, endpoint_path, http_method]):
             error_msg = f"Incomplete execution details found for operationId '{tool_name}': {execution_details}"
             logger.error(error_msg)
             return format_error_response(error_msg)

        logger.info(f"Found execution details: Service={found_service}, Path={endpoint_path}, Method={http_method.upper()}")
        
        # Execute the tool call using the found service, path, and method
        tool_url = f"{mcpo_url}/{found_service}{endpoint_path}"
        logger.info(f"Executing {http_method.upper()} request to: {tool_url}")
        
        try:
            req_timeout = 15 # Set timeout for actual tool call
            if http_method.lower() == "get":
                response = requests.get(tool_url, params=parameters, timeout=req_timeout)
            elif http_method.lower() == "post":
                response = requests.post(tool_url, json=parameters, timeout=req_timeout)
            elif http_method.lower() == "put":
                 response = requests.put(tool_url, json=parameters, timeout=req_timeout)
            elif http_method.lower() == "delete":
                 response = requests.delete(tool_url, params=parameters, timeout=req_timeout)
            # Add other methods (PATCH, etc.) if needed
            else:
                 return format_error_response(f"Unsupported HTTP method '{http_method}' found for tool {tool_name}")

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            
            # Handle potential non-JSON responses
            try:
                result_json = response.json()
                logger.info("Tool executed successfully, received JSON response.")
                return result_json
            except json.JSONDecodeError:
                logger.warning("Tool executed, but response was not valid JSON. Returning raw text.")
                return {"response_text": response.text} # Return raw text if not JSON

        except requests.exceptions.Timeout:
            return format_error_response(f"Tool execution timed out after {req_timeout}s for {tool_url}")
        except requests.RequestException as e:
            # Attempt to get more detail from response if available
            error_detail = str(e)
            if e.response is not None:
                try:
                    error_detail += f" - Response: {e.response.text[:500]}" # Limit response size
                except Exception:
                    pass # Ignore if response text itself causes issues
            return format_error_response(f"Tool execution failed: {error_detail}")
            
    except Exception as e:
        # General catch-all for unexpected errors
        logger.exception(f"Unexpected error during execute_tool_call for {tool_name}") # Log full traceback
        return format_error_response(f"Unexpected error executing tool {tool_name}: {str(e)}")

def discover_mcp_tools(service_names: List[str], mcpo_url: str = DEFAULT_MCPO_URL) -> Dict:
    """
    Discover available tools from specified MCP servers and return execution details.
    
    Args:
        service_names: List of MCP service names (e.g., ["time", "weather"])
        mcpo_url: Base URL for the MCPO server
    
    Returns:
        Dictionary mapping operationId to its execution details and LLM schema.
        Example: { "opId": { "service": "svc", "path": "/p", "method": "post", "llm_schema": {...} }, ... }
    """
    tools_map = {}
    
    for service_name in service_names:
        try:
            # Get the OpenAPI schema for this service
            schema_url = f"{mcpo_url}/{service_name}/openapi.json"
            schema_response = requests.get(schema_url, timeout=5) # Add timeout
            schema_response.raise_for_status()
            schema = schema_response.json()
            
            # Validate schema
            if not validate_tool_schema(schema):
                logger.error(f"Invalid schema for service {service_name}")
                continue
            
            # Extract tools from the schema
            for path, methods in schema.get("paths", {}).items():
                for method, details in methods.items():
                    operation_id = details.get("operationId")
                    # Skip if no operationId (required for tool calls)
                    if not operation_id:
                        continue
                    
                    # Build the LLM schema part
                    llm_schema = {
                        "type": "function",
                        "name": operation_id,
                        "description": details.get("description") or details.get("summary") or "",
                    }
                    
                    # Extract parameters from the requestBody schema
                    parameters = {"type": "object", "properties": {}, "required": []}
                    request_body = details.get("requestBody", {})
                    if request_body:
                        content = request_body.get("content", {}).get("application/json", {})
                        schema_ref = content.get("schema", {}).get("$ref")
                        
                        if schema_ref:
                            # Extract the schema name from the reference
                            schema_name = schema_ref.split("/")[-1]
                            schema_def = schema.get("components", {}).get("schemas", {}).get(schema_name, {})
                            
                            # Get properties
                            for prop_name, prop_details in schema_def.get("properties", {}).items():
                                parameters["properties"][prop_name] = {
                                    "type": prop_details.get("type", "string"),
                                    "description": prop_details.get("description", "")
                                }
                            
                            # Get required fields
                            parameters["required"] = schema_def.get("required", [])
                    
                    llm_schema["parameters"] = parameters
                    
                    # Validate LLM schema before adding
                    if validate_tool_definition(llm_schema):
                         # Store execution details along with LLM schema
                         tools_map[operation_id] = {
                             "service": service_name,
                             "path": path,
                             "method": method,
                             "llm_schema": llm_schema
                         }
                    else:
                        logger.error(f"Invalid tool definition for {operation_id}")
            
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching schema for service {service_name}")
            continue
        except requests.RequestException as e:
            logger.error(f"Failed to discover tools for service {service_name}: {e}")
            continue
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON schema for service {service_name}: {e}")
            continue
        except Exception as e:
            logger.error(f"Unexpected error discovering tools for service {service_name}: {e}")
            continue
    
    return tools_map

def format_tools_for_llm(tools_map: Dict) -> str:
    """
    Format discovered tools (from map) as a system prompt section for LLMs.
    
    Args:
        tools_map: Dictionary mapping operationId to details including llm_schema.
    
    Returns:
        Formatted system prompt section with tool definitions.
    """
    if not tools_map:
        return ""
    
    # Extract just the llm_schema part for formatting
    llm_schemas = [details["llm_schema"] for details in tools_map.values()]
    if not llm_schemas:
        return "" # Should not happen if tools_map is not empty, but safeguard
        
    tools_json = json.dumps(llm_schemas, indent=2)
    
    # Use pre-formatted strings for examples to avoid complex escapes
    empty_example = '''{\n     "tool_calls": []\n   }'''
    tool_call_example = '''{\n  "tool_calls": [\n    {"name": "toolName1", "parameters": {"key1": "value1"}},\n    {"name": "toolName2", "parameters": {"key2": "value2"}}\n  ]\n}'''

    system_prompt = f"""Available Tools: {tools_json}

Your task is to decide if any tools from the list are needed to answer the user's query. Follow these instructions precisely:

<required_format>
- If no tools are needed, you MUST output ONLY the following JSON object:
{empty_example}

- If one or more tools are needed, you MUST output ONLY a JSON object containing a single "tool_calls" array. Each object in the array must have:
  - "name": The exact tool's name (operationId) from the Available Tools list.
  - "parameters": A dictionary of required parameters and their corresponding values based on the user query.

- The format MUST be exactly:
{tool_call_example}
</required_format>

CRITICAL: Respond ONLY with the JSON object described above. Do not include any other text, explanations, apologies, or conversational filler before or after the JSON object.
"""
    return system_prompt

def extract_service_names_from_prompt(system_prompt: str) -> List[str]:
    """
    Extract MCP service names from a system prompt.
    
    Args:
        system_prompt: The system prompt to extract service names from
    
    Returns:
        List of MCP service names
    """
    # Look for specific MCP service definitions
    # This is a simple implementation - you may need to enhance based on your prompt format
    service_names = []
    
    # Pattern for service names in various formats
    patterns = [
        r'MCP\s+Services:\s*\n([\s\S]*?)(?:\n\n|\Z)',  # MCP Services: list format
        r'MCP\s+Servers:\s*\n([\s\S]*?)(?:\n\n|\Z)',   # MCP Servers: list format
        r'Use\s+MCP\s+services:\s*\n([\s\S]*?)(?:\n\n|\Z)',  # Use MCP services: format
        r'Available\s+MCP\s+tools:\s*\n([\s\S]*?)(?:\n\n|\Z)'  # Available MCP tools: format
    ]
    
    for pattern in patterns:
        matches = re.search(pattern, system_prompt, re.IGNORECASE)
        if matches:
            services_text = matches.group(1)
            # Extract service names (one per line)
            for line in services_text.split('\n'):
                service = line.strip().strip('-*•').strip()
                if service and not service.startswith('http'):
                    service_names.append(service)
    
    # If no structured format is found, look for individual mentions
    if not service_names:
        # Look for common service names mentioned directly
        common_services = ["time", "weather", "search", "memory", "knowledge", "wikipedia"]
        for service in common_services:
            if re.search(rf'\b{service}\b', system_prompt, re.IGNORECASE):
                service_names.append(service)
    
    return service_names

def prepare_system_prompt(original_prompt: str, mcpo_url: str = DEFAULT_MCPO_URL, validate_tools: bool = False) -> Tuple[str, Dict]:
    """
    Prepare a system prompt by discovering tools for mentioned MCP services and adding definitions.
    
    Args:
        original_prompt: The original system prompt.
        mcpo_url: Base URL for the MCPO server.
        validate_tools: Whether to validate discovered tool definitions using validate_tool_definition.
    
    Returns:
        Tuple containing:
            - Updated system prompt string with tool definitions.
            - Dictionary mapping operationId to discovered tool details (tools_map).
    """
    logger.info(f"Preparing system prompt. validate_tools={validate_tools}")
    # Extract service names from the prompt
    service_names = extract_service_names_from_prompt(original_prompt)
    logger.info(f"Extracted service names: {service_names}")
    
    if not service_names:
        # No MCP services mentioned
        logger.info("No MCP services mentioned in prompt.")
        return original_prompt, {} # Return original prompt and empty map
    
    # Discover tools for the mentioned services
    tools_map = discover_mcp_tools(service_names, mcpo_url)
    logger.info(f"Discovered {len(tools_map)} potential tools initially.")
    
    if not tools_map:
        # No tools discovered
        logger.warning("No tools discovered for mentioned services.")
        return original_prompt, {} # Return original prompt and empty map
        
    # Validate tools if enabled
    if validate_tools:
        validated_tools_map = {}
        for op_id, details in tools_map.items():
            # Assuming llm_schema exists and is the part to validate
            if "llm_schema" in details and validate_tool_definition(details["llm_schema"]):
                 validated_tools_map[op_id] = details
            else:
                 logger.warning(f"Tool definition validation failed for {op_id}, excluding.")
        
        if not validated_tools_map:
             logger.error("No valid tools found after validation.")
             return original_prompt, {} # Return original prompt and empty map
        
        logger.info(f"{len(validated_tools_map)} tools remain after validation.")
        tools_map = validated_tools_map # Use the validated map
    
    # Format the tools for LLM (using the potentially filtered tools_map)
    tools_prompt_section = format_tools_for_llm(tools_map)
    
    # Replace existing tools section or append
    tools_section_pattern = r'Available\\s+Tools:[\\s\\S]*?(?=\\n\\n<required_format>|\\Z)' # Match until format instructions or end
    if re.search(tools_section_pattern, original_prompt, re.IGNORECASE):
        # Replace existing tools section
        logger.info("Replacing existing 'Available Tools' section.")
        updated_prompt = re.sub(
            tools_section_pattern,
            tools_prompt_section.strip(), # Use strip to avoid extra newlines if section is empty
            original_prompt,
            count=1, # Replace only the first instance
            flags=re.IGNORECASE
        )
    else:
        # Append tools section
        logger.info("Appending 'Available Tools' section.")
        # Add extra newline if original prompt doesn't end with one
        separator = "\n\n" if original_prompt.strip() else "" 
        if original_prompt.strip() and not original_prompt.endswith('\n'):
             separator = "\n\n"
        elif original_prompt.strip() and original_prompt.endswith('\n') and not original_prompt.endswith('\n\n'):
             separator = "\n" # Only need one more newline
             
        updated_prompt = original_prompt.rstrip() + separator + tools_prompt_section

    logger.debug(f"Updated prompt generated: {updated_prompt[:300]}...")
    return updated_prompt, tools_map

def validate_tool_call_format(tool_call: Dict) -> bool:
    """
    Validate that a tool call matches the required format.
    
    Args:
        tool_call: The tool call to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    # Check that tool_call is a dictionary
    if not isinstance(tool_call, dict):
        return False
        
    # Check required fields
    if "name" not in tool_call or "parameters" not in tool_call:
        return False
        
    # Check field types
    if not isinstance(tool_call["name"], str):
        return False
    if not isinstance(tool_call["parameters"], dict):
        return False
        
    # Check that name starts with tool_endpoint_
    name = tool_call["name"]
    prefix = "tool_endpoint_"
    if not name.startswith(prefix):
        return False
        
    # Check for at least two underscores after the prefix (service_action_method)
    remaining_name = name[len(prefix):]
    if remaining_name.count('_') < 2:
        return False
        
    # Check that parts are not empty
    parts = remaining_name.split('_')
    if len(parts) < 3 or any(not part for part in parts):
        return False

    return True 