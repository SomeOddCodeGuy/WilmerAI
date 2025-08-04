# WilmerAI – Developer Documentation

## 1\. Project Overview

WilmerAI is a **middleware system** designed to bridge user interfaces (e.g., SillyTavern, OpenWebUI, custom clients) with various Large Language Model (LLM) backends. Its primary function is to process user prompts by leveraging a highly modular and extensible workflow engine.

At its core, WilmerAI orchestrates complex, multi-step interactions by routing prompts through sequences of nodes defined in JSON configuration files. Each node performs a specific task—calling an LLM, running a Python script, managing memory, or triggering another workflow. This architecture allows developers to create sophisticated, dynamic, and stateful conversational agents with ease.

### Key Capabilities

  - **Smart Prompt Routing:** Automatically directs user input to the most appropriate workflow (Optional)
  - **Multi-Step, Multi-LLM Workflows:** Chains multiple LLMs and tools together to handle complex queries.
  - **Stateful Conversation Management:** Manages short-term memory, long-term memory, and rolling summaries for contextual awareness.
  - **Extensible Node-Based System:** Easily add new capabilities by creating custom "handlers" for new workflow node types.
  - **Dynamic Tool Use:** Integrate external tools, APIs, and custom Python scripts directly into workflows.
  - **Flexible API Compatibility:** Exposes OpenAI- and Ollama-compatible endpoints while being able to connect to a variety of LLM backends (OpenAI, Ollama, KoboldCPP, etc.).
  - **Partial Multi-Modal Support:** Initial support for image processing is implemented and can be expanded.

-----

## 2\. Architectural Flow

A typical request in WilmerAI follows this high-level path:

1.  **API Ingestion & Routing:** A request arrives at a public endpoint (e.g., `/v1/chat/completions`). The `$ApiServer$` in `Middleware/api/api_server.py` routes the request to the appropriate registered handler within the `Middleware/api/handlers/impl/` directory.
2.  **Data Transformation:** The specific API handler (e.g., `$ChatCompletionsAPI$`) parses the client-specific request, validates its contents, and transforms the payload into a standardized internal message list format.
3.  **Engine Handoff:** The handler calls the `$workflow_gateway.handle_user_prompt()` function, passing it the standardized message list and other relevant parameters like the streaming flag. This function serves as the single bridge between the API layer and the core workflow engine.
4.  **Workflow Initialization:** The gateway invokes the `$WorkflowManager$`, providing it with the workflow name and initial message payload.
5.  **Dependency Setup:** The `$WorkflowManager$` loads the relevant workflow configuration and prepares all necessary dependencies, including node handlers and services.
6.  **Execution Delegation:** It creates an instance of the `$WorkflowProcessor$`, injecting all dependencies and the specific request context into it.
7.  **Node-by-Node Execution:** The `$WorkflowProcessor$` iterates through each node in the workflow configuration. For each node, it:
        a. Determines the node's type (e.g., "Standard", "PythonModule", "CustomWorkflow").
        b. Selects the appropriate **Node Handler** (e.g., `$StandardNodeHandler$`, `$ToolNodeHandler$`).
        c. Invokes the handler's `handle()` method.
8.  **Handler Logic:** The specific handler executes its logic. This often involves:
        a. Using the `$WorkflowVariableManager$` to substitute variables (e.g., `{agent1Output}`).
        b. Calling a service that uses the `$llmapis$` package to format prompts and get a response from an LLM.
        c. Running a tool or managing a memory file.
9.  **Response Generation:** The final "responder" node's output is streamed or returned back up the chain to the user.

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
│  │  ├─ ...
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
│     │  │  └─  base_workflow_node_handler.py
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

### Description of Directories and Key Files

#### **`Middleware/`**

