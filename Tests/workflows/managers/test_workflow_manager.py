# tests/workflows/managers/test_workflow_manager.py

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from Middleware.workflows.managers.workflow_manager import WorkflowManager


@pytest.fixture
def mock_dependencies(mocker):
    """Mocks all external dependencies for WorkflowManager and its child components."""
    # Mock service instantiations
    mocker.patch("Middleware.workflows.managers.workflow_manager.LlmHandlerService")
    mocker.patch("Middleware.workflows.managers.workflow_manager.LockingService")
    mocker.patch("Middleware.workflows.managers.workflow_manager.WorkflowVariableManager")

    # Mock handler instantiations
    mocker.patch("Middleware.workflows.managers.workflow_manager.MemoryNodeHandler")
    mocker.patch("Middleware.workflows.managers.workflow_manager.ToolNodeHandler")
    mocker.patch("Middleware.workflows.managers.workflow_manager.SpecializedNodeHandler")
    mocker.patch("Middleware.workflows.managers.workflow_manager.SubWorkflowHandler")
    mocker.patch("Middleware.workflows.managers.workflow_manager.StandardNodeHandler")

    # Mock the WorkflowProcessor, which is the primary component orchestrated by the manager
    mock_processor_class = mocker.patch("Middleware.workflows.managers.workflow_manager.WorkflowProcessor")
    mock_processor_instance = MagicMock()
    mock_processor_instance.execute.return_value = iter(["non-streaming result"])
    mock_processor_class.return_value = mock_processor_instance

    # Mock utility functions
    mock_uuid = mocker.patch("uuid.uuid4", return_value="mock-workflow-id")
    mock_extract_id = mocker.patch("Middleware.workflows.managers.workflow_manager.extract_discussion_id")
    mock_remove_tag = mocker.patch("Middleware.workflows.managers.workflow_manager.remove_discussion_id_tag")
    mock_default_path_finder = mocker.patch(
        "Middleware.workflows.managers.workflow_manager.default_get_workflow_path",
        return_value="/fake/path/workflow.json"
    )

    # Mock file I/O for loading workflow configs
    mock_file_open = mocker.patch("builtins.open", mock_open(read_data='{}'))
    mock_json_load = mocker.patch("json.load")

    return {
        "WorkflowProcessor": mock_processor_class,
        "mock_processor_instance": mock_processor_instance,
        "LockingService": mocker.patch('Middleware.workflows.managers.workflow_manager.LockingService'),
        "default_get_workflow_path": mock_default_path_finder,
        "extract_discussion_id": mock_extract_id,
        "remove_discussion_id_tag": mock_remove_tag,
        "json_load": mock_json_load,
        "open": mock_file_open
    }


class TestWorkflowManagerInitialization:
    """Tests the __init__ method of the WorkflowManager."""

    def test_init_default_path_finder(self, mock_dependencies):
        """
        Verifies that the default path finder function is used when no override is provided.
        """
        manager = WorkflowManager(workflow_config_name="test_workflow")
        assert manager.path_finder_func == mock_dependencies["default_get_workflow_path"]

    def test_init_with_user_folder_override(self, mock_dependencies):
        """
        Verifies that a lambda with the correct override is created for the path finder.
        """
        manager = WorkflowManager("test_workflow", workflow_user_folder_override="custom_user")
        manager.path_finder_func("some_workflow")

        mock_dependencies["default_get_workflow_path"].assert_called_once_with(
            "some_workflow", user_folder_override="custom_user"
        )

    def test_init_registers_all_node_handlers(self, mock_dependencies):
        """
        Verifies that all expected node types are registered in the node_handlers dictionary.
        """
        manager = WorkflowManager(workflow_config_name="test_workflow")
        expected_node_types = [
            "Standard", "PythonModule", "SlowButQualityRAG", "ConversationMemory",
            "FullChatSummary", "RecentMemory", "RecentMemorySummarizerTool",
            "ChatSummaryMemoryGatheringTool", "GetCurrentSummaryFromFile",
            "chatSummarySummarizer", "WriteCurrentSummaryToFileAndReturnIt",
            "QualityMemory", "GetCurrentMemoryFromFile", "ConversationalKeywordSearchPerformerTool",
            "MemoryKeywordSearchPerformerTool", "VectorMemorySearch", "OfflineWikiApiFullArticle",
            "OfflineWikiApiBestFullArticle", "OfflineWikiApiTopNFullArticles",
            "OfflineWikiApiPartialArticle", "CustomWorkflow", "ConditionalCustomWorkflow",
            "WorkflowLock", "GetCustomFile", "SaveCustomFile", "ImageProcessor", "StaticResponse"
        ]
        for node_type in expected_node_types:
            assert node_type in manager.node_handlers


