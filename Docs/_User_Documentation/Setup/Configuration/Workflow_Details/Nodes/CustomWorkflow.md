## Custom Nested Workflows: The `CustomWorkflow` Node

The **`CustomWorkflow` Node** allows you to execute an entire, separate workflow from within the current workflow. This
is incredibly powerful for encapsulating reusable logic, breaking down complex processes into smaller, manageable parts,
and orchestrating multi-step agentic tasks. The final result of the child workflow is captured and stored in the
parent's state, accessible to subsequent nodes.

### How It Works

A child workflow runs in an **isolated context**. It cannot directly access the outputs of the parent workflow (e.g.,
`{agent1Output}` from the parent is unavailable inside the child). Data must be passed in explicitly. The final result
of the child workflow is then returned to the parent and saved as the output of the `CustomWorkflow` node itself.

-----

### Properties

| Property                            | Type             | Required | Default | Description                                                                                                                                                                                                              |
|:------------------------------------|:-----------------|:---------|:--------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                          | String           | Yes      | N/A     | Must be set to `"CustomWorkflow"`.                                                                                                                                                                                       |
| **`title`**                         | String           | No       | ""      | A descriptive title for the node shown in logs.                                                                                                                                                                          |
| **`workflowName`**                  | String           | Yes      | N/A     | The filename of the child workflow to execute (e.g., `"MySubWorkflow.json"`) without the `.json`.                                                                                                                        |
| **`is_responder`**                  | Boolean          | No       | `false` | Determines if this node provides the final, user-facing response. If `true`, the child workflow's output is streamed to the user. If `false`, the output is captured as a variable for later nodes in the parent to use. |
| **`scoped_variables`**              | Array of Strings | No       | `[]`    | **(Recommended)** The list of values to pass from the parent into the child workflow's global scope. These become available to *all nodes* in the child workflow as `{agent1Input}`, `{agent2Input}`, etc.               |
| **`workflowUserFolderOverride`**    | String           | No       | `null`  | Specifies a user folder from which to load the `workflowName`. Use `_common` for workflows shared across all users.                                                                                                      |
| **`firstNodeSystemPromptOverride`** | String           | No       | `null`  | **(Legacy)** Overrides the `systemPrompt` for the very first node in the child workflow. Use `scoped_variables` instead.                                                                                                 |
| **`firstNodePromptOverride`**       | String           | No       | `null`  | **(Legacy)** Overrides the `prompt` for the very first node in the child workflow. Use `scoped_variables` instead.                                                                                                       |

-----

### Data Flow

#### **Passing Data to a Child Workflow (Input)**

1. **`scoped_variables` (Recommended Method):** This is the most powerful and flexible method. The values you list are
   passed to the child workflow and can be accessed *at any node* using the `{agent#Input}` syntax, where the number
   corresponds to the order in the array (e.g., the first item becomes `{agent1Input}`).

    * **Parent Node Config:**
      ```json
      "scoped_variables": [
        "{agent1Output}",          // Becomes {agent1Input} in child
        "{lastUserMessage}"        // Becomes {agent2Input} in child
      ]
      ```
    * **Usage anywhere in the Child Workflow's JSON:**
      ```json
      "prompt": "Analyze this text: '{agent1Input}'. The user's original question was '{agent2Input}'."
      ```

2. **Prompt Overrides (Legacy Method):** You can embed parent variables directly into the `firstNode...PromptOverride`
   properties. This method is limited as the data is only available to the **first node** of the child workflow.

#### **Receiving Data from a Child Workflow (Output)**

The process is simple: The entire final output of the child workflow is treated as the output of the `CustomWorkflow`
node itself. For example, if a `CustomWorkflow` is the **4th node** in your parent workflow, its result will be stored
in the parent's `{agent4Output}` variable.

-----

### Full Syntax Example

This example from a larger research workflow demonstrates calling a reusable child workflow to search Wikipedia and
summarize the findings.

```json
{
  "title": "Custom Wiki Search 1: Initial Search",
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

* **`workflowName`**: Executes the specified summarization workflow.
* **`workflowUserFolderOverride`**: Loads it from the shared `_common` folder.
* **`is_responder`: `false`**: The result (the summary from Wikipedia) will be captured in the `{agent4Output}`
  variable, not sent to the user directly.
* **`scoped_variables`**: Passes the output from the parent's first node (`{agent1Output}`) and third node (
  `{agent3Output}`) into the child workflow, where they will be available as `{agent1Input}` and `{agent2Input}`,
  respectively.
