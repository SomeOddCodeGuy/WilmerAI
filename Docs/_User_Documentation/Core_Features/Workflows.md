### **Feature Guide: The WilmerAI Workflow Engine**

WilmerAI's core logic is driven by a node-based workflow engine. A workflow is a JSON file that defines a sequence of
operations, called nodes, that are executed in order to process a user's prompt. This system allows for the creation of
complex, multi-step behaviors by chaining together different Large Language Models (LLMs), custom tools, and memory
systems.

This guide provides a straightforward overview of how to construct and understand WilmerAI workflows.

-----

## The Core Components of a Workflow

A workflow's functionality is defined by three primary concepts: the workflow file itself, the nodes within it, and the
system for passing data between those nodes.

### 1\. The Workflow File

A workflow is defined as a JSON object. This structure contains a required `nodes` key, which holds the list of
operations to be executed. Any other top-level keys in the object are automatically registered as custom variables that
can be used throughout the workflow.

**Example Workflow Structure (`MyWorkflow.json`):**

```json
{
  "persona": "You are a helpful and creative AI assistant.",
  "nodes": [
    {
      "title": "First Node: Gather Data",
      "type": "VectorMemorySearch",
      "endpointName": "Creative-Fast-Endpoint"
    },
    {
      "title": "Second Node: Respond to User",
      "type": "Standard",
      "systemPrompt": "{persona}",
      "prompt": "Based on this information: {agent1Output}\n\nPlease answer the user's question.",
      "endpointName": "Creative-Fast-Endpoint",
      "returnToUser": true
    }
  ]
}
```

In this example, `persona` is a custom variable.

### 2\. Nodes

A **node** is a single JSON object within the `nodes` list that represents one step in the process. Each node has a
`type` that determines its function, such as calling an LLM (`Standard`), running a Python script (`PythonModule`), or
executing another workflow (`CustomWorkflow`).

Key properties for a node include:

* **`title`**: A descriptive name for the node.
* **`type`**: The functional type of the node, which determines what it does.
* **`endpointName`**: Specifies which LLM backend to use if the node needs to make a model call.
* **`returnToUser`**: A boolean (`true`/`false`). Only one node in a workflow can be designated as the **responder** by
  setting this to `true`. Its output is what gets sent back to the user.

### 3\. Data Flow Between Nodes

The engine provides a simple mechanism for passing data between nodes. The string output of any node is automatically
captured in a variable named `{agent#Output}`, where `#` corresponds to the node's position (1-indexed) in the `nodes`
list.

* The output of the **1st node** is available as **`{agent1Output}`**.
* The output of the **2nd node** is available as **`{agent2Output}`**.
* And so on.

Any subsequent node can use these variables in its configuration to build upon the results of previous steps. In the
example above, the second node uses `{agent1Output}` in its `prompt` to incorporate the data retrieved by the first
node.

-----

## The Variable System

Workflows have access to a variable system that allows for dynamic content. These variables can be used in specific text
fields within a node, such as `prompt`, `systemPrompt`, and `filepath`.

* **Custom Variables**: As shown previously, any key-value pair defined at the root of the workflow JSON object becomes
  a reusable variable (e.g., `{persona}`).

* **Node Output Variables**: The `{agent#Output}` variables that pass data sequentially between nodes.

* **Built-in System Variables**: The system provides a set of pre-populated variables for accessing contextual
  information. Key examples include:

    * **Date & Time**: `{todays_date_pretty}` (e.g., "September 1, 2025"), `{current_time_24h}` (e.g., "18:41").
    * **Conversation History**: Variables for accessing recent turns, such as `{chat_user_prompt_last_one}` or
      `{templated_user_prompt_last_ten}`.
    * **Full Conversation**: The `{messages}` variable provides the entire conversation history as a list of objects,
      which is particularly useful when combined with Jinja2 templating for complex logic.

* **Jinja2 Templating**: For more advanced conditional logic or loops within a prompt, you can enable the Jinja2 engine
  by adding `"jinja2": true` to a node's configuration.

-----

## A Catalog of Node Types

The workflow engine supports a variety of node types, each handled by a dedicated class. Below is a summary of the
available node categories and some key examples.

#### **Core & Utility Nodes**

