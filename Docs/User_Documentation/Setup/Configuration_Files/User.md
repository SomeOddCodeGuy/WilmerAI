### **`User` Configuration Files**

The User configuration file is the central settings file for a specific user instance of WilmerAI. It defines server
behavior, workflow routing, memory management, file paths, and logging.

User configuration files are located in the `Public/Configs/Users/` directory. To add a new user, copy an existing file,
rename it (e.g., `MyUser.json`), and modify its contents. To activate a user configuration, either update the
`_current-user.json` file with the username or use the `--User <username>` command-line argument at startup.

Multiple users can be served from a single Wilmer instance by specifying `--User` multiple times:

```bash
bash run_macos.sh --User user-one --User user-two --User user-three
```

In multi-user mode, per-user `port` settings are ignored. The listening port must be specified via the `--port`
command-line flag; if omitted it defaults to `5050`. The concurrency gate serializes all requests across all users,
protecting shared LLM hardware. The front-end selects a user by setting the model field to the target username
(e.g., `"model": "user-two"` or `"model": "user-two:coding"`).

-----

#### **Field Definitions**

Each User JSON file contains a single object with the following key-value pairs.

##### `port`

* **Description**: Specifies the network port on which the WilmerAI instance will listen. This allows multiple instances
  to run simultaneously. The server binds to `127.0.0.1` (localhost only) by default; use `--listen` to bind to
  `0.0.0.0` for network access. In multi-user mode this setting is ignored; use `--port` on the command line instead
  (defaults to `5050`).
* **Data Type**: `integer`
* **Required**: Yes (single-user mode)
* **Example**: `5006`

-----

##### `stream`

* **Description**: Controls whether LLM responses are streamed back to the client. When enabled, responses are sent incrementally as they are generated rather than waiting for the complete response.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

##### `customWorkflowOverride`

* **Description**: Selects custom workflow mode when `true` and `allowSharedWorkflows` is `false`. In custom workflow
  mode, prompt categorization and routing are bypassed, and all incoming prompts execute the workflow specified in
  `customWorkflow`. This setting is ignored when `allowSharedWorkflows` is `true`.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

-----

##### `customWorkflow`

* **Description**: The name of the workflow to execute for all prompts in custom workflow mode. The value must match a
  workflow file name (without the `.json` extension) located in
  `Public/Configs/Workflows/<username>/`.
* **Data Type**: `string`
* **Required**: Only when `allowSharedWorkflows` is `false` and `customWorkflowOverride` is `true`
* **Example**: `"CodingWorkflow-LargeModel-Centric"`

-----

##### `routingConfig`

* **Description**: The name of the routing configuration file to use in router mode, which is active when both
  `allowSharedWorkflows` and `customWorkflowOverride` are `false`. This file, located in `Public/Configs/Routing/`,
  maps prompt categories (e.g., "Coding", "General Chat") to specific workflows.
* **Data Type**: `string`
* **Required**: Only in router mode
* **Example**: `"assistantSingleModelCategoriesConfig"`

-----

##### `categorizationWorkflow`

* **Description**: The name of the workflow that analyzes an incoming prompt in router mode and assigns it a category
  from the `routingConfig` file. The output determines which subsequent workflow is executed.
* **Data Type**: `string`
* **Required**: Only in router mode
* **Example**: `"CustomCategorizationWorkflow"`

-----

##### `maxCategorizationAttempts`

* **Description**: The maximum number of times the categorization workflow will run before falling back to the default
  workflow (`_DefaultWorkflow`). If the LLM's output does not match any configured category after this many attempts,
  the request is routed to the default workflow. A value of `1` means a single attempt with no retries. Higher values
  allow retries at the cost of additional LLM calls. Only relevant in router mode.
* **Data Type**: `integer`
* **Required**: No
* **Default**: `1`
* **Example**: `3`

-----

##### `discussionIdMemoryFileWorkflowSettings`

* **Description**: Specifies the workflow configuration file (without the `.json` extension) that governs how
  persistent, long-term memories are generated. This workflow handles conversation history chunking and the creation of
  file-based and vector-based memories.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"_DiscussionId-MemoryFile-Workflow-Settings"`

-----

##### `fileMemoryToolWorkflow`

* **Description**: The name of the workflow triggered to process and manage memories stored as files.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"MemoryFileToolWorkflow"`

-----

##### `chatSummaryToolWorkflow`

