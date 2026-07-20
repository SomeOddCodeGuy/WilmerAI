import json
from unittest.mock import MagicMock, patch

import pytest

from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool


@pytest.fixture(autouse=True)
def _hermetic_discussion_id_workflow_path(mocker):
    """handle_discussion_id_flow resolves the discussion-id workflow path through
    the real user config on disk (get_discussion_id_workflow_path -> get_user_config);
    stub the tool module's by-name import so tests never read machine state. Tests
    exercising the flow already patch load_config, so the fake path is never opened."""
    mocker.patch(
        'Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_id_workflow_path',
        return_value='/fake/discussion-id-workflow-settings.json')


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
            json.dumps({"title": "Test", "summary": "A test summary.", "entities": [], "key_phrases": []}),
            api_key_hash=mock_context.api_key_hash,
            index_topics=False,
        )

        assert mock_vector_db.add_vector_check_hash.call_count == 2
        mock_vector_db.add_vector_check_hash.assert_any_call(
            mock_context.discussion_id, "hash1", api_key_hash=mock_context.api_key_hash
        )
        mock_vector_db.add_vector_check_hash.assert_any_call(
            mock_context.discussion_id, "hash2", api_key_hash=mock_context.api_key_hash
        )

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_failed_vector_add_does_not_log_hash(self, mock_parse_json, mock_vector_db, mock_context):
        """A memory the DB refused to store (add returns None) must not count as
        a success: the chunk hash stays unlogged so the chunk is retried on the
        next memory cycle instead of being silently lost."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'test-vector-workflow'}
        hashed_chunks = [("first chunk", "hash1")]

        mock_context.workflow_manager.run_custom_workflow.return_value = '{}'
        mock_parse_json.return_value = {"title": "T", "summary": "S", "entities": [], "key_phrases": []}
        mock_vector_db.add_memory_to_vector_db.return_value = None

        tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        mock_vector_db.add_memory_to_vector_db.assert_called_once()
        mock_vector_db.add_vector_check_hash.assert_not_called()

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
            json.dumps({"title": "Direct", "summary": "Direct summary.", "entities": ["a"], "key_phrases": ["b"]}),
            api_key_hash=mock_context.api_key_hash,
            index_topics=False,
        )
        mock_vector_db.add_vector_check_hash.assert_called_once_with(
            mock_context.discussion_id, "chunk_hash", api_key_hash=mock_context.api_key_hash
        )

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_generate_and_store_vector_memories_threads_index_topics(self, mock_parse_json, mock_vector_db,
                                                                     mock_context):
        """Tests that vectorMemoryIndexTopics in the discussion settings reaches the write call."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'test-vector-workflow', 'vectorMemoryIndexTopics': True}
        hashed_chunks = [("a chunk", "hash1")]

        mock_context.workflow_manager.run_custom_workflow.return_value = 'raw'
        mock_parse_json.return_value = {"title": "T", "summary": "S.", "entities": [],
                                        "key_phrases": [], "topics": ["board games"]}

        tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        mock_vector_db.add_memory_to_vector_db.assert_called_once_with(
            mock_context.discussion_id,
            "S.",
            json.dumps({"title": "T", "summary": "S.", "entities": [], "key_phrases": [],
                        "topics": ["board games"]}),
            api_key_hash=mock_context.api_key_hash,
            index_topics=True,
        )

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

    def test_resolve_condensation_lock_timeout(self):
        """The lock-timeout resolver honors the config override, 0/negative (wait forever),
        and falls back to the generous default for missing or non-numeric values."""
        from Middleware.workflows.tools.slow_but_quality_rag_tool import (
            _DEFAULT_CONDENSATION_LOCK_TIMEOUT_SECONDS as DEFAULT,
        )
        resolve = SlowButQualityRAGTool._resolve_condensation_lock_timeout
        assert resolve({}) == float(DEFAULT)
        assert resolve({'condensationLockTimeoutSeconds': 5}) == 5.0
        assert resolve({'condensationLockTimeoutSeconds': 0}) == 0.0
        assert resolve({'condensationLockTimeoutSeconds': -1}) == -1.0
        assert resolve({'condensationLockTimeoutSeconds': 'nope'}) == float(DEFAULT)

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=2000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    def test_handle_discussion_id_flow_skips_when_lock_contended(
            self, mock_chunker, mock_get_path, mock_estimate_tokens, mock_read_hashes, mock_load_config,
            mock_path_exists, mock_context, caplog
    ):
        """If the per-discussion condensation lock can't be acquired within the bound, the
        node skips this round (no unlocked write) instead of blocking forever (PASS2-005)."""
        from Middleware.workflows.tools.slow_but_quality_rag_tool import _get_condensation_lock

        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 1000,
            'maxMessagesBetweenChunks': 5,
            'condensationLockTimeoutSeconds': 0.01,
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(5)]
        mock_chunker.return_value = [("some chunk text", "some_hash")]

        # Hold the lock so the node's bounded acquire times out.
        lock = _get_condensation_lock(mock_context.discussion_id)
        assert lock.acquire()
        try:
            with patch.object(tool, 'process_new_memory_chunks') as mock_process:
                with caplog.at_level(
                    "WARNING", logger="Middleware.workflows.tools.slow_but_quality_rag_tool"
                ):
                    tool.handle_discussion_id_flow(mock_context)
                mock_process.assert_not_called()
            assert any("skipping memory generation" in r.getMessage() for r in caplog.records)
        finally:
            lock.release()
            from Middleware.workflows.tools.slow_but_quality_rag_tool import (
                _condensation_locks, _condensation_locks_guard)
            with _condensation_locks_guard:
                _condensation_locks.pop(mock_context.discussion_id, None)

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
        """No discussion_id: the flow returns before ever consulting the discussion-id
        workflow config, even when the conversation is long enough to otherwise qualify
        (>= 3 messages, so the message-count guard cannot mask a broken id guard)."""
        mock_context.discussion_id = None
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(5)]
        tool = SlowButQualityRAGTool()

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config') as mock_load:
            tool.handle_discussion_id_flow(mock_context)

        mock_load.assert_not_called()

    def test_handle_discussion_id_flow_fewer_than_three_messages_skips(self, mock_context):
        """With a discussion_id but fewer than 3 messages, no memory work happens:
        the discussion-id workflow config is never loaded."""
        mock_context.messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]
        tool = SlowButQualityRAGTool()

        with patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config') as mock_load:
            tool.handle_discussion_id_flow(mock_context)

        mock_load.assert_not_called()

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
                patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config'), \
                patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
                      return_value='/nonexistent/memory.json'):
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
        Pins the flow-level half of the "walking hash" contract: handle_discussion_id_flow
        itself must never call add_vector_check_hash (the original bug advanced the hash
        at the flow level even when nothing was stored), and it must hand the hashed
        chunks to generate_and_store_vector_memories unchanged. The store-level half
        (the guard inside generate_and_store_vector_memories that skips the hash when
        nothing lands) is pinned by test_failed_vector_add_does_not_log_hash and
        test_junk_llm_output_stores_nothing_and_skips_hash.
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
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=5000)
    def test_vector_path_empty_chunker_output_generates_nothing(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """If the trigger fires but chunking yields no chunks (no text blocks), the
        flow logs and skips generation instead of calling the store with nothing."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryChunkEstimatedTokenSize': 1000,
            'vectorMemoryMaxMessagesBetweenChunks': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(10)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = []

        with patch.object(tool, 'generate_and_store_vector_memories') as mock_generate:
            tool.handle_discussion_id_flow(mock_context)

        mock_chunker.assert_called_once()
        mock_generate.assert_not_called()
        mock_vector_db.add_vector_check_hash.assert_not_called()

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
        # Only 4 messages (including no system since they're filtered), within lookback of 5
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
        # 3 messages but one is system; after filtering, only 2 non-system messages remain
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

                assert mock_chunker.called, (
                    "Flow never reached the chunker; the system-message filter was not exercised"
                )
                messages_arg = mock_chunker.call_args[0][0]
                assert messages_arg, "Chunker received no messages"
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

    # --- Invariant K (memory half): wilmerContextEstimationLevel scales the memory
    # chunk-size thresholds. Config-local (lives in the discussion-id workflow config),
    # applied whenever set with NO clampPromptToContextWindow gating; conservative /
    # absent leaves the thresholds unchanged. ---

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.chunk_messages_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.hash_single_message')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=6000)
    def test_estimation_level_raises_vector_token_threshold(
            self, mock_estimate_tokens, mock_hasher, mock_chunker, mock_vector_db, mock_load_config, mock_context
    ):
        """An estimate of 6000 triggers at conservative (>= 6000) but NOT at aggressive,
        which scales the threshold to 9000 (6000 < 9000). The level raised the bar."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': True,
            'lookbackStartTurn': 1,
            'vectorMemoryChunkEstimatedTokenSize': 6000,
            'vectorMemoryMaxMessagesBetweenChunks': 100,
            'wilmerContextEstimationLevel': 'aggressive',
        }
        mock_context.messages = [{"role": "user", "content": f"message_{i}"} for i in range(10)]
        mock_hasher.side_effect = lambda msg: f"hash_of_{msg['content']}"
        mock_vector_db.get_vector_check_hash_history.return_value = []

        with patch.object(tool, 'generate_and_store_vector_memories') as mock_generate:
            tool.handle_discussion_id_flow(mock_context)
            mock_generate.assert_not_called()
            mock_chunker.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing chunk", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length', return_value=1000)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=20)
    def test_estimation_level_raises_file_token_threshold(
            self, mock_find_hash, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """An estimate of 1000 triggers file-memory at conservative (>= 1000) but NOT at
        aggressive, which scales the threshold to 1500 (1000 < 1500)."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 1,
            'chunkEstimatedTokenSize': 1000,
            'maxMessagesBetweenChunks': 100,
            'wilmerContextEstimationLevel': 'aggressive',
        }
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

    def test_process_single_chunk_passes_request_id_chat(self, mock_context):
        """Tests that process_single_chunk passes request_id for chat-style APIs."""
        mock_context.llm_handler.takes_message_collection = True

        SlowButQualityRAGTool.process_single_chunk(
            "my text chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        call_args, call_kwargs = mock_context.llm_handler.llm.get_response_from_llm.call_args
        assert call_kwargs.get('request_id') == "test-req-123"
        assert call_kwargs.get('llm_takes_images') is False

    def test_process_single_chunk_returns_empty_without_llm_handler(self, mock_context):
        """A context with no llm_handler at all returns "" without crashing and
        without attempting variable substitution."""
        mock_context.llm_handler = None

        result = SlowButQualityRAGTool.process_single_chunk(
            "chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        assert result == ""
        mock_context.workflow_variable_service.apply_variables.assert_not_called()

    def test_process_single_chunk_returns_empty_when_handler_has_no_llm(self, mock_context):
        """A handler whose internal .llm is missing returns "" without crashing."""
        mock_context.llm_handler.llm = None

        result = SlowButQualityRAGTool.process_single_chunk(
            "chunk", "Prompt: [TextChunk]", "System: [TextChunk]", mock_context
        )

        assert result == ""
        mock_context.workflow_variable_service.apply_variables.assert_not_called()

    def test_perform_rag_on_conversation_chunk_delegates_with_config(self, mock_context):
        """With a discussion_id, the conversation-chunk entry point (used by the
        SlowButQualityRAG tool node) delegates to perform_rag_on_memory_chunk with
        the node's own config and its chunksPerMemory setting."""
        tool = SlowButQualityRAGTool()
        mock_context.config = {'chunksPerMemory': 5}

        with patch.object(tool, 'perform_rag_on_memory_chunk', return_value="summary") as mock_rag:
            result = tool.perform_rag_on_conversation_chunk("sys", "prompt", "chunk", mock_context)

        assert result == "summary"
        mock_rag.assert_called_once_with(
            "sys", "prompt", "chunk", mock_context, mock_context.config,
            custom_delimiter="", chunks_per_memory=5
        )

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
        it contains no memory chunks. This is the key fix: previously, the code
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

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.os.path.exists', return_value=True)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.load_config')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing memory", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.rough_estimate_token_length')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.find_last_matching_hash_message', return_value=0)
    def test_file_path_hash_cursor_current_skips_before_threshold_check(
            self, mock_find_hash, mock_get_path, mock_estimate_tokens,
            mock_read_hashes, mock_load_config, mock_path_exists, mock_context
    ):
        """When the hash cursor says nothing is new (find_last_matching_hash_message
        returns 0), the flow returns before even estimating tokens; this is the
        no-op path taken on every turn between memory generations."""
        tool = SlowButQualityRAGTool()
        mock_load_config.return_value = {
            'useVectorForQualityMemory': False,
            'lookbackStartTurn': 3,
            'chunkEstimatedTokenSize': 1000,
            'maxMessagesBetweenChunks': 5
        }
        mock_context.messages = [{"role": "user", "content": f"message {i}"} for i in range(20)]

        with patch.object(tool, 'process_new_memory_chunks') as mock_process:
            tool.handle_discussion_id_flow(mock_context)

        mock_process.assert_not_called()
        mock_estimate_tokens.assert_not_called()

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
        the tracker seeding should NOT happen; only consolidation mode seeds it.
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


