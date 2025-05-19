import json
import logging
import requests
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default MCPO server base URL (used if not provided in constructor)
DEFAULT_MCPO_URL = os.environ.get("MCPO_URL", "http://localhost:8889")

class MCPServiceDiscoverer:
    """
    Handles discovery and processing of MCP tools from OpenAPI schemas.

    Responsibilities:
    - Fetching OpenAPI schemas from specified MCP services.
    - Validating the structure of schemas and tool definitions.
    - Processing schemas to extract tool details (execution info + LLM schema).
    - Combining tools from multiple services.
    """
    def __init__(self, mcpo_url: str = DEFAULT_MCPO_URL):
        """
        Initializes the discoverer with the MCPO base URL.

        Args:
            mcpo_url: Base URL for the MCPO server. Defaults to DEFAULT_MCPO_URL.
        """
        self.mcpo_url = mcpo_url
        logger.info(f"MCPServiceDiscoverer initialized with MCPO URL: {self.mcpo_url}")

    def fetch_service_schema(self, service_name: str) -> Optional[Dict]:
        """
        Fetch the OpenAPI schema for a single service.

        Args:
            service_name: Name of the service (e.g., "time").

        Returns:
            OpenAPI schema as dictionary, or None if fetching or parsing fails.
        """
        schema_url = f"{self.mcpo_url}/{service_name}/openapi.json"
        logger.info(f"Fetching schema for service '{service_name}' from {schema_url}")
        try:
            schema_response = requests.get(schema_url, timeout=30)
            schema_response.raise_for_status() # Check for HTTP errors
            schema_json = schema_response.json()
            logger.info(f"Successfully fetched schema for '{service_name}'.")
            return schema_json
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching schema for service '{service_name}' from {schema_url}")
            return None
        except requests.exceptions.RequestException as e:
            # Log HTTP errors or connection issues
            logger.error(f"Failed to fetch schema for service '{service_name}' from {schema_url}: {e}")
            return None
        except json.JSONDecodeError as e:
            # Log errors if the response is not valid JSON
            logger.error(f"Invalid JSON received for schema of service '{service_name}' from {schema_url}: {e}")
            return None
        except Exception as e:
            # Catch any other unexpected errors during fetching
            logger.exception(f"Unexpected error fetching schema for service '{service_name}': {e}")
            return None

    def validate_tool_schema(self, schema: Dict, service_name: str) -> bool:
        """
        Validate that an OpenAPI schema has the required structure for tool discovery.
        Logs warnings for non-critical missing fields.

        Args:
            schema: OpenAPI schema dictionary to validate.
            service_name: Name of the service (for logging).

        Returns:
            bool: True if the essential 'paths' key exists, False otherwise.
        """
        if not isinstance(schema, dict):
            logger.error(f"Schema validation failed for '{service_name}': Input is not a dictionary.")
            return False

        if "paths" not in schema:
            logger.error(f"Schema validation failed for '{service_name}': Missing required 'paths' key.")
            return False

        # Optional checks with warnings
        for path, methods in schema.get("paths", {}).items():
            if not isinstance(methods, dict):
                 logger.warning(f"Schema check for '{service_name}': Path '{path}' item is not a dictionary of methods.")
                 continue
            for method, details in methods.items():
                 if not isinstance(details, dict):
                      logger.warning(f"Schema check for '{service_name}': Method '{method}' for path '{path}' is not a dictionary.")
                      continue
                 if not details.get("operationId"):
                     logger.warning(f"Schema check for '{service_name}': Missing operationId in {path} {method}. Tool cannot be called by name.")
                 if not details.get("description") and not details.get("summary"):
                     logger.warning(f"Schema check for '{service_name}': Missing description/summary in {path} {method}. LLM may lack context.")

        logger.debug(f"Basic schema validation passed for '{service_name}'.")
        return True

    def create_llm_schema(self, endpoint_details: Dict, full_schema: Dict) -> Dict:
        """
        Create an LLM-compatible function schema from OpenAPI endpoint details.
        Handles parameters from 'parameters' list and 'requestBody'. Resolves simple local refs.

        Args:
            endpoint_details: Dictionary of a specific endpoint (e.g., schema['paths']['/path']['get']).
            full_schema: The complete OpenAPI schema (for resolving $ref).

        Returns:
            Dictionary containing the LLM-compatible function schema.
        """
        operation_id = endpoint_details.get("operationId")
        if not operation_id:
            # This case should ideally be filtered out earlier, but handle defensively
            logger.error("Cannot create LLM schema: Missing operationId.")
            # Return an empty or placeholder structure might be better than raising error here.
            return {"type": "function", "name": "unknown_operation", "description": "Error: Missing operationId", "parameters": {}}

        description = endpoint_details.get("description") or endpoint_details.get("summary") or f"Execute {operation_id}"
        logger.debug(f"Creating LLM schema for {operation_id}. Description: '{description[:50]}...'")

        llm_schema = {
            "type": "function",
            "name": operation_id, # Use operationId directly as the function name
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
        properties = llm_schema["parameters"]["properties"]
        required = llm_schema["parameters"]["required"]

        # --- Process 'parameters' list (query, path, header, cookie) ---
        for param in endpoint_details.get("parameters", []):
            if isinstance(param, dict) and param.get("in") in ["query", "path", "header", "cookie"]:
                param_name = param.get("name")
                if param_name:
                    param_schema = param.get("schema", {})
                    properties[param_name] = {
                        "type": param_schema.get("type", "string"),
                        "description": param.get("description", param_schema.get("description", "")) # Prefer param description
                    }
                    # Add enum if present
                    if "enum" in param_schema:
                         properties[param_name]["enum"] = param_schema["enum"]
                    # Add default if present
                    if "default" in param_schema:
                         properties[param_name]["default"] = param_schema["default"]

                    if param.get("required"):
                        if param_name not in required:
                            required.append(param_name)
                    logger.debug(f"Added parameter '{param_name}' from 'parameters' list for {operation_id}")
                else:
                     logger.warning(f"Skipping parameter without name in {operation_id}")

        # --- Process 'requestBody' ---
        request_body = endpoint_details.get("requestBody")
        if isinstance(request_body, dict):
            logger.debug(f"Processing requestBody for {operation_id}")
            content_schema_ref = request_body.get("content", {}).get("application/json", {}).get("schema")

            if isinstance(content_schema_ref, dict):
                resolved_schema = content_schema_ref
                # Resolve simple local $ref
                if "$ref"in content_schema_ref:
                    ref_path = content_schema_ref["$ref"]
                    logger.debug(f"Resolving requestBody schema reference: {ref_path}")
                    try:
                        parts = ref_path.split('/')
                        if len(parts) == 4 and parts[0] == '#' and parts[1] == 'components' and parts[2] == 'schemas':
                            schema_name = parts[3]
                            resolved_schema = full_schema.get("components", {}).get("schemas", {}).get(schema_name)
                            if not isinstance(resolved_schema, dict):
                                logger.warning(f"Failed to resolve reference '{ref_path}' or resolved value is not a dict.")
                                resolved_schema = None # Mark as unresolved
                        else:
                            logger.warning(f"Unsupported reference format: {ref_path}")
                            resolved_schema = None # Mark as unresolved
                    except Exception as e:
                        logger.error(f"Error resolving reference {ref_path}: {e}")
                        resolved_schema = None # Mark as unresolved

                # Extract properties if we have a valid, resolved object schema
                if isinstance(resolved_schema, dict) and resolved_schema.get("type") == "object" and "properties" in resolved_schema:
                    logger.debug(f"Extracting properties from resolved requestBody schema for {operation_id}")
                    req_body_props = resolved_schema.get("properties", {})
                    req_body_required = resolved_schema.get("required", [])

                    for prop_name, prop_details in req_body_props.items():
                        if isinstance(prop_details, dict):
                             # Avoid overwriting properties defined in 'parameters' list
                             if prop_name not in properties:
                                 properties[prop_name] = {
                                     "type": prop_details.get("type", "string"),
                                     "description": prop_details.get("description", "")
                                 }
                                 # Add enum/default if present in request body property
                                 if "enum" in prop_details:
                                      properties[prop_name]["enum"] = prop_details["enum"]
                                 if "default" in prop_details:
                                      properties[prop_name]["default"] = prop_details["default"]

                                 logger.debug(f"Added parameter '{prop_name}' from requestBody schema for {operation_id}")
                             else:
                                 logger.warning(f"Parameter '{prop_name}' from requestBody conflicts with existing parameter for {operation_id}. Keeping existing.")
                        else:
                             logger.warning(f"Property '{prop_name}' in requestBody schema for {operation_id} is not a dictionary. Skipping.")

                    # Add required fields from request body schema
                    for req_prop in req_body_required:
                        if isinstance(req_prop, str) and req_prop not in required:
                            required.append(req_prop)
                elif resolved_schema: # If resolved_schema exists but isn't a valid object schema
                    logger.warning(f"RequestBody schema for {operation_id} is not a processable object with properties. Schema: {resolved_schema}")
            else:
                logger.debug(f"No application/json schema found or schema is not a dict in requestBody for {operation_id}")
        else:
             logger.debug(f"No requestBody found for {operation_id}")


        # Clean up empty required list and properties object
        if not required:
            del llm_schema["parameters"]["required"]
        if not properties:
             # If no properties, set parameters to an empty dict as per some standards,
             # though OpenAI spec might prefer the structure with empty properties/optional required.
             # Let's keep the structure but log it.
             logger.debug(f"No parameters found for tool {operation_id}. Keeping standard structure with empty properties.")
             # llm_schema["parameters"] = {} # Alternative: Set parameters to empty dict

        logger.debug(f"Final LLM schema for {operation_id}: {json.dumps(llm_schema, indent=2)}")
        return llm_schema

    def validate_tool_definition(self, tool_schema: Dict) -> bool:
        """
        Validate that a generated LLM tool schema has the required fields.

        Args:
            tool_schema: The LLM tool schema dictionary to validate.

        Returns:
            bool: True if valid, False otherwise.
        """
        if not isinstance(tool_schema, dict):
            logger.error("Tool definition validation failed: Input is not a dictionary.")
            return False

        required_fields = ["type", "name", "description", "parameters"]
        missing_fields = [field for field in required_fields if field not in tool_schema]
        if missing_fields:
            logger.error(f"Tool definition validation failed for '{tool_schema.get('name', 'unknown')}': Missing required fields: {missing_fields}")
            return False

        if tool_schema["type"] != "function":
            logger.error(f"Tool definition validation failed for '{tool_schema['name']}': Invalid tool type '{tool_schema['type']}', expected 'function'.")
            return False

        # Validate parameters structure: must be a dict.
        # Can be empty {} if no parameters, or {"type": "object", "properties": {...}}
        if not isinstance(tool_schema["parameters"], dict):
            logger.error(f"Tool definition validation failed for '{tool_schema['name']}': 'parameters' field must be a dictionary, got {type(tool_schema['parameters']).__name__}.")
            return False

        # Further checks if parameters is not empty
        if tool_schema["parameters"]:
             if tool_schema["parameters"].get("type") != "object":
                  logger.error(f"Tool definition validation failed for '{tool_schema['name']}': If parameters is not empty, its 'type' must be 'object'.")
                  return False
             if "properties" not in tool_schema["parameters"] or not isinstance(tool_schema["parameters"]["properties"], dict):
                  logger.error(f"Tool definition validation failed for '{tool_schema['name']}': If parameters is not empty, it must contain a 'properties' dictionary.")
                  return False
             if "required" in tool_schema["parameters"] and not isinstance(tool_schema["parameters"]["required"], list):
                  logger.error(f"Tool definition validation failed for '{tool_schema['name']}': Optional 'required' field in parameters must be a list.")
                  return False


        logger.debug(f"Tool definition validation passed for '{tool_schema['name']}'.")
        return True

    def process_service_schema(self, schema: Dict, service_name: str) -> Dict[str, Dict]:
        """
        Process a single validated OpenAPI schema to extract tool details.

        Args:
            schema: The validated OpenAPI schema dictionary.
            service_name: Name of the service this schema belongs to.

        Returns:
            Dictionary mapping operationId to tool details (service, path, method, llm_schema).
            Filters out endpoints without operationId.
        """
        service_tools_map = {}
        paths = schema.get("paths", {})

        if not isinstance(paths, dict):
             logger.error(f"Cannot process schema for '{service_name}': 'paths' is not a dictionary.")
             return {}

        logger.info(f"Processing schema for service '{service_name}', found {len(paths)} paths.")

        for path, methods in paths.items():
             if not isinstance(methods, dict):
                  logger.warning(f"Skipping path '{path}' in '{service_name}': Entry is not a dictionary of methods.")
                  continue

             for method, details in methods.items():
                  if not isinstance(details, dict):
                       logger.warning(f"Skipping method '{method}' in path '{path}' of '{service_name}': Entry is not a dictionary.")
                       continue

                  operation_id = details.get("operationId")
                  if not operation_id:
                      logger.warning(f"Skipping {method.upper()} {path} in '{service_name}': Missing required 'operationId'.")
                      continue # Skip if no operationId (required for reliable tool calls)

                  logger.debug(f"Processing operationId '{operation_id}' ({method.upper()} {path}) in service '{service_name}'.")

                  # Create the LLM schema part
                  llm_schema = self.create_llm_schema(details, schema)

                  # Extract request body schema if present
                  request_body_schema = None
                  request_body_content = details.get("requestBody", {}).get("content", {})
                  # Check specifically for application/json schema
                  if "application/json" in request_body_content and "schema" in request_body_content["application/json"]:
                      request_body_schema = request_body_content["application/json"]["schema"]
                      logger.debug(f"Found request body schema for {operation_id}")

                  # Store details for the execution map
                  # (Store details regardless of llm_schema validation)
                  tool_details_entry = {
                      "service": service_name,
                      "path": path,
                      "method": method.lower(), # Store method in lowercase standard
                      "llm_schema": llm_schema,
                      # Store parameter details extracted from OpenAPI 'parameters' list
                      # Needed by the executor to differentiate query/path/header/cookie params
                      "openapi_params": details.get("parameters", [])
                  }

                  # Add request body schema to map entry
                  if request_body_schema:
                       tool_details_entry["request_body_schema"] = request_body_schema

                  service_tools_map[operation_id] = tool_details_entry
                  logger.debug(f"Stored details for operationId '{operation_id}'.")

        logger.info(f"Finished processing schema for '{service_name}', extracted {len(service_tools_map)} tools with operationIds.")
        return service_tools_map

    def discover_mcp_tools(self, service_names: List[str]) -> Dict[str, Dict]:
        """
        Discover available tools by fetching and processing schemas for multiple services.

        Args:
            service_names: List of MCP service names (e.g., ["time", "weather"]).

        Returns:
            Dictionary mapping operationId to its execution details and LLM schema.
            Example: { "opId": { "service": "svc", "path": "/p", "method": "post", "llm_schema": {...} }, ... }
            Returns an empty dict if no services are provided or no tools are found.
        """
        if not service_names:
            logger.warning("discover_mcp_tools called with empty service_names list.")
            return {}

        all_tools_map = {}
        logger.info(f"Starting tool discovery for services: {service_names}")

        for service_name in service_names:
            if not isinstance(service_name, str) or not service_name:
                 logger.warning(f"Skipping invalid service name: {service_name}")
                 continue

            schema = self.fetch_service_schema(service_name)
            if not schema:
                logger.warning(f"Could not fetch schema for service '{service_name}', skipping.")
                continue

            # Validate the basic structure needed for processing
            if not self.validate_tool_schema(schema, service_name):
                logger.error(f"Invalid or incomplete schema structure for service '{service_name}', skipping processing.")
                continue

            # Process the valid schema to extract tools
            try:
                service_tools = self.process_service_schema(schema, service_name)
                if service_tools:
                     # Check for duplicate operationIds across services
                     duplicates = [op_id for op_id in service_tools if op_id in all_tools_map]
                     if duplicates:
                          logger.warning(f"Duplicate operationId(s) found while processing '{service_name}': {duplicates}. Tools from '{service_name}' will overwrite existing ones.")
                     # Merge the discovered tools, potentially overwriting duplicates
                     all_tools_map.update(service_tools)
                     logger.info(f"Added/updated {len(service_tools)} tools from service '{service_name}'.")
                else:
                     logger.info(f"No tools with operationIds found in schema for service '{service_name}'.")
            except Exception as e:
                # Catch unexpected errors during schema processing for a single service
                logger.exception(f"Unexpected error processing schema for service '{service_name}': {e}")
                continue # Continue to the next service

        logger.info(f"Completed tool discovery. Found {len(all_tools_map)} tools in total across {len(service_names)} requested services.")
        return all_tools_map

    def discover_and_validate_mcp_tools(self, service_names: List[str], validate_llm_schema: bool = False) -> Dict[str, Dict]:
        """
        High-level method to discover tools and optionally validate their LLM schemas.

        Args:
            service_names: List of service names to discover tools for.
            validate_llm_schema: If True, validate the generated LLM schema for each tool
                                 using `validate_tool_definition` and exclude invalid tools.

        Returns:
            Dictionary mapping operationId to tool details. Only includes tools that
            passed validation if `validate_llm_schema` is True.
        """
        # Step 1: Discover all tools first
        discovered_tools_map = self.discover_mcp_tools(service_names)

        if not discovered_tools_map:
            logger.info("No tools discovered.")
            return {}

        if not validate_llm_schema:
            logger.info(f"Tool validation skipped. Returning all {len(discovered_tools_map)} discovered tools.")
            return discovered_tools_map

        # Step 2: Validate LLM schemas if requested
        logger.info(f"Validating LLM schemas for {len(discovered_tools_map)} discovered tools.")
        validated_tools_map = {}
        invalid_count = 0
        for op_id, details in discovered_tools_map.items():
            llm_schema = details.get("llm_schema")
            if isinstance(llm_schema, dict) and self.validate_tool_definition(llm_schema):
                validated_tools_map[op_id] = details
                logger.debug(f"Validation passed for tool '{op_id}'.")
            else:
                logger.warning(f"LLM schema validation failed for tool '{op_id}'. Excluding from results. Schema: {llm_schema}")
                invalid_count += 1

        if not validated_tools_map:
             logger.error(f"No valid tools found after LLM schema validation (checked {len(discovered_tools_map)}, {invalid_count} failed).")
             return {}

        logger.info(f"{len(validated_tools_map)} tools remain after LLM schema validation ({invalid_count} failed).")
        return validated_tools_map 