# tests/utilities/test_vector_db_utils.py
# We import the standard datetime module as real_datetime to use its classes and constants
# while allowing the 'datetime' module used by the source code to be patched.
import datetime as real_datetime
import json
import math
import os
import sqlite3
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Import the functions to test
from Middleware.utilities.vector_db_utils import (
    MAX_KEYWORDS_FOR_SEARCH,
    _get_db_path,
    _legacy_vector_db_path,
    _legacy_vector_db_path_cwd,
    _sanitize_fts5_term,
    add_embeddings_to_db,
    add_memory_to_vector_db,
    add_vector_check_hash,
    get_all_embeddings,
    get_db_connection,
    get_memories_by_ids,
    get_memories_without_embeddings,
    get_vector_check_hash_history,
    initialize_vector_db,
    search_memories_by_keyword,
    setup_database_functions,
)

# A consistent discussion ID for testing
TEST_DISCUSSION_ID = "test-discussion-123"

# Memory texts with deliberately unequal relevance for the keyword "dragon".
# The strong match repeats the term many times in a short text; the weak match
# mentions it exactly once inside a much longer text.
STRONG_DRAGON_TEXT = (
    "The dragon returned. Dragon fire, dragon scales, dragon wings: the dragon was everywhere."
)
WEAK_DRAGON_TEXT = (
    "The travelers spent many weeks crossing the mountains and valleys, trading stories "
    "with villagers, cataloging herbs and minerals along the road, and only once, near "
    "the very end of the journey, catching a distant glimpse of a dragon flying far away "
    "over the northern peaks."
)


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


@pytest.fixture
def relevance_memory_db(memory_db_path):
    """
    Fixture with unequal keyword relevance for bm25 ranking tests.

    One memory matches "dragon" strongly (high term frequency across several
    columns of a short document), one matches weakly (a single mention in a
    longer document), and three memories do not match at all. The non-matching
    corpus is required because bm25's IDF component needs contrast: with only
    two documents in the index, the scores can tie.
    """
    add_memory_to_vector_db(
        TEST_DISCUSSION_ID,
        STRONG_DRAGON_TEXT,
        json.dumps(
            {
                "title": "Dragon sighting",
                "summary": "All about the dragon.",
                "entities": ["Dragon"],
                "key_phrases": ["dragon fire"],
            }
        ),
    )
    add_memory_to_vector_db(
        TEST_DISCUSSION_ID,
        WEAK_DRAGON_TEXT,
        json.dumps(
            {
                "title": "Travel log",
                "summary": "A long journey through the mountains.",
                "entities": ["Travelers"],
                "key_phrases": ["mountain crossing"],
            }
        ),
    )
    filler_texts = [
        "A discussion about baking sourdough bread and yeast starters.",
        "Notes on repairing the old sailboat hull before summer arrives.",
        "A summary of quarterly budget planning for the household finances.",
    ]
    for i, text in enumerate(filler_texts):
        add_memory_to_vector_db(
            TEST_DISCUSSION_ID,
            text,
            json.dumps(
                {
                    "title": f"Filler {i}",
                    "summary": text,
                    "entities": [],
                    "key_phrases": [],
                }
            ),
        )

    return memory_db_path


# === Test Cases ===

# --- Helper Function Tests ---
def test_get_db_path_new_location(mocker, tmp_path):
    """
    When neither a new database nor a legacy database exists, the function
    returns the new path inside the discussion folder.
    """
    discussion_folder = tmp_path / "discussions" / TEST_DISCUSSION_ID
    mocker.patch(
        "Middleware.utilities.vector_db_utils.config_utils.get_discussion_folder_path",
        return_value=str(discussion_folder),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path",
        return_value=str(tmp_path / "nonexistent_legacy.db"),
    )

    result = _get_db_path(TEST_DISCUSSION_ID)

    assert result == str(discussion_folder / "vector_memory.db")


def test_get_db_path_legacy_stickiness(mocker, tmp_path):
    """
    When the new path does not exist but a legacy database file is present,
    the legacy path is returned so existing data keeps being used in place.
    """
    discussion_folder = tmp_path / "discussions" / TEST_DISCUSSION_ID
    discussion_folder.mkdir(parents=True)
    legacy_db = tmp_path / "Public" / f"{TEST_DISCUSSION_ID}_vector_memory.db"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"")

    mocker.patch(
        "Middleware.utilities.vector_db_utils.config_utils.get_discussion_folder_path",
        return_value=str(discussion_folder),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path",
        return_value=str(legacy_db),
    )

    result = _get_db_path(TEST_DISCUSSION_ID)

    assert result == str(legacy_db)