class TestRunWorkflow:
    """Tests the core run_workflow instance method."""

    def test_run_workflow_non_streaming_dict_config(self, mock_dependencies):
        """
        Tests the happy path for a non-streaming request with a modern, dictionary-based workflow config.
        """
        workflow_dict = {"nodes": [{"type": "Standard"}], "custom_var": "value"}
        mock_dependencies["json_load"].return_value = workflow_dict
        manager = WorkflowManager(workflow_config_name="test_workflow")

        result = manager.run_workflow(messages=[], request_id="req-123", stream=False)

        assert result == "non-streaming result"

        # Verify the processor was initialized with correctly parsed config
        call_kwargs = mock_dependencies["WorkflowProcessor"].call_args.kwargs
        assert call_kwargs["workflow_file_config"] == workflow_dict
        assert call_kwargs["configs"] == workflow_dict["nodes"]

    def test_run_workflow_non_streaming_list_config(self, mock_dependencies):
        """
        Tests that the manager correctly handles the legacy list-based workflow format.
        """
        workflow_list = [{"type": "Standard", "title": "Legacy Node"}]
        mock_dependencies["json_load"].return_value = workflow_list
        manager = WorkflowManager(workflow_config_name="test_workflow")

        manager.run_workflow(messages=[], request_id="req-123")

        call_kwargs = mock_dependencies["WorkflowProcessor"].call_args.kwargs
        assert call_kwargs["workflow_file_config"] == {}
        assert call_kwargs["configs"] == workflow_list

    def test_run_workflow_streaming_success(self, mock_dependencies):
        """
        Tests that a streaming workflow correctly returns the generator from the processor.
        """
        mock_generator = iter(["chunk1", "chunk2"])
        mock_dependencies["mock_processor_instance"].execute.return_value = mock_generator
        manager = WorkflowManager(workflow_config_name="test_workflow")

        result = manager.run_workflow(messages=[], request_id="123", stream=True)

        assert result is mock_generator
        assert list(result) == ["chunk1", "chunk2"]

    @pytest.mark.parametrize("yield_values, expected_result, expected_log_msg", [
        ([], None, "Non-streaming workflow returned no output."),
        (["first", "last"], "last", "Expected 1 output from non-streaming workflow, but got 2"),
    ])
    def test_run_workflow_non_streaming_edge_cases(self, mock_dependencies, caplog, yield_values, expected_result,
                                                   expected_log_msg):
        """Tests non-streaming edge cases: no output and multiple outputs."""
        mock_dependencies["mock_processor_instance"].execute.return_value = iter(yield_values)
        manager = WorkflowManager(workflow_config_name="test_workflow")

        result = manager.run_workflow(messages=[], request_id="123")

        assert result == expected_result
        assert expected_log_msg in caplog.text

    def test_run_workflow_handles_discussion_id(self, mock_dependencies):
        """
        Tests that discussion ID is correctly extracted or used if provided.
        """
        messages = [{"role": "user", "content": "[DiscussionId]extracted-id[/DiscussionId] Hello"}]
        manager = WorkflowManager(workflow_config_name="test_workflow")

        # Case 1: discussionId is passed in, so we don't extract
        mock_dependencies["extract_discussion_id"].return_value = "extracted-id"
        manager.run_workflow(messages=messages, request_id="123", discussionId="provided-id")

        assert mock_dependencies["WorkflowProcessor"].call_args.kwargs["discussion_id"] == "provided-id"
        mock_dependencies["extract_discussion_id"].assert_not_called()
        mock_dependencies["remove_discussion_id_tag"].assert_called_once_with(messages)

        # Case 2: discussionId is None, so we extract it
        mock_dependencies["extract_discussion_id"].reset_mock()
        mock_dependencies["remove_discussion_id_tag"].reset_mock()
        manager.run_workflow(messages=messages, request_id="456")

        assert mock_dependencies["WorkflowProcessor"].call_args.kwargs["discussion_id"] == "extracted-id"
        mock_dependencies["extract_discussion_id"].assert_called_once_with(messages)

    def test_run_workflow_exception_handling(self, mock_dependencies):
        """
        Ensures that locks are cleared even if the workflow execution fails.
        """
        mock_dependencies["open"].side_effect = json.JSONDecodeError("mock error", "", 0)
        manager = WorkflowManager("test_workflow")

        with pytest.raises(json.JSONDecodeError):
            manager.run_workflow(messages=[], request_id="123")

        manager.locking_service.delete_node_locks.assert_called_once()


