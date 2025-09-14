### **Developer Guide: `Middleware/api/`**

## 1\. Overview

This directory contains the primary entry point for the WilmerAI application: a Flask web server that exposes all
public-facing API endpoints. Its fundamental role is to act as a robust **compatibility and translation layer**. It
accepts requests conforming to popular external schemas (like OpenAI and Ollama), transforms the data into a
standardized internal format, and dispatches the request to the central workflow engine for processing.

The architecture is designed to be modular and extensible. The API logic is broken down into an orchestrator (
`ApiServer`), a business logic gateway (`workflow_gateway`), and a series of self-contained **handlers** for specific
API schemas. A key component of this architecture is the `ResponseBuilderService`, which centralizes all logic for
constructing API-specific JSON responses, ensuring that outgoing data perfectly matches the schema expected by the
client.

This separation of concerns makes the system cleaner, more maintainable, and significantly easier to extend with new
endpoints or entire API compatibility layers.

-----

## 2\. Architectural Flow

A request's journey through the `api` package follows a well-defined sequence. The primary difference in the flow
depends on whether the client requests a streaming or non-streaming response.

1. **Ingestion**: An external client sends an HTTP request to a specific URL (e.g., `/v1/chat/completions`).

2. **Routing**: The Flask application, orchestrated by `ApiServer` at startup, routes the request to the appropriate
   `MethodView` class (e.g., `ChatCompletionsAPI`) located within a registered handler file (e.g.,
   `openai_api_handler.py`).

3. **Method Invocation**: The corresponding HTTP method within the class is called (typically `post()`). The method
   immediately sets a global `API_TYPE` variable (e.g., `openaichatcompletion`) so downstream components know which
   response format to use.

4. **Pre-Processing & Validation**: The method performs initial actions, such as applying decorators (e.g.,
   `@handle_openwebui_tool_check`) and validating the incoming JSON payload.

5. **Data Transformation**: The endpoint's logic transforms the client-specific payload into a standardized internal
   `messages` list. This includes parsing different structures, handling multimedia content like base64 images, and
   applying configuration-based transformations.

6. **Engine Handoff**: The transformed `messages` list and a boolean `stream` flag are passed to the
   `handle_user_prompt()` function in `workflow_gateway.py`. This is the critical handoff point where control is passed
   to the internal workflow engine.

7. **Response Handling**: The handler waits for a result from the workflow engine. The handling depends on the `stream`
   flag:

    * **Streaming**: If `stream` is true, `handle_user_prompt()` returns a Python generator. The handler immediately
      returns a Flask `Response` object with the appropriate `mimetype` (e.g., `'text/event-stream'`). As the backend
      engine generates text, the generator yields formatted data chunks. Deep within the streaming logic,
      `api_helpers.build_response_json()` is called for each token, which in turn uses the `ResponseBuilderService` to
      construct a perfectly formatted JSON chunk string for the specific API type.
    * **Non-Streaming**: If `stream` is false, `handle_user_prompt()` returns a single, complete string of text. The
      handler then calls the appropriate method **directly** on the `ResponseBuilderService` (e.g.,
      `response_builder.build_openai_chat_completion_response(text)`) to construct the final, complete JSON object. This
      object is then returned to the client using Flask's `jsonify`.

-----

## 3\. Directory & File Breakdown

### `Middleware/api/`

#### `app.py`

* **Responsibility**: Instantiates the global Flask `app` object.
* **Rationale**: By placing the app instance in its own file, other modules can import it without creating circular
  dependencies.

#### `api_server.py`

* **Responsibility**: Discovers all API handlers, registers their routes with the Flask app, and runs the web server. It
  is the main orchestrator for the API layer.
* **Key Components**:
    * `ApiServer` class:
        * `_discover_and_register_handlers()`: Automatically scans the `Middleware/api/handlers/impl/` directory for
          Python files. It imports them, finds any classes that inherit from `BaseApiHandler`, and calls their
          `register_routes()` method, making the system plug-and-play.
        * `run()`: Starts the Flask server.

#### `workflow_gateway.py`

* **Responsibility**: Acts as the single, standardized bridge between the API request handlers and the backend workflow
  engine.
* **Key Components**:
    * `handle_user_prompt()`: The crucial function that every data-handling endpoint calls. It takes the standardized
      `messages` list and dispatches it to the correct backend service (`PromptCategorizationService` or
      `WorkflowManager`).
    * `@handle_openwebui_tool_check()`: A decorator that inspects incoming requests for a specific tool-selection prompt
      from clients like OpenWebUI and returns a valid, empty tool-call response to allow the client to proceed
      gracefully.

#### `api_helpers.py`

