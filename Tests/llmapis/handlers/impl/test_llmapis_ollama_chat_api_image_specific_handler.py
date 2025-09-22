# Tests/llmapis/handlers/impl/test_ollama_chat_api_image_specific_handler.py

import pytest

from Middleware.llmapis.handlers.impl.ollama_chat_api_image_specific_handler import OllamaApiChatImageSpecificHandler


@pytest.fixture
def handler() -> OllamaApiChatImageSpecificHandler:
    """
    Provides a default instance of OllamaApiChatImageSpecificHandler for testing.
    This fixture simplifies test setup by providing a pre-configured handler
    with mock configuration data, reducing code duplication across tests.
    """
    return OllamaApiChatImageSpecificHandler(
        base_url="http://mock-ollama:11434",
        api_key="",
        gen_input={"temperature": 0.7, "top_k": 40},
        model_name="llava-mock",
        headers={"Content-Type": "application/json"},
        stream=False,
        api_type_config={"type": "ollamaApiChatImageSpecific"},
        endpoint_config={},
        max_tokens=512,
        dont_include_model=False
    )


class TestBuildMessagesFromConversation:
    """
    Tests the core logic of the _build_messages_from_conversation method,
    which is responsible for formatting conversations with image data.
    """

    def test_with_single_image(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Verifies that a single image message is correctly processed and attached
        to the last user message in the conversation.
        """
        # Arrange
        conversation = [
            {"role": "user", "content": "Hello there."},
            {"role": "images", "content": "base64_string_of_a_cat"},
            {"role": "user", "content": "Please describe this image."}
        ]

        # Act
        result = handler._build_messages_from_conversation(conversation, None, None)

        # Assert
        assert len(result) == 2, "Should remove the 'images' role message"
        assert not any(msg["role"] == "images" for msg in result)

        last_user_msg = result[1]
        assert last_user_msg["role"] == "user"
        assert last_user_msg["content"] == "Please describe this image."
        assert "images" in last_user_msg, "Image data should be attached to the last user message"
        assert last_user_msg["images"] == ["base64_string_of_a_cat"]
        assert "images" not in result[0], "Image data should not be attached to earlier messages"

    def test_with_multiple_images(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Ensures that content from multiple 'images' messages is collected and
        attached to the last user message in the correct order.
        """
        # Arrange
        conversation = [
            {"role": "images", "content": "base64_string_1"},
            {"role": "user", "content": "This is the first image."},
            {"role": "assistant", "content": "Got it."},
            {"role": "images", "content": "base64_string_2"},
            {"role": "user", "content": "And this is the second. What are they?"}
        ]

        # Act
        result = handler._build_messages_from_conversation(conversation, None, None)

        # Assert
        assert len(result) == 3, "Should contain 2 user messages and 1 assistant message"

        last_user_msg = result[2]
        assert last_user_msg["role"] == "user"
        assert "images" in last_user_msg
        assert last_user_msg["images"] == ["base64_string_1", "base64_string_2"], "Should contain both image strings"

    def test_with_no_images(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Verifies that a conversation without any image messages is returned unmodified.
        """
        # Arrange
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi, how can I help you?"}
        ]

        # Act
        result = handler._build_messages_from_conversation(list(conversation), None, None)

        # Assert
        assert result == conversation, "Conversation should be unchanged"
        assert not any("images" in msg for msg in result)

    def test_with_image_but_no_user_message(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Tests that if an image message exists but there is no user message,
        the image message is simply removed without being attached anywhere.
        """
        # Arrange
        conversation = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "images", "content": "base64_string_no_user"}
        ]

        # Act
        result = handler._build_messages_from_conversation(conversation, None, None)

        # Assert
        assert len(result) == 1
        assert result[0]["role"] == "system"
        assert not any("images" in msg for msg in result), "Image content should not be present"

    def test_removes_empty_final_assistant_message(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Ensures that if the last message is from the assistant and has empty content,
        it is removed from the conversation.
        """
        # Arrange
        conversation = [
            {"role": "user", "content": "Tell me a joke."},
            {"role": "assistant", "content": ""}
        ]

        # Act
        result = handler._build_messages_from_conversation(conversation, None, None)

        # Assert
        assert len(result) == 1, "Empty assistant message should be popped"
        assert result[0]["role"] == "user"

    def test_keeps_non_empty_final_assistant_message(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Verifies that a final assistant message with content is not removed.
        """
        # Arrange
        conversation = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"}
        ]

        # Act
        result = handler._build_messages_from_conversation(list(conversation), None, None)

        # Assert
        assert len(result) == 2
        assert result == conversation

    def test_corrects_systemMes_role(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Tests that the legacy role 'systemMes' is correctly converted to 'system'.
        """
        # Arrange
        conversation = [
            {"role": "systemMes", "content": "You are a bot."},
            {"role": "user", "content": "Hello bot."}
        ]

        # Act
        result = handler._build_messages_from_conversation(conversation, None, None)

        # Assert
        assert len(result) == 2
        assert result[0]["role"] == "system", "Role should be corrected to 'system'"
        assert result[0]["content"] == "You are a bot."

    def test_builds_from_prompts_when_conversation_is_none(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Checks that a new conversation is correctly initialized from system and user
        prompts when the initial conversation list is None.
        """
        # Arrange
        system_prompt = "You are a helpful system."
        prompt = "This is the user's first message."

        # Act
        result = handler._build_messages_from_conversation(None, system_prompt, prompt)

        # Assert
        expected = [
            {"role": "system", "content": "You are a helpful system."},
            {"role": "user", "content": "This is the user's first message."}
        ]
        assert result == expected


class TestPayloadIntegration:
    """
    Tests the integration between the overridden _build_messages_from_conversation
    and the inherited _prepare_payload method to ensure the final payload is correct.
    """

    def test_prepare_payload_integrates_image_data_correctly(self, handler: OllamaApiChatImageSpecificHandler):
        """
        Verifies that calling _prepare_payload on the image-specific handler
        results in a final payload dictionary that correctly includes the image data
        in the 'messages' list, formatted for the Ollama API.
        """
        # Arrange
        conversation = [
            {"role": "system", "content": "You are a vision assistant."},
            {"role": "user", "content": "What is in this picture?"},
            {"role": "images", "content": "base64_string_of_a_pig"}
        ]

        # Act
        payload = handler._prepare_payload(conversation, None, None)

        # Assert
        assert "model" in payload and payload["model"] == "llava-mock"
        assert "options" in payload and payload["options"]["temperature"] == 0.7
        assert "stream" in payload and payload["stream"] is False
        assert "messages" in payload

        messages = payload["messages"]
        assert len(messages) == 2, "Should contain system and user messages"

        system_msg, user_msg = messages[0], messages[1]

        assert system_msg["role"] == "system"
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "What is in this picture?"
        assert "images" in user_msg
        assert user_msg["images"] == ["base64_string_of_a_pig"]
