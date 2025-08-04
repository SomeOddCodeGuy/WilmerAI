# /Middleware/workflows/handlers/base/base_workflow_node_handler.py

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class BaseHandler(ABC):
    """
    Defines the abstract base class for all workflow node handlers.

    This class establishes the common interface that all concrete node handlers
    (e.g., StandardNodeHandler, ToolNodeHandler) must implement. It ensures that
    the WorkflowProcessor can interact with any handler in a uniform way by
    calling its `handle` method. The constructor initializes shared services
    required by all handler subclasses.

    Attributes:
        workflow_manager (Any): An instance of the WorkflowManager, used for
            tasks like initiating sub-workflows.
        workflow_variable_service (Any): The service responsible for substituting
            variables (e.g., `{lastUserMessage}`) in strings.
        llm_handler (Any | None): A handler for LLM interactions, set by the
            WorkflowProcessor for each execution call.
    """
    def __init__(self, workflow_manager: Any, workflow_variable_service: Any, **kwargs):
        self.workflow_manager = workflow_manager
        self.workflow_variable_service = workflow_variable_service
        self.llm_handler = None # This will be set by WorkflowManager for each call

    @abstractmethod
    def handle(self, config: Dict, messages: List[Dict], request_id: str, workflow_id: str,
               discussion_id: str, agent_outputs: Dict, stream: bool) -> Any:
        """
        Executes the logic for a specific workflow node.

        This abstract method defines the contract for executing a node's logic.
        Each concrete handler subclass must provide its own implementation of this
        method to perform its specific task, such as calling an LLM, running a
        tool, or managing conversation memory.

        Args:
            config (Dict): The configuration dictionary for this specific node from
                the workflow JSON file.
            messages (List[Dict]): The history of the conversation, with each
                message being a role/content dictionary pair.
            request_id (str): The unique identifier for the entire incoming API
                request.
            workflow_id (str): The unique identifier for the current run of the
                workflow.
            discussion_id (str): The unique identifier for the conversation
                thread, used for stateful operations like memory.
            agent_outputs (Dict): A dictionary holding the outputs from previously
                executed nodes in the current workflow run.
            stream (bool): A flag indicating whether the output from a responder
                node should be streamed back to the client.

        Returns:
            Any: The result of the node's execution. This output is typically a
            string and is stored in `agent_outputs` for use by subsequent nodes.
        """
        pass