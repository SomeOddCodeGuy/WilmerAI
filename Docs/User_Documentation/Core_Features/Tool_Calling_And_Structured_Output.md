# Tool Calling and Structured Output

WilmerAI supports OpenAI-style tool calling end to end: from front-end passthrough, through multi-round tool
loops, up to grammar-enforced tool calls and grammar-constrained node outputs on backends that support
constrained decoding. This page is the overview; the detailed configuration reference for every property
mentioned here lives in [Workflow Features](../Setup/Workflow_Details/Workflow_Features.md).

## Tool Call Passthrough

A front-end that sends OpenAI-format `tools` can use them through WilmerAI without WilmerAI needing to
understand the tools itself. Set `"allowTools": true` on the responding node of a workflow and tool definitions
are forwarded to the backend LLM; tool call responses are relayed back to the front-end in the correct format
(OpenAI or Ollama shape, whichever the client connected with). Claude, OpenAI-compatible, and Ollama backends
are supported, with format conversion handled automatically in both directions.

## Multi-Round Tool Loops: `appendNativeToolExchange`

Wilmer workflows commonly embed the conversation into an authored prompt as text (a single user message). That
style is deliberate (it sidesteps chat templates that reject consecutive same-role turns), but it breaks the
round of a tool loop where the front-end has just executed a call and replayed the result: the model sees the
exchange as text and tends to answer in text instead of calling again.

Setting `"appendNativeToolExchange": true` on an authored-prompt responder delivers that trailing tool exchange
as native messages after the authored prompt, placing the model in the standard generate-after-tool-result
position while still sending exactly one user turn. Multi-round flows (search loops, file tools, code
execution, image-generation retries) then work reliably through authored-prompt workflows. Backends whose chat
templates cannot render tool turns can opt out endpoint-wide with `"backendSupportsToolTurns": false`.

The property controls history delivery independently of `allowTools`. An authored-prompt internal planner can use
`appendNativeToolExchange: true` with `allowTools` left disabled to inspect the live call and result in their native
roles without receiving tool definitions or giving the planner's output a frontend execution path. Only the responding
node should enable `allowTools` when the frontend must execute the model's calls.

## Enforced Tool Calls (forced and `required` `tool_choice`)

When a client demands a call (`tool_choice` pinned to a function, or `"required"`) and the endpoint's API
type declares a structured-output mechanism, WilmerAI requests a tool-call JSON shape through the backend's
constrained decoding and converts successfully parsed output into a standard `tool_calls` response. Backend
enforcement can vary, so WilmerAI parse-checks the output and retries generation once after a failed parse. If
the retry also fails, it returns the raw text and logs an error. Rounds with `tool_choice: "auto"` retain native
tool handling, allowing the model to decide whether to call a tool.

## Structured Node Outputs: `structuredOutputFile`

Any `Standard` node can pin its own output to a JSON Schema. Write the schema as a file under
`Public/Configs/StructuredOutputs/` and reference it from the node:

Configuration property fragment; insert these fields into the containing JSON object.

```jsonc
"structuredOutputFile": "RequestVerdict"
```

WilmerAI requests schema-constrained output for routing decisions, extraction results, classifications, or
state-document updates. Enforcement depends on the backend and its support for the schema. Downstream nodes
should validate the returned JSON and required fields before using the result.

Two rules of thumb: describe the desired structure in the prompt as well (grammar backends do not show the
model the schema), and use endpoints with thinking disabled on constrained nodes.

Avoid combining `structuredOutputFile` with `allowTools: true` on the same node. When the client forces a
tool call the combination is rejected as a configuration error; when `tool_choice` is `auto` the schema
grammar-locks the output, so the model cannot emit a native tool call even though tools were advertised (a
warning is logged). Constrained nodes should not be the node that handles tools.

Note on failover: whether a round is constrained is decided by the primary endpoint's API type. If a
`backupEndpointName` endpoint of a *different* API type serves the call, the schema is re-attached using the
backup's own declared mechanism; a backup whose API type declares no `structuredOutput` block runs the round
unconstrained (prompt steering plus the parse/redraw backstop only).

## Backend Support

Structured output is declared per API type in a `structuredOutput` block (see the
[ApiType configuration guide](../Setup/Configuration_Files/ApiType.md)). Shipped API types cover llama.cpp
(`response_format`), OpenAI-compatible servers including LM Studio and vLLM (`response_format`), and Ollama
0.5+ (`format`). Claude enforces forced `tool_choice` natively and needs no declaration. Backends without
per-request constraint support (for example the stock mlx-lm server) simply do not engage the feature. A custom
API type whose backend accepts a schema at any request field can declare support in pure JSON, with no code
changes.
