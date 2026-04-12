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
            request_id=None,  # Added for cancellation support
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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
            request_id=None,
            tools=None,
            tool_choice=None,
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


# --- Tests for _apply_image_limit ---

class TestApplyImageLimit:
    """Tests for the static _apply_image_limit helper."""

    def test_zero_limit_does_nothing(self):
        """max_images=0 means no limit; all images are kept."""
        messages = [
            {"role": "user", "content": "a", "images": ["i1", "i2"]},
            {"role": "user", "content": "b", "images": ["i3"]},
        ]
        LLMDispatchService._apply_image_limit(messages, 0)
        assert messages[0]["images"] == ["i1", "i2"]
        assert messages[1]["images"] == ["i3"]

    def test_negative_limit_does_nothing(self):
        """Negative max_images means no limit."""
        messages = [{"role": "user", "content": "a", "images": ["i1"]}]
        LLMDispatchService._apply_image_limit(messages, -1)
        assert messages[0]["images"] == ["i1"]

    def test_limit_keeps_most_recent(self):
        """With 5 images and limit 2, only the last 2 are kept."""
        messages = [
            {"role": "user", "content": "a", "images": ["i1", "i2"]},
            {"role": "user", "content": "b", "images": ["i3"]},
            {"role": "user", "content": "c", "images": ["i4", "i5"]},
        ]
        LLMDispatchService._apply_image_limit(messages, 2)
        # Oldest message: images removed entirely
        assert "images" not in messages[0]
        # Middle message: images removed entirely
        assert "images" not in messages[1]
        # Newest message: both images kept (2 <= limit of 2)
        assert messages[2]["images"] == ["i4", "i5"]

    def test_limit_splits_within_message(self):
        """When a single message has more images than the remaining budget,
        only the most recent images in that message are kept."""
        messages = [
            {"role": "user", "content": "a", "images": ["i1", "i2", "i3"]},
            {"role": "user", "content": "b", "images": ["i4"]},
        ]
        LLMDispatchService._apply_image_limit(messages, 2)
        # Last message uses 1 of 2 budget; first message gets 1 remaining → keeps last 1
        assert messages[0]["images"] == ["i3"]
        assert messages[1]["images"] == ["i4"]

    def test_limit_exact_match(self):
        """When total images equals the limit, all are kept."""
        messages = [
            {"role": "user", "content": "a", "images": ["i1"]},
            {"role": "user", "content": "b", "images": ["i2"]},
        ]
        LLMDispatchService._apply_image_limit(messages, 2)
        assert messages[0]["images"] == ["i1"]
        assert messages[1]["images"] == ["i2"]

    def test_limit_higher_than_total(self):
        """When limit exceeds total images, all are kept."""
        messages = [{"role": "user", "content": "a", "images": ["i1"]}]
        LLMDispatchService._apply_image_limit(messages, 100)
        assert messages[0]["images"] == ["i1"]

    def test_no_images_in_any_message(self):
        """Messages without images are left untouched."""
        messages = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        LLMDispatchService._apply_image_limit(messages, 2)
        assert "images" not in messages[0]
        assert "images" not in messages[1]

    def test_mixed_messages_with_and_without_images(self):
        """Only messages with images are affected; text-only messages are untouched."""
        messages = [
            {"role": "user", "content": "a", "images": ["i1", "i2"]},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "b"},
            {"role": "user", "content": "c", "images": ["i3"]},
        ]
        LLMDispatchService._apply_image_limit(messages, 1)
        assert "images" not in messages[0]
        assert "images" not in messages[1]
        assert "images" not in messages[2]
        assert messages[3]["images"] == ["i3"]

    def test_empty_images_list_ignored(self):
        """Messages with an empty images list are skipped, not counted."""
        messages = [
            {"role": "user", "content": "a", "images": []},
            {"role": "user", "content": "b", "images": ["i1"]},
        ]
        LLMDispatchService._apply_image_limit(messages, 1)
        assert messages[0]["images"] == []
        assert messages[1]["images"] == ["i1"]


# --- Tests for max_images in dispatch ---

