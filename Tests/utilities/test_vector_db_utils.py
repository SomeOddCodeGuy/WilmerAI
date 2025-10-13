# tests/utilities/test_vector_db_utils.py
# We import the standard datetime module as real_datetime to use its classes and constants
# while allowing the 'datetime' module used by the source code to be patched.
import datetime as real_datetime
import json
import math
import sqlite3
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Import the functions to test
from Middleware.utilities.vector_db_utils import (
    MAX_KEYWORDS_FOR_SEARCH,
    _get_db_path,
    _sanitize_fts5_term,
    add_memory_to_vector_db,
    add_vector_check_hash,
    get_db_connection,
    get_vector_check_hash_history,
    initialize_vector_db,
    search_memories_by_keyword,
    setup_database_functions,
)

# A consistent discussion ID for testing
TEST_DISCUSSION_ID = "test-discussion-123"


# === Fixtures ===
@pytest.fixture
def memory_db_path(mocker):
    """
    Provides a URI for a unique, shared, in-memory SQLite database for each test function.
    This ensures isolation between tests.
    """
    # 1. Generate a unique name for the in-memory database for this specific test run
    db_name = f"memdb_{uuid.uuid4()}"
    # 'mode=memory&cache=shared' allows multiple connections to the same in-memory DB
    db_uri = f"file:{db_name}?mode=memory&cache=shared"

    # 2. Patch _get_db_path to return this unique URI
    mocker.patch(
        "Middleware.utilities.vector_db_utils._get_db_path", return_value=db_uri
    )

    # 3. Initialize the database.
    # We must keep at least one connection open (initial_conn) for the duration of the fixture
    # to keep the shared in-memory database alive.
    # We must use uri=True here as we are connecting directly to the URI.
    initial_conn = sqlite3.connect(db_uri, uri=True)

    # Initialize the schema using the application code.
    # initialize_vector_db will call get_db_connection, which now correctly handles the URI.
    initialize_vector_db(TEST_DISCUSSION_ID)

    yield db_uri

    # 4. Teardown: Closing the last connection destroys the shared in-memory database.
    initial_conn.close()


@pytest.fixture
def populated_memory_db(memory_db_path):
    """Fixture that provides a pre-populated in-memory database for search tests."""
    memories = [
        (
            "Summary about Python programming.",
            json.dumps(
                {
                    "title": "Python Basics",
                    "summary": "A summary of Python.",
                    "entities": ["Python", "Programming"],
                    "key_phrases": ["scripting language", "data science"],
                }
            ),
        ),
        (
            "Details on the WilmerAI project.",
            json.dumps(
                {
                    "title": "WilmerAI Architecture",
                    "summary": "An overview of the middleware system.",
                    "entities": ["WilmerAI", "Middleware", "LLM"],
                    "key_phrases": ["workflow engine", "node-based"],
                }
            ),
        ),
        (
            "Information about SQL databases.",
            json.dumps(
                {
                    "title": "SQL Databases",
                    "summary": "How SQL works.",
                    "entities": ["SQL", "SQLite", "Database"],
                    "key_phrases": ["relational data", "query language"],
                }
            ),
        ),
    ]

    for memory_text, metadata in memories:
        add_memory_to_vector_db(TEST_DISCUSSION_ID, memory_text, metadata)

    return memory_db_path


# === Test Cases ===

# --- Helper Function Tests ---
def test_get_db_path(mocker):
    """
    Tests that the database path is constructed correctly and the directory is created.
    """
    mock_makedirs = mocker.patch("os.makedirs")
    expected_path = f"Public/{TEST_DISCUSSION_ID}_vector_memory.db"
    # Mock os.path.join to ensure consistency across platforms if necessary
    mocker.patch("os.path.join", return_value=expected_path)

    result = _get_db_path(TEST_DISCUSSION_ID)

    mock_makedirs.assert_called_once_with("Public", exist_ok=True)
    assert result == expected_path


@pytest.mark.parametrize(
    "term, expected",
    [
        ("simple", '"simple"'),
        (' search term ', '"search term"'),
        ('term-with-hyphen', '"term with hyphen"'),  # Hyphens replaced by spaces
        ('a"quote', '"a""quote"'),  # Internal quotes escaped
        ('', '""'),
        ('FTS5 operators like AND OR NOT', '"FTS5 operators like AND OR NOT"'),
    ]
)
def test_sanitize_fts5_term(term, expected):
    """Tests the sanitization logic for FTS5 search terms."""
    assert _sanitize_fts5_term(term) == expected


