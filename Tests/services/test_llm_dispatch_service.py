from copy import deepcopy

import pytest

from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.workflows.models.execution_context import ExecutionContext

# --- Test Data ---

SAMPLE_MESSAGES = [
    {"role": "system", "content": "Initial system message."},
    {"role": "user", "content": "Hello, bot."},
    {"role": "assistant", "content": "Hello, human."},
    {"role": "user", "content": "How are you?"},
    {"role": "assistant", "content": "I am a large language model."},
    {"role": "user", "content": "Tell me a joke."},
]



# --- Fixtures ---

@pytest.fixture
def mock_context(mocker):
    """
    Creates a mock ExecutionContext object with mocked dependencies.
    This provides a clean, controlled environment for each test.
    """
    # Mock the final LLM call target
    mock_llm = mocker.Mock()
    mock_llm.get_response_from_llm.return_value = "mocked_llm_response"

    # Mock the LLM handler
    mock_llm_handler = mocker.Mock()
    mock_llm_handler.llm = mock_llm
    mock_llm_handler.prompt_template_file_name = "test_template.json"
    mock_llm_handler.add_generation_prompt = False
    mock_llm_handler.takes_message_collection = False  # Default to completions API

    # Mock the variable service to return the prompt as-is
    mock_variable_service = mocker.Mock()
    mock_variable_service.apply_variables.side_effect = lambda prompt, context: prompt

    # Create the mock ExecutionContext instance
    context = mocker.Mock(spec=ExecutionContext)
    context.llm_handler = mock_llm_handler
    context.config = {}  # Start with an empty node config
    context.workflow_variable_service = mock_variable_service
    context.messages = deepcopy(SAMPLE_MESSAGES)

    return context


# --- Test Suite for Completions API Logic ---

class TestLLMDispatchServiceCompletions:
    """
    Tests the logic path where llm_handler.takes_message_collection is False.
    """

    def test_dispatch_uses_prompt_from_config(self, mock_context, mocker):
        """
        Verifies that when a 'prompt' is specified in the node config,
        it is used instead of the conversation history.
        """
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "prompt": "User instruction."
        }
        # Mock the template functions that will be called
        mock_format_system = mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                                          return_value="formatted_system")
        mock_get_last_turns = mocker.patch(
            'Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string')

        LLMDispatchService.dispatch(context=mock_context)

        # Verify the correct system prompt was formatted
        mock_format_system.assert_called_once_with("System instruction.", "test_template.json", False)

        # Verify that conversation history was NOT used
        mock_get_last_turns.assert_not_called()

        # Verify the final LLM call has the correct arguments
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User instruction.",
            llm_takes_images=False,
            request_id=None  # Added for cancellation support
        )

    def test_dispatch_uses_last_n_messages_when_prompt_is_absent(self, mock_context, mocker):
        """
        Verifies that when 'prompt' is absent, the service falls back to
        formatting the last N turns of the conversation history.
        """
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "lastMessagesToSendInsteadOfPrompt": 3
        }
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")
        mock_get_last_turns = mocker.patch(
            'Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string',
            return_value="formatted_last_3_turns"
        )

        LLMDispatchService.dispatch(context=mock_context)

        # It should ask for n + 1 messages to get n turns
        mock_get_last_turns.assert_called_once_with(
            mock_context.messages, 4,
            template_file_name="test_template.json",
            isChatCompletion=False
        )
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="formatted_last_3_turns",
            llm_takes_images=False,
            request_id=None
        )

    def test_dispatch_applies_all_template_flags(self, mock_context, mocker):
        """
        Verifies that all boolean flags for prompt templating are correctly applied.
        """
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "prompt": "base prompt",
            "addUserTurnTemplate": True,
            "addOpenEndedAssistantTurnTemplate": True
        }
        mock_context.llm_handler.add_generation_prompt = True

        mock_format_system = mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                                          return_value="formatted_system")
        mock_format_user = mocker.patch('Middleware.services.llm_dispatch_service.format_user_turn_with_template',
                                        return_value="user_templated")
        mock_format_asst = mocker.patch(
            'Middleware.services.llm_dispatch_service.format_assistant_turn_with_template',
            return_value="asst_templated")
        mock_add_end_token = mocker.patch(
            'Middleware.services.llm_dispatch_service.add_assistant_end_token_to_user_turn',
            return_value="final_prompt")

        LLMDispatchService.dispatch(context=mock_context)

        # Verify system prompt formatting was called
        mock_format_system.assert_called_once_with("System instruction.", "test_template.json", False)
        # Verify the chain of transformations
        mock_format_user.assert_called_once_with("base prompt", "test_template.json", False)
        mock_format_asst.assert_called_once_with("user_templated", "test_template.json", False)
        mock_add_end_token.assert_called_once_with("asst_templated", "test_template.json", False)

        # Verify the final prompt is the result of the last transformation
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="final_prompt",
            llm_takes_images=False,
            request_id=None
        )

    def test_dispatch_with_llm_takes_images(self, mock_context, mocker):
        """
        Verifies that when llm_takes_images=True, the flag is passed through
        to the LLM handler for Completions APIs.
        """
        mock_context.config = {
            "systemPrompt": "System prompt.",
            "prompt": "Describe this image."
        }

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system_for_image_test")

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system_for_image_test",
            prompt="Describe this image.",
            llm_takes_images=True,
            request_id=None
        )