class TestDispatchMaxImages:
    """Tests for the max_images parameter in LLMDispatchService.dispatch."""

    def test_max_images_limits_gathered_images_text_prompt_path(self, mock_context):
        """When using a text prompt, gathered images are trimmed to max_images."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"prompt": "Describe.", "lastMessagesToSendInsteadOfPrompt": 10}
        mock_context.messages = [
            {"role": "user", "content": "a", "images": ["i1"]},
            {"role": "user", "content": "b", "images": ["i2"]},
            {"role": "user", "content": "c", "images": ["i3"]},
        ]

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True, max_images=2)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        user_msg = conversation[-1]
        # Should keep only the last 2: i2, i3
        assert user_msg["images"] == ["i2", "i3"]

    def test_max_images_limits_last_n_messages_path(self, mock_context, mocker):
        """When using last N messages, images in the collection are trimmed."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"lastMessagesToSendInsteadOfPrompt": 10}
        returned_turns = [
            {"role": "user", "content": "a", "images": ["i1", "i2"]},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "b", "images": ["i3", "i4"]},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True, max_images=2)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        # System prompt is empty string, so no system message added
        # First message should have images stripped (budget exhausted by last message)
        assert "images" not in conversation[0]
        assert conversation[2]["images"] == ["i3", "i4"]

    def test_max_images_zero_sends_all(self, mock_context):
        """max_images=0 sends all images without limit."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"prompt": "Describe.", "lastMessagesToSendInsteadOfPrompt": 10}
        mock_context.messages = [
            {"role": "user", "content": "a", "images": ["i1"]},
            {"role": "user", "content": "b", "images": ["i2", "i3"]},
        ]

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True, max_images=0)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        user_msg = conversation[-1]
        assert user_msg["images"] == ["i1", "i2", "i3"]

    def test_max_images_with_no_images_present(self, mock_context):
        """max_images set but no images in messages does not break anything."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"prompt": "Just text."}
        mock_context.messages = [
            {"role": "user", "content": "hello"},
        ]

        LLMDispatchService.dispatch(context=mock_context, llm_takes_images=True, max_images=5)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        user_msg = conversation[-1]
        assert "images" not in user_msg


# --- Tests for allowTools gate ---

