# WilmerAI Features Reference

This document covers features of WilmerAI beyond the core workflow/node system. For workflow authoring,
node properties, and variables, see the companion documents.

---

## API Gateway

WilmerAI emulates OpenAI and Ollama APIs. Frontends connect to WilmerAI as if it were a standard LLM service.

### Endpoints

**OpenAI-compatible:**
- `POST /v1/chat/completions`: Chat completions (structured messages array). Primary endpoint.
- `POST /v1/completions`: Legacy text completions (single prompt string).
- `GET /v1/models`: List available workflows as "models."

**Ollama-compatible:**
- `POST /api/chat`: Chat completions.
- `POST /api/generate`: Text completions.
- `GET /api/tags`: List available models.
- `DELETE /api/chat`, `DELETE /api/generate`: Cancel in-progress request with `{"request_id": "..."}`.

Streaming responses support disconnect cleanup. Eventlet heartbeats enable detection during prefill; fallback
streaming detects closure when synchronous execution returns control. Closing a response before iteration releases
request bookkeeping and stops scheduled Eventlet work. Synchronous non-streaming requests have no disconnect watcher.
Explicit cancellation closes owned pools and any attached response, but Session.close alone does not guarantee that
a request blocked before response headers is interrupted; transport timeouts still apply.

### Idempotent Retries

The OpenAI completion endpoints (`/v1/chat/completions`, `/v1/completions`) honor an optional
`X-Idempotency-Key` header (opaque string, <= 128 chars, case-insensitive). Send the same value across all
retries of one logical request; use a fresh value per new request. When a key arrives that is still in flight,
WilmerAI cancels the abandoned original and serves the new request fresh, so a retry never double-generates on
the backend. Retry only on failures that happen before the response starts. Header absent = legacy behavior.
Keys are process-local (not persisted across restarts).

### WilmerProxy Runtime Mode

Start a filter instance with `--Mode WilmerProxy --WilmerProxyConfig <name>` to expose selected aliases from one or
more upstream WilmerAI instances. Config files live at `Public/Configs/WilmerProxy/<name>.json`. Each public model maps
independently to an `upstream` name and exact downstream `targetModel`.

WilmerProxy mode registers only the OpenAI model, chat-completion, and legacy-completion routes. It replaces only the
top-level model value and forwards the otherwise complete JSON object. It bypasses workflow request normalization,
workflow execution, endpoint configs, `llmapis`, and response building. Successful streams and upstream error bodies
are relayed instead of reconstructed.

Each upstream authorization policy is `passthrough`, `configured`, or `omit`. Additional request headers use the
explicit `forwardHeaders` allowlist, which defaults to `X-Idempotency-Key`. Requests are not retried and redirects are
not followed. Redirect bodies remain under relay ownership. Location or Content-Location headers that cannot be
serialized as URLs are omitted while the upstream status and body are preserved.

### Streaming

Set `stream: true` in the request for token-by-token streaming. Controlled per-user via the `stream` setting.

### Discussion ID

Include `[DiscussionId]my-id[/DiscussionId]` anywhere in a message to enable persistent memory for that
conversation. WilmerAI strips the tag before processing.

---

## Backend LLM Connections

WilmerAI connects to LLM backends through three config layers:

1. **Endpoint** (`Endpoints/`): the "where". URL, model name, API key, prompt injection, response cleaning.
2. **ApiType** (`ApiTypes/`): the "how". Maps property names to the backend's API schema (OpenAI, Ollama, Claude, etc.).
3. **Preset** (`Presets/`): the "what". Generation parameters (temperature, top_p, stop sequences, etc.).

Each Standard node requires an `endpointName` and a `preset`. Different nodes in the same workflow
can use different endpoints, allowing you to mix local and cloud models in one request.

Supported backend types: OpenAI-compatible (chat + completions), Anthropic Claude, Ollama (chat + generate),
KoboldCpp, Llama.cpp, Text Generation WebUI, Apple MLX.

---

## Prompt Routing

Routes incoming requests to different workflows based on user intent. Uses a two-part system:

1. **Routing config** (`Routing/`): Maps category names to workflows with descriptions.
2. **Categorization workflow**: A standard workflow that analyzes the prompt and outputs a category name.

**How it works:** Request arrives -> categorization workflow runs -> outputs a category name (e.g., "CODING") ->
matched to routing config -> corresponding workflow executes. If no match after `maxCategorizationAttempts`,
falls back to `_DefaultWorkflow`.

