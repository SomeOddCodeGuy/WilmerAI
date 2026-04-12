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
    mock_dispatch.assert_called_once_with(context=mock_execution_context, llm_takes_images=False, max_images=0)


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


# --- acceptImages / maxImagesToSend tests ---

def test_accept_images_true_passes_flag_to_dispatch(standard_node_handler, mocker):
    """When acceptImages is true, dispatch is called with llm_takes_images=True."""
    context = ExecutionContext(
        request_id="r1", workflow_id="w1", discussion_id="d1",
        config={"type": "Standard", "acceptImages": True},
        messages=[{"role": "user", "content": "describe this"}],
        stream=False
    )
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch',
        return_value="response"
    )
    standard_node_handler.handle(context)
    mock_dispatch.assert_called_once_with(context=context, llm_takes_images=True, max_images=0)


def test_accept_images_with_max_images(standard_node_handler, mocker):
    """When acceptImages is true and maxImagesToSend is set, both are forwarded."""
    context = ExecutionContext(
        request_id="r1", workflow_id="w1", discussion_id="d1",
        config={"type": "Standard", "acceptImages": True, "maxImagesToSend": 3},
        messages=[{"role": "user", "content": "describe this"}],
        stream=False
    )
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch',
        return_value="response"
    )
    standard_node_handler.handle(context)
    mock_dispatch.assert_called_once_with(context=context, llm_takes_images=True, max_images=3)


def test_accept_images_false_ignores_max_images(standard_node_handler, mocker):
    """When acceptImages is false, max_images is always 0 even if maxImagesToSend is set."""
    context = ExecutionContext(
        request_id="r1", workflow_id="w1", discussion_id="d1",
        config={"type": "Standard", "acceptImages": False, "maxImagesToSend": 5},
        messages=[{"role": "user", "content": "hello"}],
        stream=False
    )
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch',
        return_value="response"
    )
    standard_node_handler.handle(context)
    mock_dispatch.assert_called_once_with(context=context, llm_takes_images=False, max_images=0)


def test_accept_images_no_images_in_messages(standard_node_handler, mocker):
    """When acceptImages is true but no messages contain images, dispatch still succeeds."""
    context = ExecutionContext(
        request_id="r1", workflow_id="w1", discussion_id="d1",
        config={"type": "Standard", "acceptImages": True, "maxImagesToSend": 2},
        messages=[
            {"role": "user", "content": "just text"},
            {"role": "assistant", "content": "reply"},
        ],
        stream=False
    )
    mock_dispatch = mocker.patch(
        'Middleware.workflows.handlers.impl.standard_node_handler.LLMDispatchService.dispatch',
        return_value="text response"
    )
    result = standard_node_handler.handle(context)
    assert result == "text response"
    mock_dispatch.assert_called_once_with(context=context, llm_takes_images=True, max_images=2)