def test_get_db_path_new_preferred_when_both_exist(mocker, tmp_path):
    """
    Once a new-location database exists, it is preferred even if a legacy
    file is also present.
    """
    discussion_folder = tmp_path / "discussions" / TEST_DISCUSSION_ID
    discussion_folder.mkdir(parents=True)
    new_db = discussion_folder / "vector_memory.db"
    new_db.write_bytes(b"")
    legacy_db = tmp_path / "Public" / f"{TEST_DISCUSSION_ID}_vector_memory.db"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"")

    mocker.patch(
        "Middleware.utilities.vector_db_utils.config_utils.get_discussion_folder_path",
        return_value=str(discussion_folder),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path",
        return_value=str(legacy_db),
    )

    result = _get_db_path(TEST_DISCUSSION_ID)

    assert result == str(new_db)


def test_get_db_path_cwd_legacy_stickiness(mocker, tmp_path):
    """
    When the new path and the project-root legacy path do not exist but a
    cwd-relative legacy database is present (a non-project-root launch), that
    cwd legacy path is returned so existing data is not silently orphaned.
    """
    discussion_folder = tmp_path / "discussions" / TEST_DISCUSSION_ID
    discussion_folder.mkdir(parents=True)
    cwd_legacy_db = tmp_path / "cwd" / "Public" / f"{TEST_DISCUSSION_ID}_vector_memory.db"
    cwd_legacy_db.parent.mkdir(parents=True)
    cwd_legacy_db.write_bytes(b"")
    missing_project_legacy = tmp_path / "project_root" / "Public" / f"{TEST_DISCUSSION_ID}_vector_memory.db"

    mocker.patch(
        "Middleware.utilities.vector_db_utils.config_utils.get_discussion_folder_path",
        return_value=str(discussion_folder),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path",
        return_value=str(missing_project_legacy),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path_cwd",
        return_value=str(cwd_legacy_db),
    )

    result = _get_db_path(TEST_DISCUSSION_ID)

    assert result == str(cwd_legacy_db)


def test_get_db_path_api_key_hash_skips_legacy_probes(mocker, tmp_path):
    """
    When per-user isolation is active (api_key_hash provided), existing legacy
    databases must NOT be reused; the shared legacy file would bleed one
    user's vector memories into another's. The isolated new path is returned
    even though both legacy candidates exist on disk.
    """
    discussion_folder = tmp_path / "discussions" / TEST_DISCUSSION_ID
    discussion_folder.mkdir(parents=True)
    legacy_db = tmp_path / "Public" / f"{TEST_DISCUSSION_ID}_vector_memory.db"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"")
    cwd_legacy_db = tmp_path / "cwd" / "Public" / f"{TEST_DISCUSSION_ID}_vector_memory.db"
    cwd_legacy_db.parent.mkdir(parents=True)
    cwd_legacy_db.write_bytes(b"")

    mock_folder = mocker.patch(
        "Middleware.utilities.vector_db_utils.config_utils.get_discussion_folder_path",
        return_value=str(discussion_folder),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path",
        return_value=str(legacy_db),
    )
    mocker.patch(
        "Middleware.utilities.vector_db_utils._legacy_vector_db_path_cwd",
        return_value=str(cwd_legacy_db),
    )

    result = _get_db_path(TEST_DISCUSSION_ID, api_key_hash="abc123")

    assert result == str(discussion_folder / "vector_memory.db")
    assert result != str(legacy_db)
    assert result != str(cwd_legacy_db)
    mock_folder.assert_called_once_with(TEST_DISCUSSION_ID, api_key_hash="abc123")


def test_legacy_vector_db_path_naming_contract(mocker):
    """
    Pins the project-root legacy path format:
    {project_root}/Public/{discussion_id}_vector_memory.db
    """
    fake_root = os.path.join(os.sep, "fake", "project_root")
    mocker.patch(
        "Middleware.utilities.vector_db_utils.config_utils.get_project_root_directory_path",
        return_value=fake_root,
    )

    result = _legacy_vector_db_path(TEST_DISCUSSION_ID)

    assert result == os.path.join(fake_root, "Public", f"{TEST_DISCUSSION_ID}_vector_memory.db")


