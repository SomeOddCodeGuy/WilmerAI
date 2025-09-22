### **A Technical Guide to Conversation Timestamps**

This guide provides a complete technical reference for WilmerAI's automated conversation timestamping system. The
information is validated against the system's source code to ensure accuracy. This system provides crucial temporal
context to LLMs, allowing them to be aware of the passage of time within a conversation.

#### **Core Principle: Automated Temporal Context**

The timestamp system is an automated feature designed to track the time of each message within a persistent
conversation. When enabled, it transparently injects time data into the conversation history before it is sent to an
LLM. This process is entirely managed by the middleware and is activated whenever a request includes a `discussionId`.

-----

### **Part 1: Enabling Timestamps in a Workflow**

Timestamping is not a standalone node type but rather a feature configured within a **`Standard`** node. By setting
specific boolean properties, you can control whether and how timestamps are added to the message history for that
specific LLM call.

#### **Configuration Properties**

These properties are added to any `Standard` node object in your workflow's JSON file.

| Property                              | Type    | Required | Default | Description                                                                                                                                                                                                                                                                                                       |
|:--------------------------------------|:--------|:---------|:--------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`addDiscussionIdTimestampsForLLM`** | Boolean | No       | `false` | When set to `true`, the system will process the conversation history, adding a timestamp to the beginning of each message's content. This requires a `discussionId` to be active for the conversation.                                                                                                            |
| **`useRelativeTimestamps`**           | Boolean | No       | `false` | If `addDiscussionIdTimestampsForLLM` is `true`, setting this to `true` will format timestamps as relative strings (e.g., "[Sent 5 minutes ago]") instead of absolute date-time strings.                                                                                                                           |
| **`useGroupChatTimestampLogic`**      | Boolean | No       | `false` | If `true`, enables a special mode to handle group chats and generation prompts, committing the assistant's timestamp **immediately** after the response is generated. If `false` (default), the timestamp is committed on the **next user turn**, which is the recommended setting for standard one-on-one chats. |

#### **Example `Standard` Node Configuration**

This example shows a node configured to inject relative timestamps and use the immediate commit logic for group chats.

```json
{
  "title": "Respond with Temporal Awareness",
  "type": "Standard",
  "endpointName": "Creative-Endpoint",
  "prompt": "{chat_user_prompt_last_one}",
  "returnToUser": true,
  "addDiscussionIdTimestampsForLLM": true,
  "useRelativeTimestamps": true,
  "useGroupChatTimestampLogic": true
}
```

-----

### **Part 2: How the Timestamp System Works**

The timestamping process relies on a persistent storage file, a two-part mechanism to accurately capture assistant
response times, and a backfilling algorithm to process historical messages.

#### **Storage and Identification**

* For each unique `discussionId`, a corresponding `.json` file is created to store timestamps.
* Each message is identified by a **SHA-256 hash** of its role and content.
* The storage file is a dictionary mapping the message hash to its timestamp string.

#### **The Timestamping Mechanism**

A key challenge is knowing the timestamp of an assistant's message *before* its full content has been generated. The
system solves this with a placeholder mechanism.

1. **Placeholder Creation:** The moment a `Standard` node begins generating a response, the system calls
   `save_placeholder_timestamp`. This saves the **current time** to the discussion's timestamp file under a special,
   temporary key.

2. **Timestamp Commitment:** How the placeholder is resolved depends on the `useGroupChatTimestampLogic` flag:

    * **Default Logic (`useGroupChatTimestampLogic: false`):** The placeholder is resolved on the **next user turn**.
      When the user sends their next message, `track_message_timestamps` is called. It retrieves the placeholder
      timestamp, applies it to the previous assistant message (whose full content is now known), and assigns a new,
      current timestamp to the incoming user message. This is the most robust method for standard one-on-one chats.

    * **Group Chat Logic (`useGroupChatTimestampLogic: true`):** The timestamp is committed **immediately** after the
      assistant's response is fully generated. The system calls `commit_assistant_response`, which calculates the hash
      of the final message content, retrieves the placeholder timestamp, and saves it permanently with the new hash.
      This mode includes special handling for generation prompts:

        * **Reconstruction:** If the last message in the conversation history appears to be a generation prompt (e.g.,
          `CharacterName:`), and the LLM's response does *not* begin with such a prefix, the system will automatically
          prepend the generation prompt to the LLM's response before hashing. This ensures the final stored content
          matches what would appear in a continuous chat, creating a consistent hash.

