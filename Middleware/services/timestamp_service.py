# /Middleware/services/timestamp_service.py

import logging
from typing import List, Dict

from Middleware.utilities.config_utils import get_discussion_timestamp_file_path
from Middleware.utilities.datetime_utils import (
    current_timestamp,
    format_relative_time_ago,
    format_relative_time_string,
    add_seconds_to_timestamp,
    parse_timestamp_string
)
from Middleware.utilities.file_utils import load_timestamp_file, save_timestamp_file
from Middleware.utilities.hashing_utils import hash_single_message

logger = logging.getLogger(__name__)

# Define the placeholder hash for the new logic.
PLACEHOLDER_HASH = "PLACEHOLDER_TIMESTAMP_HASH_0000"
# Define the legacy placeholder hash for migration/cleanup purposes.
LEGACY_PLACEHOLDER_HASH = "PLACEHOLDER_TIMESTAMP_HASH_0000"


def _is_generation_prompt(message: Dict[str, str]) -> bool:
    """
    Heuristic check to determine if a message is likely a generation prompt
    (e.g., "CharacterName:").

    Args:
        message (Dict[str, str]): The message dictionary to check.

    Returns:
        bool: True if the message is a likely generation prompt, False otherwise.
    """
    content = message.get('content', '').strip()
    if len(content) < 100 and content.endswith(':'):
        logger.debug(f"Detected generation prompt: '{content}'")
        return True
    return False


