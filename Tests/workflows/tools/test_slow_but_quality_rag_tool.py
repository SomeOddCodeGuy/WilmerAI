# tests/workflows/tools/test_slow_but_quality_rag_tool.py

import json
from unittest.mock import MagicMock, patch

import pytest

from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool


# pytest fixture to create a reusable ExecutionContext for tests
@pytest.fixture
def mock_context(mocker):
    """Creates a mock ExecutionContext object for tests."""
    context = ExecutionContext(
        request_id="test-req-123",
        workflow_id="test-wf-123",
        discussion_id="test-disc-123",
        config={"key": "value"},
        messages=[{"role": "user", "content": "Hello"}],
        stream=False,
        workflow_config={"global_key": "global_value"},
        agent_outputs={"agent1Output": "some previous result"}
    )
    # Mock services that are attached to the context
    context.workflow_manager = MagicMock()
    context.workflow_variable_service = MagicMock()
    # The variable service's apply_variables should just return the input prompt by default
    context.workflow_variable_service.apply_variables.side_effect = lambda prompt, ctx, **kwargs: prompt

    # Mock LlmHandler
    mock_llm_handler = MagicMock()
    mock_llm_handler.takes_message_collection = True
    mock_llm_handler.llm.get_response_from_llm.return_value = "LLM Response"
    context.llm_handler = mock_llm_handler

    return context


