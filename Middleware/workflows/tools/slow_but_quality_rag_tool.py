from copy import deepcopy
import logging
from typing import List, Dict

from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities.config_utils import get_discussion_memory_file_path, load_config, \
    get_discussion_id_workflow_path, get_endpoint_config
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns, \
    remove_discussion_id_tag_from_string
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template, \
    format_system_prompt_with_template, add_assistant_end_token_to_user_turn
from Middleware.utilities.prompt_utils import chunk_messages_with_hashes, \
    extract_text_blocks_from_hashed_chunks, find_last_matching_hash_message
from Middleware.utilities.search_utils import filter_keywords_by_speakers, advanced_search_in_chunks, search_in_chunks
from Middleware.utilities.text_utils import get_message_chunks, clear_out_user_assistant_from_chunks, \
    rough_estimate_token_length
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.tools.parallel_llm_processing_tool import ParallelLlmProcessingTool

logger = logging.getLogger(__name__)

class SlowButQualityRAGTool:
    """
    A very slow but more thorough RAG tool that utilizes LLMs to parse through
    large chunks of text to find the appropriate context
    """

    def __init__(self):
        pass

    def perform_keyword_search(self, keywords: str, target, llm_handler, discussion_id, **kwargs):
        """
        :param keywords: A string representing the keywords to search for.
        :param target: The target object to perform the keyword search on.
        :param kwargs: Additional keyword arguments.
        :return: The result of the keyword search.

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
                logger.info("Fatal Workflow Error: cannot perform keyword search; no user prompt")
        elif target == "RecentMemories":
            if 'messages' in kwargs:
                messages = kwargs['messages']
                logger.info("In recent memories")
                logger.info(messages)
                result = self.perform_memory_file_keyword_search(keywords, messages, llm_handler, discussion_id)
                return result

    def perform_conversation_search(self, keywords: str, messagesOriginal, llm_handler, lookbackStartTurn=0):
        """
        Perform a conversation search based on given keywords and user prompt.

        Args:
            keywords (str): A string containing keywords to search for.
            messagesOriginal (list): A collection representing the user's prompt for the conversation search.
            lookbackStartTurn (int, optional): How many turns back from the most recent to begin our search. Defaults to 0.

        Returns:
            str: A string representing the search result chunks joined by '--ChunkBreak--'.
        """
        logger.info("Entering perform_conversation_search")

        # If we have fewer pairs than lookbackStartTurn, we can stop here
        if len(messagesOriginal) <= lookbackStartTurn:
            return 'There are no memories. This conversation has not gone long enough for there to be memories.'

        message_copy = deepcopy(messagesOriginal)

        pair_chunks = get_message_chunks(message_copy, lookbackStartTurn, 400)

        # In case the LLM designated the speakers as keywords, we want to remove them
        # The speakers would trigger tons of erroneous hits
        last_n_turns = extract_last_n_turns(message_copy, 10, llm_handler.takes_message_collection)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        logger.info("Keywords: " + str(keywords))

        search_result_chunks = advanced_search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        logger.info("******** BEGIN SEARCH RESULT CHUNKS ************")
        logger.info("Search result chunks: ", '\n\n'.join(filtered_chunks))
        logger.info("******** END SEARCH RESULT CHUNKS ************")

        return '--ChunkBreak--'.join(filtered_chunks)

    def perform_memory_file_keyword_search(self, keywords: str, messagesOriginal, llm_handler, discussion_id):
        """
        Perform a memory file keyword search based on given keywords and user prompt.

        Args:
            keywords (str): A string containing keywords to search for.
            messagesOriginal (list): A collection representing the user's prompt for the conversation search.

        Returns:
            str: A string representing the search result chunks joined by '--ChunkBreak--'.
        """
        logger.info("Entering perform_memory_file_keyword_search")
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
        logger.info("Keywords: " + str(keywords))

        search_result_chunks = search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        logger.info("******** BEGIN SEARCH RESULT CHUNKS ************")
        logger.info("Search result chunks: ", '\n\n'.join(filtered_chunks))
        logger.info("******** END SEARCH RESULT CHUNKS ************")

        return '\n\n'.join(filtered_chunks)

    def process_new_memory_chunks(self, chunks, hash_chunks, rag_system_prompt, rag_prompt, workflow,
                                  discussionId, messages, chunks_per_memory=3):
        """
        Processes new memory chunks by performing RAG on them and updating the memory file.
        """
        rag_tool = SlowButQualityRAGTool()
        chunks.reverse()

        all_chunks = "--ChunkBreak--".join(chunks)
        logger.info("Processing chunks: ", all_chunks)

        result = rag_tool.perform_rag_on_memory_chunk(rag_system_prompt, rag_prompt, all_chunks, workflow, messages,
                                                      discussionId, "--rag_break--", chunks_per_memory)
        results = result.split("--rag_break--")
        results.reverse()
        logger.info("Total results: " + str(len(results)))
        logger.info("Total chunks: " + str(len(hash_chunks)))
        hash_chunks.reverse()

        replaced = [(summary, hash_code) for summary, (_, hash_code) in zip(results, hash_chunks)]

        filepath = get_discussion_memory_file_path(discussionId)

        # Read existing chunks from the file
        existing_chunks = read_chunks_with_hashes(filepath)

        print("Existing chunks before reverse: ", str(existing_chunks))
        replaced.reverse()

        # Append new chunks at the end
        updated_chunks = existing_chunks + replaced
        print("Updated chunks: " + str(updated_chunks))

        # Save updated chunks to the file
        update_chunks_with_hashes(updated_chunks, filepath, mode="overwrite")

    def handle_discussion_id_flow(self, discussionId: str, messagesOriginal: List[Dict[str, str]]) -> None:
        """
        Handle the discussion flow based on the discussion ID and messages provided.
        """
        if len(messagesOriginal) < 3:
            print("Less than 3 messages, no memory will be generated.")
            return

        filepath = get_discussion_memory_file_path(discussionId)
        messages_copy = deepcopy(messagesOriginal)

        logger.info("Entering discussionId Workflow")
        discussion_id_workflow_filepath = get_discussion_id_workflow_path()
        discussion_id_workflow_config = load_config(discussion_id_workflow_filepath)

        rag_system_prompt = discussion_id_workflow_config['systemPrompt']
        rag_prompt = discussion_id_workflow_config['prompt']

        chunk_size = discussion_id_workflow_config.get('chunkEstimatedTokenSize', 1000)
        max_messages_between_chunks = discussion_id_workflow_config.get('maxMessagesBetweenChunks', 0)

        discussion_chunks = read_chunks_with_hashes(filepath)
        discussion_chunks.reverse()  # Reverse to maintain correct chronological order when processing

        if len(discussion_chunks) == 0:
            logger.info("No discussion chunks")
            self.process_full_discussion_flow(messages_copy, rag_system_prompt, rag_prompt,
                                              discussion_id_workflow_config, discussionId)
        else:
            number_of_messages_to_pull = find_last_matching_hash_message(messages_copy, discussion_chunks)
            if (number_of_messages_to_pull > 3):
                number_of_messages_to_pull = number_of_messages_to_pull - 3
            else:
                number_of_messages_to_pull = 0

            logger.info("Number of messages since last memory chunk update: ", number_of_messages_to_pull)

            messages_to_process = messages_copy[:-3] if len(messages_copy) > 3 else messages_copy
            logger.info("Messages to process: ", messages_to_process)
            if (len(messages_to_process) == 0):
                return

            if (rough_estimate_token_length(
                    '\n'.join(value for content in messages_to_process for value in content.values())) > chunk_size) \
                    or number_of_messages_to_pull > max_messages_between_chunks:

                logger.info("number_of_messages_to_pull is: " + str(number_of_messages_to_pull))
                trimmed_discussion_pairs = extract_last_n_turns(messages_to_process, number_of_messages_to_pull,
                                                                remove_all_systems_override=True)
                if (len(trimmed_discussion_pairs) == 0):
                    return

                trimmed_discussion_pairs.reverse()  # Reverse to process in chronological order
                logger.info("Retrieved number of trimmed_discussion_pairs: " + str(len(trimmed_discussion_pairs)))

                logger.info("Trimmed discussion pairs:" + str(trimmed_discussion_pairs))

                print("Before chunk messages with hashes")
                trimmed_discussion_chunks = chunk_messages_with_hashes(trimmed_discussion_pairs, chunk_size,
                                                                       max_messages_before_chunk=max_messages_between_chunks)
                logger.info("Past chunk messages with hashes")

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
        Process the entire discussion flow if no previous chunks are available or if the
        last chunk is outdated.
        """
        if len(messages) < 3:
            print("Less than 3 messages, no memory will be generated.")
            return

        logger.info("Beginning full discussion flow")

        new_messages = deepcopy(messages)
        if len(new_messages) > 3:
            new_messages = new_messages[:-3]  # Exclude the last 3 messages

        new_messages.reverse()  # Reverse for chronological processing
        filtered_messages_to_chunk = [message for message in new_messages if message["role"] != "system"]

        chunk_size = workflow_config.get('chunkEstimatedTokenSize', 1500)
        max_messages_between_chunks = workflow_config.get('maxMessagesBetweenChunks', 0)
        chunk_hashes = chunk_messages_with_hashes(filtered_messages_to_chunk, chunk_size,
                                                  max_messages_before_chunk=max_messages_between_chunks)
        chunk_hashes.reverse()  # Reverse chunks to maintain correct order

        print("Past chunking hashes")

        pass_chunks = extract_text_blocks_from_hashed_chunks(chunk_hashes)
        pass_chunks.reverse()  # Ensure correct order for chunk processing

        BATCH_SIZE = 10
        for i in range(0, len(chunk_hashes), BATCH_SIZE):
            batch_chunk_hashes = chunk_hashes[i:i + BATCH_SIZE]
            batch_pass_chunks = pass_chunks[i:i + BATCH_SIZE]

            self.process_new_memory_chunks(batch_pass_chunks, batch_chunk_hashes, rag_system_prompt, rag_prompt,
                                           workflow_config, discussionId, messages)

    @staticmethod
    def perform_rag_on_conversation_chunk(rag_system_prompt: str, rag_prompt: str, text_chunk: str, config: dict,
                                          custom_delimiter: str = "") -> str:
        """
        Perform Retrieval-Augmented Generation (RAG) on a given chunk of conversation.

        Args:
            rag_system_prompt (str): The system prompt for the RAG process.
            rag_prompt (str): The prompt used for RAG processing.
            text_chunk (str): The chunk of text to process.
            config (dict): Configuration parameters for the RAG process.
            custom_delimiter (str, optional): Custom delimiter to separate chunks. Defaults to "".

        Returns:
            List[str]: The processed chunks of text.
        """
        chunks = text_chunk.split('--ChunkBreak--')
        parallel_llm_processing_service = ParallelLlmProcessingTool(config)
        return parallel_llm_processing_service.process_prompt_chunks(chunks, rag_prompt, rag_system_prompt,
                                                                     custom_delimiter)

    @staticmethod
    def perform_rag_on_memory_chunk(rag_system_prompt: str, rag_prompt: str, text_chunk: str, config: dict,
                                    messages, discussionId: str, custom_delimiter: str = "",
                                    chunks_per_memory: int = 3) -> str:
        """
        Perform RAG on a given chunk of conversation.
        """
        chunks = text_chunk.split('--ChunkBreak--')

        discussion_chunks = read_chunks_with_hashes(get_discussion_memory_file_path(discussionId))
        memory_chunks = extract_text_blocks_from_hashed_chunks(discussion_chunks)

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

            logger.info("Processing memory chunk. Current memories is: [[" + current_memories.strip() + "]]")
            system_prompt = rag_system_prompt.replace('[Memory_file]', current_memories.strip())
            prompt = rag_prompt.replace('[Memory_file]', current_memories.strip())

            result_chunk = SlowButQualityRAGTool.process_single_chunk(chunk, llm_handler, prompt, system_prompt,
                                                                      messages, config)
            result_chunks.append(result_chunk)
            memory_chunks.append(result_chunk)

        return custom_delimiter.join(result_chunks)

    @staticmethod
    def process_single_chunk(chunk, llm_handler, workflow_prompt, workflow_system_prompt,
                             messages, config):
        """
        Processes a single chunk using the specified LLM handler.

        Parameters:
        chunk (str): The text chunk to be processed.
        index (int): The index of the chunk in the original text.
        llm_handler (LlmHandlerService): The handler for processing the chunk.
        workflow_prompt (str): The prompt used in processing.
        workflow_system_prompt (str): The system prompt used in processing.
        results_queue (Queue): Queue where the result is placed after processing.
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
                                                           prompt=formatted_prompt)
        else:
            collection = []
            if formatted_system_prompt:
                collection.append({"role": "system", "content": formatted_system_prompt})
            if formatted_prompt:
                collection.append({"role": "user", "content": formatted_prompt})

            result = llm_handler.llm.get_response_from_llm(collection)

        if result:
            return result
