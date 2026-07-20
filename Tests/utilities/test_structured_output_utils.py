import json

from Middleware.utilities.structured_output_utils import (
    build_tool_calls_result,
    build_tool_enforcement_schema,
    build_tools_description_text,
    get_forced_tool_name,
    get_structured_output_config,
    parse_constrained_tool_response,
)

GENERATE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": "Generate an image from a text description.",
        "parameters": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "enum": ["AAM XL AnimeMix"]},
                "prompt": {"type": "string"},
            },
            "required": ["model", "prompt"],
        },
    },
}
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    },
}
FORCED = {"type": "function", "function": {"name": "generate_image"}}


class TestGetStructuredOutputConfig:
    def test_openai_json_schema_style(self):
        config = {"structuredOutput": {"field": "response_format", "style": "openaiJsonSchema"}}
        assert get_structured_output_config(config) == \
               {"field": "response_format", "style": "openaiJsonSchema", "strict": True}

    def test_raw_style(self):
        config = {"structuredOutput": {"field": "format", "style": "raw"}}
        assert get_structured_output_config(config) == \
               {"field": "format", "style": "raw", "strict": True}

    def test_strict_false_declared(self):
        """An API type aimed at a backend enforcing OpenAI strict-mode schema
        rules can declare strict:false to send non-strict json_schema."""
        config = {"structuredOutput": {"field": "response_format",
                                       "style": "openaiJsonSchema", "strict": False}}
        assert get_structured_output_config(config)["strict"] is False

    def test_strict_defaults_true_for_non_bool_junk(self):
        config = {"structuredOutput": {"field": "response_format",
                                       "style": "openaiJsonSchema", "strict": "nonsense"}}
        assert get_structured_output_config(config)["strict"] is True

    def test_dotted_field_accepted(self):
        config = {"structuredOutput": {"field": "structured_outputs.json", "style": "raw"}}
        assert get_structured_output_config(config)["field"] == "structured_outputs.json"

    def test_absent_block_means_none(self):
        assert get_structured_output_config({"type": "openAIChatCompletion"}) is None

    def test_unknown_style_means_none(self):
        config = {"structuredOutput": {"field": "grammar", "style": "gbnf"}}
        assert get_structured_output_config(config) is None

    def test_missing_field_means_none(self):
        config = {"structuredOutput": {"style": "raw"}}
        assert get_structured_output_config(config) is None

    def test_non_dict_config_means_none(self):
        assert get_structured_output_config(None) is None
        assert get_structured_output_config("LlamaCppServer") is None


class TestGetForcedToolName:
    def test_forced_function_object(self):
        assert get_forced_tool_name(FORCED) == "generate_image"

    def test_auto_required_none_and_absent(self):
        assert get_forced_tool_name("auto") is None
        assert get_forced_tool_name("required") is None
        assert get_forced_tool_name("none") is None
        assert get_forced_tool_name(None) is None

    def test_malformed_objects(self):
        assert get_forced_tool_name({"type": "function"}) is None
        assert get_forced_tool_name({"type": "function", "function": {}}) is None
        assert get_forced_tool_name({"type": "tool", "name": "x"}) is None


class TestBuildToolEnforcementSchema:
    def test_forced_uses_the_tools_parameter_schema(self):
        schema = build_tool_enforcement_schema([GENERATE_IMAGE_TOOL, SEARCH_TOOL], FORCED)
        assert schema["properties"]["name"]["const"] == "generate_image"
        assert schema["properties"]["arguments"] == \
               GENERATE_IMAGE_TOOL["function"]["parameters"]
        assert schema["required"] == ["name", "arguments"]

    def test_forced_tool_missing_from_definitions_constrains_name_only(self):
        schema = build_tool_enforcement_schema([SEARCH_TOOL], FORCED)
        assert schema["properties"]["name"]["const"] == "generate_image"
        assert schema["properties"]["arguments"] == {"type": "object"}

    def test_required_builds_anyof_across_tools(self):
        schema = build_tool_enforcement_schema([GENERATE_IMAGE_TOOL, SEARCH_TOOL], "required")
        names = [e["properties"]["name"]["const"] for e in schema["anyOf"]]
        assert names == ["generate_image", "web_search"]

    def test_required_with_single_tool_is_flat(self):
        schema = build_tool_enforcement_schema([SEARCH_TOOL], "required")
        assert "anyOf" not in schema
        assert schema["properties"]["name"]["const"] == "web_search"

    def test_required_with_no_usable_tools_is_none(self):
        assert build_tool_enforcement_schema([], "required") is None
        assert build_tool_enforcement_schema([{"type": "function"}], "required") is None

    def test_auto_and_none_do_not_constrain(self):
        assert build_tool_enforcement_schema([GENERATE_IMAGE_TOOL], "auto") is None
        assert build_tool_enforcement_schema([GENERATE_IMAGE_TOOL], None) is None
        assert build_tool_enforcement_schema([GENERATE_IMAGE_TOOL], "none") is None

    def test_tool_without_parameters_gets_open_object(self):
        bare = {"type": "function", "function": {"name": "ping"}}
        schema = build_tool_enforcement_schema([bare], "required")
        assert schema["properties"]["arguments"] == {"type": "object"}


class TestBuildToolsDescriptionText:
    def test_forced_names_the_required_tool(self):
        text = build_tools_description_text([GENERATE_IMAGE_TOOL, SEARCH_TOOL], FORCED)
        assert "calling the tool 'generate_image'" in text
        assert "- generate_image: Generate an image" in text
        assert "- web_search: Search the web." in text
        assert json.dumps(GENERATE_IMAGE_TOOL["function"]["parameters"]) in text

    def test_required_phrasing(self):
        text = build_tools_description_text([SEARCH_TOOL], "required")
        assert "exactly one of these tools" in text
        assert '"name"' in text and '"arguments"' in text

    def test_empty_tools_is_empty_string(self):
        assert build_tools_description_text([], FORCED) == ""
        assert build_tools_description_text(None, "required") == ""

    def test_malformed_entries_skipped(self):
        text = build_tools_description_text(
            [{"bogus": 1}, {"type": "function", "function": {"name": ""}}, SEARCH_TOOL],
            "required")
        assert "- web_search" in text
        assert "bogus" not in text


