import sys

from Middleware.core.open_ai_api import WilmerApi
from Middleware.utilities import sql_lite_utils, instance_utils


def parse_arguments():
    if len(sys.argv) > 1:
        if (len(sys.argv[1]) > 0):
            print("sys.argv 1 is " + str(sys.argv[1]))
            instance_utils.CONFIG_DIRECTORY = sys.argv[1]
    if len(sys.argv) > 2:
        if (len(sys.argv[2]) > 0):
            print("sys.argv 2 is " + str(sys.argv[2]))
            instance_utils.USER = sys.argv[2]


if __name__ == '__main__':
    # Parse the command-line arguments
    parse_arguments()

    print(f"Config Directory: {instance_utils.CONFIG_DIRECTORY}")
    print(f"User: {instance_utils.USER}")

    print(f"Deleting old locks for that do not belong to Wilmer Instance_Id: '{instance_utils.INSTANCE_ID}'")
    sql_lite_utils.SqlLiteUtils.delete_old_locks(instance_utils.INSTANCE_ID)

    print("Starting API")
    api = WilmerApi()
    api.run_api()
