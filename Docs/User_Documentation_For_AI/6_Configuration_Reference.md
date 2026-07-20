# WilmerAI Configuration Reference

All configuration files are JSON, located under `Public/Configs/`. Names referenced in workflows and other configs
are always filenames without the `.json` extension.

---

## User Config

**Location:** `Public/Configs/Users/<username>.json`

The central settings file for a WilmerAI user instance. Activate with `--User <username>` at startup.

### Core Settings

| Field | Type | Required | Description |
|---|---|---|---|
| `port` | int | Yes (single-user) | Listening port. Ignored in multi-user mode (use `--port`). |
| `stream` | bool | Yes | Enable streaming responses to the client. |

### Workflow Routing

| Field | Type | Required | Description |
|---|---|---|---|
| `customWorkflowOverride` | bool | Yes | If true, skip routing and always use `customWorkflow`. |
| `customWorkflow` | string | Yes | Workflow name to use when `customWorkflowOverride` is true. |
| `routingConfig` | string | Yes | Routing config filename (from `Routing/`). Used when `customWorkflowOverride` is false. |
| `categorizationWorkflow` | string | Yes | Workflow that categorizes prompts into routing categories. |
| `maxCategorizationAttempts` | int | No (default: 1) | Retries before falling back to `_DefaultWorkflow`. |

### Memory Workflows

These reference workflow filenames used internally by the memory system.

| Field | Type | Description |
|---|---|---|
| `discussionIdMemoryFileWorkflowSettings` | string | Memory generation settings file (e.g., `"_DiscussionId-MemoryFile-Workflow-Settings"`). |
| `fileMemoryToolWorkflow` | string | Workflow for file-based memory operations. |
| `chatSummaryToolWorkflow` | string | Workflow for rolling chat summary generation. |
| `conversationMemoryToolWorkflow` | string | Workflow for chunked memory creation. |
| `recentMemoryToolWorkflow` | string | Workflow for recent memory retrieval. |

### Directories

| Field | Type | Description |
|---|---|---|
| `discussionDirectory` | string | Absolute path where discussion files (memories, summaries, vector DBs) are stored. Optional; defaults to `{PublicDirectory}/DiscussionIds/` (a sibling of `Configs/`, not inside it). Overridable by the `--DiscussionDirectory` CLI flag. |
| `sqlLiteDirectory` | string | Absolute path for the per-user SQLite database (workflow locks). Optional; defaults to `{PublicDirectory}/SqlLiteDBs/`. Overridable by the `--UserLevelSqlLiteDirectory` CLI flag. |

Path resolution for all three runtime-data directories follows the same order: CLI flag > user config setting >
`{PublicDirectory}/<default-subdir>/`. When `--PublicDirectory` is not set, every default resolves to a subfolder
under `{install_dir}/Public/` (the directory containing `server.py`), not relative to the current working directory.
This means logs, lock DBs, discussion data, etc. never quietly drop into a user's home folder or a daemon's working
directory. Runtime data (DiscussionIds, SqlLiteDBs, logs) lives as siblings of `Configs/` under `Public/`, never
inside `Configs/`. `--ConfigDirectory` remains supported for backwards compatibility and still governs config
resolution, but `--PublicDirectory` is the recommended flag for shared installations because it controls both configs
and runtime data together. Legacy data at pre-refactor locations (`Public/DiscussionIds/`, lock DBs in the project
root) is used in place if found; no automatic migration is performed.

### Subdirectory Overrides

| Field | Type | Description |
|---|---|---|
| `endpointConfigsSubDirectory` | string | Subfolder within `Endpoints/` for this user's endpoint configs. |
| `workflowConfigsSubDirectoryOverride` | string | Load workflows from `Workflows/<value>/` instead of the user folder. |
| `presetConfigsSubDirectoryOverride` | string | Custom subfolder within `Presets/<ApiType>/` for presets. |
| `structuredOutputConfigsSubDirectory` | string | Custom subfolder within `StructuredOutputs/` for `structuredOutputFile` schemas. Default: username; root fallback. |
| `sharedWorkflowsSubDirectoryOverride` | string | Custom folder name instead of `_shared` for shared workflows. Default: `"_shared"`. |

### Prompt Template Settings

