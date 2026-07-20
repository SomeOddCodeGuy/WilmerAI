### **Developer Guide: `Middleware/llmapis/`**

This guide provides a deep dive into the architecture and implementation of the `Middleware/llmapis/` package, covering
its data flows, class responsibilities, and implementation details.

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

This architecture makes the system extensible, allowing new LLM backends to be integrated with minimal changes to
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
   crucial `$apiTypeConfig$` which defines the `$llm_type$` (e.g., `"openAIChatCompletion"`, `"claudeMessages"`).

3. **Handler Selection (Factory)**: The `$LlmApiService$` immediately calls its own `$create_api_handler()$` method.
   This method acts as a factory, using an `$if/elif$` block to inspect the `$llm_type$` string and instantiate the
   correct concrete handler class from the `$handlers/impl/$` directory.

4. **Request Execution**: An external service (e.g., `$LLMDispatchService$`) calls the
   public `$LlmApiService.get_response_from_llm()` method, providing the conversation history, prompts, and an optional
   **`request_id`** for cancellation.

5. **Initial Prompt Manipulation**: Inside `$get_response_from_llm()$`, some initial modifications occur. If the
   target LLM cannot handle images, the `images` key is stripped from all messages here. For the **completions** path
   (where `system_prompt` and `prompt` strings are passed directly), `addTextToStartOfSystem` and
   `addTextToStartOfPrompt` are applied to those strings. For the **chat completions** path (where a `conversation`
   list is passed instead), these text injections are handled one layer deeper in
   `BaseChatCompletionsHandler._build_messages_from_conversation()`, which also handles `addTextToStartOfCompletion`
   and `ensureTextAddedToAssistantWhenChatCompletion` for response seeding/prefilling.

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
      When the LLM produces tool calls, chunks may also contain a `'tool_calls'` key.
    * **Non-streaming**: A single raw string containing the full generated text, or a dictionary with `'content'`,
      `'tool_calls'`, and `'finish_reason'` keys when the LLM response includes tool calls.

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

### `handlers/base/base_api_transport.py`

* **Responsibility**: The shared HTTP transport that all outbound API handlers build on. Holds no generation-specific
  state; `$LlmApiHandler$` layers streaming and payload/prompt concerns on top of it, and `$EmbeddingApiHandler$`
  uses it as-is.
* **Key Components**:
    * `$BaseApiTransport$`: Owns the persistent `requests.Session`, the retry policy (`urllib3 Retry` with 5xx
      backoff, or `total=0` when `suppress_retries` is set), and the connect timeout from `$get_connect_timeout()$`.
    * `$execute_non_streaming_post()$`: The cancellation-aware non-streaming POST skeleton: pre-flight cancellation
      check, bounded manual retry loop (3 attempts, or 1 with `suppress_retries`), abort-callback registration per
      attempt, cancellation-aware error interpretation (a session closed by abort reads as cancelled, not as an
      error), and finally-block unregistration of the abort callback. Returns the parsed JSON body, or `None` if
      the request was cancelled.
    * `$_AbortHandle$`: The cancellation state shared between a request and the `$CancellationService$`. Its
      `abort()` method is registered as the abort callback and aggressively closes the session (and any attached
      in-flight response) to interrupt the stream or prefill phase. Used by both the non-streaming skeleton here
      and the streaming path in `$LlmApiHandler.handle_streaming()$`.
    * `$close()$`: Closes the HTTP session to release keep-alive connections.

### `handlers/base/base_llm_api_handler.py`

* **Responsibility**: Defines the abstract contract for all LLM API handlers and layers the generation-specific
  behavior (streaming, prompt/payload preparation, and sampler injection) on top of the HTTP transport it
  inherits from `$BaseApiTransport$`.
