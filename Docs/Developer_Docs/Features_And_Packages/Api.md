-----

### **Developer Guide: `Middleware/api/`**

## 1\. Overview

This directory contains the primary entry point for the WilmerAI application: a Flask web server that exposes all public-facing API endpoints. Its fundamental role is to act as a robust **compatibility and translation layer**. It accepts requests conforming to popular external schemas (like OpenAI and Ollama), transforms the data into a standardized internal format, and dispatches the request to the central workflow engine for processing.

The architecture is designed to be modular and extensible. The API logic is broken down into an orchestrator (`ApiServer`), a business logic gateway (`workflow_gateway`), and a series of self-contained **handlers** for specific API schemas. A key component of this architecture is the `ResponseBuilderService`, which centralizes all logic for constructing API-specific JSON responses, ensuring that outgoing data perfectly matches the schema expected by the client.

This separation of concerns makes the system cleaner, more maintainable, and significantly easier to extend with new endpoints or entire API compatibility layers.

-----

## 2\. Architectural Flow

A request's journey through the `api` package follows a well-defined sequence. The primary difference in the flow
depends on whether the client requests a streaming or non-streaming response.

1. **Ingestion**: An external client sends an HTTP request to a specific URL (e.g., `/v1/chat/completions`).

2. **Routing**: The Flask application, orchestrated by `ApiServer` at startup, routes the request to the
   appropriate `MethodView` class (e.g., `ChatCompletionsAPI`) located within a registered handler file (
   e.g., `openai_api_handler.py`).

3. **Method Invocation**: The corresponding HTTP method within the class is called (typically `post()`). The method
   immediately performs two key setup actions:

    * It generates a unique **`request_id`** and stores it in Flask's `g` context object. This ID is used throughout the
      stack to enable request cancellation.
    * It sets a global `API_TYPE` variable (e.g., `openaichatcompletion`) so downstream components know which response
      format to use.

4. **Pre-Processing & Validation**: The method performs initial actions, such as applying decorators (
   e.g., `@handle_openwebui_tool_check`) and validating the incoming JSON payload.

5. **Data Transformation**: The endpoint's logic transforms the client-specific payload into a standardized
   internal `messages` list. This includes parsing different structures, handling multimedia content like base64 images,
   and applying configuration-based transformations.

6. **Engine Handoff**: The **`request_id`**, transformed `messages` list, and a boolean `stream` flag are passed to
   the `handle_user_prompt()` function in `workflow_gateway.py`. This is the critical handoff point where control is
   passed to the internal workflow engine.

7. **Response Handling**: The handler waits for a result from the workflow engine. The handling depends on the `stream`
   flag:

    * **Streaming**: If `stream` is true, `handle_user_prompt()` returns a Python generator. The handler immediately
      returns a Flask `Response` object with the appropriate `mimetype` (e.g., `'text/event-stream'`). The handler is
      specifically designed to work with production WSGI servers like `Eventlet` to detect client disconnects and
      trigger cancellation. Deep within the streaming logic, `api_helpers.build_response_json()` is called for each
      token, which in turn uses the `ResponseBuilderService` to construct a perfectly formatted JSON chunk string for
      the specific API type.
    * **Non-Streaming**: If `stream` is false, `handle_user_prompt()` returns a single, complete string of text. The
      handler then calls the appropriate method **directly** on the `ResponseBuilderService` (
      e.g., `response_builder.build_openai_chat_completion_response(text)`) to construct the final, complete JSON
      object. This object is then returned to the client using Flask's `jsonify`.

-----

## 3\. Directory & File Breakdown

### `Middleware/api/`

#### `app.py`

* **Responsibility**: Instantiates the global Flask `app` object.
* **Rationale**: By placing the app instance in its own file, other modules can import it without creating circular
  dependencies.

#### `api_server.py`

* **Responsibility**: Discovers all API handlers, registers their routes with the Flask app, and exposes the app for a
  WSGI server to run. It is the main orchestrator for the API layer.
* **Key Components**:
    * `ApiServer` class:
        * `_discover_and_register_handlers()`: Automatically scans the `Middleware/api/handlers/impl/` directory for
          Python files. It imports them, finds any classes that inherit from `BaseApiHandler`, and calls
          their `register_routes()` method, making the system plug-and-play.
        * `run()`: Starts the Flask development server (for debugging only).

#### `workflow_gateway.py`

* **Responsibility**: Acts as the single, standardized bridge between the API request handlers and the backend workflow
  engine.
