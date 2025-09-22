# tests/services/test_memory_service.py

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
    mock_search.assert_called_once_with("123", "search terms", 5)
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
    mock_search.assert_called_once_with("123", "search terms", 10)
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
    mock_read = mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes')
    mock_read.side_effect = [all_memory_chunks, summary_chunks]

    mocker.patch.object(memory_service, 'find_how_many_new_memories_since_last_summary', return_value=0)

    # Act
    result = memory_service.get_latest_memory_chunks_with_hashes_since_last_summary("123")

    # Assert
    assert result == []


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
    # Arrange
    memory_chunks = [('mem1', 'h1'), ('mem2', 'h2')]
    extracted_text = ['mem1', 'mem2']
    mocker.patch('Middleware.services.memory_service.get_discussion_memory_file_path')
    mocker.patch('Middleware.services.memory_service.read_chunks_with_hashes', return_value=memory_chunks)
    mocker.patch('Middleware.services.memory_service.extract_text_blocks_from_hashed_chunks',
                 return_value=extracted_text)

    # Act
    result = memory_service.get_current_memories("123")

    # Assert
    assert result == extracted_text


# ==============================================================
# ==== find_how_many_new_memories_since_last_summary Tests ====
# ==============================================================

@pytest.mark.parametrize("summary_chunk, memory_chunks, expected", [
    (None, [('m', 'h1')], 1),
    ([('s', 'h1')], [], -1),
    ([('s', 'h3')], [('m', 'h1'), ('m', 'h2'), ('m', 'h3')], 0),
    ([('s', 'h1')], [('m', 'h1'), ('m', 'h2'), ('m', 'h3')], 2),
    ([('s', 'h_not_found')], [('m', 'h1')], -1),
])
def test_find_how_many_new_memories(memory_service, summary_chunk, memory_chunks, expected):
    # Act
    result = memory_service.find_how_many_new_memories_since_last_summary(summary_chunk, memory_chunks)

    # Assert
    assert result == expected