* **Key Components**:
    * `$LlmApiHandler(BaseApiTransport, ABC)$`: The abstract base class for the LLM handler hierarchy.
    * `$handle_streaming()`: Owns the streaming request path: prepares the payload, sends the streaming POST over
      the inherited session, iterates the response (SSE or line-delimited JSON per `$_iterate_by_lines$`), and
      checks `cancellation_service.is_cancelled(request_id)` before processing each line. Registers an
      `$_AbortHandle$` so cancellation can tear down the connection mid-stream or during prefill.
    * `$handle_non_streaming()`: Contributes payload preparation and response parsing; the HTTP retry loop,
      cancellation handling, and abort callbacks are delegated to `$BaseApiTransport.execute_non_streaming_post()$`.
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
      Claude's specific SSE stream format. It also overrides `_build_messages_from_conversation` to convert per-message
      `"images"` keys into Claude's multimodal content block format (`{"type": "image", "source": {"type": "base64",
      "media_type": "...", "data": "..."}}` for base64 data and `{"type": "image", "source": {"type": "url",
      "url": "..."}}` for HTTP URLs). Images are placed before text in content blocks per Claude's recommendation.
    * **`$OllamaChatHandler$`**: Inherits from `$BaseChatCompletionsHandler$`. It overrides `_prepare_payload` to place
      generation parameters in an `options` object and sets `$_iterate_by_lines$` to `True` to handle line-delimited
      JSON streaming.
    * **`$OpenAiApiHandler$`**: Inherits from `$BaseChatCompletionsHandler$`. It overrides
      `_build_messages_from_conversation` to convert per-message `"images"` keys into OpenAI's multimodal content format
      (`{"type": "image_url", "image_url": {"url": "..."}}`), handling base64 data URIs, raw base64 strings (with MIME
      type detection), and HTTP URLs.
    * **`$KoboldCppApiHandler$`**: Inherits from `$BaseCompletionsHandler$`. It implements `_get_api_endpoint_url` to
      return the correct Kobold endpoint. As a completions handler, it flattens conversation into a single prompt string
      and does not process images.

**Note on Image/Multimodal Support**: Images are carried as a per-message `"images"` key on regular message dicts (e.g.,
`{"role": "user", "content": "What's this?", "images": ["base64data"]}`). There are no separate `role: "images"` messages.
Chat completion handlers (`OllamaChatHandler`, `OpenAiApiHandler`, `ClaudeApiHandler`) detect the
`"images"` key and format images appropriately for each API in their `_build_messages_from_conversation` methods.
For `OpenAiApiHandler` and `ClaudeApiHandler`, the shared traversal and the text-only error fallback live in
`handlers/base/image_injection.py`; each handler supplies its own block format (`_process_single_image_source`),
image placement (Claude prepends, OpenAI appends), and API-visible fallback note text.
Completions handlers (e.g., `KoboldCppApiHandler`) do not process images. The `LlmApiService` gatekeeper
strips the `"images"` key from all messages when `llm_takes_images` is False, ensuring non-vision models never see image
data. Separate "ImageSpecific" handlers are no longer needed and have been deprecated.

The `Standard` node supports direct image passthrough via `acceptImages: true` in its config, with an optional
`maxImagesToSend` integer to cap the number of images sent to the backend (keeping the most recent). The
`StandardNodeHandler` reads these flags and passes `llm_takes_images` and `max_images` to
`LLMDispatchService.dispatch()`. Inside dispatch, `_apply_image_limit()` trims images from oldest to newest across
the message collection or the gathered image list, depending on code path.

The `ImageProcessor` workflow node supports optional per-discussion caching of vision responses via the
`saveVisionResponsesToDiscussionId` property. When enabled, vision LLM responses are stored in
`{discussion_id}/vision_responses.json` (keyed by a hash of the message's role, content, and sorted image data).
Cache reads/writes use `read_vision_responses` / `write_vision_responses` in `file_utils.py`, and the hash function
is `hash_message_with_images` in `hashing_utils.py`.

### `handlers/impl/embedding_api_handler.py`

* **Responsibility**: Calls a user-configured embeddings endpoint. Used by the `$EmbeddingService$` for the
  vector-memory semantic tier (`searchMode: "semantic"` / `"hybrid"`; see `Memories.md`).
* **Key Components**:
    * `$EmbeddingApiHandler$`: Deliberately a **sibling** of `$LlmApiHandler$` rather than a subclass: embeddings
      have no streaming, no prompt templates, and no samplers, so it extends `$BaseApiTransport$` directly and adds
      only URL construction, payload shaping, and response parsing for the two supported API types (the ApiType
      config's `type` field): `"openAIEmbeddings"` (`POST {base}/v1/embeddings`; OpenAI, llama.cpp server with
      `--embedding`, and most compatible servers) and `"ollamaEmbeddings"` (`POST {base}/api/embed`).
    * `$get_embeddings(texts, request_id)$`: Embeds a batch of texts via
      `$BaseApiTransport.execute_non_streaming_post()$` and returns one vector per input text in input order.
      Returns an empty list for empty input, `None` if the request was cancelled, and raises `ValueError` on a
      malformed response or a vector-count mismatch.

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

-----

## 6\. Tool Call Support

The `llmapis` layer supports forwarding tool definitions to backend LLMs and returning structured tool call responses.
The internal canonical format for tools, tool_choice, and tool call responses is OpenAI's format. Handlers for
non-OpenAI backends are responsible for converting to and from their native formats.

### Payload Preparation

`_prepare_payload` on `$BaseChatCompletionsHandler$` accepts optional `tools` and `tool_choice` keyword arguments. When
provided, these are included in the outgoing payload. Each concrete handler may convert them to the backend's native
format:

* **`$OpenAiApiHandler$`**: Passes `tools` and `tool_choice` through unchanged, as they are already in OpenAI format.
* **`$ClaudeApiHandler$`**: Converts tool definitions via `_convert_tools_to_claude_format()`, which transforms the
  OpenAI structure (`{"type": "function", "function": {"name": ..., "parameters": ...}}`) into Claude's structure
  (`{"name": ..., "input_schema": ...}`). Similarly, `_convert_tool_choice_to_claude_format()` maps OpenAI's
  `tool_choice` strings and objects to Claude's equivalents (e.g., `"auto"` becomes `{"type": "auto"}`).
* **`$OllamaChatHandler$`**: Passes `tools` and `tool_choice` through directly, as Ollama accepts OpenAI-format tool
  definitions.

### Conversation Replay (Tool Round Trips)

The internal message format keeps tool traffic in OpenAI's shape: an assistant message carries a `tool_calls` list
and each result arrives as a `role: "tool"` message with a `tool_call_id`. OpenAI-compatible and Ollama backends
accept these directly. The Anthropic Messages API accepts neither, so `$ClaudeApiHandler$._prepare_payload` runs
`_convert_tool_messages_for_claude()` over the conversation before sending:

* An assistant message with `tool_calls` becomes an assistant turn whose content is a block list: existing text
  first, then one `{"type": "tool_use", "id": ..., "name": ..., "input": {...}}` block per call. Argument strings
  are parsed to the object Claude requires; unparseable arguments degrade to `{}` with a warning.
* A `role: "tool"` message becomes a user turn holding a `{"type": "tool_result", "tool_use_id": ..., "content": ...}`
  block. Consecutive results merge into one user turn, and a plain user message immediately following tool results
  merges into that same turn (tool_result blocks must lead the turn), keeping roles alternating.

Without this conversion, the second request of any tool loop pointed at a Claude endpoint (the one that replays the
call and its result) was rejected with a 400.

Related: the message builders drop the empty trailing assistant marker added by `add_missing_assistant`, but never
one that carries `tool_calls`; that is structural data, not filler (`$BaseChatCompletionsHandler$` and
`$OllamaChatHandler$` both guard this).

### Streaming Responses (`_process_stream_data`)

`_process_stream_data` can now return dictionaries that include a `tool_calls` key alongside `token` and
`finish_reason`. The format of `tool_calls` in the returned dict is always OpenAI's delta format. Each handler
normalizes its backend's streaming output:

* **`$OpenAiApiHandler$`**: Extracts `tool_calls` directly from the SSE delta object.
* **`$ClaudeApiHandler$`**: Converts Claude's `content_block_start` (type `tool_use`) and `content_block_delta`
  (type `input_json_delta`) events into OpenAI-format tool call deltas.
* **`$OllamaChatHandler$`**: Converts Ollama's tool call format (where `arguments` is a dict) to OpenAI's format
  (where `arguments` is a JSON string), generating synthetic `id` values for each call.

### Non-Streaming Responses (`_parse_non_stream_response`)

`_parse_non_stream_response` returns `Union[str, Dict[str, Any]]`. When the response contains tool calls, it returns
a dictionary with three keys:

* `content` (str): Any text content from the response.
* `tool_calls` (list): Tool calls in OpenAI format.
* `finish_reason` (str): Typically `"tool_calls"` when tool calls are present.

When no tool calls are present, the method returns a plain string as before.

The same normalization rules apply: Claude and Ollama handlers convert their native tool call structures to OpenAI
format before returning. Ollama specifically converts `arguments` from a dict to a JSON string to match OpenAI's
convention.

-----

## 7\. Endpoint Failover

The `$LlmApiService$` supports transparent failover to a backup endpoint when the primary endpoint raises an exception.
This is configured per-endpoint via the optional `backupEndpointName` field in the endpoint JSON. Backups may chain
arbitrarily (each backup can itself specify a further backup), and cycle protection prevents infinite loops from
misconfiguration.

### Triggering Condition

Failover is triggered on **any** exception raised by the handler call, including `requests.exceptions.ConnectionError`,
`Timeout`, `RequestException`, and generic `ValueError` / `RuntimeError` / `OSError`. The feature deliberately does not
introduce new timeout behaviour; the existing `$get_connect_timeout()` connect timeout and the 14400-second read
timeout are unchanged. This is intentional: WilmerAI is often used with local models that legitimately take many minutes
to respond, and we do not want to spuriously failover on long reads.

### Streaming vs Non-Streaming

* **Non-streaming**: If `$handle_non_streaming()$` raises, the service instantiates an `$LlmApiService$` for the backup
  endpoint and delegates the call. The delegated call returns the backup's response transparently to the caller.

* **Streaming**: The wrapping generator tracks whether any token has been yielded to the caller. If the handler raises
  **before** the first token, failover delegates to the backup's generator and yields its tokens instead. If the handler
  raises **after** one or more tokens have been emitted, the original exception is re-raised; streaming failover cannot
  recover mid-stream because the client has already received partial data.

### Retry Suppression

When an endpoint has a backup configured, its `$LlmApiHandler$` is instantiated with `suppress_retries=True`. This has
two effects on the handler's HTTP behaviour:

1. The underlying `$urllib3 Retry$` adapter is configured with `total=0`, disabling the automatic 5xx retry loop.
2. The manual retry loop in `$BaseApiTransport.execute_non_streaming_post()$` (which `$handle_non_streaming()$`
   delegates to) collapses to a single attempt (`retries = 1` instead of `retries = 3`).

Endpoints without a backup (typically the tail of a chain, or endpoints configured without failover) retain the original
retry behaviour: 5 `urllib3` retries with exponential backoff on 5xx responses, and 3 manual attempts on network
exceptions in the non-streaming path.

### Egress Guard

Failover ships the whole conversation/prompt to the backup's host, so `$_build_backup_service()$` classifies that host
before delegating (`_classify_backup_host`, parsing the backup endpoint's `endpoint` URL):

- **local** (loopback / RFC1918-private / link-local IP, or `localhost`/`*.localhost`): allowed silently.
- **remote** (a public IP literal): **blocked** with a `$RuntimeError$` unless the backup endpoint sets
  `allowRemoteBackup: true`. This is safe-by-default: a transient local failure cannot silently send the prompt to a
  public address.
- **unknown** (a hostname that cannot be classified without DNS): allowed, but logged at `$WARNING$` as possible
  off-machine egress (a synchronous guard deliberately does not resolve DNS, and blanket-blocking hostnames would break
  the common case of referencing a backend by name).

The guard classifies by address only; it does not inspect what the backend does with the data. `allowRemoteBackup` is
read from the backup endpoint's config (the host that would receive the traffic opts in).

### Preset Resolution

The backup service is constructed with the preset name from the originating endpoint's optional `backupPresetName`
field, falling back to the originating request's own preset name when that field is unset
(`presetname=self._backup_preset_name or self._presetname` in `$_build_backup_service()$`). That name is resolved
against the **backup's own** preset type, so a heterogeneous backup (a different API type) must either ship a preset of
the inherited name in its `Presets/<type>/` directory or set `backupPresetName` to one it does; otherwise construction
raises `$FileNotFoundError$` mid-failover. See `Endpoint.md` (`backupPresetName`) for the operator-facing description.

### Concurrency Gate Interaction

When `CONCURRENCY_LEVEL == "endpoint"`, `$get_response_from_llm()$` also acquires the per-instance LLM-call semaphore for
the duration of the outbound call and **must release it before delegating to a backup**; otherwise the backup's own
acquire would deadlock against the still-held slot at `limit=1`. The full mechanics (acquire/release placement,
streaming vs non-streaming, generator-close handling) are documented in `Api.md` §7.7. The slot-wait `$TimeoutError$` is
not a backend failure and does **not** trigger failover.

### Cycle Protection

Each `$LlmApiService$` carries a `_visited_endpoints: Set[str]` set that accumulates across the chain. The primary adds
itself to the set on construction. When building the backup service, `$_build_backup_service()$` checks whether the
backup name is already in the set; if so, it raises `$RuntimeError$` with a message naming the offending chain. Callers
should never pass `_visited_endpoints` explicitly; it is an internal parameter populated by the service itself during
failover.

### Lifecycle and Logging

* Each failover hop logs a `$WARNING$` on the `$Middleware.llmapis.llm_api$` logger with the primary name, the
  exception type and message, and the backup name being attempted.
* A stream failure after tokens have already been emitted logs an `$ERROR$` explaining that failover is not possible.
* Cycles raise `$RuntimeError$` naming the offending endpoint chain.
* The primary handler's `$close()$` is invoked exactly once before delegation; the backup service manages its own
  handler lifecycle.
* `$is_busy_flag$` is cleared before delegation and remains `False` after the backup returns or after the chain is
  exhausted.

### Caller Transparency

No caller code needs to change. `$LlmApiService$` is instantiated with the primary endpoint name as usual, and the
service handles failover internally. All call sites (workflow nodes, memory/summarization, categorization, chat
responders) inherit failover automatically.
