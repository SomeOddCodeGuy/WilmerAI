# tests/workflows/handlers/impl/test_web_fetch_handler.py

import json
import types

import pytest
import requests

from Middleware.workflows.handlers.impl.web_fetch_handler import (
    WebFetchHandler,
    _AddressNotAllowedError,
    _ResponseTooLargeError,
)
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.fixture
def web_fetch_handler(mocker):
    mock_workflow_manager = mocker.MagicMock()
    mock_variable_service = mocker.MagicMock()
    # By default, variable substitution is a pass-through.
    mock_variable_service.apply_variables.side_effect = lambda template, context: template
    return WebFetchHandler(
        workflow_manager=mock_workflow_manager,
        workflow_variable_service=mock_variable_service,
    )


def _make_context(config, stream=False):
    return ExecutionContext(
        request_id="req-1",
        workflow_id="wf-1",
        discussion_id=None,
        config=config,
        messages=[],
        stream=stream,
    )


def _mock_response(mocker, *, status_code=200, text="ok", json_body=None, headers=None):
    mock_resp = mocker.MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code
    mock_resp.text = text
    # The handler streams the body (default size cap on) via iter_content; yield
    # the text as a single byte chunk so the capped read succeeds.
    mock_resp.iter_content.return_value = [text.encode("utf-8")]
    mock_resp.headers = headers or {"Content-Type": "text/plain"}
    if json_body is not None:
        mock_resp.json.return_value = json_body
    if status_code >= 400:
        http_err = requests.exceptions.HTTPError(f"{status_code} error", response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


class _StubResponse:
    """A minimal stand-in for requests.Response whose .text derives from the bytes
    the handler captures.

    A MagicMock(spec=Response) exposes .text as a static attribute, so a test using
    it can never tell whether the handler actually assembled the streamed chunks (it
    reads back the pre-set string regardless). This stub instead reconstructs .text
    from the chunks the handler reads: once the handler has loaded a bounded
    ._content, .text decodes that (proving the cap/assembly); before then it decodes
    the full chunk list (mimicking requests' lazy, UNBOUNDED read).
    """

    def __init__(self, chunks, *, status_code=200, headers=None, encoding="utf-8"):
        self._chunks = list(chunks)
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/plain"}
        self.encoding = encoding
        self._content = False
        self._content_consumed = False
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        self.closed = True

    @property
    def text(self):
        if self._content is False or not self._content_consumed:
            return b"".join(self._chunks).decode(self.encoding)
        return self._content.decode(self.encoding)

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error", response=self)


def test_missing_url_raises(web_fetch_handler):
    context = _make_context({"type": "WebFetch"})
    with pytest.raises(ValueError, match="'url'"):
        web_fetch_handler.handle(context)


def test_invalid_output_format_raises(web_fetch_handler):
    context = _make_context({"type": "WebFetch", "url": "http://x", "outputFormat": "bogus"})
    with pytest.raises(ValueError, match="outputFormat"):
        web_fetch_handler.handle(context)


def test_invalid_on_error_raises(web_fetch_handler):
    context = _make_context({"type": "WebFetch", "url": "http://x", "onError": "swallow"})
    with pytest.raises(ValueError, match="onError"):
        web_fetch_handler.handle(context)


def test_invalid_headers_type_raises(web_fetch_handler):
    context = _make_context({"type": "WebFetch", "url": "http://x", "headers": "Authorization: Bearer abc"})
    with pytest.raises(ValueError, match="headers"):
        web_fetch_handler.handle(context)


def test_get_default_method_and_timeout(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="hello world"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://example.com"})

    result = web_fetch_handler.handle(context)

    assert result == "hello world"
    mock_request.assert_called_once_with(
        method="GET",
        url="http://example.com",
        headers=None,
        data=None,
        timeout=30,
        proxies=None,
        verify=True,
        allow_redirects=True,
        stream=True,
    )


def test_post_with_headers_and_body(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="created", status_code=200),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://api.example.com/items",
        "method": "post",
        "headers": {"Authorization": "Bearer abc", "Accept": "application/json"},
        "body": '{"k": "v"}',
        "timeout": 12,
    })

    web_fetch_handler.handle(context)

    mock_request.assert_called_once_with(
        method="POST",
        url="http://api.example.com/items",
        headers={"Authorization": "Bearer abc", "Accept": "application/json"},
        data='{"k": "v"}',
        timeout=12,
        proxies=None,
        verify=True,
        allow_redirects=True,
        stream=True,
    )


