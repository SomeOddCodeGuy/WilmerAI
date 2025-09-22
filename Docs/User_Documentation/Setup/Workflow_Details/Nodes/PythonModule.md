## The `PythonModule` Node

The `PythonModule` node is a powerful and flexible feature that allows you to extend WilmerAI's capabilities by
executing custom Python scripts directly within your workflows. This enables you to perform complex data manipulation,
interact with external APIs, access local files, or integrate any custom logic you need.

-----

### **JSON Configuration**

To use this node, you must configure it in your workflow's JSON file. Below is a detailed breakdown of each field.

#### **Complete Example**

```json
{
  "title": "My Custom Python Tool",
  "type": "PythonModule",
  "module_path": "C:/WilmerAI/Public/Scripts/process_data.py",
  "args": [
    "A static string argument",
    "{llm_responder_output}",
    "{currentDate}"
  ],
  "kwargs": {
    "api_key": "your-secret-key",
    "user_id": "{userName}"
  }
}
```

#### **Field Breakdown**

* `"title"`: **(String, Required)**

    * **Purpose**: A unique name for this node instance. The output of this node (the string returned by your Python
      script) will be stored in a workflow variable named after this title.
    * **Example**: If the `title` is `"My Custom Python Tool"`, its output can be accessed in subsequent nodes using the
      variable `{My Custom Python ToolOutput}`.

* `"type"`: **(String, Required)**

    * **Purpose**: Specifies the node handler to use.
    * **Value**: Must always be set to `"PythonModule"`.

* `"module_path"`: **(String, Required)**

    * **Purpose**: The full, absolute file path to the Python (`.py`) script you want to execute.
    * **Value**: A valid path on the machine where the WilmerAI server is running, for example,
      `"D:/WilmerAI/MyScripts/MyTestModule.py"`.

* `"args"`: **(Array, Optional)**

    * **Purpose**: A list of positional arguments to pass to your Python script's `Invoke` function. The order is
      preserved.
    * **Value**: An array of strings, numbers, or other JSON values. **Crucially, any string value can contain WilmerAI
      variables** (e.g., `{agent1Output}`), which will be resolved *before* being passed to your script.

* `"kwargs"`: **(Object, Optional)**

    * **Purpose**: A dictionary of keyword arguments to pass to your Python script's `Invoke` function.
    * **Value**: A JSON object where keys are the argument names and values are the argument content. Like `args`, the
      values here **also support WilmerAI variables**.

-----

### **Python Script Requirements**

Your Python script must adhere to a specific structure to be compatible with the `PythonModule` node.

#### **The `Invoke` Function**

1. **Required Function**: Your `.py` file **must** contain a function named exactly `Invoke`.
2. **Function Signature**: The function signature must be `def Invoke(*args, **kwargs):`. This allows it to accept the
   arguments passed from the JSON configuration.
3. **Return Value**: The function **must return a single value**. This value will be converted to a string and become
   the output of the node, which is then stored in the corresponding `{titleOutput}` variable for other nodes to use.

#### **Example Script**

Let's assume this script is located at `C:/WilmerAI/Public/Scripts/process_data.py`, matching the `module_path` in our
JSON example.

```python
# C:/WilmerAI/Public/Scripts/process_data.py
import logging

# It's good practice to set up a logger
logger = logging.getLogger(__name__)


def Invoke(*args, **kwargs):
    """
    This function processes data passed from a WilmerAI workflow.
    
    *args will be a tuple: 
      ('A static string argument', 'LLM response text', '2025-09-01')
    
    **kwargs will be a dictionary:
      {'api_key': 'your-secret-key', 'user_id': 'SomeUserName'}
    """
    try:
        # --- 1. Accessing Arguments ---
        static_arg = args[0]
        llm_output = args[1]
        date = args[2]

        user = kwargs.get("user_id", "default_user")
        api_key = kwargs.get("api_key")  # Be careful with secrets!

        # --- 2. Perform Custom Logic ---
        # For example, let's count the words in the LLM's output.
        word_count = len(llm_output.split())

        # You can perform any action here: call another API, read a file, etc.
        logger.info(f"Processing data for user '{user}' on {date}.")

        # --- 3. Return a String Result ---
        # This string will be the node's output.
        return f"Successfully processed the text. It contains {word_count} words."

    except IndexError:
        # Handle cases where expected args are missing
        return "Error: Not enough arguments provided to the script."
    except Exception as e:
        logger.error(f"An unexpected error occurred in the Python module: {e}")
        return f"Error: An unexpected error occurred: {str(e)}"

```

-----

### **Advanced: Error Handling**

For more controlled error reporting, you can raise a `DynamicModuleError` from your script. This allows you to pass a
clean error message back to WilmerAI, which will be logged and returned as the node's output without crashing the entire
workflow.

```python
# C:/WilmerAI/Public/Scripts/robust_tool.py
import os

# The dynamic loader adds the project root to sys.path, so this import works.
from Middleware.workflows.tools.dynamic_module_loader import DynamicModuleError


def Invoke(*args, **kwargs):
    api_key = kwargs.get("api_key")

    if not api_key:
        # This raises a specific, controlled error.
        raise DynamicModuleError(
            message="API key was not provided.",
            module_name="RobustTool",
            details={"reason": "Missing 'api_key' in kwargs"}
        )

    # ... logic that uses the API key ...

    return "API call was successful."
```