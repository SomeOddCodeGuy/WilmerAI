### **`User` Configuration Files**

The User configuration file is the central settings file for a specific user instance of WilmerAI. It defines server
behavior, workflow routing, memory management, file paths, and logging.

User configuration files are located in the `Public/Configs/Users/` directory. To add a new user, copy an existing file,
rename it (e.g., `MyUser.json`), and modify its contents. To activate a user configuration, either update the
`_current-user.json` file with the username or use the `--User <username>` command-line argument at startup.

-----

#### **Field Definitions**

Each User JSON file contains a single object with the following key-value pairs.

##### `port`

* **Description**: Specifies the network port on which the WilmerAI instance will listen. This allows multiple instances
  to run simultaneously. The server hosts on `0.0.0.0` by default, making it accessible on the local network.
* **Data Type**: `integer`
* **Required**: Yes
* **Example**: `5006`

-----

##### `customWorkflowOverride`

* **Description**: A boolean flag that controls the routing system. If set to `true`, the prompt categorization and
  routing logic is bypassed, and all incoming prompts are forced to execute the workflow specified in the
  `customWorkflow` field.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

-----

##### `customWorkflow`

* **Description**: The name of the workflow to execute for all prompts when `customWorkflowOverride` is `true`. The
  value must match a workflow file name (without the `.json` extension) located in
  `Public/Configs/Workflows/<username>/`.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"CodingWorkflow-LargeModel-Centric"`

-----

##### `routingConfig`

* **Description**: The name of the routing configuration file to use when `customWorkflowOverride` is `false`. This
  file, located in `Public/Configs/Routing/`, maps prompt categories (e.g., "Coding", "General Chat") to specific
  workflows.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"assistantSingleModelCategoriesConfig"`

-----

##### `categorizationWorkflow`

* **Description**: The name of the workflow that analyzes an incoming prompt and assigns it a category from the
  `routingConfig` file. The output of this workflow determines which subsequent workflow is executed.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"CustomCategorizationWorkflow"`

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
* \-**Data Type**: `string`
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

* **Description**: The absolute path to the directory where persistent conversation files (e.g., `_memories.json`,
  `_chat_summary.json`) are stored. The application requires this directory to exist when a `discussionId` is used. For
  Windows paths, use double backslashes (`\\`).
* **Data Type**: `string` (file path)
* **Required**: Yes
* **Example**: `"D:\\WilmerAI\\Discussions"`

-----

##### `sqlLiteDirectory`

* **Description**: The absolute path to the directory where the user's SQLite database (`WilmerDb.<username>.sqlite`)
  will be created. This database is used by the `LockingService` for `WorkflowLock` nodes.
* **Data Type**: `string` (file path)
* **Required**: Yes
* **Example**: `"D:\\WilmerAI\\Databases"`

-----

##### `endpointConfigsSubDirectory`

* **Description**: The name of the subfolder within `Public/Configs/Endpoints/` that contains the JSON files defining
  the user's LLM endpoints (API URLs, keys, etc.).
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"assistant-single-model"`

-----

##### `workflowConfigsSubDirectoryOverride`

* **Description**: Specifies a custom subfolder within `Public/Configs/Workflows/_overrides/` for workflow configurations.
  When set, workflows are loaded from `_overrides/<override>/` instead of the user's folder. This allows multiple users to
  share a common set of workflows.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"coding-workflows"` (loads from `_overrides/coding-workflows/`)

-----

##### `presetConfigsSubDirectoryOverride`

* **Description**: Specifies a custom subfolder within `Public/Configs/Presets/<ApiType>/` for LLM generation presets (
  e.g., temperature). If omitted, the system defaults to a subfolder named after the user. This allows multiple users to
  share a common set of presets.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"shared-presets"`

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
* **Data Type**: `boolean`
* **Required**: No
* **Example**: `true`

-----

##### `allowSharedWorkflows`

* **Description**: If `true`, the `/v1/models` and `/api/tags` API endpoints return workflow folders from
  `Public/Configs/Workflows/_shared/` as selectable models. This allows front-end applications to select different
  workflow folders via the model dropdown. If `false` or omitted (the default), only the username is returned as a
  model, and workflow selection occurs through the normal routing or `customWorkflow` settings.
* **Data Type**: `boolean`
* **Required**: No
* **Default**: `false`
* **Example**: `true`

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

```json
{
  // The network port for this WilmerAI instance to listen on.
  "port": 5006,
  // If true, bypasses routing and uses 'customWorkflow' for all requests.
  "customWorkflowOverride": false,
  // The workflow to use when 'customWorkflowOverride' is true.
  "customWorkflow": "CodingWorkflow-LargeModel-Centric",
  // The routing configuration file that maps categories to workflows.
  "routingConfig": "assistantSingleModelCategoriesConfig",
  // The workflow that categorizes incoming prompts.
  "categorizationWorkflow": "CustomCategorizationWorkflow",
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
  "endpointConfigsSubDirectory": "assistant-single-model",
  // Optional override to use a shared folder for workflow configurations (within _overrides/).
  "workflowConfigsSubDirectoryOverride": "coding-workflows",
  // Optional override to use a shared folder for generation presets.
  "presetConfigsSubDirectoryOverride": "shared-presets",
  // The prompt template for flattening chat messages for completion APIs.
  "chatPromptTemplateName": "_chatonly",
  // If true, adds "User: " and "Assistant: " prefixes to messages.
  "chatCompleteAddUserAssistant": true,
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
  "sharedWorkflowsSubDirectoryOverride": "_shared"
}
```