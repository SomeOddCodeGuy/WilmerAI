# tests/workflows/handlers/impl/test_specialized_node_handler.py

from unittest.mock import MagicMock, patch

import pytest

# Dependencies to mock
from Middleware.common import instance_global_variables
# Base classes and exceptions
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.locking_service import LockingService
# The class to test
from Middleware.workflows.handlers.impl.specialized_node_handler import SpecializedNodeHandler
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.fixture
def mock_locking_service(mocker):
    """Mocks the LockingService class to prevent DB interactions."""
    mock_service_instance = MagicMock(spec=LockingService)
    mocker.patch(
        'Middleware.workflows.handlers.impl.specialized_node_handler.LockingService',
        return_value=mock_service_instance
    )
    return mock_service_instance


@pytest.fixture
def specialized_handler(mock_locking_service):
    """Provides an instance of SpecializedNodeHandler with mocked dependencies."""
    mock_workflow_manager = MagicMock()
    mock_variable_service = MagicMock()
    mock_variable_service.apply_variables.side_effect = lambda prompt, context: prompt.format(
        **{**context.agent_inputs, **context.agent_outputs}
    )

    handler = SpecializedNodeHandler(
        workflow_manager=mock_workflow_manager,
        workflow_variable_service=mock_variable_service
    )
    handler.mock_locking_service = mock_locking_service
    handler.mock_variable_service = mock_variable_service
    return handler


@pytest.fixture
def base_context():
    """Provides a basic, reusable ExecutionContext object."""
    return ExecutionContext(
        request_id="req-123",
        workflow_id="wf-abc",
        discussion_id="disc-xyz",
        config={},
        messages=[],
        stream=False,
        agent_outputs={},
        agent_inputs={},
        llm_handler=MagicMock()
    )


class TestHandleRouter:
    """Tests the main 'handle' method to ensure it routes to the correct internal function."""

    @pytest.mark.parametrize("node_type, method_to_mock", [
        ("WorkflowLock", "handle_workflow_lock"),
        ("GetCustomFile", "handle_get_custom_file"),
        ("SaveCustomFile", "handle_save_custom_file"),
        ("ImageProcessor", "handle_image_processor_node"),
        ("StaticResponse", "handle_static_response"),
    ])
    def test_handle_routes_to_correct_method(self, mocker, specialized_handler, base_context, node_type,
                                             method_to_mock):
        """Verifies that handle() calls the appropriate internal method based on node type."""
        mock_method = mocker.patch.object(specialized_handler, method_to_mock, return_value="mocked_return")
        base_context.config = {"type": node_type}

        result = specialized_handler.handle(base_context)

        mock_method.assert_called_once_with(base_context)
        assert result == "mocked_return"

    def test_handle_raises_for_unknown_type(self, specialized_handler, base_context):
        """Ensures a ValueError is raised for an unrecognized node type."""
        base_context.config = {"type": "UnknownType"}
        with pytest.raises(ValueError, match="Unknown specialized node type: UnknownType"):
            specialized_handler.handle(base_context)


class TestHandleWorkflowLock:
    """Tests the 'WorkflowLock' node logic."""

    def test_acquires_lock_when_not_locked(self, specialized_handler, base_context):
        """Should acquire a lock if one is not already active."""
        specialized_handler.mock_locking_service.get_lock.return_value = False
        base_context.config = {"workflowLockId": "test-lock"}

        specialized_handler.handle_workflow_lock(base_context)

        specialized_handler.mock_locking_service.get_lock.assert_called_once_with("test-lock")
        specialized_handler.mock_locking_service.create_node_lock.assert_called_once_with(
            instance_global_variables.INSTANCE_ID, base_context.workflow_id, "test-lock"
        )

    def test_terminates_when_locked(self, specialized_handler, base_context):
        """Should raise EarlyTerminationException if a lock is already active."""
        specialized_handler.mock_locking_service.get_lock.return_value = True
        base_context.config = {"workflowLockId": "test-lock"}

        with pytest.raises(EarlyTerminationException, match="Workflow is locked by test-lock"):
            specialized_handler.handle_workflow_lock(base_context)

        specialized_handler.mock_locking_service.create_node_lock.assert_not_called()

    def test_raises_error_if_lock_id_missing(self, specialized_handler, base_context):
        """Should raise ValueError if 'workflowLockId' is missing from the config."""
        base_context.config = {}
        with pytest.raises(ValueError, match="A WorkflowLock node must have a 'workflowLockId'"):
            specialized_handler.handle_workflow_lock(base_context)