def test_variable_substitution_runs_on_url_headers_body(web_fetch_handler, mocker):
    sub_map = {
        "http://example.com/{path}": "http://example.com/items/42",
        "Bearer {apiKey}": "Bearer s3cret",
        "Accept": "Accept",  # header keys are NOT substituted, only values
        "application/json": "application/json",
        '{"id": "{id}"}': '{"id": "42"}',
    }
    web_fetch_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com/{path}",
        "method": "POST",
        "headers": {"Authorization": "Bearer {apiKey}", "Accept": "application/json"},
        "body": '{"id": "{id}"}',
    })

    web_fetch_handler.handle(context)

    mock_request.assert_called_once_with(
        method="POST",
        url="http://example.com/items/42",
        headers={"Authorization": "Bearer s3cret", "Accept": "application/json"},
        data='{"id": "42"}',
        timeout=30,
        proxies=None,
        verify=True,
        allow_redirects=True,
        stream=True,
    )


def test_output_format_json_serializes_parsed_response(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text='{"x": 1}', json_body={"x": 1}),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "outputFormat": "json"})

    result = web_fetch_handler.handle(context)

    assert json.loads(result) == {"x": 1}


def test_output_format_full_includes_status_headers_body(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(
            mocker,
            status_code=200,
            text="hi",
            headers={"X-Trace": "abc"},
        ),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "outputFormat": "full"})

    result = web_fetch_handler.handle(context)

    parsed = json.loads(result)
    assert parsed["status_code"] == 200
    assert parsed["body"] == "hi"
    assert parsed["headers"]["X-Trace"] == "abc"


def test_http_error_raises_by_default(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, status_code=500, text="boom"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x"})

    with pytest.raises(requests.exceptions.HTTPError):
        web_fetch_handler.handle(context)


def test_http_error_returns_response_body_when_on_error_return_text(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, status_code=500, text="server fail"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "onError": "return"})

    result = web_fetch_handler.handle(context)

    assert result == "server fail"


def test_http_error_returns_full_payload_when_on_error_return_full(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(
            mocker,
            status_code=404,
            text="not found",
            headers={"X-Err": "1"},
        ),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://x",
        "onError": "return",
        "outputFormat": "full",
    })

    result = web_fetch_handler.handle(context)
    parsed = json.loads(result)

    assert parsed["status_code"] == 404
    assert parsed["body"] == "not found"
    assert parsed["headers"]["X-Err"] == "1"
    assert "error" in parsed


def test_connection_error_raises_by_default(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        side_effect=requests.exceptions.ConnectTimeout("connect timeout"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x"})

    with pytest.raises(requests.exceptions.ConnectTimeout):
        web_fetch_handler.handle(context)


def test_connection_error_returns_message_when_on_error_return(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        side_effect=requests.exceptions.ConnectTimeout("connect timeout"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "onError": "return"})

    result = web_fetch_handler.handle(context)
    assert "connect timeout" in result


def test_proxy_socks5_forwarded_to_requests(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "proxy": "socks5://localhost:1080",
    })

    web_fetch_handler.handle(context)

    kwargs = mock_request.call_args.kwargs
    assert kwargs["proxies"] == {
        "http": "socks5://localhost:1080",
        "https": "socks5://localhost:1080",
    }


def test_proxy_http_scheme_also_works(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "proxy": "http://proxy.internal:3128",
    })

    web_fetch_handler.handle(context)

    kwargs = mock_request.call_args.kwargs
    assert kwargs["proxies"] == {
        "http": "http://proxy.internal:3128",
        "https": "http://proxy.internal:3128",
    }


def test_proxy_supports_variable_substitution(web_fetch_handler, mocker):
    sub_map = {"http://example.com": "http://example.com", "{proxyUrl}": "socks5://10.0.0.1:1080"}
    web_fetch_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "proxy": "{proxyUrl}",
    })

    web_fetch_handler.handle(context)

    kwargs = mock_request.call_args.kwargs
    assert kwargs["proxies"] == {
        "http": "socks5://10.0.0.1:1080",
        "https": "socks5://10.0.0.1:1080",
    }


def test_proxy_must_be_string(web_fetch_handler):
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "proxy": {"host": "localhost", "port": 1080},
    })
    with pytest.raises(ValueError, match="'proxy'"):
        web_fetch_handler.handle(context)


def test_proxy_empty_string_is_treated_as_no_proxy(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "proxy": "",
    })

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["proxies"] is None


