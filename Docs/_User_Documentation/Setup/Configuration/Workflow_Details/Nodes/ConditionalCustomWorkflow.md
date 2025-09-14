## In-Workflow Routing: The `ConditionalCustomWorkflow` Node

The **`ConditionalCustomWorkflow` Node** extends the `CustomWorkflow` node with powerful branching logic. It dynamically
selects and executes a specific sub-workflow based on the resolved value of a conditional variable (e.g., the output
from a previous node). This allows you to create adaptive workflows that react differently based on runtime conditions.

Each potential path, or "route," can also have its own unique prompt overrides, giving you fine-grained control over how
each selected sub-workflow is initiated.

-----

### Properties

| Property                         | Type             | Required | Default | Description                                                                                                                                  |
|:---------------------------------|:-----------------|:---------|:--------|:---------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                       | String           | Yes      | N/A     | Must be set to `"ConditionalCustomWorkflow"`.                                                                                                |
| **`title`**                      | String           | No       | ""      | A descriptive title for the node shown in logs.                                                                                              |
| **`is_responder`**               | Boolean          | No       | `false` | Determines if the *selected* sub-workflow provides the final user-facing response.                                                           |
| **`conditionalKey`**             | String           | Yes      | N/A     | A variable placeholder (e.g., `{agent1Output}`) whose resolved value determines which workflow to execute.                                   |
| **`conditionalWorkflows`**       | Object           | Yes      | N/A     | A dictionary mapping the possible values of `conditionalKey` to workflow filenames. A special **`"Default"`** key can be used as a fallback. |
| **`scoped_variables`**           | Array of Strings | No       | `[]`    | **(Recommended)** A list of values to pass into whichever child workflow is chosen. Works identically to the `CustomWorkflow` node.          |
| **`routeOverrides`**             | Object           | No       | `{}`    | A dictionary specifying prompt overrides for each potential route. The keys here should correspond to the keys in `conditionalWorkflows`.    |
| **`workflowUserFolderOverride`** | String           | No       | `null`  | Specifies a user folder from which to load the selected workflow. Use `_common` for shared workflows.                                        |

-----

### Behavior and Logic Flow

1. **Conditional Execution**: The node resolves the value of `conditionalKey`. It then performs a **case-insensitive**
   search for that value as a key within the `conditionalWorkflows` map. For example, if `{agent1Output}` resolves to
   `"python"`, `"Python"`, or `"PYTHON"`, it will correctly match the `"Python"` key and select the corresponding
   workflow. If no match is found, it will use the workflow specified under the `Default` key.

2. **⚠️ Known Issue: Route Override Key Casing**: When looking for overrides in the `routeOverrides` map, the logic is
   different. The system will look for a key that matches the **Capitalized** version of the resolved `conditionalKey`
   value (e.g., `"python"` becomes `"Python"`). This means the keys in your `routeOverrides` object **must be
   capitalized** to be found.

    * ✅ **Correct**: `"Python"`, `"JavaScript"`
    * ❌ **Incorrect**: `"python"`, `"javascript"`

3. **Fallback Behavior**: If `routeOverrides` is not defined for a matching route, the selected sub-workflow will
   execute using its own default prompts.

-----

### Full Syntax Example

This node first determines the programming language needed and then routes to a specialized workflow for it, passing the
user's message in as context.

```json
{
  "title": "Route to a Specific Coding Model",
  "type": "ConditionalCustomWorkflow",
  "is_responder": true,
  "conditionalKey": "{agent1Output}",
  "conditionalWorkflows": {
    "Python": "PythonCodingWorkflow",
    "JavaScript": "JavaScriptCodingWorkflow",
    "Default": "GeneralCodingWorkflow"
  },
  "scoped_variables": [
    "{lastUserMessage}"
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

* **`conditionalKey`**: The node will check the value of `{agent1Output}`.
* **`conditionalWorkflows`**: If the value is (case-insensitively) `"Python"`, it will run `PythonCodingWorkflow`.
  If it's `"JavaScript"`, it runs `JavaScriptCodingWorkflow`. For anything else, it falls back to the `"Default"`
  workflow.
* **`scoped_variables`**: The user's last message will be passed to the chosen workflow and be available as
  `{agent1Input}`.
* **`routeOverrides`**: If the `"Python"` route is chosen, the system prompt of the first node in that child workflow
  will be overridden with the specified text. Note that `"Python"` and `"JavaScript"` are correctly capitalized.

-----

