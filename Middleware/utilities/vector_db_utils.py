# Middleware/utilities/vector_db_utils.py
import datetime
import json
import logging
import math
import os
import sqlite3
from typing import List, Optional

from Middleware.utilities import config_utils

logger = logging.getLogger(__name__)

# This prevents exceeding SQLite's expression depth limit (SQLITE_LIMIT_EXPR_DEPTH).
MAX_KEYWORDS_FOR_SEARCH = 60


def _legacy_vector_db_path(discussion_id: str) -> str:
    """
    Returns the project-root pre-refactor path for the vector memory database.

    Before vector DBs were co-located with other per-discussion files, the old
    code created them via ``os.makedirs('Public')``, a *working-directory-
    relative* ``Public/{discussion_id}_vector_memory.db``. For installs always
    launched from the project root that resolves to
    ``{project_root}/Public/{discussion_id}_vector_memory.db``, which this
    function returns. Installs launched from another working directory have
    their old file elsewhere; :func:`_legacy_vector_db_path_cwd` covers that
    case. Legacy-stickiness logic keeps reading and writing to an existing
    legacy file rather than orphaning it.

    Args:
        discussion_id (str): The unique identifier for the discussion.

    Returns:
        str: The project-root legacy path for the discussion's vector memory database.
    """
    return os.path.join(
        config_utils.get_project_root_directory_path(),
        'Public',
        f'{discussion_id}_vector_memory.db',
    )


def _legacy_vector_db_path_cwd(discussion_id: str) -> str:
    """
    Returns the working-directory-relative pre-refactor path for the vector DB.

    The old code created the database with ``os.makedirs('Public')``, so the
    file resolved against the process's current working directory at the time
    it was first written. When an install was launched from a directory other
    than the project root (e.g. a systemd unit or a launch from the home
    directory, the same scenario that motivated pinning the log directory),
    the legacy file lives at ``{cwd}/Public/{discussion_id}_vector_memory.db``
    rather than under the project root. Probing this candidate avoids silently
    orphaning that data on non-project-root launches.

    Args:
        discussion_id (str): The unique identifier for the discussion.

    Returns:
        str: The cwd-relative legacy path for the discussion's vector memory database.
    """
    return os.path.join(
        os.getcwd(),
        'Public',
        f'{discussion_id}_vector_memory.db',
    )


def _get_db_path(discussion_id: str, api_key_hash: Optional[str] = None) -> str:
    """
    Returns the SQLite database file path for a specific discussion's vector memory.

    The database is now co-located with other per-discussion files inside
    the discussion folder returned by
    :func:`config_utils.get_discussion_folder_path`, at
    ``{discussion_folder}/vector_memory.db``.

    For backwards compatibility, if the database does not yet exist at the
    new location but a pre-refactor legacy file is present, that legacy path
    is returned and continues to be used for that discussion's lifespan. Two
    legacy locations are probed because the old code wrote a
    working-directory-relative ``Public/...`` file: first
    ``{project_root}/Public/{discussion_id}_vector_memory.db`` and then the
    cwd-relative ``{cwd}/Public/{discussion_id}_vector_memory.db`` (these
    coincide only when the process was launched from the project root). No
    automatic migration is performed; to migrate, a user can move the file
    into the discussion folder manually.

    Args:
        discussion_id (str): The unique identifier for the discussion.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation. Passed through to
            :func:`config_utils.get_discussion_folder_path`.

    Returns:
        str: The full path to the discussion-specific SQLite database file.
    """
    discussion_folder = config_utils.get_discussion_folder_path(
        discussion_id, api_key_hash=api_key_hash
    )
    new_path = os.path.join(discussion_folder, 'vector_memory.db')

    if os.path.exists(new_path):
        return new_path

    # The pre-refactor legacy DBs lived in shared, non-isolated 'Public/...' locations
    # that predate per-user directory isolation. Only fall back to them in single-user
    # mode (api_key_hash is None). When per-user isolation is active, reusing a shared
    # legacy file would bleed one user's vector memories into another's, so skip the
    # legacy probes entirely and use the isolated new path.
    if api_key_hash is None:
        project_root_legacy = _legacy_vector_db_path(discussion_id)
        if os.path.exists(project_root_legacy):
            logger.info(
                "Using legacy vector memory database at '%s'. Move the file to '%s' to migrate.",
                project_root_legacy,
                new_path,
            )
            return project_root_legacy

        # The old code wrote a cwd-relative 'Public/...' file; on non-project-root
        # launches this differs from the project-root candidate above. Probe it so
        # an existing user's vector memories are not orphaned by a fresh empty DB.
        cwd_legacy = _legacy_vector_db_path_cwd(discussion_id)
        if os.path.abspath(cwd_legacy) != os.path.abspath(project_root_legacy) and os.path.exists(cwd_legacy):
            logger.info(
                "Using legacy vector memory database at '%s'. Move the file to '%s' to migrate.",
                cwd_legacy,
                new_path,
            )
            return cwd_legacy

    return new_path


