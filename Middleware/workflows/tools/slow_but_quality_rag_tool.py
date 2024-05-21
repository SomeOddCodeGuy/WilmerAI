from Middleware.utilities.config_utils import get_discussion_memory_file_path, load_config, \
    get_discussion_chat_summary_file_path, get_default_parallel_processor_name, get_workflow_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes
from Middleware.utilities.logging_utils import log
from Middleware.utilities.prompt_extraction_utils import extract_pairs_and_system_prompt_from_wilmer_templated_string, \
    extract_last_n_turns, extract_discussion_id
from Middleware.utilities.prompt_utils import find_last_matching_memory_hash, \
    find_last_matching_hash_pair, get_pairs_within_index, chunk_turns_with_hashes, \
    extract_text_blocks_from_hashed_chunks
from Middleware.utilities.search_utils import filter_keywords_by_speakers, advanced_search_in_chunks, search_in_chunks
from Middleware.utilities.text_utils import turn_pairs_into_chunked_text_of_token_size
from Middleware.workflows.tools.parallel_llm_processing_tool import ParallelLlmProcessingTool


class SlowButQualityRAGTool:
    """
    A very slow but more thorough RAGing tool that utilizes LLMs to parse through
    large chunks of test to find the appropriate context
    """

    def __init__(self):
        pass

    def perform_keyword_search(self, keywords: str, target, **kwargs):
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
            if 'user_prompt' in kwargs:
                user_prompt = kwargs['user_prompt']
                result = self.perform_conversation_search(keywords, user_prompt, lookbackStartTurn)
                return result
            else:
                print("Fatal Workflow Error: cannot perform keyword search; no user prompt")
        elif target == "RecentMemories":
            if 'user_prompt' in kwargs:
                user_prompt = kwargs['user_prompt']
                result = self.perform_memory_file_keyword_search(keywords, user_prompt)
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
                chunk = chunk.replace('Assistant: ', '')
                new_chunks.append(chunk)
        return new_chunks

    def perform_conversation_search(self, keywords: str, user_prompt, lookbackStartTurn=0):
        """
        Perform a conversation search based on given keywords and user prompt.

        :param keywords: A string containing keywords to search for.
        :param user_prompt: A string representing the user's prompt for the conversation search.
        :param lookbackStartTurn: How many turns back from the most recent to begin our search
        :return: A string representing the search result chunks joined by '--ChunkBreak--'.
        """
        print("Entering perform_conversation_search")
        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt)

        # if we have less pairs than lookbackStartTurn, we can stop here
        if len(pairs) <= lookbackStartTurn:
            return 'There are no memories. This conversation has not gone long enough for there to be memories.'

        pair_chunks = self.get_pair_chunks_from_pairs(pairs, lookbackStartTurn, 400)

        # In case the LLM designated the speakers as keywords, we want to remove them
        # The speakers would trigger tons erroneous hits
        last_n_turns = extract_last_n_turns(user_prompt, 10)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        print("Keywords: " + str(keywords))

        search_result_chunks = advanced_search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = self.clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        print("******** BEGIN SEARCH RESULT CHUNKS ************")
        print("Search result chunks: ", '\n\n'.join(filtered_chunks))
        print("******** END SEARCH RESULT CHUNKS ************")

        return '--ChunkBreak--'.join(filtered_chunks)

    def perform_memory_file_keyword_search(self, keywords: str, user_prompt):
        """
        Perform a conversation search based on given keywords and user prompt.

        :param keywords: A string containing keywords to search for.
        :param user_prompt: A string representing the user's prompt for the conversation search.
        :return: A string representing the search result chunks joined by '--ChunkBreak--'.
        """
        print("Entering perform_conversation_search")
        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
        discussion_id = extract_discussion_id(system_prompt)
        filepath = get_discussion_memory_file_path(discussion_id)

        hash_chunks = read_chunks_with_hashes(filepath)
        pair_chunks = extract_text_blocks_from_hashed_chunks(hash_chunks)

        if len(pair_chunks) > 3:
            pair_chunks = pair_chunks[:-3]

        # In case the LLM designated the speakers as keywords, we want to remove them
        # The speakers would trigger tons erroneous hits
        last_n_turns = extract_last_n_turns(user_prompt, 10)
        keywords = filter_keywords_by_speakers(last_n_turns, keywords)
        print("Keywords: " + str(keywords))

        search_result_chunks = search_in_chunks(pair_chunks, keywords, 10)
        search_result_chunks = self.clear_out_user_assistant_from_chunks(search_result_chunks)
        filtered_chunks = [s for s in search_result_chunks if s]

        print("******** BEGIN SEARCH RESULT CHUNKS ************")
        print("Search result chunks: ", '\n\n'.join(filtered_chunks))
        print("******** END SEARCH RESULT CHUNKS ************")

        return '\n\n'.join(filtered_chunks)

    def process_new_memory_chunks(self, chunks, hash_chunks, rag_prompt, parallel_workflow, discussionId):
        rag_tool = SlowButQualityRAGTool()
        workflow = get_workflow_path(parallel_workflow)
        workflow_config = load_config(workflow)
        print("Workflow Name: " + workflow)

        all_chunks = "--ChunkBreak--".join(chunks)

        print("Processing chunks: ", all_chunks)

        result = rag_tool.perform_rag_on_conversation_chunk(rag_prompt,
                                                            all_chunks,
                                                            workflow_config,
                                                            "--rag_break--")
        results = result.split("--rag_break--")
        print("Total results: " + str(len(results)))
        print("Total chunks: " + str(len(hash_chunks)))
        print("Sample result:", results[0] if results else "No results available")
        print("Sample chunk:", hash_chunks[0] if hash_chunks else "No chunks available")

        # Now we replace the chunks in the chunk-hashes with processed summaries
        replaced = [(summary, hash_code) for summary, (_, hash_code) in zip(results, hash_chunks)]

        filepath = get_discussion_memory_file_path(discussionId)

        # Now save it to the file
        update_chunks_with_hashes(replaced, filepath)

    def get_recent_memories(self, user_prompt, max_turns_to_search=0, max_summary_chunks_from_file=0):
        print("Entered get_recent_memories")
        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
        discussion_id = extract_discussion_id(system_prompt)

        if discussion_id is None:
            final_pairs = self.get_recent_chat_pairs_up_to_max(max_turns_to_search, pairs)

            log("Recent Memory complete. Total number of pair chunks: {}".format(len(final_pairs)))

            return '--ChunkBreak--'.join(final_pairs)

        else:
            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_chunks = read_chunks_with_hashes(
                filepath)
            if len(hashed_chunks) == 0:
                final_pairs = self.get_recent_chat_pairs_up_to_max(max_turns_to_search, pairs)
                return '--ChunkBreak--'.join(final_pairs)
            else:
                chunks = extract_text_blocks_from_hashed_chunks(hashed_chunks)
                if max_summary_chunks_from_file == 0:
                    max_summary_chunks_from_file = 3
                elif max_summary_chunks_from_file == -1:
                    return chunks
                elif len(chunks) <= max_summary_chunks_from_file:
                    return chunks

                latest_summaries = chunks[-max_summary_chunks_from_file:]
                return '--ChunkBreak--'.join(latest_summaries)

    def get_chat_summary_memories(self, user_prompt, max_turns_to_search=0, max_summary_chunks_from_file=0):
        print("Entered get_chat_summary_memories")
        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
        discussion_id = extract_discussion_id(system_prompt)

        if discussion_id is None:
            final_pairs = self.get_recent_chat_pairs_up_to_max(max_turns_to_search, pairs)

            log("Chat Summary memory gathering complete. Total number of pair chunks: {}".format(len(final_pairs)))

            return '--ChunkBreak--'.join(final_pairs)

        else:
            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_memory_chunks = read_chunks_with_hashes(
                filepath)
            if len(hashed_memory_chunks) == 0:
                final_pairs = self.get_recent_chat_pairs_up_to_max(max_turns_to_search, pairs)
                return '--ChunkBreak--'.join(final_pairs)
            else:
                filepath = get_discussion_chat_summary_file_path(discussion_id)
                hashed_summary_chunk = read_chunks_with_hashes(
                    filepath)
                index = find_last_matching_memory_hash(hashed_summary_chunk, hashed_memory_chunks)

                if max_summary_chunks_from_file > 0 and 0 < index < max_summary_chunks_from_file:
                    max_summary_chunks_from_file = index

                memory_chunks = extract_text_blocks_from_hashed_chunks(hashed_memory_chunks)

                if max_summary_chunks_from_file == 0:
                    max_summary_chunks_from_file = 3
                elif max_summary_chunks_from_file == -1:
                    return memory_chunks
                elif len(memory_chunks) <= max_summary_chunks_from_file:
                    return memory_chunks

                latest_summaries = memory_chunks[-max_summary_chunks_from_file:]
                return '--ChunkBreak--'.join(latest_summaries)

    def get_recent_chat_pairs_up_to_max(self, max_turns_to_search, pairs):
        # if we have less pairs than lookbackStartTurn, we can stop here
        if len(pairs) <= 1:
            print("No memory chunks")
            return 'There are no memories. This conversation has not gone long enough for there to be memories.'

        print("Number of pairs: " + str(len(pairs)))

        # Take the last max_turns_to_search number of pairs from the collection
        if max_turns_to_search > 0:
            pairs = pairs[-min(max_turns_to_search, len(pairs)):]

        print("Max turns to search: " + str(max_turns_to_search))
        print("Number of pairs: " + str(len(pairs)))

        pair_chunks = self.get_pair_chunks_from_pairs(pairs, 0, 400)
        filtered_chunks = [s for s in pair_chunks if s]

        final_pairs = self.clear_out_user_assistant_from_chunks(filtered_chunks)

        return final_pairs

    def handle_discussion_id_flow(self, discussionId, pairs):
        filepath = get_discussion_memory_file_path(discussionId)

        # If there is, we will use long term memory instead
        print("Entering discussionId Workflow")
        rag_prompt = ("Below, within brackets, is an excerpt from a roleplay. Please summarize, in vivid and "
                      "complete detail, the events within the excerpt. This summary will be added to a running "
                      "collection of summaries, so please don't write anything else except the summary. "
                      "Please use the character/user names explicitly, as some may write in first person but "
                      "you need to write your descriptions in third person."
                      "\n[\n[TextChunk]\n]\n")
        parallel_workflow = get_default_parallel_processor_name()
        discussion_chunks = read_chunks_with_hashes(filepath)
        if len(discussion_chunks) == 0:
            print("No discussion chunks")
            self.process_full_discussion_flow(pairs, rag_prompt, parallel_workflow, discussionId)
        else:
            index = find_last_matching_hash_pair(pairs, discussion_chunks)
            print("Index within recent memory: ", index)
            if index > 5:
                trimmed_discussion_pairs = get_pairs_within_index(pairs, index)
                print("Trimmed discussion pair length: ", len(trimmed_discussion_pairs))
                print(trimmed_discussion_pairs)
                print("Entering chunking")
                trimmed_discussion_chunks = chunk_turns_with_hashes(trimmed_discussion_pairs, 1500)
                if len(trimmed_discussion_chunks) > 1:
                    # Remove chunk of most recent pairs
                    chunks = trimmed_discussion_chunks[:-1]
                    pass_chunks = extract_text_blocks_from_hashed_chunks(chunks)

                    self.process_new_memory_chunks(pass_chunks,
                                                   trimmed_discussion_chunks,
                                                   rag_prompt,
                                                   parallel_workflow,
                                                   discussionId)
            elif index == -1:
                print("-1 flow hit. Processing discussions")
                self.process_full_discussion_flow(pairs, rag_prompt, parallel_workflow, discussionId)

    def process_full_discussion_flow(self, pairs, rag_prompt, parallel_workflow, discussionId):
        chunk_hashes = chunk_turns_with_hashes(pairs, 1500)
        chunk_hashes.reverse()
        pass_chunks = extract_text_blocks_from_hashed_chunks(chunk_hashes)
        BATCH_SIZE = 20

        # Iterate through the arrays in batches
        for i in range(0, len(chunk_hashes), BATCH_SIZE):
            # Create a batch slice for both arrays
            batch_chunk_hashes = chunk_hashes[i:i + BATCH_SIZE]
            batch_pass_chunks = pass_chunks[i:i + BATCH_SIZE]

            print("Length of batch_chunk_hashes: ", len(batch_chunk_hashes))

            # Process the current batch
            self.process_new_memory_chunks(batch_pass_chunks, batch_chunk_hashes, rag_prompt, parallel_workflow,
                                           discussionId)

    def get_pair_chunks_from_pairs(self, pairs, lookbackStartTurn: int, chunk_size):
        if lookbackStartTurn > 0:
            pairs = pairs[-lookbackStartTurn:]
        else:
            # Let's drop the last item in the list; the search has a bad tendency to
            # respond to the message
            if len(pairs) > 1:
                pairs = pairs[:-1]

        # We're going to break the conversation into 500 token chunks, and then perform our search
        return turn_pairs_into_chunked_text_of_token_size(pairs, chunk_size)

    @staticmethod
    def perform_rag_on_conversation_chunk(rag_prompt: str, text_chunk: str, config, custom_delimiter=""):
        chunks = text_chunk.split('--ChunkBreak--')

        parallel_llm_processing_service = ParallelLlmProcessingTool(config)
        return parallel_llm_processing_service.process_prompt_chunks(chunks, rag_prompt, custom_delimiter)
