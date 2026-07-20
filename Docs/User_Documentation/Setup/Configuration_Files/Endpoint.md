### **`Endpoint` Configuration Files**

The Endpoint configuration files define a connection to a specific Large Language Model (LLM) backend. Each JSON file in
the `Public/Configs/Endpoints/` directory tells the WilmerAI middleware the server's address, its API format, and a set
of rules for injecting text into prompts and cleaning the model's raw responses.

-----

#### **Field Definitions**

Each Endpoint JSON file contains a single object with the following key-value pairs, organized by function.

-----

#### **Embeddings Endpoints**

An endpoint whose `apiTypeConfigFileName` references an embeddings ApiType (`OpenAI-Embeddings` or
`Ollama-Embeddings`; see the ApiTypes documentation) is an **embeddings endpoint**, used by the memory system's
semantic search rather than for text generation. Workflow nodes cannot reference it as a generation endpoint;
attempting to do so fails with a clear error. Only four fields apply: `endpoint`, `apiTypeConfigFileName`,
`modelNameToSendToAPI`, and optionally `apiKey` (plus `dontIncludeModel`). Presets, prompt templates, and all
injection/cleaning fields are ignored.

*Complete example (`Embedding-Endpoint.json`):*

```json
{
  "modelNameForDisplayOnly": "Embeddings (for semantic memory search; point at a llama.cpp server started with --embedding, or any /v1/embeddings server)",
  "endpoint": "http://127.0.0.1:8081",
  "apiTypeConfigFileName": "OpenAI-Embeddings",
  "modelNameToSendToAPI": "nomic-embed-text",
  "dontIncludeModel": false,
  "apiKey": ""
}
```

Reference it from the discussion memory settings (`embeddingEndpointName`) to embed memories as they are written,
and from a `VectorMemorySearch` node (`embeddingEndpointName` with `searchMode: "semantic"` or `"hybrid"`) to
search them. Working examples ship in `Endpoints/_example_users/Embedding-Endpoint.json` and
`Endpoints/_example-endpoints/embeddings-*.json`.

-----

#### **Core Connection Details**

These fields are essential for establishing a connection to the LLM server.

##### `endpoint`

* **Description**: The full URL of the LLM API server, such as an OpenAI-compatible service.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"http://localhost:11434"`

##### `apiTypeConfigFileName`

* **Description**: The name of the JSON file (without the `.json` extension) from the `Public/Configs/ApiTypes/`
  directory. This file defines the specific API schema (e.g., Ollama, KoboldCpp, OpenAI) that WilmerAI should use for
  this endpoint.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"Ollama"`

##### `maxContextTokenSize`

* **Description**: The maximum context size in tokens that the model can handle. This value is used by the corresponding
  `ApiTypes` configuration to set the model's truncation length property.
* **Data Type**: `integer`
* **Required**: Yes
* **Example**: `8192`

-----

#### **Context Window Management**

These optional fields control how Wilmer keeps the prompts it builds for this endpoint inside the model's context
window. Both default to "off / no change", so existing endpoints behave exactly as before unless you opt in.

##### `clampPromptToContextWindow`

* **Description**: The master switch for context window awareness. When `true`, Wilmer bounds every conversation it
  builds for a node on this endpoint so the request fits within `maxContextTokenSize` (its own response budget
  reserved), by dropping the **oldest whole conversation messages** until it fits. It trims the **conversation only**;
  it never edits the operator's authored `prompt` / `systemPrompt`. If an authored prompt is itself too large, Wilmer
  logs a warning and sends it as-is (a visible backend rejection is preferred over silently dropping your
  instructions). When `false` (the default), Wilmer makes no window-based decisions and the conversation is sent as
  selected. This can also be set per node (highest priority) or on the user config (lowest), resolved
  node > endpoint > user > default `false`.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

##### `wilmerContextEstimationLevel`

* **Description**: Calibrates Wilmer's deliberately conservative token estimator for this endpoint's model. The
  estimator never under-counts (so it is safe on dense text and small-vocabulary tokenizers), but it can over-count
  real tokens by up to ~1.85x on efficient large-vocabulary models, which wastes most of a big context window. This
  level scales the budgets Wilmer derives from the window so they reclaim that wasted headroom. It is **internal
  budgeting only and is never sent to the inference engine** (it never changes `maxContextTokenSize` /
  `truncate_length`). It is active only while `clampPromptToContextWindow` is on for the node; with the clamp off it
  has no effect. Allowed values and their budget multipliers: `conservative` (1.0, the default, no change),
  `balanced` (1.25), `aggressive` (1.5), `xaggressive` (1.85). An unknown or non-string value falls back to
  `conservative` with a one-time warning.
