### **Developer Guide: Context Compactor**

This guide provides a deep dive into the architecture and implementation of the Context Compactor feature. The Context
Compactor is a workflow node that directly summarizes conversation messages into two rolling summaries, separate from the
existing memory system. It uses token-based windowing to divide conversations into Recent, Old, and Oldest sections,
then generates and persists summaries for the Old and Oldest sections via LLM calls.

-----

## 1\. Overview

The Context Compactor exists as an alternative to the memory system for maintaining conversational context. Where the
memory system creates discrete memory chunks and rolling chat summaries through a multi-service pipeline
(`SlowButQualityRAGTool`, `MemoryService`), the Context Compactor operates as a single self-contained handler that
directly manages its own windowing, summarization, and file persistence.

The core idea is a sliding window over the conversation history, divided into three zones:

- **Recent**: The most recent messages, left untouched. These are passed directly in the conversation context.
- **Old**: A configurable token window of messages at medium distance from the conversation's end. These are summarized
  with a topic-focused prompt that uses the Recent messages as context for relevance.
- **Oldest**: Everything before the Old window. These are maintained as a rolling neutral summary that grows as the Old
  window slides forward.

The handler produces XML-tagged output compatible with `TagTextExtractor` for downstream extraction in workflows.

-----

## 2\. Key Files

| File | Responsibility |
|------|----------------|
| `Middleware/workflows/handlers/impl/context_compactor_handler.py` | The handler class (`ContextCompactorHandler`). Contains all windowing, trigger, LLM call, and persistence logic. |
| `Middleware/utilities/config_utils.py` | Config utility functions: `get_context_compactor_settings_name`, `get_context_compactor_settings_path`, `get_discussion_context_compactor_old_file_path`, `get_discussion_context_compactor_oldest_file_path`. |
| `Middleware/common/constants.py` | Node type registration. `"ContextCompactor"` is listed in `VALID_NODE_TYPES`. |
| `Middleware/workflows/managers/workflow_manager.py` | Handler registration. `ContextCompactorHandler` is instantiated and mapped to the `"ContextCompactor"` type string in the `node_handlers` dictionary. |
| `Tests/workflows/handlers/impl/test_context_compactor_handler.py` | Unit tests covering all handler behavior. |

-----

## 3\. Architecture

### Handler Registration

`ContextCompactorHandler` inherits from `BaseHandler`. Unlike memory nodes (routed through `MemoryNodeHandler`) or
specialized nodes (routed through `SpecializedNodeHandler`), the Context Compactor is registered as a standalone handler
directly in `WorkflowManager.__init__()`:

```python
context_compactor_handler = ContextCompactorHandler(**common_dependencies)
# ...
self.node_handlers = {
    # ...
    "ContextCompactor": context_compactor_handler,
}
```

This means the `WorkflowProcessor` dispatches directly to `ContextCompactorHandler.handle()` without any intermediate
routing layer.

### Dependencies

The handler uses three external dependencies:

- **`LlmHandlerService`**: Instantiated in the handler's `__init__`. Creates temporary LLM handlers for each call via
  `load_model_from_config()`.
- **`read_chunks_with_hashes` / `update_chunks_with_hashes`** from `file_utils`: Used for reading and writing the
  persisted state files. State is stored as lists of `(text_block, hash)` tuples serialized to JSON.
- **`rough_estimate_token_length`** from `text_utils`: Used for token estimation during boundary calculation. This
  function intentionally overestimates by ~10% for safety (using the higher of word-based and character-based estimates,
  then applying a 1.10 safety margin).

### Config Utilities

Four functions in `config_utils.py` support the Context Compactor:

- `get_context_compactor_settings_name()`: Reads the `contextCompactorSettingsFile` value from the user's config.
- `get_context_compactor_settings_path()`: Resolves that name to a full file path via `get_workflow_path()`.
- `get_discussion_context_compactor_old_file_path(discussion_id)`: Returns the path for the Old section state file,
  using `get_discussion_file_path(discussion_id, 'context_compactor_old')`.
- `get_discussion_context_compactor_oldest_file_path(discussion_id)`: Returns the path for the Oldest section state
  file, using `get_discussion_file_path(discussion_id, 'context_compactor_oldest')`.

-----

## 4\. Execution Flow

The `handle(context)` method follows this sequence:

1. **Load settings**: Calls `_load_settings()`, which reads the context compactor settings file specified by
   `contextCompactorSettingsFile` in the user's config. Returns early with an empty string if settings cannot be loaded.

2. **Validate discussion ID**: Returns early with an empty string if `context.discussion_id` is `None`.

3. **Apply lookback**: Slices `context.messages` to exclude the last `lookbackStartTurn` messages from the working
   set. This prevents recent, potentially incomplete exchanges from being summarized. If fewer than 2 messages remain
   after the trim, returns cached output (or empty string).