# --- Database Connection and Setup Tests ---
def test_setup_database_functions():
    """
    Tests that the custom recency_score function is registered on the connection.
    """
    mock_conn = MagicMock(spec=sqlite3.Connection)
    setup_database_functions(mock_conn)

    # Verify create_function was called with the correct parameters
    mock_conn.create_function.assert_called_once()
    args, kwargs = mock_conn.create_function.call_args
    assert args[0] == "recency_score"
    assert args[1] == 1  # Arity (number of arguments)
    assert callable(args[2])  # The function itself
    assert kwargs == {"deterministic": False}


def test_recency_score_logic():
    """
    Tests the internal logic of the recency_score function with controlled time mocking.
    """
    # Create a real in-memory database connection for executing the SQL function
    conn = sqlite3.connect(":memory:")

    # Define the fixed time we want 'now' to be. It must be timezone-aware (UTC).
    mock_now_val = real_datetime.datetime(2025, 9, 20, 22, 0, 0, tzinfo=real_datetime.timezone.utc)

    # We must patch the 'datetime' module within the namespace where it is used (vector_db_utils).
    # The patch must be active when the function is registered AND when the SQL is executed.
    with patch("Middleware.utilities.vector_db_utils.datetime") as mock_datetime_module:
        # The source code calls 'datetime.datetime.now()' and 'datetime.datetime.fromisoformat()'.
        # We need to mock the 'datetime' class within the mocked 'datetime' module.
        mock_datetime_class = MagicMock()
        mock_datetime_module.datetime = mock_datetime_class

        # Configure datetime.datetime.now() to return our fixed, aware timestamp.
        # Using return_value ensures that even when called with arguments (like the timezone),
        # it returns the specific value we defined.
        mock_datetime_class.now.return_value = mock_now_val

        # Configure datetime.datetime.fromisoformat() to use the actual implementation.
        mock_datetime_class.fromisoformat.side_effect = real_datetime.datetime.fromisoformat

        # Ensure 'datetime.timezone' is available
        mock_datetime_module.timezone = real_datetime.timezone

        # Now register the functions.
        setup_database_functions(conn, decay_rate=0.1, max_boost=3.0)

        # Case 1: Brand new memory (0 days old) -> Should receive max boost
        score_new = conn.execute(
            "SELECT recency_score(?)", (mock_now_val.isoformat(),)
        ).fetchone()[0]
        # If the mock works correctly, now_utc - date_added_utc should be exactly 0.
        assert score_new == pytest.approx(3.0)

        # Case 2: Memory from 7 days ago
        old_date = (mock_now_val - real_datetime.timedelta(days=7)).isoformat()
        score_old = conn.execute("SELECT recency_score(?)", (old_date,)).fetchone()[0]
        # Calculation: 1.0 + (max_boost - 1.0) * exp(-decay_rate * days)
        expected_score = 1.0 + (2.0) * math.exp(-0.1 * 7)
        assert score_old == pytest.approx(expected_score, rel=1e-5)

        # Case 3: Invalid date string -> Should return default score of 1.0
        score_invalid = conn.execute(
            "SELECT recency_score(?)", ("not-a-date",)
        ).fetchone()[0]
        assert score_invalid == 1.0

    conn.close()


def test_recency_score_type_error_handling(mocker):
    """
    Tests that a TypeError (e.g., subtracting naive and aware datetimes) is handled gracefully.
    """
    conn = sqlite3.connect(":memory:")
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.warning")

    # Setup a scenario where 'now' returns a naive datetime, but the input is aware.
    naive_now = real_datetime.datetime(2025, 9, 20, 22, 0, 0)
    aware_input = real_datetime.datetime(2025, 9, 20, 21, 0, 0, tzinfo=real_datetime.timezone.utc).isoformat()

    with patch("Middleware.utilities.vector_db_utils.datetime") as mock_datetime_module:
        mock_datetime_class = MagicMock()
        mock_datetime_module.datetime = mock_datetime_class
        mock_datetime_module.timezone = real_datetime.timezone

        # Mock now() to return a naive datetime, simulating the mock ignoring the tz argument
        mock_datetime_class.now.return_value = naive_now
        mock_datetime_class.fromisoformat.side_effect = real_datetime.datetime.fromisoformat

        setup_database_functions(conn)

        # This execution should cause a TypeError internally
        score = conn.execute(
            "SELECT recency_score(?)", (aware_input,)
        ).fetchone()[0]

        # The result should be the fallback value
        assert score == 1.0

        # A warning should have been logged
        mock_logger.assert_called()
        assert "Error calculating recency score" in mock_logger.call_args[0][0]

    conn.close()


