# tests/llmapis/handlers/base/test_base_llm_api_handler_cancellation.py

import pytest
import requests
from unittest.mock import MagicMock, patch, Mock
from io import StringIO

from Middleware.llmapis.handlers.base.base_llm_api_handler import LlmApiHandler
from Middleware.services.cancellation_service import cancellation_service


class MockLlmApiHandler(LlmApiHandler):
    """Concrete implementation of LlmApiHandler for testing."""

    def _get_api_endpoint_url(self) -> str:
        return "http://localhost:8000/api/test"

    def _prepare_payload(self, conversation, system_prompt, prompt, *, tools=None, tool_choice=None,
                         structured_output_schema=None):
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
            yield "data: chunk1"
            yield "data: chunk2"
            # Cancel after second chunk
            cancellation_service.request_cancellation(request_id)
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

        # Should get all chunks, in order, with the final one carrying the finish_reason
        assert results == [
            {"token": "chunk1", "finish_reason": None},
            {"token": "chunk2", "finish_reason": None},
            {"token": "chunk3", "finish_reason": None},
            {"token": "", "finish_reason": "stop"},
        ]

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
        # The POST should never have been issued for a pre-cancelled request
        mock_post.assert_not_called()

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
            yield ""  # Empty line (should be skipped)
            yield "data: chunk1"
            yield ""
            cancellation_service.request_cancellation(request_id)
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


