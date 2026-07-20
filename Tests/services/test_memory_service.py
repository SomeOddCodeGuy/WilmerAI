# tests/services/test_memory_service.py

from copy import deepcopy

import pytest

from Middleware.services.memory_service import MemoryService


@pytest.fixture
def memory_service():
    """Provides a fresh instance of MemoryService for each test."""
    return MemoryService()


@pytest.fixture
def mock_messages():
    """Provides a standard list of messages for testing."""
    return [
        {'role': 'user', 'content': 'Message 1'},
        {'role': 'assistant', 'content': 'Message 2'},
        {'role': 'user', 'content': 'Message 3'},
        {'role': 'assistant', 'content': 'Message 4'},
        {'role': 'user', 'content': 'Message 5'}
    ]


# ===================================
# ==== search_vector_memories Tests ====
# ===================================

def test_search_vector_memories_no_discussion_id(memory_service):
    # Act
    result = memory_service.search_vector_memories(discussion_id=None, keywords="test")

    # Assert
    assert result == "Cannot search vector memories without a discussionId."


def test_search_vector_memories_no_results_found(mocker, memory_service):
    # Arrange
    mock_search = mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
                               return_value=[])

    # Act
    result = memory_service.search_vector_memories(discussion_id="123", keywords="search terms")

    # Assert
    mock_search.assert_called_once_with("123", "search terms", 5, api_key_hash=None,
                                        bm25_weights=None, use_recency=False)
    assert result == "No relevant memories found in the vector database for the given keywords."


def test_search_vector_memories_with_results(mocker, memory_service):
    # Arrange
    # Mock sqlite3.Row by using dictionary-like objects
    mock_row1 = {'memory_text': 'Summary of memory 1.'}
    mock_row2 = {'memory_text': 'Summary of memory 2.'}
    mock_search = mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
                               return_value=[mock_row1, mock_row2])

    # Act
    result = memory_service.search_vector_memories(discussion_id="123", keywords="search terms", limit=10)

    # Assert
    mock_search.assert_called_once_with("123", "search terms", 10, api_key_hash=None,
                                        bm25_weights=None, use_recency=False)
    expected_output = "Summary of memory 1.\n\n---\n\nSummary of memory 2."
    assert result == expected_output


# ===================================
# ==== get_recent_memories Tests ====
# ===================================

def test_get_recent_memories_stateless_mode(mocker, memory_service, mock_messages):
    # Arrange
    mock_get_recent_chats = mocker.patch(
        'Middleware.services.memory_service.MemoryService._get_recent_chat_messages_up_to_max',
        return_value=["chunk 1", "chunk 2"]
    )

    # Act
    result = memory_service.get_recent_memories(
        messages=mock_messages,
        discussion_id=None,
        max_turns_to_search=5,
        lookback_start=1
    )

    # Assert
    mock_get_recent_chats.assert_called_once_with(5, mock_messages, 1)
    assert result == "chunk 1--ChunkBreak--chunk 2"


def test_get_recent_memories_stateful_no_memories_exist(mocker, memory_service):
    # Arrange
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    result = memory_service.get_recent_memories(messages=[], discussion_id="123")

    # Assert
    assert result == "No memories have been generated yet"


@pytest.mark.parametrize("max_chunks, expected_slice_start", [
    (0, -3),
    (2, -2),
    (5, -5),
])
def test_get_recent_memories_stateful_with_various_limits(mocker, memory_service, max_chunks, expected_slice_start):
    # Arrange
    hashed_chunks = [('text1', 'h1'), ('text2', 'h2'), ('text3', 'h3'), ('text4', 'h4')]
    all_chunks = ['text1', 'text2', 'text3', 'text4']
    expected_chunks = all_chunks[expected_slice_start:]

    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=hashed_chunks)
    mocker.patch('Middleware.services.memory_service.extract_text_blocks_from_hashed_chunks', return_value=all_chunks)

    # Act
    result = memory_service.get_recent_memories(
        messages=[],
        discussion_id="123",
        max_summary_chunks_from_file=max_chunks
    )

    # Assert
    assert result == '--ChunkBreak--'.join(expected_chunks)


def test_get_recent_memories_stateful_get_all_memories(mocker, memory_service):
    # Arrange
    hashed_chunks = [('text1', 'h1'), ('text2', 'h2'), ('text3', 'h3')]
    all_chunks = ['text1', 'text2', 'text3']

    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=hashed_chunks)
    mocker.patch('Middleware.services.memory_service.extract_text_blocks_from_hashed_chunks', return_value=all_chunks)

    # Act
    result = memory_service.get_recent_memories(
        messages=[],
        discussion_id="123",
        max_summary_chunks_from_file=-1
    )

    # Assert
    assert result == "text1--ChunkBreak--text2--ChunkBreak--text3"