* **Description**: The name of the workflow used to generate and update a rolling summary of the conversation history
  for a given `discussionId`.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"GetChatSummaryToolWorkflow"`

-----

##### `conversationMemoryToolWorkflow`

* **Description**: The name of the workflow that processes the conversation to create discrete, chunked memories for
  later retrieval.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"CustomConversationMemoryToolWorkflow"`

-----

##### `recentMemoryToolWorkflow`

* **Description**: The name of the workflow responsible for retrieving and summarizing the most recent turns of a
  conversation for immediate context.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"RecentMemoryToolWorkflow"`

-----

##### `discussionDirectory`

* **Description**: The absolute path to the directory where persistent conversation files (memories, summaries, vector
  memory databases, etc.) are stored. When unset, WilmerAI falls back to `{PublicDirectory}/DiscussionIds/`, a
  *sibling* of `Configs/` under the `Public/` root, never inside `Configs/`. The `--DiscussionDirectory` CLI flag
  overrides this setting. For Windows paths, use double backslashes (`\\`).
* **Data Type**: `string` (file path)
* **Required**: No
* **Example**: `"D:\\WilmerAI\\Discussions"`
* **Resolution order**: CLI `--DiscussionDirectory` > this config setting > `{PublicDirectory}/DiscussionIds/` (or
  `{project_root}/Public/DiscussionIds/` when `--PublicDirectory` is not set).
* **Backwards compatibility**: If a discussion folder already exists at the pre-refactor location
  (`{project_root}/Public/DiscussionIds/{discussion_id}/`), that folder continues to be used for reads and writes; no
  automatic migration happens.

-----

##### `sqlLiteDirectory`

* **Description**: The absolute path to the directory where the user's SQLite database (`WilmerDb.<username>.sqlite`)
  will be created. This database is used by the `LockingService` for `WorkflowLock` nodes. When unset, WilmerAI falls
  back to `{PublicDirectory}/SqlLiteDBs/` (a sibling of `Configs/`, not inside it). The
  `--UserLevelSqlLiteDirectory` CLI flag overrides this setting.
* **Data Type**: `string` (file path)
* **Required**: No
* **Example**: `"D:\\WilmerAI\\Databases"`
* **Resolution order**: CLI `--UserLevelSqlLiteDirectory` > this config setting > `{PublicDirectory}/SqlLiteDBs/` (or
  `{project_root}/Public/SqlLiteDBs/` when `--PublicDirectory` is not set).
* **Backwards compatibility**: If a database file already exists at a pre-refactor location (the current working
  directory or the project root), it continues to be used; move the file to the new location to migrate.

-----

##### `endpointConfigsSubDirectory`

* **Description**: The name of the subfolder within `Public/Configs/Endpoints/` that contains the JSON files defining
  the user's LLM endpoints (API URLs, keys, etc.).
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"_shared"`

-----

##### `workflowConfigsSubDirectoryOverride`

* **Description**: Specifies a custom subfolder within `Public/Configs/Workflows/` for workflow configurations.
  When set, workflows are loaded from `Public/Configs/Workflows/<override>/` instead of the folder named after the user.
  This allows multiple users to share a common set of workflows.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"coding-workflows"` (loads from `Public/Configs/Workflows/coding-workflows/`)

-----

##### `presetConfigsSubDirectoryOverride`

* **Description**: Specifies a custom subfolder within `Public/Configs/Presets/<ApiType>/` for LLM generation presets (
  e.g., temperature). If omitted, the system defaults to a subfolder named after the user. This allows multiple users to
  share a common set of presets.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"shared-presets"`

-----

##### `structuredOutputConfigsSubDirectory`

* **Description**: Specifies the subfolder within `Public/Configs/StructuredOutputs/` where this user's
  structured-output schema files (referenced by the `structuredOutputFile` node property) are looked up. If omitted,
  defaults to a subfolder named after the user. A schema not found in the subfolder is looked up in the
  `StructuredOutputs` root, so shared schemas can live at the root.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"shared-schemas"`

-----

##### `chatPromptTemplateName`

* **Description**: The name of the prompt template file (without the `.json` extension) from
  `Public/Configs/PromptTemplates/`. This template formats a list of messages into a single string for use with legacy
  completion-style APIs.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"_chatonly"`

-----

##### `chatCompleteAddUserAssistant`

* **Description**: If `true`, the system automatically prepends role prefixes (e.g., "User: ", "Assistant: ") to message
  content. This is for models that expect explicit roles in a flattened prompt string.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

##### `chatCompletionAddMissingAssistantGenerator`

