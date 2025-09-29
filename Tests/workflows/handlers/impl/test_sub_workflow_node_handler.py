# Tests/workflows/handlers/impl/test_sub_workflow_handler.py
from unittest.mock import Mock, call

import pytest

from Middleware.workflows.handlers.impl.sub_workflow_handler import SubWorkflowHandler
from Middleware.workflows.models.execution_context import ExecutionContext


# Helper to create a consistent, mockable ExecutionContext for tests
def create_mock_context(config, stream=False, agent_outputs=None, agent_inputs=None):
    """Creates a mock ExecutionContext for testing."""
    return ExecutionContext(
        request_id="test_req_id",
        workflow_id="test_wf_id",
        discussion_id="test_disc_id",
        config=config,
        messages=[{"role": "user", "content": "hello"}],
        stream=stream,
        agent_outputs=agent_outputs or {},
        agent_inputs=agent_inputs or {},
    )


@pytest.fixture
def mock_workflow_manager():
    """Fixture for a mocked WorkflowManager."""
    return Mock()


@pytest.fixture
def mock_variable_service():
    """Fixture for a mocked WorkflowVariableManager."""
    mock_service = Mock()
    # Behavior must now be explicitly defined in each test.
    return mock_service


@pytest.fixture
def sub_workflow_handler(mock_workflow_manager, mock_variable_service):
    """Fixture for an instance of SubWorkflowHandler with mocked dependencies."""
    handler = SubWorkflowHandler(
        workflow_manager=mock_workflow_manager,
        workflow_variable_service=mock_variable_service
    )
    return handler


# ----------------------------------------
# Tests for handle()
# ----------------------------------------
def test_handle_routes_to_custom_workflow(mocker, sub_workflow_handler):
    """Verify handle() calls handle_custom_workflow for type 'CustomWorkflow'."""
    mock_handle_custom = mocker.patch.object(sub_workflow_handler, 'handle_custom_workflow',
                                             return_value="custom_result")

    context = create_mock_context({"type": "CustomWorkflow"})
    result = sub_workflow_handler.handle(context)

    mock_handle_custom.assert_called_once_with(context)
    assert result == "custom_result"


def test_handle_routes_to_conditional_custom_workflow(mocker, sub_workflow_handler):
    """Verify handle() calls handle_conditional_custom_workflow for type 'ConditionalCustomWorkflow'."""
    mock_handle_conditional = mocker.patch.object(sub_workflow_handler, 'handle_conditional_custom_workflow',
                                                  return_value="conditional_result")

    context = create_mock_context({"type": "ConditionalCustomWorkflow"})
    result = sub_workflow_handler.handle(context)

    mock_handle_conditional.assert_called_once_with(context)
    assert result == "conditional_result"


def test_handle_raises_error_on_unknown_type(sub_workflow_handler):
    """Verify handle() raises a ValueError for an unrecognized node type."""
    context = create_mock_context({"type": "UnknownWorkflowType"})

    with pytest.raises(ValueError, match="Unknown sub-workflow node type: UnknownWorkflowType"):
        sub_workflow_handler.handle(context)


# ----------------------------------------
# Tests for _prepare_scoped_inputs()
# ----------------------------------------
def test_prepare_scoped_inputs_with_variables(sub_workflow_handler, mock_variable_service):
    """Verify scoped inputs are correctly resolved using the variable service."""
    config = {
        "scoped_variables": ["{agent1Output}", "some_static_value", "{agent2Output}"]
    }
    context = create_mock_context(config)

    # Define specific return values for the mocked calls
    mock_variable_service.apply_variables.side_effect = ["resolved_output_1", "resolved_static", "resolved_output_2"]

    result = sub_workflow_handler._prepare_scoped_inputs(context)

    assert result == ["resolved_output_1", "resolved_static", "resolved_output_2"]
    # Check that apply_variables was called with the correct arguments in order
    mock_variable_service.apply_variables.assert_has_calls([
        call("{agent1Output}", context),
        call("some_static_value", context),
        call("{agent2Output}", context)
    ])


def test_prepare_scoped_inputs_empty_list(sub_workflow_handler, mock_variable_service):
    """Verify an empty 'scoped_variables' list results in an empty list."""
    context = create_mock_context({"scoped_variables": []})

    result = sub_workflow_handler._prepare_scoped_inputs(context)

    assert result == []
    mock_variable_service.apply_variables.assert_not_called()


