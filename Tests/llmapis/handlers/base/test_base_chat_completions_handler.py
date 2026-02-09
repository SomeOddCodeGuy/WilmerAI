from typing import Any, Dict, Optional

import pytest

# The class we are testing
from Middleware.llmapis.handlers.base.base_chat_completions_handler import BaseChatCompletionsHandler


# A concrete implementation is needed for testing the abstract base class
class ConcreteChatHandler(BaseChatCompletionsHandler):
    """A concrete implementation of BaseChatCompletionsHandler for testing purposes."""

    def _get_api_endpoint_url(self) -> str:
        return "http://test.com/chat"

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
            base_url="http://test.com",
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
        The base handler no longer filters images - this allows handlers that support images
        (OpenAI, Ollama) to override _build_messages_from_conversation and process them.
        Handlers that don't support images receive pre-filtered conversations from llm_api.py.
        """
        handler = handler_factory()
        conversation = [
            {"role": "user", "content": "What is in this image?"},
            {"role": "images", "content": "base64_string_here"}
        ]
        messages = handler._build_messages_from_conversation(conversation, None, None)
        # Images pass through the base handler - filtering happens upstream
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "images"

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