class TestAllowToolsGate:
    """Tests the allowTools boolean gate in LLMDispatchService.dispatch."""

    def test_tools_suppressed_by_default(self, mock_context, mocker):
        """When config has no 'allowTools' key, tools and tool_choice are not passed to the LLM."""
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt."
        }
        mock_context.tools = [{"type": "function", "function": {"name": "test"}}]
        mock_context.tool_choice = "auto"

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User prompt.",
            llm_takes_images=False,
            request_id=None,
            tools=None,
            tool_choice=None,
        )

    def test_tools_suppressed_when_false(self, mock_context, mocker):
        """When config has allowTools=False, tools and tool_choice are not passed to the LLM."""
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt.",
            "allowTools": False
        }
        mock_context.tools = [{"type": "function", "function": {"name": "test"}}]
        mock_context.tool_choice = "auto"

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User prompt.",
            llm_takes_images=False,
            request_id=None,
            tools=None,
            tool_choice=None,
        )

    def test_tools_sent_when_allow_tools_true(self, mock_context, mocker):
        """When config has allowTools=True, context.tools and context.tool_choice are forwarded."""
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt.",
            "allowTools": True
        }
        mock_context.tools = [{"type": "function", "function": {"name": "test"}}]
        mock_context.tool_choice = "auto"

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User prompt.",
            llm_takes_images=False,
            request_id=None,
            tools=[{"type": "function", "function": {"name": "test"}}],
            tool_choice="auto",
        )

    def test_tools_sent_when_true_chat_api(self, mock_context):
        """When allowTools=True on a chat API path, tools are forwarded."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt.",
            "allowTools": True
        }
        mock_context.tools = [{"type": "function", "function": {"name": "test"}}]
        mock_context.tool_choice = "auto"

        LLMDispatchService.dispatch(context=mock_context)

        expected_collection = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "User prompt."}
        ]
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=expected_collection,
            llm_takes_images=False,
            request_id=None,
            tools=[{"type": "function", "function": {"name": "test"}}],
            tool_choice="auto",
        )

    def test_tools_none_on_context_with_allow_tools_true(self, mock_context, mocker):
        """When allowTools=True but context.tools is None, tools=None is passed without error."""
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt.",
            "allowTools": True
        }
        mock_context.tools = None
        mock_context.tool_choice = None

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User prompt.",
            llm_takes_images=False,
            request_id=None,
            tools=None,
            tool_choice=None,
        )

    def test_tools_suppressed_completions_api(self, mock_context, mocker):
        """With completions API, tools are suppressed when allowTools is False."""
        mock_context.llm_handler.takes_message_collection = False
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt.",
            "allowTools": False
        }
        mock_context.tools = [{"type": "function", "function": {"name": "test"}}]
        mock_context.tool_choice = "required"

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User prompt.",
            llm_takes_images=False,
            request_id=None,
            tools=None,
            tool_choice=None,
        )

    def test_tools_sent_completions_api(self, mock_context, mocker):
        """With completions API, tools are sent when allowTools is True."""
        mock_context.llm_handler.takes_message_collection = False
        mock_context.config = {
            "systemPrompt": "System.",
            "prompt": "User prompt.",
            "allowTools": True
        }
        mock_context.tools = [{"type": "function", "function": {"name": "test"}}]
        mock_context.tool_choice = "required"

        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")

        LLMDispatchService.dispatch(context=mock_context)

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            conversation=None,
            system_prompt="formatted_system",
            prompt="User prompt.",
            llm_takes_images=False,
            request_id=None,
            tools=[{"type": "function", "function": {"name": "test"}}],
            tool_choice="required",
        )


# --- Tests for _merge_consecutive_assistant_messages ---

class TestMergeConsecutiveAssistantMessages:
    """Tests for the static _merge_consecutive_assistant_messages helper."""

    def test_no_consecutive_assistants_unchanged(self):
        """Alternating roles are left untouched."""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
            {"role": "assistant", "content": "goodbye"},
        ]
        original = deepcopy(messages)
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert messages == original

    def test_two_consecutive_assistants_merged(self):
        """Two adjacent assistant messages become one."""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "part 1"},
            {"role": "assistant", "content": "part 2"},
        ]
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert len(messages) == 2
        assert messages[1] == {"role": "assistant", "content": "part 1\npart 2"}

    def test_three_consecutive_assistants_merged(self):
        """Three adjacent assistant messages collapse into one."""
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert len(messages) == 2
        assert messages[1] == {"role": "assistant", "content": "a\nb\nc"}

    def test_custom_delimiter(self):
        """The delimiter parameter controls how content is joined."""
        messages = [
            {"role": "assistant", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
        LLMDispatchService._merge_consecutive_assistant_messages(messages, delimiter="\n---\n")
        assert messages[0]["content"] == "first\n---\nsecond"

    def test_system_message_separates_assistants(self):
        """A system message between assistants prevents merging."""
        messages = [
            {"role": "assistant", "content": "before"},
            {"role": "system", "content": "system note"},
            {"role": "assistant", "content": "after"},
        ]
        original = deepcopy(messages)
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert messages == original

    def test_tool_role_separates_assistants(self):
        """The tool-call sequence assistant -> tool -> assistant is NOT merged."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "f"}}]},
            {"role": "tool", "content": "result", "tool_call_id": "1"},
            {"role": "assistant", "content": "I used the tool."},
        ]
        original = deepcopy(messages)
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert messages == original

    def test_preserves_extra_keys_from_first_message(self):
        """Non-content keys from the first message in a run are kept."""
        messages = [
            {"role": "assistant", "content": "first", "images": ["img1"]},
            {"role": "assistant", "content": "second"},
        ]
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert len(messages) == 1
        assert messages[0]["content"] == "first\nsecond"
        assert messages[0]["images"] == ["img1"]

    def test_multiple_runs(self):
        """Two separate runs of consecutive assistants are each merged independently."""
        messages = [
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "b1"},
            {"role": "assistant", "content": "b2"},
        ]
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert len(messages) == 3
        assert messages[0] == {"role": "assistant", "content": "a1\na2"}
        assert messages[1] == {"role": "user", "content": "question"}
        assert messages[2] == {"role": "assistant", "content": "b1\nb2"}

    def test_single_message_no_change(self):
        """A single message is a no-op."""
        messages = [{"role": "assistant", "content": "only one"}]
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert messages == [{"role": "assistant", "content": "only one"}]

    def test_empty_list(self):
        """An empty list is a no-op."""
        messages = []
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert messages == []

    def test_empty_content_merged(self):
        """Assistant messages with empty content are still merged."""
        messages = [
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "text"},
        ]
        LLMDispatchService._merge_consecutive_assistant_messages(messages)
        assert len(messages) == 1
        assert messages[0]["content"] == "\ntext"


