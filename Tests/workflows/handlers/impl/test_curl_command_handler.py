# tests/workflows/handlers/impl/test_curl_command_handler.py

import json
import subprocess
import types

import pytest

from Middleware.workflows.handlers.impl.curl_command_handler import (
    CurlCommandHandler,
    _DEFAULT_MAX_RESPONSE_BYTES,
)
from Middleware.workflows.models.execution_context import ExecutionContext

# Default cap that the handler injects as `--max-filesize` when the author has
# not specified one. Kept as a prefix helper so command assertions stay readable.
_CAP = ["--max-filesize", str(_DEFAULT_MAX_RESPONSE_BYTES)]


@pytest.fixture
def curl_handler(mocker):
    mock_workflow_manager = mocker.MagicMock()
    mock_variable_service = mocker.MagicMock()
    mock_variable_service.apply_variables.side_effect = lambda template, context: template
    return CurlCommandHandler(
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


class _FakeStream:
    """A pipe-like object that hands out predetermined byte chunks then EOF."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def read(self, size=-1):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


class _FakePopen:
    """A minimal stand-in for subprocess.Popen for the curl handler's streaming read.

    The handler reads stdout/stderr on reader threads, waits on the process with a
    timeout, and may kill it on a cap breach. This fake records the wait timeout and
    the kill so tests can assert on them without spawning a real subprocess.
    """

    def __init__(self, stdout_chunks=(), stderr_chunks=(), returncode=0, hang=False):
        self.stdout = _FakeStream(stdout_chunks)
        self.stderr = _FakeStream(stderr_chunks)
        self._returncode = returncode
        self.returncode = None
        self.killed = False
        self.hang = hang
        self.wait_timeout = None
        self._wait_calls = 0

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_calls == 1:
            self.wait_timeout = timeout
            if self.hang and not self.killed:
                raise subprocess.TimeoutExpired(cmd=["curl"], timeout=timeout)
        if self.returncode is None:
            self.returncode = self._returncode
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def _fake(stdout=b"", stderr=b"", returncode=0, hang=False):
    """Builds a _FakePopen from str/bytes single-chunk stdout/stderr."""

    def _chunks(value):
        if not value:
            return []
        return [value if isinstance(value, bytes) else value.encode("utf-8")]

    return _FakePopen(_chunks(stdout), _chunks(stderr), returncode=returncode, hang=hang)


def _patch_popen(mocker, fake):
    return mocker.patch(
        "Middleware.workflows.handlers.impl.curl_command_handler.subprocess.Popen",
        return_value=fake,
    )


def test_missing_args_raises(curl_handler):
    context = _make_context({"type": "CurlCommand"})
    with pytest.raises(ValueError, match="'args'"):
        curl_handler.handle(context)


def test_args_not_a_list_raises(curl_handler):
    context = _make_context({"type": "CurlCommand", "args": "curl http://x"})
    with pytest.raises(ValueError, match="list"):
        curl_handler.handle(context)


def test_invalid_output_format_raises(curl_handler):
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "outputFormat": "weird"})
    with pytest.raises(ValueError, match="outputFormat"):
        curl_handler.handle(context)


def test_invalid_on_error_raises(curl_handler):
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "onError": "ignore"})
    with pytest.raises(ValueError, match="onError"):
        curl_handler.handle(context)


def test_runs_with_shell_false_and_prepends_curl(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="hello"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-sS", "http://example.com"],
    })

    result = curl_handler.handle(context)

    assert result == "hello"
    assert mock_popen.call_args.args[0] == ["curl", *_CAP, "-sS", "http://example.com"]
    call_kwargs = mock_popen.call_args.kwargs
    assert call_kwargs["shell"] is False
    assert call_kwargs["stdout"] == subprocess.PIPE
    assert call_kwargs["stderr"] == subprocess.PIPE


def test_variable_substitution_per_arg(curl_handler, mocker):
    sub_map = {
        "-H": "-H",
        "Authorization: Bearer {token}": "Authorization: Bearer abc123",
        "https://api.example.com/{endpoint}": "https://api.example.com/items",
    }
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="{}"))
    context = _make_context({
        "type": "CurlCommand",
        "args": [
            "-sS", "-H", "Authorization: Bearer {token}",
            "https://api.example.com/{endpoint}",
        ],
    })

    curl_handler.handle(context)

    assert mock_popen.call_args.args[0] == [
        "curl", *_CAP,
        "-sS", "-H", "Authorization: Bearer abc123",
        "https://api.example.com/items",
    ]


def test_non_numeric_timeout_raises(curl_handler, mocker):
    """A non-numeric timeout must raise the node's own clear ValueError, not a deep TypeError."""
    mock_popen = _patch_popen(mocker, _fake(stdout=""))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "timeout": "soon"})

    with pytest.raises(ValueError, match="timeout"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_non_positive_timeout_raises(curl_handler):
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "timeout": -1})
    with pytest.raises(ValueError, match="timeout"):
        curl_handler.handle(context)


