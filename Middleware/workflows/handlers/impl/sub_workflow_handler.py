# /Middleware/workflows/handlers/impl/sub_workflow_handler.py

import logging
from typing import Any, List, Dict, Optional

from Middleware.utilities.streaming_utils import stream_static_content
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

    def _prepare_workflow_overrides(self, context: ExecutionContext, overrides_config: Optional[Dict] = None):
        """
        Prepares prompt overrides and streaming settings for a sub-workflow.

        This method correctly determines the responder and streaming flags based on the parent
        processor's decision (communicated via `context.stream`).

        Args:
            context (ExecutionContext): The current node's execution context.
            overrides_config (Optional[Dict]): An optional dictionary (e.g., from routeOverrides)
                                               to source prompt overrides from. Defaults to None.

        Returns:
            tuple: A tuple containing the resolved system prompt override, prompt override,
                   the non-responder flag, and the streaming flag.
        """
        source_config = overrides_config if overrides_config is not None else context.config

        if context.stream:
            # This node is the responder. The child workflow is allowed to stream and must produce a response.
            non_responder = None
            allow_streaming = True
        else:
            # This is a non-responder node. The child workflow cannot stream or respond.
            non_responder = True
            allow_streaming = False

        # Centralized prompt override logic
        system_override_key = "firstNodeSystemPromptOverride" if "firstNodeSystemPromptOverride" in source_config else "systemPromptOverride"
        prompt_override_key = "firstNodePromptOverride" if "firstNodePromptOverride" in source_config else "promptOverride"

        system_override_raw = source_config.get(system_override_key, None)
        system_prompt = self.workflow_variable_service.apply_variables(system_override_raw,
                                                                       context) if system_override_raw not in [None,
                                                                                                               ""] else None

        prompt_override_raw = source_config.get(prompt_override_key, None)
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
        workflow_user_folder_override = context.config.get("workflowUserFolderOverride")

        system_prompt, prompt, non_responder, allow_streaming = self._prepare_workflow_overrides(context)
        scoped_inputs = self._prepare_scoped_inputs(context)

        return self.workflow_manager.run_custom_workflow(
            workflow_name=workflow_name, request_id=context.request_id, discussion_id=context.discussion_id,
            messages=context.messages, non_responder=non_responder, is_streaming=allow_streaming,
            first_node_system_prompt_override=system_prompt, first_node_prompt_override=prompt,
            scoped_inputs=scoped_inputs,
            workflow_user_folder_override=workflow_user_folder_override
        )

    def handle_conditional_custom_workflow(self, context: ExecutionContext):
        """
        Selects and executes a sub-workflow based on a resolved conditional value. If no match is found,
        it can return default content or fall back to a default workflow.

        Args:
            context (ExecutionContext): The current node's execution context.

        Returns:
            Any: The result returned by the executed sub-workflow or the resolved default content.
        """
        logger.info("Conditional Custom Workflow initiated")

        conditional_key = context.config.get("conditionalKey")
        raw_key_value = self.workflow_variable_service.apply_variables(conditional_key,
                                                                       context) if conditional_key else ""
        key_value = raw_key_value.strip().lower()

        workflow_map = {k.lower(): v for k, v in context.config.get("conditionalWorkflows", {}).items()}
        workflow_name = workflow_map.get(key_value)

        if not workflow_name:
            # No direct match found. Check for default content before default workflow.
            default_content_template = context.config.get("UseDefaultContentInsteadOfWorkflow")

            if default_content_template is not None:
                logger.info(
                    f"No workflow match for conditionalKey='{raw_key_value}'. Using 'UseDefaultContentInsteadOfWorkflow'."
                )
                resolved_content = self.workflow_variable_service.apply_variables(
                    str(default_content_template), context
                )

                if context.stream:
                    logger.debug("Returning default content as a stream.")
                    return stream_static_content(resolved_content)
                else:
                    logger.debug("Returning default content as a single string.")
                    return resolved_content

            # No default content provided, so fall back to the default workflow.
            workflow_name = workflow_map.get("default", "No_Workflow_Name_Supplied")
            logger.info(f"No direct match for '{raw_key_value}', falling back to default workflow: '{workflow_name}'")
        else:
            logger.info(f"Resolved conditionalKey='{raw_key_value}' => workflow_name='{workflow_name}'")

        workflow_user_folder_override = context.config.get("workflowUserFolderOverride")

        # Get route overrides for the specific key
        route_overrides_map = {k.lower(): v for k, v in context.config.get("routeOverrides", {}).items()}
        route_overrides = route_overrides_map.get(key_value, {})

        system_prompt, prompt, non_responder, allow_streaming = self._prepare_workflow_overrides(
            context, overrides_config=route_overrides
        )

        scoped_inputs = self._prepare_scoped_inputs(context)

        return self.workflow_manager.run_custom_workflow(
            workflow_name=workflow_name,
            request_id=context.request_id,
            discussion_id=context.discussion_id,
            messages=context.messages,
            non_responder=non_responder,
            is_streaming=allow_streaming,
            first_node_system_prompt_override=system_prompt,
            first_node_prompt_override=prompt,
            scoped_inputs=scoped_inputs,
            workflow_user_folder_override=workflow_user_folder_override
        )