def test_html_stripped_drops_scripts_styles_head_and_returns_visible_text(web_fetch_handler, mocker):
    html = (
        "<!DOCTYPE html>"
        "<html><head>"
        "<title>Hidden Title</title>"
        "<meta charset='utf-8'>"
        "<link rel='stylesheet' href='/x.css'>"
        "<style>.a{color:red}</style>"
        "<script>var x = 1;</script>"
        "</head>"
        "<body>"
        "<h1>Heading</h1>"
        "<p>First paragraph with <strong>bold</strong> text.</p>"
        "<script>tracking();</script>"
        "<noscript>Please enable JS</noscript>"
        "<p>Second paragraph &amp; entities &#x27;ok&#x27;.</p>"
        "</body></html>"
    )
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text=html),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "outputFormat": "html-stripped",
    })

    result = web_fetch_handler.handle(context)

    # Head content (title, meta, link), script bodies, style bodies, and noscript content
    # should all be gone. Body text — including across multiple paragraphs — should survive,
    # and entities should be decoded.
    assert "Hidden Title" not in result
    assert "var x" not in result
    assert "tracking" not in result
    assert "color:red" not in result
    assert "Please enable JS" not in result
    assert "Heading" in result
    assert "First paragraph with" in result
    assert "bold" in result
    assert "text." in result
    assert "Second paragraph & entities 'ok'." in result


def test_html_stripped_handles_plain_text_response(web_fetch_handler, mocker):
    """Plain text passed through the stripper should survive (no tags to strip)."""
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="hello, world"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "outputFormat": "html-stripped",
    })

    result = web_fetch_handler.handle(context)
    assert "hello, world" in result


def test_html_stripped_handles_broken_html_without_raising(web_fetch_handler, mocker):
    """Unclosed tags should not crash the parser; visible text should still come through."""
    html = "<html><body><p>Open paragraph<div>Nested<span>text"
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text=html),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "outputFormat": "html-stripped",
    })

    result = web_fetch_handler.handle(context)
    assert "Open paragraph" in result
    assert "Nested" in result
    assert "text" in result


def test_html_stripped_skips_unclosed_script_block(web_fetch_handler, mocker):
    """An unclosed <script> tag should still suppress its contents from the output."""
    html = "<html><body><p>before</p><script>leak_this()"
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text=html),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "outputFormat": "html-stripped",
    })

    result = web_fetch_handler.handle(context)
    assert "before" in result
    assert "leak_this" not in result


def test_html_stripped_on_error_return_uses_stripper(web_fetch_handler, mocker):
    """When onError=return and outputFormat=html-stripped, an HTML error body is stripped too."""
    error_html = "<html><body><h1>500 Internal Error</h1><p>Try again.</p></body></html>"
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, status_code=500, text=error_html),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "outputFormat": "html-stripped",
        "onError": "return",
    })

    result = web_fetch_handler.handle(context)
    assert "<html>" not in result
    assert "<h1>" not in result
    assert "500 Internal Error" in result
    assert "Try again." in result


def test_streaming_response_returns_generator(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="hello"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x"}, stream=True)

    result = web_fetch_handler.handle(context)

    assert isinstance(result, types.GeneratorType)
    chunks = list(result)
    joined = "".join(c["token"] for c in chunks)
    assert joined == "hello"


def test_non_numeric_timeout_raises(web_fetch_handler, mocker):
    """A non-numeric timeout must raise the node's own clear ValueError, not a deep TypeError."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "timeout": "soon"})

    with pytest.raises(ValueError, match="timeout"):
        web_fetch_handler.handle(context)
    mock_request.assert_not_called()


def test_non_positive_timeout_raises(web_fetch_handler):
    context = _make_context({"type": "WebFetch", "url": "http://x", "timeout": 0})
    with pytest.raises(ValueError, match="timeout"):
        web_fetch_handler.handle(context)


def test_numeric_string_timeout_is_coerced(web_fetch_handler, mocker):
    """A numeric string timeout is coerced to a number and forwarded to requests."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "timeout": "15"})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["timeout"] == 15


def test_verify_true_is_pinned(web_fetch_handler, mocker):
    """TLS verification must be explicitly pinned on, not left to an implicit default."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x"})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["verify"] is True


def test_json_output_on_non_json_200_raises_by_default(web_fetch_handler, mocker):
    """outputFormat=json on a non-JSON 200 body raises (default onError=raise)."""
    resp = _mock_response(mocker, status_code=200, text="not json")
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "not json", 0)
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "outputFormat": "json"})

    with pytest.raises(json.JSONDecodeError):
        web_fetch_handler.handle(context)


def test_allow_redirects_can_be_disabled(web_fetch_handler, mocker):
    """allowRedirects=false is forwarded to requests so a 30x is not followed."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "allowRedirects": False})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["allow_redirects"] is False


def test_allow_redirects_must_be_bool(web_fetch_handler):
    context = _make_context({"type": "WebFetch", "url": "http://x", "allowRedirects": "yes"})
    with pytest.raises(ValueError, match="allowRedirects"):
        web_fetch_handler.handle(context)


def test_response_exceeding_cap_raises_by_default(web_fetch_handler, mocker):
    """A body larger than maxResponseBytes aborts the read instead of buffering it all."""
    resp = _mock_response(mocker, text="ok")
    resp.iter_content.return_value = [b"0123456789"]  # 10 bytes > cap of 5
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "maxResponseBytes": 5})

    with pytest.raises(_ResponseTooLargeError):
        web_fetch_handler.handle(context)
    resp.close.assert_called_once()


