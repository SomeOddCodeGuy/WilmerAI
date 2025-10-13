# Tests/workflows/processors/test_workflows_processor.py

import copy
from unittest.mock import Mock, patch, ANY

import pytest

from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.llm_service import LlmHandlerService
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

# Define the set of types we expect to be valid during testing.
MOCK_VALID_TYPES = ["Standard", "Tool", "CustomWorkflow", "ConditionalCustomWorkflow", "StaticResponse"]


# ##################################
# ##### Fixtures
# ##################################

@pytest.fixture
def mock_node_handlers():
    """Provides a dictionary of mocked node handlers."""
    mock_workflow_manager = Mock()
    standard_handler = Mock(name="StandardHandler")
    custom_workflow_handler = Mock(name="CustomWorkflowHandler")
    tool_handler = Mock(name="ToolHandler")
    static_response_handler = Mock(name="StaticResponseHandler")

    custom_workflow_handler.workflow_manager = mock_workflow_manager

    return {
        "Standard": standard_handler,
        "CustomWorkflow": custom_workflow_handler,
        "Tool": tool_handler,
        "StaticResponse": static_response_handler,
    }


@pytest.fixture
def mock_llm_handler_service():
    """Mocks the LlmHandlerService."""
    service = Mock(spec=LlmHandlerService)
    service.load_model_from_config.return_value = Mock()
    return service


@pytest.fixture
def mock_workflow_variable_service():
    """Mocks the WorkflowVariableManager."""
    return Mock(spec=WorkflowVariableManager)


@pytest.fixture
def mock_internal_services(mocker):
    """Mocks services instantiated internally by the WorkflowProcessor."""
    mock_locking_service = mocker.patch('Middleware.workflows.processors.workflows_processor.LockingService')
    mock_timestamp_service = mocker.patch('Middleware.workflows.processors.workflows_processor.TimestampService')
    return {
        "locking": mock_locking_service.return_value,
        "timestamp": mock_timestamp_service.return_value,
    }


@pytest.fixture
def mock_processor_utils(mocker):
    """Mocks utility functions and constants used directly by the WorkflowProcessor."""
    mocker.patch('Middleware.workflows.processors.workflows_processor.get_endpoint_config', return_value={})
    mocker.patch('Middleware.workflows.processors.workflows_processor.get_chat_template_name', return_value="default")
    mocker.patch('Middleware.workflows.processors.workflows_processor.VALID_NODE_TYPES', MOCK_VALID_TYPES)
    mock_post_process = mocker.patch('Middleware.workflows.processors.workflows_processor.post_process_llm_output',
                                     side_effect=lambda content, ep_config, node_config: content)
    return {
        "post_process": mock_post_process,
    }


@pytest.fixture
def workflow_processor_factory(mock_llm_handler_service, mock_workflow_variable_service, mock_node_handlers,
                               mock_internal_services, mock_processor_utils):
    """A factory fixture to create WorkflowProcessor instances with specific configurations."""

    def _factory(configs, stream=False, discussion_id="disc-123", messages=None, non_responder_flag=None,
                 overrides=None, scoped_inputs=None):
        if messages is None:
            messages = [{"role": "user", "content": "hello"}]
        if overrides is None:
            overrides = {}

        configs_copy = copy.deepcopy(configs)

        return WorkflowProcessor(
            node_handlers=mock_node_handlers,
            llm_handler_service=mock_llm_handler_service,
            workflow_variable_service=mock_workflow_variable_service,
            workflow_config_name="TestWorkflow",
            workflow_file_config={"top_level_var": "value", "nodes": configs_copy},
            configs=configs_copy,
            request_id="req-123",
            workflow_id="wf-123",
            discussion_id=discussion_id,
            messages=messages,
            stream=stream,
            non_responder_flag=non_responder_flag,
            first_node_system_prompt_override=overrides.get("systemPrompt"),
            first_node_prompt_override=overrides.get("prompt"),
            scoped_inputs=scoped_inputs
        )

    return _factory


