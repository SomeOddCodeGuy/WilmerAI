# middleware/utilities/structured_output_utils.py
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Wrapper styles the "structuredOutput" ApiType block may declare. The block is
# declarative, like "thinking" and "samplerFieldMap": "field" names the payload
# key the schema is written to (dotted for nesting, e.g. "structured_outputs.json"),
# and "style" names how the schema value is wrapped there. Adding a new API type
# with structured-output support is therefore pure JSON unless it needs a wrapper
# shape not listed here (those are implemented in
# LlmApiHandler._attach_structured_output).
#   - "openaiJsonSchema": {"type": "json_schema", "json_schema": {name, strict, schema}}
#   - "raw": the JSON schema object itself
SUPPORTED_STYLES = ("openaiJsonSchema", "raw")


def get_structured_output_config(api_type_config: Any) -> Optional[Dict[str, str]]:
    """
    Reads and validates the structured-output block an API type declares.

    Args:
        api_type_config: The parsed ApiTypes config dict for an endpoint.

    Returns:
        Optional[Dict[str, str]]: The {"field", "style", "strict"} block when
        the API type declares a valid one; None when the block is absent or
        invalid (an invalid block is logged). "strict" (default True) only
        affects the "openaiJsonSchema" style: backends implementing OpenAI's
        strict mode reject schemas lacking additionalProperties:false, so API
        types aimed at such backends can declare "strict": false to send the
        schema in non-strict mode instead of erroring.
    """
    if not isinstance(api_type_config, dict):
        return None
    block = api_type_config.get("structuredOutput")
    if not isinstance(block, dict):
        return None
    field = block.get("field")
    style = block.get("style")
    if isinstance(field, str) and field and style in SUPPORTED_STYLES:
        return {"field": field, "style": style, "strict": bool(block.get("strict", True))}
    logger.warning("ApiType declares an invalid structuredOutput block "
                   "(field=%r, style=%r); treating as unsupported. Valid styles: %s.",
                   field, style, ", ".join(SUPPORTED_STYLES))
    return None


def _tool_entry_schema(tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Builds the {"name", "arguments"} schema for one OpenAI-format tool entry.

    Args:
        tool (Dict[str, Any]): One entry from an OpenAI-format tools array.

    Returns:
        Optional[Dict[str, Any]]: The schema constraining a call to this tool,
        or None when the entry is malformed (no function name).
    """
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    parameters = function.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        parameters = {"type": "object"}
    return {
        "type": "object",
        "properties": {
            "name": {"const": name},
            "arguments": parameters,
        },
        "required": ["name", "arguments"],
    }


def build_tool_enforcement_schema(tools: Optional[List[Dict[str, Any]]],
                                  tool_choice: Any) -> Optional[Dict[str, Any]]:
    """
    Builds the JSON schema that constrains a model response to a tool call.

    Produces a schema for the {"name": ..., "arguments": {...}} shape Wilmer
    converts back into an OpenAI tool_calls response. For a forced-function
    tool_choice the schema pins that single tool (using its parameter schema
    when it is among the definitions); for tool_choice "required" the schema is
    an anyOf across every defined tool.

    Args:
        tools (Optional[List[Dict[str, Any]]]): OpenAI-format tool definitions.
        tool_choice: The request's tool_choice value.

    Returns:
        Optional[Dict[str, Any]]: The constraint schema, or None when
        tool_choice does not demand a call (absent/auto/none) or nothing
        usable can be built.
    """
    forced_name = get_forced_tool_name(tool_choice)
    if forced_name:
        for tool in tools or []:
            entry = _tool_entry_schema(tool)
            if entry and entry["properties"]["name"]["const"] == forced_name:
                return entry
        # Pinned tool not among the definitions: constrain to the pinned name
        # with open arguments rather than silently not constraining.
        return {
            "type": "object",
            "properties": {"name": {"const": forced_name},
                           "arguments": {"type": "object"}},
            "required": ["name", "arguments"],
        }
    if tool_choice == "required":
        entries = [entry for tool in tools or []
                   if (entry := _tool_entry_schema(tool))]
        if not entries:
            return None
        if len(entries) == 1:
            return entries[0]
        return {"anyOf": entries}
    return None


def get_forced_tool_name(tool_choice: Any) -> Optional[str]:
    """
    Extracts the function name from a forced-function tool_choice.

    Args:
        tool_choice: The request's tool_choice value.

    Returns:
        Optional[str]: The pinned function name, or None when tool_choice is
        not the forced-function object form.
    """
    if not isinstance(tool_choice, dict) or tool_choice.get("type") != "function":
        return None
    function = tool_choice.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    return name if isinstance(name, str) and name else None


def build_tools_description_text(tools: Optional[List[Dict[str, Any]]],
                                 tool_choice: Any) -> str:
    """
    Renders tool definitions as text for injection into a constrained round.

    Grammar-constrained backends do not show the model the schema, and the
    native tools field is dropped on constrained rounds (the combination is
    unsupported on llama.cpp and Ollama), so the model must be told about the
    tools in the prompt.

    Args:
        tools (Optional[List[Dict[str, Any]]]): OpenAI-format tool definitions.
        tool_choice: The request's tool_choice value.

    Returns:
        str: A description block, or an empty string when there are no tools.
    """
    lines = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = function.get("description") or ""
        parameters = function.get("parameters")
        lines.append(f"- {name}: {description}".rstrip(": "))
        if isinstance(parameters, dict) and parameters:
            lines.append(f"  parameters (JSON Schema): {json.dumps(parameters)}")
    if not lines:
        return ""
    forced_name = get_forced_tool_name(tool_choice)
    if forced_name:
        requirement = (f"You must respond by calling the tool '{forced_name}'. ")
    else:
        requirement = "You must respond by calling exactly one of these tools. "
    return ("The following tools are available:\n" + "\n".join(lines) + "\n\n"
            + requirement
            + "Respond with a single JSON object of the form "
              '{"name": <tool name>, "arguments": {<tool arguments>}} and nothing else.')


def parse_constrained_tool_response(text: Any,
                                    tools: Optional[List[Dict[str, Any]]],
                                    tool_choice: Any = None) -> Optional[Dict[str, Any]]:
    """
    Parses a constrained round's text output into a tool call, if valid.

    The constraint mechanism guarantees this parse succeeds on enforcing
    backends; on fail-open backends (llama.cpp bad-grammar 200s, servers that
    silently ignore the constraint field) unconstrained prose arrives here and
    fails the parse, which callers treat as a miss.

    Args:
        text: The raw response text from the constrained round.
        tools (Optional[List[Dict[str, Any]]]): The request's tool definitions.
        tool_choice: The request's tool_choice value (a forced pin also
            admits its name even if absent from the definitions).

    Returns:
        Optional[Dict[str, Any]]: {"name": str, "arguments": dict} when the
        text is a valid call to a known tool; None otherwise.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("name")
    arguments = parsed.get("arguments")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(arguments, dict):
        return None
    known_names = set()
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            known_names.add(function["name"])
    forced_name = get_forced_tool_name(tool_choice)
    if forced_name:
        known_names.add(forced_name)
    if name not in known_names:
        return None
    return {"name": name, "arguments": arguments}