def test_response_exceeding_cap_returns_when_on_error_return(web_fetch_handler, mocker):
    resp = _mock_response(mocker, text="ok")
    resp.iter_content.return_value = [b"0123456789"]
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://x",
        "maxResponseBytes": 5,
        "onError": "return",
    })

    result = web_fetch_handler.handle(context)
    assert "exceeded" in result


def test_cap_disabled_when_zero_does_not_stream(web_fetch_handler, mocker):
    """maxResponseBytes=0 disables the cap and the request is not streamed."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="big body"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "maxResponseBytes": 0})

    result = web_fetch_handler.handle(context)

    assert result == "big body"
    assert mock_request.call_args.kwargs["stream"] is False


def test_max_response_bytes_must_be_int(web_fetch_handler):
    context = _make_context({"type": "WebFetch", "url": "http://x", "maxResponseBytes": "big"})
    with pytest.raises(ValueError, match="maxResponseBytes"):
        web_fetch_handler.handle(context)


def test_body_within_cap_is_returned(web_fetch_handler, mocker):
    """A body under the cap is read fully and returned unchanged."""
    resp = _mock_response(mocker, text="hello world")
    resp.iter_content.return_value = [b"hello ", b"world"]
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "maxResponseBytes": 1024})

    result = web_fetch_handler.handle(context)
    assert result == "hello world"


def test_body_within_cap_assembles_streamed_chunks(web_fetch_handler, mocker):
    """The capped read must actually join the streamed chunks (PASS2-014).

    Uses a stub Response whose .text derives from the bytes the handler loads, so a
    broken chunk-join would change the result (a MagicMock's static .text would hide it).
    """
    resp = _StubResponse([b"hel", b"lo ", b"world"], status_code=200)
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({"type": "WebFetch", "url": "http://x", "maxResponseBytes": 1024})

    result = web_fetch_handler.handle(context)

    assert result == "hello world"
    assert resp._content == b"hello world"
    assert resp._content_consumed is True


def test_http_error_body_is_capped_on_return_path(web_fetch_handler, mocker):
    """An over-cap error body must be truncated, not pulled in full via .text (PASS2-001).

    Without the bounded error read, _format_error reads response.text, which on a
    streamed response lazily reads the ENTIRE body off the socket regardless of
    maxResponseBytes. The stub's .text reflects that: only a bounded ._content keeps
    it short.
    """
    # 50 bytes of body, cap of 8.
    resp = _StubResponse([b"XXXXXXXXXX"] * 5, status_code=500)
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://x",
        "onError": "return",
        "maxResponseBytes": 8,
    })

    result = web_fetch_handler.handle(context)

    assert result == "XXXXXXXX"
    assert len(result) == 8
    assert resp.closed is True


def test_http_error_raise_path_closes_streamed_response(web_fetch_handler, mocker):
    """On the raise path the (unconsumed) streamed error response is closed, not leaked.

    The body is NOT read (0 bytes pulled), but the socket must be released rather than
    held open until GC.
    """
    resp = _StubResponse([b"X" * 100], status_code=500)
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({"type": "WebFetch", "url": "http://x"})  # onError defaults to raise

    with pytest.raises(requests.exceptions.HTTPError):
        web_fetch_handler.handle(context)

    assert resp.closed is True


def test_http_error_body_capped_on_return_path_full_format(web_fetch_handler, mocker):
    """The bounded error read also bounds the body embedded in the 'full' payload."""
    resp = _StubResponse([b"YYYYYYYYYY"] * 5, status_code=502, headers={"X-Err": "1"})
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://x",
        "onError": "return",
        "outputFormat": "full",
        "maxResponseBytes": 8,
    })

    parsed = json.loads(web_fetch_handler.handle(context))

    assert parsed["status_code"] == 502
    assert parsed["body"] == "YYYYYYYY"
    assert resp.closed is True


def test_json_output_on_non_json_200_returns_body_when_on_error_return(web_fetch_handler, mocker):
    """outputFormat=json on a non-JSON 200 body honors onError=return and, per the onError
    table, returns the available response body rather than only the decode-error string."""
    resp = _mock_response(mocker, status_code=200, text="not json")
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "not json", 0)
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=resp,
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://x",
        "outputFormat": "json",
        "onError": "return",
    })

    result = web_fetch_handler.handle(context)

    assert result == "not json"


# --- TLS verification: opt-in `verify` toggle and `caBundle` (default stays strict) ---

def test_default_verify_is_true_when_unconfigured(web_fetch_handler, mocker):
    """Opt-in guarantee: with neither field set, requests is called with verify=True
    (the original always-on certifi behavior), unchanged."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://example.com"})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["verify"] is True