* **Responsibility**: Provides helper functions used across the API layer, primarily for handling streaming data.
* **Key Functions**:
    * `build_response_json()`: Constructs a **single streaming JSON chunk**. It acts as a dispatcher, calling the
      appropriate chunk-building method on the `ResponseBuilderService` based on the globally set `API_TYPE`.
    * `extract_text_from_chunk()`: Parses an incoming data chunk from an LLM backend and extracts the text content,
      handling multiple formats (SSE, plain JSON).
    * `sse_format()`: Formats a string into the correct Server-Sent Event (SSE) structure.

### `Middleware/services/`

#### `response_builder_service.py`

* **Responsibility**: To act as the **single source of truth for all API response schemas**. This service centralizes
  the logic for creating JSON payloads, decoupling the response format from the handler and helper logic.
* **Key Components**:
    * `ResponseBuilderService` class:
        * **Non-Streaming Methods**: Contains methods like `build_openai_chat_completion_response()` and
          `build_ollama_generate_response()` that accept the final generated text and return a complete,
          schema-compliant dictionary. These are called directly by the API handlers.
        * **Streaming Chunk Methods**: Contains methods like `build_openai_chat_completion_chunk()` and
          `build_ollama_chat_chunk()` that create a single, schema-compliant JSON chunk for a streaming response. These
          are called by `api_helpers.build_response_json()`.

### `Middleware/api/handlers/`

#### `base/base_api_handler.py`

* **Responsibility**: Defines the abstract interface (`BaseApiHandler`) that all API handlers must implement.
* **Key Components**:
    * `@abstractmethod register_routes()`: The contract method. Every concrete handler must implement this to register
      its URL rules with the Flask app.

#### `impl/openai_api_handler.py`

* **Responsibility**: Implements all endpoints that conform to the OpenAI API specification.
* **Key `MethodView` Classes**:
    * `ModelsAPI`: Handles `/v1/models`.
    * `CompletionsAPI`: Handles the legacy `/v1/completions`.
    * `ChatCompletionsAPI`: Handles the standard `/v1/chat/completions`.
* **Interactions**: Uses `workflow_gateway.handle_user_prompt()` to process requests. For non-streaming responses, it
  calls methods on the `ResponseBuilderService` directly to format the final JSON object.

#### `impl/ollama_api_handler.py`

* **Responsibility**: Implements all endpoints that conform to the Ollama API specification.
* **Key `MethodView` Classes**:
    * `GenerateAPI`: Handles `/api/generate`.
    * `ApiChatAPI`: Handles `/api/chat`.
    * `TagsAPI`: Handles `/api/tags`.
    * `VersionAPI`: Handles `/api/version`.
* **Interactions**: Uses `workflow_gateway.handle_user_prompt()` to process requests. For non-streaming responses, it
  calls methods on the `ResponseBuilderService` directly to format the final JSON object.

-----

## 4\. How to Extend

The architecture makes it easy to add new functionality. The `ApiServer` automatically discovers new handlers, so in
most cases, you only need to add new files without modifying existing ones.

### Example 1: Add a New API Endpoint

This example adds a new non-streaming endpoint `/my_custom_endpoint` that accepts a simple JSON object like
`{"text": "Hello"}` and returns a custom JSON response.

1. **Update the Response Builder**: First, teach the system how to build your new response format.

    * Open `Middleware/services/response_builder_service.py`.
    * Add a new method to the `ResponseBuilderService` class for your final, non-streaming response.

   <!-- end list -->

   ```python
   # In Middleware/services/response_builder_service.py
   class ResponseBuilderService:
       # ... other methods
       def build_my_custom_api_response(self, full_text: str) -> Dict[str, Any]:
           """Builds the final, non-streaming response for MyCustomAPI."""
           return {
               "id": f"custom-{int(time.time())}",
               "reply": full_text,
               "model": self._get_model_name(),
               "timestamp": datetime.utcnow().isoformat() + 'Z'
           }
   ```

2. **Create the Handler File**:

    * Create a new file in `Middleware/api/handlers/impl/`, named `my_custom_api_handler.py`.
    * Add the following code. It defines the endpoint logic, calls the workflow, and then uses the new response builder
      method to format the output.

   <!-- end list -->

   ```python
   # In Middleware/api/handlers/impl/my_custom_api_handler.py
   from flask import request, jsonify, Response
   from flask.views import MethodView

   from Middleware.api.app import app
   from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
   from Middleware.api.workflow_gateway import handle_user_prompt
   from Middleware.common import instance_global_variables
   from Middleware.services.response_builder_service import ResponseBuilderService

   # Instantiate the service
   response_builder = ResponseBuilderService()

   # Define the endpoint's logic
   class MyCustomAPI(MethodView):
       @staticmethod
       def post() -> Response:
           instance_global_variables.API_TYPE = "mycustomapi"
           data = request.get_json()

           if "text" not in data:
               return jsonify({"error": "The 'text' field is required."}), 400

           # Transform request into standard internal format
           messages = [{"role": "user", "content": data["text"]}]
           
           # Handoff to engine for processing (non-streaming)
           llm_response_text = handle_user_prompt(messages, stream=False)

           # Use the ResponseBuilderService to construct the final payload
           response_payload = response_builder.build_my_custom_api_response(llm_response_text)
           
           return jsonify(response_payload)

   # Define the handler and register its routes
   class MyCustomApiHandler(BaseApiHandler):
       def register_routes(self, app_instance: app):
           app_instance.add_url_rule(
               '/my_custom_endpoint',
               view_func=MyCustomAPI.as_view('my_custom_api')
           )
   ```

