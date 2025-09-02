## The `ImageProcessor` Node

This guide provides a comprehensive, code-validated overview of the `ImageProcessor` node for WilmerAI. It details the
node's precise execution logic, properties, and best practices to enable developers and AI agents to author effective
image-aware workflows.

### Core Purpose

The **`ImageProcessor`** node serves as the essential bridge between user-provided images and the text-based nodes of a
workflow. Its primary function is to call a vision-capable LLM to generate detailed text descriptions of any images
present in the user's latest message. These text descriptions are then consolidated and made available to all subsequent
nodes, allowing text-only LLMs to "understand" and reason about visual content.

If the user's message contains no images, the node will output the string
`"There were no images attached to the message"` and the workflow will continue normally.

-----

### Internal Execution Flow: How It Handles Multiple Images

This section clarifies the precise, step-by-step operational logic of the node, which is crucial for understanding its
output. The node does **not** process images independently in parallel; it processes them sequentially and then *
*aggregates the results into a single output**.

1. **Isolate Content**: The node first separates the conversation history into two parts: a list of all text-based
   messages and a list of all image-based messages from the user's most recent turn.

2. **Sequential Processing Loop**: The node iterates through each image message one by one. For **each individual image
   **, it performs the following steps:

    * It creates a temporary, isolated context for the LLM call.
    * This context includes the **entire text history** of the conversation plus the **single image** currently being
      processed.
    * It calls the vision LLM specified in `endpointName` with this context, the `systemPrompt`, and the `prompt`.
    * The resulting text description for that single image is stored.

3. **Result Aggregation**: After the loop has finished and every image has been described, the node takes all the
   individual text descriptions it generated and joins them together into **one single string**. The descriptions are
   separated by the delimiter `\n-------------\n`.

4. **Final Output**: This final, consolidated string of all image descriptions becomes the node's output. This output is
   then handled in two ways simultaneously, depending on the node's configuration.

This logic directly answers the common question: *"Does the node wait for all descriptions before proceeding?"* **Yes,
it does.** It processes all images, combines their descriptions into a single block of text, and only then does it
complete its execution and allow the workflow to proceed to the next node.

-----

### Data Flow: The Two Ways to Access Image Descriptions

The `ImageProcessor` provides two powerful mechanisms for passing the aggregated text descriptions to the rest of the
workflow.

1. **Direct Output (`{agent#Output}`)**: The node **always** returns the aggregated string of descriptions as its
   standard output. If the `ImageProcessor` is the first node in a workflow, this string is immediately available to all
   subsequent nodes via the `{agent1Output}` variable. This method is ideal for workflows that require precise,
   controlled injection of the image content into a later prompt.

