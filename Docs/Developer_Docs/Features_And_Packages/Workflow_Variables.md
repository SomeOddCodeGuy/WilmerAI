### **Developer Guide: Workflow Variables**

This document provides a comprehensive guide to using dynamic variables within the WilmerAI workflow system. It details
the available built-in variables, the powerful Jinja2 templating engine, and the simple process for adding custom
variables directly from a workflow's JSON configuration.

The system is powered by the **`$WorkflowVariableManager$`**, a service that leverages the central *
*`$ExecutionContext$`** to make a wide range of data available for substitution in prompts and tool arguments.

-----

## 1\. Available Variables (Reference Guide)

The following variables are automatically available within any prompt in a workflow.

#### **Custom Workflow Variables**

Any top-level key (except for `"nodes"`) in your workflow JSON file is automatically available as a variable.

- `{my_custom_variable}`: The value of the `"my_custom_variable"` key in the JSON file.

#### **Inter-Node Variables**

These variables allow you to pass data between nodes and between parent and child workflows.

- `{agent<N>Output}`: The string result from the Nth node (1-indexed) in the **current** workflow. For example,
  `{agent1Output}` is the result of the first node.
- `{agent<N>Input}`: A value passed into a sub-workflow from a parent workflow via `scoped_variables`. For example,
  `{agent1Input}` is the first value passed from the parent.

#### **Conversation History Variables**

Multiple formats of the conversation history are provided.

- `{chat_user_prompt_last_<N>}`: The last N turns of the conversation, formatted as a raw string. Supported values for N
  are `1`, `2`, `3`, `4`, `5`, `10`, `20`. Example: `{chat_user_prompt_last_one}`.
- `{templated_user_prompt_last_<N>}`: The last N turns of the conversation, formatted with the LLM's specific chat
  template (e.g., adding `[INST]` tokens). Supported values for N are the same as above.
- `{chat_user_prompt_n_messages}`: The last N turns as a raw string, where N is configured by the node-level property
  `nMessagesToIncludeInVariable` (defaults to 5). This is the preferred approach when the hardcoded counts above do not
  meet your needs, since any integer value is supported.
- `{templated_user_prompt_n_messages}`: Same as above, but formatted with the LLM's chat template. Controlled by the
  same `nMessagesToIncludeInVariable` property.
- `{chat_user_prompt_estimated_token_limit}`: Recent turns as a raw string, selected by estimated token budget rather
  than message count. The budget is configured by the node-level property `estimatedTokensToIncludeInVariable` (defaults
  to 2048). Starting from the most recent message and working backwards, messages are included as long as the
  accumulated estimated token count stays within the budget. At least one message is always included, even if it alone
  exceeds the budget. Token estimation uses `rough_estimate_token_length`, which intentionally overestimates by using
  the higher of a word-based estimate (1.35 tokens/word) and a character-based estimate (3.5 chars/token), then
  applying a configurable `safety_margin` multiplier (default 1.10).
- `{templated_user_prompt_estimated_token_limit}`: Same as above, but formatted with the LLM's chat template.
  Controlled by the same `estimatedTokensToIncludeInVariable` property.
- `{chat_user_prompt_min_n_max_tokens}`: A combination of the N-messages and token-limit approaches. This variable
  pulls a minimum number of messages (set by `minMessagesInVariable`, defaults to 5), then continues adding older
  messages as long as the accumulated estimated token count stays within the budget (set by
  `maxEstimatedTokensInVariable`, defaults to 2048). The minimum message count takes precedence: if the minimum
  messages alone exceed the token budget, they are all still included. Beyond the minimum, expansion stops when the next
  message would push the total past the token limit. This is useful when you want at least N messages of context, but
  are willing to include more if the conversation messages are short enough to fit within a token budget.
- `{templated_user_prompt_min_n_max_tokens}`: Same as above, but formatted with the LLM's chat template. Controlled by
  the same `minMessagesInVariable` and `maxEstimatedTokensInVariable` properties.
- `{chat_system_prompt}`: The system prompt sent from the front-end client.
- `{templated_system_prompt}`: The system prompt formatted with the LLM's specific chat template.
- `{templated_user_prompt_without_system}`: The full conversation (excluding system messages) formatted with the LLM's
  chat template.
- `{chat_user_prompt_without_system}`: The full conversation (excluding system messages) as a raw string.
- `{messages}`: The entire conversation history as a list of dictionaries (`[{'role': 'user', 'content': '...'}]`). This
  is primarily for use with **Jinja2 templating**.

**Conversation Variable Formatting Options:**