def test_boolean_timeout_raises(curl_handler, mocker):
    """A boolean timeout is rejected even though bool is an int subclass."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "timeout": True})

    with pytest.raises(ValueError, match="timeout"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_numeric_string_timeout_is_coerced(curl_handler, mocker):
    """A numeric string timeout is coerced to a number and forwarded to proc.wait."""
    fake = _fake(stdout="")
    _patch_popen(mocker, fake)
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "timeout": "15"})

    curl_handler.handle(context)

    assert fake.wait_timeout == 15


def test_custom_timeout_passed_through(curl_handler, mocker):
    fake = _fake(stdout="")
    _patch_popen(mocker, fake)
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "timeout": 5})

    curl_handler.handle(context)

    assert fake.wait_timeout == 5


def test_output_format_stdout_stderr_concatenates(curl_handler, mocker):
    _patch_popen(mocker, _fake(stdout="data\n", stderr="info\n"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "outputFormat": "stdout+stderr",
    })

    result = curl_handler.handle(context)

    assert result == "data\ninfo\n"


def test_output_format_full_returns_json_envelope(curl_handler, mocker):
    _patch_popen(mocker, _fake(stdout="body", stderr="warn", returncode=0))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "outputFormat": "full",
    })

    result = curl_handler.handle(context)
    parsed = json.loads(result)

    assert parsed == {"stdout": "body", "stderr": "warn", "returncode": 0}


def test_nonzero_exit_raises_by_default(curl_handler, mocker):
    _patch_popen(mocker, _fake(stdout="", stderr="connect refused", returncode=7))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"]})

    with pytest.raises(RuntimeError, match="status 7"):
        curl_handler.handle(context)


def test_nonzero_exit_returns_when_on_error_return(curl_handler, mocker):
    _patch_popen(mocker, _fake(stdout="partial", stderr="connect refused", returncode=7))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "onError": "return",
        "outputFormat": "full",
    })

    result = curl_handler.handle(context)
    parsed = json.loads(result)

    assert parsed["returncode"] == 7
    assert parsed["stderr"] == "connect refused"
    assert parsed["stdout"] == "partial"


def test_timeout_raises_by_default(curl_handler, mocker):
    _patch_popen(mocker, _fake(hang=True))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "timeout": 2})

    with pytest.raises(subprocess.TimeoutExpired):
        curl_handler.handle(context)


def test_timeout_returns_message_when_on_error_return(curl_handler, mocker):
    fake = _fake(hang=True)
    _patch_popen(mocker, fake)
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "timeout": 2,
        "onError": "return",
    })

    result = curl_handler.handle(context)
    assert result == "curl timed out after 2 seconds"
    # On timeout the handler kills the process so it cannot linger.
    assert fake.killed is True


def test_timeout_full_format_envelope_with_partial_output(curl_handler, mocker):
    """A timeout with onError=return and outputFormat=full yields the JSON envelope:
    null returncode, the timeout error message, and whatever partial output curl
    produced before it was killed."""
    fake = _fake(stdout="partial data", stderr="still trying", hang=True)
    _patch_popen(mocker, fake)
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "timeout": 2,
        "onError": "return",
        "outputFormat": "full",
    })

    parsed = json.loads(curl_handler.handle(context))

    assert parsed["returncode"] is None
    assert parsed["error"] == "curl timed out after 2 seconds"
    assert parsed["stdout"] == "partial data"
    assert parsed["stderr"] == "still trying"
    assert fake.killed is True


def test_nonzero_exit_returns_partial_stdout_with_default_format(curl_handler, mocker):
    """A non-zero exit with onError=return and the default (stdout) format returns
    the partial stdout curl produced, not an error message."""
    _patch_popen(mocker, _fake(stdout="partial body", stderr="connect refused", returncode=7))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "onError": "return",
    })

    result = curl_handler.handle(context)

    assert result == "partial body"


def test_curl_not_installed_raises(curl_handler, mocker):
    mocker.patch(
        "Middleware.workflows.handlers.impl.curl_command_handler.subprocess.Popen",
        side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'curl'"),
    )
    context = _make_context({"type": "CurlCommand", "args": ["http://x"]})

    with pytest.raises(FileNotFoundError):
        curl_handler.handle(context)


def test_proxy_prepends_dash_x_to_args(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-sS", "http://example.com"],
        "proxy": "socks5://localhost:1080",
    })

    curl_handler.handle(context)

    assert mock_popen.call_args.args[0] == [
        "curl", *_CAP, "-x", "socks5://localhost:1080", "-sS", "http://example.com",
    ]


def test_proxy_supports_variable_substitution(curl_handler, mocker):
    sub_map = {
        "-sS": "-sS",
        "http://example.com": "http://example.com",
        "{proxyUrl}": "socks5://10.0.0.1:1080",
    }
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda template, ctx: sub_map.get(template, template)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-sS", "http://example.com"],
        "proxy": "{proxyUrl}",
    })

    curl_handler.handle(context)

    assert mock_popen.call_args.args[0] == [
        "curl", *_CAP, "-x", "socks5://10.0.0.1:1080", "-sS", "http://example.com",
    ]


def test_proxy_must_be_string(curl_handler):
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://example.com"],
        "proxy": {"host": "localhost"},
    })
    with pytest.raises(ValueError, match="'proxy'"):
        curl_handler.handle(context)


def test_proxy_empty_string_does_not_add_dash_x(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://example.com"],
        "proxy": "",
    })

    curl_handler.handle(context)

    assert mock_popen.call_args.args[0] == ["curl", *_CAP, "http://example.com"]


def test_max_filesize_not_injected_when_zero(curl_handler, mocker):
    """maxResponseBytes=0 disables the --max-filesize injection and the in-process cap."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "maxResponseBytes": 0})

    curl_handler.handle(context)

    assert mock_popen.call_args.args[0] == ["curl", "http://x"]


