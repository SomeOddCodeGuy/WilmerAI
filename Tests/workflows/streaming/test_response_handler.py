# Tests/workflows/streaming/test_response_handler.py
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

    mocker.patch('Middleware.workflows.streaming.response_handler.get_current_username', return_value="test_user")
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

    mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.API_TYPE',
                 "openaichatcompletion")

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
        assert handler3._reconstruction_applied is True
        assert result3 == "Character Name: Character Name: Multi-word"

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
        mocker.patch('Middleware.workflows.streaming.response_handler.instance_global_variables.API_TYPE', api_type)
        mocker.patch('Middleware.workflows.streaming.response_handler.api_helpers')
        mocker.patch('Middleware.workflows.streaming.response_handler.StreamingThinkRemover')
        mocker.patch('Middleware.workflows.streaming.response_handler.get_current_username')
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
