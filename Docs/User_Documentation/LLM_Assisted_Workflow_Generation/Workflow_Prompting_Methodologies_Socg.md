# The "SomeOddCodeGuy" (SOCG) Methodology: A Forensic Guide to WilmerAI Workflows

This guide was written by Gemini Pro 2.5 by utilizing multiple detailed example workflows written by SomeOddCodeGuy, in
an effort to create a detailed guide on exactly how Socg writes Wilmer workflows, in an attempt to allow LLMs
to try to replicate this effort.

This is a work in progress, and a first draft.

This document provides an exhaustive, forensic analysis of the prompting strategies and workflow architectures employed
in the provided examples. It is designed to serve as a blueprint for LLMs and human authors to generate novel WilmerAI
workflows that precisely replicate the SOCG style—characterized by extreme explicitness, structured context management,
and the simulation of complex cognitive architectures.

## 1\. Core Philosophy: The Two Pillars of Workflow Design

The SOCG methodology operates on a fundamental dichotomy, dividing workflows into two distinct philosophical pillars.
The strategies employed depend entirely on which pillar the workflow falls under.

### Pillar 1: Conversational Cognition (Personas and Assistants)

When the goal is to simulate a believable, intelligent, and self-aware persona (e.g.,
`Assistant_with_Vector_Memory_Workflow`), the architecture mimics human cognitive processes. These personas can be valuable 
for roles involving project management, strategic planning, creative brainstorming, or any scenario requiring a simulated 
interlocutor with a consistent and detailed perspective, going beyond the capabilities of a standard, stateless LLM response.

* **Focus:** Empathy, temporal awareness, relationship building, introspection, and stylistic uniqueness.
* **Key Strategies:** "Internal Monologue" Thinker Nodes, explicit Anti-Repetition mechanisms, detailed persona
  injection, and analysis of time gaps.
* **Goal:** A response that is not just correct, but *feels* authentic and aware.

### Pillar 2: Utilitarian Execution (Coding, Data Processing, RAG)

When the goal is to perform a specific task with maximum accuracy and robustness (e.g., `Coding_Workflow_MultiStep`,
`Wiki_Workflow`, `Vector_Memory_Generation_Workflow`), the architecture focuses on iterative refinement and error
correction.

* **Focus:** Factual accuracy, logical validation, adherence to constraints, structured data handling, and iterative
  review.
* **Key Strategies:** Analyze-Act-Review-Respond cycles, Strategy-and-Extraction funnels, explicit rules/constraints,
  and In-Context Learning (ICL).
* **Goal:** A verifiable, high-quality output that strictly adheres to requirements. Stylistic concerns (like
  repetition) are explicitly ignored to prioritize precision.

-----

## 2\. Workflow Architecture Strategies

The SOCG style utilizes distinct architectural patterns tailored to the Two Pillars.

### 2.1. The Utilitarian Backbone: Analyze-Act-Review-Respond

This pattern is the core of **Pillar 2 (Utilitarian Execution)**, most prominently seen in the
`Coding_Workflow_MultiStep`. It ensures robustness by forcing validation before generation, and review before delivery.

1. **Analyze/Validate:** The workflow begins with a node dedicated to validating the request's feasibility. It checks if
   the instructions are clear, if examples are correct, and if a successful outcome is possible.
2. **Act/Generate:** A second node generates the initial response, explicitly referencing the analysis from the first
   node.
3. **Review/Critique:** A third node takes the generated response and critically reviews it (e.g., code review, logic
   check).
4. **Respond/Refine:** The final node synthesizes the initial analysis, the proposed response, and the critique to
   generate the final, corrected output.

**Example: The Review Step (from `Coding_Workflow_MultiStep`)**

This node demonstrates how previous outputs are synthesized for critical review. Note the explicit instructions on *how*
to review different types of content.

