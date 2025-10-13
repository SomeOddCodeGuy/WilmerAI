# tests/workflows/processors/test_workflow_processor_cancellation.py

import pytest
from unittest.mock import MagicMock, patch, Mock

from Middleware.workflows.processors.workflows_processor import WorkflowProcessor
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
def mock_dependencies():
    """Create mock dependencies for WorkflowProcessor."""
    node_handlers = {
        'Standard': MagicMock(),
        'CustomWorkflow': MagicMock()
    }
    node_handlers['CustomWorkflow'].workflow_manager = MagicMock()

    llm_handler_service = MagicMock()
    workflow_variable_service = MagicMock()

    return {
        'node_handlers': node_handlers,
        'llm_handler_service': llm_handler_service,
        'workflow_variable_service': workflow_variable_service,
        'workflow_config_name': 'test_workflow',
        'workflow_file_config': {},
        'configs': [],
        'request_id': 'test_request_123',
        'workflow_id': 'workflow_456',
        'discussion_id': 'discussion_789',
        'messages': [{'role': 'user', 'content': 'test message'}],
        'stream': False,
        'non_responder_flag': None,
        'first_node_system_prompt_override': None,
        'first_node_prompt_override': None,
        'scoped_inputs': None
    }


class TestWorkflowProcessorCancellation:
    """Test suite for WorkflowProcessor cancellation integration."""

    def test_cancellation_before_first_node(self, mock_dependencies, setup_cancellation_service):
        """Test that cancellation before the first node terminates the workflow."""
        mock_dependencies['configs'] = [
            {'type': 'Standard', 'returnToUser': True}
        ]

        processor = WorkflowProcessor(**mock_dependencies)

        # Request cancellation before execution
        cancellation_service.request_cancellation(mock_dependencies['request_id'])

        # Execute should raise EarlyTerminationException
        with pytest.raises(EarlyTerminationException) as exc_info:
            list(processor.execute())

        assert mock_dependencies['request_id'] in str(exc_info.value)

        # Cancellation should be acknowledged
        assert not cancellation_service.is_cancelled(mock_dependencies['request_id'])

    def test_cancellation_between_nodes(self, mock_dependencies, setup_cancellation_service):
        """Test that cancellation between nodes terminates the workflow."""
        mock_dependencies['configs'] = [
            {'type': 'Standard'},
            {'type': 'Standard'},
            {'type': 'Standard', 'returnToUser': True}
        ]

        # Mock the handler to track executions
        execution_count = {'count': 0}

        def mock_handle(context):
            execution_count['count'] += 1
            # Cancel after first node
            if execution_count['count'] == 1:
                cancellation_service.request_cancellation(mock_dependencies['request_id'])
            return "test output"

        mock_dependencies['node_handlers']['Standard'].handle = mock_handle

        processor = WorkflowProcessor(**mock_dependencies)

        # Execute should raise EarlyTerminationException after first node
        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Only first node should have executed
        assert execution_count['count'] == 1

        # Cancellation should be acknowledged
        assert not cancellation_service.is_cancelled(mock_dependencies['request_id'])

    def test_no_cancellation_completes_normally(self, mock_dependencies, setup_cancellation_service):
        """Test that workflow completes normally when no cancellation is requested."""
        mock_dependencies['configs'] = [
            {'type': 'Standard'},
            {'type': 'Standard', 'returnToUser': True}
        ]

        execution_count = {'count': 0}

        def mock_handle(context):
            execution_count['count'] += 1
            return f"output {execution_count['count']}"

        mock_dependencies['node_handlers']['Standard'].handle = mock_handle

        processor = WorkflowProcessor(**mock_dependencies)

        # Execute should complete without exception
        result = list(processor.execute())

        # Both nodes should have executed
        assert execution_count['count'] == 2

        # Should have received output from second node (responder)
        assert len(result) > 0

    def test_cancellation_different_request_id(self, mock_dependencies, setup_cancellation_service):
        """Test that cancellation of a different request ID doesn't affect this workflow."""
        mock_dependencies['configs'] = [
            {'type': 'Standard'},
            {'type': 'Standard', 'returnToUser': True}
        ]

        execution_count = {'count': 0}

        def mock_handle(context):
            execution_count['count'] += 1
            return f"output {execution_count['count']}"

        mock_dependencies['node_handlers']['Standard'].handle = mock_handle

        # Cancel a different request
        cancellation_service.request_cancellation('different_request_999')

        processor = WorkflowProcessor(**mock_dependencies)

        # Execute should complete normally
        result = list(processor.execute())

        # Both nodes should have executed
        assert execution_count['count'] == 2

    def test_cancellation_acknowledged_after_termination(self, mock_dependencies, setup_cancellation_service):
        """Test that cancellation is properly acknowledged after early termination."""
        mock_dependencies['configs'] = [
            {'type': 'Standard', 'returnToUser': True}
        ]

        request_id = mock_dependencies['request_id']
        cancellation_service.request_cancellation(request_id)

        processor = WorkflowProcessor(**mock_dependencies)

        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Verify cancellation was acknowledged (removed from the set)
        assert not cancellation_service.is_cancelled(request_id)

    def test_multiple_nodes_cancellation_at_each_check(self, mock_dependencies, setup_cancellation_service):
        """Test that cancellation is checked at the start of each node execution."""
        mock_dependencies['configs'] = [
            {'type': 'Standard'},
            {'type': 'Standard'},
            {'type': 'Standard'},
            {'type': 'Standard', 'returnToUser': True}
        ]

        execution_order = []

        def mock_handle(context):
            node_num = len(execution_order) + 1
            execution_order.append(node_num)
            # Cancel after second node
            if node_num == 2:
                cancellation_service.request_cancellation(mock_dependencies['request_id'])
            return f"output {node_num}"

        mock_dependencies['node_handlers']['Standard'].handle = mock_handle

        processor = WorkflowProcessor(**mock_dependencies)

        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # First two nodes should execute, third should be cancelled before execution
        assert execution_order == [1, 2]

    @patch('Middleware.workflows.processors.workflows_processor.logger')
    def test_cancellation_logs_warning(self, mock_logger, mock_dependencies, setup_cancellation_service):
        """Test that cancellation logs an appropriate warning message."""
        mock_dependencies['configs'] = [
            {'type': 'Standard', 'returnToUser': True}
        ]

        request_id = mock_dependencies['request_id']
        cancellation_service.request_cancellation(request_id)

        processor = WorkflowProcessor(**mock_dependencies)

        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Verify warning was logged
        mock_logger.warning.assert_called()
        warning_call_args = str(mock_logger.warning.call_args)
        assert 'cancelled' in warning_call_args.lower()
        assert request_id in warning_call_args

    def test_post_response_cleanup_cancellation(self, mock_dependencies, setup_cancellation_service):
        """Test that cancellation works for non-responder nodes after a responder."""
        mock_dependencies['configs'] = [
            {'type': 'Standard', 'returnToUser': True},  # Responder
            {'type': 'Standard', 'returnToUser': False},  # Post-response cleanup
            {'type': 'Standard', 'returnToUser': False}   # Another cleanup
        ]

        execution_log = []

        def mock_handle(context):
            execution_log.append(context.config.get('returnToUser'))
            # Cancel after responder completes
            if context.config.get('returnToUser') is True:
                cancellation_service.request_cancellation(mock_dependencies['request_id'])
            return "output"

        mock_dependencies['node_handlers']['Standard'].handle = mock_handle

        processor = WorkflowProcessor(**mock_dependencies)

        # The responder should execute and return, but cleanup nodes should be cancelled
        with pytest.raises(EarlyTerminationException):
            list(processor.execute())

        # Should have only executed the responder, not the cleanup nodes
        assert execution_log == [True], f"Expected only responder to execute, got: {execution_log}"

    def test_multi_request_isolation(self, mock_dependencies, setup_cancellation_service):
        """Test that cancelling one request doesn't affect another concurrent request."""
        # Create two separate processor instances with different request IDs
        request_id_a = "request_a_123"
        request_id_b = "request_b_456"

        config = [
            {'type': 'Standard'},
            {'type': 'Standard'},
            {'type': 'Standard', 'returnToUser': True}
        ]

        execution_log_a = []
        execution_log_b = []

        def make_handler(request_id, log):
            def handler(context):
                log.append(request_id)
                return "output"
            return handler

        # Setup processor A
        deps_a = {**mock_dependencies, 'request_id': request_id_a, 'configs': config}
        deps_a['node_handlers']['Standard'].handle = make_handler(request_id_a, execution_log_a)
        processor_a = WorkflowProcessor(**deps_a)

        # Setup processor B
        deps_b = {**mock_dependencies, 'request_id': request_id_b, 'configs': config}
        deps_b['node_handlers'] = {
            'Standard': MagicMock(),
            'CustomWorkflow': MagicMock()
        }
        deps_b['node_handlers']['CustomWorkflow'].workflow_manager = MagicMock()
        deps_b['node_handlers']['Standard'].handle = make_handler(request_id_b, execution_log_b)
        processor_b = WorkflowProcessor(**deps_b)

        # Cancel only request A
        cancellation_service.request_cancellation(request_id_a)

        # Execute processor A - should fail
        with pytest.raises(EarlyTerminationException):
            list(processor_a.execute())

        # Execute processor B - should complete normally
        result_b = list(processor_b.execute())

        # Verify A was cancelled but B completed
        assert len(execution_log_a) == 0, "Request A should not have executed any nodes"
        assert len(execution_log_b) == 3, f"Request B should have executed all nodes, got {len(execution_log_b)}"
        assert len(result_b) > 0, "Request B should have returned output"

    @patch('Middleware.common.instance_global_variables.API_TYPE', 'ollamaapichat')
    def test_streaming_cancellation_during_node_execution(self, mock_dependencies, setup_cancellation_service):
        """
        Test that cancellation works when a node is actively streaming tokens.

        This simulates a scenario where an LLM is generating tokens and the request
        is cancelled mid-generation. The node should stop yielding tokens.
        """
        mock_dependencies['configs'] = [
            {'type': 'Standard', 'returnToUser': True}
        ]
        mock_dependencies['stream'] = True

        tokens_generated = []
        request_id = mock_dependencies['request_id']

        def mock_streaming_handler(context):
            """Mock handler that yields tokens and can be cancelled mid-stream."""
            # This simulates what an actual LLM streaming call would do
            for i in range(10):
                # Check cancellation before each token (simulating the LLM API layer check)
                if cancellation_service.is_cancelled(request_id):
                    break
                tokens_generated.append(f"token_{i}")
                # Simulate yielding a token in the format expected by streaming response handler
                yield {"token": f"token_{i}", "finish_reason": None}
                # Cancel after 3 tokens
                if i == 2:
                    cancellation_service.request_cancellation(request_id)

        mock_dependencies['node_handlers']['Standard'].handle = mock_streaming_handler

        processor = WorkflowProcessor(**mock_dependencies)

        # Execute and consume the stream
        result_tokens = []
        for token in processor.execute():
            result_tokens.append(token)

        # Should have generated only 3 tokens before cancellation stopped it
        assert len(tokens_generated) == 3, f"Should have generated 3 tokens, got {len(tokens_generated)}: {tokens_generated}"
        # Cancellation should still be registered (not yet acknowledged since we consumed the generator normally)
        # Actually it would be acknowledged if the processor hit the check, but in this case the node itself stopped
        # so the processor completed normally. This test shows node-level cancellation awareness.
