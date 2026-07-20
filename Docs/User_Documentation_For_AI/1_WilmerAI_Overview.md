# WilmerAI Overview for LLMs

## What WilmerAI Is

WilmerAI is middleware between a frontend (chat UI, coding assistant, etc.) and LLM backends. It exposes
OpenAI-compatible and Ollama-compatible API endpoints. Internally, it runs a **workflow**: a JSON file defining a
sequence of **nodes** that execute top-to-bottom. Each node does one thing: call an LLM, search memory, run a script,
extract data, etc. The output of each node is available to all subsequent nodes.

The final node's output (or whichever node is designated the responder) is returned to the frontend as if WilmerAI were
a normal LLM.

## Endpoints

WilmerAI serves:

- `/v1/chat/completions`: OpenAI chat completions. The frontend sends a messages array; WilmerAI runs the workflow.
- `/v1/completions`, `/api/generate`: Text/Ollama completion. Requires tag-formatted prompt:
  `[Beg_Sys]system text[Beg_User]username: msg[Beg_Assistant]assistant: msg[Beg_User]username: next msg[Beg_Assistant]`
- `/v1/models`, `/api/tags`: Lists available workflows as selectable "models."

Generation parameters (temperature, top_k, etc.) are controlled per-node via **presets**, not by the frontend.

## Workflow Selection and Routing

- **Model field routing**: The frontend's `model` field selects a workflow. Format: `username:workflow-name` or just
  `workflow-name`. Workflows in `_shared/` folders (containing `_DefaultWorkflow.json`) appear in the models list.
- **Prompt routing**: An optional routing engine analyzes user intent and dispatches to the appropriate workflow.
- **In-workflow routing**: `ConditionalCustomWorkflow` nodes branch to different sub-workflows based on prior node output.

## Configuration Structure

```
Public/Configs/
  ApiTypes/        # API schema definitions (OpenAI, Ollama, etc.)
  Endpoints/       # LLM connection configs (URL, API type, model name)
  Presets/         # Generation parameters (temperature, top_k, etc.)
  PromptTemplates/ # Chat templates for different model families
  Routing/         # Prompt router config (domains -> workflows)
  Users/           # Per-user settings (port, paths, features)
  Workflows/       # Workflow JSON files
    _shared/       # Shared workflows listed by models endpoint
    <username>/    # User-specific workflows
```

Each workflow node specifies an `endpointName` (which LLM to call) and optionally a `preset` (generation params).
These are **references to JSON config filenames** (without `.json`) that the user has created in those directories.
For example, `"endpointName": "My-Claude-Endpoint"` refers to `Public/Configs/Endpoints/<subdirectory>/My-Claude-Endpoint.json`,
where `<subdirectory>` is the user's `endpointConfigsSubDirectory` setting (e.g. `_shared` for the default `chat-ui` user).
When writing workflows, use endpoint and preset names the user has already defined, or ask them what names to use.

## Multi-User Mode

Start with multiple `--User` flags. All users share one instance and concurrency gate. The models endpoint aggregates
workflows from all users. Requests route to the correct user via the model field (`user-two:coding`).

## Workflow JSON Structure

```json
{
  "my_custom_var": "Reusable text or persona definition",
  "nodes": [
    {
      "title": "Step 1",
      "type": "NodeType",
      ...
    },
    {
      "title": "Step 2",
      "type": "Standard",
      "systemPrompt": "{my_custom_var}",
      "prompt": "Context from step 1: {agent1Output}\n\nUser said: {chat_user_prompt_last_one}"
    }
  ]
}
```

- Top-level keys (other than `nodes`) become custom variables usable in content fields as `{key_name}`.
- Node outputs are `{agent1Output}`, `{agent2Output}`, etc. (1-indexed by position).
- Child workflows (called via `CustomWorkflow` node) receive data through `scoped_variables`, accessed as
  `{agent1Input}`, `{agent2Input}`, etc. Child workflows cannot see parent `{agent#Output}` values.

## Responder Node

The last node in the top-level workflow automatically becomes the responder (its output goes to the frontend). You
rarely need `"returnToUser": true`; that flag overrides the default and is only for niche cases where you want a
mid-workflow node to respond while later nodes continue running (e.g., memory generation after response).

## Tool Call Passthrough

Set `"allowTools": true` on the responding `Standard` node to forward tool definitions from the frontend to the backend
LLM and relay tool call responses back. Only useful on the responding node. Add `"lowercaseToolCallFunctionNames": true`
if the backend LLM produces capitalized function names (common with local models like Gemma and Qwen).

