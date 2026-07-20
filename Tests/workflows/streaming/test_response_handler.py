from typing import Dict, Any, Generator, List

import pytest

from Middleware.workflows.streaming.response_handler import StreamingResponseHandler


# Helper to create a sample raw dictionary generator for tests
def raw_dict_generator_factory(chunks: List[Dict[str, Any]]) -> Generator[Dict[str, Any], None, None]:
    """Yields dictionary chunks for testing process_stream."""
    yield from chunks


@pytest.fixture
def mock_dependencies(mocker):
    """Mocks all external dependencies for StreamingResponseHandler."""

    def mock_build_response_json(token, finish_reason, **kwargs):
        """A simple function to act as the side_effect for the mock."""
        import json
        return json.dumps({"token": token, "finish_reason": str(finish_reason) if finish_reason else "None"})

    mock_api_helpers = mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
    mock_api_helpers.build_response_json.side_effect = mock_build_response_json
    mock_api_helpers.sse_format.side_effect = lambda data, output_format: f"data: {data}\n\n" if output_format not in (
        'ollamagenerate', 'ollamaapichat') else f"{data}\n"

    mock_add_assistant = mocker.patch(
        'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant', return_value=False)
    mock_add_missing_assistant = mocker.patch(
        'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
        return_value=False)

    mock_remover_instance = mocker.MagicMock()
    mock_remover_instance.process_delta.side_effect = lambda delta: delta
    mock_remover_instance.finalize.return_value = ""
    mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover',
                 return_value=mock_remover_instance)

    mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                 return_value="openaichatcompletion")

    return {
        "api_helpers": mock_api_helpers,
        "remover": mock_remover_instance,
        "add_assistant": mock_add_assistant,
        "add_missing_assistant": mock_add_missing_assistant
    }


