from typing import Dict, Any, Optional, List, Tuple

from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_discussion_chat_summary_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, \
    update_chunks_with_hashes
from Middleware.utilities.prompt_extraction_utils import extract_pairs_and_system_prompt_from_wilmer_templated_string, \
    extract_discussion_id
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool


class PromptProcessor:

    def __init__(self, workflow_variable_service: Any, llm_handler: Any) -> None:
        """
        Initializes the PromptProcessor class.

        :param workflow_variable_service: The service responsible for applying variables to prompts.
        :param llm_handler: The handler for interacting with large language models (LLMs).
        """
        self.workflow_variable_service = workflow_variable_service
        self.slow_but_quality_rag_service = SlowButQualityRAGTool()
        self.llm_handler = llm_handler

    def perform_slow_but_quality_rag(self, config: Dict, user_prompt: str, agent_outputs: Optional[Dict] = None) -> Any:
        """
        Performs a Retrieval-Augmented Generation (RAG) process using a slow but high-quality approach.

        :param config: The configuration dictionary containing RAG parameters.
        :param user_prompt: The original prompt provided by the user.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :return: The result of the RAG process or an Exception if configuration is missing.
        """
        if "ragTarget" in config:
            rag_target = config["ragTarget"]
        else:
            return Exception("No rag target specified in Slow But Quality RAG node")

        if "ragType" in config:
            rag_type = config["ragType"]
        else:
            return Exception("No rag type specified in Slow But Quality RAG node")

        prompt = self.workflow_variable_service.apply_variables(prompt=config["prompt"], llm_handler=self.llm_handler,
                                                                unaltered_prompt=user_prompt,
                                                                agent_outputs=agent_outputs,
                                                                do_not_apply_prompt_template=True)
        rag_target = self.workflow_variable_service.apply_variables(rag_target, llm_handler=self.llm_handler,
                                                                    unaltered_prompt=user_prompt,
                                                                    agent_outputs=agent_outputs,
                                                                    do_not_apply_prompt_template=True)

        if rag_type == "CurrentConversation":
            return self.slow_but_quality_rag_service.perform_rag_on_conversation_chunk(prompt, rag_target, config)

    def perform_keyword_search(self, config: Dict, user_prompt: str, agent_outputs: Optional[Dict] = None,
                               lookbackStartTurn: int = 0) -> Any:
        """
        Performs a keyword search within the conversation or recent memories based on the provided configuration.

        :param config: The configuration dictionary containing search parameters.
        :param user_prompt: The original prompt provided by the user.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :param lookbackStartTurn: The starting turn index to look back from (default: 0).
        :return: The result of the keyword search or an Exception if keywords are missing.
        """
        if "keywords" in config:
            keywords = config["keywords"]
        else:
            return Exception("No keywords specified in Keyword Search node")

        # The keywords are coming from a previous agent, so we need those
        keywords = self.workflow_variable_service.apply_variables(keywords, self.llm_handler, user_prompt,
                                                                  agent_outputs, True)

        if "searchTarget" not in config or config["searchTarget"] == "CurrentConversation":
            print("Performing search on Current Conversation")
            return self.slow_but_quality_rag_service.perform_keyword_search(keywords, "CurrentConversation",
                                                                            user_prompt=user_prompt,
                                                                            lookbackStartTurn=lookbackStartTurn)

        if "searchTarget" not in config or config["searchTarget"] == "RecentMemories":
            print("Performing search on Current Conversation")
            return self.slow_but_quality_rag_service.perform_keyword_search(keywords,
                                                                            "RecentMemories",
                                                                            user_prompt=user_prompt,
                                                                            lookbackStartTurn=lookbackStartTurn)

    def save_summary_to_file(self, config: Dict, user_prompt: str,
                             agent_outputs: Optional[Dict] = None) -> Exception | Any:
        """
        Saves a chat summary to a file after processing the user prompt and applying variables.

        :param config: The configuration dictionary containing summary parameters.
        :param user_prompt: The original prompt provided by the user.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :return: The processed summary string.
        """
        if "input" in config:
            summary = config["input"]
        else:
            return Exception("No summary found ")

        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
        discussion_id = extract_discussion_id(system_prompt)

        # The keywords are coming from a previous agent, so we need those
        summary = self.workflow_variable_service.apply_variables(summary, self.llm_handler, user_prompt,
                                                                 agent_outputs, True)

        if discussion_id is None:
            return summary

        memory_filepath = get_discussion_memory_file_path(discussion_id)

        hashed_chunks = read_chunks_with_hashes(
            memory_filepath)

        last_chunk = hashed_chunks[-1]
        old_text, old_hash = last_chunk
        last_chunk = summary, old_hash

        chunks = [last_chunk]

        print("Old_text: {}".format(old_text))
        print("Old_hash: {}".format(old_hash))
        print("Summary:\n{}".format(summary))

        filepath = get_discussion_chat_summary_file_path(discussion_id)
        update_chunks_with_hashes(chunks, filepath, "overwrite")

        return summary

    def gather_recent_memories(self, user_prompt: str, max_turns_to_pull=0, max_summary_chunks_from_file=0):

        return self.slow_but_quality_rag_service.get_recent_memories(user_prompt=user_prompt,
                                                                     max_turns_to_search=max_turns_to_pull,
                                                                     max_summary_chunks_from_file=max_summary_chunks_from_file)

    def gather_chat_summary_memories(self, user_prompt: str, max_turns_to_pull: int = 0,
                                     max_summary_chunks_from_file: int = 0) -> List[Tuple[str, str]]:
        """
        Gathers chat summary memories from the conversation based on the user prompt and specified limits.

        :param user_prompt: The original prompt provided by the user.
        :param max_turns_to_pull: The maximum number of turns to pull from the conversation (default: 0).
        :param max_summary_chunks_from_file: The maximum number of summary chunks to pull from the file (default: 0).
        :return: A list of tuples containing the chat summary memories.
        """

        return self.slow_but_quality_rag_service.get_chat_summary_memories(user_prompt=user_prompt,
                                                                           max_turns_to_search=max_turns_to_pull,
                                                                           max_summary_chunks_from_file=max_summary_chunks_from_file)

    def handle_memory_file(self, discussion_id: str, pairs: List[Tuple[Optional[str], Optional[str]]]) -> Any:
        """
        Handles the memory file associated with a discussion ID, processing the user/assistant pairs.

        :param discussion_id: The unique identifier for the discussion.
        :param pairs: A list of tuples representing user/assistant turns in the conversation.
        :return: The result of handling the memory file or an Exception if an error occurs.
        """
        return self.slow_but_quality_rag_service.handle_discussion_id_flow(discussion_id, pairs)

    def handle_conversation_type_node(self, config: Dict, user_prompt: Optional[str] = None,
                                      agent_outputs: Optional[Dict] = None) -> str:
        """
        Handles a conversation type node by applying variables to the prompt and obtaining a response from the LLM.

        :param config: The configuration dictionary containing the prompt and other parameters.
        :param user_prompt: The original prompt provided by the user (default: None).
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :return: The response from the LLM.
        """
        # now we need to apply the variables to that prompt
        prompt = self.workflow_variable_service.apply_variables(prompt=config["prompt"], llm_handler=self.llm_handler,
                                                                unaltered_prompt=user_prompt,
                                                                agent_outputs=agent_outputs)

        agent_output = self.llm_handler.llm.get_response_from_llm(prompt)

        return agent_output
