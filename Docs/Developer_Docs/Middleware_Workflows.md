# `Middleware/workflows/` – Developer Documentation

## 1\. Overview

Welcome to the heart of WilmerAI's logic engine. The `workflows` directory contains the entire system responsible for interpreting and executing the multi-step processes defined in workflow JSON files. This is where user prompts are transformed into a series of actions—from calling LLMs to running custom tools—to produce a final, coherent response.

The architecture is designed to be highly modular and extensible, revolving around a few key concepts. Understanding this structure is critical for debugging issues and, more importantly, for adding new capabilities to WilmerAI.

### Core Concepts

  - **Workflow:** A sequence of steps defined in a JSON file (e.g., in `Public/Configs/Workflows/`). It represents a complete plan for handling a specific type of request.
  - **Node:** A single object within a workflow's JSON array. Each node represents one step in the process and has a specific `type` (e.g., `Standard`, `PythonModule`, `CustomWorkflow`) which determines its behavior.
  - **Manager (`$WorkflowManager$`):** The high-level orchestrator. It acts as the entry point, responsible for setting up the necessary dependencies and initiating a workflow run.
  - **Processor (`$WorkflowProcessor$`):** The low-level execution engine. It takes the prepared context from the Manager and iterates through the workflow's nodes one by one.
  - **Handler (`$...NodeHandler$`):** A specialized class that knows how to execute a single type of node. For every `type` a node can have, there is a corresponding Handler class. **This is the primary extension point of the system.**

## 2\. Architectural Flow

When a workflow is triggered, the flow of control within this directory proceeds as follows:

1.  **Initiation:** An external service (typically `$WilmerApi$`) calls a static method on `$WorkflowManager$` (e.g., `run_custom_workflow()`), providing the name of the workflow and the initial conversation messages.
2.  **Setup & Preparation:** The `$WorkflowManager$` instance is created. It loads the specified workflow JSON file and prepares all dependencies, including instantiating all available **Node Handlers**.
3.  **Delegation to Processor:** The `$WorkflowManager$` then creates an instance of the `$WorkflowProcessor$`, injecting the loaded configuration, the prepared handlers, all necessary services (`$LlmHandlerService$`, `$WorkflowVariableManager$`), and the request-specific data (messages, IDs, etc.).
4.  **Execution Loop:** The `$WorkflowProcessor.execute()` method is called. It begins iterating through the list of nodes from the workflow configuration.
5.  **Handler Dispatch:** For each node, the `$WorkflowProcessor$` reads its `type` field and looks up the corresponding **Handler** class from the dictionary of handlers it received.
6.  **Node Execution:** The `$WorkflowProcessor$` calls the `handle()` method on the selected Handler, passing it the node's specific configuration and the current state of the conversation.
7.  **Specialized Logic:** The `handle()` method within the specific Handler class executes its unique logic. For instance:
      - `$StandardNodeHandler$` calls the `$LLMDispatchService$` to get an LLM response.
      - `$ToolNodeHandler$` runs a Python script or calls an external API.
      - `$SubWorkflowHandler$` makes a recursive call back to the `$WorkflowManager$` to start a nested workflow.
8.  **State Update:** The output from the handler is stored in an `agent_outputs` dictionary within the `$WorkflowProcessor$`, making it available to subsequent nodes in the same workflow run via variable substitution (e.g., `{agent1Output}`).
9.  **Response Generation:** The loop continues until all nodes are processed or a node is designated as the final responder. The output of this final node is then yielded back up the call stack to the user.

## 3\. Directory & File Breakdown

### `managers/`

This directory contains high-level classes that orchestrate and manage workflows.

  - **`workflow_manager.py`**

      - **Responsibility:** To act as the primary entry point for all workflow executions. It is responsible for **setup and delegation**.
      - **Key Components:**
          - Static methods (`run_custom_workflow`, `handle_recent_memory_parser`, etc.): These are the public-facing methods used by the rest of the application to start a workflow.
          - `__init__()`: Initializes all services and, critically, creates the `self.node_handlers` dictionary, which maps node `type` strings to their corresponding Handler class instances. This is where new handlers are registered.
          - `run_workflow()`: The instance method that loads the JSON config and passes control to the `$WorkflowProcessor$`.

  - **`workflow_variable_manager.py`**

      - **Responsibility:** To perform dynamic variable substitution.
      - **Key Components:**
          - `apply_variables()`: A method that takes a string (like a prompt from a workflow node) and replaces placeholders like `{agent1Output}`, `{lastUserMessage}`, or `{discussionId}` with their actual runtime values.

### `processors/`

This directory houses the core execution engine.

  - **`workflows_processor.py`**
      - **Responsibility:** To execute a pre-configured workflow step-by-step. It is a stateful class that exists for the duration of a single workflow run.
      - **Key Components:**
          - `__init__()`: Accepts all context and dependencies from the `$WorkflowManager$`.
          - `execute()`: A generator method that contains the main loop for iterating through the workflow nodes, dispatching to the correct handler, and managing the `agent_outputs` state.
          - `_process_section()`: A helper method that prepares the `$LlmHandler$` for a given node before passing control to the node's handler.

### `handlers/`

