### **A Feature Guide to WilmerAI for Workflow Authors**

This document provides a high-level overview of the core features and capabilities available within the WilmerAI system.
It is intended to serve as a comprehensive guide for an LLM tasked with authoring workflows, bridging the gap between
the project overview and the detailed technical references for nodes and variables.

For each feature, this guide will explain its purpose, its primary use case, the key workflow nodes associated with it,
and reference any available in-depth documentation for further details.

---

## Core LLM Interaction and Advanced Templating

The most fundamental capability of WilmerAI is its ability to interact with Large Language Models. This is primarily
achieved through the **`Standard` node**, which assembles context, sends a request to a configured LLM endpoint, and
processes the response.

A key aspect of this feature is the powerful templating engine that allows for the creation of dynamic, context-aware
prompts. While simple variable substitution (`{my_variable}`) is supported by default, you can enable a full **Jinja2
templating engine** on a per-node basis by adding `"jinja2": true`. This unlocks advanced logic like loops and
conditionals directly within your prompt strings, which is especially useful for formatting the `{messages}` variable (
the entire conversation history).

* **Key Node**: `Standard`
* **Detailed Documentation**:
    * `A Comprehensive Guide to WilmerAI Workflow Nodes`
    * `Developer Guide: Workflow Node Jinja2 Support`

---

## Modular and Reusable Workflows (Nesting)

WilmerAI allows you to build complex processes by breaking them down into smaller, reusable components. This is achieved
by "nesting" workflows—running one workflow file as a single step inside another. A **Parent** workflow uses a *
*`CustomWorkflow` node** to call a self-contained **Child** workflow.

This architecture promotes reusability (e.g., creating a single `summarize.json` workflow and calling it from anywhere),
simplifies complex logic by breaking it into manageable parts, and enables the creation of high-level "orchestrator"
workflows. Data is passed from the parent to the child explicitly via the `scoped_variables` property, which the child
receives as `{agent#Input}` variables.

* **Key Node**: `CustomWorkflow`
* **Detailed Documentation**: `Feature Guide: Custom Nested Workflows`

---

## Conditional Logic and In-Workflow Routing

Workflows are not limited to a rigid, linear sequence of steps. WilmerAI supports dynamic, non-linear execution paths
through conditional logic. This allows a workflow to function as an intelligent agent that can make decisions and route
a task to the most appropriate tool based on the current context.

This is primarily accomplished using the **`ConditionalCustomWorkflow` node**, which acts as an "if/then" switch. It
evaluates a variable (often the output of a previous step) and executes a specific child workflow based on that value.
For more complex evaluations, the **`Conditional` node** can be used first to evaluate a logical expression (with `AND`/
`OR` operators) and return a simple `"TRUE"` or `"FALSE"` to drive the routing decision.

* **Key Nodes**: `ConditionalCustomWorkflow`, `Conditional`
* **Detailed Documentation**:
    * `Feature Guide: WilmerAI's In-Workflow Routing`
    * `In-Workflow Routing: The ConditionalCustomWorkflow Node`

---

## Stateful Conversation Memory

WilmerAI features a sophisticated, three-part memory system to provide long-term, stateful context for conversations.
This system is designed for performance by separating the slow process of writing memories from the fast process of
reading them.

The three components are:

1. **Long-Term Memory File**: Chronological, summarized chunks of the conversation.
2. **Rolling Chat Summary**: A single, continuously updated high-level summary of the entire discussion.
3. **Searchable Vector Memory**: A vector database containing structured memory objects (title, summary, entities) for
   efficient semantic search (RAG).

Memory "writer" nodes like **`QualityMemory`** run in the background to create and update memories, while fast "reader"
nodes like **`VectorMemorySearch`** or **`GetCurrentSummaryFromFile`** retrieve context to be used in a prompt.

* **Key Nodes**: `QualityMemory` (writer), `VectorMemorySearch` (reader), `GetCurrentSummaryFromFile` (reader),
  `RecentMemorySummarizerTool` (reader)
* **Detailed Documentation**:
    * `Feature Guide: WilmerAI's Memory System`
    * `WilmerAI Workflow Memory Node Catalog`

---

## Automated Conversation Timestamps

To provide LLMs with temporal awareness, WilmerAI can automatically inject timestamps into the conversation history.
When enabled on a `Standard` node, this system prepends a timestamp to each message's content before sending it to the
LLM.

The feature can be configured to use **absolute** timestamps (e.g., `(Saturday, 2025-09-20 16:30:05)`) or **relative**
ones (e.g., `[Sent 5 minutes ago]`). Additionally, the system provides the **`{time_context_summary}`** variable, which
gives a high-level natural language summary of the conversation's timeline (e.g., "This conversation started 2 hours
ago...").

* **Key Node**: `Standard` (with `addDiscussionIdTimestampsForLLM` flag)
* **Detailed Documentation**: `A Technical Guide to Conversation Timestamps`

---

## External Tool Integration

The workflow engine can be extended with custom tools and integrations to external services. This allows you to add
capabilities that are not native to the WilmerAI system.

Two primary methods for this are:

1. **Custom Python Scripts**: The **`PythonModule` node** allows you to execute an arbitrary local Python script and use
   its string output as the result of the node. This is the most flexible way to add custom logic or connect to other
   APIs.
2. **Offline Wikipedia Integration**: WilmerAI has a built-in integration with the `OfflineWikipediaTextApi` service. A
   family of **`OfflineWikiApi...` nodes** allows a workflow to perform a semantic search against a local Wikipedia
   database to retrieve factual articles for Retrieval-Augmented Generation (RAG).

* **Key Nodes**: `PythonModule`, `OfflineWikiApiBestFullArticle`, `OfflineWikiApiTopNFullArticles`, etc.
* **Detailed Documentation**:
    * `Feature Guide: WilmerAI's Offline Wikipedia Integration`
    * `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## Vision Capabilities

WilmerAI can process and understand images provided in a user's message. The **`ImageProcessor` node** takes any images
from the user's latest turn, sends them to a configured vision-capable LLM, and generates a detailed text description.

The aggregated text description is then made available as the node's output (`{agent#Output}`). This allows a
subsequent, text-only `Standard` node to use the description as context, effectively giving the entire workflow "sight."

* **Key Node**: `ImageProcessor`
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## In-Workflow Data and File Manipulation

For common data processing and file system tasks, WilmerAI includes several utility nodes. These nodes allow workflows
to read and write local files and perform basic data manipulation without needing an LLM call or an external Python
script.

* **File I/O**: The **`GetCustomFile`** node reads the contents of a text file, while the **`SaveCustomFile`** node
  writes string content to a file.
* **Data Processing**: The **`StringConcatenator`** node joins a list of strings with a specified delimiter, and the *
  *`ArithmeticProcessor`** node evaluates a simple mathematical expression.

* **Key Nodes**: `GetCustomFile`, `SaveCustomFile`, `StringConcatenator`, `ArithmeticProcessor`
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`

---

## Concurrency Control

For long-running, asynchronous tasks that should not be run simultaneously (like regenerating a conversation summary),
WilmerAI provides a locking mechanism. The **`WorkflowLock` node** can be used to acquire a named lock. If another
workflow execution reaches a node with the same lock ID, it will terminate immediately, thus preventing race conditions
and redundant processing. The lock is automatically released after 10 minutes or when the workflow that acquired it
completes.

* **Key Node**: `WorkflowLock`
* **Detailed Documentation**: `A Comprehensive Guide to WilmerAI Workflow Nodes`