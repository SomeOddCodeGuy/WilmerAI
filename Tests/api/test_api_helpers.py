import json

import pytest

from Middleware.api import api_helpers
from Middleware.api.app import app
from Middleware.common import instance_global_variables


@pytest.fixture(autouse=True)
def reset_api_type():
    """Clears the thread-local api_type after every test in this module so
    values like "unsupported_api" cannot leak into later tests."""
    yield
    instance_global_variables.clear_api_type()


@pytest.mark.parametrize("api_type, expected_method", [
    ("openaichatcompletion", "build_openai_chat_completion_chunk"),
    ("openaicompletion", "build_openai_completion_chunk"),
    ("ollamagenerate", "build_ollama_generate_chunk"),
    ("ollamaapichat", "build_ollama_chat_chunk"),
])
def test_build_response_json_dispatcher(mocker, monkeypatch, api_type, expected_method):
    """Tests that build_response_json calls the correct service method based on API_TYPE."""
    mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
    from Middleware.common import instance_global_variables
    instance_global_variables.set_api_type(api_type)

    mock_method = getattr(mock_response_builder, expected_method)
    mock_method.return_value = {"status": "ok"}

    result = api_helpers.build_response_json("test_token", "stop")

    # Ollama methods accept request_id as third parameter (defaults to None)
    # Chat-capable methods (ollamaapichat, openaichatcompletion) also receive tool_calls=None
    if api_type == "ollamaapichat":
        mock_method.assert_called_once_with("test_token", "stop", None, tool_calls=None)
    elif api_type == "openaichatcompletion":
        mock_method.assert_called_once_with("test_token", "stop", tool_calls=None)
    elif api_type == "ollamagenerate":
        mock_method.assert_called_once_with("test_token", "stop", None)
    else:
        mock_method.assert_called_once_with("test_token", "stop")
    assert json.loads(result) == {"status": "ok"}


def test_build_response_json_unsupported_type(monkeypatch):
    """Tests that a ValueError is raised for an unsupported API type."""
    from Middleware.common import instance_global_variables
    instance_global_variables.set_api_type("unsupported_api")
    with pytest.raises(ValueError, match="Unsupported API type for streaming: unsupported_api"):
        api_helpers.build_response_json("token")


