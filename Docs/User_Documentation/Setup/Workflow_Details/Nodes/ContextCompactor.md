### **Context Compaction: The `ContextCompactor` Node**

The **`ContextCompactor`** node compacts conversation history into two rolling summaries that are returned as XML-tagged
text. It works independently from the memory system. Rather than summarizing memories (which are themselves summaries),
it directly summarizes conversation messages with recency awareness. The node divides the conversation into three
windows:

- **Recent**: The most recent messages, kept untouched as-is.
- **Old**: Medium-distance messages, summarized with topic awareness based on the Recent messages.
- **Oldest**: Far-back messages, maintained as a neutral rolling summary.

The summaries are persisted to disk per discussion and returned wrapped in XML-style tags, making them easy to extract
downstream with a `TagTextExtractor` node.

-----

#### **How It Works**

1. **Settings Loading:** The node loads its configuration from a separate settings file. The settings file name is
   specified via the `contextCompactorSettingsFile` field in the user config, and the file itself lives in the user's
   workflow folder.
2. **Lookback Skip:** The last N messages (configured by `lookbackStartTurn`) are skipped before calculating windows.
   This prevents the node from processing messages that are still actively being written.
3. **Boundary Calculation:** The remaining messages are divided into three sections using token-based windowing. Starting
   from the end and walking backwards, the node allocates `recentContextTokens` worth of messages to the Recent section,
   then `oldContextTokens` worth to the Old section. Everything before the Old section falls into Oldest territory.
4. **Compaction Trigger Check:** The node determines whether compaction is needed by checking three conditions: first
   run (no existing state), boundary shift (messages have moved from Old to Oldest since the last run), or new messages
   appearing in the Old window.
5. **LLM Summarization:** When compaction is triggered, up to three LLM calls are made:
   - **Call 1 (always):** Summarize the Old window messages, focused on the current topic as indicated by the Recent
     messages.
   - **Call 2 (boundary shift only):** Generate a neutral summary of messages that shifted from Old to Oldest.
   - **Call 3 (boundary shift only):** Incorporate the neutral summary into the existing rolling Oldest summary.
6. **State Persistence:** The Old and Oldest summaries are saved to separate JSON files keyed by discussion ID.
7. **Output Formatting:** The node returns the summaries wrapped in `<context_compactor_old>` and
   `<context_compactor_oldest>` XML tags.

-----

#### **Properties**

The node configuration itself is minimal. All substantive configuration lives in the settings file.

| Property   | Type   | Required | Default | Description                                                      |
|:-----------|:-------|:---------|:--------|:-----------------------------------------------------------------|
| **`type`** | String | Yes      | N/A     | Must be `"ContextCompactor"`.                                    |
| **`title`**| String | No       | `""`    | A descriptive name for the node, used for logging and debugging. |

-----

#### **Settings File Reference**

The settings file is a JSON file placed in the user's workflow folder. Its name is specified in the user config via the
`contextCompactorSettingsFile` field.

| Setting                          | Type    | Required | Default   | Description                                                                                                   |
|:---------------------------------|:--------|:---------|:----------|:--------------------------------------------------------------------------------------------------------------|
| **`endpointName`**               | String  | Yes      | N/A       | The LLM endpoint to use for summarization calls.                                                              |
| **`preset`**                     | String  | Yes      | N/A       | The generation preset to use for summarization calls.                                                         |
| **`maxResponseSizeInTokens`**    | Integer | No       | `750`     | Maximum tokens per LLM response.                                                                              |
| **`recentContextTokens`**        | Integer | No       | `20000`   | Token budget for the Recent section. Messages within this budget (from the end) are kept untouched.           |
| **`oldContextTokens`**           | Integer | No       | `20000`   | Token budget for the Old section. Messages within this budget (after the Recent section) are summarized.      |
| **`lookbackStartTurn`**          | Integer | No       | `5`       | Number of most recent messages to skip before calculating windows.                                            |
| **`oldSectionSystemPrompt`**     | String  | No       | `"You are a summarization AI."` | System prompt for the Old section summarization (Call 1).                                  |
| **`oldSectionPrompt`**           | String  | No       | `"[MESSAGES_TO_SUMMARIZE]"`     | User prompt for the Old section summarization. Placeholders: `[MESSAGES_TO_SUMMARIZE]`, `[RECENT_MESSAGES]`.  |
| **`neutralSummarySystemPrompt`** | String  | No       | `"You are a summarization AI."` | System prompt for neutral summary generation (Call 2).                                    |
| **`neutralSummaryPrompt`**       | String  | No       | `"[MESSAGES_TO_SUMMARIZE]"`     | User prompt for neutral summary generation. Placeholder: `[MESSAGES_TO_SUMMARIZE]`.       |
| **`oldestUpdateSystemPrompt`**   | String  | No       | `"You are a summarization AI."` | System prompt for updating the Oldest rolling summary (Call 3).                           |
| **`oldestUpdatePrompt`**         | String  | No       | `"[EXISTING_SUMMARY]\n\n[NEW_CONTENT]"` | User prompt for updating the Oldest rolling summary. Placeholders: `[EXISTING_SUMMARY]`, `[NEW_CONTENT]`. |

