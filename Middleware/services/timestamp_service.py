# /Middleware/services/timestamp_service.py

import logging
from typing import List, Dict

from Middleware.utilities.config_utils import get_discussion_timestamp_file_path
from Middleware.utilities.datetime_utils import current_timestamp, add_seconds_to_timestamp, \
    subtract_minutes_from_timestamp
from Middleware.utilities.file_utils import load_timestamp_file, save_timestamp_file
from Middleware.utilities.hashing_utils import hash_single_message

logger = logging.getLogger(__name__)


class TimestampService:
    """
    A service responsible for managing and applying timestamps to conversation messages.

    This service handles the business logic for reading message timestamp history,
    applying new timestamps based on conversational context, and persisting
    these timestamps to storage. It ensures that conversations have a coherent
    and logical timeline.
    """

    def track_message_timestamps(self, messages: List[Dict[str, str]], discussion_id: str) -> List[Dict[str, str]]:
        """
        Processes messages to add timestamps based on history and conversational turn order.

        It loads existing timestamps, adds new ones for recent messages using specific
        rules for new and ongoing conversations, and saves any updates back to storage.

        Args:
            messages (List[Dict[str, str]]): List of messages containing role and content.
            discussion_id (str): The unique identifier for the discussion.

        Returns:
            List[Dict[str, str]]: The updated list of messages with timestamps prepended to content.
        """
        logger.debug("Processing timestamps for discussion_id: %s", discussion_id)

        # Load or initialize the timestamp file
        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)

        timestamps_updated = False

        # Generate hashes for all non-system messages to use as keys
        message_hashes = [
            hash_single_message(msg) if msg['role'] not in ['system', 'systemMes'] else None
            for msg in messages
        ]

        # First pass: add timestamps to all known messages
        for idx, message in enumerate(messages):
            msg_hash = message_hashes[idx]
            if msg_hash and msg_hash in timestamps:
                message['content'] = f"{timestamps[msg_hash]} {message['content']}"

        # Identify the indices of non-system messages for rule-based processing
        non_system_messages_indices = [i for i, h in enumerate(message_hashes) if h is not None]

        # Rule for new conversations (first 3 messages are untimestamped)
        if len(non_system_messages_indices) >= 3 and \
                message_hashes[non_system_messages_indices[0]] not in timestamps and \
                message_hashes[non_system_messages_indices[1]] not in timestamps:
            oldest_idx = non_system_messages_indices[0]
            second_oldest_idx = non_system_messages_indices[1]

            # Backfill the first two messages
            oldest_time = subtract_minutes_from_timestamp(2)
            messages[oldest_idx]['content'] = f"{oldest_time} {messages[oldest_idx]['content']}"
            timestamps[message_hashes[oldest_idx]] = oldest_time

            second_time = current_timestamp()
            messages[second_oldest_idx]['content'] = f"{second_time} {messages[second_oldest_idx]['content']}"
            timestamps[message_hashes[second_oldest_idx]] = second_time
            timestamps_updated = True

        # Rule for ongoing conversations (more than 3 messages)
        if len(non_system_messages_indices) >= 4:
            fourth_last_idx = non_system_messages_indices[-4]
            third_last_idx = non_system_messages_indices[-3]
            second_last_idx = non_system_messages_indices[-2]
            last_idx = non_system_messages_indices[-1]

            # Timestamp the user's latest message (second-to-last overall)
            if message_hashes[second_last_idx] not in timestamps:
                ts = current_timestamp()
                messages[second_last_idx]['content'] = f"{ts} {messages[second_last_idx]['content']}"
                timestamps[message_hashes[second_last_idx]] = ts
                timestamps_updated = True

            # Add a temporary timestamp to the assistant's latest message (not saved)
            if message_hashes[last_idx] not in timestamps:
                messages[last_idx]['content'] = f"{current_timestamp()} {messages[last_idx]['content']}"

            # Backfill the assistant's previous message if needed
            if message_hashes[third_last_idx] not in timestamps:
                user_prev_round_hash = message_hashes[fourth_last_idx]
                if user_prev_round_hash in timestamps:
                    user_prev_round_ts_str = timestamps[user_prev_round_hash]
                    # Estimate the LLM response time as 10 seconds after the user message
                    llm_ts = add_seconds_to_timestamp(user_prev_round_ts_str, 10)
                    messages[third_last_idx]['content'] = f"{llm_ts} {messages[third_last_idx]['content']}"
                    timestamps[message_hashes[third_last_idx]] = llm_ts
                    timestamps_updated = True

        if timestamps_updated:
            save_timestamp_file(timestamp_file, timestamps)
            logger.debug("Timestamps file updated for discussion_id: %s", discussion_id)

        return messages