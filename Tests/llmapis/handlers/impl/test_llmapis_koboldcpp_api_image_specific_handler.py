# Tests/llmapis/handlers/impl/test_koboldcpp_api_image_specific_handler.py

from copy import deepcopy

import pytest

from Middleware.llmapis.handlers.impl.koboldcpp_api_image_specific_handler import KoboldCppImageSpecificApiHandler

# Default arguments to initialize the handler for testing
BASE_ARGS = {
    "base_url": "http://localhost:5001",
    "api_key": "test_key",
    "model_name": "test-model",
    "headers": {"Content-Type": "application/json"},
    "stream": False,
    "api_type_config": {},
    "endpoint_config": {},
    "max_tokens": 128,
}


@pytest.fixture
def gen_input_fixture():
    """Provides a fresh copy of a base gen_input dictionary for each test."""
    return {
        "temperature": 0.7,
        "top_p": 0.9,
    }


@pytest.fixture
def handler_fixture(gen_input_fixture):
    """Provides a clean instance of the KoboldCppImageSpecificApiHandler for each test."""
    # Pass a deepcopy of gen_input to ensure test isolation
    return KoboldCppImageSpecificApiHandler(**BASE_ARGS, gen_input=deepcopy(gen_input_fixture))


def test_prepare_payload_with_image_data(handler_fixture, mocker):
    """
    Tests that _prepare_payload correctly extracts image data from the conversation
    and adds it to the gen_input dictionary before calling the parent method.
    """
    # Arrange
    mock_super_prepare = mocker.patch(
        'Middleware.llmapis.handlers.impl.koboldcpp_api_handler.KoboldCppApiHandler._prepare_payload',
        return_value={"prompt": "Test prompt", "temperature": 0.7}
    )

    conversation = [
        {"role": "user", "content": "Describe this image for me."},
        {"role": "images", "content": ["base64_string_1"]},
        {"role": "assistant", "content": "Certainly! What is it?"},
        {"role": "user", "content": "And this one too."},
        {"role": "images", "content": ["base64_string_2"]},
    ]
    system_prompt = "You are a helpful assistant."
    user_prompt = "Final prompt."

    # Act
    handler_fixture._prepare_payload(conversation, system_prompt, user_prompt)

    # Assert
    assert "images" in handler_fixture.gen_input
    assert handler_fixture.gen_input["images"] == [["base64_string_1"], ["base64_string_2"]]

    mock_super_prepare.assert_called_once_with(conversation, system_prompt, user_prompt)


def test_prepare_payload_without_image_data(handler_fixture, mocker, gen_input_fixture):
    """
    Tests that _prepare_payload does not modify gen_input when no image data
    is present in the conversation.
    """
    # Arrange
    mock_super_prepare = mocker.patch(
        'Middleware.llmapis.handlers.impl.koboldcpp_api_handler.KoboldCppApiHandler._prepare_payload',
        return_value={"prompt": "Test prompt"}
    )

    conversation = [
        {"role": "user", "content": "Hello there."},
        {"role": "assistant", "content": "Hi! How can I help?"}
    ]
    system_prompt = "System instructions."
    user_prompt = "A user question."

    # Act
    handler_fixture._prepare_payload(conversation, system_prompt, user_prompt)

    # Assert
    assert "images" not in handler_fixture.gen_input

    assert handler_fixture.gen_input == gen_input_fixture

    mock_super_prepare.assert_called_once_with(conversation, system_prompt, user_prompt)


def test_prepare_payload_with_empty_conversation(handler_fixture, mocker, gen_input_fixture):
    """
    Tests that _prepare_payload handles an empty conversation list gracefully.
    """
    # Arrange
    mock_super_prepare = mocker.patch(
        'Middleware.llmapis.handlers.impl.koboldcpp_api_handler.KoboldCppApiHandler._prepare_payload'
    )
    conversation = []
    system_prompt = "System instructions."
    user_prompt = "A user question."

    # Act
    handler_fixture._prepare_payload(conversation, system_prompt, user_prompt)

    # Assert
    assert "images" not in handler_fixture.gen_input
    assert handler_fixture.gen_input == gen_input_fixture
    mock_super_prepare.assert_called_once_with(conversation, system_prompt, user_prompt)


def test_prepare_payload_with_none_conversation(handler_fixture, mocker, gen_input_fixture):
    """
    Tests that _prepare_payload handles a None conversation object gracefully.
    """
    # Arrange
    mock_super_prepare = mocker.patch(
        'Middleware.llmapis.handlers.impl.koboldcpp_api_handler.KoboldCppApiHandler._prepare_payload'
    )
    conversation = None
    system_prompt = "System instructions."
    user_prompt = "A user question."

    # Act
    handler_fixture._prepare_payload(conversation, system_prompt, user_prompt)

    # Assert
    assert "images" not in handler_fixture.gen_input
    assert handler_fixture.gen_input == gen_input_fixture
    mock_super_prepare.assert_called_once_with(conversation, system_prompt, user_prompt)