def test_max_filesize_not_duplicated_when_author_sets_it(curl_handler, mocker):
    """If the author already passes --max-filesize, the handler does not inject a second one."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["--max-filesize", "500", "http://x"],
    })

    curl_handler.handle(context)

    cmd = mock_popen.call_args.args[0]
    assert cmd.count("--max-filesize") == 1
    assert cmd == ["curl", "--max-filesize", "500", "http://x"]


def test_max_response_bytes_must_be_int(curl_handler):
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "maxResponseBytes": "big"})
    with pytest.raises(ValueError, match="maxResponseBytes"):
        curl_handler.handle(context)


def test_boolean_max_response_bytes_raises(curl_handler, mocker):
    """A boolean cap is rejected even though bool is an int subclass."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "maxResponseBytes": True})

    with pytest.raises(ValueError, match="maxResponseBytes"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_body_within_cap_is_streamed_and_returned(curl_handler, mocker):
    """Stdout under the cap is read chunk-by-chunk and returned joined; curl is not killed."""
    fake = _FakePopen(stdout_chunks=[b"hel", b"lo ", b"world"])
    _patch_popen(mocker, fake)
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "maxResponseBytes": 1024})

    result = curl_handler.handle(context)

    assert result == "hello world"
    assert fake.killed is False


def test_body_exceeding_cap_raises_by_default(curl_handler, mocker):
    """An over-cap body aborts curl and raises, even though --max-filesize did not catch it
    (the in-process cap is the true bound)."""
    fake = _FakePopen(stdout_chunks=[b"0123456789", b"abcdefghij"])  # 20 bytes
    _patch_popen(mocker, fake)
    context = _make_context({"type": "CurlCommand", "args": ["http://x"], "maxResponseBytes": 8})

    with pytest.raises(RuntimeError, match="exceeded"):
        curl_handler.handle(context)
    assert fake.killed is True


