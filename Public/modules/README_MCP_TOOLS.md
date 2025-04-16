# MCP Tool Integration

This module provides integration with MCP (Model Context Protocol) services for Wilmer's AI system. It allows LLMs to automatically discover and invoke tools from MCP servers mentioned in the system prompt.

## Overview

The integration consists of two main Python modules:

1. `mcp_tool_executor.py` - Handles discovering available tools from MCP servers and executing tool calls
2. `mcp_workflow_integration.py` - Integrates MCP tools with Wilmer's workflow system

## Configuration

The following configurations have been set up:

1. **Workflow**: `WilmerData/Public/Configs/Workflows/socg-openwebui-norouting-general-offline-mcp/MCPToolsWorkflow.json`
2. **Endpoint**: `WilmerData/Public/Configs/Endpoints/socg-openwebui-norouting-general-offline-mcp/Worker-Endpoint.json`
3. **User**: `WilmerData/Public/Configs/Users/socg-openwebui-norouting-general-offline-mcp.json`

## How It Works

1. The system automatically detects MCP services mentioned in the system prompt.
2. It discovers available tools from those services using the OpenAPI schemas.
3. It updates the system prompt with tool definitions.
4. When the LLM generates a tool call, it executes the tool and formats the results for the next response.

## Using MCP Tools

To use MCP tools in your prompts, simply mention the MCP services you want to use in OpenWebUI System Prompt. For example:

```
You are a helpful AI assistant with access to the following MCP services: time, openweather.

When you need to get the current time or weather information, use the appropriate tool.
```

The system will automatically discover the available tools from the mentioned services and make them available to the LLM.

## Supported MCP Services

The integration works with any MCP service that provides an OpenAPI schema. By default, it's configured to work with:

1. `time` - Provides time-related operations
2. `openweather` - Provides weather information (not implemented currently)

## MCPO Server

### What is MCPO?

MCPO (MCP-to-OpenAPI) is a proxy server developed by the Open WebUI team that allows MCP tools to be exposed as standard OpenAPI/REST endpoints. This solves several challenges with raw MCP servers:

- 🔓 Raw MCP servers communicate over stdio, which lacks security features
- ❌ Raw MCP is incompatible with many tools and services
- 🧩 Raw MCP lacks standard features like documentation, authentication, and error handling

### Configuration Options

The integration is configured to use the MCPO server running at http://localhost:8889 by default. You can change this URL in three ways:

1. **Environment Variable**: Set the `MCPO_URL` environment variable with your custom server URL:
   ```bash
   export MCPO_URL=http://your-mcpo-server:port
   ```

2. **.env File**: Add or modify the `MCPO_URL` in the `.env` file in the project root:
   ```
   MCPO_URL=http://your-mcpo-server:port
   ```

The system will load the environment variable first, with the hardcoded default as a fallback.

### Setting Up Your Own MCPO Server

If you want to run your own MCPO server to expose MCP tools as REST APIs, you can use the `mcpo` tool from Open WebUI:

1. **Install mcpo**:
   ```bash
   pip install mcpo
   ```

2. **Run an MCP service through MCPO**:
   ```bash
   mcpo --port 8889 -- your-mcp-service --your-service-args
   ```

For example, to run a time service:
```bash
mcpo --port 8889 -- mcp-server-time --local-timezone=America/New_York
```

3. Run unit tests
(change PYTHONPATH to your Python path and adjust unit test folder accordingly e.g. WilmerAI instead of WilmerData)
export PYTHONPATH=/root/projects/Wilmer/WilmerAI:${PYTHONPATH} && WilmerAI/venv/bin/python -m unittest discover -s WilmerData/Public/modules/tests -p 'test_*.py' | cat

This will start a proxy server at http://localhost:8889 that exposes your MCP service's capabilities as REST APIs with auto-generated OpenAPI documentation.

### Benefits of Using MCPO

- ✅ Works instantly with OpenAPI tools, SDKs, and UIs
- 🛡 Adds security, stability, and scalability using trusted web standards
- 🧠 Auto-generates interactive docs for every tool
- 🔌 Uses pure HTTP—no sockets, no glue code, no surprises

Note: The hardcoded URL has been removed from the workflow configuration files, so the system now relies on either the environment variable or the default value defined in the Python modules.

## Integration with Open WebUI

This MCP tool integration is designed to work with [MCPO](https://github.com/open-webui/mcpo).

If you're using Open WebUI with this integration, you can take advantage of their MCPO implementation for a more robust and feature-rich experience. 