#### **Historical and New Message Processing**

When a request is made, the `track_message_timestamps` function processes the entire conversation history to ensure all
messages have a correct, chronologically consistent timestamp.

1. **Backward Iteration:** The system starts from the present moment and iterates backward through the message list.
2. **Anchor Time:** For each message, it calculates a content hash.
    * If a timestamp for that hash already exists in the discussion's file, that known timestamp becomes the new "anchor
      time."
    * If no timestamp exists (i.e., it is a new or previously untracked message), the system assigns the current anchor
      time to it and saves this to the file.
3. **Backfilling:** After assigning a timestamp to an unknown message, the system decrements the anchor time by **one
   second**. This new, earlier time becomes the anchor for the next message in the backward sequence. This process
   ensures that even conversations that predate the timestamping system are given a logical, sequential timeline.
4. **Generation Prompt Handling:** The system uses a heuristic to identify and ignore simple, non-content messages at
   the end of the list that serve only as generation prompts (e.g., `{"role": "assistant", "content": "Assistant:"}`).
   These are not assigned a timestamp.

-----

### **Part 3: Timestamp Formats**

Based on the `useRelativeTimestamps` property, timestamps are prepended to the `content` of each message in one of two
formats.

#### **Absolute Timestamps** (`useRelativeTimestamps: false`)

This is the default format. It provides a full, unambiguous date and time, wrapped in parentheses.

* **Format:** `(DayOfWeek, YYYY-MM-DD HH:MM:SS)`
* **Example Message `content`:** `(Saturday, 2025-09-20 16:30:05) Hello, how can I assist you today?`

#### **Relative Timestamps** (`useRelativeTimestamps: true`)

This format provides a more human-readable, context-dependent time, wrapped in square brackets.

* **Format:** `[Sent {time} ago]`
* **Example Message `content`:** `[Sent 2 hours, 15 minutes ago] I need help with my workflow.`

-----

### **Part 4: The `{time_context_summary}` Variable**

In addition to injecting timestamps directly into messages, the system provides a high-level summary variable that can
be used in prompts. This variable gives the LLM an immediate understanding of the conversation's overall timeline.

#### **Generation**

The `get_time_context_summary` function is called by the `WorkflowVariableManager` to create this variable. It works by:

1. Loading all saved timestamps for the current `discussionId`.
2. Identifying the **earliest** timestamp (conversation start) and the **most recent** timestamp.
3. Formatting these into a concise, natural-language string.

#### **Usage and Example**

The `{time_context_summary}` variable can be used in any valid content field, but it is most effective in a
`systemPrompt`.

* **Example Output:**
  `[Time Context: This conversation started 2 days, 5 hours ago. The most recent message was sent 15 minutes ago.]`

#### **Example Workflow Node**

This node uses the summary variable to give the LLM temporal context at the start of its processing.

```json
{
  "persona": "You are a helpful AI assistant.",
  "nodes": [
    {
      "title": "Context-Aware Responder",
      "type": "Standard",
      "endpointName": "Analytical-Endpoint",
      "systemPrompt": "{persona}\n\n{time_context_summary}",
      "prompt": "Considering our conversation history, please answer the user's latest question: {chat_user_prompt_last_one}",
      "returnToUser": true,
      "addDiscussionIdTimestampsForLLM": true,
      "useRelativeTimestamps": false
    }
  ]
}
```