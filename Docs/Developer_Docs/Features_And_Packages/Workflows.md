### **Developer Guide: WilmerAI Logic Engine (`Middleware/workflows/`)**

This guide provides a deep dive into the architecture and implementation of the WilmerAI logic engine. It has been
updated to reflect the current, refactored system, which is built around a central `ExecutionContext` object.
Understanding this structure is essential for debugging, extending, and utilizing the full capabilities of the workflow
system.

-----

## 1\. Core Concepts & Architecture

The system is designed to be modular and state-driven, transforming user requests into a series of coordinated actions
defined by a workflow.

### Core Components

- **Workflow:** A JSON file that defines a sequence of steps, or "nodes." It serves as a blueprint for handling a
  specific type of request. The system supports both a legacy list-based format and a modern dictionary-based format
  that can contain top-level configuration.
- **Node:** A single JSON object within a workflow's `nodes` array. Each node represents one operational step and has a
  `type` that dictates its function (e.g., `Standard`, `PythonModule`, `CustomWorkflow`).
- **`$WorkflowManager$`:** The high-level orchestrator and primary entry point. Its static methods (e.g.,
  `run_custom_workflow`) are called by external services to initiate a workflow. The manager is responsible for loading
  the workflow configuration, instantiating all necessary dependencies (including all node handlers), and delegating
  execution to the `$WorkflowProcessor$`.
- **`$WorkflowProcessor$`:** The low-level execution engine. It iterates through the nodes of a loaded workflow. For *
  *each node**, it assembles a new, comprehensive **`$ExecutionContext$`** object containing the complete runtime state.
  It then dispatches this context to the appropriate handler for execution.
- **`$ExecutionContext$`:** A central dataclass object that encapsulates all runtime data for a single node's execution.
  It holds the node's configuration, the entire conversation history, outputs from previous nodes (`agent_outputs`),
  inputs from a parent workflow (`agent_inputs`), the current LLM handler, and references to core services. This object
  is the sole argument passed to a node handler, simplifying the development of new nodes.
- **`$...NodeHandler$`:** A specialized class designed to execute a specific `type` of node. For every possible node
  `type` (e.g., `"Standard"`, `"PythonModule"`), there is a corresponding handler class. Each handler implements a
  `handle(context: ExecutionContext)` method, making it a primary extension point for new functionality.
- **`$WorkflowVariableManager$`:** A utility service responsible for dynamically substituting placeholders in strings (
  like prompts or tool arguments) with their real-time values from the workflow's state. Its methods take the
  `$ExecutionContext$` as an argument, giving it access to all necessary data for substitutions. It resolves two primary
  variable types:
    - **Agent Output (`{agent1Output}`):** The result from a previously completed node within the *same* workflow run.
      String values are sentinel-escaped (`{`/`}` → `__WILMER_L_CURLY__`/`__WILMER_R_CURLY__`) before entering the
      variables dictionary to prevent `str.format()` from misinterpreting literal braces as placeholders.
    - **Agent Input (`{agent1Input}`):** A value passed from a *parent* workflow into a *child* sub-workflow. It is
      available to all nodes within the child workflow. Also sentinel-escaped for the same reason.
- **`$StreamingResponseHandler$`:** A dedicated class that processes a raw data stream from an LLM. It applies content
  modifications, such as removing `<think>` tags or custom prefixes defined in the workflow or endpoint configuration,
  and formats the output into a client-ready Server-Sent Event (SSE) stream. Tool call chunks bypass the text
  processing pipeline entirely and are emitted directly as SSE output.

### Architectural Flow

1. **Initiation:** An external service, like the API gateway, calls a static method on `$WorkflowManager$` (e.g.,
   `run_custom_workflow`), providing the workflow name and initial conversation history.
2. **Setup & Preparation:** The `$WorkflowManager$` is instantiated. It loads the specified workflow JSON file and
   creates a central registry (`self.node_handlers`) that maps node `type` strings to instances of their corresponding *
   *Node Handler** classes.
3. **Delegation to Processor:** The Manager creates an instance of `$WorkflowProcessor$`, injecting all dependencies,
   the full workflow configuration, the handler registry, and the request data.
4. **Execution Loop:** The `$WorkflowProcessor.execute()` method is called, which begins iterating through each node
   defined in the workflow's configuration. At the start of each iteration, the processor checks if a cancellation has
   been requested for this workflow execution and raises an `EarlyTerminationException` if so.
5. **Context Creation:** For each node in the loop, the `$WorkflowProcessor$` **assembles a new `ExecutionContext`
   object**. This object is populated with the node's specific configuration, the full conversation history, the
   top-level workflow configuration, all available agent inputs and outputs, the appropriate LLM handler for that node,
   and other runtime data.
