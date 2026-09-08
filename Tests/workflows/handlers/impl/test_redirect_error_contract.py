"""WebFetch redirect parsing obeys the configured error and output contracts."""
from types import SimpleNamespace
import json

import pytest
import requests

from Middleware.workflows.handlers.impl.web_fetch_handler import WebFetchHandler
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.mark.parametrize("transport", ["requests", "curl"])
@pytest.mark.parametrize("location,on_error,output_format,stream", [
    ("http://[", "return", "full", False),
    ("http://[", "return", "text", True),
    ("http://[", "raise", "full", False),
    ("https://example.com:invalid/next", "return", "full", False),
    ("https://example.com:invalid/next", "raise", "text", True),
    # A raw Latin-1 Location byte is not a valid UTF-8 redirect target.
    ("/caf\u00e9", "return", "full", False),
    ("/caf\u00e9", "raise", "text", True),
    ("/next", "return", "full", False),
    ("/next", "raise", "text", True),
])
def test_general_fetch_redirect_error_contract(transport, location, on_error, output_format, stream, monkeypatch):
    response = requests.Response()
    response.status_code = 302
    response.headers["Location"] = location
    response._content = b""
    response._content_consumed = True
    final = requests.Response()
    final.status_code = 200
    final._content = b"ordinary page"
    final._content_consumed = True
    closed = []
    response.close = lambda: closed.append("redirect")
    final.close = lambda: closed.append("final")
    sends = []
    def request_once(**kwargs):
        sends.append(kwargs["url"])
        return response if len(sends) == 1 else final
    monkeypatch.setattr("Middleware.workflows.handlers.impl.web_fetch_handler.request_without_redirects", request_once)
    handler = WebFetchHandler(workflow_manager=None,
                             workflow_variable_service=SimpleNamespace(apply_variables=lambda text, context: text))
    monkeypatch.setattr(handler, "_request_with_curl", request_once)
    context = ExecutionContext(request_id="synthetic-redirect", workflow_id="review", discussion_id=None,
                               config={"url": "https://example.com/page", "onError": on_error,
                                       "outputFormat": output_format, "transport": transport},
                               messages=[], stream=stream)
    invalid = location.startswith("http") or location == '/caf\u00e9'
    try:
        if invalid and on_error == "raise":
            with pytest.raises(requests.exceptions.InvalidURL, match="^Redirect URL could not be parsed$"):
                handler.handle(context)
            assert sends == ["https://example.com/page"]
            return
        result = handler.handle(context)
        if stream:
            result = "".join(chunk["token"] for chunk in result)
        if output_format == "full":
            result = json.loads(result)
    finally:
        assert closed == (["redirect"] if invalid else ["redirect", "final"])
    if invalid:
        message = result["error"] if output_format == "full" else result
        assert message == "Redirect URL could not be parsed"
        assert len(sends) == 1
    else:
        assert (result["body"] if output_format == "full" else result) == "ordinary page"
        assert sends == ["https://example.com/page", "https://example.com/next"]
        assert closed == ["redirect", "final"]
