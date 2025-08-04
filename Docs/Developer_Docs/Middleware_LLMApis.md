# `Middleware/llmapis/` – Developer Documentation

## Overview

The `$Middleware/llmapis/$` package serves as the critical translation layer between WilmerAI's internal logic and the diverse ecosystem of external Large Language Model (LLM) APIs. Its primary responsibility is to abstract away the significant differences between various LLM backends (e.g., OpenAI, Ollama, KoboldCPP), allowing the rest of the application to interact with any supported LLM through a standardized interface.

This package solves the problem of API heterogeneity by employing a **Strategy Pattern**. It defines a common contract for all API interactions and provides a family of interchangeable "handler" classes, each implementing the specific protocol for a single backend. This design handles variations in authentication, payload structure, streaming formats, and response parsing, making it highly modular and extensible.

## Core Concepts

  * **API Handler**: A dedicated Python class that encapsulates all the logic required for end-to-end communication with a specific type of LLM API. This includes building the request payload, sending the HTTP request, and parsing the response, whether it is streaming or non-streaming.

  * **Chat Completions vs. Completions**: The package is fundamentally built around two dominant LLM interaction paradigms, which are represented by two distinct base handlers:

      * **Chat Completions (`$BaseChatCompletionsHandler$`)**: For modern APIs that accept a structured list of messages, each with a `role` (e.g., `$system$`, `$user$`, `$assistant$`) and `content`. This is the format used by OpenAI's `/v1/chat/completions` and Ollama's `/api/chat`.
      * **Completions (`$BaseCompletionsHandler$`)**: For simpler or legacy APIs that accept a single, unstructured string of text as the prompt. The entire conversation history and system instructions must be flattened into this single string. This is the format used by KoboldCPP's `/api/v1/generate` and the legacy OpenAI `/v1/completions` endpoint.

  * **Streaming Formats**: The handlers are designed to transparently manage two different real-time streaming protocols:

      * **Server-Sent Events (SSE)**: A standard where each data chunk is prefixed with `$data:$`, and the stream is often terminated by a special `$[DONE]$` message. This is used by OpenAI and KoboldCPP.
      * **Line-Delimited JSON**: A simpler format where the API streams a sequence of complete JSON objects, with each object separated by a newline character. This is the format used by Ollama.

## Architectural Flow

The process of sending a prompt to an LLM via this package follows a clear, sequential path from service instantiation to response delivery.

