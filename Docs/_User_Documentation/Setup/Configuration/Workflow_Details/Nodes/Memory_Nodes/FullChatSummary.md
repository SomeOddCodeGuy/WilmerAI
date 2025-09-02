## The `FullChatSummary` Node

This guide provides a comprehensive, code-validated overview of the `FullChatSummary` node. It details the node's
complex execution logic, properties, and performance implications, highlighting its role as a combined creator and
retriever.

### Core Purpose

The **`FullChatSummary`** node retrieves the single, "rolling summary" of the entire conversation. It includes "smart"
logic to automatically update the summary if it detects that it is stale relative to the main memory file.

Functionally, you can think of this node as a **combination of the `QualityMemory` and `chatSummarySummarizer`
nodes**. It first ensures the main memory file is up-to-date (the `QualityMemory` part) and then ensures the rolling
summary is also up-to-date (the `chatSummarySummarizer` part) before finally returning the result.

⚠️ **Performance Warning**: Because this node is a **combined creator and retriever**, it first triggers the entire
`QualityMemory` creation process *before* retrieving the summary. This can introduce significant delays and is a
critical factor in workflow design.

-----

### Internal Execution Flow

This node performs two major operations in strict sequence:

1. **Trigger Memory Creation**: The node **first triggers the entire `QualityMemory` creation process**. It checks for
   new messages in the conversation and generates new memory chunks for the main `<id>_memories.jsonl` file if
   thresholds are met. The workflow **will wait** for this potentially slow operation to complete.
2. **Perform Staleness Check & Retrieval**: Only after the creation step is finished does it proceed.
    * It compares the hash of the current rolling summary to the hashes in the main memory file.
    * If the summary is **stale** (new memory chunks exist), it triggers a background sub-workflow to generate a new,
      updated summary and returns the new version.
    * If the summary is **up-to-date**, it simply reads the summary text from the file and returns it.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node **always** returns a single string containing the full text of the
  rolling chat summary, whether it was read directly or newly generated.

-----

### Node Properties

| Property             | Type    | Required? | Description                                                                                                                                                                              |
|:---------------------|:--------|:----------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**           | String  | ✅ Yes     | Must be exactly `"FullChatSummary"`.                                                                                                                                                     |
| **`isManualConfig`** | Boolean | ❌ No      | **Default: `false`**. If `true`, disables both the memory creation and staleness check, forcing a direct, "dumb" read from the summary file. This is the only way to make the node fast. |

-----

### Workflow Strategy and Annotated Example

Use this node when a task requires broad, high-level context of the entire conversation. To avoid unexpected delays,
consider using `isManualConfig: true` and managing summary updates in a separate, dedicated workflow.

```json
[
  {
    "title": "Step 1: Retrieve the complete story so far",
    "type": "FullChatSummary",
    "isManualConfig": true
    // --- BEHAVIOR CONTROL ---
    // isManualConfig is set to true to prevent the node from running the slow
    // memory creation process first. This makes it a fast, read-only operation.
  },
  {
    "title": "Step 2: Use the summary to answer a high-level question",
    "type": "Standard",
    "returnToUser": true,
    "prompt": "Based on the following complete summary of our conversation, please answer my question.\n\nSummary:\n{agent1Output}\n\nUser's Question: {chat_user_prompt_last_one}"
  }
]
```