| Field | Type | Description |
|---|---|---|
| `chatPromptTemplateName` | string | Prompt template filename (from `PromptTemplates/`). Used for completions-style APIs. |
| `chatCompleteAddUserAssistant` | bool | Prepend `User: ` / `Assistant: ` role prefixes to messages. |
| `chatCompletionAddMissingAssistantGenerator` | bool | Add final empty `Assistant: ` prefix to prompt the model. |

### Conversation Variable Formatting

| Field | Type | Default | Description |
|---|---|---|---|
| `separateConversationInVariables` | bool | false | Use custom delimiter between messages in `chat_user_prompt_*` variables. |
| `conversationSeparationDelimiter` | string | `"\n"` | Delimiter to use when `separateConversationInVariables` is true. |
| `userWideWorkflowVariables` | object | none | Operator-defined shared `{placeholders}` available to every workflow (e.g. a base directory for a workflow's state files), so a value is set once instead of repeated per workflow. Lowest precedence: never shadows a built-in or a workflow-level key; a value may itself reference another variable, resolved on a second pass. |

### Feature Toggles

| Field | Type | Default | Description |
|---|---|---|---|
| `useOfflineWikiApi` | bool | none | Enable offline Wikipedia nodes. |
| `offlineWikiApiHost` | string | none | Wikipedia API host (e.g., `"127.0.0.1"`). |
| `offlineWikiApiPort` | int | none | Wikipedia API port (e.g., `5728`). |
| `useFileLogging` | bool | false | Write logs to file (single-user fallback; use `--file-logging` in multi-user). |
| `allowSharedWorkflows` | bool | false | List `_shared/` workflow folders in models API endpoints. |
| `encryptUsingApiKey` | bool | false | Encrypt discussion files using the `Authorization: Bearer` key. |
| `redactLogOutput` | bool | false | Redact user content from all log output. |
| `interceptOpenWebUIToolRequests` | bool | false | Intercept OpenWebUI tool-selection requests with empty response. |
| `livenessToolCall` | object | none | `{ "toolName": "...", "arguments": {...} }`; `toolName` required, `arguments` optional. When set, Wilmer injects this harmless no-op tool call into a streamed response from a responder node with `"injectLivenessToolCall": true` in its node config when the response would otherwise end with no tool call (closing with `finish_reason: tool_calls` so agentic frontends call back instead of ending the run). Setting it also enables ingestion-side cleanup: buried liveness machinery turns are stripped, and runs of 3+ identical tool-call exchanges are collapsed to one with a note appended to the kept result. Users without this setting never have their conversations rewritten. The `arguments` should include the `[Wilmer]` marker. |
| `contextCompactorSettingsFile` | string | none | Settings file for ContextCompactor node (in workflow folder). |
| `connectTimeoutInSeconds` | int | 30 | TCP connection timeout for LLM endpoints. |
| `clampPromptToContextWindow` | bool | false | User-level default for the context-window clamp (see Endpoint Config). A node or endpoint setting overrides it; absent here means each endpoint/node decides, defaulting off. The shipped user configs set this `true`. |

---

## Endpoint Config

**Location:** `Public/Configs/Endpoints/<subdirectory>/<name>.json`

Defines a connection to a specific LLM backend. Referenced by `endpointName` in workflow nodes.

### Core Connection

| Field | Type | Required | Description |
|---|---|---|---|
| `endpoint` | string | Yes | Full URL of the LLM API (e.g., `"http://localhost:11434"`). |
| `apiTypeConfigFileName` | string | Yes | ApiType config name (e.g., `"OllamaApiChat"`, `"Open-AI-API"`, `"Claude"`). |
| `maxContextTokenSize` | int | Yes | Maximum context size in tokens for this model. |
| `modelNameToSendToAPI` | string | Yes | Model identifier sent in API requests (e.g., `"llama3:8b-instruct-q5_K_M"`). |
| `dontIncludeModel` | bool | Yes | If true, omit model name from request payload. |
| `promptTemplate` | string | Yes | Prompt template name (from `PromptTemplates/`). Used for completions-style formatting. |
| `apiKey` | string | No | API key for authentication (sent as Bearer token). |
| `addGenerationPrompt` | bool | No | Append assistant turn prefix to signal model to begin generating. |
| `backupEndpointName` | string | No | Name of another endpoint in the same `Endpoints/` subdirectory to fail over to if a request to this endpoint raises **any** exception (connection error, request timeout, HTTP error, or any other backend failure). Failover fires at most once per distinct endpoint; cycles are detected and rejected. |
| `backupPresetName` | string | No | Preset name the backup loads on failover. Defaults to the originating request's preset name, resolved against the backup's own preset type. Set it when the backup's API type has no preset of that name. |
| `allowRemoteBackup` | bool | false | Opt-in for a public-IP backup. Failover sends the prompt to the backup's host, so a public-IP backup is blocked by default; set `true` on the backup endpoint to permit off-machine failover. Loopback/private/LAN backups are always allowed; hostname backups are allowed but logged. |

### Context Window Management

Optional; both default to "no change". The clamp trims the **conversation only** to fit the window (dropping oldest whole messages); it **never** edits the authored `prompt` / `systemPrompt` (an oversized authored prompt is warned about and sent as-is). The estimation level is **internal budgeting only and is never sent to the engine**.

| Field | Type | Default | Description |
|---|---|---|---|
| `clampPromptToContextWindow` | bool | `false` | Master switch for context-window awareness. When `true`, conversations built for this endpoint are bounded to `maxContextTokenSize` (response budget reserved) by dropping the oldest whole messages. Resolved node > endpoint > user > default off. |
| `wilmerContextEstimationLevel` | string | `"conservative"` | Calibrates Wilmer's conservative token estimator for this model so window budgets reclaim headroom the estimate wastes on efficient tokenizers. One of `conservative` (1.0), `balanced` (1.25), `aggressive` (1.5), `xaggressive` (1.85). Active only while the clamp is on; unknown values fall back to `conservative` with a warning. |

### Prompt Injection

| Field | Type | Description |
|---|---|---|
| `addTextToStartOfSystem` | bool | Enable prepending text to system prompt. |
| `textToAddToStartOfSystem` | string | Text to prepend (e.g., `"/no_think "`). |
| `addTextToStartOfPrompt` | bool | Enable prepending text to user prompt. |
| `textToAddToStartOfPrompt` | string | Text to prepend. |
| `addTextToStartOfCompletion` | bool | Enable seeding the assistant's response. |
| `textToAddToStartOfCompletion` | string | Text to seed (e.g., `"<think>"`). |
| `ensureTextAddedToAssistantWhenChatCompletion` | bool | If true, create a new assistant message for the seed text instead of appending to last message. |
| `backendSupportsToolTurns` | bool | Default `true`. Set `false` when the model's chat template cannot render native tool turns; `appendNativeToolExchange` nodes then fall back to text-transcript delivery for this endpoint. |

### Response Cleaning

Applied in order: think tag removal, custom prefix removal, whitespace trimming.

| Field | Type | Description |
|---|---|---|
| `removeThinking` | bool | Enable think block removal. |
| `startThinkTag` | string | Opening tag (e.g., `"<think>"`). Case-insensitive. |
| `endThinkTag` | string | Closing tag (e.g., `"</think>"`). Case-insensitive. |
| `openingTagGracePeriod` | int | Window (chars) at response start in which the opening tag must begin. Default 100. |
| `expectOnlyClosingThinkTag` | bool | Discard all text until `endThinkTag` is found (for models that omit the opening tag). |
| `removeCustomTextFromResponseStartEndpointWide` | bool | Enable prefix removal. |
| `responseStartTextToRemoveEndpointWide` | array | List of strings; first match at response start is removed. |
| `trimBeginningAndEndLineBreaks` | bool | Strip leading/trailing whitespace from response. |

---

## ApiType Config

**Location:** `Public/Configs/ApiTypes/<name>.json`

Defines how WilmerAI communicates with a specific type of LLM backend. Acts as a "driver" that maps
property names to what the backend API expects.

| Field | Type | Description |
|---|---|---|
| `type` | string | **Critical.** Selects the internal handler. Valid values: `"openAIChatCompletion"`, `"openAIV1Completion"`, `"claudeMessages"`, `"koboldCppGenerate"`, `"ollamaApiChat"`, `"ollamaApiGenerate"`. Embeddings-only values (endpoint cannot generate text): `"openAIEmbeddings"`, `"ollamaEmbeddings"`. |
| `presetType` | string | Subfolder in `Presets/` to load generation params from (e.g., `"Ollama"`, `"OpenAiCompatibleApis"`). |
| `truncateLengthPropertyName` | string/null | API key name for max context size (e.g., `"max_context_length"`). Null if not applicable. |
| `maxNewTokensPropertyName` | string | API key name for max response tokens (e.g., `"max_tokens"`, `"num_predict"`, `"max_length"`). |
| `streamPropertyName` | string | API key name for streaming flag (usually `"stream"`). |
| `structuredOutput` | object | Optional, declarative. `{"field": <payload key, dotted for nesting>, "style": "openaiJsonSchema"\|"raw"}`. E.g. `{"field":"response_format","style":"openaiJsonSchema"}` (llama.cpp/LM Studio/vLLM/OpenAI), `{"field":"format","style":"raw"}` (Ollama), `{"field":"structured_outputs.json","style":"raw"}` (vLLM native). Omit for backends without support (e.g. mlx-lm). Enables tool enforcement and `structuredOutputFile`. |

### Pre-defined ApiTypes

| Config Name | Backend |
|---|---|
| `Open-AI-API` | OpenAI-compatible chat completions |
| `OpenAI-Compatible-Completions` | OpenAI-compatible text completions |
| `Claude` | Anthropic Claude Messages API |
| `OllamaApiChat` | Ollama chat completions |
| `OllamaApiGenerate` | Ollama text completions |
| `KoboldCpp` | KoboldCpp text completions |
| `LlamaCppServer` | Llama.cpp chat completions |
| `Text-Generation-WebUI` | Text Generation WebUI chat completions |
| `mlx-lm` | Apple MLX model server |
| `OpenAI-Embeddings` | Embeddings via `/v1/embeddings` (OpenAI, llama.cpp `--embedding`, compatible servers) |
| `Ollama-Embeddings` | Embeddings via Ollama `/api/embed` (e.g. `nomic-embed-text`) |

**Embeddings endpoints**: an Endpoints file referencing an embeddings ApiType only needs `endpoint`,
`apiTypeConfigFileName`, `modelNameToSendToAPI`, and optionally `apiKey`. No preset, prompt template, or
generation fields apply. Referenced by `embeddingEndpointName` (memory settings file and/or the
`VectorMemorySearch` node) to enable semantic/hybrid memory search.

---

## Preset Config

**Location:** `Public/Configs/Presets/<ApiPresetType>/[username]/<name>.json`

Defines LLM generation parameters (temperature, top_p, etc.). Key-value pairs are injected directly into
the API request payload. The parameter names must be valid for the target backend.

**Lookup order:** User-specific path first (`<ApiPresetType>/<username>/<preset>.json`), then global
(`<ApiPresetType>/<preset>.json`).

**Important:** Max response tokens are controlled by the workflow node's `maxResponseSizeInTokens`, not by the preset.

Example:
```json
{
  "temperature": 0.7,
  "top_p": 0.9,
  "top_k": 0,
  "rep_pen": 1.1,
  "stop_sequence": ["Human:", "<|im_end|>"]
}
```

For Ollama backends, the handler automatically nests these under an `options` object.

---

## Routing Config

**Location:** `Public/Configs/Routing/<name>.json`

Maps prompt categories to workflows. Used when `customWorkflowOverride` is false.

Structure: each top-level key is a category name (convention: `UPPERCASE_SNAKE_CASE`). Value is an object with:

| Field | Type | Description |
|---|---|---|
| `description` | string | Injected into the categorization prompt to help the LLM choose this category. |
| `workflow` | string | Workflow filename (without `.json`) to execute if this category is selected. |

Example:
```json
{
  "CODING": {
    "description": "Requests involving writing, editing, or discussing code.",
    "workflow": "CodingWorkflow"
  },
  "FACTUAL": {
    "description": "Requests requiring factual, encyclopedic information.",
    "workflow": "FactualWorkflow-With-RAG"
  },
  "CONVERSATIONAL": {
    "description": "Casual conversation or anything not in other categories.",
    "workflow": "DefaultConversationalWorkflow"
  }
}
```

**Routing process:** The categorization workflow runs, outputs a category name, it's matched (case-insensitively)
to a key in this file, and the corresponding workflow executes. If no match, `_DefaultWorkflow` runs.

### Categorization Prompt Variables

These variables are auto-generated from the routing config and available in the categorization workflow:

| Variable | Description |
|---|---|
| `{category_colon_descriptions}` | `"CODING: description; FACTUAL: description; ..."` |
| `{category_colon_descriptions_newline_bulletpoint}` | Each category on a new line with `- ` prefix. |
| `{categoriesSeparatedByOr}` | `"CODING or FACTUAL or CONVERSATIONAL"` |
| `{categoryNameBulletpoints}` | Bulleted list of category names. |
| `{category_list}` | Python `list` of category names (renders as a list repr, e.g. `['CODING', 'FACTUAL']`, when interpolated). For a plain string use `{categoriesSeparatedByOr}` or `{categoryNameBulletpoints}`. |
| `{category_descriptions}` | Python `list` of descriptions (renders as a list repr when interpolated). For plain-string contexts use `{category_colon_descriptions}` or `{category_colon_descriptions_newline_bulletpoint}`. |

---

## Prompt Template Config

**Location:** `Public/Configs/PromptTemplates/<name>.json`

Defines how to format conversation history into a single string for **completions-style APIs** (KoboldCpp,
older OpenAI, etc.). Ignored by chat completions APIs that accept structured message arrays.

| Field | Description |
|---|---|
| `promptTemplateSystemPrefix` | Inserted before system prompt content. |
| `promptTemplateSystemSuffix` | Inserted after system prompt content. |
| `promptTemplateUserPrefix` | Inserted before each user message. |
| `promptTemplateUserSuffix` | Inserted after each user message. |
| `promptTemplateAssistantPrefix` | Inserted before each assistant message. Also appended at end to cue generation. |
| `promptTemplateAssistantSuffix` | Inserted after each assistant message. Omitted from the final assistant turn. |
| `promptTemplateEndToken` | Special token appended to end of formatted prompt (controlled by `addGenerationPrompt`). |

Example (Llama 3):
```json
{
  "promptTemplateSystemPrefix": "<|start_header_id|>system<|end_header_id|>\n\n",
  "promptTemplateSystemSuffix": "<|eot_id|>",
  "promptTemplateUserPrefix": "<|start_header_id|>user<|end_header_id|>\n\n",
  "promptTemplateUserSuffix": "<|eot_id|>",
  "promptTemplateAssistantPrefix": "<|start_header_id|>assistant<|end_header_id|>\n\n",
  "promptTemplateAssistantSuffix": "<|eot_id|>"
}
```

The built-in `_chatonly` template uses only newlines, suitable for models without special tokens.

---

## Memory Settings File

**Location:** `Public/Configs/Workflows/<username>/_DiscussionId-MemoryFile-Workflow-Settings.json`

Configures the memory system per-discussion.

### Key Fields

| Field | Type | Description |
|---|---|---|
| `useVectorForQualityMemory` | bool | If true, `QualityMemory` node writes to vector DB; if false, to file-based memory. |
| `endpointName` | string | Default LLM endpoint for memory generation. |
| `preset` | string | Default generation preset. |
| `maxResponseSizeInTokens` | int | Default max tokens for memory LLM calls. |
| `lookbackStartTurn` | int | Exclude the most recent N turns from memory generation. |
| `wilmerContextEstimationLevel` | string | Optional. Calibrates the conservative token estimator for the memory chunking thresholds (`vectorMemoryChunkEstimatedTokenSize`, `chunkEstimatedTokenSize`) so chunks hold the intended real content on efficient tokenizers. One of `conservative` (1.0, default, no change), `balanced` (1.25), `aggressive` (1.5), `xaggressive` (1.85). Config-local: applies whenever set, independent of `clampPromptToContextWindow`. |

### Vector Memory Config

| Field | Description |
|---|---|
| `vectorMemoryWorkflowName` | Optional workflow for generating structured vector memory JSON. |
| `vectorMemoryEndpointName` | Endpoint for vector memory generation (fallback if no workflow). |
| `vectorMemoryPreset` | Preset for vector memory generation. |
| `vectorMemoryMaxResponseSizeInTokens` | Max tokens for vector memory. |
| `vectorMemoryChunkEstimatedTokenSize` | Token threshold for triggering vector memory creation. |
| `vectorMemoryMaxMessagesBetweenChunks` | Message count threshold for vector memory. |
| `vectorMemoryIndexTopics` | Optional, default false. Write-time topic indexing: folds the memory metadata's `topics` list into the searchable index (the key_phrases column) as each memory is written, so keyword searches can match a memory by its conversation-level topic (e.g. the campaign, project, or event a fact belongs to) even when the memory text never restates it. Off indexes exactly what was indexed historically. |
| `embeddingEndpointName` | Optional. Embeddings endpoint (ApiType `openAIEmbeddings`/`ollamaEmbeddings`). When set, new vector memories are embedded on write, enabling `searchMode: semantic`/`hybrid` on `VectorMemorySearch`. |
| `embeddingBackfillBatchSize` | Optional, default 20. Older un-embedded memories embedded per processed chunk (a single memory pass may process several chunks; lazy backfill). 0 disables. Bulk alternative: `Scripts/backfill_embeddings.py`. |
| `useStateDocument` | Optional, default false. Vector path only: merge newly stored facts into `state_document.md` via a sub-workflow. |
| `stateDocumentWorkflowName` | Required if `useStateDocument`. Merge workflow; receives new facts as `{agent1Input}`, current document as `{agent2Input}`; output replaces the document. |
| `stateDocumentMinRetentionRatio` | Optional, default 0.5. Shrink guard: merge output smaller than this fraction of the current document is rejected. 0 disables. |

### File-Based Memory Config

| Field | Description |
|---|---|
| `fileMemoryWorkflowName` | Optional workflow for generating file-based memory summaries. |
| `systemPrompt` | System prompt for file memory LLM (used if no workflow). Must contain context for summarization. |
| `prompt` | User prompt for file memory. Use `[TextChunk]` placeholder for the text to summarize. |
| `chunkEstimatedTokenSize` | Token threshold for triggering file memory creation. |
| `maxMessagesBetweenChunks` | Message count threshold for file memory. |

Memory generates when **either threshold** is reached first (whichever happens sooner).

### Condensation Config (optional, same file)

| Field | Description |
|---|---|
| `condenseMemories` | Bool. Enable automatic consolidation of older file-based memories. Default: false. |
| `memoriesBeforeCondensation` | Int. How many new memories trigger a condensation pass. |
| `memoryCondensationBuffer` | Int. Most recent memories to keep granular (excluded from condensation). Default: 0. |
| `condenseMemoriesEndpointName` | Optional endpoint override for condensation LLM. |
| `condenseMemoriesPreset` | Optional preset override. |
| `condenseMemoriesSystemPrompt` | Custom system prompt for condensation. |
| `condenseMemoriesPrompt` | Custom prompt. Placeholders: `[MemoriesToCondense]`, `[Memories_Before_Memories_to_Condense]`. |
| `condenseMemoriesMaxResponseSizeInTokens` | Optional max token override. |
| `condensationLockTimeoutSeconds` | Float. Bounded wait for the per-discussion memory lock before skipping this round (memory generation retries next qualifying turn). Default: 600. Set to 0 or negative to wait indefinitely. |

### Important: Vector and File Memories Can Coexist

The `useVectorForQualityMemory` flag only controls what the `QualityMemory` node does. File-based memory
creation is triggered independently by `RecentMemory`, `FullChatSummary` (when `isManualConfig` is false),
and other update-capable nodes. This means you can set `useVectorForQualityMemory: true` to have
`QualityMemory` write to the vector DB, while also using `FullChatSummary` or `RecentMemory` nodes to
maintain file-based memories and the rolling summary simultaneously.

To run both systems, configure both the vector and file sections of this settings file with appropriate
endpoints, presets, and thresholds.

---

## Context Compactor Settings File

**Location:** `Public/Configs/Workflows/<username>/<contextCompactorSettingsFile>.json`

Referenced by the `contextCompactorSettingsFile` field in the user config. This is a **separate file** from
the memory settings; the ContextCompactor is independent of the memory system.

### Settings

| Field | Type | Default | Description |
|---|---|---|---|
| `endpointName` | string | required | LLM endpoint for summarization calls. |
| `preset` | string | required | Generation preset for summarization. |
| `maxResponseSizeInTokens` | int | 750 | Max tokens per LLM response. |
| `recentContextTokens` | int | 20000 | Token budget for the Recent window (kept untouched). |
| `oldContextTokens` | int | 20000 | Token budget for the Old window (summarized with topic focus). |
| `lookbackStartTurn` | int | 5 | Most recent messages to skip before calculating windows. |
| `wilmerContextEstimationLevel` | string | conservative | Optional. Calibrates the conservative token estimator for the `recentContextTokens` / `oldContextTokens` budgets so each section holds the intended real content on efficient tokenizers. One of `conservative` (1.0, no change), `balanced` (1.25), `aggressive` (1.5), `xaggressive` (1.85). Config-local: applies whenever set, independent of `clampPromptToContextWindow`. |
| `oldSectionSystemPrompt` | string | default | System prompt for Old section summarization. |
| `oldSectionPrompt` | string | default | User prompt. Placeholders: `[MESSAGES_TO_SUMMARIZE]`, `[RECENT_MESSAGES]`. |
| `neutralSummarySystemPrompt` | string | default | System prompt for neutral summary (when messages shift to Oldest). |
| `neutralSummaryPrompt` | string | default | User prompt. Placeholder: `[MESSAGES_TO_SUMMARIZE]`. |
| `oldestUpdateSystemPrompt` | string | default | System prompt for updating the Oldest rolling summary. |
| `oldestUpdatePrompt` | string | default | User prompt. Placeholders: `[EXISTING_SUMMARY]`, `[NEW_CONTENT]`. |

### How ContextCompactor Differs from ChatSummary

| Aspect | ChatSummary (Memory System) | ContextCompactor |
|---|---|---|
| Input source | Summarizes memories (already summaries) | Directly summarizes raw conversation messages |
| Topic awareness | Neutral high-level overview | Old section is topic-focused based on recent messages |
| Detail level | Compressed twice, high-level | More granular, especially in Old section |
| Dependencies | Part of memory system, needs memory nodes | Independent, reads messages directly |
| Output | Single summary string | Two XML-tagged sections (Old + Oldest) |
| Best for | Long-term broad context | Detailed mid-range context with topic relevance |

You can use both in the same workflow. ChatSummary provides the broad strokes; ContextCompactor provides
more detail about recent-to-middle conversation with awareness of the current topic.

### Example Settings File

```json
{
  "endpointName": "Memory-Endpoint",
  "preset": "Memory-Preset",
  "maxResponseSizeInTokens": 750,
  "recentContextTokens": 20000,
  "oldContextTokens": 20000,
  "lookbackStartTurn": 5,
  "oldSectionSystemPrompt": "You are a summarization AI. Summarize the conversation section, focusing on details relevant to the current topic.",
  "oldSectionPrompt": "Summarize this excerpt:\n\n[MESSAGES_TO_SUMMARIZE]\n\nCurrent conversation context:\n\n[RECENT_MESSAGES]\n\nFocus on details relevant to the current topic. Use participant names.",
  "neutralSummarySystemPrompt": "You are a summarization AI. Provide a neutral summary of the conversation excerpt.",
  "neutralSummaryPrompt": "Summarize this excerpt neutrally:\n\n[MESSAGES_TO_SUMMARIZE]",
  "oldestUpdateSystemPrompt": "You are a summarization AI. Incorporate new content into the existing rolling summary.",
  "oldestUpdatePrompt": "Existing summary:\n\n[EXISTING_SUMMARY]\n\nNew content:\n\n[NEW_CONTENT]\n\nProduce an updated summary."
}
```

### User Config Setup

Add to your user JSON:
```json
{
  "contextCompactorSettingsFile": "_DiscussionId-ContextCompactor-Settings"
}
```

---

## MCP Server Registry

**Location:** `Public/Configs/MCPServers/<name>.json`

Each file defines one MCP server. The base filename (without `.json`) is the value put in an `MCPToolCall` node's
`server` field. The MCP SDK supports three transports; pick one per file via the `transport` field.

### stdio (spawns a local subprocess)

| Field | Type | Required | Description |
|---|---|---|---|
| `transport` | string | Yes | `"stdio"`. |
| `command` | string | Yes | Binary to execute (e.g., a path to a locally installed MCP server; `"npx"` also works but fetches the package on demand). |
| `args` | array | No | Command-line arguments (default `[]`). |
| `env` | object | No | Environment variables for the subprocess. When omitted, the subprocess gets a minimal default environment from the MCP SDK (not Wilmer's full environment). |
| `cwd` | string | No | Working directory for the subprocess. |

### sse (Server-Sent Events over HTTP)

| Field | Type | Required | Description |
|---|---|---|---|
| `transport` | string | Yes | `"sse"`. |
| `url` | string | Yes | The SSE endpoint URL. |
| `headers` | object | No | Headers to send (typically auth). |

### streamable_http (bi-directional HTTP)

| Field | Type | Required | Description |
|---|---|---|---|
| `transport` | string | Yes | `"streamable_http"`. |
| `url` | string | Yes | The MCP HTTP endpoint URL. |
| `headers` | object | No | Headers to send. |
