"""Unit tests for Middleware/llmapis/sampler_translation.py."""
import pytest

from Middleware.llmapis.sampler_translation import (
    SAMPLER_LITERAL_NULL,
    deep_merge,
    normalize_gen_input,
    resolve_thinking,
    translate,
)


# --- deep_merge -----------------------------------------------------------

class TestDeepMerge:
    def test_scalar_override_wins(self):
        assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_disjoint_keys_union(self):
        assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_nested_dicts_merge_recursively(self):
        base = {"ctk": {"enable_thinking": False}}
        override = {"ctk": {"reasoning_effort": "high"}}
        assert deep_merge(base, override) == {
            "ctk": {"enable_thinking": False, "reasoning_effort": "high"}
        }

    def test_nested_leaf_collision_override_wins(self):
        base = {"ctk": {"enable_thinking": False}}
        override = {"ctk": {"enable_thinking": True}}
        assert deep_merge(base, override) == {"ctk": {"enable_thinking": True}}

    def test_arrays_are_replaced_not_concatenated(self):
        assert deep_merge({"stop": ["a"]}, {"stop": ["b"]}) == {"stop": ["b"]}

    def test_dict_replaces_scalar_and_vice_versa(self):
        assert deep_merge({"a": 1}, {"a": {"x": 1}}) == {"a": {"x": 1}}
        assert deep_merge({"a": {"x": 1}}, {"a": 2}) == {"a": 2}

    def test_inputs_not_mutated(self):
        base = {"ctk": {"a": 1}}
        override = {"ctk": {"b": 2}}
        deep_merge(base, override)
        assert base == {"ctk": {"a": 1}}
        assert override == {"ctk": {"b": 2}}


# --- normalize_gen_input --------------------------------------------------

class TestNormalizeGenInput:
    def test_null_drops_key(self):
        assert normalize_gen_input({"temperature": 0.5, "repeat_penalty": None}) == {"temperature": 0.5}

    def test_sentinel_becomes_literal_null(self):
        assert normalize_gen_input({"draft_model": SAMPLER_LITERAL_NULL}) == {"draft_model": None}

    def test_recurses_into_nested_objects(self):
        src = {"ctk": {"keep": True, "drop": None, "force": SAMPLER_LITERAL_NULL}}
        assert normalize_gen_input(src) == {"ctk": {"keep": True, "force": None}}

    def test_emptied_object_is_dropped(self):
        assert normalize_gen_input({"ctk": {"a": None}}) == {}

    def test_arrays_are_left_untouched(self):
        # A stop sequence equal to the sentinel string must stay literal.
        src = {"stop": [SAMPLER_LITERAL_NULL, None]}
        assert normalize_gen_input(src) == {"stop": [SAMPLER_LITERAL_NULL, None]}

    def test_falsy_values_are_preserved(self):
        src = {"temperature": 0, "flag": False, "text": ""}
        assert normalize_gen_input(src) == {"temperature": 0, "flag": False, "text": ""}

    def test_input_not_mutated(self):
        src = {"a": None, "b": 1}
        normalize_gen_input(src)
        assert src == {"a": None, "b": 1}

    def test_json_schema_is_opaque_and_keeps_literal_nulls(self):
        # A constrained-decoding schema is a verbatim payload: a literal null inside
        # it (here a JSON Schema "default": null) must survive, not be dropped as an
        # "omit field" marker the way a top-level null is.
        src = {"json_schema": {"type": "object", "properties": {"x": {"default": None}}}}
        assert normalize_gen_input(src) == src

    def test_grammar_object_is_passed_through_verbatim(self):
        src = {"grammar": {"root": "x", "ignored": None}}
        assert normalize_gen_input(src) == {"grammar": {"root": "x", "ignored": None}}


# --- resolve_thinking -----------------------------------------------------

LLAMACPP_THINKING = {"thinking": {"location": "chat_template_kwargs", "field": "enable_thinking", "mode": "bool"}}
OLLAMA_THINKING = {"thinking": {"location": "top", "field": "think", "mode": "bool"}}
OPENAI_THINKING = {"thinking": {"location": "top", "field": "reasoning_effort", "mode": "effort"}}


class TestResolveThinking:
    def test_bool_off_into_chat_template_kwargs(self):
        assert resolve_thinking("off", LLAMACPP_THINKING, "llama") == {
            "chat_template_kwargs": {"enable_thinking": False}
        }

    def test_bool_on_top_level(self):
        assert resolve_thinking("on", OLLAMA_THINKING, "ollama") == {"think": True}

    def test_effort_off_emits_nothing(self):
        assert resolve_thinking("off", OPENAI_THINKING, "openai") == {}

    def test_effort_level_passthrough(self):
        assert resolve_thinking("high", OPENAI_THINKING, "openai") == {"reasoning_effort": "high"}

    def test_effort_on_defaults_to_medium(self):
        assert resolve_thinking("on", OPENAI_THINKING, "openai") == {"reasoning_effort": "medium"}

    def test_unsupported_apitype_drops(self):
        assert resolve_thinking("on", {"thinking": {"mode": "unsupported"}}, "claude") == {}

    def test_missing_descriptor_drops(self):
        assert resolve_thinking("on", {}, "kobold") == {}

    @pytest.mark.parametrize("off_value", [
        # Documented off-synonyms
        "off", "false", "no", "0", "none", "disabled",
        # Case and whitespace variants (values are normalized via str().strip().lower())
        "OFF", " off ", "  FALSE  ",
        # Non-strings: str(False) -> "false", str(0) -> "0", both in the off-set
        False, 0,
    ])
    def test_bool_mode_off_synonyms(self, off_value):
        assert resolve_thinking(off_value, OLLAMA_THINKING, "ollama") == {"think": False}

    @pytest.mark.parametrize("off_value", ["off", "FALSE", " none ", False, 0])
    def test_effort_mode_off_synonyms_emit_nothing(self, off_value):
        assert resolve_thinking(off_value, OPENAI_THINKING, "openai") == {}

    def test_valid_mode_missing_field_drops(self):
        descriptor = {"thinking": {"location": "top", "mode": "bool"}}
        assert resolve_thinking("off", descriptor, "ollama") == {}

    def test_unknown_mode_string_drops(self):
        descriptor = {"thinking": {"location": "top", "field": "think", "mode": "fancy"}}
        assert resolve_thinking("on", descriptor, "ollama") == {}

    def test_effort_invalid_level_defaults_to_medium(self):
        assert resolve_thinking("maximum", OPENAI_THINKING, "openai") == {"reasoning_effort": "medium"}