The `chat_user_prompt_*` variables (all raw/non-templated conversation variables) support two formatting controls that
alter how messages are joined into a string:

- **Node-level `addUserAssistantTags`** (boolean, default `false`): When `true`, each message is prefixed with its role
  (`User: `, `Assistant: `, `System: `). This is a per-node setting read from `context.config`, so different nodes in the
  same workflow can produce differently formatted conversation strings. Does not affect the `templated_user_prompt_*`
  variables, which already have their own template-driven formatting.
- **User-level `separateConversationInVariables`** (boolean, default `false`) and **`conversationSeparationDelimiter`**
  (string, default `"\n"`): When `separateConversationInVariables` is `true`, the delimiter from
  `conversationSeparationDelimiter` replaces the default `\n` between messages. Read via `get_separate_conversation_in_variables()`
  and `get_conversation_separation_delimiter()` in `config_utils.py`. These apply globally to all nodes.

Both options can be combined. Implementation: `generate_variables()` reads the node config and user config to determine
`add_role_tags` and `separator`, then passes them to `generate_conversation_turn_variables()` and to each of the
configurable variable builders (`extract_last_n_turns_as_string`, `extract_last_turns_by_estimated_token_limit_as_string`,
`extract_last_turns_with_min_messages_and_token_limit_as_string`). The underlying shared helper is
`_format_messages_to_string()` in `prompt_extraction_utils.py`.

**Tool Call Visibility (`includeToolCallsInConversation`):**

When the conversation history contains assistant messages with a `tool_calls` field but empty or null `content` (common
with agentic frontends), those messages appear as blank turns in the conversation variables by default. The node-level
boolean property `includeToolCallsInConversation` (default `false`) controls whether these tool calls are rendered as
text.

When enabled, `generate_variables()` preprocesses the messages through `enrich_messages_with_tool_calls()` (in
`prompt_extraction_utils.py`) before passing them to any conversation variable builder. This function creates a shallow
copy of the messages list; for each assistant message with `tool_calls`, it creates a new dict with the tool call text
injected into `content`. Messages without tool calls pass through as-is. The original `context.messages` are never
mutated.

Each tool call is formatted by `format_tool_calls_as_text()` as `[Tool Call: {name}] {summary}`, where the summary is
produced by `_summarize_tool_arguments()`: it parses the arguments JSON, returns the first string-valued field truncated
to 200 characters, or falls back to the raw arguments string truncated to 200 characters. Multiple tool calls in a
single message produce one line each, joined by newlines. If the assistant message already has non-empty `content`, the
tool call text is appended after a newline. The enriched tool call text is passed through `escape_brackets_in_string()`
before injection, replacing any literal `{`/`}` with `__WILMER_L_CURLY__`/`__WILMER_R_CURLY__` sentinel tokens. This
prevents `str.format()` in `apply_variables()` from misinterpreting JSON braces in tool arguments as format
placeholders.

The enriched messages are used for both the hardcoded conversation turn variables (`generate_conversation_turn_variables`)
and the configurable slice variables (`messages_copy`). The `format_system_prompts` call still receives the original
`context.messages` since system prompts are unaffected.

#### **Category Variables (Internal)**

These variables are generated by the categorization system (`extract_additional_attributes()`) and are primarily used
internally by `ConditionalCustomWorkflow` categorization prompts, but since they are regular variables in the dict,
they can be used in any prompt.

- `{category_list}`: Comma-separated list of category names.
- `{category_descriptions}`: Category names followed by their descriptions.
- `{category_colon_descriptions}`: Category names and descriptions separated by colons.
- `{categoriesSeparatedByOr}`: Category names joined with "or" (e.g., "Python or JavaScript or General").
- `{category_colon_descriptions_newline_bulletpoint}`: Category descriptions formatted as a bulleted list.
- `{categoryNameBulletpoints}`: Category names formatted as a bulleted list.

#### **Date & Time Variables**

A variety of pre-formatted date and time strings are available.

- `{todays_date_pretty}`: Example: `August 17, 2025`
- `{todays_date_iso}`: Example: `2025-08-17`
- `{YYYY_MM_DD}`: Example: `2025_08_17` (underscore-separated format, useful for filenames)
- `{current_time_12h}`: Example: `7:09 PM`
- `{current_time_24h}`: Example: `19:09`
- `{current_month_full}`: Example: `August`
- `{current_day_of_week}`: Example: `Sunday`
- `{current_day_of_month}`: Example: `17`

#### **Contextual Variables**

