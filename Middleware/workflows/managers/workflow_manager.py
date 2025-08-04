# /Middleware/workflows/managers/workflow_manager.py

import json
import logging
import uuid
from typing import Dict, List, Generator, Union

from Middleware.common import instance_global_variables
from Middleware.services.locking_service import LockingService
from Middleware.utilities.config_utils import (
    get_active_conversational_memory_tool_name, get_active_recent_memory_tool_name,
    get_file_memory_tool_name,
    get_chat_summary_tool_workflow_name,
    get_workflow_path as default_get_workflow_path
)
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id, remove_discussion_id_tag
from Middleware.workflows.handlers.impl.memory_node_handler import MemoryNodeHandler
from Middleware.workflows.handlers.impl.specialized_node_handler import SpecializedNodeHandler
from Middleware.workflows.handlers.impl.standard_node_handler import StandardNodeHandler
from Middleware.workflows.handlers.impl.sub_workflow_handler import SubWorkflowHandler
from Middleware.workflows.handlers.impl.tool_node_handler import ToolNodeHandler
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.services.llm_service import LlmHandlerService
from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Manages the setup and orchestration of workflows.

    This class acts as the primary entry point for all workflow executions. It
    loads the specified workflow configuration, prepares all dependencies (such as
    services and node handlers), and then delegates the step-by-step execution
    to the WorkflowProcessor.

    Attributes:
        workflowConfigName (str): The name of the workflow configuration file.
        workflow_variable_service (WorkflowVariableManager): Service for variable substitution.
        llm_handler_service (LlmHandlerService): Service for creating LLM handlers.
        locking_service (LockingService): Service for managing workflow locks.
        node_handlers (Dict[str, BaseWorkflowNodeHandler]): A mapping of node types to their handler instances.
    """

    @staticmethod
    def run_custom_workflow(workflow_name, request_id, discussion_id: str, messages: List[Dict[str, str]] = None,
                            non_responder=None, is_streaming=False, first_node_system_prompt_override=None,
                            first_node_prompt_override=None) -> Union[Generator[str, None, None], str, None]:
        """
        A static helper method to run a specified workflow by name.

        This method provides a simple, direct entry point to initiate a workflow.
        It instantiates the WorkflowManager for the given workflow name and
        delegates execution to its `run_workflow` instance method.

        Args:
            workflow_name (str): The name of the workflow to execute.
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation context.
            messages (List[Dict[str, str]], optional): A list of message objects.
            non_responder (bool, optional): If True, the workflow runs but does not yield a final response.
            is_streaming (bool, optional): If True, returns a generator for streaming responses. Defaults to False.
            first_node_system_prompt_override (str, optional): A system prompt to override the one in the first node.
            first_node_prompt_override (str, optional): A prompt to override the one in the first node.

        Returns:
            Union[Generator[str, None, None], str, None]: A generator if streaming, the final string
            response if not streaming, or None if no output is generated.
        """
        workflow_gen = WorkflowManager(workflow_config_name=workflow_name)
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=non_responder,
                                         stream=is_streaming,
                                         first_node_system_prompt_override=first_node_system_prompt_override,
                                         first_node_prompt_override=first_node_prompt_override)

    @staticmethod
    def handle_conversation_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[str, None]:
        """
        Runs the workflow responsible for parsing and storing conversation memory.

        This helper method initiates the specific workflow defined as the active
        conversational memory tool. It always runs as a non-responder, as its
        purpose is to update memory state, not generate a user-facing reply.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation context.
            messages (List[Dict[str, str]], optional): The list of message objects to be processed for memory.

        Returns:
            Union[str, None]: The output from the memory processing workflow, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_conversational_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_recent_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[str, None]:
        """
        Runs the workflow for parsing and storing recent memory.

        This helper initiates the workflow designated for handling recent memory.
        It operates as a non-responder, processing the latest messages to update
        the short-term memory state for the conversation.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation context.
            messages (List[Dict[str, str]], optional): The list of recent message objects to process.

        Returns:
            Union[str, None]: The output from the recent memory processing workflow, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_recent_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_full_chat_summary_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[str, None]:
        """
        Runs the workflow that generates a full summary of the chat history.

        This helper method initiates the chat summarization workflow. It is run
        as a non-responder, with its output typically being saved to a file or
        variable for later use in providing long-term context.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation context.
            messages (List[Dict[str, str]], optional): The full list of message objects to summarize.

        Returns:
            Union[str, None]: The generated summary string, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_chat_summary_tool_workflow_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def process_file_memories(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[str, None]:
        """
        Runs the workflow for processing and saving file-based memories.

        This helper triggers the workflow designed to handle file-based memory
        operations, such as saving summaries or contextual data retrieved from
        files. It always runs as a non-responder.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation context.
            messages (List[Dict[str, str]], optional): The list of message objects.

        Returns:
            Union[str, None]: The output from the file memory workflow, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_file_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    def __init__(self, workflow_config_name, **kwargs):
        """
        Initializes the WorkflowManager instance.

        This constructor sets up the necessary services and registers all available
        node handlers. Each handler is instantiated with common dependencies,
        creating a map between node type strings (e.g., "Standard") and their
        corresponding handler instances, ready for the WorkflowProcessor.

        Args:
            workflow_config_name (str): The name of the workflow configuration file.
            **kwargs: Accepts an optional `path_finder_func` to override the
                      default workflow path resolution. Other kwargs are passed to
                      the `WorkflowVariableManager`.
        """
        self.path_finder_func = kwargs.pop('path_finder_func', default_get_workflow_path)
        self.workflowConfigName = workflow_config_name
        self.workflow_variable_service = WorkflowVariableManager(**kwargs)
        self.llm_handler_service = LlmHandlerService()
        self.locking_service = LockingService()

        common_dependencies = {
            "workflow_manager": self,
            "workflow_variable_service": self.workflow_variable_service,
        }

        memory_handler_dependencies = {
            **common_dependencies,
            "process_file_memories_func": self.process_file_memories,
            "handle_recent_memory_parser_func": self.handle_recent_memory_parser,
            "handle_full_chat_summary_parser_func": self.handle_full_chat_summary_parser,
            "handle_conversation_memory_parser_func": self.handle_conversation_memory_parser,
        }

        memory_node_handler = MemoryNodeHandler(**memory_handler_dependencies)

        self.node_handlers = {
            "Standard": StandardNodeHandler(**common_dependencies),
            "ConversationMemory": memory_node_handler,
            "FullChatSummary": memory_node_handler,
            "RecentMemory": memory_node_handler,
            "RecentMemorySummarizerTool": memory_node_handler,
            "ChatSummaryMemoryGatheringTool": memory_node_handler,
            "GetCurrentSummaryFromFile": memory_node_handler,
            "chatSummarySummarizer": memory_node_handler,
            "WriteCurrentSummaryToFileAndReturnIt": memory_node_handler,
            "QualityMemory": memory_node_handler,
            "GetCurrentMemoryFromFile": memory_node_handler,
            "ConversationalKeywordSearchPerformerTool": ToolNodeHandler(**common_dependencies),
            "MemoryKeywordSearchPerformerTool": ToolNodeHandler(**common_dependencies),
            "SlowButQualityRAG": ToolNodeHandler(**common_dependencies),
            "PythonModule": ToolNodeHandler(**common_dependencies),
            "OfflineWikiApiFullArticle": ToolNodeHandler(**common_dependencies),
            "OfflineWikiApiBestFullArticle": ToolNodeHandler(**common_dependencies),
            "OfflineWikiApiTopNFullArticles": ToolNodeHandler(**common_dependencies),
            "OfflineWikiApiPartialArticle": ToolNodeHandler(**common_dependencies),
            "CustomWorkflow": SubWorkflowHandler(**common_dependencies),
            "ConditionalCustomWorkflow": SubWorkflowHandler(**common_dependencies),
            "WorkflowLock": SpecializedNodeHandler(**common_dependencies),
            "GetCustomFile": SpecializedNodeHandler(**common_dependencies),
            "ImageProcessor": SpecializedNodeHandler(**common_dependencies),
        }

    def run_workflow(self, messages, request_id, discussionId: str = None, stream: bool = False, nonResponder=None,
                     first_node_system_prompt_override=None, first_node_prompt_override=None) -> Union[Generator[str, None, None], str, None]:
        """
        Executes the configured workflow.

        This is the core execution method for a WorkflowManager instance. It loads
        the workflow configuration, generates necessary IDs, instantiates the
        WorkflowProcessor with all required context, and then starts the
        execution. It handles both streaming and non-streaming responses.

        Args:
            messages (List[Dict[str, str]]): The list of message objects for the current turn.
            request_id (str): The unique identifier for the overall API request.
            discussionId (str, optional): The identifier for the conversation. If None, it is extracted from messages.
            stream (bool, optional): Whether to yield responses as a stream. Defaults to False.
            nonResponder (bool, optional): If True, the workflow runs but no final response is yielded.
            first_node_system_prompt_override (str, optional): System prompt to override the first node's config.
            first_node_prompt_override (str, optional): User prompt to override the first node's config.

        Returns:
            Union[Generator[str, None, None], str, None]: A generator of response chunks if stream is True.
            The final, complete response string if stream is False. None if no
            output is produced in non-streaming mode.

        Raises:
            Exception: Re-raises any exception that occurs during workflow
                       processing after performing cleanup (e.g., releasing locks).
        """
        workflow_id = str(uuid.uuid4())
        discussion_id = discussionId if discussionId is not None else extract_discussion_id(messages)
        remove_discussion_id_tag(messages)

        try:
            config_file = self.path_finder_func(self.workflowConfigName)
            with open(config_file) as f:
                configs = json.load(f)

            processor = WorkflowProcessor(
                node_handlers=self.node_handlers,
                llm_handler_service=self.llm_handler_service,
                workflow_variable_service=self.workflow_variable_service,
                workflow_config_name=self.workflowConfigName,
                configs=configs,
                request_id=request_id,
                workflow_id=workflow_id,
                discussion_id=discussion_id,
                messages=messages,
                stream=stream,
                non_responder_flag=nonResponder,
                first_node_system_prompt_override=first_node_system_prompt_override,
                first_node_prompt_override=first_node_prompt_override
            )

            result_generator = processor.execute()

            if stream:
                return result_generator
            else:
                exhaust_generator = list(result_generator)
                if len(exhaust_generator) > 1:
                    logger.warning(
                        f"Expected 1 output from non-streaming workflow, but got {len(exhaust_generator)}. Returning the last one.")
                    return exhaust_generator[-1]
                if len(exhaust_generator) == 0:
                    logger.warning("Non-streaming workflow returned no output.")
                    return None
                return exhaust_generator[0]

        except Exception as e:
            logger.exception("An error occurred while setting up the workflow: %s", e)
            logger.info(
                f"Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{workflow_id}' due to an error.")
            self.locking_service.delete_node_locks(instance_global_variables.INSTANCE_ID, workflow_id)
            raise