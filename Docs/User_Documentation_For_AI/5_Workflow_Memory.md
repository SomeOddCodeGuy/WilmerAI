# WilmerAI Memory System Reference

## Memory System

WilmerAI has a three-part memory system tied to a `discussionId` (conversation identifier). Without a `discussionId`,
memory nodes either fall back to stateless mode or return empty results.

**Providing a discussionId:** Include `[DiscussionId]my-unique-id[/DiscussionId]` anywhere in a user or system
message. WilmerAI strips the tag before processing. The ID links all memory files for that conversation.

### The Three Memory Stores

1. **Long-Term Memory File** (`<id>_memories.json`): Chronological summarized chunks of conversation. Each chunk covers
   a range of messages. Created by `QualityMemory` when enough new messages accumulate.

2. **Rolling Chat Summary** (`<id>_chat_summary.json`): A single continuously-updated high-level summary of the entire
   conversation. Updated by `FullChatSummary` or `chatSummarySummarizer`.

3. **Vector Memory Database** (`<id>_vector_memory.db`): Structured memory objects (title, summary, entities) stored in
   a searchable database. Queried via full-text keyword search (SQLite FTS5 with BM25 ranking). Created by `QualityMemory`
   when `useVectorForQualityMemory` is enabled in the discussion's memory settings.

### Writer vs. Reader Nodes

- **Writers** create/update memories. They are slow (involve LLM calls) and typically run after the response is sent.
- **Readers** retrieve memories. They are fast and used inline to inject context into prompts.

### Memory Configuration

Memory behavior is configured per-discussion in a settings file
(`_DiscussionId-MemoryFile-Workflow-Settings.json`) that specifies the endpoint, preset, chunk sizes, and whether to
use vector or file-based memory. See 6_Configuration_Reference.md for the full settings file schema.

### Running Multiple Memory Systems Together

Vector memories, file-based memories, rolling chat summary, and the ContextCompactor are all independent and
can run simultaneously:

- **`useVectorForQualityMemory: true`** makes `QualityMemory` write to vector DB. File-based memory still
  works via `FullChatSummary`, `RecentMemory`, or other update-capable nodes.
- **ContextCompactor** is completely separate from the memory system. It has its own settings file and
  summarizes raw conversation messages directly (not memory chunks). See 6_Configuration_Reference.md.
- **Rolling Chat Summary** is updated by `chatSummarySummarizer` or `FullChatSummary` from file-based
  memory chunks, independently of vector memory.

**Example: Workflow using all four systems**

```json
{
  "persona": "You are an assistant with comprehensive memory.",
  "nodes": [
    {
      "title": "Search Vector Memory",
      "type": "VectorMemorySearch",
      "input": "{chat_user_prompt_last_one}",
      "limit": 5
    },
    {
      "title": "Get Chat Summary",
      "type": "GetCurrentSummaryFromFile"
    },
    {
      "title": "Compact Context",
      "type": "ContextCompactor"
    },
    {
      "title": "Extract Old Context",
      "type": "TagTextExtractor",
      "tagToExtractFrom": "{agent3Output}",
      "fieldToExtract": "context_compactor_old"
    },
    {
      "title": "Extract Oldest Context",
      "type": "TagTextExtractor",
      "tagToExtractFrom": "{agent3Output}",
      "fieldToExtract": "context_compactor_oldest"
    },
    {
      "title": "Respond to User",
      "type": "Standard",
      "endpointName": "Main-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "{persona}\n\nBroad conversation history:\n{agent2Output}\n\nOldest context:\n{agent5Output}\n\nRecent context:\n{agent4Output}\n\nRelevant memories:\n{agent1Output}",
      "prompt": "",
      "lastMessagesToSendInsteadOfPrompt": 10,
      "maxResponseSizeInTokens": 4000
    },
    {
      "title": "Lock for Background Work",
      "type": "WorkflowLock",
      "workflowLockId": "MemoryGenerationLock"
    },
    {
      "title": "Update Memories",
      "type": "QualityMemory"
    }
  ]
}
```

This workflow: reads vector memory (node 1) + chat summary (node 2) + context compactor (nodes 3-5) ->
responds (node 6, auto-responder as the last Standard node before lock/memory) -> locks (node 7) ->
writes new memories in background (node 8). Requires both the memory settings file and the context
compactor settings file to be configured.

---

## Memory Nodes

### QualityMemory (Writer)

The primary memory creator. Analyzes recent conversation and generates new memory chunks in the background. Produces
no output.

```json
{ "type": "QualityMemory" }
```

Behavior depends on `useVectorForQualityMemory` in discussion settings -- writes to vector DB or memory file.

