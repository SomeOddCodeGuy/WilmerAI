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
