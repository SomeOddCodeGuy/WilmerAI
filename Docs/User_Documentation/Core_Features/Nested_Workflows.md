### **Feature Guide: Custom Nested Workflows**

Are your workflows becoming overly complex? Do you find yourself rebuilding the same logic for common tasks? WilmerAI’s
**Custom Nested Workflows** feature allows you to run one workflow as a single, reusable step inside another.

-----

## How It Works: Parent and Child Orchestration

At a high level, the process involves a **Parent** workflow calling a self-contained **Child** workflow. The Parent
orchestrates the overall task, while the Child executes a specific, reusable piece of logic.

A typical flow looks like this:

1. **Node Insertion:** A **Parent** workflow contains a special "Custom Workflow" node.
2. **Child Assignment:** This node points to a **Child** workflow file (e.g., `Summarize.json`).
3. **Data Transfer:** The Parent can pass specific information to the Child, such as the output from a previous step in
   the Parent's sequence.
4. **Isolated Execution:** The Child workflow runs completely from start to finish in an isolated environment.
5. **Result Return:** The final result from the Child is sent back to the Parent, which can then use this result in its
   subsequent steps.

A nested workflow can either run "silently" in the background (where its output is used internally by the parent) or it
can be designated as the "responder" to provide the final output directly to the user.

-----

## Key Benefits of Nested Workflows

Using this feature allows you to create more organized, efficient, and powerful automations.

* **Reusability**: Build common tasks (like searching a database, summarizing text, or categorizing input) as a
  standalone workflow. You can then call this "sub-workflow" from anywhere, saving you from duplicating logic.

* **Simplicity**: Break down a massive, complex 20-step process into smaller, logical parts. For example, a "Research
  Assistant" workflow could be composed of three sub-workflows: `1. Plan_Research_Strategy`, `2. Execute_Web_Searches`,
  and `3. Synthesize_Findings`. This makes the parent workflow much easier to read and manage.

* **Orchestration**: Create high-level "orchestrator" workflows that don't perform tasks themselves, but instead call a
  series of specialized sub-workflows in the correct order, passing data between them to accomplish a complex goal.