def test_legacy_vector_db_path_cwd_naming_contract(mocker):
    """
    Pins the cwd-relative legacy path format:
    {cwd}/Public/{discussion_id}_vector_memory.db
    """
    fake_cwd = os.path.join(os.sep, "fake", "cwd")
    mocker.patch(
        "Middleware.utilities.vector_db_utils.os.getcwd",
        return_value=fake_cwd,
    )

    result = _legacy_vector_db_path_cwd(TEST_DISCUSSION_ID)

    assert result == os.path.join(fake_cwd, "Public", f"{TEST_DISCUSSION_ID}_vector_memory.db")


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


def test_add_memory_topics_not_indexed_by_default(memory_db_path):
    """
    Tests that the 'topics' metadata stays out of the FTS index when index_topics
    is omitted, preserving the historical indexing exactly.
    """
    metadata_str = json.dumps(
        {
            "title": "Game night",
            "summary": "Priya plays a halfling rogue.",
            "entities": ["Priya"],
            "key_phrases": ["halfling rogue"],
            "topics": ["Dungeons and Dragons"],
        }
    )
    add_memory_to_vector_db(TEST_DISCUSSION_ID, "Priya plays a halfling rogue.", metadata_str)

    conn = sqlite3.connect(memory_db_path, uri=True)
    conn.row_factory = sqlite3.Row
    fts_row = conn.execute("SELECT * FROM memories_fts").fetchone()
    conn.close()

    assert fts_row["key_phrases"] == "halfling rogue"
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "Dungeons and Dragons")
    assert results == []


def test_add_memory_index_topics_folds_into_key_phrases(memory_db_path):
    """
    Tests that index_topics=True makes topic terms keyword-searchable via the
    key_phrases FTS column, without altering the stored metadata.
    """
    metadata_str = json.dumps(
        {
            "title": "Game night",
            "summary": "Priya plays a halfling rogue.",
            "entities": ["Priya"],
            "key_phrases": ["halfling rogue"],
            "topics": ["Dungeons and Dragons", "tabletop games"],
        }
    )
    add_memory_to_vector_db(TEST_DISCUSSION_ID, "Priya plays a halfling rogue.", metadata_str,
                            index_topics=True)

    conn = sqlite3.connect(memory_db_path, uri=True)
    conn.row_factory = sqlite3.Row
    fts_row = conn.execute("SELECT * FROM memories_fts").fetchone()
    mem_row = conn.execute("SELECT * FROM memories").fetchone()
    conn.close()

    assert fts_row["key_phrases"] == "halfling rogue Dungeons and Dragons tabletop games"
    # The ground-truth metadata is untouched; only the FTS index gains the terms.
    assert mem_row["metadata_json"] == metadata_str
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "Dungeons and Dragons")
    assert len(results) == 1
    assert results[0]["memory_text"] == "Priya plays a halfling rogue."


def test_add_memory_index_topics_without_topics_is_harmless(memory_db_path):
    """
    Tests that index_topics=True with no 'topics' key leaves key_phrases as-is.
    """
    metadata_str = json.dumps(
        {
            "title": "T",
            "summary": "S",
            "entities": [],
            "key_phrases": ["only phrase"],
        }
    )
    add_memory_to_vector_db(TEST_DISCUSSION_ID, "S", metadata_str, index_topics=True)

    conn = sqlite3.connect(memory_db_path, uri=True)
    conn.row_factory = sqlite3.Row
    fts_row = conn.execute("SELECT * FROM memories_fts").fetchone()
    conn.close()

    assert fts_row["key_phrases"] == "only phrase"


def test_add_memory_with_invalid_json_fails_fast_no_writes(memory_db_path, mocker):
    """
    Tests that invalid metadata JSON fails fast: the JSON is parsed before any
    database write begins, so no transaction opens and no data lands in either table.
    """
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")
    invalid_json = '{"title": "Test Title", "summary": }'  # Malformed JSON

    add_memory_to_vector_db(TEST_DISCUSSION_ID, "some text", invalid_json)

    # Check that the specific JSON error was logged
    assert any("Failed to parse metadata JSON" in call[0][0] for call in mock_logger.call_args_list)

    # Verify nothing was written: no data should exist in either table
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
    # Both memories mention "language" exactly once in the same column, so their
    # bm25 scores can legitimately tie; strict ordering is pinned by
    # test_search_memories_by_keyword_relevance_ordering. Here we pin only that
    # bm25 rank values are negative scores (more negative = more relevant).
    assert all(r["rank"] < 0 for r in results)
    texts = [r["memory_text"] for r in results]
    assert any("Python programming" in text for text in texts)
    assert any("SQL databases" in text for text in texts)


