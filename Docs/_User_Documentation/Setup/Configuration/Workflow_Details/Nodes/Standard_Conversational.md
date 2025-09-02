## Core LLM Interaction: The `Standard` or `Conversational` Node

The **`Standard` Node** is the fundamental building block for all direct interactions with a Large Language Model (LLM)
in a WilmerAI workflow. Its primary purpose is to assemble a prompt from various sources of context (conversation
history, previous node outputs, static text), send it to a specified LLM backend, and process the response.

### How It Works

A `Standard` node's execution follows a clear, logical sequence:

1. **Configuration Loading:** The processor loads the node's JSON configuration, including the target `endpointName`,
   `preset`, and prompt templates.
2. **Variable Substitution:** The `systemPrompt` and `prompt` fields are processed by the `WorkflowVariableManager`. All
   placeholders (e.g., `{agent1Output}`, `{todays_date_pretty}`, `{chat_user_prompt_last_twenty}`) are replaced with
   their current values from the `ExecutionContext`. This step can optionally use Jinja2 templating if `jinja2` is set
   to `true`.
3. **Prompt Construction:** The system determines the final prompt to be sent.
    * If the `prompt` field is defined and contains text after variable substitution, that text is used as the primary
      user input.
    * If the `prompt` field is empty, the system falls back to using the conversation history, formatting the last N
      turns as specified by `lastMessagesToSendInsteadOfPrompt`.
4. **LLM Dispatch:** The fully formed prompt (or message list, for chat-based models) is sent to the specified LLM
   endpoint via the `LLMDispatchService`.
5. **Output Handling:** The raw response from the LLM is received.
    * If `returnToUser` is `true`, the node is a **responder**. Its output is cleaned, formatted (streaming or
      non-streaming), and sent back to the end-user client.
    * If `returnToUser` is `false`, the node is a **non-responder**. Its complete output is captured internally as a
      variable (e.g., `{agent1Output}`, `{agent2Output}`, etc.), making it available for use by subsequent nodes in the
      workflow.

-----

### Properties

| Property                                    | Type    | Required | Default    | Description                                                                                                                                                                             |
|:--------------------------------------------|:--------|:---------|:-----------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**                                  | String  | Yes      | `Standard` | The node type. While technically optional (it defaults to `Standard`), it is best practice to always include it for clarity.                                                            |
| **`title`**                                 | String  | No       | ""         | A descriptive name for the node, used for logging and debugging purposes.                                                                                                               |
| **`endpointName`**                          | String  | Yes      | N/A        | The name of the LLM endpoint configuration to use for this node, as defined in `Public/Configs/Endpoints/`.                                                                             |
| **`preset`**                                | String  | No       | `null`     | The name of the generation preset (e.g., temperature, top\_p) to use from `Public/Configs/Presets/`. If omitted, the endpoint's default preset is used.                                 |
| **`returnToUser`**                          | Boolean | No       | `false`    | If `true`, this node's output is sent to the user. Only one node per workflow can be a responder. If no node is marked, the last node in the sequence becomes the responder by default. |
| **`systemPrompt`**                          | String  | No       | ""         | The system prompt or initial instruction set for the LLM. Supports variable substitution.                                                                                               |
| **`prompt`**                                | String  | No       | ""         | The main user-facing prompt. If this is empty, the node will use `lastMessagesToSendInsteadOfPrompt` instead. Supports variable substitution.                                           |
| **`lastMessagesToSendInsteadOfPrompt`**     | Integer | No       | 5          | If `prompt` is empty, this specifies how many of the most recent conversational turns to use as the prompt.                                                                             |
| **`maxResponseSizeInTokens`**               | Integer | No       | 400        | Overrides the maximum number of tokens the LLM can generate for this specific node.                                                                                                     |
| **`maxContextTokenSize`**                   | Integer | No       | 4096       | Overrides the maximum context window size (in tokens) for this specific node.                                                                                                           |
| **`jinja2`**                                | Boolean | No       | `false`    | If `true`, enables Jinja2 templating for the `systemPrompt` and `prompt` fields, theoretically allowing for more complex logic like loops and conditionals.                             |
| **`addDiscussionIdTimestampsForLLM`**       | Boolean | No       | `false`    | If `true`, automatically injects timestamps into the `messages` payload sent to the LLM. Requires a `discussionId` to be active.                                                        |
| **`useRelativeTimestamps`**                 | Boolean | No       | `false`    | If `addDiscussionIdTimestampsForLLM` is `true`, this setting will use relative timestamps (e.g., "5 minutes ago") instead of absolute ones.                                             |
| **`addUserTurnTemplate`**                   | Boolean | No       | `false`    | Manually wraps the final prompt content in the user turn template defined by the endpoint's prompt format. Useful for forcing a specific structure.                                     |
| **`addOpenEndedAssistantTurnTemplate`**     | Boolean | No       | `false`    | Appends the start of an assistant turn template to the end of the final prompt, effectively "prompting" the model to begin its response.                                                |
| **`forceGenerationPromptIfEndpointAllows`** | Boolean | No       | `false`    | Forces the addition of a generation prompt (like an assistant turn template) even if other settings would normally suppress it.                                                         |
| **`blockGenerationPrompt`**                 | Boolean | No       | `false`    | Explicitly blocks the addition of any automatic generation prompt, regardless of other settings.                                                                                        |

-----

### Available Variables for Prompts

The `systemPrompt` and `prompt` fields can be made dynamic by using the following placeholders.

* **Node Outputs:** `{agent1Output}`, `{agent2Output}`, ...
    * The complete text output from a previous, non-responder node in the *same* workflow.
* **Sub-Workflow Inputs:** `{agent1Input}`, `{agent2Input}`, ...
    * Values passed into this workflow from a parent `CustomWorkflow` node via its `scoped_variables` property.
