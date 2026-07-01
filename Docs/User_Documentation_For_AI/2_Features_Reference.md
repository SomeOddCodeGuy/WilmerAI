# WilmerAI Features Reference

This document covers features of WilmerAI beyond the core workflow/node system. For workflow authoring,
node properties, and variables, see the companion documents.

---

## API Gateway

WilmerAI emulates OpenAI and Ollama APIs. Frontends connect to WilmerAI as if it were a standard LLM service.

### Endpoints

**OpenAI-compatible:**
- `POST /v1/chat/completions` -- Chat completions (structured messages array). Primary endpoint.
- `POST /v1/completions` -- Legacy text completions (single prompt string).
- `GET /v1/models` -- List available workflows as "models."

**Ollama-compatible:**
- `POST /api/chat` -- Chat completions.
- `POST /api/generate` -- Text completions.
- `GET /api/tags` -- List available models.
- `DELETE /api/chat`, `DELETE /api/generate` -- Cancel in-progress request with `{"request_id": "..."}`.

All POST endpoints support cancellation via client disconnection (close the HTTP connection).

### Streaming

Set `stream: true` in the request for token-by-token streaming. Controlled per-user via the `stream` setting.

### Discussion ID

Include `[DiscussionId]my-id[/DiscussionId]` anywhere in a message to enable persistent memory for that
conversation. WilmerAI strips the tag before processing.

---

## Backend LLM Connections

WilmerAI connects to LLM backends through three config layers:

1. **Endpoint** (`Endpoints/`) -- Where: URL, model name, API key, prompt injection, response cleaning.
2. **ApiType** (`ApiTypes/`) -- How: Maps property names to the backend's API schema (OpenAI, Ollama, Claude, etc.).
3. **Preset** (`Presets/`) -- What: Generation parameters (temperature, top_p, stop sequences, etc.).

Each workflow node specifies an `endpointName` and optionally a `preset`. Different nodes in the same workflow
can use different endpoints, allowing you to mix local and cloud models in one request.

Supported backend types: OpenAI-compatible (chat + completions), Anthropic Claude, Ollama (chat + generate),
KoboldCpp, Llama.cpp, Text Generation WebUI, Apple MLX.

---

## Prompt Routing

Routes incoming requests to different workflows based on user intent. Uses a two-part system:

1. **Routing config** (`Routing/`) -- Maps category names to workflows with descriptions.
2. **Categorization workflow** -- A standard workflow that analyzes the prompt and outputs a category name.

**How it works:** Request arrives -> categorization workflow runs -> outputs a category name (e.g., "CODING") ->
matched to routing config -> corresponding workflow executes. If no match after `maxCategorizationAttempts`,
falls back to `_DefaultWorkflow`.

**Enable:** Set `customWorkflowOverride: false` in user config, configure `routingConfig` and
`categorizationWorkflow`.

**Disable:** Set `customWorkflowOverride: true` and specify `customWorkflow` to use a single workflow for everything.

Auto-generated variables for categorization workflows: `{category_colon_descriptions}`,
`{categoriesSeparatedByOr}`, `{categoryNameBulletpoints}`, `{category_colon_descriptions_newline_bulletpoint}`.

---

## In-Workflow Routing

The `ConditionalCustomWorkflow` node provides if/then branching within a workflow. A prior node (often a
`Standard` node acting as a categorizer) outputs a key value, and the routing node dispatches to the
matching sub-workflow. See the Node Reference for properties.

---

## Nested Workflows (Parent/Child)

The `CustomWorkflow` node executes another workflow file as a child. Child workflows run in isolated context --
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

Three-part persistent memory tied to a `discussionId`:

1. **Long-Term Memory File** (`<id>_memories.json`) -- Chronological summarized chunks.
2. **Rolling Chat Summary** (`<id>_chat_summary.json`) -- Continuously updated high-level summary.
3. **Vector Memory Database** (`<id>_vector_memory.db`) -- Structured memory objects indexed for full-text keyword search (SQLite FTS5/BM25).

**Writer nodes** (slow, run after response): `QualityMemory`, `chatSummarySummarizer`, `FullChatSummary` (default mode).

**Reader nodes** (fast, use inline): `VectorMemorySearch`, `GetCurrentSummaryFromFile`, `RecentMemorySummarizerTool`,
`GetCurrentMemoryFromFile`, `FullChatSummary` (with `isManualConfig: true`).

**Typical pattern:** Read memory -> LLM responds -> WorkflowLock -> QualityMemory runs in background.

Memory generation triggers when either the token threshold (`chunkEstimatedTokenSize`) or message count threshold
(`maxMessagesBetweenChunks`) is reached, whichever comes first.

**Memory condensation** (optional): Automatically consolidates older file-based memories into fewer, denser summaries.
Configured via `condenseMemories`, `memoriesBeforeCondensation`, `memoryCondensationBuffer` in the memory settings file.

See 5_Workflow_Memory.md for full memory node details and 4_Workflow_Variables.md for variables.

---

## Per-User Encryption and Data Isolation

When a client sends `Authorization: Bearer <key>`:
- **Directory isolation** activates automatically -- discussion files stored under a hash-based subdirectory.
- **Encryption** activates if `encryptUsingApiKey: true` in user config -- files encrypted at rest with Fernet
  (AES-128-CBC + HMAC-SHA256) derived from the API key.

When no API key is sent, behavior is unchanged (original directory, plaintext files).

Encrypted files: memories, summaries, timestamps, vision cache, condensation tracker, context compactor state.
**Not encrypted:** SQLite databases (vector memory, workflow locks), configuration files.

**Log redaction:** Automatic when encryption is active. Can also be enabled independently with
`redactLogOutput: true` in user config.

**Key management:** WilmerAI does not store/validate keys. Lost key = unrecoverable files. Re-key and
decrypt scripts available in `Scripts/`.

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
overlap freely -- useful for setups where workflows make outbound calls to services that may call back into the
same Wilmer instance.

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

1. **Merge:** `mergeConsecutiveAssistantMessages: true` -- Collapse runs into one message. Optional delimiter
   via `mergeConsecutiveAssistantMessagesDelimiter`.
2. **Insert:** `insertUserTurnBetweenAssistantMessages: true` -- Add synthetic user messages between them.
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

Set `lowercaseToolCallFunctionNames: true` to lowercase function names in tool call responses before relaying
them to the frontend. This fixes local models (Gemma, Qwen, etc.) that produce capitalized names like `Glob`
instead of `glob`. Off by default; do not enable for frontends like Claude Code that expect original casing.

---

## Workflow Selection via Model Field

When `allowSharedWorkflows` is true, workflows in `_shared/` folders appear in the models list. The frontend
selects a workflow by setting the model field:

| Format | Behavior |
|---|---|
| `username:workflow` | Use specific workflow (and user in multi-user mode). |
| `username` | Route to that user's default workflow. |
| `workflow` | Use workflow from `_shared/` if it exists. |
| Anything else | Normal routing/`customWorkflow`. |

Shared workflows are folders in `_shared/` containing a `_DefaultWorkflow.json` file.

---

## Multi-User Mode

Start with multiple `--User` flags. All users share one instance, one port (`--port`, default 5050),
and one concurrency gate. Per-user `port` config is ignored. File logging (`--file-logging`) automatically
isolates to per-user subdirectories.