# --- Tests for _insert_user_turns_between_assistant_messages ---

class TestInsertUserTurnsBetweenAssistantMessages:
    """Tests for the static _insert_user_turns_between_assistant_messages helper."""

    def test_no_consecutive_assistants_unchanged(self):
        """Alternating roles get no insertions."""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ]
        original = deepcopy(messages)
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert messages == original

    def test_two_consecutive_assistants_gets_insert(self):
        """A synthetic user message is inserted between two assistants."""
        messages = [
            {"role": "assistant", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert len(messages) == 3
        assert messages[0] == {"role": "assistant", "content": "first"}
        assert messages[1] == {"role": "user", "content": "Continue."}
        assert messages[2] == {"role": "assistant", "content": "second"}

    def test_three_consecutive_assistants_gets_two_inserts(self):
        """Three consecutive assistants get two synthetic user messages."""
        messages = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert len(messages) == 5
        assert messages[0]["role"] == "assistant"
        assert messages[1] == {"role": "user", "content": "Continue."}
        assert messages[2]["role"] == "assistant"
        assert messages[3] == {"role": "user", "content": "Continue."}
        assert messages[4]["role"] == "assistant"

    def test_custom_text(self):
        """The text parameter controls the synthetic message content."""
        messages = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages, text="Proceed.")
        assert messages[1] == {"role": "user", "content": "Proceed."}

    def test_tool_role_separates_assistants(self):
        """assistant -> tool -> assistant does NOT get an insertion."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "1"},
            {"role": "assistant", "content": "done"},
        ]
        original = deepcopy(messages)
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert messages == original

    def test_empty_list_unchanged(self):
        """An empty list is a no-op."""
        messages = []
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert messages == []

    def test_single_message_unchanged(self):
        """A single message gets no insertion."""
        messages = [{"role": "assistant", "content": "only one"}]
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert messages == [{"role": "assistant", "content": "only one"}]

    def test_user_user_no_insert(self):
        """Consecutive user messages do NOT get a synthetic assistant message."""
        messages = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        original = deepcopy(messages)
        LLMDispatchService._insert_user_turns_between_assistant_messages(messages)
        assert messages == original


# --- Integration tests for consecutive assistant normalization in dispatch ---

class TestDispatchConsecutiveAssistantNormalization:
    """Tests that the merge/insert features are wired into dispatch correctly."""

    def test_merge_applied_in_chat_path(self, mock_context, mocker):
        """mergeConsecutiveAssistantMessages causes merging in the chat API path."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 10,
            "mergeConsecutiveAssistantMessages": True,
        }
        returned_turns = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "part 1"},
            {"role": "assistant", "content": "part 2"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        # The two assistant messages should be merged
        assistant_msgs = [m for m in conversation if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "part 1\npart 2"

    def test_merge_uses_custom_delimiter(self, mock_context, mocker):
        """mergeConsecutiveAssistantMessagesDelimiter is respected."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 10,
            "mergeConsecutiveAssistantMessages": True,
            "mergeConsecutiveAssistantMessagesDelimiter": " | ",
        }
        returned_turns = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        assistant_msgs = [m for m in conversation if m["role"] == "assistant"]
        assert assistant_msgs[0]["content"] == "a | b"

    def test_insert_applied_in_chat_path(self, mock_context, mocker):
        """insertUserTurnBetweenAssistantMessages causes insertion in the chat API path."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 10,
            "insertUserTurnBetweenAssistantMessages": True,
        }
        returned_turns = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        roles = [m["role"] for m in conversation]
        # Should be: user, assistant, user(synthetic), assistant
        assert roles == ["user", "assistant", "user", "assistant"]
        synthetic = [m for m in conversation if m["content"] == "Continue."]
        assert len(synthetic) == 1

    def test_insert_uses_custom_text(self, mock_context, mocker):
        """insertedUserTurnText is respected."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 10,
            "insertUserTurnBetweenAssistantMessages": True,
            "insertedUserTurnText": "Go on.",
        }
        returned_turns = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        synthetic = [m for m in conversation if m["role"] == "user"]
        assert len(synthetic) == 1
        assert synthetic[0]["content"] == "Go on."

    def test_merge_takes_precedence_over_insert(self, mock_context, mocker):
        """When both features are enabled, merge wins."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 10,
            "mergeConsecutiveAssistantMessages": True,
            "insertUserTurnBetweenAssistantMessages": True,
        }
        returned_turns = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        # Merged, not inserted — so one assistant message.
        # The user message safety net injects the most recent user message
        # from the full conversation since the window had none.
        assistant_msgs = [m for m in conversation if m["role"] == "assistant"]
        user_msgs = [m for m in conversation if m["role"] == "user"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "a\nb"
        assert len(user_msgs) == 1

    def test_neither_feature_enabled_no_change(self, mock_context, mocker):
        """When both features are disabled, consecutive assistants pass through unchanged."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 10,
        }
        returned_turns = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        assistant_msgs = [m for m in conversation if m["role"] == "assistant"]
        assert len(assistant_msgs) == 2

    def test_not_applied_in_text_prompt_path(self, mock_context):
        """When a prompt string is set, normalization is not applied (single user message)."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "prompt": "Some prompt text.",
            "mergeConsecutiveAssistantMessages": True,
            "insertUserTurnBetweenAssistantMessages": True,
        }

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        # Should just be a single user message from the prompt
        assert len(conversation) == 1
        assert conversation[0]["role"] == "user"


