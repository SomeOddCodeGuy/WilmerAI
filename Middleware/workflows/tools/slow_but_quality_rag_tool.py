import json
import logging
import os
import re
import threading
from copy import deepcopy
from dataclasses import replace as dc_replace
from typing import List, Dict, Any, Optional

from Middleware.services.embedding_service import EmbeddingService
from Middleware.services.llm_service import LlmHandlerService
from Middleware.services.memory_service import MemoryService
from Middleware.utilities import vector_db_utils, vector_math_utils
from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_endpoint_config, load_config, \
    get_discussion_id_workflow_path, get_discussion_condensation_tracker_file_path, get_estimation_level_multiplier, \
    get_discussion_state_document_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes, read_condensation_tracker, write_condensation_tracker, \
    read_plain_text_file, write_plain_text_file
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks, find_last_matching_hash_message, \
    chunk_messages_with_hashes, hash_single_message
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns
from Middleware.utilities.search_utils import filter_keywords_by_speakers, advanced_search_in_chunks, search_in_chunks
from Middleware.utilities.text_utils import get_message_chunks, clear_out_user_assistant_from_chunks, \
    rough_estimate_token_length
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

# Per-discussion locks to prevent concurrent condensation of the same memory file.
# Capped at _MAX_CONDENSATION_LOCKS to prevent unbounded growth on long-running servers.
_condensation_locks: Dict[str, threading.Lock] = {}
_condensation_locks_guard = threading.Lock()
_MAX_CONDENSATION_LOCKS = 500
# Bounded wait (seconds) for the per-discussion condensation lock. Generous on purpose:
# a concurrent request condensing a large memory file can legitimately hold the lock for
# minutes, and the bound only exists to stop a permanently-stuck holder from hanging the
# (often post-returnToUser) memory node, and its reader greenlet, for the life of the
# process. Override per workflow with 'condensationLockTimeoutSeconds'; set it to 0 (or
# negative) to wait indefinitely (the original, unbounded behavior).
_DEFAULT_CONDENSATION_LOCK_TIMEOUT_SECONDS = 600


def _get_condensation_lock(discussion_id: str) -> threading.Lock:
    """Returns a per-discussion lock, creating one if it doesn't exist yet."""
    with _condensation_locks_guard:
        if discussion_id not in _condensation_locks:
            if len(_condensation_locks) >= _MAX_CONDENSATION_LOCKS:
                # Evict the oldest entry (first key in insertion order),
                # but only if it is not currently held by another thread.
                oldest_key = next(iter(_condensation_locks))
                oldest_lock = _condensation_locks[oldest_key]
                if not oldest_lock.locked():
                    del _condensation_locks[oldest_key]
            _condensation_locks[discussion_id] = threading.Lock()
        return _condensation_locks[discussion_id]