-----

#### **Variable Usage**

The `ContextCompactor` node does not use workflow variable substitution in its own configuration, since its configuration
is minimal (just `type` and `title`). All substantive configuration is loaded from the settings file.

The node's output is assigned to a variable based on the node's position in the workflow (e.g., `{agent1Output}`,
`{agent2Output}`, etc.), and can be referenced by downstream nodes. The output contains XML-tagged summaries that can be
parsed with `TagTextExtractor`.

-----

#### **User Config Setup**

Add the `contextCompactorSettingsFile` field to your user config JSON:

```json
{
  "contextCompactorSettingsFile": "_DiscussionId-ContextCompactor-Settings"
}
```

This tells the node to look for a file named `_DiscussionId-ContextCompactor-Settings.json` in the user's workflow
folder.

-----

#### **Full Syntax Example**

**Node configuration** (in the workflow JSON):

```json
{
  "type": "ContextCompactor",
  "title": "Compact conversation context"
}
```

**Settings file** (`_DiscussionId-ContextCompactor-Settings.json` in the workflow folder):

```json
{
  "endpointName": "Memory-Generation-Endpoint",
  "preset": "Memory-Generation-Preset",
  "maxResponseSizeInTokens": 750,
  "recentContextTokens": 20000,
  "oldContextTokens": 20000,
  "lookbackStartTurn": 5,
  "oldSectionSystemPrompt": "You are a summarization AI. Your task is to summarize a section of a conversation, focusing on details that are most relevant to the current topic being discussed. Preserve key facts, decisions, and context that would help someone understand the conversation's progression toward the current topic.",
  "oldSectionPrompt": "Below is an excerpt from an ongoing conversation that occurred some time ago. Please summarize it, focusing on details most relevant to the current direction of the conversation.\n\nThe excerpt to summarize:\n\n<messages_to_summarize>\n[MESSAGES_TO_SUMMARIZE]\n</messages_to_summarize>\n\nFor context, here are the most recent messages in the conversation, which indicate the current topic:\n\n<recent_messages>\n[RECENT_MESSAGES]\n</recent_messages>\n\nPlease provide a concise summary of the excerpt, emphasizing details relevant to the current conversation direction. Use the participants' names explicitly. Respond with the summary text only.",
  "neutralSummarySystemPrompt": "You are a summarization AI. Your task is to provide a neutral, comprehensive summary of a conversation excerpt without any topic bias. Capture all key facts, events, decisions, and context.",
  "neutralSummaryPrompt": "Below is an excerpt from a conversation. Please provide a neutral, comprehensive summary capturing all key details, facts, decisions, and context from the excerpt.\n\n<messages_to_summarize>\n[MESSAGES_TO_SUMMARIZE]\n</messages_to_summarize>\n\nPlease provide a concise, neutral summary. Use the participants' names explicitly. Respond with the summary text only.",
  "oldestUpdateSystemPrompt": "You are a summarization AI. Your task is to incorporate new content into an existing rolling summary, producing an updated summary that covers everything.",
  "oldestUpdatePrompt": "Below is an existing summary of earlier parts of a conversation, followed by new content that should be incorporated into it.\n\nExisting summary:\n\n<existing_summary>\n[EXISTING_SUMMARY]\n</existing_summary>\n\nNew content to incorporate:\n\n<new_content>\n[NEW_CONTENT]\n</new_content>\n\nPlease produce an updated summary that incorporates the new content into the existing summary. Keep it concise but comprehensive. Use the participants' names explicitly. Respond with the updated summary text only."
}
```

**Output:**

```xml
<context_compactor_old>Topic-focused summary of the Old section goes here...</context_compactor_old>
<context_compactor_oldest>Rolling summary of the Oldest section goes here...</context_compactor_oldest>
```

-----

#### **Example with TagTextExtractor**

