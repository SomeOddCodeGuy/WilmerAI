# WilmerAI Variables Reference

Variables use `{variable_name}` syntax in content fields. Enable `"jinja2": true` on a node for Jinja2 templating.

## Which Fields Support Variables

**Full variable support:** `prompt`, `systemPrompt`, `content`, `filepath`, `scoped_variables`, `promptToSearch`,
`strings` (in StringConcatenator), `expression`, `jsonToExtractFrom`, `fieldToExtract`, `tagToExtractFrom`, `input`
(VectorMemorySearch), `args`/`kwargs` (PythonModule).

**Limited variable support (only `{agent#Input}` and custom workflow vars, NOT `{agent#Output}`):**
`endpointName`, `preset`, `maxResponseSizeInTokens`.

**No variable support:** `type`, `workflowName`, `returnToUser`, `jinja2`, keys inside `conditionalWorkflows`.

## Custom Variables

Any top-level key in the workflow JSON (other than `nodes`) becomes a variable:

```json
{
  "persona": "You are a coding assistant.",
  "nodes": [{ "systemPrompt": "{persona}", ... }]
}
```

## Data Flow Variables

| Variable | Description |
|---|---|
| `{agent#Output}` | Output of node # in the current workflow (1-indexed). |
| `{agent#Input}` | Value passed from parent via `scoped_variables` (1-indexed). |

## Conversation History Variables

| Variable | Description |
|---|---|
| `{chat_user_prompt_last_one}` | Last message as raw text. Also: `_last_two`, `_last_three`, `_last_four`, `_last_five`, `_last_ten`, `_last_twenty`. |
| `{chat_user_prompt_n_messages}` | Last N messages (N set by node property `nMessagesToIncludeInVariable`, default 5). |
| `{chat_user_prompt_estimated_token_limit}` | Messages fitting within estimated token budget (set by `estimatedTokensToIncludeInVariable`, default 2048). |
| `{chat_user_prompt_min_n_max_tokens}` | At least N messages (set by `minMessagesInVariable`), expanding up to token budget (`maxEstimatedTokensInVariable`). |
| `{chat_system_prompt}` | The system prompt from the frontend. |
| `{chat_user_prompt_without_system}` | Full conversation (no system messages) as raw text. |
| `{messages}` | Full conversation as list of dicts. Most useful with Jinja2: `{% for m in messages %}`. |

Each `chat_user_prompt_*` variable has a `templated_user_prompt_*` counterpart that wraps messages in the LLM's chat template.

**Formatting options for `chat_user_prompt_*`:**
- Node-level `addUserAssistantTags` (bool): Prefix messages with `User: ` / `Assistant: `.
- User-level `separateConversationInVariables` + `conversationSeparationDelimiter`: Custom delimiter between messages.
- Node-level `includeToolCallsInConversation` (bool): Show `[Tool Call: {name}]` in blank assistant turns.

## Date and Time Variables

| Variable | Example |
|---|---|
| `{todays_date_pretty}` | "September 13, 2025" |
| `{todays_date_iso}` | "2025-09-13" |
| `{YYYY_MM_DD}` | "2025_09_13" (underscore format, good for filenames) |
| `{current_time_12h}` | "04:30 PM" |
| `{current_time_24h}` | "16:30" |
| `{current_month_full}` | "September" |
| `{current_day_of_week}` | "Saturday" |
| `{current_day_of_month}` | "13" |

## Context and Memory Variables

| Variable | Description |
|---|---|
| `{Discussion_Id}` | Current conversation identifier. Empty string if none. |
| `{time_context_summary}` | Natural language summary of conversation timeline. |

**Do NOT use `{current_chat_summary}`** -- it is defined but never populated. Use `GetCurrentSummaryFromFile` node instead.

## Special Placeholders (no curly braces)

These are replaced within specific node types, not by the general variable system:

- `[TextChunk]` -- text block in memory generation workflows
- `[IMAGE_BLOCK]` -- image description in `ImageProcessor.message`
- `[Memory_file]`, `[Full_Memory_file]`, `[Chat_Summary]` -- memory file content in memory workflows
- `[LATEST_MEMORIES]`, `[CHAT_SUMMARY]` -- used by `chatSummarySummarizer`

## Important: User-Defined Variables Are Limited

You can only create constants (top-level keys in the workflow JSON). You cannot create dynamically-named variables.
A variable like `{my_custom_runtime_value}` will not work unless it is a key defined at the top of the workflow file
with a static value or a reference to another valid variable.
