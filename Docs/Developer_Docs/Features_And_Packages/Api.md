-----

### **Developer Guide: `Middleware/api/`**

## 1\. Overview

This directory contains the primary entry point for the WilmerAI application: a Flask web server that exposes all public-facing API endpoints. Its fundamental role is to act as a **compatibility and translation layer**. It accepts requests conforming to popular external schemas (like OpenAI and Ollama), transforms the data into a standardized internal format, and dispatches the request to the central workflow engine for processing.

The architecture is designed to be modular and extensible. The API logic is broken down into an orchestrator (`ApiServer`), a business logic gateway (`workflow_gateway`), and a series of self-contained **handlers** for specific API schemas. A key component of this architecture is the `ResponseBuilderService`, which centralizes all logic for constructing API-specific JSON responses, ensuring that outgoing data matches the schema expected by the client.

This separation of concerns makes the system easier to maintain and to extend with new endpoints or entire API compatibility layers.

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
          their `register_routes()` method, making the system plug-and-play. The class exposes the Flask
          `app` for a WSGI server; port resolution and server startup live in the entry-point scripts
          (`server.py`, `run_eventlet.py`, `run_waitress.py`), not on `ApiServer` itself.

#### `workflow_gateway.py`

* **Responsibility**: Acts as the single, standardized bridge between the API request handlers and the backend workflow
  engine.
* **Key Components**:
    * `handle_user_prompt()`: The function that every data-handling endpoint calls. It takes the `request_id`,
      the standardized `messages` list, and a `stream` flag, and dispatches the request to the correct backend service.
      Before any routing, **and only when the current user's config has `livenessToolCall` set**
      (`config_utils.get_liveness_tool_call()` returns non-None), it passes the conversation through
      `strip_machinery_turns()` and then `collapse_duplicate_tool_calls()`. Users without `livenessToolCall`
      never have their conversations rewritten.
    * `strip_machinery_turns()`: Removes buried machinery no-op turns from the ingested conversation before anything
      else sees them. Machinery-injected turns (such as the liveness guard's synthetic tool call, see
      `Wilmer_Prompt_Flow_Beginning_To_End.md`) must be **one-shot**: the model sees the injection exactly once (as
      the conversation's trailing exchange on the request immediately following the injection, where it serves as
      corrective feedback that the previous reply lacked a tool call), and it is stripped from every conversation in
      which it sits buried, so a small model can never adopt it as a repeatable pattern. The trailing exchange is the
      final assistant tool-call turn plus its following `role: "tool"` results (trailing assistant filler does not
      bury it: either the empty filler appended by `add_missing_assistant` handling or the bare `"Assistant:"`
      content used when `chatCompleteAddUserAssistant` is enabled). A tool call is identified as machinery when its
      `id` starts with `wilmer_liveness_` (a genuine injection), when its arguments contain the `[Wilmer]` marker
      substring (which also catches model-emitted imitations of an earlier injection), or when its name and
      arguments exactly equal the user's configured `livenessToolCall` (necessary for Ollama-format frontends,
      whose wire format carries no tool-call id, when the configured arguments lack the marker). Buried matching
      calls are removed from their assistant turn; a turn left with no genuine calls and no text content (the bare
      `"Assistant:"` filler counts as no content) is dropped entirely, along with its paired `role: "tool"` result
      messages (matched by `tool_call_id`, or by immediate adjacency for results that carry no id). Malformed
      `tool_calls` entries are tolerated and treated as genuine.
    * `collapse_duplicate_tool_calls()`: Runs at ingestion immediately after `strip_machinery_turns()`, under the
      same `livenessToolCall` gate. When the
      conversation contains a run of three or more consecutive exchanges (each an assistant turn making exactly one
      tool call followed by its result) where every call (same function, same arguments) and every
      whitespace-normalized result are identical, the run is collapsed to its first exchange and a note is appended
      to the kept result stating how many times the call was repeated and that repeating it will not change the
      outcome. Small models fall into repetition attractors where each visible copy of the exchange reinforces the
      next repeat, and identical empty results get misread as tool failure; collapsing removes the reinforcement and
      delivers the corrective inside the tool result, where the model actually reads. Two consecutive repeats (a
      legitimate retry), multi-call turns, differing arguments, and differing results (polling) are never collapsed.
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
    * `sse_format()`: Formats a string into the correct Server-Sent Event (SSE) structure.
    * `get_model_name()`: Returns the model identifier for API responses. When a workflow override is active, returns
      `username:workflow` format; otherwise returns just the username.
    * `parse_model_field()`: Parses the model field from incoming API requests and extracts a workflow name if one is
      specified. Supports formats like `username:workflow`, `workflow`, and `username:workflow:latest`.
    * `set_workflow_override()`: Sets the global workflow override from the model field. Called at the start of request
      processing.
    * `clear_workflow_override()`: Clears the workflow override. Called at the end of request processing.
    * `get_active_workflow_override()`: Returns the currently active workflow override, if any.
    * `extract_api_key()`: Reads the API key from the `Authorization: Bearer` header.
    * `extract_idempotency_key()`: Reads the client's `X-Idempotency-Key` header (case-insensitive; empty or
      longer than `MAX_IDEMPOTENCY_KEY_LENGTH` = 128 is treated as absent). See section 8.

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
        * **Ollama `done` semantics**: The Ollama chunk builders mark a chunk `"done": true` for **any** terminal
          `finish_reason` ("stop", "length", "tool_calls", ...), not just "stop"; Ollama clients read the stream
          until they see `done: true`, so a stream that ends on a token cap or a tool call must still terminate.
          A `done_reason` field is included on the terminal chunk, mapped to Ollama's vocabulary ("length" stays
          "length"; everything else maps to "stop").
        * **Ollama tool-call shape**: `build_ollama_chat_chunk()` and `build_ollama_chat_response()` convert tool
          calls to Ollama's native wire shape via `_convert_tool_calls_to_ollama_format()`: `arguments` as a JSON
          object, no OpenAI `id`/`type`/`index` envelope. The conversion is idempotent, so callers may pass either
          OpenAI-format or already-native calls.
        * **Models List Methods**: `build_openai_models_response()` and `build_ollama_tags_response()` return lists of
          available workflows from the `_shared` folder. Each workflow is presented in `username:workflow` format,
          allowing front-end applications to select specific workflows via their model dropdown.

