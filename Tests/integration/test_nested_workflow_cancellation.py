# tests/integration/test_nested_workflow_cancellation.py

"""
End-to-end integration tests for request cancellation with nested workflows.

These tests verify that cancellation signals correctly terminate both parent
and child workflows in a nested workflow scenario. The core propagation test
drives the real machinery (WorkflowManager -> WorkflowProcessor ->
SubWorkflowHandler -> nested WorkflowManager), mocking only workflow-config
loading and the LLM dispatch layer.
"""

import pytest
from unittest.mock import MagicMock

from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.cancellation_service import cancellation_service
from Middleware.workflows.managers.workflow_manager import WorkflowManager
from Middleware.workflows.processors.workflows_processor import WorkflowProcessor


@pytest.fixture
def setup_cancellation_service():
    """Clear cancellation service before each test."""
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)
    yield
    for req_id in list(cancellation_service.get_all_cancelled_requests()):
        cancellation_service.acknowledge_cancellation(req_id)


@pytest.fixture
def real_workflow_environment(mocker):
    """
    Wires WorkflowManager to run the real sub-workflow machinery hermetically:
    workflow configs are served from an in-memory registry instead of disk,
    services that would touch disk or real user config are mocked, and the LLM
    dispatch layer is the only mocked execution surface. StandardNodeHandler
    and SubWorkflowHandler remain real so the true nested path is exercised.
    """
    workflow_configs = {}

    # Serve workflow configs from the in-memory registry. The path finder
    # returns the workflow name itself as the "path"; json.load resolves the
    # config for whichever "file" was opened last.
    mocker.patch(
        'Middleware.workflows.managers.workflow_manager.default_get_workflow_path',
        side_effect=lambda name, **kwargs: name
    )
    mock_file_open = mocker.patch('builtins.open', mocker.mock_open(read_data='{}'))
    mocker.patch('json.load',
                 side_effect=lambda f: workflow_configs[mock_file_open.call_args[0][0]])

    # Services that would touch disk or the real user config.
    mocker.patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService')
    mocker.patch('Middleware.workflows.managers.workflow_manager.LockingService')
    mocker.patch('Middleware.workflows.processors.workflows_processor.LockingService')
    mocker.patch('Middleware.workflows.processors.workflows_processor.TimestampService')
    mocker.patch('Middleware.workflows.processors.workflows_processor.get_chat_template_name',
                 return_value='chatml')
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_chat_template_name',
                 return_value='chatml')
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.MemoryService')
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.TimestampService')

    # Handlers not exercised by these tests are stubbed at construction time.
    for handler_cls in ('MemoryNodeHandler', 'ToolNodeHandler', 'SpecializedNodeHandler',
                        'ContextCompactorHandler', 'WebFetchHandler', 'CurlCommandHandler',
                        'MCPToolCallHandler'):
        mocker.patch(f'Middleware.workflows.managers.workflow_manager.{handler_cls}')

    # The LLM dispatch layer is mocked; everything above it is real.
    mock_dispatch_service = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService')

    return {
        'workflow_configs': workflow_configs,
        'dispatch': mock_dispatch_service.dispatch,
    }


def make_processor(node_handlers, configs, request_id, workflow_id):
    """Builds a WorkflowProcessor with the boilerplate arguments used by the
    hand-wired multi-level tests below."""
    return WorkflowProcessor(
        node_handlers=node_handlers,
        llm_handler_service=MagicMock(),
        workflow_variable_service=MagicMock(),
        workflow_config_name=workflow_id,
        workflow_file_config={'nodes': configs},
        configs=configs,
        request_id=request_id,
        workflow_id=workflow_id,
        discussion_id="discussion_123",
        messages=[{"role": "user", "content": "test"}],
        stream=False,
        non_responder_flag=None,
        first_node_system_prompt_override=None,
        first_node_prompt_override=None,
        scoped_inputs=None
    )


