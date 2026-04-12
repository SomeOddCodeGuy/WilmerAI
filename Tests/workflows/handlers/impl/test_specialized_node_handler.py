from unittest.mock import MagicMock, patch

import pytest

from Middleware.common import instance_global_variables
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.locking_service import LockingService
from Middleware.utilities.streaming_utils import stream_static_content
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
def mock_variable_service():
    """Provides a mock for the WorkflowVariableManager."""
    mock_service = MagicMock()
    mock_service.apply_variables.side_effect = lambda prompt, context: prompt.format(
        **(context.agent_inputs or {}), **(context.agent_outputs or {})
    )
    return mock_service


@pytest.fixture
def specialized_handler(mock_locking_service, mock_variable_service):
    """Provides an instance of SpecializedNodeHandler with mocked dependencies."""
    handler = SpecializedNodeHandler(
        workflow_manager=MagicMock(),
        workflow_variable_service=mock_variable_service
    )
    return handler


@pytest.fixture
def base_context(mock_variable_service):
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
        llm_handler=MagicMock(),
        workflow_variable_service=mock_variable_service
    )


class TestHandleRouter:
    """Tests the main 'handle' method to ensure it routes to the correct internal function."""

    @pytest.mark.parametrize("node_type, method_to_mock", [
        ("WorkflowLock", "handle_workflow_lock"),
        ("GetCustomFile", "handle_get_custom_file"),
        ("SaveCustomFile", "handle_save_custom_file"),
        ("ImageProcessor", "handle_image_processor_node"),
        ("StaticResponse", "handle_static_response"),
        ("ArithmeticProcessor", "handle_arithmetic_processor"),
        ("Conditional", "handle_conditional"),
        ("StringConcatenator", "handle_string_concatenator"),
        ("JsonExtractor", "handle_json_extractor"),
        ("TagTextExtractor", "handle_tag_text_extractor"),
        ("DelimitedChunker", "handle_delimited_chunker"),
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

    def test_acquires_lock_when_not_locked(self, specialized_handler, base_context, mock_locking_service):
        """Should acquire a lock if one is not already active."""
        mock_locking_service.get_lock.return_value = False
        base_context.config = {"workflowLockId": "test-lock"}

        specialized_handler.handle_workflow_lock(base_context)

        mock_locking_service.get_lock.assert_called_once_with("test-lock")
        mock_locking_service.create_node_lock.assert_called_once_with(
            instance_global_variables.INSTANCE_ID, base_context.workflow_id, "test-lock"
        )

    def test_terminates_when_locked(self, specialized_handler, base_context, mock_locking_service):
        """Should raise EarlyTerminationException if a lock is already active."""
        mock_locking_service.get_lock.return_value = True
        base_context.config = {"workflowLockId": "test-lock"}

        with pytest.raises(EarlyTerminationException, match="Workflow is locked by test-lock"):
            specialized_handler.handle_workflow_lock(base_context)

        mock_locking_service.create_node_lock.assert_not_called()

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

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file', return_value="file content")
    def test_applies_variables_to_filepath(self, mock_load_file, specialized_handler, base_context, mock_variable_service):
        """Should apply variable substitution to the filepath before loading the file."""
        mock_variable_service.apply_variables.side_effect = lambda path, ctx: path.replace(
            "{Discussion_Id}", "conv-123"
        ).replace("{YYYY_MM_DD}", "2025_12_07")

        base_context.config = {"filepath": "/data/{Discussion_Id}_notes.txt"}

        result = specialized_handler.handle_get_custom_file(base_context)

        mock_variable_service.apply_variables.assert_called_once_with(
            "/data/{Discussion_Id}_notes.txt", base_context
        )
        mock_load_file.assert_called_once_with(
            filepath="/data/conv-123_notes.txt",
            delimiter="\n",
            custom_delimiter="\n"
        )
        assert result == "file content"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file', return_value="dated content")
    def test_applies_date_variable_to_filepath(self, mock_load_file, specialized_handler, base_context, mock_variable_service):
        """Should substitute YYYY_MM_DD variable in the filepath."""
        mock_variable_service.apply_variables.side_effect = lambda path, ctx: path.replace(
            "{YYYY_MM_DD}", "2025_12_07"
        )

        base_context.config = {"filepath": "/logs/{YYYY_MM_DD}_actions.txt"}

        result = specialized_handler.handle_get_custom_file(base_context)

        mock_load_file.assert_called_once_with(
            filepath="/logs/2025_12_07_actions.txt",
            delimiter="\n",
            custom_delimiter="\n"
        )
        assert result == "dated content"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file', return_value="combined content")
    def test_applies_multiple_variables_to_filepath(self, mock_load_file, specialized_handler, base_context, mock_variable_service):
        """Should substitute multiple variables in the filepath."""
        mock_variable_service.apply_variables.side_effect = lambda path, ctx: path.replace(
            "{Discussion_Id}", "session-abc"
        ).replace("{YYYY_MM_DD}", "2025_12_07")

        base_context.config = {"filepath": "/data/{YYYY_MM_DD}/{Discussion_Id}_output.txt"}

        specialized_handler.handle_get_custom_file(base_context)

        mock_load_file.assert_called_once_with(
            filepath="/data/2025_12_07/session-abc_output.txt",
            delimiter="\n",
            custom_delimiter="\n"
        )


class TestHandleSaveCustomFile:
    """Tests the 'SaveCustomFile' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file')
    def test_saves_file_successfully(self, mock_save_file, specialized_handler, base_context, mock_variable_service):
        """Should resolve variables in both filepath and content, then call the save utility."""
        base_context.config = {"filepath": "/path/save.txt", "content": "Hello {agent1Output}"}
        base_context.agent_outputs = {"agent1Output": "World"}

        resolved_content = base_context.config["content"].format(agent1Output="World")

        result = specialized_handler.handle_save_custom_file(base_context)

        assert mock_variable_service.apply_variables.call_count == 2
        mock_variable_service.apply_variables.assert_any_call("/path/save.txt", base_context)
        mock_variable_service.apply_variables.assert_any_call("Hello {agent1Output}", base_context)
        mock_save_file.assert_called_once_with(filepath="/path/save.txt", content=resolved_content)
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

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file')
    def test_applies_variables_to_filepath(self, mock_save_file, specialized_handler, base_context, mock_variable_service):
        """Should apply variable substitution to the filepath before saving."""
        def mock_apply(text, ctx):
            return text.replace("{Discussion_Id}", "conv-456").replace("{agent1Output}", "result")

        mock_variable_service.apply_variables.side_effect = mock_apply
        base_context.config = {
            "filepath": "/data/{Discussion_Id}_output.txt",
            "content": "Output: {agent1Output}"
        }

        result = specialized_handler.handle_save_custom_file(base_context)

        assert mock_variable_service.apply_variables.call_count == 2
        mock_variable_service.apply_variables.assert_any_call("/data/{Discussion_Id}_output.txt", base_context)
        mock_variable_service.apply_variables.assert_any_call("Output: {agent1Output}", base_context)

        mock_save_file.assert_called_once_with(
            filepath="/data/conv-456_output.txt",
            content="Output: result"
        )
        assert result == "File successfully saved to /data/conv-456_output.txt"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file')
    def test_applies_date_variable_to_filepath(self, mock_save_file, specialized_handler, base_context, mock_variable_service):
        """Should substitute YYYY_MM_DD variable in the filepath when saving."""
        def mock_apply(text, ctx):
            return text.replace("{YYYY_MM_DD}", "2025_12_07")

        mock_variable_service.apply_variables.side_effect = mock_apply
        base_context.config = {
            "filepath": "/logs/{YYYY_MM_DD}_report.txt",
            "content": "Daily report"
        }

        result = specialized_handler.handle_save_custom_file(base_context)

        mock_save_file.assert_called_once_with(
            filepath="/logs/2025_12_07_report.txt",
            content="Daily report"
        )
        assert "2025_12_07" in result

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file')
    def test_applies_multiple_variables_to_filepath(self, mock_save_file, specialized_handler, base_context, mock_variable_service):
        """Should substitute multiple variables in the filepath when saving."""
        def mock_apply(text, ctx):
            return text.replace("{Discussion_Id}", "session-xyz").replace("{YYYY_MM_DD}", "2025_12_07")

        mock_variable_service.apply_variables.side_effect = mock_apply
        base_context.config = {
            "filepath": "/data/{YYYY_MM_DD}/{Discussion_Id}_summary.txt",
            "content": "Summary content"
        }

        specialized_handler.handle_save_custom_file(base_context)

        mock_save_file.assert_called_once_with(
            filepath="/data/2025_12_07/session-xyz_summary.txt",
            content="Summary content"
        )


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
        """Should correctly process a single image from a message's images key."""
        user_msg = {"role": "user", "content": "describe this", "images": ["img1_data"]}
        base_context.messages = [user_msg]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "description of image 1"
        mock_dispatch.assert_called_once()

        call_context = mock_dispatch.call_args.kwargs['context']
        assert call_context.messages[0]["images"] == ["img1_data"]
        assert mock_dispatch.call_args.kwargs['llm_takes_images'] is True

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           side_effect=["desc1", "desc2"])
    def test_processes_multiple_images(self, mock_dispatch, specialized_handler, base_context):
        """Should process multiple images from a message and join their descriptions."""
        user_msg = {"role": "user", "content": "describe these", "images": ["img1_data", "img2_data"]}
        base_context.messages = [user_msg]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "desc1\n-------------\ndesc2"
        assert mock_dispatch.call_count == 2

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           side_effect=["desc1", "desc2"])
    def test_original_context_messages_not_mutated(self, mock_dispatch, specialized_handler, base_context):
        """The original context.messages must not be modified during image processing."""
        base_context.messages = [
            {"role": "user", "content": "first", "images": ["img1", "img2"]},
            {"role": "assistant", "content": "reply"},
        ]
        original_images = list(base_context.messages[0]["images"])

        specialized_handler.handle_image_processor_node(base_context)

        # Original message still has both images intact
        assert base_context.messages[0]["images"] == original_images
        # Assistant message unchanged
        assert base_context.messages[1] == {"role": "assistant", "content": "reply"}

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="desc")
    def test_add_as_user_message_true(self, mock_dispatch, specialized_handler, base_context, mock_variable_service):
        """Should insert a new user message with the description into the conversation history."""
        user_msg = {"role": "user", "content": "describe this", "images": ["img_data"]}
        base_context.config = {"addAsUserMessage": True}
        base_context.messages = [user_msg]

        mock_variable_service.apply_variables.side_effect = lambda t, c: t.replace('[IMAGE_BLOCK]', 'desc')

        specialized_handler.handle_image_processor_node(base_context)

        assert len(base_context.messages) == 2
        new_message = base_context.messages[0]
        assert new_message["role"] == "user"
        assert "[IMAGE_BLOCK]" not in new_message["content"]
        assert "desc" in new_message["content"]


