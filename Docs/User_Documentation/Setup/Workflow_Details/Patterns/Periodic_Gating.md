# The Periodic Gating Pattern (Turn Counter)

## The problem

Some workflow steps are expensive or noisy to run on every single turn: collecting facts into a log, re-summarizing,
calling a heavy model. You would rather run them once every N turns, over a batch of what has happened since. And you
would rather not spend an LLM call just to decide whether it is time yet.

A turn counter does exactly that: a small number on disk, advanced by deterministic nodes, that fires an expensive step
every Nth turn and otherwise costs almost nothing.

## The shape

A counter file gates the expensive step. Every turn:

1. **`GetCustomFile`** reads the counter.
2. **`ArithmeticProcessor`** adds 1 to it.
3. **`Conditional`** checks whether it has reached N.
4. **`ConditionalCustomWorkflow`** branches on that:
   - **reached N** → run the expensive step, then reset the counter to `0`.
   - **not yet** → save the incremented counter and pass the current state through.

```
every turn:
  GetCustomFile counter ─▶ Arithmetic {counter}+1 ─▶ Conditional ">= N" ─▶ ConditionalCustomWorkflow
                                                                              ├─ "TRUE" ─▶ Run: do the work, reset counter to 0
                                                                              └─ default ─▶ Tick: save counter+1, pass through
```

Steps 1-4 are **entirely deterministic**; no tokens are spent deciding whether to run. The model only runs on the Nth
turn, inside the Run branch.

## Why each piece is there

- **The counter lives on disk** (per conversation, via `{Discussion_Id}` in the path), because a workflow is stateless
  between invocations; the file *is* the memory of how many turns have passed.
- **`ArithmeticProcessor` returns `"-1"` for any non-numeric input**, which handles first-run for free. A missing
  counter file reads back as a "file not found" marker; `{marker} + 1` is non-numeric, so it evaluates to `-1`, and
  `-1 >= N` is `FALSE` → the tick branch. No special-casing for the missing file; the counter self-heals up to `0`
  within a couple of turns.
- **`Conditional` emits `"TRUE"`/`"FALSE"`**, and `ConditionalCustomWorkflow` matches those keys case-insensitively.
  Map `"TRUE"` to the Run workflow and use `"Default"` for the Tick, so anything that isn't `TRUE` just ticks.
- **The two branches are separate sub-workflows.** The **Tick** only saves the incremented count and returns the
  passed-through state, with no LLM. The **Run** does the work and then resets the counter to `0`.

## Skeleton

**`Counter_Maintainer.json`**, the deterministic gate:

```json
[
  { "title": "Load the counter", "type": "GetCustomFile",
    "filepath": "{someDir}/turn_counter_{Discussion_Id}.txt", "delimiter": "", "customReturnDelimiter": "\n" },
  { "title": "Load the state to pass through", "type": "GetCustomFile",
    "filepath": "{someDir}/record_{Discussion_Id}.md", "delimiter": "", "customReturnDelimiter": "\n" },
  { "title": "Increment", "type": "ArithmeticProcessor", "expression": "{agent1Output} + 1" },
  { "title": "Time to run?", "type": "Conditional", "condition": "{agent3Output} >= 10" },
  { "title": "Run every 10 turns, otherwise tick", "type": "ConditionalCustomWorkflow",
    "conditionalKey": "{agent4Output}",
    "conditionalWorkflows": { "TRUE": "Counter_Run", "Default": "Counter_Tick" },
    "scoped_variables": [ "{agent3Output}", "{agent2Output}" ] }
]
```

**`Counter_Tick.json`**, pure plumbing, no LLM (`{agent1Input}` = incremented count, `{agent2Input}` = passed-through state):

```json
[
  { "title": "Save the incremented counter", "type": "SaveCustomFile",
    "filepath": "{someDir}/turn_counter_{Discussion_Id}.txt", "content": "{agent1Input}", "mode": "overwrite" },
  { "title": "Return the state unchanged", "type": "StaticResponse", "content": "{agent2Input}" }
]
```

**`Counter_Run.json`**, which resets first, then does the periodic work:

```json
[
  { "title": "Reset the counter", "type": "SaveCustomFile",
    "filepath": "{someDir}/turn_counter_{Discussion_Id}.txt", "content": "0", "mode": "overwrite" },
  { "title": "Do the periodic work", "type": "Standard", "endpointName": "Worker-Endpoint", "preset": "Worker-Endpoint",
    "systemPrompt": "…", "prompt": "…process the recent batch…", "returnToUser": false }
  // …save/return as needed…
]
```

## What to run on the Nth turn

The Run step gets a **batch**: the whole stretch since the last run. Give it a token-bounded window of the recent
conversation (e.g. `{chat_user_prompt_min_n_max_tokens}` with `minMessagesInVariable` set to the batch size) plus
whatever context helps it do good work: the rolling chat summary (the story so far), and the system prompt's persona and
setting. Processing a batch at once means each event or change is handled **once**, which is why this cleanly avoids the
"re-processed every turn" duplication that a per-turn gate suffers.

## The weak-model caveat (read this before shipping to small models)

The **gating** works well for weak models: it is deterministic and spends no tokens on 9 turns out of 10, which matters
when each model call is slow. But watch the **Run step's output**.

A small model asked to emit a *multi-item list* ("write all the new events from this batch") can fall into a repetition
loop, emitting the same items over and over until it hits the token cap. If that output is then **appended** to a file,
the loop is multiplied into the file, producing a worse result than doing the work per-turn. This is a real, observed
failure on ~4B-class models. On capable models it does not happen; they emit clean lists.

Safeguards, if you must run this on small models:

- **Cap the Run step's `maxResponseSizeInTokens` tightly** so a loop is cut short.
- **Prefer an overwrite/rewrite over an append** for the gated write, so a bad output *replaces* the file rather than
  accumulating into it.
- **Add a mechanical exact-line de-duplication** of the file as a backstop after the write.
- If none of those is acceptable, keep the per-turn approach on small models and reserve periodic gating for larger
  ones. (A per-turn writer that emits one item at a time is much less prone to the loop.)

## Freshness

The record written by the Run step lags by up to N turns. That is fine when whatever consumes the record *also* sees the
recent conversation (a responder that receives the last several messages, for instance): the live context covers the
recent gap while the periodic step maintains the durable record.

## Gotchas

- **One counter can gate several steps.** Increment it in one place, have each gated step check it, and reset it once
  after the last step runs. Order matters: a step that resets the counter before the others have checked it will skip
  them.
- **Per-conversation isolation:** `{Discussion_Id}` in the counter path keeps each conversation's count separate.
- **Sub-workflows are isolated.** Pass the counter and any state into the Run/Tick children via `scoped_variables`.

See also [The Decision Tree to Return a File](Decision_Tree_To_Return_File.md), which gates on *whether something
changed* rather than *how many turns have passed*; the two compose (a file-updating tree whose expensive rewrite is
itself throttled by a counter).