class TestBaseLlmApiHandlerNonStreamingCancellation:
    """Test suite for cancellation behavior in handle_non_streaming."""

    @patch('requests.Session.post')
    def test_non_streaming_cancellation_before_start(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that a pre-cancelled request returns "" without issuing the POST."""
        request_id = "test_llm_nonstream_precancel_123"

        cancellation_service.request_cancellation(request_id)

        result = mock_handler.handle_non_streaming(prompt="test", request_id=request_id)

        assert result == ""
        mock_post.assert_not_called()

    def test_non_streaming_cancellation_before_retry(self, mock_handler, setup_cancellation_service, mocker):
        """
        Test that cancellation detected at the top of a retry iteration returns ""
        without issuing another POST.

        is_cancelled is called in this order: pre-check, attempt-1 loop top,
        attempt-1 except handler (after the POST fails), attempt-2 loop top.
        The side_effect sequence makes only the attempt-2 loop-top check report
        cancellation, exercising the cancel-before-retry branch.
        """
        request_id = "test_llm_nonstream_retry_cancel_123"

        mocker.patch.object(cancellation_service, 'is_cancelled',
                            side_effect=[False, False, False, True])
        mock_post = mocker.patch('requests.Session.post',
                                 side_effect=requests.exceptions.RequestException("Connection failed"))

        result = mock_handler.handle_non_streaming(prompt="test", request_id=request_id)

        assert result == ""
        # Only the first attempt's POST was made; the retry was cancelled before posting
        assert mock_post.call_count == 1

    @patch('requests.Session.post')
    def test_non_streaming_cancellation_during_request(self, mock_post, mock_handler, setup_cancellation_service):
        """
        Test that a request error caused by cancellation mid-flight returns ""
        instead of raising or retrying.
        """
        request_id = "test_llm_nonstream_midflight_123"

        def post_side_effect(*args, **kwargs):
            # Simulate the abort callback closing the connection mid-request
            cancellation_service.request_cancellation(request_id)
            raise requests.exceptions.RequestException("Connection aborted")

        mock_post.side_effect = post_side_effect

        result = mock_handler.handle_non_streaming(prompt="test", request_id=request_id)

        assert result == ""
        assert mock_post.call_count == 1


class TestNonStreamingRetryLoop:
    """Test suite for the manual retry loop in handle_non_streaming."""

    @patch('requests.Session.post')
    def test_retries_three_times_and_reraises_on_final_attempt(self, mock_post, mock_handler,
                                                               setup_cancellation_service):
        """Test that a persistent request error is retried 3 times, then re-raised."""
        mock_post.side_effect = requests.exceptions.RequestException("Connection failed")

        with pytest.raises(requests.exceptions.RequestException, match="Connection failed"):
            mock_handler.handle_non_streaming(prompt="test")

        assert mock_post.call_count == 3

    @patch('requests.Session.post')
    @patch('Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout', return_value=30)
    def test_suppress_retries_makes_single_attempt(self, mock_timeout, mock_post, setup_cancellation_service):
        """Test that suppress_retries=True shrinks the retry loop to a single attempt."""
        handler = MockLlmApiHandler(
            base_url="http://localhost:8000",
            api_key="test_key",
            gen_input={},
            model_name="test_model",
            headers={"Content-Type": "application/json"},
            stream=False,
            api_type_config={},
            endpoint_config={},
            max_tokens=100,
            suppress_retries=True
        )
        mock_post.side_effect = requests.exceptions.RequestException("Connection failed")

        with pytest.raises(requests.exceptions.RequestException, match="Connection failed"):
            handler.handle_non_streaming(prompt="test")

        assert mock_post.call_count == 1


class TestAbortCallbackLifecycle:
    """Test suite for abort callback registration, unregistration, and behavior."""

    def test_streaming_abort_callback_registered_and_unregistered(self, mock_handler,
                                                                  setup_cancellation_service, mocker):
        """
        Test that streaming registers an abort callback with the cancellation
        service, unregisters it in the finally block, and that invoking the
        captured callback closes the session.
        """
        request_id = "test_abort_lifecycle_stream_123"
        mock_register = mocker.patch.object(cancellation_service, 'register_abort_callback')
        mock_unregister = mocker.patch.object(cancellation_service, 'unregister_abort_callbacks')

        mock_session = MagicMock()
        mock_handler.session = mock_session
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"
        mock_response.iter_lines = lambda decode_unicode=True: iter(['data: {"done": true}'])
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_session.post.return_value = mock_response

        list(mock_handler.handle_streaming(prompt="test", request_id=request_id))

        mock_register.assert_called_once()
        assert mock_register.call_args[0][0] == request_id
        abort_callback = mock_register.call_args[0][1]
        assert callable(abort_callback)
        mock_unregister.assert_called_once_with(request_id)

        # Invoking the captured callback must aggressively close the session
        abort_callback()
        mock_session.close.assert_called_once()
        mock_session.adapters.clear.assert_called_once()

    def test_non_streaming_abort_callback_registered_and_unregistered(self, mock_handler,
                                                                      setup_cancellation_service, mocker):
        """
        Test that non-streaming registers an abort callback, unregisters it in the
        finally block, and that invoking the captured callback closes the session.
        """
        request_id = "test_abort_lifecycle_nonstream_123"
        mock_register = mocker.patch.object(cancellation_service, 'register_abort_callback')
        mock_unregister = mocker.patch.object(cancellation_service, 'unregister_abort_callbacks')

        mock_session = MagicMock()
        mock_handler.session = mock_session
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "response"}
        mock_session.post.return_value = mock_response

        result = mock_handler.handle_non_streaming(prompt="test", request_id=request_id)

        assert result == "response"
        mock_register.assert_called_once()
        assert mock_register.call_args[0][0] == request_id
        abort_callback = mock_register.call_args[0][1]
        assert callable(abort_callback)
        mock_unregister.assert_called_once_with(request_id)

        # Invoking the captured callback must aggressively close the session
        abort_callback()
        mock_session.close.assert_called_once()
        mock_session.adapters.clear.assert_called_once()


class TestHandleStreamingLineProcessing:
    """Test suite for targeted handle_streaming line-processing behavior."""

    @patch('requests.Session.post')
    def test_streaming_done_marker_skipped(self, mock_post, mock_handler, setup_cancellation_service):
        """Test that a 'data: [DONE]' line is skipped without being processed as data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            yield "data: [DONE]"
            yield "data: chunk2"

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = list(mock_handler.handle_streaming(prompt="test"))

        assert results == [
            {"token": "chunk1", "finish_reason": None},
            {"token": "chunk2", "finish_reason": None},
        ]

    @patch('requests.Session.post')
    @patch('Middleware.llmapis.handlers.base.base_llm_api_handler.logger')
    def test_streaming_http_error_captures_body_and_raises(self, mock_logger, mock_post,
                                                           mock_handler, setup_cancellation_service):
        """
        Test that an HTTP >= 400 response has its body captured and logged before
        raise_for_status propagates the error.
        """
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "upstream exploded"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        with pytest.raises(requests.exceptions.HTTPError):
            list(mock_handler.handle_streaming(prompt="test"))

        mock_response.raise_for_status.assert_called_once()
        error_logs = [str(call) for call in mock_logger.error.call_args_list]
        assert any("upstream exploded" in log for log in error_logs)


class MockLineDelimitedHandler(MockLlmApiHandler):
    """Handler variant using line-delimited JSON streaming (the Ollama protocol)."""

    @property
    def _iterate_by_lines(self):
        return True


class TestLineDelimitedStreaming:
    """The _iterate_by_lines=True branch of the base streaming loop: raw lines are
    passed to _process_stream_data whole, with no SSE 'data:' prefix handling."""

    @patch('requests.Session.post')
    def test_raw_lines_processed_without_sse_prefix(self, mock_post, setup_cancellation_service):
        handler = MockLineDelimitedHandler(
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

        def mock_iter_lines(decode_unicode=True):
            yield '{"chunk": 1}'
            yield ""  # blank line skipped
            yield '{"chunk": 2}'
            yield '{"done": true}'

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = list(handler.handle_streaming(prompt="test"))

        # Each raw line reaches _process_stream_data verbatim (no data: stripping),
        # blank lines are skipped, and the finish_reason chunk ends the stream.
        assert results == [
            {"token": '{"chunk": 1}', "finish_reason": None},
            {"token": '{"chunk": 2}', "finish_reason": None},
            {"token": "", "finish_reason": "stop"},
        ]

    @patch('requests.Session.post')
    def test_sse_prefixed_line_is_not_stripped_in_line_mode(self, mock_post, setup_cancellation_service):
        """In line mode a 'data:'-prefixed line is data, not an SSE frame: the
        prefix must be passed through to the parser untouched."""
        handler = MockLineDelimitedHandler(
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
        mock_response.iter_lines = lambda decode_unicode=True: iter(["data: not-sse"])
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = list(handler.handle_streaming(prompt="test"))

        assert results == [{"token": "data: not-sse", "finish_reason": None}]


class TestStreamingMidStreamErrors:
    """RequestException raised while iterating the stream body."""

    @patch('requests.Session.post')
    def test_midstream_error_after_cancellation_exits_gracefully(self, mock_post, mock_handler,
                                                                 setup_cancellation_service):
        """When the abort callback tears down the connection, iter_lines raises a
        network error; because the request is cancelled, the generator must end
        cleanly (tokens so far preserved) instead of raising."""
        request_id = "test_midstream_cancel_err_1"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            cancellation_service.request_cancellation(request_id)
            raise requests.exceptions.ConnectionError("connection torn down by abort")

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        results = list(mock_handler.handle_streaming(prompt="test", request_id=request_id))

        assert results == [{"token": "chunk1", "finish_reason": None}]

    @patch('requests.Session.post')
    def test_midstream_error_without_cancellation_raises(self, mock_post, mock_handler,
                                                         setup_cancellation_service):
        """The same network error with NO cancellation is a genuine failure and
        must propagate to the caller (this is what streaming failover keys on)."""
        request_id = "test_midstream_genuine_err_1"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.encoding = "utf-8"

        def mock_iter_lines(decode_unicode=True):
            yield "data: chunk1"
            raise requests.exceptions.ConnectionError("backend died")

        mock_response.iter_lines = mock_iter_lines
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_post.return_value = mock_response

        gen = mock_handler.handle_streaming(prompt="test", request_id=request_id)
        assert next(gen) == {"token": "chunk1", "finish_reason": None}
        with pytest.raises(requests.exceptions.ConnectionError, match="backend died"):
            next(gen)


class TestNonStreamingResultShapes:
    """handle_non_streaming's handling of the parser's return value."""

    @patch('requests.Session.post')
    def test_dict_result_passed_through_unchanged(self, mock_post, mock_handler,
                                                  setup_cancellation_service, mocker):
        """A tool-call response (dict with content/tool_calls/finish_reason) is
        returned as-is, not coerced to a string."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"raw": "body"}
        mock_post.return_value = mock_response

        tool_result = {
            "content": "calling",
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "calc", "arguments": "{}"}}],
            "finish_reason": "tool_calls",
        }
        mocker.patch.object(mock_handler, '_parse_non_stream_response', return_value=tool_result)

        result = mock_handler.handle_non_streaming(prompt="test")

        assert result is tool_result

    @patch('requests.Session.post')
    def test_none_result_becomes_empty_string(self, mock_post, mock_handler,
                                              setup_cancellation_service, mocker):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response
        mocker.patch.object(mock_handler, '_parse_non_stream_response', return_value=None)

        assert mock_handler.handle_non_streaming(prompt="test") == ""

    @patch('requests.Session.post')
    def test_parse_error_propagates(self, mock_post, mock_handler,
                                    setup_cancellation_service, mocker):
        """A parser bug or unexpected body shape must surface (it is what triggers
        failover upstream), not be swallowed into an empty response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"unexpected": "shape"}
        mock_post.return_value = mock_response
        mocker.patch.object(mock_handler, '_parse_non_stream_response',
                            side_effect=KeyError("choices"))

        with pytest.raises(KeyError):
            mock_handler.handle_non_streaming(prompt="test")


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

    @patch('Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout', return_value=30)
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

    @patch('Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout', return_value=60)
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
    @patch('Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout', return_value=45)
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
    @patch('Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout', return_value=30)
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