def test_search_memories_by_keyword_relevance_ordering(relevance_memory_db):
    """
    Pins the corrected bm25 ordering: SQLite FTS5 bm25 scores are negative
    (more negative = more relevant), so 'ORDER BY rank ASC' must return the
    strongest match first, not last.
    """
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "dragon", limit=5)

    assert len(results) == 2
    assert results[0]["memory_text"] == STRONG_DRAGON_TEXT
    assert results[1]["memory_text"] == WEAK_DRAGON_TEXT
    # The stronger match must have the strictly smaller (more negative) rank.
    assert results[0]["rank"] < results[1]["rank"]
    assert all(r["rank"] < 0 for r in results)


def test_search_memories_by_keyword_relevance_survives_limit(relevance_memory_db):
    """
    With limit=1 the single surviving row must be the strongest match. Under
    the old 'ORDER BY rank DESC' bug the weak match would have been returned.
    """
    results = search_memories_by_keyword(TEST_DISCUSSION_ID, "dragon", limit=1)

    assert len(results) == 1
    assert results[0]["memory_text"] == STRONG_DRAGON_TEXT


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


def test_search_memories_keyword_limit_warning(memory_db_path, mocker):
    """
    Tests truncation semantics for oversized keyword lists: a warning is
    logged, a memory matching only a keyword past the truncation boundary
    (keyword #61+) is not returned, while a memory matching keyword #1 is.
    """
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.warning")

    kept_text = "This memory mentions keyword0 explicitly."
    dropped_text = f"This memory mentions keyword{MAX_KEYWORDS_FOR_SEARCH} explicitly."

    def make_metadata(title):
        return json.dumps({"title": title, "summary": "", "entities": [], "key_phrases": []})

    # Matches the first keyword ("keyword0"), so it survives truncation.
    add_memory_to_vector_db(TEST_DISCUSSION_ID, kept_text, make_metadata("Kept"))
    # Matches only the 61st keyword (index MAX_KEYWORDS_FOR_SEARCH), which is truncated away.
    add_memory_to_vector_db(TEST_DISCUSSION_ID, dropped_text, make_metadata("Dropped"))

    # Create a search query exceeding the limit
    num_keywords = MAX_KEYWORDS_FOR_SEARCH + 5
    keywords = [f"keyword{i}" for i in range(num_keywords)]
    search_query = ";".join(keywords)

    results = search_memories_by_keyword(TEST_DISCUSSION_ID, search_query, limit=5)

    # Only the memory matching a keyword inside the truncated window is returned.
    texts = [r["memory_text"] for r in results]
    assert kept_text in texts
    assert dropped_text not in texts

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


# --- Ranking Option Tests (bm25_weights / use_recency) ---

def _insert_memory_with_date(db_uri, memory_text, metadata, date_added):
    """Inserts a memory with a controlled date_added, mirroring the production insert shape."""
    conn = sqlite3.connect(db_uri, uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO memories (discussion_id, memory_text, date_added, metadata_json) VALUES (?, ?, ?, ?)',
            (TEST_DISCUSSION_ID, memory_text, date_added, json.dumps(metadata)))
        memory_id = cur.lastrowid
        cur.execute(
            'INSERT INTO memories_fts (rowid, title, summary, entities, key_phrases, memory_text_unweighted) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (memory_id, metadata.get('title', ''), metadata.get('summary', ''),
             ' '.join(metadata.get('entities', [])), ' '.join(metadata.get('key_phrases', [])),
             memory_text))
        conn.commit()
        return memory_id
    finally:
        conn.close()