# ##################################
# ##### Test Cases
# ##################################

class TestWorkflowProcessorExecution:
    """Tests the main execute() method and overall orchestration."""

    def test_execute_single_node_non_streaming(self, workflow_processor_factory, mock_node_handlers):
        """Verifies the execution of a simple, single-node workflow (non-streaming)."""
        config = [{"type": "Standard", "endpointName": "TestEndpoint"}]
        expected_response = "LLM response."
        mock_node_handlers["Standard"].handle.return_value = expected_response
        processor = workflow_processor_factory(configs=config, stream=False)

        result_list = list(processor.execute())

        assert result_list == [expected_response]
        mock_node_handlers["Standard"].handle.assert_called_once()
        context = mock_node_handlers["Standard"].handle.call_args[0][0]
        assert isinstance(context, ExecutionContext)
        assert context.stream is False

    def test_execute_multi_node_state_passing(self, workflow_processor_factory, mock_node_handlers):
        """Verifies that outputs from earlier nodes are available in the ExecutionContext of later nodes."""
        config = [{"type": "Standard", "title": "Node 1"}, {"type": "Tool", "title": "Node 2"}]
        mock_node_handlers["Standard"].handle.return_value = "Output 1"
        mock_node_handlers["Tool"].handle.return_value = "Final Output"
        processor = workflow_processor_factory(configs=config, stream=False)

        list(processor.execute())

        mock_node_handlers["Tool"].handle.assert_called_once()
        context_node2 = mock_node_handlers["Tool"].handle.call_args[0][0]
        assert context_node2.agent_outputs["agent1Output"] == "Output 1"

    def test_execute_responder_logic(self, workflow_processor_factory, mock_node_handlers):
        """Verifies that only the designated responder node returns to the user, and subsequent nodes still execute."""
        config = [
            {"type": "Standard", "title": "N1"},
            {"type": "Standard", "title": "N2 (Responder)", "returnToUser": True},
            {"type": "Standard", "title": "N3 (Post)"},
        ]
        mock_node_handlers["Standard"].handle.side_effect = ["Out1", "Out2 User", "Out3"]
        processor = workflow_processor_factory(configs=config, stream=False)

        result_list = list(processor.execute())

        assert result_list == ["Out2 User"]
        assert mock_node_handlers["Standard"].handle.call_count == 3

    def test_execute_last_node_is_implicit_responder(self, workflow_processor_factory, mock_node_handlers):
        """Verifies the last node is a responder by default if no other responder is set."""
        config = [{"type": "Standard"}, {"type": "StaticResponse"}]  # No 'returnToUser'
        mock_node_handlers["Standard"].handle.return_value = "Internal result"
        mock_node_handlers["StaticResponse"].handle.return_value = "Final result"
        processor = workflow_processor_factory(configs=config)

        result = list(processor.execute())

        assert result == ["Final result"]
        assert mock_node_handlers["Standard"].handle.call_count == 1
        assert mock_node_handlers["StaticResponse"].handle.call_count == 1
        # The first node was not a responder
        context1 = mock_node_handlers["Standard"].handle.call_args[0][0]
        assert context1.stream is False
        # The second (last) node *was* a responder
        context2 = mock_node_handlers["StaticResponse"].handle.call_args[0][0]
        assert context2.stream is False  # The processor's stream flag is False

    def test_execute_prompt_overrides(self, workflow_processor_factory, mock_node_handlers):
        """Verifies that prompt overrides are applied to the first node with a prompt field."""
        config = [
            {"type": "Tool"},
            {"type": "Standard", "systemPrompt": "Original Sys", "prompt": "Original Prompt"},
            {"type": "Standard", "systemPrompt": "Sys 3", "prompt": "Prompt 3"},
        ]
        mock_node_handlers["Tool"].handle.return_value = "Tool Output"
        mock_node_handlers["Standard"].handle.return_value = "Standard Output"
        overrides = {"systemPrompt": "Overridden Sys", "prompt": "Overridden Prompt"}
        processor = workflow_processor_factory(configs=config, overrides=overrides)

        list(processor.execute())

        assert mock_node_handlers["Tool"].handle.call_count == 1
        assert mock_node_handlers["Standard"].handle.call_count == 2

        context_node2 = mock_node_handlers["Standard"].handle.call_args_list[0].args[0]
        assert context_node2.config["systemPrompt"] == "Overridden Sys"
        assert context_node2.config["prompt"] == "Overridden Prompt"

        context_node3 = mock_node_handlers["Standard"].handle.call_args_list[1].args[0]
        assert context_node3.config["systemPrompt"] == "Sys 3"
        assert context_node3.config["prompt"] == "Prompt 3"

    def test_execute_scoped_inputs(self, workflow_processor_factory, mock_node_handlers):
        """Verifies that scoped inputs are correctly mapped and available in the context."""
        config = [{"type": "Standard"}]
        scoped_inputs = ["Input 1", "Input 2"]
        processor = workflow_processor_factory(configs=config, scoped_inputs=scoped_inputs)

        list(processor.execute())

        context = mock_node_handlers["Standard"].handle.call_args[0][0]
        expected_inputs = {"agent1Input": "Input 1", "agent2Input": "Input 2"}
        assert context.agent_inputs == expected_inputs
        assert context.agent_outputs == expected_inputs

    @patch('Middleware.workflows.processors.workflows_processor.StreamingResponseHandler')
    def test_execute_streaming_custom_workflow_passes_through(self, mock_stream_handler_cls, workflow_processor_factory,
                                                              mock_node_handlers):
        """Tests that pre-formatted SSE streams from CustomWorkflow nodes are passed through directly."""
        sse_generator = (x for x in ["data: sub-chunk\n\n", "data: [DONE]\n\n"])
        mock_node_handlers["CustomWorkflow"].handle.return_value = sse_generator
        configs = [{"type": "CustomWorkflow", "returnToUser": True}]
        processor = workflow_processor_factory(configs=configs, stream=True)

        result = list(processor.execute())

        assert result == ["data: sub-chunk\n\n", "data: [DONE]\n\n"]
        # The crucial assertion: the main processor's StreamingResponseHandler is NOT used.
        mock_stream_handler_cls.assert_not_called()


