### **`ApiTypes` Configuration Files**

The `ApiTypes` configuration files are the "drivers" for WilmerAI's `llmapis` layer. Each JSON file defines how the
middleware should communicate with a specific type of Large Language Model (LLM) backend API. It acts as a translator,
telling the system what to name the properties in the final JSON payload sent to the LLM.

This allows WilmerAI to support various backends—like Ollama, KoboldCpp, or any OpenAI-compatible service—without
changing its core code. You can add support for a new LLM provider simply by creating a new `ApiTypes` file.

-----

#### **Field Definitions**

Each `ApiTypes` JSON file contains a single object with the following key-value pairs.

##### `nameForDisplayOnly`

* **Description**: A human-readable name for this API configuration. This field is for your reference only and is **not
  used by the application logic**.
* **Data Type**: `string`
* **Required**: No
* **Example**: `"Ollama Llama3 8B Chat"`

-----

##### `type`

* **Description**: **This is the most critical field.** It's a specific string that tells the `LlmApiService` which
  internal handler to use for this API. Each handler is tailored to a specific API protocol (e.g., chat completions vs.
  single-string generation). Choosing the correct `type` ensures that the conversation history and parameters are
  formatted correctly.
* **Data Type**: `string`
* **Required**: Yes
* **Valid Values**: The value must be one of the following strings, as defined in `Middleware/llmapis/llm_api.py`:
    * `"openAIChatCompletion"`: For APIs following the OpenAI `/v1/chat/completions` standard, which uses a structured
      list of messages.
    * `"openAIV1Completion"`: For legacy APIs following the OpenAI `/v1/completions` standard, which takes a single
      flattened prompt string.
    * `"claudeMessages"`: For the Anthropic Claude Messages API, which uses a structured list of messages.
    * `"koboldCppGenerate"`: For the KoboldCpp `/api/v1/generate` endpoint. This is a completions-style API.
    * `"ollamaApiChat"`: For the Ollama `/api/chat` endpoint, which uses a message list and a nested `options` object
      for parameters. Supports images when used with the ImageProcessor node.
    * `"ollamaApiGenerate"`: For the Ollama `/api/generate` endpoint, which is a completions-style API with a nested
      `options` object.

  **Deprecated types (kept for backwards compatibility):** The following types are deprecated and route to their
  standard handlers. Use the regular types above instead - they support images when used with the ImageProcessor node:
    * `"koboldCppGenerateImageSpecific"` → use `"koboldCppGenerate"`
    * `"ollamaApiChatImageSpecific"` → use `"ollamaApiChat"`
    * `"openAIApiChatImageSpecific"` → use `"openAIChatCompletion"`

-----

##### `presetType`

* **Description**: Specifies the subfolder within `Public/Configs/Presets/` from which to load generation parameter
  presets (e.g., temperature, top\_k). This allows you to group presets that are compatible with a specific API type.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: If you set this to `"Ollama"`, the system will look for preset files in the
  `Public/Configs/Presets/Ollama/` directory.

-----

##### `truncateLengthPropertyName`

* **Description**: Defines the JSON key that the target API expects for setting the **maximum context size**. The actual
  numeric value for this key is pulled from the `maxContextTokenSize` field in your `Endpoints` configuration file. If
  the target API does not support this feature, you can omit this key or set its value to `null`.
* **Data Type**: `string` or `null`
* **Required**: No
* **Example**: For KoboldCpp, this would be `"max_context_length"`. For OpenAI, you would omit it.

-----

##### `maxNewTokensPropertyName`

* **Description**: Defines the JSON key that the target API expects for setting the **maximum number of new tokens to
  generate** in the response. The numeric value for this key is set in each individual node within a workflow's
  configuration. This is a mandatory setting for any LLM call.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: For OpenAI, this is `"max_tokens"`. For KoboldCpp, it's `"max_length"`.

-----

##### `streamPropertyName`

* **Description**: Defines the JSON key that the target API expects for the **streaming flag**. The boolean value (
  `true` or `false`) is determined by the `stream` parameter in the original request sent by the client application (
  e.g., SillyTavern).
* **Data Type**: `string`
* **Required**: Yes
* **Example**: For most APIs (OpenAI, Ollama, KoboldCpp), the value is simply `"stream"`.

-----

#### **Example `ApiTypes` File**

Here is a fully-commented example for an Ollama Chat API (`/api/chat`).

```json
{
  // A friendly name for UI or logging purposes. Not used by the program.
  "nameForDisplayOnly": "Ollama Chat API (e.g., Llama3)",
  // Critical key. Selects the OllamaChatHandler, which knows how to
  // format messages and parameters for Ollama's /api/chat endpoint.
  "type": "ollamaApiChat",
  // Tells the system to look for generation presets (temperature, top_p, etc.)
  // inside the /Public/Configs/Presets/Ollama/ directory.
  "presetType": "Ollama",
  // The Ollama API does not set max context via a top-level payload property;
  // it's often part of the model file or a parameter in the 'options' object.
  // The handler manages this, so we set it to null here.
  "truncateLengthPropertyName": null,
  // Specifies that the max tokens value should be sent in the payload
  // as: "num_predict": 1024. The Ollama handler will correctly place this
  // inside the nested "options" object.
  "maxNewTokensPropertyName": "num_predict",
  // Specifies that the streaming flag should be sent in the payload as:
  // "stream": true.
  "streamPropertyName": "stream"
}
```

#### Pre-defined ApiTypes

- **`Claude`**: For Anthropic's Claude Messages API. Chat completion API supporting structured message lists
- **`KoboldCpp`**: For KoboldCpp's text completion api. Supports images when used with the ImageProcessor node
- **`LlamaCppServer`**: For Llama.cpp chat completion api
- **`OllamaApiChat`**: For Ollama's chat completion api. Supports images when used with the ImageProcessor node
- **`OllamaApiGenerate`**: For Ollama's text completion api
- **`Open-AI-API`**: For standard OpenAI api compatible chat completion apis. Supports images when used with the
  ImageProcessor node
- **`OpenAI-Compatible-Completions`**: For standard OpenAI api compatible text completion apis
- **`Text-Generation-WebUI`**: For the Text Generation WebUI project's chat completion API
- **`mlx-lm`**: For Apple MLX model server

#### Image Support

Image processing is handled automatically by the ImageProcessor workflow node. When the ImageProcessor node is used,
images are passed to the LLM and the handler formats them appropriately for each API type. For non-ImageProcessor nodes,
images are automatically filtered out. This means you do not need separate "image-specific" API types - the same API
type works for both text-only and vision-capable workflows.