def test_verify_false_disables_verification(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "https://internal", "verify": False})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["verify"] is False


def test_ca_bundle_forwarded_to_requests_as_path(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.os.path.isfile",
        return_value=True,
    )
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "https://internal",
        "caBundle": "/etc/ssl/private-ca.pem",
    })

    web_fetch_handler.handle(context)

    # verify stays ON (a path), just trusts the supplied CA.
    assert mock_request.call_args.kwargs["verify"] == "/etc/ssl/private-ca.pem"


def test_ca_bundle_supports_variable_substitution(web_fetch_handler, mocker):
    sub_map = {"https://internal": "https://internal", "{caPath}": "/tmp/ca.pem"}
    web_fetch_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.os.path.isfile",
        return_value=True,
    )
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "https://internal",
        "caBundle": "{caPath}",
    })

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["verify"] == "/tmp/ca.pem"


def test_verify_false_takes_precedence_over_ca_bundle(web_fetch_handler, mocker):
    """An explicit verify:false disables verification; caBundle is ignored (not even
    checked for existence)."""
    isfile = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.os.path.isfile",
        return_value=True,
    )
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "https://internal",
        "verify": False,
        "caBundle": "/etc/ssl/private-ca.pem",
    })

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["verify"] is False
    isfile.assert_not_called()


def test_ca_bundle_empty_string_falls_back_to_default_verify(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "https://x", "caBundle": ""})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["verify"] is True


def test_ca_bundle_missing_file_raises(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.os.path.isfile",
        return_value=False,
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "https://x",
        "caBundle": "/no/such/ca.pem",
    })
    with pytest.raises(ValueError, match="'caBundle' file not found"):
        web_fetch_handler.handle(context)


def test_ca_bundle_must_be_string(web_fetch_handler):
    context = _make_context({
        "type": "WebFetch",
        "url": "https://x",
        "caBundle": ["/etc/ssl/ca.pem"],
    })
    with pytest.raises(ValueError, match="'caBundle'"):
        web_fetch_handler.handle(context)


def test_verify_must_be_boolean(web_fetch_handler):
    context = _make_context({
        "type": "WebFetch",
        "url": "https://x",
        "verify": "false",
    })
    with pytest.raises(ValueError, match="'verify'"):
        web_fetch_handler.handle(context)


# --- SSRF address guard (blockPrivateAddresses / allowedHosts), all opt-in ---

def test_guard_inactive_forwards_redirect_handling_to_requests(web_fetch_handler, mocker):
    """With neither guard field set the guard is inert: requests follows redirects itself
    (allow_redirects forwarded), preserving the original behavior."""
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({"type": "WebFetch", "url": "http://example.com"})

    web_fetch_handler.handle(context)

    assert mock_request.call_args.kwargs["allow_redirects"] is True


def test_block_private_addresses_rejects_loopback(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://127.0.0.1:8080/admin",
        "blockPrivateAddresses": True,
    })

    with pytest.raises(_AddressNotAllowedError):
        web_fetch_handler.handle(context)
    mock_request.assert_not_called()


