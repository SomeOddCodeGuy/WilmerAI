import argparse

from Middleware.core.open_ai_api import WilmerApi
from Middleware.utilities import sql_lite_utils, instance_utils


def parse_arguments():
    parser = argparse.ArgumentParser(description="Process configuration directory and user arguments.")
    parser.add_argument("--ConfigDirectory", type=str, help="Custom path to the configuration directory")
    parser.add_argument("--User", type=str, help="User to run Wilmer as")

    parser.add_argument("positional", nargs="*", help="Positional arguments for ConfigDirectory and User")

    args = parser.parse_args()

    if len(args.positional) > 0 and args.positional[0].strip():
        instance_utils.CONFIG_DIRECTORY = args.positional[0].strip()
    if len(args.positional) > 1 and args.positional[1].strip():
        instance_utils.USER = args.positional[1].strip()

    if args.ConfigDirectory and args.ConfigDirectory.strip():
        instance_utils.CONFIG_DIRECTORY = args.ConfigDirectory.strip()
    if args.User and args.User.strip():
        instance_utils.USER = args.User.strip()


if __name__ == '__main__':
    parse_arguments()

    print(f"Config Directory: {instance_utils.CONFIG_DIRECTORY}")
    print(f"User: {instance_utils.USER}")

    print(f"Deleting old locks that do not belong to Wilmer Instance_Id: '{instance_utils.INSTANCE_ID}'")
    sql_lite_utils.SqlLiteUtils.delete_old_locks(instance_utils.INSTANCE_ID)

    print("Starting API")
    api = WilmerApi()
    api.run_api()
