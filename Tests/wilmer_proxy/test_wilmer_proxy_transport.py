from unittest.mock import MagicMock

import pytest
import requests

from Middleware.wilmer_proxy.config import WilmerProxyUpstreamConfig
from Middleware.wilmer_proxy.transport import WilmerProxyTransport


def _upstream(mode="passthrough", api_key=""):
    return WilmerProxyUpstreamConfig(
        name="main",
        base_url="http://127.0.0.1:5060",
        authorization_mode=mode,
        api_key=api_key,
        forward_headers=("X-Idempotency-Key", "X-Trace-Id"),
        connect_timeout_seconds=2.5,
        read_timeout_seconds=90.0,
        verify_tls=False,
    )


def test_build_headers_passes_authorization_and_only_explicit_headers():
    headers = WilmerProxyTransport._build_headers(
        {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
            "Authorization": "Bearer client-key",
            "X-Idempotency-Key": "request-1",
            "X-Trace-Id": "trace-1",
            "X-Not-Allowed": "discard-me",
        },
        _upstream(),
    )

    assert headers == {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "text/event-stream",
        "Accept-Encoding": "identity",
        "Authorization": "Bearer client-key",
        "X-Idempotency-Key": "request-1",
        "X-Trace-Id": "trace-1",
    }


@pytest.mark.parametrize(
    ("mode", "api_key", "expected"),
    [
        ("configured", "upstream-key", "Bearer upstream-key"),
        ("omit", "", None),
    ],
)
def test_build_headers_applies_non_passthrough_authorization_modes(mode, api_key, expected):
    headers = WilmerProxyTransport._build_headers(
        {"Authorization": "Bearer client-key"},
        _upstream(mode, api_key),
    )

    assert headers.get("Authorization") == expected


def test_open_request_disables_implicit_environment_redirects_and_retries(mocker):
    response = MagicMock()
    session = MagicMock()
    session.request.return_value = response
    session_factory = mocker.patch(
        "Middleware.wilmer_proxy.transport.requests.Session", return_value=session)

    opened_session, opened_response = WilmerProxyTransport().open_request(
        method="POST",
        path="/v1/chat/completions",
        body=b'{"model":"chat-ui:general"}',
        incoming_headers={"Authorization": "Bearer client-key"},
        upstream=_upstream(),
    )

    session_factory.assert_called_once_with()
    assert session.trust_env is False
    session.request.assert_called_once_with(
        method="POST",
        url="http://127.0.0.1:5060/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": "Bearer client-key",
        },
        data=b'{"model":"chat-ui:general"}',
        stream=True,
        allow_redirects=False,
        timeout=(2.5, 90.0),
        verify=False,
    )
    assert opened_session is session
    assert opened_response is response


def test_open_request_closes_session_when_connection_fails(mocker):
    session = MagicMock()
    session.request.side_effect = requests.ConnectionError("unavailable")
    mocker.patch(
        "Middleware.wilmer_proxy.transport.requests.Session", return_value=session)

    with pytest.raises(requests.ConnectionError):
        WilmerProxyTransport().open_request(
            method="POST",
            path="/v1/completions",
            body=b"{}",
            incoming_headers={},
            upstream=_upstream(),
        )

    session.close.assert_called_once_with()