class TestParseConstrainedToolResponse:
    def test_valid_call_parses(self):
        text = json.dumps({"name": "generate_image",
                           "arguments": {"model": "AAM XL AnimeMix", "prompt": "wizard"}})
        parsed = parse_constrained_tool_response(text, [GENERATE_IMAGE_TOOL])
        assert parsed == {"name": "generate_image",
                          "arguments": {"model": "AAM XL AnimeMix", "prompt": "wizard"}}

    def test_prose_fails_open_backends_return_none(self):
        assert parse_constrained_tool_response("Hello! How can I help?", [GENERATE_IMAGE_TOOL]) is None

    def test_unknown_tool_name_rejected(self):
        text = json.dumps({"name": "rm_rf", "arguments": {}})
        assert parse_constrained_tool_response(text, [GENERATE_IMAGE_TOOL]) is None

    def test_forced_pin_name_admitted_even_if_undefined(self):
        text = json.dumps({"name": "generate_image", "arguments": {"prompt": "x"}})
        assert parse_constrained_tool_response(text, [SEARCH_TOOL], FORCED) is not None

    def test_non_dict_arguments_rejected(self):
        text = json.dumps({"name": "web_search", "arguments": "query=x"})
        assert parse_constrained_tool_response(text, [SEARCH_TOOL]) is None

    def test_non_object_json_rejected(self):
        assert parse_constrained_tool_response("[1, 2]", [SEARCH_TOOL]) is None
        assert parse_constrained_tool_response('"a string"', [SEARCH_TOOL]) is None

    def test_empty_and_non_string_rejected(self):
        assert parse_constrained_tool_response("", [SEARCH_TOOL]) is None
        assert parse_constrained_tool_response(None, [SEARCH_TOOL]) is None
        assert parse_constrained_tool_response({"already": "parsed"}, [SEARCH_TOOL]) is None

    def test_surrounding_whitespace_tolerated(self):
        text = "\n  " + json.dumps({"name": "web_search", "arguments": {"query": "x"}}) + "  \n"
        assert parse_constrained_tool_response(text, [SEARCH_TOOL]) is not None


class TestBuildToolCallsResult:
    def test_shape_matches_internal_tool_call_dict(self):
        result = build_tool_calls_result({"name": "web_search", "arguments": {"query": "x"}})
        assert result["content"] == ""
        assert result["finish_reason"] == "tool_calls"
        call = result["tool_calls"][0]
        assert call["id"].startswith("wilmer-")
        assert call["type"] == "function"
        assert call["function"]["name"] == "web_search"
        assert json.loads(call["function"]["arguments"]) == {"query": "x"}

    def test_ids_are_unique(self):
        a = build_tool_calls_result({"name": "t", "arguments": {}})
        b = build_tool_calls_result({"name": "t", "arguments": {}})
        assert a["tool_calls"][0]["id"] != b["tool_calls"][0]["id"]


class TestLoadStructuredOutputSchema:
    """Named-collection resolution for author-declared schemas."""

    def _patch_config(self, mocker, tmp_path, sub_directory="tester"):
        from Middleware.utilities import config_utils

        def fake_path(directory, sub, name):
            assert directory == "StructuredOutputs"
            base = tmp_path / directory / sub if sub else tmp_path / directory
            return str(base / f"{name}.json")

        mocker.patch.object(config_utils, 'get_config_value', return_value=None)
        mocker.patch.object(config_utils, 'get_current_username', return_value=sub_directory)
        mocker.patch.object(config_utils, 'get_config_with_subdirectory', side_effect=fake_path)
        mocker.patch.object(config_utils, 'load_config',
                            side_effect=lambda p: json.load(open(p)))
        return tmp_path / "StructuredOutputs"

    def test_loads_from_user_subdirectory(self, mocker, tmp_path):
        from Middleware.utilities.structured_output_utils import load_structured_output_schema
        base = self._patch_config(mocker, tmp_path)
        (base / "tester").mkdir(parents=True)
        (base / "tester" / "MyShape.json").write_text('{"type": "object"}')

        assert load_structured_output_schema("MyShape") == {"type": "object"}

    def test_falls_back_to_root(self, mocker, tmp_path):
        from Middleware.utilities.structured_output_utils import load_structured_output_schema
        base = self._patch_config(mocker, tmp_path)
        base.mkdir(parents=True)
        (base / "Shared.json").write_text('{"type": "object", "title": "shared"}')

        assert load_structured_output_schema("Shared")["title"] == "shared"

    def test_path_unsafe_name_rejected(self, mocker, tmp_path):
        from Middleware.utilities.structured_output_utils import load_structured_output_schema
        self._patch_config(mocker, tmp_path)
        import pytest
        with pytest.raises(ValueError, match="not a valid config name"):
            load_structured_output_schema("../evil")

    def test_non_object_schema_rejected(self, mocker, tmp_path):
        from Middleware.utilities.structured_output_utils import load_structured_output_schema
        base = self._patch_config(mocker, tmp_path)
        (base / "tester").mkdir(parents=True)
        (base / "tester" / "Bad.json").write_text('["not", "an", "object"]')
        import pytest
        with pytest.raises(ValueError, match="JSON object schema"):
            load_structured_output_schema("Bad")
