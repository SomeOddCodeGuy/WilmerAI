### **Developer Guide: `Middleware/llmapis/`**

This guide provides a deep dive into the architecture and implementation of the `Middleware/llmapis/` package. It has
been updated to reflect the verified data flows, class responsibilities, and specific implementation details of the
current codebase.

-----

## 1\. Overview

The `$Middleware/llmapis/$` package is the foundational translation layer that connects WilmerAI's core logic to
external Large Language Model (LLM) APIs. Its central purpose is to abstract the significant technical differences
between various LLM backends (e.g., OpenAI, Anthropic Claude, Ollama, KoboldCPP), enabling the application to
communicate with any supported LLM through a single, standardized interface.

To solve the problem of API heterogeneity, the package employs two key design patterns:

* A **Strategy Pattern**, where a family of interchangeable "handler" classes encapsulates the unique communication
  protocol for each LLM backend. This modular design isolates the logic for handling different authentication methods,
  payload structures, streaming formats, and response parsing.
* A **Factory Pattern**, where a central service class (`$LlmApiService$`) is responsible for selecting and
  instantiating the correct handler (strategy) at runtime based on configuration.

This architecture makes the system highly extensible, allowing new LLM backends to be integrated with minimal changes to
the core application logic.

-----

## 2\. Core Concepts

The package is built on a few fundamental concepts that dictate its structure and operation.

* **API Handler (`$LlmApiHandler$`)**: A dedicated Python class that contains all the logic necessary for end-to-end
  communication with a specific LLM API. This includes preparing the request payload, sending the HTTP request, and
  parsing the raw response. Each concrete handler resides in `$Middleware/llmapis/handlers/impl/$`.

* **Interaction Paradigms**: The system is designed around the two dominant LLM API paradigms, which are represented by
  two distinct abstract base handlers:

    * **Chat Completions (`$BaseChatCompletionsHandler$`)**: For modern APIs that accept a structured list of messages,
      where each message has a `role` (e.g., `$system$`, `$user$`) and `content`. This is the standard for APIs like
      OpenAI's `/v1/chat/completions`, Ollama's `/api/chat`, and Anthropic's Claude Messages API.
    * **Completions (`$BaseCompletionsHandler$`)**: For simpler or legacy APIs that accept a single, unstructured string
      of text as a prompt. The entire conversation history and system instructions must be flattened into this string.
      This is used by APIs like KoboldCPP's `/api/v1/generate`.

* **Streaming Formats**: The handlers transparently manage different real-time streaming protocols, controlled by
  the `$_iterate_by_lines$` property in the handler implementation:

    * **Server-Sent Events (SSE)**: A common format where data chunks may be prefixed with markers like `$data:$`. Used
      by OpenAI, Anthropic, and KoboldCPP. A handler for this format will return `False` for `$_iterate_by_lines$`.
    * **Line-Delimited JSON**: A simpler format where the API streams a sequence of complete JSON objects, each
      separated by a newline. Used by Ollama. A handler for this format will return `True` for `$_iterate_by_lines$`.

-----

## 3\. Architectural Flow

A request to an LLM follows a clear, sequential path from service instantiation to the delivery of a raw response.

1. **Service Instantiation**: A high-level service (e.g., `$LlmHandlerService$`) creates an instance
   of `$LlmApiService$` from `$llm_api.py$`.

2. **Configuration Loading**: The `$LlmApiService.__init__()$` method loads all necessary configurations from JSON
   files. This includes the endpoint URL, API key, generation parameters from the specified preset, and the
   crucial `$apiTypeConfig$` which defines the `$llm_type$` (e.g., `"openAIChatCompletion"`, `"claudeApiChat"`).

3. **Handler Selection (Factory)**: The `$LlmApiService$` immediately calls its own `$create_api_handler()$` method.
   This method acts as a factory, using an `$if/elif$` block to inspect the `$llm_type$` string and instantiate the
   correct concrete handler class from the `$handlers/impl/$` directory.

4. **Request Execution**: An external service (e.g., `$LLMDispatchService$`) calls the
   public `$LlmApiService.get_response_from_llm()` method, providing the conversation history, prompts, and an optional
   **`request_id`** for cancellation.

5. **Initial Prompt Manipulation**: Inside `$get_response_from_llm()$`, some initial, universal prompt modifications
   occur. Based on endpoint configuration, text can be prepended to the system or user prompts. If the target LLM cannot
   handle images, image messages are also filtered out here.

6. **Delegation to Handler**: `$LlmApiService$` determines if the request is for streaming or non-streaming and
   delegates the call to the appropriate method on the instantiated handler: `$handler.handle_streaming()`
   or `$handler.handle_non_streaming()`. The `request_id` is passed along.

