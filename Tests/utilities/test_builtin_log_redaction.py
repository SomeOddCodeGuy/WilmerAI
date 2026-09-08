"""Focused request-privacy probes with synthetic provider and MCP responses."""
from contextlib import asynccontextmanager
import json
import logging
from types import SimpleNamespace

import pytest
import requests

from Middleware.llmapis.handlers.impl.openai_completions_api_handler import OpenAiCompletionsApiHandler
from Middleware.llmapis.handlers.impl.ollama_chat_api_handler import OllamaChatHandler
from Middleware.llmapis.handlers.impl.ollama_generate_api_handler import OllamaGenerateApiHandler
from Middleware.llmapis.handlers.impl.koboldcpp_api_handler import KoboldCppApiHandler
from Middleware.utilities.sensitive_logging_utils import (
    set_encryption_context, clear_encryption_context, is_encryption_active,
)
from Middleware.workflows.handlers.impl.mcp_tool_call_handler import MCPToolCallHandler
from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.tools import mcp_client_tool

MARKER = "synthetic-private-upstream-content"


@pytest.fixture(autouse=True)
def clear_privacy():
    previous = is_encryption_active()
    clear_encryption_context()
    yield
    set_encryption_context(previous)


@pytest.mark.parametrize("private", [True, False], ids=["private", "ordinary"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize("handler_class", [OpenAiCompletionsApiHandler, OllamaChatHandler,
                                           OllamaGenerateApiHandler, KoboldCppApiHandler])
def test_provider_parser_diagnostics_respect_privacy(handler_class, stream, private, caplog):
    # These parsers do not use instance state; avoid an unrelated HTTP session.
    handler = object.__new__(handler_class)
    set_encryption_context(private)
    with caplog.at_level(logging.WARNING):
        if stream:
            assert handler._process_stream_data(MARKER) is None
        else:
            assert handler._parse_non_stream_response({"error": MARKER}) == ""
    assert bool(caplog.records), "The error path must actually emit a diagnostic"
    assert (MARKER in caplog.text) is (not private)


@pytest.mark.parametrize("private", [True, False], ids=["private", "ordinary"])
def test_image_fallback_exception_respects_privacy(private, caplog):
    from Middleware.llmapis.handlers.base.image_injection import inject_images_into_messages

    def fail_image(source):
        raise ValueError(source)

    set_encryption_context(private)
    with caplog.at_level(logging.ERROR):
        result = inject_images_into_messages(
            [{"role": "user", "content": "ordinary input", "images": [MARKER]}],
            fail_image, True, "example", "fallback")
    assert "error processing" in result[0]["content"]
    assert "images" not in result[0]
    assert caplog.records
    assert (MARKER in caplog.text) is (not private)
    assert ("Traceback" in caplog.text) is (not private)


@pytest.mark.parametrize("private", [True, False], ids=["private", "ordinary"])
def test_ollama_actual_nonstream_transport_to_parser(private, monkeypatch, caplog):
    monkeypatch.setattr("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", lambda: 1)
    handler = OllamaChatHandler(base_url="https://provider.example", api_key="", gen_input={},
                                model_name="example", headers={}, stream=False,
                                api_type_config={}, endpoint_config={}, max_tokens=20)
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({"error": MARKER}).encode()
    response._content_consumed = True
    sends = []
    def post(*args, **kwargs):
        sends.append((args, kwargs))
        return response
    monkeypatch.setattr(handler.session, "post", post)
    set_encryption_context(private)
    try:
        with caplog.at_level(logging.WARNING):
            assert handler.handle_non_streaming(conversation=[{"role": "user", "content": "ordinary input"}]) == ""
        assert len(sends) == 1
        assert (MARKER in caplog.text) is (not private)
    finally:
        handler.session.close()


@pytest.mark.parametrize("private", [True, False], ids=["private", "ordinary"])
def test_native_mcp_error_result_respects_privacy(private, monkeypatch, caplog):
    import mcp
    from mcp.types import CallToolResult, TextContent
    calls = []
    @asynccontextmanager
    async def memory_streams(*args):
        yield object(), object()
    class MemorySession:
        def __init__(self, *args):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def initialize(self):
            pass
        async def call_tool(self, name, **kwargs):
            calls.append(name)
            return CallToolResult(isError=True, content=[TextContent(type="text", text=MARKER)])
    monkeypatch.setattr(mcp_client_tool, "load_mcp_server_config", lambda name: {"transport": "stdio", "command": "unused"})
    monkeypatch.setattr(mcp_client_tool, "_connect_streams", memory_streams)
    monkeypatch.setattr(mcp, "ClientSession", MemorySession)
    handler = MCPToolCallHandler(workflow_manager=None,
                                workflow_variable_service=SimpleNamespace(apply_variables=lambda text, context: text))
    context = ExecutionContext(request_id="synthetic-mcp", workflow_id="review", discussion_id=None,
                               config={"type": "MCPToolCall", "server": "example", "tool": "example",
                                       "onError": "return"}, messages=[], stream=False)
    set_encryption_context(private)
    with caplog.at_level(logging.WARNING):
        result = handler.handle(context)
    assert MARKER in result
    assert calls == ["example"]
    assert (MARKER in caplog.text) is (not private)


@pytest.mark.parametrize("private", [True, False], ids=["private", "ordinary"])
def test_memory_chunk_text_respects_privacy(private, caplog):
    from Middleware.utilities.text_utils import get_message_chunks
    set_encryption_context(private)
    with caplog.at_level(logging.DEBUG):
        chunks = get_message_chunks([{"role": "user", "content": MARKER},
                                     {"role": "assistant", "content": "ordinary reply"}], 0, 400)
    assert MARKER in "".join(chunks)
    assert (MARKER in caplog.text) is (not private)


@pytest.mark.parametrize("private", [True, False], ids=["private", "ordinary"])
def test_encrypted_summary_write_respects_log_privacy(private, caplog, monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from Middleware.workflows.handlers.impl import memory_node_handler as module
    key = Fernet.generate_key()
    destination = tmp_path / "summary.json"
    monkeypatch.setattr(module, "get_discussion_memory_file_path", lambda *args, **kwargs: str(tmp_path / "memory.json"))
    monkeypatch.setattr(module, "get_discussion_chat_summary_file_path", lambda *args, **kwargs: str(destination))
    handler = object.__new__(module.MemoryNodeHandler)
    context = ExecutionContext(request_id="synthetic-summary", workflow_id="review", discussion_id="example",
                               config={}, messages=[], stream=False, encryption_key=key)
    set_encryption_context(private)
    with caplog.at_level(logging.DEBUG):
        assert handler._save_summary_to_file(context, summary_override=MARKER, last_hash_override="example-hash") == MARKER
    encrypted = destination.read_bytes()
    destination.unlink()
    assert MARKER.encode() not in encrypted
    assert MARKER.encode() in Fernet(key).decrypt(encrypted)
    assert (MARKER in caplog.text) is (not private)
