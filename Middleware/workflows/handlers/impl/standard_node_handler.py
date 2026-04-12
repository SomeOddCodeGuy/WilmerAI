import logging
from typing import Any

from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class StandardNodeHandler(BaseHandler):
    """
    Handles the execution of 'Standard' type nodes within a workflow.

    This handler processes nodes that represent a standard interaction with a
    Large Language Model. It delegates the core task of calling the LLM to the
    LLMDispatchService.
    """

    def handle(self, context: ExecutionContext) -> Any:
        """
        Executes the logic for a 'Standard' node using the LLM dispatch service.

        Args:
            context (ExecutionContext): The context object containing all state
                                        for this node's execution.

        Returns:
            Any: The response from the LLM, which may be a string or a generator
                 for streaming responses.
        """
        logger.debug("Handling 'Standard' node.")
        accept_images = context.config.get("acceptImages", False)
        max_images = context.config.get("maxImagesToSend", 0) if accept_images else 0
        return LLMDispatchService.dispatch(
            context=context,
            llm_takes_images=accept_images,
            max_images=max_images
        )
