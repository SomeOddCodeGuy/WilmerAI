# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_mcp_prompt_utils.py

import json

from Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_prompt_utils import (
    _format_mcp_tools_for_llm_prompt,
    _integrate_tools_into_prompt,
)


def _sample_tools_map():
    return {
        "get_current_time": {
            "service": "time",
            "path": "/current",
            "method": "post",
            "llm_schema": {
                "type": "function",
                "name": "get_current_time",
                "description": "Get the current time in a timezone",
                "parameters": {
                    "type": "object",
                    "properties": {"timezone": {"type": "string", "description": ""}},
                    "required": ["timezone"],
                },
            },
        }
    }


def test_format_tools_empty_map_returns_empty_string():
    """
    Tests that an empty tools map produces an empty prompt section.
    """
    assert _format_mcp_tools_for_llm_prompt({}) == ""


def test_format_tools_includes_schema_and_required_format():
    """
    Tests that the formatted prompt section embeds the tool's llm_schema as
    JSON and includes the required_format instructions block.
    """
    # Act
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())

    # Assert: Section starts with the marker and contains the schema and format block.
    assert section.startswith("Available Tools:")
    assert "<required_format>" in section
    assert '"name": "get_current_time"' in section
    # The embedded schema must be valid JSON when extracted between the
    # marker and the instructions.
    embedded = section.split("Available Tools:", 1)[1].split("\n\nYour task", 1)[0]
    schemas = json.loads(embedded)
    assert schemas[0]["name"] == "get_current_time"


def test_format_tools_skips_entries_without_llm_schema():
    """
    Tests that tools_map entries missing the 'llm_schema' key are skipped,
    and that a map with only invalid entries yields an empty string.
    """
    # Arrange: One valid and one invalid entry.
    tools_map = _sample_tools_map()
    tools_map["broken_tool"] = {"service": "x", "path": "/y", "method": "get"}

    # Act
    section = _format_mcp_tools_for_llm_prompt(tools_map)

    # Assert: Valid tool present, broken tool absent.
    assert '"get_current_time"' in section
    assert "broken_tool" not in section

    # An all-invalid map produces no section at all.
    assert _format_mcp_tools_for_llm_prompt({"broken_tool": {"service": "x"}}) == ""


def test_format_tools_unserializable_schema_returns_empty_string():
    """
    Tests that a tools map whose llm_schema cannot be JSON-serialized yields
    an empty prompt section (logged error) instead of a TypeError escaping
    into the workflow.
    """
    tools_map = {
        "bad_tool": {
            "llm_schema": {
                "type": "function",
                "name": "bad_tool",
                "description": "d",
                "parameters": {"unserializable": {1, 2}},
            }
        }
    }
    assert _format_mcp_tools_for_llm_prompt(tools_map) == ""


def test_integrate_tools_appends_when_no_existing_section():
    """
    Tests that the tools section is appended to a prompt that has no
    existing 'Available Tools:' block.
    """
    # Arrange
    original = "You are a helpful assistant."
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())

    # Act
    updated = _integrate_tools_into_prompt(original, section)

    # Assert: Original text retained, section appended after it.
    assert updated.startswith("You are a helpful assistant.")
    assert "Available Tools:" in updated
    assert updated.index("Available Tools:") > updated.index("helpful assistant")


def test_integrate_tools_replaces_existing_section():
    """
    Tests that an existing 'Available Tools:' block is replaced rather
    than duplicated.
    """
    # Arrange: Prompt already containing a stale tools section.
    original = (
        "You are a helpful assistant.\n\n"
        "Available Tools: [{\"name\": \"old_tool\"}]"
    )
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())

    # Act
    updated = _integrate_tools_into_prompt(original, section)

    # Assert: The old tool is gone, the new one present, and only one section exists.
    assert "old_tool" not in updated
    assert '"get_current_time"' in updated
    assert updated.count("Available Tools:") == 1


def test_integrate_tools_with_empty_section_returns_original():
    """
    Tests that an empty tools section leaves the original prompt untouched.
    """
    original = "You are a helpful assistant."
    assert _integrate_tools_into_prompt(original, "") == original


def test_integrate_tools_is_idempotent():
    """
    Re-enhancing an already-enhanced prompt must replace the whole previous
    section in place, not append a second <required_format> block. This is the
    regression test for the historical duplicating behavior.
    """
    base = "You are a helpful assistant."
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())

    once = _integrate_tools_into_prompt(base, section)
    twice = _integrate_tools_into_prompt(once, section)

    assert twice == once
    assert twice.count("<required_format>") == 1
    assert twice.count("Available Tools:") == 1
    assert twice.count("CRITICAL:") == 1


def test_integrate_tools_preserves_text_after_enhanced_section():
    """
    Content that follows a fully-enhanced section (e.g. a persona suffix) must
    survive re-enhancement intact.
    """
    base = "You are a helpful assistant."
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())
    once = _integrate_tools_into_prompt(base, section)
    with_suffix = once + "\n\nAlways answer in French."

    updated = _integrate_tools_into_prompt(with_suffix, section)

    assert updated.endswith("Always answer in French.")
    assert updated.count("<required_format>") == 1


def test_integrate_tools_heals_previously_duplicated_sections():
    """
    Prompts corrupted by the old behavior (multiple stacked enhanced sections)
    collapse back to a single section on the next enhancement.
    """
    base = "You are a helpful assistant."
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())
    once = _integrate_tools_into_prompt(base, section)
    # Simulate the historical duplication: two full sections back to back.
    corrupted = once + "\n\n" + section.strip()
    assert corrupted.count("<required_format>") == 2

    healed = _integrate_tools_into_prompt(corrupted, section)

    assert healed.count("<required_format>") == 1
    assert healed.count("Available Tools:") == 1


def test_integrate_tools_heals_headerless_duplicate_format_blocks():
    """
    The historical duplication actually left ONE "Available Tools:" header
    followed by stacked header-less format blocks: the old code replaced only
    the text before <required_format>, leaving a block + CRITICAL trailer
    behind on every re-enhancement. That real shape must heal too.
    """
    base = "You are a helpful assistant."
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())
    once = _integrate_tools_into_prompt(base, section)
    leftover = "\n\n" + section[section.index("<required_format>"):].strip()
    corrupted = once + leftover + leftover
    assert corrupted.count("Available Tools:") == 1
    assert corrupted.count("<required_format>") == 3
    assert corrupted.count("CRITICAL:") == 3

    healed = _integrate_tools_into_prompt(corrupted, section)

    assert healed.count("<required_format>") == 1
    assert healed.count("Available Tools:") == 1
    assert healed.count("CRITICAL:") == 1
    assert healed == once


def test_integrate_tools_orphan_cleanup_stops_at_unrelated_content():
    """
    Orphan-block cleanup is anchored to the front of the tail: a format block
    that sits after other content is user-authored, not duplication residue,
    and must survive re-enhancement.
    """
    base = "You are a helpful assistant."
    section = _format_mcp_tools_for_llm_prompt(_sample_tools_map())
    once = _integrate_tools_into_prompt(base, section)
    suffix = "\n\nCustom rules.\n\n<required_format>user-authored</required_format>"

    updated = _integrate_tools_into_prompt(once + suffix, section)

    assert updated.endswith(suffix)
    assert updated.count("<required_format>") == 2
