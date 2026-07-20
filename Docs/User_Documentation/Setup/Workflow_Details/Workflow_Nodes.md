## A Comprehensive Guide to WilmerAI Workflow Nodes

This document provides an exhaustive reference for all available non-memory-related nodes within the WilmerAI workflow
system. It is designed to be a complete guide for an LLM to understand the purpose, configuration, and proper usage of
each node.

-----

### **Core LLM Interaction: The `Standard` Node**

The **`Standard` Node** (also referred to as `Conversational`) is the fundamental building block for all direct
interactions with a Large Language Model (LLM). Its primary purpose is to assemble a prompt from various sources of
context (conversation history, previous node outputs, static text), send it to a specified LLM backend, and process the
response.

#### **Properties**

| Property                                    | Type    | Required | Default    | Description                                                                                                                           |
|:--------------------------------------------|:--------|:---------|:-----------|:--------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                                  | String  | Yes      | `Standard` | The node type. Best practice is to always include it for clarity.                                                                     |
| **`title`**                                 | String  | No       | `""`       | A descriptive name for the node, used for logging and debugging.                                                                      |
| **`endpointName`**                          | String  | Yes      | N/A        | The name of the LLM endpoint configuration. **Supports LIMITED variables: only `{agent#Input}` and static workflow variables, NOT `{agent#Output}`.**  |
| **`preset`**                                | String  | Yes      | N/A        | The name of the generation preset to use. If omitted, the endpoint's default is used. **Supports LIMITED variables like endpointName.** |
| **`returnToUser`**                          | Boolean | No       | `false`    | If `true`, this node's output is sent to the user. Only one node per workflow can be a responder.                                     |
| **`systemPrompt`**                          | String  | Yes      | N/A        | The system prompt or initial instruction set for the LLM. Supports variable substitution.                                             |
| **`prompt`**                                | String  | Yes      | N/A        | The main user-facing prompt. If this is empty, the node will use `lastMessagesToSendInsteadOfPrompt`. Supports variable substitution. |
| **`lastMessagesToSendInsteadOfPrompt`**     | Integer | No       | `5`        | If `prompt` is empty, this specifies how many recent conversational turns to use as the prompt.                                       |
| **`lastMessagesToSendInsteadOfPromptMaxTokenSize`** | Integer | No | N/A | Optional token ceiling applied on top of `lastMessagesToSendInsteadOfPrompt` (only used when `prompt` is empty). The selected recent turns are trimmed, newest-first, to fit this estimated-token budget, which is useful when individual turns are large (e.g. agentic tool results). When `clampPromptToContextWindow` is on for the node, this value is scaled by the endpoint's `wilmerContextEstimationLevel`. If omitted, only the message count bounds the window. (The context-window clamp, when enabled, largely subsumes this cap.) |
| **`maxResponseSizeInTokens`**               | Integer/String | No       | `400`      | Overrides the maximum number of tokens the LLM can generate for this node. **Supports LIMITED variables like endpointName.**         |
| **`maxContextTokenSize`**                   | Integer | No       | `4096`     | Overrides the maximum context window size (in tokens) for this node.                                                                  |
| **`nMessagesToIncludeInVariable`**           | Integer | No       | `5`        | Controls how many messages are included in the `{chat_user_prompt_n_messages}` and `{templated_user_prompt_n_messages}` variables.    |
| **`estimatedTokensToIncludeInVariable`**    | Integer | No       | `2048`     | Controls the estimated token budget for the `{chat_user_prompt_estimated_token_limit}` and `{templated_user_prompt_estimated_token_limit}` variables. Messages are included from most recent backwards until the budget is reached. At least one message is always included. |
| **`minMessagesInVariable`**                 | Integer | No       | `5`        | Used with `maxEstimatedTokensInVariable`. Sets the minimum message count for the `{chat_user_prompt_min_n_max_tokens}` and `{templated_user_prompt_min_n_max_tokens}` variables. These messages are always included regardless of the token budget. |
| **`maxEstimatedTokensInVariable`**          | Integer | No       | `2048`     | Used with `minMessagesInVariable`. Sets the token budget for expansion beyond the minimum message count. After the minimum messages are included, older messages are added until this budget would be exceeded. |
| **`jinja2`**                                | Boolean | No       | `false`    | If `true`, enables Jinja2 templating for the `systemPrompt` and `prompt` fields.                                                      |
| **`addDiscussionIdTimestampsForLLM`**       | Boolean | No       | `false`    | If `true`, automatically injects timestamps into the `messages` payload sent to the LLM.                                              |
| **`useRelativeTimestamps`**                 | Boolean | No       | `false`    | If `addDiscussionIdTimestampsForLLM` is `true`, this uses relative timestamps (e.g., "5 minutes ago").                                |
| **`useGroupChatTimestampLogic`**            | Boolean | No       | `false`    | Activates special timestamping logic for group chat-style generation prompts.                                                         |
| **`addUserTurnTemplate`**                   | Boolean | No       | `false`    | Manually wraps the final prompt content in the user turn template defined by the endpoint.                                            |
| **`addOpenEndedAssistantTurnTemplate`**     | Boolean | No       | `false`    | Appends the start of an assistant turn template to the end of the final prompt.                                                       |
| **`forceGenerationPromptIfEndpointAllows`** | Boolean | No       | `false`    | Forces the addition of a generation prompt even if other settings would normally suppress it.                                         |
| **`blockGenerationPrompt`**                 | Boolean | No       | `false`    | Explicitly blocks the addition of any automatic generation prompt.                                                                    |
| **`acceptImages`**                          | Boolean | No       | `false`    | If `true`, images attached to conversation messages are preserved and sent to the LLM backend. The endpoint must support vision/multimodal input. When `false`, images are stripped. If `true` but no images are present, the node behaves as a normal text request. |
| **`maxImagesToSend`**                       | Integer | No       | `0`        | Only relevant when `acceptImages` is `true`. Limits the number of images sent to the backend, keeping the most recent. `0` means no limit. **Supports LIMITED variables like endpointName.** |
| **`allowTools`**                            | Boolean | No       | `false`    | If `true`, tool definitions from the frontend request are forwarded to the LLM when this node executes. Tool call responses from the LLM are passed back to the frontend. Should typically only be enabled on the responding node. See [Tool Call Passthrough](Workflow_Features.md#tool-call-passthrough). |
| **`appendNativeToolExchange`**              | Boolean | No       | `false`    | Authored-prompt nodes only. Delivers the conversation's trailing tool exchange (the assistant `tool_calls` turn the frontend just executed plus its `role: "tool"` results) as native messages after the authored prompt, excluding it from the text transcript, so the model generates from the standard post-tool-result position. Required for reliable multi-round tool loops through authored-prompt nodes. Inert on collection-mode nodes, on completions backends, and on endpoints declaring `backendSupportsToolTurns: false`. See [Delivering the Live Tool Exchange Natively](Workflow_Features.md#delivering-the-live-tool-exchange-natively-appendnativetoolexchange). |
| **`lowercaseToolCallFunctionNames`**        | Boolean | No       | `false`    | If `true`, tool call function names in LLM responses are lowercased before being sent to the frontend. Fixes local models that produce capitalized names (e.g., `Glob` instead of `glob`). Works for both streaming and non-streaming. See [Lowercasing Tool Call Function Names](Workflow_Features.md#lowercasing-tool-call-function-names). |
| **`structuredOutputFile`**                  | String  | No       | none       | Name of a JSON Schema file in `Public/Configs/StructuredOutputs/` that grammar-constrains this node's output (the backend must support constrained decoding; declared per API type). The node's output is guaranteed-parseable JSON matching the schema. Describe the desired structure in the prompt too; the model does not see the schema. See [Structured Output](Workflow_Features.md#structured-output-grammar-constrained-responses). |
| **`mergeConsecutiveAssistantMessages`**     | Boolean | No       | `false`    | If `true`, consecutive assistant messages are merged into one before sending to the LLM. Only applies when `prompt` is empty. Tool-call sequences (assistant -> tool -> assistant) are not affected. See [Consecutive Assistant Message Normalization](Workflow_Features.md#consecutive-assistant-message-normalization). |
| **`mergeConsecutiveAssistantMessagesDelimiter`** | String | No   | `"\n"`     | Delimiter for joined content when merging consecutive assistant messages. |
| **`insertUserTurnBetweenAssistantMessages`** | Boolean | No      | `false`    | If `true`, a synthetic user message is inserted between consecutive assistant messages. Alternative to merging. See [Consecutive Assistant Message Normalization](Workflow_Features.md#consecutive-assistant-message-normalization). |
| **`insertedUserTurnText`**                  | String  | No       | `"Continue."` | Content of the synthetic user message when using insertion. |
| **`addUserAssistantTags`**                  | Boolean | No       | `false`    | If `true`, prefixes each message in `chat_user_prompt_*` variables with its role (e.g., `User: `, `Assistant: `). Per-node setting. Does not affect `templated_user_prompt_*` variables. |
| **`includeToolCallsInConversation`**        | Boolean | No       | `false`    | If `true`, injects text summaries of `tool_calls` into assistant message content for conversation history variables (formatted as `[Tool Call: {name}] {summary}`), and prefixes tool result messages with a `[Tool Result: {name}]` label recovered from the originating call. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Full variables are supported in the `systemPrompt` and `prompt` fields. The `endpointName`,
  `preset`, and `maxResponseSizeInTokens` fields support LIMITED variables (only `{agent#Input}` from parent workflows
  and static variables defined in the workflow JSON, NOT `{agent#Output}` which doesn't exist yet). For
  `maxResponseSizeInTokens`, the variable must resolve to a valid integer string (e.g., `"5000"`).
* **Responder Node:** Only one node in a workflow can have `returnToUser` set to `true`. If no node is designated, the
  last node in the workflow automatically becomes the responder.
* **Prompt Fallback:** The node prioritizes the `prompt` field. If it's empty, it will fall back to using the
  conversation history as defined by `lastMessagesToSendInsteadOfPrompt`.

#### **Full Syntax Example**

This example shows a non-responder "thinking" node that synthesizes information from previous nodes and the conversation
history.

```json
{
  "title": "LLM Thinking Over to User Request",
  "type": "Standard",
  "systemPrompt": "System Information: Today is {todays_date_pretty}. The user is {human_persona_name}.\n\n<your_profile>\n{agent3Output}\n</your_profile>\n\n<user_profile>\n{agent2Output}\n</user_profile>",
  "prompt": "Please consider the most recent twenty messages of your online conversation with {human_persona_name}:\n\n<recent_conversation>\n{chat_user_prompt_last_twenty}\n</recent_conversation>\n\nPlease think carefully about all of this by answering the following questions:\n- A) How long has it been since the last message?\n- B) What did {human_persona_name} mean in their last message to you?\n- C) Carefully consider what the best way to respond might be.",
  "endpointName": "Thinker-Endpoint",
  "preset": "Thinker-Preset",
  "maxResponseSizeInTokens": 8000,
  "addUserTurnTemplate": true,
  "returnToUser": false,
  "addDiscussionIdTimestampsForLLM": true,
  "useRelativeTimestamps": true
}
```

#### **Variable Substitution for Child Workflows**

When calling a child workflow via `CustomWorkflow`, you can pass dynamic values for `endpointName`, `preset`, and
`maxResponseSizeInTokens` using `scoped_variables`. This allows the parent workflow to control which endpoint, preset,
and response size the child uses.

**Parent Workflow (calls the child with dynamic config):**

```json
{
  "title": "Run Analysis with Custom Settings",
  "type": "CustomWorkflow",
  "workflowName": "General_Workflow_Replaceable_Endpoint",
  "workflowUserFolderOverride": "_common",
  "scoped_variables": [
    "MyDynamicEndpoint",
    "MyDynamicPreset",
    "6000"
  ]
}
```

**Child Workflow (receives the values as `{agent#Input}`):**

```json
{
  "title": "Responding Agent",
  "type": "Standard",
  "endpointName": "{agent1Input}",
  "preset": "{agent2Input}",
  "maxResponseSizeInTokens": "{agent3Input}",
  "systemPrompt": "...",
  "prompt": ""
}
```

In this example, the child workflow will use endpoint `MyDynamicEndpoint`, preset `MyDynamicPreset`, and generate up to
`6000` tokens.

-----

### **Logic & Control Flow: The `Conditional` Node**

The **`Conditional`** node is a control flow utility that evaluates a complex logical expression and returns the string
`"TRUE"` or `"FALSE"`. Its output is designed to be used by a `ConditionalCustomWorkflow` node to make branching
decisions. It supports comparisons, logical operators (`AND`, `OR`), and parentheses `()` for grouping.

#### **Properties**

| Property           | Type    | Required | Default | Description                                                                                                     |
|:-------------------|:--------|:---------|:--------|:----------------------------------------------------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A     | Must be `"Conditional"`.                                                                                        |
| **`title`**        | String  | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                |
| **`condition`**    | String  | Yes      | N/A     | The logical expression to evaluate (e.g., `({val} >= 100 AND '{status}' != 'ERROR') OR {is_override} == TRUE`). |
| **`returnToUser`** | Boolean | No       | `false` | This node is designed for internal logic; its output is not intended for the end-user.                          |

#### **Limitations and Key Usage Notes**

* **Variable Support:** The `condition` property supports all available workflow variables.
* **Type Inference:** The node intelligently infers types. Values in quotes (e.g., `'complete'`) are strings. Unquoted
  `TRUE` or `FALSE` are booleans. Other unquoted values are treated as numbers if possible, otherwise as strings.
* **IMPORTANT:** Be careful when doing comparisons. The node distinguishes between a boolean and a string. The output of
  a `Conditional` node is a boolean `TRUE` or `FALSE`. If `agent3Output` comes from a `Conditional` node and is `TRUE`,
  the comparison `"{agent3Output} == 'TRUE'"` will be **FALSE** because `(boolean) TRUE` is not equal to
  `(string) 'TRUE'`. The correct comparison is `"{agent3Output} == TRUE"`.

#### **Full Syntax Example**

This example demonstrates complex logic with `OR` and parentheses, checking for multiple valid states or an override
condition.

```json
{
  "title": "Check for valid state or admin override",
  "type": "Conditional",
  "condition": "({agent1Output} == 'Admin') OR ({agent2Output} == 'Approved' AND {agent3Output} == TRUE)"
}
```

-----

### **In-Workflow Routing: The `ConditionalCustomWorkflow` Node**

The **`ConditionalCustomWorkflow` Node** provides branching logic. It dynamically selects and executes a
sub-workflow based on the value of a conditional variable (e.g., the output from a `Conditional` node). It also supports
a default content fallback, preventing the need for an extra workflow file for a simple default response.

#### **Properties**

| Property                                 | Type             | Required | Default | Description                                                                                                                          |
|:-----------------------------------------|:-----------------|:---------|:--------|:-------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                               | String           | Yes      | N/A     | Must be set to `"ConditionalCustomWorkflow"`.                                                                                        |
| **`title`**                              | String           | No       | `""`    | A descriptive title for the node shown in logs.                                                                                      |
| **`is_responder`**                       | Boolean          | No       | `false` | Determines if the output provides the final user-facing response. Renamed from `returnToUser` for clarity.                           |
| **`conditionalKey`**                     | String           | Yes      | N/A     | A variable placeholder (e.g., `{agent1Output}`) whose resolved value determines which workflow to execute.                           |
| **`conditionalWorkflows`**               | Object           | Yes      | N/A     | A dictionary mapping possible values of `conditionalKey` to workflow filenames. A special `"Default"` key can be used as a fallback. |
| **`UseDefaultContentInsteadOfWorkflow`** | String           | No       | `null`  | A string (supports variables) to return as output if no condition is met. This takes precedence over the `"Default"` workflow.       |
| **`scoped_variables`**                   | Array of Strings | No       | `[]`    | A list of values to pass into whichever child workflow is chosen.                                                                    |
| **`routeOverrides`**                     | Object           | No       | `{}`    | A dictionary specifying prompt overrides for each potential route. Keys should correspond to keys in `conditionalWorkflows`.         |
| **`workflowUserFolderOverride`**         | String           | No       | `null`  | Specifies a user folder from which to load the selected workflow. Use `_common` for shared workflows.                                |

#### **Limitations and Key Usage Notes**

* **IMPORTANT:** Only `scoped_variables`, `UseDefaultContentInsteadOfWorkflow`, and `conditionalKey` support workflow
  variables.
* **You cannot set a variable as a workflow name.** Configuration keys like workflow names inside `conditionalWorkflows`
  and `routeOverrides` must be static, hardcoded strings.
* **Matching Logic:** The match for both `conditionalWorkflows` and `routeOverrides` keys is **case-insensitive**.

#### **Full Syntax Example**

This node routes to a specialized coding workflow based on the language detected in a previous step.

```json
{
  "title": "Route to a Specific Coding Model",
  "type": "ConditionalCustomWorkflow",
  "is_responder": true,
  "conditionalKey": "{agent1Output}",
  "workflowUserFolderOverride": "_common",
  "conditionalWorkflows": {
    "Python": "PythonCodingWorkflow",
    "JavaScript": "JavaScriptCodingWorkflow",
    "Default": "GeneralCodingWorkflow"
  },
  "UseDefaultContentInsteadOfWorkflow": "I'm sorry, I can only assist with Python and JavaScript at the moment.",
  "scoped_variables": [
    "{agent2Output}"
  ],
  "routeOverrides": {
    "Python": {
      "systemPromptOverride": "You are an expert Python programmer. The user's request is: {agent1Input}"
    },
    "JavaScript": {
      "systemPromptOverride": "You are a master JavaScript developer. The user's request is: {agent1Input}"
    }
  }
}
```

> Values sent in as scoped_variables are accessible within the child workflow that is called as agentXInputs. So
> the first scoped_variable is agent1Input, second scoped_variable is agent2Input, etc.

-----

### **Modular Logic: The `CustomWorkflow` Node**

The **`CustomWorkflow` Node** allows you to execute a separate workflow from within the current one. This is essential
for encapsulating reusable logic and breaking down complex processes. Child workflows run in an isolated context; data
must be passed in explicitly via `scoped_variables`.

#### **Properties**

| Property                            | Type             | Required | Default | Description                                                                                                         |
|:------------------------------------|:-----------------|:---------|:--------|:--------------------------------------------------------------------------------------------------------------------|
| **`type`**                          | String           | Yes      | N/A     | Must be set to `"CustomWorkflow"`.                                                                                  |
| **`title`**                         | String           | No       | `""`    | A descriptive title for the node shown in logs.                                                                     |
| **`workflowName`**                  | String           | Yes      | N/A     | The filename of the child workflow to execute (without the `.json`).                                                |
| **`is_responder`**                  | Boolean          | No       | `false` | Determines if this node provides the final user-facing response. Renamed from `returnToUser`.                       |
| **`scoped_variables`**              | Array of Strings | No       | `[]`    | A list of values to pass from the parent to the child workflow. These become `{agent1Input}`, `{agent2Input}`, etc. |
| **`workflowUserFolderOverride`**    | String           | No       | `null`  | Specifies a user folder to load the workflow from. Use `_common` for shared workflows.                              |
| **`firstNodeSystemPromptOverride`** | String           | No       | `null`  | **(Legacy)** Overrides the `systemPrompt` for the first node in the child workflow. Use `scoped_variables` instead. |
| **`firstNodePromptOverride`**       | String           | No       | `null`  | **(Legacy)** Overrides the `prompt` for the first node in the child workflow. Use `scoped_variables` instead.       |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Variable substitution is supported within the `scoped_variables` array and the legacy prompt
  override fields.
* **Static Configuration:** The `workflowName` and `workflowUserFolderOverride` fields **do not** support variables and
  must be static strings.

#### **Full Syntax Example**

This example calls a reusable child workflow to perform a search and summarize the findings.

```json
{
  "title": "Custom Wiki Search: Initial Search",
  "type": "CustomWorkflow",
  "workflowName": "Util_Workflow_Wiki_Search_And_Summarize",
  "workflowUserFolderOverride": "_common",
  "is_responder": false,
  "scoped_variables": [
    "{agent1Output}",
    "{agent3Output}"
  ]
}
```

> Values sent in as scoped_variables are accessible within the child workflow that is called as agentXInputs. So
> the first scoped_variable is agent1Input, second scoped_variable is agent2Input, etc.

-----

### **Resumable History Processing: The `ConversationChunkProcessor` Node**

The **`ConversationChunkProcessor` Node** runs a sub-workflow over the conversation in fixed-size chunks of messages,
tracking how far it has processed with a per-node hash cursor. When a long conversation is resumed under a fresh
discussion id, it walks the entire backlog in chunks and runs the sub-workflow on each one before the turn's response is
produced, so a record built from the conversation (an event log, a per-persona tracker) is caught up from history rather
than starting blind. It shares the `scoped_variables` mechanism of `CustomWorkflow`: the chunk is passed as
`{agent1Input}` and any `scoped_variables` follow.

Key properties: **`id`** (required, unique, names the cursor file), **`workflowName`** (the per-chunk sub-workflow),
**`chunkSize`** (messages per chunk, default 10), **`lookbackMessages`** (freshest messages left unprocessed, default
4), **`cursorDirectory`** (required), and **`returnFile`** (optional; returns a record file's content so a later node can
read it).

See [The `ConversationChunkProcessor` Node](Nodes/ConversationChunkProcessor.md) for the full reference.

-----

### **Data Manipulation: The `ArithmeticProcessor` Node**

The **`ArithmeticProcessor`** node performs a basic mathematical calculation. It takes a string expression containing
two numbers and one operator (`+`, `-`, `*`, `/`), resolves any variables, computes the result, and returns it as a
string. If the expression is invalid, it returns `"-1"`.

#### **Properties**

| Property           | Type    | Required | Default | Description                                                              |
|:-------------------|:--------|:---------|:--------|:-------------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A     | Must be `"ArithmeticProcessor"`.                                         |
| **`title`**        | String  | No       | `""`    | A descriptive name for the node.                                         |
| **`expression`**   | String  | Yes      | N/A     | The mathematical expression to evaluate (e.g., `{agent1Output} * 1.07`). |
| **`returnToUser`** | Boolean | No       | `false` | Unlikely to be used, as this node is for internal data processing.       |

#### **Limitations and Key Usage Notes**

* **Variable Support:** The `expression` property supports all available workflow variables. These variables are
  expected to resolve to numeric values.

#### **Full Syntax Example**

This node calculates a final price by adding a 7% tax to a subtotal from a previous node.

```json
{
  "title": "Calculate Final Price with Tax",
  "type": "ArithmeticProcessor",
  "expression": "{agent1Output} * 1.07",
  "returnToUser": false
}
```

-----

### **Data Manipulation: The `StringConcatenator` Node**

The **`StringConcatenator`** is a utility for combining multiple strings into one. It takes a list of strings, resolves
any variables, and joins them with a specified delimiter. It can also act as a streaming responder.

#### **Properties**

| Property           | Type            | Required | Default | Description                                                                       |
|:-------------------|:----------------|:---------|:--------|:----------------------------------------------------------------------------------|
| **`type`**         | String          | Yes      | N/A     | Must be `"StringConcatenator"`.                                                   |
| **`title`**        | String          | No       | `""`    | A descriptive name for the node.                                                  |
| **`strings`**      | List of Strings | Yes      | N/A     | A JSON array of strings to be joined. Each string supports variable substitution. |
| **`delimiter`**    | String          | No       | `""`    | The character(s) to insert between each string. `"\n"` is common for new lines.   |
| **`returnToUser`** | Boolean         | No       | `false` | If `true`, this node's output is sent to the user, with support for streaming.    |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Every string within the `strings` list supports full variable substitution.

#### **Full Syntax Example**

This example assembles a multi-line user profile from various data sources.

```json
{
  "title": "Assemble User Profile Block",
  "type": "StringConcatenator",
  "strings": [
    "--- User Profile ---",
    "Name: {user_name}",
    "Key Trait: {agent1Output}",
    "Report Generated: {todays_date_pretty}"
  ],
  "delimiter": "\n",
  "returnToUser": false
}
```

-----

### **Data Extraction: The `JsonExtractor` Node**

The **`JsonExtractor`** node extracts a specific field from a JSON string. It parses a JSON object (optionally wrapped
in markdown code blocks), resolves workflow variables, and returns the value of the specified field as a string. This
is useful for parsing structured LLM outputs.

#### **Properties**

| Property                | Type   | Required | Default | Description                                                                                          |
|:------------------------|:-------|:---------|:--------|:-----------------------------------------------------------------------------------------------------|
| **`type`**              | String | Yes      | N/A     | Must be `"JsonExtractor"`.                                                                           |
| **`title`**             | String | No       | `""`    | A descriptive name for the node.                                                                     |
| **`jsonToExtractFrom`** | String | Yes      | N/A     | The JSON string to extract from. Supports variables. Handles markdown code blocks automatically.     |
| **`fieldToExtract`**    | String | Yes      | N/A     | The name of the field to extract. Supports variables.                                                |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Both `jsonToExtractFrom` and `fieldToExtract` support full variable substitution.
* **Markdown Handling:** The node automatically strips ` ```json ` and ` ``` ` code block wrappers before parsing.
* **Return Types:** Strings are returned as-is; numbers/booleans become strings; nested objects/arrays become JSON
  strings; `null` returns an empty string.

#### **Full Syntax Example**

This node extracts the "name" field from a JSON object returned by a previous LLM node.

```json
{
  "title": "Extract Character Name from LLM Response",
  "type": "JsonExtractor",
  "jsonToExtractFrom": "{agent1Output}",
  "fieldToExtract": "name"
}
```

**Example Input (from `agent1Output`):**
```json
{"name": "Socg", "file": "Socg.txt"}
```

**Example Output:** `Socg`

-----

### **Data Extraction: The `TagTextExtractor` Node**

The **`TagTextExtractor`** node extracts content from XML/HTML-style tags within a text string. It searches for a
specified tag (e.g., `<answer>...</answer>`) and returns the content between the opening and closing tags. This is
useful for parsing structured LLM outputs where the model wraps content in custom tags.

#### **Properties**

| Property              | Type   | Required | Default | Description                                                                    |
|:----------------------|:-------|:---------|:--------|:-------------------------------------------------------------------------------|
| **`type`**            | String | Yes      | N/A     | Must be `"TagTextExtractor"`.                                                  |
| **`title`**           | String | No       | `""`    | A descriptive name for the node.                                               |
| **`tagToExtractFrom`** | String | Yes      | N/A     | The text string to search within. Supports variables.                          |
| **`fieldToExtract`**    | String | Yes      | N/A     | The name of the tag to search for (without angle brackets). Supports variables.|

#### **Limitations and Key Usage Notes**

* **Variable Support:** Both `tagToExtractFrom` and `fieldToExtract` support full variable substitution.
* **Case Sensitivity:** Tag matching is case-sensitive (`<Answer>` and `<answer>` are different).
* **First Match:** If multiple instances of the tag exist, only the first match is extracted.
* **Whitespace:** Leading/trailing whitespace is stripped from the extracted content.

#### **Full Syntax Example**

This node extracts the content within `<answer>` tags from an LLM response.

```json
{
  "title": "Extract Answer from LLM Response",
  "type": "TagTextExtractor",
  "tagToExtractFrom": "{agent1Output}",
  "fieldToExtract": "answer"
}
```

**Example Input (from `agent1Output`):**
```
I've analyzed your question. Here is my response:

<answer>
The capital of France is Paris.
</answer>

I hope this helps.
```

**Example Output:** `The capital of France is Paris.`

-----

### **Data Manipulation: The `DelimitedChunker` Node**

The **`DelimitedChunker`** node splits a string on a delimiter and returns either the first N or last N chunks, rejoined
with the same delimiter. It functions like `head` and `tail` for delimited content, useful for trimming long
delimited data such as logs, CSV rows, or section-separated documents.

#### **Properties**

| Property        | Type    | Required | Default | Description                                                                                                                |
|:----------------|:--------|:---------|:--------|:---------------------------------------------------------------------------------------------------------------------------|
| **`type`**      | String  | Yes      | N/A     | Must be `"DelimitedChunker"`.                                                                                              |
| **`title`**     | String  | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                           |
| **`content`**   | String  | Yes      | N/A     | The string to split. Supports variable substitution.                                                                       |
| **`delimiter`** | String  | Yes      | N/A     | The string to split on. Supports variable substitution.                                                                    |
| **`mode`**      | String  | Yes      | N/A     | Either `"head"` (first N chunks) or `"tail"` (last N chunks).                                                             |
| **`count`**     | Integer | Yes      | N/A     | Number of chunks to keep. Must be >= 1.                                                                                    |

#### **Limitations and Key Usage Notes**

* **Variable Support:** `content` and `delimiter` support full variable substitution. `mode` and `count` must be literal
  values.
* **Count >= Total Chunks:** Returns the full original content unchanged.
* **Empty Content:** Returns an empty string.
* **Delimiter Not Found:** Returns the full content unchanged (one chunk).
* **Validation:** Missing required fields, invalid `mode`, or non-positive-integer `count` all return descriptive error
  message strings.

#### **Full Syntax Example**

This example keeps the last 5 lines from a newline-separated string.

```json
{
  "title": "Keep Last 5 Lines",
  "type": "DelimitedChunker",
  "content": "{agent1Output}",
  "delimiter": "\n",
  "mode": "tail",
  "count": 5
}
```

For detailed documentation including additional examples and edge case behavior, see
[DelimitedChunker Node](Nodes/DelimitedChunker.md).

-----

### **Utility: The `GetCustomFile` Node**

The **`GetCustomFile`** node loads the content of a local text file into the workflow as a string. This allows you to
inject large blocks of static text (like instructions or reference material) without cluttering the workflow JSON.

#### **Properties**

| Property                    | Type   | Required | Default | Description                                                                                           |
|:----------------------------|:-------|:---------|:--------|:------------------------------------------------------------------------------------------------------|
| **`type`**                  | String | Yes      | N/A     | Must be `"GetCustomFile"`.                                                                            |
| **`title`**                 | String | No       | `""`    | An optional, human-readable name for the node.                                                        |
| **`filepath`**              | String | Yes      | N/A     | The full path to the text file to load. Supports variables including `{Discussion_Id}` and `{YYYY_MM_DD}`. |
| **`delimiter`**             | String | No       | `\n`    | An optional string to search for and replace within the file's content.                               |
| **`customReturnDelimiter`** | String | No       | `\n`    | An optional string that will replace every instance of the `delimiter`.                               |
| **`headCount`** / **`tailCount`** | Integer | No | (none) | Optional, opt-in limiting. Return only the first N (`headCount`) or last N (`tailCount`) chunks, where chunks are split on `chunkDelimiter` (a newline by default). Set at most one; setting both returns an error. Applied before delimiter replacement. |
| **`chunkDelimiter`**        | String | No       | `\n`    | The separator that defines a "chunk" for `headCount`/`tailCount`. Defaults to a single newline (line-based). No effect unless `headCount` or `tailCount` is set. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** The `filepath` field supports full variable substitution, including `{Discussion_Id}` for
  per-conversation files and `{YYYY_MM_DD}` for date-based files.
* **File Not Found:** If the file doesn't exist, the node returns `"Custom instruction file did not exist"`.
* **IMPORTANT:** Do not set a delimiter or custom delimiter if you want the file to be pulled as it was originally
  written.

#### **Full Syntax Example**

This node loads a project specification and replaces a simple `---` separator with a more decorative one.

```json
{
  "title": "Load Project Specification",
  "type": "GetCustomFile",
  "filepath": "D:\\Users\\User\\Desktop\\project_spec.txt",
  "delimiter": "---",
  "customReturnDelimiter": "\n**********\n"
}
```

#### **Dynamic Filepath Example**

This node loads session-specific notes using the conversation's unique identifier.

```json
{
  "title": "Load Session Notes",
  "type": "GetCustomFile",
  "filepath": "/data/sessions/{Discussion_Id}_notes.txt"
}
```

-----

### **Utility: The `SaveCustomFile` Node**

The **`SaveCustomFile`** node writes string content to a local text file. This is useful for saving data generated
during a workflow, such as an LLM's analysis, a conversation summary, or a report.

#### **Properties**

| Property       | Type   | Required | Default | Description                                                                                             |
|:---------------|:-------|:---------|:--------|:--------------------------------------------------------------------------------------------------------|
| **`type`**     | String | Yes      | N/A     | Must be `"SaveCustomFile"`.                                                                             |
| **`title`**    | String | No       | `""`    | An optional, human-readable name for the node.                                                          |
| **`filepath`** | String | Yes      | N/A     | The full path where the file will be saved. Supports variables including `{Discussion_Id}` and `{YYYY_MM_DD}`. |
| **`content`**  | String | Yes      | N/A     | The string content to be written to the file. Supports variables.                                       |
| **`mode`**     | String | No       | `overwrite` | Either `"overwrite"` (default, replaces the file) or `"append"` (adds `content` to the end, creating the file if missing). The write is atomic. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Both `filepath` and `content` fields support full variable substitution, including
  `{Discussion_Id}` for per-conversation files and `{YYYY_MM_DD}` for date-based files.
* **Error Handling:** The node returns a status message indicating success or failure (e.g., due to permissions).
* **Directory Creation:** If parent directories don't exist, the node will attempt to create them.

#### **Full Syntax Example**

This node saves a code review summary generated by a previous node to a file.

```json
{
  "title": "Save Code Review Summary to File",
  "type": "SaveCustomFile",
  "filepath": "D:\\WilmerAI\\Reports\\code_review_summary.txt",
  "content": "CODE REVIEW SUMMARY\n-----------------\nReviewer: Automated\nFindings: {agent1Output}"
}
```

#### **Dynamic Filepath Example**

This node saves a daily report using the date variable.

```json
{
  "title": "Save Daily Report",
  "type": "SaveCustomFile",
  "filepath": "/data/reports/{YYYY_MM_DD}_report.txt",
  "content": "Report for {todays_date_pretty}:\n\n{agent1Output}"
}
```

-----

### **Utility: The `StaticResponse` Node**

The **`StaticResponse`** node returns a hardcoded string. It's versatile for debugging, providing static instructions,
or delivering canned responses without an LLM call. When designated as a responder, it can simulate a streaming
response.

#### **Properties**

| Property           | Type    | Required | Default | Description                                                           |
|:-------------------|:--------|:---------|:--------|:----------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A     | Must be `"StaticResponse"`.                                           |
| **`title`**        | String  | No       | `""`    | An optional, human-readable name for the node.                        |
| **`content`**      | String  | Yes      | N/A     | The static text content that the node will output.                    |
| **`returnToUser`** | Boolean | No       | `false` | If `true`, the `content` is sent to the user, with streaming support. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** The `content` field supports full variable substitution (e.g., `{agent1Output}`, `{current_username}`).
* **Streaming:** If `returnToUser` is `true` and the request is for streaming, the content is delivered word-by-word.

#### **Full Syntax Example**

This node sends a pre-written message directly to the user as a final, streaming response.

```json
{
  "title": "Return System Status Message",
  "type": "StaticResponse",
  "content": "Acknowledged. All requested operations have been completed successfully. No further action is required.",
  "returnToUser": true
}
```

-----

### **Vision: The `ImageProcessor` Node**

The **`ImageProcessor`** node is the bridge between user-provided images and text-based nodes. It calls a vision-capable
LLM to generate text descriptions of images in the user's latest message. These descriptions are then made available to
subsequent nodes.

#### **Properties**

| Property               | Type    | Required | Default | Description                                                                                                       |
|:-----------------------|:--------|:---------|:--------|:------------------------------------------------------------------------------------------------------------------|
| **`type`**             | String  | Yes      | N/A     | Must be `"ImageProcessor"`.                                                                                       |
| **`endpointName`**     | String  | Yes      | N/A     | The name of the vision-capable LLM endpoint. **Supports LIMITED variables: only `{agent#Input}` and static workflow variables, NOT `{agent#Output}`.**  |
| **`systemPrompt`**     | String  | Yes      | N/A     | The system prompt for the vision LLM, instructing it on how to describe the image. Supports variables.            |
| **`prompt`**           | String  | Yes      | N/A     | The user prompt for the vision LLM, guiding what to focus on. Supports variables.                                 |
| **`preset`**           | String  | Yes      | N/A     | The generation preset for the vision LLM. **Supports LIMITED variables like endpointName.**                       |
| **`addAsUserMessage`** | Boolean | No       | `false` | If `true`, injects the aggregated image description into the conversation history as a new user message.          |
| **`message`**          | String  | No       | N/A     | A template string for the injected message. **Must contain the `[IMAGE_BLOCK]` placeholder.** Supports variables. |
| **`saveVisionResponsesToDiscussionId`** | Boolean | No | `false` | If `true` and a `discussion_id` is available, caches vision responses per-discussion to avoid redundant LLM calls. Changes `addAsUserMessage` to per-message injection. See the [ImageProcessor node docs](Nodes/Image_Processor.md) for details. |

#### **Limitations and Key Usage Notes**

* **Limited Variable Support:** `endpointName` and `preset` support LIMITED variables (only `{agent#Input}` from parent
  workflows and static variables, NOT `{agent#Output}` which doesn't exist yet).
* **Sequential Processing:** The node processes images one by one and aggregates their descriptions into a single string
  output, separated by `\n-------------\n`.
* **`[IMAGE_BLOCK]` Placeholder:** This special keyword is **only valid** inside the `message` property of this node. It
  marks where the aggregated descriptions will be inserted.

#### **Full Syntax Example**

This node analyzes all user images and injects the description into the chat history for a subsequent text-only node to
use.

```json
{
  "title": "Analyze and Describe All User Images",
  "type": "ImageProcessor",
  "endpointName": "Vision-Endpoint",
  "preset": "Vision-Preset",
  "addAsUserMessage": true,
  "message": "[SYSTEM: An image analysis module has processed the user's recent image(s). The detailed description is below:\n\n[IMAGE_BLOCK]\n\nThis is now part of our conversation.]",
  "systemPrompt": "You are a world-class visual analysis AI. Describe the image in meticulous detail for a text-only assistant.",
  "prompt": "Based on our recent conversation:\n{chat_user_prompt_last_five}\n\nDescribe the image's contents in extreme detail. Transcribe any text you see."
}
```

-----

### **External Tools: The `PythonModule` Node**

The **`PythonModule`** node executes a custom Python script, allowing you to extend workflow capabilities with custom
logic, API calls, or file access. The script must contain an `Invoke(*args, **kwargs)` function that returns a single
string value.

#### **Properties**

| Property          | Type   | Required | Default | Description                                                                                   |
|:------------------|:-------|:---------|:--------|:----------------------------------------------------------------------------------------------|
| **`type`**        | String | Yes      | N/A     | Must be `"PythonModule"`.                                                                     |
| **`title`**       | String | No       | `""`    | A descriptive name for the node.                                                              |
| **`module_path`** | String | Yes      | N/A     | The file path to the Python (`.py`) script. Absolute, or relative (resolved against the cwd first, then the WilmerAI install root). |
| **`args`**        | Array  | No       | `[]`    | A list of positional arguments to pass to the `Invoke` function. Values support variables.    |
| **`kwargs`**      | Object | No       | `{}`    | A dictionary of keyword arguments to pass to the `Invoke` function. Values support variables. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** All values within the `args` array and `kwargs` object support variable substitution.
* **Script Requirement:** The target Python file must define a function `Invoke(*args, **kwargs)` that returns a single
  value, which will be converted to a string.
* **Output Variable:** The string returned by the `Invoke` function becomes the node's output.

#### **Full Syntax Example**

This node executes a script to process data, passing arguments from workflow variables.

```json
{
  "title": "My Custom Python Tool",
  "type": "PythonModule",
  "module_path": "D:/WilmerAI/Public/Scripts/process_data.py",
  "args": [
    "A static string argument",
    "{agent1Output}"
  ],
  "kwargs": {
    "api_key": "your-secret-key",
    "user_id": "{userName}"
  }
}
```

-----

### **External Tools: The Offline Wikipedia Nodes**

The **Offline Wikipedia** nodes query a local `OfflineWikipediaTextApi` service to retrieve factual information from a
Wikipedia database. This is used for Retrieval-Augmented Generation (RAG) by providing context to an LLM. The
`promptToSearch` field supports variables.

#### **`OfflineWikiApiBestFullArticle`**

Performs a broad search and returns only the single best-matching full article.

##### **Full Syntax Example**

```json
{
  "title": "Get Best Article on Alan Turing",
  "type": "OfflineWikiApiBestFullArticle",
  "promptToSearch": "Who was Alan Turing?"
}
```

#### **`OfflineWikiApiFullArticle`**

Retrieves the first full article returned by the search query.

##### **Full Syntax Example**

```json
{
  "title": "Get First-Result Article",
  "type": "OfflineWikiApiFullArticle",
  "promptToSearch": "The geography of Antarctica"
}
```

#### **`OfflineWikiApiPartialArticle`**

Retrieves one or more article summaries (typically the first paragraph).

##### **Properties**

| Property             | Type    | Required | Default | Description                                                         |
|:---------------------|:--------|:---------|:--------|:--------------------------------------------------------------------|
| **`type`**           | String  | Yes      | N/A     | `"OfflineWikiApiPartialArticle"`.                                   |
| **`title`**          | String  | No       | `""`    | A descriptive name.                                                 |
| **`promptToSearch`** | String  | Yes      | N/A     | The search query.                                                   |
| **`percentile`**     | Float   | No       | `0.5`   | Minimum relevance score (0.0 to 1.0) for an article to be included. |
| **`num_results`**    | Integer | No       | `1`     | The number of article summaries to retrieve.                        |

##### **Full Syntax Example**

```json
{
  "title": "Get Photosynthesis Summaries",
  "type": "OfflineWikiApiPartialArticle",
  "promptToSearch": "What is photosynthesis?",
  "num_results": 2
}
```

#### **`OfflineWikiApiTopNFullArticles`**

Returns a specified number of the most relevant full articles.

##### **Properties**

| Property             | Type    | Required | Default | Description                                                                  |
|:---------------------|:--------|:---------|:--------|:-----------------------------------------------------------------------------|
| **`type`**           | String  | Yes      | N/A     | `"OfflineWikiApiTopNFullArticles"`.                                          |
| **`title`**          | String  | No       | `""`    | A descriptive name.                                                          |
| **`promptToSearch`** | String  | Yes      | N/A     | The search query.                                                            |
| **`percentile`**     | Float   | No       | `0.5`   | Minimum relevance score for the initial candidate pool.                      |
| **`num_results`**    | Integer | No       | `10`    | The size of the initial candidate pool.                                      |
| **`top_n_articles`** | Integer | No       | `3`     | The final number of articles to return. A negative value reverses the order. |

##### **Full Syntax Example**

```json
{
  "title": "Get top 3 articles on Roman History",
  "type": "OfflineWikiApiTopNFullArticles",
  "promptToSearch": "The fall of the Roman Republic",
  "top_n_articles": 3
}
```

-----

### **External Tools: The `WebFetch` Node**

The **`WebFetch`** node issues an HTTP request to a user-configured URL using the `requests` library and returns the
response. It is intended for pulling data from arbitrary HTTP/HTTPS endpoints inside a workflow (for example, hitting an
internal API and feeding the response into a later LLM node). All string fields support variable substitution.

#### **Properties**

| Property           | Type    | Required | Default  | Description                                                                                                            |
|:-------------------|:--------|:---------|:---------|:-----------------------------------------------------------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A      | Must be `"WebFetch"`.                                                                                                  |
| **`title`**        | String  | No       | `""`     | A human-readable name for the node.                                                                                    |
| **`url`**          | String  | Yes      | N/A      | The target URL. Supports variable substitution.                                                                        |
| **`method`**       | String  | No       | `"GET"`  | HTTP method. Common values: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`. Case-insensitive.                                 |
| **`headers`**      | Object  | No       | `{}`     | A JSON object of request headers. Values support variable substitution. Header keys are sent as written.               |
| **`body`**         | String  | No       | None     | A raw request body string. Supports variable substitution.                                                             |
| **`timeout`**      | Integer | No       | `30`     | Request timeout in seconds.                                                                                            |
| **`outputFormat`** | String  | No       | `"text"` | One of `"text"` (response body as a string), `"json"` (response body re-serialized as JSON), `"full"` (status/headers/body wrapped in a JSON object), `"html-stripped"` (HTML run through a stdlib-only stripper that removes script/style/head/noscript/iframe content and returns the remaining visible text). |
| **`onError`**      | String  | No       | `"raise"`| `"raise"` aborts the workflow on connection failure or HTTP 4xx/5xx. `"return"` causes the node to emit an error payload (shape matches `outputFormat`) so the workflow can branch on it. |
| **`proxy`**        | String  | No       | None     | Optional proxy URL routed through both `http` and `https` traffic. Any scheme `requests` supports works: `socks5://`, `socks5h://`, `socks4://`, `http://`, `https://`. Supports variable substitution. An empty string is treated as "no proxy". |
| **`caBundle`**     | String  | No       | None     | Opt-in. Path to a CA bundle (PEM) used to verify the server's TLS certificate; verification stays ON. Use for HTTPS endpoints behind a private/internal CA (e.g. `mkcert`). Default verification uses the bundled `certifi` roots, NOT the OS keychain. Supports variable substitution; empty string = not set; a non-existent path raises `ValueError`. |
| **`verify`**       | Boolean | No       | `true`   | Opt-in. `true` (default) verifies against the default `certifi` store. `false` disables TLS verification entirely (logs a warning; vulnerable to MITM; prefer `caBundle`). An explicit `false` takes precedence over `caBundle`. |
| **`allowRedirects`** | Boolean | No     | `true`   | Whether HTTP 3xx redirects are followed. Set `false` to stop a remote redirect from bouncing the request to another host. |
| **`maxResponseBytes`** | Integer | No   | `10485760` | Body-size cap in bytes (10 MiB). The body is streamed and the read aborts past the cap. Set `0` to disable the cap. |

#### **Limitations and Key Usage Notes**

* **`outputFormat: "text"` does not strip HTML.** It returns whatever the server sent, byte-for-byte (decoded via the
  response encoding). For a clean text extraction from HTML, use `outputFormat: "html-stripped"`, which runs the body
  through a stdlib-only stripper (removing script/style/head/noscript/iframe content), or run the response through a
  `PythonModule` node for custom extraction.
* **Privacy / SSRF.** This node makes outbound HTTP calls to the URLs you configure. Wilmer never adds anything to the
  request beyond what you put in the node config. There is no host/IP allowlist, so treat any `url` built from
  conversation-derived variables as untrusted input; see the [WebFetch node doc](Nodes/WebFetch.md) for the SSRF
  warning and the `allowRedirects` control.
* **TLS.** HTTPS is supported transparently via the `requests` library's certificate verification (always on).

#### **Full Syntax Example**

```json
{
  "title": "Fetch user record",
  "agentName": "UserRecord",
  "type": "WebFetch",
  "url": "https://api.example.com/users/{userId}",
  "method": "GET",
  "headers": {
    "Authorization": "Bearer {apiToken}",
    "Accept": "application/json"
  },
  "timeout": 15,
  "outputFormat": "json"
}
```

For detailed documentation including the full error-handling matrix, see [WebFetch Node](Nodes/WebFetch.md).

-----

### **External Tools: The `CurlCommand` Node**

The **`CurlCommand`** node invokes the system `curl` binary via `subprocess.Popen` with `shell=False`, streaming its
output so the response body can be bounded in-process. Arguments are
supplied as a JSON list (no shell parsing), and each element is variable-substituted before being passed to curl. Use
this node when you specifically need the `curl` binary itself, for example to use a curl-only flag or to mirror a
shell command exactly. For most HTTP/HTTPS use cases, prefer the [WebFetch Node](#external-tools-the-webfetch-node).

#### **Properties**

| Property           | Type       | Required | Default    | Description                                                                                                            |
|:-------------------|:-----------|:---------|:-----------|:-----------------------------------------------------------------------------------------------------------------------|
| **`type`**         | String     | Yes      | N/A        | Must be `"CurlCommand"`.                                                                                               |
| **`title`**        | String     | No       | `""`       | A human-readable name for the node.                                                                                    |
| **`args`**         | List       | Yes      | N/A        | A list of strings passed to curl as separate arguments. Each element supports variable substitution.                   |
| **`timeout`**      | Integer    | No       | `30`       | Maximum time in seconds curl is allowed to run.                                                                        |
| **`outputFormat`** | String     | No       | `"stdout"` | One of `"stdout"` (curl's stdout), `"stdout+stderr"` (concatenated), `"full"` (JSON envelope with stdout/stderr/returncode). |
| **`onError`**      | String     | No       | `"raise"`  | `"raise"` aborts the workflow on non-zero exit or timeout. `"return"` causes the node to emit an error payload (shape matches `outputFormat`). |
| **`proxy`**        | String     | No       | None       | Optional proxy URL. Translated to `-x <url>` and prepended to `args` before curl is invoked. Any scheme curl supports works (`socks5://`, `socks5h://`, `socks4://`, `http://`, `https://`). Supports variable substitution. An empty string is treated as "no proxy". |
| **`maxResponseBytes`** | Integer | No     | `10485760` | Body-size cap (10 MiB), enforced two ways: curl's `--max-filesize` is injected for advertised-length responses (unless the author supplied one), and stdout is read incrementally with curl killed the instant the body exceeds the cap (bounds chunked/unknown-length responses too). Set `0` to disable both. |
| **`blockOptionInjection`** | Boolean | No | `false`   | When `true`, rejects an `args` element that resolves (via variable substitution) to a leading-`-` value (a curl option) or a leading-`@` value (an `@file` data read, e.g. `-d @/etc/passwd`) unless its template literally started with that character. Blocks curl-option and local-file-read injection from untrusted variables; prefer `--data-raw` for variable-fed bodies. |
| **`allowSchemeInjection`** | Boolean | No | `false`   | The scheme-injection guard is ON by default: an `args` element whose resolved value introduces a non-`http`/`https` scheme via variable substitution (`file://`, `ftp://`, `dict://`, ...) is rejected; author-literal schemes are allowed. Set `true` to permit substituted schemes. |

#### **Limitations and Key Usage Notes**

* **No shell.** The command is executed with `shell=False`. Shell metacharacters (pipes, redirections, glob expansion)
  do not work. If you need a shell pipeline, wrap it in a small shell script and invoke that script via a `PythonModule`
  node, or use multiple `CurlCommand` nodes chained together.
* **System binary required.** If `curl` is not on the host's PATH, the node raises `FileNotFoundError` at execution
  time.
* **Privacy.** This node makes outbound HTTP/HTTPS calls only to the URLs you configure in the `args` list.
* **`shell=False` blocks shell injection, not curl's own options.** curl can read/write local files via `file://`,
  `-d @file`, and `-o`; a substituted value starting with `-` becomes a curl flag, and one starting with `@` in a data
  slot becomes a local-file read. `blockOptionInjection` (opt-in) blocks substituted `-` and `@` values; use
  `--data-raw` for variable-fed bodies. See the
  [CurlCommand node doc](Nodes/CurlCommand.md) for the full security notes and the `blockOptionInjection` control.

#### **Full Syntax Example**

```json
{
  "title": "POST to internal API",
  "agentName": "ApiResponse",
  "type": "CurlCommand",
  "args": [
    "-sS", "-X", "POST",
    "-H", "Authorization: Bearer {apiToken}",
    "-H", "Content-Type: application/json",
    "-d", "{requestBody}",
    "https://api.example.com/items"
  ],
  "timeout": 20,
  "outputFormat": "full"
}
```

For detailed documentation including the full error-handling matrix and tips on choosing between this node and
`WebFetch`, see [CurlCommand Node](Nodes/CurlCommand.md).

-----

### **External Tools: The `MCPToolCall` Node**

The **`MCPToolCall`** node invokes a single tool on a named Model Context Protocol (MCP) server, with the tool name
and arguments fixed by the workflow author. The LLM is not in the loop; this is a deterministic, workflow-driven
tool call, suited to "fetch this specific piece of data" or "perform this specific action" steps.

Servers are declared once in `Public/Configs/MCPServers/<name>.json` and referenced by name from the node. All three
MCP transports are supported: `stdio` (spawns a subprocess), `sse` (Server-Sent Events over HTTP), and
`streamable_http`.

#### **Properties**

| Property           | Type    | Required | Default   | Description                                                                                                            |
|:-------------------|:--------|:---------|:----------|:-----------------------------------------------------------------------------------------------------------------------|
| **`type`**         | String  | Yes      | N/A       | Must be `"MCPToolCall"`.                                                                                               |
| **`title`**        | String  | No       | `""`      | A human-readable name for the node.                                                                                    |
| **`server`**       | String  | Yes      | N/A       | The name of an MCP server config in `Public/Configs/MCPServers/`. Supports variable substitution.                      |
| **`tool`**         | String  | Yes      | N/A       | The MCP tool to invoke on that server. Supports variable substitution.                                                 |
| **`arguments`**    | Object  | No       | `{}`      | A JSON object of tool arguments. String values support variable substitution; numbers, booleans, lists, and nested objects pass through. |
| **`timeout`**      | Number  | No       | `30`      | Per-call timeout in seconds.                                                                                           |
| **`onError`**      | String  | No       | `"raise"` | `"raise"` aborts the workflow when the MCP call fails. `"return"` causes the node to return the error message so the workflow can branch on it. |

#### **Server Registry**

Each MCP server config under `Public/Configs/MCPServers/` describes one transport. Examples ship under
`MCPServers/_examples/`:

* **stdio** (subprocess):
  ```json
  {
    "transport": "stdio",
    "command": "/absolute/path/to/mcp-server-filesystem",
    "args": ["/path/to/allowed/directory"],
    "env": {},
    "cwd": null
  }
  ```
* **sse**:
  ```json
  {
    "transport": "sse",
    "url": "http://localhost:8888/sse",
    "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE"}
  }
  ```
* **streamable_http**:
  ```json
  {
    "transport": "streamable_http",
    "url": "http://localhost:8888/mcp",
    "headers": {}
  }
  ```

#### **Limitations and Key Usage Notes**

* **One tool per node.** This node is deliberately not an agentic loop. To compose multiple MCP calls or to let an
  LLM choose which tool to call, use multiple nodes (one `MCPToolCall` each).
* **No connection pooling in v1.** Each invocation opens a fresh transport. This is simpler and safer; persistent
  connections may be added later.
* **stdio spawns a subprocess.** The `command` and `args` you configure run on the Wilmer host with the privileges of
  the Wilmer process. Treat them like any other PythonModule-style integration.
* **Privacy.** Outbound traffic is limited to whatever transport you configure: local subprocess (stdio), or the URL
  you wrote down (sse / streamable_http).

#### **Full Syntax Example**

```json
{
  "title": "Read user notes from MCP filesystem",
  "agentName": "UserNotes",
  "type": "MCPToolCall",
  "server": "filesystem",
  "tool": "read_file",
  "arguments": {
    "path": "/data/notes/{userId}.txt"
  },
  "timeout": 15
}
```

For detailed documentation including the full error-handling matrix and per-transport configuration reference, see
[MCPToolCall Node](Nodes/MCPToolCall.md).

-----

### **Concurrency Control: The `WorkflowLock` Node**

The **`WorkflowLock`** node prevents race conditions during long-running, asynchronous operations. It creates a
temporary lock that halts subsequent workflow executions at that point, ensuring a resource-intensive task (like memory
generation) isn't triggered multiple times concurrently. If a lock is active, the workflow terminates immediately.

#### **Properties**

| Property             | Type   | Required | Default | Description                                                                           |
|:---------------------|:-------|:---------|:--------|:--------------------------------------------------------------------------------------|
| **`type`**           | String | Yes      | N/A     | Must be `"WorkflowLock"`.                                                             |
| **`title`**          | String | No       | `""`    | A descriptive name for the node.                                                      |
| **`workflowLockId`** | String | Yes      | N/A     | The unique identifier for the lock. Nodes with the same ID contend for the same lock. |

#### **Limitations and Key Usage Notes**

* **Placement:** The lock should be placed immediately after the responder node and before the long-running task.
* **Automatic Release:** Locks are released upon workflow completion or after a 10-minute safety timeout. They are also
  cleared on application restart.
* **Scope:** Locks are scoped per-user.

#### **Full Syntax Example**

This node acquires a lock before a subsequent node begins a long memory generation process.

```json
{
  "title": "Acquire Lock for Memory Generation",
  "type": "WorkflowLock",
  "workflowLockId": "FullCustomChatSummaryLock"
}
```

-----

### **Context Summarization: The `ContextCompactor` Node**

The **`ContextCompactor`** node compacts conversation history into two rolling summaries using token-based windowing.
It divides the conversation into three sections: **Recent** (untouched), **Old** (topic-focused summary), and
**Oldest** (neutral rolling summary). The output is returned as XML-tagged text compatible with `TagTextExtractor`.

This node is separate from the memory system. All settings come from a dedicated settings file referenced by
`contextCompactorSettingsFile` in the user config.

#### **Properties**

| Property   | Type   | Required | Default | Description                                               |
|:-----------|:-------|:---------|:--------|:----------------------------------------------------------|
| **`type`** | String | Yes      | N/A     | Must be `"ContextCompactor"`.                             |
| **`title`**| String | No       | `""`    | A descriptive name for the node, used for logging.        |

#### **Limitations and Key Usage Notes**

* **Settings File Required:** The node requires `contextCompactorSettingsFile` to be set in the user config, pointing
  to a settings JSON file in the workflow folder. See the
  [ContextCompactor Node documentation](Nodes/ContextCompactor.md) for the full settings reference.
* **Discussion ID Required:** The node requires a `discussionId` to persist summaries. Without one, it returns an
  empty string.
* **Output Format:** The output uses XML-style tags (`<context_compactor_old>` and `<context_compactor_oldest>`) that
  can be extracted using `TagTextExtractor`.
* **Compaction Triggers:** Compaction runs on first use, when messages shift between windows, or when the Old window
  content changes. Otherwise, cached summaries are returned.

#### **Full Syntax Example**

```json
{
  "title": "Compact conversation context",
  "type": "ContextCompactor"
}
```

The output can then be parsed with `TagTextExtractor`:

```json
{
  "title": "Extract Old Section",
  "type": "TagTextExtractor",
  "tagToExtractFrom": "{agent1Output}",
  "fieldToExtract": "context_compactor_old"
}
```