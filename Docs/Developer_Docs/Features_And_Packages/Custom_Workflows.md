### **Developer Guide: Sub-Workflow Nodes (`CustomWorkflow` & `ConditionalCustomWorkflow`)**

This guide provides a technical overview of the sub-workflow execution nodes, which are critical for creating modular, reusable, and conditional logic within the WilmerAI Logic Engine. These nodes, handled by the `$SubWorkflowHandler$`, enable recursive invocation of the entire workflow system.

-----

## 1\. Core Concepts & Architecture

The `CustomWorkflow` and `ConditionalCustomWorkflow` nodes allow one workflow (the "parent") to execute another workflow (the "child") as a single, atomic step. This is the primary mechanism for composition and code reuse in the system. The final output of the child workflow is captured and injected back into the parent's state, making it available to subsequent nodes.

### Architectural Integration

Sub-workflow execution is not a special case but rather a recursive application of the main architectural flow. The process is orchestrated by the `$SubWorkflowHandler$`, which acts as a client to the top-level `$WorkflowManager$`.

1.  **Initiation (Parent):** The parent's `$WorkflowProcessor$` iterates to a `CustomWorkflow` node. If this node is the designated "responder" for the entire request (e.g., it's the last node), the processor flags it for streaming. It assembles an `$ExecutionContext$` for this node and dispatches it to the registered `$SubWorkflowHandler$`.
2.  **Preparation (Handler):** The `$SubWorkflowHandler$` uses the parent's `$ExecutionContext$` to:
      * Check if the node was flagged as a responder (by checking `context.stream`).
      * Resolve any variables listed in `scoped_variables` to get their concrete values.
      * Determine which child workflow to run (either statically from `workflowName` or dynamically via the logic in `ConditionalCustomWorkflow`).
3.  **Recursive Call:** The handler calls the static method `$WorkflowManager$.run_custom_workflow`, passing the child workflow's name, the resolved `scoped_variables` as `scoped_inputs`, and importantly, the correct **streaming and responder flags** inherited from the parent context.
4.  **Child Execution:** This call creates a **new instance** of `$WorkflowManager$` and `$WorkflowProcessor$` for the child workflow. This child execution environment is completely isolated from the parent, with one key exception: the `scoped_inputs` are processed into its initial `agent_inputs` state.
5.  **Return Value:** The child workflow runs to completion. Its final output (either a string or a generator for streaming) is returned from the `$WorkflowManager$.run\_custom\_workflow` call.
6.  **State Update (Parent):** The `$SubWorkflowHandler$` receives this return value and returns it to the parent's `$WorkflowProcessor$`. The parent processor then saves this value in its `agent_outputs` dictionary, making the child's result available to subsequent nodes (e.g., as `{agent3Output}`).

-----

## 2\. Component & Data Flow Deep Dive

Understanding the data flow between parent and child workflows is essential for debugging and proper implementation.

### Key Component: `$SubWorkflowHandler$`

  * **File:** `Middleware/workflows/handlers/impl/sub_workflow_handler.py`
  * **Responsibility:** A specialized handler registered to both the `"CustomWorkflow"` and `"ConditionalCustomWorkflow"` node types. It acts as a router and orchestrator for sub-workflow execution.
  * **Core Logic:**
    1.  The main `handle(context: ExecutionContext)` method inspects the node `type` and dispatches to either `handle_custom_workflow` or `handle_conditional_custom_workflow`.
    2.  It uses a centralized helper method, `_prepare_workflow_overrides`, to correctly determine the streaming and responder status for the child workflow. **Crucially, it inherits this status from the parent's context (`context.stream`)** rather than a configuration flag.
    3.  It invokes the child workflow via a top-level call to `context.workflow_manager.run_custom_workflow`.

### Parent-to-Child Data Flow

A child workflow is isolated and cannot access the parent's `agent_outputs` (e.g., `{agent1Output}`). Data must be passed explicitly.

#### **Mechanism 1: `scoped_variables` (Modern & Recommended)**

This is the most robust method for passing data, making it globally available within the child workflow as `agent_inputs`.