class TestWorkflowOverride:
    """Tests for workflow override functionality via model field."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        from Middleware.common import instance_global_variables
        original_users = instance_global_variables.USERS
        yield
        instance_global_variables.USERS = original_users
        instance_global_variables.clear_request_user()
        instance_global_variables.clear_workflow_override()

    def test_get_model_name_without_override(self, mocker):
        """Tests that get_model_name returns just username when no override is set."""
        mocker.patch('Middleware.api.api_helpers.get_current_username', return_value='test_user')
        from Middleware.common import instance_global_variables
        instance_global_variables.clear_workflow_override()
        assert api_helpers.get_model_name() == 'test_user'

    def test_get_model_name_with_override(self, mocker):
        """Tests that get_model_name returns username:workflow when override is set."""
        mocker.patch('Middleware.api.api_helpers.get_current_username', return_value='test_user')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_workflow_override('Coding_Workflow')
        assert api_helpers.get_model_name() == 'test_user:Coding_Workflow'

    def test_parse_model_field_none(self, mocker):
        """Tests that parse_model_field returns (None, None) for None input."""
        assert api_helpers.parse_model_field(None) == (None, None)

    def test_parse_model_field_empty(self, mocker):
        """Tests that parse_model_field returns (None, None) for empty string."""
        assert api_helpers.parse_model_field('') == (None, None)

    def test_parse_model_field_username_workflow_format(self, mocker):
        """Tests that parse_model_field extracts workflow from username:workflow format in single-user mode."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        user, workflow = api_helpers.parse_model_field('test_user:Coding_Workflow')
        assert user is None
        assert workflow == 'Coding_Workflow'

    def test_parse_model_field_username_workflow_not_found(self, mocker):
        """Tests that parse_model_field returns (None, None) when workflow doesn't exist."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=False)
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        assert api_helpers.parse_model_field('test_user:NonExistent') == (None, None)

    def test_parse_model_field_workflow_only(self, mocker):
        """Tests that parse_model_field can parse just a workflow name."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        user, workflow = api_helpers.parse_model_field('Coding_Workflow')
        assert workflow == 'Coding_Workflow'
        assert user is None

    def test_parse_model_field_strips_latest_suffix(self, mocker):
        """Tests that parse_model_field strips :latest suffix from Ollama models."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        user, workflow = api_helpers.parse_model_field('Coding_Workflow:latest')
        assert user is None
        assert workflow == 'Coding_Workflow'

    def test_parse_model_field_username_workflow_latest(self, mocker):
        """Tests parsing username:workflow:latest format."""
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        # After stripping :latest, becomes "test_user:Coding_Workflow"
        user, workflow = api_helpers.parse_model_field('test_user:Coding_Workflow:latest')
        assert user is None
        assert workflow == 'Coding_Workflow'

    def test_set_workflow_override(self, mocker):
        """Tests that set_workflow_override sets the global variables."""
        mocker.patch('Middleware.api.api_helpers.parse_model_field', return_value=(None, 'Test_Workflow'))
        from Middleware.common import instance_global_variables
        instance_global_variables.clear_workflow_override()
        instance_global_variables.clear_request_user()

        api_helpers.set_workflow_override('test_user:Test_Workflow')

        assert instance_global_variables.get_workflow_override() == 'Test_Workflow'

    def test_set_workflow_override_none(self, mocker):
        """Tests that set_workflow_override handles None workflow."""
        mocker.patch('Middleware.api.api_helpers.parse_model_field', return_value=(None, None))
        from Middleware.common import instance_global_variables
        instance_global_variables.set_workflow_override('existing')

        api_helpers.set_workflow_override('unknown_model')

        assert instance_global_variables.get_workflow_override() is None

    def test_clear_workflow_override(self):
        """Tests that clear_workflow_override clears both workflow override and request user."""
        from Middleware.common import instance_global_variables
        instance_global_variables.set_workflow_override('Test_Workflow')
        instance_global_variables.set_request_user('some_user')

        api_helpers.clear_workflow_override()

        assert instance_global_variables.get_workflow_override() is None
        assert instance_global_variables.get_request_user() is None

    def test_get_active_workflow_override(self):
        """Tests that get_active_workflow_override returns the current value."""
        from Middleware.common import instance_global_variables
        instance_global_variables.set_workflow_override('Active_Workflow')
        assert api_helpers.get_active_workflow_override() == 'Active_Workflow'

    def test_get_active_workflow_override_none(self):
        """Tests that get_active_workflow_override returns None when not set."""
        from Middleware.common import instance_global_variables
        instance_global_variables.clear_workflow_override()
        assert api_helpers.get_active_workflow_override() is None


class TestMultiUserModelParsing:
    """Tests for multi-user model field parsing."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        from Middleware.common import instance_global_variables
        original_users = instance_global_variables.USERS
        yield
        instance_global_variables.USERS = original_users
        instance_global_variables.clear_request_user()
        instance_global_variables.clear_workflow_override()

    def test_multi_user_username_only(self, mocker):
        """In multi-user mode, a bare username sets request user, no workflow."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two', 'user-three']
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=False)

        user, workflow = api_helpers.parse_model_field('user-two')
        assert user == 'user-two'
        assert workflow is None

    def test_multi_user_username_with_workflow(self, mocker):
        """In multi-user mode, username:workflow sets both user and workflow."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        mocker.patch('Middleware.api.api_helpers._workflow_exists_for_user', return_value=True)

        user, workflow = api_helpers.parse_model_field('user-two:coding')
        assert user == 'user-two'
        assert workflow == 'coding'

    def test_multi_user_username_with_nonexistent_workflow(self, mocker):
        """In multi-user mode, username:bad-workflow still sets user, no workflow."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        mocker.patch('Middleware.api.api_helpers._workflow_exists_for_user', return_value=False)

        user, workflow = api_helpers.parse_model_field('user-two:nonexistent')
        assert user == 'user-two'
        assert workflow is None

    def test_multi_user_unrecognized_model(self, mocker):
        """In multi-user mode, a model matching no user and no workflow returns (None, None)."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=False)

        user, workflow = api_helpers.parse_model_field('some-random-model')
        assert user is None
        assert workflow is None

    def test_multi_user_bare_workflow_rejected(self, mocker):
        """In multi-user mode, a bare workflow name (no user prefix) is rejected.

        A bare workflow name is ambiguous in multi-user mode because there is
        no way to determine which user's shared folder to check.  Returning
        (None, None) lets require_identified_user() produce a clean 400 error.
        """
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)

        user, workflow = api_helpers.parse_model_field('coding')
        assert user is None
        assert workflow is None

    def test_multi_user_unrecognized_user_with_colon_skips_shared_folder(self, mocker):
        """In multi-user mode an unrecognized 'user:workflow' must NOT consult
        the shared workflows folder: no request user is set yet, so that lookup
        would crash (get_current_username raises in multi-user mode). The value
        is simply rejected and require_identified_user() produces the 400."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        mocker.patch(
            'Middleware.api.api_helpers.workflow_exists_in_shared_folder',
            side_effect=AssertionError("shared-folder lookup must not run in multi-user mode"))

        assert api_helpers.parse_model_field('ghost:coding') == (None, None)

    def test_single_user_mode_legacy_behavior(self, mocker):
        """In single-user mode (USERS is None), existing behavior is preserved."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)

        user, workflow = api_helpers.parse_model_field('test_user:Coding')
        assert user is None
        assert workflow == 'Coding'

    def test_single_user_one_entry_legacy_behavior(self, mocker):
        """In single-user mode (USERS has one entry), existing behavior is preserved."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['test_user']
        mocker.patch('Middleware.api.api_helpers.workflow_exists_in_shared_folder', return_value=True)

        user, workflow = api_helpers.parse_model_field('test_user:Coding')
        assert user is None
        assert workflow == 'Coding'

    def test_set_request_context_from_model_sets_both(self, mocker):
        """Tests that set_request_context_from_model sets both user and workflow."""
        mocker.patch('Middleware.api.api_helpers.parse_model_field', return_value=('user-two', 'coding'))
        from Middleware.common import instance_global_variables

        api_helpers.set_request_context_from_model('user-two:coding')

        assert instance_global_variables.get_request_user() == 'user-two'
        assert instance_global_variables.get_workflow_override() == 'coding'

    def test_set_request_context_from_model_user_only(self, mocker):
        """Tests that set_request_context_from_model sets just user when no workflow."""
        mocker.patch('Middleware.api.api_helpers.parse_model_field', return_value=('user-one', None))
        from Middleware.common import instance_global_variables

        api_helpers.set_request_context_from_model('user-one')

        assert instance_global_variables.get_request_user() == 'user-one'
        assert instance_global_variables.get_workflow_override() is None

    def test_clear_request_context(self):
        """Tests that clear_request_context clears both user and workflow."""
        from Middleware.common import instance_global_variables
        instance_global_variables.set_request_user('user-one')
        instance_global_variables.set_workflow_override('coding')

        api_helpers.clear_request_context()

        assert instance_global_variables.get_request_user() is None
        assert instance_global_variables.get_workflow_override() is None

    def test_latest_suffix_stripped_in_multi_user(self, mocker):
        """Tests that :latest suffix is stripped before multi-user parsing."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        mocker.patch('Middleware.api.api_helpers._workflow_exists_for_user', return_value=True)

        user, workflow = api_helpers.parse_model_field('user-two:coding:latest')
        assert user == 'user-two'
        assert workflow == 'coding'