def test_get_recent_memories_stateful_forwards_encryption_key_and_api_key_hash(mocker, memory_service):
    """The path function receives api_key_hash and the file read receives encryption_key."""
    # Arrange
    enc_key = mocker.sentinel.encryption_key
    key_hash = mocker.sentinel.api_key_hash
    mock_path = mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path',
                             return_value='/mock/memories.json')
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    memory_service.get_recent_memories(messages=[], discussion_id="123",
                                       encryption_key=enc_key, api_key_hash=key_hash)

    # Assert
    mock_path.assert_called_once_with("123", api_key_hash=key_hash)
    mock_read.assert_called_once_with('/mock/memories.json', encryption_key=enc_key)


# =========================================================================
# ==== get_latest_memory_chunks_with_hashes_since_last_summary Tests ====
# =========================================================================

def test_get_latest_chunks_no_memory_file(mocker, memory_service):
    # Arrange
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    result = memory_service.get_latest_memory_chunks_with_hashes_since_last_summary("123")

    # Assert
    assert result == []


def test_get_latest_chunks_no_summary_file(mocker, memory_service):
    # Arrange
    memory_chunks = [('mem1', 'h1'), ('mem2', 'h2')]
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes')
    mock_read.side_effect = [memory_chunks, []]
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')

    # Act
    result = memory_service.get_latest_memory_chunks_with_hashes_since_last_summary("123")

    # Assert
    assert result == memory_chunks


def test_get_latest_chunks_with_new_memories(mocker, memory_service):
    # Arrange
    all_memory_chunks = [('mem1', 'h1'), ('mem2', 'h2'), ('mem3', 'h3')]
    summary_chunks = [('sum', 'h1')]
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes')
    mock_read.side_effect = [all_memory_chunks, summary_chunks]

    mocker.patch.object(memory_service, 'find_how_many_new_memories_since_last_summary', return_value=2)

    # Act
    result = memory_service.get_latest_memory_chunks_with_hashes_since_last_summary("123")

    # Assert
    assert result == [('mem2', 'h2'), ('mem3', 'h3')]


def test_get_latest_chunks_no_new_memories(mocker, memory_service):
    # Arrange
    all_memory_chunks = [('mem1', 'h1'), ('mem2', 'h2')]
    summary_chunks = [('sum', 'h2')]
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes')
    mock_read.side_effect = [all_memory_chunks, summary_chunks]

    mocker.patch.object(memory_service, 'find_how_many_new_memories_since_last_summary', return_value=0)

    # Act
    result = memory_service.get_latest_memory_chunks_with_hashes_since_last_summary("123")

    # Assert
    assert result == []


def test_get_latest_chunks_stale_summary_hash_returns_all(mocker, memory_service):
    """
    When the summary's anchor hash is no longer present in the memory file
    (find_how_many_new_memories_since_last_summary returns -1), the stale
    summary is ignored and all memory chunks are returned.
    """
    # Arrange
    all_memory_chunks = [('mem1', 'h1'), ('mem2', 'h2'), ('mem3', 'h3')]
    summary_chunks = [('sum', 'h_stale')]
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes')
    mock_read.side_effect = [all_memory_chunks, summary_chunks]
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')

    mocker.patch.object(memory_service, 'find_how_many_new_memories_since_last_summary', return_value=-1)

    # Act
    result = memory_service.get_latest_memory_chunks_with_hashes_since_last_summary("123")

    # Assert
    assert result == all_memory_chunks


def test_get_latest_chunks_forwards_encryption_key_and_api_key_hash(mocker, memory_service):
    """Both path functions receive api_key_hash and both file reads receive encryption_key."""
    # Arrange
    enc_key = mocker.sentinel.encryption_key
    key_hash = mocker.sentinel.api_key_hash
    mock_mem_path = mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path',
                                 return_value='/mock/memories.json')
    mock_sum_path = mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path',
                                 return_value='/mock/summary.json')
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes')
    mock_read.side_effect = [[('mem1', 'h1')], []]

    # Act
    memory_service.get_latest_memory_chunks_with_hashes_since_last_summary(
        "123", encryption_key=enc_key, api_key_hash=key_hash)

    # Assert
    mock_mem_path.assert_called_once_with("123", api_key_hash=key_hash)
    mock_sum_path.assert_called_once_with("123", api_key_hash=key_hash)
    assert mock_read.call_args_list == [
        mocker.call('/mock/memories.json', encryption_key=enc_key),
        mocker.call('/mock/summary.json', encryption_key=enc_key),
    ]


# ========================================
# ==== get_chat_summary_memories Tests ====
# ========================================

