### **WilmerAI – Developer Documentation**

`NOTE: Pass one or more of these documents with your prompt to an LLM to help give context to the codebase.`

## 1\. Project Overview

WilmerAI is a Python-based **middleware system** designed to act as a bridge between user-facing clients (e.g.,
SillyTavern, OpenWebUI) and various Large Language Model (LLM) backends (e.g., OpenAI, Anthropic Claude, Ollama,
KoboldCPP). Its primary
function is to process user prompts by leveraging a modular and extensible **node-based workflow engine**.

The architecture is centered on the **`$ExecutionContext$`** object. This data structure encapsulates all runtime
information for a single operational step—including the full conversation history, the current node's configuration, and
outputs from previous nodes. The core engine creates a new `ExecutionContext` for each node in a workflow and passes it
as the sole argument to a specialized **Node Handler**.

This state-driven design makes the system clean and easy to extend. Each node in a workflow performs a specific task and
is designated as either a **responder** (its output is sent to the user) or a **non-responder** (its output is saved as
a variable for subsequent nodes). Nodes can call an LLM, run a Python script (tool), manage conversational memory, or
trigger another workflow. This architecture enables developers to create sophisticated, dynamic, and stateful
conversational agents.

### Key Capabilities

* **Multi-Step, State-Driven Workflows:** Chains multiple LLMs and tools together using a central `$ExecutionContext$`
  to manage state between nodes.
* **Extensible Node System:** New functionality is added by creating new Node Handler classes that operate on the
  `$ExecutionContext$`, making the system highly adaptable.
* **Flexible API Compatibility:** Exposes OpenAI- and Ollama-compatible endpoints. It uses a dedicated \*
  \*`$ResponseBuilderService$`\*\* as the single source of truth for all outgoing API schemas, ensuring responses match
  the
  client's expectations.
* **Stateful Conversation Management:** Manages short-term and long-term memory using a `discussionId` to track
  conversational context. This includes summarized memory chunks, rolling chat summaries, and a discussion-specific
  vector database for keyword-based retrieval.
* **Dynamic Tool Use:** Integrates external tools, APIs, and custom Python scripts directly into workflows, allowing for
  capabilities like Retrieval-Augmented Generation (RAG) and API interactions.
* **Streaming Responses:** Natively supports both streaming (`stream=true`) and single-block (`stream=false`) responses
  from responder nodes.
* **Flexible Variable System:** Supports inter-node variables (`{agent1Output}`), date/time variables, and custom
  variables defined directly in the workflow JSON, with optional Jinja2 templating for advanced logic.

-----

## 2\. Architectural Flow

A typical request in WilmerAI follows this path, transforming a client request into a schema-compliant LLM response.

1. **API Ingestion & Routing:** A request arrives at a public endpoint (e.g., `/v1/chat/completions`). The Flask server
   in `Middleware/api/` routes the request to the appropriate registered **API Handler** (e.g.,
   `openai_api_handler.py`).

2. **API Pre-processing:** The API handler sets a global `API_TYPE` variable (e.g., `openaichatcompletion`) to inform
   downstream components of the required response format. It then transforms the incoming request payload into a
   standardized internal `messages` list.

3. **Engine Handoff:** The handler calls the `$workflow_gateway.handle_user_prompt()` function. This function serves as
   the **single bridge** between the API layer and the core workflow engine.

4. **Workflow Initialization:** The gateway invokes the `$WorkflowManager$`. The manager loads the relevant workflow
   JSON, instantiates all necessary services, and creates a central registry mapping node `type` strings to their
   corresponding **Node Handler** instances (e.g., `"Standard"` -\> `$StandardNodeHandler$`).

5. **Execution Delegation:** The manager delegates control to the `$WorkflowProcessor$`, the core engine that executes
   the workflow step-by-step.

6. **Node Execution Loop:** The `$WorkflowProcessor$` iterates through each node in the workflow configuration. For \*
   \*each node\*\*, it performs the following steps:
   a. It assembles a new, comprehensive **`$ExecutionContext$`** object, populating it with the node's config, the full
   conversation history, all available variables, and service references.
   b. It reads the node's `type` and uses the handler registry to select the appropriate **Node Handler**.
   c. It calls the `handle(context)` method on the selected handler, passing the `$ExecutionContext$` as the sole
   argument.