* **`Standard`**: The most common type; makes a direct call to an LLM.
* **`PythonModule`**: Executes a custom Python script and returns its string output.
* **`GetCustomFile`**: Reads the content of a local text file.
* **`ImageProcessor`**: Generates a text description for an image supplied by the user.

-----

#### **Workflow Orchestration Nodes**

* **`CustomWorkflow`**: Executes another, separate workflow file, allowing for modular and reusable logic.
* **`ConditionalCustomWorkflow`**: Runs one of several sub-workflows based on the value of a variable.

-----

#### **Memory System Nodes**

This category contains nodes for creating, retrieving, and managing conversation memories.

**Memory Creators**

* **`QualityMemory`**: The primary and **only recommended node for creating memories**. It analyzes recent conversation
  history and, if thresholds are met, generates and saves new memories to storage (either vector DB or `.jsonl` file).
  This node produces **no direct output** (`{agent#Output}` is empty) and is designed to run as a background task,
  typically at the end of a workflow, to avoid delaying the user's response.
* **`RecentMemory`**: A dual-function node that first blocks execution to create memories and then retrieves
  them. It is **not recommended for use** due to its inefficient, blocking behavior.

**Memory Retrievers**

* **`VectorMemorySearch`**: The primary tool for Retrieval-Augmented Generation (RAG). It performs a relevance-based
  search against the vector memory database. It requires a string of keywords in its `input` field, **separated by a
  semicolon (`;`)**. It returns an aggregated string of the most relevant memory summaries. Requires an active
  `discussionId`.
* **`RecentMemorySummarizerTool`**: The primary retriever for file-based memories (`.jsonl`). It fetches the most recent
  memory chunks. It can operate in a stateless mode (pulling from recent chat history) if no `discussionId` is active.
* **`FullChatSummary`**: Retrieves the "rolling summary" of the entire conversation. By default, it first triggers the
  `QualityMemory` creation process, which can cause significant delays. Setting the property `"isManualConfig": true`
  disables this behavior, making it a fast, read-only operation.
* **`GetCurrentSummaryFromFile`**: A simple and fast "dumb reader." Its only function is to read the contents of the
  summary file directly, without performing any staleness checks or updates.

**Low-Level Memory Tools**

* **`chatSummarySummarizer`**: A low-level node for iteratively updating the rolling chat summary. It processes new
  memories in batches and uses the special placeholders `[CHAT_SUMMARY]` and `[LATEST_MEMORIES]` in its prompts to
  manage the update loop.

-----

#### **Specialized & Search Nodes**

* **`OfflineWikiApi...`**: A set of nodes for querying a local Wikipedia database.
* **`SlowButQualityRAG`**: A specialized tool for a high-quality Retrieval-Augmented Generation process.

-----

## Putting It All Together: A Practical Example

The following workflow demonstrates how these components work together. It defines a persona, uses one node to retrieve
relevant facts from memory, and a second node to synthesize those facts into a response for the user.

```json
{
  "persona": "You are a helpful AI assistant who always uses retrieved facts to inform your answers.",
  "nodes": [
    {
      "title": "Gather Relevant Memories",
      "type": "VectorMemorySearch",
      "input": "{chat_user_prompt_last_one}",
      "limit": 3
    },
    {
      "title": "Respond to User Using Memories",
      "type": "Standard",
      "systemPrompt": "{persona}",
      "prompt": "Based on the following relevant information:\n\n---\n{agent1Output}\n---\n\nPlease answer the user's most recent question.",
      "endpointName": "Ollama-Endpoint-Default",
      "returnToUser": true
    },
    {
      "title": "(In Background) Update memories with the latest turn",
      "type": "QualityMemory"
    }
  ]
}
```

1. A custom variable `persona` is defined.
2. The first node (`VectorMemorySearch`) runs a search using the user's last prompt as input. Its output (the retrieved
   memories) is stored in the `{agent1Output}` variable.
3. The second node (`Standard`) runs. It is the **responder** (`"returnToUser": true`). It uses both the `{persona}`
   variable and the `{agent1Output}` variable to construct a final prompt for the LLM. The LLM's response is then sent
   to the user.
4. The third node (`QualityMemory`) runs last. It has no output and does not delay the response to the user. It analyzes
   the conversation that just occurred and creates a new memory chunk if necessary.