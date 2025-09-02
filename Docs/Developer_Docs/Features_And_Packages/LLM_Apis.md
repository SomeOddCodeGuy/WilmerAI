### **Developer Guide: `Middleware/llmapis/`**

This guide provides a deep dive into the architecture and implementation of the `Middleware/llmapis/` package. It has
been updated to reflect the verified data flows, class responsibilities, and specific implementation details of the
current codebase.

-----

## 1\. Overview

The `$Middleware/llmapis/$` package is the foundational translation layer that connects WilmerAI's core logic to
external Large Language Model (LLM) APIs. Its central purpose is to abstract the significant technical differences
between various LLM backends (e.g., OpenAI, Ollama, KoboldCPP), enabling the application to communicate with any
supported LLM through a single, standardized interface.

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
      OpenAI's `/v1/chat/completions` and Ollama's `/api/chat`.
    * **Completions (`$BaseCompletionsHandler$`)**: For simpler or legacy APIs that accept a single, unstructured string
      of text as a prompt. The entire conversation history and system instructions must be flattened into this string.
      This is used by APIs like KoboldCPP's `/api/v1/generate`.

* **Streaming Formats**: The handlers transparently manage two different real-time streaming protocols, controlled by
  the `$_iterate_by_lines$` property in the handler implementation:

    * **Server-Sent Events (SSE)**: The standard format where each data chunk is prefixed with `$data:$`. Used by OpenAI
      and KoboldCPP. A handler for this format will return `False` for `$_iterate_by_lines$`.
    * **Line-Delimited JSON**: A simpler format where the API streams a sequence of complete JSON objects, each
      separated by a newline. Used by Ollama. A handler for this format will return `True` for `$_iterate_by_lines$`.

-----

## 3\. Architectural Flow

A request to an LLM follows a clear, sequential path from service instantiation to the delivery of a raw response.

