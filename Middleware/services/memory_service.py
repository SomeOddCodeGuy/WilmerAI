# /Middleware/services/memory_service.py

import logging
from copy import deepcopy
from typing import Dict, List, Tuple, Optional

from Middleware.utilities import text_utils
from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_discussion_chat_summary_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks

logger = logging.getLogger(__name__)


class MemoryService:
    """
    A service class responsible for all business logic related to managing
    and retrieving conversational memory and summaries.
    """

    def get_recent_memories(self, messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0,
                            max_summary_chunks_from_file=0, lookback_start=0) -> str:
        """
        Retrieves recent memories from chat messages or memory files.

        Args:
            messages (List[Dict[str, str]]): The list of recent chat messages.
            discussion_id (str): The ID for the discussion to pull file-based memories.
            max_turns_to_search (int): Maximum turns to search in the chat history.
            max_summary_chunks_from_file (int): Maximum summary chunks to retrieve from memory files.
            lookback_start (int): Number of messages to go back before starting to pull messages for the memory

        Returns:
            str: The recent memories concatenated as a single string with '--ChunkBreak--' delimiter.
        """
        logger.debug("Entered MemoryService.get_recent_memories")

        if discussion_id is None:
            final_pairs = self._get_recent_chat_messages_up_to_max(max_turns_to_search, messages, lookback_start)
            logger.debug("Recent Memory complete. Total number of pair chunks: {}".format(len(final_pairs)))
            return '--ChunkBreak--'.join(final_pairs)
        else:
            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_chunks = read_chunks_with_hashes(filepath)
            if len(hashed_chunks) == 0:
                return "No memories have been generated yet"
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

    def get_latest_memory_chunks_with_hashes_since_last_summary(self, discussion_id: str) -> List[Tuple[str, str]]:
        """
        Retrieves memory chunks and their hashes from the memory file, starting from the last processed
        hash found in the corresponding summary file.

        Args:
            discussion_id (str): The discussion ID.

        Returns:
            List[Tuple[str, str]]: A list of new, unprocessed memory tuples of (hash, memory chunk).
        """
        memory_filepath = get_discussion_memory_file_path(discussion_id)
        summary_filepath = get_discussion_chat_summary_file_path(discussion_id)
        all_memory_chunks = read_chunks_with_hashes(memory_filepath)

        if not all_memory_chunks:
            return []

        summary_chunks = read_chunks_with_hashes(summary_filepath)
        if summary_chunks:
            last_used_index_from_end = self.find_how_many_new_memories_since_last_summary(summary_chunks, all_memory_chunks)
            logger.debug("Finding last memory chunk for summary. Index from end is: {}".format(last_used_index_from_end))

            if last_used_index_from_end is not None:
                actual_index = len(all_memory_chunks) - last_used_index_from_end
                logger.debug("Calculated actual index: {}".format(actual_index))

                if actual_index == len(all_memory_chunks):
                    logger.debug("All memories are up to date. Returning empty array.")
                    return []

                logger.debug("Returning new memory chunks starting from index: {}".format(actual_index))
                return all_memory_chunks[actual_index:]

        logger.debug("No matching memory chunk found in summary. Returning all chunks.")
        return all_memory_chunks

    def get_chat_summary_memories(self, messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0) -> str:
        """
        Gathers new memories that need to be incorporated into a long-term chat summary.

        Args:
            messages (List[Dict[str, str]]): The list of recent chat messages (used as fallback).
            discussion_id (str): The ID for the discussion to pull file-based memories.
            max_turns_to_search (int): Maximum turns to search in chat history if no discussion_id.

        Returns:
            str: The new memories concatenated as a single string with '------------' delimiter.
        """
        logger.debug("Entered MemoryService.get_chat_summary_memories")

        if discussion_id is None:
            final_pairs = self._get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
            logger.debug(f"Chat Summary memory gathering complete. Total number of pair chunks: {len(final_pairs)}")
            return '\n------------\n'.join(final_pairs)

        memory_chunks_with_hashes = self.get_latest_memory_chunks_with_hashes_since_last_summary(discussion_id)

        if not memory_chunks_with_hashes:
            logger.debug("[DEBUG] No new memory chunks found, returning an empty string.")
            return ''

        memory_chunks = [chunk for _, chunk in memory_chunks_with_hashes]
        return '\n------------\n'.join(memory_chunks)

    def _get_recent_chat_messages_up_to_max(self, max_turns_to_search: int, messages: List[Dict[str, str]],
                                            lookback_start: int = 0) -> List[str]:
        """
        Internal helper to retrieve recent chat messages up to a maximum number of turns.
        """
        if len(messages) <= 1:
            logger.debug("No memory chunks available.")
            return ["There are no memories to grab yet"]

        if lookback_start >= len(messages):
            logger.debug("Lookback start exceeds the total number of messages.")
            return ["There are no memories to grab yet"]

        message_copy = deepcopy(messages)
        start_index = max(0, len(message_copy) - lookback_start)
        end_index = max(0, start_index - max_turns_to_search)
        selected_messages = message_copy[end_index:start_index]

        if not selected_messages:
            logger.debug("No messages found within the specified range.")
            return ["There are no memories to grab yet"]

        pair_chunks = text_utils.get_message_chunks(selected_messages, 0, 400)
        filtered_chunks = [s for s in pair_chunks if s]
        return text_utils.clear_out_user_assistant_from_chunks(filtered_chunks)

    def get_current_summary(self, discussion_id: str) -> str:
        """
        Retrieves the most recent full summary text from its file.
        """
        filepath = get_discussion_chat_summary_file_path(discussion_id)
        current_summary_chunks = read_chunks_with_hashes(filepath)

        if not current_summary_chunks:
            return "There is not yet a summary file"

        return extract_text_blocks_from_hashed_chunks(current_summary_chunks)[0]

    def get_current_memories(self, discussion_id: str) -> List[str]:
        """
        Retrieves all current memory chunk texts from their file.
        """
        filepath = get_discussion_memory_file_path(discussion_id)
        current_memory_chunks = read_chunks_with_hashes(filepath)

        if not current_memory_chunks:
            return ["There are not yet any memories"]

        return extract_text_blocks_from_hashed_chunks(current_memory_chunks)


    def find_how_many_new_memories_since_last_summary(self, hashed_summary_chunk: Optional[List[Tuple[str, str]]],
                                                  hashed_memory_chunks: List[Tuple[str, str]]) -> int:
        """
        Find the index of the last hashed summary chunk that matches any hash in the hashed memory chunks.

        Parameters:
        hashed_summary_chunk (Optional[List[Tuple[str, str]]]): A list of tuples representing the hashed summary chunk, or None.
        hashed_memory_chunks (List[Tuple[str, str]]): A list of tuples representing the hashed memory chunks.

        Returns:
        int: The index of the last matching memory hash, or -1 if no match is found.
        """
        if not hashed_memory_chunks:
            return -1

        if not hashed_summary_chunk:
            return len(hashed_memory_chunks)

        summary_hash = hashed_summary_chunk[-1][1]

        memory_hashes = [hash_tuple[1] for hash_tuple in hashed_memory_chunks]

        return memory_hashes[::-1].index(summary_hash) if summary_hash in memory_hashes else -1