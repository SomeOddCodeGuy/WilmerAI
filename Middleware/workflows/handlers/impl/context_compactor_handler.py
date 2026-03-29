import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities.config_utils import (
    get_context_compactor_settings_path,
    get_discussion_context_compactor_old_file_path,
    get_discussion_context_compactor_oldest_file_path,
    load_config
)
from Middleware.utilities.file_utils import read_chunks_with_hashes, update_chunks_with_hashes
from Middleware.utilities.hashing_utils import hash_content
from Middleware.utilities.text_utils import rough_estimate_token_length
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

# Per-discussion locks to prevent concurrent compaction of the same discussion.
# Capped at _MAX_COMPACTOR_LOCKS to prevent unbounded growth on long-running servers.
_compactor_locks: Dict[str, threading.Lock] = {}
_compactor_locks_guard = threading.Lock()
_MAX_COMPACTOR_LOCKS = 500


def _get_compactor_lock(discussion_id: str) -> threading.Lock:
    """Returns a per-discussion lock for compaction, creating one if needed."""
    with _compactor_locks_guard:
        if discussion_id not in _compactor_locks:
            if len(_compactor_locks) >= _MAX_COMPACTOR_LOCKS:
                oldest_key = next(iter(_compactor_locks))
                oldest_lock = _compactor_locks[oldest_key]
                if not oldest_lock.locked():
                    del _compactor_locks[oldest_key]
            _compactor_locks[discussion_id] = threading.Lock()
        return _compactor_locks[discussion_id]


_BOUNDARY_SENTINEL = "__boundary__"