def test_get_db_connection_uri(memory_db_path):
    """
    Tests that get_db_connection correctly handles the URI path provided by the fixture.
    """
    # The fixture patches _get_db_path to return a URI (starts with "file:").
    # We test if get_db_connection internally uses uri=True.
    conn = get_db_connection(TEST_DISCUSSION_ID)
    assert conn is not None
    assert isinstance(conn, sqlite3.Connection)

    # Verify row factory and custom functions (proves setup ran)
    assert conn.row_factory == sqlite3.Row
    result = conn.execute("SELECT recency_score('2025-01-01T00:00:00+00:00')").fetchone()
    assert result is not None
    conn.close()


def test_get_db_connection_non_uri(mocker):
    """
    Tests that get_db_connection works correctly with a standard file path (not a URI).
    """
    db_path = ":memory:"  # In-memory DB not using URI syntax
    mocker.patch("Middleware.utilities.vector_db_utils._get_db_path", return_value=db_path)

    # We also patch sqlite3.connect to verify the uri=False argument
    mock_connect = mocker.patch("sqlite3.connect", return_value=MagicMock(spec=sqlite3.Connection))

    conn = get_db_connection(TEST_DISCUSSION_ID)
    assert conn is not None

    # Verify connect was called with uri=False
    mock_connect.assert_called_with(db_path, check_same_thread=False, uri=False)


def test_get_db_connection_error(mocker):
    """
    Tests that get_db_connection returns None on connection error.
    """
    mocker.patch("Middleware.utilities.vector_db_utils._get_db_path", return_value="/invalid/path/db.sqlite")
    mocker.patch("sqlite3.connect", side_effect=sqlite3.Error("Connection failed"))
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    conn = get_db_connection(TEST_DISCUSSION_ID)

    assert conn is None
    mock_logger.assert_called_once()
    assert "Database connection error" in mock_logger.call_args[0][0]


def test_initialize_vector_db(memory_db_path):
    """
    Tests that all necessary tables are created in the database.
    """
    # The database is already initialized by the memory_db_path fixture.
    # We connect again just to inspect the schema.
    conn = sqlite3.connect(memory_db_path, uri=True)
    cursor = conn.cursor()

    # Check for table existence
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "memories" in tables
    assert "vector_memory_hash_log" in tables
    # FTS5 creates the main virtual table and several shadow tables
    assert "memories_fts" in tables


def test_initialize_vector_db_connection_error(mocker):
    """
    Tests error handling in initialize_vector_db when connection fails.
    """
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    initialize_vector_db("bad-discussion-id")

    mock_logger.assert_called_once()
    assert "Failed to initialize vector DB" in mock_logger.call_args[0][0]
    assert "Could not connect to database" in mock_logger.call_args[0][0]


def test_initialize_vector_db_execution_error(mocker):
    """
    Tests error handling when SQL execution fails during initialization.
    """
    mock_conn = MagicMock(spec=sqlite3.Connection)
    # Simulate an error on the first execute call
    mock_conn.execute.side_effect = sqlite3.Error("SQL execution failed")
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    initialize_vector_db(TEST_DISCUSSION_ID)

    # Ensure the error is logged
    mock_logger.assert_called()
    assert "Failed to initialize vector DB" in mock_logger.call_args[0][0]

    # Ensure the connection is closed even if an error occurs (due to finally block)
    mock_conn.close.assert_called_once()


