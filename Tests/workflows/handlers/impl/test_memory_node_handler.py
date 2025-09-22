from unittest.mock import MagicMock

import pytest

# The class we are testing
from Middleware.workflows.handlers.impl.memory_node_handler import MemoryNodeHandler
# The context object it uses as an argument
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.fixture
def mock_dependencies(mocker):
    """Fixture to create all mocked dependencies for MemoryNodeHandler."""
    # Mock services and utilities that are imported into the memory_node_handler module
    return {
        "workflow_manager": MagicMock(),
        "workflow_variable_service": MagicMock(),
        "process_file_memories_func": MagicMock(),
        "handle_recent_memory_parser_func": MagicMock(),
        "handle_full_chat_summary_parser_func": MagicMock(),
        "handle_conversation_memory_parser_func": MagicMock(),
        "memory_service": mocker.patch('Middleware.workflows.handlers.impl.memory_node_handler.MemoryService',
                                       autospec=True).return_value,
        "slow_but_quality_rag_service": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.SlowButQualityRAGTool', autospec=True).return_value,
        "llm_dispatch_service": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.LLMDispatchService',
            autospec=True),
        "read_chunks_mock": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.read_chunks_with_hashes'),
        "update_chunks_mock": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.update_chunks_with_hashes'),
        "extract_text_blocks_mock": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.extract_text_blocks_from_hashed_chunks'),
        "get_summary_path_mock": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.get_discussion_chat_summary_file_path'),
        "get_memory_path_mock": mocker.patch(
            'Middleware.workflows.handlers.impl.memory_node_handler.get_discussion_memory_file_path'),
    }


@pytest.fixture
def memory_handler(mock_dependencies):
    """Fixture to create an instance of MemoryNodeHandler with mocked dependencies."""
    return MemoryNodeHandler(
        workflow_manager=mock_dependencies["workflow_manager"],
        workflow_variable_service=mock_dependencies["workflow_variable_service"],
        process_file_memories_func=mock_dependencies["process_file_memories_func"],
        handle_recent_memory_parser_func=mock_dependencies["handle_recent_memory_parser_func"],
        handle_full_chat_summary_parser_func=mock_dependencies["handle_full_chat_summary_parser_func"],
        handle_conversation_memory_parser_func=mock_dependencies["handle_conversation_memory_parser_func"]
    )


@pytest.fixture
def base_context(mock_dependencies):
    """
    Fixture to create a base ExecutionContext object for tests.

    This is updated to include mocked services that dependent functions
    (like LLMDispatchService) expect to find on the context object.
    """
    return ExecutionContext(
        request_id="test-req-123",
        workflow_id="test-wf-456",
        discussion_id="test-disc-789",
        config={},
        messages=[{"role": "user", "content": "Hello"}],
        stream=False,
        # Add the mocked services here for functions that read them from the context
        workflow_variable_service=mock_dependencies["workflow_variable_service"],
        llm_handler=MagicMock()
    )


# ########################################
# ### Main `handle` Router Method Tests
# ########################################

