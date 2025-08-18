## Quick Guide to Understanding Memories in WilmerAI

Memories in WilmerAI have gotten a major upgrade\! They are now more powerful and allow for much smarter and more
relevant context. Let's break down how they work now.

-----

### \#\# What are the memories?

Wilmer's memory system now has three key components that work together:

* **Long-Term Memory File (`<id>_memories.jsonl`)**: This is the classic memory file. It still takes your conversation,
  breaks it into chunks, and an LLM writes a summary of each chunk. Think of it as a detailed, chronological diary of
  your chat.
* **Rolling Chat Summary (`<id>_summary.jsonl`)**: This file takes the summarized chunks from the Long-Term Memory file
  and weaves them into a single, continuously updated story of your conversation. It gives the AI a high-level overview
  of everything that has happened so far.
* **Searchable Vector Memory (`<id>_vector_memory.db`)**: This is the exciting new part\! 🧠 It's a dedicated, smart
  database for your discussion. When a memory is created, it can be saved here with extra metadata like a **title,
  summary, entities, and key phrases**. This makes your memories highly searchable, allowing the AI to perform a "smart
  search" to find the *most relevant* pieces of information about a specific topic, rather than just looking at the last
  few things you said.

-----

### \#\# How do you use memories in a workflow?

The core idea is the same: you must have a **`[DiscussionId]`** tag in your chat to activate persistent memories. Once
activated, you can use specific nodes in your workflow to interact with the memory system.

The system is now split into "Creator" nodes (which do the heavy lifting of writing memories) and "Retriever" nodes (
which just read them).

#### **The Memory Creator**

* **`QualityMemory`**: This is the main node for **creating and updating** all your memory files. You place this in your
  workflow where you want the memory generation to happen (usually at the end, after a workflow lock). It's the engine
  that powers the whole system.

  *Example Config:*

  ```json
  {
    "id": "create_memories_node",
    "type": "QualityMemory",
    "name": "Create/Update Memories"
  }
  ```

#### **The Memory Retrievers (Readers)**

* **`RecentMemorySummarizerTool`**: This node quickly **reads** the last few chunks from your Long-Term Memory File.
  It's great for giving an AI general context of what just happened.

  *Example Config:*

  ```json
  {
    "id": "get_recent_memories_node",
    "type": "RecentMemorySummarizerTool",
    "name": "Get Recent Memories",
    "maxTurnsToPull": 0,
    "maxSummaryChunksFromFile": 3 // Pulls the last 3 memory chunks
  }
  ```

* **`FullChatSummary`**: This node **reads** the Rolling Chat Summary file. Use this to give the AI the complete "story
  so far."

  *Example Config:*

  ```json
  {
    "id": "get_full_summary_node",
    "type": "FullChatSummary",
    "name": "Get Full Chat Summary"
  }
  ```

* **`VectorMemorySearch`**: This is the new **smart search** node. It takes keywords and searches the Vector Memory
  database for the most relevant information. This is perfect for Retrieval-Augmented Generation (RAG), where you want
  the AI to look up specific facts from your conversation history before responding.

  *Example Config:*

  ```json
  {
    "id": "smart_search_node",
    "type": "VectorMemorySearch",
    "name": "Search for Specific Details",
    // Keywords must be separated by a semicolon (;)
    "input": "Project Stardust;mission parameters;Dr. Evelyn Reed"
  }
  ```

-----

### \#\# Why have "Creator" and "Reader" nodes?

This separation is all about **performance and keeping your chat fast**. Writing memories, especially the new searchable
ones, can take a few moments. By splitting the process, you can have a responsive AI that chats with you instantly while
another process works quietly in the background to keep the memories updated.

This is where **Workflow Locks** are key. Consider this workflow order:

1. **Read Memory** (`VectorMemorySearch` or `FullChatSummary`).
2. **AI Responds** (The AI uses the memory you just read).
3. **Workflow Lock** engages.
4. **Create Memory** (`QualityMemory` runs in the background).

When you send a prompt, the workflow instantly grabs existing memories (fast\!), gets a response to you from your main
AI (fast\!), and then locks. While you're reading the response, a secondary process can start working on the
`QualityMemory` node in the background to update everything based on what you just said.