7. **Payload Preparation**: The handler's `$_prepare_payload()` method is called. This is where the logic diverges based
   on the paradigm.

8. **HTTP Request and Response Parsing**: The generic `handle_...()` methods in `$base_llm_api_handler.py$` send the
   prepared payload to the LLM's URL. For streaming responses, the method
   checks `cancellation_service.is_cancelled(request_id)` before processing each chunk, allowing requests to be
   interrupted mid-stream. The response is then processed by the concrete handler's implementation of
   either `$_process_stream_data()` (for streaming) or `$_parse_non_stream_response()` (for non-streaming).

9. **Return Raw Data**: The handler returns **raw, unformatted data** back to the `$LlmApiService$`, which passes it up
   to the original caller.

    * **Streaming**: A generator that yields standardized dictionaries, like `{'token': '...', 'finish_reason': '...'}`.
    * **Non-streaming**: A single raw string containing the full generated text.

Final formatting and content cleaning (e.g., removing `<think>` tags) are the responsibility of higher-level components,
such as a `$WorkflowProcessor$` or `$StreamingResponseHandler$`, which consume this raw output.

-----

## 4\. Key Responsibilities by File

### `llm_api.py`

* **Responsibility**: The primary public entry point and orchestrator for the `llmapis` package.
* **Key Components**:
    * `$LlmApiService$`: The main class that loads configuration and manages the interaction flow.
    * `$create_api_handler()`: A factory method that instantiates the correct handler based on the `$llm_type$`.
    * `$get_response_from_llm(...)$`: The main public method. It accepts a `request_id` and delegates the API call to
      the selected handler. It returns a **raw, unformatted** result.

### `handlers/base/base_llm_api_handler.py`

* **Responsibility**: Defines the abstract contract for all API handlers and provides the shared boilerplate for making
  HTTP requests.
* **Key Components**:
    * `$LlmApiHandler(ABC)$`: The abstract base class for the entire handler hierarchy.
    * `$handle_streaming()` / `$handle_non_streaming()`: Concrete methods containing the shared logic for sending HTTP
      requests. The streaming method includes the core cancellation check logic.
    * **Abstract Methods**: Defines the interface that all concrete handlers must implement.

### `handlers/base/base_chat_completions_handler.py`

* **Responsibility**: Provides the shared implementation for the "Chat Completions" paradigm (list of messages).

### `handlers/base/base_completions_handler.py`

* **Responsibility**: Provides the shared implementation for the "Completions" paradigm (single string prompt).

### `handlers/impl/`

* **Responsibility**: This directory contains the concrete handler implementations, each tailored to a specific LLM API
  backend.
* **Examples**:
    * **`$ClaudeApiHandler$`**: Inherits from `$BaseChatCompletionsHandler$`. It overrides `_prepare_payload` to match
      the Anthropic Messages API format (e.g., moving the system prompt to a top-level parameter) and correctly parses
      Claude's specific SSE stream format.
    * **`$OllamaChatHandler$`**: Inherits from `$BaseChatCompletionsHandler$`. It overrides `_prepare_payload` to place
      generation parameters in an `options` object and sets `$_iterate_by_lines$` to `True` to handle line-delimited
      JSON streaming.
    * **`$KoboldCppApiHandler$`**: Inherits from `$BaseCompletionsHandler$`. It implements `_get_api_endpoint_url` to
      return the correct Kobold endpoint.
    * **`$OllamaApiChatImageSpecificHandler$`**: Extends `$OllamaChatHandler$`. It
      overrides `_build_messages_from_conversation` to find image data and attach it to the last user message,
      formatting it for Ollama's multimodal API.

-----

## 5\. How to Extend

### How to Add Support for a New LLM API

The process for adding a new LLM remains the same. The guide below provides the high-level steps.

1. **Analyze the Target API**: Determine its paradigm (Chat vs. Completions), payload structure, and streaming format.
2. **Create the Handler File**: Create a new file in `$Middleware/llmapis/handlers/impl/`.
3. **Define the Handler Class**: Inherit from `$BaseChatCompletionsHandler$` or `$BaseCompletionsHandler$`.
4. **Implement the Required Methods**: Provide concrete implementations for the abstract methods to match your target
   API's protocol.
5. **Create an API Type Configuration**: Add a new JSON file in your `Public/Configs/ApiTypes/` directory defining a
   unique `type` string.
6. **Register the New Handler**: Add your new handler to the factory method `$LlmApiService.create_api_handler()`
   in `$Middleware/llmapis/llm_api.py$`.