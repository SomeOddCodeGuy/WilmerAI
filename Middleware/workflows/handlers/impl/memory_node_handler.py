# Middleware/workflows/handlers/impl/memory_node_handler.py

import logging
from dataclasses import replace as dc_replace
from typing import Any, Callable

from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.services.memory_service import MemoryService
from Middleware.utilities.config_utils import get_discussion_chat_summary_file_path, get_discussion_memory_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, update_chunks_with_hashes
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool

logger = logging.getLogger(__name__)


class MemoryNodeHandler(BaseHandler):
    """
    Handles workflow nodes related to conversational memory.

    This class centralizes the logic for various memory operations, acting as a
    router that dispatches tasks to specific methods based on the node's 'type'
    from the workflow configuration. It is initialized with bound methods from
    the WorkflowManager to allow it to trigger memory-parsing sub-workflows.
    """

    def __init__(self, workflow_manager: Any, workflow_variable_service: Any,
                 process_file_memories_func: Callable, handle_recent_memory_parser_func: Callable,
                 handle_full_chat_summary_parser_func: Callable, handle_conversation_memory_parser_func: Callable,
                 **kwargs):
        """
        Initializes the MemoryNodeHandler and its dependencies.

        Args:
            workflow_manager (Any): The central workflow manager instance.
            workflow_variable_service (Any): The service for variable substitution.
            process_file_memories_func (Callable): Function to process file-based memories.
            handle_recent_memory_parser_func (Callable): Function to parse recent memories.
            handle_full_chat_summary_parser_func (Callable): Function to parse the full chat summary.
            handle_conversation_memory_parser_func (Callable): Function to parse conversation memory.
            **kwargs: Additional keyword arguments for the base handler.
        """
        super().__init__(workflow_manager, workflow_variable_service, **kwargs)
        self._process_file_memories = process_file_memories_func
        self._handle_recent_memory_parser = handle_recent_memory_parser_func
        self._handle_full_chat_summary_parser = handle_full_chat_summary_parser_func
        self._handle_conversation_memory_parser = handle_conversation_memory_parser_func

        self.memory_service = MemoryService()
        self.slow_but_quality_rag_service = SlowButQualityRAGTool()

    def handle(self, context: ExecutionContext) -> Any:
        """
        Routes a memory-related node to the appropriate internal handler method.

        Args:
            context (ExecutionContext): The runtime context for the current node.

        Returns:
            Any: The result of the memory operation.
        """
        node_type = context.config.get("type")
        logger.debug(f"MemoryNodeHandler handling node of type: {node_type}")

        if node_type == "VectorMemorySearch":
            if not context.discussion_id:
                return "Cannot perform VectorMemorySearch without a discussionId."
            keywords_input = context.config.get("input", "")
            keywords = self.workflow_variable_service.apply_variables(keywords_input, context)
            limit = context.config.get("limit", 5)
            return self.memory_service.search_vector_memories(context.discussion_id, keywords, limit)

        elif node_type == "ConversationMemory":
            if not context.discussion_id:
                return "There are not yet any memories"
            return self._handle_conversation_memory_parser(context.request_id, context.discussion_id, context.messages,
                                                                api_key=context.api_key)

        elif node_type == "FullChatSummary":
            return self._handle_full_chat_summary(context)

        elif node_type == "RecentMemory":
            if context.discussion_id is not None:
                self._handle_memory_file(context, force_file_memory=True)
            return self._handle_recent_memory_parser(context.request_id, context.discussion_id, context.messages,
                                                        api_key=context.api_key)

        elif node_type == "RecentMemorySummarizerTool":
            memories = self.memory_service.get_recent_memories(
                context.messages, context.discussion_id, context.config["maxTurnsToPull"],
                context.config["maxSummaryChunksFromFile"],
                context.config.get("lookbackStart", 0),
                encryption_key=context.encryption_key, api_key_hash=context.api_key_hash)
            custom_delimiter = context.config.get("customDelimiter")
            # Memory chunks are stored and returned joined by the internal '--ChunkBreak--'
            # sentinel.  If the workflow node specifies a custom delimiter, replace the
            # sentinel with it before returning so the LLM sees the intended separator.
            if custom_delimiter is not None and memories is not None:
                return memories.replace("--ChunkBreak--", custom_delimiter)
            elif memories is not None:
                return memories
            else:
                return "There are not yet any memories"

        elif node_type == "ChatSummaryMemoryGatheringTool":
            return self.memory_service.get_chat_summary_memories(context.messages, context.discussion_id,
                                                                 context.config["maxTurnsToPull"],
                                                                 encryption_key=context.encryption_key,
                                                                 api_key_hash=context.api_key_hash)

        elif node_type == "GetCurrentSummaryFromFile":
            if not context.discussion_id:
                return "There is not yet a summary file"
            return self.memory_service.get_current_summary(context.discussion_id,
                                                             encryption_key=context.encryption_key,
                                                             api_key_hash=context.api_key_hash)

        elif node_type == "GetCurrentMemoryFromFile":
            if not context.discussion_id:
                return "There are not yet any memories"
            memories = self.memory_service.get_current_memories(context.discussion_id,
                                                                  encryption_key=context.encryption_key,
                                                                  api_key_hash=context.api_key_hash)
            custom_delimiter = context.config.get("customDelimiter", "--ChunkBreak--")
            return custom_delimiter.join(memories)

        elif node_type == "chatSummarySummarizer":
            if not context.discussion_id:
                return "There is not yet a summary file"
            return self._handle_process_chat_summary(context)

        elif node_type == "WriteCurrentSummaryToFileAndReturnIt":
            return self._save_summary_to_file(context)

        elif node_type == "QualityMemory":
            return self._handle_quality_memory_workflow(context)

        else:
            raise ValueError(f"MemoryNodeHandler received unhandled node type: {node_type}")

    def _handle_memory_file(self, context: ExecutionContext, force_file_memory: bool = False) -> Any:
        """
        Delegates to the RAG tool to handle the full memory creation workflow.

        Args:
            context (ExecutionContext): The runtime context for the current node.

        Returns:
            Any: The result from the memory creation process.
        """
        return self.slow_but_quality_rag_service.handle_discussion_id_flow(context, force_file_memory)

    def _save_summary_to_file(self, context: ExecutionContext, summary_override: str = None,
                              last_hash_override: str = None) -> Any:
        """
        Saves a generated chat summary to its dedicated file.

        Args:
            context (ExecutionContext): The runtime context for the current node.
            summary_override (str, optional): A summary string to use instead of one
                from the context. Defaults to None.
            last_hash_override (str, optional): A hash to associate with the summary
                instead of the latest one from the memory file. Defaults to None.

        Returns:
            Any: The summary string that was saved.
        """
        if summary_override is None:
            if "input" not in context.config:
                raise ValueError("No 'input' found in config for saving summary.")
            summary_input = context.config["input"]
            summary = self.workflow_variable_service.apply_variables(summary_input, context)
        else:
            summary = summary_override

        if context.discussion_id is None:
            return summary

        memory_filepath = get_discussion_memory_file_path(context.discussion_id, api_key_hash=context.api_key_hash)
        hashed_chunks = read_chunks_with_hashes(memory_filepath, encryption_key=context.encryption_key)

        if last_hash_override is None:
            if not hashed_chunks:
                raise ValueError("Cannot save summary without a last hash and no memory chunks exist.")
            last_chunk = hashed_chunks[-1]
            _, old_hash = last_chunk
            last_chunk_with_hash = (summary, old_hash)
        else:
            last_chunk_with_hash = (summary, last_hash_override)

        chunks_to_write = [last_chunk_with_hash]
        logger.debug(f"Saving summary to file:\n{summary}")

        filepath = get_discussion_chat_summary_file_path(context.discussion_id, api_key_hash=context.api_key_hash)
        update_chunks_with_hashes(chunks_to_write, filepath, "overwrite", encryption_key=context.encryption_key)

        return summary

    def _handle_process_chat_summary(self, context: ExecutionContext) -> Any:
        """
        Manages an iterative, multi-turn chat summarization process.

        Args:
            context (ExecutionContext): The runtime context for the current node.

        Returns:
            Any: The final, updated chat summary.
        """
        memory_chunks_with_hashes = self.memory_service.get_latest_memory_chunks_with_hashes_since_last_summary(
            context.discussion_id, encryption_key=context.encryption_key, api_key_hash=context.api_key_hash)
        current_chat_summary = self.memory_service.get_current_summary(
            context.discussion_id, encryption_key=context.encryption_key, api_key_hash=context.api_key_hash)

        if not memory_chunks_with_hashes:
            return current_chat_summary

        system_prompt_template = context.config.get('systemPrompt', '')
        prompt_template = context.config.get('prompt', '')
        minMemoriesPerSummary = context.config.get('minMemoriesPerSummary', 3)
        max_memories_per_loop = context.config.get('loopIfMemoriesExceed', 3)

        if '[CHAT_SUMMARY]' not in system_prompt_template and '[CHAT_SUMMARY]' not in prompt_template and \
                '[LATEST_MEMORIES]' not in system_prompt_template and '[LATEST_MEMORIES]' not in prompt_template:
            summary = LLMDispatchService.dispatch(context=context)
            self._save_summary_to_file(context, summary_override=summary)
            return summary

        # Process memories in batches rather than all at once. Each LLM call is bounded
        # by the context window; batching ensures no single call is overloaded when a
        # large backlog of unprocessed memories exists. The rolling summary is updated
        # after each batch so that each subsequent call can reference up-to-date context.
        while len(memory_chunks_with_hashes) > max_memories_per_loop:
            batch_chunks = memory_chunks_with_hashes[:max_memories_per_loop]
            latest_memories_chunk = '\n------------\n'.join([chunk for chunk, _ in batch_chunks])
            last_hash = batch_chunks[-1][1]

            updated_system_prompt = system_prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)
            updated_prompt = prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)

            temp_config = {**context.config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt}

            # Create a temporary context for the dispatch call with the modified config
            temp_context = dc_replace(context, config=temp_config)
            summary = LLMDispatchService.dispatch(context=temp_context)

            self._save_summary_to_file(context, summary_override=summary, last_hash_override=last_hash)

            memory_chunks_with_hashes = memory_chunks_with_hashes[max_memories_per_loop:]
            current_chat_summary = self.memory_service.get_current_summary(
                context.discussion_id, encryption_key=context.encryption_key, api_key_hash=context.api_key_hash)

        # Only summarize the remaining memories if there are enough of them. Generating
        # a summary from too few new chunks would produce thin or near-duplicate output
        # relative to the existing summary. The workflow waits until the minimum
        # accumulation threshold is reached before triggering a new LLM call.
        if 0 < len(memory_chunks_with_hashes) and len(memory_chunks_with_hashes) >= minMemoriesPerSummary:
            latest_memories_chunk = '\n------------\n'.join([chunk for chunk, _ in memory_chunks_with_hashes])
            last_hash = memory_chunks_with_hashes[-1][1]

            updated_system_prompt = system_prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)
            updated_prompt = prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)

            temp_config = {**context.config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt}

            # Create another temporary context for the dispatch call
            temp_context = dc_replace(context, config=temp_config)
            summary = LLMDispatchService.dispatch(context=temp_context)

            self._save_summary_to_file(context, summary_override=summary, last_hash_override=last_hash)
            return summary

        return current_chat_summary

    def _handle_full_chat_summary(self, context: ExecutionContext):
        """
        Determines if a full chat summary needs updating before returning it.

        Args:
            context (ExecutionContext): The runtime context for the current node.

        Returns:
            The updated chat summary string, a list of summary text blocks (when
            the existing summary is still current), "No summary found" if no
            summary file exists, or None if no discussionId is present.
        """
        if context.discussion_id is not None:
            if context.config.get("isManualConfig"):
                filepath = get_discussion_chat_summary_file_path(context.discussion_id, api_key_hash=context.api_key_hash)
                summary_chunk = read_chunks_with_hashes(filepath, encryption_key=context.encryption_key)
                return extract_text_blocks_from_hashed_chunks(summary_chunk) if summary_chunk else "No summary found"

            self._handle_memory_file(context, force_file_memory=True)

            mem_filepath = get_discussion_memory_file_path(context.discussion_id, api_key_hash=context.api_key_hash)
            hashed_memory_chunks = read_chunks_with_hashes(mem_filepath, encryption_key=context.encryption_key)

            sum_filepath = get_discussion_chat_summary_file_path(context.discussion_id, api_key_hash=context.api_key_hash)
            hashed_summary_chunk = read_chunks_with_hashes(sum_filepath, encryption_key=context.encryption_key)

            index = self.memory_service.find_how_many_new_memories_since_last_summary(hashed_summary_chunk,
                                                                                      hashed_memory_chunks)

            if index > 1 or index < 0:
                return self._handle_full_chat_summary_parser(context.request_id, context.discussion_id,
                                                             context.messages, api_key=context.api_key)
            else:
                return extract_text_blocks_from_hashed_chunks(hashed_summary_chunk)
        return None

    def _handle_quality_memory_workflow(self, context: ExecutionContext):
        """
        Handles the QualityMemory node by invoking the correct memory creation process.

        This will trigger the full persistent memory creation workflow if a discussionId
        is present, otherwise it falls back to a stateless in-memory parser.

        Args:
            context (ExecutionContext): The runtime context for the current node.

        Returns:
            Any: The result from the invoked memory creation or parsing function.
        """
        if context.discussion_id is None:
            return self._handle_recent_memory_parser(context.request_id, None, context.messages,
                                                        api_key=context.api_key)
        else:
            return self._handle_memory_file(context)