1.  **Service Instantiation**: An external service (e.g., `$LLMDispatchService$`) initiates a request by creating an instance of ` $LlmApiService$ from  `$llm\_api.py$\`. It passes in configuration details like the endpoint name, preset name, and whether streaming is enabled.

2.  **Configuration Loading**: The `$LlmApiService.__init__()$` method loads all relevant configuration from JSON files, including the endpoint URL, API key, generation parameters from the preset, and—most importantly—the ` $apiTypeConfig$ which specifies the  `$llm\_type$\` (e.g., $"openAIChatCompletion"$, $"ollamaApiChat"$).

3.  **Handler Selection (Factory Pattern)**: The `$LlmApiService$` immediately calls its own `$create_api_handler()$` method. This method acts as a factory, using a large `$if/elif$` block to select and instantiate the correct concrete handler class from `$Middleware/llmapis/handlers/impl/$` based on the `$llm_type$` string.

4.  **Request Execution**: The external service calls the `$LlmApiService.get_response_from_llm()$` method, providing the conversation history and prompts.

5.  **Delegation to Handler**: `$LlmApiService$` determines whether the request is for streaming or non-streaming and delegates the call to the appropriate method on the instantiated handler object: `$handler.handle_streaming()` or `$handler.handle_non_streaming()`.

6.  **Payload Preparation**: Inside the base `$LlmApiHandler$`, the `$handle_...()` method first calls the abstract `_prepare_payload()` method. This call is dispatched to the implementation in one of the intermediate base classes (`$BaseChatCompletionsHandler$` or `$BaseCompletionsHandler$`), which correctly formats the conversation into either a message list or a single string prompt.

7.  **HTTP Request**: The `$handle_...()` method sends the prepared payload to the target LLM's URL (retrieved via the handler's `_get_api_endpoint_url()` method) using a `requests.Session`.

8.  **Response Processing**:

      * For **streaming** requests, the method iterates over the response chunks. It calls the handler's concrete `_process_stream_data()` implementation to parse each API-specific chunk and extract the text token.
      * For **non-streaming** requests, it waits for the full response, parses the JSON, and calls the handler's `_parse_non_stream_response()` implementation to extract the complete generated text.

9.  **Return Value**: The final generated text (or a generator yielding text chunks) is returned up the call stack to the originating service.

## Directory & File Breakdown

### \#\#\# `llm_api.py`

  * **Responsibility**: To act as the primary service entry point and factory for the `llmapis` package, connecting high-level configuration to specific handler implementations.
  * **Key Components**:
      * `$LlmApiService$`: The main class that orchestrates the interaction with a single configured LLM endpoint.
      * `$__init__(endpoint, presetname, ...)$`: Constructor that loads all required configuration from files based on the provided names.
      * `$create_api_handler()$`: A factory method that inspects the loaded configuration and instantiates the appropriate concrete handler from the `$handlers/impl/` directory.
      * `$get_response_from_llm(...)$`: The main public method that takes conversation data and delegates the actual API call to the selected handler instance.
  * **Interactions**: Instantiated and used by higher-level services like `$LLMDispatchService$`. It creates and uses instances of various `$LlmApiHandler$` subclasses.

### \#\#\# `handlers/base/`

This subdirectory defines the abstract architecture and shared logic for all API handlers.

#### \#\#\#\# `base_llm_api_handler.py`

  * **Responsibility**: To define the abstract contract that all concrete API handlers must follow and to provide the generic boilerplate for making HTTP requests.
  * **Key Components**:
      * `$LlmApiHandler(ABC)$`: The abstract base class for the entire handler hierarchy.
      * `$handle_streaming()` / `$handle_non_streaming()`: Concrete methods that contain the shared logic for making HTTP requests with `requests`, handling streaming vs. non-streaming responses, and calling the abstract methods for API-specific tasks.
      * **Abstract Methods**: Defines the core interface that subclasses must implement:
          * `$_get_api_endpoint_url()`: Must return the full URL for the API endpoint.
          * `$_prepare_payload()`: Must format the conversation into the final JSON payload.
          * `$_process_stream_data()`: Must parse a single chunk from a streaming response.
          * `$_parse_non_stream_response()`: Must extract the text from a complete JSON response.
  * **Interactions**: Serves as the ultimate parent class for all other handlers in this package.

#### \#\#\#\# `base_chat_completions_handler.py`

  * **Responsibility**: To provide a shared implementation for the "Chat Completions" paradigm (list of messages).
  * **Key Components**:
      * `$BaseChatCompletionsHandler$`: The intermediate base class for chat-style APIs.
      * `$_prepare_payload()`: Implements the abstract method to orchestrate the creation of a standard chat payload.
      * `$_build_messages_from_conversation()`: The core logic for this class. It takes the raw conversation history and transforms it into the required `messages` array, handling various prompt modifications along the way.
  * **Interactions**: Inherits from `$LlmApiHandler$`. Is the direct parent of handlers like `$OpenAiApiHandler$` and `$OllamaChatHandler$`.

#### \#\#\#\# `base_completions_handler.py`

  * **Responsibility**: To provide a shared implementation for the "Completions" paradigm (single string prompt).
  * **Key Components**:
      * `$BaseCompletionsHandler$`: The intermediate base class for completion-style APIs.
      * `$_prepare_payload()`: Implements the abstract method by calling `_build_prompt_from_conversation` and placing the result in the payload.
      * `$_build_prompt_from_conversation()`: Contains the logic to flatten the system and user prompts into a single, cohesive string.
  * **Interactions**: Inherits from `$LlmApiHandler$`. Is the direct parent of handlers like `$KoboldCppApiHandler$` and `$OpenAiCompletionsApiHandler$`.

### \#\#\# `handlers/impl/`

This subdirectory contains the concrete implementations, each one tailored to a specific API backend.

#### \#\#\#\# `koboldcpp_api_handler.py` / `koboldcpp_api_image_specific_handler.py`

  * **Responsibility**: Handles communication with KoboldCPP's `/generate` endpoint, with an extension for image-enabled models.
  * **Key Methods**:
      * Implements `_get_api_endpoint_url`, `_process_stream_data`, etc., to match KoboldCPP's specific SSE format (which uses a named event `message`) and JSON response structure.
      * The `$KoboldCppImageSpecificApiHandler$` overrides `_prepare_payload` to inject an `images` list into the generation parameters before calling the parent's implementation.
  * **Interactions**: Inherits from `$BaseCompletionsHandler$`.

#### \#\#\#\# `ollama_chat_api_handler.py` / `ollama_chat_api_image_specific_handler.py`

  * **Responsibility**: Handles communication with Ollama's `/api/chat` endpoint, supporting both text and multimodal models.
  * **Key Methods**:
      * Implements the abstract methods to handle Ollama's line-delimited JSON streaming and its unique payload structure, where generation parameters are nested inside an `$options$` object.
      * The `$OllamaApiChatImageSpecificHandler$` overrides `_build_messages_from_conversation` to find image data and attach it to the last user message under an `$images$` key, as required by Ollama's vision models.
  * **Interactions**: Inherits from `$BaseChatCompletionsHandler$`.

#### \#\#\#\# `ollama_generate_api_handler.py`

  * **Responsibility**: Handles communication with Ollama's simpler `/api/generate` single-prompt endpoint.
  * **Key Methods**: Implements the necessary methods to format the payload for the `/generate` endpoint and parse its distinct line-delimited JSON stream.
  * **Interactions**: Inherits from `$BaseCompletionsHandler$`.

#### \#\#\#\# `openai_api_handler.py` / `openai_chat_api_image_specific_handler.py`

  * **Responsibility**: Handles communication with any OpenAI-compatible `/v1/chat/completions` endpoint for text and vision models.
  * **Key Methods**:
      * Implements the parsing logic for the standard OpenAI SSE stream and non-streaming response structure.
      * The `$OpenAIApiChatImageSpecificHandler$` overrides `_build_messages_from_conversation` to perform complex image processing. It can handle image URLs, local file URIs, and base64 strings, converting them all into the `content` array format required by OpenAI vision APIs.
  * **Interactions**: Inherits from `$BaseChatCompletionsHandler$`.

#### \#\#\#\# `openai_completions_api_handler.py`

  * **Responsibility**: Handles communication with the legacy OpenAI-compatible `/v1/completions` endpoint.
  * **Key Methods**: Implements the parsing logic specific to the legacy completions API response format.
  * **Interactions**: Inherits from `$BaseCompletionsHandler$`.

## How to Extend / Use

The handler-based design makes it straightforward to add support for a new LLM API. Follow these steps:

### How to Add Support for a New LLM API

1.  **Analyze the Target API**

      * Is it a "Chat Completions" style (message list) or "Completions" style (single prompt)? This determines which base class you will inherit from.
      * What is the full endpoint URL?
      * What is the structure of the JSON payload? Where do generation parameters (like `$temperature$`, `$max_tokens$`) go?
      * How does it stream? Is it SSE (`$data:$`) or line-delimited JSON?
      * What is the structure of a streaming data chunk and a non-streaming response? Where is the generated text located?

2.  **Create the Handler File**

      * Create a new file in `$Middleware/llmapis/handlers/impl/`, such as `$my_new_api_handler.py$`.

3.  **Define the Handler Class**

      * In the new file, define your class, inheriting from either `$BaseChatCompletionsHandler$` or `$BaseCompletionsHandler$`.

    <!-- end list -->

    ```python
    # In middleware/llmapis/handlers/impl/my_new_api_handler.py
    from Middleware.llmapis.handlers.base.base_completions_handler import BaseCompletionsHandler
    # or BaseChatCompletionsHandler

    class MyNewApiHandler(BaseCompletionsHandler):
        # ... implementation ...
    ```

4.  **Implement the Required Methods**

      * You must provide concrete implementations for the abstract methods to match your target API's protocol.

    <!-- end list -->

    ```python
    def _get_api_endpoint_url(self) -> str:
        # Return the full URL for the new API
        return f"{self.base_url}/api/v2/generate"

    # You may need to override _prepare_payload if the structure is highly custom
    # Otherwise, the base class implementation may be sufficient.

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

5.  **Create an API Type Configuration**

      * In your `Public/Configs/api_type_configs` directory, add a new JSON file (e.g., `MyNewAPI.json`). This file tells the system how to interpret your handler's needs.
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

6.  **Register the New Handler**

      * Finally, open `$Middleware/llmapis/llm_api.py$` and add your new handler to the factory method `$LlmApiService.create_api_handler()$`.

    <!-- end list -->

    ```python
    # In LlmApiService.create_api_handler()
    # ... other elif blocks ...
    elif self.llm_type == "myNewApiCompletion":
        return MyNewApiHandler(
            # Pass all the required arguments from self
            base_url=self.endpoint_url,
            api_key=self.api_key,
            # ... etc.
        )
    ```

Once these steps are complete, you can create an endpoint configuration that uses your new `$llm_type$ (`"myNewApiCompletion"\`), and WilmerAI will be able to communicate with the new LLM backend.