* **Key Components**:
    * `handle_user_prompt()`: The crucial function that every data-handling endpoint calls. It takes the `request_id`,
      the standardized `messages` list, and a `stream` flag, and dispatches the request to the correct backend service.
    * `@handle_openwebui_tool_check()`: A decorator that inspects incoming requests for a specific tool-selection prompt
      from clients like OpenWebUI and returns a valid, empty tool-call response to allow the client to proceed
      gracefully.

#### `api_helpers.py`

* **Responsibility**: Provides helper functions used across the API layer, primarily for handling streaming data and
  workflow override management.
* **Key Functions**:
    * `build_response_json()`: Constructs a **single streaming JSON chunk**. It acts as a dispatcher, calling the
      appropriate chunk-building method on the `ResponseBuilderService` based on the globally set `API_TYPE`.
    * `extract_text_from_chunk()`: Parses an incoming data chunk from an LLM backend and extracts the text content,
      handling multiple formats (SSE, plain JSON).
    * `sse_format()`: Formats a string into the correct Server-Sent Event (SSE) structure.
    * `get_model_name()`: Returns the model identifier for API responses. When a workflow override is active, returns
      `username:workflow` format; otherwise returns just the username.
    * `parse_model_field()`: Parses the model field from incoming API requests and extracts a workflow name if one is
      specified. Supports formats like `username:workflow`, `workflow`, and `username:workflow:latest`.
    * `set_workflow_override()`: Sets the global workflow override from the model field. Called at the start of request
      processing.
    * `clear_workflow_override()`: Clears the workflow override. Called at the end of request processing.
    * `get_active_workflow_override()`: Returns the currently active workflow override, if any.

### `Middleware/services/`

#### `response_builder_service.py`

* **Responsibility**: To act as the **single source of truth for all API response schemas**. This service centralizes
  the logic for creating JSON payloads, decoupling the response format from the handler and helper logic.
* **Key Components**:
    * `ResponseBuilderService` class:
        * **Non-Streaming Methods**: Contains methods like `build_openai_chat_completion_response()`
          and `build_ollama_generate_response()` that accept the final generated text and return a complete,
          schema-compliant dictionary.
        * **Streaming Chunk Methods**: Contains methods like `build_openai_chat_completion_chunk()`
          and `build_ollama_chat_chunk()` that create a single, schema-compliant JSON chunk for a streaming response.
        * **Models List Methods**: `build_openai_models_response()` and `build_ollama_tags_response()` return lists of
          available workflows from the `_shared` folder. Each workflow is presented in `username:workflow` format,
          allowing front-end applications to select specific workflows via their model dropdown.

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
* **Interactions**: Generates a `request_id` for each call. Uses `workflow_gateway.handle_user_prompt()` to process
  requests. Relies on `eventlet` and client disconnection to trigger the `CancellationService`.

#### `impl/ollama_api_handler.py`

* **Responsibility**: Implements all endpoints that conform to the Ollama API specification, plus extensions for
  cancellation.
* **Key `MethodView` Classes**:
    * `GenerateAPI`: Handles `POST /api/generate`.
    * `ApiChatAPI`: Handles `POST /api/chat`.
    * `TagsAPI`: Handles `/api/tags`.
    * `VersionAPI`: Handles `/api/version`.
    * **`CancelChatAPI` / `CancelGenerateAPI`**: Handle `DELETE` requests to `/api/chat` and `/api/generate`,
      respectively. This is a WilmerAI-specific extension that allows clients to explicitly cancel a running request by
      providing its `request_id`.
* **Interactions**: Generates a `request_id` and includes it in responses to the client.
  Uses `workflow_gateway.handle_user_prompt()` to process requests. Streaming responses include disconnect detection
  that triggers cancellation.

-----

## 4\. Workflow Selection via Model Field

WilmerAI allows front-end applications to select specific workflows by using the model field in API requests. This
feature enables users to switch between different workflows without changing their configuration.

### How It Works

1. **Models List Endpoints**: The `/v1/models` (OpenAI) and `/api/tags` (Ollama) endpoints return a list of available
   workflows from `Public/Configs/Workflows/_shared/`. Each workflow is presented in `username:workflow` format.

2. **Request Processing**: When a request includes a model field containing a workflow name, the API handler:
    * Calls `api_helpers.set_workflow_override()` to parse and store the workflow name
    * The workflow gateway checks for an active override before using normal routing
    * If a valid workflow is found in `_shared/`, it's executed directly