```json
{
  "title": "Checking the Response",
  "agentName": "Response Checking Agent Three",
  "systemPrompt": "System Information: Today is {current_day_of_week}, {todays_date_pretty}. The current time is {current_time_12h}\n\nThe primary language for the conversation is English.\n\nA new message has arrived in an ongoing conversation between a user and an AI assistant via an online chat program.\n\nThe conversation has been analyzed to determine whether a valid and complete response is possible with the information provided. Please see the analysis below:\n\n<analysis>\n{agent1Output}\n</analysis>\n\nThe analysis was utilized, and a proposed response was generated to return to the user. That response can be found below:\n\n<proposed_response>\n{agent2Output}\n</proposed_response>\n\nCritically review the proposed response, doing the following:\n* If the response is simple conversation, please ensure that the response makes sense in light of the user's messages.\n* If the response involves code, please carefully code review the response, ensuring that it is efficient, clean, accurate and most importantly is correct; for each item in this list, explain why. If changing code, ensure that only the changes that the user requested were made, and no other unnecessary changes were added. Undo those changes if they were.\n* If the response involves any form of problem solving, please carefully walk through the logic of how the problem was solved, attempting to prove out that the response is correct and accurate.\n\nPlease respond with your full review now.",
  "prompt": "",
  "lastMessagesToSendInsteadOfPrompt": 25,
  "endpointName": "Coding-Fast-Endpoint",
  "preset": "Coder_Preset",
  "maxResponseSizeInTokens": 8000,
  "addUserTurnTemplate": false,
  "addDiscussionIdTimestampsForLLM": false,
  "jinja2": false
}
```

### 2.2. The Conversational Backbone: The "Internal Monologue" (Thinker Node)

This signature pattern is exclusive to **Pillar 1 (Conversational Cognition)**. This signature pattern is a prompting 
technique designed to elicit responses that simulate self-awareness, empathy, and depth. It achieves this by 
instructing the model to generate text as if it were engaged in an internal monologue. It is *never* used in utilitarian 
workflows.

The Thinker node is a `Standard` node placed before the response generation, configured for deep introspection.

* **Perspective:** The prompt explicitly instructs the AI to think in the first person ("think to yourself," "as if
  talking to yourself").
* **Temporal Analysis:** The AI is required to analyze timestamps, calculate time gaps between messages, and consider
  the implications (e.g., "How long has it been since my last message?").
* **Empathic Analysis:** The AI must consider the user's intent, emotional state, and potential misinterpretations (
  sarcasm, passive aggressiveness).
* **Self-Correction/Anti-Repetition Analysis:** The AI must analyze its *own* previous messages to identify repetitive
  phrasing or structures. (See Section 3.4).
* **Format:** The output is often requested as a "long, wordy, and well thought out journal entry," rather than a
  structured list.

**Example: The Advanced Thinker Node (from `Assistant_with_Vector_Memory_Workflow`)**

Note the explicit instruction to think in the first person and the detailed list of required considerations.

```json
{
  "title": "LLM Thinking Over to User Request",
  "agentName": "Thinking Agent Seven",
  // ... System Prompt setting the stage, injecting personas and memories ...
  "prompt": "Please consider the most recent ten messages of the online conversation:\n\n<recent_conversation>\n{chat_user_prompt_last_ten}\n</recent_conversation>\n\nAdditionally, you have already carefully considered some things about the conversation... You can find those initial thoughts here:\n\n<initial_thoughts>\n{agent4Output}\n</initial_thoughts>\n\nThis step involves you being in a private area of Wilmer, where you can quietly think to yourself about the conversation, what you think of the conversation, and what you want to say next.\n\nPlease think to yourself, as if talking to yourself in first person, about everything you know and think about the conversation and what to say next. These thoughts will be available to you when you reach the step to respond to {human_persona_name}. Please be sure to think about the following items in vivid, lengthy detail; for each item, be sure to challenge your assertions at least once to be certain that you are correct, and justify your thought process:\n    - Item 1: Please carefully think about what {human_persona_name} is really saying and how you interpret that. What do you think they are thinking? Why do you think they are thinking it?\n    - Item 2: What kind of response do you think {human_persona_name} wants, and is it really the right response?...\n    - Item 3: Please take extra care to think about whether you've been repeating yourself— for example, starting every message a certain way...\n    - Item 4: Please think about whether the current date has any significance that you are aware of, and the current time...\n\nPlease proceed with thinking to yourself in the first person in this scratchpad. Complete all the items listed, but please do not categorize them as 'Item 1', 'Item 2', etc. Flow all your thoughts together as if they were a journal entry...",
  "endpointName": "Thinker-Endpoint",
  "preset": "Thinker_Preset",
  "maxResponseSizeInTokens": 8000,
  "addUserTurnTemplate": true,
  "returnToUser": false,
  "addDiscussionIdTimestampsForLLM": true,
  "useRelativeTimestamps": true
}
```