def test_body_exceeding_cap_returns_message_when_on_error_return(curl_handler, mocker):
    fake = _FakePopen(stdout_chunks=[b"0123456789abcdef"])
    _patch_popen(mocker, fake)
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "maxResponseBytes": 8,
        "onError": "return",
    })

    result = curl_handler.handle(context)

    assert "exceeded" in result
    assert fake.killed is True


def test_body_exceeding_cap_full_format_envelope(curl_handler, mocker):
    fake = _FakePopen(stdout_chunks=[b"0123456789abcdef"], stderr_chunks=[b"warn"])
    _patch_popen(mocker, fake)
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "maxResponseBytes": 8,
        "onError": "return",
        "outputFormat": "full",
    })

    parsed = json.loads(curl_handler.handle(context))

    assert parsed["returncode"] is None
    assert "error" in parsed
    assert parsed["stdout"] == "01234567"  # truncated to the cap


def test_block_option_injection_rejects_substituted_flag(curl_handler, mocker):
    """With the guard on, a variable that expands into a leading-dash value is rejected."""
    sub_map = {"{userInput}": "-o/tmp/evil", "http://x": "http://x"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["{userInput}", "http://x"],
        "blockOptionInjection": True,
    })

    with pytest.raises(ValueError, match="option-like"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_option_injection_allows_author_written_flag(curl_handler, mocker):
    """The guard allows flags written literally by the author (template starts with '-')."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-sS", "http://x"],
        "blockOptionInjection": True,
    })

    result = curl_handler.handle(context)

    assert result == "ok"
    assert "-sS" in mock_popen.call_args.args[0]


def test_option_injection_allowed_when_guard_disabled(curl_handler, mocker):
    """Default behavior (guard off) keeps a substituted leading-dash value as a real curl flag."""
    sub_map = {"{userInput}": "-o/tmp/x", "http://x": "http://x"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["{userInput}", "http://x"]})

    curl_handler.handle(context)

    assert "-o/tmp/x" in mock_popen.call_args.args[0]


def test_block_option_injection_must_be_bool(curl_handler):
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "blockOptionInjection": "yes",
    })
    with pytest.raises(ValueError, match="blockOptionInjection"):
        curl_handler.handle(context)


def test_block_option_injection_rejects_substituted_at_file_value(curl_handler, mocker):
    """With the guard on, a variable that expands into an '@file' data value (which
    curl would read off disk) is rejected, even though it does not start with '-'."""
    sub_map = {"{userInput}": "@/etc/passwd", "http://x": "http://x"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-d", "{userInput}", "http://x"],
        "blockOptionInjection": True,
    })

    with pytest.raises(ValueError, match="'@'-prefixed"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_option_injection_allows_author_written_at_value(curl_handler, mocker):
    """An '@' the author wrote literally in the template is intentional and allowed."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-d", "@/home/me/payload.json", "http://x"],
        "blockOptionInjection": True,
    })

    result = curl_handler.handle(context)

    assert result == "ok"
    assert "@/home/me/payload.json" in mock_popen.call_args.args[0]


def test_at_file_injection_allowed_when_guard_disabled(curl_handler, mocker):
    """Default behavior (guard off) keeps a substituted '@file' value untouched."""
    sub_map = {"{userInput}": "@/etc/passwd", "http://x": "http://x"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["-d", "{userInput}", "http://x"]})

    curl_handler.handle(context)

    assert "@/etc/passwd" in mock_popen.call_args.args[0]


