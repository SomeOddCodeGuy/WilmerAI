## Quick Guide to Understanding Workflows in WilmerAI

Workflows are by far the most complex part of Wilmer to configure, and there is [an entire section of the
readme about them](../../README.md#understanding-workflows), so I will try to keep this straight forward and
not rehash the same materials.

### Workflow Structure

Workflows are jsons that are made up of nodes that run from top to bottom. First node runs first, then second node
runs second, all the way to the end.

Consider the below workflow:

```json
[
  {
    "title": "Checking AI's recent memory about this topic",
    "agentName": "Chat Summary",
    "type": "FullChatSummary",
    "isManualConfig": true
  },
  {
    "title": "Recent memory gathering",
    "agentName": "Recent Memory Gathering Tool",
    "type": "RecentMemorySummarizerTool",
    "maxTurnsToPull": 30,
    "maxSummaryChunksFromFile": 30,
    "customDelimiter": "\n------------\n"
  },
  {
    "title": "Responding to User Request",
    "agentName": "Response Agent Two",
    "systemPrompt": "Below is an excerpt from an online discussion being conducted in a chat program between a user and an AI.\nDetailed instructions about the discussion can be found in brackets below:\n[\n{chat_system_prompt}\n]\nThe entire conversation up to this point may have been summarized; if so, then that summary can be found in brackets below:\n[\n{agent1Output}\n]\nAlong with the rolling summary of the conversation, the AI also generates 'memories' of key and pertinent information found through the conversation as it progresses. These 'memories' may span the entire chat, or if the chat is too long may only cover part of the discussion. The 'memories' can be found below:\n[\n{agent2Output}\n]\nGiven this information, please continue the conversation below.",
    "prompt": "",
    "lastMessagesToSendInsteadOfPrompt": 20,
    "endpointName": "OpenWebUI-NoRouting-Single-Model-Endpoint",
    "preset": "_OpenWebUI_NoRouting_Single_Model_Conversational_Preset",
    "maxResponseSizeInTokens": 800,
    "addUserTurnTemplate": false,
    "forceGenerationPromptIfEndpointAllows": false,
    "addDiscussionIdTimestampsForLLM": false
  }
]
```

The first node is a [FullChatSummary](../../README.md#full-chat-summary-node) node. This will check if there are
any memories or a chat summary, and if it should create or update those. It will then return the chat summary file.

The second node is the [RecentMemorySummarizerTool](../../README.md#recent-memory-summarizer-tool) node. This will pull
as many memories as you specify here (`maxSummaryChunksFromFile`; so here's we're pulling a max of 30), and return them
separated by a custom separator you specify (customDelimiter).

The third node is what responds to the user. If you look, you can see it referencing {agent1Output} and {agent2Output}.
We'll talk about that in a second, but here you can see that each node does something specific, and they run from top
to bottom.

### Agent Outputs

Any node that returns a value will have its value stored in an agent output corresponding its spot in the workflow. So
node 1 has its return saved in agent1Output. Node 3 has its return saved in agent3Output. Any node that comes after that
node can access the return by referencing those in curly braces, like {agent1Output} or {agent3Output}.

In our above example, node 1 returned the full chat summary and node 2 returned memories. In node 3, responding to us,
we referenced both to let the LLM have access to that.

### Responding nodes

In a workflow, only 1 node can respond to the user (writing back to SillyTavern or OpenWebUI for example). Generally,
that node is the very last one in a workflow. However, it's possible to specify `returnToUser` as true, in which case
a node that isn't the last one can go. An example of a workflow that does this is the [convo-roleplay-dual-model
workflow locked](../../Public/Configs/Workflows/convo-roleplay-dual-model/FullCustomWorkflow-ChatSummary-WorkflowLocked.json)
workflow. If you look, the last few nodes are just locking the workflow and writing the summary; it's actually a node
in the middle that is responding to the user. You can read more about why you might want to do
this [here, in the memories
readme](Memories.md#why-do-some-nodes-make-memories-and-some-nodes-just-pull-them).