* **Description**: If `true` (and `chatCompleteAddUserAssistant` is also `true`), this adds a final, empty "Assistant: "
  prefix to the end of the prompt to signal to the LLM that it should begin its response.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

##### `separateConversationInVariables`

* **Description**: If `true`, conversation variable strings (e.g., `{chat_user_prompt_last_ten}`) use the delimiter
  specified in `conversationSeparationDelimiter` between messages instead of the default single newline. This allows you
  to visually separate messages from each other in the resulting text. Has no effect on the `templated_user_prompt_*`
  variables, which use the prompt template's formatting instead.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

-----

##### `conversationSeparationDelimiter`

* **Description**: The delimiter string inserted between messages in `chat_user_prompt_*` conversation variables when
  `separateConversationInVariables` is `true`. Common values include `"\n\n"` for double-newline separation, or a
  visible marker like `"\n*** END MESSAGE ***\n"`. JSON decodes `\n` and `\u000a` into actual newlines.
  To store a literal backslash followed by `n`, use `\\n`. Unescaped newlines inside JSON strings are invalid.
* **Data Type**: `string`
* **Required**: No
* **Default**: `"\n"`
* **Example**: `"\n*** END MESSAGE ***\n"`

-----

##### `userWideWorkflowVariables`

* **Description**: An object of operator-defined shared variables exposed as `{placeholders}` to every workflow this
  user runs. Each key/value becomes a substitution variable usable in any node prompt, system prompt, or path field, and
  a value may itself reference another variable (e.g. `"{YYYY_MM_DD}"`), which resolves on a second substitution
  pass. The intended use is a single source of truth for values that would otherwise be repeated across many workflow
  files, such as a shared operator-managed reference directory. For per-discussion state, use the built-in
  `{Discussion_Directory}` variable instead so the path follows API-key storage isolation. These are the
  lowest-precedence variables: a built-in (date/time, `Discussion_Id`, `Discussion_Directory`, the conversation
  variables) or a workflow-level key of the same name always wins, so a custom entry can only fill a name nothing else
  defines and can never shadow a built-in.
* **Data Type**: `object` (string keys to string values)
* **Required**: No
* **Default**: none
* **Example**: `{ "referenceFilesDir": "./Public/reference_files" }`

-----

##### `livenessToolCall`

* **Description**: A harmless tool call that Wilmer injects into a streamed response when the responding workflow
  node has opted in and the response would otherwise end with no tool call in it. Some agentic frontends end their
  autonomous loop the moment a response arrives without a tool call;
  if a workflow-driven task still has work left, that ends the run and leaves it waiting on a human. With this
  configured, Wilmer appends the given tool call and closes the response with `finish_reason: tool_calls`, so the
  frontend executes the no-op, calls back, and the task keeps moving unattended. The tool named here must be valid
  for the frontend in use (for example `bash` in pi). Injection only happens for responder nodes that set
  `"injectLivenessToolCall": true` in their node config: nodes whose turn is always mid-task, such as a status or
  report turn that produces plain text while the task continues. Responders without the property keep the default
  contract: a text-only response ends the frontend's loop, which is how a finished task is meant to stop. Only
  applies to streamed responses in the OpenAI chat completions and Ollama chat formats, which are the formats that
  carry tool calls.

  Injected turns are one-shot: the model sees the injection exactly once, on the request immediately after it
  fires, where it appears at the end of the conversation as feedback that the previous reply lacked a tool call.
  Wilmer strips it out of every later request before any workflow sees it, so the model cannot pick it up as a
  pattern to repeat. The strip keys on the `[Wilmer]` marker in the call's arguments (which also catches any
  model-produced copies of the injection), so the configured `arguments` should always include the `[Wilmer]`
  marker, and the string should be kept short; it only ever appears once per firing in the frontend's transcript.
* **Data Type**: `object` with a required `toolName` (string) and optional `arguments` (object)
* **Required**: No
* **Default**: none (no injection)
* **Example**: `{ "toolName": "bash", "arguments": { "command": "echo '[Wilmer] No tool call in the last reply; auto-continuing.'" } }`

-----

##### `connectTimeoutInSeconds`

* **Description**: The timeout in seconds for establishing an HTTP connection to an LLM endpoint. This only covers the
  TCP connection phase (the initial handshake), not the time spent waiting for the LLM to process and respond. If the
  connection cannot be established within this time, the request fails. This is useful for detecting unreachable
  endpoints quickly rather than waiting for the full request timeout.