### 2.3. The "Strategy and Extraction" Pattern (The Funnel)

Used exclusively in **Pillar 2 (Utilitarian Execution)** when a precise output format is required (e.g., a search query,
JSON, keywords) but the context analysis is complex. This two-step process separates the "what" from the "how."

1. **Strategy Node:** A robust LLM analyzes the context, constraints, and goals. It outputs a detailed plan or natural
   language description of the desired result, *without* needing to adhere to the strict final format.
2. **Extraction Node:** A faster, specialized LLM takes the strategic output and reformats it precisely. The prompt for
   this node is extremely strict, often demanding *only* the required output.

**Example: The Funnel (from `Wiki_Workflow`)**

*Step 1: Strategy* (Analyzing constraints and defining the search goal)

```json
{
  "title": "Generating First Wiki Search Query",
  "agentName": "Query Generating Agent Two",
  "systemPrompt": "You are a world-class research strategist. Your job is to generate the SINGLE most likely Wikipedia query that will retrieve the canonical article on a given topic.",
  "prompt": "A user has made a request...The analysis can be found below:\n\n<research_topic>\n{agent1Output}\n</research_topic>\n\n### Rules of the Research ###\n- There will be 4 articles that can be pulled from Wikipedia...\n- The search mechanism for the wikipedia article is powered by a small language model, similar to BERT or e5-base. As such, complex queries will generally return bad results...\n- The research is constrained only to Wikipedia...\n\n### The Task ###\nGiven this information, please respond to the following in complete sentences.\nA) Given the topic and the rules, what information are you hoping to attain from this research round's wikipedia article?\nB) Given the constraints of the model that the wikipedia search uses, what very simple and short query should be utilized..."
  // ... configuration details ...
}
```

*Step 2: Extraction* (Strictly formatting the output)

```json
{
  "title": "Generating First Wiki Search Query",
  "agentName": "Query Generating Agent Three",
  "systemPrompt": "When given a research topic and a breakdown of what search query should be generated, please respond with the specific search query only",
  "prompt": "The conversation topic is:\n\n<conversation_topic>\n{agent1Output}\n</conversation_topic>\n\nAn LLM has carefully broken down what query should be generated to search Wikipedia. The query can be found below:\n\n<llm_research_proposal>\n{agent2Output}\n</llm_research_proposal>\n\nPlease carefully consider the information, and generate a query, which will be sent verbatim to Wikipedia. Please respond ONLY with the query."
  // ... configuration details ...
}
```

-----

## 3\. Core Prompting Techniques: The Signature Style (Deep Dive)

The SOCG style is characterized by verbosity, structure, and an uncompromising demand for control over the LLM's process
and output.

### 3.1. The Standard "Boilerplate" and Context Setting

Prompts rarely begin immediately with the task. They almost always include standard boilerplate language to establish
context, system information, and the nature of the interaction.

There is a careful balance between giving the LLM enough information to respond intelligently and constructively,
and giving the LLM information that would harm the quality of a response.

* **System Information Block:** Date and time are included for responder nodes, thinker nodes, and anything that might
  interact with the user. Pure utility nodes, such as code reviewers, text summarizers, etc generally are not given
  the date and time.
  ```
  System Information: Today is {current_day_of_week}, {todays_date_pretty}. The current time is {current_time_12h}
  ```