* **Data Type**: `string`
* **Required**: No
* **Default**: `"conservative"`
* **Example**: `"aggressive"`

-----

#### **Model Identification**

These fields control how the model is identified in the API request.

##### `modelNameForDisplayOnly`

* **Description**: A human-readable name for this endpoint configuration. This field is for your reference only and is *
  *not used by the application logic**.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"Local Llama3 for Summaries"`

##### `modelNameToSendToAPI`

* **Description**: The specific model identifier to be included in the API request payload. This is necessary for
  multi-model servers like Ollama or OpenAI.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"llama3:8b-instruct-q5_K_M"`

##### `dontIncludeModel`

* **Description**: If `true`, the `modelNameToSendToAPI` field and its corresponding key will be omitted from the API
  request payload. This is useful for single-model servers that do not accept a model parameter.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `promptTemplate`

* **Description**: The name of the prompt template file (without the `.json` extension) from the
  `Public/Configs/PromptTemplates/` directory. This template defines how conversation history is formatted for
  Completions-style APIs. For Chat Completions APIs, the template is not used for formatting but is still required
  in the configuration.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"llama3"`

##### `addGenerationPrompt`

* **Description**: If `true`, a generation prompt (such as the assistant turn prefix from the prompt template) is
  appended to the end of the formatted prompt. This signals to the model that it should begin generating a response.
  Can be overridden at the node level via `forceGenerationPromptIfEndpointAllows` or `blockGenerationPrompt`.
* **Data Type**: `boolean`
* **Required**: No
* **Example**: `true`

##### `apiKey`

* **Description**: The API key to use for authentication when connecting to the LLM backend. This is sent as a
  Bearer token in the Authorization header. Leave empty or omit for backends that do not require authentication.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"sk-your-api-key-here"`

-----

#### **Failover**

##### `backupEndpointName`

* **Description**: The name of another endpoint configuration (without the `.json` extension) from the
  `Public/Configs/Endpoints/` directory to use as a backup if this endpoint fails. If the primary endpoint raises
  any exception during a request (for example, a connection refusal, the remote host being unreachable, an HTTP 5xx
  response that cannot be recovered, or any other error from the backend), the middleware will transparently retry
  the same request against the backup endpoint. The backup's JSON is loaded independently, so the backup may point to
  a completely different server, API type, model, and even its own `backupEndpointName` to chain further: for
  example, `General-Endpoint` -> `General-Backup-Endpoint` -> `General-Second-Backup-Endpoint`. Cycles are detected;
  if a chain loops back on itself (e.g., `A` -> `B` -> `A`), the request is aborted with a clear error. Any backend
  exception, including connection errors and request timeouts, triggers failover. To avoid prematurely switching
  away from slow local models that legitimately take many minutes to respond, the backend read timeout is configured
  generously, so a model that is still generating is not cut off mid-response. (This is distinct from the
  concurrency slot-wait timeout, which does not trigger failover.) For streaming requests, failover is only possible
  before the first token is sent to the client; once any part of the response has been streamed, the original
  failure is reported rather than retried against a backup.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"General-Backup-Endpoint"`

##### `backupPresetName`

* **Description**: The preset name the backup endpoint should load when failover delegates to it. By default the
  backup is constructed with the **originating request's preset name**, the same name the primary was called with.
  That name is then resolved against the *backup's own* preset type (its `Presets/<presetType>/` directory). This is
  fine when the same preset name exists for every API type involved (the shipped example configs mirror identical
  preset filenames across each type directory), but a heterogeneous failover (say an OpenAI primary failing over to a
  Claude backup) breaks if the originating preset name has no file in the backup type's directory: construction would
  raise `FileNotFoundError` mid-failover. Set `backupPresetName` on the primary endpoint to the preset the backup
  should use instead, and the backup will load that name rather than inheriting the primary's. Leave it unset to keep
  the inherited-name behavior.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"Claude-Backup-Preset"`

##### `allowRemoteBackup`