**Enable:** Set both `allowSharedWorkflows: false` and `customWorkflowOverride: false` in user config, then configure
`routingConfig` and `categorizationWorkflow`.

**Disable:** Set `customWorkflowOverride: true` and specify `customWorkflow` to use a single workflow for everything,
or set `allowSharedWorkflows: true` to select workflows through the request model field.

Auto-generated variables for categorization workflows: `{category_colon_descriptions}`,
`{categoriesSeparatedByOr}`, `{categoryNameBulletpoints}`, `{category_colon_descriptions_newline_bulletpoint}`.

---

## In-Workflow Routing

The `ConditionalCustomWorkflow` node provides if/then branching within a workflow. A prior node (often a
`Standard` node acting as a categorizer) outputs a key value, and the routing node dispatches to the
matching sub-workflow. See the Node Reference for properties.

---

## Nested Workflows (Parent/Child)

The `CustomWorkflow` node executes another workflow file as a child. Child workflows run in isolated context;
they cannot access parent `{agent#Output}` variables. Data must be passed explicitly via `scoped_variables`,
which the child receives as `{agent1Input}`, `{agent2Input}`, etc.

Use cases: reusable logic (summarization, search), breaking large workflows into manageable parts, building
orchestrator workflows that call specialized sub-workflows.

---

## Jinja2 Templating

Add `"jinja2": true` to any node to enable Jinja2 syntax in `prompt` and `systemPrompt` fields.

- **Expressions:** `{{ variable_name }}` to print a value.
- **Conditionals:** `{% if agent1Output == 'QUESTION' %}...{% else %}...{% endif %}`
- **Loops:** `{% for message in messages %}{{ message.role }}: {{ message.content }}{% endfor %}`
- **Filters:** `{{ message.role | capitalize }}`

All standard workflow variables are available in the Jinja2 context. The `{messages}` variable (full
conversation as a list of dicts) is especially useful with Jinja2 for custom formatting.

When `jinja2` is false or absent, standard `{variable}` substitution is used (Python `str.format()`).

---

## Conversation Timestamps

Automatically injects timestamps into conversation messages before sending to the LLM. Requires a `discussionId`.

**Enable on a Standard node:**

| Property | Description |
|---|---|
| `addDiscussionIdTimestampsForLLM` | Set to true to enable. |
| `useRelativeTimestamps` | If true: `[Sent 5 minutes ago]`. If false (default): `(Saturday, 2025-09-20 16:30:05)`. |
| `useGroupChatTimestampLogic` | If true, commit assistant timestamps immediately (for group chats). If false, commit on next user turn (recommended for 1-on-1). |

Timestamps are stored per-discussion in a JSON file. Historical messages without timestamps are backfilled
with sequential 1-second offsets.

The `{time_context_summary}` variable provides a natural language summary:
`[Time Context: This conversation started 2 days ago. The most recent message was sent 15 minutes ago.]`

---

## Memory System

Four-part persistent memory tied to a `discussionId`:

1. **Long-Term Memory File** (`<id>_memories.json`): Chronological summarized chunks.
2. **Rolling Chat Summary** (`<id>_chat_summary.json`): Continuously updated high-level summary.
3. **Vector Memory Database** (`vector_memory.db` in the discussion folder; a legacy `<id>_vector_memory.db` at the old `Public/` location keeps being used if present): Structured memory objects indexed for full-text keyword search (SQLite FTS5/BM25). Optionally also stores per-model embeddings (`embeddingEndpointName` in memory settings) enabling semantic/hybrid search on `VectorMemorySearch` (`searchMode`, merged via RRF); degrades to keyword search when embeddings are unavailable.
4. **State Document** (`state_document.md`): Optional always-injected markdown snapshot of what is currently true (profile / world state); maintained by a merge sub-workflow (`useStateDocument`), read via `GetCurrentStateDocument`.

**Writer nodes** (slow, run after response): `QualityMemory`, `chatSummarySummarizer`, `FullChatSummary` (default mode).

**Reader nodes** (fast, use inline): `VectorMemorySearch`, `GetCurrentSummaryFromFile`, `RecentMemorySummarizerTool`,
`GetCurrentMemoryFromFile`, `GetCurrentStateDocument`, `FullChatSummary` (with `isManualConfig: true`).

