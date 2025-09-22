# tests/llmapis/test_llm_api.py

import json
from unittest.mock import mock_open, MagicMock

import pytest

from Middleware.llmapis.llm_api import LlmApiService

MOCK_ENDPOINT_CONFIG = {
    "endpoint": "http://localhost:1234",
    "apiKey": "test_api_key",
    "modelNameToSendToAPI": "test-model",
    "apiTypeConfigFileName": "openAIChatCompletion",
    "dontIncludeModel": False,
}

MOCK_API_TYPE_CONFIG = {
    "type": "openAIChatCompletion",
    "presetType": "OpenAI",
    "streamPropertyName": "stream",
    "maxNewTokensPropertyName": "max_tokens",
}

MOCK_PRESET_CONFIG = {"temperature": 0.7, "top_p": 0.9}

SUPPORTED_HANDLERS = [
    ("openAIChatCompletion", "OpenAiApiHandler"),
    ("koboldCppGenerate", "KoboldCppApiHandler"),
    ("koboldCppGenerateImageSpecific", "KoboldCppImageSpecificApiHandler"),
    ("openAIV1Completion", "OpenAiCompletionsApiHandler"),
    ("ollamaApiChat", "OllamaChatHandler"),
    ("ollamaApiGenerate", "OllamaGenerateApiHandler"),
    ("ollamaApiChatImageSpecific", "OllamaApiChatImageSpecificHandler"),
    ("openAIApiChatImageSpecific", "OpenAIApiChatImageSpecificHandler"),
]


@pytest.fixture
def mock_configs(mocker):
    """A pytest fixture to mock all configuration utility functions."""
    mocker.patch("Middleware.llmapis.llm_api.get_endpoint_config", return_value=MOCK_ENDPOINT_CONFIG)
    mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value=MOCK_API_TYPE_CONFIG)
    mocker.patch(
        "Middleware.llmapis.llm_api.get_openai_preset_path", return_value="/fake/path/to/preset.json"
    )
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch(
        "builtins.open", mock_open(read_data=json.dumps(MOCK_PRESET_CONFIG))
    )