class TestNestedWorkflowCancellation:
    """Integration tests for nested workflow cancellation."""

    def test_parent_workflow_cancellation_terminates_child(
            self, real_workflow_environment, setup_cancellation_service):
        """
        Drives the REAL nested path: a parent workflow's CustomWorkflow node is
        handled by the real SubWorkflowHandler, which spawns a real nested
        WorkflowManager/WorkflowProcessor for the child. A cancellation raised
        while the child's first LLM node runs must stop the child's remaining
        node AND the parent's follow-up node, and the request_id must have
        propagated into the child's dispatch calls.
        """
        request_id = "test_nested_cancel_123"

        real_workflow_environment['workflow_configs'].update({
            "parent_workflow": {"nodes": [
                {"type": "CustomWorkflow", "workflowName": "child_workflow", "title": "Run Child"},
                {"type": "Standard", "title": "parent-after-child", "returnToUser": True},
            ]},
            "child_workflow": {"nodes": [
                {"type": "Standard", "title": "child-node-1"},
                {"type": "Standard", "title": "child-node-2"},
            ]},
        })

        dispatched = []

        def fake_dispatch(context, llm_takes_images, max_images):
            dispatched.append((context.config.get("title"), context.request_id))
            # Simulate the operator cancelling the request while the child
            # workflow is executing its first LLM node.
            if context.config.get("title") == "child-node-1":
                cancellation_service.request_cancellation(context.request_id)
            return "LLM output"

        real_workflow_environment['dispatch'].side_effect = fake_dispatch

        manager = WorkflowManager(workflow_config_name="parent_workflow")

        with pytest.raises(EarlyTerminationException):
            manager.run_workflow(
                messages=[{"role": "user", "content": "hello"}],
                request_id=request_id,
                discussionId="disc-nested",
                stream=False,
            )

        # The request_id propagated into the child workflow's dispatch, and
        # ONLY the first child node ran: the child's second node and the
        # parent's follow-up node were both stopped by the cancellation.
        assert dispatched == [("child-node-1", request_id)]
        assert not cancellation_service.is_cancelled(request_id), "Cancellation should be acknowledged"

    def test_child_workflow_cancellation_propagates_to_parent(self, mocker, setup_cancellation_service):
        """
        Test that a cancellation in a child workflow propagates up to the parent.

        Scenario:
        - Parent workflow starts and executes its first node
        - Parent spawns child workflow
        - Child's first node triggers a cancellation
        - The child stops before its remaining nodes; the parent stops before
          its remaining nodes
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
            {"type": "Standard", "returnToUser": True}
        ]

        execution_log = []

        def mock_standard(context):
            wf_id = context.workflow_id
            execution_log.append(('standard', wf_id))
            # Cancel as soon as the first child Standard node executes
            if wf_id == "child_id":
                cancellation_service.request_cancellation(request_id)
            return "output"

        def mock_custom_workflow(context):
            execution_log.append(('child_start', 'child_id'))
            child_processor = make_processor(context.node_handlers, child_config,
                                             context.request_id, "child_id")
            return list(child_processor.execute())

        node_handlers = {
            'Standard': MagicMock(handle=mock_standard),
            'CustomWorkflow': MagicMock(handle=mock_custom_workflow)
        }
        node_handlers['CustomWorkflow'].workflow_manager = MagicMock()

        processor = make_processor(node_handlers, parent_config, request_id, "parent_id")

        # Should raise EarlyTerminationException when child is cancelled
        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Exact flow: parent's first node ran, the child started, the child's
        # first node ran and cancelled, then nothing else at either level.
        assert execution_log == [
            ('standard', 'parent_id'),
            ('child_start', 'child_id'),
            ('standard', 'child_id'),
        ]
        assert not cancellation_service.is_cancelled(request_id), "Cancellation should be acknowledged"

    def test_multiple_nested_levels_cancellation(self, mocker, setup_cancellation_service):
        """
        Test cancellation with multiple levels of nesting (grandparent -> parent -> child).

        The cancellation is triggered from inside the DEEPEST child's first
        node, and must stop every remaining node at all three levels.
        """
        request_id = "test_multi_level_789"

        # Mock internal services
        mocker.patch('Middleware.workflows.processors.workflows_processor.LockingService')
        mocker.patch('Middleware.workflows.processors.workflows_processor.TimestampService')

        execution_log = []

        # Each level has a follow-up node after its nesting/first node so we can
        # prove that NO further node ran at ANY level after the cancellation.
        child_config = [
            {"type": "Standard", "title": "child-node-1"},
            {"type": "Standard", "title": "child-node-2", "returnToUser": True},
        ]
        parent_config = [
            {"type": "CustomWorkflow", "workflowName": "child"},
            {"type": "Standard", "title": "parent-after", "returnToUser": True},
        ]
        grandparent_config = [
            {"type": "CustomWorkflow", "workflowName": "parent"},
            {"type": "Standard", "title": "grandparent-after", "returnToUser": True},
        ]

        def mock_standard(context):
            execution_log.append(f"standard:{context.workflow_id}:{context.config.get('title')}")
            # Cancel from inside the deepest child's first node.
            if context.workflow_id == "child" and context.config.get("title") == "child-node-1":
                cancellation_service.request_cancellation(request_id)
            return "output"

        def dynamic_custom_handler(context):
            workflow_name = context.config.get('workflowName')
            execution_log.append(f"entering:{workflow_name}")
            configs = parent_config if workflow_name == 'parent' else child_config
            nested = make_processor(context.node_handlers, configs,
                                    context.request_id, workflow_name)
            return list(nested.execute())

        node_handlers = {
            'Standard': MagicMock(handle=mock_standard),
            'CustomWorkflow': MagicMock(handle=dynamic_custom_handler)
        }
        node_handlers['CustomWorkflow'].workflow_manager = MagicMock()

        processor = make_processor(node_handlers, grandparent_config, request_id, "grandparent")

        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # The full expected sequence: descend into parent, descend into child,
        # run the deepest node (which cancels), and then NOTHING further at
        # any level (no child-node-2, no parent-after, no grandparent-after).
        assert execution_log == [
            "entering:parent",
            "entering:child",
            "standard:child:child-node-1",
        ]
        assert not cancellation_service.is_cancelled(request_id), "Cancellation should be acknowledged"
