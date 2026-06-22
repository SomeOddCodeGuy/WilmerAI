# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_ensure_system_prompt.py

import pytest

from Public.workflow_python_scripts._isevendays_mcp_scripts import ensure_system_prompt
from Public.workflow_python_scripts._isevendays_mcp_scripts.ensure_system_prompt import Invoke, load_default_prompt


def _tools_map():
    return {
        "get_current_time": {
            "service": "time",
            "path": "/current",
            "method": "post",
            "llm_schema": {
                "type": "function",
                "name": "get_current_time",
                "description": "Get the current time",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    }


@pytest.fixture
def mock_discoverer(mocker):
    """Mocks MCPServiceDiscoverer so no MCPO HTTP discovery happens."""
    mock_cls = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.ensure_system_prompt.MCPServiceDiscoverer"
    )
    mock_cls.return_value.discover_mcp_tools.return_value = _tools_map()
    return mock_cls


# ---------------------------------------------------------------------------
# load_default_prompt
# ---------------------------------------------------------------------------


def test_load_default_prompt_reads_file(tmp_path):
    """
    Tests that the default prompt is read from the given path when present.
    """
    prompt_file = tmp_path / "default_tool_prompt.txt"
    prompt_file.write_text("You are a tool-using assistant.")
    assert load_default_prompt(str(prompt_file)) == "You are a tool-using assistant."


def test_load_default_prompt_missing_file_returns_fallback(tmp_path):
    """
    Tests that a missing prompt file yields the built-in fallback prompt
    instead of raising.
    """
    result = load_default_prompt(str(tmp_path / "nope.txt"))
    assert "You are an assistant with access to various tools." in result


# ---------------------------------------------------------------------------
# Invoke (prompt injection + discovery orchestration)
# ---------------------------------------------------------------------------


def test_invoke_adds_system_prompt_with_discovered_tools(mock_discoverer, tmp_path):
    """
    Tests that when no system prompt exists, a default prompt is added with
    the discovered tool schemas injected, and the tools map is returned.
    """
    # Arrange
    prompt_file = tmp_path / "default_tool_prompt.txt"
    prompt_file.write_text("You are a tool-using assistant.")
    messages = [{"role": "user", "content": "what time is it? use the time tool"}]

    # Act
    result = Invoke(
        messages,
        default_prompt_path=str(prompt_file),
        mcpo_url="http://localhost:8889",
        user_identified_services="time",
    )

    # Assert: System prompt inserted at index 0 with tools injected.
    assert result["messages"][0]["role"] == "system"
    assert "Available Tools:" in result["messages"][0]["content"]
    assert '"get_current_time"' in result["messages"][0]["content"]
    assert result["chat_system_prompt"] == result["messages"][0]["content"]
    assert result["discovered_tools_map"] == _tools_map()
    # Discovery was asked for exactly the user-identified service.
    mock_discoverer.return_value.discover_mcp_tools.assert_called_once_with(["time"])


def test_invoke_enhances_existing_system_prompt(mock_discoverer, tmp_path):
    """
    Tests that an existing system prompt is enhanced in place with the
    discovered tools rather than a second system message being added.
    """
    # Arrange
    messages = [
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "time please"},
    ]

    # Act
    result = Invoke(
        messages,
        default_prompt_path=str(tmp_path / "unused.txt"),
        mcpo_url="http://localhost:8889",
        user_identified_services="time",
    )

    # Assert: Still a single system message, enhanced with tools.
    assert len([m for m in result["messages"] if m["role"] == "system"]) == 1
    assert result["messages"][0]["content"].startswith("You are concise.")
    assert "Available Tools:" in result["messages"][0]["content"]


def test_invoke_treats_none_services_as_no_discovery(mock_discoverer, tmp_path):
    """
    Tests that the literal extractor output 'none' results in no services
    being passed to discovery.
    """
    # Arrange
    mock_discoverer.return_value.discover_mcp_tools.return_value = {}
    prompt_file = tmp_path / "default_tool_prompt.txt"
    prompt_file.write_text("Base prompt.")

    # Act
    result = Invoke(
        [{"role": "user", "content": "hi"}],
        default_prompt_path=str(prompt_file),
        user_identified_services="none",
    )

    # Assert
    mock_discoverer.return_value.discover_mcp_tools.assert_called_once_with([])
    assert result["discovered_tools_map"] == {}


def test_invoke_parses_stringified_messages(mock_discoverer, tmp_path):
    """
    Tests that a stringified message list (as produced by workflow variable
    substitution) is parsed back into a list.
    """
    # Arrange
    prompt_file = tmp_path / "default_tool_prompt.txt"
    prompt_file.write_text("Base prompt.")
    messages_str = "[{'role': 'user', 'content': 'what time is it?'}]"

    # Act
    result = Invoke(
        messages_str,
        default_prompt_path=str(prompt_file),
        user_identified_services="time",
    )

    # Assert: Parsed list with the system prompt prepended.
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][1] == {"role": "user", "content": "what time is it?"}


def test_invoke_aggregates_generator_service_list(mock_discoverer, tmp_path):
    """
    Tests that a generator for user_identified_services (from a streaming
    upstream node) is aggregated before being split into service names.
    """
    # Arrange
    prompt_file = tmp_path / "default_tool_prompt.txt"
    prompt_file.write_text("Base prompt.")

    def service_chunks():
        yield "ti"
        yield "me"

    # Act
    Invoke(
        [{"role": "user", "content": "hi"}],
        default_prompt_path=str(prompt_file),
        user_identified_services=service_chunks(),
    )

    # Assert
    mock_discoverer.return_value.discover_mcp_tools.assert_called_once_with(["time"])


def test_invoke_uses_default_tool_prompt_path_fallback(mock_discoverer, mocker):
    """
    Tests that when no default_prompt_path kwarg is given, the path comes
    from config_utils.get_default_tool_prompt_path (the restored shim).
    """
    # Arrange
    mock_discoverer.return_value.discover_mcp_tools.return_value = {}
    mock_path = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.ensure_system_prompt.get_default_tool_prompt_path",
        return_value="/nonexistent/default_tool_prompt.txt",
    )

    # Act
    result = Invoke([{"role": "user", "content": "hi"}])

    # Assert: Shim consulted; missing file falls back to built-in prompt text.
    mock_path.assert_called_once()
    assert "You are an assistant with access to various tools." in (
        result["messages"][0]["content"]
    )