7. **LLM Abstraction:** If a node needs to call an LLM, it uses a service that invokes the `llmapis` layer. This layer
   abstracts the differences between backends and returns **raw, unformatted data**: either a full string or a generator
   of data dictionaries.

8. **Response Cleaning:** The `$WorkflowProcessor$` receives the raw output from the designated **responder node** and
   orchestrates the final cleaning:
   a. For **streaming** responses (`stream=true`), it passes the raw data generator to the \*
   \*`$StreamingResponseHandler$`\*\*. This handler processes the stream chunk-by-chunk—removing `<think>` tags and
   stripping prefixes—to produce a clean stream.
   b. For **non-streaming** responses (`stream=false`), it passes the complete raw text to the `post_process_llm_output`
   utility function, which applies the identical cleaning logic all at once.

9. **Final Formatting & Return:** The cleaned response (string or stream) is sent back up to the API layer. The original
   API handler uses the **`$ResponseBuilderService$`** to construct the final, schema-compliant JSON object or streaming
   chunk based on the `API_TYPE` set in step 2. This is then sent to the client.

Outputs from **non-responding nodes** are saved internally by the `$WorkflowProcessor$` as variables (e.g.,
`{agent1Output}`) for use by later nodes.

-----

## 3\. Directory Breakdown

```plaintext
WilmerAI
│
├── Middleware/
│   ├── api/
│   │   ├── handlers/
│   │   │   ├── base/
│   │   │   │   ├── __init__.py
│   │   │   │   └── base_api_handler.py
│   │   │   ├── impl/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── ollama_api_handler.py
│   │   │   │   └── openai_api_handler.py
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   ├── api_helpers.py
│   │   ├── api_server.py
│   │   ├── app.py
│   │   └── workflow_gateway.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── constants.py
│   │   └── instance_global_variables.py
│   ├── exceptions/
│   │   ├── __init__.py
│   │   └── early_termination_exception.py
│   ├── llmapis/
│   │   ├── handlers/
│   │   │   ├── base/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base_chat_completions_handler.py
│   │   │   │   ├── base_completions_handler.py
│   │   │   │   └── base_llm_api_handler.py
│   │   │   ├── impl/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── claude_api_handler.py
│   │   │   │   ├── koboldcpp_api_handler.py
│   │   │   │   ├── ollama_chat_api_handler.py
│   │   │   │   ├── ollama_generate_api_handler.py
│   │   │   │   ├── openai_api_handler.py
│   │   │   │   └── openai_completions_api_handler.py
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   └── llm_api.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── llm_handler.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cancellation_service.py
│   │   ├── llm_dispatch_service.py
│   │   ├── llm_service.py
│   │   ├── locking_service.py
│   │   ├── memory_service.py
│   │   ├── prompt_categorization_service.py
│   │   ├── response_builder_service.py
│   │   └── timestamp_service.py
│   ├── utilities/
│   │   ├── __init__.py
│   │   ├── config_utils.py
│   │   ├── datetime_utils.py
│   │   ├── file_utils.py
│   │   ├── hashing_utils.py
│   │   ├── prompt_extraction_utils.py
│   │   ├── prompt_manipulation_utils.py
│   │   ├── prompt_template_utils.py
│   │   ├── search_utils.py
│   │   ├── streaming_utils.py
│   │   ├── text_utils.py
│   │   └── vector_db_utils.py
│   ├── workflows/
│   │   ├── handlers/
│   │   │   ├── base/
│   │   │   │   ├── __init__.py
│   │   │   │   └── base_workflow_node_handler.py
│   │   │   ├── impl/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── memory_node_handler.py
│   │   │   │   ├── specialized_node_handler.py
│   │   │   │   ├── standard_node_handler.py
│   │   │   │   ├── sub_workflow_handler.py
│   │   │   │   └── tool_node_handler.py
│   │   │   └── __init__.py
│   │   ├── managers/
│   │   │   ├── __init__.py
│   │   │   ├── workflow_manager.py
│   │   │   └── workflow_variable_manager.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── execution_context.py
│   │   ├── processors/
│   │   │   ├── __init__.py
│   │   │   └── workflows_processor.py
│   │   ├── streaming/
│   │   │   ├── __init__.py
│   │   │   └── response_handler.py
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── dynamic_module_loader.py
│   │   │   ├── offline_wikipedia_api_tool.py
│   │   │   ├── parallel_llm_processing_tool.py
│   │   │   └── slow_but_quality_rag_tool.py
│   │   └── __init__.py
│   └── __init__.py
│
├─ Public
│  └─ Configs
│     ├─ ApiTypes
│     ├─ Endpoints
│     │  ├─ folders named after usernames
│     │  └─ ...
│     ├─ Presets
│     │  ├─ folders named for specific types
│     │  │  ├─ folders named after usernames
│     │  │  └─ ...
│     │  └─ ...
│     ├─ PromptTemplates
│     ├─ Routing
│     ├─ Users
│     └─ Workflows
│        ├─ folders named after usernames
│        └─ ...
├── Tests/
│   ├── api/
│   │   ├── handlers/
│   │   │   └── impl/
│   │   │       ├── test_api_cancellation.py
│   │   │       ├── test_ollama_api_handler.py
│   │   │       └── test_openai_api_handler.py
│   │   ├── test_api_helpers.py
│   │   ├── test_api_server.py
│   │   └── test_workflow_gateway.py
│   ├── integration/
│   │   └── test_nested_workflow_cancellation.py
│   ├── llmapis/
│   │   ├── handlers/
│   │   │   ├── base/
│   │   │   │   ├── test_base_chat_completions_handler.py
│   │   │   │   └── test_base_llm_api_handler_cancellation.py
│   │   │   └── impl/
│   │   │       ├── test_llmapis_claude_api_handler.py
│   │   │       ├── test_llmapis_koboldcpp_api_handler.py
│   │   │       ├── test_llmapis_ollama_chat_api_handler.py
│   │   │       ├── test_llmapis_ollama_generate_api_handler.py
│   │   │       ├── test_llmapis_openai_chat_handler.py
│   │   │       └── test_llmapis_openai_completions_api_handler.py
│   │   └── test_llm_api.py
│   ├── services/
│   │   ├── test_cancellation_service.py
│   │   ├── test_llm_dispatch_service.py
│   │   ├── test_llm_service.py
│   │   ├── test_locking_service.py
│   │   ├── test_memory_service.py
│   │   ├── test_prompt_categorization_service.py
│   │   ├── test_response_builder_service.py
│   │   └── test_timestamp_service.py
│   ├── utilities/
│   │   ├── test_config_utils.py
│   │   ├── test_datetime_utils.py
│   │   ├── test_file_utils.py
│   │   ├── test_hashing_utils.py
│   │   ├── test_prompt_extraction_utils.py
│   │   ├── test_prompt_manipulation_utils.py
│   │   ├── test_prompt_template_utils.py
│   │   ├── test_search_utils.py
│   │   ├── test_streaming_utils.py
│   │   ├── test_text_utils.py
│   │   └── test_vector_db_utils.py
│   ├── workflows/
│   │   ├── handlers/
│   │   │   └── impl/
│   │   │       ├── test_memory_node_handler.py
│   │   │       ├── test_specialized_node_handler.py
│   │   │       ├── test_standard_node_handler.py
│   │   │       ├── test_sub_workflow_node_handler.py
│   │   │       └── test_tool_node_handler.py
│   │   ├── managers/
│   │   │   ├── test_workflow_manager.py
│   │   │   └── test_workflow_variable_manager.py
│   │   ├── processors/
│   │   │   ├── test_workflow_processor_cancellation.py
│   │   │   └── test_workflows_processor.py
│   │   ├── streaming/
│   │   │   └── test_response_handler.py
│   │   └── tools/
│   │       ├── test_dynamic_module_loader.py
│   │       ├── test_offline_wikipedia_api_tool.py
│   │       └── test_slow_but_quality_rag_tool.py
│   └── conftest.py
│
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── pytest.ini
├── requirements-test.txt
├── requirements.txt
├── run_eventlet.py
├── run_waitress.py
├── run_macos.sh
├── run_windows.bat
└── server.py
```

