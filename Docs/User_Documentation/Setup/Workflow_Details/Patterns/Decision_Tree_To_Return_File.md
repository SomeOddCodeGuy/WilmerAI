# The Decision Tree to Return a File Pattern

## The problem

You want a file (a document, a log, a snapshot) that stays current across a long conversation. Every turn it might
need an update, but two naive approaches both fail:

- **Rewrite it every turn.** A smaller model re-emitting the whole file will eventually drop something it wasn't asked
  to touch, and you pay the cost on turns where nothing changed.
- **Trust the model to remember.** The moment the relevant history scrolls out of the context window, it's gone.

This pattern solves both. It is a [decision tree](Decision_Tree.md) with one extra rule: **every leaf returns the
file**. State lives on disk; a cheap decider chooses what, if anything, to do to the file; and on a quiet turn the file
is returned exactly as it was, so there is no opportunity to drift.

## The shape

A small sub-workflow, called from a parent through a `CustomWorkflow` node, with three nodes:

1. **Load** the file with `GetCustomFile`.
2. **Decide** with a fast `Standard` node: given the recent messages and the current file, what does the file need?
   In the smallest version the closed set is just `YES` (something changed) or `NO`.
3. **Route** with `ConditionalCustomWorkflow`: each matching answer runs a child that edits and re-saves the file and
   returns it; everything else falls through to a default that returns the file untouched.

```
parent workflow
  └─ CustomWorkflow ─▶ Document tree (sub-workflow)
                        1. GetCustomFile        → the current file
                        2. Standard decider     → "YES" or "NO"
                        3. ConditionalCustomWorkflow
                             ├─ "YES"  ─▶ Update (sub-workflow): rewrite → save → return the file
                             └─ default ─▶ return the current file unchanged
```

The tree does not have to be binary. A decider that answers `ADD`, `EDIT`, or `NOTHING` can route to an appending
child and a surgically-editing child, with `NOTHING` falling through to the untouched file; each write strategy gets
its own one-job leaf (see the strategy table below).

## Why each piece is there

- **The decider earns its keep twice.** It skips the expensive update on turns where nothing changed, and, more
  importantly, its no-change path returns the file *verbatim*, which is what guarantees no drift. Preservation is not
  something you have to prompt for; it is structural.
- **A bare answer from a closed set needs no extractor.** `ConditionalCustomWorkflow` matches its `conditionalKey`
  against the branch keys case-insensitively, so the decider's output feeds it directly. If it ever emits something
  malformed, no branch matches and it falls through to the default, which is the safe pass-through, so a bad answer
  costs you a stale file for one turn, never a corrupted one.
- **The pass-through is a fallback, not a workflow.** Set `"UseDefaultContentInsteadOfWorkflow": "{agent1Output}"` on
  the `ConditionalCustomWorkflow` (where `{agent1Output}` is the loaded file). No second workflow file is needed for
  the "nothing changed" case.
- **The tree's return value is its last node's output.** A workflow returns the output of its first `returnToUser`
  node, or its last node if none. Placing the `ConditionalCustomWorkflow` last means the sub-workflow returns either
  the updated file (from the update child) or the untouched file (from the default); the caller gets the current file
  content either way.

## Skeleton

**`Document_Tree.json`**, the decider and the router:

```json
[
  {
    "title": "Load the document",
    "type": "GetCustomFile",
    "filepath": "{someBaseDir}/document_{Discussion_Id}.md",
    "delimiter": "",
    "customReturnDelimiter": "\n"
  },
  {
    "title": "Has anything changed?",
    "type": "Standard",
    "endpointName": "Worker-Endpoint",
    "preset": "Worker-Endpoint",
    "systemPrompt": "You maintain a document that records <what the document is>. Given the current document and the most recent messages, determine whether the recent messages changed anything the document should now reflect. Respond with YES if something changed, or NO if it did not. **ONLY respond with either YES or NO**.",
    "prompt": "Here is the document as it currently stands:\n\n<document>\n{agent1Output}\n</document>\n\nHere are the most recent messages:\n\n<recent_messages>\n{chat_user_prompt_last_ten}\n</recent_messages>\n\nHas anything the document should reflect changed? **ONLY respond with either YES or NO**.",
    "maxResponseSizeInTokens": 100,
    "addUserTurnTemplate": true,
    "returnToUser": false
  },
  {
    "title": "Update only if it changed",
    "type": "ConditionalCustomWorkflow",
    "conditionalKey": "{agent2Output}",
    "conditionalWorkflows": { "YES": "Document_Update" },
    "UseDefaultContentInsteadOfWorkflow": "{agent1Output}",
    "scoped_variables": [ "{agent1Output}", "{chat_user_prompt_last_ten}" ]
  }
]
```