class TestProcessNewMemoryChunks:
    """Direct unit tests for process_new_memory_chunks."""

    @pytest.fixture
    def mock_context(self, mocker):
        """Creates a mock ExecutionContext for these tests."""
        context = ExecutionContext(
            request_id="test-req-123",
            workflow_id="test-wf-123",
            discussion_id="test-disc-123",
            config={"key": "value"},
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
            workflow_config={"global_key": "global_value"},
            agent_outputs={}
        )
        context.workflow_manager = MagicMock()
        context.workflow_variable_service = MagicMock()
        return context

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes',
           return_value=[("existing summary", "existing_hash")])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_appends_split_results_to_existing_chunks(
            self, mock_get_path, mock_read_hashes, mock_update_chunks, mock_context
    ):
        """The RAG output is split on --rag_break--, each summary is paired with its
        chunk hash, and the file is overwritten with existing + new pairs."""
        tool = SlowButQualityRAGTool()
        chunks = ["chunk one", "chunk two"]
        hash_chunks = [("chunk one", "h1"), ("chunk two", "h2")]
        workflow_config = {'endpointName': 'test-endpoint'}

        with patch.object(tool, 'perform_rag_on_memory_chunk',
                          return_value="s1--rag_break--s2") as mock_rag:
            tool.process_new_memory_chunks(chunks, hash_chunks, "sys", "prompt",
                                           workflow_config, mock_context)

        mock_rag.assert_called_once_with(
            "sys", "prompt", "chunk one--ChunkBreak--chunk two", mock_context,
            workflow_config, "--rag_break--", 3
        )
        mock_update_chunks.assert_called_once_with(
            [("existing summary", "existing_hash"), ("s1", "h1"), ("s2", "h2")],
            '/fake/memories.json', mode="overwrite", encryption_key=None
        )

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.update_chunks_with_hashes')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
           return_value='/fake/memories.json')
    def test_result_hash_count_mismatch_truncates_and_warns(
            self, mock_get_path, mock_read_hashes, mock_update_chunks, mock_context, caplog
    ):
        """When the LLM returns more summaries than there are hashed chunks, the zip
        truncates to the shorter list and a warning is logged."""
        tool = SlowButQualityRAGTool()
        chunks = ["chunk one", "chunk two"]
        hash_chunks = [("chunk one", "h1"), ("chunk two", "h2")]

        with patch.object(tool, 'perform_rag_on_memory_chunk',
                          return_value="s1--rag_break--s2--rag_break--s3"):
            with caplog.at_level(
                "WARNING", logger="Middleware.workflows.tools.slow_but_quality_rag_tool"
            ):
                tool.process_new_memory_chunks(chunks, hash_chunks, "sys", "prompt",
                                               {}, mock_context)

        mock_update_chunks.assert_called_once_with(
            [("s1", "h1"), ("s2", "h2")],
            '/fake/memories.json', mode="overwrite", encryption_key=None
        )
        assert any("does not match" in r.getMessage() for r in caplog.records)


