# `Middleware/api/` – Developer Documentation

## 1\. Overview

This directory houses the primary entry point for the entire WilmerAI application. It contains the Flask web server responsible for exposing all public-facing API endpoints. Its fundamental role is to act as a robust **compatibility and translation layer**. It accepts requests from various clients that conform to popular schemas (like OpenAI and Ollama), parses them, transforms the data into a standardized internal format, and then dispatches the request to the central workflow engine for processing. It is, in essence, the "front door" to WilmerAI.

The architecture is designed to be modular and extensible. Instead of a single monolithic file, the API logic is broken down into an orchestrator (`$ApiServer$`), a business logic gateway (`$workflow_gateway$`), and a series of self-contained **handlers**. Each handler is responsible for a specific set of related API endpoints (e.g., all Ollama-compatible routes). This separation of concerns makes the system cleaner, more maintainable, and significantly easier to extend.

## 2\. Architectural Flow

A request's journey through the `$api$` package follows a well-defined sequence. Understanding this flow is key to understanding how WilmerAI interacts with the outside world.

1.  **Ingestion**: An external client sends an HTTP request to a specific URL, for example, `/v1/chat/completions`.
2.  **Routing**: The Flask application, orchestrated by the ` $ApiServer$ at startup, routes the request to the appropriate  `$MethodView$`class (e.g.,`$ChatCompletionsAPI$` ) located within one of the registered handler files (e.g.,  `$openai\_api\_handler.py$\`).
3.  **Method Invocation**: The corresponding HTTP method within the class is called (typically `$post()$`).
4.  **Pre-Processing & Validation**: The method performs initial actions, such as:
      * Applying decorators like `@handle_openwebui_tool_check()` (from `$workflow_gateway$`) to gracefully handle special client behaviors without failing.
      * Parsing the incoming JSON payload using `request.get_json()`.
      * Validating that required fields like `$messages$` exist.
5.  **Data Transformation**: The endpoint's logic transforms the client-specific payload into a standardized internal format. This can include:
      * Extracting a list of messages.
      * Processing multimedia content, like a list of base64-encoded images from an Ollama-style request.
      * Converting a legacy flat `$prompt$` string into a structured message list using `$parse_conversation()$`.
      * Applying configuration-based transformations, like prepending `User:` and `Assistant:` prefixes to message content.
6.  **Engine Handoff**: The transformed message list, along with a boolean `$stream$` flag, is passed to the `$handle_user_prompt()` function in `$workflow_gateway.py$`. This is the critical handoff point where control is passed from the API layer to the internal workflow engine (either the `$PromptCategorizer$` or `$WorkflowManager$`).
7.  **Response Handling**: The method waits for a result from the workflow engine. The handling depends on the `$stream$` flag:
      * **Streaming**: If `$stream$` is true, it receives a generator. The endpoint immediately returns a Flask `$Response` object with the `mimetype='text/event-stream'`, which streams the generated data chunks back to the client.
      * **Non-Streaming**: If `$stream$` is false, it receives a single, complete string. The endpoint then formats this string into the specific JSON response structure that the original client expects (e.g., an OpenAI `$chat.completion$` object or an Ollama `$api/chat$` response object) and returns it as a JSON response.

## 3\. Directory & File Breakdown

### `$Middleware/api/`

#### `$app.py$`

  * **Responsibility:** To instantiate the global Flask `$app$` object.
  * **Key Components:**
      * `$app = Flask(__name__)$`: The single instance of the Flask application.
  * **Rationale:** By placing the app instance in its own file, other modules (like the server and the handlers) can import it without creating circular dependencies.

#### `$api_server.py$`

  * **Responsibility:** To discover all API handlers, register their routes with the Flask app, and run the web server. This is the main orchestrator for the API layer.
  * **Key Components:**
      * `$ApiServer$` class:
          * `$_discover_and_register_handlers()`: This method automatically scans the `$Middleware/api/handlers/impl/` directory for Python files. It imports them, finds any classes that inherit from `$BaseApiHandler$`, and calls their `$register_routes()` method. This makes the system plug-and-play.
          * `$run(debug: bool)$`: This method starts the Flask server. It is the primary entry point for the API, called from the root `$server.py$`.

#### `$workflow_gateway.py$`

  * **Responsibility:** To act as the single, standardized bridge between the API request handlers and the backend workflow engine. It isolates the business logic of "what to do with a prompt" from the web layer.
  * **Key Components:**
      * `$handle_user_prompt(...)`: This is the crucial function that every data-handling endpoint calls after parsing its request. It takes the standardized message list and dispatches it to the correct backend service (`$PromptCategorizationService$` or `$WorkflowManager$`).
      * `@handle_openwebui_tool_check()`: A decorator applied to chat endpoints. It inspects incoming requests for a specific system prompt used by OpenWebUI for tool selection and returns a valid, empty response to allow the client to proceed gracefully.
      * `$_sanitize_log_data()`: A helper function for truncating potentially large data (like base64 images) before logging.

#### `$api_helpers.py$`

  * **Responsibility:** To provide helper functions used exclusively by the API layer (handlers and gateway).
  * **Key Functions:**
      * `$build_response_json()`: Constructs a complete, non-streaming JSON response payload that matches the schema expected by the original client.
      * `$extract_text_from_chunk()`: Parses an incoming data chunk from an LLM backend and extracts the text content.
      * `$sse_format()`: Formats a string into the correct Server-Sent Event (SSE) structure.
  * **Interactions:** Called by handlers to format responses and by the workflow engine's streaming utilities.

### `$Middleware/api/handlers/`

This directory contains all the logic for the specific API endpoints. It is structured to separate the abstract base class from concrete implementations.

#### `$base/base_api_handler.py$`

  * **Responsibility:** To define the abstract interface that all API handlers must implement.
  * **Key Components:**
      * `$BaseApiHandler(ABC)$`: An abstract base class.
      * `@abstractmethod register_routes()`: The contract method. Every concrete handler must implement this to register its URL rules with the Flask app.

#### `$impl/openai_api_handler.py$`

  * **Responsibility:** To implement all endpoints that conform to the OpenAI API specification.
  * **Key Components (`MethodView` Classes):**
      * `$ModelsAPI$`: Handles `/v1/models`.
      * `$CompletionsAPI$`: Handles the legacy `/v1/completions`.
      * `$ChatCompletionsAPI$`: Handles the standard `/v1/chat/completions`.
  * **Interactions:** Uses `$workflow_gateway.handle_user_prompt()` to process requests and `$api_helpers` to format responses.

#### `$impl/ollama_api_handler.py$`

  * **Responsibility:** To implement all endpoints that conform to the Ollama API specification.
  * **Key Components (`MethodView` Classes):**
      * `$GenerateAPI$`: Handles `/api/generate`.
      * `$ApiChatAPI$`: Handles `/api/chat`.
      * `$TagsAPI$`: Handles `/api/tags`.
      * `$VersionAPI$`: Handles `/api/version`.
  * **Interactions:** Uses `$workflow_gateway.handle_user_prompt()` to process requests and `$api_helpers` to format responses.

## 4\. How to Extend

Thanks to the new architecture, adding a new set of API endpoints is a clean and isolated process. You simply create a new handler file; **no existing files need to be modified.**

### How to Add a New API Endpoint

1.  **Create a Handler File**: Create a new file in `$Middleware/api/handlers/impl/`, for example, `my_custom_api_handler.py`.

2.  **Define Endpoint Logic**: In your new file, create a class that inherits from `flask.views.MethodView` for each endpoint you want to add. Implement the method for the HTTP verb (e.g., `$post()`).

3.  **Define the Handler Class**: In the same file, create a main handler class that inherits from `$BaseApiHandler`.

4.  **Register Routes**: Implement the `$register_routes()` method in your handler class. This method should contain all the `app.add_url_rule()` calls to link URL paths to your `MethodView` classes.

The `$ApiServer$` will automatically discover and register your new handler when the application starts.

**Example**: Adding a `/my_custom_endpoint` in a new file.

```python
# In Middleware/api/handlers/impl/my_custom_api_handler.py

import time
from flask import request, jsonify, Response
from flask.views import MethodView

# Import the necessary components
from Middleware.api.app import app
from Middleware.api.handlers.base_api_handler import BaseApiHandler
from Middleware.api.workflow_gateway import handle_user_prompt
from Middleware.api import api_helpers
from Middleware.common import instance_global_variables

# Step 2: Define the endpoint's logic
class MyCustomAPI(MethodView):
    @staticmethod
    def post() -> Response:
        instance_global_variables.API_TYPE = "mycustomapi"
        data = request.get_json()

        if "text" not in data:
            return jsonify({"error": "The 'text' field is required."}), 400

        messages = [{"role": "user", "content": data["text"]}]
        llm_response_text = handle_user_prompt(messages, stream=False)

        response_payload = {
            "id": f"custom-{int(time.time())}",
            "reply": llm_response_text,
            "model": api_helpers.get_model_name()
        }
        return jsonify(response_payload)

# Step 3 & 4: Define the handler and register its routes
class MyCustomApiHandler(BaseApiHandler):
    def register_routes(self, app_instance: app):
        app_instance.add_url_rule(
            '/my_custom_endpoint',
            view_func=MyCustomAPI.as_view('my_custom_api')
        )
```