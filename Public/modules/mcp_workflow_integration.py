import ast
import json
import logging
import os
import re
import sys
from typing import Dict, List, Any, Union, Optional

# Add the module directory to the path and import our MCP tool executor
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)
import mcp_tool_executor

logger = logging.getLogger(__name__)

# Default MCPO server URL - can be configured in environment, config, or passed through kwargs
DEFAULT_MCPO_URL = os.environ.get("MCPO_URL", "http://localhost:8889")

def parse_string_messages(messages: str) -> List[Dict[str, str]]:
    """
    Parse string messages into proper message format.
    
    Args:
        messages: String messages to parse
        
    Returns:
        List of message dictionaries
    """
    parsed_messages = []
    
    # Remove "user: " or "assistant: " prefix if present
    if messages.lower().startswith(("user: ", "assistant: ")):
        role, content = messages.split(": ", 1)
        parsed_messages.append({"role": role.lower(), "content": content})
    else:
        # Default to user role if no prefix
        parsed_messages.append({"role": "user", "content": messages})
        
    return parsed_messages

def validate_node_type(node_type: str) -> bool:
    """
    Validate that the node type is one of the allowed types.
    
    Args:
        node_type: The type to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    VALID_TYPES = [
        'Standard', 'ConversationMemory', 'FullChatSummary', 'RecentMemory',
        'ConversationalKeywordSearchPerformerTool', 'MemoryKeywordSearchPerformerTool',
        'RecentMemorySummarizerTool', 'ChatSummaryMemoryGatheringTool',
        'GetCurrentSummaryFromFile', 'chatSummarySummarizer', 'GetCurrentMemoryFromFile',
        'WriteCurrentSummaryToFileAndReturnIt', 'SlowButQualityRAG', 'QualityMemory',
        'PythonModule', 'OfflineWikiApiFullArticle', 'OfflineWikiApiBestFullArticle',
        'OfflineWikiApiTopNFullArticles', 'OfflineWikiApiPartialArticle', 'WorkflowLock',
        'CustomWorkflow', 'ConditionalCustomWorkflow', 'GetCustomFile', 'ImageProcessor'
    ]
    return node_type in VALID_TYPES

def validate_response_format(response: str) -> bool:
    """
    Validate that the response matches the required format.
    
    Args:
        response: The response to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    try:
        # Try to parse as JSON first
        data = json.loads(response)
        
        # Check for tool_calls array
        if not isinstance(data.get("tool_calls"), list):
            return False
            
        # Validate each tool call
        for tool_call in data["tool_calls"]:
            if not isinstance(tool_call, dict):
                return False
            if "name" not in tool_call or "parameters" not in tool_call:
                return False
            if not tool_call["name"].startswith("tool_endpoint_"):
                return False
                
        return True
    except json.JSONDecodeError:
        return False

def format_tool_results_response(original_response: str, tool_results: List[Dict]) -> str:
    """
    Format tool results into a response that includes both the original response and results.
    
    Args:
        original_response: The original LLM response
        tool_results: List of tool results to format
        
    Returns:
        Formatted response string
    """
    if not tool_results:
        return original_response
        
    formatted_response = original_response.rstrip() + "\n\n"
    formatted_response += "Tool Results:\n\n"
    
    for idx, result in enumerate(tool_results, 1):
        tool_call = result.get("tool_call", {})
        tool_result = result.get("result", {})
        
        formatted_response += "Tool Call:\n"
        formatted_response += f"Name: {tool_call.get('name', 'unknown')}\n"
        formatted_response += f"Parameters: {json.dumps(tool_call.get('parameters', {}), indent=2)}\n\n"
        
        if "error" in tool_result:
            formatted_response += f"Error: {tool_result['error']}\n"
            if "status" in tool_result:
                formatted_response += f"Status: {tool_result['status']}\n"
            if "timestamp" in tool_result:
                formatted_response += f"Timestamp: {tool_result['timestamp']}\n"
        else:
            formatted_response += f"Result: {json.dumps(tool_result, indent=2)}\n"
            
        formatted_response += "\n"
    
    return formatted_response