class TestRequireIdentifiedUser:
    """Tests for multi-user request rejection."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        from Middleware.common import instance_global_variables
        original_users = instance_global_variables.USERS
        yield
        instance_global_variables.USERS = original_users
        instance_global_variables.clear_request_user()
        instance_global_variables.clear_workflow_override()

    def test_single_user_mode_always_passes(self):
        """In single-user mode, require_identified_user always returns None."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = None
        instance_global_variables.clear_request_user()

        assert api_helpers.require_identified_user() is None

    def test_single_user_list_always_passes(self):
        """With only one user configured, require_identified_user always returns None."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['solo-user']
        instance_global_variables.clear_request_user()

        assert api_helpers.require_identified_user() is None

    def test_multi_user_with_request_user_passes(self):
        """In multi-user mode, passes when request user is set."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        instance_global_variables.set_request_user('user-one')

        assert api_helpers.require_identified_user() is None

    def test_multi_user_without_request_user_rejects(self):
        """In multi-user mode, rejects when no request user is set."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['user-one', 'user-two']
        instance_global_variables.clear_request_user()

        error = api_helpers.require_identified_user()
        assert error is not None
        assert 'user-one' in error
        assert 'user-two' in error

    def test_multi_user_rejection_message_lists_available_users(self):
        """Rejection message includes all configured usernames."""
        from Middleware.common import instance_global_variables
        instance_global_variables.USERS = ['bob', 'jill', 'mack']
        instance_global_variables.clear_request_user()

        error = api_helpers.require_identified_user()
        assert 'bob' in error
        assert 'jill' in error
        assert 'mack' in error


class TestBuildResponseJsonToolCalls:
    """Tests that build_response_json passes tool_calls through to the correct builder methods."""

    def test_build_response_json_openai_chat_with_tool_calls(self, mocker):
        """OpenAI chat completion builder receives tool_calls when provided."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("openaichatcompletion")

        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]
        mock_response_builder.build_openai_chat_completion_chunk.return_value = {"choices": []}

        api_helpers.build_response_json("", "tool_calls", tool_calls=tool_calls)

        mock_response_builder.build_openai_chat_completion_chunk.assert_called_once_with(
            "", "tool_calls", tool_calls=tool_calls
        )

    def test_build_response_json_ollama_chat_with_tool_calls(self, mocker):
        """Ollama chat builder receives tool_calls when provided."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("ollamaapichat")

        tool_calls = [{"id": "call_2", "type": "function", "function": {"name": "search", "arguments": '{"q":"x"}'}}]
        mock_response_builder.build_ollama_chat_chunk.return_value = {"message": {}}

        api_helpers.build_response_json("", "tool_calls", tool_calls=tool_calls)

        mock_response_builder.build_ollama_chat_chunk.assert_called_once_with(
            "", "tool_calls", None, tool_calls=tool_calls
        )

    def test_build_response_json_openai_chat_without_tool_calls(self, mocker):
        """OpenAI chat completion builder receives tool_calls=None when not provided."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("openaichatcompletion")

        mock_response_builder.build_openai_chat_completion_chunk.return_value = {"choices": []}

        api_helpers.build_response_json("hello", "stop")

        mock_response_builder.build_openai_chat_completion_chunk.assert_called_once_with(
            "hello", "stop", tool_calls=None
        )

    def test_build_response_json_openai_completion_ignores_tool_calls(self, mocker):
        """OpenAI legacy completion builder does not receive tool_calls (completions endpoint does not support them)."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("openaicompletion")

        tool_calls = [{"id": "call_3", "type": "function", "function": {"name": "noop", "arguments": "{}"}}]
        mock_response_builder.build_openai_completion_chunk.return_value = {"choices": []}

        api_helpers.build_response_json("token", "stop", tool_calls=tool_calls)

        mock_response_builder.build_openai_completion_chunk.assert_called_once_with("token", "stop")

    def test_build_response_json_ollama_generate_ignores_tool_calls(self, mocker):
        """Ollama generate builder does not receive tool_calls (generate endpoint does not support them)."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("ollamagenerate")

        tool_calls = [{"id": "call_4", "type": "function", "function": {"name": "noop", "arguments": "{}"}}]
        mock_response_builder.build_ollama_generate_chunk.return_value = {"response": ""}

        api_helpers.build_response_json("token", "stop", tool_calls=tool_calls)

        mock_response_builder.build_ollama_generate_chunk.assert_called_once_with("token", "stop", None)


