import json
from unittest.mock import MagicMock, patch

import pytest

from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool


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
    context.workflow_manager = MagicMock()
    context.workflow_variable_service = MagicMock()
    context.workflow_variable_service.apply_variables.side_effect = lambda prompt, ctx, **kwargs: prompt

    mock_llm_handler = MagicMock()
    mock_llm_handler.takes_message_collection = True
    mock_llm_handler.llm.get_response_from_llm.return_value = "LLM Response"
    context.llm_handler = mock_llm_handler

    return context


class TestSlowButQualityRAGTool:
    """Unit tests for the SlowButQualityRAGTool class."""

    def test_init(self):
        """Tests that the tool initializes its MemoryService."""
        tool = SlowButQualityRAGTool()
        assert tool.memory_service is not None
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
        hashed_chunks = [("first chunk", "hash1"), ("second chunk", "hash2")]

        mock_context.workflow_manager.run_custom_workflow.return_value = '{"title": "Test", "summary": "A test summary.", "entities": [], "key_phrases": []}'
        mock_parse_json.return_value = {"title": "Test", "summary": "A test summary.", "entities": [],
                                        "key_phrases": []}

        tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        assert mock_context.workflow_manager.run_custom_workflow.call_count == 2
        mock_context.workflow_manager.run_custom_workflow.assert_called_with(
            workflow_name='test-vector-workflow',
            request_id=mock_context.request_id,
            discussion_id=mock_context.discussion_id,
            messages=mock_context.messages,
            non_responder=True,
            scoped_inputs=["second chunk"],
            api_key=mock_context.api_key
        )

        assert mock_vector_db.add_memory_to_vector_db.call_count == 2
        mock_vector_db.add_memory_to_vector_db.assert_called_with(
            mock_context.discussion_id,
            "A test summary.",
            json.dumps({"title": "Test", "summary": "A test summary.", "entities": [], "key_phrases": []})
        )

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
        hashed_chunks = [("a single chunk", "chunk_hash")]

        mock_process_chunk.return_value = '```json\n{"title": "Direct", "summary": "Direct summary.", "entities": ["a"], "key_phrases": ["b"]}\n```'

        with patch.object(SlowButQualityRAGTool, '_parse_llm_json_output',
                          return_value={"title": "Direct", "summary": "Direct summary.", "entities": ["a"],
                                        "key_phrases": ["b"]}) as mock_parser:
            tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        mock_llm_service.return_value.initialize_llm_handler.assert_called_once()
        mock_process_chunk.assert_called_once()
        mock_parser.assert_called_once()
        mock_vector_db.add_memory_to_vector_db.assert_called_once_with(
            mock_context.discussion_id,
            "Direct summary.",
            json.dumps({"title": "Direct", "summary": "Direct summary.", "entities": ["a"], "key_phrases": ["b"]})
        )
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

        mock_search.assert_called_once_with(["mem1"], "test keywords", 10)
        assert result == "found memory"

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=5000)
    def test_handle_discussion_id_flow_vector_path(self, mock_estimate_tokens, mock_chunker, mock_vector_db, mock_load_config, mock_context):
        """Tests the main orchestrator method for the vector memory path."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {'useVectorForQualityMemory': True, 'lookbackStartTurn': 1,
                                         'vectorMemoryChunkEstimatedTokenSize': 1000,
                                         'vectorMemoryMaxMessagesBetweenChunks': 5}

        mock_context.messages = [
            {"role": "user", "content": "message 1"},
            {"role": "assistant", "content": "message 2"},
            {"role": "user", "content": "message 3"},
            {"role": "assistant", "content": "message 4"}
        ]

        mock_vector_db.get_vector_check_hash_history.return_value = ["hash_of_message_1"]
        mock_chunker.return_value = [("Processed chunk text for msg 2 and 3", "hash_from_last_chunk")]

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message') as mock_hasher:
            mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"

            with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
                tool.handle_discussion_id_flow(mock_context)

                mock_generate.assert_called_once()
                call_args, _ = mock_generate.call_args
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

    def test_perform_rag_on_conversation_chunk_no_discussion_id(self, mock_context):
        """Tests that perform_rag_on_conversation_chunk returns empty string when discussion_id is None."""
        mock_context.discussion_id = None
        tool = SlowButQualityRAGTool()

        result = tool.perform_rag_on_conversation_chunk("sys", "prompt", "chunk", mock_context)

        assert result == ""

    def test_perform_memory_file_keyword_search_no_discussion_id(self, mock_context):
        """Tests that perform_memory_file_keyword_search returns empty string when discussion_id is None."""
        mock_context.discussion_id = None
        tool = SlowButQualityRAGTool()

        result = tool.perform_memory_file_keyword_search("keyword1;keyword2", mock_context)

        assert result == ""

    def test_handle_discussion_id_flow_no_discussion_id(self, mock_context):
        """Tests that handle_discussion_id_flow returns early when discussion_id is None."""
        mock_context.discussion_id = None
        tool = SlowButQualityRAGTool()

        tool.handle_discussion_id_flow(mock_context)

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
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=5000)
    def test_scenario_b_vector_hash_history_robustness(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
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
            'lookbackStartTurn': LOOKBACK,
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

        mock_chunker.return_value = [("Processed new chunk", "hash_from_last_chunk")]

        with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
            tool.handle_discussion_id_flow(mock_context)

            EXPECTED_NEW_MESSAGES = mock_context.messages[11:13]

            mock_chunker.assert_called_once()
            call_args, _ = mock_chunker.call_args
            messages_arg = call_args[0]
            assert messages_arg == EXPECTED_NEW_MESSAGES

            mock_generate.assert_called_once()
            gen_call_args, _ = mock_generate.call_args
            assert gen_call_args[0] == [("Processed new chunk", "hash_from_last_chunk")]

            # Hash logging is now handled INSIDE generate_and_store_vector_memories per-chunk,
            # so handle_discussion_id_flow no longer calls add_vector_check_hash directly
            mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=5000)
    def test_vector_hash_not_updated_when_no_memories_stored(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
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
            'lookbackStartTurn': 1,
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
            gen_call_args, _ = mock_generate.call_args
            assert gen_call_args[0] == [("Some chunk text", "some_hash")]
            # Hash logging is handled INSIDE generate_and_store_vector_memories,
            # so handle_discussion_id_flow doesn't call it directly
            mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100)
    def test_vector_hash_not_updated_when_thresholds_not_met(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """
        Tests that neither chunking nor memory generation occurs when new messages
        don't meet either threshold (token count or message count). The threshold
        check now happens before chunking, so the chunker should not be called at all.
        """
        tool = SlowButQualityRAGTool()

        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryMaxMessagesBetweenChunks': 10,  # High threshold
            'vectorMemoryChunkEstimatedTokenSize': 5000  # High threshold
        }

        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(5)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = ["hash_of_message_0"]

        with patch.object(tool, 'generate_and_store_vector_memories') as mock_generate:
            tool.handle_discussion_id_flow(mock_context)

            mock_chunker.assert_not_called()
            mock_generate.assert_not_called()
            mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=6000)
    def test_vector_token_threshold_triggers_memory_generation(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """Tests that vector memory generation triggers when token threshold is met."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryChunkEstimatedTokenSize': 6000,
            'vectorMemoryMaxMessagesBetweenChunks': 100
        }
        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(10)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = []
        mock_chunker.return_value = [("chunk text", "chunk_hash")]

        with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
            tool.handle_discussion_id_flow(mock_context)
            mock_generate.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=5999)
    def test_vector_token_below_threshold_no_generation(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """Tests that vector memory generation does NOT trigger when token count is below threshold."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryChunkEstimatedTokenSize': 6000,
            'vectorMemoryMaxMessagesBetweenChunks': 100
        }
        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(10)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = []

        with patch.object(tool, 'generate_and_store_vector_memories') as mock_generate:
            tool.handle_discussion_id_flow(mock_context)
            mock_generate.assert_not_called()
            mock_chunker.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100)
    def test_vector_message_threshold_triggers_memory_generation(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """Tests that vector memory generation triggers when message count threshold is met."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryChunkEstimatedTokenSize': 50000,
            'vectorMemoryMaxMessagesBetweenChunks': 8
        }
        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(10)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = []
        mock_chunker.return_value = [("chunk text", "chunk_hash")]

        with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
            tool.handle_discussion_id_flow(mock_context)
            mock_generate.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100)
    def test_vector_lookback_start_turn_respected(
            self, mock_estimate_tokens, mock_hasher, mock_vector_db, mock_load_config, mock_context
    ):
        """Tests that the vector path uses lookbackStartTurn (not vectorMemoryLookBackTurns)
        and returns early when message count is within the lookback window."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 5,
            'vectorMemoryChunkEstimatedTokenSize': 1,
            'vectorMemoryMaxMessagesBetweenChunks': 1
        }
        # Only 4 messages (including no system since they're filtered) — within lookback of 5
        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(4)]

        with patch.object(tool, 'generate_and_store_vector_memories') as mock_generate:
            tool.handle_discussion_id_flow(mock_context)
            mock_generate.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100)
    def test_system_messages_filtered_from_memory_chunks(
            self, mock_estimate_tokens, mock_hasher, mock_vector_db, mock_load_config, mock_context
    ):
        """Tests that system messages are excluded from memory processing in both paths.
        This prevents system prompts from being turned into memories."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryChunkEstimatedTokenSize': 1,
            'vectorMemoryMaxMessagesBetweenChunks': 1
        }
        # 3 messages but one is system — after filtering, only 2 non-system messages remain
        # With lookback of 1, only 1 message is eligible
        mock_context.messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = []

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes') as mock_chunker:
            mock_chunker.return_value = [("chunk text", "chunk_hash")]
            with patch.object(tool, 'generate_and_store_vector_memories', return_value=1) as mock_generate:
                tool.handle_discussion_id_flow(mock_context)

                if mock_chunker.called:
                    messages_arg = mock_chunker.call_args[0][0]
                    for msg in messages_arg:
                        assert msg['role'] != 'system', "System messages should be filtered out"

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


    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=False)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_consolidation_mode_seeds_condensation_tracker_when_enabled(
            self, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists,
            mock_tracker_path, mock_write_tracker, mock_context
    ):
        """
        When memory file was deleted (consolidation mode) and condenseMemories is enabled,
        the condensation tracker should be seeded with the last memory hash so that
        subsequent condensation runs don't re-condense the freshly regenerated memories.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 3,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 20,
            'condenseMemories': True,
            'memoriesBeforeCondensation': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(160)]
        mock_chunker.return_value = [("chunk1", "hash1"), ("chunk2", "hash2"), ("chunk3", "hash3")]

        with patch.object(tool, 'process_new_memory_chunks'):
            with patch.object(tool, 'condense_memories'):
                tool.handle_discussion_id_flow(mock_context)
                mock_write_tracker.assert_called_once_with(
                    '/fake/tracker.json',
                    {'lastCondensationHash': 'hash3'},
                    encryption_key=None
                )

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=False)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_consolidation_mode_does_not_seed_tracker_when_condensation_disabled(
            self, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists,
            mock_write_tracker, mock_context
    ):
        """
        When memory file was deleted (consolidation mode) but condenseMemories is disabled,
        the condensation tracker should NOT be written.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 3,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 20,
            'condenseMemories': False
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(160)]
        mock_chunker.return_value = [("chunk1", "hash1"), ("chunk2", "hash2"), ("chunk3", "hash3")]

        with patch.object(tool, 'process_new_memory_chunks'):
            with patch.object(tool, 'condense_memories'):
                tool.handle_discussion_id_flow(mock_context)
                mock_write_tracker.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=100000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_normal_mode_does_not_seed_tracker_even_when_condensation_enabled(
            self, mock_chunker, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists,
            mock_write_tracker, mock_context
    ):
        """
        When memory file exists (normal mode) and condenseMemories is enabled,
        the tracker seeding should NOT happen — only consolidation mode seeds it.
        """
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 30000,
            'maxMessagesBetweenChunks': 5,
            'condenseMemories': True,
            'memoriesBeforeCondensation': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(25)]
        mock_chunker.return_value = [("chunk1", "hash1"), ("chunk2", "hash2")]

        with patch.object(tool, 'process_new_memory_chunks'):
            with patch.object(tool, 'condense_memories'):
                tool.handle_discussion_id_flow(mock_context)
                mock_write_tracker.assert_not_called()


