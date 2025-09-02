### **`Endpoint` Configuration Files**

The Endpoint configuration files define a connection to a specific Large Language Model (LLM) backend. Each JSON file in
the `Public/Configs/Endpoints/` directory tells the WilmerAI middleware the server's address, its API format, and a set
of rules for injecting text into prompts and cleaning the model's raw responses.

-----

#### **Field Definitions**

Each Endpoint JSON file contains a single object with the following key-value pairs, organized by function.

-----

#### **Core Connection Details**

These fields are essential for establishing a connection to the LLM server.

##### `endpoint`

* **Description**: The full URL of the LLM API server, such as an OpenAI-compatible service.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"http://localhost:11434"`

##### `apiTypeConfigFileName`

* **Description**: The name of the JSON file (without the `.json` extension) from the `Public/Configs/ApiTypes/`
  directory. This file defines the specific API schema (e.g., Ollama, KoboldCpp, OpenAI) that WilmerAI should use for
  this endpoint.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"Ollama"`

##### `maxContextTokenSize`

* **Description**: The maximum context size in tokens that the model can handle. This value is used by the corresponding
  `ApiTypes` configuration to set the model's truncation length property.
* **Data Type**: `integer`
* **Required**: Yes
* **Example**: `8192`

-----

#### **Model Identification**

These fields control how the model is identified in the API request.

##### `modelNameForDisplayOnly`

* **Description**: A human-readable name for this endpoint configuration. This field is for your reference only and is *
  *not used by the application logic**.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"Local Llama3 for Summaries"`

##### `modelNameToSendToAPI`

* **Description**: The specific model identifier to be included in the API request payload. This is necessary for
  multi-model servers like Ollama or OpenAI.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"llama3:8b-instruct-q5_K_M"`

##### `dontIncludeModel`

* **Description**: If `true`, the `modelNameToSendToAPI` field and its corresponding key will be omitted from the API
  request payload. This is useful for single-model servers that do not accept a model parameter.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

#### **Prompt & Content Injection**

These settings allow for adding text to different parts of the prompt before it is sent to the LLM.

##### `addTextToStartOfSystem`

* **Description**: A flag that, when `true`, prepends the content of `textToAddToStartOfSystem` to the system prompt.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `textToAddToStartOfSystem`

* **Description**: The string content to prepend to the system prompt when `addTextToStartOfSystem` is enabled.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"/no_think "`

##### `addTextToStartOfPrompt`

* **Description**: A flag that, when `true`, prepends the content of `textToAddToStartOfPrompt` to the final user
  prompt. For Chat Completion APIs, this modifies the content of the last message with `role: "user"`.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

##### `textToAddToStartOfPrompt`

* **Description**: The string content to prepend to the user prompt when `addTextToStartOfPrompt` is enabled.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `""`

##### `addTextToStartOfCompletion`

* **Description**: A flag that, when `true`, appends the content of `textToAddToStartOfCompletion` to the end of the
  context to "seed" the AI's response, forcing it to begin its generation with the specified text.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `textToAddToStartOfCompletion`

* **Description**: The string content used to seed the AI's response when `addTextToStartOfCompletion` is enabled.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"<think>First, I will analyze the user's request.</think>"`

##### `ensureTextAddedToAssistantWhenChatCompletion`

* **Description**: Modifies the behavior of `addTextToStartOfCompletion` for Chat Completion APIs. If `true` and the
  last message is not from the assistant, a new `role: "assistant"` message is added containing the seed text. If
  `false`, the text is appended to the content of the last message, regardless of its role.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

#### **Response Cleaning & Filtering**

These settings process the raw text from the LLM after it is received. Operations are applied in this order: 1) Thinking
Block Removal, 2) Custom Prefix Removal, 3) Whitespace Trimming.

##### `removeThinking`

* **Description**: The master switch for the thinking block removal feature. If `true`, the system will attempt to find
  and remove text between `startThinkTag` and `endThinkTag`.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

##### `startThinkTag`

* **Description**: The opening tag that marks the beginning of a "thinking" block to be removed from the response.
  Case-insensitive.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"<think>"`

##### `endThinkTag`

* **Description**: The closing tag that marks the end of a "thinking" block. Case-insensitive.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"</think>"`

##### `openingTagGracePeriod`

* **Description**: The number of characters at the start of the response to scan for a `startThinkTag`. If the tag is
  not found within this window, removal is skipped for that response.
* **Data Type**: `integer`
* **Required**: Yes
* **Example**: `100`

##### `expectOnlyClosingThinkTag`

* **Description**: A special mode for models that may omit the opening tag. If `true`, the system buffers and discards
  all text until it finds the `endThinkTag`, then begins streaming the subsequent text.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

##### `removeCustomTextFromResponseStartEndpointWide`

* **Description**: If `true`, enables the removal of one of the strings defined in
  `responseStartTextToRemoveEndpointWide` from the beginning of the LLM's response.
* **Data Type**: `boolean`
* **Required**: Yes
* **Example**: `false`

##### `responseStartTextToRemoveEndpointWide`

* **Description**: A list of strings to remove from the beginning of the response. The system removes the first string
  in the list that it finds a match for.
* **Data Type**: `list of strings`
* **Required**: Yes
* **Example**: `["Assistant:", "Okay, here is the information you requested:"]`

##### `trimBeginningAndEndLineBreaks`

* **Description**: If `true`, any leading or trailing whitespace (spaces, newlines, tabs) is removed from the final
  response.
* \-**Data Type**: `boolean`
* **Required**: Yes
* **Example**: `true`

-----

#### **Example Endpoint File**

```json
{
  "modelNameForDisplayOnly": "Small model for all tasks",
  "endpoint": "http://12.0.0.1:5000",
  "apiTypeConfigFileName": "KoboldCpp",
  "maxContextTokenSize": 8192,
  "modelNameToSendToAPI": "",
  "trimBeginningAndEndLineBreaks": true,
  "dontIncludeModel": false,
  "removeThinking": true,
  "startThinkTag": "<think>",
  "endThinkTag": "</think>",
  "openingTagGracePeriod": 100,
  "expectOnlyClosingThinkTag": false,
  "addTextToStartOfSystem": true,
  "textToAddToStartOfSystem": "/no_think ",
  "addTextToStartOfPrompt": false,
  "textToAddToStartOfPrompt": "",
  "addTextToStartOfCompletion": false,
  "textToAddToStartOfCompletion": "",
  "ensureTextAddedToAssistantWhenChatCompletion": false,
  "removeCustomTextFromResponseStartEndpointWide": false,
  "responseStartTextToRemoveEndpointWide": []
}
```