class ContextCompactorHandler(BaseHandler):
    """
    Handles the ContextCompactor node type.

    This handler compacts conversation history into two rolling summaries:
    - An 'Old' section with topic-aware detail, covering a configurable window
      of messages at medium distance from the end of the conversation.
    - An 'Oldest' section with a neutral rolling summary, covering all messages
      beyond the Old window.

    The handler uses token-based windowing to determine which messages fall into
    each section, and persists summaries to files keyed by discussion ID.
    """

    def __init__(self, workflow_manager: Any, workflow_variable_service: Any, **kwargs):
        super().__init__(workflow_manager, workflow_variable_service, **kwargs)
        self.llm_handler_service = LlmHandlerService()

    def handle(self, context: ExecutionContext) -> Any:
        """
        Main entry point for the ContextCompactor node.

        Loads settings, calculates message boundaries, determines whether
        compaction is needed, and if so, runs up to three LLM calls to
        generate or update the Old and Oldest summaries.

        Always returns the current summaries from files (if they exist),
        regardless of whether a new compaction was triggered.

        Args:
            context (ExecutionContext): The runtime context for this node.

        Returns:
            str: Formatted output with XML-style tags containing the summaries,
                 or an empty string if no summaries exist yet.
        """
        settings = self._load_settings()
        if settings is None:
            logger.warning("ContextCompactor: No settings file configured. Returning empty string.")
            return ""

        discussion_id = context.discussion_id
        if discussion_id is None:
            logger.warning("ContextCompactor: No discussion_id available. Returning empty string.")
            return ""

        messages = context.messages

        lookback_start_turn = settings.get("lookbackStartTurn", 5)
        recent_context_tokens = settings.get("recentContextTokens", 20000)
        old_context_tokens = settings.get("oldContextTokens", 20000)
        if lookback_start_turn > 0 and len(messages) > lookback_start_turn:
            working_messages = messages[:-lookback_start_turn]
        else:
            working_messages = messages

        if len(working_messages) < 2:
            logger.debug("ContextCompactor: Not enough messages after lookback skip. Returning cached or empty.")
            return self._return_cached_output(discussion_id, context=context)

        boundaries = self._calculate_boundaries(working_messages, recent_context_tokens, old_context_tokens)

        old_state = self._load_state(discussion_id, "old", context=context)
        oldest_state = self._load_state(discussion_id, "oldest", context=context)

        should_compact, has_boundary_shifted = self._should_compact(
            working_messages, boundaries, old_state
        )

        if not should_compact:
            logger.debug("ContextCompactor: No compaction needed. Returning cached summaries.")
            return self._return_cached_output(discussion_id, context=context)

        lock = _get_compactor_lock(discussion_id)
        if not lock.acquire(blocking=False):
            logger.info("Compaction already in progress for %s. Returning cached.", discussion_id)
            return self._return_cached_output(discussion_id, context=context)

        try:
            self._run_compaction(context, settings, working_messages, boundaries,
                                 old_state, oldest_state, has_boundary_shifted, discussion_id)
        finally:
            lock.release()

        return self._return_cached_output(discussion_id, context=context)

    def _load_settings(self) -> Optional[Dict[str, Any]]:
        """
        Loads the context compactor settings from the configured settings file.

        Returns:
            dict or None: The settings dictionary, or None if the settings file
                          is not configured or cannot be loaded.
        """
        try:
            settings_path = get_context_compactor_settings_path()
            return load_config(settings_path)
        except Exception as e:
            logger.error("ContextCompactor: Failed to load settings: %s", e)
            return None

    def _calculate_boundaries(self, messages: List[Dict[str, str]],
                              recent_context_tokens: int,
                              old_context_tokens: int) -> Dict[str, int]:
        """
        Calculates the message index boundaries for Recent, Old, and Oldest sections.

        Iterates from the end of the message list backwards, accumulating token
        counts to find where the Recent section ends and the Old section ends.

        Args:
            messages: The working messages (after lookback skip).
            recent_context_tokens: Token budget for the Recent (untouched) section.
            old_context_tokens: Token budget for the Old section.

        Returns:
            dict with keys:
                - 'recent_start_idx': Index where the Recent section begins
                                      (messages[recent_start_idx:] are recent)
                - 'old_start_idx': Index where the Old section begins
                                   (messages[old_start_idx:recent_start_idx] are old)
                - Everything before old_start_idx is in the Oldest territory.
        """
        total_messages = len(messages)

        token_count = 0
        recent_start_idx = total_messages
        for i in range(total_messages - 1, -1, -1):
            msg_tokens = rough_estimate_token_length(messages[i].get("content", ""))
            if token_count + msg_tokens > recent_context_tokens:
                recent_start_idx = i + 1
                break
            token_count += msg_tokens
        else:
            recent_start_idx = 0

        token_count = 0
        old_start_idx = recent_start_idx
        for i in range(recent_start_idx - 1, -1, -1):
            msg_tokens = rough_estimate_token_length(messages[i].get("content", ""))
            if token_count + msg_tokens > old_context_tokens:
                old_start_idx = i + 1
                break
            token_count += msg_tokens
        else:
            if recent_start_idx > 0:
                old_start_idx = 0

        return {
            "recent_start_idx": recent_start_idx,
            "old_start_idx": old_start_idx,
        }

    def _should_compact(self, messages: List[Dict[str, str]],
                        boundaries: Dict[str, int],
                        old_state: List[Tuple[str, str]]) -> Tuple[bool, bool]:
        """
        Determines whether a compaction cycle should run.

        Args:
            messages: The working messages.
            boundaries: The calculated boundaries dict.
            old_state: The existing Old section state from file.

        Returns:
            Tuple of (should_compact: bool, has_boundary_shifted: bool)
        """
        old_start_idx = boundaries["old_start_idx"]
        recent_start_idx = boundaries["recent_start_idx"]

        if old_start_idx >= recent_start_idx:
            return False, False

        if not old_state:
            return True, False

        raw_stored = old_state[-1][1]
        # Parse index:hash format; fall back to raw value for legacy entries
        stored_hash = raw_stored.split(':', 1)[1] if raw_stored and ':' in raw_stored else raw_stored
        current_boundary_hash = self._hash_message_content(
            messages[old_start_idx].get("content", "")
        ) if old_start_idx < len(messages) else None

        has_boundary_shifted = (stored_hash != current_boundary_hash)

        if has_boundary_shifted:
            return True, True

        stored_recent_hash = old_state[0][1]
        current_recent_hash = self._hash_message_content(
            messages[recent_start_idx - 1].get("content", "")
        ) if recent_start_idx > 0 and recent_start_idx <= len(messages) else None

        if stored_recent_hash != current_recent_hash:
            return True, False

        return False, False

    def _run_compaction(self, context: ExecutionContext, settings: Dict[str, Any],
                        messages: List[Dict[str, str]], boundaries: Dict[str, int],
                        old_state: List[Tuple[str, str]],
                        oldest_state: List[Tuple[str, str]],
                        has_boundary_shifted: bool, discussion_id: str) -> None:
        """
        Runs the compaction cycle: up to 3 LLM calls.

        Call 1: Generate Old section (topic-focused summary of the Old window).
        Call 2: Generate neutral summary of messages that shifted from Old to Oldest
                (only if boundary shifted).
        Call 3: Update the Oldest rolling summary with the neutral summary
                (only if boundary shifted).

        Args:
            context: The execution context.
            settings: The compactor settings.
            messages: The working messages.
            boundaries: The calculated boundaries.
            old_state: Existing Old section state.
            oldest_state: Existing Oldest section state.
            has_boundary_shifted: Whether messages shifted from Old to Oldest.
            discussion_id: The discussion ID for file persistence.
        """
        old_start_idx = boundaries["old_start_idx"]
        recent_start_idx = boundaries["recent_start_idx"]

        old_messages = messages[old_start_idx:recent_start_idx]
        recent_messages = messages[recent_start_idx:]

        old_summary = self._generate_old_section(old_messages, recent_messages, settings, context)

        old_boundary_hash = self._hash_message_content(
            messages[old_start_idx].get("content", "")
        ) if old_start_idx < len(messages) else ""
        recent_boundary_hash = self._hash_message_content(
            messages[recent_start_idx - 1].get("content", "")
        ) if recent_start_idx > 0 else ""

        old_chunks = [(old_summary, recent_boundary_hash), (_BOUNDARY_SENTINEL, f"{old_start_idx}:{old_boundary_hash}")]
        self._save_state(discussion_id, "old", old_chunks, context=context)

        if has_boundary_shifted and old_start_idx > 0:
            # Find where the previous Old boundary was. The stored value now
            # includes the message index for precise lookup, falling back to
            # a linear scan if the index no longer matches (conversation mutation).
            prev_old_start_idx = 0
            if old_state:
                stored_value = old_state[-1][1]
                if ':' in stored_value:
                    idx_str, stored_boundary_hash = stored_value.split(':', 1)
                    try:
                        idx = int(idx_str)
                        if idx < len(messages) and self._hash_message_content(messages[idx].get("content", "")) == stored_boundary_hash:
                            prev_old_start_idx = idx
                        else:
                            # Index no longer valid — fall back to scan
                            for i, msg in enumerate(messages):
                                if self._hash_message_content(msg.get("content", "")) == stored_boundary_hash:
                                    prev_old_start_idx = i
                                    break
                    except (ValueError, IndexError):
                        for i, msg in enumerate(messages):
                            if self._hash_message_content(msg.get("content", "")) == stored_value:
                                prev_old_start_idx = i
                                break
                else:
                    # Legacy format without index — scan
                    for i, msg in enumerate(messages):
                        if self._hash_message_content(msg.get("content", "")) == stored_value:
                            prev_old_start_idx = i
                            break

            shifted_messages = messages[prev_old_start_idx:old_start_idx]

            if shifted_messages:
                neutral_summary = self._generate_neutral_summary(shifted_messages, settings, context)

                existing_oldest = ""
                if oldest_state:
                    existing_oldest = oldest_state[0][0]

                updated_oldest = self._update_oldest_section(existing_oldest, neutral_summary, settings, context)

                oldest_hash = self._hash_message_content(
                    messages[0].get("content", "")
                )
                oldest_chunks = [(updated_oldest, oldest_hash)]
                self._save_state(discussion_id, "oldest", oldest_chunks, context=context)

    def _generate_old_section(self, old_messages: List[Dict[str, str]],
                              recent_messages: List[Dict[str, str]],
                              settings: Dict[str, Any],
                              context: ExecutionContext) -> str:
        """
        LLM Call 1: Generate a topic-focused summary of the Old window.

        Uses the recent messages as topic context so the summary focuses on
        details relevant to the current conversation direction.

        Args:
            old_messages: Messages in the Old window.
            recent_messages: Messages in the Recent window (for topic context).
            settings: The compactor settings.
            context: The execution context.

        Returns:
            str: The topic-focused summary.
        """
        system_prompt = settings.get("oldSectionSystemPrompt", "You are a summarization AI.")
        prompt_template = settings.get("oldSectionPrompt", "[MESSAGES_TO_SUMMARIZE]")

        messages_text = self._messages_to_text(old_messages)
        recent_text = self._messages_to_text(recent_messages)

        prompt = prompt_template.replace("[MESSAGES_TO_SUMMARIZE]", messages_text)
        prompt = prompt.replace("[RECENT_MESSAGES]", recent_text)

        result = self._call_llm(system_prompt, prompt, settings, context)
        if not result or not result.strip():
            logger.warning("LLM returned empty response for old section; preserving original text.")
            return messages_text
        return result

    def _generate_neutral_summary(self, shifted_messages: List[Dict[str, str]],
                                  settings: Dict[str, Any],
                                  context: ExecutionContext) -> str:
        """
        LLM Call 2: Generate a neutral (non-topic-biased) summary of messages
        that shifted from the Old window into Oldest territory.

        Args:
            shifted_messages: Messages that moved past the Old boundary.
            settings: The compactor settings.
            context: The execution context.

        Returns:
            str: The neutral summary.
        """
        system_prompt = settings.get("neutralSummarySystemPrompt", "You are a summarization AI.")
        prompt_template = settings.get("neutralSummaryPrompt", "[MESSAGES_TO_SUMMARIZE]")

        messages_text = self._messages_to_text(shifted_messages)
        prompt = prompt_template.replace("[MESSAGES_TO_SUMMARIZE]", messages_text)

        result = self._call_llm(system_prompt, prompt, settings, context)
        if not result or not result.strip():
            logger.warning("LLM returned empty response for neutral summary; preserving original text.")
            return messages_text
        return result

    def _update_oldest_section(self, existing_summary: str, new_content: str,
                               settings: Dict[str, Any],
                               context: ExecutionContext) -> str:
        """
        LLM Call 3: Incorporate a neutral summary into the existing rolling
        Oldest summary.

        Args:
            existing_summary: The current Oldest rolling summary.
            new_content: The neutral summary of newly shifted messages.
            settings: The compactor settings.
            context: The execution context.

        Returns:
            str: The updated rolling summary.
        """
        system_prompt = settings.get("oldestUpdateSystemPrompt", "You are a summarization AI.")
        prompt_template = settings.get("oldestUpdatePrompt", "[EXISTING_SUMMARY]\n\n[NEW_CONTENT]")

        prompt = prompt_template.replace("[EXISTING_SUMMARY]", existing_summary)
        prompt = prompt.replace("[NEW_CONTENT]", new_content)

        result = self._call_llm(system_prompt, prompt, settings, context)
        if not result or not result.strip():
            logger.warning("LLM returned empty response for oldest section update; preserving existing summary.")
            return existing_summary
        return result

    def _call_llm(self, system_prompt: str, prompt: str,
                  settings: Dict[str, Any],
                  context: ExecutionContext) -> str:
        """
        Makes an LLM call using the endpoint and preset from settings.

        Creates a temporary LLM handler from the settings configuration
        and dispatches the prompt.

        Args:
            system_prompt: The system prompt to send.
            prompt: The user prompt to send.
            settings: The compactor settings (contains endpointName, preset, etc).
            context: The execution context.

        Returns:
            str: The LLM response text.
        """
        endpoint_name = settings.get("endpointName")
        preset_name = settings.get("preset")
        max_tokens = settings.get("maxResponseSizeInTokens", 750)

        llm_handler = self.llm_handler_service.load_model_from_config(
            config_name=endpoint_name,
            preset=preset_name,
            stream=False,
            max_tokens=max_tokens
        )

        if not llm_handler.takes_message_collection:
            return llm_handler.llm.get_response_from_llm(
                system_prompt=system_prompt,
                prompt=prompt,
                llm_takes_images=False,
                request_id=context.request_id
            )
        else:
            collection = []
            if system_prompt:
                collection.append({"role": "system", "content": system_prompt})
            if prompt:
                collection.append({"role": "user", "content": prompt})
            return llm_handler.llm.get_response_from_llm(
                collection,
                llm_takes_images=False,
                request_id=context.request_id
            )

    def _load_state(self, discussion_id: str, section: str, context: 'ExecutionContext' = None) -> List[Tuple[str, str]]:
        """
        Loads the persisted state for a section (old or oldest) from its file.

        Args:
            discussion_id: The discussion ID.
            section: Either "old" or "oldest".
            context: Optional ExecutionContext providing pre-computed encryption_key and api_key_hash.

        Returns:
            List of (text_block, hash) tuples, or empty list if no file exists.
        """
        api_key_hash = context.api_key_hash if context else None
        encryption_key = context.encryption_key if context else None
        if section == "old":
            filepath = get_discussion_context_compactor_old_file_path(discussion_id, api_key_hash=api_key_hash)
        else:
            filepath = get_discussion_context_compactor_oldest_file_path(discussion_id, api_key_hash=api_key_hash)
        return read_chunks_with_hashes(filepath, encryption_key=encryption_key)

    def _save_state(self, discussion_id: str, section: str,
                    chunks: List[Tuple[str, str]], context: 'ExecutionContext' = None) -> None:
        """
        Saves the state for a section (old or oldest) to its file.

        Args:
            discussion_id: The discussion ID.
            section: Either "old" or "oldest".
            chunks: List of (text_block, hash) tuples to save.
            context: Optional ExecutionContext providing pre-computed encryption_key and api_key_hash.
        """
        api_key_hash = context.api_key_hash if context else None
        encryption_key = context.encryption_key if context else None
        if section == "old":
            filepath = get_discussion_context_compactor_old_file_path(discussion_id, api_key_hash=api_key_hash)
        else:
            filepath = get_discussion_context_compactor_oldest_file_path(discussion_id, api_key_hash=api_key_hash)
        update_chunks_with_hashes(chunks, filepath, mode="overwrite", encryption_key=encryption_key)

    def _return_cached_output(self, discussion_id: str, context: 'ExecutionContext' = None) -> str:
        """
        Returns the formatted output from existing cached files.

        Reads both the Old and Oldest section files and formats the output
        with XML-style tags.

        Args:
            discussion_id: The discussion ID.
            context: Optional ExecutionContext providing pre-computed encryption_key and api_key_hash.

        Returns:
            str: The formatted output, or empty string if no summaries exist.
        """
        old_state = self._load_state(discussion_id, "old", context=context)
        oldest_state = self._load_state(discussion_id, "oldest", context=context)

        old_summary = ""
        if old_state:
            for text_block, _ in old_state:
                if text_block != _BOUNDARY_SENTINEL:
                    old_summary = text_block
                    break

        oldest_summary = ""
        if oldest_state:
            oldest_summary = oldest_state[0][0]

        if not old_summary and not oldest_summary:
            return ""

        return self._format_output(old_summary, oldest_summary)

    @staticmethod
    def _format_output(old_summary: str, oldest_summary: str) -> str:
        """
        Wraps the summaries in XML-style tags for downstream extraction
        via TagTextExtractor.

        Args:
            old_summary: The Old section summary.
            oldest_summary: The Oldest section summary.

        Returns:
            str: The formatted output string.
        """
        parts = []
        if old_summary:
            parts.append(f"<context_compactor_old>{old_summary}</context_compactor_old>")
        if oldest_summary:
            parts.append(f"<context_compactor_oldest>{oldest_summary}</context_compactor_oldest>")
        return "\n".join(parts)

    @staticmethod
    def _messages_to_text(messages: List[Dict[str, str]]) -> str:
        """
        Converts a list of message dicts to a readable text block.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.

        Returns:
            str: Formatted text block of the messages.
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _hash_message_content(content: str) -> str:
        """
        Generates a SHA-256 hash of message content.

        Args:
            content: The message content string.

        Returns:
            str: The hex digest of the SHA-256 hash.
        """
        return hash_content(content)
