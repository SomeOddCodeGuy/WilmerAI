### A Technical Guide to WilmerAI Workflow Variables

This guide provides a comprehensive and validated reference to all dynamic variables available within the WilmerAI
workflow system. It has been corrected against the system's source code to ensure accuracy and prevent the generation of
invalid workflows.

#### Core Principle: Dynamic Substitution

The **`WorkflowVariableManager`** service is responsible for replacing placeholders in your workflow's string properties
with real-time data. This happens automatically before a node is executed.

-----

### Part 1: How to Use Variables

#### Standard Formatting (`{...}`)

By default, simply place the variable name in curly braces within any valid string property. The system uses Python's
`str.format()` method for substitution.

```json
{
  "title": "Greet User with Time",
  "type": "Standard",
  "systemPrompt": "Today is {todays_date_pretty}. The current time is {current_time_12h}.",
  "prompt": "Please respond to the user's message: {chat_user_prompt_last_one}"
}
```

#### Jinja2 Templating (Advanced)

For advanced logic like loops or conditionals, add **`"jinja2": true`** to the node's configuration. This allows you to
use the full Jinja2 syntax.

```json
{
  "title": "Render Conversation History",
  "type": "Standard",
  "jinja2": true,
  "prompt": "Here is the conversation so far:\n\n{% for message in messages %}{{ message.role | capitalize }}: {{ message.content }}\n{% endfor %}\n\nHow can I help you now?"
}
```

#### ⚠️ Critical Limitation: Configuration vs. Content

Variable substitution is performed by node handlers on specific fields, not by the core workflow engine. This creates a
critical distinction between what can and cannot be a variable.

**The principle is: Configuration keys are static, content keys can be dynamic.**

##### ✅ Fields that SUPPORT variables (Content)

You **CAN** use variables in fields that are treated as content for the node to process.

* `prompt`
* `systemPrompt`
* `title`
* `promptToSearch` (and similar input fields on specialized nodes)
* `filepath` (in `GetCustomFile`, the handler specifically processes variables for this field)

##### ❌ Fields that DO NOT SUPPORT variables (Configuration)

You **CANNOT** use variables in fields that define a node's configuration. These fields are read by the workflow engine
*before* variables are processed. Using a variable here will cause the workflow to fail. **Always use hardcoded, static
string values for them.**

* `type`
* **`endpointName`** (This is a common mistake. It must be a static string).
* `preset`
* `returnToUser` (This is a boolean `true`/`false`, not a string).
* `workflowName`
* Keys within a `conditionalWorkflows` object.
* `jinja2` (This is a boolean `true`/`false`).

#### Adding Custom Variables (The Correct Way)

You can add your own reusable variables by adding a new key-value pair to the top level of your workflow JSON file. Any
key that is not `"nodes"` will automatically become an available variable for use in **content fields**.

**Correct Example `my_workflow.json`:**

```json
{
  "shared_persona": "You are a witty AI assistant who loves puns.",
  "nodes": [
    {
      "title": "Respond to User",
      "type": "Standard",
      "endpointName": "Creative-Fast-Endpoint",
      "systemPrompt": "{shared_persona}",
      "prompt": "{chat_user_prompt_last_one}",
      "returnToUser": true
    }
  ]
}
```

-----

### Part 2: Complete Variable & Placeholder Reference

This is an exhaustive list of all available variables, validated against `workflow_variable_manager.py`.

#### Custom Workflow Variables

* **`{custom_variable}`**: The value of any top-level key in the workflow's JSON file (except for `"nodes"`).

#### Data Flow Variables

* **`{agent#Output}`**: The string result from a previous node in the **same** workflow. The `#` corresponds to the
  node's position (1-indexed). For example, `{agent1Output}` is the result of the first node.
* **`{agent#Input}`**: A value passed from a parent workflow into a child workflow via the `scoped_variables` property
  of a `CustomWorkflow` node. The `#` corresponds to the value's position in the `scoped_variables` list (1-indexed).

#### Conversation History Variables

* **`{chat_user_prompt_last_one}`**: The raw text of the last message in the conversation.
* **`{chat_user_prompt_last_two}`**: Raw text of the last 2 turns.
* **`{chat_user_prompt_last_three}`**: Raw text of the last 3 turns.
* **`{chat_user_prompt_last_four}`**: Raw text of the last 4 turns.
* **`{chat_user_prompt_last_five}`**: Raw text of the last 5 turns.
* **`{chat_user_prompt_last_ten}`**: Raw text of the last 10 turns.
* **`{chat_user_prompt_last_twenty}`**: Raw text of the last 20 turns.
* **`{templated_user_prompt_last_one}`**: The last message, formatted with the LLM's chat template (e.g.,
  `[INST]...[/INST]`).
* **`{templated_user_prompt_last_two}`**: Last 2 turns, templated.
* **`{templated_user_prompt_last_three}`**: Last 3 turns, templated.
* **`{templated_user_prompt_last_four}`**: Last 4 turns, templated.
* **`{templated_user_prompt_last_five}`**: Last 5 turns, templated.
* **`{templated_user_prompt_last_ten}`**: Last 10 turns, templated.
* **`{templated_user_prompt_last_twenty}`**: Last 20 turns, templated.
* **`{chat_system_prompt}`**: The system prompt sent from the front-end client.
* **`{system_prompts_as_string}`**: All system messages from the conversation history concatenated into a single string.
* **`{messages}`**: The entire conversation history as a raw list of dictionaries (e.g.,
  `[{'role': 'user', 'content': '...'}]`). **Note**: This is available for both standard formatting and Jinja2, but it
  is most useful with Jinja2 for iterating over the conversation history.

#### Date & Time Variables

* **`{todays_date_pretty}`**: e.g., "August 30, 2025"
* **`{todays_date_iso}`**: e.g., "2025-08-30"
* **`{current_time_12h}`**: e.g., "08:00 PM"
* **`{current_time_24h}`**: e.g., "20:00"
* **`{current_month_full}`**: e.g., "August"
* **`{current_day_of_week}`**: e.g., "Saturday"
* **`{current_day_of_month}`**: e.g., "30"

#### Context & Memory Variables

* **`{time_context_summary}`**: A natural language summary of the conversation's timeline (e.g., "The user started this
  conversation a few minutes ago").
* **`{current_chat_summary}`**: **⚠️ UNAVAILABLE VARIABLE:** The helper function `generate_chat_summary_variables` that
  populates this is **not called** by the main variable generation logic. **Do not use `{current_chat_summary}`** as it
  will not be substituted. To get the summary, you must use a dedicated node like `GetCurrentSummaryFromFile`.

#### Special Placeholders (Context-Specific)

These are not standard variables but are special keywords replaced within specific node types or sub-workflows. They do
**not** use curly braces. Their processing logic is not present in the core `WorkflowVariableManager` and is handled by
specialized workflows (e.g., those called by the `QualityMemory` node).

* **`[TextChunk]`**: Represents a block of text to be processed into a memory.
* **`[IMAGE_BLOCK]`**: Represents the AI-generated description of an image within an `ImageProcessor` context.
* **`[Memory_file]`**, **`[Full_Memory_file]`**, **`[Chat_Summary]`**: Represent various memory files for file-based
  memory generation.
* **`[LATEST_MEMORIES]`**, **`[CHAT_SUMMARY]`**: Used specifically by the `chatSummarySummarizer` node type.