class TestHandleGetCustomFile:
    """Tests the 'GetCustomFile' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file', return_value="file content")
    def test_calls_load_custom_file_with_correct_args(self, mock_load_file, specialized_handler, base_context):
        """Should call the file utility with arguments from the node config."""
        base_context.config = {
            "filepath": "/path/to/file.txt",
            "delimiter": ";",
            "customReturnDelimiter": "\n"
        }

        result = specialized_handler.handle_get_custom_file(base_context)

        assert result == "file content"
        mock_load_file.assert_called_once_with(
            filepath="/path/to/file.txt",
            delimiter=";",
            custom_delimiter="\n"
        )

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file')
    def test_defaults_delimiters(self, mock_load_file, specialized_handler, base_context):
        """Should use default delimiters when they are not specified in the config."""
        base_context.config = {"filepath": "/path/to/file.txt"}

        specialized_handler.handle_get_custom_file(base_context)

        mock_load_file.assert_called_once_with(
            filepath="/path/to/file.txt",
            delimiter="\n",
            custom_delimiter="\n"
        )

    def test_returns_error_if_filepath_missing(self, specialized_handler, base_context):
        """Should return an error message if 'filepath' is missing."""
        base_context.config = {}
        result = specialized_handler.handle_get_custom_file(base_context)
        assert result == "No filepath specified"


class TestHandleSaveCustomFile:
    """Tests the 'SaveCustomFile' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file')
    def test_saves_file_successfully(self, mock_save_file, specialized_handler, base_context):
        """Should resolve variables and call the save utility."""
        base_context.config = {"filepath": "/path/save.txt", "content": "Hello {agent1Output}"}
        base_context.agent_outputs = {"agent1Output": "World"}

        result = specialized_handler.handle_save_custom_file(base_context)

        specialized_handler.mock_variable_service.apply_variables.assert_called_once_with(
            "Hello {agent1Output}", base_context
        )
        mock_save_file.assert_called_once_with(filepath="/path/save.txt", content="Hello World")
        assert result == "File successfully saved to /path/save.txt"

    def test_handles_missing_filepath(self, specialized_handler, base_context):
        """Should return an error message if 'filepath' is missing."""
        base_context.config = {"content": "some content"}
        assert specialized_handler.handle_save_custom_file(base_context) == "No filepath specified"

    def test_handles_missing_content(self, specialized_handler, base_context):
        """Should return an error message if 'content' is missing."""
        base_context.config = {"filepath": "/path/save.txt"}
        assert specialized_handler.handle_save_custom_file(base_context) == "No content specified"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file',
           side_effect=IOError("Disk full"))
    def test_handles_save_exception(self, mock_save_file, specialized_handler, base_context):
        """Should return a formatted error message if the save operation fails."""
        base_context.config = {"filepath": "/path/save.txt", "content": "some content"}

        result = specialized_handler.handle_save_custom_file(base_context)

        assert "Error saving file: Disk full" in result