def format_results_only(tool_results: List[Dict]) -> str:
    """
    Format only the tool results without the original response.
    
    Args:
        tool_results: List of tool results to format
    
    Returns:
        Formatted string containing only the tool results, removing any markers
    """
    if not tool_results:
        return ""
        
    formatted_response = "Tool Results:\n\n"
    
    for idx, result in enumerate(tool_results, 1):
        tool_call = result.get("tool_call", {})
        tool_result = result.get("result", {})
        
        formatted_response += "Tool:\n"
        formatted_response += f"Name: {tool_call.get('name', 'unknown')}\n"
        formatted_response += f"Parameters: {json.dumps(tool_call.get('parameters', {}), indent=2)}\n\n"
        
        if "error" in tool_result:
            formatted_response += f"Error: {tool_result['error']}\n"
            if "status" in tool_result:
                formatted_response += f"Status: {tool_result['status']}\n"
            if "timestamp" in tool_result:
                formatted_response += f"Timestamp: {tool_result['timestamp']}\n"
        else:
            # Clean the raw tool result before adding to the response
            cleaned_result = json.dumps(tool_result, indent=2)
            # Remove potential |{{| markers if they somehow got into the result
            cleaned_result = cleaned_result.replace("|{{|", "{").replace("|}}}|", "}").replace("|}}|", "}")
            formatted_response += f"Result: {cleaned_result}\n"
            
        formatted_response += "\n"
    
    return formatted_response.strip() # Return stripped response

