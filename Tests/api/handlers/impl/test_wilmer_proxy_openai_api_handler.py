import json

import pytest
import requests
from flask import Flask

from Middleware.api.handlers.impl.wilmer_proxy_openai_api_handler import (
    WilmerProxyOpenAIApiHandler,
)
from Middleware.wilmer_proxy.config import (
    WilmerProxyConfig,
    WilmerProxyModelConfig,
    WilmerProxyUpstreamConfig,
)


class FakeSession:
    def __init__(self):
        self.close_count = 0

    def close(self):
        self.close_count += 1


@pytest.mark.parametrize("consume", [0, 1, 2])
def test_wsgi_close_owns_upstream_before_or_after_first_yield(consume):
    from werkzeug.test import EnvironBuilder

    handler = WilmerProxyOpenAIApiHandler.__new__(WilmerProxyOpenAIApiHandler)
    session = FakeSession()
    upstream = FakeUpstreamResponse(chunks=[b"one", b"two"])
    response = handler._relay_response(session, upstream, True)
    iterable = response(EnvironBuilder(method="POST").get_environ(), lambda *args: None)
    for _ in range(consume):
        next(iterable)
    iterable.close()
    iterable.close()
    assert session.close_count == upstream.close_count == 1
    assert upstream.iterated is (consume > 0)


def test_connection_nominated_response_headers_are_removed():
    upstream = FakeUpstreamResponse(headers={
        "cOnNeCtIoN": "keep-alive, X-Internal", "x-INTERNAL": "private", "X-Result": "public",
    })
    assert WilmerProxyOpenAIApiHandler._response_headers(upstream) == {"X-Result": "public"}


class FakeUpstreamResponse:
    def __init__(self, body=b"", status=200, headers=None, chunks=None):
        self.content = body
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}
        self._chunks = chunks or []
        self.close_count = 0
        self.iterated = False

    def iter_content(self, chunk_size):
        assert chunk_size == 16384
        self.iterated = True
        yield from self._chunks

    def close(self):
        self.close_count += 1


class RecordingTransport:
    def __init__(self, upstream_response=None, error=None):
        self.upstream_response = upstream_response or FakeUpstreamResponse()
        self.error = error
        self.calls = []
        self.sessions = []

    def open_request(self, **kwargs):
        kwargs["incoming_headers"] = dict(kwargs["incoming_headers"])
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        session = FakeSession()
        self.sessions.append(session)
        return session, self.upstream_response


def _wilmer_proxy_config():
    upstream = WilmerProxyUpstreamConfig(
        name="main",
        base_url="http://127.0.0.1:5060",
        authorization_mode="passthrough",
    )
    return WilmerProxyConfig(
        name="frontend-filter",
        upstreams={"main": upstream},
        models={
            "general": WilmerProxyModelConfig(
                public_name="general",
                upstream="main",
                target_model="chat-ui:general",
            ),
            "coding": WilmerProxyModelConfig(
                public_name="coding",
                upstream="main",
                target_model="developer:coding",
            ),
        },
    )


@pytest.fixture
def make_client():
    clients = []

    def factory(transport=None):
        app = Flask(__name__)
        app.config["TESTING"] = True
        selected_transport = transport or RecordingTransport()
        WilmerProxyOpenAIApiHandler(
            wilmer_proxy_config=_wilmer_proxy_config(),
            transport=selected_transport,
        ).register_routes(app)
        client = app.test_client()
        clients.append(client)
        return client, selected_transport

    return factory


@pytest.mark.parametrize("path", ["/v1/models", "/models"])
def test_models_lists_only_public_aliases(make_client, path):
    client, transport = make_client()

    response = client.get(path)

    assert response.status_code == 200
    assert [model["id"] for model in response.get_json()["data"]] == ["general", "coding"]
    assert "chat-ui:general" not in response.get_data(as_text=True)
    assert transport.calls == []