If you send another message while the background process is still working, the workflow will simply stop at the lock,
but you'll still get a fast response from the AI based on the memories that were read *before* the lock. This means you
can have a seamless conversation without waiting for memory processing.

-----

### \#\# Configuring Your Memories: File vs. Vector

You now have a choice in how your memories are created. In your `_DiscussionId-MemoryFile-Workflow-Settings.json` file,
you'll find a new key setting:

* **`useVectorForQualityMemory`**: If this is `false` (the classic way), the `QualityMemory` node will only write to the
  Long-Term Memory file. If you set it to `true`, it will create the powerful, searchable Vector Memories instead\!

*Example `_DiscussionId-MemoryFile-Workflow-Settings.json`:*

```json
{
  // This is the master switch for the new memory system.
  // Set to true to create searchable vector memories.
  // Set to false to use the classic file-based memory system.
  "useVectorForQualityMemory": true,
  // ====================================================================
  // == Vector Memory Configuration (Only used if the above is true) ==
  // ====================================================================

  // For advanced users: specify a workflow to generate the structured JSON for a vector memory.
  "vectorMemoryWorkflowName": "my-vector-memory-workflow",
  // The LLM endpoint to use specifically for vector memory generation. Falls back to "endpointName".
  "vectorMemoryEndpointName": "gpt-4-turbo",
  // The preset for the specified endpoint. Falls back to "preset".
  "vectorMemoryPreset": "default_preset_for_json_output",
  // The max response size for the generated JSON. Falls back to "maxResponseSizeInTokens".
  "vectorMemoryMaxResponseSizeInTokens": 1024,
  // The target size in tokens for a chunk of conversation before it's processed.
  "vectorMemoryChunkEstimatedTokenSize": 1000,
  // The max number of new messages before forcing processing, even if token size isn't met.
  "vectorMemoryMaxMessagesBetweenChunks": 5,
  // How many of the most recent turns to ignore. This prevents summarizing an in-progress thought.
  "vectorMemoryLookBackTurns": 3,
  // ====================================================================
  // == File-based Memory Configuration (Only used if the switch is false) ==
  // ====================================================================

  // For advanced users: specify a workflow to generate the summary text for a file-based memory.
  "fileMemoryWorkflowName": "my-file-memory-workflow",
  // The system prompt used for the summarization LLM call when not using a workflow.
  "systemPrompt": "You are an expert summarizer. Your task is to extract key facts...",
  // The user prompt used for the summarization LLM call. [TextChunk] is replaced automatically.
  "prompt": "Please summarize the following conversation chunk: [TextChunk]",
  // The target size in tokens for a chunk of conversation before it's summarized.
  "chunkEstimatedTokenSize": 1000,
  // The max number of new messages before forcing a summarization, even if token size isn't met.
  "maxMessagesBetweenChunks": 5,
  // How many of the most recent turns to ignore for file-based memory generation.
  "lookbackStartTurn": 3,
  // ====================================================================
  // == General / Fallback LLM Settings                           ==
  // ====================================================================

  // The default LLM endpoint to use if a specific one (e.g., vectorMemoryEndpointName) isn't set.
  "endpointName": "default_endpoint",
  // The default preset to use.
  "preset": "default_preset",
  // The default max response size in tokens.
  "maxResponseSizeInTokens": 400
}
```

-----

### \#\# Cleaning Up and Regenerating Memories

Sometimes you might want to rebuild your memories from scratch. Maybe you changed the summarization prompts or edited a
bunch of old messages.

To do this, you need to **delete the memory files**. With the new system, there can be up to three:

1. `Public/<id>_memories.jsonl` (Long-Term Memory)
2. `Public/<id>_summary.jsonl` (Rolling Summary)
3. `Public/<id>_vector_memory.db` (The Searchable Vector Memory)

**Important**: If you delete the memory files, you should delete all of them for that discussion to avoid confusing the
system. The next time you run a workflow with a `QualityMemory` node, Wilmer will see the files are missing and
regenerate everything from your chat history.

The tip about consolidating memories still works, too\! If you feel too many small memories were created because of the
`maxMessagesBetweenChunks` limit, just delete the files. When they are regenerated, Wilmer will prioritize the
`chunkEstimatedTokenSize`, likely creating fewer, but larger and more comprehensive, memory chunks from your history.