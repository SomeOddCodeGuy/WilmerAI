### **`PromptTemplates` Configuration Files**

The `PromptTemplates` configuration files define how conversation history should be formatted before being sent to a
Large Language Model (LLM). Their primary function is to flatten a structured conversation (with system, user, and
assistant roles) into a single string, using specific control tokens and separators required by certain models.

This formatting is **only required for "Completions" style APIs** (e.g., KoboldCpp, older OpenAI models) that accept a
single text prompt. For modern "Chat Completions" APIs (e.g., OpenAI Chat, Ollama Chat) that accept a structured list of
messages, the settings in these files are ignored.

-----

#### **File Location and Association**

* **Location**: `PromptTemplates` files must be located in the `Public/Configs/PromptTemplates/` directory.
* **Association**: A template is associated with an LLM endpoint by setting the `promptTemplateFileName` property in
  that endpoint's configuration file (found in `Public/Configs/Endpoints/`). For example:
  `"promptTemplateFileName": "llama3.json"`.

-----

#### **Field Definitions**

Each `PromptTemplates` JSON file contains an object with a selection of the following key-value pairs. Keys that are
omitted from the file are treated as empty strings.

##### `promptTemplateSystemPrefix`

* **Description**: The string to be inserted **before** the system prompt's content.
* **Data Type**: `string`
* **Required**: No

-----

##### `promptTemplateSystemSuffix`

* **Description**: The string to be inserted **after** the system prompt's content.
* **Data Type**: `string`
* **Required**: No

-----

##### `promptTemplateUserPrefix`

* **Description**: The string to be inserted **before** every user message's content.
* **Data Type**: `string`
* **Required**: No

-----

##### `promptTemplateUserSuffix`

* **Description**: The string to be inserted **after** every user message's content.
* **Data Type**: `string`
* **Required**: No

-----

##### `promptTemplateAssistantPrefix`

* **Description**: The string to be inserted **before** every assistant message's content. This prefix is also added at
  the very end of the final prompt to signal to the model that it is its turn to generate a response.
* **Data Type**: `string`
* **Required**: No

-----

##### `promptTemplateAssistantSuffix`

* **Description**: The string to be inserted **after** every assistant message's content. This suffix is **automatically
  omitted** from the final assistant message in the history to prevent the model from generating it as part of its
  response.
* **Data Type**: `string`
* **Required**: No

-----

##### `promptTemplateEndToken`

* **Description**: A special token that can be appended to the end of the entire formatted prompt. Its inclusion is
  controlled by the `add_generation_prompt` flag in the `llm_handler` logic.
* **Data Type**: `string`
* **Required**: No

-----

#### **Example `PromptTemplate` File and Formatting Logic**

The following example shows how a conversation history is flattened into a single prompt string using a template file.

**Conversation History:**

1. **System:** `You are a helpful assistant.`
2. **User:** `Hello!`
3. **Assistant:** `Hi! How can I help?`
4. **User:** `What is WilmerAI?`

**Template File (`llama3.json`):**

```json
{
  "promptTemplateSystemPrefix": "<|start_header_id|>system<|end_header_id|>\n\n",
  "promptTemplateSystemSuffix": "<|eot_id|>",
  "promptTemplateUserPrefix": "<|start_header_id|>user<|end_header_id|>\n\n",
  "promptTemplateUserSuffix": "<|eot_id|>",
  "promptTemplateAssistantPrefix": "<|start_header_id|>assistant<|end_header_id|>\n\n",
  "promptTemplateAssistantSuffix": "<|eot_id|>"
}
```

**Final String Sent to Completions API:**
The system concatenates the prefix, content, and suffix for each message in order, and then adds the final assistant
prefix to cue the model's response.

```
<|start_header_id|>system<|end_header_id|>

You are a helpful assistant.<|eot_id|><|start_header_id|>user<|end_header_id|>

Hello!<|eot_id|><|start_header_id|>assistant<|end_header_id|>

Hi! How can I help?<|eot_id|><|start_header_id|>user<|end_header_id|>

What is WilmerAI?<|eot_id|><|start_header_id|>assistant<|end_header_id|>


```

-----

#### **Special Considerations**

* **No Special Tokens (`_chatonly.json`)**: WilmerAI includes a template named `_chatonly.json`. It uses only newlines (
  `\n`) for prefixes and suffixes. This is suitable for Completions-based models that do not require special tokens but
  still need the conversation history formatted as a single block of text.
* **Formatting Direction**: These templates only affect the prompt sent **to** the LLM. They do not parse or clean the
  response **from** the LLM. Response cleaning (e.g., removing prefixes like `Assistant:` from the model's output) is
  configured in the `Endpoint` and workflow node settings and handled by the `StreamingResponseHandler`.
* **Model Documentation**: Always refer to the official documentation for the target LLM to find the correct prompt
  format. The accuracy of the tokens and separators in the template file is critical for model performance.