## A Technical Guide to Authoring WilmerAI Workflows

This guide provides the complete, validated rules, structure, and component details for generating valid and effective
workflows for the WilmerAI system. It has been verified against the system's source code (`workflow_manager.py`,
`workflow_variable_manager.py`, and `workflow_processor.py`) to ensure total accuracy.

### Core Principle: The Workflow

A WilmerAI workflow is a **JSON file** that defines a sequence of operations called **"nodes"**. These nodes execute
sequentially from top to bottom. The string output of any node is automatically made available to all subsequent nodes,
allowing for the creation of complex, multi-step agentic behaviors.

-----

## Part 1: Workflow Structure & Variables

Workflows use a dictionary-based JSON format. This structure is strongly preferred as it allows for the use of reusable
custom variables.

#### Recommended Structure

The root of the JSON **must be an object**. This object should contain a required `nodes` key (a list of node objects)
and any number of other top-level keys that will serve as custom variables.

```json
{
  "persona": "You are a helpful and creative AI assistant.",
  "nodes": [
    {
      "title": "Gather Relevant Memories",
      "type": "VectorMemorySearch",
      "endpointName": "Creative-Fast-Endpoint"
    },
    {
      "title": "Respond to User",
      "type": "Standard",
      "systemPrompt": "{persona}\n\nRelevant memories:\n{agent1Output}",
      "endpointName": "Creative-Fast-Endpoint",
      "returnToUser": true
    }
  ]
}
```

* **Custom Variables**: As seen with `"persona"` and `"default_endpoint"`, any key-value pair defined at the root of the
  JSON object (except for `nodes`) is automatically registered as a reusable variable. These can be used in any valid *
  *content field** within a node.

* **`nodes` list**: This is a required list of node objects that will be executed in order.

For backward compatibility, a simple list of nodes is also supported, but the dictionary structure is the correct modern
format.

-----

## Part 2: The Data Flow System

Data is passed between nodes and between parent/child workflows using a precise system of `Output` and `Input`
variables.

#### `{agent#Output}`: Passing Data Between Nodes

When a node executes, its string result is automatically captured in a special output variable. The variable name is
based on the node's position (**1-indexed**) in the `nodes` list.

* The result of the **1st node** is stored in **`{agent1Output}`**.
* The result of the **2nd node** is stored in **`{agent2Output}`**.
* ...and so on.

Any subsequent node within the *same workflow* can use these output variables in its string properties.

#### `{agent#Input}`: Passing Data to Child Workflows

A child workflow (executed by a `CustomWorkflow` node) runs in an isolated context and **cannot** access its parent's
`{agent#Output}` variables. Data must be passed explicitly from the parent to the child using the `scoped_variables`
property.

* The parent workflow defines a list of values in `scoped_variables`.
* The child workflow receives these values in special `{agent#Input}` variables, numbered according to their order in
  the parent's `scoped_variables` list.

**Parent Workflow Example (`main.json`)**

```json
{
  "nodes": [
    {
      "title": "Get a block of text",
      "type": "GetCustomFile",
      "filepath": "D:\\data.txt"
    },
    {
      "title": "Call Summarizer",
      "type": "CustomWorkflow",
      "workflowName": "summarize.json",
      "scoped_variables": [
        "{agent1Output}"
      ]
    }
  ]
}
```

**Child Workflow Example (`summarize.json`)**

```json
[
  {
    "title": "Summarize the passed-in text",
    "type": "Standard",
    "prompt": "Please summarize the following text: {agent1Input}"
  }
]
```

-----

## Part 3: A Catalog of Node Types

This is a catalog of available node types, validated against the `WorkflowManager`'s `node_handlers` dictionary.

#### Core & Utility Nodes

* **`Standard`**: The most fundamental node. Makes a direct call to an LLM.
* **`PythonModule`**: Executes a custom Python script as long as it matches the required signature, and returns the
  string output from that script as the nodes output.
* **`GetCustomFile`**: Loads a `.txt` file from disk and places its content into the node's output.
* **`ImageProcessor`**: Generates a text description from an image provided by the user.

#### Workflow Orchestration Nodes

* **`CustomWorkflow`**: Executes another workflow file, allowing for modular logic.
* **`ConditionalCustomWorkflow`**: Runs a specific sub-workflow based on the value of a variable.
* **`WorkflowLock`**: Pauses execution if a named lock is active, preventing race conditions.

#### Memory System Nodes

* **`QualityMemory`**: The primary node for creating and updating long-term vector and file-based memories. It runs in
  the background and produces no direct output.
* **`VectorMemorySearch`**: Performs a semantic search against the vector memory database to retrieve relevant
  information (RAG).