class TestEnsureUserMessagePresent:
    """Tests for LLMDispatchService._ensure_user_message_present."""

    def test_noop_when_user_message_exists(self):
        """No change when collection already contains a user message."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        full = list(collection)
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 3

    def test_inserts_user_message_after_system(self):
        """Inserts the most recent user message after the system message."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "thinking"},
            {"role": "assistant", "content": "done"},
        ]
        full = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "thinking"},
            {"role": "assistant", "content": "done"},
        ]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 4
        assert collection[1]["role"] == "user"
        assert collection[1]["content"] == "do something"

    def test_inserts_at_position_zero_when_no_system(self):
        """Inserts at position 0 when collection has no system message."""
        collection = [
            {"role": "assistant", "content": "result"},
        ]
        full = [
            {"role": "user", "content": "query"},
            {"role": "assistant", "content": "result"},
        ]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 2
        assert collection[0]["role"] == "user"
        assert collection[0]["content"] == "query"

    def test_inserts_after_multiple_system_messages(self):
        """Inserts after all leading system messages."""
        collection = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
            {"role": "assistant", "content": "response"},
        ]
        full = [
            {"role": "system", "content": "sys1"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "response"},
        ]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 4
        assert collection[2]["role"] == "user"
        assert collection[2]["content"] == "question"

    def test_noop_when_full_messages_has_no_user(self):
        """No change when the full conversation also has no user messages."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "response"},
        ]
        full = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "response"},
        ]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 2

    def test_picks_most_recent_user_message(self):
        """Uses the last user message from the full conversation."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "response"},
        ]
        full = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "response"},
        ]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert collection[1]["content"] == "second question"

    def test_tool_call_chain_scenario(self):
        """The exact bug scenario: tool-call chain with no user messages in the window."""
        collection = [
            {"role": "system", "content": "You are helpful"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "file contents", "tool_call_id": "1"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
            {"role": "tool", "content": "success", "tool_call_id": "2"},
            {"role": "assistant", "content": "I've fixed the bug"},
        ]
        full = [
            {"role": "user", "content": "fix the bug in foo.py"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "file contents", "tool_call_id": "1"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
            {"role": "tool", "content": "success", "tool_call_id": "2"},
            {"role": "assistant", "content": "I've fixed the bug"},
        ]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 7
        assert collection[1]["role"] == "user"
        assert collection[1]["content"] == "fix the bug in foo.py"
        # Rest of the chain is unchanged
        assert collection[2]["role"] == "assistant"
        assert collection[3]["role"] == "tool"

    def test_noop_with_empty_collection(self):
        """Empty collection with user in full — inserts it (degenerate case)."""
        collection = []
        full = [{"role": "user", "content": "hello"}]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 1
        assert collection[0]["role"] == "user"

    def test_noop_with_empty_full_messages(self):
        """Empty full_messages — no user message to insert."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "hi"},
        ]
        full = []
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert len(collection) == 2

    def test_inserted_message_is_a_copy(self):
        """The inserted message is a new dict, not the same object from full_messages."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "response"},
        ]
        original_user_msg = {"role": "user", "content": "query"}
        full = [original_user_msg, {"role": "assistant", "content": "response"}]
        LLMDispatchService._ensure_user_message_present(collection, full)
        assert collection[1] is not original_user_msg
        assert collection[1]["content"] == "query"

    def test_synthetic_user_from_insert_counts(self):
        """If insertUserTurnBetweenAssistantMessages already added a user message,
        _ensure_user_message_present should be a no-op."""
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "Continue."},
            {"role": "assistant", "content": "b"},
        ]
        full = [{"role": "user", "content": "original"}]
        LLMDispatchService._ensure_user_message_present(collection, full)
        # Should not insert — synthetic user message already present
        assert len(collection) == 4


