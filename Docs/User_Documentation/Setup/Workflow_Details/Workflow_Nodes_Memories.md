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
    * Append a new summarized memory chunk to the long-term memory file (`<id>_memories.jsonl`).
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
  "input": "Project Stardust;mission parameters;Dr. Evelyn Reed",
  "limit": 5
}
```

#### **Field Rundown**

* **`title`**: (Optional) A descriptive name for the node.
* **`type`**: (Required) Must be `"VectorMemorySearch"`.
* **`input`**: (Required) A string of keywords to search for. Keywords **must** be separated by a semicolon (`;`).
  Supports variables.
* **`limit`**: (Optional) The maximum number of memory results to return. Defaults to `5`.

#### **Actions & Output**

* **Action**: This node **reads** from the vector database (`<id>_vector_memory.db`).
* **Output**: Returns a single string containing the text of the most relevant memories, separated by `\n\n---\n\n`. If
  no memories are found, it returns a message stating so.

-----

### RecentMemorySummarizerTool

The **`RecentMemorySummarizerTool`** is a fast **retriever** node that fetches the most recent memory chunks from the
long-term memory file (`_memories.jsonl`). It is ideal for giving an LLM a quick summary of recent events without
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

* **Action**: This node **reads** from the long-term memory file (`<id>_memories.jsonl`).
* **Output**: Returns a single string containing the text of the requested recent memories.

-----

### GetCurrentSummaryFromFile

The **`GetCurrentSummaryFromFile`** node is a simple and extremely fast **retriever**. Its only job is to read the
entire contents of the rolling chat summary file (`_summary.jsonl`) and return it as a string. It performs no checks and
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

* **Action**: This node **reads** from the rolling chat summary file (`<id>_summary.jsonl`).
* **Output**: Returns a single string containing the full text of the current chat summary.

-----

### FullChatSummary

The **`FullChatSummary`** is a combined **creator and retriever** node. By default, it first ensures the file-based
memories (`_memories.jsonl`) are up-to-date, then checks if the rolling summary (`_summary.jsonl`) is stale and updates
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
  `<id>_memories.jsonl`) and the rolling summary file (`<id>_summary.jsonl`). It always **reads** from the summary file.
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

* **Action**: This node **writes** to the long-term memory file (`<id>_memories.jsonl`) and then **reads** from it in
  the same step.
* **Output**: Returns a single string containing the text of the most recent memories.

-----

### ChatSummaryMemoryGatheringTool (Legacy)

The **`ChatSummaryMemoryGatheringTool`** is a specialized legacy **retriever**. Its purpose is to gather all new memory
chunks from the long-term memory file (`_memories.jsonl`) that have been created since the last rolling summary was
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

* **Action**: This node **reads** from both the long-term memory file (`<id>_memories.jsonl`) and the summary file (
  `<id>_summary.jsonl`) to determine which memories are new.
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