### Description of Directories and Key Files

#### **`Middleware/`**

This is the application's core logic.

* **`api/`**: The API entry point. Houses the Flask server (`app.py`, `api_server.py`) and modular handlers (e.g.,
  `openai_api_handler.py`) for different API schemas. It acts as a compatibility and translation layer. The \*
  \*`workflow_gateway.py`\*\* file provides the single, standardized bridge to the backend workflow engine.
* **`llmapis/`**: The abstraction layer for communicating with external LLM backends. It translates requests and parses
  responses, abstracting away API differences. This layer's job is to return **raw, unformatted data** from the backing
  APIs. The `$LlmApiService$` in `llm_api.py` is the main entry point, acting as a factory to select the correct handler
  from `handlers/impl/`.
* **`services/`**: Contains stateless, reusable business logic. Key services include:
  \* `$response_builder_service.py$`: The **single source of truth** for constructing all API-specific JSON responses
  and streaming chunks, ensuring schema compliance.
  \* `$MemoryService$`: Centralizes all logic for memory retrieval (reading) from memory files or the vector database.
  \* `$LLMDispatchService$`: Orchestrates the final call to the `$LlmApiService$` to get a response from a language
  model.
* **`utilities/`**: A collection of stateless helper modules.
  \* `text_utils.py`: Contains `rough_estimate_token_length()`, the heuristic token counter used throughout the
  codebase for estimating token counts without a model-specific tokenizer. It uses a word-based ratio (1.35
  tokens/word) and a character-based ratio (3.5 chars/token), taking the higher of the two and applying a
  configurable `safety_margin` (default 1.10) to deliberately overestimate. Also contains functions for chunking
  text and messages by token size (`reduce_text_to_token_limit`, `split_into_tokenized_chunks`,
  `chunk_messages_by_token_size`).
  \* `streaming_utils.py`: Contains logic for response cleaning, including `post_process_llm_output` for non-streaming
  text and `$StreamingThinkRemover$` for stateful stream cleaning.
  \* `vector_db_utils.py`: The abstraction layer for the SQLite FTS5 vector memory database.