class TimestampService:
    """
    Handles the business logic for applying and persisting message timestamps.
    """

    def save_placeholder_timestamp(self, discussion_id: str):
        """
        Saves a placeholder timestamp to be committed later.
        This marks the beginning of an assistant's response generation.

        Args:
            discussion_id (str): The unique identifier for the conversation.
        """
        if not discussion_id:
            return

        timestamp_to_save = current_timestamp()
        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)

        logger.debug("Saving placeholder timestamp for discussion_id: %s", discussion_id)
        timestamps[PLACEHOLDER_HASH] = timestamp_to_save
        save_timestamp_file(timestamp_file, timestamps)

    def commit_assistant_response(self, discussion_id: str, content: str):
        """
        Commits the final assistant response content, associating it with the
        previously saved placeholder timestamp.

        Args:
            discussion_id (str): The unique identifier for the conversation.
            content (str): The content of the assistant's response.
        """
        if not discussion_id:
            return

        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)

        if PLACEHOLDER_HASH in timestamps:
            placeholder_time = timestamps.pop(PLACEHOLDER_HASH)
            if content:
                message_hash = hash_single_message({'role': 'assistant', 'content': content})
                logger.debug("Committing placeholder timestamp for hash: %s", message_hash)
                timestamps[message_hash] = placeholder_time
            else:
                logger.debug("Cleared placeholder for empty assistant response.")
            save_timestamp_file(timestamp_file, timestamps)
        elif content:
            logger.warning("Attempted to commit assistant response without a placeholder. Saving with current time.")
            message_hash = hash_single_message({'role': 'assistant', 'content': content})
            timestamps[message_hash] = current_timestamp()
            save_timestamp_file(timestamp_file, timestamps)

    def save_specific_timestamp(self, discussion_id: str, content: str, timestamp: str):
        """
        Saves a specific timestamp for a given message content hash.
        Overrides existing timestamps if they differ (e.g., updating a bootstrapped time).

        Args:
            discussion_id (str): The unique identifier for the conversation.
            content (str): The content of the message to be hashed.
            timestamp (str): The timestamp string to save.
        """
        if not discussion_id or not content or not timestamp:
            return

        logger.debug("Saving specific timestamp for discussion_id: %s", discussion_id)

        message_hash = hash_single_message({'role': 'assistant', 'content': content})

        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)
        timestamps_updated = False

        if LEGACY_PLACEHOLDER_HASH in timestamps:
            del timestamps[LEGACY_PLACEHOLDER_HASH]
            timestamps_updated = True

        if message_hash not in timestamps or timestamps[message_hash] != timestamp:
            if message_hash in timestamps:
                logger.debug("Updating existing timestamp for hash: %s. Old: %s, New: %s",
                             message_hash, timestamps[message_hash], timestamp)
            else:
                logger.debug("Timestamp saved for hash: %s", message_hash)
            timestamps[message_hash] = timestamp
            timestamps_updated = True
        else:
            logger.debug("Timestamp already exists and matches for hash: %s.", message_hash)

        if timestamps_updated:
            save_timestamp_file(timestamp_file, timestamps)

    def resolve_and_track_history(self, messages: List[Dict[str, str]], discussion_id: str):
        """
        Ensures the timestamp file is up-to-date based on the incoming history.
        Resolves pending placeholders from previous turns and tracks hashes for new messages.
        Does NOT modify the content of the messages list. Should be called once at the start of a request.

        Args:
            messages (List[Dict[str, str]]): The list of conversation messages.
            discussion_id (str): The unique identifier for the conversation.
        """
        logger.debug("Resolving and tracking timestamp history for discussion_id: %s.", discussion_id)

        if not discussion_id:
            return

        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)
        timestamps_updated = False

        # --- Phase 0: Resolve placeholder from a previous turn ---
        if PLACEHOLDER_HASH in timestamps:
            logger.debug("Found pending placeholder. Attempting to resolve.")
            placeholder_time = timestamps[PLACEHOLDER_HASH]
            resolved = False

            for i in range(len(messages) - 1, -1, -1):
                message = messages[i]
                if message.get('role', '').lower() == 'assistant':
                    if i == len(messages) - 1 and _is_generation_prompt(message):
                        continue

                    msg_hash = hash_single_message(message)
                    if msg_hash not in timestamps:
                        logger.info("Applying pending placeholder to last assistant message (hash: %s)", msg_hash)
                        timestamps[msg_hash] = placeholder_time
                    else:
                        logger.debug("Last valid assistant message already tracked.")

                    resolved = True
                    break

            if not resolved:
                logger.warning(
                    "Could not find a suitable assistant message to resolve pending placeholder (e.g., chat started with assistant, or only system messages present).")

            del timestamps[PLACEHOLDER_HASH]
            timestamps_updated = True

        # Clean up legacy placeholder
        if LEGACY_PLACEHOLDER_HASH in timestamps:
            del timestamps[LEGACY_PLACEHOLDER_HASH]
            timestamps_updated = True

        # --- Phase 1: Chronological Resolution (Backward Iteration) ---

        time_anchor = current_timestamp()

        for i in range(len(messages) - 1, -1, -1):
            message = messages[i]
            role = message.get('role', '').lower()

            if role in ['system', 'systemmes']:
                continue

            if i == len(messages) - 1 and _is_generation_prompt(message):
                continue

            msg_hash = hash_single_message(message)

            if msg_hash in timestamps:
                time_anchor = timestamps[msg_hash]
            else:
                timestamps_updated = True
                timestamps[msg_hash] = time_anchor
                logger.debug(f"Assigning timestamp {time_anchor} to new message (Index: {i}, Role: {role})")

            new_anchor = add_seconds_to_timestamp(time_anchor, -1)

            if new_anchor == time_anchor:
                logger.warning(f"Failed to decrement time anchor '{time_anchor}'. Backfill accuracy might be affected.")
            else:
                time_anchor = new_anchor

        if timestamps_updated:
            save_timestamp_file(timestamp_file, timestamps)
            logger.debug("Timestamps file updated for discussion_id: %s", discussion_id)

    def format_messages_with_timestamps(self, messages: List[Dict[str, str]], discussion_id: str,
                                        use_relative_time: bool = False) -> List[Dict[str, str]]:
        """
        Applies timestamp formatting to the content of the messages list.
        Assumes that resolve_and_track_history has already been run for this request.

        Args:
            messages (List[Dict[str, str]]): The list of conversation messages.
            discussion_id (str): The unique identifier for the conversation.
            use_relative_time (bool): If True, formats timestamps as relative time (e.g., "[5 minutes ago]").

        Returns:
            List[Dict[str, str]]: The list of messages with timestamps prepended to their content.
        """
        logger.debug("Formatting messages with timestamps for discussion_id: %s. Relative time: %s", discussion_id,
                     use_relative_time)

        if not discussion_id:
            return messages

        timestamp_file = get_discussion_timestamp_file_path(discussion_id)
        timestamps = load_timestamp_file(timestamp_file)

        def format_timestamp(ts_str):
            if use_relative_time:
                return format_relative_time_ago(ts_str)
            return ts_str

        for i, message in enumerate(messages):
            role = message.get('role', '').lower()

            if role in ['system', 'systemmes']:
                continue

            if i == len(messages) - 1 and _is_generation_prompt(message):
                continue

            msg_hash = hash_single_message(message)

            if msg_hash in timestamps:
                resolved_ts = timestamps[msg_hash]
                formatted_ts = format_timestamp(resolved_ts)

                if not message['content'].startswith(formatted_ts):
                    message['content'] = f"{formatted_ts} {message['content']}"

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

        data_to_process = timestamps_data
        if timestamps_data and (LEGACY_PLACEHOLDER_HASH in timestamps_data or PLACEHOLDER_HASH in timestamps_data):
            data_to_process = timestamps_data.copy()
            data_to_process.pop(LEGACY_PLACEHOLDER_HASH, None)
            data_to_process.pop(PLACEHOLDER_HASH, None)

        if not data_to_process:
            return ""

        datetime_objects = []
        for ts_str in data_to_process.values():
            dt_obj = parse_timestamp_string(ts_str)
            if dt_obj:
                datetime_objects.append(dt_obj)

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
