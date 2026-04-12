### **Data Manipulation: The `DelimitedChunker` Node**

The **`DelimitedChunker`** node splits a string on a delimiter and returns either the first N or last N chunks, rejoined
with the same delimiter. It functions like `head` and `tail` for delimited content. This is useful for trimming long
delimited data — for example, keeping only the most recent entries from a newline-separated log, or taking the first
few sections of a `---`-separated document.

-----

#### **How It Works**

1. **Configuration Loading:** The processor loads the `content`, `delimiter`, `mode`, and `count` fields from the node's
   configuration.
2. **Variable Substitution:** The `content` and `delimiter` fields are processed with the `WorkflowVariableManager`,
   substituting all placeholders with their runtime values.
3. **Splitting:** The resolved content is split on the resolved delimiter into chunks.
4. **Selection:** Based on the `mode`, the node takes either the first `count` chunks (`"head"`) or the last `count`
   chunks (`"tail"`). If `count` is greater than or equal to the total number of chunks, the full content is returned
   unchanged.
5. **Rejoining:** The selected chunks are joined back together using the resolved delimiter, and the result is returned
   as the node's output.

-----

#### **Properties**

| Property        | Type    | Required | Default | Description                                                                                                                    |
|:----------------|:--------|:---------|:--------|:-------------------------------------------------------------------------------------------------------------------------------|
| **`type`**      | String  | Yes      | N/A     | Must be `"DelimitedChunker"`.                                                                                                  |
| **`title`**     | String  | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                               |
| **`content`**   | String  | Yes      | N/A     | The string to split. Supports variable substitution (e.g., `{agent1Output}`).                                                  |
| **`delimiter`** | String  | Yes      | N/A     | The string to split on. Supports variable substitution. Can be any string, including multi-character delimiters like `"---"`.   |
| **`mode`**      | String  | Yes      | N/A     | Either `"head"` (keep the first N chunks) or `"tail"` (keep the last N chunks). Any other value produces an error.             |
| **`count`**     | Integer | Yes      | N/A     | The number of chunks to keep. Must be a positive integer (>= 1).                                                               |

-----

#### **Variable Usage**

Both `content` and `delimiter` support all available workflow variables. This allows you to:
- Reference text output from a previous node (e.g., `{agent1Output}`)
- Pass text from a parent workflow (e.g., `{agent1Input}`)
- Use a dynamically determined delimiter from another node's output

The `mode` and `count` fields are **not** subject to variable substitution. They must be literal values in the workflow
configuration.

-----

#### **Full Syntax Example**

This example takes the output of a previous node (a newline-separated list), and keeps only the last 5 lines.

```json
{
  "title": "Keep Last 5 Lines",
  "type": "DelimitedChunker",
  "content": "{agent1Output}",
  "delimiter": "\n",
  "mode": "tail",
  "count": 5
}
```

-----

#### **Example: Trimming a Separator-Delimited Document**

If `agent1Output` contains a document with sections separated by `---`:

```
Section A content
---
Section B content
---
Section C content
---
Section D content
```

This configuration keeps only the first two sections:

```json
{
  "title": "Keep First Two Sections",
  "type": "DelimitedChunker",
  "content": "{agent1Output}",
  "delimiter": "---",
  "mode": "head",
  "count": 2
}
```

**Output:**
```
Section A content
---
Section B content
```

-----

#### **Example: Getting the Last Entry from a CSV Row**

If `agent1Output` contains a comma-separated row like `"alpha,beta,gamma,delta"`:

```json
{
  "title": "Get Last CSV Value",
  "type": "DelimitedChunker",
  "content": "{agent1Output}",
  "delimiter": ",",
  "mode": "tail",
  "count": 1
}
```

**Output:** `delta`

-----

#### **Behavior and Edge Cases**

* **Empty Content:** If the resolved content is an empty string, the node returns an empty string without error.
* **Delimiter Not Found:** If the delimiter does not appear in the content, there is exactly one chunk. For any
  `count >= 1`, the full content is returned unchanged.
* **Count Equals or Exceeds Chunks:** If `count` is greater than or equal to the total number of chunks, the full
  original content is returned unchanged — no error is raised.
* **Missing Required Fields:** If `content`, `delimiter`, `mode`, or `count` is missing from the configuration,
  the node returns a descriptive error message string (e.g., `"No delimiter specified"`).
* **Invalid Mode:** If `mode` is anything other than `"head"` or `"tail"`, the node returns an error message naming
  the invalid value.
* **Invalid Count:** If `count` is not a positive integer (e.g., zero, negative, a float, a string, or a boolean),
  the node returns an error message describing the problem.
* **Output Variable:** The result string is assigned to a variable based on the node's position in the workflow
  (e.g., `{agent1Output}`, `{agent2Output}`, etc.).
