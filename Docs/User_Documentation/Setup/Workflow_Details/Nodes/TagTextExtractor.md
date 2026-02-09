### **Data Extraction: The `TagTextExtractor` Node**

The **`TagTextExtractor`** node is a utility for extracting content from XML/HTML-style tags within a text string. It
searches for a specified tag (e.g., `<answer>...</answer>`) and returns the content between the opening and closing
tags. This is useful for parsing structured LLM outputs where the model has been instructed to wrap specific content
in custom tags.

-----

#### **How It Works**

1. **Configuration Loading:** The processor loads the `tagToExtractFrom` and `fieldToExtract` fields from the node's
   configuration.
2. **Variable Substitution:** Both fields are processed with the `WorkflowVariableManager`, allowing you to use variables
   like `{agent1Output}` or `{agent1Input}` to reference text from other nodes.
3. **Tag Matching:** The node searches for the first occurrence of `<tagName>...</tagName>` in the text using a
   case-sensitive regex pattern.
4. **Content Extraction:** If the tag is found, the content between the opening and closing tags is extracted.
5. **Whitespace Handling:** Leading and trailing whitespace is stripped from the extracted content, but internal
   whitespace and formatting is preserved.

-----

#### **Properties**

| Property              | Type   | Required | Default | Description                                                                                                |
|:----------------------|:-------|:---------|:--------|:-----------------------------------------------------------------------------------------------------------|
| **`type`**            | String | Yes      | N/A     | Must be `"TagTextExtractor"`.                                                                              |
| **`title`**           | String | No       | `""`    | A descriptive name for the node, used for logging and debugging.                                           |
| **`tagToExtractFrom`** | String | Yes      | N/A     | The text string to search within. Supports variable substitution.                                          |
| **`fieldToExtract`**    | String | Yes      | N/A     | The name of the tag to search for (without angle brackets). Supports variable substitution.                |

-----

#### **Variable Usage**

Both `tagToExtractFrom` and `fieldToExtract` support all available workflow variables. This allows you to:
- Reference text output from a previous LLM node (e.g., `{agent1Output}`)
- Pass text strings from a parent workflow (e.g., `{agent1Input}`)
- Dynamically specify which tag to extract based on workflow state

-----

#### **Full Syntax Example**

This example extracts the content within `<answer>` tags from an LLM response.

```json
{
  "title": "Extract Answer from LLM Response",
  "type": "TagTextExtractor",
  "tagToExtractFrom": "{agent1Output}",
  "fieldToExtract": "answer"
}
```

**Example Input (from `agent1Output`):**
```
I've analyzed your question carefully. Here is my response:

<answer>
The capital of France is Paris.
</answer>

I hope this helps with your research.
```

**Example Output:** `The capital of France is Paris.`

-----

#### **Example with Custom Tags**

You can use any tag name that makes sense for your workflow. Common patterns include:
- `<thinking>...</thinking>` for chain-of-thought reasoning
- `<code>...</code>` for code blocks
- `<summary>...</summary>` for summaries
- `<character_name>...</character_name>` for specific data fields

```json
{
  "title": "Extract Character Name",
  "type": "TagTextExtractor",
  "tagToExtractFrom": "{agent1Output}",
  "fieldToExtract": "character_name"
}
```

**Example Input:**
```
Based on the story context, I've created a character:

<character_name>
Socg the Wanderer
</character_name>

<character_description>
A mysterious traveler with a penchant for riddles.
</character_description>
```

**Example Output:** `Socg the Wanderer`

-----

#### **Example with Dynamic Tag Name**

You can use variables to dynamically determine which tag to extract.

```json
{
  "title": "Extract Dynamic Tag Content",
  "type": "TagTextExtractor",
  "tagToExtractFrom": "{agent1Output}",
  "fieldToExtract": "{agent2Output}"
}
```

If `agent2Output` contains `"character_description"`, this will extract the content from the
`<character_description>` tags.

-----

#### **Example with Multiline Content**

The node preserves internal formatting, including newlines and indentation.

```json
{
  "title": "Extract Code Block",
  "type": "TagTextExtractor",
  "tagToExtractFrom": "{agent1Output}",
  "fieldToExtract": "code"
}
```

**Example Input:**
```
Here is the implementation:

<code>
def hello_world():
    print("Hello, World!")
    return True
</code>
```

**Example Output:**
```
def hello_world():
    print("Hello, World!")
    return True
```

-----

#### **Behavior and Edge Cases**

* **Tag Not Found:** If the specified tag is not found in the text, the node returns an empty string.
* **First Match Only:** If multiple instances of the same tag exist, only the first match is extracted.
* **Case Sensitivity:** Tag matching is case-sensitive. `<Answer>` and `<answer>` are treated as different tags.
* **Nested Tags:** The node uses non-greedy matching, so `<outer><inner>content</inner></outer>` with `fieldToExtract`
  set to `"outer"` will return `<inner>content</inner>`.
* **Self-Closing Tags:** Self-closing tags (e.g., `<tag/>`) are not supported. The node requires both opening and
  closing tags.
* **Empty Content:** If the tag exists but contains only whitespace, the node returns an empty string.
* **Mismatched Tags:** If the opening and closing tags don't match (e.g., `<tag>content</other>`), the node returns an
  empty string.
* **Special Characters in Tag Names:** Tag names with special regex characters (like `.` or `*`) are properly escaped.
  Tags with underscores (`_`), hyphens (`-`), and alphanumeric characters work correctly.
* **Output Variable:** The extracted string is assigned to a variable based on the node's position in the workflow
  (e.g., `{agent1Output}`, `{agent2Output}`, etc.).
