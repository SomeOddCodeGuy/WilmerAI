# Canonical Samplers & Per-ApiType Translation

This document describes the endpoint-embedded preset system: how a single set of canonical sampler
values written on an endpoint is translated to each backend's native request fields at runtime, and
the known/assumed field set each ApiType was mapped against.

- **Code:** `Middleware/llmapis/sampler_translation.py` (pure translation/merge/normalize logic),
  `Middleware/llmapis/llm_api.py` (`_resolve_gen_input`), `set_gen_input` in
  `Middleware/llmapis/handlers/base/base_llm_api_handler.py`.

-----

## Why this exists

Presets historically lived as one JSON file per `(ApiType, user, preset-name)`. The same logical
preset had to be re-authored once per backend because each backend names its sampler fields
differently (`n_predict` vs `num_predict` vs `max_tokens`; `repeat_penalty` vs `rep_pen` vs
`repetition_penalty`). This produced a large file-management burden.

The embedded-preset system lets a user describe samplers **once, in a single canonical vocabulary**
(llama.cpp's field names), inside an endpoint's `presetSamplers` block. At request time Wilmer
translates those canonical values into whatever the calling endpoint's ApiType actually accepts, and
drops anything that ApiType does not support. The legacy folder-preset system is unchanged and is
used as the fallback.

-----

## Resolution chain

For a workflow node referencing endpoint **E** and preset name **P**:

1. If an endpoint named **P** exists and carries a `presetSamplers` block, translate that block to
   **E's** ApiType and use it. **P is only the value donor; E decides the translation target**, so an
   endpoint can borrow another endpoint's samplers even across API types. The common case is `P == E`
   (a node using its own endpoint's samplers).
2. Otherwise fall back to the legacy `Public/Configs/Presets/<presetType>/[user]/<P>.json` file,
   byte-for-byte unchanged.

An optional `appendPresetName` on E names a preset file (in E's native field names, **not**
translated) that is deep-merged on top as the highest-precedence override layer. It is resolved
through the same configurable preset path as any other preset, so it respects
`presetConfigsSubDirectoryOverride`.

The preset name is resolved as an **endpoint name** (not an arbitrary label). Endpoint names are
unique per endpoint folder, so this is collision-free by construction. Because no endpoint is named
like the legacy presets (`*-Preset` vs `*-Endpoint`), existing configs keep resolving to the folder
file and nothing changes for them.

-----

## The canonical vocabulary

Canonical field names are llama.cpp server's sampling fields (`CANONICAL_SAMPLER_FIELDS` in
`sampler_translation.py`). Writing one of these in a `presetSamplers` block makes it eligible for
translation; writing anything else (that is not a known special key) is treated as a likely typo and
dropped with a warning.

```
temperature  dynatemp_range  dynatemp_exponent  top_k  top_p  min_p  top_n_sigma  typical_p
repeat_penalty  repeat_last_n  presence_penalty  frequency_penalty
dry_multiplier  dry_base  dry_allowed_length  dry_penalty_last_n  dry_sequence_breakers
xtc_probability  xtc_threshold  mirostat  mirostat_tau  mirostat_eta
seed  stop  samplers  logit_bias  ignore_eos  n_probs  min_keep  grammar  json_schema
```

Plus two special block keys that are not flat samplers:

- **`thinkingMode`** — canonical reasoning control (see below).
- **`chat_template_kwargs`** — an open passthrough object (see below).

**Deliberately not canonical:** max-tokens, the streaming flag, and context truncation. Those are
injected structurally by `set_gen_input` from the node/endpoint (via the ApiType's
`maxNewTokensPropertyName` / `streamPropertyName` / `truncateLengthPropertyName`), so including them
as canonical samplers would double-handle them.

-----

## Per-ApiType mapping summary (the decision basis)

Each `Public/Configs/ApiTypes/*.json` file carries its own `samplerFieldMap`, `supportsChatTemplateKwargs`,
and `thinking` descriptor. The map is keyed **per ApiType file, not per wire protocol** — four
ApiTypes share the `openAIChatCompletion` handler yet accept very different sampler sets, so each
gets an independent map. The table below summarizes what each was mapped against; the authoritative
detail is in each config file.

| ApiType file | Wire protocol | Mapped fields | `chat_template_kwargs` | Thinking | Notable native renames |
| --- | --- | --- | --- | --- | --- |
| `LlamaCppServer` | openAIChatCompletion | 31 (full canonical) | Yes | `enable_thinking` in `chat_template_kwargs` | identity map |
| `OllamaApiChat` / `OllamaApiGenerate` | ollamaApiChat / ollamaApiGenerate | 14 | No | top-level `think` | identity (handler nests under `options`) |
| `KoboldCpp` | koboldCppGenerate | 24 | No | unsupported | `typical_p`→`typical`, `top_n_sigma`→`nsigma`, `repeat_penalty`→`rep_pen`, `repeat_last_n`→`rep_pen_range`, `seed`→`sampler_seed`, `stop`→`stop_sequence` |
| `Open-AI-API` | openAIChatCompletion | 7 | No | top-level `reasoning_effort` | identity (small set: no `top_k`/`min_p`/`mirostat`/etc.) |
| `OpenAI-Compatible-Completions` | openAIV1Completion | 7 | No | unsupported | identity (legacy completions) |
| `mlx-lm` | openAIChatCompletion | 10 | No | unsupported | `repeat_penalty`→`repetition_penalty`, `repeat_last_n`→`repetition_context_size` |
| `Text-Generation-WebUI` | openAIChatCompletion | 22 | No | unsupported | `repeat_penalty`→`repetition_penalty`, `repeat_last_n`→`repetition_penalty_range`, `mirostat`→`mirostat_mode`, `grammar`→`grammar_string` |
| `Claude` | claudeMessages | 4 | No | unsupported | `stop`→`stop_sequences` (only `temperature`/`top_p`/`top_k`/`stop` exist) |

Notes and assumptions made while authoring:

- **Drop-and-warn, never error.** A canonical knob absent from a target's `samplerFieldMap` (e.g.
  `min_p` to Claude/OpenAI) is dropped with a clear warn-level log naming the field, the ApiType, and
  the reason. This is expected: llama.cpp is a superset, so cloud targets drop most of it.
