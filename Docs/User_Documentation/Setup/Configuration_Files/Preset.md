### **`Preset` Configuration Files**

Preset files are JSON configurations that define the generation parameters for a Large Language Model (LLM). The system
directly passes the key-value pairs from a selected preset file into the final JSON payload sent to the LLM backend API.

This design allows WilmerAI to support any parameter offered by a target backend (e.g., KoboldCpp, Ollama,
OpenAI-compatible) without requiring changes to the core application code.

> **Newer alternative — embedded samplers on the endpoint.** Folder presets (described on this page)
> still work exactly as before and remain the fallback. But you can now avoid maintaining one preset
> file per API type by writing your samplers **once, in a canonical vocabulary, directly on the
> endpoint** via a `presetSamplers` block; Wilmer translates them to whatever the endpoint's API type
> needs and drops anything it does not support. See **Embedded Samplers (`presetSamplers`)** in
> [`Endpoint.md`](./Endpoint.md). A folder preset can still be layered on top of an embedded block as
> a native-field override via the endpoint's `appendPresetName`.

-----

#### **File Location and Structure**

Presets are loaded from a hierarchical directory structure, which allows for both shared (global) and user-specific
configurations. The base directory for all presets is `Public/Configs/Presets/`.

The full path to a preset file follows this pattern:
`Public/Configs/Presets/<ApiPresetType>/[username]/<preset_name>.json`

##### `<ApiPresetType>`

* **Description**: A folder name that groups presets for a specific type of API backend. This value is determined by the
  `presetType` key in the corresponding `ApiTypes` configuration file (`Public/Configs/ApiTypes/*.json`).
* **Example**: `Ollama`, `KoboldCpp`, `OpenAiCompatibleApis`

##### `[username]`

* **Description**: An optional subdirectory named after the current user (e.g., `default`). Presets in this folder are
  specific to that user and will override global presets with the same name.
* **Example**: `default`, `admin`

##### `<preset_name>.json`

* **Description**: The preset file itself. The filename, without the `.json` extension, serves as the preset's unique
  identifier within its `ApiPresetType` group.

##### Example presets

Each `<ApiPresetType>` folder ships a reference preset at `_example_preset/Example-Preset.json` showing the **native**
sampler fields that API type expects (for example `rep_pen` / `sampler_order` for KoboldCpp, `stop_sequences` for
ClaudeMessages, `think` for Ollama, `repetition_penalty` / `mirostat_mode` for Text-Generation-WebUI). The
`_example_preset` folder is a reference only and is not loaded at runtime; copy a file into your user's preset folder
(or the `<ApiPresetType>` root) and rename it to use it.

-----

#### **Preset Lookup Order**

When a workflow node requests a preset (e.g., `my_preset`), the system searches for the file in the following order:

1. **User-Specific Path**: It first checks the current user's directory.
    * `Public/Configs/Presets/OpenAiCompatibleApis/default/my_preset.json`
2. **Global Path**: If the file is not found in the user-specific path, it falls back to the parent `<ApiPresetType>`
   directory.
    * `Public/Configs/Presets/OpenAiCompatibleApis/my_preset.json`

This allows for default, global presets to be defined while also allowing individual users to create their own custom
overrides.

-----

#### **Preset Application Logic**

The key-value pairs defined in a preset's JSON file are injected directly into the body of the API request. The
`llmapis` handlers automatically format the final payload according to the requirements of the target backend.

##### **Standard Behavior**

For most backends, such as KoboldCpp and OpenAI-compatible APIs, the keys from the preset are merged into the top level
of the JSON payload.

* **Example `creative.json` Preset:**

  ```json
  {
    "temperature": 1.2,
    "top_p": 0.9,
    "stop_sequence": [
      "Human:",
      "\n"
    ]
  }
  ```

* **Resulting API Payload:**

  ```json
  {
    "prompt": "Once upon a time...",
    "temperature": 1.2,
    "top_p": 0.9,
    "stop_sequence": [
      "Human:",
      "\n"
    ],
    "max_tokens": 500
  }
  ```

##### **Backend-Specific Behavior (Ollama)**

Some backends, like Ollama, require generation parameters to be nested inside a specific JSON object. The `llmapis`
handlers for these backends manage this translation automatically. Using the same `creative.json` preset, the handler
for `ollamaApiChat` would place the parameters inside an `options` object.

* **Resulting Ollama API Payload:**
  ```json
  {
    "model": "llama3",
    "messages": [
      ...
    ],
    "options": {
      "temperature": 1.2,
      "top_p": 0.9,
      "stop": [
        "Human:",
        "\n"
      ]
    }
  }
  ```

The handler adapts the payload structure, but the parameter names (`temperature`, `top_p`, `stop`) and their values must
be valid for the target LLM backend. Always consult the API documentation for the specific backend in use.