**Typical pattern:** Read memory -> LLM responds -> WorkflowLock -> QualityMemory runs in background.

Memory generation triggers when either the token threshold (`chunkEstimatedTokenSize`) or message count threshold
(`maxMessagesBetweenChunks`) is reached, whichever comes first.

**Memory condensation** (optional): Automatically consolidates older file-based memories into fewer, denser summaries.
Configured via `condenseMemories`, `memoriesBeforeCondensation`, `memoryCondensationBuffer` in the memory settings file.

See 5_Workflow_Memory.md for full memory node details and 4_Workflow_Variables.md for variables.

---

## Per-User Encryption and Data Isolation

When a client sends `Authorization: Bearer <key>`:
- **Directory isolation** activates automatically for built-in discussion files. Workflow files receive the same scope
  when their path starts with `{Discussion_Directory}`.
- **Encryption** activates if `encryptUsingApiKey: true` in user config: files encrypted at rest with Fernet
  (AES-128-CBC + HMAC-SHA256) derived from the API key.

The key is a client storage namespace, not a validated login credential. Independent clients should use different
high-entropy keys. When no key is sent, clients using the same discussion ID share the original directory.

Encrypted files: memories, summaries, timestamps, vision cache, condensation tracker, context compactor state.
**Not encrypted:** SQLite databases (vector memory, workflow locks), configuration files.

**Log redaction:** Automatic when encryption is active. Can also be enabled independently with
`redactLogOutput: true` in user config.
OpenAI chat/completions and Ollama chat/generate provisionally redact diagnostics before user selection, then apply
the selected user's policy before payload logging. Early selection errors stay redacted; ordinary requests retain
normal diagnostics. Private payload logging does not invoke lazy serialization.
Built-in module diagnostics, including provider parse failures, native MCP errors, memory summaries and image
fallback errors, honor this request policy. Independent third-party loggers and startup messages are outside it.
Eventlet reader cleanup diagnostics and WebPageFetch handler/service warnings use the same request policy, including
warnings when an operator permits fetching after a robots failure.
Cancellation callbacks capture the generation's privacy flag at registration. Cleanup and cancellation-service error
logs keep that policy across threads or greenlets, preserve a private caller and restore caller state after invocation.

**Key management:** WilmerAI does not store/validate keys. Lost keys make encrypted files unrecoverable. Preserve the
original API key and workflow selection; disabling encryption does not decrypt existing files. Runtime encryption
occurs during individual built-in discussion file writes.

---

## Concurrency Limiting

Controls how many requests WilmerAI processes simultaneously.

| Flag | Default | Description |
|---|---|---|
| `--concurrency N` | 1 | Max simultaneous requests (or LLM calls in endpoint mode). 0 = no limit. |
| `--concurrency-timeout N` | 900 (15 min) | Seconds to wait for a slot before returning HTTP 503. |
| `--concurrency-level LEVEL` | `wilmer` | Where the gate is enforced. `wilmer` gates at the WSGI front door; `endpoint` lifts that gate and serializes only outbound LLM API calls so reentrant requests cannot deadlock. |

Applies to POST endpoints only. GET (models list) and DELETE (cancellation) are always available.

In multi-user mode, the concurrency gate is shared across all users, protecting shared LLM hardware. In `endpoint`
mode the protection is preserved (only one LLM call at a time at `--concurrency 1`) while requests themselves can
overlap freely, which is useful for setups where workflows make outbound calls to services that may call back into
the same Wilmer instance.

---

## Offline Wikipedia Integration

Connects to a local `OfflineWikipediaTextApi` service for factual RAG.

**Enable in user config:**
```json
{
  "useOfflineWikiApi": true,
  "offlineWikiApiHost": "127.0.0.1",
  "offlineWikiApiPort": 5728
}
```

Use the `OfflineWikiApi*` family of nodes in workflows to query. See Node Reference for node types.

---

## Custom Python Scripts

The `PythonModule` node executes a local Python script. The script must define:

```python
def Invoke(*args, **kwargs):
    # Process arguments, return a string
    return "result string"
```

Arguments are passed from the node's `args` (array) and `kwargs` (object) properties. All values support
variable substitution. The returned string becomes the node's output.

For controlled error reporting, raise `DynamicModuleError` from
`Middleware.workflows.tools.dynamic_module_loader`.

