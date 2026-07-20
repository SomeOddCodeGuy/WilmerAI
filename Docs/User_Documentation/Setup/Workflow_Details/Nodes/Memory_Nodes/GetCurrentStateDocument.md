## The `GetCurrentStateDocument` Node

This guide provides a code-validated overview of the `GetCurrentStateDocument` node. It details the
node's function as a direct reader of the discussion's state document.

### Core Purpose

The **`GetCurrentStateDocument`** node is a simple, direct **"dumb" reader**. Its sole function is to
read the complete contents of the discussion's state document (`state_document.md`) and return it as a
single string. It performs no staleness checks, triggers no updates, and has no complex logic.

The state document is a single, continuously updated markdown document that holds the **current,
ground-truth state** of the conversation's subject matter. It is the "what is true right now" layer of
the memory system, distinct from the other memory components:

* The **Long-Term Memory File** and **Searchable Vector Memory** are historical records: they hold
  everything that was ever true, in the order it happened.
* The **Rolling Chat Summary** is a narrative: it describes how the conversation has unfolded.
* The **State Document** is a snapshot: it describes the present. When a fact changes, the state
  document's entry is replaced; the old value remains available in the historical records.

What the document contains is entirely defined by the prompts in the state document workflow, not by
WilmerAI itself. An assistant persona might maintain sections like `## Identity & Background`,
`## Work & Projects`, and `## Ongoing Situations`; a novel-style roleplay might instead maintain
`## Characters`, `## World State`, and `## Active Quests`. See the State Document section of the
memory nodes guide for how the document is created and updated.

Because the document is stored as plain markdown, users can open and hand-edit it at any time (unless
per-user encryption is active, in which case it is encrypted at rest like the other memory files). A
`.bak` file holding the previous version sits alongside it after every automatic update.

-----

### Internal Execution Flow

1. **File Location**: The node identifies the path to the `state_document.md` file inside the active
   discussion's folder using the `discussionId`.
2. **File Read**: It reads the document's full text.
3. **Return**: It returns the text as a single string. If no `discussionId` is available, or the file
   does not exist yet, it returns a fallback message.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node always returns a string containing the full state
  document text. If no `discussionId` is active, or no document has been written yet, it returns
  `"No state document has been created yet"`.

-----

### Node Properties

| Property   | Type   | Required? | Description                                      |
|:-----------|:-------|:----------|:--------------------------------------------------|
| **`type`** | String | Yes       | Must be exactly `"GetCurrentStateDocument"`.     |

-----

### Workflow Strategy and Annotated Example

The state document is designed to be **always injected**, not searched. Core facts about the user (or
the roleplay world) should be present on every single response, without depending on a keyword search
happening to surface them. Place this node early in a workflow and inject its output into the system
prompts of your thinking and responder nodes; use `VectorMemorySearch` alongside it to recall the
episodic long tail that does not belong in an always-on document.

```json
[
  {
    "title": "Step 1: Load the current state document",
    "type": "GetCurrentStateDocument"
    // --- BEHAVIOR CONTROL ---
    // This is a direct file read. No update is triggered here; the document is
    // written by the QualityMemory vector pipeline when useStateDocument is
    // enabled in the discussion settings.
  },
  {
    "title": "Step 2: Respond with the state document as context",
    "type": "Standard",
    "returnToUser": true,
    "systemPrompt": "You are a helpful assistant. The current state of the user's life and ongoing situations is:\n<current_state>\n{agent1Output}\n</current_state>",
    "prompt": "Please respond to the conversation, staying consistent with the current state above."
  }
]
```