* **Data Type**: `integer`
* **Required**: No
* **Default**: `30`
* **Example**: `60`

-----

##### `useOfflineWikiApi`

* **Description**: If `true`, enables the `OfflineWikipediaTextApi` tool, allowing workflows to query a local Wikipedia
  database.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

##### `offlineWikiApiHost`

* **Description**: The IP address or hostname of the server running the `OfflineWikipediaTextApi`.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"127.0.0.1"`

-----

##### `offlineWikiApiPort`

* **Description**: The network port on which the `OfflineWikipediaTextApi` server is listening.
* **Data Type**: `integer`
* **Required**: Yes
* **Example**: `5728`

-----

##### `useFileLogging`

* **Description**: If `true`, logs are written to a `wilmerai.log` file in the directory specified by the
  `--LoggingDirectory` command-line argument. If `false` or omitted, logs are only printed to the console.
  This setting is only used as a fallback in **single-user mode** when `--file-logging` is not passed on the
  command line. In **multi-user mode**, this per-user setting is ignored entirely; use the `--file-logging`
  command-line flag instead to enable file logging for the server. When file logging is active in multi-user
  mode, each user's log output is automatically written to a separate file under a per-user subdirectory
  (e.g., `logs/alice/wilmerai.log`, `logs/bob/wilmerai.log`). System and startup logs go to
  `logs/wilmerai.log`.
* **Data Type**: `boolean`
* **Required**: No
* **Example**: `true`

-----

##### `allowSharedWorkflows`

* **Description**: If `true`, selects shared workflow mode and makes it mutually exclusive with custom workflow and
  router modes. The `/v1/models` and `/api/tags` endpoints return workflow folders from
  `Public/Configs/Workflows/_shared/` as selectable models. Each request must name one of those advertised models.
  `customWorkflowOverride`, `customWorkflow`, `routingConfig`, and `categorizationWorkflow` are ignored. If `false` or
  omitted, workflow selection uses custom workflow mode or router mode.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

-----

##### `encryptUsingApiKey`

> **Warning: loss of the API key permanently loses access to encrypted data.** WilmerAI has no key reset or recovery
> mechanism. Encrypted backups also require the key. Save the exact key securely and back up existing files before
> enabling this setting. Keep the original workflow-selection name, which also participates in key derivation.

* **Description**: If `true`, enables per-user encryption of supported built-in discussion JSON files and state
  documents using the API key provided in the `Authorization: Bearer <key>` header. When enabled, files are encrypted at
  rest using Fernet symmetric encryption derived from the API key, and stored under a hash-based subdirectory for
  directory isolation. Requires the `cryptography` library. Without an API key in the request, this setting has no
  effect.
  Existing plaintext is encrypted on its next write. Custom text files and SQLite databases are not covered.
  Switching this setting off does not decrypt existing files. Preserve the original key and workflow selection
  to read existing encrypted files.
  See [the encryption guide](../../Core_Features/Per_User_Encryption.md).
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

-----

##### `redactLogOutput`

* **Description**: If `true`, log messages that could contain user conversation content are automatically redacted for all requests, regardless of whether encryption is enabled or an API key is present. This can be used standalone to protect log files even without encryption enabled. When encryption is active for a request, redaction also activates automatically even if this setting is `false`.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

-----

##### `interceptOpenWebUIToolRequests`

* **Description**: If `true`, OpenWebUI tool-selection requests are intercepted and answered with an empty tool-call
  response, bypassing the workflow engine entirely. OpenWebUI sends these requests when "tools" (plugins) are enabled
  in the UI; they contain a distinctive system prompt asking the model to choose from available tools. When `false`
  (the default), these requests are routed through the normal workflow pipeline like any other prompt. This is
  typically the desired behavior when Open WebUI is configured with a separate Task model that handles tool selection.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

-----

##### `contextCompactorSettingsFile`

* **Description**: The name of the JSON settings file (without the `.json` extension) that configures the
  ContextCompactor feature. This file, located in the user's workflow folder (e.g., `Public/Configs/Workflows/<username>/`), controls parameters such as token budgets
  for recent and old context windows, the LLM endpoint and preset used for summarization, and the prompts for each
  compaction stage.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"ContextCompactorSettings"`

-----

##### `sharedWorkflowsSubDirectoryOverride`

* **Description**: Specifies a custom folder name to use instead of `_shared` for the shared workflows folder. When set,
  the `/v1/models` and `/api/tags` endpoints (when `allowSharedWorkflows` is true) will list workflow folders from
  `Public/Configs/Workflows/<override>/` instead of `_shared/`. Similarly, workflow selection via the API model field
  will look in this folder instead of `_shared/`.