class TestStreamingResponseHandler:
    """Unit tests for the StreamingResponseHandler class."""

    # region __init__ and _is_prefix_stripping_needed tests
    @pytest.mark.parametrize("endpoint_config, workflow_config, add_assistant, expected", [
        ({}, {}, False, False),
        ({"trimBeginningAndEndLineBreaks": True}, {}, False, True),
        ({}, {"removeCustomTextFromResponseStart": True}, False, True),
        ({"removeCustomTextFromResponseStartEndpointWide": True}, {}, False, True),
        ({}, {"addDiscussionIdTimestampsForLLM": True}, False, True),
        ({}, {}, True, True),
    ])
    def test_is_prefix_stripping_needed(self, mocker, endpoint_config, workflow_config, add_assistant, expected):
        mocker.patch('Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
                     return_value=add_assistant)
        mocker.patch('Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
                     return_value=add_assistant)
        handler = StreamingResponseHandler(endpoint_config, workflow_config)
        assert handler._is_prefix_stripping_needed() == expected

    def test_init_should_buffer_for_generation_prompt(self, mock_dependencies):
        """Tests that buffering is enabled when a generation_prompt is provided."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        assert handler._should_buffer_for_prefixes is True

    @pytest.mark.parametrize("workflow_enabled, endpoint_enabled, expected_limit", [
        (False, False, 100), (True, False, 100), (False, True, 100), (True, True, 200),
    ])
    def test_init_prefix_buffer_limit(self, mock_dependencies, workflow_enabled, endpoint_enabled, expected_limit):
        workflow_config = {"removeCustomTextFromResponseStart": workflow_enabled}
        endpoint_config = {"removeCustomTextFromResponseStartEndpointWide": endpoint_enabled}
        handler = StreamingResponseHandler(endpoint_config, workflow_config)
        assert handler._prefix_buffer_limit == expected_limit

    # endregion

    # region _process_prefixes_from_buffer tests
    def test_process_prefixes_no_match(self, mock_dependencies):
        handler = StreamingResponseHandler({}, {})
        handler._prefix_buffer = "  Hello world"
        result = handler._process_prefixes_from_buffer()
        assert result == "Hello world"

    def test_process_prefixes_workflow_custom_prefix(self, mock_dependencies):
        workflow_config = {
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["FIRST:", "SECOND:"]
        }
        handler = StreamingResponseHandler({}, workflow_config)
        handler._prefix_buffer = "FIRST: The quick brown fox."
        result = handler._process_prefixes_from_buffer()
        assert result == "The quick brown fox."

    def test_process_prefixes_order_of_operations(self, mock_dependencies):
        mock_dependencies["add_assistant"].return_value = True
        mock_dependencies["add_missing_assistant"].return_value = True
        workflow_config = {
            "removeCustomTextFromResponseStart": True, "responseStartTextToRemove": ["WORKFLOW:"],
            "addDiscussionIdTimestampsForLLM": True
        }
        endpoint_config = {
            "removeCustomTextFromResponseStartEndpointWide": True,
            "responseStartTextToRemoveEndpointWide": ["ENDPOINT:"]
        }
        handler = StreamingResponseHandler(endpoint_config, workflow_config)
        handler._prefix_buffer = "WORKFLOW:ENDPOINT:[Sent less than a minute ago]Assistant: Text"
        assert handler._process_prefixes_from_buffer() == "Text"

    def test_process_prefixes_reconstructs_with_generation_prompt(self, mock_dependencies):
        """Tests that the generation prompt is prepended when the LLM response doesn't have a prefix."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        handler._prefix_buffer = "Hello there."
        result = handler._process_prefixes_from_buffer()
        assert result == "Roland: Hello there."
        assert handler._reconstruction_applied is True

    def test_process_prefixes_skips_reconstruction_if_llm_provides_prefix(self, mock_dependencies):
        """Tests that the generation prompt is NOT prepended if the LLM already provided a 'Name:' prefix."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        handler._prefix_buffer = "Roland: I am already here."
        result = handler._process_prefixes_from_buffer()
        assert result == "Roland: I am already here."
        assert handler._reconstruction_applied is False

    def test_process_prefixes_reconstructs_with_empty_buffer_then_strips(self, mock_dependencies):
        """Tests that an empty buffer gets the prompt, which is then stripped by other rules."""
        workflow_config = {"removeCustomTextFromResponseStart": True, "responseStartTextToRemove": ["Roland: "]}
        handler = StreamingResponseHandler({}, workflow_config, generation_prompt="Roland:")
        handler._prefix_buffer = " "
        result = handler._process_prefixes_from_buffer()
        assert result == ""
        assert handler._reconstruction_applied is True

    def test_process_prefixes_removes_timestamp_prefix(self, mock_dependencies):
        """Tests that timestamp prefixes are properly removed from responses."""
        workflow_config = {"addDiscussionIdTimestampsForLLM": True}
        handler = StreamingResponseHandler({}, workflow_config)
        handler._prefix_buffer = "[Sent less than a minute ago] Hello world"
        result = handler._process_prefixes_from_buffer()
        assert result == "Hello world"

    def test_process_prefixes_removes_timestamp_without_space(self, mock_dependencies):
        """Tests timestamp removal when there's no space after the timestamp."""
        workflow_config = {"addDiscussionIdTimestampsForLLM": True}
        handler = StreamingResponseHandler({}, workflow_config)
        handler._prefix_buffer = "[Sent less than a minute ago]Hello world"
        result = handler._process_prefixes_from_buffer()
        assert result == "Hello world"

    def test_process_prefixes_reconstruction_before_stripping(self, mock_dependencies):
        """Tests that reconstruction happens before stripping operations."""
        workflow_config = {
            "addDiscussionIdTimestampsForLLM": True,
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["Roland:"]
        }
        handler = StreamingResponseHandler({}, workflow_config, generation_prompt="Roland:")
        handler._prefix_buffer = "[Sent less than a minute ago] Hello there."
        result = handler._process_prefixes_from_buffer()
        # Should: 1) Prepend "Roland: " 2) Strip timestamp 3) Strip "Roland:"
        assert result == "Hello there."
        assert handler._reconstruction_applied is True

    def test_process_prefixes_detects_various_colon_prefixes(self, mock_dependencies):
        """Tests that various character name formats with colons are detected."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Alice:")
        handler._prefix_buffer = "Alice: Already here"
        handler._reconstruction_applied = False
        result = handler._process_prefixes_from_buffer()
        assert handler._reconstruction_applied is False
        assert result == "Alice: Already here"

        handler2 = StreamingResponseHandler({}, {}, generation_prompt="Alice:")
        handler2._prefix_buffer = "Hello there"
        handler2._reconstruction_applied = False
        result2 = handler2._process_prefixes_from_buffer()
        assert handler2._reconstruction_applied is True
        assert result2 == "Alice: Hello there"

        single_word_prefix_cases = [
            ("Bob123:", "Bob123: Present"),
            ("User_Name:", "User_Name: Speaking"),
            ("A:", "A: Short name"),
        ]

        for prompt, buffer_content in single_word_prefix_cases:
            handler = StreamingResponseHandler({}, {}, generation_prompt=prompt)
            handler._prefix_buffer = buffer_content
            handler._reconstruction_applied = False
            result = handler._process_prefixes_from_buffer()
            assert handler._reconstruction_applied is False
            assert result == buffer_content

        handler3 = StreamingResponseHandler({}, {}, generation_prompt="Character Name:")
        handler3._prefix_buffer = "Character Name: Multi-word"
        handler3._reconstruction_applied = False
        result3 = handler3._process_prefixes_from_buffer()
        assert handler3._reconstruction_applied is False
        assert result3 == "Character Name: Multi-word"

    def test_process_prefixes_only_reconstructs_once(self, mock_dependencies):
        """Tests that reconstruction only happens once even if called multiple times."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        handler._prefix_buffer = "Hello"

        result1 = handler._process_prefixes_from_buffer()
        assert result1 == "Roland: Hello"
        assert handler._reconstruction_applied is True

        handler._prefix_buffer = "World"
        result2 = handler._process_prefixes_from_buffer()
        assert result2 == "World"

    # endregion

    # region process_stream tests
    def test_process_stream_no_prefixing(self, mock_dependencies):
        handler = StreamingResponseHandler({}, {})
        raw_stream = raw_dict_generator_factory([
            {"token": "Hello"}, {"token": " world"}, {"token": "!", "finish_reason": "stop"}
        ])
        result = list(handler.process_stream(raw_stream))
        assert len(result) == 5
        assert '{"token": "Hello", "finish_reason": "None"}' in result[0]
        assert '{"token": " world", "finish_reason": "None"}' in result[1]
        assert '{"token": "!", "finish_reason": "None"}' in result[2]
        assert '{"token": "", "finish_reason": "stop"}' in result[3]
        assert result[4] == "data: [DONE]\n\n"
        assert handler.full_response_text == "Hello world!"

    def test_process_stream_with_prefixing_and_buffering(self, mock_dependencies):
        workflow_config = {"removeCustomTextFromResponseStart": True, "responseStartTextToRemove": ["Prefix: "]}
        handler = StreamingResponseHandler({}, workflow_config)
        handler._prefix_buffer_limit = 10
        raw_stream = raw_dict_generator_factory([
            {"token": "Prefix: "}, {"token": "Hel"}, {"token": "lo"}, {"token": " world"},
        ])
        result = list(handler.process_stream(raw_stream))
        assert len(result) == 5
        assert '{"token": "Hel", "finish_reason": "None"}' in result[0]
        assert '{"token": "lo", "finish_reason": "None"}' in result[1]
        assert '{"token": " world", "finish_reason": "None"}' in result[2]
        assert '{"token": "", "finish_reason": "stop"}' in result[3]
        assert handler.full_response_text == "Hello world"
        assert handler._prefixes_processed

    def test_process_stream_with_prefixing_short_stream(self, mock_dependencies):
        workflow_config = {"removeCustomTextFromResponseStart": True, "responseStartTextToRemove": ["Prefix: "]}
        handler = StreamingResponseHandler({}, workflow_config)
        raw_stream = raw_dict_generator_factory([
            {"token": "Prefix: Short", "finish_reason": "stop"}
        ])
        result = list(handler.process_stream(raw_stream))
        assert len(result) == 3
        assert '{"token": "Short", "finish_reason": "None"}' in result[0]
        assert '{"token": "", "finish_reason": "stop"}' in result[1]
        assert handler.full_response_text == "Short"
        assert handler._prefixes_processed

    @pytest.mark.parametrize("api_type, expect_done", [
        ("openaichatcompletion", True), ("openaicompletion", True),
        ("ollamagenerate", False), ("ollamaapichat", False),
    ])
    def test_process_stream_final_done_message(self, mocker, api_type, expect_done):
        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value=api_type)
        mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
        mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover')
        # __init__ resolves these from the real user config on disk if unpatched.
        mocker.patch('Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
                     return_value=False)
        mocker.patch('Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
                     return_value=False)
        # The stream is empty, so the liveness guard's empty-response branch runs;
        # left unpatched it would read the real user config from disk (hermeticity).
        mocker.patch('Middleware.workflows.streaming.response_handler.get_liveness_tool_call',
                     return_value=None)
        from Middleware.api import api_helpers
        mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers.sse_format',
                     side_effect=api_helpers.sse_format)
        handler = StreamingResponseHandler({}, {})
        raw_stream = raw_dict_generator_factory([])
        result = list(handler.process_stream(raw_stream))
        final_message = result[-1] if result else ""
        if expect_done:
            assert final_message == "data: [DONE]\n\n"
        else:
            assert not final_message.startswith("data: [DONE]")

    def test_process_stream_with_generation_prompt_reconstruction(self, mock_dependencies):
        """Tests that generation prompt reconstruction works correctly in streaming mode."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Assistant:")
        handler._prefix_buffer_limit = 20

        raw_stream = raw_dict_generator_factory([
            {"token": "Hello"}, {"token": " there"}, {"token": ", how"},
            {"token": " can"}, {"token": " I help?", "finish_reason": "stop"}
        ])

        result = list(handler.process_stream(raw_stream))
        assert handler.full_response_text == "Assistant: Hello there, how can I help?"
        assert handler._reconstruction_applied is True

    def test_process_stream_with_generation_prompt_no_reconstruction(self, mock_dependencies):
        """Tests that reconstruction is skipped when LLM already provides the prefix."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Assistant:")
        handler._prefix_buffer_limit = 20

        raw_stream = raw_dict_generator_factory([
            {"token": "Assistant:"}, {"token": " Hello"}, {"token": " there", "finish_reason": "stop"}
        ])

        result = list(handler.process_stream(raw_stream))
        assert handler.full_response_text == "Assistant: Hello there"
        assert handler._reconstruction_applied is False

    def test_process_stream_timestamp_removal_with_streaming(self, mock_dependencies):
        """Tests timestamp removal in streaming context."""
        workflow_config = {"addDiscussionIdTimestampsForLLM": True}
        handler = StreamingResponseHandler({}, workflow_config)
        handler._prefix_buffer_limit = 50

        raw_stream = raw_dict_generator_factory([
            {"token": "[Sent less"}, {"token": " than a minute"}, {"token": " ago] Hello"},
            {"token": " world", "finish_reason": "stop"}
        ])

        result = list(handler.process_stream(raw_stream))
        assert handler.full_response_text == "Hello world"
        assert handler._prefixes_processed is True

    def test_process_stream_complex_prefix_scenario(self, mock_dependencies):
        """Tests a complex scenario with generation prompt, timestamp, and custom prefix."""
        workflow_config = {
            "addDiscussionIdTimestampsForLLM": True,
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["Assistant:"]
        }
        handler = StreamingResponseHandler({}, workflow_config, generation_prompt="Assistant:")
        handler._prefix_buffer_limit = 100

        raw_stream = raw_dict_generator_factory([
            {"token": "[Sent less than"}, {"token": " a minute ago]"},
            {"token": " Hello there", "finish_reason": "stop"}
        ])

        result = list(handler.process_stream(raw_stream))
        assert handler.full_response_text == "Hello there"
        assert handler._reconstruction_applied is True
        assert handler._prefixes_processed is True
    # endregion


