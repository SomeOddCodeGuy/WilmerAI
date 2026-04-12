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

A key aspect of this feature is the powerful templating engine that allows for the creation of dynamic, context-aware
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
by "nesting" workflows -- running one workflow file as a single step inside another. A **Parent** workflow uses a *
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

WilmerAI features a sophisticated, three-part memory system to provide long-term, stateful context for conversations.
This system is designed for performance by separating the slow process of writing memories from the fast process of
reading them.

The three components are:

1. **Long-Term Memory File**: Chronological, summarized chunks of the conversation.
2. **Rolling Chat Summary**: A single, continuously updated high-level summary of the entire discussion.
3. **Searchable Vector Memory**: A vector database containing structured memory objects (title, summary, entities) for
   efficient semantic search (RAG).

Memory "writer" nodes like **`QualityMemory`** run in the background to create and update memories, while fast "reader"
nodes like **`VectorMemorySearch`** or **`GetCurrentSummaryFromFile`** retrieve context to be used in a prompt.

* **Key Nodes**: `QualityMemory` (writer), `VectorMemorySearch` (reader), `GetCurrentSummaryFromFile` (reader),
  `RecentMemorySummarizerTool` (reader)
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

Two primary methods for this are:

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
effectively giving the entire workflow "sight."

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

Only enable `allowTools` on nodes where tool calling makes sense. In practice, this means the final responding node -- the node whose output is sent back to the user. Enabling it on non-responding nodes (internal "thinking" steps, summarizers, categorizers, etc.) is not useful, because those nodes are not communicating with the frontend and tool call responses would have nowhere to go.

If a workflow has multiple `Standard` nodes, only the responding node should have `allowTools` set to `true`. If no tools are present in the frontend request, the flag has no effect and the node behaves normally.

### Related: Tool Call Visibility in Conversation Variables

When tool calls are present in the conversation history, assistant messages with `tool_calls` but no text `content`
appear as blank turns in conversation variables by default. Setting `includeToolCallsInConversation` to `true` on a
node injects a text summary of each tool call (formatted as `[Tool Call: {name}] {summary}`) into those messages,
making them visible to downstream prompts.

* **Key Node**: `Standard` (with `allowTools` flag)
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

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