class TestHandleMethod:
    def test_vector_memory_search(self, memory_handler, mock_dependencies, base_context):
        """Tests the 'VectorMemorySearch' node type happy path."""
        base_context.config = {
            "type": "VectorMemorySearch",
            "input": "search for {agent1Output}",
            "limit": 10
        }
        mock_wvs = mock_dependencies["workflow_variable_service"]
        mock_mem_service = mock_dependencies["memory_service"]
        mock_wvs.apply_variables.return_value = "search for keywords"
        mock_mem_service.search_vector_memories.return_value = "Found memories."

        result = memory_handler.handle(base_context)

        mock_wvs.apply_variables.assert_called_once_with("search for {agent1Output}", base_context)
        mock_mem_service.search_vector_memories.assert_called_once_with(
            "test-disc-789", "search for keywords", 10
        )
        assert result == "Found memories."

    def test_vector_memory_search_no_discussion_id(self, memory_handler, base_context):
        """Tests 'VectorMemorySearch' node when discussion_id is None."""
        base_context.config = {"type": "VectorMemorySearch"}
        base_context.discussion_id = None

        result = memory_handler.handle(base_context)

        assert result == "Cannot perform VectorMemorySearch without a discussionId."

    def test_conversation_memory(self, memory_handler, mock_dependencies, base_context):
        """Tests that the 'ConversationMemory' node calls the correct parser function."""
        base_context.config = {"type": "ConversationMemory"}
        mock_parser = mock_dependencies["handle_conversation_memory_parser_func"]
        mock_parser.return_value = "parsed conversation memory"

        result = memory_handler.handle(base_context)

        mock_parser.assert_called_once_with(
            base_context.request_id, base_context.discussion_id, base_context.messages
        )
        assert result == "parsed conversation memory"

    def test_recent_memory_with_discussion_id(self, memory_handler, mock_dependencies, base_context):
        """Tests 'RecentMemory' node with a discussion_id, which should trigger memory creation first."""
        base_context.config = {"type": "RecentMemory"}
        mock_parser = mock_dependencies["handle_recent_memory_parser_func"]
        mock_rag = mock_dependencies["slow_but_quality_rag_service"]
        mock_parser.return_value = "parsed recent memory"

        result = memory_handler.handle(base_context)

        mock_rag.handle_discussion_id_flow.assert_called_once_with(base_context, force_file_memory=True)
        mock_parser.assert_called_once_with(
            base_context.request_id, base_context.discussion_id, base_context.messages
        )
        assert result == "parsed recent memory"

    def test_recent_memory_without_discussion_id(self, memory_handler, mock_dependencies, base_context):
        """Tests 'RecentMemory' node without a discussion_id, which should skip memory creation."""
        base_context.config = {"type": "RecentMemory"}
        base_context.discussion_id = None
        mock_parser = mock_dependencies["handle_recent_memory_parser_func"]
        mock_rag = mock_dependencies["slow_but_quality_rag_service"]
        mock_parser.return_value = "parsed stateless recent memory"

        result = memory_handler.handle(base_context)

        mock_rag.handle_discussion_id_flow.assert_not_called()
        mock_parser.assert_called_once_with(
            base_context.request_id, None, base_context.messages
        )
        assert result == "parsed stateless recent memory"

    def test_recent_memory_summarizer_tool(self, memory_handler, mock_dependencies, base_context):
        """Tests 'RecentMemorySummarizerTool' node type without a custom delimiter."""
        base_context.config = {
            "type": "RecentMemorySummarizerTool",
            "maxTurnsToPull": 5,
            "maxSummaryChunksFromFile": 3,
            "lookbackStart": 1
        }
        mock_mem_service = mock_dependencies["memory_service"]
        mock_mem_service.get_recent_memories.return_value = "chunk1--ChunkBreak--chunk2"

        result = memory_handler.handle(base_context)

        mock_mem_service.get_recent_memories.assert_called_once_with(
            base_context.messages, base_context.discussion_id, 5, 3, 1
        )
        assert result == "chunk1--ChunkBreak--chunk2"

    def test_recent_memory_summarizer_tool_with_custom_delimiter(self, memory_handler, mock_dependencies,
                                                                 base_context):
        """Tests 'RecentMemorySummarizerTool' correctly applies a custom delimiter."""
        base_context.config = {
            "type": "RecentMemorySummarizerTool", "maxTurnsToPull": 5,
            "maxSummaryChunksFromFile": 3, "customDelimiter": " ||| "
        }
        mock_mem_service = mock_dependencies["memory_service"]
        mock_mem_service.get_recent_memories.return_value = "chunk1--ChunkBreak--chunk2"

        result = memory_handler.handle(base_context)

        assert result == "chunk1 ||| chunk2"

    def test_recent_memory_summarizer_tool_no_memories(self, memory_handler, mock_dependencies, base_context):
        """Tests 'RecentMemorySummarizerTool' when the service returns None."""
        base_context.config = {"type": "RecentMemorySummarizerTool", "maxTurnsToPull": 5, "maxSummaryChunksFromFile": 3}
        mock_dependencies["memory_service"].get_recent_memories.return_value = None

        result = memory_handler.handle(base_context)

        assert result == "There are not yet any memories"

    @pytest.mark.parametrize("node_type", ["GetCurrentSummaryFromFile", "GetCurrentMemoryFromFile"])
    def test_get_current_file_nodes(self, memory_handler, mock_dependencies, base_context, node_type):
        """Tests nodes that perform a simple read of the current summary file."""
        base_context.config = {"type": node_type}
        mock_mem_service = mock_dependencies["memory_service"]
        mock_mem_service.get_current_summary.return_value = "current summary from file"

        result = memory_handler.handle(base_context)

        mock_mem_service.get_current_summary.assert_called_once_with(base_context.discussion_id)
        assert result == "current summary from file"

    def test_quality_memory_with_discussion_id(self, memory_handler, mock_dependencies, base_context):
        """Tests 'QualityMemory' node with a discussion_id, triggering the RAG tool."""
        base_context.config = {"type": "QualityMemory"}
        mock_rag = mock_dependencies["slow_but_quality_rag_service"]
        mock_rag.handle_discussion_id_flow.return_value = "rag tool ran"

        result = memory_handler.handle(base_context)

        mock_rag.handle_discussion_id_flow.assert_called_once_with(base_context, False)
        assert result == "rag tool ran"

    def test_quality_memory_without_discussion_id(self, memory_handler, mock_dependencies, base_context):
        """Tests 'QualityMemory' node without a discussion_id, falling back to the stateless parser."""
        base_context.config = {"type": "QualityMemory"}
        base_context.discussion_id = None
        mock_parser = mock_dependencies["handle_recent_memory_parser_func"]
        mock_parser.return_value = "stateless memory parsed"

        result = memory_handler.handle(base_context)

        mock_parser.assert_called_once_with(base_context.request_id, None, base_context.messages)
        assert result == "stateless memory parsed"

    def test_unhandled_node_type_raises_error(self, memory_handler, base_context):
        """Tests that an unknown node type raises a ValueError."""
        base_context.config = {"type": "UnknownAndInvalidNodeType"}
        with pytest.raises(ValueError,
                           match="MemoryNodeHandler received unhandled node type: UnknownAndInvalidNodeType"):
            memory_handler.handle(base_context)