def test_prepare_scoped_inputs_not_present(sub_workflow_handler, mock_variable_service):
    """Verify a missing 'scoped_variables' key results in an empty list."""
    context = create_mock_context({})  # No scoped_variables key

    result = sub_workflow_handler._prepare_scoped_inputs(context)

    assert result == []
    mock_variable_service.apply_variables.assert_not_called()


def test_prepare_scoped_inputs_with_none_values(sub_workflow_handler, mock_variable_service):
    """Verify None values in scoped_variables are handled correctly."""
    config = {
        "scoped_variables": [None, "valid_value", None]
    }
    context = create_mock_context(config)

    # Mock behavior: The implementation calls str() on the input before passing it to apply_variables.
    mock_variable_service.apply_variables.side_effect = lambda s, ctx: f"resolved_{s}"

    result = sub_workflow_handler._prepare_scoped_inputs(context)

    # Expecting string representation of None
    assert result == ["resolved_None", "resolved_valid_value", "resolved_None"]


# ----------------------------------------
# Tests for _prepare_workflow_overrides()
# ----------------------------------------
@pytest.mark.parametrize("context_stream, expected_non_responder, expected_streaming", [
    (True, None, True),  # Responder node
    (False, True, False)  # Non-responder node
])
def test_prepare_overrides_sets_flags_correctly(sub_workflow_handler, context_stream, expected_non_responder,
                                                expected_streaming):
    """Verify non-responder and streaming flags are set based on context.stream."""
    context = create_mock_context({}, stream=context_stream)

    _, _, non_responder, allow_streaming = sub_workflow_handler._prepare_workflow_overrides(context)

    assert non_responder is expected_non_responder
    assert allow_streaming is expected_streaming


def test_prepare_overrides_resolves_variables_from_context_config(sub_workflow_handler, mock_variable_service):
    """Verify prompt overrides are read from context.config and resolved."""
    config = {
        "firstNodeSystemPromptOverride": "system_{persona}",
        "firstNodePromptOverride": "prompt_{last_message}"
    }
    context = create_mock_context(config)

    # Define behavior
    mock_variable_service.apply_variables.side_effect = ["resolved_system_{persona}", "resolved_prompt_{last_message}"]

    system_prompt, prompt, _, _ = sub_workflow_handler._prepare_workflow_overrides(context)

    assert system_prompt == "resolved_system_{persona}"
    assert prompt == "resolved_prompt_{last_message}"
    mock_variable_service.apply_variables.assert_has_calls([
        call("system_{persona}", context),
        call("prompt_{last_message}", context)
    ])


def test_prepare_overrides_uses_overrides_config_when_provided(sub_workflow_handler, mock_variable_service):
    """Verify prompt overrides are read from overrides_config if it's passed."""
    context_config = {"systemPromptOverride": "context_system"}
    overrides_config = {"systemPromptOverride": "override_system"}
    context = create_mock_context(context_config)

    # Define behavior
    mock_variable_service.apply_variables.return_value = "resolved_override_system"

    system_prompt, _, _, _ = sub_workflow_handler._prepare_workflow_overrides(context,
                                                                              overrides_config=overrides_config)

    assert system_prompt == "resolved_override_system"
    mock_variable_service.apply_variables.assert_called_once_with("override_system", context)


@pytest.mark.parametrize("system_key, prompt_key", [
    ("firstNodeSystemPromptOverride", "firstNodePromptOverride"),  # New keys
    ("systemPromptOverride", "promptOverride")  # Legacy keys
])
def test_prepare_overrides_handles_different_key_names(sub_workflow_handler, mock_variable_service, system_key,
                                                       prompt_key):
    """Verify both new and legacy override keys are supported."""
    config = {
        system_key: "system_value",
        prompt_key: "prompt_value"
    }
    context = create_mock_context(config)

    # Define behavior
    mock_variable_service.apply_variables.side_effect = ["resolved_system_value", "resolved_prompt_value"]

    system_prompt, prompt, _, _ = sub_workflow_handler._prepare_workflow_overrides(context)

    assert system_prompt == "resolved_system_value"
    assert prompt == "resolved_prompt_value"