@patch("Middleware.workflows.managers.workflow_manager.WorkflowManager")
class TestStaticMethods:
    """Tests the static factory methods of the WorkflowManager."""

    def test_run_custom_workflow(self, MockWorkflowManager):
        """
        Verifies the `run_custom_workflow` static method correctly instantiates
        and calls a WorkflowManager instance with all parameters.
        """
        mock_instance = MockWorkflowManager.return_value

        WorkflowManager.run_custom_workflow(
            workflow_name="my_custom_flow",
            request_id="req-abc",
            discussion_id="disc-123",
            messages=[{"role": "user", "content": "hi"}],
            non_responder=False,
            is_streaming=True,
            first_node_system_prompt_override="sys",
            first_node_prompt_override="prompt",
            scoped_inputs=["input1"],
            workflow_user_folder_override="user_xyz"
        )

        MockWorkflowManager.assert_called_once_with(
            workflow_config_name="my_custom_flow",
            workflow_user_folder_override="user_xyz"
        )
        mock_instance.run_workflow.assert_called_once_with(
            [{"role": "user", "content": "hi"}], "req-abc", "disc-123", nonResponder=False, stream=True,
            first_node_system_prompt_override="sys",
            first_node_prompt_override="prompt",
            scoped_inputs=["input1"]
        )

    @pytest.mark.parametrize("static_method_name, config_getter_path", [
        ("handle_conversation_memory_parser", "get_active_conversational_memory_tool_name"),
        ("handle_recent_memory_parser", "get_active_recent_memory_tool_name"),
        ("handle_full_chat_summary_parser", "get_chat_summary_tool_workflow_name"),
        ("process_file_memories", "get_file_memory_tool_name"),
    ])
    def test_memory_parser_static_methods(
            self, MockWorkflowManager, mocker, static_method_name, config_getter_path
    ):
        """
        Tests all memory-related static methods to ensure they call the manager
        with the correct workflow name and `nonResponder=True`.
        """
        mock_config_getter = mocker.patch(f'Middleware.workflows.managers.workflow_manager.{config_getter_path}',
                                          return_value="memory_workflow")
        method_to_test = getattr(WorkflowManager, static_method_name)

        method_to_test(request_id="req-mem", discussion_id="disc-mem", messages=[])

        mock_config_getter.assert_called_once()
        MockWorkflowManager.assert_called_once_with(workflow_config_name="memory_workflow")
        mock_instance = MockWorkflowManager.return_value
        mock_instance.run_workflow.assert_called_once_with([], "req-mem", "disc-mem", nonResponder=True)
