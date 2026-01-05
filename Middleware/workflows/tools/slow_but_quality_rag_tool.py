import json
import logging
import re
from copy import deepcopy
from typing import List, Dict, Any

from Middleware.services.llm_service import LlmHandlerService
from Middleware.services.memory_service import MemoryService
from Middleware.utilities import vector_db_utils
from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_endpoint_config, load_config, \
    get_discussion_id_workflow_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks, find_last_matching_hash_message, \
    chunk_messages_with_hashes, hash_single_message
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns
from Middleware.utilities.search_utils import filter_keywords_by_speakers, advanced_search_in_chunks, search_in_chunks
from Middleware.utilities.text_utils import get_message_chunks, clear_out_user_assistant_from_chunks, \
    rough_estimate_token_length
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


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
            logger.warning(f"Could not find a JSON block or object in the LLM output.")
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

        # Create a temporary context for the specific LLM handler needed for this task
        temp_llm_context = deepcopy(context)
        temp_llm_context.llm_handler = llm_handler
        temp_llm_context.config = config  # Ensure the correct node config is used

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
                    scoped_inputs=scoped_inputs
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
                for memory_metadata in memories_to_process:
                    if isinstance(memory_metadata, dict):
                        required_keys = ['title', 'summary', 'entities', 'key_phrases']
                        if all(k in memory_metadata for k in required_keys):
                            memory_summary = memory_metadata['summary']
                            vector_db_utils.add_memory_to_vector_db(
                                context.discussion_id,
                                memory_summary,
                                json.dumps(memory_metadata)
                            )
                            successful_adds += 1

                if successful_adds > 0:
                    # Write the hash immediately after successfully storing memories for this chunk
                    # This makes the process resumable - if interrupted, we can pick up from the last hash
                    vector_db_utils.add_vector_check_hash(context.discussion_id, chunk_hash)
                    logger.info(
                        f"Successfully generated and stored {successful_adds} vector memory/memories for discussion {context.discussion_id}. Hash logged for resumability.")
                    total_memories_stored += successful_adds
                else:
                    logger.error(f"Received empty response from LLM/workflow for vector memory generation.")

        return total_memories_stored

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
        filepath = get_discussion_memory_file_path(context.discussion_id)
        hash_chunks = read_chunks_with_hashes(filepath)
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
        if len(context.messages) < 3:
            logger.debug("Less than 3 messages, no memory will be generated.")
            return

        messages_copy = deepcopy(context.messages)
        # This method uses a specific, separate config file to govern its behavior.
        discussion_id_workflow_config = load_config(get_discussion_id_workflow_path())
        use_vector_memory_from_config = discussion_id_workflow_config.get('useVectorForQualityMemory', False)

        if use_vector_memory_from_config and not force_file_memory:
            vector_db_utils.initialize_vector_db(context.discussion_id)
            logger.debug("Running vector memory check.")

            lookback_turns = discussion_id_workflow_config.get('vectorMemoryLookBackTurns', 3)
            if len(messages_copy) <= lookback_turns:
                return

            # Define the boundary for eligible messages (we won't process the last few turns)
            end_index = len(messages_copy) - lookback_turns

            # 1. Get the history of the last N hashes, not just one.
            hash_history = vector_db_utils.get_vector_check_hash_history(context.discussion_id, limit=10)

            start_index = 0  # Default to the beginning if no hash is found
            if hash_history:
                found_match = False
                # 2. Loop through the historical hashes, from newest to oldest.
                for historical_hash in hash_history:
                    # 3. Search the full conversation for the current hash in the loop.
                    for i in range(end_index - 1, -1, -1):
                        if hash_single_message(messages_copy[i]) == historical_hash:
                            # 4. If a hash is found, we have our starting point. Break the loops.
                            start_index = i + 1
                            found_match = True
                            logger.info(
                                f"Found matching historical hash at message index {i}. Starting memory generation from there.")
                            break
                    if found_match:
                        break

                if not found_match:
                    logger.warning(
                        f"Could not find any of the last {len(hash_history)} historical hashes for {context.discussion_id}. Reprocessing all eligible messages.")
                    # If no hashes in history match, start_index remains 0.

            new_message_content_to_process = []
            if start_index < end_index:
                new_message_content_to_process = messages_copy[start_index:end_index]

            if new_message_content_to_process:
                logger.info(
                    f"Found {len(new_message_content_to_process)} new messages to consider for vector memory generation.")

                chunk_size = discussion_id_workflow_config.get('vectorMemoryChunkEstimatedTokenSize', 1000)
                max_messages = discussion_id_workflow_config.get('vectorMemoryMaxMessagesBetweenChunks', 5)
                hashed_chunks = chunk_messages_with_hashes(new_message_content_to_process, chunk_size,
                                                           max_messages_before_chunk=max_messages)
                text_chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)

                if not text_chunks:
                    logger.info(
                        f"Messages did not meet chunking threshold (need {max_messages} messages or {chunk_size} estimated tokens). No memories generated.")
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
            filepath = get_discussion_memory_file_path(context.discussion_id)
            discussion_chunks = read_chunks_with_hashes(filepath)
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
            max_messages = discussion_id_workflow_config.get('maxMessagesBetweenChunks', 5)
            token_count = rough_estimate_token_length(
                '\n'.join(m['content'] for m in new_message_content_to_process if 'content' in m)
            )
            file_exists = bool(discussion_chunks)
            trigger_by_tokens = token_count > chunk_size
            trigger_by_messages = file_exists and len(new_message_content_to_process) > max_messages

            if trigger_by_tokens or trigger_by_messages:
                logger.info("Threshold met. Generating new memories.")
                hashed_chunks = chunk_messages_with_hashes(new_message_content_to_process, chunk_size,
                                                           max_messages_before_chunk=max_messages)
                text_chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)
                if len(hashed_chunks) >= 1:
                    logger.info("Using original file-based memory creation flow.")
                    rag_system_prompt = discussion_id_workflow_config.get('systemPrompt', '')
                    rag_prompt = discussion_id_workflow_config.get('prompt', '')
                    self.process_new_memory_chunks(text_chunks, hashed_chunks, rag_system_prompt, rag_prompt,
                                                   discussion_id_workflow_config, context)
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
        replaced = [(summary, hash_code) for summary, (_, hash_code) in zip(results, hash_chunks)]
        filepath = get_discussion_memory_file_path(context.discussion_id)
        existing_chunks = read_chunks_with_hashes(filepath)
        updated_chunks = existing_chunks + replaced
        update_chunks_with_hashes(updated_chunks, filepath, mode="overwrite")

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
        discussion_chunks = read_chunks_with_hashes(get_discussion_memory_file_path(context.discussion_id))
        memory_chunks = extract_text_blocks_from_hashed_chunks(discussion_chunks)
        chat_summary = self.memory_service.get_current_summary(context.discussion_id)

        endpoint_name = workflow_config.get('endpointName')
        preset_name = workflow_config.get('preset')
        max_tokens = workflow_config.get("maxResponseSizeInTokens", 400)
        endpoint_data = get_endpoint_config(endpoint_name)
        llm_handler_service = LlmHandlerService()
        llm_handler = llm_handler_service.initialize_llm_handler(
            endpoint_data, preset_name, endpoint_name, False,
            endpoint_data.get("maxContextTokenSize", 4096), max_tokens
        )

        # Create a temporary context with the correct, newly created llm_handler
        temp_llm_context = deepcopy(context)
        temp_llm_context.llm_handler = llm_handler
        # Also ensure the config in the temp context is the correct one for *this* task
        temp_llm_context.config = workflow_config

        # Note: The 'fileMemoryWorkflowName' should be in 'workflow_config', not 'context.config'
        file_workflow_name = workflow_config.get('fileMemoryWorkflowName')
        result_chunks = []
        for chunk in chunks:
            current_memories = '\n--------------\n'.join(memory_chunks[-3:])
            full_memories = '\n--------------\n'.join(memory_chunks)
            result_chunk = ""
            if file_workflow_name:
                logger.info(f"Using workflow '{file_workflow_name}' to generate file-based memory.")
                scoped_inputs = [chunk, current_memories.strip(), full_memories.strip(), chat_summary.strip()]
                result_chunk = context.workflow_manager.run_custom_workflow(
                    workflow_name=file_workflow_name, request_id=context.request_id,
                    discussion_id=context.discussion_id, messages=context.messages,
                    non_responder=True, scoped_inputs=scoped_inputs
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
                llm_takes_images=False
            )
        else:
            collection = []
            if formatted_system_prompt:
                collection.append({"role": "system", "content": formatted_system_prompt})
            if formatted_prompt:
                collection.append({"role": "user", "content": formatted_prompt})
            return llm_handler.llm.get_response_from_llm(
                collection,
                llm_takes_images=False
            )