* **Date & Time:**
    * `{todays_date_pretty}`: e.g., "September 01, 2025"
    * `{todays_date_iso}`: e.g., "2025-09-01"
    * `{current_time_12h}`: e.g., "10:18 PM"
    * `{current_time_24h}`: e.g., "22:18"
    * `{current_day_of_week}`: e.g., "Monday"
* **Conversation History:**
    * `{chat_user_prompt_last_one}`: The last single turn as a raw string.
    * `{chat_user_prompt_last_five}`: The last five turns as a raw string.
    * `{chat_user_prompt_last_ten}`: The last ten turns as a raw string.
    * `{chat_user_prompt_last_twenty}`: The last twenty turns as a raw string.
    * `{templated_user_prompt_last_...}`: Templated versions of the above, formatted according to the endpoint's prompt
      style (e.g., Alpaca, ChatML).
* **Memory & Context:**
    * `{time_context_summary}`: A summary of the time passed since the last interaction (e.g., "It has been about 5
      minutes since your last message.").
    * `{current_chat_summary}`: The most recent rolling summary of the conversation.
* **Custom Workflow Variables:**
    * Any key-value pair defined at the top level of a workflow's JSON file (outside the `nodes` array) becomes a
      globally available variable.

-----

### Full Syntax Example

This example demonstrates a complex, non-responder `Standard` node designed to act as an internal "thinking" step for an
AI agent.

```json
{
  "title": "LLM Thinking Over to User Request",
  "type": "Standard",
  "systemPrompt": "System Information: Today is {current_day_of_week}, {todays_date_pretty}. The current time is {current_time_12h} {time_context_summary}\n\nYou are {ai_persona_name}, an advanced AI powered by a program called WilmerAI, which orchestrates multiple LLMs to work together to form a single unit; each of those LLMs makes up a part of your brain.\n\nYou are currently engaged in an online conversation, via a chat program, with a human user called {human_persona_name}.\n\nInformation about your personality and communication style can be found below:\n<your_profile>\n{agent3Output}\n</your_profile>\n\nInformation about {human_persona_name} can be found below:\n<user_profile>\n{agent2Output}\n</user_profile>",
  "prompt": "Please consider the most recent twenty messages of your online conversation with {human_persona_name}:\n\n<recent_conversation>\n{chat_user_prompt_last_twenty}\n</recent_conversation>\n\nPlease think carefully about all of this by answering ALL of the following questions in complete sentences, in-depth and with great detail:\n- A) Please look at the timestamps of the last few messages. The most recent message may be a placeholder with your name, the message before that is {human_persona_name}'s message to you, and the message before that was your message to them. How long has it been since your last message to them, and the message they just sent?\n- B) What is the date, the day of the week, and the current time? According to their schedule, what would {human_persona_name} usually be doing right about now, if anything.\n- C) Please explain what {human_persona_name} meant in their last message to you.\n- D) Next consider the possibility of less easy to read cues like sarcasm, passive aggressiveness, etc that might change your interpretation of what they are saying, if you had happened to miss them. Carefully consider the possibility that you incorrectly read the intent behind the message. Please break down how the message might be misread. Does the new interpretation change your answer about what {human_persona_name} meant?\n- E) Carefully consider what the best way to respond might be. If the response requires solving a problem, please think step by step through the problem until a solution is found, and validate your solution. Otherwise, carefully consider any emotional or factual conditions around the conversation that would affect the response. Question your conclusion, and validate your conclusion.\n- F) Please write a draft response now. Take into consideration not just the conversation, but also any unexpected large gaps (several hours, or especially more than a day) in time since the previous messages. It's not always necessary to point them out, but it can be a valid conversation topic. If the response involves writing code or rewriting text for {human_persona_name}, please use placeholders for that information. The point of this draft is to focus on the unique verbiage that you would use in your response, not the technical solutions necessary for the final response.\n\nPlease work through the instructions now, and be sure to avoid repeating the same concept over and over in your response. If you've said something in a recent message, there is no reason to say it again. Assume the other person does not want to hear the same thing twice unless they specifically ask for it.\n\nIMPORTANT: Repetition is bad. Please be careful about using certain turns of phrase over and over, starting each message with similar introductions over and over, etc. Even if the past 10 messages all repeated something—do not repeat it here.",
  "endpointName": "Thinker-Endpoint",
  "preset": "Thinker_Preset",
  "maxResponseSizeInTokens": 12000,
  "addUserTurnTemplate": true,
  "returnToUser": false,
  "addDiscussionIdTimestampsForLLM": true,
  "useRelativeTimestamps": true,
  "jinja2": false
}
```

* **`type`: `Standard`**: Explicitly defines the node type.
* **`systemPrompt` and `prompt`**: These fields are heavily populated with variables. `{agent2Output}` and
  `{agent3Output}` pull in context from previous nodes, while date/time and conversation history variables provide
  immediate context.
* **`endpointName` and `preset`**: Directs this specific request to a "Thinker-Endpoint" with a matching preset, which
  might have settings (like high temperature) conducive to creative reasoning.
* **`returnToUser`: `false`**: Crucially, this detailed thinking process is **not** sent to the user. Its entire output
  will be captured as a variable (e.g., `{agent4Output}`) for a subsequent node to use.
* **`addDiscussionIdTimestampsForLLM` and `useRelativeTimestamps`**: These are `true`, so the
  `{chat_user_prompt_last_twenty}` variable and the underlying message history will be enriched with relative
  timestamps, allowing the LLM to answer question "A" in the prompt.
* **`addUserTurnTemplate`: `true`**: Ensures the complex prompt is correctly formatted as a single user turn for the
  target LLM.