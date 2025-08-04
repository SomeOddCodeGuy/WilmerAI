# /Middleware/workflows/handlers/impl/memory_node_handler.py
import logging
from typing import Dict, List, Any, Callable, Optional

from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.services.memory_service import MemoryService
from Middleware.utilities.config_utils import get_discussion_chat_summary_file_path, get_discussion_memory_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, update_chunks_with_hashes
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool

logger = logging.getLogger(__name__)


class MemoryNodeHandler(BaseHandler):
    """
    Handles workflow nodes related to conversational memory.

    This class centralizes the logic for various memory operations, such as
    creating summaries, retrieving recent conversation turns, and managing
    memory files. It acts as a router, dispatching tasks to specific
    methods based on the node's 'type' from the workflow configuration.
    It is initialized with bound methods from the WorkflowManager to allow
    it to trigger other memory-parsing workflows.
    """

    def __init__(self, workflow_manager: Any, workflow_variable_service: Any,
                 process_file_memories_func: Callable, handle_recent_memory_parser_func: Callable,
                 handle_full_chat_summary_parser_func: Callable, handle_conversation_memory_parser_func: Callable,
                 **kwargs):
        """
        Initializes the MemoryNodeHandler.

        This constructor stores bound methods from the WorkflowManager, which are
        used to invoke other workflows for complex memory parsing tasks. It also
        instantiates services and tools required for its operations.

        Args:
            workflow_manager (Any): An instance of the WorkflowManager.
            workflow_variable_service (Any): An instance of the WorkflowVariableManager.
            process_file_memories_func (Callable): Bound method from WorkflowManager
                to process memories stored in files.
            handle_recent_memory_parser_func (Callable): Bound method from WorkflowManager
                to parse recent, in-flight memories.
            handle_full_chat_summary_parser_func (Callable): Bound method from
                WorkflowManager to generate a summary of the entire chat history.
            handle_conversation_memory_parser_func (Callable): Bound method from
                WorkflowManager to parse general conversation memory.
            **kwargs: Catches other dependencies passed from the WorkflowManager.
        """
        super().__init__(workflow_manager, workflow_variable_service, **kwargs)
        self._process_file_memories = process_file_memories_func
        self._handle_recent_memory_parser = handle_recent_memory_parser_func
        self._handle_full_chat_summary_parser = handle_full_chat_summary_parser_func
        self._handle_conversation_memory_parser = handle_conversation_memory_parser_func

        self.memory_service = MemoryService()
        self.slow_but_quality_rag_service = SlowButQualityRAGTool()

    def handle(self, config: Dict, messages: List[Dict], request_id: str, workflow_id: str,
               discussion_id: str, agent_outputs: Dict, stream: bool) -> Any:
        """
        Routes a memory-related node to the appropriate internal handler method.

        This method acts as the main entry point for the handler. It reads the
        'type' field from the node's configuration and calls the corresponding
        method to perform the requested memory operation.

        Args:
            config (Dict): The configuration for the specific workflow node.
            messages (List[Dict]): The conversation history as role/content pairs.
            request_id (str): The unique ID for the overall request.
            workflow_id (str): The ID of the current workflow.
            discussion_id (str): The ID for the conversation thread.
            agent_outputs (Dict): A dictionary of outputs from previous nodes.
            stream (bool): Flag indicating if the response should be streamed.

        Returns:
            Any: The result of the memory operation, typically a string containing
                 memories or a summary. The exact type depends on the node.

        Raises:
            ValueError: If the node 'type' is not recognized by this handler.
        """
        node_type = config.get("type")
        logger.debug(f"MemoryNodeHandler handling node of type: {node_type}")

        if node_type == "ConversationMemory":
            return self._handle_conversation_memory_parser(request_id, discussion_id, messages)

        if node_type == "FullChatSummary":
            return self._handle_full_chat_summary(messages, config, request_id, discussion_id)

        if node_type == "RecentMemory":
            if discussion_id is not None:
                self._handle_memory_file(discussion_id, messages)
            return self._handle_recent_memory_parser(request_id, discussion_id, messages)

        if node_type == "RecentMemorySummarizerTool":
            memories = self.memory_service.get_recent_memories(messages, discussion_id, config["maxTurnsToPull"],
                                              config["maxSummaryChunksFromFile"], config.get("lookbackStart", 0))
            custom_delimiter = config.get("customDelimiter")
            if custom_delimiter is not None and memories is not None:
                return memories.replace("--ChunkBreak--", custom_delimiter)
            elif memories is not None:
                return memories
            else:
                return "There are not yet any memories"

        if node_type == "ChatSummaryMemoryGatheringTool":
            return self.memory_service.get_chat_summary_memories(messages, discussion_id, config["maxTurnsToPull"])

        if node_type == "GetCurrentSummaryFromFile" or node_type == "GetCurrentMemoryFromFile":
            return self.memory_service.get_current_summary(discussion_id)

        if node_type == "chatSummarySummarizer":
            return self._handle_process_chat_summary(config, messages, agent_outputs, discussion_id)

        if node_type == "WriteCurrentSummaryToFileAndReturnIt":
            return self._save_summary_to_file(config, messages, discussion_id, agent_outputs)

        if node_type == "QualityMemory":
            return self._handle_quality_memory_workflow(request_id, messages, discussion_id)

        raise ValueError(f"MemoryNodeHandler received unhandled node type: {node_type}")

    def _handle_memory_file(self, discussion_id: str, messages: List[Dict[str, str]]) -> Any:
        """
        Processes and writes recent conversation turns to a memory file.

        This method delegates to the SlowButQualityRAGTool to handle the logic
        of appending new messages to the long-term memory file associated with
        the given discussion ID.

        Args:
            discussion_id (str): The ID for the conversation thread.
            messages (List[Dict[str, str]]): The current conversation history.

        Returns:
            Any: The result from the underlying RAG tool's handling method.
        """
        return self.slow_but_quality_rag_service.handle_discussion_id_flow(discussion_id, messages)

    def _save_summary_to_file(self, config: Dict, messages: List[Dict[str, str]], discussion_id: str,
                              agent_outputs: Optional[Dict] = None, summaryOverride: str = None,
                              lastHashOverride: str = None) -> Any:
        """
        Saves a generated chat summary to a dedicated summary file.

        This method applies workflow variables to a summary string (if not
        overridden) and writes it to the discussion's summary file. It links
        the summary to the last piece of conversation memory it's based on
        by using a hash, ensuring traceability.

        Args:
            config (Dict): The node's configuration, used to get the input summary.
            messages (List[Dict[str, str]]): The conversation history.
            discussion_id (str): The ID for the conversation thread.
            agent_outputs (Optional[Dict]): Outputs from previous nodes for variables.
            summaryOverride (Optional[str]): An explicit summary string to save.
            lastHashOverride (Optional[str]): An explicit hash to associate the summary with.

        Returns:
            str: The summary string that was saved to the file.

        Raises:
            ValueError: If no summary input is available or if a hash is needed
                        but cannot be found.
        """
        if summaryOverride is None:
            if "input" not in config:
                raise ValueError("No 'input' found in config for saving summary.")
            summary = config["input"]
            summary = self.workflow_variable_service.apply_variables(
                summary, self.llm_handler, messages, agent_outputs, config=config
            )
        else:
            summary = summaryOverride

        if discussion_id is None:
            return summary

        memory_filepath = get_discussion_memory_file_path(discussion_id)
        hashed_chunks = read_chunks_with_hashes(memory_filepath)

        if lastHashOverride is None:
            if not hashed_chunks:
                raise ValueError("Cannot save summary without a last hash and no memory chunks exist.")
            last_chunk = hashed_chunks[-1]
            _, old_hash = last_chunk
            last_chunk_with_hash = (summary, old_hash)
        else:
            last_chunk_with_hash = (summary, lastHashOverride)

        chunks_to_write = [last_chunk_with_hash]
        logger.debug(f"Saving summary to file:\n{summary}")

        filepath = get_discussion_chat_summary_file_path(discussion_id)
        update_chunks_with_hashes(chunks_to_write, filepath, "overwrite")

        return summary

    def _handle_process_chat_summary(self, config: Dict, messages: List[Dict[str, str]],
                                     agent_outputs: Dict[str, str], discussion_id: str) -> Any:
        """
        Manages an iterative, multi-turn chat summarization process.

        This method updates a long-running chat summary by integrating new
        conversation turns. It fetches memories created since the last summary,
        and if they meet a minimum threshold, uses an LLM to generate a new
        summary. It can loop through memories in batches to handle long chats.

        Args:
            config (Dict): The node's config, containing prompts and settings.
            messages (List[Dict[str, str]]): The conversation history.
            agent_outputs (Dict[str, str]): Outputs from previous nodes.
            discussion_id (str): The ID for the conversation thread.

        Returns:
            str: The newly generated summary, or the existing summary if no
                 update was performed.
        """
        memory_chunks_with_hashes = self.memory_service.get_latest_memory_chunks_with_hashes_since_last_summary(discussion_id)
        current_chat_summary = self.memory_service.get_current_summary(discussion_id)

        if not memory_chunks_with_hashes:
            return current_chat_summary

        system_prompt_template = config.get('systemPrompt', '')
        prompt_template = config.get('prompt', '')
        minMemoriesPerSummary = config.get('minMemoriesPerSummary', 3)
        max_memories_per_loop = config.get('loopIfMemoriesExceed', 3)

        if '[CHAT_SUMMARY]' not in system_prompt_template and '[CHAT_SUMMARY]' not in prompt_template and \
                '[LATEST_MEMORIES]' not in system_prompt_template and '[LATEST_MEMORIES]' not in prompt_template:
            summary = LLMDispatchService.dispatch(
                llm_handler=self.llm_handler,
                workflow_variable_service=self.workflow_variable_service,
                config=config,
                messages=messages,
                agent_outputs=agent_outputs
            )
            self._save_summary_to_file(config, messages, discussion_id, agent_outputs, summary)
            return summary

        while len(memory_chunks_with_hashes) > max_memories_per_loop:
            batch_chunks = memory_chunks_with_hashes[:max_memories_per_loop]
            latest_memories_chunk = '\n------------\n'.join([chunk for chunk, _ in batch_chunks])
            last_hash = batch_chunks[-1][1]

            updated_system_prompt = system_prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)
            updated_prompt = prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)

            temp_config = {**config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt}

            summary = LLMDispatchService.dispatch(
                llm_handler=self.llm_handler,
                workflow_variable_service=self.workflow_variable_service,
                config=temp_config,
                messages=messages,
                agent_outputs=agent_outputs
            )

            self._save_summary_to_file(config, messages, discussion_id, agent_outputs, summary, last_hash)

            memory_chunks_with_hashes = memory_chunks_with_hashes[max_memories_per_loop:]
            current_chat_summary = self.memory_service.get_current_summary(discussion_id)

        if 0 < len(memory_chunks_with_hashes) and len(memory_chunks_with_hashes) >= minMemoriesPerSummary:
            latest_memories_chunk = '\n------------\n'.join([chunk for chunk, _ in memory_chunks_with_hashes])
            last_hash = memory_chunks_with_hashes[-1][1]

            updated_system_prompt = system_prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)
            updated_prompt = prompt_template.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)

            temp_config = {**config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt}

            summary = LLMDispatchService.dispatch(
                llm_handler=self.llm_handler,
                workflow_variable_service=self.workflow_variable_service,
                config=temp_config,
                messages=messages,
                agent_outputs=agent_outputs
            )

            self._save_summary_to_file(config, messages, discussion_id, agent_outputs, summary, last_hash)
            return summary

        return current_chat_summary

    def _handle_full_chat_summary(self, messages, config, request_id, discussion_id):
        """
        Determines if a full chat summary needs updating before returning it.

        This method checks for new conversation memories that have been saved since
        the last summary was created. If new memories are found, it invokes a
        sub-workflow to generate an updated summary. Otherwise, it returns the
        current summary stored on disk.

        Args:
            messages (List[Dict]): The conversation history.
            config (Dict): The node's configuration.
            request_id (str): The unique ID for the overall request.
            discussion_id (str): The ID for the conversation thread.

        Returns:
            Any: The result from the summary parser workflow or the existing
                 summary string from the file. Returns None if discussion_id is None.
        """
        if discussion_id is not None:
            if config.get("isManualConfig"):
                filepath = get_discussion_chat_summary_file_path(discussion_id)
                summary_chunk = read_chunks_with_hashes(filepath)
                return extract_text_blocks_from_hashed_chunks(summary_chunk) if summary_chunk else "No summary found"

            self._handle_memory_file(discussion_id, messages)

            mem_filepath = get_discussion_memory_file_path(discussion_id)
            hashed_memory_chunks = read_chunks_with_hashes(mem_filepath)

            sum_filepath = get_discussion_chat_summary_file_path(discussion_id)
            hashed_summary_chunk = read_chunks_with_hashes(sum_filepath)

            index = self.memory_service.find_how_many_new_memories_since_last_summary(hashed_summary_chunk, hashed_memory_chunks)

            if index > 1 or index < 0:
                return self._handle_full_chat_summary_parser(request_id, discussion_id, messages)
            else:
                return extract_text_blocks_from_hashed_chunks(hashed_summary_chunk)
        return None

    def _handle_quality_memory_workflow(self, request_id, messages, discussion_id):
        """
        Invokes the appropriate memory processing sub-workflow based on context.

        This method acts as a router. If a discussion ID is not provided, it
        triggers a simple, stateless recent memory parsing workflow. If a
        discussion ID is present, it triggers the more complex workflow that
        processes memories stored in files.

        Args:
            request_id (str): The unique ID for the overall request.
            messages (List[Dict]): The conversation history.
            discussion_id (str): The ID for the conversation thread.

        Returns:
            Any: The result from the invoked memory sub-workflow.
        """
        if discussion_id is None:
            return self._handle_recent_memory_parser(request_id, None, messages)
        else:
            self._handle_memory_file(discussion_id, messages)
            return self._process_file_memories(request_id, discussion_id, messages)