6. **Handler Dispatch:** The `$WorkflowProcessor$` reads the node's `type` field, validates it against the
   `VALID_NODE_TYPES` whitelist in `Middleware/common/constants.py`, and uses its injected registry to find the matching
   **Node Handler** instance. **When adding a new node type, it must be registered in three places:** the
   `VALID_NODE_TYPES` list in `constants.py`, the `node_handlers` dictionary in `$WorkflowManager$.__init__`, and the
   handler's dispatch method (e.g., `SpecializedNodeHandler.handle`).
7. **Node Execution:** The `$WorkflowProcessor$` calls the `handle()` method on the selected handler, passing it the
   single, comprehensive **`ExecutionContext` object**.
8. **State Update:** The output returned by the handler is captured by the `$WorkflowProcessor$` and stored in its
   internal `agent_outputs` dictionary. This makes the result available as an **Agent Output** (e.g., `{agent1Output}`,
   `{agent2Output}`) to all subsequent nodes in the current workflow.
9. **Response Generation:** The loop continues until a node marked as a "responder" is executed or the workflow ends.
   The `$WorkflowProcessor$` then manages the final output:
    - **Non-Streaming:** It returns the final string result directly after performing any required post-processing.
    - **Streaming:** It delegates the raw data *generator* from the handler to the **`$StreamingResponseHandler$`**,
      which processes the stream chunk-by-chunk and yields client-ready SSE events.

-----

## 2\. Directory & File Breakdown

This section details the responsibility of each key file in the `Middleware/workflows/` directory.

#### `managers/`

- **`workflow_manager.py` (`$WorkflowManager$`)**

    - **Responsibility:** The main entry point and setup coordinator.
    - **Details:** Contains static methods for initiating workflows. Its `__init__` method acts as the central registry
      where all **Node Handlers** are instantiated and mapped to their corresponding node `type` strings. It delegates
      the step-by-step execution to the `$WorkflowProcessor$`.

- **`workflow_variable_manager.py` (`$WorkflowVariableManager$`)**

    - **Responsibility:** Dynamic substitution of placeholders in strings.
    - **Details:** Provides the `apply_variables` method, which accepts an `ExecutionContext` object to resolve
      placeholders using the full runtime state of the workflow.

#### `processors/`

- **`workflows_processor.py` (`$WorkflowProcessor$`)**
    - **Responsibility:** To execute a pre-configured workflow step-by-step and manage the final response.
    - **Details:** Contains the main `execute()` loop. Its most critical function is to create a new, fully populated
      `ExecutionContext` for each node before dispatching it to the correct handler. It also maintains the
      `agent_outputs` dictionary to manage state between nodes.
    - **Node Execution Logging:** At the end of each workflow, logs an INFO-level summary of all executed nodes using
      `NodeExecutionInfo` objects. The summary includes node index, type, name (from `title` or `agentName`), endpoint
      details, and execution time. Helper methods include `_get_node_name()` (extracts display name, showing workflow
      destinations for sub-workflow nodes), `_get_endpoint_details()` (resolves endpoint name/URL with variable
      substitution), and `_log_node_execution_summary()` (formats and logs the summary).
    - **Variable Substitution:** The `maxResponseSizeInTokens` field supports workflow variable substitution (e.g.,
      `{agent#Input}`), allowing parent workflows to dynamically control response size limits for child workflows.

#### `handlers/`

- **`base/base_workflow_node_handler.py` (`$BaseHandler$`)**

    - **Responsibility:** Defines the abstract interface for all node handlers.
    - **Details:** An Abstract Base Class (ABC) ensuring all handlers implement a `handle(context: ExecutionContext)`
      method.

- **`impl/` (Implementations)**

    - `standard_node_handler.py`: Handles the `"Standard"` node type for LLM calls. Supports optional image
      passthrough via the `acceptImages` config flag, with `maxImagesToSend` controlling how many images reach the
      backend. When `acceptImages` is `true`, the handler passes `llm_takes_images=True` and the resolved
      `max_images` count to `LLMDispatchService.dispatch()`.
    - `tool_node_handler.py`: A router for tool-related nodes (`"PythonModule"`, `"OfflineWikiApi..."`, etc.).
    - `memory_node_handler.py`: A router for memory-related nodes (`"RecentMemory"`, `"VectorMemorySearch"`, etc.).
    - `sub_workflow_handler.py`: Handles nodes that trigger other workflows (`"CustomWorkflow"`,
      `"ConditionalCustomWorkflow"`). It calls back to the `$WorkflowManager$` to run a nested workflow, resolving
      and passing any `scoped_variables` from the parent context.
    - `specialized_node_handler.py`: A router for miscellaneous nodes: `"WorkflowLock"`, `"GetCustomFile"`,
      `"SaveCustomFile"`, `"StaticResponse"`, `"ImageProcessor"`, `"JsonExtractor"`, `"ArithmeticProcessor"`,
      `"Conditional"`, `"StringConcatenator"`, `"TagTextExtractor"`, and `"DelimitedChunker"`.
    - `context_compactor_handler.py`: Handles the `"ContextCompactor"` node type, which compacts conversation
      history into rolling summaries.

