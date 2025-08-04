import logging
from copy import deepcopy
from typing import List, Dict

from Middleware.services.llm_service import LlmHandlerService
from Middleware.services.memory_service import MemoryService
from Middleware.utilities.config_utils import get_discussion_memory_file_path, load_config, \
    get_discussion_id_workflow_path, get_endpoint_config
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes
from Middleware.utilities.hashing_utils import extract_text_blocks_from_hashed_chunks, find_last_matching_hash_message, \
    chunk_messages_with_hashes
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns, \
    remove_discussion_id_tag_from_string
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template, \
    format_system_prompt_with_template, add_assistant_end_token_to_user_turn
from Middleware.utilities.search_utils import filter_keywords_by_speakers, advanced_search_in_chunks, search_in_chunks
from Middleware.utilities.text_utils import get_message_chunks, clear_out_user_assistant_from_chunks, \
    rough_estimate_token_length
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.tools.parallel_llm_processing_tool import ParallelLlmProcessingTool

logger = logging.getLogger(__name__)


class SlowButQualityRAGTool:
    """
    A tool that uses Large Language Models (LLMs) to perform a slow but thorough
    Retrieval-Augmented Generation (RAG) search on large chunks of text
    to find appropriate context.
    """

    def __init__(self):
        self.memory_service = MemoryService()

    def perform_keyword_search(self, keywords: str, target, llm_handler, discussion_id, **kwargs):
        """
        Performs a keyword-based search on either the current conversation or
        recent memory files.

        This method determines the search target based on the 'target' parameter
        and delegates the keyword search to the appropriate handler method.

        Args:
            keywords (str): A string containing keywords to search for.
            target (str): The target of the search. Can be "CurrentConversation"
                          or "RecentMemories".
            llm_handler: The LLM handler to be used for processing.
            discussion_id (str): The unique identifier for the current discussion.
            **kwargs: Additional keyword arguments.
                      - messages (List[Dict[str,str]]): A collection of messages
                                                        representing the conversation.
                      - lookbackStartTurn (int): The number of turns back to start
                                                 the search.

        Returns:
            str: The result of the keyword search, or an error message if the
                 search cannot be performed.
        """
        if target == "CurrentConversation":
            if 'lookbackStartTurn' in kwargs:
                lookbackStartTurn = kwargs['lookbackStartTurn']
            else:
                lookbackStartTurn = 0
            if 'messages' in kwargs:
                messages = kwargs['messages']
                result = self.perform_conversation_search(keywords, messages, llm_handler, lookbackStartTurn)
                return result
            else:
                logger.error("Fatal Workflow Error: cannot perform keyword search; no user prompt")
        elif target == "RecentMemories":
            if 'messages' in kwargs:
                messages = kwargs['messages']
                logger.debug("In recent memories")
                logger.debug(messages)
                result = self.perform_memory_file_keyword_search(keywords, messages, llm_handler, discussion_id)
                return result

    def perform_conversation_search(self, keywords: str, messagesOriginal, llm_handler, lookbackStartTurn=0):
        """
        Performs a keyword search on the current conversation messages.

        This function retrieves conversation turns, filters them, and performs
        an advanced search based on the provided keywords.

        Args:
            keywords (str): A string of keywords to search for.
            messagesOriginal (List[Dict[str,str]]): The list of conversation messages.
            llm_handler: The LLM handler to determine message collection compatibility.
            lookbackStartTurn (int, optional): The number of turns back from the
                                               most recent message to begin the search.
                                               Defaults to 0.

        Returns:
            str: The search result chunks, joined by '--ChunkBreak--'.
        """
        logger.debug("Entering perform_conversation_search")

        # If we have fewer pairs than lookbackStartTurn, we can stop here
        if len(messagesOriginal) <= lookbackStartTurn:
            return 'There are no memories. This conversation has not gone long enough for there to be memories.'

        message_copy = deepcopy(messagesOriginal)

        pair_chunks = get_message_chunks(message_copy, lookbackStartTurn, 400)

        # In case the LLM designated the speakers as keywords, we want to remove them
        # The speakers would trigger tons of erroneous hits
        last_n_turns = extract_last_n_turns(message_copy, 10, llm_handler.takes_message_collection)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        logger.info("Keywords: %s", str(keywords))

        search_result_chunks = advanced_search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        logger.info("******** BEGIN SEARCH RESULT CHUNKS ************")
        logger.info("Search result chunks: %s", '\n\n'.join(filtered_chunks))
        logger.info("******** END SEARCH RESULT CHUNKS ************")

        return '--ChunkBreak--'.join(filtered_chunks)

    def perform_memory_file_keyword_search(self, keywords: str, messagesOriginal, llm_handler, discussion_id):
        """
        Performs a keyword search on the memory file associated with a discussion.

        This function reads the memory file, extracts text chunks, and performs
        a search based on the provided keywords.

        Args:
            keywords (str): A string of keywords to search for.
            messagesOriginal (List[Dict[str,str]]): The list of conversation messages.
            llm_handler: The LLM handler to determine message collection compatibility.
            discussion_id (str): The unique identifier for the current discussion.

        Returns:
            str: The search result chunks, joined by newline characters.
        """
        logger.debug("Entering perform_memory_file_keyword_search")
        filepath = get_discussion_memory_file_path(discussion_id)

        message_copy = deepcopy(messagesOriginal)

        hash_chunks = read_chunks_with_hashes(filepath)
        pair_chunks = extract_text_blocks_from_hashed_chunks(hash_chunks)

        if len(pair_chunks) > 3:
            pair_chunks = pair_chunks[:-3]

        # In case the LLM designated the speakers as keywords, we want to remove them
        # The speakers would trigger tons of erroneous hits
        last_n_turns = extract_last_n_turns(message_copy, 10, llm_handler.takes_message_collection)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        logger.info("Keywords: %s", str(keywords))

        search_result_chunks = search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        logger.info("******** BEGIN SEARCH RESULT CHUNKS ************")
        logger.info("Search result chunks: %s", '\n\n'.join(filtered_chunks))
        logger.info("******** END SEARCH RESULT CHUNKS ************")

        return '\n\n'.join(filtered_chunks)

    def process_new_memory_chunks(self, chunks, hash_chunks, rag_system_prompt, rag_prompt, workflow,
                                  discussionId, messages, chunks_per_memory=3):
        """
        Processes new memory chunks by performing RAG on them and updating the memory file.

        This function takes a list of new chunks, uses RAG to summarize them,
        and appends the summaries to the existing memory file.

        Args:
            chunks (List[str]): A list of text chunks to be processed.
            hash_chunks (List[Tuple[str, str]]): A list of tuples containing
                                                 the text and hash for each chunk.
            rag_system_prompt (str): The system prompt for the RAG process.
            rag_prompt (str): The user prompt for the RAG process.
            workflow (dict): The workflow configuration dictionary.
            discussionId (str): The unique identifier for the current discussion.
            messages (List[Dict[str,str]]): The conversation messages.
            chunks_per_memory (int, optional): The number of chunks to process
                                               per memory. Defaults to 3.
        """
        rag_tool = SlowButQualityRAGTool()

        all_chunks = "--ChunkBreak--".join(chunks)
        logger.debug("Processing chunks: %s", all_chunks)

        result = rag_tool.perform_rag_on_memory_chunk(rag_system_prompt, rag_prompt, all_chunks, workflow, messages,
                                                      discussionId, "--rag_break--", chunks_per_memory)
        results = result.split("--rag_break--")
        logger.debug("Total results: %s", len(results))
        logger.debug("Total chunks: %s", len(hash_chunks))

        replaced = [(summary, hash_code) for summary, (_, hash_code) in zip(results, hash_chunks)]

        filepath = get_discussion_memory_file_path(discussionId)

        # Read existing chunks from the file
        existing_chunks = read_chunks_with_hashes(filepath)

        logger.debug("Existing chunks before reverse: %s", str(existing_chunks))

        # Append new chunks at the end
        updated_chunks = existing_chunks + replaced
        logger.debug("Updated chunks: %s", str(updated_chunks))

        # Save updated chunks to the file
        update_chunks_with_hashes(updated_chunks, filepath, mode="overwrite")

    def handle_discussion_id_flow(self, discussionId: str, messagesOriginal: List[Dict[str, str]]) -> None:
        """
        Manages the memory creation flow for a specific discussion ID.

        This function checks if new memories need to be generated based on
        the length of the conversation and the existing memory file. It
        then initiates the appropriate memory processing flow.

        Args:
            discussionId (str): The unique identifier for the current discussion.
            messagesOriginal (List[Dict[str, str]]): The conversation messages.
        """
        if len(messagesOriginal) < 3:
            logger.debug("Less than 3 messages, no memory will be generated.")
            return

        filepath = get_discussion_memory_file_path(discussionId)
        messages_copy = deepcopy(messagesOriginal)

        logger.debug("Entering discussionId Workflow")
        discussion_id_workflow_filepath = get_discussion_id_workflow_path()
        discussion_id_workflow_config = load_config(discussion_id_workflow_filepath)

        rag_system_prompt = discussion_id_workflow_config['systemPrompt']
        rag_prompt = discussion_id_workflow_config['prompt']
        messages_from_most_recent_to_skip = discussion_id_workflow_config['lookbackStartTurn']
        if not messages_from_most_recent_to_skip or messages_from_most_recent_to_skip < 1:
            messages_from_most_recent_to_skip = 3
        logger.debug("Skipping most recent messages. Number of most recent messages to skip: %s", str(
            messages_from_most_recent_to_skip))

        chunk_size = discussion_id_workflow_config.get('chunkEstimatedTokenSize', 1000)
        max_messages_between_chunks = discussion_id_workflow_config.get('maxMessagesBetweenChunks', 0)

        discussion_chunks = read_chunks_with_hashes(filepath)
        discussion_chunks.reverse()  # Reverse to maintain correct chronological order when processing

        if len(discussion_chunks) == 0:
            logger.debug("No discussion chunks")
            self.process_full_discussion_flow(messages_copy, rag_system_prompt, rag_prompt,
                                              discussion_id_workflow_config, discussionId)
        else:
            number_of_messages_to_pull = find_last_matching_hash_message(messages_copy, discussion_chunks,
                                                                         turns_to_skip_looking_back=messages_from_most_recent_to_skip)
            if (number_of_messages_to_pull > messages_from_most_recent_to_skip):
                number_of_messages_to_pull = number_of_messages_to_pull - messages_from_most_recent_to_skip
            else:
                number_of_messages_to_pull = 0

            logger.info("Number of messages since last memory chunk update: %s", number_of_messages_to_pull)

            messages_to_process = messages_copy[:-messages_from_most_recent_to_skip] if len(
                messages_copy) > messages_from_most_recent_to_skip else messages_copy
            logger.debug("Messages to process: %s", messages_to_process)
            if len(messages_to_process) == 0:
                return

            new_messages_to_evaluate = extract_last_n_turns(messages_to_process, number_of_messages_to_pull,
                                                            remove_all_systems_override=True)

            if (rough_estimate_token_length(
                    '\n'.join(
                        value for content in new_messages_to_evaluate for value in content.values())) > chunk_size) \
                    or number_of_messages_to_pull > max_messages_between_chunks:

                logger.debug("number_of_messages_to_pull is: %s", str(number_of_messages_to_pull))

                trimmed_discussion_pairs = new_messages_to_evaluate
                if (len(trimmed_discussion_pairs) == 0):
                    return

                trimmed_discussion_pairs.reverse()  # Reverse to process in chronological order
                logger.debug("Retrieved number of trimmed_discussion_pairs: %s", str(len(trimmed_discussion_pairs)))

                logger.debug("Trimmed discussion pairs:%s", str(trimmed_discussion_pairs))

                logger.debug("Before chunk messages with hashes")
                trimmed_discussion_chunks = chunk_messages_with_hashes(trimmed_discussion_pairs, chunk_size,
                                                                       max_messages_before_chunk=max_messages_between_chunks)
                logger.debug("Past chunk messages with hashes")

                trimmed_discussion_chunks.reverse()

                if len(trimmed_discussion_chunks) >= 1:
                    pass_chunks = extract_text_blocks_from_hashed_chunks(trimmed_discussion_chunks)

                    logger.info("Processing new memories")
                    self.process_new_memory_chunks(pass_chunks, trimmed_discussion_chunks, rag_system_prompt,
                                                   rag_prompt,
                                                   discussion_id_workflow_config, discussionId, messages_copy)

            elif max_messages_between_chunks == -1:
                self.process_full_discussion_flow(messages_copy, rag_system_prompt, rag_prompt,
                                                  discussion_id_workflow_config, discussionId)

    def process_full_discussion_flow(self, messages: List[Dict[str, str]], rag_system_prompt: str, rag_prompt: str,
                                     workflow_config: dict, discussionId: str) -> None:
        """
        Processes the entire discussion history to create a new set of memory chunks.

        This function is used when there are no existing memory chunks or when
        the memory file needs to be completely rebuilt. It chunks the conversation
        and processes each chunk in batches to create new memory summaries.

        Args:
            messages (List[Dict[str, str]]): The conversation messages.
            rag_system_prompt (str): The system prompt for the RAG process.
            rag_prompt (str): The user prompt for the RAG process.
            workflow_config (dict): The workflow configuration dictionary.
            discussionId (str): The unique identifier for the current discussion.
        """
        if len(messages) < 3:
            logger.debug("Less than 3 messages, no memory will be generated.")
            return

        logger.debug("Beginning full discussion flow")

        new_messages = deepcopy(messages)
        if len(new_messages) > 3:
            new_messages = new_messages[:-3]  # Exclude the last 3 messages

        new_messages.reverse()  # Reverse for chronological processing
        filtered_messages_to_chunk = [message for message in new_messages if
                                      message["role"] not in {"system", "images", "systemMes"}]

        chunk_size = workflow_config.get('chunkEstimatedTokenSize', 1500)
        chunk_hashes = chunk_messages_with_hashes(filtered_messages_to_chunk, chunk_size,
                                                  max_messages_before_chunk=0)
        chunk_hashes.reverse()  # Reverse chunks to maintain correct order

        logger.debug("Past chunking hashes")

        pass_chunks = extract_text_blocks_from_hashed_chunks(chunk_hashes)

        # Order is correct here
        logger.debug("Pass_chunks: %s", "\n".join(pass_chunks))
        logger.debug("\n\n*******************************\n\n")

        BATCH_SIZE = 10
        for i in range(0, len(chunk_hashes), BATCH_SIZE):
            batch_chunk_hashes = chunk_hashes[i:i + BATCH_SIZE]
            batch_pass_chunks = pass_chunks[i:i + BATCH_SIZE]

            # Order is correct here
            logger.debug("Batch chunk hashes: %s", str(batch_chunk_hashes))
            logger.debug("\n\n*******************************\n\n")

            # Order is correct here
            logger.debug("Batch pass chunk hashes: %s", "\n".join(batch_pass_chunks))
            logger.debug("\n\n*******************************\n\n")

            self.process_new_memory_chunks(batch_pass_chunks, batch_chunk_hashes, rag_system_prompt, rag_prompt,
                                           workflow_config, discussionId, messages)

    def perform_rag_on_memory_chunk(self, rag_system_prompt: str, rag_prompt: str, text_chunk: str, config: dict,
                                    messages, discussionId: str, custom_delimiter: str = "",
                                    chunks_per_memory: int = 3) -> str:
        """
        Performs RAG on a given chunk of a conversation and updates memory.

        This function processes a text chunk by retrieving relevant conversation
        history and chat summaries, and then using an LLM to generate a
        summarized result.

        Args:
            rag_system_prompt (str): The system prompt for the RAG process.
            rag_prompt (str): The user prompt for the RAG process.
            text_chunk (str): The chunk of text to process, separated by
                              '--ChunkBreak--'.
            config (dict): The workflow configuration dictionary.
            messages (List[Dict[str,str]]): The conversation messages.
            discussionId (str): The unique identifier for the current discussion.
            custom_delimiter (str, optional): A custom delimiter to separate
                                              the output chunks. Defaults to "".
            chunks_per_memory (int, optional): The number of memory chunks to
                                               consider for context. Defaults to 3.

        Returns:
            str: The processed chunks joined by the custom delimiter.
        """
        chunks = text_chunk.split('--ChunkBreak--')

        discussion_chunks = read_chunks_with_hashes(get_discussion_memory_file_path(discussionId))
        memory_chunks = extract_text_blocks_from_hashed_chunks(discussion_chunks)
        chat_summary = self.memory_service.get_current_summary(discussionId)

        endpoint_data = get_endpoint_config(config['endpointName'])
        llm_handler_service = LlmHandlerService()
        llm_handler = llm_handler_service.initialize_llm_handler(endpoint_data,
                                                                 config['preset'],
                                                                 config['endpointName'],
                                                                 False,
                                                                 endpoint_data.get("maxContextTokenSize", 4096),
                                                                 config.get("maxResponseSizeInTokens", 400))

        result_chunks = []
        for chunk in chunks:
            current_memories = '\n--------------\n'.join(memory_chunks[-3:]) if len(
                memory_chunks) >= 3 else '\n--------------\n'.join(memory_chunks)
            if current_memories is None:
                current_memories = ""

            full_memories = '\n--------------\n'.join(memory_chunks)
            if full_memories is None:
                full_memories = ""

            logger.debug("Processing memory chunk")
            system_prompt = rag_system_prompt.replace('[Memory_file]', current_memories.strip())
            prompt = rag_prompt.replace('[Memory_file]', current_memories.strip())

            system_prompt = system_prompt.replace('[Full_Memory_file]', full_memories.strip())
            prompt = prompt.replace('[Full_Memory_file]', full_memories.strip())

            system_prompt = system_prompt.replace('[Chat_Summary]', chat_summary.strip())
            prompt = prompt.replace('[Chat_Summary]', chat_summary.strip())

            result_chunk = SlowButQualityRAGTool.process_single_chunk(chunk, llm_handler, prompt, system_prompt,
                                                                      messages, config)
            result_chunks.append(result_chunk)
            memory_chunks.append(result_chunk)

        return custom_delimiter.join(result_chunks)

    @staticmethod
    def perform_rag_on_conversation_chunk(rag_system_prompt: str, rag_prompt: str, text_chunk: str, config: dict,
                                          custom_delimiter: str = "") -> str:
        """
        Performs Retrieval-Augmented Generation (RAG) on a given chunk of conversation.

        This static method splits a conversation chunk into sub-chunks and uses
        a parallel processing tool to run RAG on them.

        Args:
            rag_system_prompt (str): The system prompt for the RAG process.
            rag_prompt (str): The user prompt for the RAG process.
            text_chunk (str): The chunk of text to process.
            config (dict): A dictionary containing configuration parameters,
                           including the endpoint and preset settings.
            custom_delimiter (str, optional): A custom delimiter to separate
                                              the output chunks. Defaults to "".

        Returns:
            str: The processed chunks of text joined by the custom delimiter.
        """
        chunks = text_chunk.split('--ChunkBreak--')
        parallel_llm_processing_service = ParallelLlmProcessingTool(config)
        return parallel_llm_processing_service.process_prompt_chunks(chunks, rag_prompt, rag_system_prompt,
                                                                     custom_delimiter)

    @staticmethod
    def process_single_chunk(chunk, llm_handler, workflow_prompt, workflow_system_prompt,
                             messages, config):
        """
        Processes a single text chunk using the specified LLM handler.

        This static method formats prompts, handles message collection, and
        dispatches the request to the LLM handler to get a response for a
        single chunk.

        Args:
            chunk (str): The text chunk to be processed.
            llm_handler: The handler for processing the chunk.
            workflow_prompt (str): The user prompt to be used in processing.
            workflow_system_prompt (str): The system prompt to be used in processing.
            messages (List[Dict[str,str]]): The conversation messages.
            config (dict): The workflow configuration dictionary.

        Returns:
            str: The response from the LLM handler.
        """

        workflow_variable_service = WorkflowVariableManager()
        formatted_prompt = workflow_variable_service.apply_variables(workflow_prompt, llm_handler, messages,
                                                                     remove_all_system_override=True,
                                                                     config=config)
        formatted_system_prompt = workflow_variable_service.apply_variables(workflow_system_prompt, llm_handler,
                                                                            messages, remove_all_system_override=True,
                                                                            config=config)

        formatted_prompt = formatted_prompt.replace('[TextChunk]', chunk)
        formatted_system_prompt = formatted_system_prompt.replace('[TextChunk]', chunk)

        formatted_prompt = format_user_turn_with_template(formatted_prompt, llm_handler.prompt_template_file_name,
                                                          llm_handler.takes_message_collection)
        formatted_system_prompt = format_system_prompt_with_template(formatted_system_prompt,
                                                                     llm_handler.prompt_template_file_name,
                                                                     llm_handler.takes_message_collection)

        formatted_system_prompt = remove_discussion_id_tag_from_string(formatted_system_prompt)
        formatted_prompt = remove_discussion_id_tag_from_string(formatted_prompt)

        if llm_handler.add_generation_prompt:
            formatted_prompt = add_assistant_end_token_to_user_turn(formatted_prompt,
                                                                    llm_handler.prompt_template_file_name,
                                                                    isChatCompletion=llm_handler.takes_message_collection)

        if not llm_handler.takes_message_collection:
            result = llm_handler.llm.get_response_from_llm(system_prompt=formatted_system_prompt,
                                                           prompt=formatted_prompt,
                                                           llm_takes_images=llm_handler.takes_image_collection)
        else:
            collection = []
            if formatted_system_prompt:
                collection.append({"role": "system", "content": formatted_system_prompt})
            if formatted_prompt:
                collection.append({"role": "user", "content": formatted_prompt})

            result = llm_handler.llm.get_response_from_llm(collection,
                                                           llm_takes_images=llm_handler.takes_image_collection)

        if result:
            return result