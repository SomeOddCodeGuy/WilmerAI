import sys

from Middleware.core.open_ai_api import WilmerApi
from Middleware.utilities import sql_lite_utils, instance_utils


def parse_arguments():
    args = sys.argv[1:]  # Skip the script name
    for i in range(len(args)):
        if args[i].startswith("--ConfigDirectory="):
            value = args[i].split("=", 1)[1].strip()
            if len(value) > 0:
                instance_utils.CONFIG_DIRECTORY = value
        elif args[i].startswith("--User="):
            value = args[i].split("=", 1)[1].strip()
            if len(value) > 0:
                instance_utils.USER = value
        elif i == 0 and not args[i].startswith("--"):
            value = args[i].strip()
            if len(value) > 0:
                instance_utils.CONFIG_DIRECTORY = value
        elif i == 1 and not args[i].startswith("--"):
            value = args[i].strip()
            if len(value) > 0:
                instance_utils.USER = value


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
