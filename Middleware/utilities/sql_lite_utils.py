import os
import sqlite3
import traceback
from datetime import datetime, timedelta


class SqlLiteUtils:
    DB_NAME = 'WilmerDb.sqlite'
    TABLE_NAME = 'WorkflowLocks'

    @staticmethod
    def create_node_lock(wilmer_session_id, workflow_id, workflow_lock_id):
        conn = sqlite3.connect(SqlLiteUtils.DB_NAME)
        cursor = conn.cursor()

        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {SqlLiteUtils.TABLE_NAME} (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                WilmerSessionId NVARCHAR(50),
                WorkflowId NVARCHAR(50),
                WorkflowLockId NVARCHAR(500),
                ExpirationDate DATETIME
            )
        ''')

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
        if not os.path.exists(SqlLiteUtils.DB_NAME):
            return  # DB does not exist, nothing to do

        conn = sqlite3.connect(SqlLiteUtils.DB_NAME)
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
        if not os.path.exists(SqlLiteUtils.DB_NAME):
            return False

        conn = sqlite3.connect(SqlLiteUtils.DB_NAME)
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
        if not os.path.exists(SqlLiteUtils.DB_NAME):
            return  # DB does not exist, nothing to do

        conn = sqlite3.connect(SqlLiteUtils.DB_NAME)
        cursor = conn.cursor()

        try:
            cursor.execute(f'''
                DELETE FROM {SqlLiteUtils.TABLE_NAME}
                WHERE WilmerSessionId != ?
            ''', (wilmer_session_id,))

            conn.commit()
        finally:
            conn.close()
