### **`Preset` Configuration Files**

Preset files are JSON configurations that define the generation parameters for a Large Language Model (LLM). The system
directly passes the key-value pairs from a selected preset file into the final JSON payload sent to the LLM backend API.

This design allows WilmerAI to support any parameter offered by a target backend (e.g., KoboldCpp, Ollama,
OpenAI-compatible) without requiring changes to the core application code.

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

-----

#### **Important Considerations**

* **Parameter Precedence**: The property for setting the maximum number of new tokens (e.g., `max_tokens`, `max_length`)
  is controlled by the workflow node's configuration, **not** the preset file. The value from the node will always
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