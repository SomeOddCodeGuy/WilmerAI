from Middleware.core.open_ai_api import WilmerApi
from Middleware.utilities import sql_lite_utils
from Middleware.utilities.instance_utils import INSTANCE_ID

if __name__ == '__main__':
    print(f"Deleting old locks for that do not belong to Wilmer Instance_Id: '{INSTANCE_ID}'")
    sql_lite_utils.SqlLiteUtils.delete_old_locks(INSTANCE_ID)

    print("Starting API")
    api = WilmerApi()
    api.run_api()
