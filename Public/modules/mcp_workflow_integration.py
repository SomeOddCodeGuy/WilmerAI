import ast
import json
import logging
import os
import re
import sys
from typing import Dict, List, Any, Union, Optional, Tuple

from Middleware.common.constants import VALID_NODE_TYPES

# Import the base exception from automation_utils
try:
    # This assumes automation_utils is findable via PYTHONPATH adjustments elsewhere
    from Middleware.utilities.automation_utils import DynamicModuleError
except ImportError:
    # Fallback if the import fails (e.g., during isolated testing)
    class DynamicModuleError(Exception):
        """Fallback base class if import fails."""
        def __init__(self, message, module_name=None, details=None):
            super().__init__(message)
            self.module_name = module_name
            self.details = details

# Custom Exceptions
class MCPIntegrationError(DynamicModuleError):
    """Base class for errors in this module."""
    def __init__(self, message, details=None):
        # Pass module_name automatically if desired, or set explicitly
        super().__init__(message, module_name="mcp_workflow_integration", details=details)
    pass

class MCPMessageParsingError(MCPIntegrationError):
    """Error during message parsing."""
    pass

class MCPConfigurationError(MCPIntegrationError):
    """Error related to configuration (e.g., tool_execution_map)."""
    pass

class MCPToolExecutionError(MCPIntegrationError):
    """Error during the execution of a tool call."""
    def __init__(self, message, details=None):
        # Call the updated MCPIntegrationError constructor
        super().__init__(message, details=details)

# Add the module directory to the path and import our MCP tool executor
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)
    
from Public.modules import mcp_tool_executor
# Import DEFAULT_MCPO_URL from the centralized location using absolute import
from Public.modules.mcp_service_discoverer import DEFAULT_MCPO_URL

logger = logging.getLogger(__name__)

def parse_string_messages(messages_str: str) -> List[Dict[str, str]]:
    """
    Parse a single string potentially containing role prefixes into a list
    containing a single message dictionary.
    
    Args:
        messages_str: String message to parse.
        
    Returns:
        List containing one message dictionary.
    """
    parsed_messages = []
    match = re.match(r"^(user|assistant):\s*", messages_str, re.IGNORECASE)
    if match:
        role = match.group(1).lower()
        content = messages_str[match.end():]
        parsed_messages.append({"role": role, "content": content})
    else:
        parsed_messages.append({"role": "user", "content": messages_str})
    return parsed_messages

