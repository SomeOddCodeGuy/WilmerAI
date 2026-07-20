# /Middleware/services/locking_service.py

import logging
import os
import sqlite3
import textwrap
import traceback
from datetime import datetime, timedelta
from typing import Optional

from Middleware.utilities import config_utils

logger = logging.getLogger(__name__)


class LockingService:
    """
    A service to manage workflow locks using a SQLite database.

    This service centralizes the logic for creating, checking, and deleting locks
    to prevent concurrent execution of specific workflows or nodes. It uses a
    SQLite database file specific to the current user to store lock information.
    """
    TABLE_NAME = 'WorkflowLocks'

    def __init__(self):
        """
        Initializes the LockingService.

        The constructor determines the database file path based on the current user
        and initializes the database, ensuring the necessary table exists.
        """
        self.username = config_utils.get_current_username()
        self.db_path = self._get_db_path()
        self._initialize_database()

    def _get_db_path(self) -> str:
        """
        Determines the full path for the user-specific database file.

        Resolves the target directory via
        :func:`config_utils.get_custom_dblite_filepath` (which applies the
        CLI flag > user config > ``{get_root_public_directory()}/SqlLiteDBs``
        hierarchy), then applies legacy-path stickiness: if the database
        does not yet exist at the target location but a pre-refactor database
        file exists, that legacy file is used instead so no automatic
        migration is performed. The old code created the lock DB as a
        working-directory-relative ``WilmerDb.<user>.sqlite``, so two legacy
        locations are probed (the cwd-relative path and the project-root
        path) because an install launched from a directory other than the
        project root left its old file under whichever directory it was
        launched from.

        Returns:
            str: The full file path for the SQLite database.
        """
        db_filename = f'WilmerDb.{self.username}.sqlite'
        target_dir = config_utils.get_custom_dblite_filepath()
        target_path = os.path.join(target_dir, db_filename) if target_dir else db_filename

        if os.path.exists(target_path):
            return target_path

        cwd_legacy_path = db_filename
        project_root_legacy_path = os.path.join(
            config_utils.get_project_root_directory_path(), db_filename
        )
        for legacy_path in (cwd_legacy_path, project_root_legacy_path):
            if os.path.exists(legacy_path):
                logger.info(
                    "Using legacy lock database at '%s'. Move the file to '%s' to migrate.",
                    os.path.abspath(legacy_path),
                    os.path.abspath(target_path),
                )
                return legacy_path

        return target_path

    def _get_db_connection(self) -> Optional[sqlite3.Connection]:
        """
        Establishes and returns a connection to the SQLite database.

        If a connection cannot be established, an error is logged.

        Returns:
            Optional[sqlite3.Connection]: A database connection object, or None if
                                        the connection failed.
        """
        try:
            return sqlite3.connect(self.db_path)
        except sqlite3.OperationalError as e:
            logger.error(
                f"Failed to connect to database at {self.db_path}. Please check the path and permissions. Error: {e}")
            return None

    def _initialize_database(self):
        """
        Ensures the database and required tables exist.

        This method creates the database file and the 'WorkflowLocks' table if
        they do not already exist.
        """
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        conn = self._get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                self._create_tables(cursor)
                conn.commit()
            finally:
                conn.close()

    def _create_tables(self, cursor: sqlite3.Cursor):
        """
        Creates the WorkflowLocks table if it doesn't exist.

        This private method is called during database initialization to set up
        the necessary table for storing workflow lock information.

        Args:
            cursor (sqlite3.Cursor): The cursor object for executing SQL commands.
        """
        create_table_query = textwrap.dedent(f'''
            CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                WilmerSessionId NVARCHAR(50),
                WorkflowId NVARCHAR(50),
                WorkflowLockId NVARCHAR(500),
                ExpirationDate DATETIME
            )
        ''')
        cursor.execute(create_table_query)

    def create_node_lock(self, wilmer_session_id: str, workflow_id: str, workflow_lock_id: str):
        """
        Creates a new lock record in the database.

        This method inserts a new lock record with an expiration date of 10 minutes
        into the `WorkflowLocks` table.

        Args:
            wilmer_session_id (str): A unique ID for the current WilmerAI session.
            workflow_id (str): The ID of the workflow being executed.
            workflow_lock_id (str): The unique ID for the specific node lock.
        """
        conn = self._get_db_connection()
        if conn is None:
            logger.error("Cannot create node lock, database connection failed.")
            return

        try:
            cursor = conn.cursor()
            expiration_date = datetime.now() + timedelta(minutes=10)
            insert_query = textwrap.dedent(f'''
                INSERT INTO {self.TABLE_NAME}
                (WilmerSessionId, WorkflowId, WorkflowLockId, ExpirationDate)
                VALUES (?, ?, ?, ?)
            ''')
            cursor.execute(insert_query, (wilmer_session_id, workflow_id, workflow_lock_id, expiration_date))
            conn.commit()
        finally:
            conn.close()

    def delete_node_locks(self, wilmer_session_id: str = None, workflow_id: str = None, workflow_lock_id: str = None):
        """
        Deletes lock records based on the provided criteria.

        This method allows for the deletion of locks based on the session ID,
        workflow ID, or the specific lock ID. At least one criterion must be
        provided; calling with no arguments is a no-op to prevent accidental
        deletion of all locks.

        Args:
            wilmer_session_id (str, optional): The session ID to match.
            workflow_id (str, optional): The workflow ID to match.
            workflow_lock_id (str, optional): The specific lock ID to match.
        """
        if wilmer_session_id is None and workflow_id is None and workflow_lock_id is None:
            logger.warning("delete_node_locks called with no criteria; skipping to prevent accidental full deletion.")
            return

        try:
            conn = self._get_db_connection()
            if conn is None:
                return  # Silently fail if DB isn't configured, as per original logic

            try:
                cursor = conn.cursor()
                query = f'DELETE FROM {self.TABLE_NAME} WHERE 1=1'
                params = []

                if wilmer_session_id is not None:
                    query += ' AND WilmerSessionId = ?'
                    params.append(wilmer_session_id)
                if workflow_id is not None:
                    query += ' AND WorkflowId = ?'
                    params.append(workflow_id)
                if workflow_lock_id is not None:
                    query += ' AND WorkflowLockId = ?'
                    params.append(workflow_lock_id)

                cursor.execute(query, params)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("Error unlocking locks. If you don't use workflow locks, you can safely ignore this.")

    def get_lock(self, workflow_lock_id: str) -> bool:
        """
        Checks if a valid, non-expired lock exists for the given ID.

        If the lock exists but has expired, it is automatically deleted.

        Args:
            workflow_lock_id (str): The unique ID of the lock to check.

        Returns:
            bool: True if a valid and current lock exists, False otherwise.

        Raises:
            Exception: If an error occurs during the database operation.
        """
        conn = self._get_db_connection()
        if conn is None:
            return False  # No DB means no lock

        try:
            cursor = conn.cursor()
            select_query = f'SELECT ExpirationDate FROM {self.TABLE_NAME} WHERE WorkflowLockId = ?'
            cursor.execute(select_query, (workflow_lock_id,))
            result = cursor.fetchone()
        except Exception as e:
            logger.error(f"Error in get_lock: {e}")
            traceback.print_exc()
            raise
        finally:
            conn.close()

        if result:
            expiration_date = datetime.fromisoformat(result[0])
            if expiration_date < datetime.now():
                # Lock is expired; connection is already closed, safe to open a new one
                self.delete_node_locks(workflow_lock_id=workflow_lock_id)
                return False
            return True

        return False

    def acquire_lock(self, wilmer_session_id: str, workflow_id: str, workflow_lock_id: str) -> bool:
        """
        Atomically acquires a workflow lock.

        Replaces the previous check-then-act pattern (a separate ``get_lock`` read
        followed by ``create_node_lock`` write), under which two concurrent requests
        could both observe no lock and both insert one. The check and the insert run
        inside a single ``BEGIN IMMEDIATE`` transaction, which takes SQLite's reserved
        write lock up front and serializes concurrent acquirers, so the second caller
        sees the first caller's row. An expired lock is reclaimed by deleting only that
        specific expired row (by primary key) rather than every row for the id, so a
        live lock held by another workflow is never freed.

        Args:
            wilmer_session_id (str): A unique ID for the current WilmerAI session.
            workflow_id (str): The ID of the workflow being executed.
            workflow_lock_id (str): The unique ID for the specific lock.

        Returns:
            bool: True if the lock was acquired (or locking is unavailable because the
                database could not be opened), False if a live lock already exists.
        """
        conn = self._get_db_connection()
        if conn is None:
            # No DB means locking is unavailable; proceed as the prior code did
            # (a missing lock store was treated as "no lock present").
            logger.warning("Cannot acquire workflow lock, database connection failed; proceeding without a lock.")
            return True

        try:
            conn.isolation_level = None  # take manual control of the transaction boundary
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                # Another connection held SQLite's write lock past the busy
                # timeout. Report the lock as held rather than crashing the
                # workflow; the caller's contract is a boolean.
                logger.warning("Workflow lock database is busy; treating lock '%s' as held.",
                               workflow_lock_id)
                return False
            try:
                cursor.execute(
                    f'SELECT Id, ExpirationDate FROM {self.TABLE_NAME} WHERE WorkflowLockId = ?',
                    (workflow_lock_id,))
                rows = cursor.fetchall()

                now = datetime.now()
                expired_ids = []
                for row_id, expiration in rows:
                    if datetime.fromisoformat(expiration) < now:
                        expired_ids.append(row_id)
                    else:
                        # A live lock exists; do not acquire.
                        conn.rollback()
                        return False

                # Only expired rows (if any) remain; reclaim by removing exactly those.
                for row_id in expired_ids:
                    cursor.execute(f'DELETE FROM {self.TABLE_NAME} WHERE Id = ?', (row_id,))

                expiration_date = now + timedelta(minutes=10)
                cursor.execute(
                    f'''INSERT INTO {self.TABLE_NAME}
                        (WilmerSessionId, WorkflowId, WorkflowLockId, ExpirationDate)
                        VALUES (?, ?, ?, ?)''',
                    (wilmer_session_id, workflow_id, workflow_lock_id, expiration_date))
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

    def delete_old_locks(self, current_wilmer_session_id: str):
        """
        Deletes all locks that do not belong to the current session.

        This method is intended for cleanup purposes, removing stale locks that
        might have been left behind by previous sessions.

        Args:
            current_wilmer_session_id (str): The ID of the currently active session.
        """
        try:
            conn = self._get_db_connection()
            if conn is None:
                return

            try:
                cursor = conn.cursor()
                delete_query = textwrap.dedent(f'''
                    DELETE FROM {self.TABLE_NAME}
                    WHERE WilmerSessionId != ?
                ''')
                cursor.execute(delete_query, (current_wilmer_session_id,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("Error deleting old locks. If you don't use workflow locks, you can safely ignore this.")
