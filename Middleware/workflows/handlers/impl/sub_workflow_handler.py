# /Middleware/workflows/handlers/impl/sub_workflow_handler.py

import logging
from typing import Any, List

from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class SubWorkflowHandler(BaseHandler):
    """
    Handles workflow nodes that trigger the execution of other sub-workflows.
    """

    def _prepare_scoped_inputs(self, context: ExecutionContext) -> List[str]:
        """
        Resolves placeholder variables passed as inputs to a sub-workflow.

        Args:
            context (ExecutionContext): The current node's execution context, containing configuration and state.

        Returns:
            List[str]: A list of resolved variable values to be used as inputs for the sub-workflow.
        """
        resolved_inputs = []
        scoped_variables = context.config.get("scoped_variables") or []
        for var_string in scoped_variables:
            resolved_value = self.workflow_variable_service.apply_variables(str(var_string), context)
            resolved_inputs.append(resolved_value)
        return resolved_inputs

    def handle(self, context: ExecutionContext) -> Any:
        """
        Routes the execution to the appropriate handler based on the sub-workflow node's type.

        Args:
            context (ExecutionContext): The current node's execution context.

        Returns:
            Any: The result returned by the executed sub-workflow.
        """
        node_type = context.config.get("type")
        logger.debug(f"Handling sub-workflow node of type: {node_type}")

        if node_type == "CustomWorkflow":
            return self.handle_custom_workflow(context)
        if node_type == "ConditionalCustomWorkflow":
            return self.handle_conditional_custom_workflow(context)

        raise ValueError(f"Unknown sub-workflow node type: {node_type}")

    def _prepare_workflow_overrides(self, context: ExecutionContext):
        """
        Prepares prompt overrides and streaming settings for a sub-workflow.

        Args:
            context (ExecutionContext): The current node's execution context.

        Returns:
            tuple: A tuple containing the resolved system prompt override, prompt override,
                   the non-responder flag, and the streaming flag.
        """
        is_responder = context.config.get("isResponder", False) or context.config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = context.stream if is_responder else False

        system_override_raw = context.config.get("firstNodeSystemPromptOverride", None)
        system_prompt = self.workflow_variable_service.apply_variables(system_override_raw,
                                                                       context) if system_override_raw not in [None,
                                                                                                               ""] else None

        prompt_override_raw = context.config.get("firstNodePromptOverride", None)
        prompt = self.workflow_variable_service.apply_variables(prompt_override_raw,
                                                                context) if prompt_override_raw not in [None,
                                                                                                        ""] else None

        return system_prompt, prompt, non_responder, allow_streaming

    def handle_custom_workflow(self, context: ExecutionContext):
        """
        Executes a sub-workflow with a statically defined name from the node configuration.

        Args:
            context (ExecutionContext): The current node's execution context.

        Returns:
            Any: The result returned by the executed sub-workflow.
        """
        logger.info("Custom Workflow initiated")
        workflow_name = context.config.get("workflowName", "No_Workflow_Name_Supplied")

        system_prompt, prompt, non_responder, allow_streaming = self._prepare_workflow_overrides(context)
        scoped_inputs = self._prepare_scoped_inputs(context)

        return self.workflow_manager.run_custom_workflow(
            workflow_name=workflow_name, request_id=context.request_id, discussion_id=context.discussion_id,
            messages=context.messages, non_responder=non_responder, is_streaming=allow_streaming,
            first_node_system_prompt_override=system_prompt, first_node_prompt_override=prompt,
            scoped_inputs=scoped_inputs
        )

    def handle_conditional_custom_workflow(self, context: ExecutionContext):
        """
        Selects and executes a sub-workflow based on a resolved conditional value.

        Args:
            context (ExecutionContext): The current node's execution context.

        Returns:
            Any: The result returned by the executed sub-workflow.
        """
        logger.info("Conditional Custom Workflow initiated")
        conditional_key = context.config.get("conditionalKey")
        raw_key_value = self.workflow_variable_service.apply_variables(conditional_key,
                                                                       context) if conditional_key else ""
        key_value = raw_key_value.strip().lower()

        workflow_map = {k.lower(): v for k, v in context.config.get("conditionalWorkflows", {}).items()}
        workflow_name = workflow_map.get(key_value, workflow_map.get("default", "No_Workflow_Name_Supplied"))
        logger.info(f"Resolved conditionalKey='{raw_key_value}' => workflow_name='{workflow_name}'")

        route_overrides = context.config.get("routeOverrides", {}).get(key_value.capitalize(), {})
        system_prompt_override = route_overrides.get("systemPromptOverride")
        prompt_override = route_overrides.get("promptOverride")

        is_responder = context.config.get("isResponder", False) or context.config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = context.stream if is_responder else False

        scoped_inputs = self._prepare_scoped_inputs(context)

        expanded_system_prompt = self.workflow_variable_service.apply_variables(
            system_prompt_override, context) if system_prompt_override else None

        expanded_prompt = self.workflow_variable_service.apply_variables(prompt_override,
                                                                         context) if prompt_override else None

        return self.workflow_manager.run_custom_workflow(
            workflow_name=workflow_name, request_id=context.request_id, discussion_id=context.discussion_id,
            messages=context.messages, non_responder=non_responder, is_streaming=allow_streaming,
            first_node_system_prompt_override=expanded_system_prompt,
            first_node_prompt_override=expanded_prompt,
            scoped_inputs=scoped_inputs
        )
