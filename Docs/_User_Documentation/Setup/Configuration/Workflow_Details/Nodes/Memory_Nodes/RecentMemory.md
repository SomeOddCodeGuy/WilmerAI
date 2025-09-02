## The `RecentMemory` Node

This guide provides a comprehensive, code-validated overview of the legacy `RecentMemory` node. It details its
inefficient dual-function logic and provides modern alternatives.

### Core Purpose

**`RecentMemory`** is a **dual-function node** that combines memory creation and retrieval into a single,
blocking step. It was designed to be an all-in-one solution for ensuring memories were up-to-date before retrieving
them.

-----

### Internal Execution Flow

The node performs two major operations in strict sequence, blocking execution until both are complete:

1. **Create Memories**: The node first calls the **entire `QualityMemory` creation process**. It analyzes the
   conversation for new messages, generates new summaries if thresholds are met, and saves them to disk.
2. **Retrieve Memories**: Immediately after the creation step finishes, it runs a sub-workflow to parse and return the
   recent memories, similar to `RecentMemorySummarizerTool`.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: After both creating and retrieving, the node returns a string containing the
  recent memories.

-----

### Node Properties

| Property   | Type   | Required? | Description                       |
|:-----------|:-------|:----------|:----------------------------------|
| **`type`** | String | ✅ Yes     | Must be exactly `"RecentMemory"`. |

-----

### Workflow Strategy and Annotated Example

```json
// LEGACY WORKFLOW (NOT RECOMMENDED)
[
  {
    "title": "Create and then get recent memories",
    "type": "RecentMemory"
    // --- BEHAVIOR CONTROL (INEFFICIENT) ---
    // This single step might take several seconds to run, as it waits
    // for the LLM to generate a new memory chunk before it can retrieve anything.
  },
  {
    "title": "Respond to user",
    "type": "Standard",
    "prompt": "Recent context: {agent1Output}. Now answer the user."
  }
]
```