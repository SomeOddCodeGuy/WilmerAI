from copy import deepcopy
from typing import List, Dict

from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities.config_utils import get_discussion_memory_file_path, load_config, \
    get_discussion_chat_summary_file_path, get_discussion_id_workflow_path, get_endpoint_config
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns, \
    remove_discussion_id_tag_from_string
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template, \
    format_system_prompt_with_template, add_assistant_end_token_to_user_turn
from Middleware.utilities.prompt_utils import find_last_matching_memory_hash, chunk_messages_with_hashes, \
    extract_text_blocks_from_hashed_chunks, find_last_matching_hash_message
from Middleware.utilities.search_utils import filter_keywords_by_speakers, advanced_search_in_chunks, search_in_chunks
from Middleware.utilities.text_utils import messages_into_chunked_text_of_token_size
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.tools.parallel_llm_processing_tool import ParallelLlmProcessingTool


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
                print("Fatal Workflow Error: cannot perform keyword search; no user prompt")
        elif target == "RecentMemories":
            if 'messages' in kwargs:
                messages = kwargs['messages']
                print("In recent memories")
                print(messages)
                result = self.perform_memory_file_keyword_search(keywords, messages, llm_handler, discussion_id)
                return result

    @staticmethod
    def clear_out_user_assistant_from_chunks(search_result_chunks):
        """
        Clears out the user assistant from each chunk in the given search result chunks.

        :param search_result_chunks: A list of chunks, each representing a response from a user assistant.
        :return: A new list of chunks with the user assistant removed.

        Example usage:
        search_result_chunks = ['User: Hello', 'Assistant: Hi', 'User: How are you?', 'Assistant: I'm good']
        new_chunks = clear_out_user_assistant_from_chunks(search_result_chunks)
        print(new_chunks)
        # Output: ['Hello', 'Hi', 'How are you?', "I'm good"]
        """
        new_chunks = []
        for chunk in search_result_chunks:
            if chunk is not None:
                chunk = chunk.replace('User: ', '')
                chunk = chunk.replace('USER: ', '')
                chunk = chunk.replace('Assistant: ', '')
                chunk = chunk.replace('ASSISTANT: ', '')
                chunk = chunk.replace('systemMes: ', '')
                chunk = chunk.replace('SYSTEMMES: ', '')
                new_chunks.append(chunk)
        return new_chunks

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
        print("Entering perform_conversation_search")

        # If we have fewer pairs than lookbackStartTurn, we can stop here
        if len(messagesOriginal) <= lookbackStartTurn:
            return 'There are no memories. This conversation has not gone long enough for there to be memories.'

        message_copy = deepcopy(messagesOriginal)

        pair_chunks = self.get_message_chunks(message_copy, lookbackStartTurn, 400)

        # In case the LLM designated the speakers as keywords, we want to remove them
        # The speakers would trigger tons of erroneous hits
        last_n_turns = extract_last_n_turns(message_copy, 10, llm_handler.takes_message_collection)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        print("Keywords: " + str(keywords))

        search_result_chunks = advanced_search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = self.clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        print("******** BEGIN SEARCH RESULT CHUNKS ************")
        print("Search result chunks: ", '\n\n'.join(filtered_chunks))
        print("******** END SEARCH RESULT CHUNKS ************")

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
        print("Entering perform_memory_file_keyword_search")
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
        print("Keywords: " + str(keywords))

        search_result_chunks = search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = self.clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        print("******** BEGIN SEARCH RESULT CHUNKS ************")
        print("Search result chunks: ", '\n\n'.join(filtered_chunks))
        print("******** END SEARCH RESULT CHUNKS ************")

        return '\n\n'.join(filtered_chunks)

    def process_new_memory_chunks(self, chunks, hash_chunks, rag_system_prompt, rag_prompt, workflow,
                                  discussionId, messages):
        """
        Processes new memory chunks by performing RAG (Retrieval-Augmented Generation) on them and updating the memory file.

        Args:
            chunks (list of str): The new memory chunks to process.
            hash_chunks (list of tuple): A list of tuples containing hashes and their associated chunks.
            rag_system_prompt (str): The system prompt for the RAG tool.
            rag_prompt (str): The user prompt for the RAG tool.
            workflow (dict): The workflow to use for processing chunks.
            discussionId (str): The ID of the discussion for which memory is being processed.

        Returns:
            None
        """
        rag_tool = SlowButQualityRAGTool()

        all_chunks = "--ChunkBreak--".join(chunks)
        print("Processing chunks: ", all_chunks)

        result = rag_tool.perform_rag_on_memory_chunk(rag_system_prompt, rag_prompt, all_chunks, workflow,
                                                      messages, discussionId,
                                                      "--rag_break--")
        results = result.split("--rag_break--")
        print("Total results: " + str(len(results)))
        print("Total chunks: " + str(len(hash_chunks)))
        print("Sample result:", results[0] if results else "No results available")
        print("Sample chunk:", hash_chunks[0] if hash_chunks else "No chunks available")

        # Replace the chunks in the chunk-hashes with processed summaries
        replaced = [(summary, hash_code) for summary, (_, hash_code) in zip(results, hash_chunks)]

        filepath = get_discussion_memory_file_path(discussionId)

        # Save to file
        update_chunks_with_hashes(replaced, filepath)

    def get_recent_memories(self, messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0,
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
        print("Entered get_recent_memories")

        if discussion_id is None:
            final_pairs = self.get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
            print("Recent Memory complete. Total number of pair chunks: {}".format(len(final_pairs)))
            return '--ChunkBreak--'.join(final_pairs)
        else:
            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_chunks = read_chunks_with_hashes(filepath)
            if len(hashed_chunks) == 0:
                final_pairs = self.get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
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

    def get_chat_summary_memories(self, messages: List[Dict[str, str]], discussion_id: str, max_turns_to_search=0,
                                  max_summary_chunks_from_file=0):
        """
        Retrieves chat summary memories from messages or memory files.

        Args:
            messages (List[Dict[str, str]]): The list of recent chat messages.
            max_turns_to_search (int): Maximum turns to search in the chat history.
            max_summary_chunks_from_file (int): Maximum summary chunks to retrieve from memory files.

        Returns:
            str: The chat summary memories concatenated as a single string with '--ChunkBreak--' delimiter.
        """
        print("Entered get_chat_summary_memories")

        if discussion_id is None:
            final_pairs = self.get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
            print("Chat Summary memory gathering complete. Total number of pair chunks: {}".format(len(final_pairs)))
            return '\n------------\n'.join(final_pairs)
        else:
            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_memory_chunks = read_chunks_with_hashes(filepath)
            if len(hashed_memory_chunks) == 0:
                final_pairs = self.get_recent_chat_messages_up_to_max(max_turns_to_search, messages)
                return '\n------------\n'.join(final_pairs)
            else:
                filepath = get_discussion_chat_summary_file_path(discussion_id)
                hashed_summary_chunk = read_chunks_with_hashes(filepath)
                index = find_last_matching_memory_hash(hashed_summary_chunk, hashed_memory_chunks)

                if max_summary_chunks_from_file > 0 and 0 < index < max_summary_chunks_from_file:
                    max_summary_chunks_from_file = index

                memory_chunks = extract_text_blocks_from_hashed_chunks(hashed_memory_chunks)

                if max_summary_chunks_from_file == 0:
                    max_summary_chunks_from_file = 3
                elif max_summary_chunks_from_file == -1:
                    return '\n------------\n'.join(memory_chunks)
                elif len(memory_chunks) <= max_summary_chunks_from_file:
                    return '\n------------\n'.join(memory_chunks)

                latest_summaries = memory_chunks[-max_summary_chunks_from_file:]
                return '\n------------\n'.join(latest_summaries)

    def get_recent_chat_messages_up_to_max(self, max_turns_to_search: int, messages: List[Dict[str, str]]) -> List[str]:
        """
        Retrieves recent chat messages up to a maximum number of turns to search.

        Args:
            max_turns_to_search (int): Maximum number of turns to search in the chat history.
            messages (List[Dict[str, str]]): The list of recent chat messages.

        Returns:
            List[str]: The recent chat messages as a list of chunks.
        """
        if len(messages) <= 1:
            print("No memory chunks")
            return []

        print("Number of pairs: " + str(len(messages)))

        # Take the last max_turns_to_search number of pairs from the collection
        message_copy = deepcopy(messages)
        if max_turns_to_search > 0:
            message_copy = message_copy[-min(max_turns_to_search, len(message_copy)):]

        print("Max turns to search: " + str(max_turns_to_search))
        print("Number of pairs: " + str(len(message_copy)))

        pair_chunks = self.get_message_chunks(message_copy, 0, 400)
        filtered_chunks = [s for s in pair_chunks if s]

        final_pairs = self.clear_out_user_assistant_from_chunks(filtered_chunks)

        return final_pairs

    def handle_discussion_id_flow(self, discussionId: str, messagesOriginal: List[Dict[str, str]]) -> None:
        """
        Handle the discussion flow based on the discussion ID and messages provided.

        This method manages the discussion by determining if existing memory chunks
        should be used or if a full discussion flow should be processed. It uses various
        configurations and workflow parameters to guide the process.

        Args:
            discussionId (str): The unique identifier for the discussion.
            messagesOriginal (List[Dict[str, str]]): The list of message dictionaries for the discussion.
        """
        filepath = get_discussion_memory_file_path(discussionId)

        messages_copy = deepcopy(messagesOriginal)

        print("Entering discussionId Workflow")
        discussion_id_workflow_filepath = get_discussion_id_workflow_path()
        discussion_id_workflow_config = load_config(discussion_id_workflow_filepath)
        print(discussion_id_workflow_config)

        rag_system_prompt = discussion_id_workflow_config['systemPrompt']
        rag_prompt = discussion_id_workflow_config['prompt']
        chunk_size = discussion_id_workflow_config.get('chunkEstimatedTokenSize', 1500)
        chunks_til_new_memory = discussion_id_workflow_config.get('chunksUntilNewMemory', 5)

        discussion_chunks = read_chunks_with_hashes(filepath)
        discussion_chunks.reverse()

        if len(discussion_chunks) == 0:
            print("No discussion chunks")
            self.process_full_discussion_flow(messages_copy, rag_system_prompt, rag_prompt,
                                              discussion_id_workflow_config,
                                              discussionId)
        else:
            index = find_last_matching_hash_message(messages_copy, discussion_chunks)
            print("Number of messages since last memory chunk update: ", index)
            if index > chunks_til_new_memory:
                trimmed_discussion_pairs = extract_last_n_turns(messages_copy, index, remove_all_systems_override=True)
                trimmed_discussion_pairs.reverse()
                print("Trimmed discussion message length: ", len(trimmed_discussion_pairs))
                print(trimmed_discussion_pairs)
                print("Entering chunking")
                trimmed_discussion_chunks = chunk_messages_with_hashes(trimmed_discussion_pairs, chunk_size)
                if len(trimmed_discussion_chunks) > 1:
                    chunks = trimmed_discussion_chunks[:-1]
                    pass_chunks = extract_text_blocks_from_hashed_chunks(chunks)

                    self.process_new_memory_chunks(pass_chunks, trimmed_discussion_chunks, rag_system_prompt,
                                                   rag_prompt, discussion_id_workflow_config, discussionId,
                                                   messages_copy)
            elif index == -1:
                print("-1 flow hit. Processing discussions")
                self.process_full_discussion_flow(messages_copy, rag_system_prompt, rag_prompt,
                                                  discussion_id_workflow_config,
                                                  discussionId)

    def process_full_discussion_flow(self, messages: List[Dict[str, str]], rag_system_prompt: str, rag_prompt: str,
                                     workflow_config: dict, discussionId: str) -> None:
        """
        Process the entire discussion flow if no previous chunks are available or if the
        last chunk is outdated.

        Args:
            messages (List[Dict[str, str]]): The list of message dictionaries for the discussion.
            rag_system_prompt (str): The system prompt for the RAG process.
            rag_prompt (str): The prompt used for RAG processing.
            workflow_config (dict): The name of the parallel processing workflow.
            discussionId (str): The unique identifier for the discussion.
        """
        print("Beginning full discussion flow")
        new_messages = deepcopy(messages)
        if (len(new_messages) > 1
                and new_messages[-1]['role'] == 'assistant'
                and len(new_messages[-1].get('content', '')) < 30):
            new_messages = new_messages[:-1]

        new_messages.reverse()
        filtered_messaged_to_chunk = [message for message in new_messages if message["role"] != "system"]

        chunk_hashes = chunk_messages_with_hashes(filtered_messaged_to_chunk, 1500)
        pass_chunks = extract_text_blocks_from_hashed_chunks(chunk_hashes)
        pass_chunks.reverse()
        chunk_hashes.reverse()
        BATCH_SIZE = 10

        for i in range(0, len(chunk_hashes), BATCH_SIZE):
            batch_chunk_hashes = chunk_hashes[i:i + BATCH_SIZE]
            batch_pass_chunks = pass_chunks[i:i + BATCH_SIZE]

            print("Length of batch_chunk_hashes: ", len(batch_chunk_hashes))

            self.process_new_memory_chunks(batch_pass_chunks, batch_chunk_hashes, rag_system_prompt, rag_prompt,
                                           workflow_config, discussionId, messages)

    def get_message_chunks(self, messages: List[Dict[str, str]], lookbackStartTurn: int, chunk_size: int) -> List[str]:
        """
        Break down the conversation into chunks of a specified size for processing.

        Args:
            messages (List[Dict[str, str]]): The list of message dictionaries for the discussion.
            lookbackStartTurn (int): The number of turns to look back in the conversation.
            chunk_size (int): The maximum size of each chunk in tokens.

        Returns:
            List[str]: The list of message chunks.
        """
        pairs = []
        messageCopy = deepcopy(messages)
        if lookbackStartTurn > 0:
            pairs = messageCopy[-lookbackStartTurn:]
        else:
            if len(messageCopy) > 1:
                pairs = messageCopy[:-1]

        return messages_into_chunked_text_of_token_size(pairs, chunk_size)

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
                                    messages, discussionId: str,
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

        filepath = get_discussion_memory_file_path(discussionId)
        discussion_chunks = read_chunks_with_hashes(filepath)

        endpoint_data = get_endpoint_config(config['endpointName'])
        llm_handler_service = LlmHandlerService()
        llm_handler = llm_handler_service.initialize_llm_handler(endpoint_data,
                                                                 config['preset'],
                                                                 config['endpointName'],
                                                                 False,
                                                                 endpoint_data.get("maxContextTokenSize", 4096),
                                                                 config.get("maxResponseSizeInTokens", 400))

        result_chunks = []
        memory_chunks = extract_text_blocks_from_hashed_chunks(discussion_chunks)
        print("Chunks:", chunks)

        for chunk in chunks:
            if memory_chunks is not None and len(memory_chunks) > 0:
                if (len(memory_chunks) < 4):
                    print("Memory chunks:", memory_chunks)
                    current_memories = '\n--------------\n'.join(
                        memory_chunks)
                else:
                    last_three_chunks = memory_chunks[-3:]
                    current_memories = '\n--------------\n'.join(
                        last_three_chunks)
            else:
                current_memories = ""

            print("Processing memory chunk. Current memories is: [[" + current_memories.strip() + "]]")
            system_prompt = rag_system_prompt.replace('[Memory_file]', current_memories.strip())
            prompt = rag_prompt.replace('[Memory_file]', current_memories.strip())

            result_chunk = SlowButQualityRAGTool.process_single_chunk(chunk, llm_handler, prompt, system_prompt,
                                                                      messages, config)
            memory_chunks.append(result_chunk)
            result_chunks.append(result_chunk)

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