class TestHandleImageProcessorNode:
    """Tests the 'ImageProcessor' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_no_images_in_context(self, mock_dispatch, specialized_handler, base_context):
        """Should return a specific message and not call the LLM if no images are present."""
        base_context.messages = [{"role": "user", "content": "A message with no images."}]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "There were no images attached to the message"
        mock_dispatch.assert_not_called()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="description of image 1")
    def test_processes_single_image(self, mock_dispatch, specialized_handler, base_context):
        """Should correctly process a single image message."""
        image_msg = {"role": "images", "content": "img1_data"}
        user_msg = {"role": "user", "content": "describe this"}
        base_context.messages = [user_msg, image_msg]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "description of image 1"
        mock_dispatch.assert_called_once()

        call_kwargs = mock_dispatch.call_args.kwargs
        assert call_kwargs['context'].messages == [user_msg, image_msg]
        assert call_kwargs['image_message'] == image_msg

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           side_effect=["desc1", "desc2"])
    def test_processes_multiple_images(self, mock_dispatch, specialized_handler, base_context):
        """Should process multiple image messages and join their descriptions."""
        image_msg1 = {"role": "images", "content": "img1_data"}
        image_msg2 = {"role": "images", "content": "img2_data"}
        user_msg = {"role": "user", "content": "describe these"}
        base_context.messages = [user_msg, image_msg1, image_msg2]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "desc1\n-------------\ndesc2"
        assert mock_dispatch.call_count == 2

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="desc")
    def test_add_as_user_message_true(self, mock_dispatch, specialized_handler, base_context):
        """Should insert a new user message with the description into the conversation history."""
        image_msg = {"role": "images", "content": "img_data"}
        user_msg = {"role": "user", "content": "describe this"}
        base_context.config = {"addAsUserMessage": True}
        base_context.messages = [image_msg, user_msg]

        specialized_handler.handle_image_processor_node(base_context)

        assert len(base_context.messages) == 3
        new_message = base_context.messages[1]
        assert new_message["role"] == "user"
        assert "[IMAGE_BLOCK]" not in new_message["content"]
        assert "desc" in new_message["content"]


class TestHandleStaticResponse:
    """Tests the 'StaticResponse' node logic."""

    def test_non_streaming_returns_resolved_string(self, specialized_handler, base_context):
        """Should return a fully resolved string when not streaming."""
        base_context.config = {"content": "Output is {agent1Output}"}
        base_context.agent_outputs = {"agent1Output": "resolved"}
        base_context.stream = False

        result = specialized_handler.handle_static_response(base_context)

        assert isinstance(result, str)
        assert result == "Output is resolved"
        specialized_handler.mock_variable_service.apply_variables.assert_called_once()

    def test_streaming_returns_generator(self, mocker, specialized_handler, base_context):
        """Should return a generator from the streamer method when streaming."""
        base_context.config = {"content": "stream this"}
        base_context.stream = True

        mock_streamer = mocker.patch.object(specialized_handler, '_stream_static_content')

        result = specialized_handler.handle_static_response(base_context)

        assert result == mock_streamer.return_value
        mock_streamer.assert_called_once_with("stream this")


class TestStreamStaticContent:
    """Tests the internal '_stream_static_content' generator."""

    @patch('time.sleep')
    def test_streams_words_correctly(self, mock_sleep, specialized_handler):
        """Should yield dictionaries in the correct format for each word."""
        content = "word1 word2"
        generator = specialized_handler._stream_static_content(content)
        results = list(generator)

        assert len(results) == 3
        assert results[0] == {'token': 'word1 ', 'finish_reason': None}
        assert results[1] == {'token': 'word2 ', 'finish_reason': None}
        assert results[2] == {'token': '', 'finish_reason': 'stop'}
        assert mock_sleep.call_count == 2

    @patch('time.sleep')
    def test_streams_empty_string(self, mock_sleep, specialized_handler):
        """Should yield a single 'stop' token for empty content."""
        content = ""
        generator = specialized_handler._stream_static_content(content)
        results = list(generator)

        assert len(results) == 1
        assert results[0] == {'token': '', 'finish_reason': 'stop'}
        mock_sleep.assert_not_called()
