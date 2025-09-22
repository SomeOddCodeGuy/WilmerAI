## The `ConversationMemory` Node (Legacy)

This guide provides a code-validated overview of the legacy `ConversationMemory` node.

### Core Purpose

**`ConversationMemory`** is a legacy, dual-function node that was designed to run a predefined system sub-workflow
to parse the conversation and generate memories. Its specific logic is encapsulated in an internal workflow that is less
flexible than the modern, modular approach. Like `RecentMemory`, it combines creation and retrieval in a blocking
manner.

-----

### Internal Execution Flow

The node's handler simply executes a hardcoded internal sub-workflow designed to parse, summarize, and return
conversational memories. This process is not as configurable or efficient as the current `QualityMemory` -\>
`VectorMemorySearch` pattern.

-----

### Node Properties

| Property   | Type   | Required? | Description                             |
|:-----------|:-------|:----------|:----------------------------------------|
| **`type`** | String | ✅ Yes     | Must be exactly `"ConversationMemory"`. |

-----

### Workflow Strategy and Annotated Example

This node is superseded by the modern creator/retriever pattern and is **not recommended** for new workflows due to its
inefficiency and lack of configurability.

```json
// LEGACY WORKFLOW (NOT RECOMMENDED)
[
  {
    "title": "Run legacy conversation memory process",
    "type": "ConversationMemory"
    // --- BEHAVIOR CONTROL (INEFFICIENT) ---
    // This node runs an older, all-in-one memory process
    // that is slower and less flexible than modern nodes.
  }
]
```