2. **Message Injection (`addAsUserMessage: true`)**: This is the most common and powerful method. When
   `addAsUserMessage` is set to `true`, the node performs an additional action: it creates a **single new user message**
   containing the *entire aggregated string* of descriptions and inserts it directly into the conversation history (just
   before the user's last message). This makes the descriptions a seamless part of the chat log, easily accessible to
   any subsequent node that processes the conversation history (e.g., using `lastMessagesToSendInsteadOfPrompt`).

-----

### Node Properties

This table details all the configuration properties for an `ImageProcessor` node, validated against the handler's source
code.

| Property               | Type    | Required? | Description                                                                                                                                                                                                                                                                               |
|:-----------------------|:--------|:----------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**             | String  | ✅ Yes     | Must be exactly `"ImageProcessor"`.                                                                                                                                                                                                                                                       |
| **`endpointName`**     | String  | ✅ Yes     | The static, hardcoded name of the vision-capable LLM endpoint that will analyze the image. **This field does not support variables.**                                                                                                                                                     |
| **`systemPrompt`**     | String  | ✅ Yes     | The system prompt sent to the **vision LLM**. This instructs the model on *how* to describe the image (e.g., its persona, desired level of detail, output format). It supports all standard workflow variables.                                                                           |
| **`prompt`**           | String  | ✅ Yes     | The user prompt sent to the **vision LLM**. This guides the model on *what* to focus on, often using conversation variables like `{chat_user_prompt_last_five}` for context. It supports all standard workflow variables.                                                                 |
| **`preset`**           | String  | ✅ Yes     | The static, hardcoded name of the generation preset (defining temperature, tokens, etc.) to be used by the vision LLM endpoint. **This field does not support variables.**                                                                                                                |
| **`addAsUserMessage`** | Boolean | ❌ No      | **Default: `false`**. If `true`, the node injects the aggregated image description into the conversation history as a new user message. If `false` (or omitted), the description is only available via `{agent#Output}`.                                                                  |
| **`message`**          | String  | ❌ No      | **Only used if `addAsUserMessage` is `true`**. A template string for the message that gets injected. It **must** contain the special `[IMAGE_BLOCK]` placeholder. If this property is omitted, a default system message is used instead. This field supports standard workflow variables. |

#### The `[IMAGE_BLOCK]` Placeholder: A Critical Note

The `[IMAGE_BLOCK]` placeholder is a special, context-specific keyword.

* **Valid Context**: It can **only** be used within the `message` property string of an `ImageProcessor` node.
* **Function**: It acts as the exact location where the node will insert the aggregated string of all image
  descriptions.
* **Warning**: Do **not** attempt to use `[IMAGE_BLOCK]` in any other node type (e.g., `Standard`) or in any other
  property (e.g., `prompt`). It has no function outside of the `ImageProcessor`'s `message` property and will be treated
  as literal text.

If `addAsUserMessage` is `true` and the `message` property is not provided, the system uses this default template:
`[SYSTEM: The user recently added one or more images to the conversation. The images have been analyzed by an advanced vision AI, which has described them in detail. The descriptions of the images can be found below:\n\n<vision_llm_response>\n[IMAGE_BLOCK]\n</vision_llm_response>]`

-----

### Workflow Strategy and Annotated Example

The most robust and effective strategy is to place the `ImageProcessor` as the **very first node** in a workflow. This
ensures that any visual information is immediately converted to text and made available to all subsequent text-based
nodes. Using the message injection method (`addAsUserMessage: true`) is highly recommended as it simplifies the logic
for the final responding node.

#### Annotated Example Workflow

This workflow demonstrates the recommended pattern. The first node processes any images and injects the description
directly into the chat history. The second node is a standard text-based agent that can now "see" the image content
because it's part of the conversation log it receives.

```json
[
  {
    "title": "Step 1: Analyze and Describe All User Images",
    "type": "ImageProcessor",
    "endpointName": "Image-Endpoint",
    "preset": "Vision_Default_Preset",
    "addAsUserMessage": true,
    // --- BEHAVIOR CONTROL ---
    // This is the key. The aggregated description will be added to the chat history
    // as a single new user message, making it visible to the next node.
    "message": "[SYSTEM: An image analysis module has processed the user's recent image(s). The detailed, consolidated description is below:\n\n[IMAGE_BLOCK]\n\nThis description is now part of our conversation.]",
    // --- VISION LLM PROMPTS ---
    "systemPrompt": "You are a world-class visual analysis AI. Your task is to describe an image in meticulous detail for a text-only AI assistant. Be objective, precise, and capture everything.",
    "prompt": "Based on our recent conversation context provided below, analyze the image the user just sent.\n\nRecent Messages:\n{chat_user_prompt_last_five}\n\nDescribe the image's contents in extreme detail. Transcribe any and all text you see verbatim. Leave no stone unturned; the assistant's response depends entirely on the quality of your description."
  },
  {
    "title": "Step 2: Formulate Final Response to User",
    "type": "Standard",
    // This is a regular, text-only LLM node.
    "endpointName": "Creative-Text-Endpoint",
    "preset": "Helpful_Assistant_Preset",
    "returnToUser": true,
    // --- FINAL RESPONSE PROMPTS ---
    "systemPrompt": "You are a helpful AI assistant. Today is {todays_date_pretty}. Your user may have just sent an image, which has been described by a vision system. This description is now part of the conversation history. Analyze the full history, including the image description, and provide a comprehensive response.",
    // The main prompt is left empty, as we instruct the node to use the conversation history,
    // which now contains the injected message from the ImageProcessor node.
    "prompt": "",
    "lastMessagesToSendInsteadOfPrompt": 25
    // This sends the last 25 messages, including the newly injected description, to the LLM.
  }
]
```