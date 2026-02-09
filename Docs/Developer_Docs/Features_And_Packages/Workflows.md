### **Developer Guide: WilmerAI Logic Engine (`Middleware/workflows/`)**

This guide provides a deep dive into the architecture and implementation of the WilmerAI logic engine. It has been
updated to reflect the current, refactored system, which is built around a central `ExecutionContext` object.
Understanding this structure is essential for debugging, extending, and utilizing the full capabilities of the workflow
system.

-----

## 1\. Core Concepts & Architecture

The system is designed to be modular and state-driven, transforming user requests into a series of coordinated actions
defined by a workflow.

### Core Components

- **Workflow:** A JSON file that defines a sequence of steps, or "nodes." It serves as a blueprint for handling a
  specific type of request. The system supports both a legacy list-based format and a modern dictionary-based format
  that can contain top-level configuration.
- **Node:** A single JSON object within a workflow's `nodes` array. Each node represents one operational step and has a
  `type` that dictates its function (e.g., `Standard`, `PythonModule`, `CustomWorkflow`).
- **`$WorkflowManager$`:** The high-level orchestrator and primary entry point. Its static methods (e.g.,
  `run_custom_workflow`) are called by external services to initiate a workflow. The manager is responsible for loading
  the workflow configuration, instantiating all necessary dependencies (including all node handlers), and delegating
  execution to the `$WorkflowProcessor$`.
- **`$WorkflowProcessor$`:** The low-level execution engine. It iterates through the nodes of a loaded workflow. For *
  *each node**, it assembles a new, comprehensive **`$ExecutionContext$`** object containing the complete runtime state.
  It then dispatches this context to the appropriate handler for execution.
- **`$ExecutionContext$`:** A central dataclass object that encapsulates all runtime data for a single node's execution.
  It holds the node's configuration, the entire conversation history, outputs from previous nodes (`agent_outputs`),
  inputs from a parent workflow (`agent_inputs`), the current LLM handler, and references to core services. This object
  is the sole argument passed to a node handler, simplifying the development of new nodes.
- **`$...NodeHandler$`:** A specialized class designed to execute a specific `type` of node. For every possible node
  `type` (e.g., `"Standard"`, `"PythonModule"`), there is a corresponding handler class. Each handler implements a
  `handle(context: ExecutionContext)` method, making it a primary extension point for new functionality.
- **`$WorkflowVariableManager$`:** A utility service responsible for dynamically substituting placeholders in strings (
  like prompts or tool arguments) with their real-time values from the workflow's state. Its methods take the
  `$ExecutionContext$` as an argument, giving it access to all necessary data for substitutions. It resolves two primary
  variable types:
    - **Agent Output (`{agent1Output}`):** The result from a previously completed node within the *same* workflow run.
    - **Agent Input (`{agent1Input}`):** A value passed from a *parent* workflow into a *child* sub-workflow. It is
      available to all nodes within the child workflow.
- **`$StreamingResponseHandler$`:** A dedicated class that processes a raw data stream from an LLM. It applies content
  modifications, such as removing `<think>` tags or custom prefixes defined in the workflow or endpoint configuration,
  and formats the output into a client-ready Server-Sent Event (SSE) stream.

### Architectural Flow

1. **Initiation:** An external service, like the API gateway, calls a static method on `$WorkflowManager$` (e.g.,
   `run_custom_workflow`), providing the workflow name and initial conversation history.
2. **Setup & Preparation:** The `$WorkflowManager$` is instantiated. It loads the specified workflow JSON file and
   creates a central registry (`self.node_handlers`) that maps node `type` strings to instances of their corresponding *
   *Node Handler** classes.
3. **Delegation to Processor:** The Manager creates an instance of `$WorkflowProcessor$`, injecting all dependencies,
   the full workflow configuration, the handler registry, and the request data.
4. **Execution Loop:** The `$WorkflowProcessor.execute()` method is called, which begins iterating through each node
   defined in the workflow's configuration. At the start of each iteration, the processor checks if a cancellation has
   been requested for this workflow execution and raises an `EarlyTerminationException` if so.