* **`workflows/`**: The heart of the workflow engine. This is the most important directory for understanding the
  project's logic.
  \* **`managers/`**: Contains the `$WorkflowManager$` (high-level orchestrator that builds the node handler registry)
  and `$WorkflowVariableManager$` (handles variable substitution).
  \* **`processors/`**: Contains the `$WorkflowProcessor$`, the low-level execution engine. Its most critical function
  is to create a new, fully populated **`$ExecutionContext$` for each node** before dispatching it to the correct
  handler.
  \* **`handlers/`**: Contains classes that implement the logic for each node `type` (e.g., `$StandardNodeHandler$`,
  `$ToolNodeHandler$`). This is the **primary extension point** for adding new capabilities.
  \* **`streaming/`**: Contains the crucial **`$StreamingResponseHandler$`**. This class encapsulates all logic for
  cleaning and formatting a raw LLM stream into a final, client-ready SSE stream.
  \* **`models/`**: Defines core data structures. The key file is **`$execution_context.py$`**, which defines the
  `ExecutionContext` dataclass for passing state to all node handlers, and `NodeExecutionInfo` for tracking node execution metrics used in logging.
  \* **`tools/`**: Contains implementations of complex tools callable by the `$ToolNodeHandler$`, such as the RAG
  memory creation tool (`slow_but_quality_rag_tool.py`) and a dynamic Python module loader.

#### **`Public/`**

Contains all user-facing JSON configuration files.

* **`ApiTypes/`**: Contains json files that define the schemas for different LLM APIs, specifying property names for
  things like `streaming` or `max_tokens`. These are utilized in the Endpoint configs
* **`Endpoints/`**: Contains json files that specify connection details for an LLM API (e.g., URL, API Type) that Wilmer
  will make calls to. Every LLM that the user intends to use in their workflows must be specified here. Every workflow
  node can specify a different endpoint.
