### **Feature Guide: WilmerAI's Memory System**

WilmerAI uses a three-part memory system for managing long-term conversational context. It is designed to provide both
chronological recall and relevant information retrieval.

The system separates memory creation from retrieval to maintain response speed during stateful conversations. To use
persistent memory, the `[DiscussionId]` tag must be included in the initial user message.

-----

## System Architecture: The Three Memory Components

WilmerAI's memory consists of three components. Each is stored in a separate file and linked by a unique discussion ID.

* **Long-Term Memory File (`<id>_memories.jsonl`)**: This file stores chronological summaries of the conversation. The
  system periodically reviews the chat history, divides it into chunks, and uses an LLM to summarize each chunk.
* **Rolling Chat Summary (`<id>_summary.jsonl`)**: This file contains a single, continuously updated summary of the
  entire conversation. It synthesizes the chunks from the Long-Term Memory File to provide a high-level overview.
* **Searchable Vector Memory (`<id>_vector_memory.db`)**: A dedicated vector database for the discussion. When a memory
  is created, it can be stored here as a vector embedding with structured metadata (**title, summary, entities, key
  phrases**). This allows for efficient semantic searches to retrieve relevant information based on a query.

-----

## Workflow Nodes for Memory Interaction

The memory system is controlled via workflow nodes. These are separated into nodes that create memories (computationally
intensive) and nodes that retrieve them (fast).

### Memory Creators (Writers)

These nodes analyze chat history and write data to the memory files.

* **`QualityMemory`**: The primary node for creating and updating memories. It can generate both **Long-Term File** and
  **Vector** memories depending on the configuration.
  ```json
  {
    "id": "create_memories_node",
    "type": "QualityMemory",
    "name": "Create/Update All Memories"
  }
  ```
* **`ChatSummarySummarizer`**: This node updates the **Rolling Chat Summary**. It processes new chunks from the
  long-term memory file and integrates them into the existing summary.
  ```json
  {
    "id": "update_rolling_summary_node",
    "type": "chatSummarySummarizer",
    "name": "Update Rolling Chat Summary",
    "minMemoriesPerSummary": 3,
    "loopIfMemoriesExceed": 3
  }
  ```

### Memory Retrievers (Readers)

These nodes read memory context for use in a prompt. They are categorized by their function and whether they update
memories before reading.

* **Pure/Fast Readers**: These nodes perform a direct read from the memory files. They are fast and suitable for
  providing context to an LLM call without adding latency.

* **Read-and-Update Nodes**: Before reading, these nodes first trigger the memory creation process to ensure the data is
  current. This can introduce latency.

* **`RecentMemorySummarizerTool`** (Pure/Fast Reader)
  Reads the last few summary chunks from the Long-Term Memory File, providing context on recent parts of the
  conversation.

  ```json
  {
    "id": "get_recent_memories_node",
    "type": "RecentMemorySummarizerTool",
    "name": "Get Recent Memories",
    "maxTurnsToPull": 0,
    "maxSummaryChunksFromFile": 3,
    "lookbackStart": 0,
    "customDelimiter": "--ChunkBreak--"
  }
  ```

* **`RecentMemory`** (Read-and-Update Node)
  Retrieves recent memories, but first runs the `QualityMemory` creation process to ensure long-term memories are
  current.

  ```json
  {
    "id": "update_and_get_recent_memories",
    "type": "RecentMemory",
    "name": "Update and Get Recent Memories"
  }
  ```

* **`GetCurrentSummaryFromFile`** (Pure/Fast Reader)
  Performs a direct read of the Rolling Chat Summary file (`_summary.jsonl`) to get the full conversation summary.

  ```json
  {
    "id": "get_full_summary_fast_node",
    "type": "GetCurrentSummaryFromFile",
    "name": "Get Full Chat Summary (Fast)"
  }
  ```

* **`FullChatSummary`** (Read-and-Update Node)
  Reads the Rolling Chat Summary after ensuring that both the long-term memories and the summary itself are updated.

  ```json
  {
    "id": "update_and_get_summary_node",
    "type": "FullChatSummary",
    "name": "Update and Get Full Chat Summary",
    "isManualConfig": false
  }
  ```