* **Data Type**: `string`
* **Required**: No
* **Default**: `"_shared"`
* **Example**: `"_team_workflows"` (uses `Public/Configs/Workflows/_team_workflows/` for shared workflows)

-----

#### **Example User File**

Here is a fully-commented example user configuration file.

Annotated JSON example. Remove comments before saving it as a configuration file.

```jsonc
{
  // The network port for this WilmerAI instance to listen on.
  "port": 5006,
  // If true, LLM responses are streamed incrementally back to the client.
  "stream": true,
  // If true while shared workflows are off, bypasses routing and uses 'customWorkflow' for all requests.
  "customWorkflowOverride": false,
  // The workflow to use in custom workflow mode.
  "customWorkflow": "CodingWorkflow-LargeModel-Centric",
  // The routing configuration file used when shared workflows and custom override are both false.
  "routingConfig": "assistantSingleModelCategoriesConfig",
  // The workflow that categorizes incoming prompts.
  "categorizationWorkflow": "CustomCategorizationWorkflow",
  // Max attempts for categorization before falling back to the default workflow (default: 1).
  "maxCategorizationAttempts": 1,
  // Workflow for managing long-term, persistent memory files.
  "discussionIdMemoryFileWorkflowSettings": "_DiscussionId-MemoryFile-Workflow-Settings",
  // Workflow triggered for file-based memory operations.
  "fileMemoryToolWorkflow": "MemoryFileToolWorkflow",
  // Workflow for generating a rolling summary of the chat.
  "chatSummaryToolWorkflow": "GetChatSummaryToolWorkflow",
  // Workflow for creating chunked memories from the conversation.
  "conversationMemoryToolWorkflow": "CustomConversationMemoryToolWorkflow",
  // Workflow for retrieving recent conversation turns.
  "recentMemoryToolWorkflow": "RecentMemoryToolWorkflow",
  // Directory to store all discussion-related files (memories, summaries).
  "discussionDirectory": "D:\\WilmerAI\\Discussions",
  // Directory to store the user's SQLite database for workflow locking.
  "sqlLiteDirectory": "D:\\WilmerAI\\Databases",
  // Subdirectory for this user's LLM endpoint configurations.
  "endpointConfigsSubDirectory": "_shared",
  // Optional override to use a shared folder (under Workflows/) for workflow configurations.
  "workflowConfigsSubDirectoryOverride": "coding-workflows",
  // Optional override to use a shared folder for generation presets.
  "presetConfigsSubDirectoryOverride": "shared-presets",
  // The prompt template for flattening chat messages for completion APIs.
  "chatPromptTemplateName": "_chatonly",
  // If true, adds "User: " and "Assistant: " prefixes to messages.
  "chatCompleteAddUserAssistant": true,
  // If true, uses a custom delimiter between messages in conversation variables.
  "separateConversationInVariables": false,
  // The delimiter to use between messages when separateConversationInVariables is true.
  "conversationSeparationDelimiter": "\n",
  // If true, adds a final "Assistant: " to prompt the model's reply.
  "chatCompletionAddMissingAssistantGenerator": true,
  // If true, enables the local Wikipedia API tool.
  "useOfflineWikiApi": true,
  // Hostname for the local Wikipedia API.
  "offlineWikiApiHost": "127.0.0.1",
  // Port for the local Wikipedia API.
  "offlineWikiApiPort": 5728,
  // If true, enables writing logs to a file.
  "useFileLogging": true,
  // Timeout in seconds for establishing an HTTP connection to an LLM endpoint (default: 30).
  "connectTimeoutInSeconds": 30,
  // If true, lists workflow folders from the shared workflows folder in the models API endpoints.
  "allowSharedWorkflows": false,
  // Optional override for the shared workflows folder name (default is "_shared").
  "sharedWorkflowsSubDirectoryOverride": "_shared",
  // If true, encrypts discussion files using the API key from the Authorization header.
  "encryptUsingApiKey": false,
  // If true, redacts user content from log output for all requests (not just encrypted ones).
  "redactLogOutput": false,
  // If true, intercepts OpenWebUI tool-selection requests with an empty response (default: false).
  "interceptOpenWebUIToolRequests": false,
  // Settings file for the ContextCompactor feature (without .json extension).
  "contextCompactorSettingsFile": "ContextCompactorSettings"
}
```
