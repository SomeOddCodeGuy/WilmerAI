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
    def test_init_prefix_buffer_limit(self, workflow_enabled, endpoint_enabled, expected_limit):
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


class TestToolCallStreamBypass:
    """Tests that tool call chunks in the streaming response handler bypass all text
    processing (prefix stripping, think-block removal, group chat reconstruction) and
    are emitted directly as SSE output."""

    @pytest.fixture
    def mock_deps_with_tool_calls(self, mocker):
        """Mocks all external dependencies, with build_response_json supporting tool_calls kwarg."""

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