class TestWorkflowProcessorTimestamping:
    """Tests the integration between WorkflowProcessor and TimestampService."""

    def test_timestamp_tracking_is_gated_by_flag(self, workflow_processor_factory, mock_internal_services):
        """Verifies that resolve_and_track_history is ONLY called if at least one node has the timestamp flag."""
        configs = [{"type": "Standard", "addDiscussionIdTimestampsForLLM": False}]
        processor = workflow_processor_factory(configs=configs)
        list(processor.execute())
        mock_internal_services["timestamp"].resolve_and_track_history.assert_not_called()

        mock_internal_services["timestamp"].reset_mock()

        configs = [{"type": "Standard", "addDiscussionIdTimestampsForLLM": True}]
        processor = workflow_processor_factory(configs=configs)
        list(processor.execute())
        mock_internal_services["timestamp"].resolve_and_track_history.assert_called_once_with(
            processor.messages, processor.discussion_id
        )

    def test_responder_skips_commit_when_group_chat_logic_is_off(self, workflow_processor_factory,
                                                                 mock_node_handlers, mock_internal_services):
        """Verifies placeholder is saved but NOT committed for a response when group chat logic is off."""
        config = [{"type": "Standard", "returnToUser": True, "addDiscussionIdTimestampsForLLM": True,
                   "useGroupChatTimestampLogic": False}]
        mock_node_handlers["Standard"].handle.return_value = "The LLM response."
        processor = workflow_processor_factory(configs=config, stream=False, discussion_id="disc-123")
        mock_timestamp_service = mock_internal_services["timestamp"]

        list(processor.execute())

        mock_timestamp_service.save_placeholder_timestamp.assert_called_once_with("disc-123")
        mock_timestamp_service.commit_assistant_response.assert_not_called()

    @patch('Middleware.workflows.processors.workflows_processor.StreamingResponseHandler')
    def test_responder_skips_commit_when_group_chat_logic_is_off_streaming(self, mock_stream_handler_cls,
                                                                           workflow_processor_factory,
                                                                           mock_node_handlers,
                                                                           mock_internal_services):
        """Verifies placeholder is saved but NOT committed for a streaming response when group chat logic is off."""
        config = [{"type": "Standard", "returnToUser": True, "addDiscussionIdTimestampsForLLM": True,
                   "useGroupChatTimestampLogic": False}]
        mock_stream_handler_instance = mock_stream_handler_cls.return_value
        mock_stream_handler_instance.full_response_text = "Assembled text"
        processor = workflow_processor_factory(configs=config, stream=True, discussion_id="disc-123")
        mock_timestamp_service = mock_internal_services["timestamp"]

        list(processor.execute())

        mock_timestamp_service.save_placeholder_timestamp.assert_called_once_with("disc-123")
        mock_timestamp_service.commit_assistant_response.assert_not_called()

    def test_responder_commits_timestamp_when_group_chat_logic_is_on(self, workflow_processor_factory,
                                                                     mock_node_handlers,
                                                                     mock_internal_services):
        """Verifies placeholder is saved AND committed when group chat logic is ON."""
        config = [{"type": "Standard", "returnToUser": True, "addDiscussionIdTimestampsForLLM": True,
                   "useGroupChatTimestampLogic": True}]
        final_result = "The LLM response."
        mock_node_handlers["Standard"].handle.return_value = final_result
        processor = workflow_processor_factory(configs=config, stream=False, discussion_id="disc-123")
        mock_timestamp_service = mock_internal_services["timestamp"]

        list(processor.execute())

        mock_timestamp_service.save_placeholder_timestamp.assert_called_once_with("disc-123")
        mock_timestamp_service.commit_assistant_response.assert_called_once_with("disc-123", final_result)

    @patch('Middleware.workflows.processors.workflows_processor.StreamingResponseHandler')
    def test_responder_commits_timestamp_when_group_chat_logic_is_on_streaming(self, mock_stream_handler_cls,
                                                                               workflow_processor_factory,
                                                                               mock_node_handlers,
                                                                               mock_internal_services):
        """Verifies placeholder is saved AND committed after a stream when group chat logic is ON."""
        config = [
            {"type": "Standard", "endpointName": "EP", "returnToUser": True, "addDiscussionIdTimestampsForLLM": True,
             "useGroupChatTimestampLogic": True}]
        mock_node_handlers["Standard"].handle.return_value = (x for x in ["raw"])
        mock_stream_handler_instance = mock_stream_handler_cls.return_value
        mock_stream_handler_instance.process_stream.return_value = (x for x in ["processed"])
        full_response_text = "Assembled stream text."
        mock_stream_handler_instance.full_response_text = full_response_text
        processor = workflow_processor_factory(configs=config, stream=True, discussion_id="disc-123")
        mock_timestamp_service = mock_internal_services["timestamp"]

        list(processor.execute())

        mock_timestamp_service.save_placeholder_timestamp.assert_called_once_with("disc-123")
        mock_timestamp_service.commit_assistant_response.assert_called_once_with("disc-123", full_response_text)


