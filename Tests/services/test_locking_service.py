# Tests/services/test_locking_service.py

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
    """Mocks os-level functions to prevent any real filesystem access."""
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
        LockingService()
        mock_makedirs.assert_called_once_with(FAKE_DB_PATH)

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
        ({}, "", []),
    ])
    def test_delete_node_locks(self, locking_service, mock_sqlite3, params, expected_where, expected_params):
        """Tests that locks are deleted with the correct dynamically generated SQL query."""
        _, _, mock_cursor = mock_sqlite3

        mock_cursor.reset_mock()

        locking_service.delete_node_locks(**params)
        expected_query = f'DELETE FROM {locking_service.TABLE_NAME} WHERE 1=1{expected_where}'
        mock_cursor.execute.assert_called_once_with(expected_query, expected_params)

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
