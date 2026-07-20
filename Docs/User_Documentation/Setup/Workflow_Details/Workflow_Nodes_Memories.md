## A Comprehensive Guide to WilmerAI Workflow Memory Specific Nodes

This document provides a comprehensive catalog of memory-related nodes for use within the WilmerAI workflow system. Each
entry includes a high-level overview, a complete JSON example with all available fields, and a brief description of each
field and the node's function.

-----

### QualityMemory

The **`QualityMemory`** node is the primary **creator** node for persistent memory. It analyzes the recent conversation
and, if enough new content exists, generates and saves a new memory chunk. It produces no direct output, as its sole
purpose is to write to memory in the background. Its behavior (creating a vector memory vs. a file-based memory) is
controlled by the discussion's configuration settings.

#### **Complete JSON Example**

```json
{
  "title": "Update Memories with Latest Turn",
  "type": "QualityMemory"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node used in logging.
* **`type`**: (Required) Must be `"QualityMemory"`.

#### **Actions & Output**

* **Action**: This node **writes** to memory. Depending on the `useVectorForQualityMemory` flag in the discussion's
  configuration, it will either:
    * Append a new structured memory to the vector database (`<id>_vector_memory.db`).
    * Append a new summarized memory chunk to the long-term memory file (`<id>_memories.json`).
* **Output**: This node produces **no output**. Its `{agent#Output}` variable will be empty.

-----

### VectorMemorySearch

The **`VectorMemorySearch`** node is the primary **retriever** for Retrieval-Augmented Generation (RAG). It performs a
relevance-based keyword search against the discussion's vector memory database (`_vector_memory.db`) to find specific
facts or details from the conversation's history. This node requires an active `discussionId` to function.

#### **Complete JSON Example**

```json
{
  "title": "Search for Relevant Facts",
  "type": "VectorMemorySearch",
  "input": "quarterly revenue;marketing strategy;client onboarding",
  "limit": 5,
  "bm25Weights": [3.0, 2.0, 2.0, 2.0, 0.5],
  "useRecencyScoring": true,
  "includeDates": true
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"VectorMemorySearch"`.
* **`input`**: (Required) A string of keywords to search for. Keywords **must** be separated by a semicolon (`;`).
  Supports variables.
* **`limit`**: (Optional) The maximum number of memory results to return. Defaults to `5`.
* **`bm25Weights`**: (Optional) A list of exactly five numbers weighting BM25 matches per FTS column, in order:
  title, summary, entities, key_phrases, memory text. Omitting it preserves the historical equal weighting.
  `[3.0, 2.0, 2.0, 2.0, 0.5]` is a good starting point that favors curated metadata over incidental body matches.
* **`useRecencyScoring`**: (Optional) Defaults to `false`. When `true`, ranks are multiplied by a time-decay boost so
  newer memories outrank stale ones of similar relevance. Recommended for years-long conversations.
* **`includeDates`**: (Optional) Defaults to `false`. When `true`, each result is prefixed with its creation date
  (e.g. `[2024-03-15]`) so the LLM can arbitrate between contradictory facts from different eras.
* **`searchMode`**: (Optional) Defaults to `"keyword"` (the historical BM25 search). `"semantic"` ranks memories by
  embedding similarity, matching meaning even with zero vocabulary overlap; `"hybrid"` runs both keyword and semantic
  search and merges them with Reciprocal Rank Fusion. Both require `embeddingEndpointName`, and both degrade
  gracefully to keyword search when the embeddings endpoint is missing or unreachable.
* **`semanticQuery`**: (Optional) Raw text to embed as the semantic query. Supports variables. Defaults to the
  keyword string with semicolons replaced by spaces.
* **`embeddingEndpointName`**: (Optional) An Endpoints config whose ApiType is an embeddings type
  (`openAIEmbeddings` / `ollamaEmbeddings`). Required for semantic and hybrid modes. Memories are only searchable
  semantically once they have embeddings; see the embeddings notes in the Core Features memory guide for how
  embeddings are written and backfilled.
* **`useEntityExpansion`**: (Optional) Defaults to `false`. When `true`, entities named in the metadata of the top
  results (minus any that were already query terms) become the query for a second keyword search pass (a one-hop
  lookup of everything stored about the entities the first pass surfaced), and a portion of the result slots
  (roughly a third) is reserved for memories only that second pass found. This bridges facts linked by an entity the query
  could not name: "what does the user's sister do?" first finds the memory naming the sister as Sarah, and the
  second pass then finds Sarah's job even though no query keyword appears in it. The expansion pass is pure
  keyword/BM25, works in every `searchMode`, and requires no embeddings endpoint. Expansion-only hits are appended
  after the base results.

#### **Actions & Output**

* **Action**: This node **reads** from the vector database (`<id>_vector_memory.db`).
* **Output**: Returns a single string containing the text of the most relevant memories, separated by `\n\n---\n\n`. If
  no memories are found, it returns a message stating so.

-----

### GetCurrentStateDocument

The **`GetCurrentStateDocument`** node is a fast **retriever** that reads the discussion's state document
(`state_document.md`) and returns its full text. The state document is a single, continuously updated markdown
document holding the current, ground-truth state of the conversation's subject matter: a "what is true right now"
snapshot, as opposed to the historical records kept by the other memory components. It is intended to be injected
into every response rather than searched. This node requires an active `discussionId`.

See "The State Document" section below for how the document is created and configured.

#### **Complete JSON Example**

```json
{
  "title": "Load the current state document",
  "type": "GetCurrentStateDocument"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"GetCurrentStateDocument"`.

#### **Actions & Output**

* **Action**: This node **reads** from the state document file (`state_document.md`) in the discussion folder.
* **Output**: Returns a single string containing the full document text. If no `discussionId` is available or no
  document exists yet, returns `"No state document has been created yet"`.

-----

## The State Document

The state document is an optional memory layer maintained by the vector memory pipeline. When enabled, every time the
`QualityMemory` node stores new vector memories for a chunk of conversation, the newly extracted facts are also merged
into a single markdown document via a user-defined sub-workflow. The merge workflow receives two scoped inputs:

* `{agent1Input}`: The new facts, as a bullet-point list.
* `{agent2Input}`: The current state document text (empty on the first run).

The final output of the merge workflow **replaces** the document on disk. The document's structure (its sections and
what belongs in them) is defined entirely by the prompts of the merge workflow, so the same mechanism serves very
different use cases: an assistant persona can maintain a profile of the user's life, while a roleplay can maintain
world state, characters, and active quests.