# --- translate ------------------------------------------------------------

LLAMACPP_CFG = {
    "presetType": "LlamaCppServer",
    "supportsChatTemplateKwargs": True,
    "thinking": {"location": "chat_template_kwargs", "field": "enable_thinking", "mode": "bool"},
    "samplerFieldMap": {
        "temperature": "temperature", "top_p": "top_p", "min_p": "min_p", "top_k": "top_k",
        "repeat_penalty": "repeat_penalty", "stop": "stop",
    },
}

KOBOLD_CFG = {
    "presetType": "KoboldCpp",
    "supportsChatTemplateKwargs": False,
    "thinking": {"mode": "unsupported"},
    "samplerFieldMap": {
        "temperature": "temperature", "top_p": "top_p", "repeat_penalty": "rep_pen", "stop": "stop_sequence",
    },
}

CLAUDE_CFG = {
    "presetType": "ClaudeMessages",
    "supportsChatTemplateKwargs": False,
    "thinking": {"mode": "unsupported"},
    "samplerFieldMap": {"temperature": "temperature", "top_p": "top_p", "top_k": "top_k", "stop": "stop_sequences"},
}


class TestTranslate:
    def test_flat_rename(self):
        assert translate({"temperature": 0.5, "repeat_penalty": 1.1}, KOBOLD_CFG) == {
            "temperature": 0.5, "rep_pen": 1.1
        }

    def test_unsupported_canonical_field_dropped(self):
        # min_p is a known canonical field but Kobold's map here lacks it.
        assert translate({"temperature": 0.5, "min_p": 0.05}, KOBOLD_CFG) == {"temperature": 0.5}

    def test_unknown_key_dropped_as_typo(self):
        assert translate({"temperature": 0.5, "temprature": 0.9}, LLAMACPP_CFG) == {"temperature": 0.5}

    def test_no_padding_only_present_keys(self):
        # Nothing beyond what the user wrote should appear.
        assert translate({"temperature": 0.5}, LLAMACPP_CFG) == {"temperature": 0.5}

    def test_stop_renamed_for_claude(self):
        assert translate({"stop": ["<|im_end|>"]}, CLAUDE_CFG) == {"stop_sequences": ["<|im_end|>"]}

    def test_thinking_into_chat_template_kwargs(self):
        assert translate({"temperature": 0.5, "thinkingMode": "off"}, LLAMACPP_CFG) == {
            "temperature": 0.5,
            "chat_template_kwargs": {"enable_thinking": False},
        }

    def test_thinking_and_raw_kwargs_deep_merge(self):
        block = {"thinkingMode": "off", "chat_template_kwargs": {"thinking_budget": 0}}
        assert translate(block, LLAMACPP_CFG) == {
            "chat_template_kwargs": {"enable_thinking": False, "thinking_budget": 0}
        }

    def test_raw_kwargs_wins_leaf_collision(self):
        block = {"thinkingMode": "off", "chat_template_kwargs": {"enable_thinking": True}}
        assert translate(block, LLAMACPP_CFG) == {
            "chat_template_kwargs": {"enable_thinking": True}
        }

    def test_chat_template_kwargs_dropped_when_unsupported(self):
        block = {"temperature": 0.5, "chat_template_kwargs": {"enable_thinking": False}}
        assert translate(block, CLAUDE_CFG) == {"temperature": 0.5}

    def test_donor_block_not_mutated(self):
        block = {"temperature": 0.5, "chat_template_kwargs": {"a": 1}}
        translate(block, LLAMACPP_CFG)
        assert block == {"temperature": 0.5, "chat_template_kwargs": {"a": 1}}

    def test_missing_sampler_field_map_drops_all_canonical_fields(self):
        # A legacy ApiType file with no samplerFieldMap at all supports nothing:
        # every canonical field is dropped (warn), yielding an empty native block
        # instead of raising or passing fields through untranslated.
        legacy_cfg = {"presetType": "Legacy"}
        assert translate({"temperature": 0.5, "top_p": 0.9, "stop": ["x"]}, legacy_cfg) == {}

    def test_thinking_mode_dropped_for_unsupported_apitype(self):
        # An unsupported ApiType resolves thinkingMode to an empty fragment; the
        # merge emits nothing and the canonical key itself never survives.
        assert translate({"temperature": 0.5, "thinkingMode": "off"}, CLAUDE_CFG) == {"temperature": 0.5}
        assert translate({"thinkingMode": "off"}, KOBOLD_CFG) == {}
