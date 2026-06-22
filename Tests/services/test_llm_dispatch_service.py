from copy import deepcopy

import pytest

from Middleware.services.llm_dispatch_service import (
    LLMDispatchService, _CLAMP_PER_MESSAGE_OVERHEAD_TOKENS, _CLAMP_HEADROOM_TOKENS)
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


@pytest.fixture(autouse=True)
def _hermetic_user_config(mocker):
    """Isolate dispatch tests from the real user config file.

    The context clamp resolves node -> endpoint -> user -> default(OFF) via the
    shared config_utils.is_context_clamp_enabled, whose user level calls
    get_user_config(); default it to an empty dict (clamp OFF) so tests are
    hermetic. A test that wants the user-level flag re-patches the returned mock's
    return_value.
    """
    return mocker.patch(
        'Middleware.utilities.config_utils.get_user_config', return_value={})


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


class TestDispatchMaxConversationTokenSize:
    """Tests for ``lastMessagesToSendInsteadOfPromptMaxTokenSize``: an optional token
    ceiling layered on top of the ``lastMessagesToSendInsteadOfPrompt`` message-count
    cap, so a long agentic conversation (large tool results) cannot overflow the
    endpoint context window. Keeps the most recent messages that fit within budget."""

    def test_chat_absent_param_sends_all_last_n(self, mock_context):
        """Without the param, the chat path is unchanged: all last-N messages are sent."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 4}

        LLMDispatchService.dispatch(context=mock_context)

        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert conversation[0] == {"role": "system", "content": "Sys."}
        assert [m["content"] for m in conversation[1:]] == [
            "Hello, human.", "How are you?", "I am a large language model.", "Tell me a joke."]

    def test_chat_token_cap_trims_to_budget(self, mock_context, mocker):
        """With a token ceiling, only the most-recent messages within budget are sent."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 5,
                               "lastMessagesToSendInsteadOfPromptMaxTokenSize": 200}
        # Each candidate message estimates to 100 tokens.
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)

        LLMDispatchService.dispatch(context=mock_context)

        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        # Budget 200 at 100/msg => the last 2 messages survive; system is always added.
        assert conversation[0]["role"] == "system"
        assert [m["content"] for m in conversation[1:]] == [
            "I am a large language model.", "Tell me a joke."]

    def test_chat_token_cap_keeps_at_least_one(self, mock_context, mocker):
        """A budget smaller than the most-recent message still yields exactly that one (floor 1)."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 5,
                               "lastMessagesToSendInsteadOfPromptMaxTokenSize": 1}
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)

        LLMDispatchService.dispatch(context=mock_context)

        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert [m["content"] for m in conversation[1:]] == ["Tell me a joke."]

    def test_chat_generous_cap_keeps_all_last_n(self, mock_context):
        """A generous ceiling does not trim: same result as no param."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 4,
                               "lastMessagesToSendInsteadOfPromptMaxTokenSize": 100000}

        LLMDispatchService.dispatch(context=mock_context)

        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert [m["content"] for m in conversation[1:]] == [
            "Hello, human.", "How are you?", "I am a large language model.", "Tell me a joke."]

    def test_completions_token_cap_preslices_source(self, mock_context, mocker):
        """On the completions path, the ceiling pre-slices the messages handed to the formatter."""
        mock_context.llm_handler.takes_message_collection = False  # completions API
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 5,
                               "lastMessagesToSendInsteadOfPromptMaxTokenSize": 1}
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="formatted_system")
        mock_fmt = mocker.patch(
            'Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string',
            return_value="formatted")

        LLMDispatchService.dispatch(context=mock_context)

        passed_messages = mock_fmt.call_args[0][0]
        assert [m["content"] for m in passed_messages] == ["Tell me a joke."]

    def test_none_content_message_does_not_crash(self, mock_context):
        """Tool-call assistant messages with content=None must not crash the token estimator."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.messages = [
            {"role": "user", "content": "Do the thing."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "t1"},
        ]
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 10,
                               "lastMessagesToSendInsteadOfPromptMaxTokenSize": 100000}

        LLMDispatchService.dispatch(context=mock_context)  # must not raise

        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert [m.get("content") for m in conversation[1:]] == ["Do the thing.", None, "result"]


# --- Tests for the endpoint-context-aware pre-send clamp ---

class TestEstimateTokensForTools:
    """Tests for the static _estimate_tokens_for_tools helper."""

    def test_none_returns_zero(self):
        assert LLMDispatchService._estimate_tokens_for_tools(None) == 0

    def test_empty_returns_zero(self):
        assert LLMDispatchService._estimate_tokens_for_tools([]) == 0

    def test_tool_list_returns_positive(self):
        tools = [{"type": "function", "function": {"name": "read_file", "description": "Reads a file."}}]
        assert LLMDispatchService._estimate_tokens_for_tools(tools) > 0

    def test_non_serializable_returns_zero(self):
        """A tool definition that cannot be JSON-serialized is counted as 0, not raised."""
        tools = [{"type": "function", "bad": {1, 2, 3}}]  # set is not JSON serializable
        assert LLMDispatchService._estimate_tokens_for_tools(tools) == 0


class TestComputeConversationTokenBudget:
    """Tests for the static _compute_conversation_token_budget helper."""

    def _handler(self, mocker, endpoint_file, max_tokens=0):
        llm = mocker.Mock()
        llm.endpoint_file = endpoint_file
        llm.max_tokens = max_tokens
        handler = mocker.Mock()
        handler.llm = llm
        return handler

    def test_none_when_endpoint_file_not_dict(self, mocker):
        """A mocked handler (endpoint_file is a Mock, not a dict) disables the clamp."""
        handler = mocker.Mock()  # handler.llm.endpoint_file is an auto-Mock, not a dict
        assert LLMDispatchService._compute_conversation_token_budget(handler, "sys", None) is None

    def test_none_when_window_missing(self, mocker):
        handler = self._handler(mocker, {}, max_tokens=100)
        assert LLMDispatchService._compute_conversation_token_budget(handler, "sys", None) is None

    def test_none_when_window_zero_or_negative(self, mocker):
        for bad in (0, -1):
            handler = self._handler(mocker, {"maxContextTokenSize": bad}, max_tokens=100)
            assert LLMDispatchService._compute_conversation_token_budget(handler, "sys", None) is None

    def test_none_when_window_is_bool(self, mocker):
        """A boolean maxContextTokenSize (misconfig) is rejected, not treated as 1."""
        handler = self._handler(mocker, {"maxContextTokenSize": True}, max_tokens=100)
        assert LLMDispatchService._compute_conversation_token_budget(handler, "sys", None) is None

    def test_budget_formula(self, mocker):
        """budget = window - n_predict - est(system) - est(tools) - headroom."""
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=50)
        handler = self._handler(mocker, {"maxContextTokenSize": 1000}, max_tokens=200)
        # system "sys" -> 50, tools None -> 0, headroom 512
        assert LLMDispatchService._compute_conversation_token_budget(handler, "sys", None) == 1000 - 200 - 50 - 0 - 512

    def test_budget_subtracts_tools(self, mocker):
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=50)
        handler = self._handler(mocker, {"maxContextTokenSize": 1000}, max_tokens=200)
        tools = [{"type": "function", "function": {"name": "f"}}]
        # system 50 + tools 50 subtracted
        assert LLMDispatchService._compute_conversation_token_budget(handler, "sys", tools) == 1000 - 200 - 50 - 50 - 512

    def test_empty_system_counts_zero(self, mocker):
        handler = self._handler(mocker, {"maxContextTokenSize": 1000}, max_tokens=200)
        # Empty system prompt -> 0 tokens, no estimator call needed
        assert LLMDispatchService._compute_conversation_token_budget(handler, "", None) == 1000 - 200 - 0 - 0 - 512

    def test_non_numeric_max_tokens_treated_as_zero(self, mocker):
        handler = self._handler(mocker, {"maxContextTokenSize": 1000}, max_tokens="oops")
        assert LLMDispatchService._compute_conversation_token_budget(handler, "", None) == 1000 - 0 - 0 - 0 - 512

    def test_negative_budget_logged_and_returned(self, mocker, caplog):
        """When response+system+headroom exceed the window, a negative budget is
        returned (callers still trim to it) and a warning is logged."""
        handler = self._handler(mocker, {"maxContextTokenSize": 100}, max_tokens=200)
        with caplog.at_level("WARNING"):
            budget = LLMDispatchService._compute_conversation_token_budget(handler, "", None)
        assert budget == 100 - 200 - 0 - 0 - 512
        assert any("budget" in r.message for r in caplog.records)


class TestTrimMessagesToTokenBudget:
    """Tests for the static _trim_messages_to_token_budget helper."""

    def test_none_budget_returns_same_object(self):
        messages = [{"role": "user", "content": "a"}]
        result = LLMDispatchService._trim_messages_to_token_budget(messages, None)
        assert result is messages

    def test_empty_returns_same_object(self):
        messages = []
        result = LLMDispatchService._trim_messages_to_token_budget(messages, 100)
        assert result is messages

    def test_drops_oldest_to_fit(self, mocker):
        """With each message at 100 tokens (+8 overhead = 108), a 250 budget keeps the 2 newest."""
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        messages = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        result = LLMDispatchService._trim_messages_to_token_budget(messages, 250)
        assert [m["content"] for m in result] == ["m3", "m4"]

    def test_keeps_at_least_one(self, mocker, caplog):
        """A budget below a single message still yields exactly the most recent one,
        kept WHOLE (never content-truncated), with a warning."""
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        messages = [{"role": "user", "content": "old"}, {"role": "user", "content": "new"}]
        with caplog.at_level("WARNING"):
            result = LLMDispatchService._trim_messages_to_token_budget(messages, 1)
        assert len(result) == 1
        # The single kept message is sent WHOLE; conversation content is never chopped.
        assert result[0] == {"role": "user", "content": "new"}
        assert any("single most-recent" in r.message for r in caplog.records)

    def test_generous_budget_keeps_all(self, mocker):
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=10)
        messages = [{"role": "user", "content": f"m{i}"} for i in range(4)]
        result = LLMDispatchService._trim_messages_to_token_budget(messages, 100000)
        assert [m["content"] for m in result] == ["m0", "m1", "m2", "m3"]

    def test_keeps_single_oversized_message_whole(self, caplog):
        """A single message larger than the whole budget is kept WHOLE (never content-
        truncated) and a warning is logged: a visible backend rejection beats silently
        dropping the operator's content. Uses the real estimator."""
        content = " ".join(f"w{i}" for i in range(500))
        messages = [{"role": "user", "content": content}]
        with caplog.at_level("WARNING"):
            result = LLMDispatchService._trim_messages_to_token_budget(messages, 100)
        assert len(result) == 1
        # Byte-for-byte intact: all 500 words survive, nothing chopped from either end.
        assert result[0]["content"] == content
        assert any("single most-recent" in r.message for r in caplog.records)

    def test_none_content_does_not_crash(self, mocker):
        """A message with content=None is handled (treated as empty)."""
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=10)
        messages = [{"role": "assistant", "content": None}, {"role": "user", "content": "hi"}]
        result = LLMDispatchService._trim_messages_to_token_budget(messages, 100000)
        assert len(result) == 2