class TestWorkflowProcessorRobustness:
    """Tests for exception handling and graceful failures."""

    def test_execute_early_termination_and_cleanup(self, workflow_processor_factory, mock_node_handlers,
                                                   mock_internal_services):
        """Verifies EarlyTerminationException stops the workflow and ensures locks are released."""
        config = [{"type": "Tool"}, {"type": "Standard"}]
        mock_node_handlers["Tool"].handle.side_effect = EarlyTerminationException("Stop.")
        processor = workflow_processor_factory(configs=config)
        mock_locking = mock_internal_services["locking"]

        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        mock_node_handlers["Tool"].handle.assert_called_once()
        mock_node_handlers["Standard"].handle.assert_not_called()
        mock_locking.delete_node_locks.assert_called_once()

    def test_execute_cleanup_on_generic_exception(self, workflow_processor_factory, mock_node_handlers,
                                                  mock_internal_services):
        """Verifies that the locking service cleanup is called even if a generic exception occurs."""
        mock_node_handlers["Standard"].handle.side_effect = ValueError("Something unexpected went wrong")
        processor = workflow_processor_factory(configs=[{"type": "Standard"}])
        mock_locking_service = mock_internal_services["locking"]

        with pytest.raises(ValueError):
            list(processor.execute())

        mock_locking_service.delete_node_locks.assert_called_once_with(ANY, "wf-123")

    def test_execute_invalid_node_type_defaults_to_standard(self, workflow_processor_factory, mock_node_handlers,
                                                            caplog):
        """Verifies that an unknown node type defaults to 'Standard' and logs a warning."""
        configs = [{"type": "InvalidNodeType", "endpointName": "test-ep"}]
        processor = workflow_processor_factory(configs=configs)

        list(processor.execute())

        assert "'InvalidNodeType' is not a valid node type. Defaulting to 'Standard'." in caplog.text
        mock_node_handlers["Standard"].handle.assert_called_once()