def setup_database_functions(connection: sqlite3.Connection, decay_rate: float = 0.01, max_boost: float = 2.5):
    """
    Creates and registers a custom recency_score SQL function on a database connection.

    Args:
        connection (sqlite3.Connection): The active database connection.
        decay_rate (float, optional): The decay rate for the recency calculation. Defaults to 0.01.
        max_boost (float, optional): The maximum score boost for the newest items. Defaults to 2.5.
    """

    def recency_score(date_added_str: str) -> float:
        """Calculates a score based on how many days old a memory is. Newer is higher."""
        try:
            date_added = datetime.datetime.fromisoformat(date_added_str)
            # We rely on datetime.datetime.now(tz) returning an aware object.
            # We explicitly reference the module 'datetime' here so it can be patched in tests.
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            if date_added.tzinfo is None:
                # Assume naive dates are UTC
                date_added_utc = date_added.replace(tzinfo=datetime.timezone.utc)
            else:
                date_added_utc = date_added.astimezone(datetime.timezone.utc)

            # The subtraction requires both datetimes to be aware.
            # A TypeError will be caught if one is naive (e.g., due to incorrect mocking).
            days_old = (now_utc - date_added_utc).total_seconds() / (24 * 3600)

            days_old = max(0.0, days_old)

            return 1.0 + (max_boost - 1.0) * math.exp(-decay_rate * days_old)
        except (ValueError, TypeError) as e:
            now_utc_val = locals().get('now_utc', 'N/A')
            logger.warning(
                f"Error calculating recency score for date '{date_added_str}': {e}. Now_utc value: {now_utc_val}")
            return 1.0  # Neutral boost on error

    # deterministic=False because the result depends on the current time.
    connection.create_function("recency_score", 1, recency_score, deterministic=False)


def get_db_connection(discussion_id: str, api_key_hash: Optional[str] = None) -> Optional[sqlite3.Connection]:
    """
    Establishes a connection to a discussion-specific SQLite database.
    Handles both standard file paths and SQLite URIs (e.g., for testing).

    Args:
        discussion_id (str): The unique identifier for the discussion.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation. Forwarded to the path resolver so
            the database lands in the correct per-user discussion folder.

    Returns:
        Optional[sqlite3.Connection]: A database connection object if successful, otherwise None.
    """
    db_path = _get_db_path(discussion_id, api_key_hash=api_key_hash)
    is_uri = db_path.startswith("file:")

    try:
        conn = sqlite3.connect(db_path, check_same_thread=False, uri=is_uri)
        conn.row_factory = sqlite3.Row
        setup_database_functions(conn)
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error for {discussion_id} at path {db_path}: {e}")
        return None