class TestPerformRagOnMemoryChunk:
    """Additional unit tests for perform_rag_on_memory_chunk routing behavior."""

    @pytest.fixture(autouse=True)
    def _no_disk_paths(self, mocker):
        """perform_rag_on_memory_chunk resolves the discussion memory file path,
        which creates the discussion folder on disk; keep these tests hermetic."""
        mocker.patch(
            'Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_memory_file_path',
            return_value='/nonexistent/memory.json')

    @pytest.fixture
    def mock_context(self, mocker):
        """Creates a mock ExecutionContext for these tests."""
        context = ExecutionContext(
            request_id="test-req-123",
            workflow_id="test-wf-123",
            discussion_id="test-disc-123",
            config={"key": "value"},
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
            workflow_config={"global_key": "global_value"},
            agent_outputs={}
        )
        context.workflow_manager = MagicMock()
        context.workflow_variable_service = MagicMock()
        mock_llm_handler = MagicMock()
        mock_llm_handler.takes_message_collection = True
        context.llm_handler = mock_llm_handler
        return context

    @patch('Middleware.services.memory_service.MemoryService.get_current_summary',
           return_value="The chat summary")
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_workflow_path_passes_exact_scoped_inputs(
            self, mock_get_endpoint, mock_llm_service, mock_read_hashes, mock_summary, mock_context
    ):
        """With fileMemoryWorkflowName set, each chunk routes through run_custom_workflow
        with scoped_inputs of exactly [chunk, current_memories, full_memories, chat_summary]."""
        tool = SlowButQualityRAGTool()
        workflow_config = {
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
            'fileMemoryWorkflowName': 'memory-file-workflow'
        }
        mock_context.workflow_manager.run_custom_workflow.return_value = "workflow summary"

        result = tool.perform_rag_on_memory_chunk(
            "sys", "prompt", "only chunk", mock_context, workflow_config
        )

        mock_context.workflow_manager.run_custom_workflow.assert_called_once_with(
            workflow_name='memory-file-workflow',
            request_id=mock_context.request_id,
            discussion_id=mock_context.discussion_id,
            messages=mock_context.messages,
            non_responder=True,
            scoped_inputs=[
                "only chunk",
                "No preceding memories to show",
                "No preceding memories to show",
                "The chat summary",
            ],
            api_key=mock_context.api_key
        )
        assert result == "workflow summary"

    @patch('Middleware.services.memory_service.MemoryService.get_current_summary', return_value="")
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_chunks_with_hashes', return_value=[])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_direct_path_rolls_prior_summaries_into_next_prompt(
            self, mock_get_endpoint, mock_llm_service, mock_read_hashes, mock_summary, mock_context
    ):
        """Rolling accumulation: chunk 2's prompt must contain chunk 1's freshly
        generated summary via the [Memory_file] placeholder."""
        tool = SlowButQualityRAGTool()
        workflow_config = {
            'endpointName': 'test-endpoint',
            'preset': 'test-preset',
        }
        rag_prompt = "Recent memories: [Memory_file]\nSummarize the chunk."

        with patch.object(SlowButQualityRAGTool, 'process_single_chunk',
                          side_effect=["summary1", "summary2"]) as mock_process:
            result = tool.perform_rag_on_memory_chunk(
                "sys", rag_prompt, "chunk1--ChunkBreak--chunk2", mock_context,
                workflow_config, custom_delimiter="||"
            )

        assert result == "summary1||summary2"
        assert mock_process.call_count == 2
        first_prompt = mock_process.call_args_list[0][0][1]
        second_prompt = mock_process.call_args_list[1][0][1]
        assert "No preceding memories to show" in first_prompt
        assert "summary1" in second_prompt