1. **Service Instantiation**: A high-level service (e.g., `$LlmHandlerService$`) creates an instance of
   `$LlmApiService$` from `$llm_api.py$`. It provides configuration names like `$endpoint$`, `$presetname$`, and runtime
   parameters like ` $stream$ and  `$max\_tokens$\`.

2. **Configuration Loading**: The `$LlmApiService.__init__()$` method loads all necessary configurations from JSON
   files. This includes the endpoint URL, API key, generation parameters from the specified preset, and the crucial
   `$apiTypeConfig$` which defines the `$llm_type$` (e.g., `"openAIChatCompletion"`, `"ollamaApiChat"`).

3. **Handler Selection (Factory)**: The `$LlmApiService$` immediately calls its own `$create_api_handler()$` method.
   This method acts as a factory, using an `$if/elif$` block to inspect the `$llm_type$` string and instantiate the
   correct concrete handler class from the `$handlers/impl/$` directory.

4. **Request Execution**: An external service (e.g., `$LLMDispatchService$`) calls the public
   `$LlmApiService.get_response_from_llm()$` method, providing the conversation history and prompts.

5. **Initial Prompt Manipulation**: Inside `$get_response_from_llm()$`, some initial, universal prompt modifications
   occur. Based on endpoint configuration, text can be prepended to the system or user prompts. If the target LLM cannot
   handle images, image messages are also filtered out here.

6. **Delegation to Handler**: `$LlmApiService$` determines if the request is for streaming or non-streaming and
   delegates the call to the appropriate method on the instantiated handler: `$handler.handle_streaming()` or
   `$handler.handle_non_streaming()`.

7. **Payload Preparation**: The handler's `$_prepare_payload()` method is called. This is where the logic diverges based
   on the paradigm:

    * **`$BaseCompletionsHandler$`**: It combines the system and user prompts into a single string. It may also append a
      final completion text based on its configuration.
    * **`$BaseChatCompletionsHandler$`**: It builds a structured list of `messages`. This handler contains its own
      comprehensive logic for modifying the conversation, such as adding text to the system message or appending a final
      assistant turn.

8. **HTTP Request and Response Parsing**: The generic `handle_...()` methods in `$base_llm_api_handler.py$` send the
   prepared payload to the LLM's URL. The response is then processed by the concrete handler's implementation of either
   `$_process_stream_data()` (for streaming) or `$_parse_non_stream_response()` (for non-streaming).

9. **Return Raw Data**: The handler returns **raw, unformatted data** back to the `$LlmApiService$`, which passes it up
   to the original caller.

    * **Streaming**: A generator that yields standardized dictionaries, like `{'token': '...', 'finish_reason': '...'}`.
    * **Non-streaming**: A single raw string containing the full generated text.

Final formatting and content cleaning (e.g., removing `<think>` tags) are the responsibility of higher-level components,
such as a `$WorkflowProcessor$` or `$StreamingResponseHandler$`, which consume this raw output.

-----

## 4\. Key Responsibilities by File

### `llm_api.py`

* **Responsibility**: The primary public entry point and orchestrator for the `llmapis` package. It bridges high-level
  service calls to the specific handler implementations.
* **Key Components**:
    * `$LlmApiService$`: The main class that loads configuration and manages the interaction flow.
    * `$create_api_handler()$`: A factory method that instantiates the correct handler based on the `$llm_type$` from
      the loaded configuration.
    * `$get_response_from_llm(...)$`: The main public method. It performs initial prompt modifications and then
      delegates the API call to the selected handler. It returns a **raw, unformatted** result.

### `handlers/base/base_llm_api_handler.py`

* **Responsibility**: Defines the abstract contract for all API handlers and provides the shared boilerplate for making
  HTTP requests.
* **Key Components**:
    * `$LlmApiHandler(ABC)$`: The abstract base class for the entire handler hierarchy.
    * `$handle_streaming()` / `$handle_non_streaming()`: Concrete methods containing the shared logic for sending HTTP
      requests via a `requests.Session` and processing the raw response. They call the abstract methods below to handle
      API-specific parsing.
    * **Abstract Methods**: Defines the interface that all concrete handlers must implement: `$_get_api_endpoint_url()`,
      `$_prepare_payload()`, `$_process_stream_data()`, and `$_parse_non_stream_response()`.

### `handlers/base/base_chat_completions_handler.py`

* **Responsibility**: Provides the shared implementation for the "Chat Completions" paradigm (list of messages).
* **Key Components**:
    * `$BaseChatCompletionsHandler$`: The intermediate base class for chat-style APIs.
    * `$_prepare_payload()`: Implements the abstract method by calling `_build_messages_from_conversation` and
      constructing the final payload with a `messages` key.
    * `$_build_messages_from_conversation()`: The core logic for this class. It transforms the conversation history into
      the required `messages` array and performs **extensive prompt modifications** based on endpoint configuration
      flags (e.g., `addTextToStartOfSystem`, `addTextToStartOfCompletion`).

### `handlers/base/base_completions_handler.py`

* **Responsibility**: Provides the shared implementation for the "Completions" paradigm (single string prompt).
* **Key Components**:
    * `$BaseCompletionsHandler$`: The intermediate base class for completion-style APIs.
    * `$_prepare_payload()`: Implements the abstract method by calling `_build_prompt_from_conversation`, placing the
      resulting string into a `prompt` key, and appending a final completion text if configured.
    * `$_build_prompt_from_conversation()`: Contains the logic to flatten the system and user prompts into a single,
      cohesive string.

### `handlers/impl/`

* **Responsibility**: This directory contains the concrete handler implementations, each tailored to a specific LLM API
  backend.
* **Examples**:
    * **`$OllamaChatHandler$`**: Inherits from `$BaseChatCompletionsHandler$`. It overrides `_prepare_payload` to place
      generation parameters in an `options` object and sets `$_iterate_by_lines$` to `True` to handle line-delimited
      JSON streaming.
    * **`$KoboldCppApiHandler$`**: Inherits from `$BaseCompletionsHandler$`. It implements `_get_api_endpoint_url` to
      return the correct Kobold endpoint and sets `$_required_event_name$` to `"message"` to properly parse the SSE
      stream.
    * **`$OllamaApiChatImageSpecificHandler$`**: Extends `$OllamaChatHandler$`. It overrides
      `_build_messages_from_conversation` to find image data in the conversation and attach it to the last user message,
      formatting it for Ollama's multimodal API.
    * **`$KoboldCppImageSpecificApiHandler$`**: Extends `$KoboldCppApiHandler$`. It overrides `_prepare_payload` to find
      image data and inject it into the top-level `gen_input` parameters before calling the parent method.

-----

## 5\. How to Extend

### How to Add Support for a New LLM API

1. **Analyze the Target API**

    * Is it a "Chat Completions" style (message list) or "Completions" style (single prompt)? This determines which base
      class you will inherit from.
    * What is the full endpoint URL?
    * What is the structure of the JSON payload? Where do generation parameters (e.g., `$temperature$`) go?
    * How does it stream? Is it SSE (`$data:`) or line-delimited JSON?
    * What is the structure of a streaming data chunk and a non-streaming response? Where is the generated text located?

2. **Create the Handler File**

    * Create a new file in `$Middleware/llmapis/handlers/impl/`, such as `$my_new_api_handler.py$`.

3. **Define the Handler Class**

    * In the new file, define your class, inheriting from either `$BaseChatCompletionsHandler$` or
      `$BaseCompletionsHandler$`.

   <!-- end list -->

   ```python
   # In middleware/llmapis/handlers/impl/my_new_api_handler.py
   from Middleware.llmapis.handlers.base.base_completions_handler import BaseCompletionsHandler
   # or BaseChatCompletionsHandler

   class MyNewApiHandler(BaseCompletionsHandler):
       # ... implementation ...
   ```

4. **Implement the Required Methods**

    * You must provide concrete implementations for the abstract methods to match your target API's protocol.

   <!-- end list -->

   ```python
   def _get_api_endpoint_url(self) -> str:
       # Return the full URL for the new API
       return f"{self.base_url}/api/v2/generate"

   # You may need to override _prepare_payload if the structure is highly custom.

   @property
   def _iterate_by_lines(self) -> bool:
       # Return True for line-delimited JSON, False for standard SSE
       return True

   def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
       # Parse a single line/chunk from the stream
       try:
           chunk_data = json.loads(data_str)
           token = chunk_data.get("generated_text", "")
           is_done = chunk_data.get("is_final", False)
           finish_reason = "stop" if is_done else None
           return {'token': token, 'finish_reason': finish_reason}
       except json.JSONDecodeError:
           return None

   def _parse_non_stream_response(self, response_json: Dict) -> str:
       # Parse the full response from a non-streaming call
       try:
           return response_json['results'][0]['full_text']
       except (KeyError, IndexError):
           return ""
   ```

5. **Create an API Type Configuration**

    * In your `Public/Configs/api_type_configs` directory, add a new JSON file (e.g., `MyNewAPI.json`). This file tells
      the system how to interpret your handler's needs.
    * Define a unique `type` string that you will use to identify this API.

   <!-- end list -->

   ```json
   {
     "type": "myNewApiCompletion",
     "presetType": "OpenAI",
     "streamPropertyName": "stream_response",
     "maxNewTokensPropertyName": "max_new_tokens"
   }
   ```

6. **Register the New Handler**

    * Finally, open `$Middleware/llmapis/llm_api.py$` and add your new handler to the factory method
      `$LlmApiService.create_api_handler()$`.

   <!-- end list -->

   ```python
   # In LlmApiService.create_api_handler()
   # ... other elif blocks ...
   elif self.llm_type == "myNewApiCompletion":
       return MyNewApiHandler(**common_args)
   ```