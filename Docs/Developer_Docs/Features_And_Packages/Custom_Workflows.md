### **Developer Guide: Sub-Workflow Nodes (`CustomWorkflow` & `ConditionalCustomWorkflow`)**

This guide provides a technical overview of the sub-workflow execution nodes, which are critical for creating modular,
reusable, and conditional logic within the WilmerAI Logic Engine. These nodes, handled by the `$SubWorkflowHandler$`,
enable recursive invocation of the entire workflow system.

-----

## 1\. Core Concepts & Architecture

The `CustomWorkflow` and `ConditionalCustomWorkflow` nodes allow one workflow (the "parent") to execute another
workflow (the "child") as a single, atomic step. This is the primary mechanism for composition and code reuse in the
system. The final output of the child workflow is captured and injected back into the parent's state, making it
available to subsequent nodes.

### Architectural Integration

Sub-workflow execution is not a special case but rather a recursive application of the main architectural flow. The
process is orchestrated by the `$SubWorkflowHandler$`, which acts as a client to the top-level `$WorkflowManager$`.

1. **Initiation (Parent):** The parent's `$WorkflowProcessor$` iterates to a `CustomWorkflow` node. It assembles an
   `$ExecutionContext$` for this node and dispatches it to the registered `$SubWorkflowHandler$`.
2. **Preparation (Handler):** The `$SubWorkflowHandler$` uses the parent's `$ExecutionContext$` to:
    * Resolve any variables listed in `scoped_variables` to get their concrete values.
    * Resolve any variables in legacy prompt overrides.
    * Determine which child workflow to run (either statically from `workflowName` or dynamically via the logic in
      `ConditionalCustomWorkflow`).
3. **Recursive Call:** The handler calls the static method `$WorkflowManager$.run_custom_workflow`, passing the child
   workflow's name, the resolved `scoped_variables` as `scoped_inputs`, and any prompt overrides.
4. **Child Execution:** This call creates a **new instance** of `$WorkflowManager$` and `$WorkflowProcessor$` for the
   child workflow. This child execution environment is completely isolated from the parent, with one key exception: the
   `scoped_inputs` are processed into its initial `agent_inputs` state.
5. **Return Value:** The child workflow runs to completion. Its final output (either a string or a generator for
   streaming) is returned from the `$WorkflowManager$.run\_custom\_workflow` call.
6. **State Update (Parent):** The `$SubWorkflowHandler$` receives this return value and returns it to the parent's
   `$WorkflowProcessor$`. The parent processor then saves this value in its `agent_outputs` dictionary, making the
   child's result available to subsequent nodes (e.g., as `{agent3Output}`).

-----

## 2\. Component & Data Flow Deep Dive

Understanding the data flow between parent and child workflows is essential for debugging and proper implementation.

### Key Component: `$SubWorkflowHandler$`

- **File:** `Middleware/workflows/handlers/impl/sub_workflow_handler.py`
- **Responsibility:** A specialized handler registered to both the `"CustomWorkflow"` and `"ConditionalCustomWorkflow"`
  node types. It acts as a router and orchestrator for sub-workflow execution.
- **Core Logic:**
    1. The main `handle(context: ExecutionContext)` method inspects the node `type` and dispatches to either
       `handle_custom_workflow` or `handle_conditional_custom_workflow`.
    2. It uses helper methods to prepare the data payload for the child workflow, primarily `_prepare_scoped_inputs` and
       `_prepare_workflow_overrides`.
    3. It invokes the child workflow via a top-level call to `context.workflow_manager.run_custom_workflow`.

### Parent-to-Child Data Flow

A child workflow is isolated and cannot access the parent's `agent_outputs` (e.g., `{agent1Output}`). Data must be
passed explicitly.

#### **Mechanism 1: `scoped_variables` (Modern & Recommended)**

This is the most robust method for passing data, making it globally available within the child workflow as
`agent_inputs`.

1. **Resolution (in `$SubWorkflowHandler$`):**

    * The `_prepare_scoped_inputs` method retrieves the `scoped_variables` array from the node's configuration.
    * It iterates through this array. For each entry (e.g., `"{agent1Output}"`), it calls
      `self.workflow_variable_service.apply_variables()` using the **parent's `ExecutionContext`**.
    * This resolves all placeholders into a simple list of string values:
      `['result of parent agent 1', 'user's original message']`.

