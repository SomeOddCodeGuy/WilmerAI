"""Exercise Waitress's real WSGI response handling without opening sockets."""

from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import pytest
from waitress.task import WSGITask
from werkzeug.test import EnvironBuilder

from Middleware.api.handlers.base.base_streaming import _build_streaming_response


@pytest.mark.parametrize("mimetype,chunks", [
    ("text/event-stream", [b'data: {"text":"hello"}\n\n', b"data: [DONE]\n\n"]),
    ("application/x-ndjson", [b'{"response":"hello","done":false}\n', b'{"done":true}\n']),
])
def test_waitress_streams_and_owns_connection_close(mimetype, chunks):
    application = Flask(__name__)
    cleanup = Mock()
    body_closed = Mock()
    application_headers = []

    def body():
        try:
            yield from chunks
        finally:
            body_closed()

    @application.get("/stream")
    def stream():
        response = _build_streaming_response(body(), mimetype, on_close=cleanup)
        application_headers.extend(response.headers.to_wsgi_list())
        return response

    wire = []
    channel = SimpleNamespace(
        server=SimpleNamespace(application=application, adj=SimpleNamespace(ident="")),
        write_soon=wire.append,
    )
    task = WSGITask(channel, SimpleNamespace(version="1.1", headers={}, command="GET"))
    builder = EnvironBuilder(path="/stream", method="GET")
    try:
        task.environ = builder.get_environ()
        task.service()
    finally:
        builder.close()

    assert task.status == "200 OK"
    assert task.close_on_finish is True
    assert task.chunked_response is True
    assert {name.lower() for name, _ in application_headers}.isdisjoint({"connection", "transfer-encoding"})
    assert b"Connection: close\r\n" in wire[0]
    assert b"Transfer-Encoding: chunked\r\n" in wire[0]
    assert wire[1:-1] == [f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n" for chunk in chunks]
    assert wire[-1] == b"0\r\n\r\n"
    cleanup.assert_called_once_with()
    body_closed.assert_called_once_with()