class SlowButQualityRAGTool:
    """
    Handles the creation and storage of long-term conversational memories.

    This tool uses Large Language Models (LLMs) to perform Retrieval-Augmented
    Generation (RAG) on text chunks, generating summarized memories. It supports
    both file-based and vector-based memory storage and can be triggered via
    workflows to automatically process conversation history.
    """

    def __init__(self):
        self.memory_service = MemoryService()

    @staticmethod
    def _parse_llm_json_output(llm_output: str) -> Any:
        """
        Parses JSON from an LLM's output, accommodating markdown code blocks.

        Args:
            llm_output (str): The raw string output from the LLM.

        Returns:
            Any: The parsed Python dictionary or list, or None if parsing fails.
        """
        if not llm_output:
            logger.warning("Received empty or None output to parse for JSON.")
            return None
        # Regex to find JSON in a markdown block or a raw object/array
        match = re.search(r'```json\s*([\s\S]*?)\s*```|(\{[\s\S]*\}|\[[\s\S]*\])', llm_output)
        if match:
            # Prioritize the content of the markdown block if present
            json_str = match.group(1) if match.group(1) else match.group(2)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode extracted JSON string: {json_str}. Error: {e}")
                return None
        else:
            logger.warning("Could not find a JSON block or object in the LLM output.")
            return None

    def generate_and_store_vector_memories(self, hashed_chunks: List[tuple], config: Dict,
                                            context: ExecutionContext) -> int:
        """
        Generates and stores structured vector memories from text chunks.

        This method processes text chunks, generates structured JSON metadata using
        an LLM or a sub-workflow, and stores the resulting memory and metadata
        in the discussion-specific vector database. After each chunk is successfully
        processed, the corresponding hash is written to the hash log, making the
        process resumable if interrupted.

        Args:
            hashed_chunks (List[tuple]): A list of tuples, each containing (text_chunk, hash).
            config (Dict): The configuration dictionary for this memory operation.
            context (ExecutionContext): The current workflow execution context.

        Returns:
            int: The total number of memories successfully stored in the vector database.
        """
        rag_system_prompt = "You are an expert AI assistant that analyzes text and outputs a structured JSON object..."
        rag_prompt = """Analyze the following memory text and generate a JSON object...
Memory Text:
[TextChunk]
JSON Output:"""

        vector_workflow_name = config.get('vectorMemoryWorkflowName')
        llm_handler = None
        if not vector_workflow_name:
            endpoint_name = config.get('vectorMemoryEndpointName', config.get('endpointName'))
            preset_name = config.get('vectorMemoryPreset', config.get('preset'))
            max_tokens = config.get("vectorMemoryMaxResponseSizeInTokens", 1024)
            endpoint_data = get_endpoint_config(endpoint_name)
            llm_handler_service = LlmHandlerService()
            llm_handler = llm_handler_service.initialize_llm_handler(
                endpoint_data, preset_name, endpoint_name, False,
                endpoint_data.get("maxContextTokenSize", 4096), max_tokens
            )

        temp_llm_context = dc_replace(context, llm_handler=llm_handler, config=config)

        total_memories_stored = 0

        for chunk, chunk_hash in hashed_chunks:
            if not chunk.strip():
                continue

            json_string_output = None
            if vector_workflow_name:
                logger.info(f"Using workflow '{vector_workflow_name}' to generate vector memory.")
                scoped_inputs = [chunk]
                json_string_output = context.workflow_manager.run_custom_workflow(
                    workflow_name=vector_workflow_name,
                    request_id=context.request_id,
                    discussion_id=context.discussion_id,
                    messages=context.messages,
                    non_responder=True,
                    scoped_inputs=scoped_inputs,
                    api_key=context.api_key
                )
            else:
                json_string_output = self.process_single_chunk(
                    chunk, rag_prompt, rag_system_prompt, temp_llm_context
                )

            if json_string_output:
                parsed_json = self._parse_llm_json_output(json_string_output)

                memories_to_process = []
                if isinstance(parsed_json, dict):
                    memories_to_process.append(parsed_json)
                elif isinstance(parsed_json, list):
                    memories_to_process = parsed_json

                successful_adds = 0
                stored_summaries = []
                stored_id_text_pairs = []
                for memory_metadata in memories_to_process:
                    if isinstance(memory_metadata, dict):
                        required_keys = ['title', 'summary', 'entities', 'key_phrases']
                        if all(k in memory_metadata for k in required_keys):
                            memory_summary = memory_metadata['summary']
                            memory_id = vector_db_utils.add_memory_to_vector_db(
                                context.discussion_id,
                                memory_summary,
                                json.dumps(memory_metadata),
                                api_key_hash=context.api_key_hash,
                                index_topics=bool(config.get('vectorMemoryIndexTopics', False)),
                            )
                            if memory_id is not None:
                                successful_adds += 1
                                stored_summaries.append(memory_summary)
                                stored_id_text_pairs.append((memory_id, memory_summary))

                if successful_adds > 0:
                    # Write the hash immediately after successfully storing memories for this chunk
                    # This makes the process resumable: if interrupted, we can pick up from the last hash
                    vector_db_utils.add_vector_check_hash(
                        context.discussion_id, chunk_hash, api_key_hash=context.api_key_hash
                    )
                    logger.info(
                        f"Successfully generated and stored {successful_adds} vector memory/memories for discussion {context.discussion_id}. Hash logged for resumability.")
                    total_memories_stored += successful_adds
                    # Both run after the hash log on purpose: a failure in either must
                    # not cause this chunk's facts to be re-extracted (and duplicated in
                    # the vector DB) on the next pass. The facts stay searchable either way.
                    self._store_embeddings_for_new_memories(config, context, stored_id_text_pairs)
                    self._update_state_document(config, context, stored_summaries)
                elif memories_to_process:
                    logger.error(
                        "Vector DB rejected all %d parsed memory/memories for this chunk; "
                        "hash not logged, chunk will be retried on the next pass.",
                        len(memories_to_process))
                else:
                    logger.error("Received empty response from LLM/workflow for vector memory generation.")

        return total_memories_stored

    def _store_embeddings_for_new_memories(self, config: Dict, context: ExecutionContext,
                                           id_text_pairs: List[tuple]) -> None:
        """
        Embeds newly stored vector memories, plus a lazy backfill batch.

        Runs only when 'embeddingEndpointName' is set in the discussion ID
        workflow settings. In addition to the just-stored memories, up to
        'embeddingBackfillBatchSize' (default 20) older memories that lack an
        embedding for the endpoint's model are embedded in the same call, so a
        pre-embedding database heals gradually with no bulk migration.

        Best-effort by design: any failure is logged and swallowed. Memories
        without embeddings remain fully searchable via BM25, and hybrid search
        degrades gracefully, so a down embeddings endpoint costs nothing but
        semantic coverage.

        Args:
            config (Dict): The discussion ID workflow settings dictionary.
            context (ExecutionContext): The current workflow execution context.
            id_text_pairs (List[tuple]): (memory_id, memory_text) pairs for the
                memories just stored in this chunk.
        """
        endpoint_name = config.get('embeddingEndpointName')
        if not endpoint_name:
            return

        service = None
        try:
            service = EmbeddingService(endpoint_name)
            pairs = list(id_text_pairs)

            backfill_limit = config.get('embeddingBackfillBatchSize', 20)
            if not isinstance(backfill_limit, int) or isinstance(backfill_limit, bool):
                logger.warning(
                    "embeddingBackfillBatchSize must be an integer (0 disables backfill). "
                    "Ignoring: %r", backfill_limit)
                backfill_limit = 0
            if backfill_limit > 0:
                known_ids = {memory_id for memory_id, _ in pairs}
                backlog = vector_db_utils.get_memories_without_embeddings(
                    context.discussion_id, service.model_name, limit=backfill_limit,
                    api_key_hash=context.api_key_hash)
                pairs.extend((row['id'], row['memory_text']) for row in backlog
                             if row['id'] not in known_ids)

            if not pairs:
                return

            vectors = service.get_embeddings([text for _, text in pairs],
                                             request_id=context.request_id)
            if not vectors:
                logger.error("Embeddings endpoint '%s' returned no vectors; skipping embedding storage.",
                             endpoint_name)
                return

            blobs = [(memory_id, vector_math_utils.vector_to_blob(vector))
                     for (memory_id, _), vector in zip(pairs, vectors)]
            stored = vector_db_utils.add_embeddings_to_db(
                context.discussion_id, blobs, service.model_name,
                api_key_hash=context.api_key_hash)
            logger.info("Stored %d embedding(s) for discussion %s (model '%s').",
                        stored, context.discussion_id, service.model_name)
        except Exception as e:
            logger.error("Failed to store embeddings for discussion '%s': %s",
                         context.discussion_id, e, exc_info=True)
        finally:
            if service:
                service.close()

    # Only guard against a shrink when the existing document has meaningful size;
    # small documents legitimately fluctuate while the early conversation settles.
    STATE_DOCUMENT_SHRINK_GUARD_FLOOR_CHARS = 500

    def _update_state_document(self, config: Dict, context: ExecutionContext,
                               new_memory_texts: List[str]) -> None:
        """
        Merges newly created vector memories into the discussion's state document.

        Runs the sub-workflow named by 'stateDocumentWorkflowName' with two scoped
        inputs: the new memory texts (agent1Input) and the current state document
        (agent2Input). The workflow's final output replaces the document on disk.
        The update is best-effort: any failure is logged and swallowed so that
        vector memory storage, which has already succeeded and been hash-logged,
        is never affected.

        Safety guards protect the existing document from a misbehaving LLM:
        an empty output is rejected; an output that shrinks the document below
        'stateDocumentMinRetentionRatio' (default 0.5) of its previous size is
        rejected; and the previous version is copied to 'state_document.md.bak'
        before every overwrite.

        Args:
            config (Dict): The discussion ID workflow settings dictionary.
            context (ExecutionContext): The current workflow execution context.
            new_memory_texts (List[str]): The memory summaries just stored for one chunk.
        """
        if not config.get('useStateDocument', False):
            return
        workflow_name = config.get('stateDocumentWorkflowName')
        if not workflow_name:
            logger.error(
                "useStateDocument is true but no stateDocumentWorkflowName is configured; "
                "skipping state document update.")
            return
        if not new_memory_texts:
            return

        try:
            filepath = get_discussion_state_document_file_path(
                context.discussion_id, api_key_hash=context.api_key_hash)
            current_document = read_plain_text_file(filepath, encryption_key=context.encryption_key)

            new_facts = '\n'.join(f'- {text}' for text in new_memory_texts)
            scoped_inputs = [new_facts, current_document]

            updated_document = context.workflow_manager.run_custom_workflow(
                workflow_name=workflow_name,
                request_id=context.request_id,
                discussion_id=context.discussion_id,
                messages=context.messages,
                non_responder=True,
                scoped_inputs=scoped_inputs,
                api_key=context.api_key
            )

            if not updated_document or not str(updated_document).strip():
                logger.error(
                    "State document workflow '%s' returned empty output; keeping existing document.",
                    workflow_name)
                return

            updated_document = str(updated_document).strip()

            retention_ratio = config.get('stateDocumentMinRetentionRatio', 0.5)
            if (retention_ratio and len(current_document) > self.STATE_DOCUMENT_SHRINK_GUARD_FLOOR_CHARS
                    and len(updated_document) < retention_ratio * len(current_document)):
                logger.error(
                    "State document workflow '%s' shrank the document from %d to %d characters, below "
                    "the minimum retention ratio of %s; keeping existing document. If this shrink was "
                    "intended, lower 'stateDocumentMinRetentionRatio' in the discussion ID workflow "
                    "settings.",
                    workflow_name, len(current_document), len(updated_document), retention_ratio)
                return

            write_plain_text_file(filepath, updated_document,
                                  encryption_key=context.encryption_key,
                                  backup_suffix='.bak')
            logger.info("State document updated for discussion %s (%d -> %d characters).",
                        context.discussion_id, len(current_document), len(updated_document))
        except Exception as e:
            logger.error("Failed to update state document for discussion '%s': %s",
                         context.discussion_id, e, exc_info=True)

    def perform_keyword_search(self, keywords: str, target: str, context: ExecutionContext):
        """
        Routes a keyword search to the appropriate target data source.

        Args:
            keywords (str): The keywords to search for.
            target (str): The target location to search ("CurrentConversation" or "RecentMemories").
            context (ExecutionContext): The current workflow execution context.

        Returns:
            str: The search results, formatted as a string.
        """
        lookback_start_turn = context.config.get("lookbackStartTurn", 0)
        if target == "CurrentConversation":
            if not context.messages:
                logger.error("Fatal Workflow Error: cannot perform keyword search; no user prompt")
                return ""
            return self.perform_conversation_search(keywords, context, lookback_start_turn)
        elif target == "RecentMemories":
            return self.perform_memory_file_keyword_search(keywords, context)
        return ""

    def perform_conversation_search(self, keywords: str, context: ExecutionContext, lookbackStartTurn=0):
        """
        Performs a keyword search within the current conversation history.

        Args:
            keywords (str): The keywords to search for.
            context (ExecutionContext): The current workflow execution context.
            lookbackStartTurn (int): The turn number to start the search from.

        Returns:
            str: The search results, formatted as a string with "--ChunkBreak--" delimiters.
        """
        if len(context.messages) <= lookbackStartTurn:
            return 'There are no memories. This conversation has not gone long enough for there to be memories.'
        message_copy = deepcopy(context.messages)
        pair_chunks = get_message_chunks(message_copy, lookbackStartTurn, 400)
        last_n_turns = extract_last_n_turns(message_copy, 10, context.llm_handler.takes_message_collection)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        search_result_chunks = advanced_search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]
        return '--ChunkBreak--'.join(filtered_chunks)

    def perform_memory_file_keyword_search(self, keywords: str, context: ExecutionContext):
        """
        Performs a keyword search within the persisted file-based memories.

        Args:
            keywords (str): The keywords to search for.
            context (ExecutionContext): The current workflow execution context.

        Returns:
            str: The search results, formatted as a string with newline delimiters.
        """
        if not context.discussion_id:
            logger.debug("No discussion_id available, cannot search memory files.")
            return ""
        api_key_hash = context.api_key_hash
        encryption_key = context.encryption_key
        filepath = get_discussion_memory_file_path(context.discussion_id, api_key_hash=api_key_hash)
        hash_chunks = read_chunks_with_hashes(filepath, encryption_key=encryption_key)
        pair_chunks = extract_text_blocks_from_hashed_chunks(hash_chunks)
        if len(pair_chunks) > 3:
            pair_chunks = pair_chunks[:-3]
        last_n_turns = extract_last_n_turns(deepcopy(context.messages), 10,
                                            context.llm_handler.takes_message_collection)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        search_result_chunks = search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]
        return '\n\n'.join(filtered_chunks)

    @staticmethod
    def _resolve_condensation_lock_timeout(workflow_config: Dict) -> float:
        """Returns the bounded wait (seconds) for the per-discussion condensation lock.

        Reads 'condensationLockTimeoutSeconds' from the memory workflow config, defaulting
        to a generous bound. A value of 0 or negative means wait indefinitely (restoring
        the original unbounded behavior). A non-numeric value falls back to the default.

        Args:
            workflow_config (Dict): The memory workflow config; may carry
                'condensationLockTimeoutSeconds'.

        Returns:
            float: The lock wait in seconds (0 or negative means wait indefinitely).
        """
        raw = workflow_config.get('condensationLockTimeoutSeconds', _DEFAULT_CONDENSATION_LOCK_TIMEOUT_SECONDS)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(_DEFAULT_CONDENSATION_LOCK_TIMEOUT_SECONDS)

    def handle_discussion_id_flow(self, context: ExecutionContext, force_file_memory: bool = False) -> None:
        """
        Handles the automatic generation of long-term memories for a conversation.

        This is the main entry point for automatic memory creation. It checks if
        new messages have been added since the last run and, if certain thresholds
        are met, triggers the generation of either vector or file-based memories.

        Args:
            context (ExecutionContext): The current workflow execution context.
            force_file_memory (bool): If True, forces the file-based memory path, ignoring the config.
        """
        if not context.discussion_id:
            logger.debug("No discussion_id, skipping memory generation.")
            return

        if len(context.messages) < 3:
            logger.debug("Less than 3 messages, no memory will be generated.")
            return

        messages_copy = [m for m in deepcopy(context.messages) if m.get('role') != 'system']
        # This method uses a specific, separate config file to govern its behavior.
        discussion_id_workflow_config = load_config(get_discussion_id_workflow_path())
        use_vector_memory_from_config = discussion_id_workflow_config.get('useVectorForQualityMemory', False)

        if use_vector_memory_from_config and not force_file_memory:
            vector_db_utils.initialize_vector_db(context.discussion_id, api_key_hash=context.api_key_hash)
            logger.debug("Running vector memory check.")

            lookback_turns = discussion_id_workflow_config.get('lookbackStartTurn', 3)
            if len(messages_copy) <= lookback_turns:
                return

            # Define the boundary for eligible messages (we won't process the last few turns)
            end_index = len(messages_copy) - lookback_turns

            # 1. Get the history of the last N hashes, not just one.
            hash_history = vector_db_utils.get_vector_check_hash_history(
                context.discussion_id, limit=10, api_key_hash=context.api_key_hash
            )

            start_index = 0  # Default to the beginning if no hash is found
            if hash_history:
                # Build a hash-to-index lookup for eligible messages (O(n) instead of O(n*m))
                msg_hash_to_index = {}
                for i in range(end_index):
                    msg_hash = hash_single_message(messages_copy[i])
                    msg_hash_to_index[msg_hash] = i  # Last occurrence wins

                found_match = False
                for historical_hash in hash_history:
                    matched_idx = msg_hash_to_index.get(historical_hash)
                    if matched_idx is not None:
                        start_index = matched_idx + 1
                        found_match = True
                        logger.info(
                            f"Found matching historical hash at message index {matched_idx}. Starting memory generation from there.")
                        break

                if not found_match:
                    logger.warning(
                        f"Could not find any of the last {len(hash_history)} historical hashes for {context.discussion_id}. Reprocessing all eligible messages.")

            new_message_content_to_process = []
            if start_index < end_index:
                new_message_content_to_process = messages_copy[start_index:end_index]

            if new_message_content_to_process:
                chunk_size = discussion_id_workflow_config.get('vectorMemoryChunkEstimatedTokenSize', 1000)
                # Calibrate the token threshold for this memory config's model. Wilmer's
                # estimator over-counts on efficient large-vocab tokenizers, which would
                # trigger and size chunks on too little real content; the config-local
                # wilmerContextEstimationLevel scales the estimate-space threshold up so a
                # chunk holds the intended amount of real text (conservative = 1.0 =
                # unchanged). Memory bypasses dispatch, so this is NOT gated on the clamp;
                # the level value in this config is the opt-in.
                chunk_size = int(chunk_size * get_estimation_level_multiplier(discussion_id_workflow_config))
                max_messages = discussion_id_workflow_config.get('vectorMemoryMaxMessagesBetweenChunks', 5)

                token_count = rough_estimate_token_length(
                    '\n'.join(m['content'] for m in new_message_content_to_process if 'content' in m)
                )

                logger.info(
                    f"Vector memory trigger check: {len(new_message_content_to_process)} new messages, "
                    f"~{token_count} estimated tokens. "
                    f"Thresholds: {max_messages} messages / {chunk_size} tokens.")

                trigger_by_tokens = token_count >= chunk_size
                trigger_by_messages = len(new_message_content_to_process) >= max_messages

                if not trigger_by_tokens and not trigger_by_messages:
                    logger.info("Neither threshold met. No vector memories generated.")
                    return

                if trigger_by_tokens and trigger_by_messages:
                    logger.info("Both thresholds met (tokens and messages). Generating vector memories.")
                elif trigger_by_tokens:
                    logger.info("Token threshold met. Generating vector memories.")
                else:
                    logger.info("Message count threshold met. Generating vector memories.")

                hashed_chunks = chunk_messages_with_hashes(new_message_content_to_process, chunk_size)
                text_chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)

                if not text_chunks:
                    logger.info("No text chunks produced. No memories generated.")
                else:
                    # Pass hashed_chunks so that hashes are written after each successful chunk,
                    # making the process resumable if interrupted
                    memories_stored = self.generate_and_store_vector_memories(hashed_chunks, discussion_id_workflow_config, context)
                    if memories_stored > 0:
                        logger.info(f"Completed vector memory generation. Total memories stored: {memories_stored}.")
                    else:
                        logger.warning("Chunking produced text but no memories were successfully stored.")
        else:
            # This is the file-based memory path
            logger.debug("Running file-based memory check.")
            api_key_hash = context.api_key_hash
            encryption_key = context.encryption_key
            filepath = get_discussion_memory_file_path(context.discussion_id, api_key_hash=api_key_hash)
            # Check file existence BEFORE read_chunks_with_hashes, which creates the file
            # as an empty [] if it doesn't exist. We need to distinguish between:
            # - File doesn't exist: consolidation mode (user deleted it to regenerate)
            # - File exists (even if empty): standard mode (both thresholds active)
            file_exists = os.path.exists(filepath)
            discussion_chunks = read_chunks_with_hashes(filepath, encryption_key=encryption_key)
            lookback_turns = discussion_id_workflow_config.get('lookbackStartTurn', 3)
            new_message_content_to_process = []
            if not discussion_chunks:
                if len(messages_copy) > lookback_turns:
                    new_message_content_to_process = messages_copy[:-lookback_turns]
            else:
                num_new_messages = find_last_matching_hash_message(
                    messages_copy,
                    discussion_chunks,
                    turns_to_skip_looking_back=lookback_turns
                )
                if num_new_messages > 0:
                    end_index = len(messages_copy) - lookback_turns
                    start_index = end_index - num_new_messages
                    new_message_content_to_process = messages_copy[max(0, start_index):end_index]

            if not new_message_content_to_process:
                logger.debug("No new messages to process for memories.")
                return

            logger.info(f"Found {len(new_message_content_to_process)} new messages to consider for memory generation.")
            chunk_size = discussion_id_workflow_config.get('chunkEstimatedTokenSize', 1000)
            # Calibrate the token threshold for this memory config's model (see the
            # vector-memory path above): the config-local wilmerContextEstimationLevel
            # scales the estimate-space threshold up for efficient tokenizers so a chunk
            # holds the intended real content. Conservative (default) = 1.0 = unchanged;
            # not gated on the dispatch clamp (the level value is the opt-in).
            chunk_size = int(chunk_size * get_estimation_level_multiplier(discussion_id_workflow_config))
            max_messages = discussion_id_workflow_config.get('maxMessagesBetweenChunks', 5)
            token_count = rough_estimate_token_length(
                '\n'.join(m['content'] for m in new_message_content_to_process if 'content' in m)
            )

            logger.info(f"Memory trigger check: {len(new_message_content_to_process)} new messages, "
                        f"~{token_count} estimated tokens. "
                        f"Thresholds: {max_messages} messages / {chunk_size} tokens. "
                        f"Memory file exists: {file_exists}")

            trigger_by_tokens = token_count >= chunk_size
            trigger_by_messages = file_exists and len(new_message_content_to_process) >= max_messages

            if trigger_by_tokens or trigger_by_messages:
                if trigger_by_tokens and trigger_by_messages:
                    logger.info("Both thresholds met (tokens and messages). Generating new memories.")
                elif trigger_by_tokens:
                    logger.info("Token threshold met. Generating new memories.")
                else:
                    logger.info("Message count threshold met. Generating new memories.")
                hashed_chunks = chunk_messages_with_hashes(new_message_content_to_process, chunk_size)
                text_chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)
                if len(hashed_chunks) >= 1:
                    logger.info("Using original file-based memory creation flow.")
                    rag_system_prompt = discussion_id_workflow_config.get('systemPrompt', '')
                    rag_prompt = discussion_id_workflow_config.get('prompt', '')
                    # Hold the per-discussion lock across both write and condensation
                    # to prevent concurrent memory operations from overwriting each other.
                    # Wait is bounded so a stuck holder can't hang this (often
                    # post-returnToUser) node forever; on timeout we skip this round
                    # rather than proceed unlocked (which would risk the very overwrite
                    # the lock prevents). The work is self-healing: the unprocessed
                    # messages still meet the threshold on the next qualifying turn.
                    lock = _get_condensation_lock(context.discussion_id)
                    lock_timeout = self._resolve_condensation_lock_timeout(discussion_id_workflow_config)
                    acquired = lock.acquire() if lock_timeout <= 0 else lock.acquire(timeout=lock_timeout)
                    if not acquired:
                        logger.warning(
                            "Could not acquire the condensation lock for discussion %s within %ss; "
                            "skipping memory generation this round (it will retry on the next "
                            "qualifying turn). Set 'condensationLockTimeoutSeconds' to 0 to wait "
                            "indefinitely.",
                            context.discussion_id, lock_timeout,
                        )
                    else:
                        try:
                            self.process_new_memory_chunks(text_chunks, hashed_chunks, rag_system_prompt, rag_prompt,
                                                           discussion_id_workflow_config, context)
                            # When regenerating after file deletion, seed the condensation tracker
                            # with the latest memory hash so condensation starts fresh from here.
                            if not file_exists and discussion_id_workflow_config.get('condenseMemories', False):
                                tracker_path = get_discussion_condensation_tracker_file_path(context.discussion_id, api_key_hash=api_key_hash)
                                last_hash = hashed_chunks[-1][1]
                                write_condensation_tracker(tracker_path, {'lastCondensationHash': last_hash}, encryption_key=encryption_key)
                                logger.info(
                                    f"Memory file was regenerated from scratch. "
                                    f"Seeded condensation tracker with latest hash for {context.discussion_id}."
                                )
                            self._condense_memories_already_locked(context.discussion_id, discussion_id_workflow_config, context)
                        finally:
                            lock.release()
            else:
                if not file_exists:
                    logger.info("Thresholds not met. Memory file does not exist; message threshold is disabled "
                                "(consolidation mode). Only token threshold applies.")
                else:
                    logger.info("Thresholds not met. No new memories will be generated this time.")

    def process_new_memory_chunks(self, chunks, hash_chunks, rag_system_prompt, rag_prompt, workflow_config,
                                  context: ExecutionContext, chunks_per_memory=3):
        """
        Processes new text chunks to generate and store file-based memories.

        Args:
            chunks (List[str]): The new text chunks to summarize into memories.
            hash_chunks (List[Tuple[str, str]]): Tuples of (text_chunk, hash) for the new chunks.
            rag_system_prompt (str): The system prompt for the summarization LLM call.
            rag_prompt (str): The user prompt for the summarization LLM call.
            workflow_config (Dict): The configuration for this memory operation.
            context (ExecutionContext): The current workflow execution context.
            chunks_per_memory (int): The number of chunks to process per memory generation.
        """
        all_chunks = "--ChunkBreak--".join(chunks)
        result = self.perform_rag_on_memory_chunk(rag_system_prompt, rag_prompt, all_chunks, context, workflow_config,
                                                  "--rag_break--", chunks_per_memory)
        results = result.split("--rag_break--")
        if len(results) != len(hash_chunks):
            logger.warning(
                "RAG result count (%d) does not match hash_chunks count (%d); "
                "zip will truncate to the shorter list.",
                len(results), len(hash_chunks)
            )
        replaced = [(summary, hash_code) for summary, (_, hash_code) in zip(results, hash_chunks)]
        api_key_hash = context.api_key_hash
        encryption_key = context.encryption_key
        filepath = get_discussion_memory_file_path(context.discussion_id, api_key_hash=api_key_hash)
        existing_chunks = read_chunks_with_hashes(filepath, encryption_key=encryption_key)
        updated_chunks = existing_chunks + replaced
        update_chunks_with_hashes(updated_chunks, filepath, mode="overwrite", encryption_key=encryption_key)

    def perform_rag_on_conversation_chunk(self, rag_system_prompt: str, rag_prompt: str, text_chunk: str,
                                          context: ExecutionContext) -> str:
        """
        Performs RAG on a single chunk from the current conversation.

        Args:
            rag_system_prompt (str): The system prompt for the summarization LLM call.
            rag_prompt (str): The user prompt for the summarization LLM call.
            text_chunk (str): The raw text chunk from the conversation to process.
            context (ExecutionContext): The current workflow execution context.

        Returns:
            str: The generated summary string.
        """
        if not context.discussion_id:
            logger.debug("SlowButQualityRAGTool: No discussion_id, skipping file-based RAG.")
            return ""
        return self.perform_rag_on_memory_chunk(
            rag_system_prompt, rag_prompt, text_chunk, context, context.config,
            custom_delimiter="", chunks_per_memory=context.config.get('chunksPerMemory', 3)
        )

    def perform_rag_on_memory_chunk(self, rag_system_prompt: str, rag_prompt: str, text_chunk: str,
                                    context: ExecutionContext, workflow_config: Dict, custom_delimiter: str = "",
                                    chunks_per_memory: int = 3) -> str:
        """
        Performs RAG on text chunks to generate file-based memory summaries.

        This can operate using a direct LLM call or by executing a specified
        sub-workflow for more complex summarization logic.

        Args:
            rag_system_prompt (str): The system prompt for the summarization LLM call.
            rag_prompt (str): The user prompt for the summarization LLM call.
            text_chunk (str): A string containing one or more text chunks, delimited by '--ChunkBreak--'.
            context (ExecutionContext): The current workflow execution context.
            workflow_config (Dict): The specific configuration for this memory generation task.
            custom_delimiter (str): The delimiter to join the resulting summaries.
            chunks_per_memory (int): The number of chunks to process per memory generation.

        Returns:
            str: A string of the generated summaries, joined by the custom delimiter.
        """
        chunks = text_chunk.split('--ChunkBreak--')
        api_key_hash = context.api_key_hash
        encryption_key = context.encryption_key
        discussion_chunks = read_chunks_with_hashes(
            get_discussion_memory_file_path(context.discussion_id, api_key_hash=api_key_hash),
            encryption_key=encryption_key
        )
        memory_chunks = extract_text_blocks_from_hashed_chunks(discussion_chunks)
        chat_summary = self.memory_service.get_current_summary(context.discussion_id,
                                                        encryption_key=context.encryption_key,
                                                        api_key_hash=context.api_key_hash)

        endpoint_name = workflow_config.get('endpointName')
        preset_name = workflow_config.get('preset')
        max_tokens = workflow_config.get("maxResponseSizeInTokens", 400)
        endpoint_data = get_endpoint_config(endpoint_name)
        llm_handler_service = LlmHandlerService()
        llm_handler = llm_handler_service.initialize_llm_handler(
            endpoint_data, preset_name, endpoint_name, False,
            endpoint_data.get("maxContextTokenSize", 4096), max_tokens
        )

        temp_llm_context = dc_replace(context, llm_handler=llm_handler, config=workflow_config)

        # Note: The 'fileMemoryWorkflowName' should be in 'workflow_config', not 'context.config'
        file_workflow_name = workflow_config.get('fileMemoryWorkflowName')
        result_chunks = []
        for chunk in chunks:
            current_memories = '\n--------------\n'.join(memory_chunks[-3:]) or "No preceding memories to show"
            full_memories = '\n--------------\n'.join(memory_chunks) or "No preceding memories to show"
            result_chunk = ""
            if file_workflow_name:
                logger.info(f"Using workflow '{file_workflow_name}' to generate file-based memory.")
                scoped_inputs = [chunk, current_memories.strip(), full_memories.strip(), chat_summary.strip()]
                result_chunk = context.workflow_manager.run_custom_workflow(
                    workflow_name=file_workflow_name, request_id=context.request_id,
                    discussion_id=context.discussion_id, messages=context.messages,
                    non_responder=True, scoped_inputs=scoped_inputs,
                    api_key=context.api_key
                )
            else:
                system_prompt = rag_system_prompt.replace('[Memory_file]', current_memories.strip()).replace(
                    '[Full_Memory_file]', full_memories.strip()).replace('[Chat_Summary]', chat_summary.strip())
                prompt = rag_prompt.replace('[Memory_file]', current_memories.strip()).replace(
                    '[Full_Memory_file]', full_memories.strip()).replace('[Chat_Summary]', chat_summary.strip())
                result_chunk = self.process_single_chunk(chunk, prompt, system_prompt, temp_llm_context)

            result_chunks.append(result_chunk)
            memory_chunks.append(result_chunk)
        return custom_delimiter.join(result_chunks)

    @staticmethod
    def process_single_chunk(chunk: str, workflow_prompt: str, workflow_system_prompt: str,
                             context: ExecutionContext) -> str:
        """
        Processes a single text chunk using a direct LLM call.

        Args:
            chunk (str): The raw text chunk to send to the LLM.
            workflow_prompt (str): The user prompt template.
            workflow_system_prompt (str): The system prompt template.
            context (ExecutionContext): The execution context containing the LLM handler and variables.

        Returns:
            str: The raw string response from the LLM.
        """
        llm_handler = context.llm_handler
        if not llm_handler or not llm_handler.llm:  # Added a check for the internal llm object
            logger.error("LLM handler or its internal llm is not available in the context for process_single_chunk.")
            return ""

        formatted_prompt = context.workflow_variable_service.apply_variables(workflow_prompt, context,
                                                                             remove_all_system_override=True)
        formatted_system_prompt = context.workflow_variable_service.apply_variables(workflow_system_prompt, context,
                                                                                    remove_all_system_override=True)

        formatted_prompt = formatted_prompt.replace('[TextChunk]', chunk)
        formatted_system_prompt = formatted_system_prompt.replace('[TextChunk]', chunk)

        if not llm_handler.takes_message_collection:
            return llm_handler.llm.get_response_from_llm(
                system_prompt=formatted_system_prompt,
                prompt=formatted_prompt,
                llm_takes_images=False,
                request_id=context.request_id
            )
        else:
            collection = []
            if formatted_system_prompt:
                collection.append({"role": "system", "content": formatted_system_prompt})
            if formatted_prompt:
                collection.append({"role": "user", "content": formatted_prompt})
            return llm_handler.llm.get_response_from_llm(
                collection,
                llm_takes_images=False,
                request_id=context.request_id
            )

    @staticmethod
    def _get_condensation_threshold(workflow_config: Dict) -> Optional[int]:
        """Returns memoriesBeforeCondensation when condensation is enabled and configured.

        Args:
            workflow_config (Dict): The memory workflow configuration.

        Returns:
            Optional[int]: The threshold, or None when condensation is disabled or
                misconfigured (the misconfiguration is logged).
        """
        if not workflow_config.get('condenseMemories', False):
            return None
        memories_before_condensation = workflow_config.get('memoriesBeforeCondensation')
        if memories_before_condensation is None:
            logger.error("condenseMemories is enabled but memoriesBeforeCondensation is not set. Skipping.")
            return None
        return memories_before_condensation

    def _condense_memories_already_locked(self, discussion_id: str, workflow_config: Dict,
                                          context: ExecutionContext) -> None:
        """Runs condensation assuming the caller already holds the per-discussion lock."""
        memories_before_condensation = self._get_condensation_threshold(workflow_config)
        if memories_before_condensation is None:
            return

        self._condense_memories_locked(discussion_id, workflow_config, context,
                                       memories_before_condensation)

    def condense_memories(self, discussion_id: str, workflow_config: Dict,
                          context: ExecutionContext) -> None:
        """
        Condenses older file-based memories into a single summary memory.

        When enabled via `condenseMemories: true` in the workflow config, this method
        checks whether enough new memories have accumulated since the last condensation.
        If the threshold is met, it takes the oldest N memories (excluding a configurable
        buffer of the most recent ones) and replaces them with a single LLM-generated
        condensed summary.

        The condensation state is tracked in a separate file
        (`{discussion_id}_condensation_tracker.json`) to avoid modifying the memory
        file's schema.

        Args:
            discussion_id (str): The ID of the discussion.
            workflow_config (Dict): The discussion ID workflow configuration dictionary.
            context (ExecutionContext): The current workflow execution context.
        """
        memories_before_condensation = self._get_condensation_threshold(workflow_config)
        if memories_before_condensation is None:
            return

        lock = _get_condensation_lock(discussion_id)
        if not lock.acquire(blocking=False):
            logger.info(f"Condensation already in progress for {discussion_id}. Skipping.")
            return

        try:
            self._condense_memories_locked(discussion_id, workflow_config, context,
                                           memories_before_condensation)
        finally:
            lock.release()

    def _condense_memories_locked(self, discussion_id: str, workflow_config: Dict,
                                  context: ExecutionContext,
                                  memories_before_condensation: int) -> None:
        """Inner condensation logic, called while holding the per-discussion lock."""
        buffer_size = workflow_config.get('memoryCondensationBuffer', 0)
        required_new = memories_before_condensation + buffer_size

        api_key_hash = context.api_key_hash
        encryption_key = context.encryption_key
        filepath = get_discussion_memory_file_path(discussion_id, api_key_hash=api_key_hash)
        all_memories = read_chunks_with_hashes(filepath, encryption_key=encryption_key)

        if not all_memories:
            logger.debug("No memories to condense.")
            return

        tracker_path = get_discussion_condensation_tracker_file_path(discussion_id, api_key_hash=api_key_hash)
        tracker = read_condensation_tracker(tracker_path, encryption_key=encryption_key)
        last_hash = tracker.get('lastCondensationHash')

        new_start_index = 0
        if last_hash:
            found = False
            for i, (text, h) in enumerate(all_memories):
                if h == last_hash:
                    new_start_index = i + 1
                    found = True
                    break
            if not found:
                logger.warning(
                    f"Condensation tracker hash not found in memory file for {discussion_id}. "
                    f"Treating all memories as new."
                )
                new_start_index = 0

        new_memories = all_memories[new_start_index:]
        new_count = len(new_memories)

        if new_count < required_new:
            logger.debug(
                f"Not enough new memories for condensation ({new_count} < {required_new}). Skipping."
            )
            return

        memories_to_condense = new_memories[:memories_before_condensation]

        separator = '\n--------------\n'
        combined_text = separator.join(text for text, _ in memories_to_condense)

        condense_start_index = new_start_index
        preceding_start = max(0, condense_start_index - 3)
        preceding_memories = all_memories[preceding_start:condense_start_index]
        preceding_text = separator.join(text for text, _ in preceding_memories) if preceding_memories else "No preceding memories to show"

        default_system_prompt = (
            "You are an expert summarizer. You take a collection of conversation memories "
            "and condense them into a single, cohesive summary that preserves all important "
            "details, context, and narrative flow."
        )
        default_prompt = (
            "A user is currently in an online conversation via a chat program. Over the course "
            "of the conversation, memories have been generated summarizing what has transpired.\n\n"
            "The most recent memories leading up to the ones being condensed, if any exist, can "
            "be found here:\n\n"
            "<preceding_memories>\n"
            "[Memories_Before_Memories_to_Condense]\n"
            "</preceding_memories>\n\n"
            "The following are the memories to be condensed into a single cohesive summary:\n\n"
            "<memories_to_condense>\n"
            "[MemoriesToCondense]\n"
            "</memories_to_condense>\n\n"
            "Please condense the memories within <memories_to_condense> into a single cohesive "
            "summary that captures all key details, events, and context. Preserve names, important "
            "facts, and the narrative flow. If preceding memories exist, write the condensed summary "
            "as a continuation of those events. Please respond with text only."
        )

        system_prompt = workflow_config.get('condenseMemoriesSystemPrompt', default_system_prompt)
        prompt = workflow_config.get('condenseMemoriesPrompt', default_prompt)
        prompt = prompt.replace('[MemoriesToCondense]', combined_text)
        prompt = prompt.replace('[Memories_Before_Memories_to_Condense]', preceding_text)
        system_prompt = system_prompt.replace('[Memories_Before_Memories_to_Condense]', preceding_text)

        endpoint_name = workflow_config.get(
            'condenseMemoriesEndpointName',
            workflow_config.get('endpointName')
        )
        preset_name = workflow_config.get(
            'condenseMemoriesPreset',
            workflow_config.get('preset')
        )
        max_tokens = workflow_config.get(
            'condenseMemoriesMaxResponseSizeInTokens',
            workflow_config.get('maxResponseSizeInTokens', 500)
        )

        endpoint_data = get_endpoint_config(endpoint_name)
        llm_handler_service = LlmHandlerService()
        llm_handler = llm_handler_service.initialize_llm_handler(
            endpoint_data, preset_name, endpoint_name, False,
            endpoint_data.get("maxContextTokenSize", 4096), max_tokens
        )

        temp_context = dc_replace(context, llm_handler=llm_handler, config=workflow_config)

        condensed_text = self.process_single_chunk(
            combined_text, prompt, system_prompt, temp_context
        )

        if not condensed_text or not condensed_text.strip():
            logger.error(
                f"LLM returned empty response for memory condensation on {discussion_id}. "
                f"Preserving original memories."
            )
            return

        # Assign the final hash of the batch so the tracker can locate this condensed entry
        # next run and avoid re-condensing the same memories.
        condensed_hash = memories_to_condense[-1][1]

        prefix = all_memories[:new_start_index]
        suffix = new_memories[memories_before_condensation:]
        updated_memories = prefix + [(condensed_text, condensed_hash)] + suffix

        update_chunks_with_hashes(updated_memories, filepath, mode="overwrite", encryption_key=encryption_key)
        write_condensation_tracker(tracker_path, {'lastCondensationHash': condensed_hash}, encryption_key=encryption_key)

        logger.info(
            f"Condensed {memories_before_condensation} memories into 1 for {discussion_id}. "
            f"New total: {len(updated_memories)} memories."
        )