4. **Calculate boundaries**: Calls `_calculate_boundaries()` to determine the token-based window indices that divide the
   working messages into Recent, Old, and Oldest sections.

5. **Load existing state**: Reads the persisted Old and Oldest section files via `_load_state()`.

6. **Check triggers**: Calls `_should_compact()` to determine whether a compaction cycle should run and whether the
   boundary has shifted. If no compaction is needed, returns cached output.

7. **Run compaction**: Calls `_run_compaction()`, which makes up to 3 LLM calls depending on whether the boundary
   shifted.

8. **Return output**: Calls `_return_cached_output()` to read the now-updated state files and return formatted output.

-----

## 5\. Token-Based Windowing

The `_calculate_boundaries()` method determines which messages belong to which section. It walks backwards from the end
of the working message list:

1. **Recent window**: Starting from the last message, accumulates token counts (via `rough_estimate_token_length()`)
   until the `recentContextTokens` budget is exceeded. The index where this happens becomes `recent_start_idx`.
   Messages from `recent_start_idx` to the end are in the Recent section.

2. **Old window**: Continuing backwards from `recent_start_idx - 1`, accumulates token counts until the
   `oldContextTokens` budget is exceeded. The index where this happens becomes `old_start_idx`. Messages from
   `old_start_idx` to `recent_start_idx - 1` are in the Old section.

3. **Oldest territory**: Everything before `old_start_idx` falls into Oldest territory.

If all messages fit within the Recent budget, `recent_start_idx` is 0 and there is nothing to compact. If all remaining
messages fit within the Old budget, `old_start_idx` is 0 and there is no Oldest territory yet.

The method returns a dictionary:

```python
{
    "recent_start_idx": <int>,
    "old_start_idx": <int>,
}
```

-----

## 6\. Trigger Mechanism

The `_should_compact()` method returns a tuple of `(should_compact: bool, has_boundary_shifted: bool)`. It evaluates
these conditions in order:

1. **Empty Old window**: If `old_start_idx >= recent_start_idx`, the conversation is too short to have an Old section.
   Returns `(False, False)`.

2. **First run**: If no existing Old state is loaded (empty list), this is the first compaction. Returns
   `(True, False)`. Note that `has_boundary_shifted` is `False` on first run because there is no previous boundary to
   have shifted from.

3. **Boundary shifted**: Compares the stored hash of the old boundary message (from the `__boundary__` marker in the Old
   state file) against the hash of the current message at `old_start_idx`. If they differ, the window has moved and
   messages have shifted from Old into Oldest territory. Returns `(True, True)`.

4. **Content changed**: Compares the stored hash of the recent boundary message (from the first entry in the Old state
   file) against the hash of the current message at `recent_start_idx - 1`. If they differ, the content of the Old
   window has changed (new messages entered the Old window from the Recent side). Returns `(True, False)`.

5. **No changes**: Returns `(False, False)`.

When `has_boundary_shifted` is `True`, all 3 LLM calls run during compaction. Otherwise, only Call 1 (Old section
regeneration) runs.

-----

## 7\. Compaction: LLM Calls

The `_run_compaction()` method executes up to three LLM calls:

### Call 1: `_generate_old_section()`

Always runs. Generates a topic-focused summary of the Old window messages. The prompt receives both the Old messages
(via `[MESSAGES_TO_SUMMARIZE]` placeholder) and the Recent messages (via `[RECENT_MESSAGES]` placeholder). The Recent
messages serve as topic context so the summary emphasizes details relevant to the current conversation direction.

Uses `oldSectionSystemPrompt` and `oldSectionPrompt` from settings.

### Call 2: `_generate_neutral_summary()`

Runs only when `has_boundary_shifted` is `True` and `old_start_idx > 0`. Generates a neutral (non-topic-biased) summary
of the messages that newly shifted from Old into Oldest territory. The handler locates the previous Old boundary position
by searching the messages for a content hash matching the stored boundary hash from the old state file. Only messages
between the previous boundary position and the current `old_start_idx` are sent to the LLM, not all pre-Old messages.

Uses `neutralSummarySystemPrompt` and `neutralSummaryPrompt` from settings. The prompt receives the shifted messages via
`[MESSAGES_TO_SUMMARIZE]` placeholder.

### Call 3: `_update_oldest_section()`

Runs only when Call 2 runs. Incorporates the neutral summary from Call 2 into the existing Oldest rolling summary. If no
existing Oldest summary exists, the prompt receives an empty string for the existing summary.

Uses `oldestUpdateSystemPrompt` and `oldestUpdatePrompt` from settings. The prompt receives the existing summary via
`[EXISTING_SUMMARY]` placeholder and the new neutral summary via `[NEW_CONTENT]` placeholder.