2. **Transmission:** This list of resolved strings is passed as the `scoped_inputs` parameter to \`$WorkflowManager$
   .run\_custom\_workflow.

3. **Reception (in child's `$WorkflowProcessor$`):**

    * The `WorkflowProcessor.__init__` method for the child workflow receives this list.
    * It immediately processes `scoped_inputs` into the `self.agent_inputs` dictionary, mapping the array index to a
      1-indexed key:
      ```python
      # In WorkflowProcessor.__init__
      self.agent_inputs = {}
      if scoped_inputs:
          for i, value in enumerate(scoped_inputs):
              self.agent_inputs[f"agent{i + 1}Input"] = value
      ```
    * This creates a dictionary like:
      `{'agent1Input': 'result of parent agent 1', 'agent2Input': 'user's original message'}`.

4. **Availability:** For every node executed within the child workflow, this `agent_inputs` dictionary is included in
   the `$ExecutionContext$`, making these values available for variable substitution in any prompt, argument, or
   configuration string.

#### **Mechanism 2: Prompt Overrides (Legacy)**

- The `_prepare_workflow_overrides` method in the handler resolves placeholders in `firstNodeSystemPromptOverride` and
  `firstNodePromptOverride` using the parent's context.
- These resolved strings are passed to the child's `$WorkflowManager$`, which then forces them onto the first node
  configuration that contains a prompt field.
- **Limitation:** This data is only directly available to the first node of the child workflow.

### Child-to-Parent Data Flow (Return Value)

The return mechanism is straightforward:

1. The child's `$WorkflowProcessor$.execute` method yields its final result.
2. The `$WorkflowManager$.run_workflow` method consumes this generator (if non-streaming) and returns the final string.
3. This string propagates back to the parent's `$SubWorkflowHandler$`, which received it as the result of its call to
   `run_custom_workflow`.
4. The handler returns this string to the parent's `$WorkflowProcessor$`.
5. The parent's `$WorkflowProcessor$` stores the result in its `agent_outputs` dictionary under the key corresponding to
   the current node's index (e.g., `agent_outputs['agent3Output'] = '...'`).

### Conditional Execution Logic (`ConditionalCustomWorkflow`)

The `handle_conditional_custom_workflow` method contains the branching logic. A close look at the implementation reveals
important details:

1. **Key Resolution:** The `conditionalKey` (e.g., `"{agent1Output}"`) is resolved to its string value.
2. **Key Normalization:** The resolved value is normalized for matching: `raw_key_value.strip().lower()`. This ensures
   that `"Python"`, `" python "`, and `"python"` are all treated as `"python"`.
3. **Workflow Selection:** The keys in the `conditionalWorkflows` dictionary are also iterated and converted to
   lowercase to perform a case-insensitive lookup. If no match is found, it falls back to the `"default"` key.
4. **Route Override Selection (Known Issue):** The logic for selecting a `systemPromptOverride` or `promptOverride` from
   the `routeOverrides` map is **different**.
   ```python
   # In sub_workflow_handler.py
   route_overrides = context.config.get("routeOverrides", {}).get(key_value.capitalize(), {})
   ```
   The normalized, lowercase `key_value` is explicitly capitalized (`"python"` becomes `"Python"`) before being used as
   the lookup key. This is why the keys in the `routeOverrides` object **must be capitalized** to be found. This is an
   implementation inconsistency between the workflow selection logic and the override selection logic.

-----

## 3\. Code Walkthrough & Implementation

The following snippets highlight the key implementation details within
`Middleware/workflows/handlers/impl/sub_workflow_handler.py`.

### Preparing Inputs for the Child Workflow

The `_prepare_scoped_inputs` method demonstrates how parent-context variables are resolved before being passed to the
child.

```python
# Middleware/workflows/handlers/impl/sub_workflow_handler.py

def _prepare_scoped_inputs(self, context: ExecutionContext) -> List[str]:
    # Get the list of variables to pass, e.g., ["{agent1Output}", "{lastUserMessage}"]
    scoped_variables = context.config.get("scoped_variables") or []

    resolved_inputs = []
    for var_string in scoped_variables:
        # Use the variable service with the PARENT'S context to resolve the placeholder
        resolved_value = self.workflow_variable_service.apply_variables(
            str(var_string), context
        )
        resolved_inputs.append(resolved_value)

    # Returns a flat list of resolved strings: ["some text result", "the user's question"]
    return resolved_inputs
```

### Conditional Workflow and Override Logic

The `handle_conditional_custom_workflow` method shows the precise logic for selection, including the casing
inconsistency.

```python
# Middleware/workflows/handlers/impl/sub_workflow_handler.py

def handle_conditional_custom_workflow(self, context: ExecutionContext):
    conditional_key = context.config.get("conditionalKey")  # e.g., "{agent1Output}"
    raw_key_value = self.workflow_variable_service.apply_variables(conditional_key, context)

    # 1. Normalize the resolved key to lowercase for workflow selection
    key_value = raw_key_value.strip().lower()  # e.g., "python"

    # 2. Perform a case-insensitive lookup for the workflow name
    workflow_map = {k.lower(): v for k, v in context.config.get("conditionalWorkflows", {}).items()}
    workflow_name = workflow_map.get(key_value, workflow_map.get("default", ...))

    # 3. **KNOWN ISSUE**: Use a CAPITALIZED key to look up overrides
    route_overrides = context.config.get("routeOverrides", {}).get(key_value.capitalize(), {})  # "python" -> "Python"
    system_prompt_override = route_overrides.get("systemPromptOverride")

    # ... prepare other arguments ...

    scoped_inputs = self._prepare_scoped_inputs(context)

    # ... resolve variables in overrides ...

    # 4. Initiate the recursive call to the WorkflowManager
    return self.workflow_manager.run_custom_workflow(
        workflow_name=workflow_name,
        # ... other args ...
        scoped_inputs=scoped_inputs,
        first_node_system_prompt_override=expanded_system_prompt
    )
```