def test_scheme_injection_file_blocked_by_default(curl_handler, mocker):
    """A substituted file:// URL is rejected by default (safe-by-default), before curl runs."""
    sub_map = {"{userInput}": "file:///etc/passwd"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["{userInput}"]})

    with pytest.raises(ValueError, match="file:"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_scheme_injection_blocks_other_non_http_schemes(curl_handler, mocker):
    """ftp/scp/dict/gopher introduced via substitution are blocked just like file://."""
    for bad in ("ftp://host/f", "scp://host/f", "dict://localhost:11211/stats", "gopher://h/_"):
        sub_map = {"{u}": bad}
        curl_handler.workflow_variable_service.apply_variables.side_effect = (
            lambda t, c: sub_map.get(t, t)
        )
        mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
        context = _make_context({"type": "CurlCommand", "args": ["{u}"]})

        with pytest.raises(ValueError, match="blocked"):
            curl_handler.handle(context)
        mock_popen.assert_not_called()


def test_http_scheme_substitution_allowed(curl_handler, mocker):
    """An injected http(s) scheme is fine; that is the normal use of the node."""
    sub_map = {"{url}": "https://example.com/data"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["{url}"]})

    result = curl_handler.handle(context)

    assert result == "ok"
    assert "https://example.com/data" in mock_popen.call_args.args[0]


def test_author_written_file_scheme_allowed(curl_handler, mocker):
    """A scheme the author wrote literally in the template is intentional and allowed."""
    sub_map = {"file://{path}": "file:///etc/hosts"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="data"))
    context = _make_context({"type": "CurlCommand", "args": ["file://{path}"]})

    result = curl_handler.handle(context)

    assert result == "data"
    assert "file:///etc/hosts" in mock_popen.call_args.args[0]


def test_scheme_injection_allowed_when_opted_out(curl_handler, mocker):
    """allowSchemeInjection=true fully opens up: a substituted file:// is permitted."""
    sub_map = {"{userInput}": "file:///etc/passwd"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="x"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["{userInput}"],
        "allowSchemeInjection": True,
    })

    curl_handler.handle(context)

    assert "file:///etc/passwd" in mock_popen.call_args.args[0]


def test_windows_drive_letter_not_flagged_as_scheme(curl_handler, mocker):
    """A substituted Windows path (C:\\...) is a single-letter drive, not a URL scheme."""
    sub_map = {"{p}": "C:\\data\\file.txt"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({"type": "CurlCommand", "args": ["-d", "{p}", "http://x"]})

    result = curl_handler.handle(context)

    assert result == "ok"


def test_allow_scheme_injection_must_be_bool(curl_handler):
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://x"],
        "allowSchemeInjection": "yes",
    })
    with pytest.raises(ValueError, match="allowSchemeInjection"):
        curl_handler.handle(context)


def test_streaming_returns_generator(curl_handler, mocker):
    _patch_popen(mocker, _fake(stdout="hello"))
    context = _make_context({"type": "CurlCommand", "args": ["http://x"]}, stream=True)

    result = curl_handler.handle(context)

    assert isinstance(result, types.GeneratorType)
    chunks = list(result)
    joined = "".join(c["token"] for c in chunks)
    assert joined == "hello"


# --- SSRF address guard (blockPrivateAddresses / allowedHosts), all opt-in ---

def test_block_private_addresses_rejects_loopback_url_arg(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-sS", "http://127.0.0.1:8080/admin"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_private_addresses_rejects_cloud_metadata_url_arg(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://169.254.169.254/latest/meta-data/"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_private_addresses_checks_url_equals_form(curl_handler, mocker):
    """The `--url=<url>` form is address-checked, not just the bare-URL positional form."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["--url=http://10.0.0.9/"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_private_addresses_allows_public_ip_and_pins_redirects(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://8.8.8.8/"],
        "blockPrivateAddresses": True,
    })

    result = curl_handler.handle(context)

    assert result == "ok"
    # Guard active => curl is pinned to zero redirects so a 3xx cannot bounce to an
    # unvalidated host.
    cmd = mock_popen.call_args.args[0]
    assert cmd[:1] == ["curl"]
    assert "--max-redirs" in cmd
    assert cmd[cmd.index("--max-redirs") + 1] == "0"


def test_redirect_guard_not_injected_when_author_sets_max_redirs(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["--max-redirs", "3", "http://8.8.8.8/"],
        "blockPrivateAddresses": True,
    })

    curl_handler.handle(context)

    cmd = mock_popen.call_args.args[0]
    # The author's --max-redirs stays; the handler does not add a second one.
    assert cmd.count("--max-redirs") == 1
    assert cmd[cmd.index("--max-redirs") + 1] == "3"


def test_guard_off_does_not_inject_max_redirs_or_block_private(curl_handler, mocker):
    """With the guard off, a private URL is allowed and no --max-redirs is injected
    (original behavior preserved)."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://127.0.0.1/"],
    })

    result = curl_handler.handle(context)

    assert result == "ok"
    cmd = mock_popen.call_args.args[0]
    assert "--max-redirs" not in cmd


