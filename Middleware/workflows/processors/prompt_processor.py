import logging
import traceback
from copy import deepcopy
from typing import Dict, Any, Optional, List

from Middleware.utilities.automation_utils import run_dynamic_module
from Middleware.utilities.config_utils import get_discussion_chat_summary_file_path, get_discussion_memory_file_path
from Middleware.utilities.file_utils import update_chunks_with_hashes, read_chunks_with_hashes
from Middleware.utilities.memory_utils import handle_get_current_summary_from_file, \
    get_latest_memory_chunks_with_hashes_since_last_summary
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template, \
    add_assistant_end_token_to_user_turn, format_system_prompt_with_template, get_formatted_last_n_turns_as_string, \
    format_assistant_turn_with_template
from Middleware.workflows.tools.offline_wikipedia_api_tool import OfflineWikiApiClient
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool

logger = logging.getLogger(__name__)


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
            agent_outputs=agent_outputs,
            config=config
        )
        system_prompt = self.workflow_variable_service.apply_variables(
            prompt=config["systemPrompt"],
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs,
            config=config
        )
        rag_target = self.workflow_variable_service.apply_variables(
            rag_target,
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs,
            config=config
        )

        return self.slow_but_quality_rag_service.perform_rag_on_conversation_chunk(system_prompt, prompt, rag_target,
                                                                                   config)

    def perform_keyword_search(self, config: Dict, messages: List[Dict[str, str]], discussion_id: str,
                               agent_outputs: Optional[Dict] = None,
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
        keywords = self.workflow_variable_service.apply_variables(
            keywords,
            self.llm_handler,
            messages,
            agent_outputs,
            config=config
        )

        if "searchTarget" not in config or config["searchTarget"] == "CurrentConversation":
            logger.debug("Performing search on Current Conversation")
            return self.slow_but_quality_rag_service.perform_keyword_search(
                keywords, "CurrentConversation", messages=messages, lookbackStartTurn=lookbackStartTurn,
                llm_handler=self.llm_handler, discussion_id=discussion_id
            )

        if config["searchTarget"] == "RecentMemories":
            logger.debug("Performing search on Recent Memories")
            return self.slow_but_quality_rag_service.perform_keyword_search(
                keywords, "RecentMemories", messages=messages, lookbackStartTurn=lookbackStartTurn,
                llm_handler=self.llm_handler, discussion_id=discussion_id
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

        if not self.llm_handler.takes_message_collection:
            # Current logic for building system_prompt and prompt
            system_prompt = self.workflow_variable_service.apply_variables(
                prompt=config.get("systemPrompt", ""),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs,
                config=config
            )

            prompt = config.get("prompt", "")
            if prompt:
                prompt = self.workflow_variable_service.apply_variables(
                    prompt=config.get("prompt", ""),
                    llm_handler=self.llm_handler,
                    messages=message_copy,
                    agent_outputs=agent_outputs,
                    config=config
                )

                logger.debug("Config: ")
                logger.debug(config)
                if "addUserTurnTemplate" in config:
                    add_user_turn_template = config["addUserTurnTemplate"]
                    logger.debug(f"Adding user turn template {add_user_turn_template}")
                else:
                    add_user_turn_template = False

                if "addOpenEndedAssistantTurnTemplate" in config:
                    add_open_ended_assistant_turn_template = config.get("addOpenEndedAssistantTurnTemplate", False)
                    logger.debug("Adding open-ended assistant turn template")
                else:
                    add_open_ended_assistant_turn_template = False

                if add_user_turn_template:
                    logger.debug("Adding user turn")
                    prompt = format_user_turn_with_template(
                        prompt,
                        self.llm_handler.prompt_template_file_name,
                        isChatCompletion=self.llm_handler.takes_message_collection
                    )
                if add_open_ended_assistant_turn_template:
                    logger.debug("Adding open ended assistant turn")
                    prompt = format_assistant_turn_with_template(
                        prompt,
                        self.llm_handler.prompt_template_file_name,
                        isChatCompletion=self.llm_handler.takes_message_collection
                    )
            else:
                # Extracting with template because this is v1/completions
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                prompt = get_formatted_last_n_turns_as_string(
                    message_copy, last_messages_to_send + 1,
                    template_file_name=self.llm_handler.prompt_template_file_name,
                    isChatCompletion=self.llm_handler.takes_message_collection
                )

            if self.llm_handler.add_generation_prompt:
                logger.debug("Entering add generation prompt")
                prompt = add_assistant_end_token_to_user_turn(
                    prompt,
                    self.llm_handler.prompt_template_file_name,
                    isChatCompletion=self.llm_handler.takes_message_collection
                )
            else:
                logger.debug("Did not enter add generation prompt")

            system_prompt = format_system_prompt_with_template(
                system_prompt,
                self.llm_handler.prompt_template_file_name,
                isChatCompletion=self.llm_handler.takes_message_collection
            )

            return self.llm_handler.llm.get_response_from_llm(system_prompt=system_prompt, prompt=prompt,
                                                              llm_takes_images=self.llm_handler.takes_image_collection)
        else:
            # New workflow for takes_message_collection = True
            collection = []

            system_prompt = self.workflow_variable_service.apply_variables(
                prompt=config.get("systemPrompt", ""),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs,
                config=config
            )
            if system_prompt:
                collection.append({"role": "system", "content": system_prompt})

            prompt = config.get("prompt", "")
            prompt = self.workflow_variable_service.apply_variables(
                prompt=config.get("prompt", ""),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs,
                config=config
            )
            if prompt:
                collection.append({"role": "user", "content": prompt})
            else:
                # Extracting without template because this is for chat/completions
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                last_n_turns = extract_last_n_turns(message_copy, last_messages_to_send,
                                                    self.llm_handler.takes_message_collection)
                collection.extend(last_n_turns)

            return self.llm_handler.llm.get_response_from_llm(collection,
                                                              llm_takes_images=self.llm_handler.takes_image_collection)

    def handle_process_chat_summary(self, config: Dict, messages: List[Dict[str, str]],
                                    agent_outputs: Dict[str, str], discussion_id: str) -> Any:
        """
        Handles a chat summarizer node by checking for agent outputs containing a delimiter and processing them
        based on the prompts in the config. If more than one agent output is found, or if no relevant output is found,
        it calls handle_conversation_type_node.

        :param config: Configuration dictionary containing the prompt, system prompt, and other parameters.
        :param messages: List of message dictionaries representing the conversation.
        :param agent_outputs: Dictionary of strings representing the outputs of agents.
        :param discussion_id: The discussion id for the current conversation
        :return: The result of handle_conversation_type_node or modified agent outputs based on the delimiter.
        """
        # Fetch only the memory chunks that are new since the last summary
        memory_chunks_with_hashes = get_latest_memory_chunks_with_hashes_since_last_summary(discussion_id)
        current_chat_summary = handle_get_current_summary_from_file(discussion_id)

        # Debug: show initial values
        logger.debug(f"[DEBUG] Initial memory chunks with hashes: {memory_chunks_with_hashes}")
        logger.debug(f"[DEBUG] Current chat summary: {current_chat_summary}")

        # If there are no new memories, return the current chat summary.
        if not memory_chunks_with_hashes:
            logger.debug("[DEBUG] No new memories found. Returning current chat summary.")
            return current_chat_summary

        system_prompt = config.get('systemPrompt', '')
        prompt = config.get('prompt', '')

        minMemoriesPerSummary = config.get('minMemoriesPerSummary', 3)

        # Debug: show system_prompt and prompt
        logger.debug(f"[DEBUG] Initial system prompt: {system_prompt}")
        logger.debug(f"[DEBUG] Initial prompt: {prompt}")

        # If neither [CHAT_SUMMARY] nor [LATEST_MEMORIES] are found in the prompt or system prompt, just run handle_conversation_type_node.
        if '[CHAT_SUMMARY]' not in system_prompt and '[CHAT_SUMMARY]' not in prompt and \
                '[LATEST_MEMORIES]' not in system_prompt and '[LATEST_MEMORIES]' not in prompt:
            logger.debug("[DEBUG] No [CHAT_SUMMARY] or [LATEST_MEMORIES] found in the prompts.")
            summary = self.handle_conversation_type_node(config, messages, agent_outputs)

            # Save the updated summary to file after processing the current chunk.
            logger.debug("[DEBUG] Saving summary to file after processing batch.")
            self.save_summary_to_file(config, messages, discussion_id, agent_outputs, summary)

            return summary

        # Split memory chunks into manageable batches.
        max_memories_per_loop = config.get('loopIfMemoriesExceed', 3)

        # If there are memories, but fewer than or equal to max_memories_per_loop, replace and return the result.
        if len(memory_chunks_with_hashes) <= max_memories_per_loop:
            if (len(memory_chunks_with_hashes) < minMemoriesPerSummary):
                return current_chat_summary

            latest_memories = '\n------------\n'.join(
                [chunk for chunk, _ in memory_chunks_with_hashes])  # Join memory text blocks
            updated_system_prompt = system_prompt.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories)
            updated_prompt = prompt.replace("[CHAT_SUMMARY]", current_chat_summary).replace("[LATEST_MEMORIES]",
                                                                                            latest_memories)

            # Debug: show updated prompts
            logger.debug(f"[DEBUG] Updated system prompt (fewer than max): {updated_system_prompt}")
            logger.debug(f"[DEBUG] Updated prompt (fewer than max): {updated_prompt}")

            summary = self.handle_conversation_type_node(
                {**config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt},
                messages,
                agent_outputs
            )

            # Save the updated summary to file and pass the last hash.
            last_hash = memory_chunks_with_hashes[-1][1]  # Get the hash of the last memory chunk (hash is at index 1)
            logger.info(f"Saving summary to file. Last memory chunk hash: {last_hash}")
            self.save_summary_to_file(config, messages, discussion_id, agent_outputs, summary, last_hash)

            return summary

        # If there are more memories than the max per loop, process them in batches.
        while len(memory_chunks_with_hashes) > max_memories_per_loop:
            # Take the first N memories (up to max_memories_per_loop).
            batch_chunks = memory_chunks_with_hashes[:max_memories_per_loop]
            latest_memories_chunk = '\n------------\n'.join(
                [chunk for chunk, _ in batch_chunks])  # Join memory text blocks
            last_hash = batch_chunks[-1][1]  # Get the hash of the last memory chunk in the batch (hash is at index 1)

            # Debug: show the memory chunk and last hash being processed
            logger.debug(f"[DEBUG] Processing memory chunk: {latest_memories_chunk}")
            logger.debug(f"[DEBUG] Last memory chunk hash: {last_hash}")

            # Reset the system_prompt and prompt each iteration.
            system_prompt = config.get('systemPrompt', '')
            prompt = config.get('prompt', '')

            # Replace [CHAT_SUMMARY] and [LATEST_MEMORIES] with the appropriate values.
            updated_system_prompt = system_prompt.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)
            updated_prompt = prompt.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)

            # Debug: show updated prompts during batch processing
            logger.debug(f"[DEBUG] Updated system prompt (batch): {updated_system_prompt}")
            logger.debug(f"[DEBUG] Updated prompt (batch): {updated_prompt}")

            # Call the conversation type handler with the updated prompts.
            summary = self.handle_conversation_type_node(
                {**config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt},
                messages,
                agent_outputs
            )

            # Save the updated summary to file after processing the current chunk and pass the last hash.
            logger.info(f"Saving summary to file. Last memory chunk hash: {last_hash}")
            self.save_summary_to_file(config, messages, discussion_id, agent_outputs, summary, last_hash)

            # Remove processed chunks from memory_chunks_with_hashes
            memory_chunks_with_hashes = memory_chunks_with_hashes[max_memories_per_loop:]

            # Re-fetch updated current summary from the file.
            current_chat_summary = handle_get_current_summary_from_file(discussion_id)

            # Debug: show updated values after each loop iteration
            logger.debug(f"[DEBUG] Refetched current_chat_summary: {current_chat_summary}")

        # Process any remaining memories after the loop (fewer than max_memories_per_loop).
        if 0 < len(memory_chunks_with_hashes) <= max_memories_per_loop and len(
                memory_chunks_with_hashes) >= minMemoriesPerSummary:
            latest_memories_chunk = '\n------------\n'.join([chunk for chunk, _ in memory_chunks_with_hashes])
            last_hash = memory_chunks_with_hashes[-1][
                1]  # Get the hash of the last remaining chunk (hash is at index 1)
            updated_system_prompt = system_prompt.replace("[CHAT_SUMMARY]", current_chat_summary).replace(
                "[LATEST_MEMORIES]", latest_memories_chunk)
            updated_prompt = prompt.replace("[CHAT_SUMMARY]", current_chat_summary).replace("[LATEST_MEMORIES]",
                                                                                            latest_memories_chunk)

            # Debug: show updated prompts for remaining memories
            logger.debug(f"[DEBUG] Updated system prompt (remaining): {updated_system_prompt}")
            logger.debug(f"[DEBUG] Updated prompt (remaining): {updated_prompt}")

            summary = self.handle_conversation_type_node(
                {**config, 'systemPrompt': updated_system_prompt, 'prompt': updated_prompt},
                messages,
                agent_outputs
            )

            # Save the updated summary to file after processing the current chunk and pass the last hash.
            logger.info(f"Saving summary to file. Last memory chunk hash: {last_hash}")
            self.save_summary_to_file(config, messages, discussion_id, agent_outputs, summary, last_hash)

            # At the end, return the final summary.
            logger.debug("[DEBUG] Returning final summary.")
            return summary

        else:
            logger.info("No remaining memories, returning the current summary.")
            return current_chat_summary

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

        modified_args = list(args)  # Convert tuple to list to allow modifications
        for i, arg in enumerate(modified_args):
            try:
                modified_args[i] = self.workflow_variable_service.apply_variables(
                    prompt=str(arg),
                    llm_handler=self.llm_handler,
                    messages=message_copy,
                    agent_outputs=agent_outputs,
                    config=config
                )
            except Exception as e:
                logger.error(f"Arg could not have variable applied. Exception: {e}")
                traceback.print_exc()  # This prints the stack trace
                raise
        new_args = tuple(modified_args)

        for key, value in kwargs.items():
            # Apply variables to the value
            value = self.workflow_variable_service.apply_variables(
                prompt=str(value),
                llm_handler=self.llm_handler,
                messages=message_copy,
                agent_outputs=agent_outputs,
                config=config
            )
            kwargs[key] = value
        # Call the function and return the result
        return run_dynamic_module(module_path, *new_args, **kwargs)

    def handle_offline_wiki_node(self, messages: List[Dict[str, str]], prompt,
                                 agent_outputs: [Dict], get_full_article: bool = True,
                                 use_new_best_article_endpoint: bool = False, use_top_n_articles_endpoint: bool = False,
                                 percentile: float = 0.5,
                                 num_results: int = 10,
                                 top_n_articles: int = 3) -> Any:

        message_copy = deepcopy(messages)

        variabled_prompt = self.workflow_variable_service.apply_variables(
            prompt=str(prompt),
            llm_handler=self.llm_handler,
            messages=message_copy,
            agent_outputs=agent_outputs
        )

        offline_wiki_api_client = OfflineWikiApiClient()
        if get_full_article and use_new_best_article_endpoint:
            result = offline_wiki_api_client.get_top_full_wiki_article_by_prompt(variabled_prompt)
            return result
        if get_full_article and use_top_n_articles_endpoint:
            result = offline_wiki_api_client.get_top_n_full_wiki_articles_by_prompt(variabled_prompt,
                        percentile=percentile, num_results=num_results, top_n_articles=top_n_articles)
            return result
        elif get_full_article:
            results = offline_wiki_api_client.get_full_wiki_article_by_prompt(variabled_prompt)
        else:
            results = offline_wiki_api_client.get_wiki_summary_by_prompt(variabled_prompt)

        result = "No additional information provided"
        if results is not None:
            if len(results) > 0:
                result = results[0]

        return result

    def save_summary_to_file(self, config: Dict, messages: List[Dict[str, str]], discussion_id: str,
                             agent_outputs: Optional[Dict] = None, summaryOverride: str = None,
                             lastHashOverride: str = None) -> Exception | Any:
        """
        Saves a chat summary to a file after processing the user prompt and applying variables.

        :param config: The configuration dictionary containing summary parameters.
        :param messages: The list of messages in the conversation.
        :param agent_outputs: Optional dictionary containing previous agent outputs (default: None).
        :return: The processed summary string.
        """
        if (summaryOverride is None):
            if "input" in config:
                summary = config["input"]
            else:
                return Exception("No summary found")

            # The summary is coming from a previous agent, so we need those
            summary = self.workflow_variable_service.apply_variables(
                summary,
                self.llm_handler,
                messages,
                agent_outputs,
                config=config
            )
        else:
            summary = summaryOverride

        if discussion_id is None:
            return summary

        memory_filepath = get_discussion_memory_file_path(discussion_id)
        hashed_chunks = read_chunks_with_hashes(memory_filepath)

        if lastHashOverride is None:
            last_chunk = hashed_chunks[-1]
            old_text, old_hash = last_chunk
            last_chunk = summary, old_hash
            logger.debug(f"Old_text: {old_text}")
            logger.debug(f"Old_hash: {old_hash}")
        else:
            last_chunk = summary, lastHashOverride
            logger.debug(f"lastHashOverride: {lastHashOverride}")

        chunks = [last_chunk]

        logger.debug(f"Summary:\n{summary}")

        filepath = get_discussion_chat_summary_file_path(discussion_id)
        update_chunks_with_hashes(chunks, filepath, "overwrite")

        return summary

    def handle_image_processor_node(
            self,
            config: Dict,
            messages: List[Dict[str, str]],
            agent_outputs: Optional[Dict] = None
    ) -> str:
        """
        Handles an `image_processor` node by extracting all base64-encoded images (role="images")
        and sending each one (plus systemPrompt, prompt) to the LLM for processing.

        :param config: The workflow node config (should include 'systemPrompt', 'prompt', etc.).
        :param messages: A list of message dicts; images will have role="images".
        :param agent_outputs: A dictionary of any prior outputs from the workflow.
        :return: The concatenated result of the LLM outputs for each image.
        """

        image_messages = [msg for msg in messages if msg.get("role") == "images"]
        if not image_messages:
            return "No images found in the conversation."

        system_prompt = self.workflow_variable_service.apply_variables(
            prompt=config.get("systemPrompt", ""),
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs,
            config=config
        )
        prompt = self.workflow_variable_service.apply_variables(
            prompt=config.get("prompt", ""),
            llm_handler=self.llm_handler,
            messages=messages,
            agent_outputs=agent_outputs,
            config=config
        )

        llm_responses = []
        for img_msg in image_messages:
            collection = []
            if system_prompt:
                collection.append({"role": "system", "content": system_prompt})
            if prompt:
                collection.append({"role": "user", "content": prompt})

            collection.append({"role": "images", "content": img_msg["content"]})

            logger.debug(
                f"Sending image to LLM. Prompt length: {len(prompt)}. Image size: {len(img_msg['content'])} chars.")
            response = self.llm_handler.llm.get_response_from_llm(collection,
                                                                  llm_takes_images=self.llm_handler.takes_image_collection)
            llm_responses.append(response)

        final_response = "\n-------------\n".join(llm_responses)

        return final_response
