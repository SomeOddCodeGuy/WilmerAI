### **Developer Guide: WilmerAI Memory System**

This guide provides a deep dive into the architecture and implementation of the conversational memory features within
WilmerAI. It has been updated to reflect the powerful workflow-based memory generation system, the specifics of the
vector search implementation, and the complete data schemas as verified by the current codebase.

-----

## 1\. Core Concepts & Architecture

WilmerAI's memory system is a sophisticated, multi-layered feature set implemented through specialized nodes within the
workflow engine. This design allows for different types of memory operations—creation, retrieval, and summarization—to
be strategically placed within workflows.

#### **Key Architectural Principles:**

* **Activation via `discussionId`**: All persistent, stateful memory features are tied to a `discussionId`. Its presence
  activates persistent storage mechanisms; its absence causes memory nodes to fall back to stateless, in-memory
  operations using the current chat history.

* **Separation of Concerns: Creators vs. Retrievers**: The system is fundamentally split into two categories of
  operations, handled by distinct services:

    * **Memory Creation (Write)**: These are computationally expensive processes that analyze conversation history,
      generate new summarized memories, and write them to persistent storage. This is the exclusive responsibility of
      the **`SlowButQualityRAGTool`**. This tool can generate memories either by executing a full sub-workflow for
      complex logic or by making a direct LLM call.
    * **Memory Retrieval (Read)**: These are inexpensive, fast operations that read from storage or the current chat
      history to provide context for an LLM. This is the primary responsibility of the **`MemoryService`**.

* **Node-Based Implementation**: Each memory operation is defined as a specific `node_type` in a workflow's JSON
  configuration. This gives developers explicit control over when to perform expensive write operations versus cheap
  read operations.

* **Centralized Routing and Registration**:

    * The **`MemoryNodeHandler`** acts as a central router, directing requests for different memory `node_type`s to the
      appropriate service (`MemoryService` or `SlowButQualityRAGTool`).
    * The **`WorkflowManager`** acts as the system registrar where new memory `node_type`s must be mapped to the
      `MemoryNodeHandler`.

* **Persistent Storage**: When a `discussionId` is active, the system maintains state in a user-specific directory using
  a set of discussion-specific files:

    1. **Memory File (`<id>_memories.jsonl`)**: Stores discrete, summarized chunks of the conversation for file-based
       memory. Each chunk is saved with a hash of the last message it's based on, creating a traceable, append-only
       ledger.
    2. **Chat Summary File (`<id>_summary.jsonl`)**: Stores a single, continuously updated "rolling summary" of the
       entire conversation. It's linked via a hash to the last memory chunk from the memory file that it incorporated.
    3. **Vector Memory Database (`<id>_vector_memory.db`)**: A **discussion-specific SQLite database** created on-demand
       for each `discussionId`. It uses the FTS5 extension for powerful, weighted, full-text search across two main
       tables:
        * **`memories` table**: Stores the ground-truth data. For vector memories, the `memory_text` column holds the *
          *LLM-generated summary**, not the raw conversation chunk. It also stores the full `metadata_json`.
        * **`memories_fts` table**: A virtual table that indexes the metadata for fast searching. The indexed columns
          are `title`, `summary`, `entities`, `key_phrases`, and the original `memory_text`. Search relevance is
          determined by the **`bm25`** ranking function.
    4. **Vector Memory Tracker (`vector_memory_tracker` table)**: Located inside the `<id>_vector_memory.db`, this table
       stores the hash of the last message processed for vector memory creation. This crucial feature prevents the
       system from re-processing the same conversation history on subsequent runs.

-----

## 2\. Anatomy of Memory Node Types

Understanding the creator/retriever pattern clarifies the role of each node type.

#### **Memory Creation & Persistence (Write)**

These nodes perform the "heavy lifting" of creating and saving memories. They are powered by **`SlowButQualityRAGTool`
**.