def test_unknown_model_is_rejected_without_contacting_upstream(make_client):
    client, transport = make_client()

    response = client.post(
        "/v1/chat/completions",
        json={"model": "private-workflow", "messages": []},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "model_not_found"
    assert transport.calls == []


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"not-json", "invalid_json"),
        (b"[]", "invalid_json"),
        (b'{"messages":[]}', "invalid_model"),
        (b'{"model":NaN}', "invalid_json"),
    ],
)
def test_invalid_requests_are_rejected_locally(make_client, body, code):
    client, transport = make_client()

    response = client.post(
        "/v1/chat/completions",
        data=body,
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code
    assert transport.calls == []


@pytest.mark.parametrize(
    ("public_path", "upstream_path"),
    [
        ("/v1/chat/completions", "/v1/chat/completions"),
        ("/chat/completions", "/v1/chat/completions"),
        ("/v1/completions", "/v1/completions"),
        ("/completions", "/v1/completions"),
    ],
)
def test_completion_routes_map_only_model_and_preserve_payload_semantics(
        make_client, public_path, upstream_path):
    upstream_body = b'{"id":"result-1","choices":[{"text":"ok"}]}'
    transport = RecordingTransport(FakeUpstreamResponse(body=upstream_body))
    client, _ = make_client(transport)
    payload = {
        "model": "general",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"},
                    },
                ],
                "custom_message_field": {"keep": True},
            }
        ],
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
        "tool_choice": "required",
        "temperature": 0.25,
        "top_p": 0.9,
        "stop": ["END"],
        "seed": 42,
        "response_format": {"type": "json_schema", "json_schema": {"name": "answer"}},
        "stream_options": {"include_usage": True},
        "reasoning_effort": "high",
        "metadata": {"client": "front-end"},
        "custom_extension": [1, {"nested": "value"}],
    }

    response = client.post(
        public_path,
        json=payload,
        headers={
            "Authorization": "Bearer client-key",
            "X-Idempotency-Key": "request-1",
        },
    )

    assert response.status_code == 200
    assert response.data == upstream_body
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == upstream_path
    assert call["upstream"].name == "main"
    forwarded_payload = json.loads(call["body"])
    assert forwarded_payload == {**payload, "model": "chat-ui:general"}
    assert call["incoming_headers"]["Authorization"] == "Bearer client-key"
    assert call["incoming_headers"]["X-Idempotency-Key"] == "request-1"
    assert transport.upstream_response.close_count == 1
    assert transport.sessions[0].close_count == 1


def test_nonstream_response_relays_status_body_and_end_to_end_headers(make_client):
    upstream = FakeUpstreamResponse(
        body=b'{"error":{"message":"rate limited"}}',
        status=429,
        headers={
            "Content-Type": "application/json",
            "Retry-After": "12",
            "X-Upstream-Request-Id": "upstream-1",
            "Content-Encoding": "gzip",
            "Connection": "keep-alive",
        },
    )
    client, transport = make_client(RecordingTransport(upstream))

    response = client.post(
        "/v1/chat/completions",
        json={"model": "general", "messages": []},
    )

    assert response.status_code == 429
    assert response.data == b'{"error":{"message":"rate limited"}}'
    assert response.headers["Retry-After"] == "12"
    assert response.headers["X-Upstream-Request-Id"] == "upstream-1"
    assert "Content-Encoding" not in response.headers
    assert "Connection" not in response.headers
    assert upstream.close_count == 1
    assert transport.sessions[0].close_count == 1


def test_streaming_response_relays_bytes_and_closes_once(make_client):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"one"}}]}\n\n',
        b"",
        b'data: {"choices":[{"delta":{"content":"two"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    upstream = FakeUpstreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream", "X-Stream": "raw"},
        chunks=chunks,
    )
    client, transport = make_client(RecordingTransport(upstream))

    response = client.post(
        "/v1/chat/completions",
        json={"model": "general", "messages": [], "stream": True},
        buffered=False,
    )
    relayed = b"".join(response.response)
    response.close()

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/event-stream"
    assert response.headers["X-Stream"] == "raw"
    assert relayed == b"".join(chunk for chunk in chunks if chunk)
    assert upstream.iterated is True
    assert upstream.close_count == 1
    assert transport.sessions[0].close_count == 1


def test_upstream_error_is_buffered_even_when_client_requested_stream(make_client):
    upstream = FakeUpstreamResponse(
        body=b'{"error":{"code":"bad_request"}}',
        status=400,
        headers={"Content-Type": "application/json"},
        chunks=[b"must not iterate"],
    )
    client, transport = make_client(RecordingTransport(upstream))

    response = client.post(
        "/v1/chat/completions",
        json={"model": "general", "messages": [], "stream": True},
    )

    assert response.status_code == 400
    assert response.data == b'{"error":{"code":"bad_request"}}'
    assert upstream.iterated is False
    assert upstream.close_count == 1
    assert transport.sessions[0].close_count == 1


def test_connection_failure_returns_openai_shaped_502_without_logging_exception_text(
        make_client, caplog):
    client, _ = make_client(RecordingTransport(
        error=requests.ConnectionError("sensitive upstream detail")))

    with caplog.at_level("ERROR"):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "general", "messages": []},
        )

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "message": "The configured upstream 'main' could not complete the request.",
        "type": "wilmer_proxy_error",
        "param": None,
        "code": "upstream_unavailable",
    }
    assert "sensitive upstream detail" not in caplog.text
    assert "ConnectionError" in caplog.text