Because the merge is performed by an LLM, several safety guards protect the document:

* An empty or whitespace-only merge output is rejected and the existing document is kept.
* An output that shrinks the document below the configured retention ratio is rejected (see
  `stateDocumentMinRetentionRatio` below). The guard only applies once the document exceeds 500 characters, so small
  early-conversation documents can settle freely.
* The previous version is always saved to `state_document.md.bak` before an overwrite, providing a one-step undo.
* A failed merge never affects vector memory storage, which has already completed by the time the merge runs.

The document lives in the discussion folder as plain, hand-editable markdown. When per-user encryption is active
(API key present), it is encrypted at rest like the other discussion files.

### Configuration Fields

These fields are added to the `_DiscussionId-MemoryFile-Workflow-Settings.json` file:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `useStateDocument` | bool | `false` | Master toggle. Only takes effect on the vector memory path (`useVectorForQualityMemory` must be `true`). |
| `stateDocumentWorkflowName` | str | (required if enabled) | The name of the workflow that merges new facts into the document. |
| `stateDocumentMinRetentionRatio` | float | `0.5` | The merged output must be at least this fraction of the current document's length or it is rejected. Set to `0` to disable the shrink guard. |

### Example Configuration

```json
{
  "useVectorForQualityMemory": true,
  "vectorMemoryWorkflowName": "Memory_Vector_Workflow",
  "useStateDocument": true,
  "stateDocumentWorkflowName": "State_Document_Workflow",
  "stateDocumentMinRetentionRatio": 0.5
}
```

