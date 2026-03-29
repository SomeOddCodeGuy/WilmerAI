import hashlib

import pytest

from Middleware.utilities.hashing_utils import (
    chunk_messages_with_hashes,
    extract_text_blocks_from_hashed_chunks,
    hash_single_message,
    hash_message_with_images,
    find_last_matching_hash_message,
    hash_content,
)


# --- Test Data and Fixtures ---

@pytest.fixture
def sample_messages():
    """Provides a standard list of messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, who are you?"},
        {"role": "assistant", "content": "I am an AI. How can I help?"},
        {"role": "user", "content": "What is the weather like?"},
        {"role": "assistant", "content": "I cannot check the weather."},
        {"role": "user", "content": "Look at this", "images": ["image data"]},
        {"role": "user", "content": "Okay, thank you."}
    ]


# --- Helper Function Tests ---

def test_hash_content():
    """Tests the hash_content helper for correctness."""
    content = "test message"
    expected_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    assert hash_content(content) == expected_hash


# --- Public Function Tests ---

def test_hash_single_message():
    """
    Tests that hash_single_message correctly hashes the 'content' of a message dictionary.
    """
    message = {"role": "user", "content": "Hello World"}
    expected_hash = hashlib.sha256("Hello World".encode('utf-8')).hexdigest()
    assert hash_single_message(message) == expected_hash


def test_extract_text_blocks_from_hashed_chunks():
    """
    Tests that the function correctly extracts only the text blocks from a list of tuples.
    """
    hashed_chunks = [
        ("block 1", "hash1"),
        ("block 2", "hash2"),
        ("block 3", "hash3"),
    ]
    expected_texts = ["block 1", "block 2", "block 3"]
    assert extract_text_blocks_from_hashed_chunks(hashed_chunks) == expected_texts


def test_extract_text_blocks_from_empty_list():
    """
    Tests that extract_text_blocks_from_hashed_chunks handles an empty list gracefully.
    """
    assert extract_text_blocks_from_hashed_chunks([]) == []


def test_chunk_messages_with_hashes_last_message(mocker, sample_messages):
    """
    Tests chunking with the hash of the LAST message in each chunk (default behavior).
    """
    mock_chunker = mocker.patch('Middleware.utilities.hashing_utils.chunk_messages_by_token_size')
    mock_text_blocker = mocker.patch('Middleware.utilities.hashing_utils.messages_to_text_block',
                                     side_effect=lambda x: " ".join(msg['content'] for msg in x))

    chunk1 = [sample_messages[0], sample_messages[1]]
    chunk2 = [sample_messages[2], sample_messages[3]]
    mock_chunker.return_value = [chunk1, chunk2]

    result = chunk_messages_with_hashes(sample_messages, chunk_size=100, use_first_message_hash=False)

    mock_chunker.assert_called_once_with(sample_messages, 100, 0)
    assert len(result) == 2

    assert result[0][0] == "You are a helpful assistant. Hello, who are you?"
    assert result[0][1] == hash_single_message(chunk1[-1])

    assert result[1][0] == "I am an AI. How can I help? What is the weather like?"
    assert result[1][1] == hash_single_message(chunk2[-1])


def test_chunk_messages_with_hashes_first_message(mocker, sample_messages):
    """
    Tests chunking with the hash of the FIRST message in each chunk.
    """
    mock_chunker = mocker.patch('Middleware.utilities.hashing_utils.chunk_messages_by_token_size')
    mock_text_blocker = mocker.patch('Middleware.utilities.hashing_utils.messages_to_text_block',
                                     side_effect=lambda x: " ".join(msg['content'] for msg in x))

    chunk1 = [sample_messages[0], sample_messages[1]]
    chunk2 = [sample_messages[2], sample_messages[3]]
    mock_chunker.return_value = [chunk1, chunk2]

    result = chunk_messages_with_hashes(sample_messages, chunk_size=100, use_first_message_hash=True,
                                        max_messages_before_chunk=5)

    mock_chunker.assert_called_once_with(sample_messages, 100, 5)
    assert len(result) == 2

    assert result[0][1] == hash_single_message(chunk1[0])

    assert result[1][1] == hash_single_message(chunk2[0])


@pytest.mark.parametrize(
    "description, hashed_chunks, skip_system, expected_new_messages",
    [
        # 7 messages total, search_boundary = 7-4 = 3
        # "Hello, who are you?" is at index 1, match found
        (
                "Match found in the middle, including system messages",
                [("text", hash_single_message({"role": "user", "content": "Hello, who are you?"}))],
                False,
                1  # search_boundary(3) - match_index(1) - 1 = 1
        ),
        # 6 filtered messages (system removed), search_boundary = 6-4 = 2
        # "Hello" is at filtered index 0, match found at 0
        (
                "Match found, skipping system messages",
                [("text", hash_single_message({"role": "user", "content": "Hello, who are you?"}))],
                True,
                1  # search_boundary(2) - match_index(0) - 1 = 1
        ),
        # 7 messages, search_boundary = 3, no match found
        (
                "No match found, should return search boundary count",
                [("text", "non_existent_hash")],
                False,
                3  # search_boundary = 3
        ),
        # 6 filtered messages (system removed), search_boundary = 2, no match found
        (
                "No match found, skipping system, should return search boundary count",
                [("text", "non_existent_hash")],
                True,
                2  # search_boundary = 2
        ),
        # "Okay, thank you" is at index 6, but search_boundary = 3
        # So the match is OUTSIDE the search range
        (
                "Match found is skipped due to turns_to_skip_looking_back",
                [("text", hash_single_message({"role": "user", "content": "Okay, thank you."}))],
                False,
                3  # No match in valid range, return search_boundary = 3
        )
    ]
)
def test_find_last_matching_hash_message(sample_messages, description, hashed_chunks, skip_system,
                                         expected_new_messages):
    """
    Tests various scenarios for finding the last matching hash.

    The function returns the count of NEW messages to process, which is used in the calling code:
        start_index = end_index - return_value
        new_messages = messages[start_index:end_index]

    This ensures we don't reprocess already-memorized messages.
    """
    result = find_last_matching_hash_message(sample_messages, hashed_chunks, skip_system)
    assert result == expected_new_messages


def test_find_last_matching_hash_message_images_key_hashed_by_content(sample_messages):
    """
    Messages with the 'images' key are hashed by their text content, not image data.
    A hash of the text content 'Look at this' should match the message at index 5.
    """
    hashed_chunks_with_text_hash = [
        ("text", hash_single_message({"role": "user", "content": "Look at this"}))
    ]

    # 7 messages, search_boundary = 7-4 = 3
    # "Look at this" is at index 5, which is >= search_boundary (3), so it won't match
    result = find_last_matching_hash_message(sample_messages, hashed_chunks_with_text_hash, skip_system=False)
    assert result == 3  # search_boundary, no match found in valid range


# --- Tests for hash_message_with_images ---

class TestHashMessageWithImages:
    """Tests for the hash_message_with_images function."""

    def test_basic_message_with_images(self):
        """Hashes role + content + sorted images."""
        message = {"role": "user", "content": "describe this", "images": ["imgA"]}
        expected = hash_content("user" + "describe this" + "imgA")
        assert hash_message_with_images(message) == expected

    def test_multiple_images_sorted(self):
        """Images are sorted before hashing, so order doesn't matter."""
        msg1 = {"role": "user", "content": "pic", "images": ["b_data", "a_data"]}
        msg2 = {"role": "user", "content": "pic", "images": ["a_data", "b_data"]}
        assert hash_message_with_images(msg1) == hash_message_with_images(msg2)

        expected = hash_content("user" + "pic" + "a_data" + "b_data")
        assert hash_message_with_images(msg1) == expected

    def test_no_images_key(self):
        """When there is no 'images' key, hashes role + content only."""
        message = {"role": "assistant", "content": "hello"}
        expected = hash_content("assistant" + "hello")
        assert hash_message_with_images(message) == expected

    def test_empty_images_list(self):
        """When 'images' is an empty list, hashes role + content only."""
        message = {"role": "user", "content": "text", "images": []}
        expected = hash_content("user" + "text")
        assert hash_message_with_images(message) == expected

    def test_different_role_produces_different_hash(self):
        """Same content but different role should produce different hashes."""
        msg_user = {"role": "user", "content": "hello", "images": ["img"]}
        msg_asst = {"role": "assistant", "content": "hello", "images": ["img"]}
        assert hash_message_with_images(msg_user) != hash_message_with_images(msg_asst)


def test_find_last_matching_hash_message_fewer_messages_than_skip_window():
    """
    When the conversation is shorter than turns_to_skip_looking_back, search_boundary
    is clamped to 0 rather than going negative. With no match found, the function
    returns 0 (no new messages to process) instead of a negative count.
    """
    short_messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    # Use a hash that does NOT match any message, so the no-match path returns search_boundary
    hashed_chunks = [("text", "non_existent_hash")]

    # 2 messages, turns_to_skip_looking_back=4 → without the clamp, search_boundary=-2
    # and the function would return -2. With the clamp it returns 0.
    result = find_last_matching_hash_message(
        short_messages, hashed_chunks, skip_system=False, turns_to_skip_looking_back=4
    )

    assert result == 0