---

## Consecutive Assistant Message Handling

Agentic frontends can produce multiple assistant messages in a row, which most LLM APIs reject.
WilmerAI offers two strategies on `Standard` nodes (only when `prompt` is empty):

1. **Merge:** Set `mergeConsecutiveAssistantMessages: true` to collapse runs into one message. Optional delimiter
   via `mergeConsecutiveAssistantMessagesDelimiter`.
2. **Insert:** Set `insertUserTurnBetweenAssistantMessages: true` to add synthetic user messages between them.
   Customize text with `insertedUserTurnText` (default: `"Continue."`).

If both are enabled, merging takes precedence. Tool-call sequences (`assistant -> tool -> assistant`) are
never modified.

---

## Tool Call Passthrough

Set `allowTools: true` on the responding `Standard` node. Tool definitions from the frontend are forwarded
to the backend LLM. If the LLM responds with tool calls, they're relayed back to the frontend. Works with
OpenAI, Claude, and Ollama backends.

Only useful on the responding node. Set `includeToolCallsInConversation: true` to make tool call summaries
visible in conversation variables for downstream nodes.

For multi-round tool loops through an authored-prompt responder (a node with a `prompt` field), also set
`appendNativeToolExchange: true`: the trailing assistant `tool_calls` turn and its `role:"tool"` results are
then sent as native messages after the authored prompt (and excluded from the text transcript), so the model
generates from the standard post-tool-result position instead of imitating tool syntax as text. Collection-mode
responders (no `prompt`) already send native tool history. Completions-paradigm backends ignore tools entirely.

`appendNativeToolExchange` controls history delivery independently of `allowTools`. An authored-prompt internal
planner can enable it while keeping `allowTools: false` to inspect the live call and result as native messages without
receiving tool definitions or giving its output a frontend execution path. Only the responding node should enable
`allowTools` when the frontend must execute the model's calls.

Set `lowercaseToolCallFunctionNames: true` to lowercase function names in tool call responses before relaying
them to the frontend. This fixes local models (Gemma, Qwen, etc.) that produce capitalized names like `Glob`
instead of `glob`. Off by default; do not enable for frontends like Claude Code that expect original casing.

## Structured Output (Grammar-Constrained Responses)

Backends declare a per-request constraint mechanism in their ApiType config: `structuredOutput` block with `field`
(the payload key, dotted for nesting) and `style` (`openaiJsonSchema` for llama.cpp/LM Studio/vLLM/OpenAI's
`response_format`, `raw` for Ollama's `format`); absent = unsupported. Two uses:

1. **Automatic tool enforcement**: when a request's `tool_choice` is a forced function or `"required"`, the round
   is grammar-constrained to a tool-call JSON shape and converted back to a `tool_calls` response. Native tools are
   dropped from that payload (schema+tools conflict on llama.cpp/Ollama) and injected as text. Output is
   parse-checked with one redraw (some backends fail open). `tool_choice: "auto"` is never touched.
2. **`structuredOutputFile` node property**: pins a node's output to a JSON Schema file from
   `Public/Configs/StructuredOutputs/<sub>/` (sub = `structuredOutputConfigsSubDirectory` user key, default
   username, root fallback). The output IS the constrained JSON text.

Caveats: the model never sees the schema (describe the shape in the prompt too); disable thinking on constrained
nodes; a 200 does not prove enforcement on fail-open backends.

---

## Workflow Selection via Model Field

When `allowSharedWorkflows` is true, workflows in `_shared/` folders appear in the models list. The frontend
selects a workflow by setting the model field. Shared mode disables custom workflow and routing, and a request without
a valid advertised workflow model returns HTTP 400.

| Format | Behavior |
|---|---|
| `username:workflow` | Use specific workflow (and user in multi-user mode). |
| `username` | Select the user, but reject the request because no shared workflow was selected. |
| `workflow` | Use workflow from the shared folder if it exists (single-user mode only). |
| Anything else | Reject the request because no valid shared workflow was selected. |

Shared workflows are folders in `_shared/` containing a `_DefaultWorkflow.json` file.

---

## Multi-User Mode

Start with multiple `--User` flags. All users share one instance, one port (`--port`, default 5050),
and one concurrency gate. Per-user `port` config is ignored. File logging (`--file-logging`) automatically
isolates to per-user subdirectories.