#### `streaming/`

- **`response_handler.py` (`$StreamingResponseHandler$`)**
    - **Responsibility:** Converts a raw LLM data stream into a final, client-facing SSE stream.
    - **Details:** Its `process_stream` method consumes a generator, strips `<think>` tags, removes configured
      prefixes (from both the node and endpoint configs), and formats the cleaned content into valid SSE messages.

#### `models/`

- **`execution_context.py`**
    - **`ExecutionContext`:** A `dataclass` that holds all runtime state for a single node's execution, including
      request IDs, node/workflow configs, messages, agent inputs/outputs, and service handlers.
    - **`NodeExecutionInfo`:** A `dataclass` for tracking node execution metrics used in logging. Contains fields for
      `node_index`, `node_type`, `node_name`, `endpoint_name`, `endpoint_url`, and `execution_time_seconds`. Includes
      a `format_time()` method that returns human-readable time strings and a `__str__()` method for formatted log output.

-----

## 3\. Tool Call Passthrough

WilmerAI can forward tool definitions from the incoming request to the backend LLM and relay tool call responses back
to the client. This is controlled per-node via the `allowTools` boolean configuration property.

### Node Configuration

The `allowTools` property is a boolean that defaults to `false`. When set to `true` on a node, any `tools` and
`tool_choice` values from the original client request are forwarded to the LLM for that node. When `false` (the
default), tool definitions are silently suppressed.

```json
{
  "type": "Standard",
  "allowTools": true,
  "endpoint": "my-endpoint",
  "prompt": ""
}
```

Memory nodes, summarizer nodes, categorizer nodes, and other internal processing nodes should never have `allowTools`
enabled. Only nodes that produce a final response to the client should use it, and typically only the responder node
in a workflow.

### Data Flow

1. **Ingestion:** The API gateway (`openai_api_handler.py`) extracts `tools` and `tool_choice` from the incoming
   request payload and passes them into the workflow system.
2. **ExecutionContext:** The `$WorkflowProcessor$` stores `tools` and `tool_choice` on the `$ExecutionContext$`
   dataclass, making them available to every node.
3. **Dispatch Gate:** `$LLMDispatchService.dispatch()$` reads `allowTools` from the node config. If `true`, it
   forwards `context.tools` and `context.tool_choice` to the LLM handler. If `false`, it passes `None` for both.
4. **LLM Handler:** `$LlmApiService.get_response_from_llm()$` includes the tool definitions in the payload sent to
   the backend. The internal canonical format is OpenAI's tool format; the Claude and Ollama handlers convert as
   needed (see the LLM APIs developer documentation).
5. **Response:** Tool call responses from the LLM are returned as structured dictionaries rather than plain strings.
   For streaming, `$StreamingResponseHandler$` detects `tool_calls` in the chunk data and emits them directly as SSE
   output, bypassing the text processing pipeline (prefix stripping, think-block removal). For non-streaming, the
   dispatch service returns a `Dict` with `content`, `tool_calls`, and `finish_reason` keys instead of a plain string.

-----

## 4\. Consecutive Assistant Message Normalization

Agentic frontends (e.g., coding assistants using tool calling) can produce conversation histories with multiple
assistant messages in a row without an intervening user message. Most LLM APIs reject this as invalid turn
structure. WilmerAI provides two mutually exclusive normalization strategies, controlled per-node in the config.

### Implementation

Both strategies are implemented as static methods on `$LLMDispatchService$` in `services/llm_dispatch_service.py`,
following the same pattern as `_apply_image_limit`:

- **`_merge_consecutive_assistant_messages(messages, delimiter)`:** Walks the message list and collapses runs of
  consecutive assistant messages into a single message, joining their content with the delimiter. Non-content keys
  (e.g., `tool_calls`, `images`) from the first message in a run are preserved.

- **`_insert_user_turns_between_assistant_messages(messages, text)`:** Walks the message list and inserts a synthetic
  `{"role": "user", "content": text}` between each pair of consecutive assistant messages.