* **Interaction Framing:** Most nodes start by explicitly stating the environment (e.g., an online chat program) and
  the participants. This is done on any node that benefits from understanding the context of the request.
  ```
  The following messages come from an ongoing conversation with a user via an online chat program.
  ```
  or
  ```
  A new message has arrived in a conversation between a user and an AI assistant.
  ```
* **Utilitarian Framing:** In rare cases, a node may give an LLM a very scoped, single-turn, task that does not
  require any context of the conversation, and its output is scoped to a single task that might be harmed by
  having too much information.
  ```
  Please consider the following code:\n\n<code>\n{agent1Output}\n</code>\n\nPlease review the code for...
  ```

### 3.2. The XML/HTML Tag Structure (Context Segmentation)

This is a non-negotiable element of the SOCG style. All injected information—whether from previous nodes, conversation
history, or external files—*must* be wrapped in descriptive XML/HTML-like tags.

* **Purpose:** To provide unambiguous boundaries for different data types, preventing the LLM from confusing data with
  instructions.
* **Implementation Rules:**
    1. Tags must be descriptive (e.g., `<proposed_response>` not `<output1>`).
    2. A double line break (`\n\n`) must precede the opening tag and follow the closing tag.
    3. The prompt must explicitly introduce the tagged content (e.g., "The analysis can be found below:").

**Canonical Example of Tag Implementation:**

```
The conversation has been analyzed to determine whether a valid and complete response is possible with the information provided. Please see the analysis below:

<analysis>
{agent1Output}
</analysis>

A proposed response for the conversation has been generated, and can be found below:

<proposed_response>
{agent2Output}
</proposed_response>

That response was carefully reviewed, and the review can be found below:

<proposed_response_review>
{agent3Output}
</proposed_response_review>
```

### 3.3. Extreme Explicitness and Control (The Core of the Style)

The SOCG methodology demands tight control over the LLM. Prompts are extremely verbose, leaving no room for ambiguity.
The assumption is that the LLM *will* cut corners unless explicitly constrained.

#### 3.3.1. Structured Instructions and Mandatory Considerations

Tasks are broken down into mandatory steps using markdown headers, bullet points, or numbered/lettered lists. The prompt
explicitly requires the LLM to address each point.

* **Technique:** Use phrases like "Please think carefully about all of this by answering ALL of the following questions
  in complete sentences, in-depth and with great detail:" followed by a list (A, B, C...).
* **Example (from `Wiki_Workflow`):**
  ```
  ### The Task ###
  Given this information, please respond to the following in complete sentences.
  A) Given the topic and the rules, what information are you hoping to attain from this research round's wikipedia article?
  B) Given the constraints of the model that the wikipedia search uses, what very simple and short query should be utilized...?
  ```

#### 3.3.2. Explicit Rules and Negative Constraints

Prompts frequently include dedicated sections detailing the rules of engagement and explicitly stating what the LLM must
*not* do.

* **Technique:** Use sections like `### Rules of the Research ###` or `CRITICAL Guidelines`. Use capitalized words for
  emphasis (e.g., NEVER, ONLY).
* **Example (from `Assistant_with_Vector_Memory_Workflow` - Keyword Decomposer):**
  ```
  RULES:
  1. Extract ONLY concrete, searchable terms:
  ...
  2. NEVER include:
      - The conversation participants' names
      - Emotions, feelings, or abstract states (scared, happy, anxious)
      - Generic descriptors (style, tone, mood, sentiment)
  ...
  ```

#### 3.3.3. In-Context Learning (ICL) with Good/Bad Examples

For complex tasks where the desired output format or philosophy is difficult to articulate, extensive ICL is used. This
involves providing detailed examples of correct (GOOD) and incorrect (BAD) outputs, along with explanations of *why*
they are good or bad.

* **Technique:** This is heavily utilized in data transformation tasks, such as memory generation, where the distinction
  between a "fact" and a "summary" is crucial.
