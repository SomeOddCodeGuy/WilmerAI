# /Middleware/workflows/processors/workflow_processor.py

import logging
import time
from copy import deepcopy
from typing import Dict, List, Generator, Any, Optional

from Middleware.common import instance_global_variables
from Middleware.common.constants import VALID_NODE_TYPES
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService
from Middleware.services.locking_service import LockingService
from Middleware.services.timestamp_service import TimestampService
from Middleware.utilities.config_utils import get_chat_template_name, get_endpoint_config
from Middleware.utilities.streaming_utils import post_process_llm_output
from Middleware.workflows.models.execution_context import ExecutionContext
from Middleware.workflows.streaming.response_handler import StreamingResponseHandler

# Avoids circular import for type hinting
if False:
    from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager

logger = logging.getLogger(__name__)


class WorkflowProcessor:
    """
    Processes a pre-configured workflow by executing its nodes sequentially.

    This class iterates through the nodes defined in a workflow configuration,
    creates a specific `ExecutionContext` for each node, and dispatches it
    to the appropriate handler for execution. It manages the workflow state,
    including outputs from previous nodes, and handles both streaming and
    non-streaming responses.
    """

    def __init__(self,
                 node_handlers: Dict[str, Any],
                 llm_handler_service: LlmHandlerService,
                 workflow_variable_service: 'WorkflowVariableManager',
                 workflow_config_name: str,
                 workflow_file_config: Dict[str, Any],
                 configs: List[Dict],
                 request_id: str,
                 workflow_id: str,
                 discussion_id: str,
                 messages: List[Dict],
                 stream: bool,
                 non_responder_flag: bool,
                 first_node_system_prompt_override: str,
                 first_node_prompt_override: str,
                 scoped_inputs: Optional[List[str]] = None
                 ):
        """
        Initializes the WorkflowProcessor instance.

        Args:
            node_handlers (Dict[str, Any]): A dictionary mapping node type strings to their handler instances.
            llm_handler_service (LlmHandlerService): Service for creating LLM handler instances.
            workflow_variable_service (WorkflowVariableManager): Service for resolving dynamic variables.
            workflow_config_name (str): The name of the workflow configuration being executed.
            workflow_file_config (Dict[str, Any]): The entire workflow JSON configuration file as a dictionary.
            configs (List[Dict]): The list of node configurations (the "nodes" array from the workflow).
            request_id (str): The unique identifier for the current request.
            workflow_id (str): The unique identifier for the current workflow execution.
            discussion_id (str): The identifier for the conversation history.
            messages (List[Dict]): The list of messages in the current conversation.
            stream (bool): A flag indicating whether the final response should be streamed.
            non_responder_flag (bool): A flag related to response generation logic.
            first_node_system_prompt_override (str): An optional system prompt to override the first node's prompt.
            first_node_prompt_override (str): An optional user prompt to override the first node's prompt.
            scoped_inputs (Optional[List[str]]): A list of inputs passed from a parent workflow, if any.
        """
        self.node_handlers = node_handlers
        self.llm_handler_service = llm_handler_service
        self.workflow_variable_service = workflow_variable_service
        self.locking_service = LockingService()
        self.timestamp_service = TimestampService()

        self.workflow_config_name = workflow_config_name
        self.workflow_file_config = workflow_file_config
        self.configs = configs
        self.request_id = request_id
        self.workflow_id = workflow_id
        self.discussion_id = discussion_id
        self.messages = messages
        self.stream = stream
        self.non_responder_flag = non_responder_flag
        self.first_node_system_prompt_override = first_node_system_prompt_override
        self.first_node_prompt_override = first_node_prompt_override

        # Process scoped inputs into agent_inputs dictionary
        self.agent_inputs = {}
        if scoped_inputs:
            for i, value in enumerate(scoped_inputs):
                self.agent_inputs[f"agent{i + 1}Input"] = value
        logger.debug(f"Initialized WorkflowProcessor with agent inputs: {self.agent_inputs}")

        self.llm_handler = None
        self.override_first_available_prompts = (
                self.first_node_system_prompt_override is not None or
                self.first_node_prompt_override is not None
        )

    def execute(self) -> Generator[Any, None, None]:
        """
        Executes the main workflow logic by processing nodes sequentially.

        This method iterates through each node configuration, processes it using
        the `_process_section` helper, and manages state by passing outputs
        from one node to subsequent nodes. It handles the final response
        generation, yielding results for either streaming or non-streaming cases.

        Returns:
            Generator[Any, None, None]: A generator that yields the final response.
                                        For streaming, it yields SSE events. For non-streaming,
                                        it yields a single string.
        """
        returned_to_user = False
        agent_outputs = {}
        start_time = time.perf_counter()

        try:
            for idx, config in enumerate(self.configs):
                logger.info(
                    f'------Workflow {self.workflow_config_name}; step {idx}; node type: {config.get("type", "Standard")}')

                if "systemPrompt" in config or "prompt" in config:
                    if self.override_first_available_prompts:
                        if self.first_node_system_prompt_override is not None:
                            config["systemPrompt"] = self.first_node_system_prompt_override
                        if self.first_node_prompt_override is not None:
                            config["prompt"] = self.first_node_prompt_override
                        self.override_first_available_prompts = False

                # Combine persistent agent_inputs with transient agent_outputs
                # This makes {agent1Input}, {agent2Input}, etc. available to the node
                # alongside the outputs from previous nodes in *this* workflow.
                combined_agent_variables = {**self.agent_inputs, **agent_outputs}

                if not returned_to_user and (config.get('returnToUser', False) or idx == len(self.configs) - 1):
                    returned_to_user = True
                    logger.debug("Executing a responding node flow.")

                    result_gen = self._process_section(
                        config=config, agent_outputs=combined_agent_variables,
                        is_responding_node=True
                    )

                    # Streaming logic is now centralized here
                    if self.stream and isinstance(result_gen, Generator):
                        endpoint_name = config.get("endpointName")
                        endpoint_config = get_endpoint_config(endpoint_name) if endpoint_name else {}
                        # Pass both endpoint and node config to the handler
                        stream_handler = StreamingResponseHandler(endpoint_config, config)

                        yield from stream_handler.process_stream(result_gen)

                        result = stream_handler.full_response_text
                        logger.info("\n\nOutput from the LLM: %s", result)
                    else:
                        result = result_gen
                        yield result

                    agent_outputs[f'agent{idx + 1}Output'] = result
                else:
                    logger.debug("Executing a non-responding node flow.")
                    result = self._process_section(
                        config=config, agent_outputs=combined_agent_variables,
                        is_responding_node=False
                    )
                    agent_outputs[f'agent{idx + 1}Output'] = result

        except EarlyTerminationException:
            logger.info(
                f"Terminating workflow early. Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{self.workflow_id}'")
            raise
        finally:
            end_time = time.perf_counter()
            logger.info(f"Execution time: {end_time - start_time:.2f} seconds")
            logger.info(
                f"Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{self.workflow_id}'")
            self.locking_service.delete_node_locks(instance_global_variables.INSTANCE_ID, self.workflow_id)

    def _process_section(self, config: Dict, agent_outputs: Dict, is_responding_node: bool):
        """
        Processes a single node of the workflow.

        This method prepares the LLM handler, creates the comprehensive `ExecutionContext`
        for the current node, finds the correct node handler based on the node's type,
        and dispatches the context to that handler for execution.

        Args:
            config (Dict): The configuration for the specific node being processed.
            agent_outputs (Dict): A dictionary containing outputs from all previous nodes
                                  in the current workflow execution, as well as any inputs
                                  from a parent workflow.
            is_responding_node (bool): A flag indicating if this node is responsible for
                                       generating the final user-facing response.

        Returns:
            Any: The result returned by the node's handler. This could be a string
                 or a generator for streaming responses.
        """
        is_streaming_for_node = self.stream and is_responding_node
        endpoint_config = {}

        # 1. Determine the LLM Handler for this specific node
        if "endpointName" in config and config.get("endpointName"):
            endpoint_name = config["endpointName"]
            endpoint_config = get_endpoint_config(endpoint_name)
            preset = config.get("preset")
            add_user_prompt = config.get('addUserTurnTemplate', False)
            force_gen_prompt = config.get('forceGenerationPromptIfEndpointAllows', False)
            block_gen_prompt = config.get('blockGenerationPrompt', False)

            add_generation_prompt = None
            if is_responding_node:
                if (
                        self.non_responder_flag is None and not force_gen_prompt and not add_user_prompt) or block_gen_prompt:
                    add_generation_prompt = False
            else:
                if (not force_gen_prompt and not add_user_prompt) or block_gen_prompt:
                    add_generation_prompt = False

            self.llm_handler = self.llm_handler_service.load_model_from_config(
                endpoint_name, preset, is_streaming_for_node,
                config.get("maxContextTokenSize", 4096),
                config.get("maxResponseSizeInTokens", 400),
                addGenerationPrompt=add_generation_prompt
            )
        else:
            # Provide a default, non-functional handler if no endpoint is specified
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)

        # 2. Prepare the messages payload, adding timestamps if required
        messages_to_send = self.messages
        if is_responding_node and self.discussion_id and config.get("addDiscussionIdTimestampsForLLM", False):
            if self.non_responder_flag is None:
                logger.debug("Adding timestamps to messages for LLM.")
                use_relative = config.get("useRelativeTimestamps", False)
                messages_to_send = self.timestamp_service.track_message_timestamps(
                    messages=deepcopy(self.messages),
                    discussion_id=self.discussion_id,
                    use_relative_time=use_relative
                )

        # 3. Create the unified ExecutionContext object
        context = ExecutionContext(
            request_id=self.request_id,
            workflow_id=self.workflow_id,
            discussion_id=self.discussion_id,
            config=config,
            workflow_config=self.workflow_file_config,
            messages=messages_to_send,
            stream=is_streaming_for_node,
            agent_inputs=self.agent_inputs,
            # This contains both parent inputs and prior sibling outputs
            agent_outputs=agent_outputs,
            llm_handler=self.llm_handler,
            workflow_variable_service=self.workflow_variable_service,
            # Get the manager instance from a handler that is guaranteed to have it.
            # This is used for sub-workflow calls.
            workflow_manager=self.node_handlers.get("CustomWorkflow").workflow_manager,
            node_handlers=self.node_handlers
        )

        # 4. Find and dispatch to the correct handler
        node_type = context.config.get("type", "Standard")
        if node_type not in VALID_NODE_TYPES:
            logger.warning(f"Config Type: '{node_type}' is not a valid node type. Defaulting to 'Standard'.")
            node_type = "Standard"

        handler = self.node_handlers.get(node_type)
        if not handler:
            raise ValueError(f"No handler found for node type: {node_type}")

        # The handler's llm_handler instance is set from the context for this specific call
        handler.llm_handler = context.llm_handler
        result = handler.handle(context)

        # 5. Apply centralized post-processing for non-streaming results
        if not is_streaming_for_node and isinstance(result, str) and endpoint_config:
            result = post_process_llm_output(result, endpoint_config, config)

        return result
