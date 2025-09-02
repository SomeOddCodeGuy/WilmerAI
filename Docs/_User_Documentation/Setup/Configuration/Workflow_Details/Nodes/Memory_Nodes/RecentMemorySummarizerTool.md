## The `RecentMemorySummarizerTool` Node

This guide provides a comprehensive, code-validated overview of the `RecentMemorySummarizerTool` node. It details the
node's dual-mode logic, properties, and best practices for retrieving recent conversational context.

### Core Purpose

The **`RecentMemorySummarizerTool`** node is the primary retriever for file-based memories. Its function is to quickly
fetch the most recent memory chunks from the long-term memory file (`<id>_memories.jsonl`). A key feature is its ability
to fall back to a stateless mode if no `discussionId` is active, making it versatile for retrieving context from both
long-term storage and the immediate chat history.

-----

### Internal Execution Flow

The node operates in one of two modes depending on the presence of a `discussionId`:

* **Stateful Mode (with `discussionId`)**:

    1. The node locates the discussion's `<id>_memories.jsonl` file.
    2. It reads all hashed memory chunks from the file.
    3. It slices the list to retrieve only the last `maxSummaryChunksFromFile` chunks.
    4. The text from these chunks is joined into a single string using the specified delimiter.

* **Stateless Mode (without `discussionId`)**:

    1. The node operates directly on the current conversation history (`messages` list).
    2. It looks back `maxTurnsToPull` turns from the end of the conversation.
    3. These turns are formatted and joined into a single string.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node **always** returns a single string containing the requested memory
  chunks or conversation turns. If no memories exist in stateful mode, it returns a message like
  `"There are not yet any memories"`.

-----

### Node Properties

| Property                       | Type    | Required? | Description                                                                                                                                  |
|:-------------------------------|:--------|:----------|:---------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                     | String  | ✅ Yes     | Must be exactly `"RecentMemorySummarizerTool"`.                                                                                              |
| **`maxSummaryChunksFromFile`** | Integer | ✅ Yes     | **Used in Stateful Mode.** The number of most recent memory chunks to retrieve from the `.jsonl` file. Set to `-1` to retrieve all memories. |
| **`maxTurnsToPull`**           | Integer | ✅ Yes     | **Used in Stateless Mode.** The number of recent conversation turns to pull from the chat history when no `discussionId` is present.         |
| **`customDelimiter`**          | String  | ❌ No      | **Default: `"--ChunkBreak--"`**. A custom string to use for separating the retrieved memory chunks or turns.                                 |
| **`lookbackStart`**            | Integer | ❌ No      | **Default: `0`**. The number of turns to skip from the very end of the conversation before starting to pull content.                         |

-----

### Workflow Strategy and Annotated Example

Use this node to give an AI a quick refresher on recent events before it generates a response, especially in contexts
that rely on file-based memory.

```json
[
  {
    "title": "Step 1: Get a summary of the last 3 major events",
    "type": "RecentMemorySummarizerTool",
    "maxSummaryChunksFromFile": 3,
    "maxTurnsToPull": 5,
    // This will be used if no discussionId is active
    "customDelimiter": "\n\n---\n\n"
    // --- CONTEXT GATHERING ---
    // This node quickly fetches the most recent memories without a complex search.
    // The output is placed in {agent1Output}.
  },
  {
    "title": "Step 2: Formulate Final Response",
    "type": "Standard",
    "returnToUser": true,
    "systemPrompt": "Here is a summary of recent events:\n{agent1Output}\n\nBased on these events, respond to the user's latest prompt: {chat_user_prompt_last_one}"
  }
]
```

