# /Middleware/llmapis/sampler_translation.py
"""
Canonical-to-native sampler translation for endpoint-embedded presets.

Wilmer lets a user describe generation samplers once, in a single canonical
vocabulary (llama.cpp's field set), inside an endpoint's ``presetSamplers``
block. At request time those canonical values are translated to whatever field
names the calling endpoint's ApiType actually accepts. This module owns that
translation plus the merge/normalization rules that govern how the final
generation payload is assembled.

Nothing here performs I/O. The functions are pure so they can be unit tested in
isolation and reused from both the request path and tests.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Reserved value that forces a literal JSON ``null`` onto the wire. A bare
# ``null`` in config means "omit this field" (use the backend default); this
# sentinel is the rare "actually send null" escape (e.g. mlx_lm draft_model
# unload). Namespaced to Wilmer so it can never collide with a real sampler
# value or a model-template key.
SAMPLER_LITERAL_NULL = "__wilmer_null__"

# Block keys that are not flat samplers and are handled specially by translate().
THINKING_MODE_KEY = "thinkingMode"
CHAT_TEMPLATE_KWARGS_KEY = "chat_template_kwargs"

# The canonical sampler vocabulary, based on llama.cpp server's sampling fields
# (reference doc section 1). A key present here but absent from an ApiType's
# samplerFieldMap is a knob that ApiType does not support (drop-and-warn). A key
# absent here entirely is treated as a likely typo. Max-tokens / stream /
# context-truncation are deliberately NOT canonical samplers: they are injected
# structurally from the node/endpoint by set_gen_input, so including them here
# would double-handle them.
CANONICAL_SAMPLER_FIELDS = frozenset({
    "temperature", "dynatemp_range", "dynatemp_exponent",
    "top_k", "top_p", "min_p", "top_n_sigma", "typical_p",
    "repeat_penalty", "repeat_last_n", "presence_penalty", "frequency_penalty",
    "dry_multiplier", "dry_base", "dry_allowed_length", "dry_penalty_last_n",
    "dry_sequence_breakers", "xtc_probability", "xtc_threshold",
    "mirostat", "mirostat_tau", "mirostat_eta",
    "seed", "stop", "samplers", "logit_bias", "ignore_eos",
    "n_probs", "min_keep", "grammar", "json_schema",
})

# Values of thinkingMode that mean "thinking off". Everything else is "on".
_THINKING_OFF = frozenset({"off", "false", "no", "0", "none", "disabled"})
_EFFORT_LEVELS = frozenset({"low", "medium", "high"})

# Sampler keys whose dict value is an opaque structured payload the backend consumes
# verbatim (a constrained-decoding schema / grammar). normalize_gen_input passes these
# through without recursing, so a meaningful literal null inside (e.g. a JSON Schema
# "default": null) is preserved instead of being dropped as an "omit field" marker.
_OPAQUE_SAMPLER_KEYS = frozenset({"json_schema", "grammar"})


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merges ``override`` onto ``base`` and returns a new dict.

    The merge rule is driven by the runtime value type so no per-field config is
    needed: when both sides hold a dict the dicts are merged
    recursively (so additions to an object like ``chat_template_kwargs`` never
    clobber its other keys); for any other collision the ``override`` value wins
    wholesale (scalars and arrays are atomic units). Neither input is mutated.

    Args:
        base (Dict[str, Any]): The lower-precedence layer.
        override (Dict[str, Any]): The higher-precedence layer; wins on collision.

    Returns:
        Dict[str, Any]: A new merged dictionary.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def normalize_gen_input(gen_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies the final emission pass to an assembled generation-parameter dict.

    For each object value: a JSON ``null`` drops the key (omit the
    field so the backend uses its own default); the ``SAMPLER_LITERAL_NULL``
    sentinel is replaced with a real ``None`` (force a literal null on the wire);
    a nested dict is processed recursively and dropped if it becomes empty (so no
    ``chat_template_kwargs: {}`` is emitted); everything else passes through.
    Arrays are left untouched, so a stop sequence equal to the sentinel string
    stays literal. Values under the opaque structured keys (``json_schema``,
    ``grammar``) are passed through verbatim rather than recursed, so a meaningful
    literal null inside a schema survives. A new dict is returned; the input is not
    mutated.

    Args:
        gen_input (Dict[str, Any]): The assembled generation parameters.

    Returns:
        Dict[str, Any]: The cleaned parameters ready to send.
    """
    result: Dict[str, Any] = {}
    for key, value in gen_input.items():
        if isinstance(value, dict):
            if key in _OPAQUE_SAMPLER_KEYS:
                result[key] = value
                continue
            cleaned = normalize_gen_input(value)
            if cleaned:
                result[key] = cleaned
        elif value is None:
            continue
        elif value == SAMPLER_LITERAL_NULL:
            result[key] = None
        else:
            result[key] = value
    return result