### `Middleware/api/handlers/`

#### `base/base_api_handler.py`

* **Responsibility**: Defines the abstract interface (`BaseApiHandler`) that all API handlers must implement.
* **Key Components**:
    * `@abstractmethod register_routes()`: The contract method. Every concrete handler must implement this to register
      its URL rules with the Flask app.

#### `base/base_streaming.py`

* **Responsibility**: Houses the streaming machinery shared by the OpenAI and Ollama handlers: the Eventlet-optimized
  streamer (background reader greenlet plus heartbeat-capable client generator), the synchronous fallback streamer,
  and the selector that picks between them. The `base_` filename prefix keeps this module out of the `ApiServer`
  handler discovery walk. The streaming behavior itself is described in section 5.
* **Key Components**:
    * `StreamingApiConfig`: A frozen dataclass holding the four values that differ per API schema: the log label, the
      heartbeat bytes, the response mimetype, and the stream-terminator predicate. Each handler module defines one at
      module level.
    * `handle_streaming_request()`: The selector. Uses the Eventlet streamer when Eventlet is installed and actively
      monkey-patching the socket layer; otherwise falls back to synchronous streaming. Handlers call this with their
      `StreamingApiConfig` and their own `handle_user_prompt` reference (passed at call time so tests can patch it on
      the handler module).
    * `stream_with_eventlet_optimized()` / `stream_response_fallback()`: The two streaming implementations. Both
      release the request's idempotency entry in their teardown `finally` and log pre-response disconnects (see
      section 8).

#### `impl/openai_api_handler.py`

* **Responsibility**: Implements all endpoints that conform to the OpenAI API specification.
* **Key `MethodView` Classes**:
    * `ModelsAPI`: Handles `/v1/models`.
    * `CompletionsAPI`: Handles the legacy `/v1/completions`.
    * `ChatCompletionsAPI`: Handles the standard `/v1/chat/completions`.
