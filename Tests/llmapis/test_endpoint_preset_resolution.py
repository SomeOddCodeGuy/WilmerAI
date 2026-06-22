"""Integration tests for endpoint-embedded preset resolution and set_gen_input.

Covers the resolution chain in LlmApiService and the structural
injection + normalization in set_gen_input.
"""
import json
from unittest.mock import mock_open

import pytest

from Middleware.llmapis.handlers.impl.openai_api_handler import OpenAiApiHandler
from Middleware.llmapis.llm_api import LlmApiService

ENDPOINT = {
    "endpoint": "http://localhost:1234",
    "apiKey": "k",
    "modelNameToSendToAPI": "m",
    "apiTypeConfigFileName": "LlamaCppServer",
    "dontIncludeModel": False,
}

LLAMACPP_API = {
    "type": "openAIChatCompletion",
    "presetType": "LlamaCppServer",
    "supportsChatTemplateKwargs": True,
    "thinking": {"location": "chat_template_kwargs", "field": "enable_thinking", "mode": "bool"},
    "samplerFieldMap": {"temperature": "temperature", "min_p": "min_p", "top_p": "top_p"},
}

CLAUDE_API = {
    "type": "claudeMessages",
    "presetType": "ClaudeMessages",
    "supportsChatTemplateKwargs": False,
    "thinking": {"mode": "unsupported"},
    "samplerFieldMap": {"temperature": "temperature", "top_p": "top_p", "top_k": "top_k", "stop": "stop_sequences"},
}


def _build(mocker, *, endpoint=None, api_type=LLAMACPP_API, donor=None, preset_file=None):
    """Constructs an LlmApiService with the config layer mocked, returning its _gen_input."""
    endpoint = endpoint if endpoint is not None else dict(ENDPOINT)
    mocker.patch("Middleware.llmapis.llm_api.get_endpoint_config", return_value=endpoint)
    mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value=api_type)
    mocker.patch("Middleware.llmapis.llm_api.try_get_endpoint_config", return_value=donor)
    mocker.patch("Middleware.llmapis.llm_api.get_openai_preset_path", return_value="/fake/preset.json")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("builtins.open", mock_open(read_data=json.dumps(preset_file or {})))
    mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
    service = LlmApiService(endpoint="E", presetname="P", max_tokens=128)
    return service._gen_input


class TestPresetResolution:
    def test_embedded_block_translated(self, mocker):
        donor = {"presetSamplers": {"temperature": 0.6, "min_p": 0.05, "thinkingMode": "off"}}
        gen_input = _build(mocker, donor=donor)
        assert gen_input == {
            "temperature": 0.6,
            "min_p": 0.05,
            "chat_template_kwargs": {"enable_thinking": False},
        }

    def test_borrow_translates_to_consumer_apitype(self, mocker):
        # Node's endpoint is Claude; it borrows a block authored in canonical vocab.
        # min_p is unsupported on Claude (dropped); stop renames to stop_sequences.
        donor = {"presetSamplers": {"temperature": 0.6, "min_p": 0.05, "stop": ["x"]}}
        gen_input = _build(mocker, api_type=CLAUDE_API, donor=donor)
        assert gen_input == {"temperature": 0.6, "stop_sequences": ["x"]}

    def test_folder_fallback_when_not_an_endpoint(self, mocker):
        # No endpoint named P -> legacy folder preset is used verbatim.
        gen_input = _build(mocker, donor=None, preset_file={"temperature": 0.7, "top_p": 0.9})
        assert gen_input == {"temperature": 0.7, "top_p": 0.9}

    def test_append_preset_merges_and_wins(self, mocker):
        endpoint = dict(ENDPOINT, appendPresetName="extra")
        donor = {"presetSamplers": {"temperature": 0.6}}
        # The append file (native names) is the only thing opened; it overrides on collision.
        gen_input = _build(mocker, endpoint=endpoint, donor=donor,
                           preset_file={"temperature": 0.9, "min_p": 0.02})
        assert gen_input == {"temperature": 0.9, "min_p": 0.02}

    def test_backward_compat_folder_preset_unchanged(self, mocker):
        # A folder preset with fields Wilmer never modeled passes through untouched.
        raw = {"temperature": 0.3, "some_future_field": 42, "stop": ["</s>"]}
        gen_input = _build(mocker, donor=None, preset_file=raw)
        assert gen_input == raw


class TestSetGenInput:
    def _handler(self, gen_input, api_type, endpoint_config, max_tokens=100, stream=False):
        return OpenAiApiHandler(
            base_url="http://x", api_key="k", gen_input=gen_input, model_name="m",
            headers={}, stream=stream, api_type_config=api_type, endpoint_config=endpoint_config,
            max_tokens=max_tokens, dont_include_model=False,
        )

    API = {"streamPropertyName": "stream", "maxNewTokensPropertyName": "max_tokens",
           "truncateLengthPropertyName": "truncation_length"}

    def test_injects_structural_fields(self):
        h = self._handler({"temperature": 0.5}, self.API, {"maxContextTokenSize": 4096})
        h.set_gen_input()
        assert h.gen_input == {"temperature": 0.5, "stream": False, "max_tokens": 100, "truncation_length": 4096}

    def test_explicit_null_drops_sampler(self):
        h = self._handler({"temperature": 0.5, "repeat_penalty": None}, self.API, {"maxContextTokenSize": 4096})
        h.set_gen_input()
        assert "repeat_penalty" not in h.gen_input

    def test_missing_max_context_does_not_leak_null(self):
        # Latent bug fix: when maxContextTokenSize is absent, no truncation key is emitted.
        h = self._handler({"temperature": 0.5}, self.API, {})
        h.set_gen_input()
        assert "truncation_length" not in h.gen_input

    def test_explicit_null_suppresses_max_tokens(self):
        h = self._handler({"max_tokens": None}, self.API, {"maxContextTokenSize": 4096})
        h.set_gen_input()
        assert "max_tokens" not in h.gen_input

    def test_sentinel_forces_literal_null(self):
        from Middleware.llmapis.sampler_translation import SAMPLER_LITERAL_NULL
        h = self._handler({"draft_model": SAMPLER_LITERAL_NULL}, self.API, {})
        h.set_gen_input()
        assert h.gen_input["draft_model"] is None