class TestGenerateAndStoreVectorMemoriesNegativePaths:
    """Negative-path tests for generate_and_store_vector_memories."""

    @pytest.fixture
    def mock_context(self, mocker):
        """Creates a mock ExecutionContext for these tests."""
        context = ExecutionContext(
            request_id="test-req-123",
            workflow_id="test-wf-123",
            discussion_id="test-disc-123",
            config={"key": "value"},
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
            workflow_config={"global_key": "global_value"},
            agent_outputs={}
        )
        context.workflow_manager = MagicMock()
        context.workflow_variable_service = MagicMock()
        return context

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_junk_llm_output_stores_nothing_and_skips_hash(
            self, mock_get_endpoint, mock_llm_service, mock_vector_db, mock_context
    ):
        """Junk (non-JSON) LLM output must not advance the resumability hash:
        no memory stored, no hash written, and the method returns 0."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryEndpointName': 'test-endpoint', 'vectorMemoryPreset': 'test-preset'}
        hashed_chunks = [("chunk text", "h1")]

        with patch.object(SlowButQualityRAGTool, 'process_single_chunk',
                          return_value="Sorry, I cannot produce JSON for this."):
            result = tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        assert result == 0
        mock_vector_db.add_memory_to_vector_db.assert_not_called()
        mock_vector_db.add_vector_check_hash.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_json_array_of_two_memories_stores_both_with_one_hash_write(
            self, mock_get_endpoint, mock_llm_service, mock_vector_db, mock_context
    ):
        """A JSON array with two valid memory objects yields two vector DB adds
        but only a single per-chunk hash write."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryEndpointName': 'test-endpoint', 'vectorMemoryPreset': 'test-preset'}
        hashed_chunks = [("chunk text", "h1")]
        llm_output = json.dumps([
            {"title": "A", "summary": "Summary A", "entities": [], "key_phrases": []},
            {"title": "B", "summary": "Summary B", "entities": [], "key_phrases": []},
        ])

        with patch.object(SlowButQualityRAGTool, 'process_single_chunk', return_value=llm_output):
            result = tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        assert result == 2
        assert mock_vector_db.add_memory_to_vector_db.call_count == 2
        stored_summaries = [c[0][1] for c in mock_vector_db.add_memory_to_vector_db.call_args_list]
        assert stored_summaries == ["Summary A", "Summary B"]
        mock_vector_db.add_vector_check_hash.assert_called_once_with(
            mock_context.discussion_id, "h1", api_key_hash=mock_context.api_key_hash
        )

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_memory_missing_required_key_is_skipped_without_crashing(
            self, mock_get_endpoint, mock_llm_service, mock_vector_db, mock_context
    ):
        """A memory object missing a required key (summary here) is dropped by the
        required-keys gate; the valid sibling still stores and the hash advances."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryEndpointName': 'test-endpoint', 'vectorMemoryPreset': 'test-preset'}
        hashed_chunks = [("chunk text", "h1")]
        llm_output = json.dumps([
            {"title": "A", "entities": [], "key_phrases": []},
            {"title": "B", "summary": "Summary B", "entities": [], "key_phrases": []},
        ])

        with patch.object(SlowButQualityRAGTool, 'process_single_chunk', return_value=llm_output):
            result = tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        assert result == 1
        mock_vector_db.add_memory_to_vector_db.assert_called_once()
        assert mock_vector_db.add_memory_to_vector_db.call_args[0][1] == "Summary B"
        mock_vector_db.add_vector_check_hash.assert_called_once_with(
            mock_context.discussion_id, "h1", api_key_hash=mock_context.api_key_hash
        )

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.LlmHandlerService')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_endpoint_config')
    def test_whitespace_only_chunk_is_skipped_entirely(
            self, mock_get_endpoint, mock_llm_service, mock_vector_db, mock_context
    ):
        """A whitespace-only chunk is skipped before any LLM call or DB write."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryEndpointName': 'test-endpoint', 'vectorMemoryPreset': 'test-preset'}
        hashed_chunks = [("   \n  ", "h_blank")]

        with patch.object(SlowButQualityRAGTool, 'process_single_chunk') as mock_process:
            result = tool.generate_and_store_vector_memories(hashed_chunks, config, mock_context)

        assert result == 0
        mock_process.assert_not_called()
        mock_context.workflow_manager.run_custom_workflow.assert_not_called()
        mock_vector_db.add_memory_to_vector_db.assert_not_called()
        mock_vector_db.add_vector_check_hash.assert_not_called()