A complete working example, including the merge workflow with an assistant-oriented section template and notes on
adapting it for roleplay, can be found in the `_example_assistant_with_vector_memory` workflow folder
(`State_Document_Workflow.json`).

-----

### RecentMemorySummarizerTool

The **`RecentMemorySummarizerTool`** is a fast **retriever** node that fetches the most recent memory chunks from the
long-term memory file (`_memories.json`). It is ideal for giving an LLM a quick summary of recent events without
performing a complex search. It can also operate in a stateless mode if no `discussionId` is present.

#### **Complete JSON Example**

```json
{
  "title": "Get a summary of the last 3 major events",
  "type": "RecentMemorySummarizerTool",
  "maxSummaryChunksFromFile": 3,
  "maxTurnsToPull": 5,
  "customDelimiter": "\n\n---\n\n",
  "lookbackStart": 0
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"RecentMemorySummarizerTool"`.
* **`maxSummaryChunksFromFile`**: (Required) In stateful mode (with `discussionId`), the number of recent memory chunks
  to retrieve from the file.
* **`maxTurnsToPull`**: (Required) In stateless mode (no `discussionId`), the number of recent conversation turns to
  pull from the chat history.
* **`customDelimiter`**: (Optional) A string used to separate the retrieved memory chunks. Defaults to
  `"--ChunkBreak--"`.
* **`lookbackStart`**: (Optional) The number of turns to skip from the end of the conversation before pulling content.
  Defaults to `0`.

#### **Actions & Output**

* **Action**: This node **reads** from the long-term memory file (`<id>_memories.json`).
* **Output**: Returns a single string containing the text of the requested recent memories.

-----

### GetCurrentSummaryFromFile

The **`GetCurrentSummaryFromFile`** node is a simple and extremely fast **retriever**. Its only job is to read the
entire contents of the rolling chat summary file (`_chat_summary.json`) and return it as a string. It performs no checks and
triggers no updates.

#### **Complete JSON Example**

```json
{
  "title": "Quickly grab the current conversation summary",
  "type": "GetCurrentSummaryFromFile"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"GetCurrentSummaryFromFile"`.

#### **Actions & Output**

* **Action**: This node **reads** from the rolling chat summary file (`<id>_chat_summary.json`).
* **Output**: Returns a single string containing the full text of the current chat summary.

-----

### FullChatSummary

The **`FullChatSummary`** is a combined **creator and retriever** node. By default, it first ensures the file-based
memories (`_memories.json`) are up-to-date, then checks if the rolling summary (`_chat_summary.json`) is stale and updates
it if needed, and finally returns the summary's content. This process can be slow. Setting `isManualConfig` to `true`
disables the creation/update logic, turning it into a fast "read-only" retriever.

#### **Complete JSON Example**

```json
{
  "title": "Update and Get Full Chat Summary",
  "type": "FullChatSummary",
  "isManualConfig": false
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"FullChatSummary"`.
* **`isManualConfig`**: (Optional) If `true`, disables the slow update logic and makes the node a fast, direct reader.
  Defaults to `false`.

#### **Actions & Output**

* **Action**: When `isManualConfig` is `false`, this node can **write** to both the long-term memory file (
  `<id>_memories.json`) and the rolling summary file (`<id>_chat_summary.json`). It always **reads** from the summary file.
* **Output**: Returns a single string containing the full text of the chat summary.

-----

### chatSummarySummarizer

The **`chatSummarySummarizer`** is a low-level **creator** node that generates an updated rolling chat summary. It is
designed to take an existing summary and a batch of new memory chunks, and use an LLM to integrate them into a new,
cohesive summary. It uses two special placeholders, `[CHAT_SUMMARY]` and `[LATEST_MEMORIES]`, in its prompts.

#### **Complete JSON Example**