* **Interactions**: Generates a `request_id` for each call. Uses `workflow_gateway.handle_user_prompt()` to process
  requests. Relies on `eventlet` and client disconnection to trigger the `CancellationService`. Streaming responses
  come from `base/base_streaming.py`, configured with the SSE comment heartbeat, the `text/event-stream` mimetype,
  and the `[DONE]` terminator predicate. `CompletionsAPI` and `ChatCompletionsAPI` also honor the
  `X-Idempotency-Key` header via `_admit_idempotency_key()`: a duplicate in-flight key cancels the orphaned
  original before serving the new arrival fresh (see section 8).

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
  that triggers cancellation, and come from `base/base_streaming.py`. The module defines two `StreamingApiConfig`
  instances because the two routes use different chunk shapes: `_CHAT_STREAMING_CONFIG` (`/api/chat`) sends a
  message-shaped heartbeat (`{"message": {...}, "done": false}`) while `_GENERATE_STREAMING_CONFIG`
  (`/api/generate`) sends a response-shaped one (`{"response": "", "done": false}`). Both use the
  `application/x-ndjson` mimetype and the `done:true` terminator predicate.

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
* The concurrency gate serializes all requests regardless of user, protecting shared hardware. In `endpoint` mode
  (`--concurrency-level endpoint`) the gate is enforced at the outbound LLM call rather than at the request boundary;
  the protection of shared hardware is preserved but requests themselves can overlap freely
* Log output is isolated per user into separate files (see Logging section below)

Per-request user resolution uses `get_request_user()` / `set_request_user()` stored in `_request_context`
(thread-local / greenlet-local), following the same pattern as `workflow_override` and `api_type`.

The `get_current_username()` function checks in order:
1. Request-scoped user (set from the model field)
2. `USERS` has exactly one entry: return `USERS[0]` (single-user mode)
3. `USERS` has multiple entries but no request user: **raises RuntimeError** (prevents silent cross-user data leaks)
4. `USERS` is None: fall back to `_current-user.json` (legacy, no `--User` arg)

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
| `username:workflow` | `chat-ui:general` | `(None, "general")` |
| `workflow` | `general` | `(None, "general")` if in `_shared/` |
| `username:workflow:latest` | `chat-ui:general:latest` | Strips `:latest`, same as above |
| Non-matching | `gpt-4` | `(None, None)`, uses normal routing |

**Multi-user mode** (USERS has 2+ entries):