class TestWorkflowProcessorHelpers:
    """Tests the internal helper methods of the WorkflowProcessor."""

    @pytest.mark.parametrize("messages, expected", [
        (None, None),
        ([], None),
        ([{"role": "user", "content": "Hello"}], None),
        ([{"role": "user", "content": "This is a long message that is definitely not a prompt."}], None),
        ([{"role": "assistant", "content": "AssistantName:"}], "AssistantName:"),
        ([{"role": "user", "content": "UserName: "}], "UserName:"),
    ])
    def test_identify_generation_prompt(self, workflow_processor_factory, messages, expected):
        """Tests the heuristic for identifying a generation prompt."""
        processor = workflow_processor_factory(configs=[], messages=messages)
        assert processor._identify_generation_prompt() == expected

    @pytest.mark.parametrize("llm_output, gen_prompt, expected", [
        ("the response.", "Roland:", "Roland: the response."),
        ("Roland: the response.", "Roland:", "Roland: the response."),
        ("    Assistant: a response.", "User:", "Assistant: a response."),
        ("", "Roland:", "Roland: "),
        (12345, "Roland:", 12345)
    ])
    def test_reconstruct_non_streaming(self, workflow_processor_factory, llm_output, gen_prompt, expected):
        """Tests the logic for reconstructing group chat messages for non-streaming responses."""
        processor = workflow_processor_factory(configs=[])
        assert processor._reconstruct_non_streaming(llm_output, gen_prompt) == expected


