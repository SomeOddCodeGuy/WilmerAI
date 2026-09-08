"""A synthetic curl invocation must honor request log redaction before execution."""
import logging
import pytest
from unittest.mock import Mock

from Middleware.utilities.sensitive_logging_utils import (
    clear_encryption_context, set_encryption_context,
)
from Middleware.workflows.handlers.impl.curl_command_handler import CurlCommandHandler
from Middleware.workflows.models.execution_context import ExecutionContext


def test_curl_arguments_are_redacted_when_request_redaction_is_active(caplog, monkeypatch):
    variables = Mock()
    variables.apply_variables.side_effect = lambda template, context: template
    handler = CurlCommandHandler(Mock(), variables)
    execute = Mock(return_value='ok')
    monkeypatch.setattr(handler, '_execute', execute)
    marker = 'synthetic-private-request-marker'
    context = ExecutionContext(
        request_id='review-log-redaction', workflow_id='review', discussion_id=None,
        messages=[], stream=False,
        config={'type': 'CurlCommand', 'args': ['--data-raw', marker, 'https://example.com/']},
    )
    caplog.set_level(logging.DEBUG, logger=handler.__module__)
    set_encryption_context(True)
    try:
        assert handler.handle(context) == 'ok'
        execute.assert_called_once()
        assert marker not in caplog.text
    finally:
        clear_encryption_context()


def test_curl_diagnostics_never_include_credentials_even_without_redaction(caplog, monkeypatch):
    variables = Mock()
    variables.apply_variables.side_effect = lambda template, context: template
    handler = CurlCommandHandler(Mock(), variables)
    monkeypatch.setattr(handler, '_execute', Mock(return_value='ok'))
    marker = 'synthetic-command-credential'
    context = ExecutionContext(request_id='credential-log', workflow_id='test', discussion_id=None,
        messages=[], stream=False, config={'type': 'CurlCommand',
        'args': ['--header', 'Authorization: Bearer ' + marker, 'https://example.com/']})
    caplog.set_level(logging.DEBUG, logger=handler.__module__)
    clear_encryption_context()
    assert handler.handle(context) == 'ok'
    assert marker not in caplog.text


@pytest.mark.parametrize('module_name', [
    'mcp_tool_executor', 'mcp_service_discoverer', 'workflow_utils',
    'mcp_workflow_integration', 'ensure_system_prompt', 'mcp_prompt_utils',
])
def test_helper_diagnostics_redact_content_and_exception_details(module_name, caplog):
    import importlib
    module = importlib.import_module('Public.workflow_python_scripts._isevendays_mcp_scripts.' + module_name)
    marker = 'synthetic-helper-exception-content'
    caplog.set_level(logging.DEBUG)
    set_encryption_context(True)
    try:
        try:
            raise ValueError(marker)
        except ValueError:
            module.logger.exception('Failed request: %s', marker)
        assert marker not in caplog.text
        assert '[Redacted]' in caplog.text
    finally:
        clear_encryption_context()


def test_shipped_mcp_sanitizer_honors_redaction_at_info_level(caplog):
    from Public.workflow_python_scripts._isevendays_mcp_scripts.sanitize_llm_response import Invoke

    marker = 'synthetic-private-model-result'
    caplog.set_level(logging.INFO, logger=Invoke.__module__)
    set_encryption_context(True)
    try:
        assert Invoke(marker) == marker
        assert marker not in caplog.text
    finally:
        clear_encryption_context()