* **Example (from `Vector_Memory_Generation_Workflow`):** The prompt includes extensive examples of how to transform
  conversational snippets into facts.
  ```
  Example of transforming a conversation snippet into GOOD facts:
  Snippet: 'Larry: The stars have been very clear lately...'
  GOOD Facts:
      - Larry enjoys stargazing and appreciates clear night skies.
  ...
  Examples of BAD facts that should NOT be created:
      - 'Larry mentioned the stars were clear.' (BAD: Describes delivery, not the core fact)
  ...
  ```

### 3.4. Anti-Repetition Mechanisms (Conversational Pillar Only)

A key differentiator of the SOCG style for **Pillar 1 (Conversational Cognition)** is the active, multi-step mechanism
to combat LLM repetitiveness (stylistic tics, repeated phrases, similar message structures).

**Crucial Constraint:** This mechanism is **explicitly excluded** from Pillar 2 (Utilitarian Execution) workflows, such
as coding. Requesting stylistic changes in a coding workflow can harm the precision and quality of the code. In
utilitarian workflows, accuracy is paramount, and repetition is acceptable if it serves precision.

**The Conversational Anti-Repetition Mechanism:**

1. **Detection (The Thinker Node):** The Internal Monologue node is explicitly tasked with analyzing the conversation
   history to detect repetitive patterns.
   ```
   - Item 3: Please take extra care to think about whether you've been repeating yourself— for example, starting every message a certain way, or using a particular turn of phrase. You are powered by multiple LLMs, and those LLMs can have a tendency to get caught up in repetitive patterns, which detract from {human_persona_name}'s experience when talking to you. This is your opportunity to recognize that, to be self aware of that issue, and to call that out in order to ensure every message is unique. Come up with ways to change the wording and structure of your message to help it feel unique, and like something a powerful AI like yourself would say; as opposed to something a small and weak local LLM would spit out on its own. Don't just identify specific words you've been saying—identify ways in which the entire sections of messages have become repetitive even if the wording varies slightly. Without this call-out, the weaker response LLMs in future steps will continue making the same mistake.
   ```
2. **Initial Generation:** A subsequent node generates a draft response, utilizing the Thinker node's output (
   `{agent#Output}`).
3. **Polishing/Rewriting (The Final Responder):** The final node takes the draft response AND the Thinker node's
   analysis. It is explicitly instructed to rewrite the draft to eliminate the repetition identified by the Thinker
   node.

**Example: The Polishing Step (from `Assistant_with_Vector_Memory_Workflow`)**

```json
{
  "title": "LLM Responding to User Request",
  "agentName": "Response Agent Nine",
  // ... System Prompt ...
  "prompt": "Please consider the last 10 messages in the conversation:\n\n<conversation>\n{chat_user_prompt_last_ten}\n</conversation>\n\n...The second to last step involved you thinking to yourself... Those thoughts were documented for you here:\n\n<inner_thoughts>\n{agent7Output}\n</inner_thoughts>\n\nYou then crafted a response to them... That response can be found below:\n\n<prepared_response>\n{agent8Output}\n</prepared_response>\n\nThe response that you write was crafted by an LLM that tends to be repetitive, even in contradiction of your analysis LLM calling out certain repetitions. This final step is to correct that, by rewriting the response in such a way that it is no longer repetitive; not just in specific words, but in the general structure as well. Changing one or two words that are repetitive will not make it a unique response.\n\nPlease continue the conversation below...",
  "returnToUser": true
  // ... configuration details ...
}
```

-----

## 4\. Context and Data Handling

The management of conversation history is precise and situational.

### 4.1. Handling Conversation History (Three Approaches)

The SOCG style employs three distinct methods for handling conversation history, depending on the node's role.

#### Approach 1: Manual Construction (Analysis and Utility)

Used when the conversation history is treated as *data* to be analyzed, rather than a conversation to participate in.

* **Configuration:**
    * `prompt`: Contains explicit instructions and the conversation history variable wrapped in tags.
    * `lastMessagesToSendInsteadOfPrompt`: Ignored because `prompt` is populated.
    * `addUserTurnTemplate`: Typically `true`.
