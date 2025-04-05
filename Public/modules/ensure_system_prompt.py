import json
import logging
import os
import re
import requests
import ast
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Import only the tool executor functions
try:
    from mcp_tool_executor import discover_mcp_tools, format_tools_for_llm, extract_service_names_from_prompt
except ImportError:
    # If running from a different directory, try with full path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    import sys
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    from mcp_tool_executor import discover_mcp_tools, format_tools_for_llm, extract_service_names_from_prompt

# Define our own version of prepare_system_prompt to avoid circular imports
def prepare_system_prompt(original_prompt: str, mcpo_url: str = "http://localhost:8889") -> Tuple[str, Dict]:
    """
    Prepare a system prompt by adding tool definitions for mentioned MCP services.
    Also returns the map of discovered tools.
    
    Args:
        original_prompt: The original system prompt
        mcpo_url: Base URL for the MCPO server
        
    Returns:
        Tuple: (Updated system prompt string, Dictionary of discovered tools map)
    """
    # Extract service names from the prompt
    service_names = extract_service_names_from_prompt(original_prompt)
    logger.info(f"Extracted service names from prompt: {service_names}")
    
    if not service_names:
        # No MCP services mentioned
        logger.info("No MCP services found in prompt")
        return original_prompt, {}
    
    # Discover tools and get the execution map
    tools_map = discover_mcp_tools(service_names, mcpo_url)
    logger.info(f"Discovered {len(tools_map)} tools")
    
    if not tools_map:
        # No tools discovered
        logger.warning("No tools discovered for services")
        return original_prompt, {}
    
    # Format the tools (LLM schema part only) for LLM prompt
    tools_prompt_section = format_tools_for_llm(tools_map)
    
    # Check if there's an existing tools section
    tools_section_pattern = r'Available\s+Tools:[\s\S]*?(?=\n\n|\Z)'
    if re.search(tools_section_pattern, original_prompt, re.IGNORECASE):
        # Replace existing tools section
        updated_prompt = re.sub(
            tools_section_pattern,
            tools_prompt_section,
            original_prompt,
            flags=re.IGNORECASE
        )
        logger.info("Replaced existing tools section")
    else:
        # Append tools section
        if original_prompt.strip().endswith("]"):
            # If prompt ends with a closing bracket (from instructions), add newlines before
            updated_prompt = original_prompt + "\n\n" + tools_prompt_section
        else:
            # Otherwise just append with newlines
            updated_prompt = original_prompt.rstrip() + "\n\n" + tools_prompt_section
        logger.info("Appended tools section to prompt")
    
    logger.debug(f"Updated prompt: {updated_prompt[:200]}...")
    return updated_prompt, tools_map

def load_default_prompt(default_prompt_path):
    """
    Load default system prompt from file
    
    Args:
        default_prompt_path: Path to the default prompt file
        
    Returns:
        Default system prompt string
    """
    try:
        if os.path.exists(default_prompt_path):
            with open(default_prompt_path, 'r') as f:
                default_prompt = f.read()
                logger.info(f"Loaded default prompt from {default_prompt_path}")
                return default_prompt
        else:
            logger.warning(f"Default prompt file not found: {default_prompt_path}")
            return """You are an assistant with access to various tools.

Available Tools:
You have access to the following tools:
- tool_endpoint_get_current_time_post: Get the current time in a specified timezone
"""
    except Exception as e:
        logger.error(f"Error loading default prompt: {e}")
        return """You are an assistant with access to various tools.

Available Tools:
You have access to the following tools:
- tool_endpoint_get_current_time_post: Get the current time in a specified timezone
"""