One Ollama-specific exception to the `options` nesting: the `think` key is lifted back out to the top level of the
request, because Ollama reads the reasoning toggle as a top-level field rather than a sampler option. So a preset
key `"think": false` is sent as a top-level `think` in the request, while every other preset key stays inside `options`.

-----

#### **Disabling Model Reasoning ("Thinking") via Presets**

Many current models emit a separate reasoning/"thinking" stream before their answer. The shipped workflows assume
reasoning is **off** for the non-reasoning roles (`General`, `Fast`, `Vision`, `Worker`) and for every node inside a
manual chain-of-thought (`*_cot`) workflow, because those workflows enforce reasoning themselves and a second,
model-native reasoning pass is redundant. The reasoning roles (`General-Reasoning`, `Fast-Reasoning`) leave it **on**.

Whether thinking can actually be turned off from a preset depends entirely on the backend. Presets are passed straight
through to the backend payload (see above), so a preset can only disable thinking if the backend exposes a thinking
toggle in its request body. The table below summarizes what is possible per `ApiTypes` `presetType`:

| `presetType` | Handler payload shape | Disabling thinking from the preset |
| --- | --- | --- |
| `LlamaCppServer` | OpenAI `chat/completions`, preset keys merged top-level | Supported. `"chat_template_kwargs": { "enable_thinking": false, "thinking_budget": 0 }`. To enable, supply `"chat_template_kwargs": { "thinking_budget": <n> }` and omit `enable_thinking`. |
| `ClaudeMessages` | Anthropic `messages`, preset keys merged top-level | Supported, and off by default: omit the `thinking` key entirely. To enable, add `"thinking": { "type": "enabled", "budget_tokens": <n> }`. |
| `Text-Generation-WebUI` | OpenAI `chat/completions`, preset keys merged top-level | Best effort only. `"chat_template_kwargs": { "enable_thinking": false }` is honored only if the loaded backend forwards `chat_template_kwargs` into the chat template; not every TGW loader does. |
| `OllamaApiChat` / `OllamaApiGenerate` | sampler keys nested under `options`; `think` lifted to top level | Supported. Set `"think": false` in the preset. The handler lifts the `think` key out of `options` to the top level of the request, where Ollama reads it; all other keys stay under `options`. Omit `think` (or set it `true`) to let a thinking model reason. |
| `OpenAiCompatibleApis` | `/v1/completions`, preset keys merged top-level | Depends on the ApiType (this preset folder is shared). For the **raw `/v1/completions`** ApiType it is not possible from a preset: the text-completions endpoint runs no chat template, so `chat_template_kwargs` has nothing to act on, and you must control thinking through the prompt or the endpoint-level strip. The standard **OpenAI chat** ApiType does support it: an embedded `thinkingMode` resolves to `reasoning_effort` on the request. |
| `KoboldCpp` | `/api/v1/generate`, preset keys merged top-level | Not possible from a preset. KoboldCpp's generate API exposes no thinking toggle. Use the endpoint-level strip. |

##### Endpoint-level fallback

For any backend that cannot disable thinking from a preset, the reasoning text can still be removed from the model's
**output** at the endpoint level. Set `"removeThinking": true` on the `Endpoint` config and define `startThinkTag` /
`endThinkTag` (and `expectOnlyClosingThinkTag` if the model emits only a closing tag). This strips the reasoning block
after generation rather than preventing it, so the tokens are still spent, but the reasoning stays out of the
conversation that downstream nodes and the user see.

-----

#### **Important Considerations**

* **Parameter Precedence**: The property for setting the maximum number of new tokens (e.g., `max_tokens`, `max_length`)
  is controlled by the workflow node's configuration, **not** the preset file. The value from the node should always
  override any equivalent setting in the preset.
* **Valid JSON**: Preset files must be syntactically valid JSON.
* **Backend Documentation**: The parameter keys and value types used in a preset file must be supported by the target
  LLM backend API. WilmerAI sends the parameters as defined, but the backend is responsible for interpreting them.

-----

#### **Example Preset File (KoboldCpp)**

This is an annotated example of a preset configured for a KoboldCpp backend, demonstrating various supported parameters.

```json
{
  // Controls randomness. Higher is more creative.
  "temperature": 0.7,
  // Nucleus sampling: considers tokens comprising the top 90% probability mass.
  "top_p": 0.9,
  // Top-K sampling. A value of 0 disables it.
  "top_k": 0,
  // Repetition penalty. Values >1 discourage repeating tokens.
  "rep_pen": 1.1,
  // The token range to scan for repetition.
  "rep_pen_range": 1024,
  // The order in which to apply different sampling methods.
  "sampler_order": [
    6,
    0,
    1,
    3,
    4,
    2,
    5
  ],
  // A list of strings that will stop generation when produced.
  "stop_sequence": [
    "Human:",
    "USER:",
    "<|im_end|>",
    "</s>"
  ],
  // Whether to use the model's default list of banned token IDs.
  "use_default_badwordsids": false
}
```