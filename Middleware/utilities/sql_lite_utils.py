import os
import sqlite3
import traceback
from datetime import datetime, timedelta

from Middleware.utilities import config_utils
from Middleware.utilities.config_utils import get_custom_dblite_filepath


class SqlLiteUtils:
    TABLE_NAME = 'WorkflowLocks'

    @staticmethod
    def get_wilmerdb_connection():
        username = config_utils.get_current_username()
        custom_path = get_custom_dblite_filepath()

        if (custom_path):
            db_name = os.path.join(custom_path, f'WilmerDb.{username}.sqlite')
        else:
            db_name = f'WilmerDb.{username}.sqlite'

        conn = sqlite3.connect(db_name)

        if not os.path.exists(db_name):
            print("No database found at " + db_name)
            return None

        cursor = conn.cursor()
        SqlLiteUtils.create_tables(cursor)

        return conn

    @staticmethod
    def create_tables(cursor):
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {SqlLiteUtils.TABLE_NAME} (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                WilmerSessionId NVARCHAR(50),
                WorkflowId NVARCHAR(50),
                WorkflowLockId NVARCHAR(500),
                ExpirationDate DATETIME
            )
        ''')

    @staticmethod
    def create_node_lock(wilmer_session_id, workflow_id, workflow_lock_id):
        conn = SqlLiteUtils.get_wilmerdb_connection()
        if conn is None:
            return
        cursor = conn.cursor()

        expiration_date = datetime.now() + timedelta(minutes=10)

        cursor.execute(f'''
            INSERT INTO {SqlLiteUtils.TABLE_NAME} 
            (WilmerSessionId, WorkflowId, WorkflowLockId, ExpirationDate)
            VALUES (?, ?, ?, ?)
        ''', (wilmer_session_id, workflow_id, workflow_lock_id, expiration_date))

        conn.commit()
        conn.close()

    @staticmethod
    def delete_node_locks(wilmer_session_id=None, workflow_id=None, workflow_lock_id=None):
        conn = SqlLiteUtils.get_wilmerdb_connection()
        if conn is None:
            return
        cursor = conn.cursor()

        try:
            # Start building the SQL query
            query = f'DELETE FROM {SqlLiteUtils.TABLE_NAME} WHERE 1=1'
            params = []

            # Add conditions based on the provided parameters
            if wilmer_session_id is not None:
                query += ' AND WilmerSessionId = ?'
                params.append(wilmer_session_id)

            if workflow_id is not None:
                query += ' AND WorkflowId = ?'
                params.append(workflow_id)

            if workflow_lock_id is not None:
                query += ' AND WorkflowLockId = ?'
                params.append(workflow_lock_id)

            # Execute the query with the accumulated parameters
            cursor.execute(query, params)
            conn.commit()

        finally:
            conn.close()

    @staticmethod
    def get_lock(workflow_lock_id):
        conn = SqlLiteUtils.get_wilmerdb_connection()
        if conn is None:
            return
        cursor = conn.cursor()

        try:
            cursor.execute(f'''
                SELECT ExpirationDate FROM {SqlLiteUtils.TABLE_NAME}
                WHERE WorkflowLockId = ?
            ''', (workflow_lock_id,))
            result = cursor.fetchone()

            if result:
                expiration_date = datetime.fromisoformat(result[0])

                if expiration_date < datetime.now():
                    SqlLiteUtils.delete_node_locks(workflow_lock_id=workflow_lock_id)
                    return False

                return True

        except Exception as e:
            print(f"Error in get_lock: {e}")
            traceback.print_exc()  # This prints the stack trace
            raise

        finally:
            conn.close()

        return False

    @staticmethod
    def delete_old_locks(wilmer_session_id):
        conn = SqlLiteUtils.get_wilmerdb_connection()
        if conn is None:
            return
        cursor = conn.cursor()

        try:
            cursor.execute(f'''
                DELETE FROM {SqlLiteUtils.TABLE_NAME}
                WHERE WilmerSessionId != ?
            ''', (wilmer_session_id,))

            conn.commit()
        finally:
            conn.close()