class TestHandleImageProcessorNodeWithCaching:
    """Tests the ImageProcessor node with vision response caching enabled."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_caching_disabled_by_default_uses_legacy_path(self, mock_dispatch, specialized_handler, base_context):
        """When saveVisionResponsesToDiscussionId is not set, the legacy path is used."""
        base_context.config = {}
        base_context.messages = [{"role": "user", "content": "hi", "images": ["img1"]}]
        mock_dispatch.return_value = "legacy desc"

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "legacy desc"
        mock_dispatch.assert_called_once()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_caching_noop_when_discussion_id_is_none(self, mock_dispatch, specialized_handler, base_context):
        """When discussion_id is None, falls back to legacy even if saveVisionResponsesToDiscussionId is true."""
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.discussion_id = None
        base_context.messages = [{"role": "user", "content": "hi", "images": ["img1"]}]
        mock_dispatch.return_value = "legacy desc"

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "legacy desc"
        mock_dispatch.assert_called_once()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses', return_value={})
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="new description")
    def test_cache_miss_processes_and_stores(self, mock_dispatch, mock_get_path, mock_read, mock_write,
                                             specialized_handler, base_context):
        """On cache miss, calls LLM and writes the result to the cache."""
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.messages = [{"role": "user", "content": "look", "images": ["img_data"]}]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "new description"
        mock_dispatch.assert_called_once()
        mock_write.assert_called_once()
        written_data = mock_write.call_args[0][1]
        assert len(written_data) == 1
        assert "new description" in written_data.values()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.hash_message_with_images',
           return_value="cached_hash")
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_cache_hit_skips_llm_call(self, mock_dispatch, mock_hash, mock_get_path, mock_read, mock_write,
                                      specialized_handler, base_context):
        """On cache hit, the LLM is not called and the cached response is returned."""
        mock_read.return_value = {"cached_hash": "cached description"}
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.messages = [{"role": "user", "content": "look", "images": ["img_data"]}]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "cached description"
        mock_dispatch.assert_not_called()
        mock_write.assert_not_called()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.hash_message_with_images')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="new desc")
    def test_partial_cache_hit_calls_llm_only_for_uncached(self, mock_dispatch, mock_hash, mock_get_path,
                                                            mock_read, mock_write,
                                                            specialized_handler, base_context):
        """With partial cache hit, LLM is only called for uncached messages."""
        mock_hash.side_effect = ["hash_cached", "hash_new"]
        mock_read.return_value = {"hash_cached": "old cached desc"}
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.messages = [
            {"role": "user", "content": "first", "images": ["img1"]},
            {"role": "user", "content": "second", "images": ["img2"]},
        ]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert "old cached desc" in result
        assert "new desc" in result
        mock_dispatch.assert_called_once()
        mock_write.assert_called_once()
        written_data = mock_write.call_args[0][1]
        assert "hash_cached" in written_data
        assert "hash_new" in written_data

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses', return_value={})
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_only_last_20_messages_scanned(self, mock_dispatch, mock_get_path, mock_read, mock_write,
                                           specialized_handler, base_context):
        """Only the last 20 messages are scanned for images."""
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(25)]
        messages[3]["images"] = ["old_img"]
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.messages = messages

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "There were no images attached to the message"
        mock_dispatch.assert_not_called()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses', return_value={})
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="desc")
    def test_add_as_user_message_per_message_injection(self, mock_dispatch, mock_get_path, mock_read, mock_write,
                                                       specialized_handler, base_context, mock_variable_service):
        """With caching and addAsUserMessage=true, descriptions are injected after each image message."""
        mock_variable_service.apply_variables.side_effect = lambda t, c: t
        base_context.config = {"saveVisionResponsesToDiscussionId": True, "addAsUserMessage": True}
        base_context.messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "has image", "images": ["img1"]},
            {"role": "user", "content": "last message"},
        ]

        specialized_handler.handle_image_processor_node(base_context)

        assert len(base_context.messages) == 4
        assert base_context.messages[0]["content"] == "first"
        assert base_context.messages[1]["content"] == "has image"
        assert "[IMAGE_BLOCK]" not in base_context.messages[2]["content"]
        assert base_context.messages[2]["role"] == "user"
        assert base_context.messages[3]["content"] == "last message"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses', return_value={})
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_add_as_user_message_false_returns_last_10_only(self, mock_dispatch, mock_get_path, mock_read,
                                                            mock_write, specialized_handler, base_context):
        """With addAsUserMessage=false, only descriptions from last 10 messages are returned."""
        mock_dispatch.side_effect = ["early desc", "recent desc"]
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(15)]
        messages[2]["images"] = ["old_img"]
        messages[12]["images"] = ["new_img"]
        base_context.config = {"saveVisionResponsesToDiscussionId": True, "addAsUserMessage": False}
        base_context.messages = messages

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "recent desc"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses', return_value={})
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           side_effect=["desc_img1", "desc_img2"])
    def test_multiple_images_in_one_message_aggregated(self, mock_dispatch, mock_get_path, mock_read, mock_write,
                                                       specialized_handler, base_context):
        """Multiple images in a single message are processed individually and stored as one cache entry."""
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.messages = [
            {"role": "user", "content": "two pics", "images": ["imgA", "imgB"]}
        ]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "desc_img1\n-------------\ndesc_img2"
        assert mock_dispatch.call_count == 2
        mock_write.assert_called_once()
        written_data = mock_write.call_args[0][1]
        assert len(written_data) == 1
        cached_value = list(written_data.values())[0]
        assert cached_value == "desc_img1\n-------------\ndesc_img2"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.write_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.read_vision_responses')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.get_discussion_vision_responses_file_path',
           return_value='/mock/disc_vision_responses.json')
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.hash_message_with_images',
           return_value="new_hash")
    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="new desc")
    def test_cache_write_preserves_old_entries(self, mock_dispatch, mock_hash, mock_get_path,
                                               mock_read, mock_write, specialized_handler, base_context):
        """Writing new cache entries does not remove existing entries."""
        mock_read.return_value = {"old_hash": "old description"}
        base_context.config = {"saveVisionResponsesToDiscussionId": True}
        base_context.messages = [{"role": "user", "content": "new", "images": ["img"]}]

        specialized_handler.handle_image_processor_node(base_context)

        mock_write.assert_called_once()
        written_data = mock_write.call_args[0][1]
        assert "old_hash" in written_data
        assert written_data["old_hash"] == "old description"
        assert "new_hash" in written_data
        assert written_data["new_hash"] == "new desc"


class TestHandleStaticResponse:
    """Tests the 'StaticResponse' node logic."""

    def test_non_streaming_returns_resolved_string(self, specialized_handler, base_context, mock_variable_service):
        """Should return a fully resolved string when not streaming."""
        base_context.config = {"content": "Output is {agent1Output}"}
        base_context.agent_outputs = {"agent1Output": "resolved"}
        base_context.stream = False

        result = specialized_handler.handle_static_response(base_context)

        assert isinstance(result, str)
        assert result == "Output is resolved"
        mock_variable_service.apply_variables.assert_called_once()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.stream_static_content')
    def test_streaming_returns_generator(self, mock_streamer, specialized_handler, base_context):
        """Should return a generator from the streamer utility when streaming."""
        base_context.config = {"content": "stream this"}
        base_context.stream = True

        resolved_content = "stream this"

        result = specialized_handler.handle_static_response(base_context)

        assert result == mock_streamer.return_value
        mock_streamer.assert_called_once_with(resolved_content)


class TestStreamStaticContentUtil:
    """Tests the 'stream_static_content' utility function."""

    @patch('time.sleep')
    def test_streams_tokens_correctly(self, mock_sleep):
        """Should yield dictionaries for each token (word and whitespace)."""
        content = "word1 word2"
        generator = stream_static_content(content)
        results = list(generator)

        assert len(results) == 4
        assert results[0] == {'token': 'word1', 'finish_reason': None}
        assert results[1] == {'token': ' ', 'finish_reason': None}
        assert results[2] == {'token': 'word2', 'finish_reason': None}
        assert results[3] == {'token': '', 'finish_reason': 'stop'}
        assert mock_sleep.call_count == 2

    @patch('time.sleep')
    def test_streams_preserves_whitespace_and_newlines(self, mock_sleep):
        """(CORRECTED) Should correctly preserve all whitespace including spaces, tabs, and newlines."""
        content = "Line 1\n\nLine 2 \tDone."
        generator = stream_static_content(content)
        results = list(generator)

        assert len(results) == 10

        reconstructed_content = "".join([r['token'] for r in results if r['finish_reason'] is None])
        assert reconstructed_content == content

        assert results[3] == {'token': '\n\n', 'finish_reason': None}
        assert results[6] == {'token': '2', 'finish_reason': None}
        assert results[7] == {'token': ' \t', 'finish_reason': None}
        assert results[9] == {'token': '', 'finish_reason': 'stop'}

        assert mock_sleep.call_count == 5

    @patch('time.sleep')
    def test_streams_empty_string(self, mock_sleep):
        """Should yield a single 'stop' token for empty content."""
        content = ""
        generator = stream_static_content(content)
        results = list(generator)

        assert len(results) == 1
        assert results[0] == {'token': '', 'finish_reason': 'stop'}
        mock_sleep.assert_not_called()


class TestHandleArithmeticProcessor:
    """Tests the 'ArithmeticProcessor' node logic."""

    @pytest.mark.parametrize("expression, agent_outputs, expected", [
        ("10 + 5", {}, "15"),
        ("10.5 - 5.5", {}, "5"),
        ("10 * 2.5", {}, "25"),
        ("10 / 4", {}, "2.5"),
        ("-5 * 10", {}, "-50"),
        ("{val} + 2", {"val": "8"}, "10"),
        (" 20  /  -4 ", {}, "-5"),
    ])
    def test_valid_expressions(self, specialized_handler, base_context, mock_variable_service, expression,
                               agent_outputs, expected):
        """Should correctly evaluate valid arithmetic expressions."""
        base_context.config = {"expression": expression}
        base_context.agent_outputs = agent_outputs

        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(val=c.agent_outputs.get('val'))

        result = specialized_handler.handle_arithmetic_processor(base_context)
        assert result == expected

    @pytest.mark.parametrize("expression, agent_outputs, warning_msg", [
        ("10 / 0", {}, "Division by zero"),
        ("10 ++ 5", {}, "Invalid arithmetic expression format"),
        ("ten + 5", {}, "Invalid arithmetic expression format"),
        ("{val} + 5", {"val": "text"}, "Invalid arithmetic expression format"),
    ])
    def test_invalid_expressions_return_minus_one(self, specialized_handler, base_context, mock_variable_service,
                                                  expression, agent_outputs, warning_msg):
        """Should return '-1' for invalid or erroneous expressions."""
        base_context.config = {"expression": expression}
        base_context.agent_outputs = agent_outputs

        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(val=c.agent_outputs.get('val', ''))

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_arithmetic_processor(base_context)
            assert result == "-1"
            mock_log.assert_called_once()
            assert warning_msg in mock_log.call_args[0][0]

    def test_missing_expression_returns_minus_one(self, specialized_handler, base_context):
        """Should return '-1' if the 'expression' property is missing."""
        base_context.config = {}
        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_arithmetic_processor(base_context)
            assert result == "-1"
            mock_log.assert_called_once_with("ArithmeticProcessor node is missing 'expression'.")


class TestHandleConditionalSimple:
    """Tests the 'Conditional' node logic for simple, single comparisons."""

    @pytest.mark.parametrize("condition_template, agent_outputs, expected", [
        ("10 > 5", {}, "TRUE"),
        ("5 > 10", {}, "FALSE"),
        ("10 >= 10", {}, "TRUE"),
        ("5.5 <= 5.4", {}, "FALSE"),
        ("5 == 5.0", {}, "TRUE"),
        ("'hello' == 'hello'", {}, "TRUE"),
        ('"world" != "World"', {}, "TRUE"),
        ("{val} > 5", {"val": "10"}, "TRUE"),
        ("'{status}' == 'done'", {"status": "done"}, "TRUE"),
        ("'{status}' == 'pending'", {"status": "done"}, "FALSE"),
        ("10 == '10'", {}, "FALSE"),
        ("5 > 'hello'", {}, "FALSE"),
    ])
    def test_valid_conditions(self, specialized_handler, base_context, mock_variable_service,
                              condition_template, agent_outputs, expected):
        """Should correctly evaluate various valid conditions to TRUE or FALSE."""
        base_context.config = {"condition": condition_template}
        base_context.agent_outputs = agent_outputs
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(
            val=c.agent_outputs.get('val'), status=c.agent_outputs.get('status'))

        result = specialized_handler.handle_conditional(base_context)
        assert result == expected

    def test_missing_condition_returns_false(self, specialized_handler, base_context):
        """Should return 'FALSE' if the 'condition' property is missing."""
        base_context.config = {}
        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_conditional(base_context)
            assert result == "FALSE"
            mock_log.assert_called_once_with("Conditional node is missing 'condition'.")


class TestHandleConditionalComplex:
    """Tests the 'Conditional' node with complex logic (AND, OR, parentheses)."""

    @pytest.mark.parametrize("condition_template, agent_outputs, expected", [
        ("5 > 3 AND 'a' == 'a'", {}, "TRUE"),
        ("5 > 3 AND 'a' == 'b'", {}, "FALSE"),
        ("a == a OR b == a", {}, "TRUE"),
        ("a == b OR b == a", {}, "FALSE"),
        ("5 < 3 OR 'a' == 'a'", {}, "TRUE"),
        ("5 < 3 OR 'a' == 'b'", {}, "FALSE"),
        ("(5 < 3) OR ('a' == 'a')", {}, "TRUE"),
        ("(2 < 3) OR ('a' == 'b')", {}, "TRUE"),
        ("true AND 5 > 3", {}, "TRUE"),
        ("5 < 3 or TRUE", {}, "TRUE"),
        ("FALSE OR TRUE AND TRUE", {}, "TRUE"),
        ("TRUE AND FALSE OR TRUE", {}, "TRUE"),
        ("FALSE AND TRUE OR FALSE", {}, "FALSE"),
        ("(FALSE OR TRUE) AND FALSE", {}, "FALSE"),
        ("5 > 3 AND (5 < 3 OR 1 == 1)", {}, "TRUE"),
        ("((5 > 3 AND 1 == 1) OR 2 < 1) AND 'x' == 'x'", {}, "TRUE"),
        ("((5 > 3 AND 1 == 0) OR 2 < 1) AND 'x' == 'x'", {}, "FALSE"),
        ("{val} > 5 AND '{status}' == 'complete'", {"val": 10, "status": "complete"}, "TRUE"),
        ("{val} > 5 AND '{status}' == 'complete'", {"val": 3, "status": "complete"}, "FALSE"),
        ("({val} > 5 OR '{status}' == 'pending') AND {is_admin}", {"val": 3, "status": "pending", "is_admin": "TRUE"},
         "TRUE"),
        ("{output} AND {val} > 10", {"output": "some_string", "val": 20}, "TRUE"),
        ("{output} AND {val} > 10", {"output": "", "val": 20}, "FALSE"),
        ("{output} OR {val} > 10", {"output": 0, "val": 5}, "FALSE"),
    ])
    def test_complex_expressions(self, specialized_handler, base_context, mock_variable_service,
                                 condition_template, agent_outputs, expected):
        """Should correctly evaluate complex logical expressions."""
        base_context.config = {"condition": condition_template}
        base_context.agent_outputs = agent_outputs

        def apply_vars_side_effect(template, context):
            return template.format(**context.agent_outputs)

        mock_variable_service.apply_variables.side_effect = apply_vars_side_effect

        result = specialized_handler.handle_conditional(base_context)
        assert result == expected

    @pytest.mark.parametrize("condition, warning_msg", [
        ("5 > 3 AND", "Syntax error: Not enough operands for 'AND'"),
        ("(5 > 3", "Mismatched parentheses: missing ')'"),
        ("5 > < 3", "Syntax error: Operator '<' must follow a single value."),
        ("5 OR AND 3", "Syntax error: Not enough operands for 'OR'"),
    ])
    def test_malformed_expressions(self, specialized_handler, base_context, mock_variable_service,
                                   condition, warning_msg):
        """Should return FALSE and log a warning for malformed expressions."""
        base_context.config = {"condition": condition}
        mock_variable_service.apply_variables.return_value = condition

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_conditional(base_context)
            assert result == "FALSE"
            mock_log.assert_called_once()
            assert warning_msg in mock_log.call_args[0][0]


class TestHandleStringConcatenator:
    """Tests the 'StringConcatenator' node logic."""

    @pytest.mark.parametrize("strings_template, agent_outputs, delimiter, expected", [
        (["Hello", " ", "World"], {}, "", "Hello World"),
        (["Part1", "Part2"], {}, "-", "Part1-Part2"),
        (["Name: {name}", "Age: {age}"], {"name": "Test", "age": 30}, "\n", "Name: Test\nAge: 30"),
        (["Count:", 100], {}, " ", "Count: 100"),
        ([], {}, ",", ""),
        (["Single"], {}, ",", "Single"),
        (["A", "B", "C"], {}, None, "ABC"),
    ])
    def test_non_streaming(self, specialized_handler, base_context, mock_variable_service,
                           strings_template, agent_outputs, delimiter, expected):
        """Should correctly concatenate strings and resolve variables when not streaming."""
        config = {"strings": strings_template}
        if delimiter is not None:
            config["delimiter"] = delimiter
        base_context.config = config
        base_context.agent_outputs = agent_outputs
        base_context.stream = False

        def apply_vars_side_effect(template, context):
            if isinstance(template, str):
                return template.format(**context.agent_outputs)
            return str(template)

        mock_variable_service.apply_variables.side_effect = apply_vars_side_effect

        result = specialized_handler.handle_string_concatenator(base_context)

        assert isinstance(result, str)
        assert result == expected

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.stream_static_content')
    def test_streaming(self, mock_streamer, specialized_handler, base_context, mock_variable_service):
        """Should call the streamer utility with the concatenated string when streaming."""
        base_context.config = {"strings": ["Streaming", " ", "test"], "delimiter": ""}
        base_context.stream = True

        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_string_concatenator(base_context)

        assert result == mock_streamer.return_value
        mock_streamer.assert_called_once_with("Streaming test")

    def test_handles_non_list_strings_property(self, specialized_handler, base_context):
        """Should return an empty string if 'strings' is not a list."""
        base_context.config = {"strings": "this-is-not-a-list"}

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_string_concatenator(base_context)
            assert result == ""
            mock_log.assert_called_once_with("StringConcatenator 'strings' property must be a list.")


class TestStripMarkdownCodeBlock:
    """Tests the '_strip_markdown_code_block' helper method."""

    def test_strips_json_code_block(self, specialized_handler):
        """Should strip ```json code block formatting."""
        text = '```json\n{"name": "test"}\n```'
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == '{"name": "test"}'

    def test_strips_json_uppercase_code_block(self, specialized_handler):
        """Should strip ```JSON (uppercase) code block formatting."""
        text = '```JSON\n{"name": "test"}\n```'
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == '{"name": "test"}'

    def test_strips_plain_code_block(self, specialized_handler):
        """Should strip plain ``` code block formatting."""
        text = '```\n{"name": "test"}\n```'
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == '{"name": "test"}'

    def test_handles_no_newline_after_backticks(self, specialized_handler):
        """Should handle code blocks without newline after opening backticks."""
        text = '```json{"name": "test"}```'
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == '{"name": "test"}'

    def test_returns_unchanged_when_no_code_block(self, specialized_handler):
        """Should return the original text when no code block formatting is present."""
        text = '{"name": "test"}'
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == '{"name": "test"}'

    def test_handles_whitespace_around_code_block(self, specialized_handler):
        """Should strip surrounding whitespace from code blocks."""
        text = '  \n```json\n{"name": "test"}\n```\n  '
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == '{"name": "test"}'

    def test_preserves_content_with_newlines(self, specialized_handler):
        """Should preserve newlines within the code block content."""
        text = '```json\n{\n  "name": "test",\n  "value": 123\n}\n```'
        result = specialized_handler._strip_markdown_code_block(text)
        assert '"name": "test"' in result
        assert '"value": 123' in result


class TestHandleJsonExtractor:
    """Tests the 'JsonExtractor' node logic."""

    def test_extracts_simple_string_field(self, specialized_handler, base_context, mock_variable_service):
        """Should extract a simple string field from JSON."""
        json_string = '{"name": "Alice", "file": "notes.txt"}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "Alice"

    def test_extracts_second_field(self, specialized_handler, base_context, mock_variable_service):
        """Should extract any specified field from JSON."""
        json_string = '{"name": "Alice", "file": "notes.txt"}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "file"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "notes.txt"

    def test_extracts_numeric_field(self, specialized_handler, base_context, mock_variable_service):
        """Should extract numeric fields and convert to string."""
        json_string = '{"name": "test", "count": 42}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "count"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "42"

    def test_extracts_boolean_field(self, specialized_handler, base_context, mock_variable_service):
        """Should extract boolean fields and convert to string."""
        json_string = '{"name": "test", "active": true}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "active"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "True"

    def test_extracts_nested_object_as_json_string(self, specialized_handler, base_context, mock_variable_service):
        """Should extract nested objects and return as JSON string."""
        json_string = '{"name": "test", "details": {"a": 1, "b": 2}}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "details"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == '{"a": 1, "b": 2}'

    def test_extracts_array_as_json_string(self, specialized_handler, base_context, mock_variable_service):
        """Should extract arrays and return as JSON string."""
        json_string = '{"name": "test", "items": [1, 2, 3]}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "items"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == '[1, 2, 3]'

    def test_handles_markdown_json_code_block(self, specialized_handler, base_context, mock_variable_service):
        """Should handle JSON wrapped in ```json code block."""
        json_string = '```json\n{"name": "Alice", "file": "notes.txt"}\n```'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "Alice"

    def test_handles_plain_markdown_code_block(self, specialized_handler, base_context, mock_variable_service):
        """Should handle JSON wrapped in plain ``` code block."""
        json_string = '```\n{"name": "Alice", "file": "notes.txt"}\n```'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "Alice"

    def test_applies_variables_to_json_source(self, specialized_handler, base_context, mock_variable_service):
        """Should apply variable substitution to jsonToExtractFrom."""
        base_context.config = {
            "jsonToExtractFrom": "{agent1Input}",
            "fieldToExtract": "name"
        }
        base_context.agent_inputs = {"agent1Input": '{"name": "FromVariable"}'}

        def mock_apply(template, ctx):
            if template == "{agent1Input}":
                return ctx.agent_inputs.get("agent1Input", template)
            return template

        mock_variable_service.apply_variables.side_effect = mock_apply

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "FromVariable"

    def test_applies_variables_to_field_name(self, specialized_handler, base_context, mock_variable_service):
        """Should apply variable substitution to fieldToExtract."""
        base_context.config = {
            "jsonToExtractFrom": '{"dynamic_field": "value"}',
            "fieldToExtract": "{fieldName}"
        }
        base_context.agent_inputs = {"fieldName": "dynamic_field"}

        def mock_apply(template, ctx):
            if template == "{fieldName}":
                return ctx.agent_inputs.get("fieldName", template)
            return template

        mock_variable_service.apply_variables.side_effect = mock_apply

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "value"

    def test_returns_empty_for_missing_field(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string when field is not found."""
        json_string = '{"name": "test"}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "nonexistent"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""

    def test_returns_empty_for_invalid_json(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string for invalid JSON."""
        base_context.config = {
            "jsonToExtractFrom": "not valid json",
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_json_extractor(base_context)
            assert result == ""
            assert mock_log.called
            assert "failed to parse JSON" in mock_log.call_args[0][0]

    def test_returns_empty_for_json_array(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string when JSON is an array instead of object."""
        base_context.config = {
            "jsonToExtractFrom": '[1, 2, 3]',
            "fieldToExtract": "0"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_json_extractor(base_context)
            assert result == ""
            assert "expected a JSON object" in mock_log.call_args[0][0]

    def test_returns_empty_when_json_source_missing(self, specialized_handler, base_context):
        """Should return empty string and log warning when jsonToExtractFrom is missing."""
        base_context.config = {"fieldToExtract": "name"}

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_json_extractor(base_context)
            assert result == ""
            mock_log.assert_called_once_with("JsonExtractor node is missing 'jsonToExtractFrom'.")

    def test_returns_empty_when_field_name_missing(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string and log warning when fieldToExtract is missing."""
        base_context.config = {"jsonToExtractFrom": '{"name": "test"}'}
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_json_extractor(base_context)
            assert result == ""
            mock_log.assert_called_once_with("JsonExtractor node is missing 'fieldToExtract'.")

    def test_handles_null_value(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string when field value is null."""
        json_string = '{"name": null}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""

    def test_handles_empty_string_value(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string when field value is empty string."""
        json_string = '{"name": ""}'
        base_context.config = {
            "jsonToExtractFrom": json_string,
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""


class TestHandleTagTextExtractor:
    """Tests the 'TagTextExtractor' node logic."""

    def test_extracts_simple_tag_content(self, specialized_handler, base_context, mock_variable_service):
        """Should extract content from simple XML-style tags."""
        text = """This is some text.

<thing_I_Want>
    Output that I want to grab
</thing_I_Want>

More text"""
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "thing_I_Want"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "Output that I want to grab"

    def test_extracts_content_without_surrounding_whitespace(self, specialized_handler, base_context, mock_variable_service):
        """Should strip leading/trailing whitespace from extracted content."""
        text = "<tag>   content with spaces   </tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "content with spaces"

    def test_extracts_multiline_content(self, specialized_handler, base_context, mock_variable_service):
        """Should extract multiline content between tags."""
        text = """<output>
Line 1
Line 2
Line 3
</output>"""
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "output"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_extracts_content_with_nested_elements(self, specialized_handler, base_context, mock_variable_service):
        """Should extract content including nested HTML/XML elements."""
        text = "<wrapper><inner>nested content</inner></wrapper>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "wrapper"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "<inner>nested content</inner>"

    def test_extracts_first_matching_tag(self, specialized_handler, base_context, mock_variable_service):
        """Should extract content from the first matching tag when multiple exist."""
        text = "<tag>first</tag> some text <tag>second</tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "first"

    def test_applies_variables_to_text_source(self, specialized_handler, base_context, mock_variable_service):
        """Should apply variable substitution to tagToExtractFrom."""
        base_context.config = {
            "tagToExtractFrom": "{agent1Input}",
            "fieldToExtract": "result"
        }
        base_context.agent_inputs = {"agent1Input": "<result>extracted value</result>"}

        def mock_apply(template, ctx):
            if template == "{agent1Input}":
                return ctx.agent_inputs.get("agent1Input", template)
            return template

        mock_variable_service.apply_variables.side_effect = mock_apply

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "extracted value"

    def test_applies_variables_to_tag_name(self, specialized_handler, base_context, mock_variable_service):
        """Should apply variable substitution to fieldToExtract."""
        text = "<dynamic_tag>content</dynamic_tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "{tagName}"
        }
        base_context.agent_inputs = {"tagName": "dynamic_tag"}

        def mock_apply(template, ctx):
            if template == "{tagName}":
                return ctx.agent_inputs.get("tagName", template)
            return template

        mock_variable_service.apply_variables.side_effect = mock_apply

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "content"

    def test_returns_empty_for_missing_tag(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string when tag is not found."""
        text = "<other>some content</other>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "nonexistent"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_returns_empty_when_text_source_missing(self, specialized_handler, base_context):
        """Should return empty string and log warning when tagToExtractFrom is missing."""
        base_context.config = {"fieldToExtract": "tag"}

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_tag_text_extractor(base_context)
            assert result == ""
            mock_log.assert_called_once_with("TagTextExtractor node is missing 'tagToExtractFrom'.")

    def test_returns_empty_when_tag_name_missing(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string and log warning when fieldToExtract is missing."""
        base_context.config = {"tagToExtractFrom": "<tag>content</tag>"}
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_tag_text_extractor(base_context)
            assert result == ""
            mock_log.assert_called_once_with("TagTextExtractor node is missing 'fieldToExtract'.")

    def test_handles_special_regex_characters_in_tag_name(self, specialized_handler, base_context, mock_variable_service):
        """Should properly escape special regex characters in tag names."""
        text = "<tag.with.dots>content</tag.with.dots>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag.with.dots"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "content"

    def test_handles_tags_with_underscores(self, specialized_handler, base_context, mock_variable_service):
        """Should handle tag names with underscores."""
        text = "<my_custom_tag>underscore content</my_custom_tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "my_custom_tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "underscore content"

    def test_handles_tags_with_hyphens(self, specialized_handler, base_context, mock_variable_service):
        """Should handle tag names with hyphens."""
        text = "<my-custom-tag>hyphen content</my-custom-tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "my-custom-tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "hyphen content"

    def test_handles_empty_tag_content(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string for empty tag content."""
        text = "<tag></tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_handles_whitespace_only_content(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string when tag content is only whitespace."""
        text = "<tag>   \n   </tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_does_not_match_mismatched_tags(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty when opening and closing tags don't match."""
        text = "<tag>content</other_tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_case_sensitive_tag_matching(self, specialized_handler, base_context, mock_variable_service):
        """Should perform case-sensitive tag matching."""
        text = "<Tag>content</Tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_extracts_from_middle_of_larger_text(self, specialized_handler, base_context, mock_variable_service):
        """Should extract tag from the middle of a larger document."""
        text = """
        Some preamble text here.
        More content about various things.

        <answer>
        The actual answer we want
        </answer>

        And some footer text.
        More stuff at the end.
        """
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "answer"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "The actual answer we want"

    def test_nested_same_name_tags_extracts_first_match(self, specialized_handler, base_context, mock_variable_service):
        """Should extract from first opening to first closing tag with non-greedy matching."""
        text = "<tag><tag>inner</tag></tag>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        # Non-greedy .*? matches from first <tag> to first </tag>
        assert result == "<tag>inner"

    def test_self_closing_tags_do_not_match(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty string for self-closing tags like <tag/>."""
        text = "<tag/> some other text"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_tags_with_attributes_do_not_match(self, specialized_handler, base_context, mock_variable_service):
        """Should not match tags with attributes since regex requires exact <tag>."""
        text = '<tag class="foo">content</tag>'
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == ""

    def test_additional_special_regex_characters(self, specialized_handler, base_context, mock_variable_service):
        """Should escape special regex characters beyond dots (brackets, parens, etc)."""
        text = "<tag[0]>content</tag[0]>"
        base_context.config = {
            "tagToExtractFrom": text,
            "fieldToExtract": "tag[0]"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_tag_text_extractor(base_context)

        assert result == "content"


class TestStripMarkdownCodeBlockEdgeCases:
    """Additional edge case tests for _strip_markdown_code_block."""

    def test_non_json_language_tag_stripped_with_tag_in_content(self, specialized_handler):
        """Code blocks with non-json language tags get stripped, but tag becomes part of content."""
        text = '```python\ndef hello():\n    pass\n```'
        result = specialized_handler._strip_markdown_code_block(text)
        # The regex makes json/JSON optional, so ```python still matches as a code block.
        # The language tag 'python' is not consumed by the optional group, so it
        # becomes part of the captured content.
        assert result == 'python\ndef hello():\n    pass'

    def test_mixed_case_json_stripped_with_tag_in_content(self, specialized_handler):
        """Code blocks with mixed-case ```Json are stripped, but 'Json' becomes part of content."""
        text = '```Json\n{"name": "test"}\n```'
        result = specialized_handler._strip_markdown_code_block(text)
        # (?:json|JSON)? only matches exact 'json' or 'JSON', not 'Json'
        assert result == 'Json\n{"name": "test"}'

    def test_whitespace_only_content_in_code_block(self, specialized_handler):
        """Should return empty string when code block contains only whitespace."""
        text = '```json\n   \n```'
        result = specialized_handler._strip_markdown_code_block(text)
        assert result == ""


