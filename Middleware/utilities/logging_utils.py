import logging
from enum import Enum, auto
from logging.handlers import RotatingFileHandler

from Middleware.utilities.config_utils import get_user_config
from Middleware.utilities.file_utils import get_logger_filename


# Define an enumeration for logging levels
class LoggingLevel(Enum):
    INFO_LEVEL = auto()
    WARNING_LEVEL = auto()
    ERROR_LEVEL = auto()
    CRITICAL_LEVEL = auto()

    @staticmethod
    def from_string(level_name):
        try:
            return LoggingLevel[level_name.upper().replace(' ', '_')]
        except KeyError:
            raise ValueError(
                f"Unknown level: {level_name}. Available levels are: {', '.join(LoggingLevel.__members__.keys())}")


# Configure the logging system
logging.basicConfig(
    level=LoggingLevel.INFO_LEVEL.value,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(get_logger_filename(), maxBytes=10000, backupCount=3),
        logging.StreamHandler()
    ]
)

# Create a custom logger
logger = logging.getLogger(__name__)


def set_verbose(level=LoggingLevel.INFO_LEVEL):
    """Set the verbosity level of the logger based on the configuration.

    Args:
        level (LoggingLevel): The logging level. Defaults to INFO_LEVEL.

    Raises:
        ValueError: If the level is not recognized by the LoggingLevel enum.
    """
    config_data = get_user_config()
    verbose_level = config_data.get('verboseLogging', True)  # Default to True if not specified

    if level:
        logger.setLevel(level.value)
    elif verbose_level:
        logger.setLevel(LoggingLevel.INFO_LEVEL.value)
    else:
        logger.setLevel(LoggingLevel.CRITICAL_LEVEL.value)  # Disable all logging


def get_logger():
    """Return the logger instance."""
    return logger


def log(message, level=LoggingLevel.INFO_LEVEL):
    """Log a message with an optional level. Defaults to INFO_LEVEL.

    Args:
        message (str): The message to log.
        level (LoggingLevel): The logging level. Defaults to INFO_LEVEL.

    Raises:
        ValueError: If the level is not recognized by the LoggingLevel enum.
    """
    logger.log(level.value, message)

# Example usage of the log function
# log("This is an info message", level=LoggingLevel.INFO_LEVEL)