class TestKeywordSearchEdgeCases:
    """Edge-case tests for the keyword/conversation search paths."""

    @pytest.fixture
    def mock_context(self, mocker):
        """Creates a mock ExecutionContext for these tests."""
        context = ExecutionContext(
            request_id="test-req-123",
            workflow_id="test-wf-123",
            discussion_id="test-disc-123",
            config={"key": "value"},
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
            workflow_config={"global_key": "global_value"},
            agent_outputs={}
        )
        context.workflow_manager = MagicMock()
        context.workflow_variable_service = MagicMock()
        mock_llm_handler = MagicMock()
        mock_llm_handler.takes_message_collection = True
        context.llm_handler = mock_llm_handler
        return context

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.advanced_search_in_chunks',
           return_value=["found A", "", "found B"])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.filter_keywords_by_speakers',
           side_effect=lambda _, k: k)
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_message_chunks',
           return_value=["chunk1", "chunk2"])
    def test_perform_conversation_search_joins_multiple_chunks(
            self, mock_get_chunks, mock_filter, mock_advanced_search, mock_context
    ):
        """Multiple non-empty result chunks are joined with --ChunkBreak--; empty
        chunks are filtered out of the joined string."""
        tool = SlowButQualityRAGTool()
        result = tool.perform_conversation_search("test keywords", mock_context)
        assert result == "found A--ChunkBreak--found B"

    def test_perform_conversation_search_lookback_beyond_history_returns_sentinel(self, mock_context):
        """A lookbackStartTurn at or beyond the message count returns the
        no-memories sentinel without searching anything."""
        tool = SlowButQualityRAGTool()
        result = tool.perform_conversation_search("kw", mock_context, lookbackStartTurn=1)
        assert result == ('There are no memories. This conversation has not gone long '
                          'enough for there to be memories.')

    def test_perform_keyword_search_current_conversation_empty_messages(self, mock_context):
        """CurrentConversation search with no messages short-circuits to an empty
        string without calling the conversation search."""
        mock_context.messages = []
        tool = SlowButQualityRAGTool()
        with patch.object(tool, 'perform_conversation_search') as mock_conv_search:
            result = tool.perform_keyword_search("kw", "CurrentConversation", mock_context)
        assert result == ""
        mock_conv_search.assert_not_called()


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
            # No memoryCondensationBuffer specified; should default to 0
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

    def test_skips_when_lock_already_held(self, mock_context):
        """condense_memories uses a non-blocking acquire on the per-discussion lock;
        while another holder has it, the whole condensation pass is skipped."""
        from Middleware.workflows.tools.slow_but_quality_rag_tool import _get_condensation_lock

        tool = SlowButQualityRAGTool()
        config = {'condenseMemories': True, 'memoriesBeforeCondensation': 3}
        discussion_id = "test-disc-lock-held"

        lock = _get_condensation_lock(discussion_id)
        assert lock.acquire(blocking=False)
        try:
            with patch.object(tool, '_condense_memories_locked') as mock_locked:
                tool.condense_memories(discussion_id, config, mock_context)
                mock_locked.assert_not_called()
        finally:
            lock.release()
            from Middleware.workflows.tools.slow_but_quality_rag_tool import (
                _condensation_locks, _condensation_locks_guard)
            with _condensation_locks_guard:
                _condensation_locks.pop(discussion_id, None)


