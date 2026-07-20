### **A Feature Guide to WilmerAI for Workflow Authors**

This document provides a high-level overview of the core features and capabilities available within the WilmerAI system.
It is intended to serve as a comprehensive guide for an LLM tasked with authoring workflows, bridging the gap between
the project overview and the detailed technical references for nodes and variables.

For each feature, this guide will explain its purpose, its primary use case, the key workflow nodes associated with it,
and reference any available in-depth documentation for further details.

---

## Core LLM Interaction and Advanced Templating

The most fundamental capability of WilmerAI is its ability to interact with Large Language Models. This is primarily
achieved through the **`Standard` node**, which assembles context, sends a request to a configured LLM endpoint, and
processes the response.

A key aspect of this feature is the templating engine that allows for the creation of dynamic, context-aware
prompts. While simple variable substitution (`{my_variable}`) is supported by default, you can enable a full **Jinja2
templating engine** on a per-node basis by adding `"jinja2": true`. This unlocks advanced logic like loops and
conditionals directly within your prompt strings, which is especially useful for formatting the `{messages}` variable (
the entire conversation history).

* **Key Node**: `Standard`
* **Detailed Documentation**:
    * `A Comprehensive Guide to WilmerAI Workflow Nodes`
    * `Developer Guide: Workflow Node Jinja2 Support`

---

## Modular and Reusable Workflows (Nesting)

WilmerAI allows you to build complex processes by breaking them down into smaller, reusable components. This is achieved
by "nesting" workflows: running one workflow file as a single step inside another. A **Parent** workflow uses a *
*`CustomWorkflow` node** to call a self-contained **Child** workflow.

This architecture promotes reusability (e.g., creating a single `summarize.json` workflow and calling it from anywhere),
simplifies complex logic by breaking it into manageable parts, and enables the creation of high-level "orchestrator"
workflows. Data is passed from the parent to the child explicitly via the `scoped_variables` property, which the child
receives as `{agent#Input}` variables.

* **Key Node**: `CustomWorkflow`
* **Detailed Documentation**: `Feature Guide: Custom Nested Workflows`

---

## Conditional Logic and In-Workflow Routing

Workflows are not limited to a rigid, linear sequence of steps. WilmerAI supports dynamic, non-linear execution paths
through conditional logic. This allows a workflow to function as an intelligent agent that can make decisions and route
a task to the most appropriate tool based on the current context.

This is primarily accomplished using the **`ConditionalCustomWorkflow` node**, which acts as an "if/then" switch. It
evaluates a variable (often the output of a previous step) and executes a specific child workflow based on that value.
For more complex evaluations, the **`Conditional` node** can be used first to evaluate a logical expression (with `AND`/
`OR` operators) and return a simple `"TRUE"` or `"FALSE"` to drive the routing decision.

* **Key Nodes**: `ConditionalCustomWorkflow`, `Conditional`
* **Detailed Documentation**:
    * `Feature Guide: WilmerAI's In-Workflow Routing`
    * `In-Workflow Routing: The ConditionalCustomWorkflow Node`

---

## Stateful Conversation Memory

WilmerAI features a four-part memory system to provide long-term, stateful context for conversations.
This system is designed for performance by separating the slow process of writing memories from the fast process of
reading them.

The four components are:

1. **Long-Term Memory File**: Chronological, summarized chunks of the conversation.
2. **Rolling Chat Summary**: A single, continuously updated high-level summary of the entire discussion.
3. **Searchable Vector Memory**: A database containing structured memory objects (title, summary, entities), searched
   by full-text keyword matching (SQLite FTS5 with BM25 ranking) by default, with optional embedding-based semantic
   or hybrid search via the `searchMode` setting on `VectorMemorySearch`.
4. **State Document**: A single, continuously updated markdown snapshot of what is currently true in the conversation
   (a user profile, roleplay world state, etc.), maintained by the vector memory pipeline when `useStateDocument` is
   enabled in the discussion's memory settings.

Memory "writer" nodes like **`QualityMemory`** run in the background to create and update memories, while fast "reader"
nodes like **`VectorMemorySearch`** or **`GetCurrentSummaryFromFile`** retrieve context to be used in a prompt.

