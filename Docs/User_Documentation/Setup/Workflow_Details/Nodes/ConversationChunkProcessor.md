## Resumable History Processing: The `ConversationChunkProcessor` Node

The **`ConversationChunkProcessor` Node** runs a sub-workflow over the conversation in fixed-size chunks of messages,
one chunk at a time, and remembers where it left off between turns. Its purpose is to give any record that is *built up*
from the conversation the same catch-up behavior that the file-memory system already has: when a long conversation is
started under a fresh discussion id, or dropped in wholesale from another client, the node walks the entire backlog in
chunks and runs the sub-workflow on each one **before the turn's response is produced**, so the record is fully caught
up, as if it had been maintained all along.

### The problem it solves

A record maintained turn-by-turn (a running list of events, a per-persona tracker) normally only ever sees the most
recent handful of messages. If you resume a conversation of hundreds of messages under a new discussion id, that record
starts blank and stays blind to everything that happened before the recent window. File memory avoids this by
backfilling its summaries from the whole history on first contact. This node extends the same idea to any sub-workflow.

### How It Works

A small **cursor file**, named by the node's required `id`, stores **one boundary hash per processed chunk** (the
hash of the last message in each chunk) rather than a hash of every message. Keeping one hash per chunk lets a
regenerated or reformatted tail re-anchor on an earlier chunk boundary while the cursor stays small. On every run:

1. It reads the cursor and uses the same message-hash matching the memory system uses to determine how many messages are
   new since that cursor. With no cursor (a fresh discussion id), *everything* is new.
2. It slices those new messages into `chunkSize`-message groups and runs `workflowName` once for **every complete group**,
   oldest first. There is **no per-run cap**; a long backlog is fully processed within the single turn, before any
   downstream node (such as a responder) runs.
3. After each chunk it advances the cursor, so the next turn resumes rather than reprocessing.

The freshest partial group (fewer than `chunkSize` messages) and the `lookbackMessages` tail are left for a later turn;
they are picked up once enough messages accumulate to complete a chunk. A live responder still sees those recent
messages directly, so nothing is invisible in the meantime.

Because the cursor is a set of message hashes, an edited or regenerated message near the boundary still matches an
earlier message in the stored chunk, so a single edit resumes from just before it instead of forcing a full
re-processing of the whole history.

-----

### Properties

| Property               | Type             | Required | Default | Description                                                                                                                                                                                             |
|:-----------------------|:-----------------|:---------|:--------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**             | String           | Yes      | N/A     | Must be `"ConversationChunkProcessor"`.                                                                                                                                                                |
| **`id`**               | String           | Yes      | N/A     | A unique, stable, path-safe identifier (letters, digits, `.`, `-`, `_`). It names the cursor file, so two of these nodes in one workflow keep separate cursors. Must be author-supplied; a generated id could change and orphan the cursor, forcing a full re-processing of history. |
| **`workflowName`**     | String           | Yes      | N/A     | The sub-workflow to run once per chunk (without `.json`).                                                                                                                                              |
| **`chunkSize`**        | Integer          | No       | `10`    | Number of messages per chunk.                                                                                                                                                                          |
| **`lookbackMessages`** | Integer          | No       | `4`     | How many of the freshest messages to leave unprocessed each run (they are handled once they fall into a completed chunk). Larger values keep the very latest exchanges out of the record for longer.   |
| **`cursorDirectory`**  | String           | Yes      | N/A     | Directory the cursor file is written to. Supports variables (e.g. `"{gameTempDir}"`).                                                                                                                  |
| **`returnFile`**       | String           | No       | `null`  | If set, the node returns this file's resolved content after processing, so a later node can keep reading the record it maintains. If unset, the node returns a short status string. Supports variables. |
| **`scoped_variables`** | Array of Strings | No       | `[]`    | Extra inputs passed to the sub-workflow *after* the chunk. See Data Flow. May only reference outputs of nodes that ran earlier in the parent workflow.                                                  |

-----

### Data Flow

Each chunk is passed to the sub-workflow as its `messages` (a copy of just that chunk, never the whole conversation) and
also, as text, as **`{agent1Input}`**. Any `scoped_variables` follow it as `{agent2Input}`, `{agent3Input}`, and so on:

```json
{
  "type": "ConversationChunkProcessor",
  "id": "keyEvents",
  "workflowName": "KeyEvents_ChunkUpdate",
  "chunkSize": 10,
  "lookbackMessages": 4,
  "cursorDirectory": "{gameTempDir}",
  "returnFile": "{gameTempDir}/key_events_{Discussion_Id}.md",
  "scoped_variables": [ "{agent7Output}" ]
}
```

Inside `KeyEvents_ChunkUpdate`, `{agent1Input}` is the chunk's text and `{agent2Input}` is the resolved `{agent7Output}`
from the parent. Because `scoped_variables` are resolved from the parent's earlier node outputs, any value a chunk's
sub-workflow needs (a summary, world info, a loaded file) must be produced by a node that runs **before** this one.

### The cursor file

The node writes one cursor file per `id` per discussion, named `chunk_cursor_<id>_<DiscussionId>.txt`, into
`cursorDirectory`. It holds the message hashes of the last processed chunk. Deleting it makes the node re-process the
whole conversation from the start on the next turn (a clean way to rebuild a record).

### Notes

- **Complete chunks only.** A remainder smaller than `chunkSize` is not processed until it grows into a full chunk, so a
  record built this way lags the very latest messages by up to `chunkSize` messages. This is the same trade-off the
  file-memory system makes, and it is fine whenever whatever consumes the record also sees the recent conversation.
- **Per-conversation isolation.** The cursor path includes `{Discussion_Id}`; each conversation keeps its own cursor.
- **No discussion id.** Without a discussion id the cursor file falls back to a shared name, exactly as the other
  per-discussion files in a workflow do.
- **Weak models.** If the per-chunk sub-workflow asks a model to emit a list, keep its response size capped. A chunk is
  small and bounded, so this is far less prone to the runaway repetition that open-ended "summarize everything" prompts
  can trigger on small models. Pairing it with a periodic de-duplication pass (see
  [Periodic Gating](../Patterns/Periodic_Gating.md)) guards against the failures that remain.

### Related

- [The `CustomWorkflow` Node](CustomWorkflow.md) and [The `ConditionalCustomWorkflow` Node](ConditionalCustomWorkflow.md):
  the other ways to run a workflow from inside another; this node shares their `scoped_variables` mechanism but adds
  the chunked, resumable iteration.
- [The Decision Tree to Return a File](../Patterns/Decision_Tree_To_Return_File.md): the per-turn shape this node
  replaces when a record needs to survive being resumed from history.