* **`Presets/`**: Contains json files with LLM generation parameters (temperature, top\_k, etc.). These are applied per
  workflow node.
* **`PromptTemplates/`**: Contains the json files that specify various prompt templates. Used in Endpoint configs
* **`Routing/`**: Contains json files that specify the central semantic router instructions for users/workflows that do
  routing. You specify the domains you are routing to here, and what workflows they correspond with.
* **`Users/`**: Contains json files with all of the specific settings for a user, including things like what port
  the app runs on, where to connect to things like the offline wikipedia api, and where certain files are saved, go
  here.
* **`Workflows/`**: Contains json files that define the sequence of nodes for each workflow. Workflows are organized
  into subfolders, typically named after each user (e.g., `Workflows/<username>/`). The subfolder used can be
  customized via the `workflowConfigsSubDirectoryOverride` setting in the User config.
    * **`_shared/`**: A special folder for shared workflows. Workflows placed directly in `_shared/` (or its subfolders)
      are listed by the `/v1/models` and `/api/tags` endpoints when `allowSharedWorkflows` is enabled, allowing
      front-end applications to select them via the model dropdown. The folder name can be customized via
      `sharedWorkflowsSubDirectoryOverride` in the User config.
    * **`_overrides/`**: A folder for user-specific workflow folder overrides. When `workflowConfigsSubDirectoryOverride`
      is set in the User config (e.g., to `coding-workflows`), workflows are loaded from `_overrides/coding-workflows/`
      instead of the user's default folder.

### **`run_linux/run_macos/run_windows`**

Scripts to automatically generate a venv, install the requirements.txt for the app, and run the application by calling
server.py. Takes two optional parameters:

* `--ConfigDirectory` - String input that specifies where the Public/Configs folder is at.
* `--User` - String input that specifies the name of the user you'd like to start the app as.

### **`server.py`**

Main script of the app.

-----

## 4\. Important Notes

* **The `ExecutionContext`**: This is the central architectural pattern. The `$WorkflowProcessor$` assembles a single
  `ExecutionContext` object for each node, containing all possible state (conversation history, node config, previous
  outputs, service instances). This makes node handlers simple to write and test, as they receive all their dependencies
  in one place.

* **Proxy Behavior & `API_TYPE`**: WilmerAI can act as a proxy. A client can connect to it as if it were an OpenAI
  server, while Wilmer, in the background, talks to an Ollama backend. The internal `API_TYPE` variable tracks what kind
  of API the front-end client expects. This is used by the **`$ResponseBuilderService$`** at the end of the process to
  format the response correctly for that client.

* **LLM API Paradigms**: The `llmapis` layer internally handles the two main types of LLM backends: modern **Chat
  Completions** APIs that take a structured list of messages (role/content pairs), and legacy **Completions** APIs that
  take a single flattened string prompt. The appropriate handler (`BaseChatCompletionsHandler` vs.
  `BaseCompletionsHandler`) is chosen automatically.

* **Responder vs. Non-Responder Nodes**: Each workflow can have only one **responder** node, whose output is sent to the
  user. All other nodes are **non-responders**; their output is captured internally as a variable for use by later
  nodes. The responder does not have to be the last node; this allows for cleanup tasks (like memory generation) to
  occur after the user has received their response.

* **`discussionId`**: This ID, provided by the user, is the key that enables all persistent, stateful features like
  conversation memory. If absent, features that rely on it are disabled or fall back to stateless operations.

* **Response Cleaning**: All cleaning of LLM output (removing `<think>` tags, boilerplate prefixes, etc.) happens after
  the raw, unmodified response is received from the `llmapis` layer. This logic is implemented in parallel by
  `post_process_llm_output` (for non-streaming) and the `$StreamingResponseHandler$` (for streaming) to ensure
  consistent behavior.

-----

## 5\. Request Cancellation Feature

WilmerAI includes a comprehensive request cancellation system that allows clients to abort in-progress workflows
gracefully. This feature is critical for improving user experience and resource management, enabling clients to
terminate long-running requests that are no longer needed.

