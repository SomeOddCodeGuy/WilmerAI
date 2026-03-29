## The `GetCurrentMemoryFromFile` Node

This guide provides a code-validated overview of the `GetCurrentMemoryFromFile` node. It details the
node's function as a direct reader of the long-term memory file.

### Core Purpose

The **`GetCurrentMemoryFromFile`** node is a simple, direct **"dumb" reader**. Its sole function is to
read the complete contents of the long-term memory file (`<id>_memories.json`) and return all memory
chunks joined into a single string. It performs no staleness checks, triggers no updates, and has no
complex logic.

This node is the counterpart to `GetCurrentSummaryFromFile`. Where `GetCurrentSummaryFromFile` reads
the rolling chat summary, `GetCurrentMemoryFromFile` reads the individual memory chunks that the memory
system has generated over the conversation's lifetime.

-----

### Internal Execution Flow

1. **File Location**: The node identifies the path to the `<id>_memories.json` file using the active
   `discussionId`.
2. **File Read**: It reads all memory chunks from the file.
3. **Join and Return**: It joins all chunks using the configured delimiter and returns the resulting
   string. If no `discussionId` is available, it returns a fallback message.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node always returns a string containing all memory chunks
  joined by the configured delimiter. If no `discussionId` is active, it returns
  `"There are not yet any memories"`.

-----

### Node Properties

| Property              | Type   | Required? | Description                                                                 |
|:----------------------|:-------|:----------|:----------------------------------------------------------------------------|
| **`type`**            | String | Yes       | Must be exactly `"GetCurrentMemoryFromFile"`.                               |
| **`customDelimiter`** | String | No        | The string used to join memory chunks. Defaults to `"--ChunkBreak--"`.      |

-----

### Workflow Strategy and Annotated Example

Use this node when you need the raw contents of the long-term memory file as a single string. This is
useful when you want to pass the full memory set to an LLM for analysis or condensation, or when you
need to inspect all memories without filtering.

If you only need the most recent memories, `RecentMemorySummarizerTool` is more appropriate. If you
need the rolling conversation summary rather than the individual memory chunks, use
`GetCurrentSummaryFromFile`.

```json
[
  {
    "title": "Step 1: Load all memory chunks",
    "type": "GetCurrentMemoryFromFile",
    "customDelimiter": "\n\n---\n\n"
    // --- BEHAVIOR CONTROL ---
    // This is a direct file read. It returns all memory chunks joined by the
    // specified delimiter. No memory generation is triggered.
  },
  {
    "title": "Step 2: Use the memories for a task",
    "type": "Standard",
    "returnToUser": true,
    "prompt": "Based on the following memory chunks from our conversation, summarize the key events:\n\n{agent1Output}"
  }
]
```