def test_search_bm25_weights_zero_out_columns(memory_db_path):
    """
    Tests that per-column weights change ranking deterministically: zeroing a
    column removes its contribution entirely, so the memory matching only in
    the zeroed column falls behind the one matching in the weighted column.
    """
    now_iso = real_datetime.datetime.now(real_datetime.timezone.utc).isoformat()
    title_only_id = _insert_memory_with_date(
        memory_db_path, "A neutral body of text with no special terms.",
        {"title": "Phoenix sighting", "summary": "s", "entities": [], "key_phrases": []},
        now_iso)
    text_only_id = _insert_memory_with_date(
        memory_db_path, "The phoenix rose. Phoenix feathers and phoenix fire everywhere.",
        {"title": "Neutral title", "summary": "s", "entities": [], "key_phrases": []},
        now_iso)

    # Only memory_text counts: the text-only match must rank first.
    rows = search_memories_by_keyword(TEST_DISCUSSION_ID, "phoenix",
                                      bm25_weights=[0.0, 0.0, 0.0, 0.0, 1.0])
    assert [r['id'] for r in rows] == [text_only_id, title_only_id]

    # Only title counts: the title-only match must rank first.
    rows = search_memories_by_keyword(TEST_DISCUSSION_ID, "phoenix",
                                      bm25_weights=[1.0, 0.0, 0.0, 0.0, 0.0])
    assert [r['id'] for r in rows] == [title_only_id, text_only_id]


def test_search_invalid_bm25_weights_ignored_with_warning(memory_db_path, mocker):
    """Tests that malformed weights are logged and ignored, not fatal."""
    now_iso = real_datetime.datetime.now(real_datetime.timezone.utc).isoformat()
    _insert_memory_with_date(
        memory_db_path, "A memory about a phoenix.",
        {"title": "t", "summary": "s", "entities": [], "key_phrases": []}, now_iso)
    mock_warn = mocker.patch("Middleware.utilities.vector_db_utils.logger.warning")

    rows = search_memories_by_keyword(TEST_DISCUSSION_ID, "phoenix", bm25_weights=[1.0, 2.0])

    assert len(rows) == 1
    mock_warn.assert_called_once()
    assert "bm25_weights" in mock_warn.call_args[0][0]


def test_search_bool_bm25_weight_ignored_with_warning(memory_db_path, mocker):
    """A bool sneaks past a naive numeric check (bool subclasses int); the
    validation must reject it like any other malformed weights list."""
    now_iso = real_datetime.datetime.now(real_datetime.timezone.utc).isoformat()
    _insert_memory_with_date(
        memory_db_path, "A memory about a phoenix.",
        {"title": "t", "summary": "s", "entities": [], "key_phrases": []}, now_iso)
    mock_warn = mocker.patch("Middleware.utilities.vector_db_utils.logger.warning")

    rows = search_memories_by_keyword(TEST_DISCUSSION_ID, "phoenix",
                                      bm25_weights=[True, 1.0, 1.0, 1.0, 1.0])

    assert len(rows) == 1
    mock_warn.assert_called_once()
    assert "bm25_weights" in mock_warn.call_args[0][0]


def test_search_recency_boost_flips_stale_stronger_match(memory_db_path):
    """
    Tests the recency boost end to end: an old memory with a stronger BM25 match
    outranks a fresh weaker one under pure BM25, but the fresh memory wins once
    use_recency multiplies in the time-decay boost (~2.5x for new vs ~1.0x for
    a years-old memory, larger than the term-frequency advantage).
    """
    old_iso = "2019-01-01T00:00:00+00:00"
    new_iso = real_datetime.datetime.now(real_datetime.timezone.utc).isoformat()
    old_strong_id = _insert_memory_with_date(
        memory_db_path, "The griffin attacked. The griffin was enormous and fearsome.",
        {"title": "t1", "summary": "s", "entities": [], "key_phrases": []}, old_iso)
    new_weak_id = _insert_memory_with_date(
        memory_db_path, "A griffin was mentioned briefly during the conversation today.",
        {"title": "t2", "summary": "s", "entities": [], "key_phrases": []}, new_iso)

    plain = search_memories_by_keyword(TEST_DISCUSSION_ID, "griffin")
    assert [r['id'] for r in plain] == [old_strong_id, new_weak_id]

    boosted = search_memories_by_keyword(TEST_DISCUSSION_ID, "griffin", use_recency=True)
    assert [r['id'] for r in boosted] == [new_weak_id, old_strong_id]