### Architecture Overview

The cancellation system is built around a central **`CancellationService`** singleton that maintains a thread-safe
registry of cancelled request IDs. Cancellation checks are integrated at multiple layers of the stack:

1. **API Layer**: Handles incoming cancellation requests via API-specific mechanisms
2. **Workflow Processor**: Checks for cancellation at the start of each node execution
3. **LLM API Layer**: Monitors for cancellation during streaming responses from backend LLMs

### API-Specific Cancellation Mechanisms

To maintain compatibility with the APIs WilmerAI emulates, cancellation is implemented differently for each API type:

#### Ollama API (DELETE Endpoint)

Ollama-compatible endpoints support cancellation via DELETE requests. This is a **WilmerAI-specific extension** to
handle the multi-request environment.

**Endpoints:**

- `DELETE /api/chat`
- `DELETE /api/generate`

**Request Format:**

```json
{
  "request_id": "the-request-id-to-cancel"
}
```

**Response Format:**

```json
{
  "status": "cancelled",
  "request_id": "the-request-id-to-cancel"
}
```

**Example:**

```bash
curl -X DELETE http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"request_id": "abc-123"}'
```

**Important Notes:**

- The client must track and provide the `request_id` when cancelling
- The `request_id` is generated internally by WilmerAI when the request starts
- Clients should store the `request_id` from the initial request to enable cancellation

#### OpenAI API (Client Disconnection)

OpenAI-compatible endpoints handle cancellation via **client disconnection**. When a client closes the SSE (Server-Sent
Events) stream, WilmerAI detects the disconnection and triggers cancellation automatically.

**Endpoints:**

- `/chat/completions` (streaming mode)
- `/v1/completions` (streaming mode)
- `/completions` (streaming mode)

**How It Works:**

1. Client initiates a streaming request
2. WilmerAI stores the `request_id` in Flask's `g` context object
3. If the client closes the connection, Flask raises a `ClientDisconnected`, `BrokenPipeError`, or `ConnectionError`
   exception
4. WilmerAI's exception handler catches this and calls `cancellation_service.request_cancellation()`
5. The backend workflow and LLM stream are terminated

**Example (JavaScript):**

```javascript
// Create an AbortController to enable cancellation
const controller = new AbortController();

// Start streaming request
fetch('http://localhost:5000/chat/completions', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        messages: [{role: 'user', content: 'Hello'}],
        stream: true
    }),
    signal: controller.signal
});

// Cancel the request by aborting the signal
controller.abort();
```

**Exception Types Handled:**

- `ClientDisconnected` (Werkzeug)
- `BrokenPipeError` (Python built-in)
- `ConnectionError` (Python built-in)
- `GeneratorExit` (Python built-in)

### Internal Cancellation Flow

When a cancellation is requested (via either mechanism), the following sequence occurs:

1. **Registration**: `cancellation_service.request_cancellation(request_id)` adds the ID to the internal set
2. **Workflow Check**: At the start of each node in `WorkflowProcessor.execute()`, the system
   checks `cancellation_service.is_cancelled(request_id)`
3. **Early Termination**: If cancelled, the processor calls `cancellation_service.acknowledge_cancellation(request_id)`
   and raises `EarlyTerminationException`
4. **LLM Stream Termination**: During LLM streaming in `BaseLlmApiHandler.handle_streaming()`, each chunk is preceded by
   a cancellation check
5. **Cleanup**: The `finally` block in `WorkflowProcessor.execute()` ensures locks are released

### Nested Workflow Cancellation

Cancellation works correctly with nested workflows (a workflow that calls another workflow via `CustomWorkflow` nodes):

- All nested workflows share the same `request_id`
- A cancellation signal propagates through all levels
- Both parent and child workflows check for cancellation at each node
- If a child workflow is cancelled, it raises `EarlyTerminationException`, which terminates the parent

**Example Scenario:**

```
Parent Workflow (request_id: abc-123)
  ├─ Node 1: Standard
  ├─ Node 2: CustomWorkflow ──> Child Workflow (same request_id)
  │                                ├─ Node 1: Standard
  │                                └─ Node 2: Standard [CANCELLED HERE]
  └─ Node 3: Standard [NEVER EXECUTED]
```