- **Ollama nesting is handled by the handler, not the map.** The Ollama handlers wrap `gen_input`
  into an `options` object themselves, so the map emits flat native names.
- **`chat_template_kwargs` is gated per ApiType.** It is only emitted for backends that accept it
  (currently `LlamaCppServer`). For others the whole object is dropped with a log, so it is never sent
  to e.g. Claude or real OpenAI. Its *inner* keys are never validated — they are defined by the loaded
  model's chat template, not by Wilmer.
- **Thinking is conservative on cloud/uncertain backends.** Only the cases with a clear native
  mechanism are mapped (`enable_thinking` for llama.cpp, `think` for Ollama, `reasoning_effort` for
  OpenAI). Claude, mlx-lm, KoboldCpp, Text-Generation-WebUI, and legacy completions are marked
  `unsupported` for `thinkingMode` in this version; control thinking on those via the endpoint-level
  `removeThinking` strip or native means.
- **Per-model gating is out of scope (by design).** Whether a *specific model* rejects samplers (e.g.
  adaptive Claude 4.7+ / OpenAI reasoning models rejecting `temperature`) is the user's
  responsibility; Wilmer only knows ApiType-level support and does not track individual model
  releases.

-----

## ApiType config schema additions

```jsonc
{
  // ... existing keys (type, presetType, *PropertyName) unchanged ...

  // canonical name -> this backend's native field name. Presence = supported.
  "samplerFieldMap": { "temperature": "temperature", "repeat_penalty": "rep_pen", ... },

  // whether the chat_template_kwargs passthrough object may be sent to this backend.
  "supportsChatTemplateKwargs": true,

  // how canonical thinkingMode resolves for this backend.
  //   mode: "bool" | "effort" | "unsupported"
  //   location: "top" | "chat_template_kwargs"   (for bool/effort)
  //   field: the native field name to emit
  "thinking": { "location": "chat_template_kwargs", "field": "enable_thinking", "mode": "bool" }
}
```

