# tests/services/test_embedding_service.py

import pytest

from Middleware.services.embedding_service import EmbeddingService


@pytest.fixture(autouse=True)
def mock_connect_timeout(mocker):
    # BaseApiTransport.__init__ resolves the connect timeout from the real
    # user config on disk; keep these tests hermetic.
    mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout",
                 return_value=30)


@pytest.fixture
def mock_configs(mocker):
    """Mocks the endpoint and ApiType config loaders with a valid embeddings setup."""
    mocker.patch('Middleware.services.embedding_service.get_endpoint_config', return_value={
        "endpoint": "http://localhost:8000",
        "apiTypeConfigFileName": "OpenAI-Embeddings",
        "modelNameToSendToAPI": "nomic-embed-text",
        "apiKey": "secret",
    })
    mocker.patch('Middleware.services.embedding_service.get_api_type_config', return_value={
        "type": "openAIEmbeddings",
    })


class TestEmbeddingServiceInit:
    def test_valid_embeddings_endpoint(self, mock_configs):
        service = EmbeddingService("Embedding-Endpoint")

        assert service.model_name == "nomic-embed-text"
        assert service.endpoint_name == "Embedding-Endpoint"
        assert service._handler.base_url == "http://localhost:8000"
        assert service._handler.headers["Authorization"] == "Bearer secret"

    def test_generation_api_type_rejected(self, mocker):
        mocker.patch('Middleware.services.embedding_service.get_endpoint_config', return_value={
            "endpoint": "http://localhost:8000",
            "apiTypeConfigFileName": "LlamaCppServer",
        })
        mocker.patch('Middleware.services.embedding_service.get_api_type_config', return_value={
            "type": "openAIChatCompletion",
        })

        with pytest.raises(ValueError, match="not an embeddings type"):
            EmbeddingService("Fast-Endpoint")

    def test_ollama_embeddings_type_accepted(self, mocker):
        """Both members of EMBEDDING_API_TYPES must be usable; only the OpenAI
        shape was previously pinned."""
        mocker.patch('Middleware.services.embedding_service.get_endpoint_config', return_value={
            "endpoint": "http://localhost:11434",
            "apiTypeConfigFileName": "Ollama-Embeddings",
            "modelNameToSendToAPI": "nomic-embed-text",
        })
        mocker.patch('Middleware.services.embedding_service.get_api_type_config', return_value={
            "type": "ollamaEmbeddings",
        })

        service = EmbeddingService("Ollama-Embedding-Endpoint")

        assert service._handler.api_type == "ollamaEmbeddings"
        assert service.model_name == "nomic-embed-text"

    def test_dont_include_model_forwarded_to_handler(self, mocker):
        """dontIncludeModel in the endpoint config must reach the handler; some
        servers reject payloads that include a model name."""
        mocker.patch('Middleware.services.embedding_service.get_endpoint_config', return_value={
            "endpoint": "http://localhost:8000",
            "apiTypeConfigFileName": "OpenAI-Embeddings",
            "modelNameToSendToAPI": "nomic-embed-text",
            "dontIncludeModel": True,
        })
        mocker.patch('Middleware.services.embedding_service.get_api_type_config', return_value={
            "type": "openAIEmbeddings",
        })

        service = EmbeddingService("Embedding-Endpoint")

        assert service._handler.dont_include_model is True

    def test_missing_model_name_defaults_to_empty_string(self, mocker):
        """model_name feeds the memory_embeddings 'model' column; when the
        config omits modelNameToSendToAPI it must default to '' (a stable key),
        not raise."""
        mocker.patch('Middleware.services.embedding_service.get_endpoint_config', return_value={
            "endpoint": "http://localhost:8000",
            "apiTypeConfigFileName": "OpenAI-Embeddings",
        })
        mocker.patch('Middleware.services.embedding_service.get_api_type_config', return_value={
            "type": "openAIEmbeddings",
        })

        service = EmbeddingService("Embedding-Endpoint")

        assert service.model_name == ""


class TestEmbeddingServicePassthrough:
    def test_get_embeddings_delegates_to_handler(self, mock_configs, mocker):
        service = EmbeddingService("Embedding-Endpoint")
        mock_get = mocker.patch.object(service._handler, 'get_embeddings',
                                       return_value=[[0.1, 0.2]])

        result = service.get_embeddings(["hello"], request_id="req-9")

        mock_get.assert_called_once_with(["hello"], request_id="req-9")
        assert result == [[0.1, 0.2]]

    def test_close_delegates_to_handler(self, mock_configs, mocker):
        service = EmbeddingService("Embedding-Endpoint")
        mock_close = mocker.patch.object(service._handler, 'close')

        service.close()

        mock_close.assert_called_once()
