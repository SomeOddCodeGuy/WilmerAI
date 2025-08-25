# /Middleware/services/timestamp_service.py

import logging
from datetime import datetime
from typing import List, Dict

from Middleware.utilities.config_utils import get_discussion_timestamp_file_path
from Middleware.utilities.datetime_utils import current_timestamp, subtract_minutes_from_timestamp, \
    format_relative_time_ago, format_relative_time_string
from Middleware.utilities.file_utils import load_timestamp_file, save_timestamp_file
from Middleware.utilities.hashing_utils import hash_single_message

logger = logging.getLogger(__name__)

# A constant key used to temporarily store a timestamp before the final message hash is known.
PLACEHOLDER_HASH = "PLACEHOLDER_TIMESTAMP_HASH_0000"


class TimestampService:
    """
    Handles the business logic for applying and persisting message timestamps.
    """

    def save_placeholder_timestamp(self, discussion_id: str):
        """
        Saves a timestamp with a placeholder hash for the most recent assistant response.

        This captures the timestamp at the moment of generation, to be finalized
        on the next turn when the message's final content is known.

        Args:
            discussion_id (str): The unique identifier for the conversation.
        """
        if not discussion_id:
            return
        logger.debug("Saving placeholder timestamp for discussion_id: %s", discussion_id)
        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)
        timestamps[PLACEHOLDER_HASH] = current_timestamp()
        save_timestamp_file(timestamp_file, timestamps)

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

        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)
        placeholder_ts = timestamps.pop(PLACEHOLDER_HASH, None)
        timestamps_updated = placeholder_ts is not None

        message_hashes = [
            hash_single_message(msg) if msg['role'] not in ['system', 'systemMes'] else None
            for msg in messages
        ]

        def format_timestamp(ts_str):
            if use_relative_time:
                return format_relative_time_ago(ts_str)
            return ts_str

        # First pass: apply all known timestamps from the file
        for idx, message in enumerate(messages):
            msg_hash = message_hashes[idx]
            if msg_hash and msg_hash in timestamps:
                formatted_ts = format_timestamp(timestamps[msg_hash])
                message['content'] = f"{formatted_ts} {message['content']}"

        non_system_messages_indices = [i for i, h in enumerate(message_hashes) if h is not None]
        handled_case = False

        # Case 1: Group chat or User turn with a generation prompt.
        # This is identified by the last two (or more) messages being untimestamped.
        if len(non_system_messages_indices) >= 2:
            second_last_idx = non_system_messages_indices[-2]
            last_idx = non_system_messages_indices[-1]
            hash2 = message_hashes[second_last_idx]
            hash1 = message_hashes[last_idx]

            if (hash2 and hash2 not in timestamps) and (hash1 and hash1 not in timestamps):
                logger.debug("Handling multi-message untimestamped scenario (group chat or user+gen_prompt).")
                handled_case = True

                # First, apply placeholder to the prior assistant message (now at -3, if it exists).
                if placeholder_ts and len(non_system_messages_indices) >= 3:
                    third_last_idx = non_system_messages_indices[-3]
                    hash3 = message_hashes[third_last_idx]
                    if hash3 and hash3 not in timestamps:
                        logger.debug(f"Applying placeholder timestamp to message index {third_last_idx}.")
                        messages[third_last_idx][
                            'content'] = f"{format_timestamp(placeholder_ts)} {messages[third_last_idx]['content']}"
                        timestamps[hash3] = placeholder_ts
                        timestamps_updated = True

                # Second, handle the message at -2.
                msg_to_timestamp = messages[second_last_idx]
                # If it's a user message, it gets the current time.
                if 'user' in msg_to_timestamp['role'].lower():
                    ts = current_timestamp()
                    messages[second_last_idx][
                        'content'] = f"{format_timestamp(ts)} {messages[second_last_idx]['content']}"
                    timestamps[hash2] = ts
                # If it's an assistant message (group chat), it gets the placeholder.
                elif placeholder_ts:
                    messages[second_last_idx][
                        'content'] = f"{format_timestamp(placeholder_ts)} {messages[second_last_idx]['content']}"
                    timestamps[hash2] = placeholder_ts

                timestamps_updated = True
                # The last message is a generation prompt and is intentionally ignored.

        # Case 2: Simple user turn or regeneration.
        if not handled_case:
            # Apply placeholder to the second-to-last message if it's untimestamped (normal backfill).
            if placeholder_ts and len(non_system_messages_indices) >= 2:
                target_idx = non_system_messages_indices[-2]
                target_hash = message_hashes[target_idx]
                if target_hash and target_hash not in timestamps:
                    logger.debug(f"Applying placeholder timestamp to message index {target_idx}.")
                    messages[target_idx][
                        'content'] = f"{format_timestamp(placeholder_ts)} {messages[target_idx]['content']}"
                    timestamps[target_hash] = placeholder_ts
                    timestamps_updated = True

            # Timestamp the newest message if it's a new user turn.
            if len(non_system_messages_indices) >= 1:
                last_msg_idx = non_system_messages_indices[-1]
                last_msg_hash = message_hashes[last_msg_idx]
                last_msg = messages[last_msg_idx]

                # This prevents timestamping generation prompts during regeneration.
                if (last_msg_hash and last_msg_hash not in timestamps) and 'user' in last_msg['role'].lower():
                    logger.debug(f"Applying current timestamp to newest user message index {last_msg_idx}.")
                    new_ts = current_timestamp()
                    messages[last_msg_idx][
                        'content'] = f"{format_timestamp(new_ts)} {messages[last_msg_idx]['content']}"
                    timestamps[last_msg_hash] = new_ts
                    timestamps_updated = True

        # Case 3: Bootstrapping a new conversation.
        if len(non_system_messages_indices) >= 2 and \
                message_hashes[non_system_messages_indices[0]] not in timestamps and \
                message_hashes[non_system_messages_indices[1]] not in timestamps:
            oldest_idx, second_oldest_idx = non_system_messages_indices[:2]
            oldest_time = subtract_minutes_from_timestamp(2)
            messages[oldest_idx]['content'] = f"{format_timestamp(oldest_time)} {messages[oldest_idx]['content']}"
            timestamps[message_hashes[oldest_idx]] = oldest_time
            second_time = current_timestamp()
            messages[second_oldest_idx][
                'content'] = f"{format_timestamp(second_time)} {messages[second_oldest_idx]['content']}"
            timestamps[message_hashes[second_oldest_idx]] = second_time
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

        datetime_objects = []
        for ts_str in timestamps_data.values():
            try:
                clean_ts_str = ts_str.strip("()")
                datetime_objects.append(datetime.strptime(clean_ts_str, "%A, %Y-%m-%d %H:%M:%S"))
            except (ValueError, TypeError):
                continue

        if not datetime_objects:
            return ""

        start_time = min(datetime_objects)
        most_recent_time = max(datetime_objects)
        start_relative = format_relative_time_string(start_time)
        recent_relative = format_relative_time_string(most_recent_time)

        if start_time == most_recent_time:
            return f"[Time Context: The conversation started {start_relative} ago.]"

        return (f"[Time Context: This conversation started {start_relative} ago. "
                f"The most recent message was sent {recent_relative} ago.]")
