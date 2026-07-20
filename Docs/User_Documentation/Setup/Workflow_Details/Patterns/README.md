# Workflow Patterns

The node guides under `Nodes/` describe each node type in isolation. This folder describes **compositions**: reusable
shapes built from several nodes that solve a recurring problem. Copy them as starting points; none is specific to a
particular use case.

Each pattern is written generically. Where a pattern maintains state on disk it uses an abstract "document" rather than
any one application, so the same shape applies whether you are tracking a user profile, a game's world state, a running
task list, or anything else.

## Patterns

- **[The Decision Tree](Decision_Tree.md)**: separate deciding from doing. A cheap decider node classifies the
  situation into one word from a closed set, and a `ConditionalCustomWorkflow` routes it to a child workflow that does
  exactly one job, with a safe fallback for everything else. Trees can grow wider (more branches) and deeper (a child
  that starts with its own decider).
- **[The Decision Tree to Return a File](Decision_Tree_To_Return_File.md)**: the decision tree specialized for keeping
  a file current across a long conversation, where every leaf returns the file. Built from a `GetCustomFile` reader, a
  fast decider, and a `ConditionalCustomWorkflow` whose branches edit and re-save the file while the fallback passes it
  through untouched, so quiet turns cost nothing and the file cannot drift.
- **[Periodic Gating (Turn Counter)](Periodic_Gating.md)**: run an expensive or noisy step only once every N turns, on
  a batch of what happened since, deciding when to run with entirely deterministic nodes (no LLM call for the gating).
  Built from a counter file, `ArithmeticProcessor`, `Conditional`, and a `ConditionalCustomWorkflow`. Includes the
  weak-model caveat (batch list-generation can loop on small models).

## Related

Patterns lean heavily on nested workflows and conditional routing. See:

- [The `CustomWorkflow` Node](../Nodes/CustomWorkflow.md) and
  [The `ConditionalCustomWorkflow` Node](../Nodes/ConditionalCustomWorkflow.md): running a workflow from inside another.
- [The `Conditional` Node](../Nodes/Conditional.md): evaluating an expression to `TRUE`/`FALSE` for branching.
- [Nested Workflows](../../../Core_Features/Nested_Workflows.md) and
  [Recursive Workflows](../../../LLM_Assisted_Workflow_Generation/Recursive_Workflows.md): the mechanics and limits of
  workflows calling workflows.