class TestStateDocumentUpdate:
    """Unit tests for SlowButQualityRAGTool._update_state_document."""

    def _config(self, **overrides):
        config = {
            'useStateDocument': True,
            'stateDocumentWorkflowName': 'State_Document_Workflow',
        }
        config.update(overrides)
        return config

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_state_document_file_path')
    def test_happy_path_merges_and_saves(self, mock_path, mock_read, mock_write, mock_context):
        """Tests the full merge flow: sub-workflow receives new facts and current doc, output is saved with backup."""
        tool = SlowButQualityRAGTool()
        mock_path.return_value = '/fake/state_document.md'
        mock_read.return_value = '## Old\n- old fact'
        mock_context.workflow_manager.run_custom_workflow.return_value = '## New\n- merged fact'

        tool._update_state_document(self._config(), mock_context, ['fact one', 'fact two'])

        mock_context.workflow_manager.run_custom_workflow.assert_called_once_with(
            workflow_name='State_Document_Workflow',
            request_id=mock_context.request_id,
            discussion_id=mock_context.discussion_id,
            messages=mock_context.messages,
            non_responder=True,
            scoped_inputs=['- fact one\n- fact two', '## Old\n- old fact'],
            api_key=mock_context.api_key
        )
        mock_write.assert_called_once_with(
            '/fake/state_document.md',
            '## New\n- merged fact',
            encryption_key=mock_context.encryption_key,
            backup_suffix='.bak'
        )

    def test_disabled_is_no_op(self, mock_context):
        """Tests that nothing runs when useStateDocument is absent."""
        tool = SlowButQualityRAGTool()

        tool._update_state_document({}, mock_context, ['fact'])

        mock_context.workflow_manager.run_custom_workflow.assert_not_called()

    def test_enabled_without_workflow_name_is_no_op(self, mock_context):
        """Tests that a missing stateDocumentWorkflowName is logged and skipped, not raised."""
        tool = SlowButQualityRAGTool()

        tool._update_state_document({'useStateDocument': True}, mock_context, ['fact'])

        mock_context.workflow_manager.run_custom_workflow.assert_not_called()

    def test_no_new_facts_is_no_op(self, mock_context):
        """Tests that an empty fact list never triggers the merge workflow."""
        tool = SlowButQualityRAGTool()

        tool._update_state_document(self._config(), mock_context, [])

        mock_context.workflow_manager.run_custom_workflow.assert_not_called()

    @pytest.mark.parametrize("bad_output", [None, '', '   \n  '])
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_state_document_file_path')
    def test_empty_workflow_output_keeps_existing_document(self, mock_path, mock_read, mock_write,
                                                           mock_context, bad_output):
        """Tests that an empty or whitespace merge output never overwrites the document."""
        tool = SlowButQualityRAGTool()
        mock_read.return_value = 'current document'
        mock_context.workflow_manager.run_custom_workflow.return_value = bad_output

        tool._update_state_document(self._config(), mock_context, ['fact'])

        mock_write.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_state_document_file_path')
    def test_shrink_guard_rejects_collapsed_output(self, mock_path, mock_read, mock_write, mock_context):
        """Tests that an output far smaller than the current document is rejected."""
        tool = SlowButQualityRAGTool()
        mock_read.return_value = 'x' * 1000
        mock_context.workflow_manager.run_custom_workflow.return_value = 'y' * 100

        tool._update_state_document(self._config(), mock_context, ['fact'])

        mock_write.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_state_document_file_path')
    def test_shrink_guard_disabled_by_zero_ratio(self, mock_path, mock_read, mock_write, mock_context):
        """Tests that stateDocumentMinRetentionRatio of 0 disables the shrink guard."""
        tool = SlowButQualityRAGTool()
        mock_read.return_value = 'x' * 1000
        mock_context.workflow_manager.run_custom_workflow.return_value = 'y' * 100

        tool._update_state_document(self._config(stateDocumentMinRetentionRatio=0), mock_context, ['fact'])

        mock_write.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_state_document_file_path')
    def test_shrink_guard_inactive_below_size_floor(self, mock_path, mock_read, mock_write, mock_context):
        """Tests that small documents may shrink freely (early conversations settle)."""
        tool = SlowButQualityRAGTool()
        mock_read.return_value = 'x' * 400
        mock_context.workflow_manager.run_custom_workflow.return_value = 'y' * 100

        tool._update_state_document(self._config(), mock_context, ['fact'])

        mock_write.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.write_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.read_plain_text_file')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.get_discussion_state_document_file_path')
    def test_workflow_exception_is_swallowed(self, mock_path, mock_read, mock_write, mock_context):
        """Tests that a failing merge workflow never propagates or writes."""
        tool = SlowButQualityRAGTool()
        mock_read.return_value = 'current document'
        mock_context.workflow_manager.run_custom_workflow.side_effect = RuntimeError("LLM down")

        tool._update_state_document(self._config(), mock_context, ['fact'])

        mock_write.assert_not_called()