class TestClampChatCollectionToBudget:
    """Tests for the static _clamp_chat_collection_to_budget helper."""

    def test_none_budget_noop(self):
        collection = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        original = deepcopy(collection)
        LLMDispatchService._clamp_chat_collection_to_budget(collection, None)
        assert collection == original

    def test_preserves_leading_system_messages(self, mocker):
        """The leading system message is kept; only the body is trimmed."""
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        collection = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "m0"},
            {"role": "assistant", "content": "m1"},
            {"role": "user", "content": "m2"},
        ]
        # budget 250 at 108/msg keeps the 2 newest body messages.
        LLMDispatchService._clamp_chat_collection_to_budget(collection, 250)
        assert collection[0] == {"role": "system", "content": "sys"}
        assert [m["content"] for m in collection[1:]] == ["m1", "m2"]

    def test_body_only_no_system(self, mocker):
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        collection = [{"role": "user", "content": f"m{i}"} for i in range(4)]
        LLMDispatchService._clamp_chat_collection_to_budget(collection, 250)
        assert [m["content"] for m in collection] == ["m2", "m3"]


class TestWarnIfAuthoredPromptOverflows:
    """Tests for _warn_if_authored_prompt_overflows, which warns but NEVER mutates
    an operator-authored prompt (a hard backend failure beats silent truncation)."""

    def _handler(self, mocker, window=1000):
        llm = mocker.Mock()
        llm.endpoint_file = {"maxContextTokenSize": window}
        handler = mocker.Mock()
        handler.llm = llm
        return handler

    def test_none_budget_no_warning(self, mocker, caplog):
        handler = self._handler(mocker)
        with caplog.at_level("WARNING"):
            LLMDispatchService._warn_if_authored_prompt_overflows("hello", None, {}, handler)
        assert not caplog.records

    def test_empty_prompt_no_warning(self, mocker, caplog):
        handler = self._handler(mocker)
        with caplog.at_level("WARNING"):
            LLMDispatchService._warn_if_authored_prompt_overflows("", 100, {}, handler)
        assert not caplog.records

    def test_fits_no_warning(self, mocker, caplog):
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=10)
        handler = self._handler(mocker)
        with caplog.at_level("WARNING"):
            LLMDispatchService._warn_if_authored_prompt_overflows("short", 100, {}, handler)
        assert not caplog.records

    def test_overflow_warns_and_does_not_mutate(self, mocker, caplog):
        """When the authored prompt exceeds the budget a warning is logged; the helper
        returns None and never alters the prompt."""
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=5000)
        handler = self._handler(mocker, window=1000)
        with caplog.at_level("WARNING"):
            result = LLMDispatchService._warn_if_authored_prompt_overflows(
                "big prompt", 200, {"title": "MyNode"}, handler)
        assert result is None
        assert any("authored prompt" in r.message for r in caplog.records)


