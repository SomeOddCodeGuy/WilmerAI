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
- `{system_prompts_as_string}`: All system messages from the conversation history, concatenated into a single string.
- `{messages}`: The entire conversation history as a list of dictionaries (`[{'role': 'user', 'content': '...'}]`). This
  is primarily for use with **Jinja2 templating**.

#### **Date & Time Variables**

A variety of pre-formatted date and time strings are available.

- `{todays_date_pretty}`: Example: `August 17, 2025`
- `{todays_date_iso}`: Example: `2025-08-17`
- `{current_time_12h}`: Example: `7:09 PM`
- `{current_time_24h}`: Example: `19:09`
- `{current_month_full}`: Example: `August`
- `{current_day_of_week}`: Example: `Sunday`
- `{current_day_of_month}`: Example: `17`

#### **Contextual Variables**

- `{time_context_summary}`: A human-readable summary of when the conversation started (e.g., "The user started this
  conversation a few minutes ago").

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
  "persona_details": "You are a witty pirate cartographer from the 17th century.",
  "creative_guideline": "Your answers should be imaginative and slightly dramatic.",
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
- Date/time variables
- Conversation history variables
- `{time_context_summary}`

**NOT Available:**
- `{agent#Output}` - These don't exist until nodes execute
- Any variable dependent on node execution results

This design allows nested workflows to pass endpoint configurations while maintaining the architecture where the LLM handler is loaded before node execution.

**File:** `/Middleware/workflows/managers/workflow_variable_manager.py`

```python
# In WorkflowVariableManager.generate_variables(...)

# --- Custom top-level variables from workflow JSON ---
if context.workflow_config:
    for key, value in context.workflow_config.items():
        if key != "nodes":  # Exclude the nodes list itself
            variables[key] = value
```