* **`QualityMemory`**: This is the primary **memory creator** node. It's designed to be run periodically in a workflow
  to keep persistent memory up-to-date.
    * **Process Flow**:
        1. The node triggers `SlowButQualityRAGTool.handle_discussion_id_flow`.
        2. The tool checks if new memories are needed by comparing the current conversation history against the last
           processed point (using either the file-based memory ledger hash or the vector memory tracker hash).
        3. Based on the `useVectorForQualityMemory` flag in the central discussion config, the tool proceeds to generate
           either vector or file-based memories.
        4. For the chosen memory type, the tool generates memories using one of two methods, based on its configuration:
            * **A) Workflow-Based Generation (Recommended)** ✨: If the config specifies a `fileMemoryWorkflowName` or
              `vectorMemoryWorkflowName`, the tool executes that sub-workflow.
                * **File-Based Workflow**: Passes the raw text chunk, recent memories, full memories, and the current
                  chat summary as `scoped_inputs`. The workflow's final output **must be a single summarized text block
                  **.
                * **Vector-Based Workflow**: Passes only the raw text chunk as a `scoped_input`. The workflow's final
                  output **must be a JSON string representing a single object or an array of objects**.
            * **B) Direct LLM Call (Legacy)**: If a workflow name is not provided, the system falls back to a direct LLM
              call using prompts defined in the config.

#### **Memory Retrieval (Read)**

These nodes perform fast, inexpensive "read" operations and are powered by **`MemoryService`**.

* **`RecentMemory` & `RecentMemorySummarizerTool`**: The primary **file-based memory retriever**.

    * **With `discussionId` (Stateful)**: Calls `MemoryService.get_recent_memories`, which reads the last `N` memory
      chunks from `<id>_memories.jsonl`.
    * **Without `discussionId` (Stateless)**: Falls back to an in-memory operation, grabbing the last `N` turns from the
      current `messages` list.

* **`VectorMemorySearch`**: The primary **RAG search node**.

    * **Purpose**: Performs a highly relevant, keyword-based search against the discussion-specific vector memory
      database.
    * **Process Flow**: This node takes a string of keywords. The keywords **must be separated by semicolons (`;`)**.
      The `MemoryService` calls `vector_db_utils.search_memories_by_keyword`, which sanitizes each keyword, truncates
      the list to a maximum of 60, and constructs a `MATCH` query using **`OR` logic**. It executes the query against
      the SQLite FTS5 index, returning the most relevant memory summaries ranked by the `bm25` algorithm.

* **`FullChatSummary`**: Retrieves the holistic, rolling summary of the conversation from `<id>_summary.jsonl`.

-----

## 3\. Critical Files for Development

To modify or extend the memory system, you will primarily work with these five files:

1. **`Middleware/workflows/tools/slow_but_quality_rag_tool.py`**: The heart of **memory creation**. Modify this file to
   change how memories are generated, including the logic for choosing between vector/file and workflow/LLM-call
   methods.
2. **`Middleware/services/memory_service.py`**: The core of **memory retrieval**. Modify this file to change how
   memories are read from `.jsonl` files or retrieved from the vector database.
3. **`Middleware/utilities/vector_db_utils.py`**: The **database abstraction layer**. This contains all logic for
   interacting with the discussion-specific SQLite databases, including table creation, data insertion, FTS5 search
   query construction, and term sanitization.
4. **`Middleware/workflows/handlers/impl/memory_node_handler.py`**: The **central router**. You must update this file's
   `handle` method to route any new `node_type` you create to the correct service or tool.
5. **`Middleware/workflows/managers/workflow_manager.py`**: The **system registrar**. You must register your new
   `node_type` in the `node_handlers` dictionary within this manager's constructor. This manager is also responsible for
   executing the memory generation sub-workflows.

-----

## 4\. How to Add a New Memory Feature

The system is designed for extension. Below are two common scenarios.

#### **Example A: Creating a New Memory *Retriever***

**Scenario**: Create a new retriever node called `FirstFiveMemories` that always gets the *first* five memories of a
conversation to provide context on its origin.

