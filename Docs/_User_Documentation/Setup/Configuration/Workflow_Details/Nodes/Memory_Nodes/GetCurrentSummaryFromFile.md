## The `GetCurrentSummaryFromFile` Node

This guide provides a code-validated overview of the `GetCurrentSummaryFromFile` node. It details the simple, direct
function as fast file reader.

### Core Purpose

The **`GetCurrentSummaryFromFile`** node is a simple, direct **"dumb" reader**. Its sole function is to read the
complete content of the rolling summary file (`<id>_summary.jsonl`) and return it as a string. It performs no staleness
checks, triggers no updates, and has no complex logic, making it the fastest way to retrieve the current summary.

-----

### Internal Execution Flow

1. **File Location**: The node identifies the path to the `<id>_summary.jsonl` file.
2. **File Read**: It opens the file, reads its entire contents into a string.
3. **Return Content**: It returns the string.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node **always** returns a string containing the full, raw text of the
  current rolling summary file.

-----

### Node Properties

| Property   | Type   | Required? | Description                            |
|:-----------|:-------|:----------|:---------------------------------------|
| **`type`** | String | ✅ Yes     | Must be `"GetCurrentSummaryFromFile"`. |

-----

### Workflow Strategy and Annotated Example

Use this node when you need the absolute fastest, no-frills read of the chat summary and are either managing the update
process manually or do not require the summary to be perfectly up-to-date.

```json
[
  {
    "title": "Step 1: Quickly grab the current conversation summary",
    "type": "GetCurrentSummaryFromFile"
    // --- BEHAVIOR CONTROL ---
    // This is a direct file read. It's extremely fast but the data
    // could be stale if a QualityMemory node has run recently.
    // The output is now in {agent1Output}.
  },
  {
    "title": "Step 2: Use the summary for a task",
    "type": "Standard",
    "returnToUser": true,
    "prompt": "Using this summary, please create a list of key characters:\n\n{agent1Output}"
  }
]
```