from typing import Any, Dict, Optional

import pytest

# The class we are testing
from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler


# A concrete implementation is needed for testing the abstract base class
class ConcreteChatHandler(BaseChatCompletionsHandler):
    """A concrete implementation of BaseChatCompletionsHandler for testing purposes."""

    def _get_api_endpoint_url(self) -> str:
        return "http://test.local/chat"

    def _process_stream_data(self, data_str: str) -> Optional[Dict[str, Any]]:
        pass

    def _parse_non_stream_response(self, response_json: Dict) -> str:
        pass


@pytest.fixture
def handler_factory(mocker):
    """
    Pytest fixture factory to create instances of ConcreteChatHandler
    with mocked dependencies and customizable configurations.
    """
    # Mock the text utility function since we only need to test that it's called,
    # not its internal logic.
    mocker.patch('Middleware.llmapis.handlers.base.base_chat_completions_handler.return_brackets',
                 side_effect=lambda x: x)

    def _create_handler(
            endpoint_config: Optional[Dict[str, Any]] = None,
            gen_input: Optional[Dict[str, Any]] = None,
            dont_include_model: bool = False
    ):
        return ConcreteChatHandler(
            base_url="http://test.local",
            api_key="test_key",
            gen_input=gen_input if gen_input is not None else {},
            model_name="test-model",
            headers={"Authorization": "Bearer test_key"},
            stream=False,
            api_type_config={},
            endpoint_config=endpoint_config if endpoint_config is not None else {},
            max_tokens=100,
            dont_include_model=dont_include_model
        )

    return _create_handler


# #############################################################################
# ## Tests for _build_messages_from_conversation
# #############################################################################