* **Description**: Opt-in acknowledgement that this endpoint may receive failover traffic even though its host is a
  public address. Failover forwards the full conversation and prompt to the backup, so Wilmer **blocks failover to a
  backup whose host is a public IP by default** (safe-by-default): a primary that fails over to such a backup raises a
  clear error instead of silently sending the prompt off-machine. Set `allowRemoteBackup` to `true` on the **backup
  endpoint** to permit it. This flag is only needed for a backup at a *public IP literal*: a backup on loopback or a
  private/LAN address (`127.0.0.1`, `10.x`, `172.16-31.x`, `192.168.x`, `localhost`) is treated as local and never
  blocked, and a backup referenced by *hostname* (which cannot be classified without DNS) is allowed but logged loudly
  as possible off-machine egress.
* **Data Type**: `boolean`
* **Required**: No (required only to use a public-IP backup)
* **Example**: `true`

When a failover occurs, it is logged at `WARNING` level so that the swap is visible in the logs, which is useful for
diagnosing intermittent connectivity issues. When a failover is triggered, the internal retry behaviour of the primary
endpoint is also suppressed: instead of spending time retrying HTTP 5xx responses or connection errors on the primary,
the middleware moves to the backup on the first failure so that the user-facing delay is minimised. Endpoints at the
tail of a failover chain (with no backup of their own) retain their normal retry behaviour.

**Data egress note.** Failover forwards the full request (conversation, system prompt, prompt) to whatever
`backupEndpointName` resolves to, using that backup's own URL and API key. Because a transient *local* failure could
otherwise send the user's prompt off-machine silently, the egress guard above applies: a public-IP backup is blocked
unless it sets `allowRemoteBackup: true`, a hostname backup is allowed but logged loudly, and a local/LAN backup is
allowed silently. The guard classifies the host only by address; it does not inspect what the backend then does with
the data. Be deliberate about pairing a local primary with any non-local backup if the prompt content should never
leave the machine.

-----

#### **Prompt & Content Injection**

These settings allow for adding text to different parts of the prompt before it is sent to the LLM.

##### `addTextToStartOfSystem`

* **Description**: A flag that, when `true`, prepends the content of `textToAddToStartOfSystem` to the system prompt.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `textToAddToStartOfSystem`

* **Description**: The string content to prepend to the system prompt when `addTextToStartOfSystem` is enabled.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"/no_think "`

##### `addTextToStartOfPrompt`

* **Description**: A flag that, when `true`, prepends the content of `textToAddToStartOfPrompt` to the final user
  prompt. For Chat Completion APIs, this modifies the content of the last message with `role: "user"`.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

##### `textToAddToStartOfPrompt`

* **Description**: The string content to prepend to the user prompt when `addTextToStartOfPrompt` is enabled.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `""`

##### `addTextToStartOfCompletion`

* **Description**: A flag that, when `true`, appends the content of `textToAddToStartOfCompletion` to the end of the
  context to "seed" the AI's response, forcing it to begin its generation with the specified text.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `textToAddToStartOfCompletion`

* **Description**: The string content used to seed the AI's response when `addTextToStartOfCompletion` is enabled.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"<think>First, I will analyze the user's request.</think>"`

##### `ensureTextAddedToAssistantWhenChatCompletion`

* **Description**: Modifies the behavior of `addTextToStartOfCompletion` for Chat Completion APIs. If `true` and the
  last message is not from the assistant, a new `role: "assistant"` message is added containing the seed text. If
  `false`, the text is appended to the content of the last message, regardless of its role.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `backendSupportsToolTurns`

* **Description**: Declares whether the backing model's chat template can render native tool turns (assistant
  `tool_calls` messages and `role: "tool"` results). Defaults to `true` when absent. Set to `false` for backends
  whose templates lack tool support (older models, strict-alternation templates): any workflow node with
  `appendNativeToolExchange` enabled then falls back to the text-transcript behavior for this endpoint instead of
  sending tool turns the template would reject. This lets one old backend opt out without editing every workflow
  that sets the flag, which is relevant when frontends allow switching a tool-history conversation onto a different
  model mid-chat.
* **Data Type**: `boolean`
* **Required**: No (default `true`)
* **Example**: `false`

-----

#### **Response Cleaning & Filtering**