| Format | Example | Result |
|--------|---------|--------|
| `username` | `user-two` | `("user-two", None)` (routes to user-two's default workflow) |
| `username:workflow` | `user-two:general` | `("user-two", "general")` (routes to user-two's shared workflow) |
| `workflow` (bare) | `general` | `(None, None)` (rejected, user must be specified) |
| Non-matching | `gpt-4` | `(None, None)` (rejected by `require_identified_user()`) |

### Folder Structure

```
Public/Configs/Workflows/
├── _shared/
│   ├── general/                    # Listed by models endpoint as folder name
│   │   └── _DefaultWorkflow.json   # Workflow loaded when folder is selected
│   ├── fast/
│   │   └── _DefaultWorkflow.json
│   ├── general-reasoning/
│   │   └── _DefaultWorkflow.json
│   ├── fast-reasoning/
│   │   └── _DefaultWorkflow.json
│   └── task/
│       └── _DefaultWorkflow.json
├── example-user/                   # A user's own workflow folder (optional)
│   └── ...
```

### Request Flow with Workflow Override

1. Client queries `/v1/models` → receives list of models from all configured users
2. Client sends request with `"model": "chat-ui:general"`
3. Handler calls `api_helpers.set_request_context_from_model("chat-ui:general")`
4. In multi-user mode, the request-scoped user is set to `chat-ui`
5. `workflow_gateway.handle_user_prompt()` detects the override
6. Workflow is loaded from `_shared/general/_DefaultWorkflow.json`
7. Response includes `"model": "chat-ui:general"`
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
* `Middleware/common/server_startup.py`: Contains `UserInjectionFilter` and `UserRoutingFileHandler` for per-user
  log isolation (re-exported by `server.py` for backwards compatibility)

-----

## 5\. Streaming Connection Lifecycle

All streaming responses in WilmerAI (both Ollama and OpenAI handlers) explicitly set the `Connection: close` HTTP
header. This forces the TCP connection to be torn down after each streaming response completes, rather than being
kept alive for reuse. The machinery described in this section is implemented once, in
`Middleware/api/handlers/base/base_streaming.py`, and parameterized per handler via `StreamingApiConfig`.

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
the Eventlet heartbeat mechanism would send heartbeat messages to the client, but from the client's perspective,
the stream is already complete.

The fix: each streaming generator checks whether the chunk it just yielded is the stream-complete marker:

- **Ollama**: checks for `"done": true` or `"done":true` in the encoded bytes. A substring check is safe here
  because generated text inside the chunk's JSON has its quotes escaped (`\"done\": true`), so content can never
  false-positive.
- **OpenAI**: exact match against the terminator event (`data: [DONE]`, ignoring surrounding whitespace). This
  must NOT be a substring check: each chunk is one SSE event, and a model writing the literal text "[DONE]" in
  its response would otherwise terminate the client stream mid-response.

When detected, the generator returns immediately, but the backend reader greenlet is **not** killed.
This allows post-returnToUser workflow nodes (memory summarization, categorization, reflection, etc.)
to finish processing in the background. The reader greenlet is only killed on client disconnect or error.

In the fallback (non-Eventlet) streaming path, the same stream-complete marker is detected, but
instead of returning, the generator sets a flag and continues consuming the `handle_user_prompt()`
iterator without yielding. This drives `execute()` through any remaining post-returnToUser nodes
before the generator naturally exhausts.

**Connection-hold consequence (fallback only).** Because there is no background greenlet in this path,
the only way to keep the workflow running after the responder streams its answer is to keep driving the
same WSGI generator. The client has already received the stream terminator and sees a complete response,
but the underlying HTTP request, and the worker handling it (Waitress thread, Gunicorn sync worker, or
the Flask dev server), stays occupied until the post-returnToUser nodes finish and the generator
exhausts. Deployments with heavy post-return work (large memory generation, reflection sub-workflows)
on a small worker pool should size the pool accordingly. The Eventlet path does **not** have this
property: it returns at the terminator (closing the connection) and finishes post-return nodes in the
background greenlet.

**Post-terminator exception containment (fallback only).** If a post-returnToUser node raises *after* the
terminator has been sent, the failure must not propagate out of the WSGI generator; the client already
saw a visually-complete stream, and re-raising would corrupt connection teardown. The fallback generator
therefore logs and swallows any exception that occurs once the done flag is set (mirroring the contained
handling in the Eventlet reader), and only re-raises exceptions that occur *before* the terminator.

### Heartbeat Format

Heartbeats differ between API formats:

- **Ollama (`application/x-ndjson`)**: A full JSON object matching the route's own response schema with
  `"done":false`: `/api/chat` sends an empty `"message"` object, `/api/generate` sends an empty `"response"`
  string. This ensures compatibility with clients like Open WebUI that require valid JSON on every line of the
  NDJSON stream, including strict clients that validate the chunk shape per route.
- **OpenAI (`text/event-stream`)**: An SSE comment (`:\n\n`). SSE clients ignore comment lines by design.

Both formats cause a TCP write, which is sufficient for disconnect detection: if the client has closed the
connection, the write will fail and trigger cancellation.

### Greenlet Lifecycle After Stream Completion

When the Eventlet streaming generator returns after stream-complete detection, the backend reader greenlet
is intentionally left running. The reader continues driving the `handle_user_prompt()` generator chain,
which allows `execute()` to process any remaining post-returnToUser workflow nodes (e.g., memory writes,
reflection sub-workflows, categorization). The reader greenlet exits naturally when `execute()` finishes
and the generator chain raises `StopIteration`.

The reader greenlet is only killed (via `eventlet.spawn(reader_greenlet.kill)`) when the streaming generator
exits due to client disconnect (`GeneratorExit`, `ClientDisconnected`, `BrokenPipeError`, `ConnectionError`)
or an unexpected error. In these cases, cancellation is also requested via `cancellation_service`, and each
node in `execute()` checks for cancellation at the start of its iteration.

**Cancellation registry lifecycle.** A cancellation entry is acknowledged (removed from the registry) at
whichever of these happens: the workflow's node-boundary check catches it and raises
`EarlyTerminationException`, or the stream tears down; the Eventlet reader greenlet's `finally` and the
fallback generator's `finally` both acknowledge any still-pending cancellation for their `request_id`. The
teardown acknowledgment matters because a cancellation that lands during the *final* responder node has no
later node boundary to catch it; without it the id stayed in the registry forever. As a backstop for ids that
are never acknowledged at all (e.g. bogus `request_id` values sent to the unauthenticated DELETE endpoints),
`CancellationService` lazily prunes entries older than `CANCELLATION_TTL_SECONDS` (1 hour) on each new
cancellation request, so the registry cannot grow without bound over long uptimes.

**Unbounded post-return lifetime.** On *natural* completion there is no per-node deadline or time-based cancellation:
the reader terminates only when `handle_user_prompt()` exhausts. A post-returnToUser node that blocks indefinitely
therefore keeps its reader greenlet (and the request-scoped state it captured) alive for the life of the process, since
the client has already disconnected at the terminator and nothing else will reclaim it. This is an inherent trade-off
of letting post-return work outlive the client; bound such nodes with their own timeouts rather than relying on the
request lifecycle to free them. The known concrete instance of this, the per-discussion memory condensation lock in
`slow_but_quality_rag_tool.py`, is now bounded by default: the acquire waits `condensationLockTimeoutSeconds` (default
600s) and, on timeout, skips memory generation for that round (self-healing: it retries on the next qualifying turn)
rather than blocking forever. Set that key to 0 to restore the original unbounded wait.

Correspondingly, the streaming generator's `finally` block sends `stop_signal` to the reader **only** on this
kill path. On *natural* completion (the generator returned at the terminator), it leaves `stop_signal`
unsent and lets the reader send it from its own `finally` when `execute()` finishes. This matters because the
reader only checks `stop_signal` before queueing a chunk: if a future post-returnToUser node ever yielded
output, signaling from the generator's natural-completion path would cause the reader to `break` and cut that
output off. Post-return nodes are non-responding today (they don't yield), so this is defensive, not a current
bug.

The asynchronous `eventlet.spawn(reader_greenlet.kill)` pattern (rather than a direct blocking `kill()`) is
used to avoid blocking the generator's `finally` block, which would delay the WSGI server's HTTP response
finalization.

### Implementation Details

Both `Connection: close` and stream-complete detection are implemented in the shared streaming functions
`stream_with_eventlet_optimized()` and `stream_response_fallback()` in
`Middleware/api/handlers/base/base_streaming.py`. Each handler supplies its own stream-terminator predicate,
heartbeat bytes, mimetype, and log label through its module-level `StreamingApiConfig`.

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

The `ApiServer` automatically discovers new handlers, so in most cases, you only need to add new files without
modifying existing ones.

### **Example: Add Support for a New API Type (e.g., Anthropic)**

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

The layer can operate at one of two granularities, selected at startup by the `--concurrency-level` flag:

* **`wilmer` (default)**: the semaphore is held at the WSGI middleware. Only `--concurrency` requests run at a time;
  excess requests wait at the front door or are rejected with 503 after the timeout. This is the historical behaviour
  and is described in detail in the subsections below.
* **`endpoint`**: the WSGI middleware passes every request through immediately. The same semaphore is instead
  acquired and released inside `LlmApiService.get_response_from_llm` around the outbound LLM HTTP call. This allows
  reentrant requests (workflows that call out to services that loop back into the same Wilmer instance) to make
  progress without deadlocking against a request-level gate. See section 7.7 for the `endpoint`-mode mechanics.

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

2. **Level check**: Reads `instance_global_variables.CONCURRENCY_LEVEL` at call time (not at middleware construction).
   When the level is `endpoint`, the middleware short-circuits and passes the request straight through to the inner
   app without touching the semaphore. The gate is enforced inside `LlmApiService` instead. Reading the level on each
   call (rather than once at startup) keeps test setup simple and means a single middleware instance behaves
   consistently regardless of when the level was set.

3. **Acquire with timeout**: For POST requests in `wilmer` mode, calls `semaphore.acquire(timeout=self._acquire_timeout)`.
   If the semaphore cannot be acquired within the timeout window, the request is rejected immediately.

4. **503 on timeout**: When acquire fails, the middleware calls `start_response("503 Service Unavailable", ...)`
   and returns a pre-encoded JSON body with an error message. The semaphore is never held in this path, so there
   is nothing to release.

5. **Call the inner app**: If acquired, the middleware calls `self._app(environ, start_response)` to get the
   response iterable from Flask.

6. **Exception handling**: If the inner app raises during the call (before returning a response), the middleware
   releases the semaphore immediately and re-raises the exception. This prevents a leaked semaphore slot from
   permanently reducing capacity.

7. **Wrap the response**: On success, the response iterable is wrapped in `_SemaphoreReleasingIterator`, which
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
  Users with slower hardware or very large models may want to increase this further. Applies to both `wilmer` and
  `endpoint` modes; in `endpoint` mode, an LLM call that times out at the gate raises `TimeoutError` from inside
  `get_response_from_llm` instead of returning a WSGI 503.

* **`--concurrency-level {wilmer,endpoint}`**: Selects which layer holds the semaphore. Stored in
  `instance_global_variables.CONCURRENCY_LEVEL`. Defaults to `wilmer`. See section 7.7 for the `endpoint`-mode
  implementation details.

### Method-Based Exemptions

The middleware exempts non-POST requests from the semaphore. This works because all LLM-dispatching endpoints
use POST, while metadata endpoints (model lists, version) use GET and cancellation endpoints use DELETE. The
check is done via `_requires_concurrency_limit()`, a static method that reads `REQUEST_METHOD` from the WSGI
environ. This approach avoids maintaining a path allowlist; if a new POST endpoint is added that does not
call an LLM, it would need to be handled (e.g., by switching to a path-based check or adding it to an
exemption set).

### 7.7 `endpoint`-Mode Gate (inside `LlmApiService`)

When `CONCURRENCY_LEVEL == "endpoint"`, the WSGI middleware passes every request through and the same
`BoundedSemaphore` is acquired around the outbound LLM HTTP call instead. The implementation lives in
`Middleware/llmapis/llm_api.py`:

* **`_acquire_endpoint_gate()`**: Module-level helper. Returns `False` immediately if the level is not `endpoint` or
  if no semaphore was configured (e.g. `--concurrency 0`). Otherwise calls `sem.acquire(timeout=CONCURRENCY_TIMEOUT)`
  and returns `True` on success. Raises `TimeoutError` if the semaphore could not be acquired within the timeout.

* **`_release_endpoint_gate(acquired)`**: Releases the semaphore if and only if `acquired` is `True`. The helper
  re-reads `get_request_semaphore()` rather than caching it across the call so it remains correct under test
  patching.

These helpers are wrapped around two specific code paths inside `LlmApiService.get_response_from_llm`:

1. **Non-streaming**: `gate_held = _acquire_endpoint_gate()` is called just before
   `self._api_handler.handle_non_streaming(...)`. The release happens in the outer `finally`. If the handler raises
   and a backup endpoint is configured, the gate is released *before* `_build_backup_service().get_response_from_llm(...)`
   is invoked so the backup's own `_acquire_endpoint_gate` does not deadlock against the parent at `--concurrency 1`.

2. **Streaming**: The acquire/release is moved inside `stream_wrapper`, the generator returned by
   `get_response_from_llm` for streaming calls. The gate is acquired on the *first iteration* of the generator
   (not at construction), held across every `yield`, and released in `finally`. This means:

   * If the caller abandons the generator (via `gen.close()`), the gate is released by `finally`.
   * If the upstream handler raises mid-stream, the gate is released by `finally` before the exception propagates.
   * If failover triggers before any token has been yielded, the gate is released *before* `yield from
     backup_service.get_response_from_llm(...)` so the backup can acquire its own slot.

The same `BoundedSemaphore` instance is used in both modes; only the layer at which it is acquired changes.
`--concurrency` continues to control its initial count and `--concurrency-timeout` continues to control the maximum
wait. `--concurrency 0` disables the gate entirely in both modes (the semaphore is never created).

### Why release before delegating to a backup

At `--concurrency 1`, holding the gate across a failover delegation would deadlock against ourselves: the parent
service would still hold the only slot while the backup tries to acquire one. The parent never returns until the
backup returns, and the backup never starts until the parent releases. Both the streaming and non-streaming failover
paths explicitly release the gate before invoking the backup. The backup re-acquires through its own normal
`_acquire_endpoint_gate` call, no special-case API.

### Key Files

* `Middleware/api/concurrency_middleware.py`: Contains `ConcurrencyLimitMiddleware` and
  `_SemaphoreReleasingIterator`. Reads `CONCURRENCY_LEVEL` at call time to decide whether to acquire or pass
  through.
* `Middleware/common/instance_global_variables.py`: Stores the `BoundedSemaphore` instance
  (`_request_semaphore`), along with `CONCURRENCY_LIMIT`, `CONCURRENCY_TIMEOUT`, and `CONCURRENCY_LEVEL`
  configuration values. Provides `initialize_request_semaphore(n)` and `get_request_semaphore()`.
* `Middleware/api/api_server.py`: `ApiServer._apply_concurrency_middleware()` conditionally wraps
  `app.wsgi_app` with the middleware during server initialization.
* `Middleware/llmapis/llm_api.py`: Module-level `_acquire_endpoint_gate()` / `_release_endpoint_gate()` and the
  `LlmApiService.get_response_from_llm` wrapping that uses them in `endpoint` mode.

-----

## 8\. Request Idempotency & Disconnect Propagation

Two related mechanisms keep a single-slot backend from wasting a generation when a client's request dies and it
retries. Both target the same failure mode: a client opens a streaming `/v1/chat/completions`, the connection
dies before any response byte arrives, the client retries, and, without protection, Wilmer double-generates
because the first attempt already forwarded the prompt to the backend LLM.

### The pre-response window

A streaming request has a window between "request parsed / prompt forwarded to the backend" and "first response
byte written to the client." Response headers are written lazily by the WSGI server on the first yielded chunk,
so during this window no HTTP response line has been sent yet. Two things can end a request inside this window:

* **Client disconnect**: the requesting client closes the socket. In Eventlet mode the 1-second heartbeat
  (`:\n\n` / NDJSON) forces a socket write that fails and raises `GeneratorExit`/`ClientDisconnected`, so the
  disconnect is detected within one heartbeat interval and cancellation is requested. Cancelling aborts
  Wilmer's own HTTP connection to the backend (via the `CancellationService` abort callbacks in
  `base_api_transport`), and llama.cpp-style backends abort generation when their requester disconnects.
* **Server-side failure**: the backend workflow raises *before* the first chunk (a transient backend error, a
  connection refusal, an exception in an early node). The streaming generator re-raises before yielding, so the
  WSGI server closes the accepted connection with no HTTP response; the client observes a bare "server
  disconnected without sending a response." This path is intentionally left as-is (it is what triggers the
  client's retry), but it is now **instrumented**: `stream_with_eventlet_optimized` and `stream_response_fallback`
  track a `first_output_sent` flag and, when a teardown happens before any byte was written, log a distinct
  `WARNING` tagged with the `request_id`, the cause, and the lifecycle phase (`awaiting-backend` vs
  `backend-data-buffered`). Correlate that `request_id` with the accept-path log line to find the root cause of
  pre-response drops.

### Feature 1: disconnect ⇒ cancellation

The rule is *no client connection ⇒ no backend generation*. Mid-stream and pre-response client disconnects both
request cancellation for the request's `request_id`, which:

* aborts the in-flight backend HTTP call (abort callback closes the `requests.Session`),
* trips the workflow's per-node cancellation check (`workflows_processor.execute()`), terminating the workflow
  at the next node boundary, and
* frees the request's concurrency slot (the `_SemaphoreReleasingIterator` releases when the response iterator
  is closed) and endpoint gate (`llm_api`'s `finally`).

This is keyless: by the time a client retries, its first attempt's connection is already dead, so the orphan is
already being cancelled. Non-streaming requests do not have a general mid-call disconnect watcher (the WSGI
worker is blocked in a synchronous call with no yield point to poll the socket); the idempotency key below is
what protects the non-streaming retry case.

### Feature 2: idempotency keys (`X-Idempotency-Key`)

`Middleware/services/idempotency_service.py` provides the `IdempotencyService` singleton, a thread-safe,
bounded `key -> request_id` registry (with a `request_id -> key` reverse index). It tightens the window from
"until Wilmer notices the disconnect" to "immediately," and gives a request-correlation id in the logs.

* **Admission** (`_admit_idempotency_key` in `openai_api_handler.py`): the OpenAI chat-completions and legacy
  completions endpoints read `X-Idempotency-Key` (via `api_helpers.extract_idempotency_key`; case-insensitive,
  `<= 128` chars, empty/over-long/absent = legacy client) and call `idempotency_service.register(key, request_id)`.
  `register` returns any **displaced** in-flight `request_id` that was previously bound to the same key; the
  endpoint then calls `cancellation_service.request_cancellation(displaced)` to kill the orphan and processes
  the new arrival fresh. Streams are never spliced or teed.
* **Release** is guarded and keyed by `request_id`. It only removes the forward `key -> request_id` binding when
  it still points at the finishing request, so a displaced original's late teardown clears only its own stale
  reverse index and leaves the newer request's live binding intact. Release fires from:
    * the streaming teardown (`backend_reader`'s `finally` in Eventlet mode, the fallback generator's `finally`)
      so a streaming key is held for the *entire* backend lifetime, including post-returnToUser nodes, and
      released exactly once at the end;
    * the endpoint's `finally` for the non-streaming path (the streaming path sets `handed_to_stream` and skips
      this so it does not release prematurely, since the view returns its `Response` before the stream runs).
  Release is a no-op for a request that never registered (legacy client, or any non-OpenAI endpoint), so
  `base_streaming` can call it unconditionally.
* **Bounding**: the registry is capped at `MAX_IN_FLIGHT_KEYS` (1024, LRU-evicted) and entries older than
  `IN_FLIGHT_TTL_SECONDS` (900s) are pruned lazily on the next `register` as a leak backstop. Healthy requests
  remove their own entry at completion. Keys are process-local; nothing is persisted.

Because a displaced original is cancelled through the *same* `CancellationService` machinery as a disconnect,
Feature 2 also protects the **non-streaming** retry case for free: the orphaned non-streaming workflow is
interrupted at its next node boundary even though there is no non-streaming disconnect watcher.

### Client contract (what the chat UI ships)

* `X-Idempotency-Key: <uuid4>` on every completion request; the **same** value across all retries of one
  logical request; a fresh value per new logical request.
* The client only retries when an attempt failed **before a response started** (connect errors and the
  pre-response disconnect). Once headers/tokens arrive it never retries. So Wilmer never sees a duplicate key
  for a request whose response already began; a duplicate always means the original's client is gone.
* Header absence = legacy client; Wilmer behaves exactly as before.

### Key Files

* `Middleware/services/idempotency_service.py`: the `IdempotencyService` singleton (`register`, guarded
  `release`, `get_request_id_for_key`, `clear`) and its `MAX_IN_FLIGHT_KEYS` / `IN_FLIGHT_TTL_SECONDS` bounds.
* `Middleware/api/api_helpers.py`: `extract_idempotency_key()` and `MAX_IDEMPOTENCY_KEY_LENGTH`.
* `Middleware/api/handlers/impl/openai_api_handler.py`: `_admit_idempotency_key()` and the register/release
  wiring in `ChatCompletionsAPI` / `CompletionsAPI`.
* `Middleware/api/handlers/base/base_streaming.py`: guarded release in the streaming teardowns and the
  pre-response disconnect instrumentation.