The `ApiServer` will automatically discover and register this new handler on the next application start.

### Example 2: Add Support for a New API Type (e.g., Anthropic)

This more advanced example shows how to add compatibility for an entirely new API schema, supporting both streaming and
non-streaming.

1. **Update `ResponseBuilderService`**: Add methods to build both the final response and the streaming chunks for the
   new API type.

    * Open `Middleware/services/response_builder_service.py`.
    * Add the new methods to the `ResponseBuilderService` class.

   <!-- end list -->

   ```python
   # In Middleware/services/response_builder_service.py
   class ResponseBuilderService:
       # ... other methods

       # For Anthropic Non-Streaming
       def build_anthropic_response(self, full_text: str) -> Dict[str, Any]:
           # Logic to build the final Anthropic JSON object
           return {"id": "msg_123", "type": "message", "content": [{"type": "text", "text": full_text}]}

       # For Anthropic Streaming
       def build_anthropic_chunk(self, token: str, finish_reason: Optional[str]) -> Dict[str, Any]:
           # Logic to build an Anthropic-compliant streaming chunk
           event_type = "content_block_stop" if finish_reason else "content_block_delta"
           return {"type": event_type, "index": 0, "delta": {"type": "text_delta", "text": token}}
   ```

2. **Update `api_helpers` for Streaming**: Wire the new streaming chunk builder into the streaming dispatcher.

    * Open `Middleware/api/api_helpers.py`.
    * Add an `elif` block to `build_response_json` for the new API type.

   <!-- end list -->

   ```python
   # In Middleware/api/api_helpers.py
   def build_response_json(...):
       # ...
       elif api_type == "openaichatcompletion":
           response = response_builder.build_openai_chat_completion_chunk(token, finish_reason)
       # --- ADD NEW CASE ---
       elif api_type == "anthropicchat":
           response = response_builder.build_anthropic_chunk(token, finish_reason)
       else:
           raise ValueError(f"Unsupported API type for streaming: {api_type}")
       # ...
   ```

3. **Create the New Handler File**: Create the file that will define the endpoints and translation logic for the new
   API.

    * Create `Middleware/api/handlers/impl/anthropic_api_handler.py`.
    * Implement the full logic. This includes parsing the incoming request, setting the `API_TYPE`, calling the gateway,
      and using the correct response builder methods for both streaming and non-streaming cases.

   <!-- end list -->

   ```python
   # In Middleware/api/handlers/impl/anthropic_api_handler.py
   from flask import request, jsonify, Response
   from flask.views import MethodView
   from Middleware.api.app import app
   from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
   from Middleware.api.workflow_gateway import handle_user_prompt
   from Middleware.common import instance_global_variables
   from Middleware.services.response_builder_service import ResponseBuilderService

   response_builder = ResponseBuilderService()

   class AnthropicChatAPI(MethodView):
       @staticmethod
       def post() -> Response:
           # 1. Set the API type so downstream services know the format
           instance_global_variables.API_TYPE = "anthropicchat"
           data = request.get_json()
           
           # 2. Transform the Anthropic request into our internal format
           # (This is a simplified example)
           messages = [{"role": m["role"], "content": m["content"][0]["text"]} for m in data.get("messages", [])]
           
           stream = data.get("stream", True)

           # 3. Handoff to the workflow engine
           llm_response = handle_user_prompt(messages, stream=stream)

           if stream:
               # For streaming, the generator from the engine is returned directly.
               # The api_helpers will use our new "anthropicchat" chunk builder.
               return Response(llm_response, mimetype='text/event-stream')
           else:
               # For non-streaming, directly call our new response builder method.
               response_payload = response_builder.build_anthropic_response(llm_response)
               return jsonify(response_payload)

   class AnthropicApiHandler(BaseApiHandler):
       def register_routes(self, app_instance: app):
           app_instance.add_url_rule(
               '/v1/anthropic/messages', 
               view_func=AnthropicChatAPI.as_view('anthropic_chat_api')
           )
   ```