1.  **Resolution (in `$SubWorkflowHandler$`):**
      * The `_prepare_scoped_inputs` method retrieves the `scoped_variables` array from the node's configuration.
      * It iterates through this array and uses the **parent's `ExecutionContext`** to resolve all placeholders into a simple list of string values: `['result of parent agent 1', 'user's original message']`.
2.  **Transmission:** This list of resolved strings is passed as the `scoped_inputs` parameter to \`$WorkflowManager$.run\_custom\_workflow.
3.  **Reception (in child's `$WorkflowProcessor$`):**
      * The child's `WorkflowProcessor` receives this list and processes it into the `self.agent_inputs` dictionary (e.g., `{'agent1Input': 'result of parent agent 1', 'agent2Input': '...'}`).
4.  **Availability:** This `agent_inputs` dictionary is included in the `$ExecutionContext$` for every node within the child workflow, making the values available for substitution anywhere.

#### **Mechanism 2: Prompt Overrides (Legacy)**

  * The `_prepare_workflow_overrides` method in the handler resolves placeholders in `firstNodeSystemPromptOverride` and `firstNodePromptOverride` using the parent's context.
  * These resolved strings are passed to the child's `$WorkflowManager$`, which then forces them onto the first node configuration that contains a prompt field.
  * **Limitation:** This data is only directly available to the first node of the child workflow.

### Child-to-Parent Data Flow (Return Value)

The return mechanism is straightforward: The child's final result (string or stream generator) is returned up the call stack to the parent's `$SubWorkflowHandler$`, which then returns it to the parent's `$WorkflowProcessor$` to be saved in `agent_outputs`.

### Conditional Execution Logic (`ConditionalCustomWorkflow`)

The `handle_conditional_custom_workflow` method contains the branching logic.

1.  **Key Resolution:** The `conditionalKey` (e.g., `"{agent1Output}"`) is resolved to its string value.
2.  **Key Normalization:** The resolved value is normalized for matching: `raw_key_value.strip().lower()`. This ensures that `"Python"`, `" python "`, and `"python"` are all treated as `"python"`.
3.  **Workflow Selection:** The keys in the `conditionalWorkflows` dictionary are also iterated and converted to lowercase to perform a case-insensitive lookup.
4.  **Route Override Selection (Known Issue):** The logic for selecting a `systemPromptOverride` or `promptOverride` from the `routeOverrides` map is **different**. The normalized, lowercase `key_value` is explicitly capitalized (`"python"` becomes `"Python"`) before being used as the lookup key. This is why the keys in the `routeOverrides` object **must be capitalized** to be found. This is an implementation inconsistency between the workflow selection logic and the override selection logic.

-----

## 3\. Code Walkthrough & Implementation

The following snippets highlight the key implementation details within `Middleware/workflows/handlers/impl/sub_workflow_handler.py`.

### Preparing Inputs and Inheriting Responder Status

The `_prepare_workflow_overrides` method centralizes all preparation logic and uses `context.stream` to determine if the child workflow should stream.

```python
# Middleware/workflows/handlers/impl/sub_workflow_handler.py

def _prepare_workflow_overrides(self, context: ExecutionContext, overrides_config: Optional[Dict] = None):
    """
    Prepares prompt overrides and streaming settings for a sub-workflow.

    This method correctly determines the responder and streaming flags based on the parent
    processor's decision (communicated via `context.stream`).
    """
    source_config = overrides_config if overrides_config is not None else context.config

    if context.stream:
        # This node IS the responder. Child workflow can stream and must produce a response.
        non_responder = None
        allow_streaming = True
    else:
        # This is a non-responder node. Child workflow CANNOT stream or respond.
        non_responder = True
        allow_streaming = False

    # ... (centralized logic for resolving prompt overrides) ...

    return system_prompt, prompt, non_responder, allow_streaming
```

### Conditional Workflow and Override Logic

The `handle_conditional_custom_workflow` method delegates its preparation logic to the centralized helper.

```python
# Middleware/workflows/handlers/impl/sub_workflow_handler.py

def handle_conditional_custom_workflow(self, context: ExecutionContext):
    # ... (logic to resolve conditionalKey and select workflow_name) ...

    # Find the specific override configuration for the chosen route
    route_overrides = context.config.get("routeOverrides", {}).get(key_value.capitalize(), {})

    # Use the centralized helper, passing the specific overrides for this route
    system_prompt, prompt, non_responder, allow_streaming = self._prepare_workflow_overrides(
        context,
        overrides_config=route_overrides
    )

    scoped_inputs = self._prepare_scoped_inputs(context)

    # Initiate the recursive call to the WorkflowManager with the correct flags
    return self.workflow_manager.run_custom_workflow(
        workflow_name=workflow_name,
        # ... other args ...
        non_responder=non_responder,
        is_streaming=allow_streaming,
        scoped_inputs=scoped_inputs,
        first_node_system_prompt_override=system_prompt,
        first_node_prompt_override=prompt
    )
```