def test_prepare_overrides_handles_null_and_empty_prompts(sub_workflow_handler, mock_variable_service):
    """Verify that None or empty string overrides are handled gracefully and return None."""
    config = {
        "firstNodeSystemPromptOverride": None,
        "firstNodePromptOverride": ""
    }
    context = create_mock_context(config)

    system_prompt, prompt, _, _ = sub_workflow_handler._prepare_workflow_overrides(context)

    assert system_prompt is None
    assert prompt is None
    mock_variable_service.apply_variables.assert_not_called()


def test_prepare_overrides_prefers_new_keys_over_legacy(sub_workflow_handler, mock_variable_service):
    """Verify that new keys take precedence over legacy keys when both are present."""
    config = {
        "firstNodeSystemPromptOverride": "new_system",
        "systemPromptOverride": "legacy_system",
        "firstNodePromptOverride": "new_prompt",
        "promptOverride": "legacy_prompt"
    }
    context = create_mock_context(config)

    # Define behavior
    mock_variable_service.apply_variables.side_effect = ["resolved_new_system", "resolved_new_prompt"]

    system_prompt, prompt, _, _ = sub_workflow_handler._prepare_workflow_overrides(context)

    assert system_prompt == "resolved_new_system"
    assert prompt == "resolved_new_prompt"
    # Ensure the calls used the new keys
    mock_variable_service.apply_variables.assert_has_calls([
        call("new_system", context),
        call("new_prompt", context)
    ])


# ----------------------------------------
# Tests for handle_custom_workflow()
# ----------------------------------------
def test_handle_custom_workflow_calls_manager(mocker, sub_workflow_handler, mock_workflow_manager):
    """Verify handle_custom_workflow correctly calls the workflow manager."""
    # Mock helper methods to isolate the test
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=("resolved_system", "resolved_prompt", None, True))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=["resolved_input_1"])

    config = {
        "workflowName": "MySubWorkflow",
        "workflowUserFolderOverride": "test_user"
    }
    context = create_mock_context(config, stream=True)

    sub_workflow_handler.handle_custom_workflow(context)

    mock_workflow_manager.run_custom_workflow.assert_called_once_with(
        workflow_name="MySubWorkflow",
        request_id=context.request_id,
        discussion_id=context.discussion_id,
        messages=context.messages,
        non_responder=None,
        is_streaming=True,
        first_node_system_prompt_override="resolved_system",
        first_node_prompt_override="resolved_prompt",
        scoped_inputs=["resolved_input_1"],
        workflow_user_folder_override="test_user"
    )


def test_handle_custom_workflow_with_default_workflow_name(mocker, sub_workflow_handler, mock_workflow_manager):
    """Verify handle_custom_workflow uses default name when workflowName is missing."""
    # Mock return values consistent with a non-streaming context (default for create_mock_context)
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    config = {}  # No workflowName
    context = create_mock_context(config)

    sub_workflow_handler.handle_custom_workflow(context)

    # Check that the default workflow name is used
    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == "No_Workflow_Name_Supplied"


def test_handle_custom_workflow_without_folder_override(mocker, sub_workflow_handler, mock_workflow_manager):
    """Verify handle_custom_workflow works without workflowUserFolderOverride."""
    # Mock return values consistent with a non-streaming context (default for create_mock_context)
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    config = {"workflowName": "TestWorkflow"}  # No workflowUserFolderOverride
    context = create_mock_context(config)

    sub_workflow_handler.handle_custom_workflow(context)

    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_user_folder_override'] is None
    assert call_args.kwargs['non_responder'] is True


# ----------------------------------------
# Tests for handle_conditional_custom_workflow()
# ----------------------------------------
@pytest.mark.parametrize("key_value, expected_workflow", [
    ("route_a", "WorkflowA"),  # Direct match
    ("ROUTE_A", "WorkflowA"),  # Case-insensitive match
    ("Route_A", "WorkflowA"),  # Mixed case match
    ("unknown_route", "DefaultWorkflow"),  # Fallback to default
    ("", "DefaultWorkflow"),  # Empty string fallback
    ("    route_a    ", "WorkflowA"),  # Whitespace handling
    ("another_unknown", "No_Workflow_Name_Supplied")  # Fallback when no default
])
def test_handle_conditional_selects_correct_workflow(mocker, sub_workflow_handler, mock_variable_service,
                                                     mock_workflow_manager, key_value, expected_workflow):
    """Verify conditional logic correctly selects the workflow name."""
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    # For this test, we need to return the actual key value when apply_variables is called
    # This simulates the variable being resolved to the test value
    mock_variable_service.apply_variables.return_value = key_value

    config = {
        "conditionalKey": "{some_variable}",
        "conditionalWorkflows": {
            "route_a": "WorkflowA",
            "route_b": "WorkflowB",
            "default": "DefaultWorkflow"
        }
    }

    # Remove default for the specific test case that needs it
    if key_value.strip().lower() == "another_unknown":
        del config["conditionalWorkflows"]["default"]

    context = create_mock_context(config)
    sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Check the 'workflow_name' keyword argument from the mock call
    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == expected_workflow