class TestLlmApiService:
    """Test suite for the LlmApiService class."""

    def test_init_success(self, mock_configs, mocker):
        """
        Tests successful initialization of LlmApiService, verifying that all
        configurations are loaded and attributes are set correctly.
        """
        mock_create_handler = mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")

        service = LlmApiService(endpoint="test_endpoint", presetname="test_preset", max_tokens=512)

        assert service.max_tokens == 512
        assert service.endpoint_file == MOCK_ENDPOINT_CONFIG
        assert service.api_type_config == MOCK_API_TYPE_CONFIG
        assert service._gen_input == MOCK_PRESET_CONFIG
        assert service.api_key == "test_api_key"
        assert service.endpoint_url == "http://localhost:1234"
        assert service.model_name == "test-model"
        assert service.llm_type == "openAIChatCompletion"
        mock_create_handler.assert_called_once()

    def test_init_preset_not_found_raises_error(self, mock_configs, mocker):
        """
        Tests that a FileNotFoundError is raised if the preset file does not exist,
        even after falling back to the non-user-specific path.
        """
        mocker.patch("os.path.exists", return_value=False)
        with pytest.raises(FileNotFoundError):
            LlmApiService(endpoint="test_endpoint", presetname="non_existent_preset", max_tokens=128)

    @pytest.mark.parametrize("llm_type, handler_class_name", SUPPORTED_HANDLERS)
    def test_create_api_handler_factory(self, llm_type, handler_class_name, mocker):
        """
        Tests the factory method `create_api_handler` to ensure it instantiates
        the correct handler class for each supported `llm_type`.
        """
        mock_handler = mocker.patch(f"Middleware.llmapis.llm_api.{handler_class_name}")

        mock_endpoint_config = MOCK_ENDPOINT_CONFIG.copy()
        mock_api_type_config = MOCK_API_TYPE_CONFIG.copy()
        mock_api_type_config["type"] = llm_type

        mocker.patch("Middleware.llmapis.llm_api.get_endpoint_config", return_value=mock_endpoint_config)
        mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value=mock_api_type_config)
        mocker.patch("Middleware.llmapis.llm_api.get_openai_preset_path", return_value="/fake/preset.json")
        mocker.patch("os.path.exists", return_value=True)
        mocker.patch("builtins.open", mock_open(read_data=json.dumps(MOCK_PRESET_CONFIG)))

        LlmApiService(endpoint="test", presetname="test", max_tokens=100)

        mock_handler.assert_called_once()

    def test_create_api_handler_unsupported_type_raises_error(self, mock_configs, mocker):
        """
        Tests that a ValueError is raised when an unsupported `llm_type` is provided.
        """
        mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value={"type": "unsupported_type"})

        with pytest.raises(ValueError, match="Unsupported LLM type: unsupported_type"):
            LlmApiService(endpoint="test", presetname="test", max_tokens=100)

    def test_get_response_from_llm_non_streaming(self, mock_configs, mocker):
        """
        Tests the non-streaming path of get_response_from_llm.
        """
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
        service = LlmApiService(endpoint="test", presetname="test", max_tokens=128, stream=False)

        mock_handler_instance = MagicMock()
        mock_handler_instance.handle_non_streaming.return_value = "Test response"
        service._api_handler = mock_handler_instance

        response = service.get_response_from_llm(prompt="Hello")

        assert response == "Test response"
        mock_handler_instance.handle_non_streaming.assert_called_once()
        assert service.is_busy() is False

    def test_get_response_from_llm_streaming(self, mock_configs, mocker):
        """
        Tests the streaming path of get_response_from_llm.
        """
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
        service = LlmApiService(endpoint="test", presetname="test", max_tokens=128, stream=True)

        def mock_stream_generator():
            yield {"token": "Hello"}
            yield {"token": " World"}

        mock_handler_instance = MagicMock()
        mock_handler_instance.handle_streaming.return_value = mock_stream_generator()
        service._api_handler = mock_handler_instance

        response_generator = service.get_response_from_llm(prompt="Hello")

        assert service.is_busy() is True

        result = list(response_generator)

        assert result == [{"token": "Hello"}, {"token": " World"}]
        mock_handler_instance.handle_streaming.assert_called_once()
        assert service.is_busy() is False

    def test_prompt_manipulation(self, mock_configs, mocker):
        """
        Tests that prompts are correctly modified based on endpoint configuration.
        """
        endpoint_config = {
            **MOCK_ENDPOINT_CONFIG,
            "addTextToStartOfSystem": True,
            "textToAddToStartOfSystem": "[SYSTEM] ",
            "addTextToStartOfPrompt": True,
            "textToAddToStartOfPrompt": "[USER] ",
        }
        mocker.patch("Middleware.llmapis.llm_api.get_endpoint_config", return_value=endpoint_config)
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")

        service = LlmApiService(endpoint="test", presetname="test", max_tokens=128, stream=False)
        mock_handler_instance = MagicMock()
        service._api_handler = mock_handler_instance

        service.get_response_from_llm(system_prompt="Be helpful.", prompt="Say hi.")

        call_args = mock_handler_instance.handle_non_streaming.call_args
        assert call_args.kwargs['system_prompt'] == "[SYSTEM] Be helpful."
        assert call_args.kwargs['prompt'] == "[USER] Say hi."

    def test_image_removal_when_llm_takes_no_images(self, mock_configs, mocker):
        """
        Tests that image messages are removed from the conversation when the
        `llm_takes_images` flag is False.
        """
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
        service = LlmApiService(endpoint="test", presetname="test", max_tokens=128)
        mock_handler_instance = MagicMock()
        service._api_handler = mock_handler_instance

        original_conversation = [
            {"role": "user", "content": "What is this?"},
            {"role": "images", "content": "base64-string"},
            {"role": "assistant", "content": "That is a cat."},
        ]

        service.get_response_from_llm(conversation=original_conversation, llm_takes_images=False)

        passed_conversation = mock_handler_instance.handle_non_streaming.call_args.kwargs['conversation']
        assert len(passed_conversation) == 2
        assert all(msg['role'] != 'images' for msg in passed_conversation)

        assert len(original_conversation) == 3

    def test_get_response_from_llm_handles_exceptions(self, mock_configs, mocker):
        """
        Tests that exceptions from the handler are caught, the busy flag is reset,
        and the exception is re-raised.
        """
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
        service = LlmApiService(endpoint="test", presetname="test", max_tokens=128)
        mock_handler_instance = MagicMock()
        mock_handler_instance.handle_non_streaming.side_effect = ValueError("API Error")
        service._api_handler = mock_handler_instance

        assert service.is_busy() is False
        with pytest.raises(ValueError, match="API Error"):
            service.get_response_from_llm(prompt="Hello")

        assert service.is_busy() is False

    def test_is_busy_flag(self, mock_configs, mocker):
        """
        Tests the is_busy() method reflects the internal state.
        """
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
        service = LlmApiService(endpoint="test", presetname="test", max_tokens=128)

        assert service.is_busy() is False
        service.is_busy_flag = True
        assert service.is_busy() is True