### VectorMemorySearch (Reader)

Searches the vector memory database by keywords. Returns matched memories joined by `\n\n---\n\n`.

| Property | Type | Description |
|---|---|---|
| `input` | String | Keywords separated by semicolons (`;`). **[var]** |
| `limit` | Int | Max results. Default: 5. |

### RecentMemorySummarizerTool (Reader)

Retrieves the most recent memory chunks from the memory file. Fast, no search logic.

| Property | Type | Description |
|---|---|---|
| `maxSummaryChunksFromFile` | Int | Number of recent chunks to retrieve (stateful mode). |
| `maxTurnsToPull` | Int | Recent turns to pull (stateless fallback). |
| `customDelimiter` | String | Separator between chunks. Default: `"--ChunkBreak--"`. |
| `lookbackStart` | Int | Turns to skip from end before pulling. Default: 0. |

### GetCurrentSummaryFromFile (Reader)

Reads the rolling chat summary file directly. No updates, no checks. Extremely fast.

```json
{ "type": "GetCurrentSummaryFromFile" }
```

### GetCurrentMemoryFromFile (Reader)

Reads all memory chunks from the memory file, joined by a delimiter.

| Property | Type | Description |
|---|---|---|
| `customDelimiter` | String | Separator. Default: `"--ChunkBreak--"`. |

### FullChatSummary (Reader/Writer)

By default, updates memories and summary before returning the summary. Set `"isManualConfig": true` to skip updates
and just read (fast mode).

| Property | Type | Description |
|---|---|---|
| `isManualConfig` | Bool | If true, read-only. Default: false. |

### WriteCurrentSummaryToFileAndReturnIt (Writer)

Writes a provided summary string to the chat summary file and returns it. Typically used after `chatSummarySummarizer`
to persist the generated summary.

| Property | Type | Description |
|---|---|---|
| `input` | String | The summary text to write. **[var]** Required. Typically set to `{agent#Output}` of a preceding `chatSummarySummarizer` node. |

```json
{
  "title": "Save Updated Summary",
  "type": "WriteCurrentSummaryToFileAndReturnIt",
  "input": "{agent2Output}"
}
```

### chatSummarySummarizer (Writer)

Low-level node that generates an updated rolling summary from existing summary + new memory chunks. Uses two special
placeholders in its `systemPrompt` and `prompt` fields (both placeholders can appear in either field):
- `[CHAT_SUMMARY]` -- replaced with the current rolling summary
- `[LATEST_MEMORIES]` -- replaced with new memory chunks to integrate

| Property | Type | Description |
|---|---|---|
| `minMemoriesPerSummary` | Int | Min new memories to trigger update. Default: 3. |
| `loopIfMemoriesExceed` | Int | Batch size for processing. Default: 3. |
| `systemPrompt` | String | Summarization instructions. Can contain `[CHAT_SUMMARY]` and/or `[LATEST_MEMORIES]`. |
| `prompt` | String | Summarization prompt. Can contain `[CHAT_SUMMARY]` and/or `[LATEST_MEMORIES]`. |
| `endpointName` | String | LLM endpoint. **[limited var]** |
| `preset` | String | Generation preset. **[limited var]** |

### Legacy Nodes (not recommended for new workflows)

- **RecentMemory**: Combines memory creation + retrieval in one blocking step. Use `QualityMemory` + `RecentMemorySummarizerTool` instead.
- **ChatSummaryMemoryGatheringTool**: Gathers unsummarized memory chunks. Property: `maxTurnsToPull` (int).
- **ConversationMemory**: Runs a hardcoded internal memory workflow. Inflexible.

### Memory Condensation

Optional feature that consolidates older file-based memories into fewer, denser summaries. Configured in the discussion
memory settings file:

| Field | Description |
|---|---|
| `condenseMemories` | Bool. Enable condensation. |
| `memoriesBeforeCondensation` | Int. How many new memories trigger a condensation pass. |
| `memoryCondensationBuffer` | Int. Most recent memories to keep granular (excluded from condensation). |
| `condenseMemoriesEndpointName` | Optional endpoint override. |
| `condenseMemoriesPreset` | Optional preset override. |
| `condenseMemoriesSystemPrompt` | Custom system prompt for condensation LLM. |
| `condenseMemoriesPrompt` | Custom prompt. Placeholders: `[MemoriesToCondense]`, `[Memories_Before_Memories_to_Condense]`. |
| `condensationLockTimeoutSeconds` | Float. Bounded wait for the per-discussion memory lock before skipping this round (retries next qualifying turn). Default: 600. Set to 0 or negative to wait indefinitely. |
