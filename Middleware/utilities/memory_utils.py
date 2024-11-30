import logging
from copy import deepcopy
from typing import Dict, List, Any, Tuple

from Middleware.utilities import text_utils
from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_discussion_chat_summary_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes
from Middleware.utilities.prompt_utils import extract_text_blocks_from_hashed_chunks, \
    find_how_many_new_memories_since_last_summary

logger = logging.getLogger(__name__)


def gather_chat_summary_memories(messages: List[Dict[str, str]], discussion_id: str,
                                 max_turns_to_pull: int = 0):
    """
    Gathers chat summary memories from the conversation based on the specified limits.

    :param messages: The list of messages in the conversation.
    :param max_turns_to_pull: The maximum number of turns to pull from the conversation (default: 0).
    :return: A list of tuples containing the chat summary memories.
    """
    return get_chat_summary_memories(
        messages=messages,
        discussion_id=discussion_id,
        max_turns_to_search=max_turns_to_pull
    )


def gather_recent_memories(messages: List[Dict[str, str]], discussion_id: str, max_turns_to_pull=0,
                           max_summary_chunks_from_file=0) -> Any:
    """
        Gathers recent memories from the conversation based on the specified limits.

        :param messages: The list of messages in the conversation.
        :param max_turns_to_pull: The maximum number of turns to pull from the conversation (default: 0).
        :param max_summary_chunks_from_file: The maximum number of summary chunks to pull from the file (default: 0).
        :return: A list of recent memories.
    """
    return get_recent_memories(
        messages=messages,
        max_turns_to_search=max_turns_to_pull,
        max_summary_chunks_from_file=max_summary_chunks_from_file,
        discussion_id=discussion_id
    )


def get_recent_memories(messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0,
                        max_summary_chunks_from_file=0) -> str:
    """
    Retrieves recent memories from chat messages or memory files.

    Args:
        messages (List[Dict[str, str]]): The list of recent chat messages.
        max_turns_to_search (int): Maximum turns to search in the chat history.
        max_summary_chunks_from_file (int): Maximum summary chunks to retrieve from memory files.

    Returns:
        str: The recent memories concatenated as a single string with '--ChunkBreak--' delimiter.
    """
    logger.debug("Entered get_recent_memories")

    if discussion_id is None:
        final_pairs = get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
        logger.debug("Recent Memory complete. Total number of pair chunks: {}".format(len(final_pairs)))
        return '--ChunkBreak--'.join(final_pairs)
    else:
        filepath = get_discussion_memory_file_path(discussion_id)
        hashed_chunks = read_chunks_with_hashes(filepath)
        if len(hashed_chunks) == 0:
            final_pairs = get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
            return '--ChunkBreak--'.join(final_pairs)
        else:
            chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)
            if max_summary_chunks_from_file == 0:
                max_summary_chunks_from_file = 3
            elif max_summary_chunks_from_file == -1:
                return '--ChunkBreak--'.join(chunks)
            elif len(chunks) <= max_summary_chunks_from_file:
                return '--ChunkBreak--'.join(chunks)

            latest_summaries = chunks[-max_summary_chunks_from_file:]
            return '--ChunkBreak--'.join(latest_summaries)


def get_latest_memory_chunks_with_hashes_since_last_summary(discussion_id: str) -> List[Tuple[str, str]]:
    """
    Retrieves memory chunks and their corresponding hashes from the memory file, starting from the last processed
    memory hash in the summary file.

    Args:
        discussion_id (str): The discussion ID.

    Returns:
        List[Tuple[str, str]]: A list of tuples where each tuple is (hash, memory chunk).
    """
    # Fetch memory and summary file paths
    memory_filepath = get_discussion_memory_file_path(discussion_id)
    summary_filepath = get_discussion_chat_summary_file_path(discussion_id)

    # Get all memory chunks with hashes
    all_memory_chunks = read_chunks_with_hashes(memory_filepath)  # Returns [(hash, chunk), ...]

    # If no memory chunks exist, return an empty list
    if not all_memory_chunks:
        return []

    # Get the last used hash from the summary file
    summary_chunks = read_chunks_with_hashes(summary_filepath)  # Returns [(hash, chunk), ...]

    # If the summary file exists and has chunks, find the last matching hash
    if summary_chunks:
        last_used_hash = summary_chunks[-1][1]  # The hash of the last summary

        # Find the index of the last used memory chunk
        last_used_index_from_end = find_how_many_new_memories_since_last_summary(summary_chunks, all_memory_chunks)
        logger.debug("Finding last memory chunk for summary. Index from end is: {}".format(last_used_index_from_end))

        # If a match is found
        if last_used_index_from_end is not None:
            # Calculate the correct index in the memory array
            actual_index = len(all_memory_chunks) - last_used_index_from_end
            logger.debug("Calculated actual index: {}".format(actual_index))

            # If the last used memory is the last item in all_memory_chunks, return an empty list
            if actual_index == len(all_memory_chunks):
                logger.debug("All memories are up to date. Returning empty array.")
                return []

            # Otherwise, return only the chunks after the last used memory
            logger.debug("Returning new memory chunks starting from index: {}".format(actual_index))
            return all_memory_chunks[actual_index:]

    # If no matching hash is found, or the summary file is empty, return all memory chunks
    logger.debug("No matching memory chunk found in summary. Returning all chunks.")
    return all_memory_chunks