For multi-round tool loops through authored-prompt responders, add `"appendNativeToolExchange": true` (delivers the
trailing tool exchange natively). On backends declaring a `structuredOutput` mechanism in their ApiType, demanded
calls (`tool_choice` forced/`"required"`) are grammar-enforced automatically, and `"structuredOutputFile"` pins any
node's output to a JSON Schema from `Configs/StructuredOutputs/`. See 2_Features_Reference for details.

---

## Example Workflows

### Example 1: Simple Chat Passthrough

The simplest useful workflow. Sends the conversation directly to an LLM with no processing.

```json
{
  "nodes": [
    {
      "title": "Chat with User",
      "type": "Standard",
      "endpointName": "My-LLM-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "You are a helpful assistant.",
      "prompt": "",
      "lastMessagesToSendInsteadOfPrompt": 20,
      "maxResponseSizeInTokens": 4000,
      "maxContextTokenSize": 16000
    }
  ]
}
```

When `prompt` is empty, the node sends the raw conversation history to the LLM (last 20 turns here). The single node
is automatically the responder.

### Example 2: Memory-Augmented Conversation

Searches vector memory for relevant context, retrieves the chat summary, then responds with both injected.

```json
{
  "persona": "You are a knowledgeable assistant with long-term memory. Use the provided context to inform your response.",
  "nodes": [
    {
      "title": "Generate Search Keywords",
      "type": "Standard",
      "endpointName": "Fast-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "Extract 3-5 search keywords from the user's message. Output only the keywords separated by semicolons.",
      "prompt": "{chat_user_prompt_last_one}",
      "maxResponseSizeInTokens": 100
    },
    {
      "title": "Search Memory",
      "type": "VectorMemorySearch",
      "input": "{agent1Output}",
      "limit": 5
    },
    {
      "title": "Get Chat Summary",
      "type": "GetCurrentSummaryFromFile"
    },
    {
      "title": "Respond to User",
      "type": "Standard",
      "endpointName": "Main-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "{persona}\n\nConversation summary:\n{agent3Output}\n\nRelevant memories:\n{agent2Output}",
      "prompt": "",
      "lastMessagesToSendInsteadOfPrompt": 10,
      "maxResponseSizeInTokens": 4000,
      "maxContextTokenSize": 16000
    }
  ]
}
```

Node 4 is the last node, so it automatically responds to the user. Its `systemPrompt` injects the search results
(`{agent2Output}`) and summary (`{agent3Output}`). Its empty `prompt` sends the actual conversation.

### Example 3: Categorize-Then-Route with Child Workflows

Analyzes the user's intent, then routes to a specialized sub-workflow.

```json
{
  "nodes": [
    {
      "title": "Categorize User Intent",
      "type": "Standard",
      "endpointName": "Fast-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "Categorize the user's message into exactly one of: Coding, Research, Creative. Output only the category name.",
      "prompt": "{chat_user_prompt_last_one}",
      "maxResponseSizeInTokens": 20
    },
    {
      "title": "Route to Specialist",
      "type": "ConditionalCustomWorkflow",
      "conditionalKey": "{agent1Output}",
      "conditionalWorkflows": {
        "Coding": "CodingWorkflow",
        "Research": "ResearchWorkflow",
        "Creative": "CreativeWorkflow",
        "Default": "GeneralWorkflow"
      },
      "scoped_variables": [
        "{agent1Output}"
      ],
      "returnToUser": true
    }
  ]
}
```

The child workflow (e.g., `CodingWorkflow.json`) receives `{agent1Output}` as `{agent1Input}`.

### Example 4: Parent/Child Data Passing with scoped_variables

**Parent workflow (`main.json`):**
```json
{
  "nodes": [
    {
      "title": "Analyze User Request",
      "type": "Standard",
      "endpointName": "Fast-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "Summarize what the user is asking for in one sentence.",
      "prompt": "{chat_user_prompt_last_three}",
      "maxResponseSizeInTokens": 200
    },
    {
      "title": "Call Helper Workflow",
      "type": "CustomWorkflow",
      "workflowName": "helper_respond",
      "scoped_variables": [
        "{agent1Output}",
        "You are a helpful assistant."
      ]
    }
  ]
}
```

**Child workflow (`helper_respond.json`):**
```json
{
  "nodes": [
    {
      "title": "Respond Using Parent Context",
      "type": "Standard",
      "endpointName": "Main-Endpoint",
      "preset": "Default-Preset",
      "systemPrompt": "{agent2Input}\n\nContext from analysis: {agent1Input}",
      "prompt": "",
      "lastMessagesToSendInsteadOfPrompt": 10,
      "maxResponseSizeInTokens": 4000
    }
  ]
}
```

The child cannot see the parent's `{agent1Output}`. It receives data only through `scoped_variables`:
- `{agent1Input}` = the analysis from the parent's first node
- `{agent2Input}` = the string "You are a helpful assistant."

The child's final node is the last node in the overall execution, so it automatically responds to the user.