def test_allowed_hosts_rejects_unlisted_host(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://evil.example.net/"],
        "allowedHosts": ["example.com"],
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_allowed_hosts_permits_listed_host(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://example.com/data"],
        "allowedHosts": ["example.com"],
    })

    assert curl_handler.handle(context) == "ok"
    assert "--max-redirs" in mock_popen.call_args.args[0]


def test_allowed_hosts_matching_is_case_insensitive(curl_handler, mocker):
    """Doc contract: URL args must target a listed host case-insensitively; a
    mixed-case URL host and a mixed-case allowlist entry still match."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://EXAMPLE.COM/data"],
        "allowedHosts": ["Example.Com"],
    })

    assert curl_handler.handle(context) == "ok"
    mock_popen.assert_called_once()


def test_allowed_hosts_entries_support_variable_substitution(curl_handler, mocker):
    """Doc contract: allowlist entries are variable-substituted. The resolved entry
    permits its host and everything else stays rejected."""
    sub_map = {"{allowedHost}": "trusted.example.com"}
    curl_handler.workflow_variable_service.apply_variables.side_effect = (
        lambda t, c: sub_map.get(t, t)
    )
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))

    allowed_context = _make_context({
        "type": "CurlCommand",
        "args": ["http://trusted.example.com/data"],
        "allowedHosts": ["{allowedHost}"],
    })
    assert curl_handler.handle(allowed_context) == "ok"

    denied_context = _make_context({
        "type": "CurlCommand",
        "args": ["http://other.example.com/data"],
        "allowedHosts": ["{allowedHost}"],
    })
    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(denied_context)
    # Only the allowed invocation spawned curl.
    mock_popen.assert_called_once()


def test_combined_guards_reject_allowlisted_private_address(curl_handler, mocker):
    """Doc contract: allowedHosts and blockPrivateAddresses are additive; an
    allowlisted host that is a private address is still rejected."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://127.0.0.1/status"],
        "allowedHosts": ["127.0.0.1"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_url_option_without_value_does_not_crash_guard(curl_handler, mocker):
    """A trailing `--url` with no following value must not crash the guard's arg walk;
    with no URL to validate, curl is still invoked (curl itself will error out)."""
    mock_popen = _patch_popen(mocker, _fake(stdout="", stderr="curl: no URL specified", returncode=2))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["--url"],
        "blockPrivateAddresses": True,
        "onError": "return",
    })

    curl_handler.handle(context)

    mock_popen.assert_called_once()


def test_allowed_hosts_must_be_list(curl_handler):
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://example.com"],
        "allowedHosts": "example.com",
    })
    with pytest.raises(ValueError, match="allowedHosts"):
        curl_handler.handle(context)


def test_block_private_addresses_must_be_bool(curl_handler):
    context = _make_context({
        "type": "CurlCommand",
        "args": ["http://example.com"],
        "blockPrivateAddresses": "yes",
    })
    with pytest.raises(ValueError, match="blockPrivateAddresses"):
        curl_handler.handle(context)


# --- SSRF address guard: schemeless URL positions (curl defaults them to http) ---