class TestDispatchEnsureUserMessage:
    """Tests that _ensure_user_message_present is wired into dispatch correctly."""

    def test_user_message_injected_in_tool_chain(self, mock_context, mocker):
        """When lastMessagesToSendInsteadOfPrompt returns only tool-chain messages,
        the original user message is recovered from the full conversation."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "You are helpful",
            "lastMessagesToSendInsteadOfPrompt": 4,
        }
        mock_context.messages = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "1"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
            {"role": "tool", "content": "ok", "tool_call_id": "2"},
            {"role": "assistant", "content": "done"},
        ]
        # extract_last_n_turns with n=4 returns the last 4 messages (no user)
        returned_turns = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
            {"role": "tool", "content": "ok", "tool_call_id": "2"},
            {"role": "assistant", "content": "done"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        # Should have: system, user (injected), assistant, tool, assistant
        user_msgs = [m for m in conversation if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "fix the bug"
        # User message should be right after system
        assert conversation[0]["role"] == "system"
        assert conversation[1]["role"] == "user"

    def test_no_injection_when_user_already_in_window(self, mock_context, mocker):
        """When the window already contains a user message, no injection occurs."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "systemPrompt": "sys",
            "lastMessagesToSendInsteadOfPrompt": 10,
        }
        mock_context.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        returned_turns = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.extract_last_n_turns',
                     return_value=deepcopy(returned_turns))

        LLMDispatchService.dispatch(context=mock_context)

        call_args = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation = call_args[1]["conversation"]
        user_msgs = [m for m in conversation if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert conversation == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

    def test_not_applied_in_text_prompt_path(self, mock_context, mocker):
        """When a text prompt is set, the safety net does not run."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {
            "prompt": "Some prompt.",
        }
        mock_ensure = mocker.patch.object(LLMDispatchService, '_ensure_user_message_present')

        LLMDispatchService.dispatch(context=mock_context)

        mock_ensure.assert_not_called()

    def test_not_applied_in_completions_path(self, mock_context, mocker):
        """Completions API path does not call _ensure_user_message_present."""
        mock_context.llm_handler.takes_message_collection = False
        mock_context.config = {
            "lastMessagesToSendInsteadOfPrompt": 5,
        }
        mock_ensure = mocker.patch.object(LLMDispatchService, '_ensure_user_message_present')
        mocker.patch('Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string',
                     return_value="formatted prompt")
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="system prompt")

        LLMDispatchService.dispatch(context=mock_context)

        mock_ensure.assert_not_called()
