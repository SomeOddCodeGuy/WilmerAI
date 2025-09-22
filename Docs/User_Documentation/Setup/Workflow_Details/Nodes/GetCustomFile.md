## The `GetCustomFile` Node

### Overview

The **`GetCustomFile`** node is a utility node that loads the content of a local text file directly into a workflow.
This allows you to inject large blocks of static text—like character bios, instructions, or world-building lore—without
cluttering the workflow JSON itself.

The content of the file is returned as a string, which can then be used by subsequent nodes through the workflow's
variable system (e.g., `{agent1Output}`).

### Configuration

Here is the complete JSON structure for a `GetCustomFile` node.

```json
{
  "title": "A descriptive name for this node (Optional)",
  "type": "GetCustomFile",
  "filepath": "C:\\Path\\To\\Your\\File.txt",
  "delimiter": "\\n---\\n",
  "customReturnDelimiter": "\\n***\\n"
}
```

-----

### Fields

Each field is explained in detail below.

* #### **`title`**

    * **Type**: `String`
    * **Required**: No
    * **Description**: An optional, human-readable name for the node. It's used for logging and makes the workflow
      easier to understand. It doesn't affect the node's execution.

* #### **`type`**

    * **Type**: `String`
    * **Required**: Yes
    * **Description**: This **must** be the exact string `"GetCustomFile"` to identify the node's function.

* #### **`filepath`**

    * **Type**: `String`
    * **Required**: Yes
    * **Description**: The full, absolute or relative path to the text file you want to load. The file path resolution
      is **case-insensitive**, meaning `C:\Docs\file.txt` will match `C:\docs\File.TXT`.
    * **Example**: `"D:\\WilmerAI\\Public\\lore\\world_history.txt"`

* #### **`delimiter`**

    * **Type**: `String`
    * **Required**: No
    * **Description**: An optional string of characters that the node will search for within the file's content. This is
      the text you want to **find and replace**. If you want to use special characters like newlines, be sure to escape
      them properly in the JSON (e.g., `\\n`).
    * **Default Behavior**: If omitted, it defaults to the value of `customReturnDelimiter`. If both are omitted, it
      defaults to a single newline (`\n`).

* #### **`customReturnDelimiter`**

    * **Type**: `String`
    * **Required**: No
    * **Description**: An optional string of characters that will **replace** every instance of the `delimiter` found in
      the file.
    * **Default Behavior**: If omitted, it defaults to the value provided in `delimiter`. This effectively makes the
      replacement a no-op, preserving the original delimiters.

-----

### Example

Let's illustrate how the delimiters work together.

#### Input File (`C:\Users\User\Desktop\character_sheet.txt`):

```text
Name: Captain Eva "Vortex" Rostova
---
Background: A former corporate pilot for OmniCorp, framed for a crime she didn't commit. Now she flies a freighter on the outer rim, taking any job that pays.
---
Goal: Clear her name and expose the conspiracy.
```

#### Workflow Node:

This node will find each `---` separator and replace it with a more decorative one.

```json
{
  "title": "Load Character Sheet",
  "type": "GetCustomFile",
  "filepath": "C:\\Users\\User\\Desktop\\character_sheet.txt",
  "delimiter": "---",
  "customReturnDelimiter": "\n**********\n"
}
```

#### Resulting Output:

If this is the first node in a workflow, the following string will be available in the `{agent1Output}` variable for the
next node:

```text
Name: Captain Eva "Vortex" Rostova

**********

Background: A former corporate pilot for OmniCorp, framed for a crime she didn't commit. Now she flies a freighter on the outer rim, taking any job that pays.

**********

Goal: Clear her name and expose the conspiracy.
```

-----

### Behavior and Edge Cases

It's crucial to understand how the node behaves in specific situations:

* **Output Variable**: The entire text content of the file (after delimiter replacement) is returned as a single string.
  This output is then assigned to a variable based on the node's position in the workflow (e.g., `{agent1Output}`,
  `{agent2Output}`, etc.).
* **File Not Found**: If the path in `filepath` does not lead to an existing file, the node will return the string:
  `"Custom instruction file did not exist"`.
* **Empty File**: If the file is found but is completely empty, the node will return the string:
  `"No additional information added"`.
* **Missing `filepath`**: If the `filepath` field is missing from the configuration, the node will return the string:
  `"No filepath specified"`.