Both methods modify the message list in place and are tool-call-aware: the standard sequence
`assistant(tool_calls) -> tool(result) -> assistant(response)` is NOT considered consecutive because the `tool`
role message separates the assistant messages. This is critical -- that sequence is valid per the OpenAI API spec.

### Integration Point

The methods are called in `dispatch()` within the chat API path, after the message collection is fully assembled
(after `collection.extend(last_n_turns)` and after image limiting). They only run when `prompt` is empty (the
raw-conversation path). When a text prompt is set, the conversation is flattened into a single user message, so
consecutive assistants are impossible.

Merge takes precedence if both booleans are enabled.

### Automatic User Message Recovery

After normalization, a separate safety net runs unconditionally in the `use_last_n_messages` chat API path:

- **`_ensure_user_message_present(collection, full_messages)`:** Checks whether `collection` contains any message
  with `role == "user"`. If not, it scans `full_messages` (the complete conversation history) in reverse to find
  the most recent user message and inserts a copy after any leading system messages.

This addresses a scenario that the merge/insert strategies do not cover: long agentic tool-calling chains where
`tool`-role messages separate every assistant message, preventing any direct assistant-to-assistant adjacency.
The `lastMessagesToSendInsteadOfPrompt` window can end up containing only `assistant` and `tool` messages with
no `user` message at all. Many backend chat templates (e.g., `multi_step_tool`) raise errors when no user query
is found.

The method is a no-op when the collection already contains a user message. It modifies `collection` in place
and uses `dict()` to shallow-copy the inserted message.

### Node Config Properties

| Property | Type | Default | Description |
|:---------|:-----|:--------|:------------|
| `mergeConsecutiveAssistantMessages` | Boolean | `false` | Merge runs of consecutive assistant messages into one. |
| `mergeConsecutiveAssistantMessagesDelimiter` | String | `"\n"` | Delimiter for joined content. |
| `insertUserTurnBetweenAssistantMessages` | Boolean | `false` | Insert a synthetic user turn between consecutive assistants. |
| `insertedUserTurnText` | String | `"Continue."` | Content of the synthetic user message. |

-----

## 5\. How to Extend the Workflow System

Adding new functionality typically involves one of the following methods.

### A. Add a New Node Type

This is the most powerful way to extend the system and has been streamlined by the `ExecutionContext` architecture.

1. **Define the Node Configuration:** Decide on the JSON parameters your node will need in the workflow file.

   ```json
   {
     "type": "DatabaseQuery",
     "connectionString": "your_db_connection_string",
     "query": "SELECT * FROM users WHERE name = '{chat_user_prompt_last_one}';"
   }
   ```

2. **Create the Handler File:** Create a new file (e.g., `database_query_handler.py`) in
   `Middleware/workflows/handlers/impl/`. The class must inherit from `BaseHandler` and implement the `handle` method.

   ```python
   # Middleware/workflows/handlers/impl/database_query_handler.py
   from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
   from Middleware.workflows.models.execution_context import ExecutionContext

   class DatabaseQueryHandler(BaseHandler):
       def handle(self, context: ExecutionContext) -> str:
           # Access all required data directly from the context object
           query_template = context.config.get("query")
           
           # Use the variable service (also on the context) to resolve placeholders
           resolved_query = context.workflow_variable_service.apply_variables(
               query_template, context
           )
           
           connection_string = context.config.get("connectionString")
           
           # ... (database connection and query logic) ...
           
           result = f"Executed: {resolved_query}"
           return result
   ```

3. **Register the Handler:** In `Middleware/workflows/managers/workflow_manager.py`, import your new handler and add it
   to the `self.node_handlers` dictionary in the `__init__` method.

   ```python
   # In Middleware/workflows/managers/workflow_manager.py
   # 1. Import your new handler
   from Middleware.workflows.handlers.impl.database_query_handler import DatabaseQueryHandler

   class WorkflowManager:
       def __init__(self, workflow_config_name, **kwargs):
           # ... (existing setup) ...
           
           # 2. Add your handler to the registry
           self.node_handlers = {
               "Standard": StandardNodeHandler(**common_dependencies),
               # ... (existing handlers) ...
               "DatabaseQuery": DatabaseQueryHandler(**common_dependencies),
           }
   ```

4. **Update Constants:** Add your new node type string (`"DatabaseQuery"`) to the `VALID_NODE_TYPES` list in
   `Middleware/common/constants.py` to ensure it's recognized as a valid type and to prevent warnings.

5. **Use It:** Your new node type is now ready to be used in any workflow JSON file.