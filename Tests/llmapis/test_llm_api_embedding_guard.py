# tests/llmapis/test_llm_api_embedding_guard.py

import pytest

from Middleware.llmapis.llm_api import LlmApiService


class TestEmbeddingEndpointGuard:
    """LlmApiService must refuse embeddings endpoints with a clear error."""

    @pytest.mark.parametrize("embedding_type", ["openAIEmbeddings", "ollamaEmbeddings"])
    def test_generation_service_rejects_embeddings_endpoint(self, mocker, embedding_type):
        mocker.patch('Middleware.llmapis.llm_api.get_endpoint_config', return_value={
            "endpoint": "http://localhost:8000",
            "apiTypeConfigFileName": "SomeEmbeddings",
        })
        mocker.patch('Middleware.llmapis.llm_api.get_api_type_config', return_value={
            "type": embedding_type,
        })

        with pytest.raises(ValueError, match="cannot be used for text generation"):
            LlmApiService(endpoint="Embedding-Endpoint", presetname="anything", max_tokens=100)