A common pattern is to use `ContextCompactor` followed by `TagTextExtractor` nodes to extract the individual summaries
into separate variables for use in downstream prompts.

```json
[
  {
    "title": "Compact conversation context",
    "type": "ContextCompactor"
  },
  {
    "title": "Extract Old section summary",
    "type": "TagTextExtractor",
    "tagToExtractFrom": "{agent1Output}",
    "fieldToExtract": "context_compactor_old"
  },
  {
    "title": "Extract Oldest section summary",
    "type": "TagTextExtractor",
    "tagToExtractFrom": "{agent1Output}",
    "fieldToExtract": "context_compactor_oldest"
  },
  {
    "title": "Generate response with context",
    "type": "Standard",
    "systemPrompt": "You are a helpful assistant. Here is a summary of the older parts of this conversation:\n\n{agent3Output}\n\nHere is a more detailed summary of the middle portion of the conversation:\n\n{agent2Output}",
    "prompt": "{chat_user_prompt_last_one}",
    "endpointName": "Main-Chat-Endpoint",
    "preset": "Main-Chat-Preset",
    "maxResponseSizeInTokens": 2000,
    "forceGenerationPromptIfEndpointAllows": true
  }
]
```

In this example:
- `agent1Output` contains the full XML-tagged output from `ContextCompactor`.
- `agent2Output` contains the extracted Old section summary.
- `agent3Output` contains the extracted Oldest section summary.
- The final `Standard` node uses both summaries as context in its system prompt.

-----

#### **Comparison with ChatSummary**

Both `ContextCompactor` and the ChatSummary memory nodes produce summaries of conversation history, but they serve
different purposes and work differently.

| Aspect                  | ChatSummary (Memory System)                                   | ContextCompactor                                             |
|:------------------------|:--------------------------------------------------------------|:-------------------------------------------------------------|
| **Input source**        | Summarizes memories, which are themselves summaries of chunks. | Directly summarizes raw conversation messages.               |
| **Recency awareness**   | No topic bias; produces a neutral high-level overview.         | Old section is topic-focused based on recent messages.       |
| **Granularity**         | High-level overview, information compressed twice.             | Preserves more granular detail, especially in Old section.   |
| **System dependency**   | Part of the memory system; requires memory nodes upstream.     | Independent; reads messages directly from the conversation.  |
| **Output**              | Single summary string.                                         | Two XML-tagged sections (Old and Oldest).                    |
| **Best for**            | Long-term context where a high-level overview is sufficient.   | Situations needing detailed mid-range context with topic relevance. |

In practice, you can use both in the same workflow. ChatSummary provides the broad strokes of a long conversation,
while ContextCompactor provides more detail about the recent-to-middle portions with awareness of what is currently
being discussed.

-----

#### **Behavior and Edge Cases**

* **No Settings File:** If the `contextCompactorSettingsFile` field is missing from the user config or the settings file
  cannot be loaded, the node logs a warning and returns an empty string.
* **No Discussion ID:** If no discussion ID is available in the execution context, the node logs a warning and returns
  an empty string.
* **Too Few Messages:** If fewer than 2 messages remain after the lookback skip, the node returns whatever cached
  summaries exist (or an empty string if none exist).
* **All Messages Fit in Recent:** If all messages fit within the `recentContextTokens` budget, the Old window is empty
  and no compaction occurs. Cached summaries are returned if they exist.
* **First Run:** On the first run with enough messages, the node always compacts. Only Call 1 (Old section) runs because
  there is no boundary shift yet.
* **Boundary Shift:** When the conversation grows long enough that messages move from Old into Oldest territory, all
  three LLM calls run: Old section re-summarization, neutral summary of shifted messages, and Oldest update.
* **No Boundary Shift:** When the Old window content has changed (new messages entered the window from the Recent side)
  but no messages have shifted into Oldest, only Call 1 runs to re-summarize the Old section.
* **Persistence:** Summaries are persisted to two files per discussion: `{discussion_id}/context_compactor_old.json` and
  `{discussion_id}/context_compactor_oldest.json`. These files are stored in the standard discussion file location.
* **Cached Output:** The node always returns the current on-disk summaries, whether or not a new compaction was
  triggered during the current run. This means the output is available even when compaction is skipped.
* **Output Variable:** The XML-tagged output string is assigned to a variable based on the node's position in the
  workflow (e.g., `{agent1Output}`, `{agent2Output}`, etc.).
* **Token Estimation:** Boundary calculations use a rough token estimation function, not an exact tokenizer. The actual
  token counts may differ slightly from the configured budgets.
