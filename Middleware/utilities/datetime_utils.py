# /Middleware/utilities/datetime_utils.py

from datetime import datetime, timedelta
from typing import Optional

# Define the standard format string
TIMESTAMP_FORMAT = "%A, %Y-%m-%d %H:%M:%S"


def parse_timestamp_string(timestamp_str: str) -> Optional[datetime]:
    """
    Parses the specific timestamp format used in WilmerAI into a datetime object.

    Args:
        timestamp_str (str): The timestamp string, e.g., "(Monday, 2025-08-04 18:30:00)".

    Returns:
        datetime | None: The parsed datetime object, or None if parsing fails.
    """
    if not isinstance(timestamp_str, str) or not timestamp_str:
        return None
    try:
        clean_timestamp_str = timestamp_str.strip("() ")
        return datetime.strptime(clean_timestamp_str, TIMESTAMP_FORMAT)
    except (ValueError, TypeError):
        return None


def format_datetime_to_ts(dt_obj: datetime) -> str:
    """
    Formats a datetime object into the standard WilmerAI timestamp string.

    Args:
        dt_obj (datetime): The datetime object to format.

    Returns:
        str: The formatted timestamp string.
    """
    return "(" + dt_obj.strftime(TIMESTAMP_FORMAT) + ")"


def _calculate_relative_time(base_time: datetime) -> (int, int, int):
    """
    Calculates the time difference and returns days, hours, and minutes.

    Args:
        base_time (datetime): The base datetime object to compare against the current time.

    Returns:
        tuple[int, int, int]: A tuple containing days, hours, and minutes.
    """
    delta = datetime.now() - base_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return days, hours, minutes


def format_relative_time_string(base_time: datetime) -> str:
    """
    Formats a datetime object into a human-readable relative time string.

    Args:
        base_time (datetime): The datetime object to format.

    Returns:
        str: The human-readable relative time string.
    """
    days, hours, minutes = _calculate_relative_time(base_time)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

    if not parts:
        return "less than a minute"

    return ", ".join(parts)


def current_timestamp() -> str:
    """
    Generates the current timestamp formatted as a string.

    Returns:
        str: The current timestamp string.
    """
    return format_datetime_to_ts(datetime.now())


def add_seconds_to_timestamp(timestamp_str: str, seconds: int) -> str:
    """
    Adds a specified number of seconds to a timestamp string.

    Args:
        timestamp_str (str): The timestamp string to add seconds to.
        seconds (int): The number of seconds to add.

    Returns:
        str: The new timestamp string, or the original string if parsing fails.
    """
    timestamp = parse_timestamp_string(timestamp_str)
    if timestamp:
        new_timestamp = timestamp + timedelta(seconds=seconds)
        return format_datetime_to_ts(new_timestamp)
    return timestamp_str


def subtract_minutes_from_timestamp(minutes: int) -> str:
    """
    Subtracts a specified number of minutes from the current time.

    Args:
        minutes (int): The number of minutes to subtract.

    Returns:
        str: The new timestamp string.
    """
    new_timestamp = datetime.now() - timedelta(minutes=minutes)
    return format_datetime_to_ts(new_timestamp)


def format_relative_time_ago(timestamp_str: str) -> str:
    """
    Converts an absolute timestamp string into a human-readable relative time string.

    Args:
        timestamp_str (str): The timestamp string to convert.

    Returns:
        str: The human-readable relative time string.
    """
    timestamp_dt = parse_timestamp_string(timestamp_str)
    if timestamp_dt:
        relative_str = format_relative_time_string(timestamp_dt)
        return f"[Sent {relative_str} ago]"
    return ""