def test_get_chat_summary_memories_stateless(mocker, memory_service, mock_messages):
    # Arrange
    mocker.patch.object(
        memory_service,
        '_get_recent_chat_messages_up_to_max',
        return_value=["chunk1", "chunk2"]
    )

    # Act
    result = memory_service.get_chat_summary_memories(messages=mock_messages, discussion_id=None)

    # Assert
    assert result == "chunk1\n------------\nchunk2"


def test_get_chat_summary_memories_stateful_no_new_chunks(mocker, memory_service):
    # Arrange
    mocker.patch.object(
        memory_service,
        'get_latest_memory_chunks_with_hashes_since_last_summary',
        return_value=[]
    )

    # Act
    result = memory_service.get_chat_summary_memories(messages=[], discussion_id="123")

    # Assert
    assert result == ""


def test_get_chat_summary_memories_stateful_with_new_chunks(mocker, memory_service):
    # Arrange
    mocker.patch.object(
        memory_service,
        'get_latest_memory_chunks_with_hashes_since_last_summary',
        return_value=[('new text 1', 'nh1'), ('new text 2', 'nh2')]
    )

    # Act
    result = memory_service.get_chat_summary_memories(messages=[], discussion_id="123")

    # Assert
    assert result == "new text 1\n------------\nnew text 2"


# =====================================================
# ==== _get_recent_chat_messages_up_to_max Tests ====
# =====================================================

def test_get_recent_chat_messages_not_enough_messages(memory_service):
    # Arrange
    short_messages = [{'role': 'user', 'content': 'Hello'}]

    # Act & Assert
    assert memory_service._get_recent_chat_messages_up_to_max(5, short_messages, 0) == [
        "There are no memories to grab yet"]
    assert memory_service._get_recent_chat_messages_up_to_max(5, short_messages, 2) == [
        "There are no memories to grab yet"]


def test_get_recent_chat_messages_slicing_logic(mocker, memory_service, mock_messages):
    # Arrange
    mock_get_chunks = mocker.patch('Middleware.services.memory_service.text_utils.get_message_chunks',
                                   return_value=["chunk"])
    mocker.patch('Middleware.services.memory_service.text_utils.clear_out_user_assistant_from_chunks',
                 return_value=["chunk"])

    # Act
    memory_service._get_recent_chat_messages_up_to_max(3, mock_messages, 1)

    # Assert
    expected_slice = mock_messages[1:4]
    mock_get_chunks.assert_called_once()
    assert mock_get_chunks.call_args[0][0] == expected_slice


def test_get_recent_chat_messages_zero_max_turns_returns_sentinel(memory_service, mock_messages):
    """With max_turns_to_search=0 the selected slice is empty, so the sentinel is returned."""
    # Act
    result = memory_service._get_recent_chat_messages_up_to_max(0, mock_messages, 0)

    # Assert
    assert result == ["There are no memories to grab yet"]


def test_get_recent_chat_messages_does_not_mutate_input(memory_service, mock_messages):
    """Pins the deepcopy contract: the caller's messages list is never modified."""
    # Arrange
    original = deepcopy(mock_messages)

    # Act (real text_utils code runs; several parameter combinations exercised)
    memory_service._get_recent_chat_messages_up_to_max(3, mock_messages, 0)
    memory_service._get_recent_chat_messages_up_to_max(0, mock_messages, 0)
    memory_service._get_recent_chat_messages_up_to_max(5, mock_messages, 1)

    # Assert
    assert mock_messages == original


# ===================================
# ==== get_current_summary Tests ====
# ===================================

def test_get_current_summary_no_file(mocker, memory_service):
    # Arrange
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    result = memory_service.get_current_summary("123")

    # Assert
    assert result == "There is not yet a summary file"


def test_get_current_summary_success(mocker, memory_service):
    # Arrange
    summary_chunk = [('This is the full summary.', 'h1')]
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=summary_chunk)
    mocker.patch('Middleware.services.memory_service.extract_text_blocks_from_hashed_chunks',
                 return_value=['This is the full summary.'])

    # Act
    result = memory_service.get_current_summary("123")

    # Assert
    assert result == "This is the full summary."


def test_get_current_summary_multi_chunk_returns_first_block(mocker, memory_service):
    """
    With multiple chunks in the summary file, only the FIRST text block is
    returned. extract_text_blocks_from_hashed_chunks runs unmocked to prove
    the real extraction path.
    """
    # Arrange
    summary_chunks = [('First summary block.', 'h1'), ('Second summary block.', 'h2')]
    mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=summary_chunks)

    # Act
    result = memory_service.get_current_summary("123")

    # Assert
    assert result == "First summary block."