# --- Data Insertion Tests (add_memory_to_vector_db) ---
def test_add_memory_to_vector_db_success(memory_db_path):
    """
    Tests adding a valid memory to the database, ensuring both tables are populated.
    """
    memory_text = "This is a test memory."
    metadata_str = json.dumps(
        {
            "title": "Test Title",
            "summary": "Test Summary",
            "entities": ["entity1", "entity2"],
            "key_phrases": ["key phrase 1", 'phrase with "quotes"'],
        }
    )

    # The function connects, writes, and closes internally
    add_memory_to_vector_db(TEST_DISCUSSION_ID, memory_text, metadata_str)

    # Verify results by connecting directly to the in-memory DB
    conn = sqlite3.connect(memory_db_path, uri=True)
    conn.row_factory = sqlite3.Row
    mem_row = conn.execute("SELECT * FROM memories").fetchone()
    fts_row = conn.execute("SELECT * FROM memories_fts").fetchone()
    conn.close()

    # Verify memories table content
    assert mem_row is not None
    assert mem_row["id"] == 1
    assert mem_row["memory_text"] == memory_text
    assert mem_row["metadata_json"] == metadata_str
    # Check that date_added is a valid ISO timestamp
    assert real_datetime.datetime.fromisoformat(mem_row["date_added"])

    # Verify FTS table content and formatting
    assert fts_row is not None
    assert fts_row["title"] == "Test Title"
    # Lists should be converted to space-separated strings, quotes removed
    assert fts_row["entities"] == "entity1 entity2"
    assert fts_row["key_phrases"] == "key phrase 1 phrase with quotes"


def test_add_memory_with_various_metadata(memory_db_path):
    """
    Tests the format_for_fts helper logic with missing or varied metadata types.
    """
    memory_text = "Memory with minimal data."
    metadata_str = json.dumps(
        {
            "title": "Minimal",
            "summary": None,  # Test None value
            "entities": "single entity",  # Test string instead of list
            # key_phrases missing
        }
    )
    add_memory_to_vector_db(TEST_DISCUSSION_ID, memory_text, metadata_str)

    # Verify results
    conn = sqlite3.connect(memory_db_path, uri=True)
    conn.row_factory = sqlite3.Row
    fts_row = conn.execute("SELECT * FROM memories_fts").fetchone()
    conn.close()

    assert fts_row is not None
    # The actual behavior: None is stored as NULL in SQLite, not converted to empty string
    assert fts_row["summary"] is None
    assert fts_row["entities"] == "single entity"
    assert fts_row["key_phrases"] == ""  # Missing should be empty string


def test_add_memory_with_invalid_json_rollback(memory_db_path, mocker):
    """
    Tests that an invalid JSON causes a rollback, ensuring no data is inserted into either table.
    """
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")
    invalid_json = '{"title": "Test Title", "summary": }'  # Malformed JSON

    add_memory_to_vector_db(TEST_DISCUSSION_ID, "some text", invalid_json)

    # Check that the specific JSON error was logged
    assert any("Failed to parse metadata JSON" in call[0][0] for call in mock_logger.call_args_list)

    # Verify transaction rollback: no data should exist in either table
    conn = sqlite3.connect(memory_db_path, uri=True)
    count_mem = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    count_fts = conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
    conn.close()

    assert count_mem == 0
    assert count_fts == 0


def test_add_memory_connection_error(mocker):
    """
    Tests error handling when database connection fails.
    """
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    add_memory_to_vector_db(TEST_DISCUSSION_ID, "text", '{"title": "Test"}')

    mock_logger.assert_called_once()
    assert "Failed to add memory" in mock_logger.call_args[0][0]
    assert "Could not connect to database" in mock_logger.call_args[0][0]


def test_add_memory_execution_error_rollback(mocker):
    """
    Tests error handling and rollback when SQL execution fails during insertion.
    """
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_cursor = MagicMock()
    # Simulate failure during the first INSERT
    mock_cursor.execute.side_effect = sqlite3.Error("Insertion failed")
    mock_conn.cursor.return_value = mock_cursor

    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    add_memory_to_vector_db(TEST_DISCUSSION_ID, "text", '{"title": "Test"}')

    # Check that the general failure error was logged
    assert any("Failed to add memory to vector DB" in call[0][0] for call in mock_logger.call_args_list)

    # Ensure rollback was called and connection was closed
    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    mock_conn.close.assert_called_once()


