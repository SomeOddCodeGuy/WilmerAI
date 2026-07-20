import os
import sqlite3
import textwrap
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from Middleware.services.locking_service import LockingService

# Common test data used across multiple tests
FAKE_USERNAME = "test_user"
FAKE_SESSION_ID = "session-12345"
FAKE_WORKFLOW_ID = "workflow-abcde"
FAKE_LOCK_ID = "MyCustomLockID"
FAKE_DB_PATH = "/mock/db/path"


def _unindent_sql(s: str) -> str:
    """Removes common leading whitespace from a triple-quoted SQL string."""
    return textwrap.dedent(s)


@pytest.fixture
def mock_sqlite3(mocker):
    """Mocks the entire sqlite3 module to prevent actual database interaction."""
    mock_connect = mocker.patch('sqlite3.connect')
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_cursor = MagicMock(spec=sqlite3.Cursor)
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    return mock_connect, mock_conn, mock_cursor


@pytest.fixture
def mock_config_utils(mocker):
    """Mocks all required functions from the config_utils module to isolate the service."""
    mocker.patch('Middleware.services.locking_service.config_utils.get_current_username', return_value=FAKE_USERNAME)
    mocker.patch('Middleware.services.locking_service.config_utils.get_custom_dblite_filepath',
                 return_value=FAKE_DB_PATH)


@pytest.fixture
def mock_os_utils(mocker):
    """Mocks os-level functions to prevent any real filesystem access.

    By default, the target database file is reported as existing (so
    _get_db_path returns the target path directly and legacy stickiness is
    skipped). Tests that exercise the legacy-path branch patch os.path.exists
    themselves.
    """
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('os.makedirs')
    mocker.patch('os.path.dirname', return_value=FAKE_DB_PATH)


@pytest.fixture
def mock_datetime(mocker):
    """Mocks datetime.now() to return a fixed, predictable point in time."""
    frozen_time = datetime(2025, 1, 1, 12, 0, 0)
    # Patch the datetime class within the locking_service module's namespace
    mock_dt = mocker.patch('Middleware.services.locking_service.datetime')
    mock_dt.now.return_value = frozen_time
    mock_dt.fromisoformat.side_effect = lambda ts: datetime.fromisoformat(ts)
    return frozen_time


@pytest.fixture
def locking_service(mock_config_utils, mock_os_utils, mock_sqlite3, mock_datetime):
    """
    Provides a fully mocked LockingService instance for use in tests.
    This fixture ensures all dependencies are mocked before the service is instantiated.
    """
    return LockingService()