# --- Test Suite for Chat API Logic ---

class TestLLMDispatchServiceChat:
    """
    Tests the logic path where llm_handler.takes_message_collection is True.
    """

    def test_dispatch_with_prompt_from_config(self, mock_context):
        """
        Verifies that a 'prompt' from config is converted into a user message.
        """
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "prompt": "User instruction."
        }
        expected_collection = [
            {"role": "system", "content": "System instruction."},
            {"role": "user", "content": "User instruction."}
        ]

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=False,
            request_id=None
        )

    def test_dispatch_uses_last_n_messages_when_prompt_is_absent(self, mock_context, mocker):
        """
        Verifies that the service extracts and uses the last N turns from
        the conversation history.
        """
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "lastMessagesToSendInsteadOfPrompt": 2
        }
        # The last 2 messages from our test data
        last_turns_from_history = [
            {"role": "assistant", "content": "I am a large language model."},
            {"role": "user", "content": "Tell me a joke."}
        ]
        # Mock the utility function
        mock_extract = mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                                    return_value=last_turns_from_history)

        expected_collection = [
                                  {"role": "system", "content": "System instruction."}
                              ] + last_turns_from_history

        LLMDispatchService.dispatch(context=mock_context)

        mock_extract.assert_called_once_with(mock_context.messages, 2, True)
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=False,
            request_id=None
        )

    def test_dispatch_without_system_prompt(self, mock_context, mocker):
        """
        Verifies that no system message is added if the system prompt is empty.
        """
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "",
            "prompt": "User instruction."
        }
        expected_collection = [
            {"role": "user", "content": "User instruction."}
        ]

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=False,
            request_id=None
        )

    def test_dispatch_with_llm_takes_images(self, mock_context):
        """
        Verifies that when llm_takes_images=True, the flag is passed through
        to the LLM handler for Chat APIs.
        """
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"prompt": "Describe this image."}

        expected_collection = [
            {"role": "user", "content": "Describe this image."},
        ]

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=True,
            request_id=None
        )

    def test_dispatch_collects_images_from_recent_messages(self, mock_context):
        """
        Verifies that when llm_takes_images=True and messages have an 'images' key,
        all images are collected into the user message.
        """
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"prompt": "Describe these images."}
        mock_context.messages = [
            {"role": "user", "content": "First", "images": ["img_base64_1"]},
            {"role": "assistant", "content": "Reply"},
            {"role": "user", "content": "Second", "images": ["img_base64_2", "img_base64_3"]},
        ]

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        user_msg = conversation[-1]
        assert user_msg["role"] == "user"
        assert user_msg["images"] == ["img_base64_1", "img_base64_2", "img_base64_3"]

    def test_dispatch_no_images_key_when_messages_lack_images(self, mock_context):
        """
        Verifies that when llm_takes_images=True but no messages have an 'images' key,
        the user message does not contain an 'images' key.
        """
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"prompt": "No images here."}
        mock_context.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        user_msg = conversation[-1]
        assert user_msg["role"] == "user"
        assert "images" not in user_msg
