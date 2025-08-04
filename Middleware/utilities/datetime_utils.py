# /Middleware/utilities/datetime_utils.py

from datetime import datetime, timedelta


def current_timestamp() -> str:
    """
    Returns the current timestamp.

    This function formats the current date and time into a specific string format
    and encloses it in parentheses.

    Returns:
        str: A string representing the current timestamp, e.g., "(Monday, 2025-08-03 23:39:00)".
    """
    return "(" + datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def add_seconds_to_timestamp(timestamp_str: str, seconds: int) -> str:
    """
    Adds a specified number of seconds to a given timestamp string.

    This function parses a timestamp string, adds the specified number of seconds
    to it, and returns the new timestamp in the same string format.

    Args:
        timestamp_str (str): The timestamp string to which seconds will be added,
                             e.g., "(Monday, 2025-08-03 23:39:00)".
        seconds (int): The number of seconds to add.

    Returns:
        str: A new timestamp string with the added seconds.
    """
    # Strip parentheses for parsing
    clean_timestamp_str = timestamp_str.strip("()")
    timestamp = datetime.strptime(clean_timestamp_str, "%A, %Y-%m-%d %H:%M:%S")
    new_timestamp = timestamp + timedelta(seconds=seconds)
    return "(" + new_timestamp.strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def subtract_minutes_from_timestamp(minutes: int) -> str:
    """
    Returns a timestamp from a specified number of minutes in the past.

    This function calculates a timestamp by subtracting a given number of minutes
    from the current time.

    Args:
        minutes (int): The number of minutes to subtract from the current time.

    Returns:
        str: A string representing the calculated timestamp, e.g., "(Monday, 2025-08-03 23:29:00)".
    """
    new_timestamp = datetime.now() - timedelta(minutes=minutes)
    return "(" + new_timestamp.strftime("%A, %Y-%m-%d %H:%M:%S") + ")"