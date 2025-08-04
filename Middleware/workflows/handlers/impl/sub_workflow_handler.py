# /Middleware/workflows/handlers/impl/sub_workflow_handler.py
import logging
from typing import Dict, Any, List, Optional, Tuple

from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler

logger = logging.getLogger(__name__)


class SubWorkflowHandler(BaseHandler):
    """
    Handles the execution of workflow nodes that trigger other workflows.

    This handler is responsible for nodes with the types "CustomWorkflow" and
    "ConditionalCustomWorkflow". It orchestrates the initiation of a new,
    nested workflow run by calling back to the WorkflowManager.
    """

    def handle(self, config: Dict, messages: List[Dict], request_id: str, workflow_id: str,
               discussion_id: str, agent_outputs: Dict, stream: bool) -> Any:
        """
        Executes a sub-workflow node based on its type.

        This method acts as a dispatcher, reading the 'type' from the node's
        configuration and calling the appropriate handler for either a standard
        or conditional sub-workflow. The 'workflow_id' of the parent is
        intentionally not passed to the sub-workflow, which generates its own.

        Args:
            config (Dict[str, Any]): The configuration for this specific workflow node.
            messages (List[Dict[str, str]]): A list of message dictionaries representing the conversation history.
            request_id (str): The unique identifier for the originating API request.
            workflow_id (str): The ID of the parent workflow running this node.
            discussion_id (str): The unique identifier for the conversation session.
            agent_outputs (Dict[str, Any]): A dictionary of outputs from preceding nodes.
            stream (bool): Flag indicating if the response should be streamed.

        Returns:
            Any: The output of the executed sub-workflow, which could be a
                 string or a generator for streaming responses.

        Raises:
            ValueError: If the node 'type' is unknown or unsupported by this handler.
        """
        node_type = config.get("type")
        logger.debug(f"Handling sub-workflow node of type: {node_type}")

        if node_type == "CustomWorkflow":
            return self.handle_custom_workflow(config, messages, agent_outputs, stream, request_id, discussion_id)
        if node_type == "ConditionalCustomWorkflow":
            return self.handle_conditional_custom_workflow(config, messages, agent_outputs, stream, request_id,
                                                         discussion_id)

        raise ValueError(f"Unknown sub-workflow node type: {node_type}")

    def _prepare_workflow_overrides(self, config, messages, agent_outputs, stream):
        """
        Prepares configuration overrides for a sub-workflow.

        This helper method processes the node's configuration to determine responder
        status, streaming behavior, and any prompt overrides. It applies variables
        to the system and user prompt overrides if they are provided.

        Args:
            config (Dict[str, Any]): The configuration for the sub-workflow node.
            messages (List[Dict[str, str]]): The conversation history for variable substitution.
            agent_outputs (Dict[str, Any]): Outputs from previous nodes for variable substitution.
            stream (bool): The streaming flag from the parent workflow execution.

        Returns:
            tuple: A tuple containing the following four elements:
                - The resolved system prompt override (str or None).
                - The resolved user prompt override (str or None).
                - The `non_responder` flag for the sub-workflow (bool or None).
                - The final `allow_streaming` flag for the sub-workflow (bool).
        """
        is_responder = config.get("isResponder", False) or config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = stream if is_responder else False

        system_override_raw = config.get("firstNodeSystemPromptOverride", None)
        if system_override_raw not in [None, ""]:
            system_prompt = self.workflow_variable_service.apply_variables(
                system_override_raw, self.llm_handler, messages, agent_outputs, config=config
            )
        else:
            system_prompt = None

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
        Executes a statically defined sub-workflow.

        This method handles a "CustomWorkflow" node by extracting the specified
        workflow name from the config, preparing any prompt overrides, and then
        invoking the WorkflowManager to run the specified workflow.

        Args:
            config (Dict[str, Any]): The configuration for the "CustomWorkflow" node.
            messages (List[Dict[str, str]]): The conversation history.
            agent_outputs (Dict[str, Any]): Outputs from previous nodes.
            stream (bool): The streaming flag from the parent workflow.
            request_id (str): The unique identifier for the originating API request.
            discussion_id (str): The unique identifier for the conversation session.

        Returns:
            Any: The output of the executed sub-workflow.
        """
        logger.info("Custom Workflow initiated")
        workflow_name = config.get("workflowName", "No_Workflow_Name_Supplied")

        system_prompt, prompt, non_responder, allow_streaming = \
            self._prepare_workflow_overrides(config, messages, agent_outputs, stream)

        return self.workflow_manager.run_custom_workflow(
            workflow_name=workflow_name, request_id=request_id, discussion_id=discussion_id,
            messages=messages, non_responder=non_responder, is_streaming=allow_streaming,
            first_node_system_prompt_override=system_prompt, first_node_prompt_override=prompt
        )

    def handle_conditional_custom_workflow(self, config, messages, agent_outputs, stream, request_id, discussion_id):
        """
        Executes a sub-workflow chosen based on a conditional value.

        This method handles a "ConditionalCustomWorkflow" node. It resolves a
        variable 'conditionalKey' and uses its value to select a target workflow
        from a map defined in the node's configuration. It also applies any
        route-specific prompt overrides before invoking the WorkflowManager.

        Args:
            config (Dict[str, Any]): The configuration for the "ConditionalCustomWorkflow" node.
            messages (List[Dict[str, str]]): The conversation history.
            agent_outputs (Dict[str, Any]): Outputs from previous nodes.
            stream (bool): The streaming flag from the parent workflow.
            request_id (str): The unique identifier for the originating API request.
            discussion_id (str): The unique identifier for the conversation session.

        Returns:
            Any: The output of the executed sub-workflow.
        """
        logger.info("Conditional Custom Workflow initiated")
        conditional_key = config.get("conditionalKey")
        raw_key_value = self.workflow_variable_service.apply_variables(
            conditional_key, self.llm_handler, messages, agent_outputs, config=config
        ) if conditional_key else ""

        key_value = raw_key_value.strip().lower()

        workflow_map = {k.lower(): v for k, v in config.get("conditionalWorkflows", {}).items()}
        workflow_name = workflow_map.get(key_value, workflow_map.get("default", "No_Workflow_Name_Supplied"))
        logger.info(f"Resolved conditionalKey='{raw_key_value}' => workflow_name='{workflow_name}'")

        route_overrides = config.get("routeOverrides", {}).get(key_value.capitalize(), {})
        system_prompt_override = route_overrides.get("systemPromptOverride")
        prompt_override = route_overrides.get("promptOverride")

        is_responder = config.get("isResponder", False) or config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = stream if is_responder else False

        expanded_system_prompt = self.workflow_variable_service.apply_variables(
            system_prompt_override, self.llm_handler, messages, agent_outputs, config=config
        ) if system_prompt_override else None

        expanded_prompt = self.workflow_variable_service.apply_variables(
            prompt_override, self.llm_handler, messages, agent_outputs, config=config
        ) if prompt_override else None

        return self.workflow_manager.run_custom_workflow(
            workflow_name=workflow_name, request_id=request_id, discussion_id=discussion_id,
            messages=messages, non_responder=non_responder, is_streaming=allow_streaming,
            first_node_system_prompt_override=expanded_system_prompt,
            first_node_prompt_override=expanded_prompt
        )