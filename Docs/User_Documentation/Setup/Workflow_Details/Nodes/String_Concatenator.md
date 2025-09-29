### **Data Manipulation: The String Concatenator Node**

The **`StringConcatenator`** node is a flexible utility for combining multiple strings into a single text block. It
takes a list of strings, resolves any variables within them, and joins them together using a specified delimiter. This
is perfect for assembling complex prompts, formatting reports, or creating structured text from various data points
within the workflow. If designated as a responder, this node can also stream its output just like a `StaticResponse`
node.

-----

#### **How It Works**

1. **Configuration Loading:** The processor loads the `strings` list and the `delimiter` string from the node's
   configuration.
2. **Variable Substitution:** The system iterates through every item in the `strings` list and processes it with the
   `WorkflowVariableManager`, substituting all placeholders with their runtime values.
3. **Concatenation:** The resolved strings are joined into a single string, with the `delimiter` placed between each
   element.
4. **Output Handling:**
    * If `returnToUser` is `false`, the complete, concatenated string is captured internally as a variable (e.g.,
      `{agent3Output}`).
    * If `returnToUser` is `true` and the request is for a **streaming** response, the node yields the final string to
      the client word-by-word, simulating an LLM stream.
    * If `returnToUser` is `true` and the request is for a **non-streaming** response, the complete string is returned
      to the user in a single block.
    * Even if `returnToUser` is undefined or false, if this node is the final node in a workflow it will appropriately
      respond to the user in streaming or non-streaming.

> NOTE: Do not use `returnToUser` unless you have a specific need. Leave it false, or undefined. This is a breakout
> property and if used in an inappropriate location in the workflow can cause unexpected and undesirable results.

-----

#### **Properties**

| Property           | Type            | Required | Default | Description                                                                                                             |
|:-------------------|:----------------|:---------|:--------|:------------------------------------------------------------------------------------------------------------------------|
| **`type`**         | String          | Yes      | N/A     | Must be `"StringConcatenator"`.                                                                                         |
| **`title`**        | String          | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                        |
| **`strings`**      | List of Strings | Yes      | N/A     | A JSON array of strings to be joined. Each string in the array supports variable substitution.                          |
| **`delimiter`**    | String          | No       | `""`    | The character(s) to insert between each element of the `strings` list. A common value is `"\n"` for creating new lines. |
| **`returnToUser`** | Boolean         | No       | `false` | If `true`, this node's output is sent to the user, with support for streaming.                                          |

-----

#### **Variable Usage**

Each individual string item **within the `strings` list** supports all available workflow variables. This allows you to
mix static text with dynamic data from agent outputs, date variables, and more.

-----

#### **Full Syntax Example**

This example assembles a multi-line user profile by combining custom workflow variables (`{user_name}`) with the output
from a previous node (`{agent1Output}`) and a date variable. The `\n` delimiter ensures each item is on a new line.

```json
{
  "title": "Assemble User Profile Block",
  "type": "StringConcatenator",
  "strings": [
    "--- User Profile ---",
    "Name: {user_name}",
    "Key Trait: {agent1Output}",
    "Report Generated: {todays_date_pretty}"
  ],
  "delimiter": "\n",
  "returnToUser": false
}
```