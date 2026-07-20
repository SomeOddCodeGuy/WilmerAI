# Middleware/services/memory_service.py
import json
import logging
from typing import Dict, List, Tuple, Optional

from Middleware.services.embedding_service import EmbeddingService
from Middleware.utilities import text_utils, vector_db_utils, vector_math_utils
from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_discussion_chat_summary_file_path, \
    get_discussion_state_document_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, read_plain_text_file
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks
from Middleware.utilities.sensitive_logging_utils import sensitive_log

logger = logging.getLogger(__name__)

# Entity expansion harvests entities from this many top base-search results.
ENTITY_EXPANSION_SEED_ROWS = 10


class MemoryService:
    """
    A service class responsible for all business logic related to managing
    and retrieving conversational memory and summaries.
    """

    def search_vector_memories(self, discussion_id: str, keywords: str, limit: int = 5,
                                api_key_hash: Optional[str] = None,
                                bm25_weights: Optional[List[float]] = None,
                                use_recency: bool = False,
                                include_dates: bool = False,
                                search_mode: str = "keyword",
                                semantic_query: Optional[str] = None,
                                embedding_endpoint_name: Optional[str] = None,
                                use_entity_expansion: bool = False,
                                request_id: Optional[str] = None) -> str:
        """
        Searches for memories in the vector database.

        Three search modes are supported:
          - "keyword" (default): FTS5/BM25 keyword search, the historical behavior.
          - "semantic": cosine similarity over stored embeddings.
          - "hybrid": both, merged with Reciprocal Rank Fusion.
        Semantic and hybrid modes require an embeddings endpoint; if it is
        missing, the embedding call fails, or no embeddings have been stored
        yet, the search degrades gracefully to keyword results rather than
        failing the workflow.

        When use_entity_expansion is True, entities named in the top base
        results become the query for a second keyword pass, and a portion of
        the result slots is reserved for memories only that second pass
        found. This bridges facts connected by an entity the query could
        not name (e.g. "what does the user's sister do?" -> a first hit names
        the sister as Sarah -> the second pass finds Sarah's job). The
        expansion pass is pure FTS/BM25 and works in every search mode; it
        never requires an embeddings endpoint.

        Args:
            discussion_id (str): The ID of the conversation.
            keywords (str): A semicolon-separated keyword string for BM25 search.
            limit (int): The maximum number of memories to return.
            api_key_hash (Optional[str]): Pre-computed hash for per-user
                directory isolation. Forwarded to the vector DB so the
                correct per-user discussion folder is used.
            bm25_weights (Optional[List[float]]): Five per-column BM25 weights,
                forwarded to the search. None keeps equal weighting.
            use_recency (bool): If True, newer memories receive a rank boost.
            include_dates (bool): If True, each result is prefixed with the date
                the memory was created (e.g. "[2024-03-15]"), letting the LLM
                arbitrate between contradictory facts from different eras.
            search_mode (str): "keyword", "semantic", or "hybrid".
            semantic_query (Optional[str]): Raw text to embed as the semantic
                query. Defaults to the keyword string with semicolons replaced
                by spaces when omitted.
            embedding_endpoint_name (Optional[str]): The embeddings endpoint
                config name. Required for semantic and hybrid modes.
            use_entity_expansion (bool): If True, runs the entity-expansion
                second pass described above. Expansion-only hits are appended
                after the base results. Defaults to False (no behavior change).
            request_id (Optional[str]): The request ID, forwarded to the
                embedding call so client cancellation can abort an in-flight
                semantic query instead of waiting out its read timeout.

        Returns:
            str: A string containing the formatted search results, or a message if none were found.
        """
        if not discussion_id:
            return "Cannot search vector memories without a discussionId."

        sensitive_log(logger, logging.INFO, "Searching vector memories for discussion '%s' with keywords: '%s'",
                     discussion_id, keywords)

        mode = (search_mode or "keyword").lower()
        if mode not in ("keyword", "semantic", "hybrid"):
            logger.warning("Unknown searchMode '%s'; falling back to keyword search.", search_mode)
            mode = "keyword"
        if mode in ("semantic", "hybrid") and not embedding_endpoint_name:
            logger.error("searchMode '%s' requires an embeddingEndpointName; "
                         "falling back to keyword search.", mode)
            mode = "keyword"

        keyword_rows = []
        if mode in ("keyword", "hybrid"):
            keyword_rows = vector_db_utils.search_memories_by_keyword(
                discussion_id, keywords, limit, api_key_hash=api_key_hash,
                bm25_weights=bm25_weights, use_recency=use_recency
            )

        semantic_ids: List[int] = []
        if mode in ("semantic", "hybrid"):
            query_text = (semantic_query or keywords.replace(';', ' ')).strip()
            found_ids = self._search_semantic_memory_ids(
                discussion_id, query_text, limit, embedding_endpoint_name, api_key_hash,
                request_id=request_id)
            if found_ids is None:
                logger.error("Semantic search failed; falling back to keyword-only results.")
            else:
                semantic_ids = found_ids
            if mode == "semantic" and not semantic_ids:
                # Degrade to keyword search so the workflow still gets results.
                # Covers the embedding call failing (None) as well as an empty
                # semantic result: no stored embeddings yet (the lazy-backfill
                # window) or an empty query text.
                if found_ids is not None:
                    logger.info("Semantic search produced no ranked ids; "
                                "falling back to keyword search.")
                keyword_rows = vector_db_utils.search_memories_by_keyword(
                    discussion_id, keywords, limit, api_key_hash=api_key_hash,
                    bm25_weights=bm25_weights, use_recency=use_recency
                )

        if semantic_ids and keyword_rows:
            keyword_ids = [row['id'] for row in keyword_rows]
            merged_ids = vector_math_utils.reciprocal_rank_fusion([keyword_ids, semantic_ids])[:limit]
            rows_by_id = {row['id']: row for row in keyword_rows}
            missing_ids = [mid for mid in merged_ids if mid not in rows_by_id]
            for row in vector_db_utils.get_memories_by_ids(discussion_id, missing_ids,
                                                           api_key_hash=api_key_hash):
                rows_by_id[row['id']] = row
            found_memories = [rows_by_id[mid] for mid in merged_ids if mid in rows_by_id]
        elif semantic_ids:
            found_memories = vector_db_utils.get_memories_by_ids(
                discussion_id, semantic_ids[:limit], api_key_hash=api_key_hash)
        else:
            found_memories = keyword_rows

        if use_entity_expansion and found_memories:
            found_memories = self._expand_with_entity_pass(
                discussion_id, keywords, found_memories, limit,
                api_key_hash=api_key_hash, bm25_weights=bm25_weights,
                use_recency=use_recency)

        if not found_memories:
            return "No relevant memories found in the vector database for the given keywords."

        # The `memory_text` for a vector memory is the summary generated by the LLM.
        return self.format_memory_rows(found_memories, include_dates=include_dates)

    @staticmethod
    def _expand_with_entity_pass(discussion_id: str, keywords: str, base_rows: List,
                                 limit: int, api_key_hash: Optional[str] = None,
                                 bm25_weights: Optional[List[float]] = None,
                                 use_recency: bool = False) -> List:
        """
        Runs the entity-expansion second search pass over a base result set.

        Entities listed in the metadata of the top base results (minus any
        that were already query terms) become the query for a second FTS/BM25
        pass, a deterministic one-hop lookup of everything stored about the
        entities the base search surfaced. The original terms are deliberately
        NOT repeated in the second pass: re-including them lets every seed row
        re-match on its own entities and crowd true bridge hits out of the
        ranking. Memories only the second pass found ("novel" hits) are
        guaranteed a reserved share of the final result slots (roughly a
        third) because a hit reachable only through a bridge entity would
        otherwise rank below memories matched by the original query terms.
        Novel hits are appended after the base results so the strongest
        direct matches keep their position.

        Args:
            discussion_id (str): The ID of the conversation.
            keywords (str): The original semicolon-separated keyword string.
            base_rows (List): The base search results (mapping-style rows with
                'id' and 'metadata_json').
            limit (int): The maximum number of results to return overall.
            api_key_hash (Optional[str]): Pre-computed hash for directory isolation.
            bm25_weights (Optional[List[float]]): Forwarded to the second pass.
            use_recency (bool): Forwarded to the second pass.

        Returns:
            List: The blended rows, at most `limit` long. Returns base_rows
            unchanged when no new entities or no novel hits are found.
        """
        original_terms = [k.strip() for k in keywords.split(';') if k.strip()]
        seen_terms = {term.lower() for term in original_terms}

        harvested = []
        for row in base_rows[:ENTITY_EXPANSION_SEED_ROWS]:
            try:
                metadata = json.loads(row['metadata_json'] or '{}')
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            entities = metadata.get('entities', []) if isinstance(metadata, dict) else []
            if not isinstance(entities, list):
                continue
            for entity in entities:
                term = str(entity).strip()
                if term and term.lower() not in seen_terms:
                    seen_terms.add(term.lower())
                    harvested.append(term)

        if not harvested:
            return base_rows
        harvested = harvested[:vector_db_utils.MAX_KEYWORDS_FOR_SEARCH]

        expanded_query = '; '.join(harvested)
        sensitive_log(logger, logging.INFO,
                      "Entity expansion running a second pass on %d harvested entity term(s): %s",
                      len(harvested), harvested)

        expansion_rows = vector_db_utils.search_memories_by_keyword(
            discussion_id, expanded_query, limit, api_key_hash=api_key_hash,
            bm25_weights=bm25_weights, use_recency=use_recency)

        base_ids = {row['id'] for row in base_rows}
        novel = [row for row in expansion_rows if row['id'] not in base_ids]
        if not novel:
            return base_rows

        # Never let expansion evict the strongest direct match: reserved slots
        # are capped so at least one base row always survives.
        reserved = min(max(1, limit // 3), len(novel), max(0, limit - 1))
        kept = base_rows[:max(0, limit - reserved)]
        blended = kept + novel[:limit - len(kept)]
        logger.debug("Entity expansion surfaced %d novel memory/memories; returning %d total.",
                     len(novel), len(blended))
        return blended

    @staticmethod
    def _search_semantic_memory_ids(discussion_id: str, query_text: str, limit: int,
                                    embedding_endpoint_name: str,
                                    api_key_hash: Optional[str],
                                    request_id: Optional[str] = None) -> Optional[List[int]]:
        """
        Ranks stored memory embeddings against an embedded query text.

        Args:
            discussion_id (str): The ID of the conversation.
            query_text (str): The raw text to embed as the query.
            limit (int): The maximum number of ids to return.
            embedding_endpoint_name (str): The embeddings endpoint config name.
            api_key_hash (Optional[str]): Pre-computed hash for directory isolation.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            Optional[List[int]]: Ranked memory ids (best first); an empty list
            when there is nothing to search; or None when the embedding call
            failed and the caller should degrade to keyword search.
        """
        if not query_text:
            return []

        service = None
        try:
            service = EmbeddingService(embedding_endpoint_name)
            vectors = service.get_embeddings([query_text], request_id=request_id)
            if not vectors:
                return None
            stored = vector_db_utils.get_all_embeddings(
                discussion_id, service.model_name, api_key_hash=api_key_hash)
            if not stored:
                logger.info("No stored embeddings for model '%s' in discussion '%s' yet.",
                            service.model_name, discussion_id)
                return []
            ranked = vector_math_utils.rank_by_cosine(vectors[0], stored, limit)
            return [memory_id for memory_id, _ in ranked]
        except Exception as e:
            logger.error("Semantic memory search failed for discussion '%s': %s",
                         discussion_id, e, exc_info=True)
            return None
        finally:
            if service:
                service.close()

    @staticmethod
    def format_memory_rows(rows, include_dates: bool = False) -> str:
        """
        Formats memory rows into the standard delimited result string.

        Args:
            rows: An iterable of mapping-style rows with 'memory_text' and,
                when dates are requested, 'date_added' (ISO-8601 string).
            include_dates (bool): If True, prefixes each memory with the date
                portion of its date_added (e.g. "[2024-03-15]"). Rows without a
                parseable date are emitted without a prefix.

        Returns:
            str: The memory texts joined by the standard separator.
        """
        formatted = []
        for row in rows:
            text = row['memory_text']
            if include_dates:
                try:
                    date_added = row['date_added']
                except (KeyError, IndexError):
                    date_added = None
                if date_added:
                    # date_added is written as an ISO-8601 string; the first 10
                    # characters are the YYYY-MM-DD date portion.
                    formatted.append(f"[{str(date_added)[:10]}] {text}")
                    continue
            formatted.append(text)

        return '\n\n---\n\n'.join(formatted)

    def get_recent_memories(self, messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0,
                            max_summary_chunks_from_file=0, lookback_start=0,
                            encryption_key: Optional[bytes] = None,
                            api_key_hash: Optional[str] = None) -> str:
        """
        Retrieves recent memories from chat messages or memory files.

        Args:
            messages (List[Dict[str, str]]): The list of chat messages for stateless mode.
            discussion_id (str): The ID of the discussion for stateful mode.
            max_turns_to_search (int): Max number of turns to look back in stateless mode.
            max_summary_chunks_from_file (int): Max number of memory chunks to get from a file.
            lookback_start (int): Number of messages to skip from the end.

        Returns:
            str: A string of memory chunks joined by '--ChunkBreak--'.
        """
        logger.debug("Entered MemoryService.get_recent_memories")
        if discussion_id is None:
            final_pairs = self._get_recent_chat_messages_up_to_max(max_turns_to_search, messages, lookback_start)
            logger.debug("Recent Memory complete. Total number of pair chunks: {}".format(len(final_pairs)))
            return '--ChunkBreak--'.join(final_pairs)
        else:
            filepath = get_discussion_memory_file_path(discussion_id, api_key_hash=api_key_hash)
            hashed_chunks = read_chunks_with_hashes(filepath, encryption_key=encryption_key)
            if not hashed_chunks:
                return "No memories have been generated yet"

            chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)
            if max_summary_chunks_from_file == -1:
                return '--ChunkBreak--'.join(chunks)

            # Default to 3 chunks when the caller passes 0 (meaning "use default").
            # 3 is a balance between recency (capturing the latest context) and avoiding
            # excessive repetition, since adjacent memory chunks often overlap in content.
            # Python slice handles lists shorter than max_chunks without error.
            max_chunks = max_summary_chunks_from_file or 3
            return '--ChunkBreak--'.join(chunks[-max_chunks:])

    def get_latest_memory_chunks_with_hashes_since_last_summary(self, discussion_id: str,
                                                                encryption_key: Optional[bytes] = None,
                                                                api_key_hash: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Retrieves memory chunks and hashes since the last summary was created.

        Args:
            discussion_id (str): The ID of the discussion.
            encryption_key (Optional[bytes]): Pre-computed Fernet key for file encryption.
            api_key_hash (Optional[str]): Pre-computed hash for directory isolation.

        Returns:
            List[Tuple[str, str]]: A list of (text, hash) tuples for new memory chunks.
        """
        memory_filepath = get_discussion_memory_file_path(discussion_id, api_key_hash=api_key_hash)
        all_memory_chunks = read_chunks_with_hashes(memory_filepath, encryption_key=encryption_key)
        if not all_memory_chunks:
            return []

        summary_filepath = get_discussion_chat_summary_file_path(discussion_id, api_key_hash=api_key_hash)
        summary_chunks = read_chunks_with_hashes(summary_filepath, encryption_key=encryption_key)
        if summary_chunks:
            last_used_index_from_end = self.find_how_many_new_memories_since_last_summary(summary_chunks,
                                                                                          all_memory_chunks)
            if last_used_index_from_end != -1:
                actual_index = len(all_memory_chunks) - last_used_index_from_end
                if actual_index == len(all_memory_chunks):
                    return []
                return all_memory_chunks[actual_index:]

        return all_memory_chunks

    def get_chat_summary_memories(self, messages: List[Dict[str, str]], discussion_id: str,
                                  max_turns_to_search=0,
                                  encryption_key: Optional[bytes] = None,
                                  api_key_hash: Optional[str] = None) -> str:
        """
        Gathers new memories that need to be incorporated into a long-term chat summary.

        Args:
            messages (List[Dict[str, str]]): The chat messages for stateless mode.
            discussion_id (str): The ID of the discussion for stateful mode.
            max_turns_to_search (int): Max number of turns to look back in stateless mode.

        Returns:
            str: A string of new memory chunks to be summarized, joined by newlines.
        """
        if discussion_id is None:
            final_pairs = self._get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
            return '\n------------\n'.join(final_pairs)

        memory_chunks_with_hashes = self.get_latest_memory_chunks_with_hashes_since_last_summary(
            discussion_id, encryption_key=encryption_key, api_key_hash=api_key_hash)
        if not memory_chunks_with_hashes:
            return ''

        memory_chunks = [text_block for text_block, _ in memory_chunks_with_hashes]
        return '\n------------\n'.join(memory_chunks)

    def _get_recent_chat_messages_up_to_max(self, max_turns_to_search: int, messages: List[Dict[str, str]],
                                            lookback_start: int = 0) -> List[str]:
        """
        Internal helper to get recent chat messages up to a maximum number of turns.

        Args:
            max_turns_to_search (int): The maximum number of turns to retrieve.
            messages (List[Dict[str, str]]): The full list of chat messages.
            lookback_start (int): Number of messages to skip from the end.

        Returns:
            List[str]: A list of formatted message chunks.
        """
        if len(messages) <= 1 or lookback_start >= len(messages):
            return ["There are no memories to grab yet"]

        start_index = len(messages) - lookback_start
        end_index = max(0, start_index - max_turns_to_search)
        selected_messages = messages[end_index:start_index]

        if not selected_messages:
            return ["There are no memories to grab yet"]

        pair_chunks = text_utils.get_message_chunks(selected_messages, 0, 400)
        filtered_chunks = [s for s in pair_chunks if s]
        return text_utils.clear_out_user_assistant_from_chunks(filtered_chunks)

    def get_current_summary(self, discussion_id: str,
                            encryption_key: Optional[bytes] = None,
                            api_key_hash: Optional[str] = None) -> str:
        """
        Retrieves the most recent full summary text from its file.

        Args:
            discussion_id (str): The ID of the discussion.
            encryption_key (Optional[bytes]): Pre-computed Fernet key for file encryption.
            api_key_hash (Optional[str]): Pre-computed hash for directory isolation.

        Returns:
            str: The text of the most recent chat summary.
        """
        filepath = get_discussion_chat_summary_file_path(discussion_id, api_key_hash=api_key_hash)
        current_summary_chunks = read_chunks_with_hashes(filepath, encryption_key=encryption_key)

        if not current_summary_chunks:
            return "There is not yet a summary file"

        return extract_text_blocks_from_hashed_chunks(current_summary_chunks)[0]

    def get_current_state_document(self, discussion_id: str,
                                   encryption_key: Optional[bytes] = None,
                                   api_key_hash: Optional[str] = None) -> str:
        """
        Retrieves the current state document text for a discussion.

        The state document is the continuously updated markdown document that
        holds the current ground-truth state of the conversation's subject
        matter (for example a user profile, or roleplay world state). It is
        written by the vector memory pipeline when the state document feature
        is enabled in the discussion ID workflow settings.

        Args:
            discussion_id (str): The ID of the discussion.
            encryption_key (Optional[bytes]): Pre-computed Fernet key for file encryption.
            api_key_hash (Optional[str]): Pre-computed hash for directory isolation.

        Returns:
            str: The state document text, or a placeholder message if none exists.
        """
        filepath = get_discussion_state_document_file_path(discussion_id, api_key_hash=api_key_hash)
        content = read_plain_text_file(filepath, encryption_key=encryption_key)

        if not content.strip():
            return "No state document has been created yet"

        return content

    def get_current_memories(self, discussion_id: str,
                             encryption_key: Optional[bytes] = None,
                             api_key_hash: Optional[str] = None) -> List[str]:
        """
        Retrieves all current memory chunk texts from their file.

        Args:
            discussion_id (str): The ID of the discussion.
            encryption_key (Optional[bytes]): Pre-computed Fernet key for file encryption.
            api_key_hash (Optional[str]): Pre-computed hash for directory isolation.

        Returns:
            List[str]: A list containing all memory chunk texts.
        """
        filepath = get_discussion_memory_file_path(discussion_id, api_key_hash=api_key_hash)
        current_memory_chunks = read_chunks_with_hashes(filepath, encryption_key=encryption_key)

        if not current_memory_chunks:
            return ["There are not yet any memories"]

        return extract_text_blocks_from_hashed_chunks(current_memory_chunks)

    def find_how_many_new_memories_since_last_summary(self, hashed_summary_chunk: Optional[List[Tuple[str, str]]],
                                                      hashed_memory_chunks: List[Tuple[str, str]]) -> int:
        """
        Finds the number of new memories created since the last summary.

        Args:
            hashed_summary_chunk (Optional[List[Tuple[str, str]]]): The hashed chunks from the summary file.
            hashed_memory_chunks (List[Tuple[str, str]]): The hashed chunks from the memory file.

        Returns:
            int: The number of new memories, or -1 if no match is found.
        """
        if not hashed_memory_chunks:
            return -1
        if not hashed_summary_chunk:
            return len(hashed_memory_chunks)

        summary_hash = hashed_summary_chunk[-1][1]
        memory_hashes = [hash_tuple[1] for hash_tuple in hashed_memory_chunks]

        try:
            # Reverse the list so that index() searches from the newest chunk backward.
            # The position of summary_hash in the reversed list equals the number of
            # memory chunks that were added after it, i.e. the count of new memories
            # since the last summary was written.
            return memory_hashes[::-1].index(summary_hash)
        except ValueError:
            return -1