class TestLockingService:
    """Test suite for the LockingService."""

    def test_initialization(self, locking_service, mock_sqlite3):
        """Tests that the service initializes correctly, sets up the DB path, and creates the table."""
        mock_connect, mock_conn, mock_cursor = mock_sqlite3
        assert locking_service.username == FAKE_USERNAME
        assert locking_service.db_path == os.path.join(FAKE_DB_PATH, f'WilmerDb.{FAKE_USERNAME}.sqlite')
        mock_connect.assert_called_with(locking_service.db_path)

        expected_create_sql = _unindent_sql(f'''
            CREATE TABLE IF NOT EXISTS {LockingService.TABLE_NAME} (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                WilmerSessionId NVARCHAR(50),
                WorkflowId NVARCHAR(50),
                WorkflowLockId NVARCHAR(500),
                ExpirationDate DATETIME
            )
        ''')
        mock_cursor.execute.assert_called_once_with(expected_create_sql)
        mock_conn.commit.assert_called_once()

    def test_initialization_creates_directory(self, mock_config_utils, mock_sqlite3, mocker):
        """Tests that the service creates the database directory if it doesn't exist."""
        mocker.patch('os.path.exists', return_value=False)
        mock_makedirs = mocker.patch('os.makedirs')
        mocker.patch('os.path.dirname', return_value=FAKE_DB_PATH)
        LockingService()
        mock_makedirs.assert_called_once_with(FAKE_DB_PATH)

    def test_legacy_db_path_stickiness(self, mock_config_utils, mock_sqlite3, mocker):
        """If a legacy database exists at cwd but not at the target path, the legacy path is used."""
        target_path = os.path.join(FAKE_DB_PATH, f'WilmerDb.{FAKE_USERNAME}.sqlite')
        legacy_path = f'WilmerDb.{FAKE_USERNAME}.sqlite'

        def exists(path):
            return path == legacy_path

        mocker.patch('os.path.exists', side_effect=exists)
        mocker.patch('os.makedirs')
        mocker.patch('os.path.dirname', return_value='')
        service = LockingService()
        assert service.db_path == legacy_path
        assert service.db_path != target_path

    def test_project_root_legacy_db_path_stickiness(self, mock_config_utils, mock_sqlite3, mocker):
        """If the old lock DB lives at the project root (a non-project-root launch),
        it is found via the project-root legacy candidate instead of being orphaned."""
        fake_project_root = "/mock/project/root"
        mocker.patch(
            'Middleware.services.locking_service.config_utils.get_project_root_directory_path',
            return_value=fake_project_root,
        )
        project_root_legacy = os.path.join(fake_project_root, f'WilmerDb.{FAKE_USERNAME}.sqlite')

        def exists(path):
            return path == project_root_legacy

        mocker.patch('os.path.exists', side_effect=exists)
        mocker.patch('os.makedirs')
        mocker.patch('os.path.dirname', return_value=fake_project_root)
        service = LockingService()
        assert service.db_path == project_root_legacy

    def test_new_db_path_preferred_when_both_exist(self, mock_config_utils, mock_sqlite3, mocker):
        """If both paths exist, the target path is used (legacy only kicks in when target is missing)."""
        target_path = os.path.join(FAKE_DB_PATH, f'WilmerDb.{FAKE_USERNAME}.sqlite')
        mocker.patch('os.path.exists', return_value=True)
        mocker.patch('os.makedirs')
        mocker.patch('os.path.dirname', return_value=FAKE_DB_PATH)
        service = LockingService()
        assert service.db_path == target_path

    def test_get_db_connection_failure(self, locking_service, mock_sqlite3, caplog):
        """Tests that a database connection failure is logged gracefully."""
        mock_connect, _, _ = mock_sqlite3
        mock_connect.side_effect = sqlite3.OperationalError("cannot connect")
        conn = locking_service._get_db_connection()
        assert conn is None
        assert "Failed to connect to database" in caplog.text

    def test_create_node_lock(self, locking_service, mock_sqlite3, mock_datetime):
        """Verifies a lock is correctly inserted into the database."""
        _, mock_conn, mock_cursor = mock_sqlite3
        expected_expiration = mock_datetime + timedelta(minutes=10)

        mock_cursor.reset_mock()

        locking_service.create_node_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID)

        insert_query = _unindent_sql(f'''
                INSERT INTO {LockingService.TABLE_NAME}
                (WilmerSessionId, WorkflowId, WorkflowLockId, ExpirationDate)
                VALUES (?, ?, ?, ?)
            ''')
        mock_cursor.execute.assert_called_once_with(
            insert_query,
            (FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID, expected_expiration)
        )
        mock_conn.commit.assert_called()

    @pytest.mark.parametrize("params, expected_where, expected_params", [
        ({"workflow_lock_id": "lock1"}, " AND WorkflowLockId = ?", ["lock1"]),
        ({"workflow_id": "wf1"}, " AND WorkflowId = ?", ["wf1"]),
        ({"wilmer_session_id": "sess1"}, " AND WilmerSessionId = ?", ["sess1"]),
        ({"workflow_id": "wf1", "workflow_lock_id": "lock1"},
         " AND WorkflowId = ? AND WorkflowLockId = ?", ["wf1", "lock1"]),
    ])
    def test_delete_node_locks(self, locking_service, mock_sqlite3, params, expected_where, expected_params):
        """Tests that locks are deleted with the correct dynamically generated SQL query."""
        _, _, mock_cursor = mock_sqlite3

        mock_cursor.reset_mock()

        locking_service.delete_node_locks(**params)
        expected_query = f'DELETE FROM {locking_service.TABLE_NAME} WHERE 1=1{expected_where}'
        mock_cursor.execute.assert_called_once_with(expected_query, expected_params)

    def test_delete_node_locks_no_criteria_is_noop(self, locking_service, mock_sqlite3):
        """Tests that calling delete_node_locks with no criteria is a safe no-op."""
        _, _, mock_cursor = mock_sqlite3
        mock_cursor.reset_mock()

        locking_service.delete_node_locks()
        mock_cursor.execute.assert_not_called()

    def test_get_lock_exists_and_is_valid(self, locking_service, mock_sqlite3, mock_datetime):
        """Tests checking for a lock that exists and is not expired."""
        _, _, mock_cursor = mock_sqlite3
        future_expiration = (mock_datetime + timedelta(minutes=5)).isoformat()
        mock_cursor.fetchone.return_value = (future_expiration,)
        assert locking_service.get_lock(FAKE_LOCK_ID) is True

    def test_get_lock_is_expired(self, locking_service, mock_sqlite3, mock_datetime, mocker):
        """Tests checking an expired lock, which should be deleted and return False."""
        _, _, mock_cursor = mock_sqlite3
        past_expiration = (mock_datetime - timedelta(minutes=5)).isoformat()
        mock_cursor.fetchone.return_value = (past_expiration,)
        mock_delete = mocker.patch.object(locking_service, 'delete_node_locks')
        assert locking_service.get_lock(FAKE_LOCK_ID) is False
        mock_delete.assert_called_once_with(workflow_lock_id=FAKE_LOCK_ID)

    def test_get_lock_does_not_exist(self, locking_service, mock_sqlite3):
        """Tests checking for a lock that does not exist."""
        _, _, mock_cursor = mock_sqlite3
        mock_cursor.fetchone.return_value = None
        assert locking_service.get_lock(FAKE_LOCK_ID) is False

    def test_delete_old_locks(self, locking_service, mock_sqlite3):
        """Verifies that stale locks from previous sessions are deleted."""
        _, _, mock_cursor = mock_sqlite3
        current_session_id = "new-session-id"

        mock_cursor.reset_mock()

        locking_service.delete_old_locks(current_session_id)

        delete_query = _unindent_sql(f'''
                    DELETE FROM {LockingService.TABLE_NAME}
                    WHERE WilmerSessionId != ?
                ''')
        mock_cursor.execute.assert_called_once_with(delete_query, (current_session_id,))

    @pytest.mark.parametrize("method_name, args, expected", [
        ("create_node_lock", (FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID), None),
        ("get_lock", (FAKE_LOCK_ID,), False),
        ("delete_node_locks", (FAKE_SESSION_ID,), None),
        ("delete_old_locks", (FAKE_SESSION_ID,), None),
    ])
    def test_public_methods_handle_failed_connection(self, locking_service, mocker, caplog,
                                                     method_name, args, expected):
        """Each public method degrades gracefully when _get_db_connection returns None:
        create_node_lock logs and returns, get_lock returns False, and the delete
        methods silently swallow the failure."""
        mocker.patch.object(locking_service, '_get_db_connection', return_value=None)

        result = getattr(locking_service, method_name)(*args)

        assert result is expected
        if method_name == "create_node_lock":
            assert "Cannot create node lock" in caplog.text

    def test_get_lock_reraises_db_error(self, locking_service, mock_sqlite3):
        """A database error inside get_lock is re-raised after the connection is closed."""
        _, mock_conn, mock_cursor = mock_sqlite3
        mock_conn.close.reset_mock()
        mock_cursor.execute.side_effect = sqlite3.OperationalError("disk I/O error")

        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            locking_service.get_lock(FAKE_LOCK_ID)

        mock_conn.close.assert_called_once()