* **Key Nodes**: `QualityMemory` (writer), `VectorMemorySearch` (reader), `GetCurrentSummaryFromFile` (reader),
  `RecentMemorySummarizerTool` (reader), `GetCurrentStateDocument` (reader)
* **Detailed Documentation**:
    * `Feature Guide: WilmerAI's Memory System`
    * `WilmerAI Workflow Memory Node Catalog`

---

## Automated Conversation Timestamps

To provide LLMs with temporal awareness, WilmerAI can automatically inject timestamps into the conversation history.
When enabled on a `Standard` node, this system prepends a timestamp to each message's content before sending it to the
LLM.

The feature can be configured to use **absolute** timestamps (e.g., `(Saturday, 2025-09-20 16:30:05)`) or **relative**
ones (e.g., `[Sent 5 minutes ago]`). Additionally, the system provides the **`{time_context_summary}`** variable, which
gives a high-level natural language summary of the conversation's timeline (e.g., "This conversation started 2 hours
ago...").

* **Key Node**: `Standard` (with `addDiscussionIdTimestampsForLLM` flag)
* **Detailed Documentation**: `A Technical Guide to Conversation Timestamps`

---

## External Tool Integration

The workflow engine can be extended with custom tools and integrations to external services. This allows you to add
capabilities that are not native to the WilmerAI system.

The primary methods for this are:

1. **Custom Python Scripts**: The **`PythonModule` node** allows you to execute an arbitrary local Python script and use
   its string output as the result of the node. This is the most flexible way to add custom logic or connect to other
   APIs.
2. **Offline Wikipedia Integration**: WilmerAI has a built-in integration with the `OfflineWikipediaTextApi` service. A
   family of **`OfflineWikiApi...` nodes** allows a workflow to perform a semantic search against a local Wikipedia
   database to retrieve factual articles for Retrieval-Augmented Generation (RAG).

