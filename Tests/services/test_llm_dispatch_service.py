# Tests/services/test_llm_dispatch_service.py

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

SAMPLE_IMAGE_MESSAGE = {"role": "images", "content": "base64_encoded_image_string"}


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
    mock_llm_handler.takes_image_collection = False  # Default to False
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
        # Arrange
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "prompt": "User instruction."
        }
        # Mock the template functions that will be called
        mock_format_system = mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                                          return_value="formatted_system")
        mock_get_last_turns = mocker.patch(
            'Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string')

        # Act
        LLMDispatchService.dispatch(context=mock_context)

        # Assert
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
        # Arrange
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

        # Act
        LLMDispatchService.dispatch(context=mock_context)

        # Assert
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
        # Arrange
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

        # Act
        LLMDispatchService.dispatch(context=mock_context)

        # Assert
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

    def test_dispatch_with_image_message(self, mock_context, mocker):
        """
        Verifies that an image message is correctly passed in the 'conversation'
        argument for Completions APIs that can handle them.
        """
        # Arrange
        mock_context.config = {
            "systemPrompt": "System prompt.",
            "prompt": "Describe this image."
        }
        mock_context.llm_handler.takes_image_collection = True

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system_for_image_test")

        # Act
        LLMDispatchService.dispatch(context=mock_context, image_message=SAMPLE_IMAGE_MESSAGE)

        # Assert
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=[SAMPLE_IMAGE_MESSAGE],
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
        # Arrange
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "System instruction.",
            "prompt": "User instruction."
        }
        expected_collection = [
            {"role": "system", "content": "System instruction."},
            {"role": "user", "content": "User instruction."}
        ]

        # Act
        LLMDispatchService.dispatch(context=mock_context)

        # Assert
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
        # Arrange
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

        # Act
        LLMDispatchService.dispatch(context=mock_context)

        # Assert
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
        # Arrange
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "",
            "prompt": "User instruction."
        }
        expected_collection = [
            {"role": "user", "content": "User instruction."}
        ]

        # Act
        LLMDispatchService.dispatch(context=mock_context)

        # Assert
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=False,
            request_id=None
        )

    def test_dispatch_with_image_message(self, mock_context):
        """
        Verifies that an image message is correctly appended to the message list.
        """
        # Arrange
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.takes_image_collection = True
        mock_context.config = {"prompt": "Describe this image."}

        expected_collection = [
            {"role": "user", "content": "Describe this image."},
            SAMPLE_IMAGE_MESSAGE
        ]

        # Act
        LLMDispatchService.dispatch(context=mock_context, image_message=SAMPLE_IMAGE_MESSAGE)

        # Assert
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=True,
            request_id=None
        )