This directory contains the handler classes for each node type, organized into `base` and `impl` sub-packages. This is where most of the feature-specific logic resides.

  - **`base/base_workflow_node_handler.py`**

      - **Responsibility:** Defines the contract for all handlers.
      - **Key Components:**
          - `$BaseWorkflowNodeHandler$`: An abstract base class requiring all subclasses to implement a `handle()` method. This ensures a consistent interface for the `$WorkflowProcessor$` to call.

  - **`impl/`**

      - This directory contains the concrete handler implementations for each node type.
      - **`standard_node_handler.py`**: For the `"Standard"` node type. Its primary purpose is to call an LLM.
      - **`tool_node_handler.py`**: For tool-use nodes (`"PythonModule"`, `"OfflineWikiApi..."`, etc.). It dispatches to the correct tool implementation.
      - **`memory_node_handler.py`**: For memory-related nodes (`"RecentMemory"`, `"FullChatSummary"`, etc.).
      - **`sub_workflow_handler.py`**: For nodes that trigger other workflows (`"CustomWorkflow"`, `"ConditionalCustomWorkflow"`).
      - **`specialized_node_handler.py`**: For miscellaneous nodes that don't fit other categories (`"WorkflowLock"`, `"GetCustomFile"`, `"ImageProcessor"`).

### `tools/`

This directory contains the underlying implementations of complex tools that are invoked by the `$ToolNodeHandler$`.

  - **`dynamic_module_loader.py`**: (Moved from `utilities`) A specialized utility responsible for the dynamic execution of custom Python scripts, which powers the `"PythonModule"` node type. It provides the `run_dynamic_module` function that safely loads external code by its path, finds a required `Invoke` function within the script, and executes it with the arguments specified in the workflow node. This isolates the complex and potentially risky process of running arbitrary code into a single, manageable component.
  - **`offline_wikipedia_api_tool.py`**: Logic for searching a local Wikipedia dump.
  - **`slow_but_quality_rag_tool.py`**: Implementation of the RAG (Retrieval-Augmented Generation) and keyword search functionalities.

## 4\. How to Extend the Workflow System

There are two primary ways to add new functionality: adding a new tool or adding a new node type.

### A. Adding a New Tool (Simple)

This is the easiest way to add custom functionality. It involves creating a Python script that can be called from an existing `"PythonModule"` node.

1.  **Create Your Tool:** Write a Python script with a function that performs your desired action. Place this file in `Middleware/workflows/tools/` or another appropriate location. Let's say you create `my_new_tool.py` with a function `run_my_tool(arg1, arg2)`. The `dynamic_module_loader` requires this function to be named `Invoke`.
2.  **Configure the Workflow:** In your workflow JSON file, add a node of type `"PythonModule"`:
    ```json
    {
        "type": "PythonModule",
        "module_path": "Middleware.workflows.tools.my_new_tool",
        "args": ["value_for_arg1", "{lastUserMessage}"],
        "kwargs": {}
    }
    ```
    The `$ToolNodeHandler$` will use the `$DynamicModuleLoader$` to handle importing and running this function with the specified arguments.

### B. Adding a New Node Type (Advanced)

This is the most powerful way to extend the system. It allows you to create entirely new, first-class behaviors.

Let's say you want to create a new node type called `"DatabaseQuery"`.

1.  **Define the Node:** Decide what parameters your node will need in the JSON configuration.

    ```json
    {
      "type": "DatabaseQuery",
      "connectionString": "your_db_connection_string",
      "query": "SELECT * FROM users WHERE name = '{lastUserMessage}';"
    }
    ```

2.  **Create the Handler:**

      - In the `Middleware/workflows/handlers/impl/` directory, create a new file named `database_query_handler.py`.
      - Inside this file, create a class that inherits from `$BaseWorkflowNodeHandler$`.

    <!-- end list -->

    ```python
    # /Middleware/workflows/handlers/impl/database_query_handler.py
    from ..base.base_workflow_node_handler import BaseWorkflowNodeHandler
    # ... other imports for your DB logic

    class DatabaseQueryHandler(BaseWorkflowNodeHandler):
        def handle(self, config, messages, request_id, workflow_id, discussion_id, agent_outputs, stream):
            # 1. Get parameters from the node config
            connection_string = config.get("connectionString")
            raw_query = config.get("query")

            # 2. Apply variables to the query string
            final_query = self.workflow_variable_service.apply_variables(
                raw_query, self.llm_handler, messages, agent_outputs
            )

            # 3. Execute your custom logic
            # ... (code to connect to the database and run final_query)
            query_result = ...

            # 4. Return the result
            return str(query_result)
    ```

3.  **Register the Handler:**

      - Open `Middleware/workflows/managers/workflow_manager.py`.
      - First, import your new handler class at the top of the file.
        ```python
        from Middleware.workflows.handlers.impl.database_query_handler import DatabaseQueryHandler
        ```
      - In the `__init__` method, add your new handler to the `self.node_handlers` dictionary. The key must match the `type` string from your JSON.
        ```python
        # In WorkflowManager.__init__
        self.node_handlers = {
            "Standard": StandardNodeHandler(**common_dependencies),
            "ConversationMemory": memory_node_handler,
            # ... all other handlers
            "DatabaseQuery": DatabaseQueryHandler(**common_dependencies) # Add your new handler here
        }
        ```

4.  **Update Constants:**

      - Open `Middleware/common/constants.py` and add `"DatabaseQuery"` to the `VALID_NODE_TYPES` list to prevent warnings.

5.  **Use It:** You can now use `"type": "DatabaseQuery"` in any workflow JSON file.