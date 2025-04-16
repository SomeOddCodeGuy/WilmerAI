# MCP Tool and Module Integration Tests

This directory contains unit tests for various modules, including MCP tool integration.

## Test Files

- `test_mcp_tool_executor.py`: Tests for the MCP tool executor module.
- `test_mcp_workflow_integration.py`: Tests for the MCP workflow integration module.
- `test_chat_user_prompt_last_one.py`: Tests related to chat user prompt handling.
- `test_open_ai_api.py`: Tests for interactions with the OpenAI API wrapper/module.
- `run_tests.py`: Script to discover and run all tests in this directory.

## Running the Tests

To run all tests, follow these steps:

1.  **Navigate to the project root:**
    ```bash
    cd /root/projects/Wilmer
    ```

2.  **Ensure the virtual environment is sourced (if not already):**
    ```bash
    # If WilmerAI/venv exists and is not activated
    source WilmerAI/venv/bin/activate 
    ```

3.  **Run the tests using `unittest discover`:**
    This command sets the necessary Python path and discovers tests within the `WilmerAI/Public/modules/tests` directory.
    ```bash
    export PYTHONPATH=/root/projects/Wilmer:/root/projects/Wilmer/WilmerAI:${PYTHONPATH} && \
    python -m unittest discover -s WilmerAI/Public/modules/tests -p 'test_*.py'
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