This is the application's brain, containing all the core logic.

  - **`api/`**: The entry point for all incoming API requests. It acts as the "front door" of WilmerAI, containing the Flask web server. Its role is to be a compatibility and translation layer, accepting requests conforming to various schemas, transforming them into a standard internal format, and dispatching them to the workflow engine.

      - **`app.py`**: Instantiates the global Flask `$app$` object, preventing circular dependencies.
      - **`api_server.py`**: Contains the `$ApiServer$` class, which orchestrates the API layer. It automatically discovers all handler classes in the `handlers/impl/` directory, registers their routes with Flask, and runs the web server.
      - **`workflow_gateway.py`**: Provides the single, standardized bridge between API handlers and the backend workflow engine. Its crucial `handle_user_prompt()` function is called by all endpoints to initiate processing. It also contains helpers like decorators to handle client-specific behaviors gracefully.
      - **`api_helpers.py`**: Provides helper functions used by the API layer, such as building client-specific JSON responses (`build_response_json()`) and formatting Server-Sent Events (`sse_format()`).
      - **`handlers/`**: Contains the logic for specific API endpoints, separated into a base contract and concrete implementations for different API standards (OpenAI, Ollama).
      - **How to Add a New API Endpoint**: To extend the API, create a new file in `Middleware/api/handlers/impl/`. Inside, define `MethodView` classes for your endpoints and a main handler class inheriting from `$BaseApiHandler$`. Implement the `register_routes()` method to link URLs to your views. The `$ApiServer$` will automatically discover and load it.

  - **`common/`**: Stores cross-cutting constants and definitions used throughout the middleware.

      - **`constants.py`**: A centralized file for static application-wide values. Its most important role is defining the `VALID_NODE_TYPES` list, which acts as an allowlist for all valid "type" strings in workflow JSON files. This ensures the workflow engine only processes recognized node types.

  - **`exceptions/`**: Contains custom exception classes used for control flow and error handling.

      - **`early_termination_exception.py`**: Defines the `$EarlyTerminationException$`. This exception is not an error but a specific control-flow mechanism. It is used by node handlers to signal that a workflow should stop processing immediately and return the current result, such as when a `WorkflowLock` node finds another instance already running.

  - **`llmapis/`**: The translation layer responsible for communicating with external LLM backends. This package abstracts away the differences between various APIs (e.g., OpenAI, Ollama, KoboldCPP), allowing the rest of the application to interact with them through a consistent interface.

      - **`llm_api.py`**: This file contains the `$LlmApiService$`, which acts as the primary entry point into this package. It is instantiated for a specific LLM endpoint configuration. Its key responsibilities are to load all necessary configs (endpoint URL, API key, presets) and use a factory method, `create_api_handler()`, to instantiate the correct API-specific handler based on the configured `llm_type`. Its `get_response_from_llm()` method is called by higher-level services to send a prompt and receive a response, delegating the actual communication to the selected handler.
      - **`handlers/`**: This directory contains the core abstraction for the LLM communication logic, separating the "what to do" from the "how to do it".
          - **`base/`**: Defines the abstract contracts and shared logic for all handlers.
              - **`base_llm_api_handler.py`**: Contains `$LlmApiHandler$`, the abstract base class for all API handlers. It defines the required interface (e.g., `_prepare_payload`, `_process_stream_data`) and implements the common request-sending and streaming boilerplate.
              - **`base_chat_completions_handler.py`**: An intermediate abstract class, `$BaseChatCompletionsHandler$`, that inherits from `$LlmApiHandler$`. It provides a shared implementation for APIs that use a list of messages (e.g., OpenAI `/chat/completions`). It handles the logic for building the `messages` array from conversation history.
              - **`base_completions_handler.py`**: Another intermediate abstract class, `$BaseCompletionsHandler$`, for APIs that take a single, flattened string prompt (e.g., KoboldCPP `/generate` or legacy OpenAI `/completions`). It handles the logic for converting conversation history into this single string.
          - **`impl/`**: Contains the concrete handler implementations, each tailored to a specific backend API.
              - **OpenAI Handlers (`$OpenAiApiHandler$`, `$OpenAiCompletionsApiHandler$`):** Implement the logic for standard OpenAI-compatible Chat and legacy Completions endpoints, including their specific payload structures and SSE streaming formats.
              - **Ollama Handlers (`$OllamaChatHandler$`, `$OllamaGenerateApiHandler$`):** Implement logic for Ollama's `/api/chat` and `/api/generate` endpoints. They correctly format payloads with the nested `options` dictionary and handle Ollama's line-delimited JSON streaming.
              - **KoboldCPP Handler (`$KoboldCppApiHandler$`):** Implements logic for KoboldCPP's `/generate` endpoint, handling its specific SSE event-based streaming format.
              - **Image-Specific Handlers (`$OpenAIApiChatImageSpecificHandler$`, etc.):** These specialized classes inherit from their text-only counterparts. They override methods like `_build_messages_from_conversation` or `_prepare_payload` to intercept image data, format it correctly for the target vision model, and inject it into the final request payload before delegating back to the parent class. This provides a clean separation of concerns for multimodal support.

  - **`services/`**: Contains stateless, reusable services that can be injected into various parts of the application.

      - **`llm_service.py`**: A factory service responsible for creating and configuring `$LlmHandler$` instances based on endpoint configurations. It abstracts away the details of which backend API to use.
      - **`llm_dispatch_service.py`**: A crucial stateless service that handles the final step of communicating with an LLM. Its `dispatch()` method takes a prepared configuration and message list, formats the final prompt according to the LLM's required schema (Chat vs. Completion), and calls the underlying LLM API handler. This service is used by multiple node handlers.
      - **`locking_service.py`**: Defines the `$LockingService$` class, which centralizes logic for managing workflow concurrency. It uses a user-specific SQLite database to create, check, and remove locks, preventing specific workflows or nodes from running simultaneously.
      - **`memory_service.py`**: Defines the `$MemoryService$` class, which centralizes all business logic for stateful conversation management. It is responsible for reading from and interacting with short-term memory files and long-term summary files. Its methods handle the logic for retrieving recent conversation turns, identifying new memories since the last summary, and providing the correct memory context to the workflow nodes.
      - **`timestamp_service.py`**: Defines the `$TimestampService$` class, which centralizes the business logic for applying and persisting timestamps to conversation messages. It contains complex rules to backfill timestamps and ensure a coherent, logical timeline is maintained in the message history files.

  - **`utilities/`**: A package for generic, stateless helper functions that are reusable across the application. This includes utilities for configuration and path management, file I/O, text manipulation, prompt formatting, advanced search, and stream processing.

      - **`config_utils.py`**: The central configuration management module. It abstracts all file system path logic and provides a consistent interface for accessing user settings, endpoint details, workflow files, and other configuration-based resources. It is responsible for loading user JSON files and providing high-level getter functions (`get_application_port`, `get_active_custom_workflow_name`, etc.) to the rest of the application.
      - **`datetime_utils.py`**: Provides simple, stateless helper functions for creating and manipulating formatted timestamp strings, used by the `$TimestampService$`.
      - **`file_utils.py`**: Provides a robust set of functions for file system interactions. Key responsibilities include:
          - Case-insensitive path resolution to prevent errors on different operating systems.
          - Safely reading from and writing to JSON files, including ensuring a file exists (`ensure_json_file_exists`).
          - Handling the specific format for memory files that store text chunks with their hashes (`read_chunks_with_hashes`, `write_chunks_with_hashes`).
          - Loading and saving timestamp and other custom configuration files.
      - **`prompt_extraction_utils.py`**: A specialized module for parsing and extracting information *from* raw prompt strings or message lists. Its responsibilities include parsing custom-tagged strings into structured message objects, separating the initial system prompt from the main conversation, and extracting specific parts of the chat history, like the last N turns or a `[DiscussionId]`.
      - **`prompt_template_utils.py`**: This module focuses on *applying* formatting to message lists based on template files. It prepares prompts for specific LLM backends by adding role-specific prefixes and suffixes (e.g., for completion models) or leaving them clean (for chat models). It also includes logic for preparing prompts by reducing the number of messages to fit within a specified token limit.
      - **`prompt_utils.py`**: A multi-purpose utility module that provides tools for memory management and prompt manipulation. Its key functions include:
          - Generating SHA-256 hashes for individual messages, which are used as unique identifiers for memory chunks.
          - Chunking long conversations into smaller blocks based on token size and associating them with a message hash.
          - Implementing the logic to compare message hashes with hashes stored in memory and summary files to determine how many new messages have occurred.
          - Providing helper functions to strip custom template tags (e.g., `[Beg_User]`) from text.
      - **`search_utils.py`**: Provides a suite of functions for performing advanced, content-based searches within text data (e.g., conversation logs). It implements a simple search engine using an inverted index, scores results based on token frequency and proximity, and offers functions like `advanced_search_in_chunks` to return the most relevant excerpts. This module is critical for tools that need to find specific information within a large context, like the `slow_but_quality_rag_tool`.
      - **`streaming_utils.py`**: A specialized utility to process and sanitize real-time text streams from LLMs. It provides the `$StreamingThinkRemover$` class, a stateful processor that inspects incoming text for configurable start and end tags (e.g., `<think>`, `</think>`) and removes the content between them. This ensures a clean user experience by hiding the model's internal "chain-of-thought" process from the final output.
      - **`text_utils.py`**: A foundational utility module for text manipulation. It provides a lightweight, heuristic-based token estimator (`rough_estimate_token_length`), functions for truncating text to a specific token limit, and robust tools for splitting message histories into token-aware chunks (`chunk_messages_by_token_size`). It also includes helpers to escape special characters to prevent conflicts with string formatting.

  - **`workflows/`**: The heart of the workflow engine. This directory is heavily structured to separate responsibilities.

      - **`managers/`**: Classes responsible for orchestrating and managing high-level workflow tasks.
          - **`workflow_manager.py`**: The main entry point for running a workflow. Its primary role is **setup and delegation**. It loads the workflow's JSON configuration, instantiates all necessary services and handlers, and then passes control to a `$WorkflowProcessor$` instance for execution.
          - **`workflow_variable_manager.py`**: A service that processes strings from workflow configurations and replaces dynamic variables (e.g., `{agent1Output}`, `{lastUserMessage}`) with their runtime values.
      - **`processors/`**: Contains the core execution logic of the workflow engine.
          - **`workflows_processor.py`**: The **execution engine** for a single workflow run. It receives its configuration and dependencies from the `$WorkflowManager$`. Its `execute()` method is a generator that iterates through each node of the workflow, determines the correct handler, and yields the final result. It manages the run's state, including `agent_outputs` and streaming logic.
      - **`handlers/`**: Contains the logic for specific workflow node types, separated into a base contract and concrete implementations. This is the primary mechanism for extending WilmerAI's functionality.
          - **`base/`**: Defines the abstract contracts for all workflow node handlers.
              - **` base_workflow_node_handler.py`**: The abstract base class (`$BaseHandler$`) that defines the contract for all node handlers. Every handler must implement the `handle()` method.
          - **`impl/`**: Contains the concrete handler implementations for each node type.
              - **`standard_node_handler.py`**: Handles the most common node type, "Standard". Its main job is to orchestrate the call to the `$LLMDispatchService$` to get a response from a language model.
              - **`tool_node_handler.py`**: Handles nodes that execute external tools, such as running a `PythonModule`, querying the `OfflineWikiApi`, or performing a RAG search.
              - **`memory_node_handler.py`**: Handles all memory-related nodes, such as reading from a memory file, summarizing recent turns, or triggering a full chat summary workflow.
              - **`sub_workflow_handler.py`**: Handles nodes that trigger *other* workflows (`CustomWorkflow` and `ConditionalCustomWorkflow`), allowing for nested and conditional logic.
              - **`specialized_node_handler.py`**: Handles miscellaneous, single-purpose nodes like `WorkflowLock` (which uses the `$LockingService$` for preventing concurrent runs) and `ImageProcessor`.
      - **`tools/`**: Contains the implementation of complex tools that can be called by the `$ToolNodeHandler$`.