# --- Data Retrieval Tests (search_memories_by_keyword) ---
def test_search_memories_by_keyword_basic(populated_memory_db):
    """
    Tests basic keyword search functionality and ranking.
    """
    # Test single keyword search targeting a specific entity
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "WilmerAI", limit=5)
    assert len(results) == 1
    assert "WilmerAI project" in results[0]["memory_text"]
    assert results[0]["discussion_id"] == TEST_DISCUSSION_ID
    assert "rank" in results[0].keys()  # Check that rank column exists

    # Test searching for a keyword that appears in key_phrases of multiple memories
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "language", limit=5)
    assert len(results) == 2
    # BM25 ranking might vary, but both should be present. SQLite FTS5 rank is ordered DESC (lower is better).
    assert results[0]["rank"] <= results[1]["rank"]
    texts = [r["memory_text"] for r in results]
    assert any("Python programming" in text for text in texts)
    assert any("SQL databases" in text for text in texts)


def test_search_memories_by_keyword_multi(populated_memory_db):
    """
    Tests multi-keyword search (OR logic) and limiting results.
    """
    # Test multi-keyword search with semicolon delimiter (OR logic)
    # Should return Python and SQL results
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "Python;SQLite", limit=5)
    assert len(results) == 2

    # Test limiting the results. Querying for 3 items, limiting to 2.
    results_limited = search_memories_by_keyword(TEST_DISCUSSION_ID, "Python;SQLite;WilmerAI", limit=2)
    assert len(results_limited) == 2


def test_search_memories_by_keyword_edge_cases(populated_memory_db):
    """
    Tests search edge cases like no results or empty queries.
    """
    # Test search with no results
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "nonexistent-term", limit=5)
    assert results == []

    # Test empty search query
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "", limit=5)
    assert results == []

    # Test search with only delimiters and whitespace
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, " ; ;  ", limit=5)
    assert results == []


def test_search_memories_keyword_limit_warning(populated_memory_db, mocker):
    """
    Tests that a warning is logged and the query is truncated when too many keywords are provided.
    """
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.warning")

    # Create a search query exceeding the limit
    num_keywords = MAX_KEYWORDS_FOR_SEARCH + 5
    keywords = [f"keyword{i}" for i in range(num_keywords)]
    search_query = ";".join(keywords)

    # Execution should proceed without crashing
    search_memories_by_keyword(TEST_DISCUSSION_ID, search_query, limit=5)

    # Check that the warning was logged correctly
    mock_logger.assert_called_once()
    log_message = mock_logger.call_args[0][0]
    assert f"Received {num_keywords} keywords" in log_message
    assert f"Truncating to the first {MAX_KEYWORDS_FOR_SEARCH}" in log_message


def test_search_memories_connection_error(mocker):
    """
    Tests error handling when database connection fails during search.
    """
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)
    # Note: Error is logged by get_db_connection, not search_memories_by_keyword itself

    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "test", limit=5)
    assert results == []


def test_search_memories_query_error(mocker):
    """
    Tests error handling when query execution fails.
    """
    # Setup a mock connection and cursor where execute fails
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = sqlite3.Error("Query failed")
    mock_conn.cursor.return_value = mock_cursor

    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "test", limit=5)

    assert results == []
    mock_logger.assert_called_once()
    assert "Failed to search memories in DB" in mock_logger.call_args[0][0]

    # Ensure connection is closed even on error (due to finally block)
    mock_conn.close.assert_called_once()


# --- Hash History Tests (add/get_vector_check_hash) ---
def test_add_and_get_vector_check_hash_history(memory_db_path):
    """
    Tests adding and retrieving message hashes, ensuring correct order (LIFO) and isolation.
    """
    import time
    hashes = ["hash1", "hash2", "hash3", "hash4", "hash5"]

    # Add hashes sequentially with small delays to ensure distinct timestamps
    for h in hashes:
        add_vector_check_hash(TEST_DISCUSSION_ID, h)
        time.sleep(0.001)  # 1ms delay to ensure different timestamps

    # Get full history (should be most recent first)
    history = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=10)
    assert history == list(reversed(hashes))

    # Get limited history
    history_limited = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=3)
    assert history_limited == ["hash5", "hash4", "hash3"]

    # Test different discussion ID isolation
    add_vector_check_hash("other-id", "other-hash")
    history_other = get_vector_check_hash_history("other-id", limit=10)
    assert history_other == ["other-hash"]
    history_main = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=10)
    assert "other-hash" not in history_main


