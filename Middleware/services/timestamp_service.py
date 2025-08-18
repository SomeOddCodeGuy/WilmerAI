# /Middleware/services/timestamp_service.py

import logging
from datetime import datetime
from typing import List, Dict

from Middleware.utilities.config_utils import get_discussion_timestamp_file_path
from Middleware.utilities.datetime_utils import current_timestamp, add_seconds_to_timestamp, \
    subtract_minutes_from_timestamp, format_relative_time_ago, format_relative_time_string
from Middleware.utilities.file_utils import load_timestamp_file, save_timestamp_file
from Middleware.utilities.hashing_utils import hash_single_message

logger = logging.getLogger(__name__)


class TimestampService:
    """
    Handles the business logic for applying and persisting message timestamps.
    """

    def track_message_timestamps(self, messages: List[Dict[str, str]], discussion_id: str,
                                 use_relative_time: bool = False) -> List[Dict[str, str]]:
        """
        Processes a list of messages to add absolute or relative timestamps.

        Args:
            messages (List[Dict[str, str]]): The list of conversation messages.
            discussion_id (str): The unique identifier for the conversation.
            use_relative_time (bool): If True, formats timestamps as relative time (e.g., "[5 minutes ago]").

        Returns:
            List[Dict[str, str]]: The list of messages with timestamps prepended to their content.
        """
        logger.debug("Processing timestamps for discussion_id: %s. Relative time: %s", discussion_id, use_relative_time)

        # Load or initialize the timestamp file
        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)

        timestamps_updated = False

        # Generate hashes for all non-system messages
        message_hashes = [
            hash_single_message(msg) if msg['role'] not in ['system', 'systemMes'] else None
            for msg in messages
        ]

        # Helper to format the timestamp based on the flag
        def format_timestamp(ts_str):
            if use_relative_time:
                return format_relative_time_ago(ts_str)
            return ts_str

        # First pass: add timestamps to all known messages
        for idx, message in enumerate(messages):
            msg_hash = message_hashes[idx]
            if msg_hash and msg_hash in timestamps:
                formatted_ts = format_timestamp(timestamps[msg_hash])
                message['content'] = f"{formatted_ts} {message['content']}"

        # Identify the indices of non-system messages for rule-based processing
        non_system_messages_indices = [i for i, h in enumerate(message_hashes) if h is not None]

        # Rule for new conversations
        if len(non_system_messages_indices) >= 3 and \
                message_hashes[non_system_messages_indices[0]] not in timestamps and \
                message_hashes[non_system_messages_indices[1]] not in timestamps:
            oldest_idx = non_system_messages_indices[0]
            second_oldest_idx = non_system_messages_indices[1]

            # Backfill the first two messages
            oldest_time = subtract_minutes_from_timestamp(2)
            messages[oldest_idx]['content'] = f"{format_timestamp(oldest_time)} {messages[oldest_idx]['content']}"
            timestamps[message_hashes[oldest_idx]] = oldest_time

            second_time = current_timestamp()
            messages[second_oldest_idx][
                'content'] = f"{format_timestamp(second_time)} {messages[second_oldest_idx]['content']}"
            timestamps[message_hashes[second_oldest_idx]] = second_time
            timestamps_updated = True

        # Rule for ongoing conversations
        if len(non_system_messages_indices) >= 4:
            fourth_last_idx, third_last_idx, second_last_idx, last_idx = non_system_messages_indices[-4:]

            # Timestamp the user's latest message (second-to-last overall)
            if message_hashes[second_last_idx] not in timestamps:
                ts = current_timestamp()
                messages[second_last_idx]['content'] = f"{format_timestamp(ts)} {messages[second_last_idx]['content']}"
                timestamps[message_hashes[second_last_idx]] = ts
                timestamps_updated = True

            # Add a temporary timestamp to the assistant's latest message (not saved)
            if message_hashes[last_idx] not in timestamps:
                messages[last_idx][
                    'content'] = f"{format_timestamp(current_timestamp())} {messages[last_idx]['content']}"

            # Backfill the assistant's previous message if needed
            if message_hashes[third_last_idx] not in timestamps:
                user_prev_round_hash = message_hashes[fourth_last_idx]
                if user_prev_round_hash in timestamps:
                    user_prev_round_ts_str = timestamps[user_prev_round_hash]
                    llm_ts = add_seconds_to_timestamp(user_prev_round_ts_str, 10)
                    messages[third_last_idx][
                        'content'] = f"{format_timestamp(llm_ts)} {messages[third_last_idx]['content']}"
                    timestamps[message_hashes[third_last_idx]] = llm_ts
                    timestamps_updated = True

        if timestamps_updated:
            save_timestamp_file(timestamp_file, timestamps)
            logger.debug("Timestamps file updated for discussion_id: %s", discussion_id)

        return messages

    def get_time_context_summary(self, discussion_id: str) -> str:
        """
        Generates a human-readable summary of the conversation's timeline.

        Args:
            discussion_id (str): The unique identifier for the discussion.

        Returns:
            str: A formatted string describing when the conversation started and its most recent activity.
        """
        if not discussion_id:
            return ""

        timestamp_file_path = get_discussion_timestamp_file_path(discussion_id)
        timestamps_data = load_timestamp_file(timestamp_file_path)

        if not timestamps_data:
            return ""

        # Parse all timestamp strings into datetime objects
        datetime_objects = []
        for ts_str in timestamps_data.values():
            try:
                clean_ts_str = ts_str.strip("()")
                datetime_objects.append(datetime.strptime(clean_ts_str, "%A, %Y-%m-%d %H:%M:%S"))
            except (ValueError, TypeError):
                continue  # Skip malformed entries

        if not datetime_objects:
            return ""

        # Find the earliest (start) and latest (most recent) timestamps
        start_time = min(datetime_objects)
        most_recent_time = max(datetime_objects)

        start_relative = format_relative_time_string(start_time)
        recent_relative = format_relative_time_string(most_recent_time)

        # Handle the case of a single message
        if start_time == most_recent_time:
            return f"[Time Context: The conversation started {start_relative} ago.]"

        return (f"[Time Context: This conversation started {start_relative} ago. "
                f"The most recent message was sent {recent_relative} ago.]")
