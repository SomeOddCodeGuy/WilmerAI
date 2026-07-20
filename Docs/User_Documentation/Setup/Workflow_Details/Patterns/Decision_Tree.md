# The Decision Tree Pattern

## The problem

A workflow often reaches a point where what should happen next depends on the conversation: this turn calls for one
kind of work, that turn calls for another, and most turns call for nothing at all. Two naive approaches both fail:

- **One prompt does everything.** Asking a single node to detect the situation *and* handle every variation of it means
  every instruction competes with every other one. Small models in particular do all of the jobs badly instead of one
  job well.
- **Every branch runs every turn.** Running each possible handler unconditionally pays the token and latency cost of
  all of them, on every turn, and then something still has to reconcile their outputs.

The decision tree separates *deciding* from *doing*. A cheap **decider** node classifies the situation into a single
word from a closed set; a `ConditionalCustomWorkflow` routes that word to a child workflow that does exactly one job;
a fallback catches everything else. The decision is carried by the structure of the workflow, not by prompt
instructions the model has to remember to follow.

## The shape

1. **Decide** with a fast `Standard` node: given the relevant context, answer with one bare token from a closed set
   (`ALPHA`, `BETA`, or `NONE`; the set is whatever your branches are).
2. **Route** with `ConditionalCustomWorkflow`: one child workflow per answer, plus a fallback for everything that
   does not match.

```
1. Standard decider           → "ALPHA" | "BETA" | anything else
2. ConditionalCustomWorkflow
     ├─ "ALPHA"  ─▶ Handle_Alpha (sub-workflow: one job, its own prompts)
     ├─ "BETA"   ─▶ Handle_Beta  (sub-workflow: one job, its own prompts)
     └─ no match ─▶ fallback (a "Default" workflow, or static default content)
```

Any child can begin with its own decider, which is what makes this a *tree* rather than a single branch point: the
first decider picks a family of work, the next one picks the specific job.

## Why each piece is there

- **A bare token from a closed set needs no extractor.** `ConditionalCustomWorkflow` matches its `conditionalKey`
  against the branch keys case-insensitively, so the decider's raw output feeds it directly. Tell the decider, in both
  its system prompt and its prompt, to respond with only one of the allowed words.
- **Malformed answers fall through to the fallback.** If the decider ever emits something outside the set, no branch
  matches and the node takes its fallback. Make the fallback the *safe* action and a bad answer costs you one skipped
  turn, never a wrong branch. Note that a fallback is mandatory: with no match, no `"Default"` workflow, and no
  `UseDefaultContentInsteadOfWorkflow`, the node errors at runtime. For a no-op fallback, set
  `"UseDefaultContentInsteadOfWorkflow": ""`.
- **"Nothing to do" and "bad answer" can share a branch.** If one of the decider's answers means "do nothing" (`NONE`
  in the skeleton below), leave it out of `conditionalWorkflows` entirely: it falls through to the same safe fallback a
  malformed answer does, which is exactly the behavior both cases want.
- **Each leaf is one job with its own prompts.** The child workflow for `ALPHA` never has to mention `BETA`'s job, and
  neither has to explain how to detect the situation; the tree already did that. This is what keeps prompts short and
  single-purpose.
- **Deciding is cheap; doing is expensive.** The decider runs every turn, so keep it on a fast endpoint with a tiny
  response budget. The expensive work only runs on the turns that actually need it.
- **`routeOverrides` handles near-identical branches.** When two branches differ only in phrasing, route them to the
  same child workflow and vary its first node's prompts per route, instead of maintaining two copies of the workflow.
- **Not every decision needs an LLM.** When the decision is computable (a turn counter, a string comparison), make it
  with deterministic nodes (`ArithmeticProcessor`, `Conditional`) instead of a decider; see
  [Periodic Gating](Periodic_Gating.md) for the fully deterministic version of this pattern.

Wilmer's front-door routing (`routingConfig` and the categorization workflow) is this same idea applied at the top of
the request: classify, then route. The decision tree is how you do it *inside* a workflow, where you control the
categories, the context the decider sees, and what each branch does.

## Skeleton

The decider and the router:

```json
[
  {
    "title": "Decide what this turn needs",
    "type": "Standard",
    "endpointName": "Worker-Endpoint",
    "preset": "Worker-Endpoint",
    "systemPrompt": "You watch a conversation and decide what the most recent turn calls for. Respond with ALPHA if <the first situation>. Respond with BETA if <the second situation>. Respond with NONE if neither applies; most turns are NONE. **ONLY respond with ALPHA, BETA, or NONE**.",
    "prompt": "Here are the most recent messages:\n\n<recent_messages>\n{chat_user_prompt_last_ten}\n</recent_messages>\n\nWhat does the latest turn call for? **ONLY respond with ALPHA, BETA, or NONE**.",
    "maxResponseSizeInTokens": 100,
    "addUserTurnTemplate": true,
    "returnToUser": false
  },
  {
    "title": "Route on the decision",
    "type": "ConditionalCustomWorkflow",
    "conditionalKey": "{agent1Output}",
    "conditionalWorkflows": {
      "ALPHA": "Handle_Alpha",
      "BETA": "Handle_Beta"
    },
    "UseDefaultContentInsteadOfWorkflow": "",
    "scoped_variables": [ "{chat_user_prompt_last_ten}" ]
  }
]
```

`NONE` is deliberately absent from `conditionalWorkflows`: it falls through to the empty default content, the same
no-op a malformed answer gets. The chosen child receives the scoped values as `{agent1Input}`, `{agent2Input}`, and so
on, in the order listed.

## Growing the tree

- **More branches**: add keys to `conditionalWorkflows` and words to the decider's closed set.
- **Deeper levels**: start a child workflow with its own decider. Prefer several small closed sets over one large one;
  a small model picks reliably among three or four options and unreliably among ten, and each level costs only one more
  cheap call.
- **Parallel gates**: independent yes/no deciders in sequence, each gating its own step, are often simpler than one
  combined decider that has to express every combination.

## Things to get right

- **State the closed set twice and bold it.** Both the system prompt and the prompt should end with the "ONLY respond
  with..." line. This is the single highest-value instruction in the pattern.
- **Tell the decider the base rate.** If most turns should route nowhere, say so outright ("most turns are NONE").
  That one sentence is the main defense against a decider that finds work in everything.
- **Keep the decider small.** A low `maxResponseSizeInTokens` and no request for reasoning or explanation. If a branch
  needs analysis, do the analysis inside the branch, where its prompt can be about that one job.
- **Sub-workflows are isolated.** A child cannot see the parent's `{agent#Output}` values. It *can* see the
  conversation (`{chat_user_prompt_*}`, `{chat_system_prompt}`), user-wide variables, and `{Discussion_Id}`. Anything
  else must be passed via `scoped_variables`.

## A common specialization

When every branch of the tree should end by returning the same file (update it, or pass it through untouched), use
[The Decision Tree to Return a File](Decision_Tree_To_Return_File.md), which adds the load/save plumbing and the
no-drift guarantees around this shape.
