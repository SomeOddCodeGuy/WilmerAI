# /Middleware/workflows/handlers/base/base_workflow_node_handler.py

import logging
from abc import ABC, abstractmethod
from typing import Any

from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class BaseHandler(ABC):
    """
    Defines the abstract base class for all workflow node handlers.

    This class establishes the common interface that all concrete node handlers
    (e.g., StandardNodeHandler, ToolNodeHandler) must implement. It ensures that
    the WorkflowProcessor can interact with any handler in a uniform way by
    calling its `handle` method.
    """

    def __init__(self, workflow_manager: Any, workflow_variable_service: Any, **kwargs):
        """
        Initializes the handler with shared, common services.

        Args:
            workflow_manager (Any): An instance of the WorkflowManager, used for
                tasks like initiating sub-workflows.
            workflow_variable_service (Any): The service responsible for
                substituting variables (e.g., `{lastUserMessage}`) in strings.
        """
        self.workflow_manager = workflow_manager
        self.workflow_variable_service = workflow_variable_service
        self.llm_handler = None

    @abstractmethod
    def handle(self, context: ExecutionContext) -> Any:
        """
        Executes the logic for a specific node type using the provided context.

        Args:
            context (ExecutionContext): The runtime context object containing all
                data and services needed for execution.

        Returns:
            Any: The result of the node's execution.
        """
        pass
