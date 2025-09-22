# Tests/services/test_llm_service.py

from unittest.mock import MagicMock, patch

import pytest

from Middleware.llmapis.llm_api import LlmApiService
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService

# Mock configuration data that would normally be loaded from JSON files.
MOCK_ENDPOINT_CONFIG = {
    "apiTypeConfigFileName": "TestApiType",
    "promptTemplate": "TestTemplate.json",
    "addGenerationPrompt": True
}

MOCK_ENDPOINT_CONFIG_NO_TEMPLATE = {
    "apiTypeConfigFileName": "TestApiType",
    "promptTemplate": None,
    "addGenerationPrompt": False
}

MOCK_API_TYPE_CONFIG = {
    "type": "openAIChatCompletion",
    "presetType": "OpenAI"
}


@pytest.fixture
def llm_handler_service():
    """Provides a LlmHandlerService instance for each test."""
    return LlmHandlerService()


# We patch all external dependencies: config utils, LlmApiService, and LlmHandler.
@patch('Middleware.services.llm_service.get_chat_template_name')
@patch('Middleware.services.llm_service.LlmHandler')
@patch('Middleware.services.llm_service.LlmApiService')
@patch('Middleware.services.llm_service.get_api_type_config')
def test_initialize_llm_handler_with_explicit_params(
        mock_get_api_type_config,
        mock_LlmApiService,
        mock_LlmHandler,
        mock_get_chat_template_name,
        llm_handler_service
):
    """
    Tests successful initialization of LlmHandler when all optional parameters
    are explicitly provided, ensuring they override config values.
    """
    # Arrange
    mock_get_api_type_config.return_value = MOCK_API_TYPE_CONFIG
    mock_llm_api_instance = MagicMock(spec=LlmApiService)
    mock_LlmApiService.return_value = mock_llm_api_instance
    mock_llm_handler_instance = MagicMock(spec=LlmHandler)
    mock_LlmHandler.return_value = mock_llm_handler_instance

    # Act
    result = llm_handler_service.initialize_llm_handler(
        config_data=MOCK_ENDPOINT_CONFIG,
        preset="test_preset",
        endpoint="test_endpoint",
        stream=True,
        truncate_length=2048,
        max_tokens=512,
        addGenerationPrompt=False
    )

    # Assert
    mock_get_api_type_config.assert_called_once_with("TestApiType")
    mock_LlmApiService.assert_called_once_with(
        endpoint="test_endpoint",
        presetname="test_preset",
        stream=True,
        max_tokens=512
    )
    mock_get_chat_template_name.assert_not_called()
    mock_LlmHandler.assert_called_once_with(
        mock_llm_api_instance,
        "TestTemplate.json",
        False,
        "openAIChatCompletion"
    )
    assert result == mock_llm_handler_instance


@patch('Middleware.services.llm_service.get_chat_template_name')
@patch('Middleware.services.llm_service.LlmHandler')
@patch('Middleware.services.llm_service.LlmApiService')
@patch('Middleware.services.llm_service.get_api_type_config')
def test_initialize_llm_handler_with_defaults(
        mock_get_api_type_config,
        mock_LlmApiService,
        mock_LlmHandler,
        mock_get_chat_template_name,
        llm_handler_service
):
    """
    Tests initialization using default values for addGenerationPrompt (from config)
    and prompt_template (from get_chat_template_name).
    """
    # Arrange
    mock_get_api_type_config.return_value = MOCK_API_TYPE_CONFIG
    mock_get_chat_template_name.return_value = "DefaultTemplate.json"
    mock_llm_api_instance = MagicMock(spec=LlmApiService)
    mock_LlmApiService.return_value = mock_llm_api_instance
    mock_llm_handler_instance = MagicMock(spec=LlmHandler)
    mock_LlmHandler.return_value = mock_llm_handler_instance

    # Act
    result = llm_handler_service.initialize_llm_handler(
        config_data=MOCK_ENDPOINT_CONFIG_NO_TEMPLATE,
        preset="test_preset",
        endpoint="test_endpoint",
        stream=False,
        truncate_length=4096,
        max_tokens=1024,
        addGenerationPrompt=None
    )

    # Assert
    mock_get_api_type_config.assert_called_once_with("TestApiType")
    mock_LlmApiService.assert_called_once_with(
        endpoint="test_endpoint",
        presetname="test_preset",
        stream=False,
        max_tokens=1024
    )
    mock_get_chat_template_name.assert_called_once()
    mock_LlmHandler.assert_called_once_with(
        mock_llm_api_instance,
        "DefaultTemplate.json",
        False,
        "openAIChatCompletion"
    )
    assert result == mock_llm_handler_instance


@patch('Middleware.services.llm_service.get_endpoint_config')
@patch.object(LlmHandlerService, 'initialize_llm_handler')
def test_load_model_from_config_success(
        mock_initialize_llm_handler,
        mock_get_endpoint_config,
        llm_handler_service
):
    """
    Tests that load_model_from_config successfully loads config and calls the initializer
    with the correct arguments.
    """
    # Arrange
    mock_get_endpoint_config.return_value = MOCK_ENDPOINT_CONFIG
    mock_handler_instance = MagicMock()
    mock_initialize_llm_handler.return_value = mock_handler_instance

    # Act
    result = llm_handler_service.load_model_from_config(
        config_name="test_config",
        preset="test_preset",
        stream=True,
        truncate_length=8192,
        max_tokens=123,
        addGenerationPrompt=True
    )

    # Assert
    mock_get_endpoint_config.assert_called_once_with("test_config")
    mock_initialize_llm_handler.assert_called_once_with(
        MOCK_ENDPOINT_CONFIG,
        "test_preset",
        "test_config",
        True,
        8192,
        123,
        True
    )
    assert result == mock_handler_instance


@patch('Middleware.services.llm_service.get_endpoint_config')
def test_load_model_from_config_file_not_found(
        mock_get_endpoint_config,
        llm_handler_service
):
    """
    Tests that load_model_from_config correctly propagates a FileNotFoundError
    if the configuration file cannot be loaded.
    """
    # Arrange
    mock_get_endpoint_config.side_effect = FileNotFoundError("Config file not found")

    # Act & Assert
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        llm_handler_service.load_model_from_config(
            config_name="non_existent_config",
            preset="any_preset"
        )
    mock_get_endpoint_config.assert_called_once_with("non_existent_config")
