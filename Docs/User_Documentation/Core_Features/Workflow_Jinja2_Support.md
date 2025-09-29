### **Developer Guide: Workflow Node Jinja2 Support**

This guide provides a comprehensive overview of how to leverage the **Jinja2 templating engine** within WilmerAI
workflow nodes. While standard variable substitution (`{my_variable}`) is suitable for simple cases, enabling Jinja2
unlocks advanced capabilities like conditional logic, loops, and data manipulation directly within your prompts.

This feature is powered by the `$WorkflowVariableManager$`, which dynamically switches between standard formatting and
the Jinja2 engine based on a simple flag in your node's configuration.

-----

### \#\# 1. Overview & Key Capabilities

Jinja2 is a powerful templating language for Python. By enabling it on a per-node basis, you can transform static prompt
strings into dynamic, logic-driven templates that react to the state of the workflow in real-time.

**Key Capabilities:**

* **Conditional Logic:** Use `{% if ... %}` statements to change parts of a prompt based on the output of previous nodes
  or other variables.
* **Dynamic Loops:** Iterate over lists—most notably the `{messages}` variable—using `{% for ... %}` loops to format
  conversation histories or other collections of data precisely.
* **Direct Variable Access:** All standard workflow variables (e.g., `{agent1Output}`, `{todays_date_pretty}`) are
  available within the Jinja2 context.
* **Seamless Integration:** The feature is a non-breaking, opt-in enhancement. Nodes without the Jinja2 flag continue to
  function with standard substitution.

-----

### \#\# 2. How to Enable and Use Jinja2

Activating the Jinja2 engine for a specific node is as simple as adding a single property to its JSON configuration.

#### **Step 1: Enable the Jinja2 Flag**

In any node that has a string field you wish to template (like `prompt` in a `Standard` node or `content` in a
`StaticResponse` node), add the following property:

```json
"jinja2": true
```

#### **Step 2: Write Your Template**

Once enabled, you can use Jinja2 syntax in the relevant string fields. Remember these two core syntax elements:

* **Statements `{% ... %}`:** Used for control flow, such as `if` conditions and `for` loops.
* **Expressions `{{ ... }}`:** Used to **print** the value of a variable into the final string. This is the most common
  source of errors; you must use `{{ my_variable }}` instead of `{my_variable}` to display a variable's content.

-----

### \#\# 3. Examples and Use Cases

#### **Example 1: Conditional Prompting**

This is a powerful pattern for creating chains that react to the output of a previous "thinking" or "classification"
step. Here, the system prompt for a `Standard` node changes based on the result of the first node.

```json
{
  "nodes": [
    {
      "title": "1. Classify User Intent",
      "type": "Standard",
      "prompt": "Does the user's last message ask a question or make a statement? Respond with only QUESTION or STATEMENT.",
      "endpointName": "Fast-Classifier-Endpoint",
      "returnToUser": false
    },
    {
      "title": "2. Respond Based on Intent",
      "type": "Standard",
      "jinja2": true,
      "systemPrompt": "{% if agent1Output == 'QUESTION' %}Your task is to answer the user's question directly and concisely.{% else %}Your task is to acknowledge the user's statement and ask a relevant follow-up question.{% endif %}",
      "prompt": "Based on your task, respond to the following: {{chat_user_prompt_last_one}}",
      "endpointName": "Creative-Endpoint",
      "returnToUser": true
    }
  ]
}
```

#### **Example 2: Formatting Conversation History with a Loop**

The `{messages}` variable provides the entire conversation history as a list of dictionaries. This is perfect for a
`for` loop to format the history exactly as needed for a summarization or analysis task.

```json
{
  "title": "Summarize the Conversation",
  "type": "Standard",
  "endpointName": "Summarizer-Large-Context",
  "jinja2": true,
  "prompt": "Please create a concise, third-person summary of the following chat log:\n\n--- CHAT LOG START ---\n{% for message in messages %}\n{{ message.role | capitalize }}: {{ message.content }}\n{% endfor %}\n--- CHAT LOG END ---\n\nSummary:",
  "returnToUser": true
}
```

* In this example, `{{ message.role | capitalize }}` also demonstrates a **filter**, another powerful Jinja2 feature
  that can modify the variable before it's printed.

-----

### \#\# 4. How It Works (Under the Hood)

The logic for handling Jinja2 is centralized within the `$WorkflowVariableManager$`.

1. **Handler Invocation:** A node handler (e.g., ` $StandardNodeHandler$ or  `$SpecializedNodeHandler$` ) calls the  `
   workflow\_variable\_service.apply\_variables()
   `method, passing it the raw prompt string and the current`$ExecutionContext$\`.

2. **Flag Check:** The `apply_variables` method checks for the `jinja2` flag within the context object:
   `context.config.get('jinja2', False)`.

3. **Conditional Rendering:**

    * If the flag is `true`, the method uses the `jinja2` library. It creates a `template` object from the prompt string
      and calls `template.render(**variables)`, passing in the dictionary of all available workflow variables.
    * If the flag is `false` or absent, the method falls back to using Python's standard `prompt.format(**variables)`.

This design ensures that the feature is fully self-contained within the variable substitution logic and can be easily
applied to any node or string field without requiring changes to the node handlers themselves.