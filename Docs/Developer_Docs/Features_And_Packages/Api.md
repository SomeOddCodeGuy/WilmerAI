-----

### **Developer Guide: `Middleware/api/`**

## 1\. Overview

This directory contains the primary entry point for the WilmerAI application: a Flask web server that exposes all public-facing API endpoints. Its fundamental role is to act as a robust **compatibility and translation layer**. It accepts requests conforming to popular external schemas (like OpenAI and Ollama), transforms the data into a standardized internal format, and dispatches the request to the central workflow engine for processing.

The architecture is designed to be modular and extensible. The API logic is broken down into an orchestrator (`ApiServer`), a business logic gateway (`workflow_gateway`), and a series of self-contained **handlers** for specific API schemas. A key component of this architecture is the `ResponseBuilderService`, which centralizes all logic for constructing API-specific JSON responses, ensuring that outgoing data matches the schema expected by the client.

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
   immediately performs three key setup actions:

    * It generates a unique **`request_id`** and stores it in Flask's `g` context object. This ID is used throughout the
      stack to enable request cancellation.
    * It sets the request-scoped `API_TYPE` via `set_api_type()` (e.g., `set_api_type("openaichatcompletion")`) so
      downstream components know which response format to use.
    * It extracts the **API key** from the `Authorization: Bearer` header via `api_helpers.extract_api_key()`. This key (or `None`)
      is passed through the call chain to enable per-user encryption and directory isolation. See `Encryption.md` for
      details.