3. **Response Format**: Responses include the model in `username:workflow` format when a workflow override is active,
   allowing front-ends to maintain the selected workflow across requests.

### Model Field Format

The `parse_model_field()` function in `api_helpers.py` handles these formats:

| Format | Example | Result |
|--------|---------|--------|
| `username:workflow` | `chris:openwebui-coding` | Extracts `openwebui-coding` |
| `workflow` | `openwebui-coding` | Uses `openwebui-coding` if it exists in `_shared/` |
| `username:workflow:latest` | `chris:openwebui-coding:latest` | Strips `:latest`, extracts `openwebui-coding` |
| Non-matching | `gpt-4` | Returns `None`, uses normal routing |

### Folder Structure

```
Public/Configs/Workflows/
├── _shared/
│   ├── openwebui-coding/           # Listed by models endpoint as folder name
│   │   └── _DefaultWorkflow.json   # Workflow loaded when folder is selected
│   ├── openwebui-general/
│   │   └── _DefaultWorkflow.json
│   └── openwebui-task/
│       └── _DefaultWorkflow.json
├── chris/                          # Default user folder
│   └── ...
```

### Request Flow with Workflow Override

1. Client queries `/v1/models` → receives list of `username:workflow` entries
2. Client sends request with `"model": "chris:openwebui-coding"`
3. Handler calls `api_helpers.set_workflow_override("chris:openwebui-coding")`
4. `workflow_gateway.handle_user_prompt()` detects the override
5. Workflow is loaded from `_shared/openwebui-coding/_DefaultWorkflow.json`
6. Response includes `"model": "chris:openwebui-coding"`
7. Handler calls `api_helpers.clear_workflow_override()` in `finally` block

### Key Files

* `api_helpers.py`: Contains `parse_model_field()`, `set_workflow_override()`, `clear_workflow_override()`
* `instance_global_variables.py`: Contains `WORKFLOW_OVERRIDE` global variable
* `workflow_gateway.py`: Checks for workflow override before normal routing
* `config_utils.py`: Contains `get_shared_workflows_folder()`, `get_available_shared_workflows()`,
  `workflow_exists_in_shared_folder()`

-----

## 5\. How to Extend

The architecture makes it easy to add new functionality. The `ApiServer` automatically discovers new handlers, so in
most cases, you only need to add new files without modifying existing ones.

### **Example 2: Add Support for a New API Type (e.g., Anthropic)**

This more advanced example shows how to add compatibility for an entirely new API schema, supporting both streaming and
non-streaming.

1. **Update `ResponseBuilderService`**: Add methods to build both the final response and the streaming chunks for the
   new API type.

2. **Update `api_helpers` for Streaming**: Wire the new streaming chunk builder into the streaming dispatcher
   in `build_response_json`.

3. **Create the New Handler File**: Create the file that will define the endpoints and translation logic for the new
   API.

    * Create `Middleware/api/handlers/impl/anthropic_api_handler.py`.
    * Implement the full logic. This includes generating a `request_id`, parsing the incoming request, setting
      the `API_TYPE`, calling the gateway, and using the correct response builder methods for both streaming and
      non-streaming cases.

   <!-- end list -->

   ```python
   # In Middleware/api/handlers/impl/anthropic_api_handler.py
   import uuid
   from flask import request, jsonify, Response, g
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
           # 1. Generate request ID for cancellation tracking
           request_id = str(uuid.uuid4())
           g.current_request_id = request_id

           # 2. Set the API type so downstream services know the format
           instance_global_variables.API_TYPE = "anthropicchat"
           data = request.get_json()
           
           # 3. Transform the Anthropic request into our internal format
           messages = [{"role": m["role"], "content": m["content"][0]["text"]} for m in data.get("messages", [])]
           
           stream = data.get("stream", True)

           # 4. Handoff to the workflow engine
           llm_response = handle_user_prompt(request_id, messages, stream=stream)

           if stream:
               return Response(llm_response, mimetype='text/event-stream')
           else:
               response_payload = response_builder.build_anthropic_response(llm_response)
               return jsonify(response_payload)

   class AnthropicApiHandler(BaseApiHandler):
       def register_routes(self, app_instance: app):
           app_instance.add_url_rule(
               '/v1/anthropic/messages', 
               view_func=AnthropicChatAPI.as_view('anthropic_chat_api')
           )
   ```