def resolve_thinking(thinking_mode: Any, api_type_config: Dict[str, Any], api_name: str) -> Dict[str, Any]:
    """
    Resolves the canonical ``thinkingMode`` to a backend-native fragment.

    Thinking control is not a key-to-key rename: it resolves on the
    backend into a mechanism, field name, value type, and location. That mapping
    is data-driven via the ApiType config's ``thinking`` descriptor
    ``{"location": "top"|"chat_template_kwargs", "field": <name>, "mode":
    "bool"|"effort"|"unsupported"}``. The returned fragment is meant to be
    deep-merged into the native output; an empty dict means "emit nothing".

    Args:
        thinking_mode (Any): The canonical value (off|on|low|medium|high).
        api_type_config (Dict[str, Any]): The target ApiType configuration.
        api_name (str): A human-readable ApiType name for log messages.

    Returns:
        Dict[str, Any]: A native fragment to merge, or ``{}`` if not emitted.
    """
    descriptor = api_type_config.get("thinking") or {}
    mode = descriptor.get("mode", "unsupported")

    if mode == "unsupported":
        logger.warning("Dropping thinkingMode=%r: ApiType '%s' has no thinking-control mapping.",
                       thinking_mode, api_name)
        return {}

    field = descriptor.get("field")
    if not field:
        logger.warning("Dropping thinkingMode: ApiType '%s' thinking descriptor is missing 'field'.", api_name)
        return {}

    normalized = str(thinking_mode).strip().lower()

    if mode == "bool":
        value: Any = normalized not in _THINKING_OFF
    elif mode == "effort":
        # Reasoning/effort backends cannot be turned "off" via a value; omitting
        # the field is how you decline. 'on' has no native meaning, so default it.
        if normalized in _THINKING_OFF:
            return {}
        value = normalized if normalized in _EFFORT_LEVELS else "medium"
    else:
        logger.warning("Dropping thinkingMode: unknown thinking mode %r for ApiType '%s'.", mode, api_name)
        return {}

    fragment = {field: value}
    if descriptor.get("location") == "chat_template_kwargs":
        return {CHAT_TEMPLATE_KWARGS_KEY: fragment}
    return fragment


def translate(canonical_block: Dict[str, Any], api_type_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translates a canonical ``presetSamplers`` block to native generation params.

    Flat samplers are renamed via the ApiType's ``samplerFieldMap`` and dropped
    (with a clear log) when the ApiType does not support them or the key is not a
    known canonical field. ``thinkingMode`` is routed through
    :func:`resolve_thinking`. ``chat_template_kwargs`` is passed through verbatim
    only when the ApiType accepts it (``supportsChatTemplateKwargs``); otherwise
    it is dropped. The block is never padded with defaults: only
    keys the user actually wrote are emitted.

    Args:
        canonical_block (Dict[str, Any]): The endpoint's ``presetSamplers`` block.
        api_type_config (Dict[str, Any]): The CALLING endpoint's ApiType config
            (the consumer decides the translation target, not the donor).

    Returns:
        Dict[str, Any]: Native generation parameters for the target ApiType.
    """
    field_map = api_type_config.get("samplerFieldMap") or {}
    supports_kwargs = bool(api_type_config.get("supportsChatTemplateKwargs", False))
    api_name = api_type_config.get("presetType") or api_type_config.get("nameForDisplayOnly") or "unknown"

    native: Dict[str, Any] = {}
    raw_kwargs = None
    thinking_mode = None

    for key, value in canonical_block.items():
        if key == THINKING_MODE_KEY:
            thinking_mode = value
        elif key == CHAT_TEMPLATE_KWARGS_KEY:
            raw_kwargs = value
        elif key in field_map:
            native[field_map[key]] = value
        elif key in CANONICAL_SAMPLER_FIELDS:
            logger.warning("Dropping sampler '%s': not supported by ApiType '%s'.", key, api_name)
        else:
            logger.warning("Dropping '%s': unknown canonical sampler key (likely a typo) for ApiType '%s'.",
                           key, api_name)

    # Thinking-resolver output is the base layer for chat_template_kwargs; the
    # user's raw passthrough (next) deep-merges on top so it wins per-leaf.
    if thinking_mode is not None:
        native = deep_merge(native, resolve_thinking(thinking_mode, api_type_config, api_name))

    if raw_kwargs is not None:
        if supports_kwargs:
            native = deep_merge(native, {CHAT_TEMPLATE_KWARGS_KEY: raw_kwargs})
        else:
            logger.warning("Dropping chat_template_kwargs: ApiType '%s' does not accept it.", api_name)

    return native
