### **Project Overview: WilmerAI**

WilmerAI is a middleware system that acts as a powerful orchestration engine between front-end applications and various
Large Language Model (LLM) backends. It allows you to build complex, multi-step AI behaviors using a node-based workflow
system, all while presenting a simple, industry-standard API to your existing tools.

Instead of being a single model, WilmerAI is a highly configurable engine that lets you chain together different models,
tools, and memory systems to process a single user request.

---

## The Core Concept: The Workflow Engine

At the heart of WilmerAI is a **node-based workflow engine**. A workflow is a JSON file that defines a sequence of
steps, or "nodes," to be executed in order. This allows you to create sophisticated logic that goes far beyond a simple
single-LLM response.

* **Nodes as Building Blocks:** Each node in a workflow performs a specific task, such as calling an LLM, searching a
  database, running a Python script, or retrieving conversational memory.
* **Sequential Data Flow:** The output of one node is automatically made available to all subsequent nodes. For example,
  the first node could extract keywords from a user's prompt, and the second node could use those keywords to perform a
  vector memory search. The third node could then take the search results and the original prompt to generate a final,
  context-aware answer.
* **Flexibility and Control:** This architecture gives you precise control over the entire request-response lifecycle,
  allowing for the creation of specialized agents, Retrieval-Augmented Generation (RAG) pipelines, and dynamic,
  multi-tool automations.

---

## Key Capabilities

WilmerAI integrates several powerful features into its workflow engine, enabling you to build highly customized and
intelligent systems.

### Adaptable API Gateway

WilmerAI emulates the APIs of popular services like **OpenAI** and **Ollama**. This allows you to connect your existing
front-end applications (such as OpenWebUI or SillyTavern) directly to WilmerAI without any code changes. The client
application believes it is communicating with a standard LLM service, while WilmerAI orchestrates complex workflows in
the background.

### Flexible Backend Connections

You are not locked into a single LLM provider. WilmerAI's **Adaptable LLM Connector** can interface with any LLM
backend, including local models via Ollama or KoboldCpp and cloud services from OpenAI. Furthermore, different nodes
within a single workflow can be configured to use different models, allowing you to optimize for cost, speed, and
capability at each step of a process.

### Advanced Routing and Logic

WilmerAI provides two layers of routing for creating dynamic and adaptable agents:

1. **Prompt Routing:** An initial routing engine can analyze the user's intent and direct the incoming request to the
   most appropriate workflow. For example, it can automatically send coding questions to a coding-specific workflow and
   factual queries to a research-focused one.
2. **In-Workflow Routing:** Within a workflow, conditional "if/then" logic can be implemented. A node can make a
   decision based on the output of a previous step and execute a specific sub-workflow, enabling non-linear execution
   paths.

### Modular and Reusable Workflows

Workflows can be nested, allowing you to build a task once and reuse it anywhere. A common process, such as summarizing
text or searching a database, can be encapsulated in its own "child" workflow. This child workflow can then be called as
a single node from any "parent" workflow, simplifying design and eliminating redundant logic.

### Stateful Conversation Memory

WilmerAI includes a robust, three-part memory system to provide long-term context for conversations. By including a
`[DiscussionId]` in your request, you can enable:

* **Long-Term Memory File:** Chronological, summarized chunks of the conversation.
* **Rolling Chat Summary:** A continuously updated high-level summary of the entire discussion.
* **Searchable Vector Memory:** A dedicated vector database for the discussion, allowing for efficient semantic search
  to retrieve relevant information.

### External Tool Integration

The workflow engine can be extended with custom tools. This includes nodes for running local Python scripts or
connecting to external services. A built-in example is the **Offline Wikipedia Integration**, which allows a workflow to
query a local Wikipedia database to provide factual context for a response.

---

## How It All Works: A Typical Request Flow

1. **Standard API Request:** A client application sends a request to one of WilmerAI's API endpoints (e.g.,
   `/v1/chat/completions`) in a standard format.
2. **Workflow Selection:** The engine receives the request. If configured, the **Prompt Routing** engine analyzes the
   prompt's intent to select the most appropriate workflow file.
3. **Node Execution:** The **Workflow Engine** begins executing the nodes defined in the selected workflow, one by one.
4. **Orchestration:** As the workflow runs, nodes might call different LLMs, query the vector memory database for
   relevant context, execute a nested sub-workflow for a specialized task, or run a Python script. The output from each
   step is passed along for the next step to use.
5. **Response Generation:** One node in the workflow is designated as the "responder." Its final output is captured by
   the engine.
6. **Formatted API Response:** WilmerAI formats the responder's output into the API schema the original client
   application expects (e.g., an OpenAI-compliant JSON object) and sends it back, completing the cycle.