```json
{
  "title": "Update the Rolling Conversation Summary",
  "type": "chatSummarySummarizer",
  "minMemoriesPerSummary": 2,
  "loopIfMemoriesExceed": 5,
  "systemPrompt": "You are a summarization AI. Your task is to seamlessly integrate new conversation memories into the existing summary.",
  "prompt": "EXISTING SUMMARY:\n[CHAT_SUMMARY]\n\nNEW MEMORIES TO INTEGRATE:\n[LATEST_MEMORIES]\n\nPRODUCE THE NEW, UPDATED SUMMARY:",
  "endpointName": "Text-Processing-Endpoint",
  "preset": "Summarizer_Preset"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"chatSummarySummarizer"`.
* **`minMemoriesPerSummary`**: (Optional) The minimum number of new memories required to trigger an update. Defaults to
  `3`.
* **`loopIfMemoriesExceed`**: (Optional) The batch size for processing new memories in a loop. Defaults to `3`.
* **`systemPrompt` / `prompt`**: (Required) Prompts for the summarization LLM. Must contain the `[CHAT_SUMMARY]` and
  `[LATEST_MEMORIES]` placeholders.
* **`endpointName`**: (Optional) The LLM endpoint to use for summarization. **Supports LIMITED variables: only `{agent#Input}` and static workflow variables, NOT `{agent#Output}`.**
* **`preset`**: (Optional) The generation preset to use. **Supports LIMITED variables like endpointName.**

#### **Actions & Output**

* **Action**: This node **generates** the text for a new summary. It does not write to a file itself.
* **Output**: Returns a single string containing the newly generated summary text.

-----

## Memory Condensation

Over long conversations, the file-based memory system generates many individual memory chunks. Memory condensation is
an optional feature that automatically consolidates older memories into fewer, denser summaries. When enabled, after
new memories are created, the system checks whether enough new memories have accumulated and, if so, sends the oldest
batch to an LLM to be condensed into a single summary.

This feature only applies to file-based memories (not vector memories). It is configured in the
`_DiscussionId-MemoryFile-Workflow-Settings.json` file.

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `condenseMemories` | bool | `false` | Set to `true` to enable automatic memory condensation. |
| `memoriesBeforeCondensation` | int | (required if enabled) | The number of new memories (N) that must accumulate before a condensation pass runs. |
| `memoryCondensationBuffer` | int | `0` | The number of most recent memories (X) to exclude from condensation. These "buffer" memories are kept as-is so that the most recent context remains granular. |
| `condenseMemoriesSystemPrompt` | str | built-in default | A custom system prompt for the condensation LLM call. |
| `condenseMemoriesPrompt` | str | built-in default | A custom user prompt for the condensation LLM call. Supports two placeholders: `[MemoriesToCondense]` (replaced with the memories being condensed) and `[Memories_Before_Memories_to_Condense]` (replaced with the 3 memories immediately preceding the condensed batch, for narrative context). |
| `condenseMemoriesEndpointName` | str | uses `endpointName` | An optional endpoint override for the condensation LLM call. If not set, the main memory endpoint is used. |
| `condenseMemoriesPreset` | str | uses `preset` | An optional preset override for the condensation LLM call. |
| `condenseMemoriesMaxResponseSizeInTokens` | int | uses `maxResponseSizeInTokens` | An optional max response token override for the condensation LLM call. |

### How It Works

1. After new memories are generated by the `QualityMemory` node (or any file-based memory creation path), the system
   checks if `condenseMemories` is `true`.
2. It counts how many new memories have been created since the last condensation.
3. If the count meets or exceeds `memoriesBeforeCondensation + memoryCondensationBuffer`, the oldest
   `memoriesBeforeCondensation` memories from the new batch are sent to an LLM.
4. The 3 memories immediately before the condensed batch are also provided to the LLM (via the
   `[Memories_Before_Memories_to_Condense]` placeholder) so it can write the condensed summary as a continuation
   of the existing narrative.
5. The LLM produces a single condensed summary that replaces the original batch in the memory file.
6. The remaining buffer memories are left untouched.

### Example Configuration

