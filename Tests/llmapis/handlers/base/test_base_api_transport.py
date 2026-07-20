# Tests/llmapis/handlers/base/test_base_api_transport.py

"""
Direct unit tests for BaseApiTransport and _AbortHandle.

The transport was previously only exercised through LlmApiHandler, whose
handle_non_streaming pre-checks cancellation before delegating, so the
transport's OWN pre-flight cancellation branch (the live path for
EmbeddingApiHandler, which extends the transport directly) was never hit.
These tests pin the transport contract in isolation.
"""

from unittest.mock import MagicMock

import pytest
import requests

from Middleware.llmapis.handlers.base.base_api_transport import BaseApiTransport, _AbortHandle
from Middleware.services.cancellation_service import cancellation_service


@pytest.fixture
def setup_cancellation_service():
    """Clear cancellation service state before and after each test."""
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)
    yield
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)


@pytest.fixture
def transport():
    return BaseApiTransport(
        base_url="http://localhost:9000",
        api_key="k",
        headers={"Content-Type": "application/json"},
    )


class TestExecuteNonStreamingPost:
    def test_success_returns_parsed_json_body(self, transport, setup_cancellation_service, mocker):
        mock_response = MagicMock()
        mock_response.json.return_value = {"text": "hello"}
        mock_post = mocker.patch.object(transport.session, "post", return_value=mock_response)

        result = transport.execute_non_streaming_post(
            "http://localhost:9000/v1/x", {"prompt": "p"}, request_id=None)

        assert result == {"text": "hello"}
        mock_response.raise_for_status.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"] == {"prompt": "p"}
        assert call_kwargs["headers"] == {"Content-Type": "application/json"}
        # (connect_timeout, read_timeout) tuple: connect from the conftest-patched
        # config default (10), read from the transport default (14400).
        assert call_kwargs["timeout"] == (10, 14400)

    def test_preflight_cancellation_returns_none_without_posting(self, transport,
                                                                 setup_cancellation_service, mocker):
        """The transport's own pre-flight check (the EmbeddingApiHandler path):
        an already-cancelled request returns None, never POSTs, and closes the session."""
        request_id = "transport_precancel_1"
        cancellation_service.request_cancellation(request_id)

        mock_post = mocker.patch.object(transport.session, "post")
        mock_close = mocker.patch.object(transport.session, "close")

        result = transport.execute_non_streaming_post(
            "http://localhost:9000/v1/x", {}, request_id=request_id)

        assert result is None
        mock_post.assert_not_called()
        mock_close.assert_called_once()

    def test_http_error_status_is_retried_then_raised(self, transport,
                                                      setup_cancellation_service, mocker):
        """An HTTP error surfaced by raise_for_status (HTTPError is a
        RequestException) goes through the manual retry loop: 3 attempts, then
        the error propagates."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Client Error")
        mock_post = mocker.patch.object(transport.session, "post", return_value=mock_response)

        with pytest.raises(requests.exceptions.HTTPError, match="400 Client Error"):
            transport.execute_non_streaming_post("http://localhost:9000/v1/x", {})

        assert mock_post.call_count == 3

    def test_non_request_exception_raises_immediately_without_retry(self, transport,
                                                                    setup_cancellation_service, mocker):
        """A non-RequestException failure (here a broken json() parse raising a
        bare ValueError) is not retried: it propagates from the first attempt."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("not json")
        mock_post = mocker.patch.object(transport.session, "post", return_value=mock_response)

        with pytest.raises(ValueError, match="not json"):
            transport.execute_non_streaming_post("http://localhost:9000/v1/x", {})

        assert mock_post.call_count == 1

    def test_abort_callback_unregistered_after_each_attempt(self, transport,
                                                            setup_cancellation_service, mocker):
        """Each retry attempt registers a fresh abort callback and the finally
        block unregisters it, so a failed request leaves no dangling callback."""
        request_id = "transport_cb_lifecycle_1"
        mock_register = mocker.patch.object(cancellation_service, "register_abort_callback")
        mock_unregister = mocker.patch.object(cancellation_service, "unregister_abort_callbacks")
        mocker.patch.object(transport.session, "post",
                            side_effect=requests.exceptions.ConnectionError("down"))

        with pytest.raises(requests.exceptions.ConnectionError):
            transport.execute_non_streaming_post("http://x", {}, request_id=request_id)

        assert mock_register.call_count == 3
        assert mock_unregister.call_count == 3
        assert all(c.args[0] == request_id for c in mock_unregister.call_args_list)


class TestSuppressRetriesConstruction:
    def test_suppress_retries_zero_adapter_total_and_single_manual_attempt(self,
                                                                           setup_cancellation_service,
                                                                           mocker):
        transport = BaseApiTransport(base_url="http://x", api_key="k", headers={},
                                     suppress_retries=True)
        assert transport.session.get_adapter("http://x").max_retries.total == 0

        mock_post = mocker.patch.object(transport.session, "post",
                                        side_effect=requests.exceptions.ConnectionError("down"))
        with pytest.raises(requests.exceptions.ConnectionError):
            transport.execute_non_streaming_post("http://x", {})
        assert mock_post.call_count == 1

    def test_default_read_timeout_is_14400_and_overridable(self):
        assert BaseApiTransport(base_url="http://x", api_key="k", headers={}).read_timeout == 14400
        assert BaseApiTransport(base_url="http://x", api_key="k", headers={},
                                read_timeout=60).read_timeout == 60


class TestAbortHandle:
    def test_abort_closes_session_and_attached_response(self):
        mock_session = MagicMock()
        handle = _AbortHandle(mock_session, "req-1", "non-streaming")
        mock_response = MagicMock()
        handle.response = mock_response

        handle.abort()

        mock_session.adapters.clear.assert_called_once()
        mock_session.close.assert_called_once()
        mock_response.close.assert_called_once()
        # The response reference is dropped so a second abort cannot double-close it.
        assert handle.response is None

    def test_abort_without_attached_response_only_closes_session(self):
        mock_session = MagicMock()
        handle = _AbortHandle(mock_session, "req-2", "streaming")

        handle.abort()

        mock_session.close.assert_called_once()

    def test_abort_swallows_session_close_error_and_still_closes_response(self):
        """abort() runs on another greenlet/thread; it must never raise, and a
        session-close failure must not prevent the in-flight response from
        being closed."""
        mock_session = MagicMock()
        mock_session.close.side_effect = RuntimeError("already dead")
        handle = _AbortHandle(mock_session, "req-3", "non-streaming")
        mock_response = MagicMock()
        handle.response = mock_response

        handle.abort()  # must not raise

        mock_response.close.assert_called_once()
        assert handle.response is None

    def test_abort_swallows_response_close_error(self):
        mock_session = MagicMock()
        handle = _AbortHandle(mock_session, "req-4", "streaming")
        mock_response = MagicMock()
        mock_response.close.side_effect = RuntimeError("socket gone")
        handle.response = mock_response

        handle.abort()  # must not raise

        assert handle.response is None
