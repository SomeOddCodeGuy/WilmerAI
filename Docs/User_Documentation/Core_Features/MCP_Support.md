### **Feature Guide: WilmerAI's Model Context Protocol (MCP) Integration**

The **MCP Integration** lets a WilmerAI workflow invoke tools exposed by Model Context Protocol servers. MCP is the
open protocol Anthropic published for connecting language models and agentic systems to external data sources and
actions; a growing ecosystem of MCP servers expose filesystems, databases, APIs, and other resources through a
standardized interface.

WilmerAI offers **two complementary modes** of MCP tool use, sharing one server registry
(`Public/Configs/MCPServers/`) and one underlying MCP client:

1. **Deterministic: the `MCPToolCall` node.** Performs one specific tool call against one specific server with
   arguments fixed by the workflow author. The LLM is not in the loop. This matches WilmerAI's broader design
   philosophy that the workflow author decides what runs and when. Most of this guide documents this node.
2. **Agentic: the MCP tools workflow.** An agentic loop, expressed entirely in workflow JSON via `PythonModule`
   nodes, where the **model** discovers the available tools, decides which (if any) to call, and receives the
   results before responding. Originally contributed by [iSevenDays](https://github.com/iSevenDays); its transport
   has since been migrated to the official MCP SDK (an external MCPO proxy remains supported as a legacy option).
   See the [agentic MCP tools guide](../../../Public/workflow_python_scripts/_isevendays_mcp_scripts/README_MCP_TOOLS.md) and the example
   `isevendays-openwebui-norouting-general-offline-mcp` user/workflow bundle.

-----

### **Prerequisites and Setup**

Two pieces are required:

1. **The `mcp` Python package.** WilmerAI uses the official MCP Python SDK to talk to MCP servers. It is listed in
   `requirements.txt` and is installed automatically when you install Wilmer's dependencies. If you assembled your
   environment manually, run `pip install mcp` (any 1.x release should work; the project pins a specific version in
   `requirements.txt`).

2. **One or more MCP servers** that you intend to call. These can be:
    * A local subprocess (the `stdio` transport), for example a Node-based MCP server installed via `npx`.
    * A remote HTTP server speaking `sse` (Server-Sent Events) or `streamable_http` (the newer streamable HTTP
      transport).

Servers are declared as JSON files in `Public/Configs/MCPServers/`. Example files for all three transports ship under
`MCPServers/_examples/`.

-----

## How It Works

When an `MCPToolCall` node runs, WilmerAI:

1. Loads the server config named by the node's `server` field from `Public/Configs/MCPServers/<name>.json`.
2. Opens a fresh transport connection (subprocess for `stdio`; HTTP for `sse` / `streamable_http`).
3. Initializes an MCP `ClientSession` and calls the named tool with the configured arguments.
4. Closes the connection.
5. Returns the tool's result as a string.

There is no connection pooling in this release. Each invocation is independent.

-----

## Configuration

### Server registry

Servers live in `Public/Configs/MCPServers/` (a peer of `ApiTypes/`, `Endpoints/`, `Presets/`, etc.). The base name of
each JSON file (without `.json`) is the value to put in a node's `server` field.

#### stdio (subprocess)

```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"],
  "env": {"NODE_ENV": "production"},
  "cwd": null
}
```

* `command` *(required)*: The binary to execute.
* `args` *(optional, default `[]`)*: Command-line arguments to the binary.
* `env` *(optional)*: Environment variables for the subprocess. When omitted, the subprocess inherits a minimal
  default environment provided by the MCP SDK (not Wilmer's full environment).
* `cwd` *(optional)*: Working directory for the subprocess.

#### sse

```json
{
  "transport": "sse",
  "url": "http://localhost:8888/sse",
  "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE"}
}
```

* `url` *(required)*: The SSE endpoint.
* `headers` *(optional)*: Headers to send with the request (typically authentication).

#### streamable_http

```json
{
  "transport": "streamable_http",
  "url": "http://localhost:8888/mcp",
  "headers": {}
}
```

Fields are the same as `sse`.

### Workflow node

The `MCPToolCall` node configuration is documented in detail under the Workflow Details section. The minimum required
fields are:

```json
{
  "type": "MCPToolCall",
  "server": "filesystem",
  "tool": "read_file",
  "arguments": {"path": "/etc/hostname"}
}
```

See [the MCPToolCall node documentation](../Setup/Workflow_Details/Nodes/MCPToolCall.md) for the full reference,
including timeout, variable substitution rules, and error handling.

-----

## Privacy and Security

* **Outbound traffic is limited to what you configure.** For `stdio` servers, the only "network" activity is the
  subprocess itself. For `sse` and `streamable_http`, the only outbound traffic is the URL you wrote in the server
  config.
* **stdio servers run with the privileges of the Wilmer process.** Treat them with the same care you would treat a
  PythonModule script: only run binaries you trust.
* **Secrets in server configs.** Auth tokens placed in `headers` are stored in plaintext in the server config file.
  Do not commit server configs containing real secrets to source control.

-----

## Choosing Between the Two Modes

* **Use `MCPToolCall`** when the workflow author knows exactly which tool should run and when. The LLM never decides
  which tool to call; the call is written into the workflow JSON. It is deterministic, auditable, and cheap — no
  extra LLM turns are spent on tool selection.
* **Use the agentic workflow** when the model should decide. The `Public/workflow_python_scripts/_isevendays_mcp_scripts/` integration discovers the tools a
  conversation mentions, injects their schemas into the system prompt, lets the model emit tool calls, executes
  them, and feeds the results back for a final response. It costs additional LLM calls per turn and depends on the
  model reliably emitting the expected JSON, but it handles open-ended "use whatever tool fits" requests that a
  fixed node cannot. See the [agentic MCP tools guide](../../../Public/workflow_python_scripts/_isevendays_mcp_scripts/README_MCP_TOOLS.md).

Both modes resolve server names against the same `Public/Configs/MCPServers/` registry and execute calls through the
same in-process MCP client (`MCPClient`), so a server configured once is available to both.