def initialize_vector_db(discussion_id: str, api_key_hash: Optional[str] = None):
    """
    Initializes the necessary tables for vector memory in a discussion's database.

    Args:
        discussion_id (str): The unique identifier for the discussion whose database needs initialization.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        logger.error(f"Failed to initialize vector DB for '{discussion_id}': Could not connect to database.")
        return

    try:
        # Main table to store the ground truth for each memory.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                discussion_id TEXT NOT NULL,
                memory_text TEXT NOT NULL,
                date_added TEXT NOT NULL,
                metadata_json TEXT
            );
        ''')
        # FTS5 virtual table for indexing and searching.
        conn.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                title,
                summary,
                entities,
                key_phrases,
                memory_text_unweighted,
                tokenize='porter'
            );
        ''')
        # Table to track the last processed message hash.
        # Using DATETIME type for timestamp storage.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS vector_memory_hash_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discussion_id TEXT NOT NULL,
                message_hash TEXT NOT NULL,
                timestamp DATETIME NOT NULL
            );
        ''')
        # Optional embedding store for semantic/hybrid search. Purely additive:
        # pre-embedding databases gain this empty table on their next open and
        # behave exactly as before until embeddings are written. The composite
        # primary key lets vectors from multiple embedding models coexist, so
        # switching models never destroys previous vectors and switching back
        # requires no recompute. Embeddings are derived data: every vector is
        # recomputable from memories.memory_text.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                PRIMARY KEY (memory_id, model)
            );
        ''')
        conn.commit()
        logger.info(f"Vector memory database for discussion '{discussion_id}' initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize vector DB for '{discussion_id}': {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


def add_memory_to_vector_db(discussion_id: str, memory_text: str, metadata_json_str: str,
                            api_key_hash: Optional[str] = None,
                            index_topics: bool = False) -> Optional[int]:
    """
    Adds a new memory and its FTS index entry to the database in a transaction.

    Args:
        discussion_id (str): The identifier for the discussion to add the memory to.
        memory_text (str): The core text of the memory (e.g., LLM summary).
        metadata_json_str (str): A JSON string containing metadata like title, summary, entities, etc.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.
        index_topics (bool, optional): If True, the metadata's 'topics' list is
            folded into the key_phrases FTS column so topic terms are keyword
            searchable. Defaults to False, which indexes exactly the columns
            the historical behavior indexed.

    Returns:
        Optional[int]: The new memory's id on success, or None on failure.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        logger.error(f"Failed to add memory for '{discussion_id}': Could not connect to database.")
        return None

    try:
        # Parse metadata first to fail fast before any database writes.
        metadata = json.loads(metadata_json_str)

        cursor = conn.cursor()
        date_added = datetime.datetime.now(datetime.timezone.utc).isoformat()

        cursor.execute(
            'INSERT INTO memories (discussion_id, memory_text, date_added, metadata_json) VALUES (?, ?, ?, ?)',
            (discussion_id, memory_text, date_added, metadata_json_str)
        )
        memory_id = cursor.lastrowid

        def format_for_fts(data):
            """Helper to format metadata fields (especially lists) for FTS indexing."""
            if isinstance(data, list):
                # Join list items with spaces, removing internal quotes to prevent FTS syntax issues
                return ' '.join(str(item).replace('"', '') for item in data)
            return data if data else ''

        title = metadata.get('title', '')
        summary = metadata.get('summary', '')
        entities = format_for_fts(metadata.get('entities', []))
        key_phrases = format_for_fts(metadata.get('key_phrases', []))
        if index_topics:
            # Topics often carry the conversation-level context (e.g. the group
            # or activity a fact belongs to) that the memory body omits; folding
            # them into the existing key_phrases column makes them searchable
            # without an FTS schema change.
            topics = format_for_fts(metadata.get('topics', []))
            if topics:
                key_phrases = f"{key_phrases} {topics}".strip()

        cursor.execute(
            '''
            INSERT INTO memories_fts (rowid, title, summary, entities, key_phrases, memory_text_unweighted)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (memory_id, title, summary, entities, key_phrases, memory_text)
        )

        conn.commit()
        logger.debug(f"Added vector memory for discussion_id {discussion_id} with memory_id {memory_id}")
        return memory_id

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse metadata JSON: {e}. Content: {metadata_json_str}")
        return None
    except Exception as e:
        logger.error(f"Failed to add memory to vector DB for '{discussion_id}': {e}", exc_info=True)
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()


def _sanitize_fts5_term(term: str) -> str:
    """
    Sanitizes a single search term for an FTS5 MATCH query.

    Wraps the term in double quotes to treat it as a literal phrase and
    escapes any internal double quotes. This prevents syntax errors from
    user input containing FTS5 operators.

    Args:
        term (str): The raw search term from user input.

    Returns:
        str: A sanitized search term safe for FTS5 queries.
    """
    term = term.replace('-', ' ')
    sanitized_term = term.strip().replace('"', '""')
    return f'"{sanitized_term}"'


def search_memories_by_keyword(discussion_id: str, search_query: str, limit: int = 15,
                                api_key_hash: Optional[str] = None,
                                bm25_weights: Optional[List[float]] = None,
                                use_recency: bool = False) -> List[sqlite3.Row]:
    """
    Searches memories using the FTS index in the discussion-specific database.

    The search query is a semicolon-delimited string of keywords. Results are
    ranked by the BM25 algorithm, optionally with per-column weights and a
    recency boost. Both options default to off, preserving the historical
    equal-weight, pure-BM25 ranking for existing configurations.

    Args:
        discussion_id (str): The identifier for the discussion to search within.
        search_query (str): A string of keywords separated by semicolons.
        limit (int, optional): The maximum number of results to return. Defaults to 15.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.
        bm25_weights (List[float], optional): Exactly five column weights for
            BM25, in FTS column order: title, summary, entities, key_phrases,
            memory_text_unweighted. Invalid values are logged and ignored.
        use_recency (bool, optional): If True, multiplies the BM25 rank by the
            connection's registered recency_score() of each memory's date_added,
            boosting newer memories. Defaults to False.

    Returns:
        List[sqlite3.Row]: A list of database rows matching the search query, ordered by relevance.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        return []

    try:
        cursor = conn.cursor()

        keywords = [k.strip() for k in search_query.split(';') if k.strip()]
        if not keywords:
            return []

        if len(keywords) > MAX_KEYWORDS_FOR_SEARCH:
            logger.warning(
                f"Received {len(keywords)} keywords. Truncating to the first {MAX_KEYWORDS_FOR_SEARCH} to prevent SQLite query complexity errors."
            )
            keywords = keywords[:MAX_KEYWORDS_FOR_SEARCH]

        sanitized_terms = [_sanitize_fts5_term(k) for k in keywords]
        final_query = ' OR '.join(sanitized_terms)

        rank_expr = "bm25(memories_fts)"
        rank_params: List[float] = []
        if bm25_weights is not None:
            if (isinstance(bm25_weights, (list, tuple)) and len(bm25_weights) == 5
                    and all(isinstance(w, (int, float)) and not isinstance(w, bool) for w in bm25_weights)):
                rank_expr = "bm25(memories_fts, ?, ?, ?, ?, ?)"
                rank_params = [float(w) for w in bm25_weights]
            else:
                logger.warning(
                    "bm25_weights must be a list of exactly 5 numbers "
                    "(title, summary, entities, key_phrases, memory_text). Ignoring: %s",
                    bm25_weights)

        # BM25 in FTS5 returns negative scores (more negative = better match), so
        # multiplying by a recency boost > 1 makes newer matches rank higher under
        # ORDER BY ... ASC. The full rank expression is repeated in ORDER BY (with
        # its parameters bound a second time) rather than referencing the alias,
        # because SQLite only reliably resolves aliases as bare ORDER BY terms.
        if use_recency:
            order_expr = f"{rank_expr} * recency_score(m.date_added)"
            order_params = list(rank_params)
        else:
            order_expr = "rank"
            order_params = []

        sql_query = f"""
            SELECT
                m.*,
                {rank_expr} AS rank
            FROM memories_fts AS fts
            JOIN memories AS m ON fts.rowid = m.id
            WHERE memories_fts MATCH ?
            ORDER BY {order_expr} ASC
            LIMIT ?
        """
        cursor.execute(sql_query, (*rank_params, final_query, *order_params, limit))
        return cursor.fetchall()

    except Exception as e:
        logger.error(f"Failed to search memories in DB for '{discussion_id}': {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


def get_vector_check_hash_history(discussion_id: str, limit: int = 10,
                                   api_key_hash: Optional[str] = None) -> List[str]:
    """
    Retrieves a list of the most recent message hashes from the log.

    Args:
        discussion_id (str): The identifier for the discussion.
        limit (int): The maximum number of recent hashes to retrieve.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.

    Returns:
        List[str]: A list of message hashes, ordered from most recent to oldest.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT message_hash FROM vector_memory_hash_log
            WHERE discussion_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            ''',
            (discussion_id, limit)
        )
        return [row['message_hash'] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get vector check hash history for {discussion_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()


def add_embeddings_to_db(discussion_id: str, embeddings: List[tuple], model: str,
                         api_key_hash: Optional[str] = None) -> int:
    """
    Stores embedding vectors for memories, replacing same-model rows.

    Uses INSERT OR REPLACE keyed on (memory_id, model): re-embedding a memory
    under the same model updates its row, while vectors from other models are
    left untouched so a model switch never destroys previous work.

    Args:
        discussion_id (str): The identifier for the discussion.
        embeddings (List[tuple]): (memory_id, vector_blob) pairs, where
            vector_blob is the float32 bytes from vector_math_utils.vector_to_blob
            and dim is inferred from the blob length.
        model (str): The embedding model name the vectors were produced with.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.

    Returns:
        int: The number of rows written.
    """
    if not embeddings:
        return 0

    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        logger.error(f"Failed to add embeddings for '{discussion_id}': Could not connect to database.")
        return 0

    try:
        # Each float32 is 4 bytes.
        rows = [(memory_id, model, len(blob) // 4, blob) for memory_id, blob in embeddings]
        conn.executemany(
            'INSERT OR REPLACE INTO memory_embeddings (memory_id, model, dim, vector) VALUES (?, ?, ?, ?)',
            rows)
        conn.commit()
        logger.debug(f"Stored {len(rows)} embedding(s) for discussion {discussion_id} (model '{model}').")
        return len(rows)
    except Exception as e:
        logger.error(f"Failed to add embeddings for '{discussion_id}': {e}", exc_info=True)
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()


def get_all_embeddings(discussion_id: str, model: str,
                       api_key_hash: Optional[str] = None) -> List[tuple]:
    """
    Retrieves all stored embedding blobs for one model.

    Args:
        discussion_id (str): The identifier for the discussion.
        model (str): The embedding model name to filter on. Vectors from other
            models are never compared against this model's query vectors.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.

    Returns:
        List[tuple]: (memory_id, vector_blob) pairs.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        return []

    try:
        cursor = conn.execute(
            'SELECT memory_id, vector FROM memory_embeddings WHERE model = ?', (model,))
        return [(row['memory_id'], row['vector']) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get embeddings for '{discussion_id}': {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


def get_memories_without_embeddings(discussion_id: str, model: str, limit: int = 20,
                                    api_key_hash: Optional[str] = None) -> List[sqlite3.Row]:
    """
    Retrieves memories that have no stored embedding for the given model.

    Used by the lazy backfill: each write cycle embeds a small batch of older
    memories so a pre-embedding database heals over time without a bulk job.

    Args:
        discussion_id (str): The identifier for the discussion.
        model (str): The embedding model name to check against.
        limit (int, optional): Maximum number of rows to return. Defaults to 20.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.

    Returns:
        List[sqlite3.Row]: Rows with 'id' and 'memory_text', oldest first.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        return []

    try:
        cursor = conn.execute(
            '''
            SELECT id, memory_text FROM memories
            WHERE id NOT IN (SELECT memory_id FROM memory_embeddings WHERE model = ?)
            ORDER BY id ASC
            LIMIT ?
            ''', (model, limit))
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Failed to get un-embedded memories for '{discussion_id}': {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


def get_memories_by_ids(discussion_id: str, memory_ids: List[int],
                        api_key_hash: Optional[str] = None) -> List[sqlite3.Row]:
    """
    Retrieves memory rows by id, preserving the order of the id list.

    Args:
        discussion_id (str): The identifier for the discussion.
        memory_ids (List[int]): The memory ids to fetch, in desired output order.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.

    Returns:
        List[sqlite3.Row]: The matching rows, ordered to match memory_ids.
    """
    if not memory_ids:
        return []

    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        return []

    try:
        placeholders = ','.join('?' * len(memory_ids))
        cursor = conn.execute(
            f'SELECT * FROM memories WHERE id IN ({placeholders})', memory_ids)
        rows_by_id = {row['id']: row for row in cursor.fetchall()}
        return [rows_by_id[mid] for mid in memory_ids if mid in rows_by_id]
    except Exception as e:
        logger.error(f"Failed to get memories by ids for '{discussion_id}': {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


def add_vector_check_hash(discussion_id: str, message_hash: str,
                          api_key_hash: Optional[str] = None):
    """
    Adds a new processed message hash to the historical log in a transaction.

    Args:
        discussion_id (str): The identifier for the discussion.
        message_hash (str): The new hash of the last message processed.
        api_key_hash (str, optional): A 16-char hex hash of the API key for
            per-user directory isolation.
    """
    conn = get_db_connection(discussion_id, api_key_hash=api_key_hash)
    if conn is None:
        return

    try:
        timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn.execute(
            '''
            INSERT INTO vector_memory_hash_log (discussion_id, message_hash, timestamp)
            VALUES (?, ?, ?)
            ''',
            (discussion_id, message_hash, timestamp_iso)
        )
        conn.commit()
        logger.debug(f"Added new vector check hash to log for {discussion_id}")
    except Exception as e:
        logger.error(f"Failed to add vector check hash for {discussion_id}: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
