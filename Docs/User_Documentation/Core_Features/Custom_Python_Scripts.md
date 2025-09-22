### **Feature: Custom Python Script Execution with the `PythonModule` Node**

This document outlines the functionality and implementation of the `PythonModule` node within the WilmerAI workflow
engine. This feature allows users to execute custom Python scripts as a step in a workflow, enabling the integration of
external tools, custom logic, and advanced data manipulation beyond the built-in node types.

-----

## Overview

The **`PythonModule`** node type provides a direct interface to the Python runtime environment from within a WilmerAI
workflow. It allows a workflow to execute a specified function within a Python script, pass data to it using workflow
variables, and receive a string output back. This output is then made available to all subsequent nodes, seamlessly
integrating the script's result into the workflow's data flow.

This capability is designed for users who need to:

* Perform complex data processing or calculations.
* Interact with external APIs or web services.
* Access local file systems or databases.
* Incorporate proprietary logic or specialized libraries into a workflow.

-----

## Part 1: Node Configuration in Workflow JSON

To use this feature, a node of type `PythonModule` must be defined within the workflow's JSON file. The configuration
requires specifying the script's location and any arguments to be passed to it.

### **JSON Fields**

* `"title"`: **(String, Required)** A user-defined name for the node. The string returned by the Python script will be
  stored in an output variable based on this title (e.g., a title of `"Data Processor"` makes its output available as
  `{Data ProcessorOutput}`).
* `"type"`: **(String, Required)** Must be set to `"PythonModule"`.
* `"module_path"`: **(String, Required)** The absolute file path to the target `.py` script on the machine where the
  WilmerAI server is running.
* `"args"`: **(Array, Optional)** A list of positional arguments that will be passed to the script's entry point
  function. The values in this array support WilmerAI variables, which are resolved before execution.
* `"kwargs"`: **(Object, Optional)** A key-value object of keyword arguments to be passed to the script's entry point
  function. The values in this object also support WilmerAI variables.

### **Example Configuration**

```json
{
  "nodes": [
    {
      "title": "Generate Initial Text",
      "type": "Standard",
      "prompt": "Summarize the concept of photosynthesis in one sentence.",
      "endpointName": "Generic-LLM-Endpoint",
      "returnToUser": false
    },
    {
      "title": "Process Text With Python",
      "type": "PythonModule",
      "module_path": "D:\\WilmerAI\\Scripts\\file_writer.py",
      "args": [
        "{agent1Output}"
      ],
      "kwargs": {
        "filename": "photosynthesis_summary.txt",
        "save_path": "D:\\temp\\"
      }
    }
  ]
}
```

-----

## Part 2: Python Script Requirements

For a Python script to be compatible with the `PythonModule` node, it must adhere to a specific structure.

### **The `Invoke` Function**

1. **Required Entry Point**: The Python script **must** contain a function with the exact name `Invoke`.
2. **Function Signature**: The function must be defined with the signature `def Invoke(*args, **kwargs):`. This allows
   it to accept the variable number of positional and keyword arguments passed from the JSON configuration.
3. **Return Value**: The function **must** return a single value. This value will be converted into a string and serve
   as the node's output. If no meaningful output is required, the function can return an empty string (`""`) or a
   success message.

### **Example Script**

This script corresponds to the example configuration above. It takes a string from `args` and a path and filename from
`kwargs`, then writes the content to a file.

```python
# D:\WilmerAI\Scripts\file_writer.py

import os
import logging

# It is recommended to configure logging for visibility
logger = logging.getLogger(__name__)


def Invoke(*args, **kwargs):
    """
    Receives content and file details from a WilmerAI workflow and writes to a file.
    
    *args is expected to be a tuple: 
      ('The summary of photosynthesis from the previous LLM node',)
      
    **kwargs is expected to be a dictionary:
      {'filename': 'photosynthesis_summary.txt', 'save_path': 'D:\\temp\\'}
    """
    try:
        # 1. Retrieve arguments
        content_to_write = args[0]
        file_name = kwargs.get("filename")
        save_path = kwargs.get("save_path")

        if not all([content_to_write, file_name, save_path]):
            return "Error: Missing required arguments (content, filename, or save_path)."

        # 2. Perform logic
        full_path = os.path.join(save_path, file_name)
        os.makedirs(save_path, exist_ok=True)  # Ensure the directory exists

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content_to_write)

        logger.info(f"Successfully wrote content to {full_path}")

        # 3. Return a string result
        return f"Successfully wrote content to {full_path}"

    except IndexError:
        return "Error: Expected at least one positional argument containing the content to write."
    except Exception as e:
        logger.error(f"An unexpected error occurred in the Python module: {e}")
        return f"Error: An unexpected error occurred: {str(e)}"
```

-----

## Part 3: Advanced Error Handling

For more robust error management, a script can raise a `DynamicModuleError`. This provides a controlled way to report
failures back to WilmerAI. The error message will be logged and returned as the node's output without halting the entire
workflow execution.

### **Example of Raising a Controlled Error**

```python
# Import the specific error class from WilmerAI's middleware
from Middleware.workflows.tools.dynamic_module_loader import DynamicModuleError


def Invoke(*args, **kwargs):
    api_key = kwargs.get("api_key")

    if not api_key:
        # This will be caught by the node handler and returned as the node's output
        raise DynamicModuleError(
            message="API key was not provided in kwargs.",
            module_name="MySecureTool"
        )

    # ... proceed with logic that uses the API key ...

    return "API operation was successful."
```