def Invoke(*args, **kwargs) -> str:
    """
    Main entry point for the MCP workflow integration module.
    Execute MCP tool calls based on the tool_execution_map.
    
    Args:
        *args: Variable length argument list. 
               arg[0] (raw_messages): Messages list or string.
               arg[1] (original_response): Optional LLM response.
        **kwargs: Arbitrary keyword arguments.
        
    Keyword Args:
        messages: Messages list or string (overrides args[0]).
        original_response: LLM response (overrides args[1]).
        mcpo_url: Base URL for the MCPO server.
        tool_execution_map: Map from operationId to execution details.
                          Can be a dict or a stringified dict.
        validate_tools: Whether to validate tool definitions
        validate_execution: Whether to validate tool execution
        node_type: Type of the node (for validation)
    
    Returns:
        String containing tool execution results or the original response.
    """
    # Extract parameters
    messages = None
    original_response = ""
    mcpo_url = kwargs.get("mcpo_url", DEFAULT_MCPO_URL)
    raw_tool_execution_map = kwargs.get("tool_execution_map", {})
    validate_tools = kwargs.get("validate_tools", False)
    validate_execution = kwargs.get("validate_execution", False)
    node_type = kwargs.get("node_type")
    
    # Parse tool_execution_map if it's a string
    if isinstance(raw_tool_execution_map, str):
        logger.info(f"Tool execution map is a string, attempting to parse: {raw_tool_execution_map[:100]}...")
        try:
            tool_execution_map = ast.literal_eval(raw_tool_execution_map)
            if not isinstance(tool_execution_map, dict):
                logger.error("Parsed tool_execution_map is not a dictionary")
                tool_execution_map = {}
            else:
                logger.info(f"Successfully parsed tool_execution_map with {len(tool_execution_map)} entries")
        except (ValueError, SyntaxError) as e:
            logger.error(f"Failed to parse tool_execution_map string: {e}")
            tool_execution_map = {}
    else:
        tool_execution_map = raw_tool_execution_map
    
    # Handle positional arguments
    raw_messages = None
    if args:
        raw_messages = args[0] # Get the raw messages argument
        if len(args) > 1:
            original_response = args[1]
    
    # Handle keyword arguments (override positional if both provided)
    if 'messages' in kwargs:
        raw_messages = kwargs['messages'] # Get raw from kwargs if provided
    if 'original_response' in kwargs:
        original_response = kwargs['original_response']

    # --- PARSE MESSAGES (using ast.literal_eval) --- 
    if isinstance(raw_messages, list):
        logger.info("Messages argument is already a list.")
        messages = raw_messages
    elif isinstance(raw_messages, str):
        logger.info(f"Messages argument is a string: {raw_messages[:100]}...")
        if raw_messages.strip().startswith('[') and raw_messages.strip().endswith(']'):
            logger.info("Attempting to parse stringified list using ast.literal_eval...")
            try:
                evaluated_obj = ast.literal_eval(raw_messages)
                if isinstance(evaluated_obj, list) and all(isinstance(item, dict) and 'role' in item and 'content' in item for item in evaluated_obj):
                    messages = evaluated_obj
                    logger.info("Successfully parsed stringified message list via ast.literal_eval.")
                else:
                    logger.warning("ast.literal_eval did not produce a valid message list.")
                    messages = None # Fallback
            except (ValueError, SyntaxError, MemoryError, TypeError) as e:
                logger.warning(f"Failed to parse messages string via ast.literal_eval: {e}. Falling back.")
                messages = None # Fallback
        if messages is None:
             logger.info("Using simple parse_string_messages for the string.")
             messages = parse_string_messages(raw_messages) # Fallback
    else:
        logger.warning(f"Messages argument is of unexpected type: {type(raw_messages)}. Setting to empty list.")
        messages = []
    if not isinstance(messages, list):
         logger.warning("Could not parse messages into a list, using empty list.")
         messages = []
    # --- END PARSE MESSAGES --- 

    # Validate node type if provided
    if node_type and not validate_node_type(node_type):
        logger.warning(f"Invalid node type: {node_type}")
        # Decide if we should return original_response or empty
        # Returning original_response might be safer if available
        return original_response or ""
    
    # Check for empty messages *after* parsing
    if not messages:
        logger.warning("No valid messages found after parsing in MCP workflow integration")
        return original_response or ""
        
    # Log debug info (using the parsed messages)
    logger.info(f"MCP workflow integration processing {len(messages)} messages")
    logger.info(f"Using MCPO URL: {mcpo_url}")
    
    for idx, msg in enumerate(messages):
        logger.info(f"Message {idx}: role={msg.get('role')}, content={msg.get('content', '')[:100]}...")
    
    # --- EXECUTION MODE --- 
    logger.info("Execution mode: proceeding to call MCP tool executor.")
    
    # Ensure tool_execution_map is provided
    if not tool_execution_map:
         logger.error("Execution mode requires 'tool_execution_map' kwarg, but it was not provided or is empty.")
         return original_response or "" # Return original response if map is missing
    
    # Prepare messages to send to executor
    if original_response:
        logger.info(f"Original response provided: {original_response[:100]}...")
        messages_to_send = messages + [{"role": "assistant", "content": original_response}]
    else:
        # This case shouldn't happen if we expect an LLM response before execution,
        # but handle defensively.
        logger.warning("No original_response provided to execution mode. Executor might fail if it expects one.")
        messages_to_send = messages
        
    logger.info("Calling MCP tool executor's Invoke function...")
    # Pass the tool_execution_map to the executor's Invoke
    result = mcp_tool_executor.Invoke(messages_to_send, mcpo_url, tool_execution_map=tool_execution_map)
    logger.info(f"MCP tool executor result: {result}")
    
    # Process executor result
    if result.get("has_tool_call"):
        tool_results = result.get("tool_results", [])
        logger.info(f"Tool call detected, formatting {len(tool_results)} results")

        # Check for errors if validation is enabled
        if validate_execution and any("error" in r.get("result", {}) for r in tool_results):
            logger.error("Tool execution validation failed")
            error_details = [r["result"] for r in tool_results if "error" in r.get("result", {})]
            # Return an error message suitable for the user
            user_error_response = f"Tool execution failed:\n\n{json.dumps(error_details, indent=2)}"
            logger.info(f"Returning user-friendly error response: {user_error_response[:200]}...")
            return user_error_response

        # Return only the formatted results
        formatted_results_only = format_results_only(tool_results)
        logger.info(f"Returning formatted tool results only: {formatted_results_only[:200]}...")
        return formatted_results_only # Return the raw formatted results
    else:
        # If executor didn't find/execute a tool call (e.g., bad JSON input),
        # return the original response it was given.
        original_response_from_executor = result.get("response", original_response) # Use response from executor if available
        logger.info(f"No tool call processed by executor, returning original response: {original_response_from_executor[:100] if original_response_from_executor else 'empty string'}")
        # Ensure we return an empty string if the original was None/empty
        return original_response_from_executor or ""