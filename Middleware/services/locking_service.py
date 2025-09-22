# /Middleware/services/locking_service.py

import logging
import os
import sqlite3
import textwrap  # Import the textwrap module
import traceback
from datetime import datetime, timedelta

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

        The path is constructed using a custom path from the user config, if
        available, otherwise, it defaults to the current directory.

        Returns:
            str: The full file path for the SQLite database.
        """
        custom_path = config_utils.get_custom_dblite_filepath()
        db_filename = f'WilmerDb.{self.username}.sqlite'
        if custom_path:
            return os.path.join(custom_path, db_filename)
        return db_filename

    def _get_db_connection(self) -> sqlite3.Connection | None:
        """
        Establishes and returns a connection to the SQLite database.

        If a connection cannot be established, an error is logged.

        Returns:
            sqlite3.Connection | None: A database connection object, or None if
                                        the connection failed.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            return conn
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
        if not os.path.exists(os.path.dirname(self.db_path)) and os.path.dirname(self.db_path) != '':
            os.makedirs(os.path.dirname(self.db_path))

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
        # Use textwrap.dedent to remove leading whitespace
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
            # Use textwrap.dedent here as well
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
        workflow ID, or the specific lock ID. If no criteria are provided, no
        locks will be deleted.

        Args:
            wilmer_session_id (str, optional): The session ID to match.
            workflow_id (str, optional): The workflow ID to match.
            workflow_lock_id (str, optional): The specific lock ID to match.
        """
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
            # This query is single-line, so no dedent needed
            select_query = f'SELECT ExpirationDate FROM {self.TABLE_NAME} WHERE WorkflowLockId = ?'
            cursor.execute(select_query, (workflow_lock_id,))
            result = cursor.fetchone()

            if result:
                expiration_date = datetime.fromisoformat(result[0])
                if expiration_date < datetime.now():
                    # Lock is expired, delete it and report no active lock
                    self.delete_node_locks(workflow_lock_id=workflow_lock_id)
                    return False
                # Lock is valid and current
                return True
        except Exception as e:
            logger.error(f"Error in get_lock: {e}")
            traceback.print_exc()
            raise
        finally:
            conn.close()

        return False

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
                # Use textwrap.dedent for consistency and clarity
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