def test_get_current_summary_forwards_encryption_key_and_api_key_hash(mocker, memory_service):
    """The path function receives api_key_hash and the file read receives encryption_key."""
    # Arrange
    enc_key = mocker.sentinel.encryption_key
    key_hash = mocker.sentinel.api_key_hash
    mock_path = mocker.patch('Middleware.services.memory_service.get_discussion_chat_summary_file_path',
                             return_value='/mock/summary.json')
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    memory_service.get_current_summary("123", encryption_key=enc_key, api_key_hash=key_hash)

    # Assert
    mock_path.assert_called_once_with("123", api_key_hash=key_hash)
    mock_read.assert_called_once_with('/mock/summary.json', encryption_key=enc_key)


# ===================================
# ==== get_current_memories Tests ====
# ===================================

def test_get_current_memories_no_file(mocker, memory_service):
    # Arrange
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    result = memory_service.get_current_memories("123")

    # Assert
    assert result == ["There are not yet any memories"]


def test_get_current_memories_success(mocker, memory_service):
    # Arrange. extract_text_blocks_from_hashed_chunks runs unmocked so the test
    # fails if get_current_memories stops extracting the text half of each
    # (text, hash) tuple.
    memory_chunks = [('mem1', 'h1'), ('mem2', 'h2')]
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=memory_chunks)

    # Act
    result = memory_service.get_current_memories("123")

    # Assert
    assert result == ['mem1', 'mem2']


def test_get_current_memories_forwards_encryption_key_and_api_key_hash(mocker, memory_service):
    """The path function receives api_key_hash and the file read receives encryption_key."""
    # Arrange
    enc_key = mocker.sentinel.encryption_key
    key_hash = mocker.sentinel.api_key_hash
    mock_path = mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path',
                             return_value='/mock/memories.json')
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=[])

    # Act
    memory_service.get_current_memories("123", encryption_key=enc_key, api_key_hash=key_hash)

    # Assert
    mock_path.assert_called_once_with("123", api_key_hash=key_hash)
    mock_read.assert_called_once_with('/mock/memories.json', encryption_key=enc_key)


# ==============================================================
# ==== find_how_many_new_memories_since_last_summary Tests ====
# ==============================================================

@pytest.mark.parametrize("summary_chunk, memory_chunks, expected", [
    (None, [('m', 'h1')], 1),
    ([('s', 'h1')], [], -1),
    ([('s', 'h3')], [('m', 'h1'), ('m', 'h2'), ('m', 'h3')], 0),
    ([('s', 'h1')], [('m', 'h1'), ('m', 'h2'), ('m', 'h3')], 2),
    ([('s', 'h_not_found')], [('m', 'h1')], -1),
    # An empty (but not None) summary list is treated the same as no summary:
    # every memory chunk counts as new.
    ([], [('m', 'h1'), ('m', 'h2')], 2),
    # Duplicate hash in the memory file: the reversed .index() search means the
    # NEWEST occurrence wins, so a summary anchored at 'h1' reports 0 new
    # memories, not 2.
    ([('s', 'h1')], [('m', 'h1'), ('m', 'h2'), ('m', 'h1')], 0),
])
def test_find_how_many_new_memories(memory_service, summary_chunk, memory_chunks, expected):
    # Act
    result = memory_service.find_how_many_new_memories_since_last_summary(summary_chunk, memory_chunks)

    # Assert
    assert result == expected


# ===================================
# ==== search modes (semantic / hybrid) Tests ====
# ===================================

def _vec_blob(values):
    from array import array
    return array('f', values).tobytes()


def test_search_semantic_mode_ranks_by_cosine(mocker, memory_service):
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    instance = mock_service_cls.return_value
    instance.model_name = 'emb-model'
    instance.get_embeddings.return_value = [[1.0, 0.0]]
    mocker.patch('Middleware.services.memory_service.vector_db_utils.get_all_embeddings',
                 return_value=[(1, _vec_blob([0.0, 1.0])), (2, _vec_blob([1.0, 0.0]))])
    mock_by_ids = mocker.patch('Middleware.services.memory_service.vector_db_utils.get_memories_by_ids',
                               return_value=[{'memory_text': 'closest'}, {'memory_text': 'farther'}])
    mock_keyword = mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword')

    result = memory_service.search_vector_memories(
        "disc", "some;keywords", limit=5, search_mode="semantic",
        semantic_query="what about the thing", embedding_endpoint_name="Emb")

    mock_keyword.assert_not_called()
    instance.get_embeddings.assert_called_once_with(["what about the thing"], request_id=None)
    # Memory 2 matches the query vector exactly; memory 1 is orthogonal.
    mock_by_ids.assert_called_once_with("disc", [2, 1], api_key_hash=None)
    instance.close.assert_called_once()
    assert result == 'closest\n\n---\n\nfarther'


def test_search_semantic_mode_without_endpoint_falls_back_to_keyword(mocker, memory_service):
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories("disc", "kw;terms", search_mode="semantic")

    mock_keyword.assert_called_once()
    assert result == 'kw result'