class TestJsonExtractorEdgeCases:
    """Additional edge case tests for JsonExtractor."""

    def test_top_level_string_not_a_dict(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty for top-level JSON string (not a dict)."""
        base_context.config = {
            "jsonToExtractFrom": '"just a string"',
            "fieldToExtract": "anything"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""

    def test_top_level_number_not_a_dict(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty for top-level JSON number (not a dict)."""
        base_context.config = {
            "jsonToExtractFrom": '42',
            "fieldToExtract": "anything"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""

    def test_top_level_boolean_not_a_dict(self, specialized_handler, base_context, mock_variable_service):
        """Should return empty for top-level JSON boolean (not a dict)."""
        base_context.config = {
            "jsonToExtractFrom": 'true',
            "fieldToExtract": "anything"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""

    def test_float_value_extraction(self, specialized_handler, base_context, mock_variable_service):
        """Should extract float values and convert to string."""
        base_context.config = {
            "jsonToExtractFrom": '{"pi": 3.14}',
            "fieldToExtract": "pi"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "3.14"

    def test_field_name_with_special_characters(self, specialized_handler, base_context, mock_variable_service):
        """Should handle field names with spaces, dots, and hyphens."""
        base_context.config = {
            "jsonToExtractFrom": '{"field with spaces": "val1", "field.name": "val2"}',
            "fieldToExtract": "field with spaces"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "val1"

    def test_dot_notation_field_does_not_do_nested_access(self, specialized_handler, base_context, mock_variable_service):
        """Should not do nested access with dot notation — treats field name literally."""
        base_context.config = {
            "jsonToExtractFrom": '{"details": {"name": "inner"}}',
            "fieldToExtract": "details.name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == ""

    def test_uppercase_json_code_block_integration(self, specialized_handler, base_context, mock_variable_service):
        """Should handle JSON wrapped in uppercase ```JSON code block."""
        base_context.config = {
            "jsonToExtractFrom": '```JSON\n{"name": "test"}\n```',
            "fieldToExtract": "name"
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_json_extractor(base_context)

        assert result == "test"


class TestHandleDelimitedChunker:
    """Tests the 'DelimitedChunker' node logic."""

    def test_head_mode_returns_first_n_chunks(self, specialized_handler, base_context, mock_variable_service):
        """Should return the first N chunks when mode is 'head'."""
        base_context.config = {
            "content": "a,b,c,d,e",
            "delimiter": ",",
            "mode": "head",
            "count": 3
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "a,b,c"

    def test_tail_mode_returns_last_n_chunks(self, specialized_handler, base_context, mock_variable_service):
        """Should return the last N chunks when mode is 'tail'."""
        base_context.config = {
            "content": "a,b,c,d,e",
            "delimiter": ",",
            "mode": "tail",
            "count": 2
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "d,e"

    def test_count_equals_chunks_returns_full_content(self, specialized_handler, base_context, mock_variable_service):
        """Should return the full content when count equals the number of chunks."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head",
            "count": 3
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "a,b,c"

    def test_count_exceeds_chunks_returns_full_content(self, specialized_handler, base_context, mock_variable_service):
        """Should return the full content unchanged when count exceeds the number of chunks."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "tail",
            "count": 10
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "a,b,c"

    def test_empty_content_returns_empty_string(self, specialized_handler, base_context, mock_variable_service):
        """Should return an empty string when content is empty."""
        base_context.config = {
            "content": "",
            "delimiter": ",",
            "mode": "head",
            "count": 3
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == ""

    def test_delimiter_not_found_returns_full_content(self, specialized_handler, base_context, mock_variable_service):
        """Should return the full content when the delimiter is not present (one chunk)."""
        base_context.config = {
            "content": "no delimiters here",
            "delimiter": ",",
            "mode": "head",
            "count": 1
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "no delimiters here"

    def test_missing_content_returns_error(self, specialized_handler, base_context):
        """Should return an error message when 'content' is missing."""
        base_context.config = {
            "delimiter": ",",
            "mode": "head",
            "count": 3
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "No content specified"

    def test_missing_delimiter_returns_error(self, specialized_handler, base_context):
        """Should return an error message when 'delimiter' is missing."""
        base_context.config = {
            "content": "a,b,c",
            "mode": "head",
            "count": 3
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "No delimiter specified"

    def test_missing_mode_returns_error(self, specialized_handler, base_context):
        """Should return an error message when 'mode' is missing."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "count": 3
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "No mode specified"

    def test_missing_count_returns_error(self, specialized_handler, base_context):
        """Should return an error message when 'count' is missing."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head"
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "No count specified"

    def test_invalid_mode_returns_error(self, specialized_handler, base_context, mock_variable_service):
        """Should return an error message when mode is not 'head' or 'tail'."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "middle",
            "count": 2
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "Invalid mode: must be 'head' or 'tail', got 'middle'"

    def test_count_zero_returns_error(self, specialized_handler, base_context):
        """Should return an error message when count is zero."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head",
            "count": 0
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "Invalid count: must be >= 1, got 0"

    def test_count_negative_returns_error(self, specialized_handler, base_context):
        """Should return an error message when count is negative."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head",
            "count": -2
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "Invalid count: must be >= 1, got -2"

    def test_count_not_integer_returns_error(self, specialized_handler, base_context):
        """Should return an error message when count is a float."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head",
            "count": 2.5
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "Invalid count: must be an integer, got float"

    def test_count_string_returns_error(self, specialized_handler, base_context):
        """Should return an error message when count is a string."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head",
            "count": "3"
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "Invalid count: must be an integer, got str"

    def test_count_boolean_returns_error(self, specialized_handler, base_context):
        """Should return an error message when count is a boolean (subclass of int)."""
        base_context.config = {
            "content": "a,b,c",
            "delimiter": ",",
            "mode": "head",
            "count": True
        }

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "Invalid count: must be an integer, got bool"

    def test_multichar_delimiter(self, specialized_handler, base_context, mock_variable_service):
        """Should correctly split and rejoin with a multi-character delimiter."""
        base_context.config = {
            "content": "chunk1---chunk2---chunk3---chunk4",
            "delimiter": "---",
            "mode": "head",
            "count": 2
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "chunk1---chunk2"

    def test_newline_delimiter(self, specialized_handler, base_context, mock_variable_service):
        """Should work with newline as the delimiter."""
        base_context.config = {
            "content": "line1\nline2\nline3\nline4",
            "delimiter": "\n",
            "mode": "tail",
            "count": 2
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "line3\nline4"

    def test_variable_substitution_in_content(self, specialized_handler, base_context, mock_variable_service):
        """Should resolve variables in the content field."""
        base_context.config = {
            "content": "{agent1Output}",
            "delimiter": ",",
            "mode": "head",
            "count": 2
        }
        base_context.agent_outputs = {"agent1Output": "x,y,z"}
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(
            **(c.agent_inputs or {}), **(c.agent_outputs or {})
        )

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "x,y"

    def test_variable_substitution_in_delimiter(self, specialized_handler, base_context, mock_variable_service):
        """Should resolve variables in the delimiter field."""
        base_context.config = {
            "content": "a||b||c||d",
            "delimiter": "{agent1Output}",
            "mode": "tail",
            "count": 2
        }
        base_context.agent_outputs = {"agent1Output": "||"}
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(
            **(c.agent_inputs or {}), **(c.agent_outputs or {})
        )

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "c||d"

    def test_head_count_one(self, specialized_handler, base_context, mock_variable_service):
        """Should return only the first chunk when count is 1."""
        base_context.config = {
            "content": "first,second,third",
            "delimiter": ",",
            "mode": "head",
            "count": 1
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "first"

    def test_tail_count_one(self, specialized_handler, base_context, mock_variable_service):
        """Should return only the last chunk when count is 1."""
        base_context.config = {
            "content": "first,second,third",
            "delimiter": ",",
            "mode": "tail",
            "count": 1
        }
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_delimited_chunker(base_context)

        assert result == "third"