def test_block_private_addresses_rejects_schemeless_loopback(curl_handler, mocker):
    """A schemeless positional URL (curl fetches it over http) is address-checked too."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-sS", "127.0.0.1:8080/admin"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_private_addresses_rejects_schemeless_cloud_metadata(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["169.254.169.254/latest/meta-data/"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_private_addresses_rejects_schemeless_url_space_form(curl_handler, mocker):
    """The `--url <value>` (space) form is checked even when the value is schemeless."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["--url", "10.0.0.9/"],
        "blockPrivateAddresses": True,
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_block_private_addresses_allows_schemeless_public_ip(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["8.8.8.8/"],
        "blockPrivateAddresses": True,
    })

    assert curl_handler.handle(context) == "ok"
    assert "--max-redirs" in mock_popen.call_args.args[0]


def test_address_guard_does_not_flag_option_value_that_looks_private(curl_handler, mocker):
    """A private-looking value consumed by an option (e.g. `-d 10.0.0.1`) is data, not a
    URL, so it must not be address-checked; the actual (public) URL still is."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["-d", "10.0.0.1", "http://8.8.8.8/"],
        "blockPrivateAddresses": True,
    })

    assert curl_handler.handle(context) == "ok"
    mock_popen.assert_called_once()


def test_allowed_hosts_rejects_schemeless_unlisted_host(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["evil.example.net/x"],
        "allowedHosts": ["example.com"],
    })

    with pytest.raises(ValueError, match="disallowed address"):
        curl_handler.handle(context)
    mock_popen.assert_not_called()


def test_allowed_hosts_permits_schemeless_listed_host(curl_handler, mocker):
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["example.com/data"],
        "allowedHosts": ["example.com"],
    })

    assert curl_handler.handle(context) == "ok"
    mock_popen.assert_called_once()


def test_address_guard_skips_non_http_scheme_literal(curl_handler, mocker):
    """A literal non-http(s) scheme is governed by the scheme-injection guard, not the
    address guard; the address pass must skip it rather than treat it as a host fetch."""
    mock_popen = _patch_popen(mocker, _fake(stdout="ok"))
    context = _make_context({
        "type": "CurlCommand",
        "args": ["ftp://example.com/file"],
        "blockPrivateAddresses": True,
    })

    assert curl_handler.handle(context) == "ok"
    mock_popen.assert_called_once()


# --- Reader-thread edges (stdout/stderr stream handling) ---

def test_read_diagnostic_truncates_over_cap_stderr_without_abort():
    """stderr larger than the cap is drained to EOF but only `cap` bytes are kept and
    the box is flagged truncated. Unlike the body reader, nothing is killed."""
    box = {}
    stream = _FakeStream([b"0123456789", b"abcdef"])

    CurlCommandHandler._read_diagnostic(stream, 4, box)

    assert box["data"] == b"0123"
    assert box["truncated"] is True


def test_read_diagnostic_unbounded_when_cap_disabled():
    """cap<=0 (maxResponseBytes disabled) keeps the full stderr stream."""
    box = {}
    stream = _FakeStream([b"abc", b"def"])

    CurlCommandHandler._read_diagnostic(stream, 0, box)

    assert box["data"] == b"abcdef"
    assert box["truncated"] is False


def test_read_body_keeps_partial_when_pipe_tears_down():
    """A pipe torn down mid-read (the process was killed) must not raise from the
    reader thread; whatever was captured before the teardown is kept."""

    class _TearingStream:
        def __init__(self):
            self.reads = 0

        def read(self, size=-1):
            self.reads += 1
            if self.reads == 1:
                return b"partial"
            raise ValueError("read of closed file")

    class _Proc:
        def __init__(self):
            self.stdout = _TearingStream()
            self.killed = False

        def kill(self):
            self.killed = True

    proc = _Proc()
    box = {}

    CurlCommandHandler._read_body(proc, 1024, box)

    assert box["data"] == b"partial"
    assert box["truncated"] is False
    assert proc.killed is False


def test_close_stream_swallows_close_errors_and_none():
    """Closing an already-torn-down pipe must not raise; None is a no-op; a healthy
    stream is actually closed."""

    class _ExplodingStream:
        def close(self):
            raise OSError("already closed")

    CurlCommandHandler._close_stream(_ExplodingStream())  # must not raise
    CurlCommandHandler._close_stream(None)  # must not raise

    healthy = _FakeStream([])
    CurlCommandHandler._close_stream(healthy)
    assert healthy.closed is True
