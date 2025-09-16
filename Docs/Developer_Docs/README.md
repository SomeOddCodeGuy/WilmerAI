### **WilmerAI – Developer Documentation**

`NOTE: Pass one or more of these documents with your prompt to an LLM to help give context to the codebase.`

## 1\. Project Overview

WilmerAI is a Python-based **middleware system** designed to act as a bridge between user-facing clients (e.g.,
SillyTavern, OpenWebUI) and various Large Language Model (LLM) backends (e.g., OpenAI, Ollama, KoboldCPP). Its primary
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
* **Flexible API Compatibility:** Exposes OpenAI- and Ollama-compatible endpoints. It uses a dedicated *
  *`$ResponseBuilderService$`** as the single source of truth for all outgoing API schemas, ensuring responses match the
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

6. **Node Execution Loop:** The `$WorkflowProcessor$` iterates through each node in the workflow configuration. For *
   *each node**, it performs the following steps:
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
   a. For **streaming** responses (`stream=true`), it passes the raw data generator to the *
   *`$StreamingResponseHandler$`**. This handler processes the stream chunk-by-chunk—removing `<think>` tags and
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
├─ Middleware
│  ├─ api
│  │  ├─ handlers
│  │  │  ├─ base
│  │  │  │  └─ base_api_handler.py
│  │  │  └─ impl
│  │  │     ├─ ollama_api_handler.py
│  │  │     └─ openai_api_handler.py
│  │  ├─ __init__.py
│  │  ├─ api_helpers.py
│  │  ├─ api_server.py
│  │  ├─ app.py
│  │  └─ workflow_gateway.py
│  ├─ common
│  │  ├─ constants.py
│  │  ├─ instance_global_variables.py
│  │  └─ __init__.py
│  ├─ exceptions
│  │  ├─ early_termination_exception.py
│  │  └─ __init__.py
│  ├─ llmapis
│  │  ├─ handlers
│  │  │  ├─ base
│  │  │  │  ├─ base_chat_completions_handler.py
│  │  │  │  ├─ base_completions_handler.py
│  │  │  │  └─ base_llm_api_handler.py
│  │  │  └─ impl
│  │  │     ├─ koboldcpp_api_handler.py
│  │  │     ├─ koboldcpp_api_image_specific_handler.py
│  │  │     ├─ ollama_chat_api_handler.py
│  │  │     ├─ ollama_chat_api_image_specific_handler.py
│  │  │     ├─ ollama_generate_api_handler.py
│  │  │     ├─ openai_api_handler.py
│  │  │     ├─ openai_chat_api_image_specific_handler.py
│  │  │     └─ openai_completions_api_handler.py
│  │  └─ llm_api.py
│  ├─ models
│  │  ├─ llm_handler.py
│  │  └─ __init__.py
│  ├─ services
│  │  ├─ llm_dispatch_service.py
│  │  ├─ llm_service.py
│  │  ├─ locking_service.py
│  │  ├─ memory_service.py
│  │  ├─ prompt_categorization_service.py
│  │  ├─ response_builder_service.py
│  │  ├─ timestamp_service.py
│  │  └─ __init__.py
│  ├─ utilities
│  │  ├─ config_utils.py
│  │  ├─ datetime_utils.py
│  │  ├─ file_utils.py
│  │  ├─ hashing_utils.py
│  │  ├─ prompt_extraction_utils.py
│  │  ├─ prompt_template_utils.py
│  │  ├─ prompt_utils.py
│  │  ├─ search_utils.py
│  │  ├─ streaming_utils.py
│  │  ├─ text_utils.py
│  │  ├─ vector_db_utils.py
│  │  └─ __init__.py
│  └─ workflows
│     ├─ handlers
│     │  ├─ base
│     │  │  └─ base_workflow_node_handler.py
│     │  └─ impl
│     │     ├─ memory_node_handler.py
│     │     ├─ specialized_node_handler.py
│     │     ├─ standard_node_handler.py
│     │     ├─ sub_workflow_handler.py
│     │     └─ tool_node_handler.py
│     ├─ managers
│     │  ├─ workflow_manager.py
│     │  └─ workflow_variable_manager.py
│     ├─ models
│     │  └─ execution_context.py
│     ├─ processors
│     │  └─ workflows_processor.py
│     ├─ streaming
│     │  ├─ __init__.py
│     │  └─ response_handler.py
│     ├─ tools
│     │  ├─ dynamic_module_loader.py
│     │  ├─ offline_wikipedia_api_tool.py
│     │  └─ slow_but_quality_rag_tool.py
│     └─ __init__.py
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
│
├─ run_linux.sh
├─ run_macos.sh
├─ run_windows.bat
└─ server.py
```

### Description of Directories and Key Files

#### **`Middleware/`**

This is the application's core logic.

* **`api/`**: The API entry point. Houses the Flask server (`app.py`, `api_server.py`) and modular handlers (e.g.,
  `openai_api_handler.py`) for different API schemas. It acts as a compatibility and translation layer. The *
  *`workflow_gateway.py`** file provides the single, standardized bridge to the backend workflow engine.
* **`llmapis/`**: The abstraction layer for communicating with external LLM backends. It translates requests and parses
  responses, abstracting away API differences. This layer's job is to return **raw, unformatted data** from the backing
  APIs. The `$LlmApiService$` in `llm_api.py` is the main entry point, acting as a factory to select the correct handler
  from `handlers/impl/`.
* **`services/`**: Contains stateless, reusable business logic. Key services include:
    * `$response_builder_service.py$`: The **single source of truth** for constructing all API-specific JSON responses
      and streaming chunks, ensuring schema compliance.
    * `$MemoryService$`: Centralizes all logic for memory retrieval (reading) from memory files or the vector database.
    * `$LLMDispatchService$`: Orchestrates the final call to the `$LlmApiService$` to get a response from a language
      model.
* **`utilities/`**: A collection of stateless helper modules.
    * `streaming_utils.py`: Contains logic for response cleaning, including `post_process_llm_output` for non-streaming
      text and `$StreamingThinkRemover$` for stateful stream cleaning.
    * `vector_db_utils.py`: The abstraction layer for the SQLite FTS5 vector memory database.
* **`workflows/`**: The heart of the workflow engine. This is the most important directory for understanding the
  project's logic.
    * **`managers/`**: Contains the `$WorkflowManager$` (high-level orchestrator that builds the node handler registry)
      and `$WorkflowVariableManager$` (handles variable substitution).
    * **`processors/`**: Contains the `$WorkflowProcessor$`, the low-level execution engine. Its most critical function
      is to create a new, fully populated **`$ExecutionContext$` for each node** before dispatching it to the correct
      handler.
    * **`handlers/`**: Contains classes that implement the logic for each node `type` (e.g., `$StandardNodeHandler$`,
      `$ToolNodeHandler$`). This is the **primary extension point** for adding new capabilities.
    * **`streaming/`**: Contains the crucial **`$StreamingResponseHandler$`**. This class encapsulates all logic for
      cleaning and formatting a raw LLM stream into a final, client-ready SSE stream.
    * **`models/`**: Defines core data structures. The key file is **`$execution_context.py$`**, which defines the
      central dataclass for passing state to all node handlers.
    * **`tools/`**: Contains implementations of complex tools callable by the `$ToolNodeHandler$`, such as the RAG
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
* **`Workflows/`**: Contains json files that define the sequence of nodes for each workflow.

### **`run_linux/run_macos/run_windows`**

Scripts to automatically generate a venv, install the requirements.txt for the app, and run the application by calling
server.py. Takes two optional parameters:

- `--ConfigDirectory` - String input that specifies where the Public/Configs folder is at.
- `--User` - String input that specifies the name of the user you'd like to start the app as.

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