def test_search_semantic_failure_falls_back_to_keyword(mocker, memory_service):
    mocker.patch('Middleware.services.memory_service.EmbeddingService',
                 side_effect=RuntimeError("endpoint down"))
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories(
        "disc", "kw;terms", search_mode="semantic", embedding_endpoint_name="Emb")

    mock_keyword.assert_called_once()
    assert result == 'kw result'


def test_search_semantic_mode_with_no_stored_embeddings_falls_back_to_keyword(mocker, memory_service):
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    instance = mock_service_cls.return_value
    instance.model_name = 'emb-model'
    instance.get_embeddings.return_value = [[1.0, 0.0]]
    mocker.patch('Middleware.services.memory_service.vector_db_utils.get_all_embeddings',
                 return_value=[])
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories(
        "disc", "kw", search_mode="semantic", embedding_endpoint_name="Emb")

    mock_keyword.assert_called_once_with(
        "disc", "kw", 5, api_key_hash=None, bm25_weights=None, use_recency=False)
    assert result == 'kw result'


def test_search_semantic_empty_store_fallback_passes_ranking_options(mocker, memory_service):
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    instance = mock_service_cls.return_value
    instance.model_name = 'emb-model'
    instance.get_embeddings.return_value = [[1.0, 0.0]]
    mocker.patch('Middleware.services.memory_service.vector_db_utils.get_all_embeddings',
                 return_value=[])
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories(
        "disc", "kw", limit=7, api_key_hash="hash123",
        bm25_weights=[2.0, 1.0, 1.0, 1.0, 1.0], use_recency=True,
        search_mode="semantic", embedding_endpoint_name="Emb")

    mock_keyword.assert_called_once_with(
        "disc", "kw", 7, api_key_hash="hash123",
        bm25_weights=[2.0, 1.0, 1.0, 1.0, 1.0], use_recency=True)
    assert result == 'kw result'


def test_search_hybrid_mode_with_empty_store_keeps_keyword_results(mocker, memory_service):
    mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
                 return_value=[{'id': 1, 'memory_text': 'kw only'}])
    mocker.patch.object(MemoryService, '_search_semantic_memory_ids', return_value=[])

    result = memory_service.search_vector_memories(
        "disc", "kw", search_mode="hybrid", embedding_endpoint_name="Emb")

    assert result == 'kw only'


def test_search_hybrid_mode_merges_with_rrf(mocker, memory_service):
    keyword_rows = [
        {'id': 10, 'memory_text': 'ten'},
        {'id': 20, 'memory_text': 'twenty'},
    ]
    mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
                 return_value=keyword_rows)
    mocker.patch.object(MemoryService, '_search_semantic_memory_ids', return_value=[20, 30])
    mock_by_ids = mocker.patch('Middleware.services.memory_service.vector_db_utils.get_memories_by_ids',
                               return_value=[{'id': 30, 'memory_text': 'thirty'}])

    result = memory_service.search_vector_memories(
        "disc", "kw", limit=5, search_mode="hybrid", embedding_endpoint_name="Emb")

    # RRF with k=60: id 20 appears in both lists and wins; 10 (rank 1, one list)
    # beats 30 (rank 2, one list). Only the id missing from keyword rows is fetched.
    mock_by_ids.assert_called_once_with("disc", [30], api_key_hash=None)
    assert result == 'twenty\n\n---\n\nten\n\n---\n\nthirty'


def test_search_hybrid_mode_truncates_fused_list_to_limit(mocker, memory_service):
    """The fused list can hold up to 2x limit distinct ids; hybrid must cut it
    to the caller's limit or the node blows its context budget."""
    keyword_rows = [
        {'id': 10, 'memory_text': 'ten'},
        {'id': 20, 'memory_text': 'twenty'},
        {'id': 30, 'memory_text': 'thirty'},
    ]
    mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
                 return_value=keyword_rows)
    mocker.patch.object(MemoryService, '_search_semantic_memory_ids', return_value=[20, 30, 40])
    mock_by_ids = mocker.patch('Middleware.services.memory_service.vector_db_utils.get_memories_by_ids',
                               return_value=[])

    result = memory_service.search_vector_memories(
        "disc", "kw", limit=3, search_mode="hybrid", embedding_endpoint_name="Emb")

    # RRF order is [20, 30, 10, 40]; limit 3 must drop 40 entirely (it is
    # never even fetched).
    mock_by_ids.assert_called_once_with("disc", [], api_key_hash=None)
    assert result == 'twenty\n\n---\n\nthirty\n\n---\n\nten'