def test_search_weights_and_recency_combined_ordering(memory_db_path):
    """
    Combined mode must bind the WEIGHTED rank into ORDER BY, not the FTS5
    'rank' alias (which SQLite resolves to the equal-weight default inside an
    expression): with the text column zeroed, an old title-only match must beat
    a fresh text-only match no matter how large the fresh row's recency boost.
    """
    old_iso = "2019-01-01T00:00:00+00:00"
    new_iso = real_datetime.datetime.now(real_datetime.timezone.utc).isoformat()
    title_old_id = _insert_memory_with_date(
        memory_db_path, "A neutral body of text with no special terms.",
        {"title": "Phoenix sighting", "summary": "s", "entities": [], "key_phrases": []},
        old_iso)
    text_new_id = _insert_memory_with_date(
        memory_db_path, "The phoenix rose. Phoenix feathers and phoenix fire everywhere.",
        {"title": "Neutral title", "summary": "s", "entities": [], "key_phrases": []},
        new_iso)

    rows = search_memories_by_keyword(TEST_DISCUSSION_ID, "phoenix",
                                      bm25_weights=[1.0, 0.0, 0.0, 0.0, 0.0],
                                      use_recency=True)

    assert [r['id'] for r in rows] == [title_old_id, text_new_id]


# --- Embedding Storage Tests ---

def _blob(values):
    """Packs floats into the float32 blob format used by the embedding store."""
    from array import array
    return array('f', values).tobytes()


def test_initialize_creates_memory_embeddings_table(memory_db_path):
    """Tests that init adds the embeddings table (including to pre-embedding DBs on re-open)."""
    conn = sqlite3.connect(memory_db_path, uri=True)
    count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memory_embeddings'"
    ).fetchone()[0]
    conn.close()

    assert count == 1


def test_add_memory_returns_new_id(memory_db_path):
    """Tests that add_memory_to_vector_db returns the inserted row id."""
    metadata = json.dumps({"title": "t", "summary": "s", "entities": [], "key_phrases": []})

    first_id = add_memory_to_vector_db(TEST_DISCUSSION_ID, "first", metadata)
    second_id = add_memory_to_vector_db(TEST_DISCUSSION_ID, "second", metadata)

    assert first_id == 1
    assert second_id == 2


def test_add_memory_returns_none_on_bad_metadata(memory_db_path):
    """Tests that a metadata parse failure returns None instead of an id."""
    assert add_memory_to_vector_db(TEST_DISCUSSION_ID, "text", "{not json") is None


def test_embeddings_roundtrip(memory_db_path):
    """Tests storing and retrieving embedding blobs for a model."""
    stored = add_embeddings_to_db(
        TEST_DISCUSSION_ID, [(1, _blob([1.0, 0.0])), (2, _blob([0.0, 1.0]))], "model-a")

    assert stored == 2
    pairs = get_all_embeddings(TEST_DISCUSSION_ID, "model-a")
    assert sorted(pair[0] for pair in pairs) == [1, 2]
    assert dict(pairs)[1] == _blob([1.0, 0.0])
    conn = sqlite3.connect(memory_db_path, uri=True)
    dims = [row[0] for row in conn.execute("SELECT dim FROM memory_embeddings ORDER BY memory_id")]
    conn.close()
    assert dims == [2, 2]


def test_embeddings_models_coexist_and_replace_within_model(memory_db_path):
    """
    Tests the (memory_id, model) primary key semantics: same-model re-embeds
    replace the row, while other models' vectors are untouched. This is the
    guarantee that switching embedding models never destroys previous work.
    """
    add_embeddings_to_db(TEST_DISCUSSION_ID, [(1, _blob([1.0, 0.0]))], "model-a")
    add_embeddings_to_db(TEST_DISCUSSION_ID, [(1, _blob([0.5, 0.5]))], "model-b")
    add_embeddings_to_db(TEST_DISCUSSION_ID, [(1, _blob([0.0, 1.0]))], "model-a")

    model_a = get_all_embeddings(TEST_DISCUSSION_ID, "model-a")
    model_b = get_all_embeddings(TEST_DISCUSSION_ID, "model-b")

    assert model_a == [(1, _blob([0.0, 1.0]))]
    assert model_b == [(1, _blob([0.5, 0.5]))]


def test_add_embeddings_empty_list_is_no_op(memory_db_path):
    assert add_embeddings_to_db(TEST_DISCUSSION_ID, [], "model-a") == 0