class TestBuildMessagesFromConversation:
    """
    Tests the core logic for constructing and modifying the 'messages' list.
    """

    def test_empty_conversation_with_prompts(self, handler_factory):
        """
        Tests that a message list is correctly created when the initial conversation is None.
        """
        handler = handler_factory()
        messages = handler._build_messages_from_conversation(
            conversation=None,
            system_prompt="You are a helpful assistant.",
            prompt="Hello, world!"
        )
        assert messages == [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, world!"}
        ]

    def test_role_correction(self, handler_factory):
        """
        Tests that the legacy role 'systemMes' is correctly updated to 'system'.
        """
        handler = handler_factory()
        conversation = [{"role": "systemMes", "content": "Initial system prompt."}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages[0]["role"] == "system"

    def test_image_messages_pass_through(self, handler_factory):
        """
        Tests that image messages pass through the base handler unchanged.

        Image filtering is now handled upstream in llm_api.py based on the llm_takes_images flag.
        The base handler no longer filters images; this allows handlers that support images
        (OpenAI, Ollama) to override _build_messages_from_conversation and process them.
        Handlers that don't support images receive pre-filtered conversations from llm_api.py.
        """
        handler = handler_factory()
        conversation = [
            {"role": "user", "content": "What is in this image?", "images": ["base64_string_here"]}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["images"] == ["base64_string_here"]

    def test_empty_last_assistant_message_removal(self, handler_factory):
        """
        Tests that an empty assistant message at the end of the conversation is removed.
        """
        handler = handler_factory()
        conversation = [
            {"role": "user", "content": "Prompt."},
            {"role": "assistant", "content": ""}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_trailing_empty_assistant_with_tool_calls_is_kept(self, handler_factory):
        """
        A trailing assistant message with empty content but tool_calls is structural
        data (the model's tool invocation), not the add_missing_assistant filler,
        and must not be dropped.
        """
        handler = handler_factory()
        conversation = [
            {"role": "user", "content": "Prompt."},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "calc", "arguments": "{}"}}]}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 2
        assert messages[-1]["tool_calls"][0]["id"] == "call_1"

    def test_add_text_to_existing_system_message(self, handler_factory):
        """
        Tests prepending text to an existing system message based on endpoint config.
        """
        config = {
            "addTextToStartOfSystem": True,
            "textToAddToStartOfSystem": "[PREFIX] "
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [{"role": "system", "content": "You are an assistant."}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages[0]["content"] == "[PREFIX] You are an assistant."

    def test_add_text_to_new_system_message(self, handler_factory):
        """
        Tests creating and prepending a new system message when one doesn't exist.
        """
        config = {
            "addTextToStartOfSystem": True,
            "textToAddToStartOfSystem": "[SYSTEM PREFIX]"
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [{"role": "user", "content": "Hello"}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "[SYSTEM PREFIX]"}

    def test_add_text_to_last_user_message(self, handler_factory):
        """
        Tests prepending text to the last user message in the conversation.
        """
        config = {
            "addTextToStartOfPrompt": True,
            "textToAddToStartOfPrompt": "[USER PREFIX] "
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [
            {"role": "user", "content": "First prompt."},
            {"role": "assistant", "content": "First response."},
            {"role": "user", "content": "Second prompt."}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages[2]["content"] == "[USER PREFIX] Second prompt."

    def test_add_completion_text_to_last_message_default(self, handler_factory):
        """
        Tests appending completion text to the content of the final message.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": " [SUFFIX]"
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [{"role": "user", "content": "Final prompt"}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages[0]["content"] == "Final prompt [SUFFIX]"

    def test_add_completion_text_as_new_assistant_message_with_ensure_flag(self, handler_factory):
        """
        Tests adding a new assistant message for the completion text when the 'ensure'
        flag is on and the last message is not from the assistant.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": "Assistant response starts here.",
            "ensureTextAddedToAssistantWhenChatCompletion": True
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [{"role": "user", "content": "A user prompt."}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 2
        assert messages[1] == {"role": "assistant", "content": "Assistant response starts here."}

    def test_return_brackets_is_called(self, handler_factory, mocker):
        """
        Verifies that the `return_brackets` utility function is called on the final message list.
        """
        mock_return_brackets = mocker.patch(
            'Middleware.llmapis.handlers.base.base_chat_completions_handler.return_brackets')
        handler = handler_factory()
        conversation = [{"role": "user", "content": "Test with |{{| and |}}|"}]

        handler._build_messages_from_conversation(conversation, None, None)

        mock_return_brackets.assert_called_once_with(conversation)

    def test_add_completion_text_appends_to_existing_assistant_with_ensure_flag(self, handler_factory):
        """
        Tests that when the 'ensure' flag is on and the last message is already from
        the assistant, the completion text is appended to that message rather than
        creating a new one.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": " [SUFFIX]",
            "ensureTextAddedToAssistantWhenChatCompletion": True
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [
            {"role": "user", "content": "A user prompt."},
            {"role": "assistant", "content": "Partial reply"}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages == [
            {"role": "user", "content": "A user prompt."},
            {"role": "assistant", "content": "Partial reply [SUFFIX]"}
        ]

    def test_add_completion_text_appends_to_last_assistant_without_ensure_flag(self, handler_factory):
        """
        Tests that with the 'ensure' flag off, the completion text is appended to the
        content of the final message when that message is from the assistant.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": " [SUFFIX]"
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [
            {"role": "user", "content": "A user prompt."},
            {"role": "assistant", "content": "Partial reply"}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages == [
            {"role": "user", "content": "A user prompt."},
            {"role": "assistant", "content": "Partial reply [SUFFIX]"}
        ]

    def test_add_text_to_prompt_creates_user_message_when_none_present(self, handler_factory):
        """
        Tests that 'addTextToStartOfPrompt' appends a new user message when the
        conversation contains no user messages.
        """
        config = {
            "addTextToStartOfPrompt": True,
            "textToAddToStartOfPrompt": "[USER PREFIX] "
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [{"role": "system", "content": "System only."}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages == [
            {"role": "system", "content": "System only."},
            {"role": "user", "content": "[USER PREFIX] "}
        ]

    def test_add_completion_text_to_empty_conversation(self, handler_factory):
        """
        Tests that completion text on an empty conversation produces a single
        assistant message containing that text.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": "Assistant begins:"
        }
        handler = handler_factory(endpoint_config=config)
        messages = handler._build_messages_from_conversation([], None, None)
        assert messages == [{"role": "assistant", "content": "Assistant begins:"}]

    def test_completion_text_appended_to_tool_call_assistant_missing_content_key(self, handler_factory):
        """
        A trailing assistant message carrying only tool_calls (no 'content' key, as
        produced by some tool round-trips) must not KeyError when completion text is
        appended with the ensure flag off; the text becomes its content and the
        tool_calls survive.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": "[SUFFIX]"
        }
        handler = handler_factory(endpoint_config=config)
        tool_calls = [{"id": "call_1", "type": "function",
                       "function": {"name": "calc", "arguments": "{}"}}]
        conversation = [
            {"role": "user", "content": "Prompt."},
            {"role": "assistant", "tool_calls": tool_calls}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 2
        assert messages[-1]["content"] == "[SUFFIX]"
        assert messages[-1]["tool_calls"] == tool_calls

    def test_completion_text_with_ensure_flag_onto_tool_call_assistant_missing_content_key(self, handler_factory):
        """
        Same tool_calls-only trailing assistant, but with the ensure flag on: the
        text is appended to that assistant turn (no new message is created) and no
        KeyError occurs despite the missing 'content' key.
        """
        config = {
            "addTextToStartOfCompletion": True,
            "textToAddToStartOfCompletion": "[SUFFIX]",
            "ensureTextAddedToAssistantWhenChatCompletion": True
        }
        handler = handler_factory(endpoint_config=config)
        conversation = [
            {"role": "user", "content": "Prompt."},
            {"role": "assistant",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "calc", "arguments": "{}"}}]}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 2
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "[SUFFIX]"

    def test_trailing_assistant_with_none_content_is_dropped(self, handler_factory):
        """
        A trailing assistant marker whose content is None (not just "") is filler,
        not data: it must be dropped so no null-content assistant turn reaches the API.
        """
        handler = handler_factory()
        conversation = [
            {"role": "user", "content": "Prompt."},
            {"role": "assistant", "content": None}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_trailing_assistant_missing_content_key_is_dropped(self, handler_factory):
        """
        A trailing assistant message with no 'content' key at all (and no tool_calls)
        is dropped without raising KeyError.
        """
        handler = handler_factory()
        conversation = [
            {"role": "user", "content": "Prompt."},
            {"role": "assistant"}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_return_brackets_restores_curly_braces_end_to_end(self, mocker):
        """
        End-to-end test with the real return_brackets implementation (no identity mock):
        the WILMER curly sentinels in message content are restored to literal braces.
        """
        mocker.patch('Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout',
                     return_value=30)
        handler = ConcreteChatHandler(
            base_url="http://test.local",
            api_key="test_key",
            gen_input={},
            model_name="test-model",
            headers={"Authorization": "Bearer test_key"},
            stream=False,
            api_type_config={},
            endpoint_config={},
            max_tokens=100,
            dont_include_model=False
        )
        conversation = [{"role": "user", "content": "__WILMER_L_CURLY__x__WILMER_R_CURLY__"}]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        assert messages[0]["content"] == "{x}"


# #############################################################################
# ## Tests for _prepare_payload
# #############################################################################

class TestPreparePayload:
    """
    Tests the top-level payload construction method.
    """

    def test_payload_structure_and_method_calls(self, handler_factory, mocker):
        """
        Ensures the payload is built correctly and helper methods are called.
        """
        handler = handler_factory()
        # Mock the internal methods to isolate the logic of _prepare_payload
        mock_set_gen_input = mocker.patch.object(handler, 'set_gen_input')
        mock_build_messages = mocker.patch.object(handler, '_build_messages_from_conversation',
                                                  return_value=[{"role": "user", "content": "hello"}])

        payload = handler._prepare_payload(
            conversation=[{"role": "user", "content": "hello"}],
            system_prompt=None,
            prompt=None
        )

        mock_set_gen_input.assert_called_once()
        mock_build_messages.assert_called_once()
        assert "model" in payload
        assert "messages" in payload
        assert payload["messages"] == [{"role": "user", "content": "hello"}]
        assert payload["model"] == "test-model"

    def test_payload_without_model(self, handler_factory):
        """
        Tests that the 'model' key is omitted when 'dont_include_model' is True.
        """
        handler = handler_factory(dont_include_model=True)
        payload = handler._prepare_payload(None, None, "test")
        assert "model" not in payload

    def test_payload_with_gen_input(self, handler_factory):
        """
        Tests that generation parameters from 'gen_input' are correctly merged
        into the top level of the payload.
        """
        gen_params = {"temperature": 0.8, "top_p": 0.9}
        handler = handler_factory(gen_input=gen_params)
        payload = handler._prepare_payload(None, None, "test")

        assert "temperature" in payload
        assert payload["temperature"] == 0.8
        assert "top_p" in payload
        assert payload["top_p"] == 0.9

    def test_payload_tools_and_tool_choice_passthrough(self, handler_factory):
        """
        Tests that tools and tool_choice are passed through into the payload unchanged.
        """
        handler = handler_factory()
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
            }
        }]
        tool_choice = {"type": "function", "function": {"name": "get_weather"}}

        payload = handler._prepare_payload(None, None, "test", tools=tools, tool_choice=tool_choice)

        assert payload["tools"] == tools
        assert payload["tool_choice"] == tool_choice

    def test_payload_omits_tools_and_tool_choice_when_none(self, handler_factory):
        """
        Tests that neither 'tools' nor 'tool_choice' keys appear in the payload
        when both are None.
        """
        handler = handler_factory()
        payload = handler._prepare_payload(None, None, "test", tools=None, tool_choice=None)

        assert "tools" not in payload
        assert "tool_choice" not in payload