def test_handle_conditional_applies_route_overrides(mocker, sub_workflow_handler, mock_variable_service,
                                                    mock_workflow_manager):
    """Verify that specific route overrides are passed to the prepare method."""
    mock_prepare_overrides = mocker.patch.object(
        sub_workflow_handler,
        '_prepare_workflow_overrides',
        return_value=(None, None, True, False)
    )
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    # Return the actual route key
    mock_variable_service.apply_variables.return_value = "route_a"

    route_overrides_config = {
        "systemPromptOverride": "System override for Route A"
    }
    config = {
        "conditionalKey": "{var}",
        "conditionalWorkflows": {"route_a": "WorkflowA"},
        "routeOverrides": {
            # The logic in the handler now lowercases the keys for matching
            "ROUTE_A": route_overrides_config
        }
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Assert that _prepare_workflow_overrides was called with the correct override dictionary
    mock_prepare_overrides.assert_called_once_with(context, overrides_config=route_overrides_config)
    mock_workflow_manager.run_custom_workflow.assert_called_once()


def test_handle_conditional_no_route_overrides(mocker, sub_workflow_handler, mock_variable_service,
                                               mock_workflow_manager):
    """Verify that empty overrides are passed when no route overrides match."""
    mock_prepare_overrides = mocker.patch.object(
        sub_workflow_handler,
        '_prepare_workflow_overrides',
        return_value=(None, None, True, False)
    )
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    mock_variable_service.apply_variables.return_value = "route_b"

    config = {
        "conditionalKey": "{var}",
        "conditionalWorkflows": {"route_b": "WorkflowB"},
        "routeOverrides": {
            "route_a": {"systemPromptOverride": "Override for A"}  # No override for route_b
        }
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Should be called with empty overrides_config
    mock_prepare_overrides.assert_called_once_with(context, overrides_config={})


def test_handle_conditional_missing_conditional_key(mocker, sub_workflow_handler, mock_variable_service,
                                                    mock_workflow_manager):
    """Verify behavior when conditionalKey is missing."""
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    config = {
        # No conditionalKey
        "conditionalWorkflows": {
            "default": "DefaultWorkflow"
        }
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Should use default workflow since key is empty
    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == "DefaultWorkflow"
    # apply_variables should not be called when conditionalKey is None
    mock_variable_service.apply_variables.assert_not_called()


def test_handle_conditional_empty_workflows_map(mocker, sub_workflow_handler, mock_variable_service,
                                                mock_workflow_manager):
    """Verify behavior when conditionalWorkflows is empty."""
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    mock_variable_service.apply_variables.return_value = "some_key"

    config = {
        "conditionalKey": "{var}",
        "conditionalWorkflows": {}  # Empty map
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Should use the hardcoded default
    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == "No_Workflow_Name_Supplied"


# ---------------------------------------------------------------------------
# START: Tests for 'UseDefaultContentInsteadOfWorkflow' feature
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_streaming", [True, False])
def test_handle_conditional_uses_default_content_when_no_match(mocker, sub_workflow_handler, mock_variable_service,
                                                               mock_workflow_manager, is_streaming):
    """
    Verify it returns static default content when no workflow matches, for both streaming and non-streaming.
    """
    # Mock the static content streamer for the streaming case
    mock_streamer = mocker.patch('Middleware.workflows.handlers.impl.sub_workflow_handler.stream_static_content',
                                 return_value="stream_generator")

    # When apply_variables is called for the conditional key, return a value that won't match.
    # When called for the default content, it should just return the content itself.
    def apply_vars_side_effect(value, context):
        if value == "{some_variable}":
            return "unmatched_route"
        if value == "Sorry, no match found.":
            return "Sorry, no match found."
        return value

    mock_variable_service.apply_variables.side_effect = apply_vars_side_effect

    config = {
        "conditionalKey": "{some_variable}",
        "conditionalWorkflows": {
            "route_a": "WorkflowA"
        },
        "UseDefaultContentInsteadOfWorkflow": "Sorry, no match found."
    }
    context = create_mock_context(config, stream=is_streaming)

    result = sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Assertions
    mock_workflow_manager.run_custom_workflow.assert_not_called()
    if is_streaming:
        mock_streamer.assert_called_once_with("Sorry, no match found.")
        assert result == "stream_generator"
    else:
        mock_streamer.assert_not_called()
        assert result == "Sorry, no match found."


@pytest.mark.parametrize("is_streaming", [True, False])
def test_handle_conditional_uses_default_content_with_variables(mocker, sub_workflow_handler, mock_variable_service,
                                                                mock_workflow_manager, is_streaming):
    """
    Verify it resolves variables in default content, for both streaming and non-streaming.
    """
    mock_streamer = mocker.patch('Middleware.workflows.handlers.impl.sub_workflow_handler.stream_static_content',
                                 return_value="stream_generator")

    # Define mock behavior for the variable service
    def apply_vars_side_effect(value, context):
        if value == "{some_variable}":
            return "unmatched_route"
        if value == "Sorry, {agent1Output} is not supported.":
            return "Sorry, Rust is not supported."
        return value

    mock_variable_service.apply_variables.side_effect = apply_vars_side_effect

    config = {
        "conditionalKey": "{some_variable}",
        "conditionalWorkflows": {"route_a": "WorkflowA"},
        "UseDefaultContentInsteadOfWorkflow": "Sorry, {agent1Output} is not supported."
    }
    context = create_mock_context(config, stream=is_streaming, agent_outputs={"agent1Output": "Rust"})

    result = sub_workflow_handler.handle_conditional_custom_workflow(context)

    mock_workflow_manager.run_custom_workflow.assert_not_called()
    # Ensure apply_variables was called for the default content template
    mock_variable_service.apply_variables.assert_any_call("Sorry, {agent1Output} is not supported.", context)

    if is_streaming:
        mock_streamer.assert_called_once_with("Sorry, Rust is not supported.")
        assert result == "stream_generator"
    else:
        mock_streamer.assert_not_called()
        assert result == "Sorry, Rust is not supported."


def test_handle_conditional_ignores_default_content_when_match_found(mocker, sub_workflow_handler,
                                                                     mock_variable_service, mock_workflow_manager):
    """
    Verify 'UseDefaultContentInsteadOfWorkflow' is ignored if a direct workflow match is found.
    """
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides', return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])
    mock_streamer = mocker.patch('Middleware.workflows.handlers.impl.sub_workflow_handler.stream_static_content')

    # Simulate resolving the conditional key to a matching route
    mock_variable_service.apply_variables.return_value = "route_a"

    config = {
        "conditionalKey": "{some_variable}",
        "conditionalWorkflows": {
            "route_a": "WorkflowA"
        },
        "UseDefaultContentInsteadOfWorkflow": "This should be ignored."
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    # Assertions
    mock_workflow_manager.run_custom_workflow.assert_called_once()
    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == "WorkflowA"
    mock_streamer.assert_not_called()
    # Make sure the variable service was not called on the default content
    for call_obj in mock_variable_service.apply_variables.call_args_list:
        assert call_obj.args[0] != "This should be ignored."


# -------------------------------------------------------------------------
# END: Tests for 'UseDefaultContentInsteadOfWorkflow' feature
# -------------------------------------------------------------------------

# ----------------------------------------
# Integration tests
# ----------------------------------------
def test_full_custom_workflow_flow_streaming(sub_workflow_handler, mock_workflow_manager, mock_variable_service):
    """Test the full flow of a custom workflow with streaming enabled."""
    config = {
        "type": "CustomWorkflow",
        "workflowName": "StreamingWorkflow",
        "firstNodeSystemPromptOverride": "System: {agent1Input}",
        "firstNodePromptOverride": "Prompt: {agent1Output}",
        "scoped_variables": ["{agent1Output}", "{agent2Output}"],
        "workflowUserFolderOverride": "user123"
    }

    agent_outputs = {"agent1Output": "output1", "agent2Output": "output2"}
    agent_inputs = {"agent1Input": "input1"}
    context = create_mock_context(config, stream=True, agent_outputs=agent_outputs, agent_inputs=agent_inputs)

    # Mock variable service to resolve variables dynamically based on input
    def resolve_vars(s, ctx):
        if s == "System: {agent1Input}":
            return "System: input1"
        elif s == "Prompt: {agent1Output}":
            return "Prompt: output1"
        elif s == "{agent1Output}":
            return "output1"
        elif s == "{agent2Output}":
            return "output2"
        return s

    mock_variable_service.apply_variables.side_effect = resolve_vars
    mock_workflow_manager.run_custom_workflow.return_value = "streaming_result"

    result = sub_workflow_handler.handle(context)

    assert result == "streaming_result"
    mock_workflow_manager.run_custom_workflow.assert_called_once_with(
        workflow_name="StreamingWorkflow",
        request_id="test_req_id",
        discussion_id="test_disc_id",
        messages=[{"role": "user", "content": "hello"}],
        non_responder=None,
        is_streaming=True,
        first_node_system_prompt_override="System: input1",
        first_node_prompt_override="Prompt: output1",
        scoped_inputs=["output1", "output2"],
        workflow_user_folder_override="user123"
    )


def test_full_conditional_workflow_flow_non_streaming(sub_workflow_handler, mock_workflow_manager,
                                                      mock_variable_service):
    """Test the full flow of a conditional workflow with streaming disabled."""
    config = {
        "type": "ConditionalCustomWorkflow",
        "conditionalKey": "{routeVariable}",
        "conditionalWorkflows": {
            "api": "APIWorkflow",
            "database": "DatabaseWorkflow",
            "default": "DefaultWorkflow"
        },
        "routeOverrides": {
            "API": {
                "systemPromptOverride": "API System Prompt"
            },
            "Database": {
                "promptOverride": "Database Prompt"
            }
        },
        "scoped_variables": ["{lastResult}"]
    }

    agent_outputs = {"routeVariable": "DATABASE", "lastResult": "db_data"}
    context = create_mock_context(config, stream=False, agent_outputs=agent_outputs)

    # Mock variable service dynamically based on input
    def resolve_vars(s, ctx):
        if s == "{routeVariable}":
            return "DATABASE"
        elif s == "{lastResult}":
            return "db_data"
        elif s == "Database Prompt":
            return "Resolved Database Prompt"
        return s

    mock_variable_service.apply_variables.side_effect = resolve_vars
    mock_workflow_manager.run_custom_workflow.return_value = "database_result"

    result = sub_workflow_handler.handle(context)

    assert result == "database_result"
    mock_workflow_manager.run_custom_workflow.assert_called_once_with(
        workflow_name="DatabaseWorkflow",
        request_id="test_req_id",
        discussion_id="test_disc_id",
        messages=[{"role": "user", "content": "hello"}],
        non_responder=True,
        is_streaming=False,
        first_node_system_prompt_override=None,
        first_node_prompt_override="Resolved Database Prompt",
        scoped_inputs=["db_data"],
        workflow_user_folder_override=None
    )


# ----------------------------------------
# Edge case tests
# ----------------------------------------
def test_handle_conditional_with_numeric_keys(mocker, sub_workflow_handler, mock_variable_service,
                                              mock_workflow_manager):
    """Test that numeric conditional keys are handled properly."""
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    # Define behavior
    mock_variable_service.apply_variables.return_value = "123"

    config = {
        "conditionalKey": "{numeric_var}",
        "conditionalWorkflows": {
            "123": "NumericWorkflow",
            "default": "DefaultWorkflow"
        }
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == "NumericWorkflow"


def test_handle_conditional_with_special_characters(mocker, sub_workflow_handler, mock_variable_service,
                                                    mock_workflow_manager):
    """Test that special characters in keys are handled properly."""
    mocker.patch.object(sub_workflow_handler, '_prepare_workflow_overrides',
                        return_value=(None, None, True, False))
    mocker.patch.object(sub_workflow_handler, '_prepare_scoped_inputs', return_value=[])

    # Define behavior
    mock_variable_service.apply_variables.return_value = "route-with-dash"

    config = {
        "conditionalKey": "{special_var}",
        "conditionalWorkflows": {
            "route-with-dash": "DashWorkflow",
            "route_with_underscore": "UnderscoreWorkflow"
        }
    }
    context = create_mock_context(config)

    sub_workflow_handler.handle_conditional_custom_workflow(context)

    call_args = mock_workflow_manager.run_custom_workflow.call_args
    assert call_args.kwargs['workflow_name'] == "DashWorkflow"
