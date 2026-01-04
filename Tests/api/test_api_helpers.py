# Tests/api/test_api_helpers.py

import json

import pytest

from Middleware.api import api_helpers


@pytest.mark.parametrize("api_type, expected_method", [
    ("openaichatcompletion", "build_openai_chat_completion_chunk"),
    ("openaicompletion", "build_openai_completion_chunk"),
    ("ollamagenerate", "build_ollama_generate_chunk"),
    ("ollamaapichat", "build_ollama_chat_chunk"),
])
def test_build_response_json_dispatcher(mocker, monkeypatch, api_type, expected_method):
    """Tests that build_response_json calls the correct service method based on API_TYPE."""
    mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
    monkeypatch.setattr('Middleware.common.instance_global_variables.API_TYPE', api_type)

    mock_method = getattr(mock_response_builder, expected_method)
    mock_method.return_value = {"status": "ok"}

    result = api_helpers.build_response_json("test_token", "stop")

    # Ollama methods now accept request_id as third parameter (defaults to None)
    if api_type in ("ollamagenerate", "ollamaapichat"):
        mock_method.assert_called_once_with("test_token", "stop", None)
    else:
        mock_method.assert_called_once_with("test_token", "stop")
    assert json.loads(result) == {"status": "ok"}


def test_build_response_json_unsupported_type(monkeypatch):
    """Tests that a ValueError is raised for an unsupported API type."""
    monkeypatch.setattr('Middleware.common.instance_global_variables.API_TYPE', "unsupported_api")
    with pytest.raises(ValueError, match="Unsupported API type for streaming: unsupported_api"):
        api_helpers.build_response_json("token")


@pytest.mark.parametrize("chunk, expected_text", [
    # OpenAI Chat SSE
    ('data: {"choices": [{"delta": {"content": "Hello"}}]}', "Hello"),
    # OpenAI Legacy Completion SSE
    ('data: {"choices": [{"text": " World"}]}', " World"),
    # Ollama Generate plain JSON string
    ('{"response": "Ollama"}', "Ollama"),
    # Ollama Chat plain JSON string
    ('{"message": {"content": " Chat"}}', " Chat"),
    # Direct dictionary
    ({"choices": [{"delta": {"content": "Dict"}}]}, "Dict"),
    # SSE Done signal
    ('data: [DONE]', ""),
    # Empty/None values
    (None, ""),
    ("", ""),
    ("  ", ""),
    # Malformed JSON
    ('data: {"bad": json', ""),
])
def test_extract_text_from_chunk(chunk, expected_text):
    assert api_helpers.extract_text_from_chunk(chunk) == expected_text


@pytest.mark.parametrize("input_text, expected_output", [
    ("Assistant: Hello", "Hello"),
    ("  Assistant:  Hi there", "Hi there"),
    ("No prefix here", "No prefix here"),
    ("Assistant:", ""),
])
def test_remove_assistant_prefix(input_text, expected_output):
    assert api_helpers.remove_assistant_prefix(input_text) == expected_output


class TestWorkflowOverride:
    """Tests for workflow override functionality via model field."""

    def test_get_model_name_without_override(self, mocker):
        """Tests that get_model_name returns just username when no override is set."""
        mocker.patch('Middleware.api.api_helpers.get_current_username', return_value='test_user')
        mocker.patch('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', None)
        assert api_helpers.get_model_name() == 'test_user'

    def test_get_model_name_with_override(self, mocker, monkeypatch):
        """Tests that get_model_name returns username:workflow when override is set."""
        mocker.patch('Middleware.api.api_helpers.get_current_username', return_value='test_user')
        monkeypatch.setattr('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', 'Coding_Workflow')
        assert api_helpers.get_model_name() == 'test_user:Coding_Workflow'

    def test_parse_model_field_none(self, mocker):
        """Tests that parse_model_field returns None for None input."""
        assert api_helpers.parse_model_field(None) is None

    def test_parse_model_field_empty(self, mocker):
        """Tests that parse_model_field returns None for empty string."""
        assert api_helpers.parse_model_field('') is None

    def test_parse_model_field_username_workflow_format(self, mocker):
        """Tests that parse_model_field extracts workflow from username:workflow format."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        assert api_helpers.parse_model_field('test_user:Coding_Workflow') == 'Coding_Workflow'

    def test_parse_model_field_username_workflow_not_found(self, mocker):
        """Tests that parse_model_field returns None when workflow doesn't exist."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=False)
        assert api_helpers.parse_model_field('test_user:NonExistent') is None

    def test_parse_model_field_workflow_only(self, mocker):
        """Tests that parse_model_field can parse just a workflow name."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        assert api_helpers.parse_model_field('Coding_Workflow') == 'Coding_Workflow'

    def test_parse_model_field_strips_latest_suffix(self, mocker):
        """Tests that parse_model_field strips :latest suffix from Ollama models."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        assert api_helpers.parse_model_field('Coding_Workflow:latest') == 'Coding_Workflow'

    def test_parse_model_field_username_workflow_latest(self, mocker):
        """Tests parsing username:workflow:latest format."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        # After stripping :latest, becomes "test_user:Coding_Workflow"
        assert api_helpers.parse_model_field('test_user:Coding_Workflow:latest') == 'Coding_Workflow'

    def test_set_workflow_override(self, mocker, monkeypatch):
        """Tests that set_workflow_override sets the global variable."""
        mocker.patch('Middleware.api.api_helpers.parse_model_field', return_value='Test_Workflow')
        monkeypatch.setattr('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', None)

        api_helpers.set_workflow_override('test_user:Test_Workflow')

        from Middleware.common import instance_global_variables
        assert instance_global_variables.WORKFLOW_OVERRIDE == 'Test_Workflow'

    def test_set_workflow_override_none(self, mocker, monkeypatch):
        """Tests that set_workflow_override handles None workflow."""
        mocker.patch('Middleware.api.api_helpers.parse_model_field', return_value=None)
        monkeypatch.setattr('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', 'existing')

        api_helpers.set_workflow_override('unknown_model')

        from Middleware.common import instance_global_variables
        assert instance_global_variables.WORKFLOW_OVERRIDE is None

    def test_clear_workflow_override(self, monkeypatch):
        """Tests that clear_workflow_override clears the global variable."""
        monkeypatch.setattr('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', 'Test_Workflow')

        api_helpers.clear_workflow_override()

        from Middleware.common import instance_global_variables
        assert instance_global_variables.WORKFLOW_OVERRIDE is None

    def test_get_active_workflow_override(self, monkeypatch):
        """Tests that get_active_workflow_override returns the current value."""
        monkeypatch.setattr('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', 'Active_Workflow')
        assert api_helpers.get_active_workflow_override() == 'Active_Workflow'

    def test_get_active_workflow_override_none(self, monkeypatch):
        """Tests that get_active_workflow_override returns None when not set."""
        monkeypatch.setattr('Middleware.common.instance_global_variables.WORKFLOW_OVERRIDE', None)
        assert api_helpers.get_active_workflow_override() is None
