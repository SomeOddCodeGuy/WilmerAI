import json
import logging
import time
import uuid
import types
from copy import deepcopy
from typing import Dict, List

from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import get_active_conversational_memory_tool_name, \
    get_active_recent_memory_tool_name, get_file_memory_tool_name, \
    get_chat_template_name, get_discussion_chat_summary_file_path, get_discussion_memory_file_path, \
    get_chat_summary_tool_workflow_name
from Middleware.utilities.config_utils import get_workflow_path as default_get_workflow_path
from Middleware.utilities.file_utils import read_chunks_with_hashes, load_custom_file
from Middleware.utilities.instance_utils import INSTANCE_ID
from Middleware.utilities.memory_utils import gather_chat_summary_memories, \
    handle_get_current_summary_from_file, gather_recent_memories
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id, remove_discussion_id_tag
from Middleware.utilities.prompt_utils import find_how_many_new_memories_since_last_summary, \
    extract_text_blocks_from_hashed_chunks
from Middleware.utilities.sql_lite_utils import SqlLiteUtils
from Middleware.utilities.time_tracking_utils import track_message_timestamps
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.processors.prompt_processor import PromptProcessor

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Manages the execution of workflows for various types of LLM-based tasks.
    """

    @staticmethod
    def run_custom_workflow(workflow_name, request_id, discussion_id: str, messages: List[Dict[str, str]] = None,
                            non_responder=None, is_streaming=False, first_node_system_prompt_override=None,
                            first_node_prompt_override=None):
        workflow_gen = WorkflowManager(workflow_config_name=workflow_name)
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=non_responder,
                                         stream=is_streaming,
                                         first_node_system_prompt_override=first_node_system_prompt_override,
                                         first_node_prompt_override=first_node_prompt_override)

    @staticmethod
    def handle_conversation_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing conversation memory.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_conversational_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_recent_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing recent chat memory.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_recent_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_full_chat_summary_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing a full chat summary.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_chat_summary_tool_workflow_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def process_file_memories(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for processing memories from files.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_file_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    def __init__(self, workflow_config_name, **kwargs):
        """
        Initializes the WorkflowManager with the given workflow configuration name and optional parameters.

        :param workflow_config_name: The name of the workflow configuration file.
        :param kwargs: Optional keyword arguments, including 'llm_handler' and 'lookbackStartTurn', 'path_finder_func', 'chat_template_name'.
        """
        # path_finder_func is needed for testing. When not provided, default_get_workflow_path is used (original behavior)
        self.path_finder_func = kwargs.pop('path_finder_func', default_get_workflow_path)
        self.llm_handler = None

        if 'llm_handler' in kwargs:
            self.llm_handler = kwargs['llm_handler']
        if 'lookbackStartTurn' in kwargs:
            self.lookbackStartTurn = kwargs['lookbackStartTurn']
        if 'chat_template_name' in kwargs:
            chat_template_name = kwargs.pop('chat_template_name')
            logger.debug(f"Using injected chat_template_name: {chat_template_name}")
        else:
            chat_template_name = get_chat_template_name()
            logger.debug(f"Using default chat_template_name: {chat_template_name}")
        
        self.workflow_variable_service = WorkflowVariableManager(
            chat_prompt_template_name=chat_template_name, 
            **kwargs)
        self.workflowConfigName = workflow_config_name
        self.llm_handler_service = LlmHandlerService()

    def run_workflow(self, messages, request_id, discussionId: str = None, stream: bool = False, nonResponder=None,
                     first_node_system_prompt_override=None, first_node_prompt_override=None):
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

        self.override_first_available_prompts = False

        if (first_node_system_prompt_override is not None and first_node_prompt_override is not None):
            self.override_first_available_prompts = True

        try:
            start_time = time.perf_counter()
            config_file = self.path_finder_func(self.workflowConfigName)

            with open(config_file) as f:
                configs = json.load(f)

            def gen():
                returned_to_user = False
                agent_outputs = {}
                try:
                    for idx, config in enumerate(configs):
                        logger.info(f'------Workflow {self.workflowConfigName}; ' +
                                    f'step {idx}; node type: {config.get("type", "Standard")}')

                        if "systemPrompt" in config or "prompt" in config:
                            if self.override_first_available_prompts:
                                if first_node_system_prompt_override is not None:
                                    config["systemPrompt"] = first_node_system_prompt_override
                                if first_node_prompt_override is not None:
                                    config["prompt"] = first_node_prompt_override
                                self.override_first_available_prompts = False

                        add_user_prompt = config.get('addUserTurnTemplate', False)
                        force_generation_prompt_if_endpoint_allows = (
                            config.get('forceGenerationPromptIfEndpointAllows', False))
                        block_generation_prompt = (
                            config.get('blockGenerationPrompt', False))
                        if not returned_to_user and (config.get('returnToUser', False) or idx == len(configs) - 1):
                            returned_to_user = True
                            logger.debug("Returned to user flow")
                            if (
                                    nonResponder is None and not force_generation_prompt_if_endpoint_allows and not add_user_prompt) or block_generation_prompt:
                                add_generation_prompt = False
                            else:
                                add_generation_prompt = None

                            add_timestamps = config.get("addDiscussionIdTimestampsForLLM", False)

                            if (nonResponder is None and discussion_id is not None and add_timestamps):
                                logger.debug("Timestamp is true")
                                messageCopy = deepcopy(messages)
                                messagesToSend = track_message_timestamps(messages=messageCopy,
                                                                          discussion_id=discussion_id)
                            else:
                                logger.debug("Timestamp is false")
                                messagesToSend = messages

                            result = self._process_section(
                                config,
                                request_id,
                                workflow_id,
                                discussion_id,
                                messagesToSend,
                                agent_outputs,
                                                           stream=stream, addGenerationPrompt=add_generation_prompt)
                            if stream:
                                text_chunks = []
                                for chunk in result:
                                    # Extract text using the helper function
                                    extracted_text = api_utils.extract_text_from_chunk(chunk)
                                    if extracted_text:
                                        text_chunks.append(extracted_text)
                                    yield chunk
                                result = ''.join(text_chunks)
                                logger.info(
                                    "\n\n*****************************************************************************\n")
                                logger.info("\n\nOutput from the LLM: %s", result)
                                logger.info(
                                    "\n*****************************************************************************\n\n")
                            else:
                                yield result

                            # Assign the final result to the agent's output field
                            agent_outputs[f'agent{idx + 1}Output'] = result
                        else:
                            if (
                                    not force_generation_prompt_if_endpoint_allows and not add_user_prompt) or block_generation_prompt:
                                add_generation_prompt = False
                            else:
                                add_generation_prompt = None
                            agent_outputs[f'agent{idx + 1}Output'] = self._process_section(config, request_id,
                                                                                           workflow_id,
                                                                                           discussion_id,
                                                                                           messages,
                                                                                           agent_outputs,
                                                                                           stream=False, # it is not a responder, so we don't need to stream
                                                                                           addGenerationPrompt=add_generation_prompt)
                except EarlyTerminationException:
                    logger.info(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
                    SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)
                    raise

                end_time = time.perf_counter()
                execution_time = end_time - start_time
                logger.info(f"Execution time: {execution_time} seconds")

                logger.info(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
                SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)

            if stream:
                return gen()
            else:
                exhaust_generator = [x for x in gen()]
                assert len(exhaust_generator) == 1
                return exhaust_generator[0]
        except EarlyTerminationException:
            logger.info(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
            SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)
            raise
        except Exception as e:
            logger.exception("An error occurred while processing the workflow: %s", e)
            logger.info(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
            SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)

    def _process_section(self, config: Dict, request_id, workflow_id, discussion_id: str,
                         messages: List[Dict[str, str]] = None,
                         agent_outputs: Dict = None,
                         stream: bool = False,
                         addGenerationPrompt: bool = None):
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
            logger.info("\n\n#########\n%s", config["title"])
            logger.info("\nLoading model from config %s", config["endpointName"])
            if config["endpointName"] == "" and hasattr(config, "multiModelList"):
                self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)
            else:
                self.llm_handler = self.llm_handler_service.load_model_from_config(config["endpointName"],
                                                                                   preset,
                                                                                   stream,
                                                                                   config.get("maxContextTokenSize",
                                                                                              4096),
                                                                                   config.get("maxResponseSizeInTokens",
                                                                                              400),
                                                                                   addGenerationPrompt)
        if "endpointName" not in config:
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)

        logger.debug("Prompt processor Checkpoint")
        if "type" not in config:
            section_name = config.get("title", "Unknown")
            valid_types = ["Standard", "ConversationMemory", "FullChatSummary", "RecentMemory", 
                          "ConversationalKeywordSearchPerformerTool", "MemoryKeywordSearchPerformerTool", 
                          "RecentMemorySummarizerTool", "ChatSummaryMemoryGatheringTool", "GetCurrentSummaryFromFile", 
                          "chatSummarySummarizer", "GetCurrentMemoryFromFile", "WriteCurrentSummaryToFileAndReturnIt", 
                          "SlowButQualityRAG", "QualityMemory", "PythonModule", "OfflineWikiApiFullArticle", 
                          "OfflineWikiApiBestFullArticle", "OfflineWikiApiTopNFullArticles", "OfflineWikiApiPartialArticle", 
                          "WorkflowLock", "CustomWorkflow", "ConditionalCustomWorkflow", "GetCustomFile", "ImageProcessor"]
            logger.warning(f"Config Type: No Type Found for section '{section_name}'. Expected one of: {valid_types}")
        else:
            logger.info("Config Type: %s", config.get("type"))
        prompt_processor_service = PromptProcessor(self.workflow_variable_service, self.llm_handler)

        if "type" not in config or config["type"] == "Standard":
            logger.debug("Standard")
            return prompt_processor_service.handle_conversation_type_node(config, messages, agent_outputs)
        if config["type"] == "ConversationMemory":
            logger.debug("Conversation Memory")
            return self.handle_conversation_memory_parser(request_id, discussion_id, messages)
        if config["type"] == "FullChatSummary":
            logger.debug("Entering full chat summary")
            return self.handle_full_chat_summary(messages, config, prompt_processor_service, request_id, discussion_id)
        if config["type"] == "RecentMemory":
            logger.debug("RecentMemory")

            if discussion_id is not None:
                prompt_processor_service.handle_memory_file(discussion_id, messages)

            return self.handle_recent_memory_parser(request_id, discussion_id, messages)
        if config["type"] == "ConversationalKeywordSearchPerformerTool":
            logger.debug("Conversational Keyword Search Performer")
            return prompt_processor_service.perform_keyword_search(config,
                                                                   messages,
                                                                   discussion_id,
                                                                   agent_outputs,
                                                                   config["lookbackStartTurn"])
        if config["type"] == "MemoryKeywordSearchPerformerTool":
            logger.debug("Memory Keyword Search Performer")
            return prompt_processor_service.perform_keyword_search(config,
                                                                   messages,
                                                                   discussion_id,
                                                                   agent_outputs)
        if config["type"] == "RecentMemorySummarizerTool":
            logger.debug("Recent memory summarization tool")
            memories = gather_recent_memories(messages,
                                              discussion_id,
                                              config["maxTurnsToPull"],
                                              config["maxSummaryChunksFromFile"],
                                              config.get("lookbackStart", 0))
            custom_delimiter = config.get("customDelimiter", None)
            if custom_delimiter is not None and memories is not None:
                return memories.replace("--ChunkBreak--", custom_delimiter)
            elif memories is not None:
                return memories
            else:
                return "There are not yet any memories"
        if config["type"] == "ChatSummaryMemoryGatheringTool":
            logger.debug("Chat summary memory gathering tool")
            return gather_chat_summary_memories(messages,
                                                discussion_id,
                                                config["maxTurnsToPull"])
        if config["type"] == "GetCurrentSummaryFromFile":
            logger.debug("Getting current summary from File")
            return handle_get_current_summary_from_file(discussion_id)
        if config["type"] == "chatSummarySummarizer":
            logger.debug("Summarizing the chat memory into a single chat summary")
            return prompt_processor_service.handle_process_chat_summary(config, messages, agent_outputs, discussion_id)
        if config["type"] == "GetCurrentMemoryFromFile":
            logger.debug("Getting current memories from File")
            return handle_get_current_summary_from_file(discussion_id)
        if config["type"] == "WriteCurrentSummaryToFileAndReturnIt":
            logger.debug("Writing current summary to file")
            return prompt_processor_service.save_summary_to_file(config,
                                                                 messages,
                                                                 discussion_id,
                                                                 agent_outputs)
        if config["type"] == "SlowButQualityRAG":
            logger.debug("SlowButQualityRAG")
            return prompt_processor_service.perform_slow_but_quality_rag(config, messages, agent_outputs)
        if config["type"] == "QualityMemory":
            logger.debug("Quality memory")
            return self.handle_quality_memory_workflow(request_id, messages, prompt_processor_service, discussion_id)
        if config["type"] == "PythonModule":
            logger.debug("Python Module")
            return self.handle_python_module(config, prompt_processor_service, messages, agent_outputs)
        if config["type"] == "OfflineWikiApiFullArticle":
            # DEPRECATED. REMOVING SOON
            logger.debug("Offline Wikipedia Api Full Article")
            return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"], agent_outputs)
        if config["type"] == "OfflineWikiApiBestFullArticle":
            logger.debug("Offline Wikipedia Api Best Full Article")
            return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"], agent_outputs,
                                                                     use_new_best_article_endpoint=True)
        if config["type"] == "OfflineWikiApiTopNFullArticles":
            if ("percentile" in config) and ("num_results" in config) and ("top_n_articles" in config):
                logger.debug("Offline Wikipedia Api TopN Full Articles")
                return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"],
                                                                         agent_outputs,
                                                                         use_new_best_article_endpoint=False,
                                                                         use_top_n_articles_endpoint=True,
                                                                         percentile=config["percentile"],
                                                                         num_results=config["num_results"],
                                                                         top_n_articles=config["top_n_articles"]
                                                                         )
            else:
                logger.debug("Offline Wikipedia Api TopN Full Articles")
                return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"],
                                                                         agent_outputs,
                                                                         use_new_best_article_endpoint=False,
                                                                         use_top_n_articles_endpoint=True
                                                                         )

        if config["type"] == "OfflineWikiApiPartialArticle":
            logger.debug("Offline Wikipedia Api Summary Only")
            return prompt_processor_service.handle_offline_wiki_node(messages, config["promptToSearch"], agent_outputs,
                                                                     False)
        if config["type"] == "WorkflowLock":
            logger.debug("Workflow Lock")

            workflow_lock_id = config.get("workflowLockId")
            if not workflow_lock_id:
                raise ValueError("A WorkflowLock node must have a 'workflowLockId'.")

            # Check for an existing lock
            lock_exists = SqlLiteUtils.get_lock(workflow_lock_id)

            if lock_exists:
                # Lock exists and is still valid, throw an early termination exception
                logger.info(f"Lock for {workflow_lock_id} is currently active, terminating workflow.")
                raise EarlyTerminationException(f"Workflow is locked by {workflow_lock_id}. Please try again later.")
            else:
                # No lock or expired lock, create a new one
                SqlLiteUtils.create_node_lock(INSTANCE_ID, workflow_id, workflow_lock_id)
                logger.info(
                    f"Lock for Instance_ID: '{INSTANCE_ID}' and workflow_id '{workflow_id}' and workflow_lock_id: '"
                    f"{workflow_lock_id}' has been acquired.")

        if config["type"] == "CustomWorkflow":
            return self.handle_custom_workflow(config, messages, agent_outputs, stream, request_id, discussion_id)
        if config["type"] == "ConditionalCustomWorkflow":
            return self.handle_conditional_custom_workflow(
                config, messages, agent_outputs, stream, request_id, discussion_id)
        if config["type"] == "GetCustomFile":
            logger.debug("Get custom file")
            delimiter = config.get("delimiter")
            custom_return_delimiter = config.get("customReturnDelimiter")
            filepath = config.get("filepath")

            if filepath is None:
                return "No filepath specified"

            if delimiter is None:
                if custom_return_delimiter is None:
                    custom_return_delimiter = "\n"
                    delimiter = custom_return_delimiter
                else:
                    delimiter = custom_return_delimiter
            elif custom_return_delimiter is None:
                custom_return_delimiter = delimiter

            file = load_custom_file(filepath=filepath, delimiter=delimiter, custom_delimiter=custom_return_delimiter)
            logger.debug("Custom file result: %s", file)
            return file
        if config.get("type") == "ImageProcessor":
            logger.debug("Image Processor node")
            if not any(item.get("role") == "images" for item in messages):
                logger.debug("No images were present in the conversation collection. Returning hardcoded response.")
                return "There were no images attached to the message"
            prompt_processor_service = PromptProcessor(self.workflow_variable_service, self.llm_handler)
            images = prompt_processor_service.handle_image_processor_node(config, messages, agent_outputs)
            add_as_user_message = config.get("addAsUserMessage", False)
            if (add_as_user_message):
                message = config.get("message",
                                     f"[SYSTEM: The user recently added images to the conversation. "
                                     f"The images have been analyzed by an advanced vision AI, which has described them"
                                     f" in detail. The descriptions of the images can be found below:```\n[IMAGE_BLOCK]]\n```]")
                message = self.workflow_variable_service.apply_variables(
                    message,
                    self.llm_handler,
                    messages,
                    agent_outputs,
                    config=config
                )
                message = message.replace("[IMAGE_BLOCK]", images)
                if (len(messages) >= 2):
                    messages.insert(-1, {"role": "user", "content": message})
                else:
                    messages.append({"role": "user", "content": message})

            return images

    def _prepare_workflow_overrides(self, config, messages, agent_outputs, stream):
        """
        Prepares overrides and determines responder and streaming settings for a workflow node.

        :param config: The configuration dictionary for the workflow node.
        :param messages: List of message dictionaries exchanged during the workflow.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :param stream: Boolean indicating whether streaming is enabled.
        :return: A tuple containing:
                 - system_prompt: Overridden system prompt (if any).
                 - prompt: Overridden user prompt (if any).
                 - non_responder: Boolean indicating if the node is not the final responder.
                 - allow_streaming: Boolean indicating if streaming is allowed.
        """
        is_responder = config.get("isResponder", False) or config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = stream if is_responder else False

        # Apply system prompt override if present
        system_override_raw = config.get("firstNodeSystemPromptOverride", None)
        if system_override_raw not in [None, ""]:
            system_prompt = self.workflow_variable_service.apply_variables(
                system_override_raw, self.llm_handler, messages, agent_outputs, config=config
            )
        else:
            system_prompt = None

        # Apply prompt override if present
        prompt_override_raw = config.get("firstNodePromptOverride", None)
        if prompt_override_raw not in [None, ""]:
            prompt = self.workflow_variable_service.apply_variables(
                prompt_override_raw, self.llm_handler, messages, agent_outputs, config=config
            )
        else:
            prompt = None

        return system_prompt, prompt, non_responder, allow_streaming

    def handle_custom_workflow(self, config, messages, agent_outputs, stream, request_id, discussion_id):
        """
        Handles the execution of a standard custom workflow.

        :param config: The configuration dictionary for the workflow node.
        :param messages: List of message dictionaries exchanged during the workflow.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :param stream: Boolean indicating whether streaming is enabled.
        :param request_id: Unique identifier for the request.
        :param discussion_id: Unique identifier for the discussion.
        :return: The result of executing the custom workflow.
        """
        logger.info("Custom Workflow initiated")
        workflow_name = config.get("workflowName", "No_Workflow_Name_Supplied")
        logger.info("Running custom workflow with name: %s", workflow_name)

        # Common overrides & streaming logic
        system_prompt, prompt, non_responder, allow_streaming = \
            self._prepare_workflow_overrides(config, messages, agent_outputs, stream)

        return self.run_custom_workflow(
            workflow_name=workflow_name,
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            non_responder=non_responder,
            is_streaming=allow_streaming,
            first_node_system_prompt_override=system_prompt,
            first_node_prompt_override=prompt
        )

    def handle_conditional_custom_workflow(self, config, messages, agent_outputs, stream, request_id, discussion_id):
        """
        Handles the execution of a conditional custom workflow, selecting the workflow based on a conditional key,
        and optionally applying per-route overrides to the first node of the selected workflow.

        :param config: The configuration dictionary for the workflow node, including `conditionalKey` and `conditionalWorkflows`.
        :param messages: List of message dictionaries exchanged during the workflow.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :param stream: Boolean indicating whether streaming is enabled.
        :param request_id: Unique identifier for the request.
        :param discussion_id: Unique identifier for the discussion.
        :return: The result of executing the selected workflow.
        """
        logger.info("Conditional Custom Workflow initiated")

        # Extract the conditional key and evaluate its value
        conditional_key = config.get("conditionalKey", None)
        if not conditional_key:
            logger.warning("No 'conditionalKey' provided; cannot branch. Falling back to default workflow.")

        raw_key_value = self.workflow_variable_service.apply_variables(
            conditional_key, self.llm_handler, messages, agent_outputs, config=config
        ) if conditional_key else ""

        # Normalize the key value (strip whitespace, convert to lowercase, etc.)
        key_value = raw_key_value.strip().lower()

        # Determine the workflow to execute based on the normalized key's value
        workflow_map = {k.lower(): v for k, v in config.get("conditionalWorkflows", {}).items()}  # Normalize keys
        workflow_name = workflow_map.get(key_value, workflow_map.get("default", "No_Workflow_Name_Supplied"))
        logger.info("Resolved conditionalKey='%s' => workflow_name='%s'", raw_key_value, workflow_name)

        # Fetch route-specific overrides, if any
        route_overrides = config.get("routeOverrides", {}).get(key_value.capitalize(), {})
        system_prompt_override = route_overrides.get("systemPromptOverride", None)
        prompt_override = route_overrides.get("promptOverride", None)

        # Common streaming and responder logic
        is_responder = config.get("isResponder", False) or config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = stream if is_responder else False

        # Expand route-specific overrides, if provided
        expanded_system_prompt = self.workflow_variable_service.apply_variables(
            system_prompt_override, self.llm_handler, messages, agent_outputs, config=config
        ) if system_prompt_override else None

        expanded_prompt = self.workflow_variable_service.apply_variables(
            prompt_override, self.llm_handler, messages, agent_outputs, config=config
        ) if prompt_override else None

        # Pass the resolved workflow and expanded overrides to the custom workflow executor
        return self.run_custom_workflow(
            workflow_name=workflow_name,
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            non_responder=non_responder,
            is_streaming=allow_streaming,
            first_node_system_prompt_override=expanded_system_prompt,
            first_node_prompt_override=expanded_prompt
        )

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
        logger.info("Discussion ID: %s", discussion_id)
        if discussion_id is not None:
            logger.info("Full chat summary discussion id is not none")
            if hasattr(config, "isManualConfig") and config["isManualConfig"]:
                logger.debug("Manual summary flow")
                filepath = get_discussion_chat_summary_file_path(discussion_id)
                summary_chunk = read_chunks_with_hashes(filepath)
                if len(summary_chunk) > 0:
                    logger.debug("returning manual summary")
                    return extract_text_blocks_from_hashed_chunks(summary_chunk)
                else:
                    return "No summary found"

            prompt_processor_service.handle_memory_file(discussion_id, messages)

            filepath = get_discussion_memory_file_path(discussion_id)
            hashed_memory_chunks = read_chunks_with_hashes(
                filepath)

            logger.debug("Number of hash memory chunks read: %s", len(hashed_memory_chunks))

            filepath = get_discussion_chat_summary_file_path(discussion_id)
            hashed_summary_chunk = read_chunks_with_hashes(
                filepath)

            logger.debug("Number of hash summary chunks read: %s", len(hashed_summary_chunk))
            index = find_how_many_new_memories_since_last_summary(hashed_summary_chunk, hashed_memory_chunks)

            logger.debug("Number of memory chunks since last summary update: %s", index)

            if index > 1 or index < 0:
                return self.handle_full_chat_summary_parser(request_id, discussion_id, messages)
            else:
                return extract_text_blocks_from_hashed_chunks(hashed_summary_chunk)

    def handle_quality_memory_workflow(self, request_id, messages: List[Dict[str, str]], prompt_processor_service,
                                       discussion_id: str):
        """
        Handles the workflow for processing quality memory.

        :param messages: List of message dictionaries.
        :param prompt_processor_service: An instance of PromptProcessor service to handle prompt processing.
        :param request_id: The request ID unique to the endpoint call
        :param discussion_id: The discussion id pulled from the prompt for summaries
        :return: The result of the quality memory workflow execution.
        """

        if discussion_id is None:
            logger.debug("Quality memory discussionid is none")
            return self.handle_recent_memory_parser(request_id, None, messages)
        else:
            logger.debug("Quality memory discussion_id flow")
            prompt_processor_service.handle_memory_file(discussion_id, messages)
            return self.process_file_memories(request_id, discussion_id, messages)