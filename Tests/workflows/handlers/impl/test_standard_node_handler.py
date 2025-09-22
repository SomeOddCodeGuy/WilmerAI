# tests/workflows/handlers/impl/test_standard_node_handler.py

import pytest

from Middleware.workflows.handlers.impl.standard_node_handler import StandardNodeHandler
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.fixture
def standard_node_handler(mocker):
    """
    Provides a reusable instance of StandardNodeHandler with its own
    dependencies mocked.
    """
    mock_workflow_manager = mocker.MagicMock()
    mock_variable_service = mocker.MagicMock()
    handler = StandardNodeHandler(
        workflow_manager=mock_workflow_manager,
        workflow_variable_service=mock_variable_service
    )
    return handler


@pytest.fixture
def mock_execution_context():
    """
    Provides a basic, reusable ExecutionContext object for tests.
    """
    return ExecutionContext(
        request_id="test-request-123",
        workflow_id="test-workflow-456",
        discussion_id="test-discussion-789",
        config={"type": "Standard", "title": "Test Node"},
        messages=[{"role": "user", "content": "Hello, world!"}],
        stream=False
    )


def test_handle_calls_llm_dispatch_service_with_context(standard_node_handler, mock_execution_context, mocker):
    """
    Tests that the handle method calls LLMDispatchService.dispatch exactly once
    with the provided ExecutionContext.
    """
    # Arrange
    # Mock the LLMDispatchService's static dispatch method
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch'
    )

    # Act
    standard_node_handler.handle(mock_execution_context)

    # Assert
    # Verify that the mocked dispatch method was called with the correct context object
    mock_dispatch.assert_called_once_with(context=mock_execution_context)


def test_handle_returns_non_streaming_response_from_dispatch_service(standard_node_handler, mock_execution_context,
                                                                     mocker):
    """
    Tests that the handler returns the exact string output from the dispatch
    service for a non-streaming request.
    """
    # Arrange
    expected_response = "This is a complete, non-streaming response."
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch',
        return_value=expected_response
    )

    # Act
    result = standard_node_handler.handle(mock_execution_context)

    # Assert
    # Ensure the handler's return value is exactly what the mocked service provided
    assert result == expected_response


def test_handle_returns_streaming_generator_from_dispatch_service(standard_node_handler, mock_execution_context,
                                                                  mocker):
    """
    Tests that the handler returns the exact generator object from the dispatch
    service for a streaming request.
    """

    # Arrange
    def response_generator():
        yield "Streaming chunk 1"
        yield "Streaming chunk 2"
        yield "Streaming chunk 3"

    expected_generator = response_generator()
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch',
        return_value=expected_generator
    )

    # Act
    result = standard_node_handler.handle(mock_execution_context)

    # Assert
    # Verify that the result is a generator and contains the expected content
    assert hasattr(result, '__iter__') and hasattr(result, '__next__'), "The result should be a generator"
    assert list(result) == ["Streaming chunk 1", "Streaming chunk 2", "Streaming chunk 3"]