def load_structured_output_schema(name: str) -> Dict[str, Any]:
    """
    Loads an author-declared structured-output schema by name.

    Resolution mirrors the other named config collections: the file is looked
    up under ``Public/Configs/StructuredOutputs/<sub>/<name>.json`` where
    ``<sub>`` is the user config's ``structuredOutputConfigsSubDirectory``
    (defaulting to the current username), falling back to the
    ``StructuredOutputs`` root when the subdirectory copy does not exist.

    Args:
        name (str): The schema name a workflow node referenced via its
            ``structuredOutputFile`` property.

    Returns:
        Dict[str, Any]: The parsed JSON schema.

    Raises:
        ValueError: When the name is path-unsafe, the file cannot be parsed,
            or it does not contain a non-empty JSON object.
        FileNotFoundError: When no schema file exists at either location.
    """
    import os

    from Middleware.utilities import config_utils

    if not config_utils._is_safe_flat_config_name(name):
        raise ValueError(f"structuredOutputFile '{name}' is not a valid config name.")
    sub_directory = (config_utils.get_config_value('structuredOutputConfigsSubDirectory')
                     or config_utils.get_current_username())
    path = config_utils.get_config_with_subdirectory("StructuredOutputs", sub_directory, name)
    if not os.path.exists(path):
        path = config_utils.get_config_with_subdirectory("StructuredOutputs", "", name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"structuredOutputFile '{name}' was not found in Configs/StructuredOutputs/ "
            f"(checked subdirectory '{sub_directory}' and the root).")
    try:
        schema = config_utils.load_config(path)
    except ValueError as e:
        raise ValueError(
            f"structuredOutputFile '{name}' at '{path}' could not be parsed: {e}") from e
    if not isinstance(schema, dict) or not schema:
        raise ValueError(
            f"structuredOutputFile '{name}' must contain a non-empty JSON object schema.")
    return schema


def build_tool_calls_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wraps a parsed constrained tool call in Wilmer's internal response shape.

    Args:
        parsed (Dict[str, Any]): {"name", "arguments"} from
            parse_constrained_tool_response.

    Returns:
        Dict[str, Any]: The {'content', 'tool_calls', 'finish_reason'} dict the
        existing tool-call pipeline consumes.
    """
    return {
        "content": "",
        "tool_calls": [{
            "id": f"wilmer-{uuid.uuid4().hex}",
            "type": "function",
            "function": {
                "name": parsed["name"],
                "arguments": json.dumps(parsed["arguments"]),
            },
        }],
        "finish_reason": "tool_calls",
    }
