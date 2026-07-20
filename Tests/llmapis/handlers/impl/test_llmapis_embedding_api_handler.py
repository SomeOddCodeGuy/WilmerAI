# tests/llmapis/handlers/impl/test_llmapis_embedding_api_handler.py

from unittest.mock import patch

import pytest

from Middleware.llmapis.handlers.impl.embedding_api_handler import EmbeddingApiHandler


@pytest.fixture(autouse=True)
def mock_connect_timeout(mocker):
    # BaseApiTransport.__init__ resolves the connect timeout from the real
    # user config on disk; keep these tests hermetic.
    mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout",
                 return_value=30)


def make_handler(api_type="openAIEmbeddings", dont_include_model=False):
    return EmbeddingApiHandler(
        base_url="http://localhost:8000",
        api_key="test_key",
        headers={"Content-Type": "application/json"},
        api_type=api_type,
        model_name="test-embed-model",
        dont_include_model=dont_include_model,
    )


class TestEmbeddingApiHandlerConstruction:
    def test_rejects_non_embedding_api_type(self):
        with pytest.raises(ValueError, match="Unsupported embeddings API type"):
            make_handler(api_type="openAIChatCompletion")

    def test_openai_url(self):
        assert make_handler()._get_api_endpoint_url() == "http://localhost:8000/v1/embeddings"

    def test_ollama_url(self):
        handler = make_handler(api_type="ollamaEmbeddings")
        assert handler._get_api_endpoint_url() == "http://localhost:8000/api/embed"

    def test_trailing_slash_stripped(self):
        handler = EmbeddingApiHandler(
            base_url="http://localhost:8000/", api_key="", headers={},
            api_type="openAIEmbeddings", model_name="m")
        assert handler._get_api_endpoint_url() == "http://localhost:8000/v1/embeddings"


class TestEmbeddingApiHandlerPayload:
    def test_payload_includes_model_and_input(self):
        payload = make_handler()._prepare_payload(["a", "b"])
        assert payload == {"input": ["a", "b"], "model": "test-embed-model"}

    def test_payload_omits_model_when_configured(self):
        payload = make_handler(dont_include_model=True)._prepare_payload(["a"])
        assert payload == {"input": ["a"]}


class TestEmbeddingApiHandlerParsing:
    def test_parse_openai_shape_sorted_by_index(self):
        response = {"data": [
            {"index": 1, "embedding": [0.3, 0.4]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]}

        result = make_handler()._parse_response(response)

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_parse_ollama_shape(self):
        response = {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}

        result = make_handler(api_type="ollamaEmbeddings")._parse_response(response)

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_parse_openai_missing_data_raises(self):
        with pytest.raises(ValueError, match="missing 'data'"):
            make_handler()._parse_response({"error": "nope"})

    def test_parse_empty_vector_raises(self):
        with pytest.raises(ValueError, match="non-empty vectors"):
            make_handler()._parse_response({"data": [{"index": 0, "embedding": []}]})

    def test_parse_ollama_missing_embeddings_raises(self):
        with pytest.raises(ValueError, match="non-empty vectors"):
            make_handler(api_type="ollamaEmbeddings")._parse_response({"data": []})


class TestGetEmbeddings:
    def test_empty_input_returns_empty_without_request(self):
        handler = make_handler()
        with patch.object(handler, 'execute_non_streaming_post') as mock_post:
            assert handler.get_embeddings([]) == []
        mock_post.assert_not_called()

    def test_happy_path(self):
        handler = make_handler()
        response = {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        with patch.object(handler, 'execute_non_streaming_post', return_value=response) as mock_post:
            result = handler.get_embeddings(["hello"], request_id="req-1")

        assert result == [[0.1, 0.2]]
        mock_post.assert_called_once_with(
            "http://localhost:8000/v1/embeddings",
            {"input": ["hello"], "model": "test-embed-model"},
            request_id="req-1")

    def test_cancelled_request_returns_none(self):
        handler = make_handler()
        with patch.object(handler, 'execute_non_streaming_post', return_value=None):
            assert handler.get_embeddings(["hello"]) is None

    def test_count_mismatch_raises(self):
        handler = make_handler()
        response = {"data": [{"index": 0, "embedding": [0.1]}]}
        with patch.object(handler, 'execute_non_streaming_post', return_value=response):
            with pytest.raises(ValueError, match="count mismatch"):
                handler.get_embeddings(["a", "b"])


class TestFailFastTransportDefaults:
    """Embedding calls sit inline in memory search/write flows that degrade to
    keyword search on failure, so the handler must fail fast by default rather
    than inherit the LLM transport's multi-hour timeout and retry stack."""

    def test_defaults_to_suppressed_retries(self):
        handler = make_handler()
        assert handler.suppress_retries is True

    def test_defaults_to_short_read_timeout(self):
        handler = make_handler()
        assert handler.read_timeout == 120

    def test_non_streaming_post_uses_read_timeout(self, mocker):
        handler = make_handler()
        mock_post = mocker.patch.object(handler.session, "post")
        mock_post.return_value.json.return_value = {"data": []}

        handler.execute_non_streaming_post("http://localhost:8000/v1/embeddings", {})

        assert mock_post.call_args.kwargs["timeout"] == (30, 120)

    def test_failing_post_makes_exactly_one_attempt(self, mocker):
        """Behavioral pin for suppress_retries: a down endpoint gets one POST,
        not the LLM transport's manual retry loop."""
        import requests as requests_lib
        handler = make_handler()
        mock_post = mocker.patch.object(
            handler.session, "post",
            side_effect=requests_lib.exceptions.ConnectionError("down"))

        with pytest.raises(requests_lib.exceptions.ConnectionError):
            handler.execute_non_streaming_post("http://localhost:8000/v1/embeddings", {})

        assert mock_post.call_count == 1


class TestParseResponseContract:
    def test_non_object_response_raises_value_error(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            make_handler()._parse_response([[0.1, 0.2]])

    def test_non_dict_data_entries_raise_value_error(self):
        with pytest.raises(ValueError, match="malformed"):
            make_handler()._parse_response({"data": ["not-a-dict", "also-not"]})