# ########################################
# ### Internal Helper Method Tests
# ########################################

class TestInternalSaveSummaryMethod:
    def test_save_summary_to_file_from_input(self, memory_handler, mock_dependencies, base_context):
        """Tests saving a summary resolved from the node's 'input' field."""
        base_context.config = {"input": "variable {agent1Output}"}
        mock_wvs = mock_dependencies["workflow_variable_service"]
        mock_read_chunks = mock_dependencies["read_chunks_mock"]
        mock_update_chunks = mock_dependencies["update_chunks_mock"]

        mock_wvs.apply_variables.return_value = "resolved summary"
        mock_read_chunks.return_value = [("some text", "some_hash_123")]

        result = memory_handler._save_summary_to_file(base_context)

        mock_wvs.apply_variables.assert_called_once_with("variable {agent1Output}", base_context)
        mock_read_chunks.assert_called_once()
        mock_update_chunks.assert_called_once_with(
            [("resolved summary", "some_hash_123")],
            mock_dependencies["get_summary_path_mock"].return_value,
            "overwrite"
        )
        assert result == "resolved summary"

    def test_save_summary_to_file_with_override(self, memory_handler, mock_dependencies, base_context):
        """Tests saving a summary using provided override values."""
        mock_read_chunks = mock_dependencies["read_chunks_mock"]
        mock_update_chunks = mock_dependencies["update_chunks_mock"]
        mock_read_chunks.return_value = [("other text", "other_hash_456")]

        result = memory_handler._save_summary_to_file(
            base_context,
            summary_override="overridden summary",
            last_hash_override="overridden_hash_789"
        )

        mock_dependencies["workflow_variable_service"].apply_variables.assert_not_called()
        mock_read_chunks.assert_called_once()
        mock_update_chunks.assert_called_once_with(
            [("overridden summary", "overridden_hash_789")],
            mock_dependencies["get_summary_path_mock"].return_value,
            "overwrite"
        )
        assert result == "overridden summary"

    def test_save_summary_to_file_no_input_raises_error(self, memory_handler, base_context):
        """Tests that a ValueError is raised if 'input' is missing from config."""
        base_context.config = {}
        with pytest.raises(ValueError, match="No 'input' found in config for saving summary."):
            memory_handler._save_summary_to_file(base_context)

    def test_save_summary_to_file_no_memory_chunks_raises_error(self, memory_handler, mock_dependencies, base_context):
        """Tests that a ValueError is raised if no memory chunks exist to get a hash from."""
        base_context.config = {"input": "some summary"}
        mock_dependencies["read_chunks_mock"].return_value = []

        with pytest.raises(ValueError, match="Cannot save summary without a last hash and no memory chunks exist."):
            memory_handler._save_summary_to_file(base_context)