5. **Context Creation:** For each node in the loop, the `$WorkflowProcessor$` **assembles a new `ExecutionContext`
   object**. This object is populated with the node's specific configuration, the full conversation history, the
   top-level workflow configuration, all available agent inputs and outputs, the appropriate LLM handler for that node,
   and other runtime data.
6. **Handler Dispatch:** The `$WorkflowProcessor$` reads the node's `type` field and uses its injected registry to find
   the matching **Node Handler** instance.
7. **Node Execution:** The `$WorkflowProcessor$` calls the `handle()` method on the selected handler, passing it the
   single, comprehensive **`ExecutionContext` object**.
8. **State Update:** The output returned by the handler is captured by the `$WorkflowProcessor$` and stored in its
   internal `agent_outputs` dictionary. This makes the result available as an **Agent Output** (e.g., `{agent1Output}`,
   `{agent2Output}`) to all subsequent nodes in the current workflow.
9. **Response Generation:** The loop continues until a node marked as a "responder" is executed or the workflow ends.
   The `$WorkflowProcessor$` then manages the final output:
    - **Non-Streaming:** It returns the final string result directly after performing any required post-processing.
    - **Streaming:** It delegates the raw data *generator* from the handler to the **`$StreamingResponseHandler$`**,
      which processes the stream chunk-by-chunk and yields client-ready SSE events.

-----

## 2\. Directory & File Breakdown

This section details the responsibility of each key file in the `Middleware/workflows/` directory.

#### `managers/`

- **`workflow_manager.py` (`$WorkflowManager$`)**

    - **Responsibility:** The main entry point and setup coordinator.
    - **Details:** Contains static methods for initiating workflows. Its `__init__` method acts as the central registry
      where all **Node Handlers** are instantiated and mapped to their corresponding node `type` strings. It delegates
      the step-by-step execution to the `$WorkflowProcessor$`.

- **`workflow_variable_manager.py` (`$WorkflowVariableManager$`)**

    - **Responsibility:** Dynamic substitution of placeholders in strings.
    - **Details:** Provides the `apply_variables` method, which accepts an `ExecutionContext` object to resolve
      placeholders using the full runtime state of the workflow.

#### `processors/`

- **`workflows_processor.py` (`$WorkflowProcessor$`)**
    - **Responsibility:** To execute a pre-configured workflow step-by-step and manage the final response.
    - **Details:** Contains the main `execute()` loop. Its most critical function is to create a new, fully populated
      `ExecutionContext` for each node before dispatching it to the correct handler. It also maintains the
      `agent_outputs` dictionary to manage state between nodes.
    - **Node Execution Logging:** At the end of each workflow, logs an INFO-level summary of all executed nodes using
      `NodeExecutionInfo` objects. The summary includes node index, type, name (from `title` or `agentName`), endpoint
      details, and execution time. Helper methods include `_get_node_name()` (extracts display name, showing workflow
      destinations for sub-workflow nodes), `_get_endpoint_details()` (resolves endpoint name/URL with variable
      substitution), and `_log_node_execution_summary()` (formats and logs the summary).
    - **Variable Substitution:** The `maxResponseSizeInTokens` field supports workflow variable substitution (e.g.,
      `{agent#Input}`), allowing parent workflows to dynamically control response size limits for child workflows.

#### `handlers/`

- **`base/base_workflow_node_handler.py` (`$BaseHandler$`)**

    - **Responsibility:** Defines the abstract interface for all node handlers.
    - **Details:** An Abstract Base Class (ABC) ensuring all handlers implement a `handle(context: ExecutionContext)`
      method.