def validate_node_type(node_type: str) -> bool:
    """
    Validate that the node type is one of the allowed types.
    
    Args:
        node_type: The type to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    return node_type in VALID_NODE_TYPES

def _format_single_tool_result(result: Dict) -> str:
    """
    Formats a single tool call result dictionary into a string.

    Args:
        result: Dictionary containing 'tool_call' and 'result' keys.

    Returns:
        Formatted string for the single tool result.
    """
    formatted_string = ""
    tool_call = result.get("tool_call", {})
    tool_result = result.get("result", {})

    # Prefix decided by calling function (format_results_only uses "Tool:")
    formatted_string += f"Name: {tool_call.get('name', 'unknown')}\n"
    formatted_string += f"Parameters: {json.dumps(tool_call.get('parameters', {}), indent=2)}\n\n"

    if "error" in tool_result:
        formatted_string += f"Error: {tool_result['error']}\n"
        if "status" in tool_result:
            formatted_string += f"Status: {tool_result['status']}\n"
        if "timestamp" in tool_result:
            formatted_string += f"Timestamp: {tool_result['timestamp']}\n"
    else:
        # Clean the raw tool result before adding to the response
        cleaned_result_str = json.dumps(tool_result, indent=2)
        cleaned_result_str = cleaned_result_str.replace("|{{|", "{").replace("|}}}|", "}").replace("|}}", "}")
        formatted_string += f"Result: {cleaned_result_str}\n"

    return formatted_string

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
        formatted_response += "Tool:\n"
        formatted_response += _format_single_tool_result(result)
        formatted_response += "\n"

    return formatted_response.strip()

# Helper function moved outside the class (or could be nested in Invoke)
def _parse_tool_execution_map_static(raw_map: Union[str, Dict, Any]) -> Dict:
    """Parses the tool execution map from string or dict."""
    if isinstance(raw_map, dict):
        logger.info("Tool execution map provided as dict.")
        return raw_map
    elif isinstance(raw_map, str):
        logger.info(f"Tool execution map is a string, attempting to parse: {raw_map[:100]}...")
        try:
            parsed_map = json.loads(raw_map)
            if not isinstance(parsed_map, dict):
                logger.error("Parsed tool_execution_map string is not a dictionary.")
                raise MCPConfigurationError("Parsed tool_execution_map string is not a dictionary.")
            logger.info(f"Successfully parsed tool_execution_map with {len(parsed_map)} entries.")
            return parsed_map
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tool_execution_map string as JSON: {e}")
            raise MCPConfigurationError(f"Failed to parse tool_execution_map string as JSON: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error parsing tool_execution_map string: {e}")
            raise MCPConfigurationError(f"Unexpected error parsing tool_execution_map string: {e}") from e
    else:
        logger.warning(f"tool_execution_map is of unexpected type: {type(raw_map)}. Must be dict or JSON string.")
        # Raise error instead of using empty dict to make misconfiguration explicit
        raise MCPConfigurationError(f"tool_execution_map must be a dict or string, received {type(raw_map)}")

# --- Helper function for message parsing ---
def _parse_messages_input_static(raw_messages: Any) -> List[Dict[str, str]]:
    """
    Parses the raw messages input (list, JSON string, plain string) into a list of dicts.
    Raises MCPMessageParsingError on failure.
    """
    if raw_messages is None:
         logger.warning("No messages provided.")
         return []

    if isinstance(raw_messages, list):
        logger.info("Messages argument is already a list.")
        # Validate list contents immediately
        if all(isinstance(item, dict) and 'role' in item and 'content' in item for item in raw_messages):
            return raw_messages
        else:
            logger.error("Provided list contains invalid message dictionaries.")
            raise MCPMessageParsingError("Messages list contains invalid message dictionaries (must be dicts with 'role' and 'content'.")
    elif isinstance(raw_messages, str):
        logger.info(f"Messages argument is a string: {raw_messages[:100]}...")
        if raw_messages.strip().startswith('[') and raw_messages.strip().endswith(']'):
            logger.info("Attempting to parse stringified list using json.loads...")
            evaluated_obj = None
            try:
                evaluated_obj = json.loads(raw_messages)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse messages string as JSON list: {e}. Falling back to simple string parsing.")
                # Fall through to simple string parsing
            except Exception as e:
                logger.warning(f"Unexpected error parsing messages string as JSON list: {e}. Falling back to simple string parsing.")
                # Fall through to simple string parsing

            # Perform validation *after* successful parsing and outside the try block
            if evaluated_obj is not None and isinstance(evaluated_obj, list):
                # Check if the evaluated list contains valid message dicts
                if all(isinstance(item, dict) and 'role' in item and 'content' in item for item in evaluated_obj):
                    logger.info("Successfully parsed and validated stringified message list via json.loads.")
                    return evaluated_obj
                else:
                    # Raise the specific error if content is invalid
                    logger.error("Parsed stringified list contains invalid message dictionaries.")
                    raise MCPMessageParsingError("Parsed stringified list contains invalid message dictionaries (must be dicts with 'role' and 'content'.")
            elif evaluated_obj is not None: # Parsed but wasn't a list
                logger.warning("json.loads did not produce a list.")
                # Fall through to simple string parsing

        # If not a valid JSON list string or parsing/validation failed, treat as single message string
        logger.info("Using simple parse_string_messages for the string.")
        return parse_string_messages(raw_messages) # Use helper for single string
    else:
        logger.error(f"Messages argument is of unexpected type: {type(raw_messages)}.")
        raise MCPMessageParsingError(f"Messages argument must be a list or string, received {type(raw_messages)}")

class MCPWorkflowHandler:
    """
    Handles the processing and execution of MCP tool calls within a workflow context.
    ASSUMES messages and tool_execution_map are already parsed and validated.
    """
    def __init__(self, *args, **kwargs):
        self.messages: List[Dict[str, str]] = []
        self.original_response: str = ""
        self.mcpo_url: str = DEFAULT_MCPO_URL
        self.tool_execution_map: Dict = {}
        self.validate_execution: bool = False
        self.node_type: Optional[str] = None

        try:
            self._parse_arguments(*args, **kwargs) # Simplified argument extraction
            self._validate_inputs() # Validation on already parsed inputs
        # Keep error handling for init logic itself
        except (MCPConfigurationError, MCPMessageParsingError) as e:
            logger.error(f"Initialization failed: {e}")
            raise e
        except Exception as e:
            logger.exception(f"Unexpected error during MCPWorkflowHandler initialization: {e}")
            raise MCPIntegrationError(f"Unexpected initialization error: {str(e)}") from e

    def _parse_arguments(self, *args, **kwargs):
        """Parses constructor arguments and sets instance attributes. Assumes inputs are pre-parsed."""
        # No positional args expected anymore for core data
        # Still handle potential args if design changes, but core data comes from kwargs

        # Directly assign pre-parsed/validated inputs from kwargs
        self.messages = kwargs.get('messages', []) # Default to empty list
        self.original_response = kwargs.get('original_response', "")
        self.mcpo_url = kwargs.get("mcpo_url", DEFAULT_MCPO_URL)
        self.tool_execution_map = kwargs.get("tool_execution_map", {})
        self.validate_execution = kwargs.get("validate_execution", False)
        self.node_type = kwargs.get("node_type")

    def _validate_inputs(self):
        """Performs validation checks on already parsed arguments."""
        # Validate node type (if provided)
        if self.node_type and not validate_node_type(self.node_type):
            logger.warning(f"Invalid node type provided: {self.node_type}")
            raise MCPConfigurationError(f"Invalid node type: {self.node_type}")

        # Check if handler received empty messages (might be valid case upstream)
        if not self.messages and not self.original_response:
             logger.warning("Handler initialized with no messages and no original_response.")
             # Don't raise error here, let execute_tools handle it if needed

        logger.info("Handler input arguments assigned and validated successfully.")
        logger.info(f"Handler processing {len(self.messages)} messages")
        # (Keep logging)

    def execute_tools(self) -> str:
        """
        Calls the MCP tool executor and processes the results.

        Returns:
            String containing formatted tool execution results, or the original
            response if no tool calls were made or processed.

        Raises:
            MCPToolExecutionError: If tool execution fails and validation is enabled.
            MCPIntegrationError: For unexpected errors during execution.
        """
        logger.info("Executing MCP tool calls...")

        # Prepare messages to send to executor
        messages_to_send = self.messages.copy()
        if self.original_response:
            logger.info(f"Appending original response to messages for executor: {self.original_response[:100]}...")
            messages_to_send.append({"role": "assistant", "content": self.original_response})
        elif not messages_to_send:
             # If no messages and no original_response, executor likely can't function
             logger.warning("No messages or original_response provided for execution.")
             return ""
        else:
            # This case shouldn't happen if we expect an LLM response before execution,
            # but handle defensively.
            logger.warning("No original_response provided. Executor might fail if it expects one.")

        try:
            logger.info("Calling MCP tool executor's Invoke function...")
            # Pass the necessary arguments to the executor's Invoke
            executor_result = mcp_tool_executor.Invoke(
                messages=messages_to_send, # Always pass messages kwarg
                mcpo_url=self.mcpo_url,
                tool_execution_map=self.tool_execution_map
            )
            logger.info(f"MCP tool executor result: {executor_result}")

            # Process executor result
            if executor_result.get("has_tool_call"):
                if not self.tool_execution_map:
                    error_msg = "MCP Integration Error: Tool calls were detected, but the tool execution map is empty. Cannot execute tools."
                    logger.error(error_msg)
                    # You could raise an exception here or return a formatted error string.
                    # Returning a string might be more resilient in a workflow.
                    # raise MCPConfigurationError(error_msg)
                    return error_msg # Return error string

                tool_results = executor_result.get("tool_results", [])
                logger.info(f"Tool call detected, formatting {len(tool_results)} results")

                # Check for errors if validation is enabled
                if self.validate_execution:
                    errors = [r["result"] for r in tool_results if r.get("result") and "error" in r["result"]]
                    if errors:
                        logger.error(f"Tool execution validation failed. Errors: {errors}")
                        raise MCPToolExecutionError("Tool execution validation failed", details=errors)

                # Return only the formatted results
                formatted_results = format_results_only(tool_results)
                logger.info(f"Returning formatted tool results only: {formatted_results[:300]}...")
                return formatted_results
            else:
                # If executor didn't find/execute a tool call, return the original response
                # Use the response from the executor if available, otherwise use the input one
                response_to_return = executor_result.get("response", self.original_response)
                logger.info(f"No tool call processed by executor, returning original response: {response_to_return[:100] if response_to_return else 'empty string'}")
                return response_to_return or ""

        except MCPToolExecutionError as e:
            # Re-raise specific execution errors caught during validation
            logger.error(f"Tool execution failed during validation: {e}")
            raise e # Propagate the error
        except Exception as e:
            # Catch unexpected errors from the executor call
            logger.exception(f"Unexpected error calling mcp_tool_executor.Invoke: {e}")
            raise MCPIntegrationError(f"Unexpected error during tool execution: {str(e)}") from e


def Invoke(*args, **kwargs) -> str:
    """
    Main entry point for the MCP workflow integration module.
    Instantiates MCPWorkflowHandler to execute MCP tool calls based on inputs.

    Args:
        *args: Variable length argument list.
               arg[0] (raw_messages): Messages list or string.
               arg[1] (original_response): Optional LLM response.
        **kwargs: Arbitrary keyword arguments.

    Keyword Args:
        messages: Messages list or string.
        original_response: LLM response.
        mcpo_url: Base URL for the MCPO server.
        tool_execution_map: Map from operationId to execution details (can be dict or JSON string).
        validate_execution: Whether to validate tool execution.
        node_type: Type of the node (for validation).

    Returns:
        String containing tool execution results or the original response.

    Raises:
        MCPConfigurationError: If configuration (e.g., tool_map, node_type) is invalid.
        MCPMessageParsingError: If messages input cannot be parsed correctly.
        MCPIntegrationError: For other unexpected errors during initialization or execution.
        MCPToolExecutionError: Propagated from the handler if execution fails validation.
    """
    try:
        # --- Input Parsing/Extraction ---
        raw_messages_arg = args[0] if args else None
        original_response_arg = args[1] if len(args) > 1 else ""

        raw_messages = kwargs.get('messages', raw_messages_arg)
        original_response = kwargs.get('original_response', original_response_arg)
        raw_tool_execution_map = kwargs.get("tool_execution_map")

        # --- Parse Inputs ---
        # Parse tool_execution_map
        parsed_tool_execution_map = _parse_tool_execution_map_static(raw_tool_execution_map)
        # Parse messages
        parsed_messages = _parse_messages_input_static(raw_messages)

        # --- Prepare Handler Args ---
        handler_kwargs = kwargs.copy()
        handler_kwargs['messages'] = parsed_messages # Pass PARSED messages
        handler_kwargs['original_response'] = original_response
        handler_kwargs['tool_execution_map'] = parsed_tool_execution_map # Pass PARSED map

        # Remove keys potentially derived from args to avoid duplicates if passed positionally
        # Example: if 'messages' was in args[0], remove it from kwargs if also present
        # Simplified: Assume core data (messages, map) primarily via kwargs now
        args_to_pass = ()

        # --- Instantiate Handler ---
        handler = MCPWorkflowHandler(*args_to_pass, **handler_kwargs)

        # --- Execute ---
        return handler.execute_tools()

    except MCPToolExecutionError as e:
        # Format execution errors for user output
        logger.error(f"Tool execution failed: {e}")
        error_message = f"Tool execution failed: {str(e)}"
        if hasattr(e, 'details') and e.details:
            try:
                error_message += f" - Details: {json.dumps(e.details, indent=2)}"
            except TypeError: # Handle non-serializable details
                 error_message += f" - Details: {e.details}"
        return error_message
    # Propagate parsing/config errors raised during input processing or handler init
    except (MCPMessageParsingError, MCPConfigurationError) as e:
         logger.error(f"Input parsing/configuration error: {e}")
         raise e
    except MCPIntegrationError as e:
        # Catch-all for other integration errors during execution/init
        logger.error(f"MCP integration error: {e}. Raising.")
        raise e
    except Exception as e:
         # Catch truly unexpected errors
         logger.exception(f"Unexpected error during Invoke: {e}")
         raise MCPIntegrationError(f"Unexpected error during Invoke: {str(e)}") from e