def Invoke(messages, **kwargs):
    """
    Main entry point for ensuring system prompt is present
    
    Args:
        messages: List of messages (may be empty or not contain system prompt)
        
    Keyword Args:
        default_prompt_path: Path to default prompt file
        mcpo_url: Base URL for MCPO server
        user_identified_services: Comma-separated list of service names identified in user messages
        
    Returns:
        Dict containing: messages, chat_system_prompt, discovered_tools_map
    """
    logger.info("System prompt handler invoked")
    
    # Extract parameters
    default_prompt_path = kwargs.get("default_prompt_path", "/root/projects/Wilmer/WilmerData/Public/Configs/default_tool_prompt.txt")
    mcpo_url = kwargs.get("mcpo_url", "http://localhost:8889")
    user_identified_services = kwargs.get("user_identified_services", "")

    # Parse messages if it's a string (using ast.literal_eval)
    if isinstance(messages, list):
        pass # Already a list
    elif isinstance(messages, str):
        logger.info(f"Messages argument is a string: {messages[:100]}...")
        if messages.strip().startswith('[') and messages.strip().endswith(']'):
            logger.info("Attempting to parse stringified list using ast.literal_eval...")
            try:
                evaluated_obj = ast.literal_eval(messages)
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
             from mcp_workflow_integration import parse_string_messages # Import here to avoid potential top-level issues
             messages = parse_string_messages(messages) # Assuming original string was in raw_messages
    else:
        logger.warning(f"Messages argument is of unexpected type: {type(messages)}. Setting to empty list.")
        messages = []
        
    # Ensure messages is a list
    if not isinstance(messages, list):
        logger.warning("Could not parse messages into a list, using empty list.")
        messages = []
    
    # Check if system prompt exists
    system_prompt_index = -1
    system_prompt_content = ""
    discovered_tools_map = {}
    
    for idx, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "system":
            system_prompt_index = idx
            system_prompt_content = message.get("content", "")
            break
    
    # Process user-identified services
    additional_services = []
    if user_identified_services and user_identified_services.strip().lower() != "none":
        logger.info(f"Found user-identified services: {user_identified_services}")
        # Split the comma-separated list
        services = [s.strip() for s in user_identified_services.split(",")]
        # Filter out any empty strings
        additional_services = [s for s in services if s]
        logger.info(f"Parsed additional services: {additional_services}")
    
    # If no system prompt, add one
    if system_prompt_index == -1:
        logger.info("No system prompt found, adding default")
        default_prompt = load_default_prompt(default_prompt_path)
        
        # Extract existing services from prompt and combine with user-identified ones
        existing_services = extract_service_names_from_prompt(default_prompt)
        all_services = list(set(existing_services + additional_services))
        logger.info(f"Combined services for discovery: {all_services}")
        
        # Discover tools for all services
        tools_map = discover_mcp_tools(all_services, mcpo_url)
        logger.info(f"Discovered {len(tools_map)} tools total")
        
        # Format tools for prompt
        tools_prompt_section = format_tools_for_llm(tools_map)
        
        # Add tools section to default prompt
        if "Available Tools:" in default_prompt:
            # Replace existing tools section
            enhanced_prompt = re.sub(
                r'Available\s+Tools:[\s\S]*?(?=\n\n|\Z)',
                tools_prompt_section,
                default_prompt,
                flags=re.IGNORECASE
            )
        else:
            # Append tools section
            enhanced_prompt = default_prompt.rstrip() + "\n\n" + tools_prompt_section
        
        messages.insert(0, {"role": "system", "content": enhanced_prompt})
        logger.info("Added system prompt to messages")
        system_prompt_content = enhanced_prompt
        discovered_tools_map = tools_map
    # If system prompt exists, ensure it has up-to-date tool defs including user-identified services
    else:
        logger.info("System prompt exists, checking for enhancements")
        # Extract existing services from prompt and combine with user-identified ones
        existing_services = extract_service_names_from_prompt(system_prompt_content)
        all_services = list(set(existing_services + additional_services))
        logger.info(f"Combined services for discovery: {all_services}")
        
        # Discover tools for all services
        tools_map = discover_mcp_tools(all_services, mcpo_url)
        logger.info(f"Discovered {len(tools_map)} tools total")
        
        # Only update if we found tools or the prompt needs formatting update
        if tools_map or "Available Tools:" not in system_prompt_content or "<required_format>" not in system_prompt_content:
            logger.info("System prompt needs enhancement/update")
            # Format tools for prompt
            tools_prompt_section = format_tools_for_llm(tools_map)
            
            # Update tools section in prompt
            if "Available Tools:" in system_prompt_content:
                # Replace existing tools section
                enhanced_prompt = re.sub(
                    r'Available\s+Tools:[\s\S]*?(?=\n\n|\Z)',
                    tools_prompt_section,
                    system_prompt_content,
                    flags=re.IGNORECASE
                )
            else:
                # Append tools section
                enhanced_prompt = system_prompt_content.rstrip() + "\n\n" + tools_prompt_section
            
            messages[system_prompt_index]["content"] = enhanced_prompt
            logger.info("Enhanced existing system prompt with tool definitions")
            system_prompt_content = enhanced_prompt
        else:
            logger.info("Existing system prompt is already sufficient")
        
        discovered_tools_map = tools_map
    
    # Return the updated messages, the prompt content, and the tools map
    return {
        "messages": messages, 
        "chat_system_prompt": system_prompt_content, 
        "discovered_tools_map": discovered_tools_map
    } 