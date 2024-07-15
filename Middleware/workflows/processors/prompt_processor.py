from copy import deepcopy
from typing import Dict, Any, Optional, List

from Middleware.utilities.automation_utils import run_dynamic_module
from Middleware.utilities.config_utils import get_discussion_memory_file_path, get_discussion_chat_summary_file_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, update_chunks_with_hashes
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id, extract_last_n_turns, \
    remove_discussion_id_tag
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template, \
    add_assistant_end_token_to_user_turn, format_system_prompt_with_template, get_formatted_last_n_turns_as_string
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

    def perform_slow_but_quality_rag(self, config: Dict, messages: List[Dict[str, str]],
                                     agent_outputs: Optional[Dict] = None) -> Any:
        """
        Performs a Retrieval-Augmented Generation (RAG) process using a slow but high-quality approach.

        :param config: The configuration dictionary containing RAG parameters.
        :param messages: The list of messages in the conversation.
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

        prompt = self.workflow_variable_service.apply_variables(
            prompt=config["prompt"],
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs
        )
        system_prompt = self.workflow_variable_service.apply_variables(
            prompt=config["systemPrompt"],
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs
        )
        rag_target = self.workflow_variable_service.apply_variables(
            rag_target,
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs
        )

        return self.slow_but_quality_rag_service.perform_rag_on_conversation_chunk(system_prompt, prompt, rag_target,
                                                                                   config)

    def perform_keyword_search(self, config: Dict, messages: List[Dict[str, str]], agent_outputs: Optional[Dict] = None,
                               lookbackStartTurn: int = 0) -> Any:
        """
        Performs a keyword search within the conversation or recent memories based on the provided configuration.

        :param config: The configuration dictionary containing search parameters.
        :param messages: The list of messages in the conversation.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :param lookbackStartTurn: The starting turn index to look back from (default: 0).
        :return: The result of the keyword search or an Exception if keywords are missing.
        """
        if "keywords" in config:
            keywords = config["keywords"]
        else:
            return Exception("No keywords specified in Keyword Search node")

        # The keywords are coming from a previous agent, so we need those
        keywords = self.workflow_variable_service.apply_variables(keywords, self.llm_handler, messages, agent_outputs)

        if "searchTarget" not in config or config["searchTarget"] == "CurrentConversation":
            print("Performing search on Current Conversation")
            return self.slow_but_quality_rag_service.perform_keyword_search(
                keywords, "CurrentConversation", messages=messages, lookbackStartTurn=lookbackStartTurn,
                llm_handler=self.llm_handler
            )

        if config["searchTarget"] == "RecentMemories":
            print("Performing search on Recent Memories")
            return self.slow_but_quality_rag_service.perform_keyword_search(
                keywords, "RecentMemories", messages=messages, lookbackStartTurn=lookbackStartTurn,
                llm_handler=self.llm_handler
            )

    def save_summary_to_file(self, config: Dict, messages: List[Dict[str, str]],
                             agent_outputs: Optional[Dict] = None) -> Exception | Any:
        """
        Saves a chat summary to a file after processing the user prompt and applying variables.

        :param config: The configuration dictionary containing summary parameters.
        :param messages: The list of messages in the conversation.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :return: The processed summary string.
        """
        if "input" in config:
            summary = config["input"]
        else:
            return Exception("No summary found")

        discussion_id = extract_discussion_id(messages)

        # The summary is coming from a previous agent, so we need those
        summary = self.workflow_variable_service.apply_variables(summary, self.llm_handler, messages, agent_outputs)

        if discussion_id is None:
            return summary

        memory_filepath = get_discussion_memory_file_path(discussion_id)
        hashed_chunks = read_chunks_with_hashes(memory_filepath)

        last_chunk = hashed_chunks[-1]
        old_text, old_hash = last_chunk
        last_chunk = summary, old_hash

        chunks = [last_chunk]

        print(f"Old_text: {old_text}")
        print(f"Old_hash: {old_hash}")
        print(f"Summary:\n{summary}")

        filepath = get_discussion_chat_summary_file_path(discussion_id)
        update_chunks_with_hashes(chunks, filepath, "overwrite")

        return summary

    def gather_recent_memories(self, messages: List[Dict[str, str]], max_turns_to_pull=0,
                               max_summary_chunks_from_file=0) -> Any:
        """
        Gathers recent memories from the conversation based on the specified limits.

        :param messages: The list of messages in the conversation.
        :param max_turns_to_pull: The maximum number of turns to pull from the conversation (default: 0).
        :param max_summary_chunks_from_file: The maximum number of summary chunks to pull from the file (default: 0).
        :return: A list of recent memories.
        """
        return self.slow_but_quality_rag_service.get_recent_memories(
            messages=messages,
            max_turns_to_search=max_turns_to_pull,
            max_summary_chunks_from_file=max_summary_chunks_from_file
        )

    def gather_chat_summary_memories(self, messages: List[Dict[str, str]], max_turns_to_pull: int = 0,
                                     max_summary_chunks_from_file: int = 0):
        """
        Gathers chat summary memories from the conversation based on the specified limits.

        :param messages: The list of messages in the conversation.
        :param max_turns_to_pull: The maximum number of turns to pull from the conversation (default: 0).
        :param max_summary_chunks_from_file: The maximum number of summary chunks to pull from the file (default: 0).
        :return: A list of tuples containing the chat summary memories.
        """
        return self.slow_but_quality_rag_service.get_chat_summary_memories(
            messages=messages,
            max_turns_to_search=max_turns_to_pull,
            max_summary_chunks_from_file=max_summary_chunks_from_file
        )

    def handle_memory_file(self, discussion_id: str, messages: List[Dict[str, str]]) -> Any:
        """
        Handles the memory file associated with a discussion ID, processing the user/assistant pairs.

        :param discussion_id: The unique identifier for the discussion.
        :param messages: A list of dictionaries representing the conversation messages.
        :return: The result of handling the memory file or an Exception if an error occurs.
        """
        return self.slow_but_quality_rag_service.handle_discussion_id_flow(discussion_id, messages)

    def handle_conversation_type_node(self, config: Dict, messages: List[Dict[str, str]],
                                      agent_outputs: Optional[Dict] = None) -> Any:
        """
        Handles a conversation type node by applying variables to the prompt and obtaining a response from the LLM.

        :param config: The configuration dictionary containing the prompt and other parameters.
        :param messages: The list of messages in the conversation.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :return: The response from the LLM.
        """
        message_copy = deepcopy(messages)
        remove_discussion_id_tag(message_copy)

        if not self.llm_handler.takes_message_collection:
            # Current logic for building system_prompt and prompt
            system_prompt = self.workflow_variable_service.apply_variables(
                prompt=config.get("systemPrompt", ""),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs
            )

            prompt = config.get("prompt", "")
            if prompt:
                prompt = self.workflow_variable_service.apply_variables(
                    prompt=config.get("prompt", ""),
                    llm_handler=self.llm_handler,
                    messages=message_copy,
                    agent_outputs=agent_outputs
                )

                if "addUserTurnTemplate" in config:
                    add_user_turn_template = config["addUserTurnTemplate"]
                    print(f"Adding user turn template {add_user_turn_template}")
                else:
                    add_user_turn_template = True
                if add_user_turn_template:
                    print("Adding user turn")
                    prompt = format_user_turn_with_template(prompt, self.llm_handler.prompt_template_file_name
                                                            ,
                                                            isChatCompletion=self.llm_handler.takes_message_collection)
            else:
                # Extracting with template because this is v1/completions
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                prompt = get_formatted_last_n_turns_as_string(
                    message_copy, last_messages_to_send + 1,
                    template_file_name=self.llm_handler.prompt_template_file_name,
                    isChatCompletion=self.llm_handler.takes_message_collection
                )

            if self.llm_handler.add_generation_prompt:
                prompt = add_assistant_end_token_to_user_turn(prompt, self.llm_handler.prompt_template_file_name,
                                                              isChatCompletion=self.llm_handler.takes_message_collection)

            system_prompt = format_system_prompt_with_template(system_prompt,
                                                               self.llm_handler.prompt_template_file_name
                                                               ,
                                                               isChatCompletion=self.llm_handler.takes_message_collection)

            return self.llm_handler.llm.get_response_from_llm(system_prompt=system_prompt, prompt=prompt)
        else:
            # New workflow for takes_message_collection = True
            collection = []

            system_prompt = self.workflow_variable_service.apply_variables(
                prompt=config.get("systemPrompt", ""),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs
            )
            if system_prompt:
                collection.append({"role": "system", "content": system_prompt})

            prompt = config.get("prompt", "")
            prompt = self.workflow_variable_service.apply_variables(
                prompt=config.get("prompt", ""),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs
            )
            if prompt:
                collection.append({"role": "user", "content": prompt})
            else:
                # Extracting without template because this is for chat/completions
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                last_n_turns = extract_last_n_turns(message_copy, last_messages_to_send,
                                                    self.llm_handler.takes_message_collection)
                collection.extend(last_n_turns)

            return self.llm_handler.llm.get_response_from_llm(collection)

    def handle_python_module(self, config: Dict, messages: List[Dict[str, str]], module_path: str,
                             agent_outputs: Optional[Dict] = None, *args, **kwargs) -> Any:
        """
        Handles the execution of a dynamic Python module.

        :param config: The configuration dictionary containing parameters.
        :param messages: The list of messages in the conversation.
        :param module_path: The path to the Python module to be executed.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :param args: Additional positional arguments to pass to the module.
        :param kwargs: Additional keyword arguments to pass to the module.
        :return: The result of the dynamic module execution.
        """
        message_copy = deepcopy(messages)
        remove_discussion_id_tag(message_copy)

        modified_args = list(args)  # Convert tuple to list to allow modifications
        for i, arg in enumerate(modified_args):
            try:
                modified_args[i] = self.workflow_variable_service.apply_variables(
                    prompt=str(arg),
                    llm_handler=self.llm_handler,
                    messages=message_copy,
                    agent_outputs=agent_outputs
                )
            except Exception as e:
                print(f"Arg could not have variable applied. Exception: {e}")
        new_args = tuple(modified_args)

        for key, value in kwargs.items():
            # Apply variables to the value
            value = self.workflow_variable_service.apply_variables(
                prompt=str(value),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs
            )
            kwargs[key] = value
        # Call the function and return the result
        return run_dynamic_module(module_path, *new_args, **kwargs)