```json
{
  "endpointName": "Memory-Generation-Endpoint",
  "preset": "Memory-Generation-Preset",
  "maxResponseSizeInTokens": 500,
  "chunkEstimatedTokenSize": 1000,
  "maxMessagesBetweenChunks": 15,
  "lookbackStartTurn": 5,
  "condenseMemories": true,
  "memoriesBeforeCondensation": 10,
  "memoryCondensationBuffer": 3
}
```

In this example, after every memory generation pass, the system checks if at least 13 (10 + 3) new memories exist
since the last condensation. If so, the oldest 10 are condensed into 1, and the 3 most recent are preserved as-is.

### Tracking

The condensation state is tracked in a separate file (`{discussion_id}_condensation_tracker.json`). This file is
managed automatically. If you delete it, the system will treat all memories as new and may condense from the beginning
on the next pass.

-----

### GetCurrentMemoryFromFile

The **`GetCurrentMemoryFromFile`** node is a simple **retriever** that reads all current memory chunks from the
discussion's long-term memory file (`_memories.json`) and returns them joined together as a single string. It performs
no updates or searches; it returns the full contents of the file. The chunks are joined using a configurable
delimiter. This node requires an active `discussionId` to function; without one it returns a fallback message.

#### **Complete JSON Example**

```json
{
  "title": "Load all memory chunks from file",
  "type": "GetCurrentMemoryFromFile",
  "customDelimiter": "\n\n---\n\n"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"GetCurrentMemoryFromFile"`.
* **`customDelimiter`**: (Optional) A string used to join the retrieved memory chunks. Defaults to `"--ChunkBreak--"`.

#### **Actions & Output**

* **Action**: This node **reads** from the long-term memory file (`<id>_memories.json`).
* **Output**: Returns a single string containing all memory chunks joined by the configured delimiter. If no
  `discussionId` is available, returns `"There are not yet any memories"`.

-----

### RecentMemory (Legacy)

The **`RecentMemory`** node is a legacy, dual-function node that combines **creation and retrieval**. It first triggers
the slow, blocking process of creating new file-based memories and then immediately retrieves the most recent ones. This
node is inefficient and **not recommended** for new workflows. Use `QualityMemory` and `RecentMemorySummarizerTool`
separately instead.

#### **Complete JSON Example**

```json
{
  "title": "Update and Get Recent Memories",
  "type": "RecentMemory"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"RecentMemory"`.

#### **Actions & Output**

* **Action**: This node **writes** to the long-term memory file (`<id>_memories.json`) and then **reads** from it in
  the same step.
* **Output**: Returns a single string containing the text of the most recent memories.

-----

### ChatSummaryMemoryGatheringTool (Legacy)

The **`ChatSummaryMemoryGatheringTool`** is a specialized legacy **retriever**. Its purpose is to gather all new memory
chunks from the long-term memory file (`_memories.json`) that have been created since the last rolling summary was
generated. It's intended to be the first step in a manual summary update workflow.

#### **Complete JSON Example**

```json
{
  "title": "Gather all new memory chunks since last summary",
  "type": "ChatSummaryMemoryGatheringTool",
  "maxTurnsToPull": 20
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"ChatSummaryMemoryGatheringTool"`.
* **`maxTurnsToPull`**: (Required) The number of recent turns to pull if running in stateless mode (no `discussionId`).

#### **Actions & Output**

* **Action**: This node **reads** from both the long-term memory file (`<id>_memories.json`) and the summary file (
  `<id>_chat_summary.json`) to determine which memories are new.
* **Output**: Returns a single string containing the text of all new, unsummarized memory chunks. Returns an empty
  string if no new memories exist.

-----

### ConversationMemory (Legacy)

The **`ConversationMemory`** node is a legacy, dual-function node that runs a hardcoded internal sub-workflow for memory
**creation and retrieval**. It is inflexible, inefficient, and **not recommended** for new workflows.

#### **Complete JSON Example**

```json
{
  "title": "Run legacy conversation memory process",
  "type": "ConversationMemory"
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"ConversationMemory"`.

#### **Actions & Output**

* **Action**: This node performs both **write** and **read** operations on memory files as part of its internal,
  non-configurable process.
* **Output**: Returns a string containing generated memories.