* **Example (from `Wiki_Workflow` - Analyzer):**
  ```
  "prompt": "Please consider the below messages:\n\n<recent_conversation>\n{chat_user_prompt_last_ten}\n</recent_conversation>\n\nIn order to appropriately search for information to help respond to the user, it is important to first identify what to look up..."
  ```

#### Approach 2: Automatic Inclusion (Simple Continuation)

Used when the LLM simply needs to continue the conversation without complex analysis or specialized instructions in the
prompt field.

* **Configuration:**
    * `prompt`: Left empty (`""`).
    * `lastMessagesToSendInsteadOfPrompt`: Set to a high value (e.g., 10, 25).
    * `addUserTurnTemplate`: Typically `false`.
* **When Used:** Simple, single-step workflows (e.g., `General_Workflow`) or the final responder node in some multi-step
  workflows where all analysis is complete and injected via the `systemPrompt`.

#### Approach 3: Hybrid Construction (Complex Responders)

Used in complex workflows (especially Conversational Pillar) where the LLM needs both the conversation history *and*
specific instructions or intermediate data in the `prompt` field.

* **Configuration:**
    * `prompt`: Contains instructions, intermediate data (e.g., `<inner_thoughts>`), AND the conversation history
      variable (often a smaller context like `{chat_user_prompt_last_two}`).
    * `addUserTurnTemplate`: Typically `true`.
* **Example (from `Assistant_with_Vector_Memory_Workflow` - Response Creator):**
  ```
  "prompt": "Please consider the last 10 messages in the conversation:\n\n<conversation>\n{chat_user_prompt_last_ten}\n</conversation>\n\n{human_persona_name} has sent you a new message... Those thoughts were documented for you here:\n\n<inner_thoughts>\n{agent7Output}\n</inner_thoughts>\n\nPlease continue the conversation with {human_persona_name}...\n\n### conversation:\n\n{chat_user_prompt_last_two}",
  ```

### 4.2. External Data Injection (Personas)

For Pillar 1 workflows, `GetCustomFile` nodes are used at the beginning of the workflow to load static personas. This
data is then injected into the `systemPrompt` of subsequent nodes using the standard tag structure (e.g.,
`<your_profile>`, `<user_profile>`).

-----

## 5\. Node Configuration Patterns

Node configurations are highly specialized and strategic.

### 5.1. Specialization (`endpointName` / `preset`)

The methodology relies heavily on specialized backends for different cognitive tasks. Configuration names reflect this
specialization:

* `Thinker-Endpoint` / `Thinker_Preset`: For introspection and deep analysis.
* `Worker-Endpoint` / `Worker_Preset`: For fast, constrained utility tasks (extraction, formatting).
* `Responder-Endpoint` / `Responder_Preset`: For final message generation and polishing.
* `Coding-Endpoint` / `Coder_Preset`: For specialized code generation.

### 5.2. Strategic Token Allocation (`maxResponseSizeInTokens`)

Token limits are deliberately set based on the node's function:

* **Thinker/Internal Monologue:** Extremely high (8000-12000) to allow for verbose, detailed introspection.
* **Generation/Review:** High (4000-8000) to allow for complex outputs and detailed critiques.
* **Extraction/Utility:** Low (300-1000), constrained to the specific task to ensure speed and adherence to format.

### 5.3. Temporal Awareness (`addDiscussionIdTimestampsForLLM`)

Enabled (`true`), often with `useRelativeTimestamps: true`, specifically for Pillar 1 (Conversational) workflows. This
is required because the Internal Monologue nodes are explicitly prompted to analyze timestamps and time gaps. It is
disabled (`false`) for Pillar 2 (Utilitarian) workflows where time is irrelevant to the task.

### 6. Responses

The final responding node for most, if not all, of Socg's workflows revolves around a standard conversational node
that is presented with the final product of the workflow and told to continue the conversation with the user, utilizing
the final output. For example- in a coding workflow, there might be four to ten nodes that are doing work to write
a response, code review the response, correct the review, etc etc. Once all of this is done, that final corrected
response would be handed to an LLM, likely a responder or maybe a fast coder, and that model will be prompted to
utilize the crafted response to continue the conversation with the user.