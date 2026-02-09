# tests/llmapis/handlers/base/test_base_llm_api_handler_cancellation.py

import pytest
from unittest.mock import MagicMock, patch, Mock
from io import StringIO

from Middleware.llmapis.handlers.base.base_llm_api_handler import LlmApiHandler
from Middleware.services.cancellation_service import cancellation_service


class MockLlmApiHandler(LlmApiHandler):
    """Concrete implementation of LlmApiHandler for testing."""

    def _get_api_endpoint_url(self) -> str:
        return "http://localhost:8000/api/test"

    def _prepare_payload(self, conversation, system_prompt, prompt):
        return {"prompt": prompt or "test", "stream": self.stream}

    def _process_stream_data(self, data_str: str):
        if data_str == '{"done": true}':
            return {"token": "", "finish_reason": "stop"}
        return {"token": data_str, "finish_reason": None}

    def _parse_non_stream_response(self, response_json):
        return response_json.get("text", "")


@pytest.fixture
def setup_cancellation_service():
    """Clear cancellation service before each test."""
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)
    yield
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)


@pytest.fixture
def mock_handler():
    """Create a mock LLM API handler for testing."""
    handler = MockLlmApiHandler(
        base_url="http://localhost:8000",
        api_key="test_key",
        gen_input={},
        model_name="test_model",
        headers={"Content-Type": "application/json"},
        stream=True,
        api_type_config={},
        endpoint_config={},
        max_tokens=100
    )
    return handler


