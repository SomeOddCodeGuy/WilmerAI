## The `SaveCustomFile` Node

### Overview

The **`SaveCustomFile`** node is a utility node that writes string content to a local text file. This allows you to save
data generated during a workflow (such as an LLM's detailed analysis, a summary of a conversation, or a structured
report) directly to the file system.

The node resolves any workflow variables (e.g., `{agent1Output}`) in the provided content before saving. It returns a
status message indicating the result of the operation, which can be used by subsequent nodes.

### Configuration

Here is the complete JSON structure for a `SaveCustomFile` node.

```json
{
  "title": "A descriptive name for this node (Optional)",
  "type": "SaveCustomFile",
  "filepath": "D:\\Path\\To\\Your\\File.txt",
  "content": "The content to save. This can include variables like {agent1Output} or {chat_user_prompt_last_one}."
}
```

-----

### Fields

Each field is explained in detail below.

* #### **`title`**

    * **Type**: `String`
    * **Required**: No
    * **Description**: An optional, human-readable name for the node. It's used for logging and makes the workflow
      easier to understand.

* #### **`type`**

    * **Type**: `String`
    * **Required**: Yes
    * **Description**: This **must** be the exact string `"SaveCustomFile"` to identify the node's function.

* #### **`filepath`**

    * **Type**: `String`
    * **Required**: Yes
    * **Description**: The full, absolute or relative path where the file will be saved. If the parent directories do
      not exist, the node will attempt to create them. This field supports variable substitution, allowing you to use
      placeholders like `{Discussion_Id}` and `{YYYY_MM_DD}` to create dynamic, per-conversation or date-based file
      paths.
    * **Example with variables**: `"/Users/socg/sessions/{Discussion_Id}_output.txt"` or
      `"/data/logs/{YYYY_MM_DD}_report.txt"`

* #### **`content`**

    * **Type**: `String`
    * **Required**: Yes
    * **Description**: The string content to be written to the file. This field is processed by the
      `$WorkflowVariableManager$`, so you can embed variables from previous nodes (e.g., `{agent1Output}`,
      `{agent2Input}`) or the conversation history (e.g., `{chat_user_prompt_last_one}`).

* #### **`mode`**

    * **Type**: `String`
    * **Required**: No
    * **Description**: One of `"overwrite"` (default), `"append"`, `"replace"`, `"remove"`, or `"trim"`.
        * `"overwrite"` replaces the file's contents.
        * `"append"` adds `content` to the end of the existing file (creating it if missing). Append is the clean way to
          build up an append-only log without first reading the file back into the workflow, and the write stays atomic.
        * `"replace"` swaps every occurrence of the `find` text for `content` in an existing file, leaving all other
          text untouched. This is the surgical alternative to a full rewrite: you can update a single entry without
          regenerating (and risking the loss of) the rest of the document. Use it to supersede a stale entry: for
          example, replacing "Tom is going to the dentist next week" with "Tom went to the dentist".
        * `"remove"` deletes every line that contains the `find` text from an existing file. Use it to retire an entry
          entirely. The match is substring-per-line, not exact-line: a short or common `find` value (a bare name that
          also appears inside other entries, for example) removes every line it appears in, in one atomic write. When
          `find` comes from a model output, instruct the model to return the full, distinctive entry text, and branch
          on the node's reported change count if over-deletion would be costly.
        * `"trim"` deletes every blank or whitespace-only line from an existing file, leaving the real content lines in
          place. It needs neither `content` nor `find`. Use it to tidy a line-per-entry log that a model has salted with
          stray blank lines (for example, after appending model output that occasionally included empty lines).
    * **Default Behavior**: `"overwrite"`.
    * **Note on `replace`/`remove`/`trim`**: These act on an existing file only. If the file does not exist, or nothing
      matched (`find` text absent, or no blank lines to trim), the node makes no change and reports zero edits (it does
      not create the file). Because the write only happens when something actually matched, a workflow can safely
      attempt an edit every turn and branch on whether it landed. `replace` matches `find` as a literal substring (all
      occurrences); provide a distinctive `find` value so it cannot match text you did not intend.

* #### **`find`**

    * **Type**: `String`
    * **Required**: Only when `mode` is `"replace"` or `"remove"`.
    * **Description**: The existing text to locate. For `"replace"`, every occurrence of this text is swapped for
      `content`. For `"remove"`, every line containing this text is deleted. Supports variable substitution, so the
      text to find can come from a previous node (e.g. `"find": "{agent2Output}"`).

-----

### Example

Let's say a previous "Standard" node (the first node in the workflow) generated a code review summary and stored it in
`{agent1Output}`. This `SaveCustomFile` node will then save that summary to a file.

#### Workflow Nodes:

```json
[
  {
    "type": "Standard",
    "prompt": "Review the following code changes and produce a summary covering readability, potential bugs, and adherence to project coding standards."
  },
  {
    "title": "Save Code Review Summary to File",
    "type": "SaveCustomFile",
    "filepath": "D:\\WilmerAI\\Reports\\code_review_summary.txt",
    "content": "CODE REVIEW SUMMARY\n-----------------\nReviewer: Automated\nFindings: {agent1Output}"
  }
]
```

#### Resulting Action:

A file named `code_review_summary.txt` is created at the specified path. The `{agent1Output}` placeholder is replaced
with the text generated by the first node, and the combined string is written to the file.

#### Resulting Output:

If this `SaveCustomFile` node is the second node in the workflow, the following string will be available in the
`{agent2Output}` variable for the next node:

```text
File successfully saved to D:\WilmerAI\Reports\code_review_summary.txt
```

-----

### Dynamic Filepath Example