class TestStateDocumentIntegration:
    """Tests for the state document hook inside generate_and_store_vector_memories."""

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_vector_write_path_triggers_state_document_update(self, mock_parse_json, mock_vector_db, mock_context):
        """Tests that stored summaries for a chunk are handed to the state document update."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'wf', 'useStateDocument': True,
                  'stateDocumentWorkflowName': 'State_Document_Workflow'}
        mock_context.workflow_manager.run_custom_workflow.return_value = 'raw output'
        mock_parse_json.return_value = {"title": "T", "summary": "A stored fact.",
                                        "entities": [], "key_phrases": []}

        with patch.object(tool, '_update_state_document') as mock_update:
            tool.generate_and_store_vector_memories([("chunk text", "hash1")], config, mock_context)

        mock_update.assert_called_once_with(config, mock_context, ["A stored fact."])

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_no_state_document_update_when_no_memories_stored(self, mock_parse_json, mock_vector_db, mock_context):
        """Tests that a failed chunk (no stored memories) never touches the state document."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'wf', 'useStateDocument': True,
                  'stateDocumentWorkflowName': 'State_Document_Workflow'}
        mock_context.workflow_manager.run_custom_workflow.return_value = 'raw output'
        mock_parse_json.return_value = None

        with patch.object(tool, '_update_state_document') as mock_update:
            tool.generate_and_store_vector_memories([("chunk text", "hash1")], config, mock_context)

        mock_update.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_hash_is_logged_before_state_document_update(self, mock_parse_json, mock_vector_db, mock_context):
        """Tests write ordering: hash first, so a failed doc update cannot cause duplicate re-processing."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'wf', 'useStateDocument': True,
                  'stateDocumentWorkflowName': 'State_Document_Workflow'}
        mock_context.workflow_manager.run_custom_workflow.return_value = 'raw output'
        mock_parse_json.return_value = {"title": "T", "summary": "A stored fact.",
                                        "entities": [], "key_phrases": []}

        call_order = []
        mock_vector_db.add_vector_check_hash.side_effect = lambda *a, **k: call_order.append('hash')
        with patch.object(tool, '_update_state_document',
                          side_effect=lambda *a, **k: call_order.append('update')):
            tool.generate_and_store_vector_memories([("chunk text", "hash1")], config, mock_context)

        assert call_order == ['hash', 'update']


class TestEmbeddingWriteHook:
    """Unit tests for SlowButQualityRAGTool._store_embeddings_for_new_memories."""

    def _config(self, **overrides):
        config = {'embeddingEndpointName': 'Embedding-Endpoint'}
        config.update(overrides)
        return config

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_disabled_without_endpoint_name(self, mock_service_cls, mock_vdb, mock_context):
        tool = SlowButQualityRAGTool()

        tool._store_embeddings_for_new_memories({}, mock_context, [(1, 'a fact')])

        mock_service_cls.assert_not_called()
        mock_vdb.add_embeddings_to_db.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_embeds_new_memories_plus_deduped_backlog(self, mock_service_cls, mock_vdb, mock_context):
        """New memories and the lazy-backfill batch embed in one call; overlap is deduped."""
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = [[1.0], [2.0], [3.0]]
        mock_vdb.get_memories_without_embeddings.return_value = [
            {'id': 3, 'memory_text': 'old fact'},
            {'id': 1, 'memory_text': 'already in this batch'},
        ]

        tool._store_embeddings_for_new_memories(self._config(), mock_context, [(1, 'a'), (2, 'b')])

        service.get_embeddings.assert_called_once_with(
            ['a', 'b', 'old fact'], request_id=mock_context.request_id)
        blobs = mock_vdb.add_embeddings_to_db.call_args[0][1]
        assert [memory_id for memory_id, _ in blobs] == [1, 2, 3]
        assert mock_vdb.add_embeddings_to_db.call_args[0][2] == 'emb-model'
        service.close.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_empty_embeddings_response_stores_nothing(self, mock_service_cls, mock_vdb, mock_context):
        """An endpoint returning no vectors must skip storage entirely (memories
        stay BM25-searchable) and still close the service."""
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = []

        tool._store_embeddings_for_new_memories(self._config(), mock_context, [(1, 'a')])

        mock_vdb.add_embeddings_to_db.assert_not_called()
        service.close.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_short_embedding_batch_stores_only_paired_vectors(self, mock_service_cls, mock_vdb,
                                                              mock_context):
        """If the endpoint returns fewer vectors than texts, only the pairs that
        received a vector are stored (zip truncation); the unmatched memory stays
        in the backfill backlog rather than getting a misaligned blob."""
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = [[1.0]]
        mock_vdb.get_memories_without_embeddings.return_value = []

        tool._store_embeddings_for_new_memories(self._config(), mock_context, [(1, 'a'), (2, 'b')])

        blobs = mock_vdb.add_embeddings_to_db.call_args[0][1]
        assert [memory_id for memory_id, _ in blobs] == [1]

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_backfill_disabled_by_zero_batch_size(self, mock_service_cls, mock_vdb, mock_context):
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = [[1.0]]

        tool._store_embeddings_for_new_memories(
            self._config(embeddingBackfillBatchSize=0), mock_context, [(1, 'a')])

        mock_vdb.get_memories_without_embeddings.assert_not_called()
        service.get_embeddings.assert_called_once_with(['a'], request_id=mock_context.request_id)

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_bool_batch_size_warns_and_skips_backfill(self, mock_service_cls, mock_vdb,
                                                      mock_context, caplog):
        """True is an int subclass; it must not silently act as batch size 1."""
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = [[1.0]]

        with caplog.at_level(
            "WARNING", logger="Middleware.workflows.tools.slow_but_quality_rag_tool"
        ):
            tool._store_embeddings_for_new_memories(
                self._config(embeddingBackfillBatchSize=True), mock_context, [(1, 'a')])

        assert any("embeddingBackfillBatchSize" in r.getMessage() for r in caplog.records)
        mock_vdb.get_memories_without_embeddings.assert_not_called()
        # New memories are still embedded even though backfill was skipped.
        service.get_embeddings.assert_called_once_with(['a'], request_id=mock_context.request_id)

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_non_int_batch_size_warns_and_skips_backfill(self, mock_service_cls, mock_vdb,
                                                         mock_context, caplog):
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = [[1.0]]

        with caplog.at_level(
            "WARNING", logger="Middleware.workflows.tools.slow_but_quality_rag_tool"
        ):
            tool._store_embeddings_for_new_memories(
                self._config(embeddingBackfillBatchSize="20"), mock_context, [(1, 'a')])

        assert any("embeddingBackfillBatchSize" in r.getMessage() for r in caplog.records)
        mock_vdb.get_memories_without_embeddings.assert_not_called()
        service.get_embeddings.assert_called_once_with(['a'], request_id=mock_context.request_id)

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_zero_batch_size_does_not_warn(self, mock_service_cls, mock_vdb,
                                           mock_context, caplog):
        """0 is the documented disable value; it must not produce a warning."""
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        service.get_embeddings.return_value = [[1.0]]

        with caplog.at_level(
            "WARNING", logger="Middleware.workflows.tools.slow_but_quality_rag_tool"
        ):
            tool._store_embeddings_for_new_memories(
                self._config(embeddingBackfillBatchSize=0), mock_context, [(1, 'a')])

        assert not any("embeddingBackfillBatchSize" in r.getMessage() for r in caplog.records)
        mock_vdb.get_memories_without_embeddings.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_nothing_to_embed_skips_api_call(self, mock_service_cls, mock_vdb, mock_context):
        tool = SlowButQualityRAGTool()
        service = mock_service_cls.return_value
        service.model_name = 'emb-model'
        mock_vdb.get_memories_without_embeddings.return_value = []

        tool._store_embeddings_for_new_memories(self._config(), mock_context, [])

        service.get_embeddings.assert_not_called()
        mock_vdb.add_embeddings_to_db.assert_not_called()
        service.close.assert_called_once()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.EmbeddingService')
    def test_endpoint_failure_is_swallowed(self, mock_service_cls, mock_vdb, mock_context):
        """A down embeddings endpoint must never break the memory write path."""
        tool = SlowButQualityRAGTool()
        mock_service_cls.side_effect = RuntimeError("connection refused")

        tool._store_embeddings_for_new_memories(self._config(), mock_context, [(1, 'a')])

        mock_vdb.add_embeddings_to_db.assert_not_called()

    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.vector_db_utils')
    @patch('Middleware.workflows.tools.slow_but_quality_rag_tool.SlowButQualityRAGTool._parse_llm_json_output')
    def test_generate_passes_stored_ids_to_embedding_hook(self, mock_parse_json, mock_vector_db, mock_context):
        """The write path hands (memory_id, summary) pairs from storage to the hook."""
        tool = SlowButQualityRAGTool()
        config = {'vectorMemoryWorkflowName': 'wf', 'embeddingEndpointName': 'Embedding-Endpoint'}
        mock_context.workflow_manager.run_custom_workflow.return_value = 'raw output'
        mock_parse_json.return_value = {"title": "T", "summary": "A stored fact.",
                                        "entities": [], "key_phrases": []}
        mock_vector_db.add_memory_to_vector_db.return_value = 7

        with patch.object(tool, '_store_embeddings_for_new_memories') as mock_hook:
            tool.generate_and_store_vector_memories([("chunk text", "hash1")], config, mock_context)

        mock_hook.assert_called_once_with(config, mock_context, [(7, "A stored fact.")])


class TestCondensationLockRegistry:
    """Tests for the bounded per-discussion condensation lock registry."""

    @pytest.fixture(autouse=True)
    def _isolated_registry(self):
        """Save and restore the module-level lock registry so these tests neither
        see nor leak entries from other tests."""
        from Middleware.workflows.tools.slow_but_quality_rag_tool import (
            _condensation_locks, _condensation_locks_guard)
        with _condensation_locks_guard:
            saved = dict(_condensation_locks)
            _condensation_locks.clear()
        yield
        with _condensation_locks_guard:
            _condensation_locks.clear()
            _condensation_locks.update(saved)

    def test_same_discussion_returns_same_lock(self):
        """Repeated requests for one discussion must return the identical lock object,
        otherwise the mutual exclusion it exists for is silently lost."""
        from Middleware.workflows.tools.slow_but_quality_rag_tool import _get_condensation_lock

        lock_a = _get_condensation_lock("disc-a")
        assert _get_condensation_lock("disc-a") is lock_a

    def test_eviction_of_oldest_unlocked_entry_at_cap(self, mocker):
        """At the registry cap, requesting a NEW discussion evicts the oldest
        (insertion-order) entry when that entry is not held, keeping the registry
        bounded on long-running servers."""
        from Middleware.workflows.tools import slow_but_quality_rag_tool as rag_module

        mocker.patch.object(rag_module, '_MAX_CONDENSATION_LOCKS', 2)
        rag_module._get_condensation_lock("disc-a")
        rag_module._get_condensation_lock("disc-b")

        rag_module._get_condensation_lock("disc-c")

        assert "disc-a" not in rag_module._condensation_locks
        assert set(rag_module._condensation_locks) == {"disc-b", "disc-c"}

    def test_held_oldest_lock_is_never_evicted(self, mocker):
        """A currently-held lock must survive eviction (dropping it would allow a
        second thread to condense the same memory file concurrently); the registry
        temporarily exceeds the cap instead."""
        from Middleware.workflows.tools import slow_but_quality_rag_tool as rag_module

        mocker.patch.object(rag_module, '_MAX_CONDENSATION_LOCKS', 2)
        lock_a = rag_module._get_condensation_lock("disc-a")
        rag_module._get_condensation_lock("disc-b")

        assert lock_a.acquire(blocking=False)
        try:
            lock_c = rag_module._get_condensation_lock("disc-c")
        finally:
            lock_a.release()

        assert rag_module._condensation_locks["disc-a"] is lock_a
        assert set(rag_module._condensation_locks) == {"disc-a", "disc-b", "disc-c"}
        assert lock_c is rag_module._condensation_locks["disc-c"]

    def test_existing_discussion_at_cap_does_not_evict(self, mocker):
        """Requesting a lock that already exists while the registry is at the cap
        must not evict anything; eviction only happens for genuinely new entries."""
        from Middleware.workflows.tools import slow_but_quality_rag_tool as rag_module

        mocker.patch.object(rag_module, '_MAX_CONDENSATION_LOCKS', 2)
        lock_a = rag_module._get_condensation_lock("disc-a")
        rag_module._get_condensation_lock("disc-b")

        assert rag_module._get_condensation_lock("disc-a") is lock_a
        assert set(rag_module._condensation_locks) == {"disc-a", "disc-b"}
