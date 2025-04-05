# MCP Tool Integration Tests

This directory contains unit tests for the MCP tool integration modules.

## Test Files

- `test_mcp_tool_executor.py` - Tests for the MCP tool executor module
- `test_mcp_workflow_integration.py` - Tests for the MCP workflow integration module
- `run_tests.py` - Script to run all tests

## Running the Tests

To run all tests:

```bash
python run_tests.py
```

To run a specific test file:

```bash
python test_mcp_tool_executor.py
```

## Test Coverage

The tests cover:

1. **Tool Discovery** - Discovering available tools from MCP servers
2. **Tool Execution** - Executing tool calls and handling results
3. **System Prompt Preparation** - Updating system prompts with tool definitions
4. **Response Formatting** - Formatting responses with tool results
5. **Service Name Extraction** - Extracting service names from system prompts

## Mocking

The tests use mocking to avoid making actual HTTP requests to MCP servers. This ensures the tests are fast and don't depend on external services.

## Adding More Tests

When adding new functionality to the MCP tool integration, please add corresponding tests to ensure the functionality works as expected. 