# MCP Tool Integration

This module provides integration with MCP (Model Context Protocol) services for Wilmer's AI system. It allows LLMs to automatically discover and invoke tools from MCP servers mentioned in the system prompt.

## Important Note on MCP:

> Wilmer has no way to validate or control what the MCP server or the tools it exposes may do, so please be
> sure to use only trusted and secure MCP servers. Like a front end, Wilmer can only call the tools; what those
> tools do is the responsibility of the server exposing them. Take care to ensure that you know exactly what those
> tools will do before using them.

> This functionality is still new, and may have bugs or other issues that still need to be worked out.
> Please exercise caution when using it.

## Overview

The integration consists of two main Python modules:

1. `mcp_tool_executor.py` - Handles discovering available tools from MCP servers and executing tool calls
2. `mcp_workflow_integration.py` - Integrates MCP tools with Wilmer's workflow system

## Configuration

The following configurations have been set up:

1. **Workflow**: `Public/Configs/Workflows/isevendays-openwebui-norouting-general-offline-mcp/MCPToolsWorkflow.json`
2. **Endpoint**: `Public/Configs/Endpoints/isevendays-openwebui-norouting-general-offline-mcp/Worker-Endpoint.json`
3. **User**: `Public/Configs/Users/isevendays-openwebui-norouting-general-offline-mcp.json`

## How It Works

1. The system automatically detects MCP services mentioned in the system prompt.
2. It discovers the available tools for each service:
   - **Native MCP (preferred):** if `Public/Configs/MCPServers/<service>.json` exists, the tools are listed
     directly from that server using the official `mcp` SDK, with no proxy needed. This is the same server registry
     used by the deterministic `MCPToolCall` workflow node (see the
     [MCP Support guide](../../../Docs/User_Documentation/Core_Features/MCP_Support.md) for the config format;
     examples ship in `MCPServers/_examples/`).
   - **Legacy MCPO fallback:** otherwise, the service's OpenAPI schema is fetched from an external MCPO proxy
     (see below).
3. It updates the system prompt with tool definitions.
4. When the LLM generates a tool call, it executes the tool (through the MCP SDK for registry servers, or via
   MCPO HTTP for legacy services) and formats the results for the next response.

## Using MCP Tools

To use MCP tools in your prompts, simply mention the MCP services you want to use in OpenWebUI System Prompt. For example:

```
You are a helpful AI assistant with access to the following MCP services: time, openweather.

When you need to get the current time or weather information, use the appropriate tool.
```

The system will automatically discover the available tools from the mentioned services and make them available to the LLM. The underlying code is generic and should be able to handle most any tool calling that follows the MCP standard.

## MCPO Server (legacy fallback)

> The native `MCPServers/` registry above is the preferred way to connect MCP servers. MCPO support is kept as a
> legacy option for existing setups and for services not yet declared in the registry.

### What is MCPO?

MCPO (MCP-to-OpenAPI) is a proxy server developed by the Open WebUI team that allows MCP tools to be exposed as standard OpenAPI/REST endpoints. This solves several challenges with raw MCP servers:

- Raw MCP servers communicate over stdio, which lacks security features
- Raw MCP is incompatible with many tools and services
- Raw MCP lacks standard features like documentation, authentication, and error handling

### Configuration Options

The integration is configured to use the MCPO server running at http://localhost:8889 by default. You can change this URL in the User's config file. An `MCPO_URL` environment variable can also be set, which will be used as a fallback if nothing is set in the User config.

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

This will start a proxy server at http://localhost:8889 that exposes your MCP service's capabilities as REST APIs with auto-generated OpenAPI documentation.

### Benefits of Using MCPO

- Works with OpenAPI tools, SDKs, and UIs
- Uses standard web transport (HTTP) rather than a raw MCP socket connection
- Auto-generates interactive docs for every tool
- Uses plain HTTP, so no socket handling or extra glue code is needed

## Integration with Open WebUI

This MCP tool integration is designed to work with [MCPO](https://github.com/open-webui/mcpo).

If you're using Open WebUI with this integration, you can use their MCPO implementation.
