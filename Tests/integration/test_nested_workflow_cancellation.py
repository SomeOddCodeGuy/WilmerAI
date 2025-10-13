# tests/integration/test_nested_workflow_cancellation.py

"""
End-to-end integration tests for request cancellation with nested workflows.

These tests verify that cancellation signals correctly terminate both parent
and child workflows in a nested workflow scenario.
"""

import pytest
from unittest.mock import MagicMock, patch, Mock

from Middleware.workflows.managers.workflow_manager import WorkflowManager
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.cancellation_service import cancellation_service


@pytest.fixture
def setup_cancellation_service():
    """Clear cancellation service before each test."""
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)
    yield
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)


@pytest.fixture
def mock_workflow_environment(mocker):
    """Mock the environment for workflow execution."""
    # Mock file system and config loading
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('json.load', return_value={
        "nodes": [
            {"type": "Standard", "returnToUser": True}
        ]
    })

    # Mock config utilities (correct module path)
    mocker.patch('Middleware.utilities.config_utils.get_current_username',
                 return_value='test_user')
    mocker.patch('Middleware.utilities.config_utils.get_user_config',
                 return_value={})

    # Mock LLM handler service
    mock_llm_service = MagicMock()
    mock_llm_handler = MagicMock()
    mock_llm_service.load_model_from_config.return_value = mock_llm_handler
    mocker.patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService',
                 return_value=mock_llm_service)

    # Mock internal services used by WorkflowProcessor
    mocker.patch('Middleware.workflows.processors.workflows_processor.LockingService')
    mocker.patch('Middleware.workflows.processors.workflows_processor.TimestampService')

    # Mock node handlers
    return {
        'llm_service': mock_llm_service,
        'llm_handler': mock_llm_handler
    }


