## The `chatSummarySummarizer` Node

This guide provides a comprehensive, code-validated overview of the `chatSummarySummarizer` node. It details its
powerful iterative logic and its role as the core engine for creating and updating rolling chat summaries.

### Core Purpose

The **`chatSummarySummarizer`** is a powerful, low-level **creator node** that manages the iterative process of updating
the rolling chat summary. It is designed to handle a large number of new memory chunks by processing them in intelligent
batches, preventing the LLM context from becoming too large and ensuring a coherent, evolving summary over a long
conversation.

-----

### Internal Execution Flow

1. **Gather Inputs**: The node first uses internal logic (similar to `ChatSummaryMemoryGatheringTool` and
   `GetCurrentSummaryFromFile`) to collect the existing chat summary and all new, unprocessed memory chunks.
2. **Threshold Check**: It checks if the number of new memory chunks meets the `minMemoriesPerSummary` threshold. If
   not, it stops.
3. **Batch Processing Loop**: If the number of new chunks exceeds the `loopIfMemoriesExceed` value, it enters a `while`
   loop. In each iteration of the loop, it:
    * Takes a batch of new memory chunks.
    * Calls an LLM using the provided prompts, feeding it the *previous summary* and the *current batch*.
    * The LLM's output becomes the *new* summary for the next iteration.
    * This continues until all batches are processed.
4. **Final Update**: The final generated summary is saved to the summary file.

-----

### The `[CHAT_SUMMARY]` and `[LATEST_MEMORIES]` Placeholders

These are special, context-specific keywords that are essential for this node to function.

* **Valid Context**: They can **only** be used within the `prompt` and `systemPrompt` strings of a
  `chatSummarySummarizer` node.
* **Function**:
    * `[CHAT_SUMMARY]` is the location where the node inserts the *previous* rolling summary.
    * `[LATEST_MEMORIES]` is where the node inserts the *current batch* of new memory chunks.
* **Warning**: Do not use these placeholders in any other node type. They will be treated as literal text.

-----

### Node Properties

| Property                      | Type    | Required? | Description                                                                                                                          |
|:------------------------------|:--------|:----------|:-------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                    | String  | ✅ Yes     | Must be exactly `"chatSummarySummarizer"`.                                                                                           |
| **`systemPrompt` / `prompt`** | String  | ✅ Yes     | The prompts for the summarization LLM. **Must** use the `[CHAT_SUMMARY]` and `[LATEST_MEMORIES]` placeholders to function correctly. |
| **`endpointName`**            | String  | ❌ No      | The LLM endpoint to use for summarization. **Supports LIMITED variables: only `{agent#Input}` from parent workflows and static workflow variables, NOT `{agent#Output}`.**|
| **`preset`**                  | String  | ❌ No      | The generation preset to use. **Supports LIMITED variables like endpointName.**                                                      |
| **`minMemoriesPerSummary`**   | Integer | ❌ No      | **Default: `3`**. The minimum number of new memory chunks required to trigger a summary update at all.                               |
| **`loopIfMemoriesExceed`**    | Integer | ❌ No      | **Default: `3`**. The batch size for processing new memories. If 7 new memories exist, it will run 3 times (3, 3, 1).                |

-----

### Workflow Strategy and Annotated Example

This node is the core of a manual summary update workflow, often used after `ChatSummaryMemoryGatheringTool` and before
`WriteCurrentSummaryToFileAndReturnIt`.

```json
{
  "title": "Update the Rolling Conversation Summary",
  "type": "chatSummarySummarizer",
  "minMemoriesPerSummary": 2,
  "loopIfMemoriesExceed": 5,
  "systemPrompt": "You are a summarization AI. Your task is to seamlessly integrate new conversation memories into the existing summary.",
  "prompt": "EXISTING SUMMARY:\n[CHAT_SUMMARY]\n\n---\n\nNEW MEMORIES TO INTEGRATE:\n[LATEST_MEMORIES]\n\n---\n\nPRODUCE THE NEW, UPDATED SUMMARY:",
  "endpointName": "Text-Processing-Endpoint",
  "preset": "Summarizer_Preset"
  // --- BEHAVIOR CONTROL ---
  // This node will only run if there are at least 2 new memories.
  // It will process them in batches of 5 to create the final summary,
  // which is then available in its {agent#Output}.
}
```