1. **Implement the Logic (in the Retriever)**: Open `Middleware/services/memory_service.py` and add the new method.

   ```python
   # In MemoryService class
   def get_first_five_memories(self, discussion_id: str) -> str:
       filepath = get_discussion_memory_file_path(discussion_id)
       hashed_chunks = read_chunks_with_hashes(filepath)
       if not hashed_chunks:
           return "No memories have been generated yet"
       
       chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)
       return '--ChunkBreak--'.join(chunks[:5])
   ```

2. **Create and Route the Node Type (in the Router)**: Open `Middleware/workflows/handlers/impl/memory_node_handler.py`
   and add the new type to the `handle` method's router logic.

   ```python
   # In MemoryNodeHandler.handle()
   # ...
   elif node_type == "FirstFiveMemories":
       return self.memory_service.get_first_five_memories(context.discussion_id)
   # ...
   ```

3. **Register the Node Type (in the Registrar)**: Open `Middleware/workflows/managers/workflow_manager.py` and add the
   new `node_type` to the `node_handlers` dictionary in the constructor.

   ```python
   # In WorkflowManager.__init__()
   self.node_handlers = {
       # ...
       "FirstFiveMemories": memory_node_handler,
       # ...
   }
   ```

#### **Example B: Using a Workflow for Memory *Creation***

**Scenario**: Use a multi-step workflow to generate higher-quality vector-based memories. The first step will identify
key topics, and the second step will write a structured JSON memory object for each topic.

1. **Configure the Memory System**: In your discussion ID config file, set `useVectorForQualityMemory` to `true` and
   specify the name of the workflow to run.

   ```json
   {
     "useVectorForQualityMemory": true,
     "vectorMemoryWorkflowName": "my-vector-memory-workflow",
     "fileMemoryWorkflowName": "my-file-memory-workflow"
   }
   ```

2. **Understand the Injected Context**: The system automatically passes context into your workflow as `scoped_inputs`,
   which are then available in the workflow prompts as `{agent1Input}`, `{agent2Input}`, etc. The order is critical.

    * For a **file-based** memory workflow:
        * `{agent1Input}`: The raw text chunk to be summarized.
        * `{agent2Input}`: The most recent memory chunks.
        * `{agent3Input}`: The full history of all memory chunks.
        * `{agent4Input}`: The current rolling chat summary.
    * For a **vector-based** memory workflow:
        * `{agent1Input}`: The raw text chunk to be processed.

3. **Create the Memory Workflow**: Create a new workflow file (e.g.,
   `Public/Configs/Workflows/my-vector-memory-workflow.json`). The final output of this workflow (from the last node
   where `returnToUser` is `true`) will become the new memory.

   *Workflow Definition (`.../my-vector-memory-workflow.json`):*

   ```json
   [
     {
       "id": "agent1",
       "type": "Standard",
       "prompt": "You are a topic analyzer. Read the following conversation chunk and list the 3 most important topics discussed. Chunk: {agent1Input}",
       "returnToUser": false
     },
     {
       "id": "agent2",
       "type": "Standard",
       "prompt": "You are a summarizer. The original conversation chunk is: {agent1Input}. The topics identified were: {agent1Output}. Generate a JSON array of memory objects, with one object for each topic. Each object must have 'title', 'summary', 'entities', and 'key_phrases' fields.",
       "returnToUser": true
     }
   ]
   ```

   *Final Output from Workflow:* For a vector memory workflow, this **must be a JSON string** representing a single
   object or an array of objects. For example:

   ```json
   [
     {
       "title": "Topic A Summary",
       "summary": "A detailed summary about the first topic discussed in the chunk.",
       "entities": ["Entity1", "Entity2"],
       "key_phrases": ["key phrase 1", "key phrase 2"]
     },
     {
       "title": "Topic B Summary",
       "summary": "A detailed summary about the second topic discussed in the chunk.",
       "entities": ["Entity3"],
       "key_phrases": ["key phrase 3"]
     }
   ]
   ```