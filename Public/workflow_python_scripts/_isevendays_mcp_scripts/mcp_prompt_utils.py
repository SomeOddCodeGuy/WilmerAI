import logging
import re
import json
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _format_mcp_tools_for_llm_prompt(tools_map: Dict) -> str:
    """Format discovered tools (from map) as a system prompt section for LLMs.

    Expects the map values to have an 'llm_schema' key.

    Args:
        tools_map (Dict): Dictionary mapping operationId to details including llm_schema.

    Returns:
        str: Formatted system prompt section with tool definitions, or empty string if no tools.
    """
    if not tools_map:
        logger.info("No tools provided to format for LLM prompt.")
        return ""

    # Extract just the llm_schema part for formatting
    llm_schemas = []
    for op_id, details in tools_map.items():
        if isinstance(details, dict) and "llm_schema" in details:
            llm_schemas.append(details["llm_schema"])
        else:
            logger.warning(f"Tool '{op_id}' in tools_map is missing 'llm_schema'. Skipping for prompt formatting.")

    if not llm_schemas:
        logger.warning("No valid llm_schemas found in tools_map to format.")
        return ""

    try:
        # Serialize the list of LLM schema dictionaries
        tools_json = json.dumps(llm_schemas, indent=2)
    except TypeError as e:
        logger.error(f"Failed to serialize LLM tool schemas to JSON: {e}")
        return "" # Return empty string on serialization error

    # Use pre-formatted strings for examples to avoid complex escapes
    empty_example = '''{\n     "tool_calls": []\n   }'''
    tool_call_example = '''{\n  "tool_calls": [\n    {"name": "toolName1", "parameters": {"key1": "value1"}},\n    {"name": "toolName2", "parameters": {"key2": "value2"}}\n  ]\n}'''

    # Construct the prompt section
    system_prompt_section = f"""Available Tools: {tools_json}

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
    logger.info(f"Formatted tools section for LLM prompt with {len(llm_schemas)} tools.")
    return system_prompt_section

def _integrate_tools_into_prompt(original_prompt: str, tools_prompt_section: str) -> str:
    """Update a prompt by replacing an existing tools section or appending a new one.

    Looks for a block starting with "Available Tools:" and ending before "<required_format>" or end of string.

    Args:
        original_prompt (str): The original prompt string.
        tools_prompt_section (str): Formatted tools section string (including "Available Tools:") to add/replace.

    Returns:
        str: Updated prompt string.
    """
    if not tools_prompt_section:
         logger.warning("_integrate_tools_into_prompt called with empty tools_prompt_section. Returning original prompt.")
         return original_prompt

    # A fully-integrated section spans from "Available Tools:" through the closing
    # </required_format> tag and the single-line CRITICAL trailer that
    # _format_mcp_tools_for_llm_prompt emits after it. The replacement must consume
    # that entire span: replacing only the part before <required_format> (the
    # historical behavior) left the old format block behind, so every
    # re-enhancement appended a duplicate <required_format> section to the prompt.
    full_section_pattern = re.compile(
        r'Available\s+Tools\s*:[\s\S]*?</required_format>\s*(?:CRITICAL:[^\n]*)?',
        re.IGNORECASE)
    # Fallback for a bare "Available Tools:" block without a format section
    # (e.g. hand-written prompts): match through the end of the string or up to
    # a format block that the new section will supply.
    bare_section_pattern = r'(Available\s+Tools\s*:\s*[\s\S]*?)(?=\n\n<required_format>|\Z)'

    full_matches = list(full_section_pattern.finditer(original_prompt))
    if full_matches:
        first = full_matches[0]
        logger.info(f"Replacing existing 'Available Tools' section found at index {first.start()}.")
        tail = original_prompt[first.end():]
        # Remove any extra sections left behind by the historical duplicating
        # behavior so previously-affected prompts heal on the next enhancement.
        tail = full_section_pattern.sub('', tail)
        # The historical duplication actually left HEADER-LESS format blocks
        # stacked directly after the one "Available Tools:" section (one block
        # + CRITICAL trailer per re-enhancement), which the header-anchored
        # pattern above cannot see. Consume them from the front of the tail
        # only, so an unrelated format block deeper in the prompt is never
        # touched.
        orphan_block_pattern = re.compile(
            r'\s*<required_format>[\s\S]*?</required_format>\s*(?:CRITICAL:[^\n]*)?',
            re.IGNORECASE)
        while True:
            orphan = orphan_block_pattern.match(tail)
            if not orphan:
                break
            tail = tail[orphan.end():]
        updated_prompt = original_prompt[:first.start()] + tools_prompt_section.strip() + tail
    else:
        match = re.search(bare_section_pattern, original_prompt, re.IGNORECASE | re.MULTILINE)
        if match:
            start_index = match.start(1)
            end_index = match.end(1)
            logger.info(f"Replacing existing bare 'Available Tools' section found at index {start_index}.")
            updated_prompt = original_prompt[:start_index] + tools_prompt_section.strip() + original_prompt[end_index:]
        else:
            logger.info("No existing 'Available Tools' section found. Appending new section.")
            # Add suitable separation (prefer two newlines)
            separator = "\n\n" if original_prompt.strip() else ""
            if original_prompt.strip() and not original_prompt.endswith('\n\n'):
                separator = "\n" if original_prompt.endswith('\n') else "\n\n"

            updated_prompt = original_prompt.rstrip() + separator + tools_prompt_section.strip()

    return updated_prompt 