@pytest.fixture
def mock_deps_with_tool_calls(mocker):
    """Mocks all external dependencies, with build_response_json supporting tool_calls kwarg.

    Module-level so every tool-call-related test class can use it."""

    def mock_build_response_json(token, finish_reason, **kwargs):
        import json
        result = {"token": token, "finish_reason": str(finish_reason) if finish_reason else "None"}
        if kwargs.get('tool_calls') is not None:
            result["tool_calls"] = kwargs['tool_calls']
        return json.dumps(result)

    mock_api_helpers = mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
    mock_api_helpers.build_response_json.side_effect = mock_build_response_json
    mock_api_helpers.sse_format.side_effect = lambda data, output_format: f"data: {data}\n\n" if output_format not in (
        'ollamagenerate', 'ollamaapichat') else f"{data}\n"

    mock_add_assistant = mocker.patch(
        'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
        return_value=False)
    mock_add_missing_assistant = mocker.patch(
        'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
        return_value=False)

    mock_remover_instance = mocker.MagicMock()
    mock_remover_instance.process_delta.side_effect = lambda delta: delta
    mock_remover_instance.finalize.return_value = ""
    mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover',
                 return_value=mock_remover_instance)

    mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                 return_value="openaichatcompletion")

    return {
        "api_helpers": mock_api_helpers,
        "remover": mock_remover_instance,
        "add_assistant": mock_add_assistant,
        "add_missing_assistant": mock_add_missing_assistant,
    }