class _NonClosingConnection:
    """Proxy over a real sqlite3 connection whose close() is a no-op.

    LockingService closes its connection after every operation, which would
    destroy a plain ':memory:' database; the proxy keeps the single in-memory
    database alive across calls while forwarding everything else.
    """

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        # Forward attribute assignment (e.g. isolation_level) to the real
        # connection so the proxy is transparent for transaction control.
        if name == "_conn":
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)


@pytest.fixture
def in_memory_locking_service(mocker):
    """Provides a LockingService backed by a real in-memory SQLite database."""
    mocker.patch('Middleware.services.locking_service.config_utils.get_current_username',
                 return_value=FAKE_USERNAME)
    mocker.patch('Middleware.services.locking_service.config_utils.get_custom_dblite_filepath',
                 return_value=FAKE_DB_PATH)
    # Report the DB directory as existing so no real directories or files are created.
    mocker.patch('os.path.exists', return_value=True)
    real_conn = sqlite3.connect(":memory:")
    mocker.patch.object(LockingService, '_get_db_connection',
                        return_value=_NonClosingConnection(real_conn))
    service = LockingService()
    yield service, real_conn
    real_conn.close()


class TestLockingServiceRealSql:
    """Round-trip tests against a real in-memory SQLite database, proving the
    generated SQL is valid end to end (the mocked suite above never executes it)."""

    def test_lock_round_trip(self, in_memory_locking_service):
        """create -> get True -> delete -> get False against real SQL."""
        service, _ = in_memory_locking_service

        assert service.get_lock(FAKE_LOCK_ID) is False

        service.create_node_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID)
        assert service.get_lock(FAKE_LOCK_ID) is True

        service.delete_node_locks(workflow_lock_id=FAKE_LOCK_ID)
        assert service.get_lock(FAKE_LOCK_ID) is False

    def test_expired_lock_returns_false_and_row_is_deleted(self, in_memory_locking_service, mocker):
        """An expired lock reads as False and its row is removed from the table."""
        service, real_conn = in_memory_locking_service
        creation_time = datetime(2025, 1, 1, 12, 0, 0)
        mock_dt = mocker.patch('Middleware.services.locking_service.datetime')
        mock_dt.now.return_value = creation_time
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat

        service.create_node_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID)

        # Advance past the stored 10-minute expiration.
        mock_dt.now.return_value = creation_time + timedelta(hours=1)
        assert service.get_lock(FAKE_LOCK_ID) is False

        row_count = real_conn.execute(
            f'SELECT COUNT(*) FROM {LockingService.TABLE_NAME} WHERE WorkflowLockId = ?',
            (FAKE_LOCK_ID,)
        ).fetchone()[0]
        assert row_count == 0

    def _row_count(self, real_conn):
        return real_conn.execute(
            f'SELECT COUNT(*) FROM {LockingService.TABLE_NAME} WHERE WorkflowLockId = ?',
            (FAKE_LOCK_ID,)
        ).fetchone()[0]

    def test_acquire_lock_when_free_inserts_and_returns_true(self, in_memory_locking_service):
        """A free lock is acquired atomically: returns True and inserts exactly one row."""
        service, real_conn = in_memory_locking_service

        assert service.acquire_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID) is True
        assert self._row_count(real_conn) == 1
        assert service.get_lock(FAKE_LOCK_ID) is True

    def test_acquire_lock_when_held_returns_false_without_duplicate(self, in_memory_locking_service):
        """A second acquisition of a live lock is refused and does not insert a duplicate row."""
        service, real_conn = in_memory_locking_service

        assert service.acquire_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID) is True
        assert service.acquire_lock("other-session", "other-workflow", FAKE_LOCK_ID) is False
        assert self._row_count(real_conn) == 1

    def test_acquire_lock_reclaims_only_expired_row(self, in_memory_locking_service, mocker):
        """An expired lock is reclaimed (its row replaced), leaving a single live lock."""
        service, real_conn = in_memory_locking_service
        creation_time = datetime(2025, 1, 1, 12, 0, 0)
        mock_dt = mocker.patch('Middleware.services.locking_service.datetime')
        mock_dt.now.return_value = creation_time
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat

        assert service.acquire_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID) is True

        # Advance past the 10-minute expiration; the stale row must be reclaimable.
        mock_dt.now.return_value = creation_time + timedelta(hours=1)
        assert service.acquire_lock("new-session", "new-workflow", FAKE_LOCK_ID) is True
        assert self._row_count(real_conn) == 1

    def test_acquire_lock_proceeds_when_db_unavailable(self, in_memory_locking_service, mocker):
        """If the database cannot be opened, acquisition proceeds (returns True) as before."""
        service, _ = in_memory_locking_service
        mocker.patch.object(service, '_get_db_connection', return_value=None)
        assert service.acquire_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID) is True

    def test_delete_old_locks_removes_only_other_sessions(self, in_memory_locking_service):
        """delete_old_locks removes rows from other sessions and keeps the current one."""
        service, real_conn = in_memory_locking_service
        service.create_node_lock("old-session", FAKE_WORKFLOW_ID, "old-lock")
        service.create_node_lock("current-session", FAKE_WORKFLOW_ID, "current-lock")

        service.delete_old_locks("current-session")

        rows = real_conn.execute(
            f'SELECT WilmerSessionId, WorkflowLockId FROM {LockingService.TABLE_NAME}'
        ).fetchall()
        assert rows == [("current-session", "current-lock")]

    def test_delete_node_locks_filters_by_workflow_id(self, in_memory_locking_service):
        """Deleting by workflow_id removes only that workflow's rows against real SQL."""
        service, real_conn = in_memory_locking_service
        service.create_node_lock(FAKE_SESSION_ID, "wf-A", "lock-A")
        service.create_node_lock(FAKE_SESSION_ID, "wf-B", "lock-B")

        service.delete_node_locks(workflow_id="wf-A")

        rows = real_conn.execute(
            f'SELECT WorkflowId, WorkflowLockId FROM {LockingService.TABLE_NAME}'
        ).fetchall()
        assert rows == [("wf-B", "lock-B")]
        assert service.get_lock("lock-A") is False
        assert service.get_lock("lock-B") is True


