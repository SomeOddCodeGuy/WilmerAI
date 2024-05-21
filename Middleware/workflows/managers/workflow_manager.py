import json
import time
from typing import Dict

from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities.config_utils import get_active_conversational_memory_tool_name, \
    get_active_recent_memory_tool_name, get_file_memory_tool_name, \
    get_chat_template_name, get_discussion_chat_summary_file_path, get_discussion_memory_file_path, get_workflow_path, \
    get_chat_summary_tool_workflow_name
from Middleware.utilities.file_utils import read_chunks_with_hashes
from Middleware.utilities.logging_utils import log
from Middleware.utilities.prompt_extraction_utils import extract_pairs_and_system_prompt_from_wilmer_templated_string, \
    extract_discussion_id
from Middleware.utilities.prompt_utils import find_last_matching_memory_hash, extract_text_blocks_from_hashed_chunks
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.processors.prompt_processor import PromptProcessor


class WorkflowManager:

    @staticmethod
    def handle_conversation_memory_parser(user_prompt: str = None):
        """
        Initializes and runs a workflow for parsing conversation memory.

        :param user_prompt: The user's prompt to be processed by the workflow.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_conversational_memory_tool_name())
        return workflow_gen.run_workflow(user_prompt)

    @staticmethod
    def handle_recent_memory_parser(user_prompt: str = None):
        """
        Initializes and runs a workflow for parsing recent chat memory.

        :param user_prompt: The user's prompt to be processed by the workflow.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_recent_memory_tool_name())
        return workflow_gen.run_workflow(user_prompt)

    @staticmethod
    def handle_full_chat_summary_parser(user_prompt: str = None):
        """
        Initializes and runs a workflow for parsing a full chat summary.

        :param user_prompt: The user's prompt to be processed by the workflow.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_chat_summary_tool_workflow_name())
        return workflow_gen.run_workflow(user_prompt)

    @staticmethod
    def process_file_memories(user_prompt: str = None):
        """
        Initializes and runs a workflow for processing memories from files.

        :param user_prompt: The user's prompt to be processed by the workflow.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_file_memory_tool_name())
        return workflow_gen.run_workflow(user_prompt)

    def __init__(self, workflow_config_name, **kwargs):
        """
        Initializes the WorkflowManager with the given workflow configuration name and optional parameters.

        :param workflow_config_name: The name of the workflow configuration file.
        :param kwargs: Optional keyword arguments, including 'llm_handler' and 'lookbackStartTurn'.
        """
        self.llm_handler = None
        self.workflow_variable_service = WorkflowVariableManager(**kwargs)
        self.workflowConfigName = workflow_config_name
        self.llm_handler_service = LlmHandlerService()

        if 'llm_handler' in kwargs:
            self.llm_handler = kwargs['llm_handler']
        if 'lookbackStartTurn' in kwargs:
            self.lookbackStartTurn = kwargs['lookbackStartTurn']

    def run_workflow(self, user_prompt, stream=False):
        """
         Executes the workflow based on the configuration file.

         :param user_prompt: The user's prompt to be processed by the workflow.
         :param stream: A flag indicating whether the workflow should be executed in streaming mode.
         :return: The result of the workflow execution.
        """
        start_time = time.perf_counter()
        config_file = get_workflow_path(self.workflowConfigName)

        with open(config_file) as f:
            configs = json.load(f)
        agent_outputs = {}
        for idx, config in enumerate(configs):
            if idx == len(configs) - 1 and stream:
                # This is the last item, handle it differently
                end_time = time.perf_counter()
                execution_time = end_time - start_time
                print(f"Execution time: {execution_time} seconds")
                return self._process_section(config, user_prompt, agent_outputs, stream=stream)
            else:
                agent_outputs[f'agent{idx + 1}Output'] = self._process_section(config, user_prompt, agent_outputs)

        end_time = time.perf_counter()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time} seconds")

        # Return the last agent output
        return agent_outputs[list(agent_outputs.keys())[-1]]

    def _process_section(self, config: Dict, user_prompt: str = None, agent_outputs: Dict = None, stream: bool = False):
        """
        Processes a single section of the workflow configuration.

        :param config: The configuration dictionary for the current workflow section.
        :param user_prompt: The user's prompt to be processed by the workflow.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :param stream: A flag indicating whether the workflow should be executed in streaming mode.
        :return: The result of processing the current workflow section.
        """
        preset = None
        if "preset" in config:
            preset = config["preset"]
        if "endpointName" in config:
            # load the model
            log("\n\n#########\n" + config["title"])
            log("\n" + "Loading model from config " + config["endpointName"])
            if config["endpointName"] == "" and hasattr(config, "multiModelList"):
                self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0)
            else:
                self.llm_handler = self.llm_handler_service.load_model_from_config(config["endpointName"],
                                                                                   preset,
                                                                                   config["maxNewTokens"],
                                                                                   config["minNewTokens"],
                                                                                   stream)
        if "endpointName" not in config:
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0)

        prompt_processor_service = PromptProcessor(self.workflow_variable_service, self.llm_handler)

        print("\n\nConfig Type:", config.get("type", "No Type Found"))
        if "type" not in config or config["type"] == "Standard":
            print("Standard")
            output = prompt_processor_service.handle_conversation_type_node(config, user_prompt, agent_outputs)
            return output
        if config["type"] == "ConversationMemory":
            print("Conversation Memory")
            return self.handle_conversation_memory_parser(user_prompt)
        if config["type"] == "FullChatSummary":
            print("Entering full chat summary")
            system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
            discussion_id = extract_discussion_id(system_prompt)

            if discussion_id is not None:
                print("Full chat summary discussion id is not none")
                if hasattr(config, "isManualConfig") and config["isManualConfig"] == True:
                    print("Manual summary flow")
                    filepath = get_discussion_chat_summary_file_path(discussion_id)
                    summary_chunk = read_chunks_with_hashes(filepath)
                    if len(summary_chunk) > 0:
                        print("returning manual summary")
                        return extract_text_blocks_from_hashed_chunks(summary_chunk)
                    else:
                        return "No summary found"

                prompt_processor_service.handle_memory_file(discussion_id, pairs)

                filepath = get_discussion_memory_file_path(discussion_id)
                hashed_memory_chunks = read_chunks_with_hashes(
                    filepath)

                print("Number of hash memory chunks read:", len(hashed_memory_chunks))

                filepath = get_discussion_chat_summary_file_path(discussion_id)
                hashed_summary_chunk = read_chunks_with_hashes(
                    filepath)

                print("Number of hash summary chunks read:", len(hashed_summary_chunk))
                index = find_last_matching_memory_hash(hashed_summary_chunk, hashed_memory_chunks)

                print("Index is " + str(index))

                if index > 1 or index < 0:
                    return self.handle_full_chat_summary_parser(user_prompt)
                else:
                    return extract_text_blocks_from_hashed_chunks(hashed_summary_chunk)
        if config["type"] == "RecentMemory":
            print("RecentMemory")
            system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
            discussion_id = extract_discussion_id(system_prompt)

            if discussion_id is not None:
                prompt_processor_service.handle_memory_file(discussion_id, pairs)

            return self.handle_recent_memory_parser(user_prompt)
        if config["type"] == "ConversationalKeywordSearchPerformerTool":
            print("Conversational Keyword Search Performer")
            return prompt_processor_service.perform_keyword_search(config,
                                                                   user_prompt,
                                                                   agent_outputs,
                                                                   config["lookbackStartTurn"])
        if config["type"] == "MemoryKeywordSearchPerformerTool":
            print("Memory Keyword Search Performer")
            return prompt_processor_service.perform_keyword_search(config,
                                                                   user_prompt,
                                                                   agent_outputs)
        if config["type"] == "RecentMemorySummarizerTool":
            print("Recent memory summarization tool")
            return prompt_processor_service.gather_recent_memories(user_prompt,
                                                                   config["maxTurnsToPull"],
                                                                   config["maxSummaryChunksFromFile"])
        if config["type"] == "ChatSummaryMemoryGatheringTool":
            print("Chat summary memory gathering tool")
            return prompt_processor_service.gather_chat_summary_memories(user_prompt,
                                                                         config["maxTurnsToPull"],
                                                                         config["maxSummaryChunksFromFile"])
        if config["type"] == "GetCurrentSummaryFromFile":
            print("Getting current summary from File")
            return self.handle_get_current_summary_from_file(user_prompt)
        if config["type"] == "WriteCurrentSummaryToFileAndReturnIt":
            print("Writing current summary to file")
            return prompt_processor_service.save_summary_to_file(config,
                                                                 user_prompt,
                                                                 agent_outputs)
        if config["type"] == "SlowButQualityRAG":
            print("SlowButQualityRAG")
            return prompt_processor_service.perform_slow_but_quality_rag(config, user_prompt, agent_outputs)
        if config["type"] == "OversizedPromptProcessor":
            print("Oversized prompt processor")
            return
        if config["type"] == "QualityMemory":
            print("Quality memory")
            return self.handle_quality_memory_workflow(user_prompt, prompt_processor_service)

    def handle_quality_memory_workflow(self, user_prompt, prompt_processor_service):
        """
        Handles the workflow for processing quality memory.

        This method extracts pairs and system prompt from the user prompt and processes them
        based on the presence of a discussion ID. It delegates the processing to either
        the recent memory parser or the file memories processor based on the context.

        :param user_prompt: The user's prompt to be processed by the workflow.
        :param prompt_processor_service: An instance of PromptProcessor service to handle prompt processing.
        :return: The result of the quality memory workflow execution.
        """
        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
        discussion_id = extract_discussion_id(system_prompt)

        if discussion_id is None:
            return self.handle_recent_memory_parser(user_prompt)
        else:
            print("Qualtiy memory discussion_id flow")
            prompt_processor_service.handle_memory_file(discussion_id, pairs)
            return self.process_file_memories(user_prompt)

    def handle_get_current_summary_from_file(self, user_prompt):
        """
        Retrieves the current summary from a file based on the user's prompt.

        This method extracts the system prompt and pairs from the user prompt, obtains the discussion ID,
        and reads the corresponding summary file. If the summary file exists and is not empty,
        it extracts and returns the text blocks from the file. Otherwise, it returns a message
        indicating that a summary file does not yet exist.

        :param user_prompt: The user's prompt to be processed by the workflow.
        :return: The current summary extracted from the file or a message indicating the absence of a summary file.
        """
        system_prompt, pairs = extract_pairs_and_system_prompt_from_wilmer_templated_string(user_prompt, False)
        discussion_id = extract_discussion_id(system_prompt)
        filepath = get_discussion_memory_file_path(discussion_id)

        current_summary = read_chunks_with_hashes(filepath)

        if current_summary is None or len(current_summary) == 0:
            return "There is not yet a summary file"

        return extract_text_blocks_from_hashed_chunks(current_summary)