4. **Pre-Processing & Validation**: The method validates the incoming JSON payload, sets the request-scoped
   user context from the model field, and optionally intercepts OpenWebUI tool-selection requests (when
   `interceptOpenWebUIToolRequests` is enabled in the user's config).

5. **Data Transformation**: The endpoint's logic transforms the client-specific payload into a standardized
   internal `messages` list. This includes parsing different structures, extracting images into a per-message `"images"`
   key (from Ollama's `images` array or OpenAI's multimodal content parts), and applying configuration-based
   transformations. The internal format uses `{"role": "user", "content": "text", "images": ["base64data"]}` to
   maintain the association between images and their originating message.

6. **Engine Handoff**: The **`request_id`**, transformed `messages` list, a boolean `stream` flag, and the optional
   **`api_key`** are passed to the `handle_user_prompt()` function in `workflow_gateway.py`. This is the critical
   handoff point where control is passed to the internal workflow engine.

7. **Response Handling**: The handler waits for a result from the workflow engine. The handling depends on the `stream`
   flag:

    * **Streaming**: If `stream` is true, `handle_user_prompt()` returns a Python generator. The handler immediately
      returns a Flask `Response` object with the appropriate `mimetype` (e.g., `'text/event-stream'`). The handler is
      specifically designed to work with production WSGI servers like `Eventlet` to detect client disconnects and
      trigger cancellation. Deep within the streaming logic, `api_helpers.build_response_json()` is called for each
      token, which in turn uses the `ResponseBuilderService` to construct a well formatted JSON chunk string for
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
        * `_discover_and_register_handlers()`: Automatically scans the `Middleware/api/handlers/` directory tree for
          Python files. It imports them, finds any classes that inherit from `BaseApiHandler`, and calls
          their `register_routes()` method, making the system plug-and-play.
        * `run()`: Starts the Flask development server (for debugging only).

#### `workflow_gateway.py`

* **Responsibility**: Acts as the single, standardized bridge between the API request handlers and the backend workflow
  engine.
* **Key Components**:
    * `handle_user_prompt()`: The crucial function that every data-handling endpoint calls. It takes the `request_id`,
      the standardized `messages` list, and a `stream` flag, and dispatches the request to the correct backend service.
    * `check_openwebui_tool_request()`: Called inline by the chat-style handlers (after user context is set) to
      optionally intercept OpenWebUI tool-selection requests. Only active when the current user's
      `interceptOpenWebUIToolRequests` config is `true`. When disabled (the default), tool-selection requests
      pass through to the normal workflow pipeline.

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

## 4\. Workflow Selection via Model Field and Multi-User Support

WilmerAI allows front-end applications to select specific workflows by using the model field in API requests. This
feature enables users to switch between different workflows without changing their configuration. It also supports
running multiple users from a single Wilmer instance.

### How It Works

1. **Models List Endpoints**: The `/v1/models` (OpenAI) and `/api/tags` (Ollama) endpoints return a list of available
   models. In single-user mode, this lists workflows from `_shared/` in `username:workflow` format. In multi-user mode,
   it aggregates models from all configured users.

2. **Request Processing**: When a request includes a model field, the API handler:
    * Calls `api_helpers.set_request_context_from_model()` to parse user and workflow from the model field
    * In multi-user mode, if the model matches a configured username, the request-scoped user is set
    * If a workflow is also specified, the workflow override is set
    * The workflow gateway uses the request-scoped user's config for all downstream operations

3. **Response Format**: Responses include the model in `username:workflow` format when a workflow override is active,
   allowing front-ends to maintain the selected workflow across requests.

### Multi-User Mode

A single Wilmer instance can serve multiple users by specifying `--User` multiple times at startup:

```bash
bash run_macos.sh --User user-one --User user-two --User user-three
```

When multiple users are configured:

* `instance_global_variables.USERS` is set to the list of all configured usernames
* The models endpoint aggregates models from all users
* The model field determines which user's config to use per request
* Per-user `port` config settings are ignored; the port must be specified via `--port` (defaults to `5050`)
* The concurrency gate serializes all requests regardless of user, protecting shared hardware
* Log output is isolated per user into separate files (see Logging section below)

Per-request user resolution uses `get_request_user()` / `set_request_user()` stored in `_request_context`
(thread-local / greenlet-local), following the same pattern as `workflow_override` and `api_type`.

The `get_current_username()` function checks in order:
1. Request-scoped user (set from the model field)
2. `USERS` has exactly one entry -- return `USERS[0]` (single-user mode)
3. `USERS` has multiple entries but no request user -- **raises RuntimeError** (prevents silent cross-user data leaks)
4. `USERS` is None -- fall back to `_current-user.json` (legacy, no `--User` arg)

Since all downstream config functions (`get_user_config()`, `get_config_value()`, `get_workflow_path()`, etc.)
chain through `get_current_username()`, they all become request-aware automatically. The RuntimeError in step 3
guarantees that any code path that fails to set a request-scoped user will crash loudly rather than silently
using the wrong user's configuration.

### Model Field Format

The `parse_model_field()` function in `api_helpers.py` returns a `(user, workflow)` tuple. Its behavior depends
on whether multi-user mode is active:

**Single-user mode** (USERS is None or has one entry):

| Format | Example | Result |
|--------|---------|--------|
| `username:workflow` | `chris:openwebui-coding` | `(None, "openwebui-coding")` |
| `workflow` | `openwebui-coding` | `(None, "openwebui-coding")` if in `_shared/` |
| `username:workflow:latest` | `chris:openwebui-coding:latest` | Strips `:latest`, same as above |
| Non-matching | `gpt-4` | `(None, None)`, uses normal routing |

**Multi-user mode** (USERS has 2+ entries):

| Format | Example | Result |
|--------|---------|--------|
| `username` | `user-two` | `("user-two", None)` -- routes to user-two's default workflow |
| `username:workflow` | `user-two:coding` | `("user-two", "coding")` -- routes to user-two's shared workflow |
| `workflow` (bare) | `coding` | `(None, None)` -- rejected, user must be specified |
| Non-matching | `gpt-4` | `(None, None)` -- rejected by `require_identified_user()` |

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

1. Client queries `/v1/models` → receives list of models from all configured users
2. Client sends request with `"model": "chris:openwebui-coding"`
3. Handler calls `api_helpers.set_request_context_from_model("chris:openwebui-coding")`
4. In multi-user mode, the request-scoped user is set to `chris`
5. `workflow_gateway.handle_user_prompt()` detects the override
6. Workflow is loaded from `_shared/openwebui-coding/_DefaultWorkflow.json`
7. Response includes `"model": "chris:openwebui-coding"`
8. Handler calls `api_helpers.clear_request_context()` in `finally` block

### Key Files

* `api_helpers.py`: Contains `parse_model_field()`, `set_request_context_from_model()`, `clear_request_context()`
  (plus backward-compatible aliases `set_workflow_override()` and `clear_workflow_override()`)
* `instance_global_variables.py`: Contains `USERS` list, `get_request_user()` / `set_request_user()` /
  `clear_request_user()` for per-request user, and workflow override functions. Note: the legacy `USER`
  global has been removed; all user resolution flows through `USERS` and request-scoped context.
* `config_utils.py`: Contains `get_current_username()` (request-aware with RuntimeError guarantee),
  `get_user_config_for()`, `get_shared_workflows_folder()`, `get_available_shared_workflows()`,
  `workflow_exists_in_shared_folder()`
* `workflow_gateway.py`: Checks for workflow override before normal routing
* `response_builder_service.py`: Aggregates models from all configured users
* `server.py`: Contains `UserInjectionFilter` and `UserRoutingFileHandler` for per-user log isolation

-----

## 5\. Streaming Connection Lifecycle

All streaming responses in WilmerAI (both Ollama and OpenAI handlers) explicitly set the `Connection: close` HTTP
header. This forces the TCP connection to be torn down after each streaming response completes, rather than being
kept alive for reuse.

### Why Connection: close

HTTP/1.1 defaults to persistent connections (`Connection: keep-alive`). For typical short-lived request/response
cycles, connection reuse improves performance. However, streaming responses are long-lived and have different
characteristics:

1. **Stale connection pool entries**: After a streaming response finishes, some HTTP clients (particularly Node.js
   `http.Agent`) may attempt to reuse the connection for subsequent requests. If the connection is in an
   inconsistent state after streaming (e.g., the chunked transfer encoding termination was not cleanly processed),
   the client's connection pool entry becomes stale. This blocks future requests on that connection slot.

2. **Front-end lockups**: In practice, this manifests as the front-end application (e.g., SillyTavern) becoming
   unable to send new requests or reconnect to WilmerAI after a streaming response completes. The condition
   persists until the front-end is restarted, which tears down all connections.

3. **Heartbeat interaction**: WilmerAI sends heartbeat messages every 1 second during streaming (empty NDJSON
   lines for Ollama, SSE comments for OpenAI). These keep the connection active during long prefill phases
   for disconnect detection purposes.

Setting `Connection: close` ensures that each streaming response gets a clean TCP lifecycle. The overhead of
re-establishing connections is negligible for LLM streaming responses, which typically last seconds to minutes.

### Stream-Complete Detection

In addition to `Connection: close`, the streaming generators detect when the stream is logically complete and
return immediately, rather than waiting for the entire `handle_user_prompt()` generator chain to finish.

This is necessary because of how workflow processing works. When a workflow has multiple nodes, the responding
node (which produces the stream) may not be the last node. After the stream finishes (the `done:true` chunk for
Ollama, or the `[DONE]` sentinel for OpenAI), the workflow processor continues executing remaining non-responding
nodes (memory summarization, categorization, etc.) within the same generator. During this post-stream processing,
the Eventlet heartbeat mechanism would send heartbeat messages to the client -- but from the client's perspective,
the stream is already complete.

The fix: each streaming generator checks whether the chunk it just yielded contains the stream-complete marker:

- **Ollama**: checks for `"done": true` or `"done":true` in the encoded bytes
- **OpenAI**: checks for `[DONE]` in the encoded bytes

When detected, the generator returns immediately. The `finally` block fires the stop signal and schedules
asynchronous cleanup of the backend reader greenlet.

### Heartbeat Format

Heartbeats differ between API formats:

- **Ollama (`application/x-ndjson`)**: A full JSON object matching the Ollama response schema with `"done":false`
  and an empty `"message"` content. This ensures compatibility with clients like Open WebUI that require valid
  JSON on every line of the NDJSON stream.
- **OpenAI (`text/event-stream`)**: An SSE comment (`:\n\n`). SSE clients ignore comment lines by design.

Both formats cause a TCP write, which is sufficient for disconnect detection -- if the client has closed the
connection, the write will fail and trigger cancellation.

### Non-Blocking Greenlet Cleanup

When the Eventlet streaming generator returns (after stream-complete detection or natural exhaustion), its
`finally` block must clean up the background reader greenlet. This cleanup uses `eventlet.spawn(reader_greenlet.kill)`
rather than a direct `reader_greenlet.kill()` call.

The reason: `kill()` is a blocking call that sends `GreenletExit` to the reader and waits for it to terminate.
If the reader is inside `handle_user_prompt()` doing post-stream workflow processing (non-responding nodes,
lock releases, etc.), this wait can take seconds. During that wait, the generator's `finally` block is blocked,
which prevents the Eventlet WSGI server from finalizing the HTTP response (sending the chunked transfer encoding
terminator and closing the TCP connection). From the client's perspective, the response data has arrived but the
HTTP transaction has not completed -- this can corrupt the client's HTTP connection state.

By spawning the kill into a separate greenlet, the `finally` block returns immediately, allowing the WSGI server
to finalize and close the response. The reader greenlet is cleaned up asynchronously in the background.

### Implementation Details

Both `Connection: close` and stream-complete detection are implemented in the Eventlet-optimized and fallback
streaming functions in each handler:

- `ollama_api_handler.py`: `_stream_with_eventlet_optimized()` and `_stream_response_fallback()`
- `openai_api_handler.py`: `_stream_with_eventlet_optimized()` and `_stream_response_fallback()`

Note that `Connection` is technically a hop-by-hop header under WSGI/PEP 3333 and should not normally be set by
WSGI applications. However, setting it to `close` is the safer pragmatic choice for streaming responses, as it
prevents the class of client-side connection pool issues described above. Eventlet's WSGI server respects this
header and will close the socket after the response is fully sent.

### Server-Level Keep-Alive Disable

In addition to the per-response `Connection: close` header set by Flask, the Eventlet WSGI server itself is
configured with `keepalive=False` in `run_eventlet.py`. This forces the server to set `close_connection = 1`
on every request handler instance at the WSGI protocol level, which is more authoritative than a Flask response
header. This prevents any scenario where the response-level header might be stripped or ignored by intermediary
layers.

A `socket_timeout=60` is also set as a safety net. This times out idle client sockets after 60 seconds,
preventing zombie connections from accumulating if a client fails to close its end of the connection.

-----

## 6\. How to Extend

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
           instance_global_variables.set_api_type("anthropicchat")
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

-----

## 7\. Concurrency Limiting (WSGI Middleware)

WilmerAI includes an optional concurrency-limiting layer that restricts how many requests can be in-flight at the
same time. This is implemented as a WSGI middleware rather than using Flask-level hooks, for reasons explained below.

### Why WSGI Middleware Instead of Flask Hooks

Flask provides `before_request` and `teardown_request` hooks that initially seem like a natural place to
acquire and release a semaphore. The problem is timing: Flask's `teardown_request` fires when the request context
tears down, which happens **before** the WSGI server has consumed the response iterator. For non-streaming
responses this distinction is negligible, but for streaming responses (where the response body is a generator that
yields chunks over seconds or minutes), it means the semaphore would be released long before the stream is
actually consumed. A second request could then acquire the semaphore and begin processing while the first is still
actively streaming, defeating the purpose of serialization.

By wrapping `app.wsgi_app` at the WSGI level, the middleware controls the full response lifecycle: from the moment
the request arrives until the last byte of the response iterator has been consumed (or the iterator is closed).
This guarantees that a streaming response holds the semaphore for its entire duration.

### Semaphore Type

The semaphore is a `threading.BoundedSemaphore`, created once at startup by
`instance_global_variables.initialize_request_semaphore(n)`. `BoundedSemaphore` is used instead of a plain
`Semaphore` because it raises `ValueError` if `release()` is called more times than `acquire()`. This converts
what would otherwise be a silent over-release bug (gradually inflating the concurrency count) into an immediate,
loud failure.

Under Eventlet, the standard `threading` module is monkey-patched so that `threading.BoundedSemaphore` is
replaced with the Eventlet-native greenlet-aware equivalent. No special import or conditional logic is needed;
the monkey-patching makes it transparent.

### `_SemaphoreReleasingIterator`

This is the core mechanism for ensuring the semaphore is released at the right time. It wraps the WSGI response
iterable returned by the inner application and releases the semaphore exactly once when the response is done.

Key design points:

* **Boolean guard (`_released`)**: Prevents double-release. Multiple code paths can trigger release (iterator
  exhaustion, `close()` called by the WSGI server, an exception during iteration), and all of them funnel through
  `_release()`, which checks the flag before calling `semaphore.release()`.

* **`__next__` catches `BaseException`, not `Exception`**: This is intentional. `StopIteration` (signaling
  iterator exhaustion) is a subclass of `BaseException` but not `Exception`. Similarly, `GeneratorExit` and
  `KeyboardInterrupt` bypass `Exception`. Catching `BaseException` ensures the semaphore is released under all
  termination conditions, not just well-behaved ones.

* **`close()` delegates to the underlying iterable**: Per PEP 3333, WSGI servers must call `close()` on the
  response iterable if it exists. The releasing iterator calls `_release()` and then forwards the `close()` call
  to the wrapped iterable, allowing it to perform its own cleanup (e.g., closing file handles or greenlets).

### `ConcurrencyLimitMiddleware.__call__`

The `__call__` method implements the WSGI interface and follows this sequence:

1. **Method check**: Calls `_requires_concurrency_limit(environ)` to check `REQUEST_METHOD`. Only `POST`
   requests are subject to the semaphore. Non-POST requests (GET for model lists/version, DELETE for
   cancellation) are passed directly to the inner app without acquiring. This prevents lightweight metadata
   endpoints from being blocked behind long-running LLM calls.

2. **Acquire with timeout**: For POST requests, calls `semaphore.acquire(timeout=self._acquire_timeout)`. If the
   semaphore cannot be acquired within the timeout window, the request is rejected immediately.

3. **503 on timeout**: When acquire fails, the middleware calls `start_response("503 Service Unavailable", ...)`
   and returns a pre-encoded JSON body with an error message. The semaphore is never held in this path, so there
   is nothing to release.

4. **Call the inner app**: If acquired, the middleware calls `self._app(environ, start_response)` to get the
   response iterable from Flask.

5. **Exception handling**: If the inner app raises during the call (before returning a response), the middleware
   releases the semaphore immediately and re-raises the exception. This prevents a leaked semaphore slot from
   permanently reducing capacity.

6. **Wrap the response**: On success, the response iterable is wrapped in `_SemaphoreReleasingIterator`, which
   takes ownership of releasing the semaphore when the response is fully consumed.

### Application Point

The middleware is conditionally applied in `ApiServer.__init__` via the `_apply_concurrency_middleware()` method.
This method imports `get_request_semaphore()` from `instance_global_variables` and checks whether it returns a
non-None value. If concurrency limiting is disabled (semaphore count is 0 or not configured), the middleware is
not applied at all and there is zero overhead on request processing.

When applied, the middleware wraps `self.app.wsgi_app`:

```python
self.app.wsgi_app = ConcurrencyLimitMiddleware(
    self.app.wsgi_app, semaphore,
    acquire_timeout=instance_global_variables.CONCURRENCY_TIMEOUT
)
```

This ensures it sits between the WSGI server (Eventlet) and Flask's routing layer, intercepting every request.

### Configuration

* **`--concurrency N`**: Sets the maximum number of concurrent requests. Stored in
  `instance_global_variables.CONCURRENCY_LIMIT`. When `N > 0`, a `BoundedSemaphore(N)` is created at startup.
  When `N` is 0, concurrency limiting is disabled entirely. Defaults to 1 (serialized) because most deployments
  use a single backend LLM that cannot handle parallel requests reliably.

* **`--concurrency-timeout S`**: Sets the maximum number of seconds a request will wait to acquire the semaphore
  before being rejected with a 503. Stored in `instance_global_variables.CONCURRENCY_TIMEOUT`. Defaults to 900
  seconds (15 minutes). This generous default accounts for long-running LLM inference on local hardware.
  Users with slower hardware or very large models may want to increase this further.

### Method-Based Exemptions

The middleware exempts non-POST requests from the semaphore. This works because all LLM-dispatching endpoints
use POST, while metadata endpoints (model lists, version) use GET and cancellation endpoints use DELETE. The
check is done via `_requires_concurrency_limit()`, a static method that reads `REQUEST_METHOD` from the WSGI
environ. This approach avoids maintaining a path allowlist -- if a new POST endpoint is added that does not
call an LLM, it would need to be handled (e.g., by switching to a path-based check or adding it to an
exemption set).

### Key Files

* `Middleware/api/concurrency_middleware.py`: Contains `ConcurrencyLimitMiddleware` and
  `_SemaphoreReleasingIterator`. This is the entire middleware implementation.
* `Middleware/common/instance_global_variables.py`: Stores the `BoundedSemaphore` instance
  (`_request_semaphore`), along with `CONCURRENCY_LIMIT` and `CONCURRENCY_TIMEOUT` configuration values.
  Provides `initialize_request_semaphore(n)` and `get_request_semaphore()`.
* `Middleware/api/api_server.py`: `ApiServer._apply_concurrency_middleware()` conditionally wraps
  `app.wsgi_app` with the middleware during server initialization.