class TestDispatchPreSendClampIntegration:
    """End-to-end tests that the clamp is wired into dispatch for both API branches."""

    def _set_endpoint(self, mock_context, window, n_predict):
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": window}
        mock_context.llm_handler.llm.max_tokens = n_predict

    def test_chat_doer_collection_trimmed_to_window(self, mock_context, mocker):
        """A chat last-N collection that overflows the window is trimmed to the most recent."""
        mock_context.llm_handler.takes_message_collection = True
        self._set_endpoint(mock_context, window=1000, n_predict=100)
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 10,
                               "clampPromptToContextWindow": True}
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        # budget = 1000 - 100 - 100(sys) - 0 - 512 = 288; 108/msg keeps 2 newest.
        LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert conversation[0]["role"] == "system"
        assert [m["content"] for m in conversation[1:]] == [
            "I am a large language model.", "Tell me a joke."]

    def test_chat_authored_prompt_never_truncated(self, mock_context, caplog):
        """A chat node whose authored prompt overflows the window is sent INTACT, never
        silently truncated; a warning is logged instead (hard failure beats sabotage)."""
        mock_context.llm_handler.takes_message_collection = True
        self._set_endpoint(mock_context, window=1000, n_predict=100)
        big = " ".join(f"w{i}" for i in range(3000))
        mock_context.config = {"systemPrompt": "Sys.", "prompt": big,
                               "clampPromptToContextWindow": True}
        with caplog.at_level("WARNING"):
            LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert conversation[0] == {"role": "system", "content": "Sys."}
        user_msg = conversation[-1]
        assert user_msg["role"] == "user"
        # The authored prompt survives in full -- no head or tail chopped.
        assert user_msg["content"] == big
        assert any("authored prompt" in r.message for r in caplog.records)

    def test_chat_noop_when_fits(self, mock_context):
        """A generous window leaves the chat collection untouched."""
        mock_context.llm_handler.takes_message_collection = True
        self._set_endpoint(mock_context, window=65536, n_predict=800)
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 10,
                               "clampPromptToContextWindow": True}
        LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert [m["content"] for m in conversation[1:]] == [
            "Hello, bot.", "Hello, human.", "How are you?", "I am a large language model.", "Tell me a joke."]

    def test_chat_clamp_then_ensure_recovers_user_message(self, mock_context, mocker):
        """When the clamp drops the only (oldest) user message, the user-message safety
        net recovers it from the full conversation."""
        mock_context.llm_handler.takes_message_collection = True
        self._set_endpoint(mock_context, window=1000, n_predict=100)
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 10,
                               "clampPromptToContextWindow": True}
        mock_context.messages = [
            {"role": "user", "content": "the original task"},
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        # budget 288, 108/msg keeps newest 2 (b, c) -> no user -> ensure re-adds it.
        LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        user_msgs = [m for m in conversation if m["role"] == "user"]
        assert any(m["content"] == "the original task" for m in user_msgs)

    def test_completions_source_messages_trimmed(self, mock_context, mocker):
        """On the completions last-N path, the message slice handed to the formatter is trimmed."""
        mock_context.llm_handler.takes_message_collection = False
        self._set_endpoint(mock_context, window=1000, n_predict=100)
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 10,
                               "clampPromptToContextWindow": True}
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="fs")
        mock_fmt = mocker.patch(
            'Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string',
            return_value="fmt")
        # budget = 1000 - 100 - 100(sys) - 512 = 288; 108/msg keeps 2 newest of the 6.
        LLMDispatchService.dispatch(context=mock_context)
        passed_messages = mock_fmt.call_args[0][0]
        assert [m["content"] for m in passed_messages] == [
            "I am a large language model.", "Tell me a joke."]

    def test_completions_authored_prompt_never_truncated(self, mock_context, mocker, caplog):
        """On the completions fixed-prompt path, an oversized authored prompt is sent
        INTACT, never truncated; a warning is logged instead."""
        mock_context.llm_handler.takes_message_collection = False
        self._set_endpoint(mock_context, window=1000, n_predict=100)
        big = " ".join(f"w{i}" for i in range(3000))
        mock_context.config = {"systemPrompt": "Sys.", "prompt": big,
                               "clampPromptToContextWindow": True}
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="fs")
        with caplog.at_level("WARNING"):
            LLMDispatchService.dispatch(context=mock_context)
        sent_prompt = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["prompt"]
        # The whole authored prompt survives (all 3000 words); nothing chopped.
        assert len(sent_prompt.split()) == 3000
        assert any("authored prompt" in r.message for r in caplog.records)

    def test_completions_fixed_prompt_noop_when_fits(self, mock_context, mocker):
        mock_context.llm_handler.takes_message_collection = False
        self._set_endpoint(mock_context, window=65536, n_predict=100)
        mock_context.config = {"systemPrompt": "Sys.", "prompt": "short prompt",
                               "clampPromptToContextWindow": True}
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     return_value="fs")
        LLMDispatchService.dispatch(context=mock_context)
        sent_prompt = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["prompt"]
        assert sent_prompt == "short prompt"

    def test_clamp_disabled_with_mocked_endpoint(self, mock_context):
        """With a fully-mocked handler (no real endpoint_file dict), the clamp is a
        no-op: all last-N messages pass through unchanged."""
        mock_context.llm_handler.takes_message_collection = True
        # Do NOT set endpoint_file/max_tokens to real values -> they are Mocks.
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 10}
        LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert [m["content"] for m in conversation[1:]] == [
            "Hello, bot.", "Hello, human.", "How are you?", "I am a large language model.", "Tell me a joke."]