class TestEndpointAndPresetVariableSubstitution:
    """Tests for endpoint and preset variable substitution - covering the critical gap that caused the bug."""

    def test_both_hardcoded_no_variables(self, workflow_processor_factory, mock_node_handlers,
                                        mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that BOTH hardcoded endpoints and presets WITHOUT variables work correctly - most common case."""
        config = [{"type": "Standard", "endpointName": "HardcodedEndpoint", "preset": "HardcodedPreset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        processor = workflow_processor_factory(configs=config, stream=False)

        list(processor.execute())

        # CRITICAL: apply_early_variables should NOT be called at all for fully hardcoded configs
        mock_workflow_variable_service.apply_early_variables.assert_not_called()
        # The endpoint and preset should be used directly
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "HardcodedEndpoint", "HardcodedPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_hardcoded_endpoint_variable_preset(self, workflow_processor_factory, mock_node_handlers,
                                               mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that hardcoded endpoint with variable preset works correctly."""
        config = [{"type": "Standard", "endpointName": "HardcodedEndpoint", "preset": "{agent1Input}"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "DynamicPreset"
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["MyPreset"])

        list(processor.execute())

        # apply_early_variables should be called ONLY for the preset, not the endpoint
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args[0]
        assert call_args[0] == "{agent1Input}"  # Only the preset

        # The hardcoded endpoint with resolved preset should be used
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "HardcodedEndpoint", "DynamicPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_endpoint_with_agent_input_variable(self, workflow_processor_factory, mock_node_handlers,
                                               mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that endpoints with {agentXInput} variables are substituted correctly."""
        config = [{"type": "Standard", "endpointName": "{agent1Input}", "preset": "DefaultPreset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "ResolvedEndpoint"
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["MyDynamicEndpoint"])

        list(processor.execute())

        # apply_early_variables should be called for the endpoint with variables
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args
        assert call_args[0][0] == "{agent1Input}"  # First positional arg is the prompt
        # Check keyword arguments
        assert call_args[1]['agent_inputs'] == {"agent1Input": "MyDynamicEndpoint"}
        assert 'workflow_config' in call_args[1]

        # The resolved endpoint should be used
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "ResolvedEndpoint", "DefaultPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_endpoint_with_workflow_config_variable(self, workflow_processor_factory, mock_node_handlers,
                                                   mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that endpoints with static workflow config variables are substituted correctly."""
        config = [{"type": "Standard", "endpointName": "{top_level_var}_endpoint", "preset": "DefaultPreset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "value_endpoint"
        processor = workflow_processor_factory(configs=config, stream=False)

        list(processor.execute())

        # apply_variables should be called
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args
        assert call_args[0][0] == "{top_level_var}_endpoint"
        # Check keyword arguments
        assert 'workflow_config' in call_args[1]
        assert call_args[1]['workflow_config']['top_level_var'] == 'value'

        # The resolved endpoint should be used
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "value_endpoint", "DefaultPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_hardcoded_preset_no_variables(self, workflow_processor_factory, mock_node_handlers,
                                           mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that hardcoded presets WITHOUT variables work correctly and don't trigger substitution."""
        config = [{"type": "Standard", "endpointName": "{agent1Input}", "preset": "HardcodedPreset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "DynamicEndpoint"
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["DynamicEndpoint"])

        list(processor.execute())

        # apply_variables should be called ONLY for the endpoint, not the preset
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args[0]
        assert call_args[0] == "{agent1Input}"  # Only the endpoint

        # The hardcoded preset should be used directly
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "DynamicEndpoint", "HardcodedPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_preset_with_variables(self, workflow_processor_factory, mock_node_handlers,
                                  mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that presets with variables are substituted correctly."""
        config = [{"type": "Standard", "endpointName": "MyEndpoint", "preset": "{agent1Input}_preset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "Dynamic_preset"
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["Dynamic"])

        list(processor.execute())

        # apply_variables should be called for the preset with variables
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args[0]
        assert call_args[0] == "{agent1Input}_preset"

        # The resolved preset should be used
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "MyEndpoint", "Dynamic_preset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_both_endpoint_and_preset_with_variables(self, workflow_processor_factory, mock_node_handlers,
                                                     mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that both endpoint and preset can have variables simultaneously."""
        config = [{"type": "Standard", "endpointName": "{agent1Input}", "preset": "{agent2Input}"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.side_effect = ["DynamicEndpoint", "DynamicPreset"]
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["EndpointFromParent", "PresetFromParent"])

        list(processor.execute())

        # apply_variables should be called twice (once for endpoint, once for preset)
        assert mock_workflow_variable_service.apply_early_variables.call_count == 2

        # First call for endpoint
        first_call = mock_workflow_variable_service.apply_early_variables.call_args_list[0][0]
        assert first_call[0] == "{agent1Input}"

        # Second call for preset
        second_call = mock_workflow_variable_service.apply_early_variables.call_args_list[1][0]
        assert second_call[0] == "{agent2Input}"

        # Both resolved values should be used
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "DynamicEndpoint", "DynamicPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_mixed_hardcoded_and_variable_presets(self, workflow_processor_factory, mock_node_handlers,
                                                  mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that hardcoded preset with variable endpoint works correctly."""
        config = [{"type": "Standard", "endpointName": "{agent1Input}", "preset": "StaticPreset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "ResolvedEndpoint"
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["DynamicEnd"])

        list(processor.execute())

        # apply_variables should be called only once (for endpoint, not preset)
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args[0]
        assert call_args[0] == "{agent1Input}"

        # Resolved endpoint with static preset
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "ResolvedEndpoint", "StaticPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_jinja2_template_in_endpoint(self, workflow_processor_factory, mock_node_handlers,
                                        mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that Jinja2 templates in endpoints are detected and processed."""
        config = [{"type": "Standard",
                  "endpointName": "{% if agent1Input == 'fast' %}FastEndpoint{% else %}SlowEndpoint{% endif %}",
                  "preset": "DefaultPreset"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_workflow_variable_service.apply_early_variables.return_value = "FastEndpoint"
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["fast"])

        list(processor.execute())

        # apply_variables should be called for Jinja2 template
        mock_workflow_variable_service.apply_early_variables.assert_called_once()
        call_args = mock_workflow_variable_service.apply_early_variables.call_args[0]
        assert "{% if" in call_args[0]

        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "FastEndpoint", "DefaultPreset", False, 4096, 400, addGenerationPrompt=ANY
        )

    def test_missing_endpoint_fallback(self, workflow_processor_factory, mock_node_handlers):
        """Verifies that nodes without endpointName still work (using default LlmHandler)."""
        config = [{"type": "Standard"}]  # No endpointName
        mock_node_handlers["Standard"].handle.return_value = "Response"
        processor = workflow_processor_factory(configs=config, stream=False)

        result = list(processor.execute())

        assert result == ["Response"]
        mock_node_handlers["Standard"].handle.assert_called_once()
        # Should create a default LlmHandler instead
        context = mock_node_handlers["Standard"].handle.call_args[0][0]
        assert context.llm_handler is not None

    def test_empty_string_endpoint(self, workflow_processor_factory, mock_node_handlers):
        """Verifies that empty string endpoints are handled gracefully."""
        config = [{"type": "Standard", "endpointName": ""}]  # Empty string
        mock_node_handlers["Standard"].handle.return_value = "Response"
        processor = workflow_processor_factory(configs=config, stream=False)

        result = list(processor.execute())

        assert result == ["Response"]
        mock_node_handlers["Standard"].handle.assert_called_once()

    def test_endpoint_variable_not_available_for_agent_output(self, workflow_processor_factory, mock_node_handlers,
                                                              mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that {agentXOutput} variables are NOT available in endpoint substitution context."""
        # This test documents the intentional limitation
        config = [
            {"type": "Standard", "endpointName": "FirstEndpoint"},
            {"type": "Standard", "endpointName": "{agent1Output}"}  # This should not have agent1Output available
        ]
        mock_node_handlers["Standard"].handle.side_effect = ["FirstOutput", "SecondOutput"]
        mock_workflow_variable_service.apply_early_variables.return_value = "{agent1Output}"  # Unresolved
        processor = workflow_processor_factory(configs=config, stream=False)

        list(processor.execute())

        # For the second node, verify agent_inputs doesn't contain agent1Output
        # (agent outputs are not passed to apply_early_variables at all)
        if mock_workflow_variable_service.apply_early_variables.called:
            second_call = mock_workflow_variable_service.apply_early_variables.call_args_list[-1]
            # apply_early_variables doesn't receive agent_outputs at all
            assert 'agent_outputs' not in second_call[1]
            # agent_inputs should not contain agent1Output
            assert 'agent1Output' not in second_call[1].get('agent_inputs', {})

    def test_multiple_nodes_mixed_variables(self, workflow_processor_factory, mock_node_handlers,
                                           mock_llm_handler_service, mock_workflow_variable_service):
        """Tests a complex workflow with multiple nodes having different variable patterns."""
        config = [
            {"type": "Standard", "endpointName": "StaticEndpoint", "preset": "StaticPreset"},
            {"type": "Standard", "endpointName": "{agent1Input}", "preset": "{top_level_var}"},
            {"type": "Tool"},  # No endpoint
            {"type": "Standard", "endpointName": "Another{agent2Input}Endpoint", "preset": "Static"}
        ]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        mock_node_handlers["Tool"].handle.return_value = "ToolResponse"
        mock_workflow_variable_service.apply_early_variables.side_effect = [
            "ResolvedFromInput", "value",  # Node 2
            "AnotherSecondInputEndpoint"   # Node 4
        ]
        processor = workflow_processor_factory(configs=config, stream=False,
                                              scoped_inputs=["FirstInput", "SecondInput"])

        list(processor.execute())

        # Node 1: No substitution (static)
        # Node 2: Two substitutions (endpoint and preset)
        # Node 3: No endpoint
        # Node 4: One substitution (endpoint with variable)
        assert mock_workflow_variable_service.apply_early_variables.call_count == 3

    def test_special_characters_in_hardcoded_endpoint(self, workflow_processor_factory, mock_node_handlers,
                                                      mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that special characters in hardcoded endpoints don't trigger substitution."""
        # Endpoints with special chars but no { or {{
        config = [{"type": "Standard", "endpointName": "endpoint-with-dash_and_underscore.v1", "preset": "preset@2"}]
        mock_node_handlers["Standard"].handle.return_value = "Response"
        processor = workflow_processor_factory(configs=config, stream=False)

        list(processor.execute())

        # Should not trigger substitution
        mock_workflow_variable_service.apply_early_variables.assert_not_called()
        mock_llm_handler_service.load_model_from_config.assert_called_once_with(
            "endpoint-with-dash_and_underscore.v1", "preset@2", False, 4096, 400, addGenerationPrompt=ANY
        )

    @patch('Middleware.workflows.processors.workflows_processor.StreamingResponseHandler')
    @patch('Middleware.workflows.processors.workflows_processor.get_endpoint_config')
    def test_streaming_endpoint_variable_substitution(self, mock_get_endpoint_config, mock_stream_handler_cls,
                                                      workflow_processor_factory, mock_node_handlers,
                                                      mock_llm_handler_service, mock_workflow_variable_service):
        """Verifies that endpoint variables are substituted in the streaming path before getting config."""
        # This test specifically covers the bug where {agent1Input} was not substituted in streaming mode
        config = [{"type": "Standard", "endpointName": "{agent1Input}", "returnToUser": True}]

        # Setup the mocks
        mock_node_handlers["Standard"].handle.return_value = (x for x in ["chunk1", "chunk2"])  # Generator
        mock_workflow_variable_service.apply_early_variables.return_value = "ResolvedEndpoint"
        mock_get_endpoint_config.return_value = {"some": "config"}

        mock_stream_handler_instance = mock_stream_handler_cls.return_value
        mock_stream_handler_instance.process_stream.return_value = (x for x in ["processed1", "processed2"])
        mock_stream_handler_instance.full_response_text = "Full response"

        processor = workflow_processor_factory(configs=config, stream=True,
                                              scoped_inputs=["MyEndpoint"])

        list(processor.execute())

        # Verify that apply_early_variables was called TWICE:
        # 1. Once in _process_section for loading the model
        # 2. Once in the streaming path before getting endpoint config
        assert mock_workflow_variable_service.apply_early_variables.call_count == 2

        # Both calls should be for the same endpoint template
        for call in mock_workflow_variable_service.apply_early_variables.call_args_list:
            assert call[0][0] == "{agent1Input}"

        # Verify get_endpoint_config was called with the RESOLVED endpoint name, not the template
        mock_get_endpoint_config.assert_called_with("ResolvedEndpoint")

        # Verify StreamingResponseHandler was created with the correct config
        mock_stream_handler_cls.assert_called_once()
        call_args = mock_stream_handler_cls.call_args[0]
        assert call_args[0] == {"some": "config"}  # The resolved endpoint config