### LLM Call Mechanism

The `_call_llm()` method creates a fresh `LlmHandler` via `LlmHandlerService.load_model_from_config()` for each call,
using the `endpointName`, `preset`, and `maxResponseSizeInTokens` from the settings file. It checks
`llm_handler.takes_message_collection` to determine the calling convention:

- **Message collection mode** (`takes_message_collection is True`): Constructs a list of `{"role": "system", ...}` and
  `{"role": "user", ...}` dicts and passes them as the first positional argument.
- **Completions mode** (`takes_message_collection is False`): Passes `system_prompt` and `prompt` as keyword arguments.

Both paths pass `llm_takes_images=False` and `request_id=context.request_id`.

-----

## 8\. File Storage Format

Two files are persisted per discussion, following the existing `_chat_summary.json` pattern used by
`read_chunks_with_hashes` / `update_chunks_with_hashes`. Files are written with `mode="overwrite"`, meaning the entire
file is replaced on each save.

### Old Section File (`{id}_context_compactor_old.json`)

```json
[
  {"text_block": "The topic-focused summary text...", "hash": "<hash of recent boundary message>"},
  {"text_block": "__boundary__", "hash": "<old_start_idx>:<hash of old boundary message>"}
]
```

The first entry contains the actual summary. Its hash is the SHA-256 of the content of the message at
`recent_start_idx - 1`, used for content-change detection.

The second entry is a boundary marker. Its hash is stored in `index:hash` format (e.g., `"5:abc123def..."`), where the
index is the value of `old_start_idx` at the time of writing and the hash is the SHA-256 of the content of the message
at that index. This format is used for boundary-shift detection. On load, the code first tries to split on `:` to
extract the index directly; if no `:` is found (legacy entries), it falls back to scanning the conversation for a
content match.

### Oldest Section File (`{id}_context_compactor_oldest.json`)

```json
[
  {"text_block": "The rolling neutral summary text...", "hash": "<hash of earliest message>"}
]
```

A single entry containing the rolling neutral summary. Its hash is the SHA-256 of the content of `messages[0]`.

-----

## 9\. Output Format

The `_return_cached_output()` method reads both state files and delegates to `_format_output()`, which returns an
XML-tagged string:

```xml
<context_compactor_old>Topic-focused summary of the Old window...</context_compactor_old>
<context_compactor_oldest>Rolling neutral summary of all Oldest messages...</context_compactor_oldest>
```

Either section may be absent if its summary is empty. If both are empty, an empty string is returned.

The `__boundary__` marker in the Old state file is skipped during output formatting -- only the first non-boundary entry
is used as the Old summary.

This output format is compatible with `TagTextExtractor` for downstream extraction in workflows. A workflow can use a
`TagTextExtractor` node to extract the `context_compactor_old` or `context_compactor_oldest` content by tag name.

-----

## 10\. Settings File Reference

The settings file is a JSON file located in the user's workflow folder. It is referenced via
`contextCompactorSettingsFile` in the user's config file.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `endpointName` | string | (required) | The LLM endpoint to use for summarization calls. |
| `preset` | string | (required) | The preset configuration for the LLM endpoint. |
| `maxResponseSizeInTokens` | int | 750 | Maximum token count for each LLM response. |
| `recentContextTokens` | int | 20000 | Token budget for the Recent section window. |
| `oldContextTokens` | int | 20000 | Token budget for the Old section window. |
| `lookbackStartTurn` | int | 5 | Number of most recent messages to skip before processing. Prevents incomplete exchanges from being summarized. |
| `oldSectionSystemPrompt` | string | "You are a summarization AI." | System prompt for LLM Call 1 (Old section). |
| `oldSectionPrompt` | string | "[MESSAGES_TO_SUMMARIZE]" | User prompt template for LLM Call 1. Supports `[MESSAGES_TO_SUMMARIZE]` and `[RECENT_MESSAGES]` placeholders. |
| `neutralSummarySystemPrompt` | string | "You are a summarization AI." | System prompt for LLM Call 2 (neutral summary). |
| `neutralSummaryPrompt` | string | "[MESSAGES_TO_SUMMARIZE]" | User prompt template for LLM Call 2. Supports `[MESSAGES_TO_SUMMARIZE]` placeholder. |
| `oldestUpdateSystemPrompt` | string | "You are a summarization AI." | System prompt for LLM Call 3 (Oldest update). |
| `oldestUpdatePrompt` | string | "[EXISTING_SUMMARY]\n\n[NEW_CONTENT]" | User prompt template for LLM Call 3. Supports `[EXISTING_SUMMARY]` and `[NEW_CONTENT]` placeholders. |

### Prompt Placeholders