def test_search_semantic_query_defaults_to_keywords_without_semicolons(mocker, memory_service):
    """The node handler passes semantic_query=None whenever the config omits
    semanticQuery; this derivation IS the live semantic path and must produce
    the keyword text, not an empty query (which would silently degrade
    semantic/hybrid to keyword-only forever)."""
    mock_sem = mocker.patch.object(MemoryService, '_search_semantic_memory_ids', return_value=[2])
    mocker.patch('Middleware.services.memory_service.vector_db_utils.get_memories_by_ids',
                 return_value=[{'id': 2, 'memory_text': 'hit'}])

    result = memory_service.search_vector_memories(
        "disc", "some;keywords", search_mode="semantic", embedding_endpoint_name="Emb")

    assert mock_sem.call_args[0][1] == "some keywords"
    assert result == 'hit'


def test_search_hybrid_semantic_failure_keeps_keyword_results(mocker, memory_service):
    mocker.patch('Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
                 return_value=[{'id': 1, 'memory_text': 'kw only'}])
    mocker.patch.object(MemoryService, '_search_semantic_memory_ids', return_value=None)

    result = memory_service.search_vector_memories(
        "disc", "kw", search_mode="hybrid", embedding_endpoint_name="Emb")

    assert result == 'kw only'


def test_search_unknown_mode_falls_back_to_keyword(mocker, memory_service):
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories("disc", "kw", search_mode="nonsense")

    mock_keyword.assert_called_once()
    assert result == 'kw result'


def test_search_semantic_blank_query_skips_embedding_call_and_falls_back(mocker, memory_service):
    """A blank keywords string with no semanticQuery yields an empty semantic
    query text: the embedding endpoint must never be contacted (no wasted call,
    no spurious endpoint error) and the search must degrade to keyword mode."""
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories(
        "disc", " ; ", search_mode="semantic", embedding_endpoint_name="Emb")

    mock_service_cls.assert_not_called()
    mock_keyword.assert_called_once()
    assert result == 'kw result'


def test_search_semantic_closes_service_when_get_embeddings_raises(mocker, memory_service):
    """When the embedding call itself raises (endpoint up, request fails), the
    finally block must still close the HTTP session and the search must degrade
    to keyword results."""
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    instance = mock_service_cls.return_value
    instance.model_name = 'emb-model'
    instance.get_embeddings.side_effect = RuntimeError("read timeout")
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories(
        "disc", "kw", search_mode="semantic", embedding_endpoint_name="Emb")

    instance.close.assert_called_once()
    mock_keyword.assert_called_once()
    assert result == 'kw result'


def test_search_semantic_cancelled_embedding_falls_back_to_keyword(mocker, memory_service):
    """get_embeddings returns None when the request was cancelled; the search
    must degrade to keyword results instead of raising or returning nothing."""
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    instance = mock_service_cls.return_value
    instance.model_name = 'emb-model'
    instance.get_embeddings.return_value = None
    mock_keyword = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'kw result'}])

    result = memory_service.search_vector_memories(
        "disc", "kw", search_mode="semantic", embedding_endpoint_name="Emb")

    instance.close.assert_called_once()
    mock_keyword.assert_called_once()
    assert result == 'kw result'


def test_search_semantic_forwards_request_id_to_embedding_call(mocker, memory_service):
    """The request_id must reach the embedding call so client cancellation can
    abort an in-flight semantic query."""
    mock_service_cls = mocker.patch('Middleware.services.memory_service.EmbeddingService')
    instance = mock_service_cls.return_value
    instance.model_name = 'emb-model'
    instance.get_embeddings.return_value = [[1.0, 0.0]]
    mocker.patch('Middleware.services.memory_service.vector_db_utils.get_all_embeddings',
                 return_value=[(1, _vec_blob([1.0, 0.0]))])
    mocker.patch('Middleware.services.memory_service.vector_db_utils.get_memories_by_ids',
                 return_value=[{'id': 1, 'memory_text': 'hit'}])

    result = memory_service.search_vector_memories(
        "disc", "kw", search_mode="semantic", embedding_endpoint_name="Emb",
        request_id="req-42")

    instance.get_embeddings.assert_called_once_with(["kw"], request_id="req-42")
    assert result == 'hit'


# ===================================
# ==== Entity expansion Tests ====
# ===================================

def _row(mem_id, text, entities=None):
    """Builds a mapping-style memory row with entity metadata."""
    import json as _json
    return {'id': mem_id, 'memory_text': text,
            'metadata_json': _json.dumps({'entities': entities or []})}


def test_entity_expansion_off_by_default_single_search_call(mocker, memory_service):
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[_row(1, 'base', entities=['Sarah'])])

    result = memory_service.search_vector_memories("disc", "sister; job")

    mock_search.assert_called_once()
    assert result == 'base'