These settings process the raw text from the LLM after it is received. Operations are applied in this order: 1) Thinking
Block Removal, 2) Custom Prefix Removal, 3) Whitespace Trimming.

##### `removeThinking`

* **Description**: The master switch for the thinking block removal feature. If `true`, the system will attempt to find
  and remove text between `startThinkTag` and `endThinkTag`. Only the first thinking block in a response is removed;
  if a matching `endThinkTag` is never found, the response is left unmodified.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

##### `startThinkTag`

* **Description**: The opening tag that marks the beginning of a "thinking" block to be removed from the response.
  Case-insensitive.
* **Data Type**: `string`
* **Required**: Only when `removeThinking` is `true` (if missing, the feature disables itself with a warning).
* **Example**: `"<think>"`

##### `endThinkTag`

* **Description**: The closing tag that marks the end of a "thinking" block. Case-insensitive.
* **Data Type**: `string`
* **Required**: Only when `removeThinking` is `true` (if missing, the feature disables itself with a warning).
* **Example**: `"</think>"`

##### `openingTagGracePeriod`

* **Description**: The size, in characters, of the window at the start of the response in which a `startThinkTag` must
  **begin** for the thinking block to be removed. The tag only needs to start inside this window; it may end beyond
  it. If no tag starts within the window, removal is skipped for that response.
* **Data Type**: `integer`
* **Required**: No
* **Default**: `100`
* **Example**: `100`

##### `expectOnlyClosingThinkTag`

* **Description**: A special mode for models that may omit the opening tag. If `true`, the system buffers and discards
  all text up to and including the first `endThinkTag`, then begins streaming the subsequent text. If the tag never
  appears, the full response is returned unmodified.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `false`

##### `removeCustomTextFromResponseStartEndpointWide`

* **Description**: If `true`, enables the removal of one of the strings defined in
  `responseStartTextToRemoveEndpointWide` from the beginning of the LLM's response.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

##### `responseStartTextToRemoveEndpointWide`

* **Description**: A list of strings to remove from the beginning of the response. The system removes the first string
  in the list that it finds a match for.
* **Data Type**: `list of strings`
* **Required**: Yes
* **Example**: `["Assistant:", "Okay, here is the information you requested:"]`

##### `trimBeginningAndEndLineBreaks`

* **Description**: If `true`, any leading or trailing whitespace (spaces, newlines, tabs) is removed from the final
  response.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

#### **Embedded Samplers (`presetSamplers`)**

Instead of hand-writing a separate preset file for every API type, you can describe your generation
samplers **once, directly on the endpoint**, in a single canonical vocabulary. WilmerAI translates
those values into whatever field names the endpoint's API type actually expects at request time.

The canonical vocabulary is **llama.cpp's** sampler field set. You always write `temperature`,
`top_p`, `repeat_penalty`, `min_p`, and so on, and Wilmer renames them per backend (for example
`repeat_penalty` becomes `rep_pen` for KoboldCpp, `repetition_penalty` for mlx-lm, and stays
`repeat_penalty` for Ollama).

**The benefit:** change the endpoint's `apiTypeConfigFileName` and Wilmer handles the rest.
The same `presetSamplers` block works against any backend; fields the new API type does not support
are **dropped (with a log line)** rather than sent and rejected. You do not have to maintain a
parallel preset file per backend.

##### How a node selects an embedded block

A workflow node's `preset` value is resolved as an **endpoint name** first:

1. If the `preset` value matches an endpoint that has a `presetSamplers` block, that block is
   translated to the **calling** endpoint's API type and used.
2. Otherwise Wilmer falls back to the legacy `Public/Configs/Presets/...` folder file of that name
   (unchanged behavior).

The common case is a node pointing its `preset` at the same endpoint it is calling. Because the block
is stored in canonical form, one endpoint can also **borrow** another endpoint's samplers just by
naming it (`"preset": "Some-Other-Endpoint"`), even across different API types; the values are
translated to whichever endpoint is actually being called.

> Existing setups are unaffected: legacy preset names (e.g. `General-Preset`) do not match any
> endpoint, so they keep resolving to the folder file exactly as before. Adopt embedded samplers
> per node, at your own pace, by pointing a node's `preset` at an endpoint that defines a block.

##### `presetSamplers`