class TestInternalProcessChatSummaryMethod:
    def test_no_new_memories(self, memory_handler, mock_dependencies, base_context):
        """Tests that the current summary is returned if no new memories are found."""
        mock_mem_service = mock_dependencies["memory_service"]
        mock_mem_service.get_latest_memory_chunks_with_hashes_since_last_summary.return_value = []
        mock_mem_service.get_current_summary.return_value = "existing summary"

        result = memory_handler._handle_process_chat_summary(base_context)

        assert result == "existing summary"
        mock_dependencies["llm_dispatch_service"].dispatch.assert_not_called()

    def test_simple_path_no_special_placeholders(self, memory_handler, mock_dependencies, base_context, mocker):
        """Tests the simple summarization path when prompt templates are basic."""
        base_context.config = {"systemPrompt": "System", "prompt": "User"}
        mock_mem_service = mock_dependencies["memory_service"]
        mock_dispatch = mock_dependencies["llm_dispatch_service"]

        mock_mem_service.get_latest_memory_chunks_with_hashes_since_last_summary.return_value = [("new", "h1")]
        mock_dispatch.dispatch.return_value = "new summary"
        # Mock the internal save method to isolate this test
        mocker.patch.object(memory_handler, '_save_summary_to_file')

        result = memory_handler._handle_process_chat_summary(base_context)

        mock_dispatch.dispatch.assert_called_once_with(context=base_context)
        memory_handler._save_summary_to_file.assert_called_once_with(base_context, summary_override="new summary")
        assert result == "new summary"

    def test_looping_and_final_batch(self, memory_handler, mock_dependencies, base_context, mocker):
        """Tests the iterative summarization logic with multiple loops and a final batch."""
        base_context.config = {
            "systemPrompt": "Summarize: [LATEST_MEMORIES]", "prompt": "Based on [CHAT_SUMMARY]",
            "minMemoriesPerSummary": 1, "loopIfMemoriesExceed": 2
        }
        mock_mem_service = mock_dependencies["memory_service"]
        mock_dispatch = mock_dependencies["llm_dispatch_service"]

        initial_memories = [("c1", "h1"), ("c2", "h2"), ("c3", "h3"), ("c4", "h4"), ("c5", "h5")]
        mock_mem_service.get_latest_memory_chunks_with_hashes_since_last_summary.return_value = initial_memories
        mock_mem_service.get_current_summary.side_effect = ["s0", "s1", "s2"]
        mock_dispatch.dispatch.side_effect = ["s1", "s2", "s3"]
        mocker.patch.object(memory_handler, '_save_summary_to_file', autospec=True)

        final_summary = memory_handler._handle_process_chat_summary(base_context)

        assert mock_dispatch.dispatch.call_count == 3
        # Check first call (loop 1)
        ctx1 = mock_dispatch.dispatch.call_args_list[0].kwargs['context']
        assert ctx1.config['prompt'] == "Based on s0"
        assert ctx1.config['systemPrompt'] == "Summarize: c1\n------------\nc2"
        memory_handler._save_summary_to_file.assert_any_call(base_context, summary_override="s1",
                                                             last_hash_override="h2")
        # Check second call (loop 2)
        ctx2 = mock_dispatch.dispatch.call_args_list[1].kwargs['context']
        assert ctx2.config['prompt'] == "Based on s1"
        assert ctx2.config['systemPrompt'] == "Summarize: c3\n------------\nc4"
        memory_handler._save_summary_to_file.assert_any_call(base_context, summary_override="s2",
                                                             last_hash_override="h4")
        # Check third call (final batch)
        ctx3 = mock_dispatch.dispatch.call_args_list[2].kwargs['context']
        assert ctx3.config['prompt'] == "Based on s2"
        assert ctx3.config['systemPrompt'] == "Summarize: c5"
        memory_handler._save_summary_to_file.assert_any_call(base_context, summary_override="s3",
                                                             last_hash_override="h5")
        assert final_summary == "s3"