def test_get_memories_without_embeddings(memory_db_path):
    """Tests the lazy-backfill query: only un-embedded memories, oldest first, limited."""
    metadata = json.dumps({"title": "t", "summary": "s", "entities": [], "key_phrases": []})
    for text in ("one", "two", "three"):
        add_memory_to_vector_db(TEST_DISCUSSION_ID, text, metadata)
    add_embeddings_to_db(TEST_DISCUSSION_ID, [(2, _blob([1.0]))], "model-a")

    rows = get_memories_without_embeddings(TEST_DISCUSSION_ID, "model-a", limit=10)
    assert [(row['id'], row['memory_text']) for row in rows] == [(1, "one"), (3, "three")]

    # A different model has no embeddings at all, so everything is a candidate.
    rows_b = get_memories_without_embeddings(TEST_DISCUSSION_ID, "model-b", limit=2)
    assert [row['id'] for row in rows_b] == [1, 2]


def test_get_memories_by_ids_preserves_order_and_skips_missing(memory_db_path):
    metadata = json.dumps({"title": "t", "summary": "s", "entities": [], "key_phrases": []})
    for text in ("one", "two", "three"):
        add_memory_to_vector_db(TEST_DISCUSSION_ID, text, metadata)

    rows = get_memories_by_ids(TEST_DISCUSSION_ID, [3, 99, 1])

    assert [(row['id'], row['memory_text']) for row in rows] == [(3, "three"), (1, "one")]


def test_get_memories_by_ids_empty_input(memory_db_path):
    assert get_memories_by_ids(TEST_DISCUSSION_ID, []) == []


# --- Embedding-store error paths ---
# The embedding tier is best-effort by design: every failure must degrade to an
# empty result / zero count rather than raising into the workflow, and
# connections must be closed (or rolled back) on the way out.

def test_add_embeddings_connection_error(mocker):
    """A failed connection returns 0 rows written and logs the failure."""
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    written = add_embeddings_to_db(TEST_DISCUSSION_ID, [(1, _blob([1.0]))], "model-a")

    assert written == 0
    mock_logger.assert_called_once()
    assert "Failed to add embeddings" in mock_logger.call_args[0][0]


def test_add_embeddings_execution_error_rolls_back(mocker):
    """A write failure rolls back, never commits, closes, and reports 0 rows."""
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_conn.executemany.side_effect = sqlite3.Error("write failed")
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    written = add_embeddings_to_db(TEST_DISCUSSION_ID, [(1, _blob([1.0]))], "model-a")

    assert written == 0
    mock_logger.assert_called_once()
    assert "Failed to add embeddings" in mock_logger.call_args[0][0]
    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    mock_conn.close.assert_called_once()


def test_get_all_embeddings_connection_error(mocker):
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)

    assert get_all_embeddings(TEST_DISCUSSION_ID, "model-a") == []


def test_get_all_embeddings_query_error(mocker):
    """A query failure returns [] (semantic search then degrades to keyword)."""
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_conn.execute.side_effect = sqlite3.Error("query failed")
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    result = get_all_embeddings(TEST_DISCUSSION_ID, "model-a")

    assert result == []
    mock_logger.assert_called_once()
    assert "Failed to get embeddings" in mock_logger.call_args[0][0]
    mock_conn.close.assert_called_once()


def test_get_memories_without_embeddings_connection_error(mocker):
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)

    assert get_memories_without_embeddings(TEST_DISCUSSION_ID, "model-a") == []


def test_get_memories_without_embeddings_query_error(mocker):
    """A query failure returns [] so the lazy backfill silently skips a cycle."""
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_conn.execute.side_effect = sqlite3.Error("query failed")
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    result = get_memories_without_embeddings(TEST_DISCUSSION_ID, "model-a")

    assert result == []
    mock_logger.assert_called_once()
    assert "Failed to get un-embedded memories" in mock_logger.call_args[0][0]
    mock_conn.close.assert_called_once()


def test_get_memories_by_ids_connection_error(mocker):
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=None)

    assert get_memories_by_ids(TEST_DISCUSSION_ID, [1, 2]) == []


def test_get_memories_by_ids_query_error(mocker):
    """A fetch failure returns [] rather than dropping the whole search."""
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_conn.execute.side_effect = sqlite3.Error("query failed")
    mocker.patch("Middleware.utilities.vector_db_utils.get_db_connection", return_value=mock_conn)
    mock_logger = mocker.patch("Middleware.utilities.vector_db_utils.logger.error")

    result = get_memories_by_ids(TEST_DISCUSSION_ID, [1, 2])

    assert result == []
    mock_logger.assert_called_once()
    assert "Failed to get memories by ids" in mock_logger.call_args[0][0]
    mock_conn.close.assert_called_once()
