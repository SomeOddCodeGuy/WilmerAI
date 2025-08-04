import logging
from typing import Dict, Any, List

from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler

logger = logging.getLogger(__name__)


class StandardNodeHandler(BaseHandler):
    """
    Handles the execution of 'Standard' type nodes within a workflow.

    This handler is responsible for processing workflow nodes that represent a
    standard interaction with a Large Language Model. It uses the
    LLMDispatchService to format prompts, apply variables, and send the
    final request to the configured LLM endpoint.
    """

    def handle(self, config: Dict, messages: List[Dict], request_id: str, workflow_id: str,
               discussion_id: str, agent_outputs: Dict, stream: bool) -> Any:
        """
        Executes the logic for a 'Standard' node by calling the LLM dispatch service.

        This method takes the node's configuration and the current conversation
        state, then delegates the task of preparing prompts and communicating
        with the LLM to the LLMDispatchService. It conforms to the BaseHandler
        interface, accepting all standard workflow parameters.

        Args:
            config (Dict): The configuration for this specific 'Standard' node,
                loaded from the workflow's JSON file.
            messages (List[Dict]): The history of the conversation, where each
                entry is a dictionary with 'role' and 'content'.
            request_id (str): A unique identifier for the overall incoming API request.
            workflow_id (str): The name or ID of the parent workflow being executed.
            discussion_id (str): The unique ID for the ongoing conversation, used for
                retrieving context and managing memory.
            agent_outputs (Dict): A dictionary holding the outputs of prior nodes
                in the current workflow run.
            stream (bool): A flag indicating if the response should be streamed.
                This is part of the handler's interface contract.

        Returns:
            Any: The response from the LLM, which may be a single object or a
                 generator for streaming responses.
        """
        logger.debug("Handling 'Standard' node.")

        return LLMDispatchService.dispatch(
            llm_handler=self.llm_handler,
            workflow_variable_service=self.workflow_variable_service,
            config=config,
            messages=messages,
            agent_outputs=agent_outputs
        )