* **`FullChatSummary`**: Retrieves the single "rolling summary" of the entire conversation.
* **`RecentMemorySummarizerTool`**: Retrieves a summary of the most recent memory chunks.
* **`ChatSummaryMemoryGatheringTool`**: Gathers memories related to the chat summary.
* **`GetCurrentSummaryFromFile`**: Loads the current chat summary directly from its file.
* **`WriteCurrentSummaryToFileAndReturnIt`**: Updates the summary file and outputs the new summary.
* **Other Memory Nodes**: `ConversationMemory`, `RecentMemory`, `chatSummarySummarizer`, `GetCurrentMemoryFromFile`.

#### Specialized Data & Search Nodes

* **`OfflineWikiApi...`**: A family of nodes for querying a local Wikipedia database (`...FullArticle`,
  `...BestFullArticle`, `...TopNFullArticles`, `...PartialArticle`).
* **`SlowButQualityRAG`**: A tool-based node for performing a specific RAG process.
* **`ConversationalKeywordSearchPerformerTool`**: Performs keyword search on conversations.
* **`MemoryKeywordSearchPerformerTool`**: Performs keyword search on memories.

-----

## Part 4: Complete Built-in Variable Reference

In addition to custom variables and data flow variables, the system provides a rich set of built-in variables that can
be used in any valid string field.

#### Variable Templating Engine

* **Standard Python Format**: **`{variable_name}`** is the default. The system uses Python's `str.format()` method.
* **Jinja2 Templating**: If a node config includes **`"jinja2": true`**, you can use Jinja2 syntax (e.g.,
  `{% for item in items %}`).

#### Date & Time Variables

* `{todays_date_pretty}`: e.g., "August 30, 2025"
* `{todays_date_iso}`: e.g., "2025-08-30"
* `{current_time_12h}`: e.g., "08:04 PM"
* `{current_time_24h}`: e.g., "20:04"
* `{current_month_full}`: e.g., "August"
* `{current_day_of_week}`: e.g., "Saturday"
* `{current_day_of_month}`: e.g., "30"

#### Conversation History Variables

The system provides variables for the last 1, 2, 3, 4, 5, 10, and 20 turns of the conversation.

* **Raw String Format**: `chat_user_prompt_last_one`, `chat_user_prompt_last_two`, etc.
* **LLM-Templated Format**: `templated_user_prompt_last_one`, `templated_user_prompt_last_two`, etc. (This format is
  pre-processed to match the specific chat template of the target LLM).
* `{chat_system_prompt}`: The system prompt sent from the front-end client.
* `{system_prompts_as_string}`: All system messages from the conversation history concatenated into a single string.
* `{messages}`: The entire conversation history as a raw list of dictionaries (e.g.,
  `[{'role': 'user', 'content': '...'}]`). **Note**: This is available for both standard and Jinja2 formatting, but it
  is most useful with Jinja2 for iterating over the conversation.

#### Memory & Context Variables

* `{time_context_summary}`: A natural language summary of the conversation's timeline (e.g., "The user started this
  conversation a few minutes ago").
* `{current_chat_summary}`: **⚠️ UNAVAILABLE VARIABLE:** The code review confirms that the helper function
  `generate_chat_summary_variables` that populates this is **not called** by the main variable generation logic. **Do
  not use `{current_chat_summary}`** as it will not be substituted. To get the summary, you must use a dedicated node
  like `GetCurrentSummaryFromFile`.

#### Special Placeholders (Context-Specific)

These are special keywords replaced within specific node types or sub-workflows. They do **not** use curly braces. Their
processing logic is not present in the core `WorkflowVariableManager` and is handled by specialized memory-related
workflows.

* `[TextChunk]`
* `[IMAGE_BLOCK]`
* `[Memory_file]`
* `[Full_Memory_file]`
* `[Chat_Summary]`
* `[LATEST_MEMORIES]`
* `[CHAT_SUMMARY]`

-----

## Part 5: ⚠️ Critical Limitations on Variable Usage

**This is the most important section.** The system's code confirms that variable substitution (`{...}`) is performed by
node handlers on specific fields, not by the core workflow engine. This creates a critical distinction between what can
and cannot be a variable. In general, variable usage is limited to systemprompt, prompt, and some input fields like
those found on custom workflows.

**The principle is: Configuration keys are static, content keys can be dynamic.**

#### ✅ Fields that SUPPORT variables (Content)

Below are the only fields that support variables. Any other fields on nodes will not replace variables within them

* `prompt`
* `systemPrompt`
* `promptToSearch` (and similar input fields on specialized nodes)
* `filepath` (in `GetCustomFile`, the handler specifically processes variables for this field)
* `scoped_variables` (in `CustomWorkflow` nodes, to pass the variables into the workflow being called)