* **Description**: An object of canonical (llama.cpp-named) sampler values for this endpoint. Only the
  keys you write are sent; nothing is padded with defaults. A key the target API type does not support
  is dropped with a warning. A key that is not a known canonical field is treated as a typo and
  dropped with a warning.
* **Data Type**: `object`
* **Required**: No
* **Canonical keys**:
  ```
  temperature  dynatemp_range  dynatemp_exponent  top_k  top_p  min_p  top_n_sigma  typical_p
  repeat_penalty  repeat_last_n  presence_penalty  frequency_penalty
  dry_multiplier  dry_base  dry_allowed_length  dry_penalty_last_n  dry_sequence_breakers
  xtc_probability  xtc_threshold  mirostat  mirostat_tau  mirostat_eta
  seed  stop  samplers  logit_bias  ignore_eos  n_probs  min_keep  grammar  json_schema
  ```
  Plus two special keys: `thinkingMode` and `chat_template_kwargs` (below). Max-tokens, the streaming
  flag, and context size are **not** sampler keys; they come from the node/endpoint as before.

##### `thinkingMode`

* **Description**: Canonical reasoning toggle, written inside `presetSamplers`. Wilmer maps it to each
  backend's native mechanism: `enable_thinking` inside `chat_template_kwargs` for llama.cpp, a
  top-level `think` for Ollama, `reasoning_effort` for OpenAI. On API types with no supported
  mechanism it is dropped with a warning (control thinking on those via the endpoint-level
  `removeThinking` strip instead).
* **Data Type**: `string`
* **Valid Values**: `"off"`, `"on"`, `"low"`, `"medium"`, `"high"`
* **Example**: `"off"`

##### `chat_template_kwargs`

* **Description**: An open passthrough object handed straight to the model's chat template (llama.cpp
  and compatible servers only). Use it for model-specific keys Wilmer does not model, such as
  `thinking_budget`. It is deep-merged with anything `thinkingMode` produces, so you can set both. It
  is **only sent to API types that accept it** (currently `LlamaCppServer`); for others it is dropped.
* **Data Type**: `object`
* **Required**: No
* **Example**: `{ "thinking_budget": 0 }`

##### Omitting a field, and sending a literal `null`

* Set a sampler to `null` to **omit** it entirely (useful when a backend misbehaves if the field is
  present at all). It is the same as not writing the key, but explicit and self-documenting; it also
  lets an `appendPresetName` override delete a value the base block set.
* Set a sampler to the reserved string `"__wilmer_null__"` to send a **literal JSON `null`** for that
  field (rarely needed).

##### `appendPresetName`

* **Description**: The name of a preset file (in `Public/Configs/Presets/<presetType>/`) to merge on
  top of the resolved samplers as the highest-precedence override. Its keys are in the target API
  type's **native** field names (it is not translated), making it the escape hatch for fields Wilmer
  does not model yet. It respects your configured preset subdirectory. On a key collision the append
  file wins.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"Rag-Extra"`

> A complete, copyable example showing every canonical field lives at
> `Public/Configs/Endpoints/_example-endpoints/llama-cpp-server-canonical-samplers.json`. Developers
> can find the per-API field maps and rationale in
> `Docs/Developer_Docs/Features_And_Packages/Sampler_Translation.md`.

-----

#### **Example Endpoint File**

```json
{
  "modelNameForDisplayOnly": "Small model for all tasks",
  "endpoint": "http://127.0.0.1:5000",
  "apiTypeConfigFileName": "KoboldCpp",
  "maxContextTokenSize": 8192,
  "modelNameToSendToAPI": "",
  "promptTemplate": "llama3",
  "trimBeginningAndEndLineBreaks": true,
  "dontIncludeModel": false,
  "removeThinking": true,
  "startThinkTag": "<think>",
  "endThinkTag": "</think>",
  "openingTagGracePeriod": 100,
  "expectOnlyClosingThinkTag": false,
  "addTextToStartOfSystem": true,
  "textToAddToStartOfSystem": "/no_think ",
  "addTextToStartOfPrompt": false,
  "textToAddToStartOfPrompt": "",
  "addTextToStartOfCompletion": false,
  "textToAddToStartOfCompletion": "",
  "ensureTextAddedToAssistantWhenChatCompletion": false,
  "removeCustomTextFromResponseStartEndpointWide": false,
  "responseStartTextToRemoveEndpointWide": []
}
```