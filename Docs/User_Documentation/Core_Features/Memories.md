### **Feature Guide: WilmerAI's Memory System**

WilmerAI uses a multi-layered memory system for managing long-term conversational context. It is designed
to provide both chronological recall and relevant information retrieval by allowing its different memory components to
work in concert.

The system separates memory creation from retrieval to maintain response speed. To use persistent memory, the
`[DiscussionId]` tag must be included in a user or system message. It can be anywhere and
Wilmer will find it.

The discussion id names on-disk files, so it must be path-safe: an id containing `/`, `\`, or `:` (for example a
timestamp with colons) is rejected with a log warning and the request is treated as stateless: no memories are
read or written for it. Use ids made of letters, digits, dots, dashes, and underscores.

-----

## System Architecture: The Four Memory Components

WilmerAI's memory consists of four components. Each is stored in a separate file and linked by a unique discussion ID.

* **Long-Term Memory File (`<id>_memories.json`)**: This file stores chronological summaries of the conversation. The
  system periodically reviews the chat history, divides it into chunks, and uses an LLM to summarize each chunk. This
  forms the backbone of the conversation's timeline.
* **Rolling Chat Summary (`<id>_chat_summary.json`)**: This file contains a single, continuously updated summary of the
  entire conversation. It synthesizes the chunks from the Long-Term Memory File to provide a high-level overview.
* **Searchable Vector Memory (`vector_memory.db`, stored in the discussion's folder; a legacy `<id>_vector_memory.db`
  at the old `Public/` location keeps being used if present)**: A dedicated full-text search database for the discussion. When
  a memory is created, it can be stored here with structured metadata (**title, summary, entities, key phrases**) and
  indexed for full-text keyword search (SQLite FTS5 with BM25 ranking) to retrieve relevant information based on a query.
* **State Document (`state_document.md`)**: An optional, continuously updated markdown document holding the current,
  ground-truth state of the conversation's subject matter, a "what is true right now" snapshot. Where the other
  components record history, the state document records the present: when a fact changes, its entry is replaced. It is
  designed to be injected into every response rather than searched, and its structure (a user profile, roleplay world
  state, project status, etc.) is defined entirely by the prompts of a user-configured merge workflow. The file is
  plain, hand-editable markdown, updated by the vector memory pipeline when `useStateDocument` is enabled.

-----

## Workflow Nodes for Memory Interaction

The memory system is controlled via workflow nodes. These are separated into nodes that create memories (computationally
intensive) and nodes that retrieve them (fast).

### Memory Creators (Writers)

These nodes analyze chat history and write data to the memory files.

* **`QualityMemory`**: The primary node for creating and updating **vector memories**. When this node is run, it checks
  the conversation history and generates new, structured memories for the searchable vector database.
    * *Note: If `useVectorForQualityMemory` is set to `false` in the configuration, this node will fall back to
      creating **file-based** memories instead.*
  <!-- end list -->
  ```json
  {
    "id": "create_vector_memories_node",
    "type": "QualityMemory",
    "name": "Create/Update Vector Memories"
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

* **Read-and-Update Nodes**: Before reading, these nodes first trigger the **file-based** memory creation process to
  ensure the data is current. This can introduce latency but helps achieve the freshest chronological context.

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
  Retrieves recent memories, but first triggers the **file-based memory creation process** to ensure the long-term
  memory file is current. This update logic is independent of the vector memory system.

  ```json
  {
    "id": "update_and_get_recent_memories",
    "type": "RecentMemory",
    "name": "Update and Get Recent Memories"
  }
  ```

* **`GetCurrentMemoryFromFile`** (Pure/Fast Reader)
  Performs a direct read of the Long-Term Memory File (`_memories.json`) and returns all memory chunks
  joined into a single string. Use this when you need the full, raw contents of the memory file for
  processing or display without triggering any updates.

  ```json
  {
    "id": "get_all_memories_fast_node",
    "type": "GetCurrentMemoryFromFile",
    "customDelimiter": "\n\n---\n\n"
  }
  ```

* **`GetCurrentSummaryFromFile`** (Pure/Fast Reader)
  Performs a direct read of the Rolling Chat Summary file (`_chat_summary.json`).

  ```json
  {
    "id": "get_full_summary_fast_node",
    "type": "GetCurrentSummaryFromFile",
    "name": "Get Full Chat Summary (Fast)"
  }
  ```

* **`FullChatSummary`** (Read-and-Update Node)
  Reads the Rolling Chat Summary after ensuring that both the **file-based long-term memories** and the summary itself
  are updated.

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
    "input": "quarterly revenue;marketing strategy;client onboarding",
    "limit": 5
  }
  ```

  *Note: Search keywords must be separated by a semicolon (`;`). The query uses `OR` logic and is limited to a maximum
  of 60 keywords. Optional ranking fields (`bm25Weights`, `useRecencyScoring`, and `includeDates`) improve result
  quality for long-running conversations. The optional `useEntityExpansion` flag runs a second keyword pass seeded
  with entities found in the top results, bridging facts connected by an entity the query could not name (a search
  about "the user's sister" also surfaces facts stored under her name). See the node's documentation for details.*

* **`GetCurrentStateDocument`** (Pure/Fast Reader)
  Performs a direct read of the State Document (`state_document.md`) and returns its full text. Inject this into the
  system prompts of thinking and responder nodes so that core, always-relevant facts are present on every response
  without depending on a search.

  ```json
  {
    "id": "get_state_document_node",
    "type": "GetCurrentStateDocument",
    "name": "Get the Current State Document"
  }
  ```

-----

## Performance: Separating Reading from Writing

The separation of creator and reader nodes is for performance. Writing and summarizing memories is time-consuming. This
design allows a workflow to provide a response to the user immediately, while memory processing occurs in a background
process, often managed with **Workflow Locks**.

A typical high-performance flow is as follows:

1. **Read Memory:** A fast reader node (`VectorMemorySearch`, `GetCurrentSummaryFromFile`) pulls existing context.
2. **AI Responds:** The primary LLM generates a response using the context.
3. **Workflow Lock:** The workflow locks after delivering the response to the user.
4. **Create Memory:** A creator node (like `QualityMemory`) runs in a non-blocking background process to analyze the
   latest exchange and update memory files for the next turn.

This architecture allows for a responsive chat experience by not blocking the user response on memory processing.

-----

## Memory Generation Triggering

File-based memory generation is controlled by two thresholds that work together:

* **Token threshold** (`chunkEstimatedTokenSize`): Memory generates when new messages accumulate enough tokens to reach
  or exceed this value.
* **Message count threshold** (`maxMessagesBetweenChunks`): Memory generates when this many new messages have
  accumulated since the last generation.

In normal operation (when the memory file exists on disk), the system uses **whichever threshold is reached first**. For
example, if `chunkEstimatedTokenSize` is 1000 and `maxMessagesBetweenChunks` is 20, memories will generate either when
~1000 tokens of new messages accumulate or when 20 new messages are added, whichever happens first. The memory file does
not need to contain any chunks for both thresholds to be active; it just needs to exist. In a new conversation, the
file is automatically created on the first memory check (around message 3), so both thresholds are active from that
point on.

The `lookbackStartTurn` setting excludes the most recent N turns from consideration. This is useful when your frontend
sends command messages (like system instructions) in recent turns that should not be included in memories.

### Consolidation Workflow

If you want to regenerate all memories with different chunking (for example, fewer but larger chunks), you can:

1. Delete the memory file for the discussion.
2. Adjust `chunkEstimatedTokenSize` to a larger value.
3. Let the system regenerate memories from the full conversation history.

When the memory file does not exist on disk, the message count threshold is disabled and only the token threshold
applies. This consolidation mode allows the system to create appropriately sized chunks from the full history without
being limited by the per-message threshold. Once the file is created (which happens automatically on the first memory
check after deletion), subsequent messages will use the standard mode with both thresholds.

-----

## Configuration

Memory behavior is configured in the `_DiscussionId-MemoryFile-Workflow-Settings.json` file. This file contains settings
for both vector and file-based memory generation.

### The `useVectorForQualityMemory` Flag

This flag determines the **default behavior of the `QualityMemory` node**.

* If `true`, the `QualityMemory` node will create **vector memories**.
* If `false`, the `QualityMemory` node will create **file-based memories**.

This flag **does not disable the file-based memory system**. Nodes like `RecentMemory` and `FullChatSummary` will *
*always** trigger the creation of file-based memories when their update cycle is run, regardless of this setting. This
allows you to create vector memories with `QualityMemory` while simultaneously maintaining the file-based memory
timeline with other nodes in the same workflow.

*Example `_DiscussionId-MemoryFile-Workflow-Settings.json`:*

```json
{
  // Sets the default behavior for the QualityMemory node.
  "useVectorForQualityMemory": true,
  // ====================================================================
  // == Vector Memory Configuration
  // ====================================================================
  // Specify a workflow to generate the structured JSON for a vector memory.
  "vectorMemoryWorkflowName": "my-vector-memory-workflow",
  // The settings below are used if "vectorMemoryWorkflowName" is not set.
  "vectorMemoryEndpointName": "gpt-4-turbo",
  "vectorMemoryPreset": "default_preset_for_json_output",
  "vectorMemoryMaxResponseSizeInTokens": 1024,
  "vectorMemoryChunkEstimatedTokenSize": 1000,
  "vectorMemoryMaxMessagesBetweenChunks": 5,
  // When true, each memory's "topics" metadata is folded into the searchable
  // index as it is written, so keyword searches can find a memory by its
  // conversation-level topic (the campaign, project, or event a fact belongs
  // to) even when the memory text never restates it. Off by default, which
  // indexes exactly what was indexed historically.
  "vectorMemoryIndexTopics": true,
  // ====================================================================
  // == Embedding Configuration (vector memory path only, optional)
  // ====================================================================
  // When set, newly stored vector memories are also embedded via this
  // endpoint (an Endpoints config whose ApiType is openAIEmbeddings or
  // ollamaEmbeddings), enabling semantic/hybrid search on VectorMemorySearch.
  "embeddingEndpointName": "Embedding-Endpoint",
  // Each processed chunk also embeds up to this many older, not-yet-embedded
  // memories (a single memory pass may process several chunks), so an
  // existing database heals gradually. Set 0 to disable.
  "embeddingBackfillBatchSize": 20,
  // ====================================================================
  // == State Document Configuration (vector memory path only)
  // ====================================================================
  // When enabled, newly stored vector memories are also merged into the
  // discussion's state document by the named workflow.
  "useStateDocument": true,
  "stateDocumentWorkflowName": "my-state-document-workflow",
  // Reject merge outputs smaller than this fraction of the current document.
  // Set to 0 to disable the shrink guard.
  "stateDocumentMinRetentionRatio": 0.5,
  // ====================================================================
  // == File-based Memory Configuration
  // ====================================================================
  // Specify a workflow to generate the summary text for a file-based memory.
  "fileMemoryWorkflowName": "my-file-memory-workflow",
  // The prompts below are used if "fileMemoryWorkflowName" is not set.
  "systemPrompt": "You are an expert summarizer...",
  "prompt": "Please summarize the following: [TextChunk]",
  "chunkEstimatedTokenSize": 1000,
  "maxMessagesBetweenChunks": 5,
  // ====================================================================
  // == Shared Settings (apply to both vector and file-based paths)
  // ====================================================================
  "lookbackStartTurn": 3,
  // ====================================================================
  // == General / Fallback LLM Settings
  // ====================================================================
  // The default LLM endpoint to use if a specific one isn't set.
  "endpointName": "default_endpoint",
  "preset": "default_preset",
  "maxResponseSizeInTokens": 400
}
```

### Semantic Search with Embeddings

By default, memory search is keyword-based (FTS5 with BM25 ranking). Optionally, memories can also be embedded
(turned into vectors that capture meaning) so that `VectorMemorySearch` can match memories by concept even when no
words overlap (searchMode `"semantic"`, or `"hybrid"` to combine both, which is the recommended mode).

Requirements and behavior:

* **An embeddings endpoint**: an ordinary Endpoints config file whose ApiType is `openAIEmbeddings` (OpenAI,
  llama.cpp server with `--embedding`, most compatible servers) or `ollamaEmbeddings` (Ollama with an embedding
  model such as `nomic-embed-text`). No preset is needed.
* **Vectors are written by the memory pipeline**: when `embeddingEndpointName` is set in the discussion settings,
  each new vector memory is embedded as it is stored, and a small batch of older memories is backfilled with every
  processed chunk (a single memory pass may process several chunks). Existing databases gain the (purely additive)
  embedding table automatically; nothing about existing memories is modified.
* **Bulk backfill (optional)**: users with years of memories can embed the whole backlog at once with the
  standalone `Scripts/backfill_embeddings.py` script, pointing it directly at a `vector_memory.db`
  file. This is a convenience only; the lazy backfill reaches the same state over time.
* **Model switches are safe**: embeddings are stored per-model. Changing embedding models never destroys previous
  vectors: search simply uses the current model's vectors, un-embedded memories remain findable via keyword
  search, and switching back to a previous model reuses its stored vectors immediately.
* **Graceful degradation everywhere**: if the embeddings endpoint is down or unset, writes skip embedding (memories
  stay fully searchable by keyword) and semantic/hybrid searches fall back to keyword results. Embeddings are
  derived data, always recomputable from the memory text.

### The State Document

When `useStateDocument` is `true` and the vector memory path is active, every batch of newly stored vector memories is
also merged into `state_document.md` by the workflow named in `stateDocumentWorkflowName`. The merge workflow receives
the new facts as `{agent1Input}` and the current document as `{agent2Input}`, and its final output replaces the
document on disk. Safety guards reject empty or drastically shrunken merge outputs, and the previous version is always
kept as `state_document.md.bak`. Retrieval is done with the `GetCurrentStateDocument` node.

The document's sections are defined by the merge workflow's prompts, so the same mechanism supports an assistant
maintaining a profile of the user's life, a roleplay maintaining world state and characters, or any other "current
state" a persona needs to keep straight. See the memory nodes guide (`Setup/Workflow_Details/Workflow_Nodes_Memories.md`)
for full details, and the `_example_assistant_with_vector_memory` workflow folder for a working example.

-----

## Memory Condensation

Over long conversations, the Long-Term Memory File accumulates many individual chunks. Memory condensation
is an optional feature that automatically consolidates older chunks into fewer, denser summaries to keep
the file manageable.

When enabled, after new memories are written, the system checks whether enough new memories have
accumulated since the last condensation. If the threshold is met, the oldest batch of new memories is
sent to an LLM to be summarized into a single condensed memory. The condensed memory replaces the batch
in the file.

### When to Use Condensation

Condensation is useful for very long-running conversations where the memory file would otherwise grow
without limit. It reduces the amount of data the system reads on each pass and keeps the memory file
at a manageable size.

Condensation applies only to file-based memories. Vector memories are not affected.

### Configuration

Add the following fields to your `_DiscussionId-MemoryFile-Workflow-Settings.json` file:

```json
{
  "condenseMemories": true,
  "memoriesBeforeCondensation": 5,
  "memoryCondensationBuffer": 2,
  "condenseMemoriesSystemPrompt": "You are an expert at condensing information.",
  "condenseMemoriesPrompt": "Please condense the following memories into a single summary:\n\n[MemoriesToCondense]\n\nFor context, here are the memories that came before:\n[Memories_Before_Memories_to_Condense]",
  "condenseMemoriesEndpointName": "my-endpoint",
  "condenseMemoriesPreset": "my-preset",
  "condenseMemoriesMaxResponseSizeInTokens": 800
}
```

| Field | Required | Description |
|:------|:---------|:------------|
| `condenseMemories` | Yes | Set to `true` to enable condensation. Defaults to `false`. |
| `memoriesBeforeCondensation` | Yes (if enabled) | Number of new memories that must accumulate before condensation runs. |
| `memoryCondensationBuffer` | No | Number of most recent memories to exclude from condensation (kept for granular context). Defaults to `0`. |
| `condenseMemoriesSystemPrompt` | No | System prompt for the condensation LLM call. |
| `condenseMemoriesPrompt` | No | User prompt for the condensation call. Supports `[MemoriesToCondense]` and `[Memories_Before_Memories_to_Condense]` placeholders. |
| `condenseMemoriesEndpointName` | No | Endpoint override for condensation. Falls back to `endpointName`. |
| `condenseMemoriesPreset` | No | Preset override for condensation. Falls back to `preset`. |
| `condenseMemoriesMaxResponseSizeInTokens` | No | Max token override for condensation. Falls back to `maxResponseSizeInTokens`. |

-----

## Maintenance: Regenerating Memories

To regenerate all memories for a discussion, **delete the corresponding memory files** from your discussion directory:

1. `<id>_memories.json` (Long-Term Memory)
2. `<id>_chat_summary.json` (Rolling Summary)
3. `vector_memory.db` (Searchable Vector Memory; older discussions may instead have a legacy
   `<id>_vector_memory.db` under `Public/`)

If per-user encryption is active (i.e., an `Authorization: Bearer <key>` header is being sent), these files are
located under a hash-based subdirectory within the discussion directory (e.g.,
`{discussionDirectory}/{api_key_hash}/{discussion_id}/`). Note that encrypted files are not human-readable; they
appear as binary data. See the **Per-User Encryption** guide for details.

**Important:** To prevent state conflicts, delete all memory files for a given discussion ID. When a workflow with a
memory creator node is next run, the system will detect the missing files and regenerate them from the full chat
history.