class TestBuildResponseJsonFields:
    """Tests for additional_fields merging and request_id pass-through in build_response_json."""

    @pytest.fixture(autouse=True)
    def reset_api_type(self):
        from Middleware.common import instance_global_variables
        yield
        instance_global_variables.clear_api_type()

    def test_additional_fields_merged_into_output(self, mocker):
        """additional_fields entries are merged into the final JSON payload."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("openaichatcompletion")

        mock_response_builder.build_openai_chat_completion_chunk.return_value = {"base": "value"}

        result = api_helpers.build_response_json(
            "tok", "stop", additional_fields={"extra": 123, "usage": {"total_tokens": 5}}
        )

        assert json.loads(result) == {"base": "value", "extra": 123, "usage": {"total_tokens": 5}}

    def test_additional_fields_overwrite_builder_output(self, mocker):
        """additional_fields entries overwrite keys already present in the builder output."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("openaicompletion")

        mock_response_builder.build_openai_completion_chunk.return_value = {"model": "original"}

        result = api_helpers.build_response_json("tok", "stop", additional_fields={"model": "override"})

        assert json.loads(result) == {"model": "override"}

    def test_request_id_reaches_ollama_generate_builder(self, mocker):
        """An explicit request_id is passed positionally to build_ollama_generate_chunk."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("ollamagenerate")

        mock_response_builder.build_ollama_generate_chunk.return_value = {"response": "ok"}

        api_helpers.build_response_json("tok", "stop", request_id="req-42")

        mock_response_builder.build_ollama_generate_chunk.assert_called_once_with("tok", "stop", "req-42")

    def test_request_id_reaches_ollama_chat_builder(self, mocker):
        """An explicit request_id is passed positionally to build_ollama_chat_chunk."""
        mock_response_builder = mocker.patch('Middleware.api.api_helpers.response_builder')
        from Middleware.common import instance_global_variables
        instance_global_variables.set_api_type("ollamaapichat")

        mock_response_builder.build_ollama_chat_chunk.return_value = {"message": {}}

        api_helpers.build_response_json("tok", "stop", request_id="req-42")

        mock_response_builder.build_ollama_chat_chunk.assert_called_once_with(
            "tok", "stop", "req-42", tool_calls=None
        )


@pytest.mark.parametrize("output_format, expected", [
    # Ollama formats stream newline-delimited JSON (bare data + single newline)
    ("ollamagenerate", '{"x": 1}\n'),
    ("ollamaapichat", '{"x": 1}\n'),
    # Everything else uses the SSE "data: ...\n\n" contract
    ("openaichatcompletion", 'data: {"x": 1}\n\n'),
    ("openaicompletion", 'data: {"x": 1}\n\n'),
    ("openai", 'data: {"x": 1}\n\n'),
    ("anything_else", 'data: {"x": 1}\n\n'),
])
def test_sse_format(output_format, expected):
    """sse_format wraps Ollama output as bare NDJSON and everything else as SSE."""
    assert api_helpers.sse_format('{"x": 1}', output_format) == expected


class TestExtractApiKey:
    """Tests for extracting the API key from the Authorization header."""

    def test_bearer_key_returned(self):
        """A 'Bearer <key>' header yields the key."""
        with app.test_request_context(headers={'Authorization': 'Bearer my-secret-key'}):
            assert api_helpers.extract_api_key() == 'my-secret-key'

    def test_bearer_key_is_stripped(self):
        """Whitespace around the key is stripped."""
        with app.test_request_context(headers={'Authorization': 'Bearer   spaced-key  '}):
            assert api_helpers.extract_api_key() == 'spaced-key'

    def test_bearer_with_empty_key_returns_none(self):
        """A 'Bearer ' header with no key yields None."""
        with app.test_request_context(headers={'Authorization': 'Bearer '}):
            assert api_helpers.extract_api_key() is None

    def test_no_authorization_header_returns_none(self):
        """No Authorization header yields None."""
        with app.test_request_context():
            assert api_helpers.extract_api_key() is None

    def test_non_bearer_scheme_returns_none(self):
        """A non-Bearer scheme (e.g. Basic) yields None."""
        with app.test_request_context(headers={'Authorization': 'Basic dXNlcjpwYXNz'}):
            assert api_helpers.extract_api_key() is None


class TestExtractIdempotencyKey:
    """Tests for extracting the client idempotency key from the request headers."""

    def test_present_key_returned(self):
        """An X-Idempotency-Key header yields its value."""
        key = "9f6c1c1e-8e42-4a6f-b1a2-3c4d5e6f7a8b"
        with app.test_request_context(headers={'X-Idempotency-Key': key}):
            assert api_helpers.extract_idempotency_key() == key

    def test_key_is_stripped(self):
        """Surrounding whitespace is stripped."""
        with app.test_request_context(headers={'X-Idempotency-Key': '  abc123  '}):
            assert api_helpers.extract_idempotency_key() == 'abc123'

    def test_header_is_case_insensitive(self):
        """HTTP header names are case-insensitive."""
        with app.test_request_context(headers={'x-idempotency-key': 'abc123'}):
            assert api_helpers.extract_idempotency_key() == 'abc123'

    def test_absent_header_returns_none(self):
        """No header means a legacy client -> None."""
        with app.test_request_context():
            assert api_helpers.extract_idempotency_key() is None

    def test_empty_key_returns_none(self):
        """An empty (or whitespace-only) value is treated as absent."""
        with app.test_request_context(headers={'X-Idempotency-Key': '   '}):
            assert api_helpers.extract_idempotency_key() is None

    def test_over_length_key_returns_none(self):
        """A value longer than the contract's 128-char limit is ignored."""
        too_long = "x" * (api_helpers.MAX_IDEMPOTENCY_KEY_LENGTH + 1)
        with app.test_request_context(headers={'X-Idempotency-Key': too_long}):
            assert api_helpers.extract_idempotency_key() is None

    def test_max_length_key_is_accepted(self):
        """A value exactly at the limit is accepted."""
        at_limit = "x" * api_helpers.MAX_IDEMPOTENCY_KEY_LENGTH
        with app.test_request_context(headers={'X-Idempotency-Key': at_limit}):
            assert api_helpers.extract_idempotency_key() == at_limit