def test_block_private_addresses_rejects_cloud_metadata(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://169.254.169.254/latest/meta-data/",
        "blockPrivateAddresses": True,
    })

    with pytest.raises(_AddressNotAllowedError):
        web_fetch_handler.handle(context)
    mock_request.assert_not_called()


def test_block_private_addresses_returns_envelope_on_error_return(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://10.0.0.5/",
        "blockPrivateAddresses": True,
        "onError": "return",
    })

    result = web_fetch_handler.handle(context)

    assert "disallowed address" in result


def test_block_private_addresses_allows_public_ip(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://8.8.8.8/",
        "blockPrivateAddresses": True,
    })

    result = web_fetch_handler.handle(context)

    assert result == "ok"
    # Guard active => redirects are followed manually, so requests' own redirect
    # handling is disabled on the underlying call.
    assert mock_request.call_args.kwargs["allow_redirects"] is False


def test_allowed_hosts_permits_listed_host(web_fetch_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=_mock_response(mocker, text="ok"),
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com/data",
        "allowedHosts": ["example.com"],
    })

    assert web_fetch_handler.handle(context) == "ok"


def test_allowed_hosts_rejects_unlisted_host(web_fetch_handler, mocker):
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://evil.example.net/",
        "allowedHosts": ["example.com"],
    })

    with pytest.raises(_AddressNotAllowedError):
        web_fetch_handler.handle(context)
    mock_request.assert_not_called()


def test_redirect_to_private_address_is_blocked(web_fetch_handler, mocker):
    """A public first hop that 302-redirects to a private address is rejected on the
    redirect hop, before the second request is issued."""
    redirect = _mock_response(
        mocker, status_code=302, headers={"location": "http://169.254.169.254/"}
    )
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        return_value=redirect,
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://8.8.8.8/start",
        "blockPrivateAddresses": True,
    })

    with pytest.raises(_AddressNotAllowedError):
        web_fetch_handler.handle(context)
    # Only the first hop was requested; the redirect target was rejected pre-connect.
    assert mock_request.call_count == 1
    redirect.close.assert_called_once()


def test_cross_host_redirect_strips_credentials(web_fetch_handler, mocker):
    """When the guard follows a redirect to a DIFFERENT host, credential headers are
    not carried to the new host (mirrors requests' own cross-host redirect behavior),
    while non-credential headers still travel."""
    redirect = _mock_response(
        mocker, status_code=302, headers={"location": "http://1.1.1.1/next"}
    )
    final = _mock_response(mocker, text="ok")
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        side_effect=[redirect, final],
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://8.8.8.8/start",
        "blockPrivateAddresses": True,
        "headers": {"Authorization": "Bearer secret", "X-Trace": "keep"},
    })

    assert web_fetch_handler.handle(context) == "ok"
    assert mock_request.call_count == 2
    first_headers = mock_request.call_args_list[0].kwargs["headers"]
    second_headers = mock_request.call_args_list[1].kwargs["headers"] or {}
    assert first_headers["Authorization"] == "Bearer secret"
    assert "Authorization" not in second_headers
    assert second_headers.get("X-Trace") == "keep"


def test_same_host_redirect_keeps_credentials(web_fetch_handler, mocker):
    """A redirect that stays on the same host keeps the Authorization header."""
    redirect = _mock_response(
        mocker, status_code=302, headers={"location": "http://8.8.8.8/next"}
    )
    final = _mock_response(mocker, text="ok")
    mock_request = mocker.patch(
        "Middleware.workflows.handlers.impl.web_fetch_handler.requests.request",
        side_effect=[redirect, final],
    )
    context = _make_context({
        "type": "WebFetch",
        "url": "http://8.8.8.8/start",
        "blockPrivateAddresses": True,
        "headers": {"Authorization": "Bearer secret"},
    })

    assert web_fetch_handler.handle(context) == "ok"
    second_headers = mock_request.call_args_list[1].kwargs["headers"] or {}
    assert second_headers.get("Authorization") == "Bearer secret"


def test_allowed_hosts_must_be_list(web_fetch_handler):
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "allowedHosts": "example.com",
    })
    with pytest.raises(ValueError, match="allowedHosts"):
        web_fetch_handler.handle(context)


def test_block_private_addresses_must_be_bool(web_fetch_handler):
    context = _make_context({
        "type": "WebFetch",
        "url": "http://example.com",
        "blockPrivateAddresses": "yes",
    })
    with pytest.raises(ValueError, match="blockPrivateAddresses"):
        web_fetch_handler.handle(context)