- **`impl/` (Implementations)**

    - `standard_node_handler.py`: Handles the `"Standard"` node type for LLM calls.
    - `tool_node_handler.py`: A router for tool-related nodes (`"PythonModule"`, `"OfflineWikiApi..."`, etc.).
    - `memory_node_handler.py`: A router for memory-related nodes (`"RecentMemory"`, `"VectorMemorySearch"`, etc.).
    - `sub_workflow_handler.py`: Handles nodes that trigger other workflows (`"CustomWorkflow"`). It calls back to the
      `$WorkflowManager$` to run a nested workflow, resolving and passing any `scoped_variables` from the parent
      context.
    - `specialized_node_handler.py`: A router for miscellaneous nodes like `"WorkflowLock"`, `"GetCustomFile"`,
      `"StaticResponse"`, `"JsonExtractor"`, and `"TagTextExtractor"`.

#### `streaming/`

- **`response_handler.py` (`$StreamingResponseHandler$`)**
    - **Responsibility:** Converts a raw LLM data stream into a final, client-facing SSE stream.
    - **Details:** Its `process_stream` method consumes a generator, strips `<think>` tags, removes configured
      prefixes (from both the node and endpoint configs), and formats the cleaned content into valid SSE messages.

#### `models/`

- **`execution_context.py`**
    - **`ExecutionContext`:** A `dataclass` that holds all runtime state for a single node's execution, including
      request IDs, node/workflow configs, messages, agent inputs/outputs, and service handlers.
    - **`NodeExecutionInfo`:** A `dataclass` for tracking node execution metrics used in logging. Contains fields for
      `node_index`, `node_type`, `node_name`, `endpoint_name`, `endpoint_url`, and `execution_time_seconds`. Includes
      a `format_time()` method that returns human-readable time strings and a `__str__()` method for formatted log output.

-----

## 3\. How to Extend the Workflow System

Adding new functionality typically involves one of the following methods.

### A. Add a New Node Type (Advanced)

This is the most powerful way to extend the system and has been streamlined by the `ExecutionContext` architecture.

1. **Define the Node Configuration:** Decide on the JSON parameters your node will need in the workflow file.

   ```json
   {
     "type": "DatabaseQuery",
     "connectionString": "your_db_connection_string",
     "query": "SELECT * FROM users WHERE name = '{lastUserMessage}';"
   }
   ```

2. **Create the Handler File:** Create a new file (e.g., `database_query_handler.py`) in
   `Middleware/workflows/handlers/impl/`. The class must inherit from `BaseHandler` and implement the `handle` method.

   ```python
   # Middleware/workflows/handlers/impl/database_query_handler.py
   from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
   from Middleware.workflows.models.execution_context import ExecutionContext

   class DatabaseQueryHandler(BaseHandler):
       def handle(self, context: ExecutionContext) -> str:
           # Access all required data directly from the context object
           query_template = context.config.get("query")
           
           # Use the variable service (also on the context) to resolve placeholders
           resolved_query = context.workflow_variable_service.apply_variables(
               query_template, context
           )
           
           connection_string = context.config.get("connectionString")
           
           # ... (database connection and query logic) ...
           
           result = f"Executed: {resolved_query}"
           return result
   ```

3. **Register the Handler:** In `Middleware/workflows/managers/workflow_manager.py`, import your new handler and add it
   to the `self.node_handlers` dictionary in the `__init__` method.

   ```python
   # In Middleware/workflows/managers/workflow_manager.py
   # 1. Import your new handler
   from Middleware.workflows.handlers.impl.database_query_handler import DatabaseQueryHandler

   class WorkflowManager:
       def __init__(self, workflow_config_name, **kwargs):
           # ... (existing setup) ...
           
           # 2. Add your handler to the registry
           self.node_handlers = {
               "Standard": StandardNodeHandler(**common_dependencies),
               # ... (existing handlers) ...
               "DatabaseQuery": DatabaseQueryHandler(**common_dependencies),
           }
   ```

4. **Update Constants:** Add your new node type string (`"DatabaseQuery"`) to the `VALID_NODE_TYPES` list in
   `Middleware/common/constants.py` to ensure it's recognized as a valid type and to prevent warnings.

5. **Use It:** Your new node type is now ready to be used in any workflow JSON file.