def test_entity_expansion_appends_novel_hits(mocker, memory_service):
    base = [_row(1, 'Sister is Sarah.', entities=['Sarah'])]
    second = [_row(1, 'Sister is Sarah.', entities=['Sarah']),
              _row(2, 'Sarah is a nurse.', entities=['Sarah', 'Mercy General'])]
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, second])

    result = memory_service.search_vector_memories(
        "disc", "sister; job", use_entity_expansion=True)

    assert mock_search.call_count == 2
    # The second pass searches ONLY the harvested bridge entity; repeating the
    # original terms would let seed rows re-match themselves and crowd out
    # bridge hits.
    second_call_args = mock_search.call_args_list[1]
    assert second_call_args[0] == ("disc", "Sarah", 5)
    assert result == 'Sister is Sarah.\n\n---\n\nSarah is a nurse.'


def test_entity_expansion_fills_remaining_slots_beyond_reservation(mocker, memory_service):
    """The reservation is a floor, not a cap: when base results leave room
    under the limit, every novel hit fits (kept + novel up to limit), not just
    the reserved share."""
    base = [_row(1, 'Sister is Sarah.', entities=['Sarah'])]
    second = [_row(2, 'Sarah is a nurse.'),
              _row(3, 'Sarah lives in Austin.'),
              _row(4, 'Sarah married Tom.')]
    mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, second])

    result = memory_service.search_vector_memories(
        "disc", "sister; job", limit=5, use_entity_expansion=True)

    assert result == ('Sister is Sarah.\n\n---\n\nSarah is a nurse.\n\n---\n\n'
                      'Sarah lives in Austin.\n\n---\n\nSarah married Tom.')


def test_entity_expansion_reserves_slots_when_base_fills_limit(mocker, memory_service):
    base = [_row(1, 'one', entities=['Bob']), _row(2, 'two'), _row(3, 'three')]
    second = [_row(4, 'four')]
    mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, second])

    result = memory_service.search_vector_memories(
        "disc", "kw", limit=3, use_entity_expansion=True)

    # limit 3 -> one reserved slot: the weakest base hit yields to the novel hit.
    assert result == 'one\n\n---\n\ntwo\n\n---\n\nfour'


def test_entity_expansion_limit_one_keeps_strongest_direct_match(mocker, memory_service):
    base = [_row(1, 'strongest direct match', entities=['Bob'])]
    second = [_row(4, 'expansion-only hit')]
    mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, second])

    result = memory_service.search_vector_memories(
        "disc", "kw", limit=1, use_entity_expansion=True)

    # Reserved slots must never evict the single best direct match.
    assert result == 'strongest direct match'


def test_entity_expansion_no_new_entities_skips_second_pass(mocker, memory_service):
    # The only entity is already a query term (case-insensitively).
    base = [_row(1, 'base', entities=['sarah'])]
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=base)

    result = memory_service.search_vector_memories(
        "disc", "Sarah; job", use_entity_expansion=True)

    mock_search.assert_called_once()
    assert result == 'base'


def test_entity_expansion_tolerates_malformed_metadata(mocker, memory_service):
    base = [{'id': 1, 'memory_text': 'bad json', 'metadata_json': '{not json'},
            {'id': 2, 'memory_text': 'not a list',
             'metadata_json': '{"entities": "just a string"}'},
            {'id': 3, 'memory_text': 'no metadata', 'metadata_json': None}]
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=base)

    result = memory_service.search_vector_memories(
        "disc", "kw", use_entity_expansion=True)

    # Nothing harvestable -> no second pass, base results unchanged.
    mock_search.assert_called_once()
    assert result == 'bad json\n\n---\n\nnot a list\n\n---\n\nno metadata'


def test_entity_expansion_dedups_and_caps_at_keyword_limit(mocker, memory_service):
    from Middleware.utilities.vector_db_utils import MAX_KEYWORDS_FOR_SEARCH
    many_entities = ['Dup', 'dup'] + [f'Entity{i}' for i in range(70)]
    base = [_row(1, 'one', entities=many_entities), _row(2, 'two', entities=['Dup'])]
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, []])

    memory_service.search_vector_memories("disc", "kw", use_entity_expansion=True)

    expanded_query = mock_search.call_args_list[1][0][1]
    expanded_terms = expanded_query.split('; ')
    # Duplicates collapse case-insensitively and the total stays at the FTS cap.
    assert len(expanded_terms) == MAX_KEYWORDS_FOR_SEARCH
    assert expanded_terms[0] == 'Dup'
    assert 'dup' not in expanded_terms
    assert 'kw' not in expanded_terms


def test_entity_expansion_no_novel_hits_keeps_base(mocker, memory_service):
    base = [_row(1, 'only hit', entities=['Sarah'])]
    mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, base])

    result = memory_service.search_vector_memories(
        "disc", "kw", use_entity_expansion=True)

    assert result == 'only hit'