class TestLockingServiceErrorPaths:
    """Real-SQL coverage of the three exception handlers (the previously uncovered
    statements). Errors are induced by dropping the table so the next execute()
    raises a genuine sqlite3.OperationalError inside each method's try block."""

    def _drop_table(self, real_conn):
        real_conn.execute(f'DROP TABLE {LockingService.TABLE_NAME}')

    def test_delete_node_locks_swallows_db_error(self, in_memory_locking_service, caplog):
        """A DB error inside delete_node_locks is swallowed with the documented warning."""
        service, real_conn = in_memory_locking_service
        self._drop_table(real_conn)

        with caplog.at_level("WARNING"):
            service.delete_node_locks(workflow_lock_id=FAKE_LOCK_ID)  # must not raise

        assert "Error unlocking locks" in caplog.text

    def test_delete_old_locks_swallows_db_error(self, in_memory_locking_service, caplog):
        """A DB error inside delete_old_locks is swallowed with the documented warning."""
        service, real_conn = in_memory_locking_service
        self._drop_table(real_conn)

        with caplog.at_level("WARNING"):
            service.delete_old_locks(FAKE_SESSION_ID)  # must not raise

        assert "Error deleting old locks" in caplog.text

    def test_acquire_lock_db_error_rolls_back_and_reraises(self, in_memory_locking_service):
        """A failure inside the BEGIN IMMEDIATE transaction is rolled back and re-raised,
        leaving no dangling transaction on the connection."""
        service, real_conn = in_memory_locking_service
        self._drop_table(real_conn)

        with pytest.raises(sqlite3.OperationalError):
            service.acquire_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID)

        assert real_conn.in_transaction is False

    def test_acquire_lock_busy_database_reports_lock_held(self, in_memory_locking_service, mocker, caplog):
        """A write lock held by another connection past the busy timeout raises
        OperationalError from BEGIN IMMEDIATE; that must degrade to "lock held"
        (False) rather than crash the workflow."""
        service, _ = in_memory_locking_service
        busy_conn = mocker.MagicMock()
        busy_conn.cursor.return_value.execute.side_effect = sqlite3.OperationalError("database is locked")
        mocker.patch.object(LockingService, '_get_db_connection', return_value=busy_conn)

        with caplog.at_level("WARNING"):
            assert service.acquire_lock(FAKE_SESSION_ID, FAKE_WORKFLOW_ID, FAKE_LOCK_ID) is False

        assert "busy" in caplog.text
        busy_conn.close.assert_called_once()
