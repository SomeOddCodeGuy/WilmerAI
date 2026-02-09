## A Technical Guide to Authoring WilmerAI Workflows

This guide provides the complete, validated rules, structure, and component details for generating valid and effective
workflows for the WilmerAI system. It has been verified against the system's source code (`workflow_manager.py`,
`workflow_variable_manager.py`, and `workflow_processor.py`) to ensure total accuracy.

### Core Principle: The Workflow

A WilmerAI workflow is a **JSON file** that defines a sequence of operations called **"nodes"**. These nodes execute
sequentially from top to bottom. The string output of any node is automatically made available to all subsequent nodes,
allowing for the creation of complex, multi-step agentic behaviors.

### Workflow Location

Workflows are stored in `Public/Configs/Workflows/` and organized into subfolders:

* **User Folders** (e.g., `Workflows/chris/`): The default location for a user's workflows. The folder name matches the
  username.
* **`_shared/` Folder**: A special folder for shared workflows that can be selected via the API model field. Folders
  within `_shared/` (containing a `_DefaultWorkflow.json` file) are listed by the `/v1/models` and `/api/tags`
  endpoints, allowing front-end applications to select them via the model dropdown. The
  `workflowConfigsSubDirectoryOverride` user config setting can also reference subfolders within `_shared/`.

```
Public/Configs/Workflows/
├── _shared/
│   ├── openwebui-coding/           # Listed by models endpoint as folder name
│   │   └── _DefaultWorkflow.json   # Workflow loaded when folder is selected
│   ├── openwebui-general/
│   │   └── _DefaultWorkflow.json
│   └── openwebui-task/
│       └── _DefaultWorkflow.json
├── chris/                          # Default user folder
│   └── ...
```

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

* **Custom Variables**: As seen with `"persona"`, any key-value pair defined at the root of the JSON object (except for
  `nodes`) is automatically registered as a reusable variable. These can be used in any valid **content field** within a
  node.
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
      "workflowName": "summarize",
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
* **`GetCustomFile`**: Loads a `.txt` file from disk and places its content into the node's output. Its `filepath` field
  supports variables, including `{Discussion_Id}` and `{YYYY_MM_DD}` for dynamic, per-conversation or date-based paths.
* **`SaveCustomFile`**: Writes string content to a local text file. Its `filepath` and `content` fields support
  variables, including `{Discussion_Id}` and `{YYYY_MM_DD}` for dynamic paths. The node's output is a success or error
  message.
* **`ImageProcessor`**: Generates a text description from an image provided by the user.
* **`StaticResponse`**: Returns a hardcoded string from its `content` field. Can act as a responder node and supports
  streaming.

#### Data Manipulation Nodes

* **`StringConcatenator`**: Joins a list of strings with a specified delimiter and returns the result.
* **`ArithmeticProcessor`**: Evaluates a simple mathematical expression (e.g., `{agent1Output} * 1.07`) and returns the
  result.
* **`Conditional`**: Evaluates a logical expression (with `AND`/`OR` operators) and returns `"TRUE"` or `"FALSE"`.
* **`JsonExtractor`**: Extracts a specific field from a JSON string. Automatically handles markdown code block wrappers.
* **`TagTextExtractor`**: Extracts content from XML/HTML-style tags (e.g., `<answer>...</answer>`) within a text string.

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

It is important to note that the only user defined variables that exist are the constants, which can be added to the top
of the workflow, above the Nodes array. It is not possible for a user to create new variables with their own unique
names. If the user decides that they want a dynamically assigned variable called `{last_user_who_spoke}`, which is not a
defined variable within the Wilmer system- that will not work. At best, they could assign it as a constant.

#### Variable Templating Engine

* **Standard Python Format**: **`{variable_name}`** is the default. The system uses Python's `str.format()` method.
* **Jinja2 Templating**: If a node config includes **`"jinja2": true`**, you can use Jinja2 syntax (e.g.,
  `{% for item in items %}`).

#### Date & Time Variables

* `{todays_date_pretty}`: e.g., "September 13, 2025"
* `{todays_date_iso}`: e.g., "2025-09-13"
* `{current_time_12h}`: e.g., "04:30 PM"
* `{current_time_24h}`: e.g., "16:30"
* `{current_month_full}`: e.g., "September"
* `{current_day_of_week}`: e.g., "Saturday"
* `{current_day_of_month}`: e.g., "13"

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
and cannot be a variable.

**The principle is: Configuration keys are static, content keys can be dynamic.**

#### ✅ Fields that SUPPORT variables (Content)

Below are the only fields that support variables. Any other fields on nodes will not replace variables within them.

* `prompt`
* `systemPrompt`
* `content` (e.g., in the `SaveCustomFile` node)
* `promptToSearch` (and similar input fields on specialized nodes)
* `filepath` (in `GetCustomFile` and `SaveCustomFile`, the handlers specifically process variables for this field)
* `scoped_variables` (in `CustomWorkflow` nodes, to pass the variables into the workflow being called)

#### Important note about nodes that support `returnToUser`

The `returnToUser` boolean is special, and more disruptive than it may appear. Wilmer has a concept of responding
nodes and non-responding nodes. Responding nodes are the only nodes that respect the 'streaming' flag send from the
front-end, and will always return their output directly to the user. Most nodes could be a responder.

What determines if a node is a responder is generally that the node is the very last in the main workflow. So workflows
that generate child workflows via custom workflow nodes- the last node in a child node is not guaranteed to be a
responder. For example, consider the below workflow:

* Node 1: Analyze user context (determine what the user wants)
* Node 2: Generate keywords to search wikipedia
* Node 3: Custom workflow: calls the "search_wikipedia" workflow, passing in the keywords from Node 2
    * Node 3-1: Search wikipedia
    * Node 3-2: Summarize Wikipedia results
* Node 4: Takes the output of Node 3, and continues the conversation with the user.

In the above example- Node 3-2, the final node of `search_wikipedia` is NOT a responder. Why? Because even though
it is the last node in that workflow, that workflow was not the last node in the main, calling, workflow. The
real responding node is Node 4 of the main workflow.

Alternatively- if Node 4 did not exist, Node 3-2 would automatically be the responding node, since it is the last
node that will run in the main workflow, even if it exists in a child workflow.

All of this occurs automatically, without the `returnToUser` flag set. That flag can be left at false, or removed
all-together, and the response of the last node will still occur.

The `returnToUser` flag is specifically designed to OVERRIDE this default behavior. If you were to list Node 3-2,
the last node of the child workflow `search_wikipedia`, as `returnToUser`, that node's output would be streamed to
the user. Because every request to Wilmer can only have a single node respond to the user, this means Node 4 will
not send its response to the user; that work will simply be lost.

**In the vast majority of cases, you do not need to include returnToUser on any node, and do not need to set it to
true. That field was specifically created for a very niche use-case where the user would want to have work continue
after a response was sent, such as the lengthy process of generating memories, while a workflow lock node allows the
user to continue talking to the LLM in the meantime. As such- do not use this unless you are CERTAIN you need it.**