class TestPromptIntegrityBattery:
    """Exhaustive battery proving the operator's authored content holds firm across
    the clamp/level matrix. Covers handoff invariants C (systemPrompt never
    truncated), E (clamp OFF is byte-for-byte pre-feature), F (conservative ==
    baseline), H (the level scales the conversation budget, monotonically), and I
    (the endpoint window sent to the backend is never scaled by the level). The
    sacred rule under test: Wilmer may drop whole oldest CONVERSATION messages, but
    must NEVER alter the authored prompt/systemPrompt."""

    # --- helpers -------------------------------------------------------------
    def _eight_user_messages(self):
        return [{"role": "user", "content": f"u{i}"} for i in range(8)]

    def _setup_level_case(self, mock_context, mocker, level=None, clamp=True, window=1000,
                          n_predict=100):
        """Eight equal-sized user messages, estimator pinned at 100/msg, so the
        surviving count is a clean function of the level-scaled budget.

        With window=1000, n_predict=100, system=100, headroom=512 and 108/msg:
        budget = int((1000-100)*level) - 100 - 512; survivors = floor(budget/108),
        capped at 8. => conservative 2, balanced 4, aggressive 6, xaggressive 8.
        """
        mock_context.llm_handler.takes_message_collection = True
        endpoint = {"maxContextTokenSize": window}
        if level is not None:
            endpoint["wilmerContextEstimationLevel"] = level
        mock_context.llm_handler.llm.endpoint_file = endpoint
        mock_context.llm_handler.llm.max_tokens = n_predict
        mock_context.messages = self._eight_user_messages()
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 8}
        if clamp:
            mock_context.config["clampPromptToContextWindow"] = True
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length',
                     return_value=100)

    def _body(self, mock_context):
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        return [m["content"] for m in conversation if m["role"] != "system"]

    # --- C: systemPrompt is never truncated ----------------------------------
    def test_chat_huge_system_prompt_preserved_intact(self, mock_context):
        """A system prompt far larger than the window is kept WHOLE as the leading
        system message (its tokens are budgeted out, never chopped)."""
        mock_context.llm_handler.takes_message_collection = True
        big_system = " ".join(f"s{i}" for i in range(5000))
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.config = {"systemPrompt": big_system, "lastMessagesToSendInsteadOfPrompt": 5,
                               "clampPromptToContextWindow": True}
        LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert conversation[0] == {"role": "system", "content": big_system}

    def test_completions_huge_system_prompt_preserved_intact(self, mock_context, mocker):
        """On completions, the (huge) system prompt is forwarded intact; the clamp
        never touches it."""
        mock_context.llm_handler.takes_message_collection = False
        big_system = " ".join(f"s{i}" for i in range(5000))
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.config = {"systemPrompt": big_system, "lastMessagesToSendInsteadOfPrompt": 5,
                               "clampPromptToContextWindow": True}
        # Identity system template so we can assert the content survived end to end;
        # stub the conversation formatter so the test does not touch the filesystem.
        mocker.patch('Middleware.services.llm_dispatch_service.format_system_prompt_with_template',
                     side_effect=lambda s, *a, **k: s)
        mocker.patch('Middleware.services.llm_dispatch_service.get_formatted_last_n_turns_as_string',
                     return_value="fmt")
        LLMDispatchService.dispatch(context=mock_context)
        sent_system = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["system_prompt"]
        assert sent_system == big_system

    # --- E: clamp OFF is byte-for-byte pre-feature behavior -------------------
    def test_clamp_off_absent_chat_no_trim_no_warning(self, mock_context, mocker, caplog):
        """Flag absent: even with a tiny window, NOTHING is trimmed and nothing is
        logged (the clamp is the master switch; off means let the chips fall)."""
        self._setup_level_case(mock_context, mocker, level=None, clamp=False)
        with caplog.at_level("WARNING"):
            LLMDispatchService.dispatch(context=mock_context)
        assert self._body(mock_context) == [f"u{i}" for i in range(8)]
        assert not caplog.records

    def test_clamp_off_false_chat_no_trim(self, mock_context, mocker):
        """Flag explicitly False overrides everything: no trimming."""
        self._setup_level_case(mock_context, mocker, level="xaggressive", clamp=False)
        mock_context.config["clampPromptToContextWindow"] = False
        LLMDispatchService.dispatch(context=mock_context)
        assert self._body(mock_context) == [f"u{i}" for i in range(8)]

    def test_clamp_off_does_not_scale_doer_cap(self, mock_context, mocker):
        """With the clamp OFF, a non-conservative endpoint level is INERT: the doer
        cap (lastMessagesToSendInsteadOfPromptMaxTokenSize) is applied at its RAW
        value, not level-scaled (handoff Q1)."""
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.llm.endpoint_file = {
            "maxContextTokenSize": 1000, "wilmerContextEstimationLevel": "xaggressive"}
        mock_context.messages = self._eight_user_messages()
        mock_context.config = {"systemPrompt": "Sys.", "lastMessagesToSendInsteadOfPrompt": 8,
                               "lastMessagesToSendInsteadOfPromptMaxTokenSize": 200}
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)
        LLMDispatchService.dispatch(context=mock_context)
        # Raw cap 200 at 100/msg keeps exactly the 2 newest. If the level (1.85) had
        # leaked in, the cap would have been 370 and 3 messages would survive.
        assert self._body(mock_context) == ["u6", "u7"]

    def test_clamp_off_authored_prompt_no_warning(self, mock_context, caplog):
        """Clamp OFF: an overflowing authored prompt is sent as-is with NO warning
        (warnings are part of clamp awareness, which is off)."""
        mock_context.llm_handler.takes_message_collection = True
        big = " ".join(f"w{i}" for i in range(3000))
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.config = {"systemPrompt": "Sys.", "prompt": big}  # no clamp flag
        with caplog.at_level("WARNING"):
            LLMDispatchService.dispatch(context=mock_context)
        conversation = mock_context.llm_handler.llm.get_response_from_llm.call_args[1]["conversation"]
        assert conversation[-1]["content"] == big
        assert not caplog.records

    # --- F: conservative == baseline (absence behaves as conservative) --------
    def test_absent_level_equals_conservative(self, mock_context, mocker):
        """Clamp ON with no level set keeps the same messages as an explicit
        conservative level (both 1.0): the default is a true no-op on the budget."""
        self._setup_level_case(mock_context, mocker, level=None, clamp=True)
        LLMDispatchService.dispatch(context=mock_context)
        assert self._body(mock_context) == ["u6", "u7"]

    def test_explicit_conservative_matches(self, mock_context, mocker):
        self._setup_level_case(mock_context, mocker, level="conservative", clamp=True)
        LLMDispatchService.dispatch(context=mock_context)
        assert self._body(mock_context) == ["u6", "u7"]

    # --- H: the level scales the conversation budget, monotonically -----------
    @pytest.mark.parametrize("level,kept", [
        ("conservative", 2),
        ("balanced", 4),
        ("aggressive", 6),
        ("xaggressive", 8),
    ])
    def test_level_scales_conversation_budget(self, mock_context, mocker, level, kept):
        """A higher level lets strictly more conversation through (the whole point of
        the calibration knob), and only ever drops whole oldest messages."""
        self._setup_level_case(mock_context, mocker, level=level, clamp=True)
        LLMDispatchService.dispatch(context=mock_context)
        assert self._body(mock_context) == [f"u{i}" for i in range(8 - kept, 8)]

    def test_level_effect_is_monotonic(self, mock_context, mocker):
        """Sweep all four levels and assert the surviving-message count never
        decreases as the level rises."""
        counts = []
        for level in ("conservative", "balanced", "aggressive", "xaggressive"):
            mock_context.llm_handler.llm.get_response_from_llm.reset_mock()
            self._setup_level_case(mock_context, mocker, level=level, clamp=True)
            LLMDispatchService.dispatch(context=mock_context)
            counts.append(len(self._body(mock_context)))
        assert counts == sorted(counts)
        assert counts[0] < counts[-1]  # the knob demonstrably reclaims window

    # --- I: the endpoint window forwarded to the backend is never scaled ------
    def test_level_does_not_mutate_endpoint_window(self, mock_context, mocker):
        """The level scales Wilmer's INTERNAL budget only; it must never change the
        maxContextTokenSize value (which is what the backend receives as
        truncate_length)."""
        self._setup_level_case(mock_context, mocker, level="xaggressive", clamp=True)
        LLMDispatchService.dispatch(context=mock_context)
        assert mock_context.llm_handler.llm.endpoint_file["maxContextTokenSize"] == 1000