- `{Discussion_Id}`: The unique identifier for the current conversation/discussion. Useful for creating per-conversation
  files or organizing data by session. If no discussion ID is present, this will be an empty string.
- `{time_context_summary}`: A human-readable summary of when the conversation started (e.g., "The user started this
  conversation a few minutes ago").

#### **Dynamic File Path Variables**

The `{Discussion_Id}` and `{YYYY_MM_DD}` variables are particularly useful with the `GetCustomFile` and `SaveCustomFile`
nodes, which support variable substitution in their `filepath` fields. This enables per-conversation or date-based file
storage patterns.

**Implementation Details:**
- The `filepath` field in both nodes is processed through `WorkflowVariableManager.apply_variables()` before the file
  operation is performed.
- See `specialized_node_handler.py` (`handle_get_custom_file` and `handle_save_custom_file` methods) for the
  implementation.

**Example Usage:**

```json
{
  "type": "SaveCustomFile",
  "filepath": "/data/{YYYY_MM_DD}/{Discussion_Id}_output.txt",
  "content": "{agent1Output}"
}
```

-----

## 2\. How to Use Variables

There are two ways to use variables in your prompts: standard formatting and the more powerful Jinja2 templating.

### Standard Formatting

By default, you can insert any variable into a prompt using curly braces. The system uses Python's `str.format()` method
for substitution.

```json
{
  "type": "Standard",
  "prompt": "The current time is {current_time_12h}. Please respond to this message: {chat_user_prompt_last_one}"
}
```

### Jinja2 Templating (Advanced)

For more complex logic, like loops or conditionals, you can enable the Jinja2 templating engine by adding
`"jinja2": true` to your node's configuration. This gives you access to the full power of Jinja2 syntax.

This is especially useful with the `{messages}` variable, which provides the entire conversation history as a list.

**Example: A node that summarizes a conversation using a Jinja2 loop.**

```json
{
  "type": "Standard",
  "endpointName": "Ollama-Llama3",
  "jinja2": true,
  "prompt": "Please summarize the following conversation:\n{% for message in messages %}\n{{ message.role }}: {{ message.content }}\n{% endfor %}"
}
```

-----

## 3\. How to Add a Custom Variable

Adding a new, reusable variable to a workflow is simple and **requires no code changes**.

#### **Step 1: Add the Variable to the Workflow Config**

Add your new key-value pair to the top level of your workflow's JSON file (e.g., in
`Public/Configs/Workflows/my_workflow.json`).

```json
{
  "persona_details": "You are a senior data analyst at a financial services firm.",
  "creative_guideline": "Your answers should be concise and data-driven.",
  "nodes": [
    {
      "type": "Standard",
      "returnToUser": true,
      "endpointName": "Ollama-Llama3",
      "systemPrompt": "{persona_details} You must follow this rule: {creative_guideline}",
      "prompt": "Help the user with their geography question: {chat_user_prompt_last_one}"
    }
  ]
}
```

#### **Step 2: Use the Variable in Your Prompts**

You can now immediately use `{persona_details}` and `{creative_guideline}` in any prompt within that workflow. The
system will automatically find and substitute them. **No further steps are needed.**

-----

## 4\. How It Works (Under the Hood)

The system is designed to make adding custom variables trivial by isolating the change to the JSON configuration file.

1. **`$WorkflowManager$` Loads the Config:** The manager loads the entire workflow JSON file into a
   `workflow_file_config` dictionary.

2. **`$WorkflowProcessor$` Populates the Context:** This entire dictionary is passed to the processor, which then places
   it into the `workflow_config` field of the `$ExecutionContext$` for each node.

3. **`$WorkflowVariableManager$` Reads All Keys:** The variable manager receives the context and has a generic loop that
   iterates over the `workflow_config` dictionary, making each top-level key (except `"nodes"`) available for
   substitution.

### Early Variable Substitution for `endpointName` and `preset`

As of recent updates, the `endpointName` and `preset` fields support a special form of **early variable substitution**. This occurs in `WorkflowProcessor._process_section()` BEFORE the LLM handler is loaded and BEFORE nodes execute.

**Technical Implementation:**
- The processor creates a minimal `ExecutionContext` with only pre-execution variables
- This context includes `agent_inputs` (from parent workflows) and `workflow_config` (static variables)
- It explicitly excludes `agent_outputs` since no nodes have executed yet
- Variables are applied to `endpointName` and `preset` using this limited context
- The substituted values are then used to load the LLM handler

**Available Variables for Early Substitution:**
- `{agent#Input}` - Passed from parent workflows
- Custom static variables from workflow JSON top-level