def test_get_vector_check_hash_history_empty(memory_db_path):
    """
    Tests retrieving hash history when none exist.
    """
    history = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=10)
    assert history == []


def test_get_vector_check_hash_history_connection_error(mocker):
    """
    Tests error handling when database connection fails during retrieval.
    """
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)

    history = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=10)
    assert history == []


def test_get_vector_check_hash_history_query_error(mocker):
    """
    Tests error handling when query execution fails during retrieval.
    """
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = sqlite3.Error("Query failed")
    mock_conn.cursor.return_value = mock_cursor

    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    history = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=10)

    assert history == []
    mock_logger.assert_called_once()
    assert "Failed to get vector check hash history" in mock_logger.call_args[0][0]
    mock_conn.close.assert_called_once()


def test_add_vector_check_hash_connection_error(mocker):
    """
    Tests error handling when database connection fails during hash addition.
    """
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)
    mock_logger_debug = mocker.patch("Middleware.utilities.vector_db_utils.logger.debug")

    # Should not raise an exception, just return early
    add_vector_check_hash(TEST_DISCUSSION_ID, "test-hash")

    # Debug log should not be called if connection fails
    mock_logger_debug.assert_not_called()


def test_add_vector_check_hash_execution_error_rollback(mocker):
    """
    Tests error handling and rollback when SQL execution fails during hash addition.
    """
    mock_conn = MagicMock(spec=sqlite3.Connection)

    mock_conn.execute.side_effect = sqlite3.Error("Insertion failed")

    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    add_vector_check_hash(TEST_DISCUSSION_ID, "test-hash")

    mock_logger.assert_called_once()
    assert "Failed to add vector check hash" in mock_logger.call_args[0][0]

    # Ensure rollback is called, commit is not, and connection is closed
    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    mock_conn.close.assert_called_once()


def test_vector_check_hash_timestamps(memory_db_path, mocker):
    """
    Tests that timestamps are correctly recorded and used for ordering hash entries.
    """
    # Define a sequence of times (UTC aware)
    base_time = real_datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
    time1 = base_time
    time2 = base_time + real_datetime.timedelta(minutes=1)
    time3 = base_time + real_datetime.timedelta(minutes=2)

    # Mock datetime.datetime.now() using the structured approach
    with patch("Middleware.utilities.vector_db_utils.datetime") as mock_datetime_module:
        mock_datetime_class = MagicMock()
        mock_datetime_module.datetime = mock_datetime_class
        mock_datetime_module.timezone = real_datetime.timezone

        # Configure now() to return the sequence of times
        mock_datetime_class.now.side_effect = [time1, time2, time3]

        # Add three hashes. Each call will get the next time from the side_effect list.
        add_vector_check_hash(TEST_DISCUSSION_ID, "hash1")
        add_vector_check_hash(TEST_DISCUSSION_ID, "hash2")
        add_vector_check_hash(TEST_DISCUSSION_ID, "hash3")

    # Verify they're returned in reverse chronological order
    history = get_vector_check_hash_history(TEST_DISCUSSION_ID, limit=10)
    assert history == ["hash3", "hash2", "hash1"]

    # Verify the timestamps in the database directly
    conn = sqlite3.connect(memory_db_path, uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT message_hash, timestamp FROM vector_memory_hash_log ORDER BY id").fetchall()
    conn.close()

    assert len(rows) == 3

    # The timestamps are stored as strings in SQLite (DATETIME type is actually TEXT)
    # We need to parse them back to datetime objects for comparison
    stored_times = []
    for row in rows:
        # SQLite stores datetime objects as strings in ISO format
        timestamp_str = row["timestamp"]
        # Parse the string back to a datetime object
        stored_dt = real_datetime.datetime.fromisoformat(timestamp_str)
        stored_times.append(stored_dt)

    # Compare the parsed timestamps
    assert stored_times[0] == time1
    assert stored_times[1] == time2
    assert stored_times[2] == time3