**`Document_Update.json`** runs only on a `YES`; the two scoped values arrive as `{agent1Input}` (the current
document) and `{agent2Input}` (the recent messages):

```json
[
  {
    "title": "Rewrite the document",
    "type": "Standard",
    "endpointName": "Worker-Endpoint",
    "preset": "Worker-Endpoint",
    "systemPrompt": "You maintain a document that records <what the document is>. It has just been determined that the recent messages changed it. Produce the updated document, preserving everything the messages did not touch.",
    "prompt": "Here is the current document:\n\n<document>\n{agent1Input}\n</document>\n\nHere are the most recent messages, which changed it:\n\n<recent_messages>\n{agent2Input}\n</recent_messages>\n\nWrite the updated document. Respond with only the document itself.",
    "maxResponseSizeInTokens": 2000,
    "addUserTurnTemplate": true,
    "returnToUser": false
  },
  {
    "title": "Save the document",
    "type": "SaveCustomFile",
    "filepath": "{someBaseDir}/document_{Discussion_Id}.md",
    "content": "{agent1Output}",
    "mode": "overwrite"
  },
  {
    "title": "Return the document",
    "type": "StaticResponse",
    "content": "{agent1Output}"
  }
]
```

The parent calls it with a single node, and uses the returned document in a later node:

```json
{ "title": "Update and load the document", "type": "CustomWorkflow", "workflowName": "Document_Tree", "is_responder": false }
```

## Choosing how the update writes

The update child's job is fixed; only *how it writes* changes with the kind of file:

| The file is… | Update strategy | `SaveCustomFile` mode | Why |
|:---|:---|:---|:---|
| A bounded snapshot ("what's true now") | Re-render the whole thing | `overwrite` | It stays small, so a full rewrite is safe. |
| An append-only log of discrete entries | Write only the new entry | `append` | Old entries are never touched. Show the log to the decider so it doesn't re-add an entry already present. |
| A structured/sectioned living document | Re-render, preserving unaffected sections | `overwrite` | Simple, and safe *when a strict decider keeps the document small*. |
| A flat log needing edits to existing lines | Emit the exact target text and its replacement | `replace` / `remove` | Surgical: nothing unrelated can be dropped, at the cost of the model reproducing the target text exactly. See [SaveCustomFile](../Nodes/SaveCustomFile.md). |

With more than two branches, each strategy can be its own leaf: a decider that answers `ADD` / `EDIT` / `NOTHING`
routes to an append child, a replace child, or the pass-through, and no single prompt has to describe more than one
write discipline.

The recurring safety rule: a **full rewrite is safe only while the document is small**. A snapshot is small by nature;
a log or ledger is kept small by a strict decider, or is edited surgically instead.

## Things to get right

- **Per-conversation isolation.** Put `{Discussion_Id}` in the filepath (both the load and every save) so each
  conversation keeps its own file. `GetCustomFile` and `SaveCustomFile` both resolve it.
- **Sub-workflows are isolated.** A child cannot see the parent's `{agent#Output}` values. It *can* see the conversation
  (`{chat_user_prompt_*}`, `{chat_system_prompt}`), user-wide variables from the user config, and `{Discussion_Id}`.
  Anything else must be passed via `scoped_variables`, arriving as `{agent1Input}`, `{agent2Input}`, and so on.
- **Keep bookkeeping off the final response.** The tree returns the file so a later node can use it, but if that file
  can grow, distill it with a worker step before handing it to the user-facing responder rather than injecting the
  whole thing.
- **The decider's base rate is a feature.** For a file that should change rarely, tell the decider outright that most
  turns change nothing and `NO` is expected. That single sentence is the main defense against a decider that finds a
  change in everything.
