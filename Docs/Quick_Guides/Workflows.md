## Quick Guide to Understanding Workflows in WilmerAI

Workflows are the most powerful and complex part of Wilmer to configure. There's [suspicious link removed], so this
guide will keep things straightforward and focus on the practical basics.

-----

### Workflow Structure

Workflows are JSON files made up of "nodes" that run from top to bottom. The first node runs, then the second, and so
on.

The system now uses a more powerful dictionary-based format that lets you define variables at the top level.

**New Format (Recommended)**

```json
{
  "variables": {
    "shared_endpoint": "OpenWebUI-NoRouting-Single-Model-Endpoint",
    "persona": "You are a helpful and creative AI assistant."
  },
  "nodes": [
    {
      "title": "Gather Relevant Memories",
      "type": "VectorMemorySearch",
      "endpointName": "{workflow.shared_endpoint}"
    },
    {
      "title": "Respond to User",
      "type": "Standard",
      "systemPrompt": "{workflow.persona}\n\nHere are some relevant memories from our past conversations:\n[\n{agent1Output}\n]",
      "endpointName": "{workflow.shared_endpoint}",
      "preset": "Conversational_Preset",
      "returnToUser": true
    }
  ]
}
```

Here, we've defined `shared_endpoint` and `persona` in the `variables` block. We can then reuse these values throughout
the workflow using the `{workflow.variable_name}` syntax. This makes workflows cleaner and easier to manage.

For backward compatibility, the **old format** (a simple list of nodes) is still fully supported. The example below
works exactly as it did before.

**Old Format (Still Supported)**

```json
[
  {
    "title": "Checking AI's recent memory about this topic",
    "type": "FullChatSummary"
  },
  {
    "title": "Recent memory gathering",
    "type": "RecentMemorySummarizerTool",
    "maxTurnsToPull": 30,
    "maxSummaryChunksFromFile": 30
  },
  {
    "title": "Responding to User Request",
    "systemPrompt": "The conversation summary is:\n[\n{agent1Output}\n]\nThe AI's memories are:\n[\n{agent2Output}\n]\nGiven this, please continue the conversation.",
    "endpointName": "OpenWebUI-NoRouting-Single-Model-Endpoint",
    "preset": "Conversational_Preset",
    "maxResponseSizeInTokens": 800
  }
]
```

-----

### Passing Data Between Nodes

Nodes need a way to communicate with each other. This is done with two types of variables: **Outputs** and **Inputs**.

#### Agent Outputs

When a node runs, its result (if it has one) is automatically stored in an **Agent Output**. The variable is named based
on the node's position in the list (starting from 1).

* The result of the **1st** node is stored in `{agent1Output}`.
* The result of the **2nd** node is stored in `{agent2Output}`.
* And so on.

Any subsequent node can use these results. In both examples above, the final node uses `{agent1Output}` (and
`{agent2Output}` in the second example) to give the LLM the context it gathered in the earlier steps. **Agent Outputs**
are for passing data *forward* within a *single* workflow run.

#### Agent Inputs

Sometimes you want to call one workflow from inside another (using a `CustomWorkflow` node). To pass data *into* that
sub-workflow, you use **Agent Inputs**.

Imagine this node is in your main workflow:

```json
{
  "type": "CustomWorkflow",
  "workflowName": "summarize-text-workflow",
  "scoped_variables": [
    "{agent1Output}"
  ]
}
```

This runs `summarize-text-workflow`. The value of `{agent1Output}` from the main workflow is passed into the
sub-workflow. Inside `summarize-text-workflow`, that value is now available to *all* nodes from the very beginning as
`{agent1Input}`. This is the primary way to pass data *down* into a nested workflow.

-----

### A Look at Some Node Types

The system comes with many node types for different tasks. Here are a few common ones:

* **`Standard`**: The most basic node. It's used for making a direct call to an LLM with a system prompt and user
  prompt. This is almost always the node that responds to the user.
* **Memory Nodes (`FullChatSummary`, `VectorMemorySearch`)**: These nodes are for managing the AI's memory. They can
  summarize the chat, save key facts, or search a vector database for relevant information from past conversations.
* **`PythonModule`**: A very powerful node that lets you run a custom Python script. This is the main way to add
  completely new tools and capabilities to the system.
* **`CustomWorkflow`**: As mentioned above, this node lets you run another workflow. It's perfect for reusing common
  logic, like a sequence of nodes that generates a detailed summary.

-----

### Responding Nodes

In any given workflow, only one node can send the final response back to the user (e.g., writing to SillyTavern or
OpenWebUI).

By default, the **very last node** in the workflow is the one that responds.

However, you can make an earlier node respond by setting `"returnToUser": true` in its configuration. This is useful
for "fire and forget" tasks. For example, a node can generate and return a response to the user, while later nodes run
in the background to save memories or update a summary without making the user wait.

A great example is the [suspicious link removed]. If you look at it, a `Standard` node in the middle responds to the
user, while the final nodes perform background tasks like locking the workflow and updating memory files.