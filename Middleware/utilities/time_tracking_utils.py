import logging
from datetime import datetime, timedelta
from typing import List, Dict

from Middleware.utilities.config_utils import get_discussion_timestamp_file_path
from Middleware.utilities.file_utils import load_timestamp_file, save_timestamp_file
from Middleware.utilities.prompt_utils import hash_single_message

logger = logging.getLogger(__name__)


def _current_timestamp() -> str:
    """Return the current timestamp with the day of the week, wrapped in parentheses."""
    return "(" + datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def _add_seconds_to_timestamp(timestamp_str: str, seconds: int) -> str:
    """Add a specific number of seconds to a timestamp string."""
    timestamp = datetime.strptime(timestamp_str, "(%A, %Y-%m-%d %H:%M:%S)")
    new_timestamp = timestamp + timedelta(seconds=seconds)
    return "(" + new_timestamp.strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def _subtract_minutes_from_timestamp(minutes: int) -> str:
    """Return the current timestamp minus the specified number of minutes."""
    return "(" + (datetime.now() - timedelta(minutes=minutes)).strftime("%A, %Y-%m-%d %H:%M:%S") + ")"


def track_message_timestamps(messages: List[Dict[str, str]], discussion_id: str) -> List[Dict[str, str]]:
    """
    Track timestamps for messages, append timestamps where known, and update timestamps
    for the two most recent messages, handling third-to-last if needed, and handle
    cases for new conversations.

    Parameters:
    - messages (List[Dict[str, str]]): List of messages containing role and content.
    - discussion_id (str): The ID of the discussion.

    Returns:
    - List[Dict[str, str]]: The updated list of messages with timestamps appended where applicable.
    """

    logger.debug("Processing timestamps")

    # Load or initialize the timestamp file
    timestamp_file = get_discussion_timestamp_file_path(discussion_id)
    timestamps = load_timestamp_file(timestamp_file)

    # Track if any updates to timestamps were made
    timestamps_updated = False

    # Track the hashes of non-system messages
    message_hashes = []
    for message in messages:
        if message['role'] not in ['system', 'systemMes']:
            message_hashes.append(hash_single_message(message))
        else:
            message_hashes.append(None)  # For system messages, we add None

    # Add timestamps to known messages
    for idx, message in enumerate(messages):
        if message_hashes[idx] in timestamps:
            # Add the timestamp to the beginning of the content if it exists
            message['content'] = f"{timestamps[message_hashes[idx]]} {message['content']}"

    # Handle the last three non-system messages
    non_system_messages = [
        i for i, message in enumerate(messages) if message['role'] not in ['system', 'systemMes']
    ]

    # Handle a new conversation with 3 messages and no timestamps on the first two
    if len(non_system_messages) >= 3 and message_hashes[non_system_messages[0]] not in timestamps and message_hashes[
        non_system_messages[1]] not in timestamps:
        oldest_idx = non_system_messages[0]  # Oldest message (AI's first message)
        second_to_last_idx = non_system_messages[1]  # User's response

        # Add current timestamp - 2 minutes to the oldest message (AI's first message)
        oldest_time = _subtract_minutes_from_timestamp(2)
        messages[oldest_idx]['content'] = f"{oldest_time} {messages[oldest_idx]['content']}"
        timestamps[message_hashes[oldest_idx]] = oldest_time
        timestamps_updated = True

        # Add current timestamp to the second-to-last message (User's response)
        second_time = _current_timestamp()
        messages[second_to_last_idx]['content'] = f"{second_time} {messages[second_to_last_idx]['content']}"
        timestamps[message_hashes[second_to_last_idx]] = second_time
        timestamps_updated = True

    # Handle the case for conversations with more than 3 messages
    if len(non_system_messages) >= 4:
        fourth_last_idx = non_system_messages[-4] if len(non_system_messages) > 3 else None
        third_last_idx = non_system_messages[-3]
        second_last_idx = non_system_messages[-2]
        last_idx = non_system_messages[-1]

        current_time = _current_timestamp()

        # Add current timestamp to the second-to-last message (if not already timestamped)
        if message_hashes[second_last_idx] not in timestamps:
            messages[second_last_idx]['content'] = f"{current_time} {messages[second_last_idx]['content']}"
            timestamps[message_hashes[second_last_idx]] = current_time  # Store in the file
            timestamps_updated = True  # Mark that we updated the timestamps

        # Add current timestamp to the last message but do not store in file
        if message_hashes[last_idx] not in timestamps:
            messages[last_idx]['content'] = f"{current_time} {messages[last_idx]['content']}"

        # Now, check the third-to-last message and backfill if needed
        if message_hashes[third_last_idx] not in timestamps and fourth_last_idx:
            # If the fourth-to-last message (your message from last round) has a timestamp
            if message_hashes[fourth_last_idx] in timestamps:
                user_last_round_timestamp = timestamps[message_hashes[fourth_last_idx]]
                llm_timestamp = _add_seconds_to_timestamp(user_last_round_timestamp, 10)
                messages[third_last_idx]['content'] = f"{llm_timestamp} {messages[third_last_idx]['content']}"
                timestamps[message_hashes[third_last_idx]] = llm_timestamp  # Store in the file
                timestamps_updated = True  # Mark that we updated the timestamps

    # Only save to the file if any changes were made
    if timestamps_updated:
        save_timestamp_file(timestamp_file, timestamps)

    logger.debug("Timestamp messages output:")
    logger.debug(messages)

    return messages
