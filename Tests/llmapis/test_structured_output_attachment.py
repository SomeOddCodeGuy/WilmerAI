"""Payload attachment tests for the declarative structuredOutput ApiType block."""
import pytest

from Middleware.llmapis.handlers.impl.ollama_chat_api_handler import OllamaChatHandler
from Middleware.llmapis.handlers.impl.openai_api_handler import OpenAiApiHandler

SCHEMA = {"type": "object",
          "properties": {"name": {"const": "t"}, "arguments": {"type": "object"}},
          "required": ["name", "arguments"]}


def _make(handler_cls, api_type_config):
    return handler_cls(
        base_url="http://localhost:8080",
        api_key="",
        gen_input={"temperature": 0.5},
        model_name="test-model",
        headers={},
        stream=False,
        api_type_config=api_type_config,
        endpoint_config={},
        max_tokens=100,
        dont_include_model=False,
    )


class TestResponseFormatMechanism:
    def test_openai_style_wrapper_attached(self):
        handler = _make(OpenAiApiHandler,
                        {"structuredOutput": {"field": "response_format", "style": "openaiJsonSchema"},
                         "streamPropertyName": "stream"})
        payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None,
                                           structured_output_schema=SCHEMA)
        rf = payload["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "wilmer_structured_output"
        assert rf["json_schema"]["strict"] is True
        assert rf["json_schema"]["schema"] == SCHEMA

    def test_no_schema_means_no_response_format(self):
        handler = _make(OpenAiApiHandler,
                        {"structuredOutput": {"field": "response_format", "style": "openaiJsonSchema"},
                         "streamPropertyName": "stream"})
        payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None)
        assert "response_format" not in payload

    def test_no_mechanism_leaves_payload_unconstrained_with_warning(self, caplog):
        handler = _make(OpenAiApiHandler, {"streamPropertyName": "stream"})
        with caplog.at_level("WARNING"):
            payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None,
                                               structured_output_schema=SCHEMA)
        assert "response_format" not in payload
        assert "format" not in payload
        assert any("no valid structuredOutput block" in r.message for r in caplog.records)


class TestOllamaFormatMechanism:
    def test_schema_attached_as_top_level_format(self):
        handler = _make(OllamaChatHandler,
                        {"structuredOutput": {"field": "format", "style": "raw"},
                         "streamPropertyName": "stream"})
        payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None,
                                           structured_output_schema=SCHEMA)
        assert payload["format"] == SCHEMA
        # format is a transport-level field, not a sampler option.
        assert "format" not in payload["options"]

    def test_no_schema_means_no_format_field(self):
        handler = _make(OllamaChatHandler,
                        {"structuredOutput": {"field": "format", "style": "raw"},
                         "streamPropertyName": "stream"})
        payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None)
        assert "format" not in payload


class TestDottedFieldPath:
    def test_nested_field_written_via_dotted_path(self):
        # vLLM-style native field, expressible purely in ApiType JSON.
        handler = _make(OpenAiApiHandler,
                        {"structuredOutput": {"field": "structured_outputs.json", "style": "raw"},
                         "streamPropertyName": "stream"})
        payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None,
                                           structured_output_schema=SCHEMA)
        assert payload["structured_outputs"]["json"] == SCHEMA
        assert "response_format" not in payload

    def test_non_dict_intermediate_is_coerced_not_crashed(self):
        # A sampler/preset value occupying the intermediate key must not make
        # the dotted-path walk raise; the constraint wins the slot.
        handler = _make(OpenAiApiHandler,
                        {"structuredOutput": {"field": "structured_outputs.json", "style": "raw"},
                         "streamPropertyName": "stream"})
        payload = {"structured_outputs": "preset-junk"}
        handler._attach_structured_output(payload, SCHEMA)
        assert payload["structured_outputs"]["json"] == SCHEMA


class TestStrictDeclaration:
    def test_strict_false_sends_non_strict_wrapper(self):
        handler = _make(OpenAiApiHandler,
                        {"structuredOutput": {"field": "response_format",
                                              "style": "openaiJsonSchema", "strict": False},
                         "streamPropertyName": "stream"})
        payload = handler._prepare_payload([{"role": "user", "content": "hi"}], None, None,
                                           structured_output_schema=SCHEMA)
        assert payload["response_format"]["json_schema"]["strict"] is False


class TestFieldCollisionWarning:
    def test_overwriting_existing_payload_field_warns(self, caplog):
        handler = _make(OpenAiApiHandler,
                        {"structuredOutput": {"field": "response_format", "style": "openaiJsonSchema"},
                         "streamPropertyName": "stream"})
        payload = {"response_format": {"type": "json_object"}}
        with caplog.at_level("WARNING"):
            handler._attach_structured_output(payload, SCHEMA)
        assert payload["response_format"]["type"] == "json_schema"
        assert any("overwriting the existing payload field" in r.message for r in caplog.records)