The existing `truncateLengthPropertyName` / `maxNewTokensPropertyName` / `streamPropertyName` keys are
**unchanged and still read exactly as before**; `samplerFieldMap` is purely additive, so existing
ApiType files need no migration.

-----

## thinkingMode resolution

`thinkingMode` accepts `off | on | low | medium | high` (the `off` synonyms `false`, `no`, `0`,
`none`, and `disabled` are also treated as off). `resolve_thinking` maps it per the ApiType's
`thinking` descriptor:

- **`mode: "bool"`** — `off` emits `false`, anything else `true`. Placed at `location` (top level, or
  inside `chat_template_kwargs`). Used by `LlamaCppServer` (`enable_thinking`) and Ollama (`think`).
- **`mode: "effort"`** — `off` emits nothing (you cannot turn a reasoning model "off" with a value, so
  the field is omitted); `low`/`medium`/`high` pass through; `on` defaults to `medium`. Used by
  `Open-AI-API` (`reasoning_effort`).
- **`mode: "unsupported"`** — `thinkingMode` is dropped with a warning.

Thinking budget is intentionally **not** a canonical field; it rides in raw `chat_template_kwargs`
(e.g. `"thinking_budget": 0`) for backends that accept that object, because its behavior is
model/template-dependent and often a no-op (stock Qwen templates read `enable_thinking`, not
`thinking_budget`).

-----

## Merge, omission, and the literal-null sentinel

All layers combine with a **recursive deep-merge** (`deep_merge`): when both sides are dicts they
merge recursively (so additions to `chat_template_kwargs` never clobber its other keys); otherwise the
higher-precedence layer wins. Scalars and arrays are atomic (replace, not concatenate).

After assembly and structural injection, `normalize_gen_input` runs once (at the tail of
`set_gen_input`, which every handler routes through):

- a value of `null` **drops the key** — the field is omitted so the backend uses its own default.
  This is also how a higher layer deletes a lower layer's value, and how a user keeps a field that
  "misbehaves if present at all" out of the payload.
- the sentinel string **`"__wilmer_null__"`** is replaced with a real `null` — the rare case where a
  literal JSON `null` must actually be sent.
- nested objects are processed recursively and dropped if they become empty (no `chat_template_kwargs:
  {}` is emitted).
- arrays are left untouched, so a stop sequence equal to the sentinel string stays literal.
- the structured payload keys `json_schema` and `grammar` are passed through verbatim (not recursed),
  so a meaningful literal `null` inside a schema is preserved rather than dropped.

`stream` is always injected (a transport decision). The max-tokens and context-truncation fields are
injected from the node/endpoint unless an explicit `null` is already present for them, which is
honored as a request to omit. Context truncation is only injected when the endpoint defines
`maxContextTokenSize`.

-----

## Adding or correcting a mapping

1. Find the backend's accepted request fields (consult the backend's own API
   documentation for its generation/sampling parameters).
2. Edit the relevant `Public/Configs/ApiTypes/<Name>.json`: add/adjust entries in `samplerFieldMap`
   (canonical name → native name), set `supportsChatTemplateKwargs`, and the `thinking` descriptor.
3. If a canonical field does not exist yet but should, add it to `CANONICAL_SAMPLER_FIELDS` in
   `sampler_translation.py` (otherwise it is treated as a typo and dropped).
4. Add a unit test in `Tests/llmapis/test_sampler_translation.py` asserting the rename/drop/thinking
   behavior for that ApiType.
