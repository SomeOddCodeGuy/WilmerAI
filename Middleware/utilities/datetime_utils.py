# /Middleware/utilities/datetime_utils.py

from datetime import datetime, timedelta


def _calculate_relative_time(base_time: datetime) -> (int, int, int):
    """
    Calculates the time difference and returns days, hours, and minutes.

    Args:
        base_time (datetime): The starting datetime object for the calculation.

    Returns:
        tuple[int, int, int]: A tuple containing the difference in days, hours, and minutes.
    """
    delta = datetime.now() - base_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return days, hours, minutes


def format_relative_time_string(base_time: datetime) -> str:
    """
    Formats a datetime object into a human-readable relative time string.

    For example, it converts a datetime object into strings like "2 days, 5 hours" or "15 minutes".

    Args:
        base_time (datetime): The past datetime object to compare against the current time.

    Returns:
        str: A string representing the relative time difference.
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
        str: The formatted timestamp, e.g., "(Sunday, 2025-08-17 20:08:06)".
    """
    return "(" + datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def add_seconds_to_timestamp(timestamp_str: str, seconds: int) -> str:
    """
    Adds a specified number of seconds to a timestamp string.

    Args:
        timestamp_str (str): The initial timestamp string.
        seconds (int): The number of seconds to add.

    Returns:
        str: A new timestamp string with the added seconds.
    """
    clean_timestamp_str = timestamp_str.strip("()")
    timestamp = datetime.strptime(clean_timestamp_str, "%A, %Y-%m-%d %H:%M:%S")
    new_timestamp = timestamp + timedelta(seconds=seconds)
    return "(" + new_timestamp.strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def subtract_minutes_from_timestamp(minutes: int) -> str:
    """
    Subtracts a specified number of minutes from the current time.

    Args:
        minutes (int): The number of minutes to subtract.

    Returns:
        str: A new timestamp string representing the calculated past time.
    """
    new_timestamp = datetime.now() - timedelta(minutes=minutes)
    return "(" + new_timestamp.strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def format_relative_time_ago(timestamp_str: str) -> str:
    """
    Converts an absolute timestamp string into a human-readable relative time string.

    Args:
        timestamp_str (str): The timestamp string, e.g., "(Monday, 2025-08-04 18:30:00)".

    Returns:
        str: A relative time string, e.g., "[Sent 2 hours, 15 minutes ago]".
    """
    if not timestamp_str:
        return ""

    try:
        clean_timestamp_str = timestamp_str.strip("()")
        timestamp_dt = datetime.strptime(clean_timestamp_str, "%A, %Y-%m-%d %H:%M:%S")
        relative_str = format_relative_time_string(timestamp_dt)
        return f"[Sent {relative_str} ago]"
    except (ValueError, TypeError):
        return ""