* **`VectorMemorySearch`** (Pure/Fast Reader)
  Queries the Vector Memory database for semantically relevant information. It is suitable for Retrieval-Augmented
  Generation (RAG).

  ```json
  {
    "id": "smart_search_node",
    "type": "VectorMemorySearch",
    "name": "Search for Specific Details",
    "input": "Project Stardust;mission parameters;Dr. Evelyn Reed",
    "limit": 5
  }
  ```

  *Note: Search keywords must be separated by a semicolon (`;`). The query uses `OR` logic and is limited to a maximum
  of 60 keywords.*

-----

## Performance: Separating Reading from Writing

The separation of creator and reader nodes is for performance. Writing and summarizing memories is time-consuming. This
design allows a workflow to provide a response to the user immediately, while memory processing occurs in a background
process, often managed with **Workflow Locks**.

A typical high-performance flow is as follows:

1. **Read Memory:** A fast reader node (`VectorMemorySearch`, `GetCurrentSummaryFromFile`) pulls existing context.
2. **AI Responds:** The primary LLM generates a response using the context.
3. **Workflow Lock:** The workflow locks after delivering the response to the user.
4. **Create Memory:** A creator node (`QualityMemory`) runs in a non-blocking background process to analyze the latest
   exchange and update memory files for the next turn.

This architecture allows for a responsive chat experience by not blocking the user response on memory processing.

-----

## Configuration

Memory behavior is configured in the `_DiscussionId-MemoryFile-Workflow-Settings.json` file. Memory generation can be
defined using direct LLM settings (prompts, endpoint) or by specifying a sub-workflow for more complex logic. **If a
sub-workflow is specified for a memory type, its direct LLM settings are ignored.**

The `useVectorForQualityMemory` flag controls which memory system is active.

* If `false`, `QualityMemory` writes to the Long-Term Memory file.
* If `true`, `QualityMemory` creates entries in the Searchable Vector Memory.

*Example `_DiscussionId-MemoryFile-Workflow-Settings.json`:*

```json
{
  // Sets the memory system used by the QualityMemory node.
  "useVectorForQualityMemory": true,
  // ====================================================================
  // == Vector Memory Configuration (Only used if the above is true) ==
  // ====================================================================

  // Specify a workflow to generate the structured JSON for a vector memory.
  "vectorMemoryWorkflowName": "my-vector-memory-workflow",
  // The settings below are IGNORED if "vectorMemoryWorkflowName" is set.
  "vectorMemoryEndpointName": "gpt-4-turbo",
  "vectorMemoryPreset": "default_preset_for_json_output",
  "vectorMemoryMaxResponseSizeInTokens": 1024,
  "vectorMemoryChunkEstimatedTokenSize": 1000,
  "vectorMemoryMaxMessagesBetweenChunks": 5,
  "vectorMemoryLookBackTurns": 3,
  // ====================================================================
  // == File-based Memory Configuration (Only used if the switch is false) ==
  // ====================================================================

  // Specify a workflow to generate the summary text for a file-based memory.
  "fileMemoryWorkflowName": "my-file-memory-workflow",
  // The prompts below are IGNORED if "fileMemoryWorkflowName" is set.
  "systemPrompt": "You are an expert summarizer...",
  "prompt": "Please summarize the following: [TextChunk]",
  "chunkEstimatedTokenSize": 1000,
  "maxMessagesBetweenChunks": 5,
  "lookbackStartTurn": 3,
  // ====================================================================
  // == General / Fallback LLM Settings                              ==
  // ====================================================================

  // The default LLM endpoint to use if a specific one isn't set for a direct LLM call.
  "endpointName": "default_endpoint",
  "preset": "default_preset",
  "maxResponseSizeInTokens": 400
}
```

-----

## Maintenance: Regenerating Memories

To regenerate all memories for a discussion, **delete the corresponding memory files** from the `Public/` directory:

1. `Public/<id>_memories.jsonl` (Long-Term Memory)
2. `Public/<id>_summary.jsonl` (Rolling Summary)
3. `Public/<id>_vector_memory.db` (Searchable Vector Memory)

**Important:** To prevent state conflicts, delete all memory files for a given discussion ID. When a workflow with a
memory creator node is next run, the system will detect the missing files and regenerate them from the full chat
history.
