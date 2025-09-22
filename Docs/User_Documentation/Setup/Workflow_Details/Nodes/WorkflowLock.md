## The `WorkflowLock` Node

The `WorkflowLock` node is a powerful control mechanism used to prevent race conditions during long-running,
asynchronous operations. Its primary purpose is to create a temporary, exclusive lock that halts subsequent workflow
executions at a specific point, ensuring that a resource-intensive task isn't triggered multiple times concurrently.

This is especially useful in workflows that provide a fast, initial response to the user and then proceed with a slower
background task, such as generating conversational memories or performing Retrieval-Augmented Generation (RAG).

-----

### Core Use Case

The typical scenario for a `WorkflowLock` involves separating a quick user interaction from a slow background process.
Consider a workflow designed to do the following:

1. **Retrieve Data:** Pull existing chat summaries and memories from storage.
2. **Respond to User:** Use the retrieved data and the user's latest message to generate a quick response. This node is
   marked as the **responder** (`"returnToUser": true`), so its output is sent to the client immediately.
3. **Acquire Lock:** The `WorkflowLock` node executes. If no lock is active, it creates one.
4. **Perform Slow Task:** A final node begins a long-running process, like using a powerful LLM to regenerate the entire
   chat summary based on the new conversation.

If the user sends another message while the "Slow Task" (Step 4) is still running, the new workflow execution will
proceed through Steps 1 and 2, delivering another fast response. However, when it reaches the `WorkflowLock` node (Step
3), it will detect the existing lock and **immediately terminate the workflow**. This prevents a second,
resource-intensive "Slow Task" from starting while the first one is still in progress.

-----

### Configuration

Here are the configurable fields for a `WorkflowLock` node:

| Field                | Type   | Required | Description                                                                                                                                                                            |
|----------------------|--------|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**           | String | **Yes**  | The node's type identifier. Must be set to `"WorkflowLock"`.                                                                                                                           |
| **`title`**          | String | No       | A user-friendly name or description for the node, which is helpful for readability within the workflow's JSON configuration.                                                           |
| **`workflowLockId`** | String | **Yes**  | The unique identifier for the lock. All `WorkflowLock` nodes that share the same `workflowLockId` (for the same user) will contend for the same lock, even across different workflows. |

#### Example JSON

```json
{
  "title": "Acquire Lock for Memory Generation",
  "type": "WorkflowLock",
  "workflowLockId": "FullCustomChatSummaryLock"
}
```

-----

### Behavior and Mechanics

#### Lock Acquisition and Termination

* **On Execution:** When the `WorkflowProcessor` reaches a `WorkflowLock` node, it checks for an active lock matching
  the `workflowLockId`.
* **If No Lock Exists:** A new lock is created and stored in a user-specific SQLite database. The workflow then
  continues to the next node.
* **If Lock Exists:** The node raises an `EarlyTerminationException`, which immediately stops the current workflow. No
  further nodes in that workflow are executed.

#### Lock Release and Scope

Locks are designed to be temporary and are released automatically under several conditions:

* **Workflow Completion:** The lock is automatically deleted when the workflow that created it finishes, whether it
  completes successfully or terminates with an error.
* **Safety Timeout:** As a fallback, each lock has a hardcoded **10-minute expiration time**. If a workflow crashes
  unexpectedly, the lock will be automatically cleared after 10 minutes, preventing a permanent deadlock.
* **Application Restart:** All locks from a previous session are cleared when the WilmerAI application is restarted.
* **Scope:** Locks are scoped per **user**. This means a lock created by User A will not interfere with workflows run by
  User B.

#### Recommendations

* **Placement:** Place the `WorkflowLock` node **immediately after** your designated responder node (
  `"returnToUser": true`) and **immediately before** the long-running task(s) you want to protect.
* **Unique IDs:** Use clear and descriptive `workflowLockId`s to avoid accidental conflicts. You can intentionally reuse
  the same ID in different workflows if you want them to be mutually exclusive.
* **Use Cases:** This node is most effective for non-critical background tasks that can be delayed or skipped without
  impacting the core user experience. It is particularly powerful in multi-computer or multi-model setups, allowing a
  fast "responder" model to remain available while a slower "worker" model is busy.