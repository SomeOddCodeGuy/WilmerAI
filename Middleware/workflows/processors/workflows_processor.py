# /Middleware/workflows/processors/workflow_processor.py

import logging
import time
from copy import deepcopy
from typing import Dict, List, Generator, Any

from Middleware.common.constants import VALID_NODE_TYPES
from Middleware.api import api_helpers
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService
from Middleware.common import instance_global_variables
from Middleware.services.locking_service import LockingService
from Middleware.services.timestamp_service import TimestampService
from Middleware.utilities.config_utils import get_chat_template_name

# Avoids circular import for type hinting
if False:
    from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager

logger = logging.getLogger(__name__)


class WorkflowProcessor:
    """
    Processes a pre-configured workflow by executing its nodes sequentially.

    This class acts as the core engine for a single workflow run. It takes the
    parsed workflow configuration and all necessary dependencies, then iterates
    through each node, delegating execution to the appropriate handler. It manages
    the state of the run, including agent outputs and streaming responses.
    """
    def __init__(self,
                 node_handlers: Dict[str, Any],
                 llm_handler_service: LlmHandlerService,
                 workflow_variable_service: 'WorkflowVariableManager',
                 workflow_config_name: str,
                 configs: List[Dict],
                 request_id: str,
                 workflow_id: str,
                 discussion_id: str,
                 messages: List[Dict],
                 stream: bool,
                 non_responder_flag: bool,
                 first_node_system_prompt_override: str,
                 first_node_prompt_override: str
                 ):
        """
        Initializes the WorkflowProcessor instance.

        Sets up the processor with all necessary services, configurations, and
        request-specific data required to execute a complete workflow.

        Args:
            node_handlers (Dict[str, Any]): A dictionary mapping node type names
                (e.g., "Standard", "Tool") to their handler instances.
            llm_handler_service (LlmHandlerService): The service used for loading
                and managing LLM API handlers.
            workflow_variable_service (WorkflowVariableManager): The service that
                manages variables shared across different nodes in the workflow.
            workflow_config_name (str): The name of the workflow configuration being executed.
            configs (List[Dict]): A list of dictionaries, where each dictionary
                is the configuration for a single node in the workflow.
            request_id (str): A unique identifier for the incoming API request.
            workflow_id (str): A unique identifier for this specific workflow execution instance.
            discussion_id (str): An identifier for the conversation, used to link
                related interactions for memory and context.
            messages (List[Dict]): The list of message objects (role/content pairs)
                representing the current conversation history.
            stream (bool): A flag indicating whether the final response to the user
                should be streamed.
            non_responder_flag (bool): Specifies that a node is a non-responder, meaning
            its output will not be sent to the user. Only responder nodes get their output
            sent to the user.
            first_node_system_prompt_override (str): An optional string to override
                the system prompt of the first node that has one.
            first_node_prompt_override (str): An optional string to override the
                user prompt of the first node that has one.
        """
        self.node_handlers = node_handlers
        self.llm_handler_service = llm_handler_service
        self.workflow_variable_service = workflow_variable_service
        self.locking_service = LockingService()
        self.timestamp_service = TimestampService()

        self.workflow_config_name = workflow_config_name
        self.configs = configs
        self.request_id = request_id
        self.workflow_id = workflow_id
        self.discussion_id = discussion_id
        self.messages = messages
        self.stream = stream
        self.non_responder_flag = non_responder_flag
        self.first_node_system_prompt_override = first_node_system_prompt_override
        self.first_node_prompt_override = first_node_prompt_override

        self.llm_handler = None
        self.override_first_available_prompts = (
                self.first_node_system_prompt_override is not None and
                self.first_node_prompt_override is not None
        )

    def execute(self) -> Generator[Any, None, None]:
        """
        Executes the main workflow logic by processing nodes sequentially.

        This generator method iterates through the configured nodes in the workflow.
        It identifies the node designated to respond to the user, processes it
        accordingly (streaming or non-streaming), and passes its output back.
        Outputs from non-responding nodes are stored for use by subsequent nodes.
        Finally, it ensures resources like locks are cleaned up.

        Returns:
            Generator[Any, None, None]: A generator that yields the response. For a
                streaming request, this will be a series of response chunks. For a
                non-streaming request, it will yield a single, complete response object.

        Raises:
            EarlyTerminationException: If the workflow is intentionally terminated
                before completion by a node handler.
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

                if not returned_to_user and (config.get('returnToUser', False) or idx == len(self.configs) - 1):
                    returned_to_user = True
                    logger.debug("Executing a responding node flow.")

                    result_gen = self._process_section(
                        config=config, agent_outputs=agent_outputs,
                        is_responding_node=True
                    )

                    if self.stream and isinstance(result_gen, Generator):
                        text_chunks = []
                        for chunk in result_gen:
                            extracted_text = api_helpers.extract_text_from_chunk(chunk)
                            if extracted_text:
                                text_chunks.append(extracted_text)
                            yield chunk
                        result = ''.join(text_chunks)
                        logger.info("\n\nOutput from the LLM: %s", result)
                    else:
                        result = result_gen
                        yield result

                    agent_outputs[f'agent{idx + 1}Output'] = result
                else:
                    logger.debug("Executing a non-responding node flow.")
                    result = self._process_section(
                        config=config, agent_outputs=agent_outputs,
                        is_responding_node=False
                    )
                    agent_outputs[f'agent{idx + 1}Output'] = result

        except EarlyTerminationException:
            logger.info(f"Terminating workflow early. Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{self.workflow_id}'")
            raise
        finally:
            end_time = time.perf_counter()
            logger.info(f"Execution time: {end_time - start_time:.2f} seconds")
            logger.info(f"Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{self.workflow_id}'")
            self.locking_service.delete_node_locks(instance_global_variables.INSTANCE_ID, self.workflow_id)

    def _process_section(self, config: Dict, agent_outputs: Dict, is_responding_node: bool):
        """
        Processes a single node (section) of the workflow.

        This method selects the appropriate handler for a given workflow node based on
        its 'type' in the configuration. It prepares the necessary components, such
        as the LLM handler and the message list, before invoking the node handler
        to perform its specific task.

        Args:
            config (Dict): The configuration dictionary for the specific node.
            agent_outputs (Dict): A dictionary containing outputs from previously
                executed nodes, accessible via keys like 'agent1Output'.
            is_responding_node (bool): A flag indicating if this node's output is
                intended to be sent directly to the user.

        Returns:
            Any: The result from the executed node handler. This could be a text
                string, a dictionary, or a generator if the node is streaming.

        Raises:
            ValueError: If no handler is found for the node type specified in the
                node's configuration.
        """
        is_streaming_for_node = self.stream and is_responding_node

        if "endpointName" in config and config.get("endpointName"):
            preset = config.get("preset")
            add_user_prompt = config.get('addUserTurnTemplate', False)
            force_gen_prompt = config.get('forceGenerationPromptIfEndpointAllows', False)
            block_gen_prompt = config.get('blockGenerationPrompt', False)
            add_generation_prompt = None

            if is_responding_node:
                if (self.non_responder_flag is None and not force_gen_prompt and not add_user_prompt) or block_gen_prompt:
                    add_generation_prompt = False
            else:
                if (not force_gen_prompt and not add_user_prompt) or block_gen_prompt:
                    add_generation_prompt = False

            self.llm_handler = self.llm_handler_service.load_model_from_config(
                config["endpointName"], preset, is_streaming_for_node,
                config.get("maxContextTokenSize", 4096),
                config.get("maxResponseSizeInTokens", 400),
                addGenerationPrompt=add_generation_prompt
            )
        else:
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)

        messages_to_send = self.messages
        if is_responding_node and self.discussion_id and config.get("addDiscussionIdTimestampsForLLM", False):
            if self.non_responder_flag is None:
                logger.debug("Adding timestamps to messages for LLM.")
                messages_to_send = self.timestamp_service.track_message_timestamps(messages=deepcopy(self.messages), discussion_id=self.discussion_id)

        node_type = config.get("type", "Standard")
        if node_type not in VALID_NODE_TYPES:
            logger.warning(f"Config Type: '{node_type}' is not a valid node type. Defaulting to 'Standard'.")
            node_type = "Standard"

        handler = self.node_handlers.get(node_type)
        if not handler:
            raise ValueError(f"No handler found for node type: {node_type}")

        handler.llm_handler = self.llm_handler

        return handler.handle(
            config=config,
            messages=messages_to_send,
            request_id=self.request_id,
            workflow_id=self.workflow_id,
            discussion_id=self.discussion_id,
            agent_outputs=agent_outputs,
            stream=is_streaming_for_node
        )