The `filepath` field supports workflow variable substitution, allowing you to create dynamic, per-conversation or
date-based file paths. This is useful for saving session-specific outputs, daily reports, or user-specific data.

#### Available Variables for Filepaths

* **`{Discussion_Id}`**: The unique identifier for the current conversation. Useful for per-session files.
* **`{YYYY_MM_DD}`**: Today's date in underscore-separated format (e.g., `2025_12_07`). Useful for daily logs.
* Any other workflow variable (e.g., `{agent1Output}`, custom variables defined in the workflow JSON).

#### Example: Saving Per-Conversation Output

```json
{
  "title": "Save Session Summary",
  "type": "SaveCustomFile",
  "filepath": "/data/sessions/{Discussion_Id}_summary.txt",
  "content": "Session Summary:\n{agent1Output}"
}
```

If the `Discussion_Id` is `conv-abc-123`, this will save to `/data/sessions/conv-abc-123_summary.txt`.

#### Example: Saving Daily Reports

```json
{
  "title": "Save Daily Report",
  "type": "SaveCustomFile",
  "filepath": "/data/reports/{YYYY_MM_DD}_report.txt",
  "content": "Daily Report for {todays_date_pretty}\n\n{agent1Output}"
}
```

If today is December 7, 2025, this will save to `/data/reports/2025_12_07_report.txt`.

#### Example: Surgically Replacing an Entry

An LLM node in a previous step has decided that a stored fact is now out of date and produced the old text
(`{agent1Output}`) and its replacement (`{agent2Output}`). This node swaps just that entry, leaving the rest of the
file intact.

```json
{
  "title": "Supersede a stale entry",
  "type": "SaveCustomFile",
  "mode": "replace",
  "filepath": "/data/notes/{Discussion_Id}_tracked_lists.md",
  "find": "{agent1Output}",
  "content": "{agent2Output}"
}
```

If `{agent1Output}` is not found in the file, nothing is written and the node returns
`"File unchanged: no occurrence of the target text found in ..."`.

#### Example: Removing an Entry

```json
{
  "title": "Retire a resolved item",
  "type": "SaveCustomFile",
  "mode": "remove",
  "filepath": "/data/notes/{Discussion_Id}_tracked_lists.md",
  "find": "{agent1Output}"
}
```

Every line containing the resolved `{agent1Output}` text is deleted. Note that `content` is not required for
`"remove"`.

#### Example: Combining Multiple Variables

```json
{
  "title": "Save Session-Specific Daily Log",
  "type": "SaveCustomFile",
  "filepath": "/data/{YYYY_MM_DD}/{Discussion_Id}_output.txt",
  "content": "Generated at {current_time_12h}:\n\n{agent1Output}"
}
```

-----

### Behavior and Edge Cases

It's crucial to understand how the node behaves in specific situations:

* **Output Variable**: The node returns a status message as a single string (e.g., `"File successfully saved to ..."`).
  This output is assigned to a variable based on the node's position (e.g., `{agent1Output}`, `{agent2Output}`).
* **Caution on `filepath` sources**: The path is used as given (no directory containment is applied), which is by
  design: workflows are operator-authored, the same trust boundary as code. For that reason, never interpolate a
  model- or user-derived variable (such as an `{agentNOutput}`) into `filepath`: a manipulated value could write to,
  or edit lines out of, any file the process can access. Keep `filepath` built from literals and operator-controlled
  variables like `{Discussion_Id}` or dates.
* **Variable Substitution**: Both the `filepath` and `content` fields are processed through the workflow variable
  manager before the file is saved. This means you can use any available workflow variable in both fields.
* **File System Errors**: If the file cannot be written due to permissions issues or other I/O errors, the node will
  return an error message string, for example:
  `"Error saving file: [Errno 13] Permission denied: 'D:\Windows\system.log'"`.
* **Missing `filepath`**: If the `filepath` field is missing from the configuration, the node will return the string:
  `"No filepath specified"`.
* **Missing `content`**: If the `content` field is missing from the configuration, the node will return the string:
  `"No content specified"`, except for `"remove"` and `"trim"`, which do not use `content`. Note that an empty string
  (`"content": ""`) is valid and will result in an empty file being created.
* **Append Mode**: With `"mode": "append"`, `content` is added to the end of the existing file rather than replacing it;
  a missing file is created.
* **Replace / Remove Modes**: With `"mode": "replace"` or `"mode": "remove"`, a `find` value is required; omitting it
  returns `"SaveCustomFile: mode '<mode>' requires a 'find' value"`. These modes edit an existing file in place and
  never create one; when the file is missing or `find` is not present, no write occurs and the node returns a
  `"File unchanged: ..."` message. On success it returns how many changes were made, e.g.
  `"File successfully updated: replaced 2 occurrence(s) in ..."` or `"File successfully updated: removed 1 line(s) from ..."`.
* **Trim Mode**: With `"mode": "trim"`, no `find` or `content` is needed; the node deletes blank/whitespace-only lines
  from an existing file. It never creates a file; on a missing file or one with no blank lines it returns a
  `"File unchanged: no blank lines to remove in ..."` message, and on success `"File successfully tidied: removed N blank
  line(s) from ..."`.
* **Invalid Mode**: Any value other than `"overwrite"`, `"append"`, `"replace"`, `"remove"`, or `"trim"` returns
  `"SaveCustomFile: 'mode' must be one of 'overwrite', 'append', 'replace', 'remove', or 'trim', got '<value>'"`.
* **Empty Discussion_Id**: If `{Discussion_Id}` is used but no discussion ID is present in the context, it will be
  replaced with an empty string, which may result in an invalid filepath.
* **Directory Creation**: If the parent directories in the filepath do not exist, the node will attempt to create them
  automatically.