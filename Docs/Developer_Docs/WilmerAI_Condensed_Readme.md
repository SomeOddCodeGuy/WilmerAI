### **WilmerAI – Condensed Documentation to Help LLMs**

`NOTE: Pass this along with your prompt to an LLM to help give context to code`

#### **1. Core Concept**

WilmerAI is a Python-based **middleware** that acts as a bridge between user-facing clients (like OpenWebUI) and various Large Language Model (LLM) backends (like OpenAI, Ollama, KoboldCPP).

Its central feature is a **node-based workflow engine**. It processes user requests by executing a sequence of "nodes" defined in a JSON file. Each node performs a specific task and is designated as either a **responder** (its output is sent to the user) or a **non-responder** (its output is saved as a variable for subsequent nodes). Nodes can call an LLM, run a Python script (tool), manage conversational memory, or trigger another workflow. This architecture enables the creation of complex, stateful, and dynamic AI interactions.

**Key Capabilities:**

* **Multi-Step Workflows:** Chains multiple LLMs and tools to handle complex queries.
* **Stateful Conversation Management:** Manages short-term and long-term memory using a `discussionId` to track conversational context for tools and memory services.
* **Extensible Node System:** New functionality is added by creating handlers for new node types.
* **API Compatibility:** Exposes OpenAI/Ollama-compatible endpoints for wide client support.
* **Dynamic Tool Use:** Integrates external Python scripts and APIs into workflows.
* **Streaming Responses:** Supports both streaming (`stream=true`) and single-block (`stream=false`) responses from responder nodes to the user.

-----

#### **2. Architectural Flow**

A typical request follows this path:

1.  An API request arrives at a public endpoint, where it is routed by the server in `Middleware/api/` to a specific **API Handler** (e.g., for OpenAI or Ollama compatibility).
2.  The handler transforms the request into a standardized internal format and passes it to the **`$workflow_gateway$`**, which acts as the single bridge to the backend.
3.  The gateway invokes the **`$WorkflowManager$`**, which reads the relevant JSON workflow configuration and prepares all necessary dependencies (services, handlers).
4.  The manager delegates execution to the **`$WorkflowProcessor$`**, the core engine that runs the workflow.
5.  The `$WorkflowProcessor$` iterates through each node in the JSON configuration. For each node, it selects the appropriate **Node Handler** (e.g., `$StandardNodeHandler$`, `$ToolNodeHandler$`).
6.  The selected handler executes the node's logic. This often involves:
    * Calling the `$LLMDispatchService$` to get a response from an LLM.
    * Using the `$MemoryService$` to retrieve conversation history.
    * Running a custom tool.
7.  The output from the designated **responding node** is streamed (or sent as a single response) back to the user. Outputs from **non-responding nodes** are saved internally as variables for use by later nodes in the workflow.

-----

#### **3. Core Directory Structure**

The application logic resides in the `Middleware/` directory, which is organized by function:

* **`api/`**: The API entry point. Houses the Flask server and modular handlers (e.g., `openai_api_handler.py`) for different API schemas. The `$workflow_gateway.py` file acts as the bridge to the backend workflow engine.

* **`llmapis/`**: The abstraction layer for communicating with external LLM backends (OpenAI, Ollama, etc.). The `$LlmApiService$` uses specific handlers (e.g., `$OllamaChatHandler$`) to translate requests into the format required by each backend.

* **`services/`**: Contains stateless, reusable business logic. Key services include:
    * `$MemoryService$`: Manages conversation history and summaries.
    * `$LockingService$`: Handles workflow concurrency control.
    * `$LLMDispatchService$`: Orchestrates the final call to the `llmapis` layer.

* **`workflows/`**: The heart of the workflow engine. This is the most important directory for understanding the project's logic.
    * **`managers/`**: Contains the `$WorkflowManager$`, which orchestrates the setup of a workflow run.
    * **`processors/`**: Contains the `$WorkflowProcessor$`, the execution engine that steps through the nodes.
    * **`handlers/`**: Contains classes that implement the logic for each node type. It is divided into a `base` package for the abstract `base_workflow_node_handler` and an `impl` package for concrete implementations (e.g., `$StandardNodeHandler$`, `$ToolNodeHandler$`). **This is the primary extension point for adding new capabilities.**
    * **`tools/`**: Contains the implementation of complex tools callable by the `$ToolNodeHandler$`, such as RAG or API clients.

* **`utilities/`**: A collection of stateless helper modules for tasks like configuration management (`config_utils.py`), file I/O (`file_utils.py`), and prompt manipulation (`prompt_utils.py`, `prompt_template_utils.py`).

* **`Public/`**: Contains all user-facing configuration files, which are managed as JSON documents. This includes:
    * **Workflow Configs**: Defines the sequence of nodes for a specific workflow, including each node's settings and which endpoints they call.
    * **Endpoint Configs**: Specifies connection details for an LLM API (e.g., IP address, API type, settings).
    * **API Type Configs**: Details the specific API schema (Ollama, OpenAI, KoboldCPP, etc.) that an endpoint uses.
    * **Preset Configs**: Contains LLM generation parameters like temperature, top_k, etc.
    * **User Configs**: Holds global application settings like the default port and workflow.

* **`server.py`**: The main script that launches the Flask web server.

<!-- end list -->

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
│     ├─ processors
│     │  └─ workflows_processor.py
│     ├─ tools
│     │  ├─ dynamic_module_loader.py
│     │  ├─ offline_wikipedia_api_tool.py
│     │  └─ slow_but_quality_rag_tool.py
│     └─ __init__.py
│
├─ Public
│  └─ Configs
│     └─ ... (config folders)
│
└─ server.py
```