# Test class for SlowButQualityRAGTool
class TestSlowButQualityRAGTool:
    """Unit tests for the SlowButQualityRAGTool class."""

    def test_init(self):
        """Tests that the tool initializes its MemoryService."""
        tool = SlowButQualityRAGTool()
        assert tool.memory_service is not None
        # More specific check if needed
        from Middleware.services.memory_service import MemoryService
        assert isinstance(tool.memory_service, MemoryService)

    @pytest.mark.parametrize("llm_output, expected", [
        ('```json\n{"key": "value"}\n```', {"key": "value"}),
        ('Here is the JSON: {"key": "value"}', {"key": "value"}),
        ('Some text before\n[{"item": 1}, {"item": 2}]\nand after', [{"item": 1}, {"item": 2}]),
        ('```json\n[{"item": "test"}]\n```', [{"item": "test"}]),
        ('This is not json', None),
        ('{"key": "malformed",}', None),
        ('', None),
        (None, None)
    ])
    def test_parse_llm_json_output(self, llm_output, expected):
        """Tests the static method for parsing JSON from LLM string outputs."""
        result = SlowButQualityRAGTool._parse_llm_json_output(llm_output)
        assert result == expected

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_generate_and_store_vector_memories_with_workflow(self, mock_parse_json, mock_vector_db, mock_context):
        """Tests vector memory generation using the sub-workflow path."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'test-vector-workflow'}
        # Now passing hashed_chunks (tuples of text, hash) instead of just text_chunks
        hashed_chunks = [("first chunk", "hash1"), ("second chunk", "hash2")]

        # Mock workflow manager returns a JSON string, and the parser returns a valid dict
        mock_context.workflow_manager.run_custom_workflow.return_value = '{"title": "Test", "summary": "A test summary.", "entities": [], "key_phrases": []}'
        mock_parse_json.return_value = {"title": "Test", "summary": "A test summary.", "entities": [],
                                        "key_phrases": []}

        tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        # Assert that the workflow manager was called for each chunk
        assert mock_context.workflow_manager.run_custom_workflow.call_count == 2
        mock_context.workflow_manager.run_custom_workflow.assert_called_with(
            workflow_name='test-vector-workflow',
            request_id=mock_context.request_id,
            discussion_id=mock_context.discussion_id,
            messages=mock_context.messages,
            non_responder=True,
            scoped_inputs=["second chunk"]
        )

        # Assert that the database utility was called to add the memory for each chunk
        assert mock_vector_db.add_memory_to_vector_db.call_count == 2
        mock_vector_db.add_memory_to_vector_db.assert_called_with(
            mock_context.discussion_id,
            "A test summary.",
            json.dumps({"title": "Test", "summary": "A test summary.", "entities": [], "key_phrases": []})
        )

        # Assert that a hash was logged after each successful chunk (resumability)
        assert mock_vector_db.add_vector_check_hash.call_count == 2
        mock_vector_db.add_vector_check_hash.assert_any_call(mock_context.discussion_id, "hash1")
        mock_vector_db.add_vector_check_hash.assert_any_call(mock_context.discussion_id, "hash2")

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool.process_single_chunk')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_generate_and_store_vector_memories_direct_llm_call(
            self, mock_get_endpoint, mock_llm_service, mock_process_chunk, mock_vector_db, mock_context
    ):
        """Tests vector memory generation using the direct LLM call path."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryEndpointName': 'test-endpoint', 'vectorMemoryPreset': 'test-preset'}
        # Now passing hashed_chunks (tuples of text, hash) instead of just text_chunks
        hashed_chunks = [("a single chunk", "chunk_hash")]

        mock_process_chunk.return_value = '```json\n{"title": "Direct", "summary": "Direct summary.", "entities": ["a"], "key_phrases": ["b"]}\n```'

        # Mock the JSON parser directly since it's a static method
        with patch.object(SlowButQualityRAGTool, '_parse_llm_json_output',
                          return_value={"title": "Direct", "summary": "Direct summary.", "entities": ["a"],
                                        "key_phrases": ["b"]}) as mock_parser:
            tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        # Assert that an LLM handler was initialized
        mock_llm_service.return_value.initialize_llm_handler.assert_called_once()
        # Assert process_single_chunk was called
        mock_process_chunk.assert_called_once()
        # Assert parser was used
        mock_parser.assert_called_once()
        # Assert that the database utility was called to add the memory
        mock_vector_db.add_memory_to_vector_db.assert_called_once_with(
            mock_context.discussion_id,
            "Direct summary.",
            json.dumps({"title": "Direct", "summary": "Direct summary.", "entities": ["a"], "key_phrases": ["b"]})
        )
        # Assert that a hash was logged after successful processing (resumability)
        mock_vector_db.add_vector_check_hash.assert_called_once_with(mock_context.discussion_id, "chunk_hash")

    def test_perform_keyword_search_routes_correctly(self, mock_context):
        """Tests that perform_keyword_search calls the correct sub-method based on target."""
        tool = SlowButQualityRAGTool()
        with patch.object(tool, 'perform_conversation_search') as mock_conv_search, \
                patch.object(tool, 'perform_memory_file_keyword_search') as mock_mem_search:
            tool.perform_keyword_search("keywords", "CurrentConversation", mock_context)
            mock_conv_search.assert_called_once_with("keywords", mock_context, 0)
            mock_mem_search.assert_not_called()

            mock_conv_search.reset_mock()

            tool.perform_keyword_search("keywords", "RecentMemories", mock_context)
            mock_mem_search.assert_called_once_with("keywords", mock_context)
            mock_conv_search.assert_not_called()

            result = tool.perform_keyword_search("keywords", "InvalidTarget", mock_context)
            assert result == ""

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.advanced_search_in_chunks',
           return_value=["found chunk"])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.filter_keywords_by_speakers',
           side_effect=lambda _, k: k)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_message_chunks', return_value=["chunk1", "chunk2"])
    def test_perform_conversation_search(self, mock_get_chunks, mock_filter, mock_advanced_search, mock_context):
        """Tests searching within the current conversation messages."""
        tool = SlowButQualityRAGTool()
        result = tool.perform_conversation_search("test keywords", mock_context)

        mock_get_chunks.assert_called_once()
        mock_filter.assert_called_once()
        mock_advanced_search.assert_called_once_with(["chunk1", "chunk2"], "test keywords", 10)
        assert result == "found chunk"

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.search_in_chunks', return_value=["found memory"])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.filter_keywords_by_speakers',
           side_effect=lambda _, k: k)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.extract_text_blocks_from_hashed_chunks',
           return_value=["mem1", "mem2", "mem3", "mem4"])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    def test_perform_memory_file_keyword_search(
            self, mock_get_path, mock_read_hashes, mock_extract, mock_filter, mock_search, mock_context
    ):
        """Tests searching within the memory file, checking slicing logic."""
        tool = SlowButQualityRAGTool()
        result = tool.perform_memory_file_keyword_search("test keywords", mock_context)

        mock_read_hashes.assert_called_once()
        mock_extract.assert_called_once()
        mock_filter.assert_called_once()

        # Assert that the search was performed on the sliced list (all but the last 3)
        mock_search.assert_called_once_with(["mem1"], "test keywords", 10)
        assert result == "found memory"

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_handle_discussion_id_flow_vector_path(self, mock_chunker, mock_vector_db, mock_load_config, mock_context):
        """Tests the main orchestrator method for the vector memory path."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {'useVectorForQualityMemory': True, 'vectorMemoryLookBackTurns': 1}

        mock_context.messages = [
            {"role": "user", "content": "message 1"},
            {"role": "assistant", "content": "message 2"},
            {"role": "user", "content": "message 3"},
            {"role": "assistant", "content": "message 4"}
        ]

        mock_vector_db.get_vector_check_hash_history.return_value = ["hash_of_message_1"]
        # The chunker returns tuples of (text, hash), which are now passed directly to generate_and_store_vector_memories
        mock_chunker.return_value = [("Processed chunk text for msg 2 and 3", "hash_from_last_chunk")]

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message') as mock_hasher:
            mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"

            with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
                tool.handle_discussion_id_flow(mock_context)

                mock_generate.assert_called_once()
                call_args, _ = mock_generate.call_args
                # Now receives hashed_chunks (tuples) instead of text_chunks
                hashed_chunks_arg = call_args[0]
                assert hashed_chunks_arg == [("Processed chunk text for msg 2 and 3", "hash_from_last_chunk")]

                # Hash logging is now handled INSIDE generate_and_store_vector_memories per-chunk,
                # so handle_discussion_id_flow no longer calls add_vector_check_hash directly
                mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=2000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_handle_discussion_id_flow_file_path(
            self, mock_chunker, mock_get_path, mock_estimate_tokens, mock_read_hashes, mock_load_config,
            mock_path_exists, mock_context
    ):
        """Tests the main orchestrator method for the file-based memory path."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 1000,
            'maxMessagesBetweenChunks': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(5)]

        mock_chunker.return_value = [("some chunk text", "some_hash")]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)

            mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool.process_single_chunk')
    def test_perform_rag_on_memory_chunk_direct_call(self, mock_process_chunk, mock_context):
        """Tests RAG on memory chunks using direct LLM call path."""
        tool = SlowButQualityRAGTool()
        workflow_config = {
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
            'fileMemoryWorkflowName': None
        }
        text_chunk = "chunk1--ChunkBreak--chunk2"
        mock_process_chunk.side_effect = ["summary1", "summary2"]

        # Mock dependencies
        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[]), \
                patch('Middleware.services.memory_service.MemoryService.get_current_summary', return_value=""), \
                patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService'), \
                patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config'):
            result = tool.perform_rag_on_memory_chunk(
                "sys", "prompt", text_chunk, mock_context, workflow_config, custom_delimiter="||"
            )

            assert mock_process_chunk.call_count == 2
            assert result == "summary1||summary2"

    def test_process_single_chunk_chat_api(self, mock_context):
        """Tests processing a single chunk with a Chat Completions style API."""
        mock_context.llm_handler.takes_message_collection = True

        result = SlowButQualityRAGTool.process_single_chunk(
            "my text chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        # Verify get_response_from_llm was called with a list of dicts
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once()
        call_args, _ = mock_context.llm_handler.llm.get_response_from_llm.call_args
        conversation_arg = call_args[0]

        assert isinstance(conversation_arg, list)
        assert conversation_arg[0] == {"role": "system", "content": "System: my text chunk"}
        assert conversation_arg[1] == {"role": "user", "content": "Prompt: my text chunk"}
        assert result == "LLM Response"

    def test_process_single_chunk_completions_api(self, mock_context):
        """Tests processing a single chunk with a legacy Completions style API."""
        mock_context.llm_handler.takes_message_collection = False

        result = SlowButQualityRAGTool.process_single_chunk(
            "my text chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        # Verify get_response_from_llm was called with keyword arguments
        # llm_takes_images is always False for RAG processing (no images in text chunks)
        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            system_prompt="System: my text chunk",
            prompt="Prompt: my text chunk",
            llm_takes_images=False,
            request_id="test-req-123"
        )
        assert result == "LLM Response"

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    def test_scenario_b_vector_hash_history_robustness(
            self, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """
        Tests that the vector memory flow correctly uses the most recent matching hash
        from history within the eligible window, preventing reprocessing, even if the
        lookback setting is large and the newest historical hash is outside the window.
        """
        tool = SlowButQualityRAGTool()

        LOOKBACK = 7
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'vectorMemoryLookBackTurns': LOOKBACK,
            'vectorMemoryMaxMessagesBetweenChunks': 15,
            'vectorMemoryChunkEstimatedTokenSize': 1000
        }

        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(20)]

        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"

        HASH_OUTSIDE_WINDOW = 16
        HASH_INSIDE_WINDOW = 10
        mock_vector_db.get_vector_check_hash_history.return_value = [
            f"hash_of_message_{HASH_OUTSIDE_WINDOW}",
            f"hash_of_message_{HASH_INSIDE_WINDOW}"
        ]

        # The chunker returns tuples of (text, hash), now passed directly to generate_and_store_vector_memories
        mock_chunker.return_value = [("Processed new chunk", "hash_from_last_chunk")]

        with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
            tool.handle_discussion_id_flow(mock_context)

            EXPECTED_NEW_MESSAGES = mock_context.messages[11:13]

            mock_chunker.assert_called_once()
            call_args, _ = mock_chunker.call_args
            messages_arg = call_args[0]
            assert messages_arg == EXPECTED_NEW_MESSAGES

            mock_generate.assert_called_once()
            # Verify hashed_chunks are passed (not text_chunks)
            gen_call_args, _ = mock_generate.call_args
            assert gen_call_args[0] == [("Processed new chunk", "hash_from_last_chunk")]

            # Hash logging is now handled INSIDE generate_and_store_vector_memories per-chunk,
            # so handle_discussion_id_flow no longer calls add_vector_check_hash directly
            mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    def test_vector_hash_not_updated_when_no_memories_stored(
            self, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """
        Tests that the vector memory hash is NOT updated when generate_and_store_vector_memories
        returns 0 (no memories were actually stored). This prevents the "walking hash" bug where
        the hash advances even though no memories were created.

        Note: With the resumability change, hashes are now written per-chunk INSIDE
        generate_and_store_vector_memories. This test verifies that handle_discussion_id_flow
        correctly passes hashed_chunks and that the method is called appropriately.
        """
        tool = SlowButQualityRAGTool()

        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'vectorMemoryLookBackTurns': 1,
            'vectorMemoryMaxMessagesBetweenChunks': 5,
            'vectorMemoryChunkEstimatedTokenSize': 1000
        }

        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(10)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = ["hash_of_message_5"]
        mock_chunker.return_value = [("Some chunk text", "some_hash")]

        # Simulate the case where generate_and_store_vector_memories stores 0 memories
        with patch.object(tool, 'generate_and_store_vector_memories', return_value=0) as mock_generate:
            tool.handle_discussion_id_flow(mock_context)

            mock_generate.assert_called_once()
            # Verify hashed_chunks are passed correctly
            gen_call_args, _ = mock_generate.call_args
            assert gen_call_args[0] == [("Some chunk text", "some_hash")]
            # Hash logging is handled INSIDE generate_and_store_vector_memories,
            # so handle_discussion_id_flow doesn't call it directly
            mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    def test_vector_hash_not_updated_when_chunking_returns_empty(
            self, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """
        Tests that the vector memory hash is NOT updated when chunking returns an empty list
        (messages didn't meet the threshold). This is the primary fix for the bug where
        the hash would advance even when no chunks were created.
        """
        tool = SlowButQualityRAGTool()

        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'vectorMemoryLookBackTurns': 1,
            'vectorMemoryMaxMessagesBetweenChunks': 10,  # High threshold
            'vectorMemoryChunkEstimatedTokenSize': 5000  # High threshold
        }

        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(5)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = ["hash_of_message_0"]

        # Simulate chunking returning empty list (messages below threshold)
        mock_chunker.return_value = []

        with patch.object(tool, 'generate_and_store_vector_memories') as mock_generate:
            tool.handle_discussion_id_flow(mock_context)

            # generate_and_store_vector_memories should NOT be called when chunks are empty
            mock_generate.assert_not_called()
            # Hash should NOT be updated
            mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing chunk", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=1000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=20)
    def test_trigger_fires_at_exact_token_threshold(
            self, mock_find_hash, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """Tests that token trigger fires at exactly the threshold value (>= not >)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 1000,
            'maxMessagesBetweenChunks': 100
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(25)]
        mock_chunker.return_value = [("some chunk text", "some_hash")]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing chunk", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=999)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=20)
    def test_token_trigger_does_not_fire_below_threshold(
            self, mock_find_hash, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """Tests that token trigger does NOT fire at threshold - 1 (distinguishes >= from >)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 1000,
            'maxMessagesBetweenChunks': 100
        }
        # 4 new messages (well below maxMessagesBetweenChunks=100), so message trigger won't fire.
        # Token count is 999 < 1000 threshold, so token trigger shouldn't fire either.
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(25)]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            mock_process.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing chunk", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=20)
    def test_trigger_fires_at_exact_message_threshold(
            self, mock_find_hash, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """Tests that message trigger fires at exactly the threshold value (>= not >)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 5000,
            'maxMessagesBetweenChunks': 20
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(25)]
        mock_chunker.return_value = [("some chunk text", "some_hash")]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing chunk", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=19)
    def test_message_trigger_does_not_fire_below_threshold(
            self, mock_find_hash, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """Tests that message trigger does NOT fire at threshold - 1 (distinguishes >= from >)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 5000,
            'maxMessagesBetweenChunks': 20
        }
        # 19 new messages (threshold - 1), tokens 500 < 5000. Neither threshold met.
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(25)]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            mock_process.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing chunk", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=10)
    def test_message_trigger_fires_when_tokens_below_threshold(
            self, mock_find_hash, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """Tests that message trigger fires even when tokens are below threshold (standard mode)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 5000,
            'maxMessagesBetweenChunks': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(15)]

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes',
                   return_value=[("chunk", "hash")]) as mock_chunker:
            with patch.object(tool, 'process_new_memory_chunks') as mock_process:
                tool.handle_discussion_id_flow(mock_context)
                mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=False)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    def test_consolidation_mode_when_file_does_not_exist(
            self, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """Tests that message threshold is disabled when file does not exist on disk (consolidation mode)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 5000,
            'maxMessagesBetweenChunks': 3
        }
        # 10 messages exceeds maxMessagesBetweenChunks=3, but file does not exist on disk
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(10)]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            # Should NOT trigger because file doesn't exist (consolidation mode) and token threshold not met
            mock_process.assert_not_called()

    def test_process_single_chunk_passes_request_id_completions(self, mock_context):
        """Tests that process_single_chunk passes request_id for completions-style APIs."""
        mock_context.llm_handler.takes_message_collection = False

        SlowButQualityRAGTool.process_single_chunk(
            "my text chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        mock_context.llm_handler.llm.get_response_from_llm.assert_called_once_with(
            system_prompt="System: my text chunk",
            prompt="Prompt: my text chunk",
            llm_takes_images=False,
            request_id="test-req-123"
        )

    def test_process_single_chunk_passes_request_id_chat(self, mock_context):
        """Tests that process_single_chunk passes request_id for chat-style APIs."""
        mock_context.llm_handler.takes_message_collection = True

        SlowButQualityRAGTool.process_single_chunk(
            "my text chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        call_args, call_kwargs = mock_context.llm_handler.llm.get_response_from_llm.call_args
        assert call_kwargs.get('request_id') == "test-req-123"
        assert call_kwargs.get('llm_takes_images') is False

    # ---- Scenario tests for file_exists triggering behavior ----

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_new_chat_empty_file_exists_uses_message_threshold(
            self, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """
        Scenario: New chat where file exists on disk but has no chunks (empty []).
        The message threshold should be active because the file exists, even though
        it contains no memory chunks. This is the key fix — previously, the code
        checked bool(discussion_chunks) which was False for empty files, disabling
        the message threshold entirely for new conversations.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 50000,
            'maxMessagesBetweenChunks': 5
        }
        # 25 messages, tokens (500) far below token threshold (50000),
        # but message count (24 after lookback) exceeds maxMessagesBetweenChunks (5)
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(25)]
        mock_chunker.return_value = [("chunk text", "chunk_hash")]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            # MUST trigger via message threshold, even though file has no chunks
            mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=False)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_consolidation_file_deleted_triggers_by_tokens_only(
            self, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """
        Scenario: User deletes memory file to consolidate. File does not exist on disk.
        Token threshold met (100000 >= 30000). Should trigger via tokens.
        Message threshold should be disabled (file doesn't exist = consolidation mode).
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 3,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 20
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(160)]
        mock_chunker.return_value = [("chunk1", "hash1"), ("chunk2", "hash2"), ("chunk3", "hash3")]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            # Should trigger via token threshold
            mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=False)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    def test_consolidation_file_deleted_message_threshold_disabled(
            self, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """
        Scenario: User deletes memory file to consolidate. File does not exist on disk.
        Message count (50) far exceeds maxMessagesBetweenChunks (5), but token threshold
        not met (500 < 30000). Should NOT trigger because consolidation mode disables
        the message threshold.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(50)]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            # Must NOT trigger — consolidation mode, only token threshold applies
            mock_process.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing memory", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=25)
    def test_existing_chat_message_threshold_triggers(
            self, mock_find_hash, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """
        Scenario: Existing chat with memory chunks. File exists with chunks.
        25 new messages, maxMessagesBetweenChunks=20. Token count (500) below threshold (30000).
        Should trigger via message threshold.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 3,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 20
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(100)]
        mock_chunker.return_value = [("chunk", "hash")]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            # Should trigger via message count threshold
            mock_process.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing memory", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=500)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=10)
    def test_existing_chat_below_both_thresholds_no_trigger(
            self, mock_find_hash, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """
        Scenario: Existing chat, 10 new messages. maxMessages=20, tokens=500 < 30000.
        Neither threshold met. Should NOT trigger.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 3,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 20
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(100)]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)
            mock_process.assert_not_called()