class TestToolCallStreamBypass:
    """Tests that tool call chunks in the streaming response handler bypass all text
    processing (prefix stripping, think-block removal, group chat reconstruction) and
    are emitted directly as SSE output."""

    def test_tool_call_chunk_bypasses_prefix_stripping(self, mock_deps_with_tool_calls):
        """Tool call chunks should be emitted directly without going through prefix buffering."""
        workflow_config = {
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["Prefix: "]
        }
        handler = StreamingResponseHandler({}, workflow_config)

        tool_calls_data = [{"index": 0, "id": "call_abc", "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"loc'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tool_calls_data},
        ])

        result = list(handler.process_stream(raw_stream))

        # The tool call chunk should have been emitted (plus the finish event and [DONE])
        assert any('"tool_calls"' in r for r in result), "Tool call data should appear in SSE output"

        # Verify build_response_json was called with the tool_calls kwarg
        mock_build = mock_deps_with_tool_calls["api_helpers"].build_response_json
        tool_call_calls = [c for c in mock_build.call_args_list
                           if c.kwargs.get('tool_calls') is not None or
                           (len(c) > 1 and 'tool_calls' in (c[1] or {}) and c[1]['tool_calls'] is not None)]
        assert len(tool_call_calls) >= 1, "build_response_json should be called with tool_calls kwarg"

        # The prefix buffer should not have been used for tool call content
        assert handler._prefix_buffer == ""

    def test_tool_call_chunk_bypasses_think_block_removal(self, mock_deps_with_tool_calls):
        """The think-block remover's process_delta should NOT be called for tool_call chunks,
        but should be called for normal text chunks."""
        handler = StreamingResponseHandler({}, {})
        remover = mock_deps_with_tool_calls["remover"]

        tool_calls_data = [{"index": 0, "id": "call_xyz", "type": "function",
                            "function": {"name": "search", "arguments": '{"q":'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "Hello"},
            {"token": "", "tool_calls": tool_calls_data},
            {"token": " world", "finish_reason": "stop"},
        ])

        list(handler.process_stream(raw_stream))

        # process_delta should have been called for the text chunks only
        process_delta_calls = remover.process_delta.call_args_list
        deltas_processed = [c[0][0] for c in process_delta_calls]
        assert "Hello" in deltas_processed
        assert " world" in deltas_processed
        # The tool call chunk's empty token should NOT have gone through process_delta
        # (there are only 2 text chunks, so exactly 2 calls)
        assert len(deltas_processed) == 2

    def test_interleaved_text_and_tool_calls(self, mock_deps_with_tool_calls):
        """Text chunks go through normal processing; tool_call chunks bypass. The
        full_response_text should only contain text content."""
        handler = StreamingResponseHandler({}, {})

        tool_calls_data = [{"index": 0, "id": "call_123", "type": "function",
                            "function": {"name": "calc", "arguments": '{"x": 1}'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "Let me "},
            {"token": "check."},
            {"token": "", "tool_calls": tool_calls_data},
        ])

        result = list(handler.process_stream(raw_stream))

        # full_response_text should only accumulate text content, not tool call data
        assert handler.full_response_text == "Let me check."

        # Both text chunks and tool call chunk should appear in SSE output
        text_events = [r for r in result if '"token": "Let me "' in r or '"token": "check."' in r]
        tool_events = [r for r in result if '"tool_calls"' in r]
        assert len(text_events) == 2
        assert len(tool_events) >= 1

        # Verify build_response_json calls: text calls should NOT have tool_calls kwarg
        mock_build = mock_deps_with_tool_calls["api_helpers"].build_response_json
        for call in mock_build.call_args_list:
            token_val = call.kwargs.get('token', call[0][0] if call[0] else None)
            tc_val = call.kwargs.get('tool_calls')
            if token_val in ("Let me ", "check."):
                assert tc_val is None, f"Text chunk '{token_val}' should not have tool_calls kwarg"

    def test_tool_call_finish_reason_prevents_duplicate_finish(self, mock_deps_with_tool_calls):
        """When a tool_call chunk has finish_reason, the handler should NOT emit a second
        finish event. There should be exactly one chunk with a finish_reason in the output,
        and the [DONE] sentinel should still be present."""
        handler = StreamingResponseHandler({}, {})

        tool_calls_chunk_1 = [{"index": 0, "id": "call_abc", "type": "function",
                               "function": {"name": "get_weather", "arguments": '{"loc'}}]
        tool_calls_chunk_2 = [{"index": 0, "function": {"arguments": 'ation": "NYC"}'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tool_calls_chunk_1},
            {"token": "", "tool_calls": tool_calls_chunk_2, "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        # Count events with a finish_reason that is not "None"
        import json
        finish_events = []
        for r in result:
            if r.startswith("data: [DONE]"):
                continue
            # Extract the JSON payload from the SSE line
            payload_str = r.replace("data: ", "").strip()
            if not payload_str:
                continue
            try:
                payload = json.loads(payload_str)
                if payload.get("finish_reason") not in (None, "None"):
                    finish_events.append(payload)
            except json.JSONDecodeError:
                continue

        assert len(finish_events) == 1, (
            f"Expected exactly one finish event, got {len(finish_events)}: {finish_events}"
        )
        assert finish_events[0]["finish_reason"] == "tool_calls"

        # [DONE] sentinel should still be present
        assert any("[DONE]" in r for r in result), "[DONE] sentinel should still be emitted"

    def test_tool_call_only_stream(self, mock_deps_with_tool_calls):
        """A stream with ONLY tool_call chunks (no text) should produce SSE output for
        each tool_call chunk plus [DONE]."""
        handler = StreamingResponseHandler({}, {})

        tc_1 = [{"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "fn", "arguments": '{"a'}}]
        tc_2 = [{"index": 0, "function": {"arguments": '": 1}'}}]
        tc_3 = [{"index": 0, "function": {"arguments": ""}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc_1},
            {"token": "", "tool_calls": tc_2},
            {"token": "", "tool_calls": tc_3, "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        # Should have 3 tool call SSE events + [DONE] = 4 total
        assert len(result) == 4, f"Expected 4 SSE events (3 tool_call + [DONE]), got {len(result)}: {result}"

        # Each of the first 3 should contain tool_calls data
        for i in range(3):
            assert '"tool_calls"' in result[i], f"Event {i} should contain tool_calls data"

        # [DONE] sentinel is the last event
        assert "[DONE]" in result[-1]

        # full_response_text should be empty since there was no text content
        assert handler.full_response_text == ""

    def test_finish_reason_preserved_when_on_separate_chunk(self, mock_deps_with_tool_calls):
        """When the finish_reason 'tool_calls' arrives on a separate chunk WITHOUT
        tool_calls in the delta (standard OpenAI streaming format), the final SSE
        event must emit finish_reason='tool_calls', NOT 'stop'.

        This is the standard OpenAI format for multi-tool-call streaming:
        1. Tool call chunks with tool_calls in delta, finish_reason=null
        2. Final chunk with empty delta and finish_reason='tool_calls'
        """
        import json
        handler = StreamingResponseHandler({}, {})

        tc_initial = [{"index": 0, "id": "call_abc", "type": "function",
                       "function": {"name": "bash", "arguments": ""}}]
        tc_args = [{"index": 0, "function": {"arguments": '{"cmd": "ls"}'}}]
        tc_second = [{"index": 1, "id": "call_def", "type": "function",
                      "function": {"name": "bash", "arguments": ""}}]
        tc_second_args = [{"index": 1, "function": {"arguments": '{"cmd": "pwd"}'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "Let me check.", "finish_reason": None},
            {"token": "", "tool_calls": tc_initial, "finish_reason": None},
            {"token": "", "tool_calls": tc_args, "finish_reason": None},
            {"token": "", "tool_calls": tc_second, "finish_reason": None},
            {"token": "", "tool_calls": tc_second_args, "finish_reason": None},
            # Final chunk: finish_reason but NO tool_calls in delta
            {"token": "", "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        # Find the finish event (the last non-[DONE] event with a real finish_reason)
        finish_events = []
        for r in result:
            if "[DONE]" in r:
                continue
            payload_str = r.replace("data: ", "").strip()
            if not payload_str:
                continue
            try:
                payload = json.loads(payload_str)
                fr = payload.get("finish_reason")
                if fr not in (None, "None"):
                    finish_events.append(payload)
            except json.JSONDecodeError:
                continue

        assert len(finish_events) == 1, (
            f"Expected exactly 1 finish event, got {len(finish_events)}: {finish_events}"
        )
        assert finish_events[0]["finish_reason"] == "tool_calls", (
            f"finish_reason should be 'tool_calls', got '{finish_events[0]['finish_reason']}'"
        )

        # All 4 tool call chunks should appear in the output (check for tool_calls arrays, not the string "tool_calls")
        tool_events = [r for r in result if '"tool_calls": [' in r]
        assert len(tool_events) == 4, f"Expected 4 tool call events, got {len(tool_events)}"

        # Text content should be captured
        assert handler.full_response_text == "Let me check."

    def test_finish_reason_stop_preserved_for_text_only(self, mock_deps_with_tool_calls):
        """For normal text-only streams, the finish_reason should still be 'stop'."""
        import json
        handler = StreamingResponseHandler({}, {})

        raw_stream = raw_dict_generator_factory([
            {"token": "Hello", "finish_reason": None},
            {"token": " world", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        finish_events = []
        for r in result:
            if "[DONE]" in r:
                continue
            payload_str = r.replace("data: ", "").strip()
            if not payload_str:
                continue
            try:
                payload = json.loads(payload_str)
                fr = payload.get("finish_reason")
                if fr not in (None, "None"):
                    finish_events.append(payload)
            except json.JSONDecodeError:
                continue

        assert len(finish_events) == 1
        assert finish_events[0]["finish_reason"] == "stop"

    @pytest.mark.parametrize("api_type, expect_done", [
        ("openaichatcompletion", True),
        ("openaicompletion", True),
        ("ollamagenerate", False),
        ("ollamaapichat", False),
    ])
    def test_done_sentinel_after_tool_call_stream(self, mocker, api_type, expect_done):
        """For OpenAI-format output, [DONE] should still be emitted after a tool call
        stream. For Ollama format, it should NOT be emitted."""
        import json

        def mock_build_response_json(token, finish_reason, **kwargs):
            result = {"token": token, "finish_reason": str(finish_reason) if finish_reason else "None"}
            if kwargs.get('tool_calls') is not None:
                result["tool_calls"] = kwargs['tool_calls']
            return json.dumps(result)

        mock_api_helpers = mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
        mock_api_helpers.build_response_json.side_effect = mock_build_response_json
        mock_api_helpers.sse_format.side_effect = lambda data, output_format: f"data: {data}\n\n" if output_format not in (
            'ollamagenerate', 'ollamaapichat') else f"{data}\n"

        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
            return_value=False)
        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
            return_value=False)

        mock_remover_instance = mocker.MagicMock()
        mock_remover_instance.process_delta.side_effect = lambda delta: delta
        mock_remover_instance.finalize.return_value = ""
        mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover',
                     return_value=mock_remover_instance)

        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value=api_type)

        handler = StreamingResponseHandler({}, {})

        tc = [{"index": 0, "id": "call_1", "type": "function",
               "function": {"name": "fn", "arguments": "{}"}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc, "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        has_done = any("[DONE]" in r for r in result)
        if expect_done:
            assert has_done, f"[DONE] sentinel should be emitted for {api_type}"
        else:
            assert not has_done, f"[DONE] sentinel should NOT be emitted for {api_type}"


class TestLowercaseToolCallFunctionNames:
    """Tests for the lowercaseToolCallFunctionNames node config option, which
    lowercases tool call function names in streaming responses."""

    @pytest.fixture
    def mock_deps(self, mocker):
        def mock_build_response_json(token, finish_reason, **kwargs):
            import json
            result = {"token": token, "finish_reason": str(finish_reason) if finish_reason else "None"}
            if kwargs.get('tool_calls') is not None:
                result["tool_calls"] = kwargs['tool_calls']
            return json.dumps(result)

        mock_api_helpers = mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
        mock_api_helpers.build_response_json.side_effect = mock_build_response_json
        mock_api_helpers.sse_format.side_effect = lambda data, output_format: f"data: {data}\n\n"

        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
            return_value=False)
        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
            return_value=False)

        mock_remover_instance = mocker.MagicMock()
        mock_remover_instance.process_delta.side_effect = lambda delta: delta
        mock_remover_instance.finalize.return_value = ""
        mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover',
                     return_value=mock_remover_instance)

        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value="openaichatcompletion")

        return {"api_helpers": mock_api_helpers}

    def test_lowercases_tool_call_name_when_enabled(self, mock_deps):
        """When lowercaseToolCallFunctionNames is true, function names should be lowercased."""
        import json
        handler = StreamingResponseHandler({}, {"lowercaseToolCallFunctionNames": True})

        tc = [{"index": 0, "id": "call_1", "type": "function",
               "function": {"name": "Glob", "arguments": '{"pat'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc},
            {"token": "", "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        tool_events = [r for r in result if '"tool_calls"' in r]
        assert len(tool_events) >= 1
        parsed = json.loads(tool_events[0].replace("data: ", "").strip())
        assert parsed["tool_calls"][0]["function"]["name"] == "glob"

    def test_does_not_lowercase_when_disabled(self, mock_deps):
        """When lowercaseToolCallFunctionNames is false (default), names are untouched."""
        import json
        handler = StreamingResponseHandler({}, {})

        tc = [{"index": 0, "id": "call_1", "type": "function",
               "function": {"name": "Glob", "arguments": '{"pat'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc},
            {"token": "", "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        tool_events = [r for r in result if '"tool_calls"' in r]
        parsed = json.loads(tool_events[0].replace("data: ", "").strip())
        assert parsed["tool_calls"][0]["function"]["name"] == "Glob"

    def test_lowercases_multiple_tool_calls(self, mock_deps):
        """Multiple tool calls in a single chunk all get lowercased."""
        import json
        handler = StreamingResponseHandler({}, {"lowercaseToolCallFunctionNames": True})

        tc = [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "Grep", "arguments": "{}"}},
            {"index": 1, "id": "call_2", "type": "function",
             "function": {"name": "Read", "arguments": "{}"}},
        ]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc, "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        tool_events = [r for r in result if '"tool_calls"' in r]
        parsed = json.loads(tool_events[0].replace("data: ", "").strip())
        assert parsed["tool_calls"][0]["function"]["name"] == "grep"
        assert parsed["tool_calls"][1]["function"]["name"] == "read"

    def test_skips_chunks_without_name_field(self, mock_deps):
        """Subsequent streaming chunks that only have arguments (no name) are handled gracefully."""
        import json
        handler = StreamingResponseHandler({}, {"lowercaseToolCallFunctionNames": True})

        tc_initial = [{"index": 0, "id": "call_1", "type": "function",
                       "function": {"name": "Glob", "arguments": '{"pat'}}]
        tc_args = [{"index": 0, "function": {"arguments": 'tern": "*.py"}'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc_initial},
            {"token": "", "tool_calls": tc_args},
            {"token": "", "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        tool_events = [r for r in result if '"tool_calls"' in r]
        first_parsed = json.loads(tool_events[0].replace("data: ", "").strip())
        assert first_parsed["tool_calls"][0]["function"]["name"] == "glob"

        second_parsed = json.loads(tool_events[1].replace("data: ", "").strip())
        assert "name" not in second_parsed["tool_calls"][0]["function"]
        assert second_parsed["tool_calls"][0]["function"]["arguments"] == 'tern": "*.py"}'

    def test_already_lowercase_names_unchanged(self, mock_deps):
        """Names that are already lowercase pass through without issue."""
        import json
        handler = StreamingResponseHandler({}, {"lowercaseToolCallFunctionNames": True})

        tc = [{"index": 0, "id": "call_1", "type": "function",
               "function": {"name": "get_weather", "arguments": "{}"}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc, "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        tool_events = [r for r in result if '"tool_calls"' in r]
        parsed = json.loads(tool_events[0].replace("data: ", "").strip())
        assert parsed["tool_calls"][0]["function"]["name"] == "get_weather"


class TestLivenessToolCallInjection:
    """Unit tests for the mid-task liveness guard: injecting a configured no-op
    tool call when a mid-task response would otherwise end without one."""

    LIVENESS_CONFIG = {
        "toolName": "bash",
        "arguments": {"command": "echo '[Wilmer] Task in progress; continuing autonomously.'"}
    }

    @pytest.fixture
    def mock_deps(self, mocker):
        def mock_build_response_json(token, finish_reason, **kwargs):
            import json
            result = {"token": token, "finish_reason": str(finish_reason) if finish_reason else "None"}
            if kwargs.get('tool_calls') is not None:
                result["tool_calls"] = kwargs['tool_calls']
            return json.dumps(result)

        mock_api_helpers = mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
        mock_api_helpers.build_response_json.side_effect = mock_build_response_json
        mock_api_helpers.sse_format.side_effect = lambda data, output_format: f"data: {data}\n\n" if output_format not in (
            'ollamagenerate', 'ollamaapichat') else f"{data}\n"

        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
            return_value=False)
        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
            return_value=False)

        mock_remover_instance = mocker.MagicMock()
        mock_remover_instance.process_delta.side_effect = lambda delta: delta
        mock_remover_instance.finalize.return_value = ""
        mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover',
                     return_value=mock_remover_instance)

        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value="openaichatcompletion")

        return {"api_helpers": mock_api_helpers}

    def _patch_guard(self, mocker, config=LIVENESS_CONFIG):
        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_liveness_tool_call',
            return_value=config)

    def _parse_events(self, results):
        import json
        parsed = []
        for r in results:
            payload = r.replace("data: ", "").strip()
            if payload and payload != "[DONE]":
                parsed.append(json.loads(payload))
        return parsed

    def test_injects_tool_call_when_node_opted_in_and_none_in_stream(self, mocker, mock_deps):
        """A text-only stream from an opted-in responder node gets the configured
        no-op tool call appended and closes with finish_reason tool_calls."""
        import json
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {"injectLivenessToolCall": True})

        raw_stream = raw_dict_generator_factory([
            {"token": "All findings recorded.", "finish_reason": None},
            {"token": "", "finish_reason": "stop"},
        ])
        results = list(handler.process_stream(raw_stream))
        events = self._parse_events(results)

        tool_events = [e for e in events if "tool_calls" in e]
        assert len(tool_events) == 1
        injected = tool_events[0]["tool_calls"][0]
        assert injected["index"] == 0
        assert injected["id"].startswith("wilmer_liveness_")
        assert injected["type"] == "function"
        assert injected["function"]["name"] == "bash"
        assert json.loads(injected["function"]["arguments"]) == self.LIVENESS_CONFIG["arguments"]

        assert events[-1]["finish_reason"] == "tool_calls"

    def test_injects_on_empty_response_even_without_node_opt_in(self, mocker, mock_deps):
        """A completely empty response (no text, no tool call) is a malfunction,
        not a completion: the keep-alive fires even for a node that did not opt in,
        so the frontend loop survives instead of silently stranding mid-task."""
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {})

        raw_stream = raw_dict_generator_factory([
            {"token": "", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        tool_events = [e for e in events if "tool_calls" in e]
        assert len(tool_events) == 1
        assert tool_events[0]["tool_calls"][0]["id"].startswith("wilmer_liveness_")
        assert events[-1]["finish_reason"] == "tool_calls"

    def test_no_injection_on_whitespace_only_when_opted_out_is_still_empty(self, mocker, mock_deps):
        """Whitespace-only output counts as empty: the keep-alive still fires for a
        non-opted-in node."""
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {})

        raw_stream = raw_dict_generator_factory([
            {"token": "  \n ", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        assert [e for e in events if "tool_calls" in e]

    def test_no_injection_when_node_did_not_opt_in(self, mocker, mock_deps):
        """Without injectLivenessToolCall on the node (default), a stream with real
        text ends normally; a finished task's answer must stop the frontend loop."""
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {})

        raw_stream = raw_dict_generator_factory([
            {"token": "Task complete.", "finish_reason": None},
            {"token": "", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        assert not [e for e in events if "tool_calls" in e]
        assert events[-1]["finish_reason"] == "stop"

    def test_no_injection_without_config(self, mocker, mock_deps):
        """Node opted in but no livenessToolCall configured: no injection."""
        self._patch_guard(mocker, config=None)
        handler = StreamingResponseHandler({}, {"injectLivenessToolCall": True})

        raw_stream = raw_dict_generator_factory([
            {"token": "Some text.", "finish_reason": None},
            {"token": "", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        assert not [e for e in events if "tool_calls" in e]
        assert events[-1]["finish_reason"] == "stop"

    def test_no_injection_when_stream_already_has_tool_calls(self, mocker, mock_deps):
        """A stream that produced its own tool call is already alive: no injection."""
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {"injectLivenessToolCall": True})

        tc = [{"index": 0, "id": "call_1", "type": "function",
               "function": {"name": "read", "arguments": "{}"}}]
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc, "finish_reason": "tool_calls"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        tool_events = [e for e in events if "tool_calls" in e]
        assert len(tool_events) == 1
        assert tool_events[0]["tool_calls"][0]["id"] == "call_1"

    def test_no_injection_when_tool_calls_seen_before_text_finish(self, mocker, mock_deps):
        """Tool calls earlier in the stream count even if the stream finishes as text."""
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {"injectLivenessToolCall": True})

        tc = [{"index": 0, "id": "call_1", "type": "function",
               "function": {"name": "read", "arguments": "{}"}}]
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tc, "finish_reason": None},
            {"token": "done", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        injected = [e for e in events if "tool_calls" in e
                    and e["tool_calls"][0]["id"].startswith("wilmer_liveness_")]
        assert not injected
        assert events[-1]["finish_reason"] == "stop"

    def test_no_injection_for_formats_without_tool_calls(self, mocker, mock_deps):
        """Output formats that cannot carry tool calls never get an injection."""
        self._patch_guard(mocker)
        handler = StreamingResponseHandler({}, {"injectLivenessToolCall": True})
        handler.output_format = "openaicompletion"

        raw_stream = raw_dict_generator_factory([
            {"token": "text", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        assert not [e for e in events if "tool_calls" in e]

    def test_malformed_arguments_fall_back_to_empty_object(self, mocker, mock_deps):
        """A non-dict arguments value serializes as an empty JSON object."""
        self._patch_guard(mocker,
                          config={"toolName": "bash", "arguments": "not-a-dict"})
        handler = StreamingResponseHandler({}, {"injectLivenessToolCall": True})

        raw_stream = raw_dict_generator_factory([
            {"token": "text", "finish_reason": "stop"},
        ])
        events = self._parse_events(list(handler.process_stream(raw_stream)))

        tool_events = [e for e in events if "tool_calls" in e]
        assert len(tool_events) == 1
        assert tool_events[0]["tool_calls"][0]["function"]["arguments"] == "{}"


class TestToolCallBufferFlushing:
    """Text held by the start-of-stream prefix buffer must be emitted BEFORE a
    tool-call chunk (generation order) and must never be dropped when the
    stream finishes on the tool-call chunk itself."""

    def test_buffered_text_emitted_before_tool_call(self, mock_deps_with_tool_calls):
        workflow_config = {
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["Hello there"]
        }
        handler = StreamingResponseHandler({}, workflow_config)

        tool_calls_data = [{"index": 0, "id": "call_1", "type": "function",
                            "function": {"name": "calc", "arguments": '{"x": 1}'}}]

        # "Hel" partially matches the configured prefix, so it is still buffered
        # when the tool-call delta arrives.
        raw_stream = raw_dict_generator_factory([
            {"token": "Hel"},
            {"token": "", "tool_calls": tool_calls_data},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        text_index = next(i for i, r in enumerate(result) if '"token": "Hel"' in r)
        tool_index = next(i for i, r in enumerate(result) if '"tool_calls"' in r)
        assert text_index < tool_index, "Buffered text must precede the tool call it was generated before"
        assert handler.full_response_text == "Hel"

    def test_buffered_text_not_dropped_when_finish_on_tool_chunk(self, mock_deps_with_tool_calls):
        workflow_config = {
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["Hello there"]
        }
        handler = StreamingResponseHandler({}, workflow_config)

        tool_calls_data = [{"index": 0, "id": "call_1", "type": "function",
                            "function": {"name": "calc", "arguments": '{"x": 1}'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "Hel"},
            {"token": "", "tool_calls": tool_calls_data, "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert any('"token": "Hel"' in r for r in result), \
            "Text buffered when the stream ends on a tool-call chunk must still be emitted"
        assert handler.full_response_text == "Hel"

    def test_empty_buffer_keeps_prefix_stripping_armed_after_tool_call(self, mock_deps_with_tool_calls):
        """A tool call arriving before any text must not disarm prefix stripping
        for the text that follows it."""
        workflow_config = {
            "removeCustomTextFromResponseStart": True,
            "responseStartTextToRemove": ["Prefix: "]
        }
        handler = StreamingResponseHandler({}, workflow_config)

        tool_calls_data = [{"index": 0, "id": "call_1", "type": "function",
                            "function": {"name": "calc", "arguments": '{"x": 1}'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": tool_calls_data},
            {"token": "Prefix: real answer", "finish_reason": "stop"},
        ])

        list(handler.process_stream(raw_stream))
        assert handler.full_response_text == "real answer"


class TestOllamaNativeToolCallStreaming:
    """For the ollamaapichat output format, OpenAI-style tool-call deltas must be
    accumulated and emitted once, complete, in Ollama's native shape (arguments
    as a JSON object), since Ollama's protocol has no delta form for tool calls."""

    @pytest.fixture
    def ollama_handler(self, mock_deps_with_tool_calls, mocker):
        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value="ollamaapichat")
        return StreamingResponseHandler({}, {})

    def test_fragmented_deltas_emitted_as_one_complete_native_call(self, ollama_handler):
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                          "function": {"name": "get_weather", "arguments": '{"city": '}}]},
            {"token": "", "tool_calls": [{"index": 0, "function": {"arguments": '"New York"}'}}]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        import json
        tool_events = [r for r in result if '"tool_calls"' in r]
        assert len(tool_events) == 1, "Fragments must be merged into exactly one tool-call event"
        payload = json.loads(tool_events[0])
        assert payload["tool_calls"] == [
            {"function": {"name": "get_weather", "arguments": {"city": "New York"}}}
        ]

    def test_finish_on_tool_chunk_emits_complete_native_call(self, ollama_handler):
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                          "function": {"name": "calc", "arguments": '{"x":'}}]},
            {"token": "", "finish_reason": "tool_calls",
             "tool_calls": [{"index": 0, "function": {"arguments": ' 1}'}}]},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        import json
        tool_events = [r for r in result if '"tool_calls"' in r]
        assert len(tool_events) == 1
        payload = json.loads(tool_events[0])
        assert payload["tool_calls"] == [{"function": {"name": "calc", "arguments": {"x": 1}}}]

    def test_multiple_tool_calls_kept_in_index_order(self, ollama_handler):
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [
                {"index": 1, "id": "call_b", "function": {"name": "second", "arguments": '{"b": 2}'}},
                {"index": 0, "id": "call_a", "function": {"name": "first", "arguments": '{"a": 1}'}},
            ]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        import json
        tool_events = [r for r in result if '"tool_calls"' in r]
        payload = json.loads(tool_events[0])
        assert payload["tool_calls"] == [
            {"function": {"name": "first", "arguments": {"a": 1}}},
            {"function": {"name": "second", "arguments": {"b": 2}}},
        ]

    def test_openai_format_still_passes_deltas_through(self, mock_deps_with_tool_calls):
        """Non-Ollama output formats keep the existing passthrough-delta behavior."""
        handler = StreamingResponseHandler({}, {})
        fragment = [{"index": 0, "id": "call_1", "type": "function",
                     "function": {"name": "calc", "arguments": '{"x":'}}]

        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": fragment},
            {"token": "", "tool_calls": [{"index": 0, "function": {"arguments": ' 1}'}}],
             "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))
        tool_events = [r for r in result if '"tool_calls"' in r]
        assert len(tool_events) == 2, "OpenAI clients receive each delta as it arrives"


class TestPrefixBufferReleaseDecisions:
    """Pins the three distinct buffer-release policies in process_stream:
    optimistic release on a definitive prefix mismatch, holding a whitespace-only
    buffer, the trim-whitespace-only path, and the degenerate strip-flag-with-
    empty-list path (buffer until full/done, content never lost)."""

    def test_nonmatching_first_chunk_released_immediately(self, mock_dependencies):
        """Optimistic matching: once the buffer definitively fails to match any
        configured prefix, it is released at that chunk (not held until the
        stream ends) and stripping is disarmed for the rest of the stream."""
        workflow_config = {"removeCustomTextFromResponseStart": True,
                           "responseStartTextToRemove": ["Prefix: "]}
        handler = StreamingResponseHandler({}, workflow_config)

        raw_stream = raw_dict_generator_factory([
            {"token": "Zebra"}, {"token": " one"}, {"token": " two"},
        ])

        result = list(handler.process_stream(raw_stream))

        # Chunk-per-event: if the buffer had been wrongly held to stream end,
        # the first event would carry the whole concatenated text instead.
        assert '"token": "Zebra"' in result[0]
        assert '"token": " one"' in result[1]
        assert '"token": " two"' in result[2]
        assert handler.full_response_text == "Zebra one two"
        assert handler._prefixes_processed is True

    def test_whitespace_only_first_chunk_keeps_buffering(self, mock_dependencies):
        """A whitespace-only buffer is not a mismatch: the prefix may still be
        coming. The whitespace chunk must produce no event, and the prefix that
        arrives afterwards must still be stripped."""
        workflow_config = {"removeCustomTextFromResponseStart": True,
                           "responseStartTextToRemove": ["Prefix: "]}
        handler = StreamingResponseHandler({}, workflow_config)

        raw_stream = raw_dict_generator_factory([
            {"token": "   "},
            {"token": "Prefix: hi", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert '"token": "hi"' in result[0]
        assert handler.full_response_text == "hi"

    def test_trim_whitespace_only_buffering_strips_leading_whitespace(self, mock_dependencies):
        """With only trimBeginningAndEndLineBreaks active (no prefixes, no
        generation prompt), the handler holds whitespace-only chunks, emits the
        first real content with its leading whitespace removed, then passes
        subsequent chunks straight through."""
        endpoint_config = {"trimBeginningAndEndLineBreaks": True}
        handler = StreamingResponseHandler(endpoint_config, {})

        raw_stream = raw_dict_generator_factory([
            {"token": " \n"},
            {"token": " Hello"},
            {"token": " world", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert '"token": "Hello"' in result[0]
        assert '"token": " world"' in result[1]
        assert handler.full_response_text == "Hello world"

    def test_strip_flag_with_empty_list_buffers_until_done_without_losing_text(self, mock_dependencies):
        """Degenerate config: removeCustomTextFromResponseStart is true but the
        prefix list is empty. Buffering is armed with nothing to match, so the
        buffer is held until full/done, and the content must come out intact."""
        workflow_config = {"removeCustomTextFromResponseStart": True,
                           "responseStartTextToRemove": []}
        handler = StreamingResponseHandler({}, workflow_config)

        raw_stream = raw_dict_generator_factory([
            {"token": "Hello"},
            {"token": " world", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert '"token": "Hello world"' in result[0]
        assert handler.full_response_text == "Hello world"


class TestBareStringPrefixConfigs:
    """The custom-text settings accept a bare string as well as an array; a bare
    string must be treated as one prefix, not iterated character by character."""

    def test_collect_prefixes_accepts_bare_string_configs(self, mock_dependencies):
        endpoint_config = {"removeCustomTextFromResponseStartEndpointWide": True,
                           "responseStartTextToRemoveEndpointWide": "  EP:  "}
        workflow_config = {"removeCustomTextFromResponseStart": True,
                          "responseStartTextToRemove": "WF: "}
        handler = StreamingResponseHandler(endpoint_config, workflow_config)

        # Workflow entry kept verbatim; endpoint entry whitespace-stripped.
        assert set(handler._prefixes_to_strip) == {"WF: ", "EP:"}

        raw_stream = raw_dict_generator_factory([
            {"token": "WF: EP: hi", "finish_reason": "stop"},
        ])
        result = list(handler.process_stream(raw_stream))

        assert '"token": "hi"' in result[0]
        assert handler.full_response_text == "hi"


class TestOllamaToolCallRobustness:
    """Edge cases of the Ollama-native tool-call accumulation: text tokens riding
    on tool-call chunks, malformed delta entries, dict-form arguments, and
    unparseable accumulated arguments."""

    @pytest.fixture
    def ollama_handler(self, mock_deps_with_tool_calls, mocker):
        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value="ollamaapichat")
        return StreamingResponseHandler({}, {})

    def _tool_events(self, result):
        import json
        return [json.loads(r) for r in result if '"tool_calls"' in r]

    def test_text_token_on_tool_chunk_is_emitted_and_captured(self, ollama_handler):
        """A tool-call chunk that also carries a text token: the text is emitted
        as its own event ahead of the accumulated call, and it must land in
        full_response_text (the workflow layer's captured result)."""
        raw_stream = raw_dict_generator_factory([
            {"token": "Checking the weather. ",
             "tool_calls": [{"index": 0, "id": "c1", "type": "function",
                             "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'}}]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        assert any('"token": "Checking the weather. "' in r for r in result), \
            "Text arriving on a tool-call chunk must still reach the client"
        tool_events = self._tool_events(result)
        assert len(tool_events) == 1
        assert tool_events[0]["tool_calls"] == [
            {"function": {"name": "get_weather", "arguments": {"city": "NYC"}}}
        ]
        assert ollama_handler.full_response_text == "Checking the weather. ", \
            "Text delivered to the client must not be missing from the captured result"

    def test_non_dict_tool_call_entries_are_skipped(self, ollama_handler):
        """A malformed (non-dict) entry in a tool_calls delta list is skipped
        instead of crashing the stream; valid entries still accumulate."""
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [
                "garbage-entry",
                {"index": 0, "id": "c1", "function": {"name": "fn", "arguments": '{"a": 1}'}},
            ]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        tool_events = self._tool_events(result)
        assert len(tool_events) == 1
        assert tool_events[0]["tool_calls"] == [{"function": {"name": "fn", "arguments": {"a": 1}}}]

    def test_dict_arguments_replace_accumulated_string(self, ollama_handler):
        """An already-complete call (arguments as a dict, e.g. converted from an
        Ollama or Claude backend) replaces any accumulated fragment wholesale."""
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [{"index": 0, "id": "c1",
                                          "function": {"name": "fn", "arguments": '{"partial": '}}]},
            {"token": "", "tool_calls": [{"index": 0,
                                          "function": {"arguments": {"a": 1}}}]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        tool_events = self._tool_events(result)
        assert len(tool_events) == 1
        assert tool_events[0]["tool_calls"] == [{"function": {"name": "fn", "arguments": {"a": 1}}}]

    def test_invalid_json_arguments_fall_back_to_empty_object(self, ollama_handler):
        """Accumulated arguments that never became valid JSON (stream died
        mid-arguments) are sent as an empty object, name preserved."""
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [{"index": 0, "id": "c1",
                                          "function": {"name": "fn", "arguments": '{"x": '}}]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        tool_events = self._tool_events(result)
        assert tool_events[0]["tool_calls"] == [{"function": {"name": "fn", "arguments": {}}}]

    def test_non_object_json_arguments_fall_back_to_empty_object(self, ollama_handler):
        """Arguments that parse to valid JSON but not an object (e.g. a bare
        string) are sent as an empty object."""
        raw_stream = raw_dict_generator_factory([
            {"token": "", "tool_calls": [{"index": 0, "id": "c1",
                                          "function": {"name": "fn", "arguments": '"just a string"'}}]},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(ollama_handler.process_stream(raw_stream))

        tool_events = self._tool_events(result)
        assert tool_events[0]["tool_calls"] == [{"function": {"name": "fn", "arguments": {}}}]


class TestOpenAiTextOnToolChunkCapture:
    """OpenAI passthrough branch: a chunk carrying both a text token and
    tool-call deltas delivers both in one event, and the text must land in
    full_response_text (the workflow layer's captured result)."""

    def test_text_on_tool_chunk_accumulates_into_full_response_text(self, mock_deps_with_tool_calls):
        import json
        handler = StreamingResponseHandler({}, {})

        tc = [{"index": 0, "id": "c1", "type": "function",
               "function": {"name": "fn", "arguments": "{}"}}]
        raw_stream = raw_dict_generator_factory([
            {"token": "Also text", "tool_calls": tc, "finish_reason": None},
            {"token": "", "finish_reason": "tool_calls"},
        ])

        result = list(handler.process_stream(raw_stream))

        # Select events that carry a tool_calls KEY (a bare finish event whose
        # finish_reason VALUE is "tool_calls" must not match).
        parsed = [json.loads(r.replace("data: ", "").strip()) for r in result
                  if "[DONE]" not in r]
        combined = [p for p in parsed if "tool_calls" in p]
        assert len(combined) == 1
        assert combined[0]["token"] == "Also text"
        assert combined[0]["tool_calls"] == tc
        assert handler.full_response_text == "Also text", \
            "Text delivered to the client must not be missing from the captured result"


class TestStreamTeardown:
    """Closing the SSE generator mid-stream (client disconnect) must propagate
    cleanly: no exception, no further consumption of the raw stream, and the
    upstream generator's finally block (handler teardown) must run."""

    def test_close_mid_stream_propagates_cleanly_and_finalizes_upstream(self, mock_dependencies):
        state = {"yielded": 0, "closed": False}

        def raw_generator():
            try:
                for i in range(100):
                    state["yielded"] += 1
                    yield {"token": f"t{i} ", "finish_reason": None}
            finally:
                state["closed"] = True

        handler = StreamingResponseHandler({}, {})
        sse_gen = handler.process_stream(raw_generator())

        next(sse_gen)
        next(sse_gen)
        sse_gen.close()

        assert state["closed"] is True, "Upstream generator must be finalized on close"
        assert state["yielded"] == 2, "No further chunks may be consumed after close"


class TestRealThinkRemoverIntegration:
    """Runs the handler with the REAL StreamingThinkRemover (not the passthrough
    mock) to pin the stage-1 (think removal) to stage-2 (prefix buffer) wiring.
    The remover itself is exhaustively tested in test_streaming_utils.py; these
    tests prove the handler feeds and drains it correctly."""

    THINK_ENDPOINT_CONFIG = {
        "removeThinking": True,
        "startThinkTag": "<think>",
        "endThinkTag": "</think>",
        "openingTagGracePeriod": 50,
    }

    @pytest.fixture
    def real_remover_deps(self, mocker):
        def mock_build_response_json(token, finish_reason, **kwargs):
            import json
            return json.dumps({"token": token,
                               "finish_reason": str(finish_reason) if finish_reason else "None"})

        mock_api_helpers = mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
        mock_api_helpers.build_response_json.side_effect = mock_build_response_json
        mock_api_helpers.sse_format.side_effect = lambda data, output_format: f"data: {data}\n\n"

        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_user_assistant',
            return_value=False)
        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_is_chat_complete_add_missing_assistant',
            return_value=False)
        mocker.patch(
            'Middleware.workflows.streaming.response_handler.get_liveness_tool_call',
            return_value=None)
        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.get_api_type',
                     return_value="openaichatcompletion")
        # StreamingThinkRemover deliberately NOT patched.

    def test_think_block_split_across_chunks_then_prefix_stripped(self, real_remover_deps):
        """A think block whose tags are split across chunk boundaries is removed,
        and the workflow prefix on the text AFTER the block is then stripped by
        the prefix buffer: both stages working on one stream."""
        workflow_config = {"removeCustomTextFromResponseStart": True,
                           "responseStartTextToRemove": ["Prefix: "]}
        handler = StreamingResponseHandler(self.THINK_ENDPOINT_CONFIG, workflow_config)

        raw_stream = raw_dict_generator_factory([
            {"token": "<thi"},
            {"token": "nk>secret plan</thi"},
            {"token": "nk>Prefix: Hel"},
            {"token": "lo"},
            {"token": "", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert handler.full_response_text == "Hello"
        joined = "".join(result)
        assert "secret" not in joined, "Think-block content must never reach the client"
        assert "Prefix:" not in joined.replace('"responseStartTextToRemove"', ""), \
            "The configured prefix must be stripped from the post-think text"
        assert '"token": "Hello"' in result[0]

    def test_unterminated_think_block_flushed_at_finalization(self, real_remover_deps):
        """If the stream ends inside an unterminated think block, finalization
        reconstructs and emits the original text (opening tag included) instead
        of silently dropping it."""
        handler = StreamingResponseHandler(self.THINK_ENDPOINT_CONFIG, {})

        raw_stream = raw_dict_generator_factory([
            {"token": "<think>never closed"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert handler.full_response_text == "<think>never closed"
        assert any('"token": "<think>never closed"' in r for r in result)


class TestReconstructionBufferingDelay:
    """Pins _reconstruction_pending_more_data: the group-chat reconstruction
    decision must not be made on a first tiny delta that could still grow into
    the model's own speaker prefix (else the prefix is doubled)."""

    def test_partial_prefix_across_tiny_deltas_not_doubled(self, mock_dependencies):
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        handler._prefix_buffer_limit = 40

        raw_stream = raw_dict_generator_factory([
            {"token": "Rol"}, {"token": "and:"}, {"token": " hi", "finish_reason": "stop"}
        ])

        list(handler.process_stream(raw_stream))

        # Deciding on the 3-char "Rol" would prepend the prompt and produce
        # "Roland: Roland: hi" once the model's own prefix completes.
        assert handler.full_response_text == "Roland: hi"
        assert handler._reconstruction_applied is False

    def test_short_colon_free_stream_prepends_exactly_once_on_done(self, mock_dependencies):
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        handler._prefix_buffer_limit = 40

        raw_stream = raw_dict_generator_factory([
            {"token": "hi"}, {"token": "!", "finish_reason": "stop"}
        ])

        list(handler.process_stream(raw_stream))

        assert handler.full_response_text == "Roland: hi!"
        assert handler._reconstruction_applied is True

    def test_pending_helper_edges(self, mock_dependencies):
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        threshold = len("Roland:") + 10

        # Colon inside the prompt-length window: the decision can be made now.
        assert handler._reconstruction_pending_more_data("Roland:") is False
        assert handler._reconstruction_pending_more_data(":") is False
        # Colon-free and shorter than the window: keep buffering.
        assert handler._reconstruction_pending_more_data("Rol") is True
        assert handler._reconstruction_pending_more_data("") is True
        assert handler._reconstruction_pending_more_data("x" * (threshold - 1)) is True
        # Grown past the window with no colon: no speaker prefix is coming.
        assert handler._reconstruction_pending_more_data("x" * threshold) is False
        # Once reconstruction has been applied the delay is inert.
        handler._reconstruction_applied = True
        assert handler._reconstruction_pending_more_data("Rol") is False

    def test_tool_call_chunk_does_not_force_premature_reconstruction(self, mock_dependencies):
        """A mid-stream tool-call chunk must not drain a buffer that is still
        too short for the reconstruction decision (the drain would decide on the
        tiny buffer and double the prefix)."""
        handler = StreamingResponseHandler({}, {}, generation_prompt="Roland:")
        handler._prefix_buffer_limit = 40
        tool_call = {"id": "c1", "function": {"name": "noop", "arguments": "{}"}}

        raw_stream = raw_dict_generator_factory([
            {"token": "Rol"},
            {"token": "", "tool_calls": [tool_call]},
            {"token": "and: hi", "finish_reason": "stop"},
        ])

        list(handler.process_stream(raw_stream))

        assert handler.full_response_text == "Roland: hi"
        assert handler._reconstruction_applied is False


class TestEmptyToolCallsListOnTextDelta:
    """Pins the truthiness check at the handler layer: a text delta carrying
    "tool_calls": [] must take the normal text path, not the tool-call bypass."""

    def test_text_with_empty_tool_calls_list_takes_text_path(self, mock_dependencies):
        handler = StreamingResponseHandler({}, {})

        raw_stream = raw_dict_generator_factory([
            {"token": "hi", "tool_calls": []},
            {"token": " there", "finish_reason": "stop"},
        ])

        result = list(handler.process_stream(raw_stream))

        assert handler.full_response_text == "hi there"
        # The final finish must be the stream's own stop, not a tool_calls
        # finish inherited from the bypass path.
        assert '"finish_reason": "stop"' in "".join(result)