### CancellationService API

The `CancellationService` is a singleton located at `Middleware/services/cancellation_service.py`.

**Methods:**

- **`request_cancellation(request_id: str)`**: Marks a request for cancellation
  ```python
  from Middleware.services.cancellation_service import cancellation_service
  cancellation_service.request_cancellation("my-request-id")
  ```

- **`is_cancelled(request_id: str) -> bool`**: Checks if a request is cancelled
  ```python
  if cancellation_service.is_cancelled(request_id):
      # Handle cancellation
  ```

- **`acknowledge_cancellation(request_id: str)`**: Removes a request from the registry after processing
  ```python
  cancellation_service.acknowledge_cancellation(request_id)
  ```

- **`get_all_cancelled_requests() -> Set[str]`**: Returns a copy of all cancelled request IDs (useful for debugging)

**Thread Safety:**
All methods are thread-safe and use internal locking to prevent race conditions.

### Developer Integration Guide

If you're adding a new API handler or modifying the workflow execution, follow these guidelines:

#### For API Handlers

1. **Streaming Responses**: Wrap streaming generators in a try-except block to catch disconnect exceptions
   ```python
   from Middleware.services.cancellation_service import cancellation_service
   from werkzeug.exceptions import ClientDisconnected
   from flask import g

   def streaming_with_cancellation_handling():
       try:
           for chunk in handle_user_prompt(messages, stream=True):
               yield chunk
       except (GeneratorExit, ClientDisconnected, BrokenPipeError, ConnectionError):
           request_id = getattr(g, 'current_request_id', None)
           if request_id:
               cancellation_service.request_cancellation(request_id)
           raise
   ```

2. **Dedicated Cancellation Endpoints**: If your API has a native cancellation mechanism, implement it
   ```python
   class CancelAPI(MethodView):
       @staticmethod
       def delete():
           from Middleware.services.cancellation_service import cancellation_service
           request_data = request.get_json()
           request_id = request_data.get("request_id")
           cancellation_service.request_cancellation(request_id)
           return jsonify({"status": "cancelled", "request_id": request_id}), 200
   ```

#### For Workflow Processors

Add cancellation checks at the start of long-running operations:

```python
from Middleware.services.cancellation_service import cancellation_service

if cancellation_service.is_cancelled(self.request_id):
    cancellation_service.acknowledge_cancellation(self.request_id)
    raise EarlyTerminationException(f"Request {self.request_id} cancelled")
```

#### For LLM API Handlers

Pass `request_id` through the call chain and check during streaming:

```python
for line in response.iter_lines():
    if request_id and cancellation_service.is_cancelled(request_id):
        logger.info(f"Request {request_id} cancelled. Stopping LLM stream.")
        break
    # Process line...
```

### Testing

Comprehensive unit tests are provided in:

- `tests/services/test_cancellation_service.py` - Service-level tests
- `tests/api/handlers/impl/test_api_cancellation.py` - API handler tests
- `tests/workflows/processors/test_workflow_processor_cancellation.py` - Workflow processor tests
- `tests/llmapis/handlers/base/test_base_llm_api_handler_cancellation.py` - LLM API layer tests
- `tests/integration/test_nested_workflow_cancellation.py` - End-to-end integration tests

Run tests with:

```bash
pytest tests/services/test_cancellation_service.py -v
pytest tests/ -k cancellation -v
```

-----

## 6\. Unit Testing

The project includes a comprehensive unit testing suite to ensure code quality and prevent regressions. The tests are
built using the `pytest` framework.

### Setup

To run the tests, you must first install the required development dependencies from the `requirements-test.txt` file
located in the project root.

```bash
pip install -r requirements-test.txt
```

### Running the Tests

To execute the entire test suite and generate a code coverage report, run the following command from the project's root
directory:

```bash
pytest --cov=Middleware --cov-report=term-missing
```

This command will run all tests and print a report to the console, highlighting any lines of code in the `Middleware`
directory that are not covered by the tests.