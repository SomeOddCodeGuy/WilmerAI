## The `MCPToolCall` Node

The `MCPToolCall` node invokes a single tool on a Model Context Protocol (MCP) server. The server, tool name, and
arguments are all decided by the workflow author — the LLM is not in the loop. This node is the deterministic
primitive for MCP tool use; for many common patterns (fetch this file, query this database, call this API exposed by
an MCP server) it is the only piece you need.

If you want the LLM to choose what to call out of a set of MCP tools, that is a separate, agentic pattern; it is not
covered by this node.

-----

### **JSON Configuration**

#### **Complete Example**

```json
{
  "title": "Read user notes from MCP filesystem",
  "agentName": "UserNotes",
  "type": "MCPToolCall",
  "server": "filesystem",
  "tool": "read_file",
  "arguments": {
    "path": "/data/notes/{userId}.txt"
  },
  "timeout": 15,
  "onError": "raise"
}
```

#### **Fields**

* `"type"`: **(String, Required)**

    * Must be `"MCPToolCall"`.

* `"title"`: **(String, Optional)**

    * A human-readable name for the node, used in logging.

* `"agentName"`: **(String, Required)**

    * The output variable name. The node's return value becomes `{agentName}` for downstream nodes.

* `"server"`: **(String, Required)**

    * The name of an MCP server config in `Public/Configs/MCPServers/` (without the `.json` extension). Supports
      workflow variable substitution.

* `"tool"`: **(String, Required)**

    * The MCP tool to invoke on that server. Supports workflow variable substitution.

* `"arguments"`: **(Object, Optional, default `{}`)**

    * A JSON object of tool arguments. String values run through Wilmer's variable resolver. Numbers, booleans,
      `null`, lists, and nested objects pass through unchanged (with string values inside nested structures also
      resolved).

* `"timeout"`: **(Number, Optional, default `30`)**

    * Overall per-call timeout in seconds. Bounds the whole operation — transport connect, the `initialize`
      handshake, and the tool call — via `asyncio.wait_for`, so a server that connects but never completes the
      handshake cannot block the worker.

* `"onError"`: **(String, Optional, default `"raise"`)**

    * Controls behavior when the MCP call fails (server unreachable, transport error, tool reports an error, etc.):
        * `"raise"` aborts the workflow with an `MCPToolCallError`.
        * `"return"` causes the node to emit the error message as its output, allowing a later `Conditional` node to
          branch on the failure.

-----

### **MCP Server Registry**

Each MCP server has one config file under `Public/Configs/MCPServers/`. The base name of the file (without `.json`)
is the value to put in the node's `server` field. The MCP Python SDK supports three transports; the registry mirrors
that.

#### **stdio (spawns a subprocess)**

Use this when the MCP server is a local binary that speaks MCP over stdin/stdout. The classic example is the
`@modelcontextprotocol/server-filesystem` Node package.

```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"],
  "env": {"NODE_ENV": "production"},
  "cwd": null
}
```

Fields:

* `command` *(required)*: The binary to execute.
* `args` *(optional, default `[]`)*: Command-line arguments to the binary.
* `env` *(optional)*: Environment variables to set for the subprocess. When omitted, the subprocess inherits a
  minimal default environment provided by the MCP SDK (not Wilmer's full environment).
* `cwd` *(optional)*: Working directory for the subprocess.

#### **sse (Server-Sent Events over HTTP)**

Use this when the MCP server exposes an SSE endpoint over HTTP/HTTPS.

```json
{
  "transport": "sse",
  "url": "http://localhost:8888/sse",
  "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE"}
}
```

Fields:

* `url` *(required)*: The SSE endpoint URL.
* `headers` *(optional)*: A JSON object of headers to send (typically auth).

#### **streamable_http (bi-directional HTTP)**

Use this for MCP servers that implement the newer streamable HTTP transport.

```json
{
  "transport": "streamable_http",
  "url": "http://localhost:8888/mcp",
  "headers": {}
}
```

Fields: same as `sse`.

-----

### **Variable Substitution**

The following fields support variable substitution:

* `server`
* `tool`
* Every string value inside `arguments`, including string values nested inside lists or objects.

You can reference any of Wilmer's standard variables:

* Other agent outputs: `{agent1Output}`, `{agent2Output}`, ...
* Named agents: `{MyAgent}` (matching an earlier node's `agentName`)
* Built-in variables: `{Discussion_Id}`, `{YYYY_MM_DD}`, `{userInput}`, etc.
* Custom workflow variables.

Non-string values in `arguments` (numbers, booleans, lists of non-strings) are passed through untouched.

-----

### **Output Format**

The node returns a string. The exact content depends on what the MCP server's tool returned:

* If the tool result includes `structuredContent`, the node returns a JSON-serialized version of that structured data.
* Otherwise, the node concatenates the `text` fields of all `content` parts and returns the result.
* Non-text content blocks fall back to a JSON dump of their fields.

In the `onError: "return"` case on failure, the node returns the error message as the output string.

-----

### **Privacy and Network Behavior**

`MCPToolCall` only contacts the MCP servers configured under `Public/Configs/MCPServers/`. Wilmer never adds
anything to the call beyond what you write in the node config. For stdio servers, the only "network" activity is the
subprocess itself; for SSE and streamable HTTP, the outbound traffic is exactly the request you have configured.

-----

### **Choosing How to Compose MCP Calls**

* **One specific tool call:** use a single `MCPToolCall` node.
* **Several specific tool calls in sequence:** use multiple `MCPToolCall` nodes; pipe outputs via the standard
  `{agentNOutput}` variables.
* **Branch on tool failure:** set `onError: "return"` and follow with a `Conditional` node that matches the error
  string.
* **Let the LLM decide which tool to call:** this is an agentic pattern outside the scope of `MCPToolCall`. Use the
  agentic MCP tools workflow (`Public/workflow_python_scripts/_isevendays_mcp_scripts/`, see the
  [agentic MCP tools guide](../../../../../Public/workflow_python_scripts/_isevendays_mcp_scripts/README_MCP_TOOLS.md) and the
  [MCP Support guide](../../../Core_Features/MCP_Support.md)), or simulate a constrained version with a `Standard`
  LLM node that emits a tool-name choice, followed by a `Conditional` that dispatches to one of several
  `MCPToolCall` nodes.