def get_chat_summary_memories(messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0) -> str:
    """
    Retrieves chat summary memories from messages or memory files.

    Args:
        messages (List[Dict[str, str]]): The list of recent chat messages.
        max_turns_to_search (int): Maximum turns to search in the chat history.

    Returns:
        str: The chat summary memories concatenated as a single string with '--ChunkBreak--' delimiter.
    """
    logger.debug("Entered get_chat_summary_memories")

    # If no discussion ID is provided, fall back to recent chat messages
    if discussion_id is None:
        final_pairs = get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
        logger.debug(f"Chat Summary memory gathering complete. Total number of pair chunks: {len(final_pairs)}")
        return '\n------------\n'.join(final_pairs)

    # Use the new method to get memory chunks with hashes after the last summary
    memory_chunks_with_hashes = get_latest_memory_chunks_with_hashes_since_last_summary(discussion_id)

    # If no memory chunks are found, return an empty string
    if not memory_chunks_with_hashes:
        logger.debug("[DEBUG] No memory chunks found, returning an empty string.")
        return ''

    # Concatenate only the memory chunks (ignoring hashes)
    memory_chunks = [chunk for _, chunk in memory_chunks_with_hashes]

    return '\n------------\n'.join(memory_chunks)


def get_recent_chat_messages_up_to_max(max_turns_to_search: int, messages: List[Dict[str, str]]) -> List[str]:
    """
    Retrieves recent chat messages up to a maximum number of turns to search.

    Args:
        max_turns_to_search (int): Maximum number of turns to search in the chat history.
        messages (List[Dict[str, str]]): The list of recent chat messages.

    Returns:
        List[str]: The recent chat messages as a list of chunks.
    """
    if len(messages) <= 1:
        logger.debug("No memory chunks")
        return []

    logger.debug("Number of pairs: %s", str(len(messages)))

    # Take the last max_turns_to_search number of pairs from the collection
    message_copy = deepcopy(messages)
    if max_turns_to_search > 0:
        message_copy = message_copy[-min(max_turns_to_search, len(message_copy)):]

    logger.debug("Max turns to search: %s", str(max_turns_to_search))
    logger.info("Number of pairs: %s", str(len(message_copy)))

    pair_chunks = text_utils.get_message_chunks(message_copy, 0, 400)
    filtered_chunks = [s for s in pair_chunks if s]

    final_pairs = text_utils.clear_out_user_assistant_from_chunks(filtered_chunks)

    return final_pairs


def handle_get_current_summary_from_file(discussion_id: str):
    """
    Retrieves the current summary from a file based on the user's prompt.

    :param discussion_id: Discussion id used for memories and chat summary
    :return: The current summary extracted from the file or a message indicating the absence of a summary file.
    """
    filepath = get_discussion_chat_summary_file_path(discussion_id)

    current_summary = read_chunks_with_hashes(filepath)

    if current_summary is None or len(current_summary) == 0:
        return "There is not yet a summary file"

    return extract_text_blocks_from_hashed_chunks(current_summary)[0]


def handle_get_current_memories_from_file(discussion_id):
    """
    Retrieves the current summary from a file based on the user's prompt.

    :param discussion_id: Discussion id used for memories and chat summary
    :return: The current summary extracted from the file or a message indicating the absence of a summary file.
    """
    filepath = get_discussion_memory_file_path(discussion_id)

    current_memories = read_chunks_with_hashes(filepath)

    if current_memories is None or len(current_memories) == 0:
        return "There are not yet any memories"

    return extract_text_blocks_from_hashed_chunks(current_memories)