class TestCondenseMemories:
    """Unit tests for the condense_memories method of SlowButQualityRAGTool."""

    @pytest.fixture
    def mock_context(self, mocker):
        """Creates a mock ExecutionContext for condensation tests."""
        context = ExecutionContext(
            request_id="test-req-cond",
            workflow_id="test-wf-cond",
            discussion_id="test-disc-cond",
            config={"key": "value"},
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
            workflow_config={"global_key": "global_value"},
            agent_outputs={}
        )
        context.workflow_manager = MagicMock()
        context.workflow_variable_service = MagicMock()
        context.workflow_variable_service.apply_variables.side_effect = lambda prompt, ctx, **kwargs: prompt

        mock_llm_handler = MagicMock()
        mock_llm_handler.takes_message_collection = True
        mock_llm_handler.llm.get_response_from_llm.return_value = "LLM Response"
        context.llm_handler = mock_llm_handler

        return context

    def test_disabled_when_condense_memories_false(self, mock_context):
        """Tests that condensation is skipped when condenseMemories is false."""
        tool = SlowButQualityRAGTool()
        config = {'condenseMemories': False}

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes') as mock_read:
            tool.condense_memories("disc123", config, mock_context)
            mock_read.assert_not_called()

    def test_disabled_when_condense_memories_missing(self, mock_context):
        """Tests that condensation is skipped when condenseMemories key is absent."""
        tool = SlowButQualityRAGTool()
        config = {}

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes') as mock_read:
            tool.condense_memories("disc123", config, mock_context)
            mock_read.assert_not_called()

    def test_skips_when_memories_before_condensation_not_set(self, mock_context):
        """Tests that an error is logged and condensation skips when memoriesBeforeCondensation is missing."""
        tool = SlowButQualityRAGTool()
        config = {'condenseMemories': True}

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes') as mock_read:
            tool.condense_memories("disc123", config, mock_context)
            mock_read.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_skips_when_no_memories(self, mock_mem_path, mock_read_chunks, mock_tracker_path,
                                    mock_read_tracker, mock_context):
        """Tests that condensation skips when there are no memories."""
        tool = SlowButQualityRAGTool()
        config = {'condenseMemories': True, 'memoriesBeforeCondensation': 5}

        tool.condense_memories("disc123", config, mock_context)

        mock_read_tracker.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_skips_when_not_enough_new_memories(self, mock_mem_path, mock_read_chunks, mock_tracker_path,
                                                 mock_read_tracker, mock_context):
        """Tests that condensation skips when new memory count is below threshold."""
        tool = SlowButQualityRAGTool()
        config = {'condenseMemories': True, 'memoriesBeforeCondensation': 5, 'memoryCondensationBuffer': 2}

        # 6 memories, need 5 + 2 = 7
        mock_read_chunks.return_value = [
            (f"memory {i}", f"hash{i}") for i in range(6)
        ]

        with patch.object(tool, 'process_single_chunk') as mock_process:
            tool.condense_memories("disc123", config, mock_context)
            mock_process.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_condenses_when_threshold_met_no_tracker(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests successful condensation when no prior tracker exists (first condensation)."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
            'maxResponseSizeInTokens': 500
        }

        memories = [(f"memory {i}", f"hash{i}") for i in range(5)]
        mock_read_chunks.return_value = memories

        with patch.object(tool, 'process_single_chunk', return_value="Condensed summary text") as mock_process:
            tool.condense_memories("disc123", config, mock_context)

            mock_process.assert_called_once()
            call_args = mock_process.call_args
            combined_text = call_args[0][0]
            assert "memory 0" in combined_text
            assert "memory 1" in combined_text
            assert "memory 2" in combined_text

        mock_update_chunks.assert_called_once()
        written_chunks = mock_update_chunks.call_args[0][0]
        # Should be: condensed (1) + remaining (2) = 3 memories
        assert len(written_chunks) == 3
        assert written_chunks[0] == ("Condensed summary text", "hash2")
        assert written_chunks[1] == ("memory 3", "hash3")
        assert written_chunks[2] == ("memory 4", "hash4")

        mock_write_tracker.assert_called_once_with('/fake/tracker.json', {'lastCondensationHash': 'hash2'}, encryption_key=None)

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_condenses_with_existing_tracker(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests condensation when a tracker already exists, preserving pre-tracker memories."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        # 2 old (pre-tracker) + 4 new (post-tracker)
        memories = [(f"old memory {i}", f"old_hash{i}") for i in range(2)] + \
                   [(f"new memory {i}", f"new_hash{i}") for i in range(4)]
        mock_read_chunks.return_value = memories
        mock_read_tracker.return_value = {'lastCondensationHash': 'old_hash1'}

        with patch.object(tool, 'process_single_chunk', return_value="Condensed new") as mock_process:
            tool.condense_memories("disc123", config, mock_context)
            mock_process.assert_called_once()

        written_chunks = mock_update_chunks.call_args[0][0]
        # old (2) + condensed (1) + remaining new (1) = 4
        assert len(written_chunks) == 4
        assert written_chunks[0] == ("old memory 0", "old_hash0")
        assert written_chunks[1] == ("old memory 1", "old_hash1")
        assert written_chunks[2] == ("Condensed new", "new_hash2")
        assert written_chunks[3] == ("new memory 3", "new_hash3")

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_buffer_excludes_recent_memories(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that the buffer correctly excludes the most recent memories from condensation."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 2,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        # 5 memories: condense first 3, buffer last 2
        memories = [(f"memory {i}", f"hash{i}") for i in range(5)]
        mock_read_chunks.return_value = memories

        with patch.object(tool, 'process_single_chunk', return_value="Condensed") as mock_process:
            tool.condense_memories("disc123", config, mock_context)
            mock_process.assert_called_once()

        written_chunks = mock_update_chunks.call_args[0][0]
        # condensed (1) + buffer (2) = 3
        assert len(written_chunks) == 3
        assert written_chunks[0] == ("Condensed", "hash2")
        assert written_chunks[1] == ("memory 3", "hash3")
        assert written_chunks[2] == ("memory 4", "hash4")

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_buffer_prevents_condensation_when_not_enough(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker, mock_context
    ):
        """Tests that condensation is skipped when new memories minus buffer is below threshold."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 5,
            'memoryCondensationBuffer': 3,
        }

        # 7 memories, need 5 + 3 = 8
        mock_read_chunks.return_value = [(f"memory {i}", f"hash{i}") for i in range(7)]

        with patch.object(tool, 'process_single_chunk') as mock_process:
            tool.condense_memories("disc123", config, mock_context)
            mock_process.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_empty_llm_response_preserves_originals(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that empty LLM response aborts condensation and preserves original memories."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        mock_read_chunks.return_value = [(f"memory {i}", f"hash{i}") for i in range(5)]
        mock_read_tracker.return_value = {}

        with patch.object(tool, 'process_single_chunk', return_value="") as mock_process:
            tool.condense_memories("disc123", config, mock_context)

        mock_update_chunks.assert_not_called()
        mock_write_tracker.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_whitespace_only_llm_response_preserves_originals(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that whitespace-only LLM response aborts condensation."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        mock_read_chunks.return_value = [(f"memory {i}", f"hash{i}") for i in range(5)]
        mock_read_tracker.return_value = {}

        with patch.object(tool, 'process_single_chunk', return_value="   \n  "):
            tool.condense_memories("disc123", config, mock_context)

        mock_update_chunks.assert_not_called()
        mock_write_tracker.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_stale_tracker_hash_treats_all_as_new(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that a stale tracker hash (not found in memories) treats all memories as new."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        memories = [(f"memory {i}", f"hash{i}") for i in range(5)]
        mock_read_chunks.return_value = memories
        mock_read_tracker.return_value = {'lastCondensationHash': 'nonexistent_hash'}

        with patch.object(tool, 'process_single_chunk', return_value="Condensed from stale"):
            tool.condense_memories("disc123", config, mock_context)

        written_chunks = mock_update_chunks.call_args[0][0]
        assert len(written_chunks) == 3
        assert written_chunks[0] == ("Condensed from stale", "hash2")
        assert written_chunks[1] == ("memory 3", "hash3")
        assert written_chunks[2] == ("memory 4", "hash4")

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_placeholder_substitution_in_prompt(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that both placeholders are substituted in the prompt."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 2,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
            'condenseMemoriesPrompt': 'Context: [Memories_Before_Memories_to_Condense]\nCondense these: [MemoriesToCondense]',
            'condenseMemoriesSystemPrompt': 'You are a condensation bot.'
        }

        mock_read_chunks.return_value = [("alpha memory", "hash_a"), ("beta memory", "hash_b")]

        with patch.object(tool, 'process_single_chunk', return_value="Condensed AB") as mock_process:
            tool.condense_memories("disc123", config, mock_context)

            call_args = mock_process.call_args
            prompt_arg = call_args[0][1]
            system_arg = call_args[0][2]
            assert "[MemoriesToCondense]" not in prompt_arg
            assert "[Memories_Before_Memories_to_Condense]" not in prompt_arg
            assert "alpha memory" in prompt_arg
            assert "beta memory" in prompt_arg
            assert system_arg == "You are a condensation bot."

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_preceding_memories_populated_from_prefix(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that [Memories_Before_Memories_to_Condense] contains the 3 memories before the condensed batch."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
            'condenseMemoriesPrompt': 'Preceding: [Memories_Before_Memories_to_Condense]\nCondense: [MemoriesToCondense]',
        }

        # 5 old memories (pre-tracker) + 3 new (post-tracker)
        memories = [(f"old {i}", f"old_hash{i}") for i in range(5)] + \
                   [(f"new {i}", f"new_hash{i}") for i in range(3)]
        mock_read_chunks.return_value = memories
        mock_read_tracker.return_value = {'lastCondensationHash': 'old_hash4'}

        with patch.object(tool, 'process_single_chunk', return_value="Condensed") as mock_process:
            tool.condense_memories("disc123", config, mock_context)

            prompt_arg = mock_process.call_args[0][1]
            # The 3 memories before the condensed batch (new_start_index=5) are old 2, old 3, old 4
            assert "old 2" in prompt_arg
            assert "old 3" in prompt_arg
            assert "old 4" in prompt_arg
            # The old memories 0 and 1 should NOT be in preceding (only last 3)
            preceding_section = prompt_arg.split("Condense:")[0]
            assert "old 0" not in preceding_section
            assert "old 1" not in preceding_section

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_preceding_memories_empty_when_no_prefix(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that [Memories_Before_Memories_to_Condense] is empty when condensing from the start."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
            'condenseMemoriesPrompt': 'Before:[Memories_Before_Memories_to_Condense]End. Condense: [MemoriesToCondense]',
        }

        mock_read_chunks.return_value = [(f"memory {i}", f"hash{i}") for i in range(3)]

        with patch.object(tool, 'process_single_chunk', return_value="Condensed") as mock_process:
            tool.condense_memories("disc123", config, mock_context)

            prompt_arg = mock_process.call_args[0][1]
            assert "No preceding memories to show" in prompt_arg

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_fallback_endpoint_and_preset(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that endpoint/preset falls back to main config when overrides not set."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 2,
            'memoryCondensationBuffer': 0,
            'endpointName': 'main-endpoint',
            'preset': 'main-preset',
            'maxResponseSizeInTokens': 400
        }

        mock_read_chunks.return_value = [("memory 0", "hash0"), ("memory 1", "hash1")]

        with patch.object(tool, 'process_single_chunk', return_value="Condensed"):
            tool.condense_memories("disc123", config, mock_context)

        mock_get_endpoint.assert_called_with('main-endpoint')

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_override_endpoint_used_when_set(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that condenseMemoriesEndpointName overrides the main endpointName."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 2,
            'memoryCondensationBuffer': 0,
            'endpointName': 'main-endpoint',
            'preset': 'main-preset',
            'condenseMemoriesEndpointName': 'condensation-endpoint',
            'condenseMemoriesPreset': 'condensation-preset',
        }

        mock_read_chunks.return_value = [("memory 0", "hash0"), ("memory 1", "hash1")]

        with patch.object(tool, 'process_single_chunk', return_value="Condensed"):
            tool.condense_memories("disc123", config, mock_context)

        mock_get_endpoint.assert_called_with('condensation-endpoint')

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_condensed_memory_gets_hash_of_last_in_batch(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that the condensed memory's hash is the hash of the last memory in the condensed batch."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 4,
            'memoryCondensationBuffer': 0,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        memories = [(f"memory {i}", f"unique_hash_{i}") for i in range(6)]
        mock_read_chunks.return_value = memories

        with patch.object(tool, 'process_single_chunk', return_value="Condensed 0-3"):
            tool.condense_memories("disc123", config, mock_context)

        written_chunks = mock_update_chunks.call_args[0][0]
        assert written_chunks[0][1] == "unique_hash_3"

        mock_write_tracker.assert_called_once_with('/fake/tracker.json', {'lastCondensationHash': 'unique_hash_3'}, encryption_key=None)

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
           return_value={"maxContextTokenSize": 4096})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_exact_threshold_triggers_condensation(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker,
            mock_get_endpoint, mock_llm_service, mock_update_chunks, mock_write_tracker, mock_context
    ):
        """Tests that condensation triggers at exactly N + X memories (>= not >)."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            'memoryCondensationBuffer': 2,
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        # 5 = 3 + 2
        mock_read_chunks.return_value = [(f"memory {i}", f"hash{i}") for i in range(5)]

        with patch.object(tool, 'process_single_chunk', return_value="Condensed"):
            tool.condense_memories("disc123", config, mock_context)

        mock_update_chunks.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_condensation_tracker', return_value={})
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_condensation_tracker_file_path',
           return_value='/fake/tracker.json')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_default_buffer_is_zero(
            self, mock_mem_path, mock_read_chunks, mock_tracker_path, mock_read_tracker, mock_context
    ):
        """Tests that the default buffer is 0 when memoryCondensationBuffer is not specified."""
        tool = SlowButQualityRAGTool()
        config = {
            'condenseMemories': True,
            'memoriesBeforeCondensation': 3,
            # No memoryCondensationBuffer specified - should default to 0
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }

        # 3 memories = memoriesBeforeCondensation + 0 (default buffer)
        mock_read_chunks.return_value = [(f"memory {i}", f"hash{i}") for i in range(3)]

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config',
                   return_value={"maxContextTokenSize": 4096}), \
             patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService'), \
             patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes') as mock_update, \
             patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_condensation_tracker'), \
             patch.object(tool, 'process_single_chunk', return_value="Condensed"):
            tool.condense_memories("disc123", config, mock_context)

        mock_update.assert_called_once()
