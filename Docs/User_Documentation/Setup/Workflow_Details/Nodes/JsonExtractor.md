### **Data Extraction: The `JsonExtractor` Node**

The **`JsonExtractor`** node is a utility for extracting a specific field from a JSON string. It takes a JSON object (or
a string containing JSON, optionally wrapped in markdown code blocks), resolves any workflow variables, and returns the
value of the specified field as a string. This is useful for parsing structured LLM outputs or extracting data from
API responses within a workflow.

-----

#### **How It Works**

1. **Configuration Loading:** The processor loads the `jsonToExtractFrom` and `fieldToExtract` fields from the node's
   configuration.
2. **Variable Substitution:** Both fields are processed with the `WorkflowVariableManager`, allowing you to use variables
   like `{agent1Output}` or `{agent1Input}` to reference JSON strings from other nodes.
3. **Markdown Stripping:** If the JSON string is wrapped in markdown code blocks (` ```json ` or ` ``` `), the node
   automatically strips this formatting before parsing.
4. **JSON Parsing:** The cleaned string is parsed as JSON. If parsing fails or the result is not a JSON object, the node
   returns an empty string.
5. **Field Extraction:** The specified field is extracted from the parsed JSON object.
6. **Type Conversion:** The extracted value is converted to a string:
   - Strings are returned as-is
   - Numbers and booleans are converted to their string representation
   - Nested objects and arrays are returned as JSON strings
   - `null` values return an empty string

-----

#### **Properties**

| Property              | Type   | Required | Default | Description                                                                                                           |
|:----------------------|:-------|:---------|:--------|:----------------------------------------------------------------------------------------------------------------------|
| **`type`**            | String | Yes      | N/A     | Must be `"JsonExtractor"`.                                                                                            |
| **`title`**           | String | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                                      |
| **`jsonToExtractFrom`** | String | Yes      | N/A     | The JSON string to extract from. Supports variable substitution. Can be wrapped in markdown code blocks.              |
| **`fieldToExtract`**  | String | Yes      | N/A     | The name of the field to extract from the JSON object. Supports variable substitution.                                |

-----

#### **Variable Usage**

Both `jsonToExtractFrom` and `fieldToExtract` support all available workflow variables. This allows you to:
- Reference JSON output from a previous node (e.g., `{agent1Output}`)
- Pass JSON strings from a parent workflow (e.g., `{agent1Input}`)
- Dynamically specify which field to extract based on workflow state

-----

#### **Handling Markdown Code Blocks**

LLMs often wrap JSON output in markdown code blocks for formatting. This node automatically handles the following
formats:

```
```json
{"name": "value"}
```
```

```
```
{"name": "value"}
```
```

The node will strip these code block markers before parsing the JSON.

-----

#### **Full Syntax Example**

This example extracts the "name" field from a JSON object returned by a previous LLM node.

```json
{
  "title": "Extract Character Name from LLM Response",
  "type": "JsonExtractor",
  "jsonToExtractFrom": "{agent1Output}",
  "fieldToExtract": "name"
}
```

**Example Input (from `agent1Output`):**
```json
{
  "name": "Socg",
  "file": "Socg.txt",
  "description": "A mysterious character"
}
```

**Example Output:** `Socg`

-----

#### **Example with Nested Objects**

When extracting a nested object or array, the node returns it as a JSON string.

```json
{
  "title": "Extract Character Details",
  "type": "JsonExtractor",
  "jsonToExtractFrom": "{agent1Output}",
  "fieldToExtract": "metadata"
}
```

**Example Input:**
```json
{
  "name": "Socg",
  "metadata": {"age": 25, "traits": ["brave", "clever"]}
}
```

**Example Output:** `{"age": 25, "traits": ["brave", "clever"]}`

-----

#### **Example with Dynamic Field Name**

You can use variables to dynamically determine which field to extract.

```json
{
  "title": "Extract Dynamic Field",
  "type": "JsonExtractor",
  "jsonToExtractFrom": "{agent1Output}",
  "fieldToExtract": "{agent2Output}"
}
```

If `agent2Output` contains `"description"`, this will extract the "description" field from the JSON.

-----

#### **Behavior and Edge Cases**

* **Missing Field:** If the specified field does not exist in the JSON object, the node returns an empty string.
* **Invalid JSON:** If the input cannot be parsed as JSON, the node returns an empty string and logs a warning.
* **Non-Object JSON:** If the JSON is valid but is an array or primitive (not an object), the node returns an empty
  string. Only JSON objects with key-value pairs are supported.
* **Null Values:** If the field exists but its value is `null`, the node returns an empty string.
* **Empty String Values:** If the field exists but its value is an empty string, the node returns an empty string.
* **Output Variable:** The extracted string is assigned to a variable based on the node's position in the workflow
  (e.g., `{agent1Output}`, `{agent2Output}`, etc.).
