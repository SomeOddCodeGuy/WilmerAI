"""Prompt compatibility and discussion-directory reference safety."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import Middleware.workflows.managers.workflow_variable_manager as module


@pytest.fixture
def template_context(monkeypatch):
    monkeypatch.setattr(module, 'get_chat_template_name', lambda: '_chatonly')
    monkeypatch.setattr(module, 'MemoryService', Mock())
    monkeypatch.setattr(module, 'TimestampService', Mock())
    monkeypatch.setattr(module, 'get_user_config', lambda: {})
    monkeypatch.setattr(module, 'get_separate_conversation_in_variables', lambda: False)
    path = Mock(return_value='/review/scoped/discussion')
    monkeypatch.setattr(module, 'get_discussion_folder_path', path)
    context = SimpleNamespace(config={}, workflow_config={'width': 0}, discussion_id=None,
        messages=[], agent_inputs={}, agent_outputs={}, api_key_hash='synthetic-scope', encryption_key=None)
    manager = module.WorkflowVariableManager()
    return manager, context, path


@pytest.mark.parametrize('discussion_id', [None, 'review-discussion'])
def test_dynamic_format_spec_keeps_discussion_directory_safety(template_context, discussion_id):
    manager, context, path = template_context
    context.discussion_id = discussion_id
    template = '{Discussion_Directory:>{width}}/notes.txt'
    if discussion_id is None:
        with pytest.raises(ValueError, match='discussion ID'):
            manager.apply_variables(template, context)
    else:
        assert manager.apply_variables(template, context) == '/review/scoped/discussion/notes.txt'
        path.assert_called_once_with(discussion_id, api_key_hash='synthetic-scope')


@pytest.mark.parametrize('brace', ['}', '{'])
@pytest.mark.parametrize('nested', [False, True])
def test_literal_json_fallback_survives_reference_scan(template_context, brace, nested):
    manager, context, path = template_context
    prompt = 'Return JSON: {"answer": "text"}. End with a brace: ' + brace
    if nested:
        context.workflow_config['instruction'] = prompt
    assert manager.apply_variables('{instruction}' if nested else prompt, context) == prompt
    path.assert_not_called()


@pytest.mark.parametrize('brace', ['}', '{'])
def test_reference_scan_preserves_normal_format_errors(template_context, brace):
    manager, context, path = template_context
    with pytest.raises(ValueError):
        manager.apply_variables('End with a brace: ' + brace, context)
    path.assert_not_called()


@pytest.mark.parametrize('discussion_id', [None, 'review-discussion'])
def test_scan_error_before_directory_reference_keeps_scope_guard(template_context, discussion_id):
    manager, context, path = template_context
    context.discussion_id = discussion_id
    prompt = '} {Discussion_Directory}/notes.txt'
    if discussion_id is None:
        with pytest.raises(ValueError, match='discussion ID'):
            manager.generate_variables(context, prompt=prompt)
        path.assert_not_called()
    else:
        variables = manager.generate_variables(context, prompt=prompt)
        assert variables['Discussion_Directory'] == '/review/scoped/discussion'
        path.assert_called_once_with(discussion_id, api_key_hash='synthetic-scope')
