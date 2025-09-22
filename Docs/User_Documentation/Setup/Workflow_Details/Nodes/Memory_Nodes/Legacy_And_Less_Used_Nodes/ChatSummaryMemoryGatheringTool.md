## The `ChatSummaryMemoryGatheringTool` Node

This guide provides a comprehensive, code-validated overview of the `ChatSummaryMemoryGatheringTool` node. It details
this specialized retriever's precise execution logic, properties, and its role in advanced, custom memory-management
workflows.

### Core Purpose

The **`ChatSummaryMemoryGatheringTool`** is a specialized **retriever** designed for a single purpose: to fetch all new
memory chunks created since the last rolling chat summary was generated. It acts as the first step in a manual summary
update process by gathering the precise data needed by a summarizer node (like `chatSummarySummarizer`). It does not
retrieve general memories for RAG, but rather collects the specific "new material" to be summarized.

-----

### Internal Execution Flow

1. **Identify Markers**: The node reads the main memory file (`<id>_memories.jsonl`) and the summary file (
   `<id>_summary.jsonl`).
2. **Hash Comparison**: It identifies the hash of the last memory chunk that was incorporated into the current summary.
3. **Gather New Chunks**: It then gathers all memory chunks from the main memory file that are newer than that
   last-processed hash.
4. **Result Aggregation**: The text from these new chunks is joined into a single string, ready to be passed to a
   summarization model.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node **always** returns a single string containing all the new memory chunks
  that need to be summarized. If no new memories have been created since the last summary was generated, it returns an
  empty string.

-----

### Node Properties

| Property             | Type    | Required? | Description                                                                                                                          |
|:---------------------|:--------|:----------|:-------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**           | String  | ✅ Yes     | Must be exactly `"ChatSummaryMemoryGatheringTool"`.                                                                                  |
| **`maxTurnsToPull`** | Integer | ✅ Yes     | **Used in Stateless Mode.** The number of recent conversation turns to pull from the chat history when no `discussionId` is present. |

-----

### Workflow Strategy and Annotated Example

This node should be used as the first step in a multi-stage workflow designed to manually update the rolling chat
summary. It provides the input for a subsequent summarizer node.

```json
[
  {
    "title": "Step 1: Gather all new memory chunks since last summary",
    "type": "ChatSummaryMemoryGatheringTool",
    "maxTurnsToPull": 20
    // --- DATA GATHERING ---
    // This node's output ({agent1Output}) will be a block of text containing
    // all the new memories that haven't been summarized yet.
  },
  {
    "title": "Step 2: Summarize the new chunks (if any)",
    "type": "chatSummarySummarizer",
    // This node would take {agent1Output} as an implicit input
    // and generate an updated summary.
    "prompt": "Please integrate the following new information into the existing summary...\nNew Info: [LATEST_MEMORIES]\n\nExisting Summary: [CHAT_SUMMARY]"
  }
]
```
