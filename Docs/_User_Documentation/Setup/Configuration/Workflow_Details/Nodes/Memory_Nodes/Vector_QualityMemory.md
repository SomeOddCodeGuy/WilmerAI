## The `QualityMemory` Node

This guide provides a comprehensive, code-validated overview of the `QualityMemory` node. It details the node's precise
execution logic, configuration, and best practices, establishing it as the cornerstone of the WilmerAI memory creation
system.

### Core Purpose

The **`QualityMemory`** node is the primary and **only recommended creator node** in the memory system. Its exclusive
function is to analyze the conversation history for new messages and, if certain thresholds are met, generate and save
new memories to persistent storage. It intelligently switches between creating classic file-based memories (`.jsonl`)
and modern, searchable vector memories (`.db`) based on the discussion's configuration.

Crucially, this node **produces no direct output** for subsequent nodes (its `{agent#Output}` will be empty). Its job is
to perform a "write" operation in the background. It is almost always placed at the end of a workflow to prevent memory
generation from delaying the AI's response to the user.

-----

### Internal Execution Flow

The node's logic is a sophisticated, multi-step process orchestrated by an internal tool:

1. **Mode Detection**: The node first checks if a `discussionId` is present in the context.
    * **Stateful (Default)**: If a `discussionId` is present, it proceeds with the full memory creation flow.
    * **Stateless (Fallback)**: If no `discussionId` exists, it acts as a simple retriever, parsing a few recent turns
      from the current chat history and outputting them as a string.
2. **Configuration Check**: In stateful mode, it reads the discussion-specific settings file to determine the master
   memory strategy (vector vs. file-based).
3. **History Analysis**: It compares the current conversation history against a "last processed" marker to identify new,
   unprocessed messages.
4. **Threshold Evaluation**: It determines if enough new messages exist to warrant creating a new memory chunk, based on
   configured token counts or message counts.
5. **Memory Generation**: If the threshold is met, it generates the memory summary by either executing a dedicated
   sub-workflow or making a direct LLM call.
6. **Persistence**: The newly generated memory is saved to the appropriate storage (`.db` or `.jsonl`), and the "last
   processed" marker is updated for the next run.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: This node is designed as a background task. In its primary, stateful mode, it *
  *does not return a value**. Its `{agent#Output}` will be `None`. Its sole purpose is the side effect of writing to
  memory files.

-----

### Node Properties

| Property   | Type   | Required? | Description                        |
|:-----------|:-------|:----------|:-----------------------------------|
| **`type`** | String | ✅ Yes     | Must be exactly `"QualityMemory"`. |

**Note**: All functional configuration for this node (e.g., LLM endpoints, prompts, vector vs. file strategy) is
controlled externally in a discussion-specific settings file, not within the workflow node itself.

-----

### Workflow Strategy and Annotated Example

The `QualityMemory` node should be placed at the **end** of your primary response workflow. This ensures that the
potentially slow process of memory generation happens *after* the user has already received a fast reply. It's often
paired with a `WorkflowLock` to prevent race conditions.

```json
{
  "nodes": [
    {
      "title": "Step 1: Search for relevant facts in memory",
      "type": "VectorMemorySearch",
      "input": "{chat_user_prompt_last_one}"
    },
    {
      "title": "Step 2: Respond to the user using the facts",
      "type": "Standard",
      "returnToUser": true,
      "prompt": "Relevant Information: {agent1Output}\n\nBased on this, respond to the user's last message."
    },
    {
      "title": "Step 3: Lock the workflow to allow background processing",
      "type": "WorkflowLock",
      "lockName": "memory-generation-lock"
    },
    {
      "title": "Step 4: (In Background) Update memories with the latest turn",
      "type": "QualityMemory"
      // --- BEHAVIOR CONTROL ---
      // This node runs last and has no output. It analyzes the conversation
      // that just happened and writes a new memory chunk to the database
      // if enough new content exists.
    }
  ]
}
```