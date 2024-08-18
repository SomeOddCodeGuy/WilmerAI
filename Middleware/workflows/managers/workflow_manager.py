import json
import time
import traceback
import uuid
from typing import Dict, List

from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities import instance_utils
from Middleware.utilities.config_utils import get_active_conversational_memory_tool_name, \
    get_active_recent_memory_tool_name, get_file_memory_tool_name, \
    get_chat_template_name, get_discussion_chat_summary_file_path, get_discussion_memory_file_path, get_workflow_path, \
    get_chat_summary_tool_workflow_name
from Middleware.utilities.file_utils import read_chunks_with_hashes
from Middleware.utilities.instance_utils import INSTANCE_ID
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id, remove_discussion_id_tag
from Middleware.utilities.prompt_utils import find_last_matching_memory_hash, extract_text_blocks_from_hashed_chunks
from Middleware.utilities.sql_lite_utils import SqlLiteUtils
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.processors.prompt_processor import PromptProcessor


class WorkflowManager:
    """
    Manages the execution of workflows for various types of LLM-based tasks.
    """

    @staticmethod
    def handle_conversation_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing conversation memory.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_conversational_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id)

    @staticmethod
    def handle_recent_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing recent chat memory.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_recent_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id)

    @staticmethod
    def handle_full_chat_summary_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing a full chat summary.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_chat_summary_tool_workflow_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id)

    @staticmethod
    def process_file_memories(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for processing memories from files.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_file_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id)

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

    def run_workflow(self, messages, request_id, discussionId: str = None, stream: bool = False):
        """
        Executes the workflow based on the configuration file.

        :param request_id: Request ID unique to the endpoint call
        :param messages: The user's prompt to be processed by the workflow.
        :param stream: A flag indicating whether the workflow should be executed in streaming mode.
        :return: The result of the workflow execution.
        """
        workflow_id = str(uuid.uuid4())
        if (discussionId is None):
            discussion_id = extract_discussion_id(messages)
        else:
            discussion_id = discussionId

        remove_discussion_id_tag(messages)
        try:
            start_time = time.perf_counter()
            config_file = get_workflow_path(self.workflowConfigName)

            with open(config_file) as f:
                configs = json.load(f)

            def gen():
                returned_to_user = False
                agent_outputs = {}
                try:
                    for idx, config in enumerate(configs):
                        print(f'------Workflow {self.workflowConfigName}; ' +
                              f'step {idx}; node type: {config.get("type", "Standard")}')
                        if not returned_to_user and (config.get('returnToUser', False) or idx == len(configs) - 1):
                            returned_to_user = True
                            result = self._process_section(config, request_id, workflow_id, discussion_id, messages,
                                                           agent_outputs,
                                                           stream=stream)
                            if stream:
                                text_chunks = []
                                for chunk in result:
                                    if chunk.strip() != '[DONE]' and chunk.strip() != 'data: [DONE]':
                                        text_chunks.append(
                                            json.loads(chunk.removeprefix('data:'))['choices'][0]['text'])
                                        yield chunk
                                    else:
                                        yield chunk
                                result = ''.join(text_chunks)
                            else:
                                yield result
                            agent_outputs[f'agent{idx + 1}Output'] = result
                        else:
                            agent_outputs[f'agent{idx + 1}Output'] = self._process_section(config, request_id,
                                                                                           workflow_id,
                                                                                           discussion_id,
                                                                                           messages,
                                                                                           agent_outputs)
                except EarlyTerminationException:
                    print(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
                    SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)
                    raise

                end_time = time.perf_counter()
                execution_time = end_time - start_time
                print(f"Execution time: {execution_time} seconds")

                print(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
                SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)

            if stream:
                return gen()
            else:
                exhaust_generator = [x for x in gen()]
                assert len(exhaust_generator) == 1
                return exhaust_generator[0]
        except EarlyTerminationException:
            print(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
            SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)
            raise
        except Exception as e:
            print("An error occurred while processing the workflow: ", e)
            traceback.print_exc()  # This prints the stack trace
            print(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
            SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)

    def _process_section(self, config: Dict, request_id, workflow_id, discussion_id: str,
                         messages: List[Dict[str, str]] = None,
                         agent_outputs: Dict = None,
                         stream: bool = False):
        """
        Processes a single section of the workflow configuration.

        :param config: The configuration dictionary for the current workflow section.
        :param messages: List of message dictionaries.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :param stream: A flag indicating whether the workflow should be executed in streaming mode.
        :return: The result of processing the current workflow section.
        """
        preset = None
        if "preset" in config:
            preset = config["preset"]
        if "endpointName" in config:
            # load the model
            print("\n\n#########\n" + config["title"])
            print("\n" + "Loading model from config " + config["endpointName"])
            if config["endpointName"] == "" and hasattr(config, "multiModelList"):
                self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)
            else:
                self.llm_handler = self.llm_handler_service.load_model_from_config(config["endpointName"],
                                                                                   preset,
                                                                                   stream,
                                                                                   config.get("maxContextTokenSize",
                                                                                              4096),
                                                                                   config.get("maxResponseSizeInTokens",
                                                                                              400))
        if "endpointName" not in config:
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)

        print("Prompt processor Checkpoint")
        prompt_processor_service = PromptProcessor(self.workflow_variable_service, self.llm_handler)

        print("\n\nConfig Type:", config.get("type", "No Type Found"))
        if "type" not in config or config["type"] == "Standard":
            print("Standard")
            return prompt_processor_service.handle_conversation_type_node(config, messages, agent_outputs)
        if config["type"] == "ConversationMemory":
            print("Conversation Memory")
            return self.handle_conversation_memory_parser(request_id, discussion_id, messages)
        if config["type"] == "FullChatSummary":
            print("Entering full chat summary")
            return self.handle_full_chat_summary(messages, config, prompt_processor_service, request_id, discussion_id)
        if config["type"] == "RecentMemory":
            print("RecentMemory")

            if discussion_id is not None:
                prompt_processor_service.handle_memory_file(discussion_id, messages)

            return self.handle_recent_memory_parser(request_id, discussion_id, messages)
        if config["type"] == "ConversationalKeywordSearchPerformerTool":
            print("Conversational Keyword Search Performer")
            return prompt_processor_service.perform_keyword_search(config,
                                                                   messages,
                                                                   discussion_id,
                                                                   agent_outputs,
                                                                   config["lookbackStartTurn"])
        if config["type"] == "MemoryKeywordSearchPerformerTool":
            print("Memory Keyword Search Performer")
            return prompt_processor_service.perform_keyword_search(config,
                                                                   messages,
                                                                   discussion_id,
                                                                   agent_outputs)
        if config["type"] == "RecentMemorySummarizerTool":
            print("Recent memory summarization tool")
            return prompt_processor_service.gather_recent_memories(messages,
                                                                   discussion_id,
                                                                   config["maxTurnsToPull"],
                                                                   config["maxSummaryChunksFromFile"])
        if config["type"] == "ChatSummaryMemoryGatheringTool":
            print("Chat summary memory gathering tool")
            return prompt_processor_service.gather_chat_summary_memories(messages,
                                                                         discussion_id,
                                                                         config["maxTurnsToPull"],
                                                                         config["maxSummaryChunksFromFile"])
        if config["type"] == "GetCurrentSummaryFromFile":
            print("Getting current summary from File")
            return self.handle_get_current_summary_from_file(discussion_id)
        if config["type"] == "GetCurrentMemoryFromFile":
            print("Getting current memories from File")
            return self.handle_get_current_summary_from_file(discussion_id)
        if config["type"] == "WriteCurrentSummaryToFileAndReturnIt":
            print("Writing current summary to file")
            return prompt_processor_service.save_summary_to_file(config,
                                                                 messages,
                                                                 discussion_id,
                                                                 agent_outputs)
        if config["type"] == "SlowButQualityRAG":
            print("SlowButQualityRAG")
            return prompt_processor_service.perform_slow_but_quality_rag(config, messages, agent_outputs)
        if config["type"] == "QualityMemory":
            print("Quality memory")
            return self.handle_quality_memory_workflow(request_id, messages, prompt_processor_service, discussion_id)
        if config["type"] == "PythonModule":
            print("Python Module")
            return self.handle_python_module(config, prompt_processor_service, messages, agent_outputs)
        if config["type"] == "OfflineWikiApiFullArticle":
            print("Offline Wikipedia Api Full Article")
            return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"], agent_outputs)
        if config["type"] == "OfflineWikiApiPartialArticle":
            print("Offline Wikipedia Api Summary Only")
            return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"], agent_outputs,
                                                                     False)
        if config["type"] == "WorkflowLock":
            print("Workflow Lock")

            workflow_lock_id = config.get("workflowLockId")
            if not workflow_lock_id:
                raise ValueError("A WorkflowLock node must have a 'workflowLockId'.")

            # Check for an existing lock
            lock_exists = SqlLiteUtils.get_lock(workflow_lock_id)

            if lock_exists:
                # Lock exists and is still valid, throw an early termination exception
                print(f"Lock for {workflow_lock_id} is currently active, terminating workflow.")
                raise EarlyTerminationException(f"Workflow is locked by {workflow_lock_id}. Please try again later.")
            else:
                # No lock or expired lock, create a new one
                SqlLiteUtils.create_node_lock(INSTANCE_ID, workflow_id, workflow_lock_id)
                print(
                    f"Lock for Instance_ID: '{INSTANCE_ID}' and workflow_id '{workflow_id}' and workflow_lock_id: '"
                    f"{workflow_lock_id}' has been acquired.")

    def handle_python_module(self, config, prompt_processor_service, messages, agent_outputs):
        """
        Handles the execution of a Python module within the workflow.

        :param config: The configuration dictionary for the Python module.
        :param prompt_processor_service: An instance of PromptProcessor service to handle prompt processing.
        :param messages: List of message dictionaries.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :return: The result of the Python module execution.
        """
        if config["args"] is None:
            args = ()
        else:
            args = config["args"]
        if config["kwargs"] is None:
            kwargs = {}
        else:
            kwargs = config["kwargs"]
        return prompt_processor_service.handle_python_module(config, messages, config["module_path"],
                                                             agent_outputs, *args, **kwargs)

    def handle_full_chat_summary(self, messages, config, prompt_processor_service, request_id, discussion_id):
        """
        Handles the workflow for generating a full chat summary.

        :param messages: List of message dictionaries.
        :param config: The configuration dictionary for the full chat summary workflow.
        :param prompt_processor_service: An instance of PromptProcessor service to handle prompt processing.
        :param request_id: The request ID unique to the endpoint call
        :param discussion_id: The discussion id pulled from the prompt for summaries and chats
        :return: The result of the full chat summary workflow execution.
        """
        print("CHeckingpoint1: ")
        print("Discussion ID: ", discussion_id)
        if discussion_id is not None:
            print("Full chat summary discussion id is not none")
            if hasattr(config, "isManualConfig") and config["isManualConfig"]:
                print("Manual summary flow")
                filepath = get_discussion_chat_summary_file_path(discussion_id)
                summary_chunk = read_chunks_with_hashes(filepath)
                if len(summary_chunk) > 0:
                    print("returning manual summary")
                    return extract_text_blocks_from_hashed_chunks(summary_chunk)
                else:
                    return "No summary found"

            prompt_processor_service.handle_memory_file(discussion_id, messages)

            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_memory_chunks = read_chunks_with_hashes(
                filepath)

            print("Number of hash memory chunks read:", len(hashed_memory_chunks))

            filepath = get_discussion_chat_summary_file_path(discussion_id)
            hashed_summary_chunk = read_chunks_with_hashes(
                filepath)

            print("Number of hash summary chunks read:", len(hashed_summary_chunk))
            index = find_last_matching_memory_hash(hashed_summary_chunk, hashed_memory_chunks)

            print("Number of memory chunks since last summary update: " + str(index))

            if index > 1 or index < 0:
                return self.handle_full_chat_summary_parser(request_id, discussion_id, messages)
            else:
                return extract_text_blocks_from_hashed_chunks(hashed_summary_chunk)

    def handle_quality_memory_workflow(self, request_id, messages: List[Dict[str, str]], prompt_processor_service,
                                       discussion_id):
        """
        Handles the workflow for processing quality memory.

        :param messages: List of message dictionaries.
        :param prompt_processor_service: An instance of PromptProcessor service to handle prompt processing.
        :param request_id: The request ID unique to the endpoint call
        :param discussion_id: The discussion id pulled from the prompt for summaries
        :return: The result of the quality memory workflow execution.
        """

        if discussion_id is None:
            print("Quality memory discussion_id is none")
            return self.handle_recent_memory_parser(request_id, discussion_id, messages)
        else:
            print("Quality memory discussion_id flow")
            prompt_processor_service.handle_memory_file(discussion_id, messages)
            return self.process_file_memories(request_id, discussion_id, messages)

    def handle_get_current_summary_from_file(self, discussion_id: str):
        """
        Retrieves the current summary from a file based on the user's prompt.

        :param discussion_id: Discussion id used for memories and chat summary
        :return: The current summary extracted from the file or a message indicating the absence of a summary file.
        """
        filepath = get_discussion_chat_summary_file_path(discussion_id)

        current_summary = read_chunks_with_hashes(filepath)

        if current_summary is None or len(current_summary) == 0:
            return "There is not yet a summary file"

        return extract_text_blocks_from_hashed_chunks(current_summary)

    def handle_get_current_memories_from_file(self, discussion_id):
        """
        Retrieves the current summary from a file based on the user's prompt.

        :param discussion_id: Discussion id used for memories and chat summary
        :return: The current summary extracted from the file or a message indicating the absence of a summary file.
        """
        filepath = get_discussion_memory_file_path(discussion_id)

        current_memories = read_chunks_with_hashes(filepath)

        if current_memories is None or len(current_memories) == 0:
            return "There are not yet any memories"

        return extract_text_blocks_from_hashed_chunks(current_memories)
