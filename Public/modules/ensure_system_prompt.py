import json
import logging
import os
import re
import requests
import ast
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Import functions/classes from other MCP modules
try:
    # Import the Discoverer class
    from mcp_service_discoverer import MCPServiceDiscoverer
    # Import prompt utils from their module
    from mcp_prompt_utils import (
        _format_mcp_tools_for_llm_prompt, 
        _integrate_tools_into_prompt
    )
    from Middleware.utilities.config_utils import get_default_tool_prompt_path
except ImportError:
    # Fallback if running from a different directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    import sys
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    # Import the Discoverer class
    from mcp_service_discoverer import MCPServiceDiscoverer
    # Import prompt utils from their module
    from mcp_prompt_utils import (
        _format_mcp_tools_for_llm_prompt, 
        _integrate_tools_into_prompt
    )
    from Middleware.utilities.config_utils import get_default_tool_prompt_path

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
    
    default_prompt_path = kwargs.get("default_prompt_path", get_default_tool_prompt_path())
    mcpo_url = kwargs.get("mcpo_url", "http://localhost:8889")
    user_identified_services = kwargs.get("user_identified_services", "")

    if isinstance(messages, list):
        pass
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
                    messages = None
            except (ValueError, SyntaxError, MemoryError, TypeError) as e:
                logger.warning(f"Failed to parse messages string via ast.literal_eval: {e}. Falling back.")
                messages = None
        if messages is None:
             logger.info("Using simple parse_string_messages for the string.")
             from mcp_workflow_integration import parse_string_messages
             messages = parse_string_messages(messages)
    else:
        logger.warning(f"Messages argument is of unexpected type: {type(messages)}. Setting to empty list.")
        messages = []
        
    if not isinstance(messages, list):
        logger.warning("Could not parse messages into a list, using empty list.")
        messages = []
    
    system_prompt_index = -1
    system_prompt_content = ""
    discovered_tools_map = {}
    
    for idx, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "system":
            system_prompt_index = idx
            system_prompt_content = message.get("content", "")
            break
    
    additional_services = []
    if user_identified_services and user_identified_services.strip().lower() != "none":
        logger.info(f"Found user-identified services: {user_identified_services}")
        services = [s.strip() for s in user_identified_services.split(",")]
        additional_services = [s for s in services if s]
        logger.info(f"Parsed additional services: {additional_services}")
    
    discoverer = MCPServiceDiscoverer(mcpo_url=mcpo_url)

    if system_prompt_index == -1:
        logger.info("No system prompt found, adding default")
        default_prompt = load_default_prompt(default_prompt_path)
        
        all_services = additional_services
        logger.info(f"Combined services for discovery: {all_services}")
        
        tools_map = discoverer.discover_mcp_tools(all_services)
        logger.info(f"Discovered {len(tools_map)} tools total")
        
        tools_prompt_section = _format_mcp_tools_for_llm_prompt(tools_map)
        
        enhanced_prompt = _integrate_tools_into_prompt(default_prompt, tools_prompt_section)
        
        messages.insert(0, {"role": "system", "content": enhanced_prompt})
        logger.info("Added system prompt to messages using utility function.")
        system_prompt_content = enhanced_prompt
        discovered_tools_map = tools_map
    else:
        logger.info("System prompt exists, checking for enhancements")
        all_services = additional_services
        logger.info(f"Combined services for discovery: {all_services}")
        
        tools_map = discoverer.discover_mcp_tools(all_services)
        logger.info(f"Discovered {len(tools_map)} tools total")
        
        if tools_map or "Available Tools:" not in system_prompt_content or "<required_format>" not in system_prompt_content:
            logger.info("System prompt needs enhancement/update")
            tools_prompt_section = _format_mcp_tools_for_llm_prompt(tools_map)
            
            enhanced_prompt = _integrate_tools_into_prompt(system_prompt_content, tools_prompt_section)
            
            messages[system_prompt_index]["content"] = enhanced_prompt
            logger.info("Enhanced existing system prompt using utility function.")
            system_prompt_content = enhanced_prompt
        else:
            logger.info("Existing system prompt is already sufficient")
        
        discovered_tools_map = tools_map
    
    return {
        "messages": messages, 
        "chat_system_prompt": system_prompt_content, 
        "discovered_tools_map": discovered_tools_map
    } 