- `[MESSAGES_TO_SUMMARIZE]`: Replaced with the formatted text of the messages to be summarized. Messages are formatted
  as `role: content` lines joined by newlines.
- `[RECENT_MESSAGES]`: Replaced with the formatted text of the Recent section messages (Call 1 only).
- `[EXISTING_SUMMARY]`: Replaced with the current Oldest rolling summary text (Call 3 only).
- `[NEW_CONTENT]`: Replaced with the neutral summary of shifted messages (Call 3 only).

-----

## 11\. Testing

Tests are located in `Tests/workflows/handlers/impl/test_context_compactor_handler.py`. All LLM calls are mocked. The
test file uses helper functions `_hash()` (mirrors the handler's SHA-256 hashing) and `_make_messages()` (generates
alternating user/assistant messages with controllable token sizes).

### Test Classes

| Class | Coverage |
|-------|----------|
| `TestCalculateBoundaries` | Boundary calculation: all-recent, two-section split, three-section split, empty messages. |
| `TestShouldCompact` | Trigger conditions: first run, empty Old window, boundary shifted, recent hash changed, no changes. |
| `TestHandle` | Integration of the full `handle()` method: no settings, no discussion ID, short conversation, first compaction, cached return. |
| `TestRunCompaction` | LLM call counts: without boundary shift (1 call), with boundary shift (3 calls), shift with no oldest messages (1 call). |
| `TestGenerateOldSection` | Placeholder replacement for `[MESSAGES_TO_SUMMARIZE]` and `[RECENT_MESSAGES]`. |
| `TestGenerateNeutralSummary` | Placeholder replacement for `[MESSAGES_TO_SUMMARIZE]`. |
| `TestUpdateOldestSection` | Placeholder replacement for `[EXISTING_SUMMARY]` and `[NEW_CONTENT]`. |
| `TestCallLlm` | Both calling conventions: message collection mode and completions mode. |
| `TestFormatOutput` | Output formatting: both sections, one section only, both empty. |
| `TestMessagesToText` | Message-to-text conversion. |
| `TestHashMessageContent` | Hash consistency and uniqueness. |
| `TestLookbackSkipping` | Lookback behavior: skipping last N messages, zero lookback uses all messages. |
| `TestFilePersistence` | File save and load operations for both Old and Oldest sections with correct paths. |
| `TestReturnCachedOutput` | Cached output: formatted output, empty data, boundary marker skipping. |

-----

## 12\. Relationship to the Memory System

The Context Compactor and the memory system (`QualityMemory`, `RecentMemory`, `FullChatSummary`, etc.) are independent
features. They do not share state or files. Key differences:

- **Memory system**: Creates discrete memory chunks appended to a ledger (`_memories.json`), plus a rolling chat
  summary (`_chat_summary.json`). Uses `SlowButQualityRAGTool` for creation and `MemoryService` for retrieval. Routed
  through `MemoryNodeHandler`.
- **Context Compactor**: Creates two rolling summaries (`_context_compactor_old.json` and
  `_context_compactor_oldest.json`). Manages everything internally within a single handler class. Registered directly
  in `WorkflowManager`.

Both can coexist in the same workflow. The Context Compactor does not read from or write to memory files, and the memory
system does not read from or write to context compactor files.

-----

## 13\. How to Extend

### Modify Windowing Strategy

Adjust `_calculate_boundaries()`. The current implementation walks backwards from the end with simple token
accumulation. Alternative strategies could include message-count-based windows, time-based windows, or hybrid
approaches. The method must return a dict with `recent_start_idx` and `old_start_idx` keys.

### Add or Change Trigger Conditions

Modify `_should_compact()`. The method returns `(should_compact, has_boundary_shifted)`. Additional triggers could
include time-based thresholds, token-count thresholds on the Old window content, or external signals. The
`has_boundary_shifted` flag controls whether Calls 2 and 3 run.

### Change Summarization Behavior

Update the prompt templates in the settings file. The prompts control the style, format, and focus of the summaries. No
code changes are needed for prompt-level adjustments.

### Add New Sections

To add a third summary section beyond Old and Oldest:

1. Create a new file path function in `config_utils.py` following the pattern of
   `get_discussion_context_compactor_old_file_path`.
2. Add load/save logic in the handler using `_load_state` / `_save_state` with a new section name.
3. Extend `_run_compaction()` with additional LLM calls and persistence for the new section.
4. Update `_format_output()` to include the new section in the XML-tagged output.
5. Add corresponding settings fields for the new section's prompts.

### Add New Settings Fields

Add the field to the settings file JSON. Read it in the handler via `settings.get("fieldName", default_value)`. No
registration in `config_utils.py` is needed -- settings fields are read directly from the loaded settings dict.