def test_entity_expansion_applies_after_hybrid_merge(mocker, memory_service):
    base = [_row(10, 'merged hit', entities=['Windchaser'])]
    novel = [_row(10, 'merged hit', entities=['Windchaser']),
             _row(30, 'boat detail')]
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        side_effect=[base, novel])
    mocker.patch.object(MemoryService, '_search_semantic_memory_ids', return_value=[10])

    result = memory_service.search_vector_memories(
        "disc", "boat; friend", search_mode="hybrid", embedding_endpoint_name="Emb",
        use_entity_expansion=True)

    # The expansion pass is keyword-based even in hybrid mode.
    assert mock_search.call_count == 2
    assert mock_search.call_args_list[1][0][1] == "Windchaser"
    assert result == 'merged hit\n\n---\n\nboat detail'


# ===================================
# ==== format_memory_rows / include_dates Tests ====
# ===================================

def test_format_memory_rows_without_dates(memory_service):
    rows = [{'memory_text': 'Fact one.'}, {'memory_text': 'Fact two.'}]

    result = memory_service.format_memory_rows(rows, include_dates=False)

    assert result == 'Fact one.\n\n---\n\nFact two.'


def test_format_memory_rows_with_dates_prefixes_iso_date(memory_service):
    rows = [
        {'memory_text': 'Fact one.', 'date_added': '2024-03-15T10:30:00+00:00'},
        {'memory_text': 'Fact two.', 'date_added': '2026-07-01T08:00:00+00:00'},
    ]

    result = memory_service.format_memory_rows(rows, include_dates=True)

    assert result == '[2024-03-15] Fact one.\n\n---\n\n[2026-07-01] Fact two.'


def test_format_memory_rows_with_dates_tolerates_missing_date(memory_service):
    rows = [{'memory_text': 'Undated fact.'}]

    result = memory_service.format_memory_rows(rows, include_dates=True)

    assert result == 'Undated fact.'


def test_search_vector_memories_forwards_ranking_options_and_formats_dates(mocker, memory_service):
    mock_search = mocker.patch(
        'Middleware.services.memory_service.vector_db_utils.search_memories_by_keyword',
        return_value=[{'memory_text': 'Dated fact.', 'date_added': '2025-12-25T00:00:00+00:00'}])

    result = memory_service.search_vector_memories(
        discussion_id="123", keywords="terms", limit=7,
        bm25_weights=[3.0, 2.0, 2.0, 2.0, 0.5], use_recency=True, include_dates=True)

    mock_search.assert_called_once_with("123", "terms", 7, api_key_hash=None,
                                        bm25_weights=[3.0, 2.0, 2.0, 2.0, 0.5], use_recency=True)
    assert result == '[2025-12-25] Dated fact.'


# ===================================
# ==== get_current_state_document Tests ====
# ===================================

def test_get_current_state_document_returns_content(mocker, memory_service):
    # Arrange
    mock_path = mocker.patch(
        'Middleware.services.memory_service.get_discussion_state_document_file_path',
        return_value='/fake/state_document.md')
    mock_read = mocker.patch(
        'Middleware.services.memory_service.read_plain_text_file',
        return_value='## Identity\n- A fact')

    # Act
    result = memory_service.get_current_state_document("disc1")

    # Assert
    mock_path.assert_called_once_with("disc1", api_key_hash=None)
    mock_read.assert_called_once_with('/fake/state_document.md', encryption_key=None)
    assert result == '## Identity\n- A fact'


def test_get_current_state_document_missing_file(mocker, memory_service):
    # Arrange
    mocker.patch('Middleware.services.memory_service.get_discussion_state_document_file_path',
                 return_value='/fake/state_document.md')
    mocker.patch('Middleware.services.memory_service.read_plain_text_file', return_value='')

    # Act
    result = memory_service.get_current_state_document("disc1")

    # Assert
    assert result == "No state document has been created yet"


def test_get_current_state_document_whitespace_only_file(mocker, memory_service):
    # Arrange
    mocker.patch('Middleware.services.memory_service.get_discussion_state_document_file_path',
                 return_value='/fake/state_document.md')
    mocker.patch('Middleware.services.memory_service.read_plain_text_file', return_value='  \n \n')

    # Act
    result = memory_service.get_current_state_document("disc1")

    # Assert
    assert result == "No state document has been created yet"


def test_get_current_state_document_forwards_encryption_key_and_api_key_hash(mocker, memory_service):
    # Arrange
    mock_path = mocker.patch(
        'Middleware.services.memory_service.get_discussion_state_document_file_path',
        return_value='/fake/state_document.md')
    mock_read = mocker.patch(
        'Middleware.services.memory_service.read_plain_text_file', return_value='content')

    # Act
    result = memory_service.get_current_state_document("disc1", encryption_key=b'key', api_key_hash='abc123')

    # Assert
    mock_path.assert_called_once_with("disc1", api_key_hash='abc123')
    mock_read.assert_called_once_with('/fake/state_document.md', encryption_key=b'key')
    assert result == 'content'
