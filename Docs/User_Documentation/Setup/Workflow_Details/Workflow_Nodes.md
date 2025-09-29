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
| **`endpointName`**                          | String  | Yes      | N/A        | The name of the LLM endpoint configuration to use for this node. **This field does not support variables.**                           |
| **`preset`**                                | String  | No       | `null`     | The name of the generation preset to use. If omitted, the endpoint's default is used. **This field does not support variables.**      |
| **`returnToUser`**                          | Boolean | No       | `false`    | If `true`, this node's output is sent to the user. Only one node per workflow can be a responder.                                     |
| **`systemPrompt`**                          | String  | No       | `""`       | The system prompt or initial instruction set for the LLM. Supports variable substitution.                                             |
| **`prompt`**                                | String  | No       | `""`       | The main user-facing prompt. If this is empty, the node will use `lastMessagesToSendInsteadOfPrompt`. Supports variable substitution. |
| **`lastMessagesToSendInsteadOfPrompt`**     | Integer | No       | `5`        | If `prompt` is empty, this specifies how many recent conversational turns to use as the prompt.                                       |
| **`maxResponseSizeInTokens`**               | Integer | No       | `400`      | Overrides the maximum number of tokens the LLM can generate for this node.                                                            |
| **`maxContextTokenSize`**                   | Integer | No       | `4096`     | Overrides the maximum context window size (in tokens) for this node.                                                                  |
| **`jinja2`**                                | Boolean | No       | `false`    | If `true`, enables Jinja2 templating for the `systemPrompt` and `prompt` fields.                                                      |
| **`addDiscussionIdTimestampsForLLM`**       | Boolean | No       | `false`    | If `true`, automatically injects timestamps into the `messages` payload sent to the LLM.                                              |
| **`useRelativeTimestamps`**                 | Boolean | No       | `false`    | If `addDiscussionIdTimestampsForLLM` is `true`, this uses relative timestamps (e.g., "5 minutes ago").                                |
| **`useGroupChatTimestampLogic`**            | Boolean | No       | `false`    | Activates special timestamping logic for group chat-style generation prompts.                                                         |
| **`addUserTurnTemplate`**                   | Boolean | No       | `false`    | Manually wraps the final prompt content in the user turn template defined by the endpoint.                                            |
| **`addOpenEndedAssistantTurnTemplate`**     | Boolean | No       | `false`    | Appends the start of an assistant turn template to the end of the final prompt.                                                       |
| **`forceGenerationPromptIfEndpointAllows`** | Boolean | No       | `false`    | Forces the addition of a generation prompt even if other settings would normally suppress it.                                         |
| **`blockGenerationPrompt`**                 | Boolean | No       | `false`    | Explicitly blocks the addition of any automatic generation prompt.                                                                    |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Variables are only supported in the `systemPrompt` and `prompt` fields. Configuration fields
  like `endpointName` and `preset` must be static strings.
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
  "preset": "Thinker_Preset",
  "maxResponseSizeInTokens": 8000,
  "addUserTurnTemplate": true,
  "returnToUser": false,
  "addDiscussionIdTimestampsForLLM": true,
  "useRelativeTimestamps": true
}
```

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

The **`ConditionalCustomWorkflow` Node** provides powerful branching logic. It dynamically selects and executes a
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
* **Matching Logic:** The match for `conditionalWorkflows` is **case-insensitive**. However, the match for
  `routeOverrides` keys is **case-sensitive** and expects the key to be **Capitalized**.

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

### **Utility: The `GetCustomFile` Node**

The **`GetCustomFile`** node loads the content of a local text file into the workflow as a string. This allows you to
inject large blocks of static text (like instructions or lore) without cluttering the workflow JSON.

#### **Properties**

| Property                    | Type   | Required | Default | Description                                                             |
|:----------------------------|:-------|:---------|:--------|:------------------------------------------------------------------------|
| **`type`**                  | String | Yes      | N/A     | Must be `"GetCustomFile"`.                                              |
| **`title`**                 | String | No       | `""`    | An optional, human-readable name for the node.                          |
| **`filepath`**              | String | Yes      | N/A     | The full path to the text file to load. Supports variables.             |
| **`delimiter`**             | String | No       | `\n`    | An optional string to search for and replace within the file's content. |
| **`customReturnDelimiter`** | String | No       | `\n`    | An optional string that will replace every instance of the `delimiter`. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** The `filepath` field supports variable substitution.
* **File Not Found:** If the file doesn't exist, the node returns `"Custom instruction file did not exist"`.
* **IMPORTANT:** Do not set a delimiter or custom delimiter if you want the file to be pulled as it was originally
  written.

#### **Full Syntax Example**

This node loads a character sheet and replaces a simple `---` separator with a more decorative one.

```json
{
  "title": "Load Character Sheet",
  "type": "GetCustomFile",
  "filepath": "C:\\Users\\User\\Desktop\\character_sheet.txt",
  "delimiter": "---",
  "customReturnDelimiter": "\n**********\n"
}
```

-----

### **Utility: The `SaveCustomFile` Node**

The **`SaveCustomFile`** node writes string content to a local text file. This is useful for saving data generated
during a workflow, such as an LLM's analysis, a conversation summary, or a report.

#### **Properties**

| Property       | Type   | Required | Default | Description                                                       |
|:---------------|:-------|:---------|:--------|:------------------------------------------------------------------|
| **`type`**     | String | Yes      | N/A     | Must be `"SaveCustomFile"`.                                       |
| **`title`**    | String | No       | `""`    | An optional, human-readable name for the node.                    |
| **`filepath`** | String | Yes      | N/A     | The full path where the file will be saved. Supports variables.   |
| **`content`**  | String | Yes      | N/A     | The string content to be written to the file. Supports variables. |

#### **Limitations and Key Usage Notes**

* **Variable Support:** Both `filepath` and `content` fields support full variable substitution.
* **Error Handling:** The node returns a status message indicating success or failure (e.g., due to permissions).

#### **Full Syntax Example**

This node saves a character bio generated by a previous node to a file.

```json
{
  "title": "Save Character Bio to File",
  "type": "SaveCustomFile",
  "filepath": "D:\\WilmerAI\\Characters\\jax_the_pirate.txt",
  "content": "CHARACTER PROFILE\n-----------------\nName: Jax\nBio: {agent1Output}"
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

* **Variable Support:** The `content` field does not support variable substitution; it is treated as a literal string.
* **Streaming:** If `returnToUser` is `true` and the request is for streaming, the content is delivered word-by-word.

#### **Full Syntax Example**

This node sends a pre-written message directly to the user as a final, streaming response.

```json
{
  "title": "Return System Status Message",
  "type": "StaticResponse",
  "content": "Affirmative. All systems are operating within nominal parameters. This is a pre-recorded message.",
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
| **`endpointName`**     | String  | Yes      | N/A     | The name of the vision-capable LLM endpoint. **Does not support variables.**                                      |
| **`systemPrompt`**     | String  | Yes      | N/A     | The system prompt for the vision LLM, instructing it on how to describe the image. Supports variables.            |
| **`prompt`**           | String  | Yes      | N/A     | The user prompt for the vision LLM, guiding what to focus on. Supports variables.                                 |
| **`preset`**           | String  | Yes      | N/A     | The generation preset for the vision LLM. **Does not support variables.**                                         |
| **`addAsUserMessage`** | Boolean | No       | `false` | If `true`, injects the aggregated image description into the conversation history as a new user message.          |
| **`message`**          | String  | No       | N/A     | A template string for the injected message. **Must contain the `[IMAGE_BLOCK]` placeholder.** Supports variables. |

#### **Limitations and Key Usage Notes**

* **Static Configuration:** `endpointName` and `preset` must be hardcoded strings.
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
  "endpointName": "Image-Endpoint",
  "preset": "Vision_Default_Preset",
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
| **`module_path`** | String | Yes      | N/A     | The full, absolute file path to the Python (`.py`) script.                                    |
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
  "module_path": "C:/WilmerAI/Public/Scripts/process_data.py",
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