### **A Generic Framework for Recursive Workflows**

This document serves as a guide on how Recursive Workflows can be generated within WilmerAI. The steps and structure
given are an example of a working and functional recursive workflow. Recursive workflows are not limited to this
structure, can become more complex as necessary. But this guide can serve as a starting point to understanding exactly
how an existing recursive flow is set up.

----

A recursive workflow pattern in this system involves a "Core" workflow that calls itself repeatedly to process or refine
data over multiple passes. This pattern is ideal for tasks that require breaking a complex problem into smaller,
repeatable steps, such as iterative refinement, deep analysis, or multi-step tool use.

The pattern relies on three distinct workflows:

1. **Workflow A: The Main Orchestrator**
2. **Workflow B: The Recursive Core**
3. **Workflow C: The Final Processor**

#### **Visual Flow**

```
[Start] -> [A: Orchestrator] -> [B: Recursive Core] --(loops)--> [B: Recursive Core] --(exits)--> [C: Final Processor] -> [A: Orchestrator] -> [End]
```

> Important Note: When crafting a recursive workflow, creating one that actually works is the paramount objective.
> If a user requests a workflow structure that is irreconcilable with the structure a recursive workflow should
> follow, be sure to prompt the user and discuss before continuing.
>
> Ultimately, the objective will likely be to try to achieve the *spirit* of what the user is asking, while maintaining
> the appropriate structure necessary to run the recursion.

-----

### **1. Workflow A: The Main Orchestrator**

This workflow's job is to initialize the process and handle the final result. It does not contain any looping logic
itself.

**Key Responsibilities:**

* Receives the initial input/problem statement from an external source.
* Initializes the state variables required for the loop.
* Makes the *first* call to the `Recursive Core` workflow.
* Receives the final, processed result from the recursive chain and returns it as the final output.

**Structure:**

* **Node 1: Initialize Counter**

    * **Type:** `StaticResponse`
    * **Purpose:** Sets the starting value for the iteration counter.
    * **Content:** `"0"`

* **Node 2: Initialize Accumulator**

    * **Type:** `StaticResponse`
    * **Purpose:** Creates a variable to hold the combined results from every loop.
    * **Content:** A placeholder string like `"Initial State"` or an empty string.

* **Node 3: Call the Recursive Core**

    * **Type:** `CustomWorkflow`
    * **Purpose:** To kick off the iterative process.
    * **`workflowName`:** The name of your `Recursive Core` workflow (Workflow B).
    * **`scoped_variables`:** This is critical. It passes the initial state to the loop.
      ```json
      "scoped_variables": [
        "{agent1Input}",       // The original problem/data
        "{agent1Output}",      // The initial counter (0)
        "{agent2Output}"       // The initial accumulator
      ]
      ```

* **Node 4: Return Final Result**

    * **Type:** `StaticResponse` (or similar output node)
    * **Purpose:** To return the final, synthesized output from the entire process.
    * **`returnToUser`:** `true`
    * **`content`:** `"{agent3Output}"`

-----

### **2. Workflow B: The Recursive Core**

This is the heart of the pattern. It performs one unit of work and then decides whether to call itself again or to exit
the loop.

**Key Responsibilities:**

* Receives the current state (problem, counter, accumulator).
* Checks if a stop condition has been met.
* Performs a single processing step.
* Updates the state variables (increments counter, appends to accumulator).
* Branches to either call itself again with the *new* state or calls the `Final Processor` workflow.

**Structure:**

* **Node 1: Check Max Iterations**

    * **Type:** `Conditional`
    * **Purpose:** A safety valve to prevent infinite loops. Compares the current counter against a hardcoded maximum.
    * **`condition`:** `"{agent2Input} >= 4"` (assuming counter is the second input)

* **Node 2: Perform One Unit of Work**

    * **Type:** `Standard`, `CustomWorkflow`, or any other node.
    * **Purpose:** This is where you perform the actual task for a single iteration (e.g., call an LLM to analyze data,
      search a database, refine a query). It uses `{agent1Input}` (the problem) and `{agent3Input}` (the accumulator) as
      context.

* **Node 3: Decide to Continue or Stop**

    * **Type:** `Standard` or `Conditional`
    * **Purpose:** Analyzes the result from Node 2 to make a logical decision. For example, an LLM might determine if
      the task is complete and output `CONTINUE` or `STOP`.

* **Node 4: Increment Counter**

    * **Type:** `ArithmeticProcessor`
    * **`expression`:** `"{agent2Input} + 1"`

* **Node 5: Update Accumulator**

    * **Type:** `StringConcatenator`
    * **Purpose:** Appends the result of this pass (from Node 2) to the accumulated results from previous passes.
    * **`strings`:** `["{agent3Input}", "{agent2Output}"]`
    * **`delimiter`:** `"\n\n---\n\n"` (or any other separator)

* **Node 6: Evaluate Loop Condition**

    * **Type:** `Conditional`
    * **Purpose:** Combines the stop conditions into a final boolean `TRUE`/`FALSE`.
    * **`condition`:** `"{agent1Output} == FALSE AND {agent3Output} == CONTINUE"`
        * This checks that the max iteration limit has *not* been reached AND the logical check decided to continue.

* **Node 7: The Recursive Branch**

    * **Type:** `ConditionalCustomWorkflow`
    * **`conditionalKey`:** `"{agent6Output}"` (the result of the combined check)
    * **`conditionalWorkflows`:**
        * **`"TRUE"`:** The filename of **this same workflow** (`Recursive Core`). This is the recursive call.
        * **`"FALSE"`:** The filename of the `Final Processor` workflow (Workflow C). This is the exit path.
    * **`scoped_variables`:** Passes the **updated state** to the next step.
      ```json
      "scoped_variables": [
        "{agent1Input}",       // Original problem (usually unchanged)
        "{agent4Output}",      // The NEW, incremented counter
        "{agent5Output}"       // The NEW, updated accumulator
      ]
      ```

-----

### **3. Workflow C: The Final Processor**

This workflow runs only once after the loop has finished. Its job is to perform a final cleanup, synthesis, or
formatting step.

**Key Responsibilities:**

* Receives the fully populated `accumulator` variable, which contains the results of all iterations.
* Performs a final processing step (e.g., uses an LLM to summarize all the findings into a coherent answer).
* Returns a single, clean output string.

**Structure:**

* **Node 1: Final Synthesis**
    * **Type:** `Standard`
    * **Purpose:** To process the raw, accumulated data into a final, polished response.
    * **`systemPrompt`:** Instructs an LLM on how to synthesize the input.
    * **`prompt`:** `Please synthesize the following multi-pass data into a final report:\n\n{agent1Input}` (assuming
      the accumulator is the first input).
    * **`returnToUser`:** `true` (within the context of this sub-workflow).

> Important Note on Synthesis: While the best result from synthesis is passing as much history as possible between
> the loops, it is very important to be cognizant of context windows. This is especially true for coding tasks
>
> Code is very token heavy; it's not unheard of to imagine an LLM receiving 20,000+ tokens of code with a request. For
> many local LLMs, this is bordering on the edge of too many tokens to even use; passing the history
> of re-writes and edits would immediately break most local model context windows within 2-3 iterations.
> Even proprietary AI would start to suffer degradation after a few iterations.
>
> When determining what information to pass between loops, please take care to judge how much context one could
> reasonably assume would be involved with the overall request and response, and take care not to create a
> recursive workflow that would simply error out or degrade to uselessness in only a couple of loops.