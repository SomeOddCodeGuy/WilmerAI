# Tests/llmapis/handlers/base/test_base_completions_handler.py

"""
Unit tests for BaseCompletionsHandler (the single-string "completions" paradigm).

Impl-level tests (KoboldCpp, OpenAI completions) exercise this class through
their concrete subclasses; these tests pin the base contract directly:
prompt assembly (concatenation, strip, None handling, bracket restoration),
payload shape (prompt + gen_input only), the completion-text append gate, and
the documented silent ignoring of tools/tool_choice.
"""

from typing import Any, Dict, Optional

import pytest

from Middleware.llmapis.handlers.base.base_completions_handler import BaseCompletionsHandler


class ConcreteCompletionsHandler(BaseCompletionsHandler):
    """Concrete subclass so the abstract base can be instantiated."""

    def _get_api_endpoint_url(self) -> str:
        return "http://test.local/generate"

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        pass

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        pass


@pytest.fixture
def handler_factory():
    def _create(endpoint_config: Optional[Dict[str, Any]] = None,
                gen_input: Optional[Dict[str, Any]] = None):
        return ConcreteCompletionsHandler(
            base_url="http://test.local",
            api_key="test_key",
            gen_input=gen_input if gen_input is not None else {},
            model_name="test-model",
            headers={},
            stream=False,
            api_type_config={},
            endpoint_config=endpoint_config if endpoint_config is not None else {},
            max_tokens=100,
        )

    return _create


class TestBuildPromptFromConversation:
    def test_concatenates_system_and_prompt_and_strips(self, handler_factory):
        handler = handler_factory()
        result = handler._build_prompt_from_conversation(" You are a bot. ", "Hello! ")
        # system + prompt joined with no separator, outer whitespace stripped.
        assert result == "You are a bot. Hello!"

    def test_none_inputs_become_empty_string(self, handler_factory):
        handler = handler_factory()
        assert handler._build_prompt_from_conversation(None, None) == ""
        assert handler._build_prompt_from_conversation(None, "hi") == "hi"
        assert handler._build_prompt_from_conversation("sys", None) == "sys"

    def test_bracket_sentinels_restored(self, handler_factory):
        # Real return_brackets_in_string (no mock): WILMER curly sentinels
        # must come back as literal braces in the final prompt string.
        handler = handler_factory()
        result = handler._build_prompt_from_conversation(
            "__WILMER_L_CURLY__a__WILMER_R_CURLY__", "")
        assert result == "{a}"


class TestPreparePayload:
    def test_payload_is_prompt_plus_gen_input_only(self, handler_factory):
        handler = handler_factory(gen_input={"temperature": 0.5, "rep_pen": 1.1})
        payload = handler._prepare_payload(None, "Sys. ", "User")
        # set_gen_input with an empty api_type_config injects nothing structural,
        # so the payload is exactly the prompt plus the gen params. In particular
        # the completions paradigm never emits a "model" or "messages" key here.
        assert payload == {"prompt": "Sys. User", "temperature": 0.5, "rep_pen": 1.1}

    def test_completion_text_appended_when_flagged(self, handler_factory):
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": "\nAssistant:",
        }
        handler = handler_factory(endpoint_config=config)
        payload = handler._prepare_payload(None, None, "User prompt")
        assert payload["prompt"] == "User prompt\nAssistant:"

    def test_completion_text_not_appended_when_flag_off(self, handler_factory):
        config = {
            "addTextToStartOfCompletion": False,
            "textToAddToStartOfCompletion": "\nAssistant:",
        }
        handler = handler_factory(endpoint_config=config)
        payload = handler._prepare_payload(None, None, "User prompt")
        assert payload["prompt"] == "User prompt"

    def test_tools_and_tool_choice_silently_ignored(self, handler_factory):
        # Documented contract: completions APIs do not support tools; the kwargs
        # are accepted for interface compatibility and must not leak into the payload.
        handler = handler_factory()
        tools = [{"type": "function", "function": {"name": "t"}}]
        payload = handler._prepare_payload(None, None, "hi", tools=tools, tool_choice="auto")
        assert "tools" not in payload
        assert "tool_choice" not in payload
