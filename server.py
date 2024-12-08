import argparse
import logging
import os
from logging.handlers import RotatingFileHandler

from Middleware.core.open_ai_api import WilmerApi
from Middleware.utilities import sql_lite_utils, instance_utils, config_utils

logger = logging.getLogger(__name__)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Process configuration directory and user arguments.")
    parser.add_argument("--ConfigDirectory", type=str, help="Custom path to the configuration directory")
    parser.add_argument("--User", type=str, help="User to run Wilmer as")
    parser.add_argument("--LoggingDirectory", type=str, default="logs", help="Directory for log files")

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

    if args.LoggingDirectory and args.LoggingDirectory.strip():
        instance_utils.LOGGING_DIRECTORY = args.LoggingDirectory.strip()

    if "<user>" in instance_utils.LOGGING_DIRECTORY:
        instance_utils.LOGGING_DIRECTORY = instance_utils.LOGGING_DIRECTORY.replace("<user>", instance_utils.USER)


if __name__ == '__main__':
    parse_arguments()

    handlers = [logging.StreamHandler()]
    if config_utils.get_use_file_logging():
        log_directory = instance_utils.LOGGING_DIRECTORY
        os.makedirs(log_directory, exist_ok=True)
        handlers.append(RotatingFileHandler(
            os.path.join(log_directory, "wilmerai.log"),
            maxBytes=1048576 * 3,
            backupCount=7,
        ))

    logging.basicConfig(
        handlers=handlers,
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info(f"Config Directory: {instance_utils.CONFIG_DIRECTORY}")
    logger.info(f"User: {instance_utils.USER}")
    logger.info(f"Logging Directory: {instance_utils.LOGGING_DIRECTORY}")

    logger.info(
        f"Deleting old locks that do not belong to Wilmer Instance_Id: '{instance_utils.INSTANCE_ID}'"
    )
    sql_lite_utils.SqlLiteUtils.delete_old_locks(instance_utils.INSTANCE_ID)

    logger.info("Starting API")

    api = WilmerApi()
    # Set debug=True to enable auto-reloading.
    api.run_api(debug=False)