class TestTrimBudgetBoundariesAdversarial:
    """Adversarial boundary tests for the core conversation-trim primitive
    `_trim_messages_to_token_budget` -- the sacred path. Conversation content is
    NEVER truncated; whole oldest messages drop; the newest is always kept whole."""

    OVERHEAD = _CLAMP_PER_MESSAGE_OVERHEAD_TOKENS  # per-message framing cost (8)

    def _msgs(self, n):
        return [{"role": "user", "content": f"m{i}"} for i in range(n)]

    def test_exact_boundary_two_fit(self, mocker):
        # cost/msg = 100 + overhead. budget == 2 messages exactly -> keep 2.
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        budget = 2 * (100 + self.OVERHEAD)
        result = LLMDispatchService._trim_messages_to_token_budget(self._msgs(5), budget)
        assert [m["content"] for m in result] == ["m3", "m4"]

    def test_one_under_boundary_drops_to_one(self, mocker):
        # One token under the two-message cost -> only the newest survives.
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        budget = 2 * (100 + self.OVERHEAD) - 1
        result = LLMDispatchService._trim_messages_to_token_budget(self._msgs(5), budget)
        assert [m["content"] for m in result] == ["m4"]

    def test_budget_zero_keeps_newest_whole_no_warning(self, mocker, caplog):
        # budget <= 0 is the misconfig case (warned where the budget is computed); the trim
        # primitive keeps the newest WHOLE and does NOT re-warn.
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        with caplog.at_level("WARNING"):
            result = LLMDispatchService._trim_messages_to_token_budget(self._msgs(4), 0)
        assert [m["content"] for m in result] == ["m3"]
        assert not caplog.records

    def test_budget_negative_keeps_newest_whole_no_warning(self, mocker, caplog):
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        with caplog.at_level("WARNING"):
            result = LLMDispatchService._trim_messages_to_token_budget(self._msgs(4), -500)
        assert [m["content"] for m in result] == ["m3"]
        assert not caplog.records

    def test_oversized_single_message_preserved_byte_for_byte(self):
        # Real estimator, realistic content (code, braces, unicode, newlines) far over budget.
        content = ("def f(x):\n    return {'a': x}  # café ☕\n" * 50)
        result = LLMDispatchService._trim_messages_to_token_budget([{"role": "user", "content": content}], 50)
        assert len(result) == 1
        assert result[0]["content"] == content  # not one character chopped

    def test_oversized_single_message_warns_exactly_once(self, caplog):
        content = " ".join(f"w{i}" for i in range(800))
        with caplog.at_level("WARNING"):
            LLMDispatchService._trim_messages_to_token_budget([{"role": "user", "content": content}], 100)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "single most-recent" in warnings[0].message

    def test_normal_oldest_drop_does_not_warn(self, mocker, caplog):
        # Dropping whole oldest messages (the common case) is reported at the dispatch INFO
        # layer, NOT as a WARNING from the primitive.
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        with caplog.at_level("WARNING"):
            LLMDispatchService._trim_messages_to_token_budget(self._msgs(5), 2 * (100 + self.OVERHEAD))
        assert not caplog.records

    def test_none_and_empty_content_do_not_crash(self):
        # Real estimator; tool-call assistants (content=None) and empty strings must be safe.
        messages = [{"role": "assistant", "content": None}, {"role": "user", "content": ""},
                    {"role": "tool", "content": "result"}, {"role": "user", "content": "go"}]
        result = LLMDispatchService._trim_messages_to_token_budget(messages, 100000)
        assert [m.get("content") for m in result] == [None, "", "result", "go"]

    def test_overhead_makes_borderline_message_not_fit(self, mocker):
        # A message whose CONTENT estimate equals the budget still does not fit once the
        # per-message framing overhead is added -> it is the lone (oversized) survivor.
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        result = LLMDispatchService._trim_messages_to_token_budget(self._msgs(3), 100)
        assert [m["content"] for m in result] == ["m2"]  # 100 content + 8 overhead > 100

    def test_returns_new_list_not_mutating_input(self, mocker):
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        original = self._msgs(5)
        snapshot = list(original)
        LLMDispatchService._trim_messages_to_token_budget(original, 2 * (100 + self.OVERHEAD))
        assert original == snapshot  # input list untouched

    def test_chat_clamp_preserves_system_and_trims_only_body_at_boundary(self, mocker):
        # Adversarial integration: system message must survive even at a tight budget that
        # drops most of the body; never content-truncated.
        mocker.patch('Middleware.services.llm_dispatch_service.rough_estimate_token_length', return_value=100)
        collection = [{"role": "system", "content": "SYSTEM RULES"}] + self._msgs(6)
        LLMDispatchService._clamp_chat_collection_to_budget(collection, 2 * (100 + self.OVERHEAD))
        assert collection[0] == {"role": "system", "content": "SYSTEM RULES"}
        assert [m["content"] for m in collection[1:]] == ["m4", "m5"]