* **Key Nodes**: `PythonModule`, `OfflineWikiApiBestFullArticle`, `OfflineWikiApiTopNFullArticles`, etc.
* **Detailed Documentation**:
    * `Feature Guide: WilmerAI's Offline Wikipedia Integration`
    * `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## Vision Capabilities

WilmerAI can process and understand images provided in a user's message through two approaches:

**Approach 1: Direct Image Passthrough (Standard Node)**

The simplest approach is to set `acceptImages` to `true` on a `Standard` node. This passes images directly to the
backend LLM along with the conversation. The endpoint must support vision/multimodal input. You can optionally limit
the number of images sent with `maxImagesToSend` (keeping the most recent; `0` means no limit).

```json
{
  "type": "Standard",
  "acceptImages": true,
  "maxImagesToSend": 5,
  "endpointName": "Vision-Endpoint",
  "prompt": ""
}
```

**Approach 2: ImageProcessor Node (Text Description)**

The **`ImageProcessor` node** takes any images from the user's latest turn, sends them to a configured vision-capable
LLM, and generates a detailed text description. The aggregated text description is then made available as the node's
output (`{agent#Output}`). This allows a subsequent, text-only `Standard` node to use the description as context,
making image content available to the rest of the workflow as text.

* **Key Nodes**: `Standard` (with `acceptImages`), `ImageProcessor`
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## In-Workflow Data and File Manipulation

For common data processing and file system tasks, WilmerAI includes several utility nodes. These nodes allow workflows
to read and write local files and perform basic data manipulation without needing an LLM call or an external Python
script.

* **File I/O**: The **`GetCustomFile`** node reads the contents of a text file, while the **`SaveCustomFile`** node
  writes string content to a file. Both nodes support variable substitution in their `filepath` fields, including
  `{Discussion_Id}` and `{YYYY_MM_DD}` for per-conversation or date-based file paths.
* **Data Processing**: The **`StringConcatenator`** node joins a list of strings with a specified delimiter, and the
  **`ArithmeticProcessor`** node evaluates a simple mathematical expression.
* **Data Extraction**: The **`JsonExtractor`** node extracts a specific field from a JSON string (automatically handling
  markdown code block wrappers), and the **`TagTextExtractor`** node extracts content from XML/HTML-style tags within
  text.
* **Text Chunking**: The **`DelimitedChunker`** node splits a string by a delimiter and returns a subset of the
  resulting chunks (first N via `"head"` mode or last N via `"tail"` mode), rejoined with the same delimiter.

* **Key Nodes**: `GetCustomFile`, `SaveCustomFile`, `StringConcatenator`, `ArithmeticProcessor`, `JsonExtractor`,
  `TagTextExtractor`, `DelimitedChunker`
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## Concurrency Control

For long-running, asynchronous tasks that should not be run simultaneously (like regenerating a conversation summary),
WilmerAI provides a locking mechanism. The **`WorkflowLock` node** can be used to acquire a named lock. If another
workflow execution reaches a node with the same lock ID, it will terminate immediately, thus preventing race conditions
and redundant processing. The lock is automatically released after 10 minutes or when the workflow that acquired it
completes.

* **Key Node**: `WorkflowLock`
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## Tool Call Passthrough

WilmerAI can pass through tool (function calling) definitions from a frontend application to the backend LLM, and relay tool call responses back to the frontend. This allows frontends that support tool use (such as Open WebUI, SillyTavern, or custom applications) to use tool calling through WilmerAI without WilmerAI needing to understand or interpret the tools itself.

### How It Works

When a frontend sends a request that includes tool definitions (the `tools` field in an OpenAI-compatible request), WilmerAI stores those definitions on the execution context. If a `Standard` node has `allowTools` set to `true`, the tool definitions are forwarded to the backend LLM along with the rest of the request. If the LLM responds with tool calls instead of regular text content, WilmerAI passes those tool calls back to the frontend in the correct format.

This works for both streaming and non-streaming modes. In streaming mode, tool call data is accumulated across chunks and emitted in the final response. In non-streaming mode, tool calls are returned directly in the response body.

### Supported Backend Types

Tool call passthrough is supported for the following backend API types:

- **OpenAI-compatible** endpoints
- **Claude** (Anthropic) endpoints
- **Ollama** endpoints

Format conversion is handled automatically in both directions. Tool definitions and tool calls travel through
WilmerAI in OpenAI's format internally; Claude and Ollama backends have their native formats converted on the way
out and back. Frontends connected through WilmerAI's Ollama-compatible endpoints (`/api/chat`) receive tool calls in
Ollama's native shape (complete calls with `arguments` as a JSON object), regardless of which backend produced them.

**Multi-turn tool loops depend on how the node delivers the conversation.** When the frontend replays a conversation
containing earlier tool calls and their results, those turns reach the backend as native tool messages (for Claude,
as native `tool_use`/`tool_result` content blocks) ONLY when the node sends the conversation as a message collection,
that is, when the node has no authored `prompt` and uses `lastMessagesToSendInsteadOfPrompt`. A node with an
authored `prompt` sends the backend a single user message; the conversation, including any tool history, is rendered
into that message as text. Single-shot tool calls still work through such nodes (the tool definitions are forwarded
natively either way), but on the round after a tool result, many models respond with text that imitates a tool call
instead of making a real one, because the history they see is text. Use `appendNativeToolExchange` (below) to fix
this on authored-prompt nodes. Completions-paradigm backends (`/v1/completions`-style, Ollama generate) cannot carry
tool definitions at all; `allowTools` is silently ignored there.

### Configuration

Tool calling is controlled by the `allowTools` boolean property on workflow nodes. It defaults to `false`. When set to `true`, the node will include tool definitions in its LLM request if the frontend provided them.

```json
{
  "title": "Respond to User",
  "type": "Standard",
  "endpointName": "Main-Endpoint",
  "systemPrompt": "You are a helpful assistant.",
  "prompt": "",
  "allowTools": true,
  "returnToUser": true
}
```

### When to Enable `allowTools`

Only enable `allowTools` on nodes where tool calling makes sense. In practice, this means the final responding node: the node whose output is sent back to the user. Enabling it on non-responding nodes (internal "thinking" steps, summarizers, categorizers, etc.) is not useful, because those nodes are not communicating with the frontend and tool call responses would have nowhere to go.

If a workflow has multiple `Standard` nodes, only the responding node should have `allowTools` set to `true`. If no tools are present in the frontend request, the flag has no effect and the node behaves normally.

### Delivering the Live Tool Exchange Natively: `appendNativeToolExchange`

Authored-prompt nodes (nodes with a `prompt` field) render the conversation into a single user message as text. In a
multi-round tool flow this is the round that breaks: the frontend has just executed a tool call and replayed the
conversation with the assistant `tool_calls` turn and its `role: "tool"` result appended, expecting the model to
continue. But the model sees that exchange as a text transcript and tends to answer in text, producing
pseudo-tool-call JSON in its reply instead of a real call.

Setting `appendNativeToolExchange: true` on such a node changes how that trailing exchange is delivered. The final
assistant `tool_calls` turn and its contiguous `role: "tool"` result(s) are removed from the text the prompt
variables render, and are instead appended to the outgoing request as native messages after the authored prompt:

```
system:    (the node's systemPrompt)
user:      (the authored prompt: conversation as text, WITHOUT the trailing exchange)
assistant: (the frontend's tool_calls turn, verbatim)
tool:      (the tool result, verbatim)
```

The model generates from the standard position immediately after a tool result (the position tool-capable models
are trained for) while still seeing the authored framing, and the exchange is seen exactly once. Because exactly
one user turn is still sent, chat templates that reject consecutive same-role turns are unaffected.

```json
{
  "title": "Respond to User",
  "type": "Standard",
  "endpointName": "Main-Endpoint",
  "systemPrompt": "You are a helpful assistant.",
  "prompt": "Consider the conversation:\n{chat_user_prompt_last_twenty}\nRespond to the latest message. If a tool call is required, make the tool call.",
  "allowTools": true,
  "appendNativeToolExchange": true,
  "returnToUser": true
}
```

Behavior details:

- The flag only engages on authored-prompt nodes bound to chat-completions-paradigm backends. It is inert on
  collection-mode nodes (they already send native tool history) and on completions-paradigm backends (which cannot
  carry structured turns).
- Only the TRAILING exchange is delivered natively: the call the frontend just executed. Earlier, completed tool
  exchanges remain part of the text transcript as ordinary history.
- If the conversation does not end with a tool exchange (a normal chat turn), the flag does nothing and the node
  behaves exactly as before.
- Trailing empty assistant filler (for example the bare "Assistant:" turn added by `chatCompleteAddUserAssistant`
  setups) is recognized and excluded.
- Enable it together with `allowTools` on the responding node. It is designed for tool-loop frontends (searches,
  file tools, code execution, image generation retries) talking to authored-prompt workflows.
- **Old-model escape hatch:** a backend whose chat template cannot render tool turns (older models,
  strict-alternation templates without tool support) can opt out endpoint-wide with
  `"backendSupportsToolTurns": false` in its endpoint config; the node then falls back to the text-transcript
  behavior for that endpoint. This matters when a frontend lets the user switch a conversation that already
  contains tool history onto a different model mid-chat: without the opt-out, native tool turns reaching a
  template that does not know the `tool` role can produce a backend template error rather than a reply.

### Lowercasing Tool Call Function Names

Some local models (Gemma, Qwen, and others) produce tool call function names with capitalized first letters (e.g., `Glob` instead of `glob`, `Grep` instead of `grep`). This breaks agentic frontends like OpenCode that expect exact lowercase matches against their tool definitions. Setting `lowercaseToolCallFunctionNames` to `true` on the responding node causes WilmerAI to lowercase all tool call function names before relaying them to the frontend. This works for both streaming and non-streaming responses.

This is off by default because some frontends (e.g., Claude Code) expect the original casing. Only enable it when proxying local models that produce incorrectly cased tool names.

```json
{
  "title": "Respond to User",
  "type": "Standard",
  "endpointName": "Local-Model-Endpoint",
  "systemPrompt": "You are a helpful assistant.",
  "prompt": "",
  "allowTools": true,
  "lowercaseToolCallFunctionNames": true,
  "returnToUser": true
}
```

### Keeping an Agentic Frontend's Loop Alive with `injectLivenessToolCall`

Agentic frontends end their autonomous loop the moment a response arrives with no tool call in it. For most responder nodes that is the correct contract: when the model finishes the task and answers in plain text, the loop should stop. But some responder nodes produce plain text on turns where the task is not finished, for example a status or report turn whose whole output is a written assessment while the surrounding workflow still has work to dispatch. If such a node's text-only response reaches the frontend unmodified, the frontend stops and the task stalls waiting on a human.

Setting `"injectLivenessToolCall": true` on a responder node marks its turns as always mid-task. When that node's streamed response ends with no tool call of its own, WilmerAI appends the user-configured `livenessToolCall` (see the User config documentation), a harmless no-op valid for the frontend, and closes the response with `finish_reason: tool_calls`, so the frontend executes the no-op and calls back, and the task continues unattended.

The property defaults to `false`. It requires the `livenessToolCall` user setting to be configured (without it, nothing is injected), and only applies to streamed responses in formats that carry tool calls (OpenAI chat completions and Ollama chat). A response that already contains a real tool call is never modified. Do not set this on a node that can legitimately deliver a task's final answer; the frontend would never stop looping on its own.

### Ingestion Cleanup with `livenessToolCall`

When the `livenessToolCall` user setting is configured (see the User config documentation), WilmerAI also cleans up incoming conversations before any workflow sees them: runs of 3 or more consecutive identical tool-call exchanges (same call, same arguments, same result) are collapsed to a single exchange with a note appended to the kept result stating how many times the call was repeated, and liveness machinery turns buried in the history are stripped out. Users without `livenessToolCall` are unaffected; their conversations are never rewritten.

### Related: Tool Call Visibility in Conversation Variables

When tool calls are present in the conversation history, assistant messages with `tool_calls` but no text `content`
appear as blank turns in conversation variables by default. Setting `includeToolCallsInConversation` to `true` on a
node injects a text summary of each tool call (formatted as `[Tool Call: {name}] {summary}`) into those messages,
and prefixes tool result messages with a `[Tool Result: {name}]` label recovered from the originating call, making
both visible to downstream prompts.

* **Key Node**: `Standard` (with `allowTools` flag)
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## Structured Output (Grammar-Constrained Responses)

WilmerAI can constrain an LLM's response to a JSON schema using the backend's own constrained-decoding support
(grammar sampling). A constrained response is guaranteed to parse as JSON matching the schema; a small model that
cannot reliably follow a "respond only with JSON" instruction cannot escape a grammar. The capability is declared
per API type and used in two ways: automatically, to enforce demanded tool calls, and explicitly, by workflow
authors pinning a node's output shape.

### Backend Support (declared per API type)

An ApiType config declares its constraint mechanism in a declarative `structuredOutput` block. `field` is the
request-body key the schema is written to (dotted for nesting), and `style` is the wrapper shape:

```json
"structuredOutput": {
  "field": "response_format",
  "style": "openaiJsonSchema"
}
```

| ApiType | Block | Notes |
|---|---|---|
| `LlamaCppServer` | `field: "response_format", style: "openaiJsonSchema"` | llama.cpp `/v1/chat/completions` json_schema |
| `Open-AI-API` | `field: "response_format", style: "openaiJsonSchema"` | Real OpenAI, LM Studio, vLLM all honor this |
| `OllamaApiChat` | `field: "format", style: "raw"` | Ollama's top-level `format` (full JSON schema, Ollama >= 0.5.0) |
| vLLM native (custom ApiType) | `field: "structured_outputs.json", style: "raw"` | Expressible in pure JSON, no code |
| Claude | none needed | Anthropic enforces forced `tool_choice` natively server-side |
| mlx-lm server, completions-paradigm types | none | mlx-lm silently ignores `response_format`; completions APIs are unsupported |

Declaring no block means no mechanism: structured output requests on such endpoints send unconstrained (with a
warning) and tool enforcement does not engage. A custom API type whose backend takes a schema at any field, in
either wrapper style, needs only this JSON block (no Python changes).

Three important caveats apply on every backend:

- **The model does not see the schema.** Grammar constraint happens at decode time; the schema is not injected into
  the prompt. Always describe the desired structure in the prompt as well: the grammar guarantees syntax, the
  prompt supplies intent.
- **A 200 response does not prove enforcement.** Some backends accept the constraint field and fail open (llama.cpp
  on a schema its converter cannot translate) or ignore it silently. WilmerAI parse-checks constrained tool rounds
  and never assumes; author-declared node schemas should be treated the same way by downstream consumers.
- **Disable thinking on constrained nodes.** Reasoning blocks and output grammars fight each other; use endpoints
  with thinking disabled for constrained nodes.

### Automatic Tool Enforcement (forced and required `tool_choice`)

When a frontend request demands a tool call (`tool_choice` is a forced-function object or the string
`"required"`) and the responding node's endpoint declares a mechanism, WilmerAI enforces the demand instead of
relying on the model's cooperation:

1. A schema is built from the tool definitions (the pinned tool's parameter schema, or an `anyOf` across all tools
   for `"required"`).
2. Native `tools`/`tool_choice` are dropped from the backend payload (combining them with an explicit schema is
   unsupported on llama.cpp and Ollama), and the tool definitions are injected as text instead.
3. The constrained JSON output is converted back into a standard `tool_calls` response
   (`finish_reason: "tool_calls"`).
4. Because enforcement cannot be assumed, the output is parse-checked; a failed parse triggers exactly one redraw,
   after which the raw text is returned with an error logged.

Rounds with `tool_choice: "auto"` (the normal agentic case, where the model decides) are never touched: tools pass
through natively exactly as before. Streaming rounds under a demanded call are buffered; the client declared the
round machine-consumed, and the constrained output is one short JSON object.

### Author-Declared Node Schemas: `structuredOutputFile`

A `Standard` node can pin its own output shape. Write a JSON Schema file under
`Public/Configs/StructuredOutputs/<your-folder>/` and reference it by name:

```json
{
  "title": "Verdict Node",
  "type": "Standard",
  "endpointName": "Worker-Endpoint",
  "systemPrompt": "Decide whether to approve the request. Respond ONLY with JSON: {\"verdict\": approve|reject|unsure, \"reason\": string}.",
  "prompt": "Review this request:\n\n{chat_user_prompt_last_twenty}",
  "structuredOutputFile": "RequestVerdict",
  "returnToUser": false
}
```

`Public/Configs/StructuredOutputs/<sub>/RequestVerdict.json`:

```json
{
  "type": "object",
  "properties": {
    "verdict": {"type": "string", "enum": ["approve", "reject", "unsure"]},
    "reason": {"type": "string"}
  },
  "required": ["verdict", "reason"]
}
```

The node's output is the constrained JSON text, flowing into `{agentNOutput}` (or to the client, for a responder)
exactly like any other output. Resolution follows the usual named-collection rules: the file is looked up in the
subdirectory named by the user config's `structuredOutputConfigsSubDirectory` (defaulting to the username), then in
the `StructuredOutputs` root.

This turns prompt-contract patterns (routing decisions consumed by `ConditionalCustomWorkflow`, extraction nodes,
state-document maintenance, classification with fixed enums) into guarantees instead of carefully-prompted hopes.

Details:

- Supported on chat-completions-paradigm endpoints whose API type declares a mechanism. On completions-paradigm
  endpoints the property is ignored with a warning.
- A node cannot combine `structuredOutputFile` with an active tool-enforcement round (forced/required `tool_choice`
  arriving through `allowTools`); this raises a configuration error rather than silently picking one constraint.
- The schema dialect is the backend's. llama.cpp-derived backends support a documented subset of JSON Schema
  (type/properties/required/enum/const/anyOf/arrays/nesting; no external `$ref`).

---

## Curly Brace Handling in Agent Outputs

When a node produces output containing literal curly braces (common with JSON or code), those braces could be
misinterpreted as variable placeholders by `str.format()` in subsequent nodes. WilmerAI handles this automatically:
agent output and input values (`{agent#Output}`, `{agent#Input}`) are escaped before variable substitution using
internal sentinel tokens, and the real braces are restored after substitution completes. This means workflow authors
do not need to worry about JSON or code in agent outputs breaking the variable system.

Custom workflow variables (top-level keys in the workflow JSON) are intentionally NOT escaped, because they may
contain nested variable references that need to be resolved (e.g., `"my_path": "data/{Discussion_Id}/output.txt"`).

---

## Consecutive Assistant Message Normalization

Agentic frontends (coding assistants, tool-calling clients, etc.) can produce conversation histories with multiple
assistant messages in a row without a user message between them. Most LLM APIs reject this as invalid turn structure.
WilmerAI provides two strategies to fix this automatically, configured per-node on `Standard` nodes.

Both strategies only apply when `prompt` is empty (the raw conversation is sent to the LLM). They are tool-call-aware:
the valid sequence `assistant(tool_calls) -> tool(result) -> assistant(text)` is never modified, because the `tool`
role message separates the assistant turns.

### Option A: Merge Consecutive Assistants

Set `mergeConsecutiveAssistantMessages` to `true`. Runs of consecutive assistant messages are collapsed into a single
assistant message, with their content joined by the delimiter (default `"\n"`).

```json
{
  "type": "Standard",
  "prompt": "",
  "mergeConsecutiveAssistantMessages": true,
  "mergeConsecutiveAssistantMessagesDelimiter": "\n---\n"
}
```

### Option B: Insert Synthetic User Turns

Set `insertUserTurnBetweenAssistantMessages` to `true`. A synthetic user message is inserted between each pair of
consecutive assistant messages. The default text is `"Continue."`, but it can be customized.

```json
{
  "type": "Standard",
  "prompt": "",
  "insertUserTurnBetweenAssistantMessages": true,
  "insertedUserTurnText": "Proceed with the next step."
}
```

### Precedence

If both `mergeConsecutiveAssistantMessages` and `insertUserTurnBetweenAssistantMessages` are set to `true`, merging
takes precedence.

### Automatic User Message Recovery

In addition to the above normalization strategies, WilmerAI includes an automatic safety net for the
`lastMessagesToSendInsteadOfPrompt` path. When `prompt` is empty and the selected message window contains no user
messages at all (common in long agentic tool-calling chains where `tool`-role messages separate each assistant turn),
WilmerAI automatically recovers the most recent user message from the full conversation history and inserts it after
any system messages. This prevents backend chat templates from rejecting the request due to a missing user query.

This behavior is always active in the chat API path when `prompt` is empty. It runs after any merge/insert
normalization and is a no-op if the message window already contains at least one user message.

* **Key Node**: `Standard`

---

## Debugging and Performance Monitoring

WilmerAI provides built-in logging to help debug workflows and monitor performance. At the end of each workflow
execution, an INFO-level summary is logged showing every node that executed, including timing information.

**Example Output:**
```
=== Workflow Node Execution Summary: MainWorkflow ===
Node 1: Standard || 'Prepare Response' || Responder-Endpoint || http://127.0.0.1:5001 || 182.4 seconds
Node 2: GetCustomFile || 'Load Context' || N/A || N/A || 0.1 seconds
Node 3: CustomWorkflow || 'Route to Helper -> HelperWorkflow' || N/A || N/A || 45.2 seconds
=== End of Summary: MainWorkflow ===
```

**Information Displayed:**
- **Node index**: 1-based position in the workflow
- **Node type**: The type of node (Standard, GetCustomFile, CustomWorkflow, etc.)
- **Node name**: From the `title` field, falling back to `agentName`, or "N/A"
- **Endpoint details**: The endpoint name and URL for LLM-calling nodes
- **Execution time**: Time spent executing this node in seconds

For `CustomWorkflow` and `ConditionalCustomWorkflow` nodes, the summary also shows the target workflow name(s) to help
trace execution through nested workflows.

* **Log Level**: INFO (visible in standard logging output)
* **Use Cases**: Identifying slow nodes, debugging workflow execution order, performance optimization