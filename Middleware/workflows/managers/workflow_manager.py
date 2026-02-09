# /Middleware/workflows/managers/workflow_manager.py

import json
import logging
import uuid
from typing import Dict, List, Generator, Union, Optional

from Middleware.common import instance_global_variables
from Middleware.services.llm_service import LlmHandlerService
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
from Middleware.workflows.processors.workflows_processor import WorkflowProcessor

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Manages the setup and orchestration of workflows.
    """

    @staticmethod
    def run_custom_workflow(workflow_name, request_id, discussion_id: str, messages: List[Dict[str, str]] = None,
                            non_responder: bool | None = None, is_streaming: bool = False,
                            first_node_system_prompt_override: str | None = None,
                            first_node_prompt_override: str | None = None,
                            scoped_inputs: Optional[List[str]] = None,
                            workflow_user_folder_override: Optional[str] = None) -> Union[
        Generator[str, None, None], str, None]:
        """
        Initiates and executes a specified custom workflow.

        Args:
            ...
            first_node_prompt_override (Optional[str]): A string to override the main prompt of the first node. Defaults to None.
            scoped_inputs (Optional[List[str]]): A list of inputs passed from a parent workflow. Defaults to None.
            workflow_user_folder_override (Optional[str]): An override for the user folder to load the workflow from. Defaults to None.

        Returns:
            Union[Generator[str, None, None], str, None]: A generator for streaming responses, a string for non-streaming responses, or None.
        """
        workflow_gen = WorkflowManager(
            workflow_config_name=workflow_name,
            workflow_user_folder_override=workflow_user_folder_override
        )
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=non_responder,
                                         stream=is_streaming,
                                         first_node_system_prompt_override=first_node_system_prompt_override,
                                         first_node_prompt_override=first_node_prompt_override,
                                         scoped_inputs=scoped_inputs)

    @staticmethod
    def handle_conversation_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> \
            Union[str, None]:
        """
        Runs the workflow responsible for parsing and storing conversation memory.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation thread.
            messages (Optional[List[Dict[str, str]]]): The conversation history. Defaults to None.

        Returns:
            Union[str, None]: The result of the workflow execution, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_conversational_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_recent_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[
        str, None]:
        """
        Runs the workflow for parsing and storing recent memory.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation thread.
            messages (Optional[List[Dict[str, str]]]): The conversation history. Defaults to None.

        Returns:
            Union[str, None]: The result of the workflow execution, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_recent_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_full_chat_summary_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[
        str, None]:
        """
        Runs the workflow that generates a full summary of the chat history.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation thread.
            messages (Optional[List[Dict[str, str]]]): The conversation history. Defaults to None.

        Returns:
            Union[str, None]: The result of the workflow execution, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_chat_summary_tool_workflow_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def process_file_memories(request_id, discussion_id: str, messages: List[Dict[str, str]] = None) -> Union[
        str, None]:
        """
        Runs the workflow for processing and saving file-based memories.

        Args:
            request_id (str): A unique identifier for the request.
            discussion_id (str): The identifier for the conversation thread.
            messages (Optional[List[Dict[str, str]]]): The conversation history. Defaults to None.

        Returns:
            Union[str, None]: The result of the workflow execution, or None.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_file_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    def __init__(self, workflow_config_name, **kwargs):
        """
        Initializes the WorkflowManager, loading configuration and registering node handlers.

        Args:
            workflow_config_name (str): The name of the primary workflow configuration.
            **kwargs: Additional keyword arguments, including an optional `path_finder_func` or 'workflow_user_folder_override'.
        """
        workflow_user_folder_override = kwargs.pop('workflow_user_folder_override', None)
        if workflow_user_folder_override:
            # Use a lambda to curry the folder override argument into the default path finder
            self.path_finder_func = lambda wn: default_get_workflow_path(wn,
                                                                         user_folder_override=workflow_user_folder_override)
        else:
            # Keep original behavior
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
        tool_node_handler = ToolNodeHandler(**common_dependencies)
        specialized_node_handler = SpecializedNodeHandler(**common_dependencies)
        sub_workflow_handler = SubWorkflowHandler(**common_dependencies)

        self.node_handlers = {
            "Standard": StandardNodeHandler(**common_dependencies),
            "PythonModule": tool_node_handler,
            "SlowButQualityRAG": tool_node_handler,

            # Memory Nodes
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

            # Tool-based Search nodes
            "ConversationalKeywordSearchPerformerTool": tool_node_handler,
            "MemoryKeywordSearchPerformerTool": tool_node_handler,

            "VectorMemorySearch": memory_node_handler,

            "OfflineWikiApiFullArticle": tool_node_handler,
            "OfflineWikiApiBestFullArticle": tool_node_handler,
            "OfflineWikiApiTopNFullArticles": tool_node_handler,
            "OfflineWikiApiPartialArticle": tool_node_handler,

            # Other node types
            "CustomWorkflow": sub_workflow_handler,
            "ConditionalCustomWorkflow": sub_workflow_handler,
            "WorkflowLock": specialized_node_handler,
            "GetCustomFile": specialized_node_handler,
            "SaveCustomFile": specialized_node_handler,
            "ImageProcessor": specialized_node_handler,
            "StaticResponse": specialized_node_handler,
            "ArithmeticProcessor": specialized_node_handler,
            "Conditional": specialized_node_handler,
            "StringConcatenator": specialized_node_handler,
            "JsonExtractor": specialized_node_handler,
            "TagTextExtractor": specialized_node_handler,
        }

    def run_workflow(self, messages, request_id, discussionId: str = None, stream: bool = False,
                     nonResponder: bool | None = None,
                     first_node_system_prompt_override: str | None = None,
                     first_node_prompt_override: str | None = None,
                     scoped_inputs: Optional[List[str]] = None) -> Union[
        Generator[str, None, None], str, None]:
        """
        Loads the workflow configuration and delegates execution to the WorkflowProcessor.

        Args:
            messages (List[Dict[str, str]]): The conversation history.
            request_id (str): A unique identifier for the request.
            discussionId (Optional[str]): The identifier for the conversation thread. Defaults to None.
            stream (bool): If True, the response is returned as a stream. Defaults to False.
            nonResponder (Optional[bool]): If True, the workflow runs without generating a final response. Defaults to None.
            first_node_system_prompt_override (Optional[str]): A string to override the system prompt of the first node. Defaults to None.
            first_node_prompt_override (Optional[str]): A string to override the main prompt of the first node. Defaults to None.
            scoped_inputs (Optional[List[str]]): A list of inputs passed from a parent workflow. Defaults to None.

        Returns:
            Union[Generator[str, None, None], str, None]: A generator for streaming responses, a string for non-streaming responses, or None on error/no output.
        """
        workflow_id = str(uuid.uuid4())
        discussion_id = discussionId if discussionId is not None else extract_discussion_id(messages)
        remove_discussion_id_tag(messages)

        try:
            config_file = self.path_finder_func(self.workflowConfigName)
            logger.info(f"Loading workflow: {config_file}")
            with open(config_file) as f:
                loaded_json_config = json.load(f)

            # Support both dictionary-based (new) and list-based (legacy) workflow formats.
            if isinstance(loaded_json_config, dict):
                workflow_file_config = loaded_json_config
                nodes_config = workflow_file_config.get("nodes", [])
            else:
                workflow_file_config = {}
                nodes_config = loaded_json_config

            processor = WorkflowProcessor(
                node_handlers=self.node_handlers,
                llm_handler_service=self.llm_handler_service,
                workflow_variable_service=self.workflow_variable_service,
                workflow_config_name=self.workflowConfigName,
                workflow_file_config=workflow_file_config,
                configs=nodes_config,
                request_id=request_id,
                workflow_id=workflow_id,
                discussion_id=discussion_id,
                messages=messages,
                stream=stream,
                non_responder_flag=nonResponder,
                first_node_system_prompt_override=first_node_system_prompt_override,
                first_node_prompt_override=first_node_prompt_override,
                scoped_inputs=scoped_inputs
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
                if not exhaust_generator:
                    logger.warning("Non-streaming workflow returned no output.")
                    return None
                return exhaust_generator[0]

        except Exception as e:
            logger.exception("An error occurred while setting up the workflow: %s", e)
            logger.info(
                f"Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{workflow_id}' due to an error.")
            self.locking_service.delete_node_locks(instance_global_variables.INSTANCE_ID, workflow_id)
            raise