**NOT Available:**
- `{agent#Output}` - These don't exist until nodes execute
- Date/time variables (only generated in the full `generate_variables()` method)
- Conversation history variables (require an LLM handler and full context)
- `{time_context_summary}` (requires timestamp service and discussion ID)
- Any variable dependent on node execution results

This design allows nested workflows to pass endpoint configurations while maintaining the architecture where the LLM handler is loaded before node execution.

### Conversation Variable Formatting Pipeline

The formatting of `chat_user_prompt_*` variables is controlled by two independent settings that are resolved in
`generate_variables()` before any conversation variable is built:

```python
# In WorkflowVariableManager.generate_variables(...)

# --- Conversation formatting settings ---
add_role_tags = False
separator = '\n'
if context.config and isinstance(context.config, dict):
    add_role_tags = context.config.get('addUserAssistantTags', False)
if get_separate_conversation_in_variables():
    separator = get_conversation_separation_delimiter()
```

These two values (`add_role_tags`, `separator`) are then passed as keyword arguments to:
- `generate_conversation_turn_variables(...)` — which builds the hardcoded-count variables (last_one through last_twenty)
- `extract_last_n_turns_as_string(...)` — for the `{chat_user_prompt_n_messages}` variable
- `extract_last_turns_by_estimated_token_limit_as_string(...)` — for the `{chat_user_prompt_estimated_token_limit}` variable
- `extract_last_turns_with_min_messages_and_token_limit_as_string(...)` — for the `{chat_user_prompt_min_n_max_tokens}` variable

All of these ultimately call `_format_messages_to_string()` in `prompt_extraction_utils.py`, which applies role prefixes
and joins with the configured separator:

```python
_ROLE_TAG_MAP = {
    "user": "User: ",
    "assistant": "Assistant: ",
    "system": "System: ",
}

def _format_messages_to_string(messages, add_role_tags=False, separator='\n'):
    formatted_lines = []
    for message in messages:
        content = message.get("content", "")
        if add_role_tags:
            role = message.get("role", "").lower()
            prefix = _ROLE_TAG_MAP.get(role, "")
            content = prefix + content
        formatted_lines.append(content)
    return separator.join(formatted_lines)
```

**Key files:**
- `/Middleware/workflows/managers/workflow_variable_manager.py` — reads settings, passes to builders
- `/Middleware/utilities/prompt_extraction_utils.py` — `_format_messages_to_string()` and the three `_as_string` functions
- `/Middleware/utilities/config_utils.py` — `get_separate_conversation_in_variables()`, `get_conversation_separation_delimiter()`

**File:** `/Middleware/workflows/managers/workflow_variable_manager.py`

```python
# In WorkflowVariableManager.generate_variables(...)

# --- Custom top-level variables from workflow JSON ---
if context.workflow_config:
    for key, value in context.workflow_config.items():
        if key != "nodes":  # Exclude the nodes list itself
            variables[key] = value
```

### Sentinel Escaping for Agent Outputs and Inputs

Agent output and input values (`{agent#Output}`, `{agent#Input}`) may contain literal curly braces. This commonly
occurs when a node produces JSON-formatted output (e.g., tool call data), or when a `GetCustomFile` node loads a file
whose contents were previously saved with real braces restored by `return_brackets_in_string()`.

To prevent `str.format()` in `apply_variables()` from misinterpreting these braces as format placeholders (which would
raise a `ValueError: unmatched '{' in format spec`), `generate_variables()` escapes all string-valued agent outputs and
inputs using `escape_brackets_in_string()` before adding them to the variables dictionary. This replaces `{`/`}` with
the `__WILMER_L_CURLY__`/`__WILMER_R_CURLY__` sentinel tokens — the same mechanism used at the gateway for message
content. After `str.format()` completes, `return_brackets_in_string()` restores them to real braces in the final output.

Custom workflow config variables (top-level keys in the JSON file) are intentionally NOT escaped, because they support
nested variable resolution (e.g., `"my_path": "data/{Discussion_Id}/output.txt"` must have its `{Discussion_Id}`
resolved on the second format pass).

**Key files:**
- `/Middleware/utilities/text_utils.py` — `escape_brackets_in_string()` (forward), `return_brackets_in_string()` (reverse)
- `/Middleware/workflows/managers/workflow_variable_manager.py` — escaping in `generate_variables()`, restoration in `apply_variables()`
- `/Middleware/utilities/prompt_extraction_utils.py` — `enrich_messages_with_tool_calls()` also escapes tool call text