class TestBaseLlmApiHandlerCancellation:
    """Test suite for LLM API handler cancellation integration."""

    @patch('requests.Session.post')
    def test_streaming_cancellation_during_iteration(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that cancellation stops the LLM stream during iteration."""
        request_id = "test_llm_stream_123"

        # Mock streaming response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        # Create a generator that yields several lines
        def mock_iter_lines(decode_unicode=True):
            import time
            yield "data: chunk1"
            time.sleep(0.05)  # Small delay to ensure chunk1 is processed
            yield "data: chunk2"
            time.sleep(0.05)  # Small delay to ensure chunk2 is processed
            # Cancel after second chunk
            cancellation_service.request_cancellation(request_id)
            time.sleep(0.05)  # Give time for cancellation to be detected
            yield "data: chunk3"  # This should not be processed
            yield "data: chunk4"

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        # Collect streaming results
        results = []
        for chunk in mock_handler.handle_streaming(prompt="test", request_id=request_id):
            results.append(chunk)

        # Should only get first two chunks before cancellation
        assert len(results) == 2
        assert results[0]['token'] == 'chunk1'
        assert results[1]['token'] == 'chunk2'

    @patch('requests.Session.post')
    def test_streaming_no_cancellation_completes_normally(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that streaming without cancellation processes all chunks."""
        request_id = "test_llm_stream_456"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            yield "data: chunk2"
            yield "data: chunk3"
            yield 'data: {"done": true}'

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = []
        for chunk in mock_handler.handle_streaming(prompt="test", request_id=request_id):
            results.append(chunk)

        # Should get all chunks
        assert len(results) == 4

    @patch('requests.Session.post')
    def test_streaming_cancellation_different_request_id(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that cancelling a different request ID doesn't affect this stream."""
        request_id = "test_llm_stream_789"
        other_request_id = "different_request_999"

        # Cancel a different request
        cancellation_service.request_cancellation(other_request_id)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            yield "data: chunk2"
            yield "data: chunk3"

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = []
        for chunk in mock_handler.handle_streaming(prompt="test", request_id=request_id):
            results.append(chunk)

        # Should get all chunks since our request wasn't cancelled
        assert len(results) == 3

    @patch('requests.Session.post')
    def test_streaming_cancellation_before_start(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that pre-cancelled request stops immediately."""
        request_id = "test_llm_precancel_123"

        # Cancel before starting
        cancellation_service.request_cancellation(request_id)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            yield "data: chunk2"

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = []
        for chunk in mock_handler.handle_streaming(prompt="test", request_id=request_id):
            results.append(chunk)

        # Should get no chunks since it was cancelled before the first line
        assert len(results) == 0

    @patch('requests.Session.post')
    def test_streaming_without_request_id(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that streaming without request_id works normally (no cancellation check)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            yield "data: chunk2"

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = []
        # Call without request_id
        for chunk in mock_handler.handle_streaming(prompt="test"):
            results.append(chunk)

        # Should get all chunks
        assert len(results) == 2

    @patch('requests.Session.post')
    @patch('Middleware.llmapis.handlers.base.base_llm_api_handler.logger')
    def test_streaming_cancellation_logs_info(self, mock_logger, mock_post, mock_handler, setup_cancellation_service):
        """Test that cancellation logs an info message."""
        request_id = "test_llm_logging_123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            cancellation_service.request_cancellation(request_id)
            yield "data: chunk2"

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        list(mock_handler.handle_streaming(prompt="test", request_id=request_id))

        # Verify info log was called
        mock_logger.info.assert_called()
        log_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any('cancelled' in call.lower() and request_id in call for call in log_calls)

    @patch('requests.Session.post')
    def test_streaming_sse_format_with_cancellation(self, mock_post, mock_handler, setup_cancellation_service):
        """Test cancellation works with SSE format (data: prefix)."""
        request_id = "test_llm_sse_123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            import time
            yield ""  # Empty line (should be skipped)
            yield "data: chunk1"
            time.sleep(0.05)  # Small delay to ensure chunk1 is processed
            yield ""
            cancellation_service.request_cancellation(request_id)
            time.sleep(0.05)  # Give time for cancellation to be detected
            yield "data: chunk2"  # Should not be processed

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = []
        for chunk in mock_handler.handle_streaming(prompt="test", request_id=request_id):
            results.append(chunk)

        # Should only get first chunk
        assert len(results) == 1
        assert results[0]['token'] == 'chunk1'


class TestBaseLlmApiHandlerSessionCleanup:
    """Test suite for LLM API handler session cleanup."""

    def test_close_method_closes_session(self, mock_handler):
        """Tests that close() closes the underlying requests session."""
        mock_session = MagicMock()
        mock_handler.session = mock_session

        mock_handler.close()

        mock_session.close.assert_called_once()

    def test_close_method_swallows_exceptions(self, mock_handler):
        """Tests that close() does not raise exceptions if session.close() fails."""
        mock_session = MagicMock()
        mock_session.close.side_effect = Exception("Connection error")
        mock_handler.session = mock_session

        # Should not raise
        mock_handler.close()

        mock_session.close.assert_called_once()

    @patch('Middleware.llmapis.handlers.base.base_llm_api_handler.get_connect_timeout', return_value=30)
    def test_connect_timeout_is_loaded(self, mock_get_timeout):
        """Tests that connect_timeout is loaded from config on init."""
        handler = MockLlmApiHandler(
            base_url="http://localhost:8000",
            api_key="test_key",
            gen_input={},
            model_name="test_model",
            headers={"Content-Type": "application/json"},
            stream=False,
            api_type_config={},
            endpoint_config={},
            max_tokens=100
        )
        assert handler.connect_timeout == 30

    @patch('Middleware.llmapis.handlers.base.base_llm_api_handler.get_connect_timeout', return_value=60)
    def test_connect_timeout_custom_value(self, mock_get_timeout):
        """Tests that a custom connect timeout value is used."""
        handler = MockLlmApiHandler(
            base_url="http://localhost:8000",
            api_key="test_key",
            gen_input={},
            model_name="test_model",
            headers={"Content-Type": "application/json"},
            stream=False,
            api_type_config={},
            endpoint_config={},
            max_tokens=100
        )
        assert handler.connect_timeout == 60

    @patch('requests.Session.post')
    @patch('Middleware.llmapis.handlers.base.base_llm_api_handler.get_connect_timeout', return_value=45)
    def test_streaming_post_uses_tuple_timeout(self, mock_timeout, mock_post, setup_cancellation_service):
        """Tests that streaming POST uses (connect_timeout, 14400) tuple."""
        handler = MockLlmApiHandler(
            base_url="http://localhost:8000",
            api_key="test_key",
            gen_input={},
            model_name="test_model",
            headers={"Content-Type": "application/json"},
            stream=True,
            api_type_config={},
            endpoint_config={},
            max_tokens=100
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"
        mock_response.iter_lines = lambda decode_unicode=True: iter(['data: {"done": true}'])
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        list(handler.handle_streaming(prompt="test"))

        # Verify the tuple timeout was passed
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get('timeout') == (45, 14400) or call_kwargs[1].get('timeout') == (45, 14400)

    @patch('requests.Session.post')
    @patch('Middleware.llmapis.handlers.base.base_llm_api_handler.get_connect_timeout', return_value=30)
    def test_non_streaming_post_uses_tuple_timeout(self, mock_timeout, mock_post, setup_cancellation_service):
        """Tests that non-streaming POST uses (connect_timeout, 14400) tuple."""
        handler = MockLlmApiHandler(
            base_url="http://localhost:8000",
            api_key="test_key",
            gen_input={},
            model_name="test_model",
            headers={"Content-Type": "application/json"},
            stream=False,
            api_type_config={},
            endpoint_config={},
            max_tokens=100
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "response"}
        mock_post.return_value = mock_response

        handler.handle_non_streaming(prompt="test")

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get('timeout') == (30, 14400) or call_kwargs[1].get('timeout') == (30, 14400)
