### **In-Workflow Routing: The `ConditionalCustomWorkflow` Node**

The **`ConditionalCustomWorkflow` Node** extends the `CustomWorkflow` node with powerful branching logic. It dynamically
selects and executes a specific sub-workflow based on the resolved value of a conditional variable (e.g., the output
from a previous node). This allows you to create adaptive workflows that react differently based on runtime conditions.

As a fallback, you can now provide static content to be returned if no condition is met, preventing the need to create a
separate workflow file for a simple default response. Each potential path, or "route," can also have its own unique
prompt overrides, giving you fine-grained control over how each selected sub-workflow is initiated.

-----

### Properties

| Property                                 | Type             | Required | Default | Description                                                                                                                                                                                                       |
|:-----------------------------------------|:-----------------|:---------|:--------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                               | String           | Yes      | N/A     | Must be set to `"ConditionalCustomWorkflow"`.                                                                                                                                                                     |
| **`title`**                              | String           | No       | ""      | A descriptive title for the node shown in logs.                                                                                                                                                                   |
| **`is_responder`**                       | Boolean          | No       | `false` | Determines if the output (from a sub-workflow or default content) provides the final user-facing response.                                                                                                        |
| **`conditionalKey`**                     | String           | Yes      | N/A     | A variable placeholder (e.g., `{agent1Output}`) whose resolved value determines which workflow to execute.                                                                                                        |
| **`conditionalWorkflows`**               | Object           | Yes      | N/A     | A dictionary mapping the possible values of `conditionalKey` to workflow filenames. A special **`"Default"`** key can be used as a fallback.                                                                      |
| **`UseDefaultContentInsteadOfWorkflow`** | String           | No       | `null`  | A string (supports variables) to return as output if no match is found in `conditionalWorkflows`. This takes precedence over the `"Default"` workflow. If the node is a responder, this content will be streamed. |
| **`scoped_variables`**                   | Array of Strings | No       | `[]`    | **(Recommended)** A list of values to pass into whichever child workflow is chosen. Works identically to the `CustomWorkflow` node.                                                                               |
| **`routeOverrides`**                     | Object           | No       | `{}`    | A dictionary specifying prompt overrides for each potential route. The keys here should correspond to the keys in `conditionalWorkflows`.                                                                         |
| **`workflowUserFolderOverride`**         | String           | No       | `null`  | Specifies a user folder from which to load the selected workflow. Use `_common` for shared workflows.                                                                                                             |

-----

### Behavior and Logic Flow

The node executes with the following priority:

1. **Conditional Match**: The node resolves the value of `conditionalKey`. It then performs a **case-insensitive**
   search for that value as a key within the `conditionalWorkflows` map. For example, if `{agent1Output}` resolves to
   `"python"`, `"Python"`, or `"PYTHON"`, it will correctly match the `"Python"` key and select the corresponding
   workflow.

2. **Default Content Fallback**: If no direct match is found, the node checks if the
   `UseDefaultContentInsteadOfWorkflow` property is present and not null. If it is, the system will resolve any
   variables within that string and immediately return the result as the node's output. This action takes priority over
   the "Default" workflow and halts further execution within the node.

3. **Default Workflow Fallback**: If no direct match is found and `UseDefaultContentInsteadOfWorkflow` is not provided,
   the node will then look for and execute the workflow specified under the `"Default"` key in the
   `conditionalWorkflows` map.

4. **⚠️ Known Issue: Route Override Key Casing**: When looking for overrides in the `routeOverrides` map, the logic is
   different. The system will look for a key that matches the **Capitalized** version of the resolved `conditionalKey`
   value (e.g., `"python"` becomes `"Python"`). This means the keys in your `routeOverrides` object **must be
   capitalized** to be found.

    * ✅ **Correct**: `"Python"`, `"JavaScript"`
    * ❌ **Incorrect**: `"python"`, `"javascript"`

-----

### Full Syntax Example

This node first determines the programming language needed and then routes to a specialized workflow. If the language is
not supported, it returns a static message instead of running a general-purpose workflow.

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
  "UseDefaultContentInsteadOfWorkflow": "I'm sorry, I can only assist with Python and JavaScript at the moment.",
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
* **`conditionalWorkflows`**: If the value is (case-insensitively) `"Python"` or `"JavaScript"`, it will run the
  corresponding workflow.
* **`UseDefaultContentInsteadOfWorkflow`**: If `{agent1Output}` resolves to anything else (e.g., "Java"), the node will
  **not** run the `"Default"` workflow. Instead, it will immediately return the static message as the final response.
* **`scoped_variables`**: If a workflow is chosen, the user's last message will be passed to it and be available as
  `{agent1Input}`.
* **`routeOverrides`**: If the `"Python"` or `"JavaScript"` route is chosen, the system prompt of the first node in that
  child workflow will be overridden with the specified text. Note that the keys are correctly capitalized.