class TestInternalFullChatSummaryMethod:
    def test_manual_config(self, memory_handler, mock_dependencies, base_context):
        """Tests 'FullChatSummary' with 'isManualConfig' set to true."""
        base_context.config = {"isManualConfig": True}
        mock_read_chunks = mock_dependencies["read_chunks_mock"]
        mock_extract = mock_dependencies["extract_text_blocks_mock"]
        mock_read_chunks.return_value = [("summary text", "hash")]
        mock_extract.return_value = "extracted summary"

        result = memory_handler._handle_full_chat_summary(base_context)

        mock_read_chunks.assert_called_once()
        mock_extract.assert_called_once_with([("summary text", "hash")])
        assert result == "extracted summary"

    def test_manual_config_no_summary(self, memory_handler, mock_dependencies, base_context):
        """Tests 'FullChatSummary' with 'isManualConfig' and no existing summary file."""
        base_context.config = {"isManualConfig": True}
        mock_dependencies["read_chunks_mock"].return_value = []

        result = memory_handler._handle_full_chat_summary(base_context)

        assert result == "No summary found"

    def test_needs_update(self, memory_handler, mock_dependencies, base_context):
        """Tests 'FullChatSummary' when new memories are detected, triggering a re-parse."""
        base_context.config = {}
        mock_rag = mock_dependencies["slow_but_quality_rag_service"]
        mock_mem_service = mock_dependencies["memory_service"]
        mock_parser = mock_dependencies["handle_full_chat_summary_parser_func"]

        mock_mem_service.find_how_many_new_memories_since_last_summary.return_value = 5  # Needs update
        mock_parser.return_value = "newly parsed summary"

        result = memory_handler._handle_full_chat_summary(base_context)

        mock_rag.handle_discussion_id_flow.assert_called_once_with(base_context, force_file_memory=True)
        mock_mem_service.find_how_many_new_memories_since_last_summary.assert_called_once()
        mock_parser.assert_called_once_with(
            base_context.request_id, base_context.discussion_id, base_context.messages
        )
        assert result == "newly parsed summary"

    def test_is_up_to_date(self, memory_handler, mock_dependencies, base_context):
        """Tests 'FullChatSummary' when the summary is current and doesn't need re-parsing."""
        base_context.config = {}
        mock_rag = mock_dependencies["slow_but_quality_rag_service"]
        mock_mem_service = mock_dependencies["memory_service"]
        mock_extract = mock_dependencies["extract_text_blocks_mock"]
        mock_parser = mock_dependencies["handle_full_chat_summary_parser_func"]

        mock_mem_service.find_how_many_new_memories_since_last_summary.return_value = 0  # Up to date
        mock_extract.return_value = "existing up-to-date summary"

        result = memory_handler._handle_full_chat_summary(base_context)

        mock_rag.handle_discussion_id_flow.assert_called_once_with(base_context, force_file_memory=True)
        mock_mem_service.find_how_many_new_memories_since_last_summary.assert_called_once()
        mock_parser.assert_not_called()
        mock_extract.assert_called_once()
        assert result == "existing up-to-date summary"


# ########################################
# ### Integration Scenarios
# ########################################

class TestMemoryIntegrationScenarios:

    def test_scenario_a_coexistence_of_vector_and_file_memory(self, memory_handler, mock_dependencies, base_context):
        """
        Scenario A: Verify QualityMemory (vector) and FullChatSummary (file) can coexist.
        The key validation is checking the 'force_file_memory' flag passed to the RAG tool.
        """
        mock_rag = mock_dependencies["slow_but_quality_rag_service"]
        base_context.discussion_id = "disc-id-123"  # Ensure discussion ID is set for stateful operations

        # 1. Simulate QualityMemory node execution
        base_context.config = {"type": "QualityMemory"}
        memory_handler.handle(base_context)

        # Assert: QualityMemory calls the RAG tool WITHOUT forcing file memory (False).
        # This allows the RAG tool to use vector memory based on its own configuration.
        mock_rag.handle_discussion_id_flow.assert_called_once_with(base_context, False)

        mock_rag.reset_mock()  # Reset the mock for the next step

        # 2. Simulate FullChatSummary node execution
        # We need to mock the dependencies required by the internal _handle_full_chat_summary logic
        mock_mem_service = mock_dependencies["memory_service"]
        # Assume the summary is up-to-date for simplicity; we just need to ensure the initial RAG call happens.
        mock_mem_service.find_how_many_new_memories_since_last_summary.return_value = 0
        mock_dependencies["extract_text_blocks_mock"].return_value = "current summary"

        base_context.config = {"type": "FullChatSummary"}
        memory_handler.handle(base_context)

        # Assert: FullChatSummary calls the RAG tool AND forces file memory (True).
        # This ensures file-based memory is updated regardless of the global config.
        mock_rag.handle_discussion_id_flow.assert_called_once_with(base_context, force_file_memory=True)