class TestWorkflowExistsForUser:
    """Tests for _workflow_exists_for_user shared-folder resolution."""

    def test_uses_shared_override_folder_from_user_config(self, mocker, tmp_path):
        """The user's sharedWorkflowsSubDirectoryOverride determines the folder checked."""
        (tmp_path / 'Workflows' / 'custom_shared' / 'my_workflow').mkdir(parents=True)
        mocker.patch(
            'Middleware.api.api_helpers.get_user_config_for',
            return_value={'sharedWorkflowsSubDirectoryOverride': 'custom_shared'}
        )
        mocker.patch(
            'Middleware.api.api_helpers.get_root_config_directory',
            return_value=str(tmp_path)
        )

        assert api_helpers._workflow_exists_for_user('my_workflow', 'alice') is True
        assert api_helpers._workflow_exists_for_user('missing_workflow', 'alice') is False

    def test_falls_back_to_shared_folder_without_override(self, mocker, tmp_path):
        """Without an override in the config, the '_shared' folder is checked."""
        (tmp_path / 'Workflows' / '_shared' / 'my_workflow').mkdir(parents=True)
        mocker.patch('Middleware.api.api_helpers.get_user_config_for', return_value={})
        mocker.patch(
            'Middleware.api.api_helpers.get_root_config_directory',
            return_value=str(tmp_path)
        )

        assert api_helpers._workflow_exists_for_user('my_workflow', 'alice') is True
        assert api_helpers._workflow_exists_for_user('missing_workflow', 'alice') is False

    def test_config_error_falls_back_to_shared_folder(self, mocker, tmp_path):
        """If the user config cannot be loaded, '_shared' is used as the folder."""
        (tmp_path / 'Workflows' / '_shared' / 'my_workflow').mkdir(parents=True)
        mocker.patch(
            'Middleware.api.api_helpers.get_user_config_for',
            side_effect=FileNotFoundError("no config")
        )
        mocker.patch(
            'Middleware.api.api_helpers.get_root_config_directory',
            return_value=str(tmp_path)
        )

        assert api_helpers._workflow_exists_for_user('my_workflow', 'alice') is True

    @pytest.mark.parametrize("unsafe_name", ['../evil', '/abs/path', 'sub/dir', '..'])
    def test_unsafe_workflow_name_rejected_before_any_lookup(self, mocker, unsafe_name):
        """The workflow name comes from the request's model field; a traversal
        or absolute value must be rejected outright, without loading any config
        or touching the filesystem (which could resolve outside the user's
        shared folder)."""
        mocker.patch(
            'Middleware.api.api_helpers.get_user_config_for',
            side_effect=AssertionError("config must not be read for an unsafe name"))
        mocker.patch(
            'Middleware.api.api_helpers.get_root_config_directory',
            side_effect=AssertionError("filesystem must not be probed for an unsafe name"))

        assert api_helpers._workflow_exists_for_user(unsafe_name, 'alice') is False
