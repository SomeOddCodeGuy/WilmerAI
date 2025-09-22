# Tests/utilities/test_hashing_utils.py

import hashlib

import pytest

from Middleware.utilities.hashing_utils import (
    chunk_messages_with_hashes,
    extract_text_blocks_from_hashed_chunks,
    hash_single_message,
    find_last_matching_hash_message,
    _hash_message,
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
        {"role": "images", "content": "[image data]"},
        {"role": "user", "content": "Okay, thank you."}
    ]


# --- Helper Function Tests ---

def test_hash_message_internal():
    """Tests the internal _hash_message helper for correctness."""
    content = "test message"
    expected_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    assert _hash_message(content) == expected_hash


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
    "description, hashed_chunks, skip_system, expected_messages_since_match",
    [
        (
                "Match found in the middle, including system messages",
                [("text", hash_single_message({"role": "user", "content": "Hello, who are you?"}))],
                False,
                5
        ),
        (
                "Match found, skipping system messages",
                [("text", hash_single_message({"role": "user", "content": "Hello, who are you?"}))],
                True,
                5
        ),
        (
                "No match found, should return total message count",
                [("text", "non_existent_hash")],
                False,
                6
        ),
        (
                "No match found, skipping system, should return filtered message count",
                [("text", "non_existent_hash")],
                True,
                5
        ),
        (
                "Match found is skipped due to turns_to_skip_looking_back",
                [("text", hash_single_message({"role": "user", "content": "Okay, thank you."}))],
                False,
                6
        )
    ]
)
def test_find_last_matching_hash_message(sample_messages, description, hashed_chunks, skip_system,
                                         expected_messages_since_match):
    """
    Tests various scenarios for finding the last matching hash.
    """
    result = find_last_matching_hash_message(sample_messages, hashed_chunks, skip_system)
    assert result == expected_messages_since_match


def test_find_last_matching_hash_message_filters_images_role(sample_messages):
    """
    Ensures that messages with the 'images' role are always filtered out, regardless of the skip_system flag.
    """
    hashed_chunks_with_image_hash = [
        ("text", hash_single_message({"role": "images", "content": "[image data]"}))
    ]

    result = find_last_matching_hash_message(sample_messages, hashed_chunks_with_image_hash, skip_system=False)
    assert result == 6