class TestNestedWorkflowCancellation:
    """Integration tests for nested workflow cancellation."""

    @patch('Middleware.workflows.managers.workflow_manager.open', create=True)
    def test_parent_workflow_cancellation_terminates_child(
            self, mock_open, mock_workflow_environment, setup_cancellation_service):
        """
        Test that cancelling a parent workflow also terminates the child workflow.

        Scenario:
        - Parent workflow starts
        - Parent workflow spawns child workflow
        - Cancellation signal arrives
        - Both parent and child should terminate
        """
        request_id = "test_nested_cancel_123"

        # Configure mock file reading for parent workflow
        parent_workflow_config = {
            "nodes": [
                {
                    "type": "CustomWorkflow",
                    "workflowName": "child_workflow",
                    "returnToUser": True
                }
            ]
        }

        # Configure mock file reading for child workflow
        child_workflow_config = {
            "nodes": [
                {"type": "Standard", "returnToUser": True},
                {"type": "Standard", "returnToUser": False},
            ]
        }

        execution_log = {'parent_nodes': 0, 'child_nodes': 0}

        def mock_standard_handler(context):
            """Track execution and simulate work."""
            # Determine if this is parent or child based on workflow config
            if context.workflow_config.get('nodes') == parent_workflow_config['nodes']:
                execution_log['parent_nodes'] += 1
            else:
                execution_log['child_nodes'] += 1

                # Cancel after first child node
                if execution_log['child_nodes'] == 1:
                    cancellation_service.request_cancellation(request_id)

            return "output"

        def mock_custom_workflow_handler(context):
            """Simulate nested workflow execution."""
            # This would normally call WorkflowManager.run_custom_workflow
            # For testing, we'll manually create and execute a child processor
            from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

            child_processor = WorkflowProcessor(
                node_handlers=context.node_handlers,
                llm_handler_service=MagicMock(),
                workflow_variable_service=context.workflow_variable_service,
                workflow_config_name="child_workflow",
                workflow_file_config=child_workflow_config,
                configs=child_workflow_config['nodes'],
                request_id=context.request_id,  # Same request_id for nested workflow
                workflow_id="child_workflow_id",
                discussion_id=context.discussion_id,
                messages=context.messages,
                stream=context.stream,
                non_responder_flag=None,
                first_node_system_prompt_override=None,
                first_node_prompt_override=None,
                scoped_inputs=None
            )

            # Execute child workflow - should raise EarlyTerminationException
            return list(child_processor.execute())

        # Create node handlers
        node_handlers = {
            'Standard': MagicMock(handle=mock_standard_handler),
            'CustomWorkflow': MagicMock(handle=mock_custom_workflow_handler),
        }
        node_handlers['CustomWorkflow'].workflow_manager = MagicMock()

        # Mock file contents
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = str(parent_workflow_config)
        mock_open.return_value = mock_file

        # Execute the parent workflow
        with pytest.raises(EarlyTerminationException):
            from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

            processor = WorkflowProcessor(
                node_handlers=node_handlers,
                llm_handler_service=mock_workflow_environment['llm_service'],
                workflow_variable_service=MagicMock(),
                workflow_config_name="parent_workflow",
                workflow_file_config=parent_workflow_config,
                configs=parent_workflow_config['nodes'],
                request_id=request_id,
                workflow_id="parent_workflow_id",
                discussion_id="discussion_123",
                messages=[{"role": "user", "content": "test"}],
                stream=False,
                non_responder_flag=None,
                first_node_system_prompt_override=None,
                first_node_prompt_override=None,
                scoped_inputs=None
            )

            list(processor.execute())

        # Verify that child workflow started but was cancelled
        assert execution_log['child_nodes'] == 1, "Child workflow should have executed one node before cancellation"

        # Verify cancellation was acknowledged
        assert not cancellation_service.is_cancelled(request_id), "Cancellation should be acknowledged"

    def test_child_workflow_cancellation_propagates_to_parent(self, mocker, setup_cancellation_service):
        """
        Test that a cancellation in a child workflow propagates up to the parent.

        Scenario:
        - Parent workflow starts
        - Parent spawns child workflow
        - Child workflow gets cancelled
        - Both should terminate gracefully
        """
        request_id = "test_child_cancel_456"

        # Mock internal services
        mocker.patch('Middleware.workflows.processors.workflows_processor.LockingService')
        mocker.patch('Middleware.workflows.processors.workflows_processor.TimestampService')

        parent_config = [
            {"type": "Standard"},
            {"type": "CustomWorkflow", "workflowName": "child"},
            {"type": "Standard", "returnToUser": True}
        ]

        child_config = [
            {"type": "Standard"},
            {"type": "Standard"},
            {"type": "Standard", "returnToUser": True}  # Add a third node to ensure cancellation is checked
        ]

        execution_log = []

        def mock_standard(context):
            wf_id = context.workflow_id
            execution_log.append(('standard', wf_id))
            # Count only Standard nodes with child_id (not child_start entries)
            child_standard_count = len([x for x in execution_log if x == ('standard', 'child_id')])
            # Cancel after first child Standard node executes
            if wf_id == "child_id" and child_standard_count == 1:
                # We just executed the first child Standard node, cancel now
                cancellation_service.request_cancellation(request_id)
            return "output"

        def mock_custom_workflow(context):
            from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

            child_processor = WorkflowProcessor(
                node_handlers=context.node_handlers,
                llm_handler_service=MagicMock(),
                workflow_variable_service=context.workflow_variable_service,
                workflow_config_name="child_workflow",
                workflow_file_config={'nodes': child_config},
                configs=child_config,
                request_id=context.request_id,
                workflow_id="child_id",
                discussion_id=context.discussion_id,
                messages=context.messages,
                stream=context.stream,
                non_responder_flag=None,
                first_node_system_prompt_override=None,
                first_node_prompt_override=None,
                scoped_inputs=None
            )

            execution_log.append(('child_start', 'child_id'))
            return list(child_processor.execute())

        node_handlers = {
            'Standard': MagicMock(handle=mock_standard),
            'CustomWorkflow': MagicMock(handle=mock_custom_workflow)
        }
        node_handlers['CustomWorkflow'].workflow_manager = MagicMock()

        from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

        processor = WorkflowProcessor(
            node_handlers=node_handlers,
            llm_handler_service=MagicMock(),
            workflow_variable_service=MagicMock(),
            workflow_config_name="parent_workflow",
            workflow_file_config={'nodes': parent_config},
            configs=parent_config,
            request_id=request_id,
            workflow_id="parent_id",
            discussion_id="discussion_456",
            messages=[{"role": "user", "content": "test"}],
            stream=False,
            non_responder_flag=None,
            first_node_system_prompt_override=None,
            first_node_prompt_override=None,
            scoped_inputs=None
        )

        # Should raise EarlyTerminationException when child is cancelled
        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Verify execution flow
        assert len(execution_log) >= 2, f"Should have executed parent node and started child. Got: {execution_log}"
        assert not cancellation_service.is_cancelled(request_id), "Cancellation should be acknowledged"

    def test_multiple_nested_levels_cancellation(self, mocker, setup_cancellation_service):
        """
        Test cancellation with multiple levels of nesting (grandparent -> parent -> child).

        Scenario:
        - Grandparent workflow
        - Spawns parent workflow
        - Parent spawns child workflow
        - Cancellation should terminate all levels
        """
        request_id = "test_multi_level_789"

        # Mock internal services
        mocker.patch('Middleware.workflows.processors.workflows_processor.LockingService')
        mocker.patch('Middleware.workflows.processors.workflows_processor.TimestampService')

        execution_log = []

        def mock_standard(context):
            execution_log.append(f"{context.workflow_id}")
            return "output"

        def create_nested_handler(child_configs, child_name):
            def handler(context):
                from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

                execution_log.append(f"entering_{child_name}")

                # Cancel after entering second level
                if child_name == "parent" and "entering_parent" in execution_log:
                    cancellation_service.request_cancellation(request_id)

                processor = WorkflowProcessor(
                    node_handlers=context.node_handlers,
                    llm_handler_service=MagicMock(),
                    workflow_variable_service=context.workflow_variable_service,
                    workflow_config_name=child_name,
                    workflow_file_config={'nodes': child_configs},
                    configs=child_configs,
                    request_id=context.request_id,
                    workflow_id=child_name,
                    discussion_id=context.discussion_id,
                    messages=context.messages,
                    stream=context.stream,
                    non_responder_flag=None,
                    first_node_system_prompt_override=None,
                    first_node_prompt_override=None,
                    scoped_inputs=None
                )

                return list(processor.execute())

            return handler

        child_config = [{"type": "Standard", "returnToUser": True}]
        parent_config = [{"type": "CustomWorkflow", "workflowName": "child", "returnToUser": True}]
        grandparent_config = [{"type": "CustomWorkflow", "workflowName": "parent", "returnToUser": True}]

        node_handlers = {
            'Standard': MagicMock(handle=mock_standard),
            'CustomWorkflow': MagicMock()
        }
        node_handlers['CustomWorkflow'].workflow_manager = MagicMock()

        # Need to dynamically assign the correct handler based on config
        def dynamic_custom_handler(context):
            workflow_name = context.config.get('workflowName')
            if workflow_name == 'parent':
                return create_nested_handler(parent_config, 'parent')(context)
            elif workflow_name == 'child':
                return create_nested_handler(child_config, 'child')(context)
            return "output"

        node_handlers['CustomWorkflow'].handle = dynamic_custom_handler

        from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

        processor = WorkflowProcessor(
            node_handlers=node_handlers,
            llm_handler_service=MagicMock(),
            workflow_variable_service=MagicMock(),
            workflow_config_name="grandparent",
            workflow_file_config={'nodes': grandparent_config},
            configs=grandparent_config,
            request_id=request_id,
            workflow_id="grandparent",
            discussion_id="discussion_789",
            messages=[{"role": "user", "content": "test"}],
            stream=False,
            non_responder_flag=None,
            first_node_system_prompt_override=None,
            first_node_prompt_override=None,
            scoped_inputs=None
        )

        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Should have entered grandparent and parent before cancellation
        assert "entering_parent" in execution_log
        assert not cancellation_service.is_cancelled(request_id)

