# Middleware/workflows/processors/workflows_processor.py

import json
import logging
import time
from copy import deepcopy
from typing import Dict, List, Generator, Any, Optional

from Middleware.common import instance_global_variables
from Middleware.common.constants import VALID_NODE_TYPES
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.cancellation_service import cancellation_service
from Middleware.services.llm_service import LlmHandlerService
from Middleware.services.locking_service import LockingService
from Middleware.services.timestamp_service import TimestampService
from Middleware.utilities.config_utils import get_chat_template_name, get_endpoint_config
from Middleware.utilities.encryption_utils import get_encryption_key_if_available, get_api_key_hash_if_available
from Middleware.utilities.sensitive_logging_utils import sensitive_log, log_prompt_content
from Middleware.utilities.streaming_utils import post_process_llm_output
from Middleware.workflows.models.execution_context import ExecutionContext, NodeExecutionInfo
from Middleware.workflows.streaming.response_handler import StreamingResponseHandler

# Avoids circular import for type hinting
if False:
    from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager

logger = logging.getLogger(__name__)


class WorkflowProcessor:
    """
    Processes a pre-configured workflow by executing its nodes sequentially.
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
                 non_responder_flag: Optional[bool],
                 first_node_system_prompt_override: Optional[str],
                 first_node_prompt_override: Optional[str],
                 scoped_inputs: Optional[List[str]] = None,
                 api_key: Optional[str] = None,
                 tools: Optional[List[Dict]] = None,
                 tool_choice: Optional[Any] = None
                 ):
        """
        Initializes the WorkflowProcessor instance.

        Args:
            node_handlers (Dict[str, Any]): Map of node type names to their handler instances.
            llm_handler_service (LlmHandlerService): Service for loading LLM handler configurations.
            workflow_variable_service (WorkflowVariableManager): Service for resolving workflow variables.
            workflow_config_name (str): The name of the workflow configuration file.
            workflow_file_config (Dict[str, Any]): The top-level workflow file configuration (may contain workflow-level settings).
            configs (List[Dict]): The list of node configuration dictionaries to execute.
            request_id (str): A unique identifier for the incoming request.
            workflow_id (str): A unique identifier for this workflow execution.
            discussion_id (str): The identifier for the conversation thread.
            messages (List[Dict]): The conversation history in the internal message format.
            stream (bool): If True, the responding node streams its output.
            non_responder_flag (Optional[bool]): If True, the workflow runs without generating a final response.
            first_node_system_prompt_override (Optional[str]): Override for the first node's system prompt.
            first_node_prompt_override (Optional[str]): Override for the first node's main prompt.
            scoped_inputs (Optional[List[str]]): Inputs passed from a parent workflow, mapped to agent#Input variables.
            api_key (Optional[str]): The API key from the request, used for encryption context.
            tools (Optional[List[Dict]]): Tool definitions from the incoming request.
            tool_choice (Optional[Any]): Tool selection policy from the incoming request.
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
        self.api_key = api_key
        self.encryption_key = get_encryption_key_if_available(api_key) if api_key else None
        self.api_key_hash = get_api_key_hash_if_available(api_key) if api_key else None
        self.tools = tools
        self.tool_choice = tool_choice

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

    def _identify_generation_prompt(self) -> Optional[str]:
        """
        Heuristic check to identify if the last message in the input history
        is a generation prompt (e.g., "CharacterName:").
        """
        if not self.messages:
            return None
        last_message = self.messages[-1]
        content = last_message.get('content', '').strip()
        if 0 < len(content) < 100 and content.endswith(':'):
            sensitive_log(logger, logging.DEBUG, "Detected potential generation prompt in input messages: '%s'", content)
            return content
        return None

    def _reconstruct_non_streaming(self, llm_output: str, generation_prompt: str) -> str:
        """
        Applies group chat reconstruction logic for non-streaming responses.
        """
        if not isinstance(llm_output, str):
            return llm_output
        llm_output_trimmed = llm_output.lstrip()
        if not llm_output_trimmed:
            return f"{generation_prompt} "
        first_word = llm_output_trimmed.split(' ', 1)[0]
        if first_word.endswith(':'):
            return llm_output_trimmed
        sensitive_log(logger, logging.DEBUG, "Reconstructing non-streaming group chat message. Prepended prompt: '%s'", generation_prompt)
        return f"{generation_prompt} {llm_output_trimmed}"

    def _get_node_name(self, config: Dict) -> str:
        """
        Extracts the display name for a node from its configuration.

        Prefers 'title', then 'agentName', otherwise returns 'N/A'.
        For CustomWorkflow nodes, appends ' -> WorkflowName'.
        For ConditionalCustomWorkflow nodes, appends ' -> [WF1, WF2, ...]' showing
        possible workflow destinations (truncated to first 2 if more than 3).

        Args:
            config: The node configuration dictionary containing 'title', 'agentName',
                    'type', 'workflowName', or 'conditionalWorkflows' fields.

        Returns:
            A display string for the node, suitable for logging summaries.
        """
        title = config.get("title")
        if title:
            base_name = title
        else:
            agent_name = config.get("agentName")
            if agent_name:
                base_name = agent_name
            else:
                base_name = "N/A"

        # For sub-workflow nodes, append the workflow name for easier correlation
        node_type = config.get("type", "Standard")
        if node_type == "CustomWorkflow":
            workflow_name = config.get("workflowName")
            if workflow_name:
                return f"{base_name} -> {workflow_name}"
        elif node_type == "ConditionalCustomWorkflow":
            # For conditional workflows, show the possible workflow destinations
            conditional_workflows = config.get("conditionalWorkflows", {})
            if conditional_workflows:
                workflow_names = list(conditional_workflows.values())
                if len(workflow_names) <= 3:
                    return f"{base_name} -> [{', '.join(workflow_names)}]"
                else:
                    return f"{base_name} -> [{', '.join(workflow_names[:2])}, +{len(workflow_names)-2} more]"

        return base_name

    def _get_endpoint_details(self, config: Dict) -> tuple:
        """
        Extracts endpoint name and URL from the node configuration.

        Resolves variable substitution in endpoint names (e.g., '{agent1#Output}')
        before looking up the endpoint configuration.

        Args:
            config: The node configuration dictionary, expected to contain 'endpointName'.

        Returns:
            A tuple of (endpoint_name, endpoint_url). Both values are 'N/A' if no
            endpoint is configured or if the endpoint configuration cannot be loaded.
        """
        endpoint_name_template = config.get("endpointName")
        if not endpoint_name_template:
            return "N/A", "N/A"

        # Resolve endpoint name if it contains variables
        if '{' in endpoint_name_template or '{{' in endpoint_name_template:
            endpoint_name = self.workflow_variable_service.apply_early_variables(
                endpoint_name_template,
                agent_inputs=self.agent_inputs,
                workflow_config=self.workflow_file_config
            )
        else:
            endpoint_name = endpoint_name_template

        # Get endpoint config to extract URL
        try:
            endpoint_config = get_endpoint_config(endpoint_name)
            endpoint_url = endpoint_config.get("endpoint", "N/A")
        except Exception:
            endpoint_url = "N/A"

        return endpoint_name, endpoint_url

    def _log_node_execution_summary(self, node_execution_infos: List['NodeExecutionInfo']) -> None:
        """
        Logs a summary of all node executions in the workflow at INFO level.

        Outputs a formatted summary showing each node's index, type, name,
        endpoint details, and execution time. The summary is bracketed by
        header and footer lines containing the workflow name.

        Args:
            node_execution_infos: List of NodeExecutionInfo objects containing
                                  execution details for each processed node.
        """
        if not node_execution_infos:
            return

        logger.info(f"=== Workflow Node Execution Summary: {self.workflow_config_name} ===")
        for info in node_execution_infos:
            logger.info(str(info))
        logger.info(f"=== End of Summary: {self.workflow_config_name} ===")

    def execute(self) -> Generator[Any, None, None]:
        """
        Executes the main workflow logic by processing nodes sequentially.
        """
        returned_to_user = False
        agent_outputs = {}
        start_time = time.perf_counter()
        node_execution_infos: List[NodeExecutionInfo] = []

        # Pre-scan all nodes to see if any of them will use timestamping.
        is_any_node_timestamped = False
        if self.discussion_id:
            for node_config in self.configs:
                if node_config.get("addDiscussionIdTimestampsForLLM", False):
                    is_any_node_timestamped = True
                    break

        # Timestamp history is resolved once at the start of the entire workflow run
        # rather than once per node. This ensures that the placeholder written by the
        # PREVIOUS turn's assistant response is resolved against the new incoming
        # message list before any node reads timestamps. Doing it per-node would
        # either resolve the placeholder redundantly on every node or race against
        # the placeholder being written mid-workflow.
        if is_any_node_timestamped:
            self.timestamp_service.resolve_and_track_history(self.messages, self.discussion_id,
                                                                 encryption_key=self.encryption_key,
                                                                 api_key_hash=self.api_key_hash)

        try:
            for idx, config in enumerate(self.configs):
                # Check for cancellation at the start of each node execution
                if cancellation_service.is_cancelled(self.request_id):
                    logger.warning(f"Request {self.request_id} has been cancelled. Terminating workflow early.")
                    cancellation_service.acknowledge_cancellation(self.request_id)
                    raise EarlyTerminationException(f"Workflow execution cancelled for request {self.request_id}")

                # Start timing for this node
                node_start_time = time.perf_counter()
                node_type = config.get("type", "Standard")
                node_name = self._get_node_name(config)
                endpoint_name, endpoint_url = self._get_endpoint_details(config)

                logger.info(
                    f'------Workflow {self.workflow_config_name}; step {idx}; node type: {config.get("type", "Standard")}')

                if "systemPrompt" in config or "prompt" in config:
                    if self.override_first_available_prompts:
                        if self.first_node_system_prompt_override is not None:
                            config["systemPrompt"] = self.first_node_system_prompt_override
                        if self.first_node_prompt_override is not None:
                            config["prompt"] = self.first_node_prompt_override
                        self.override_first_available_prompts = False

                combined_agent_variables = {**self.agent_inputs, **agent_outputs}

                if not returned_to_user and (config.get('returnToUser', False) or idx == len(self.configs) - 1):
                    returned_to_user = True
                    logger.debug("Executing a responding node flow.")

                    generation_prompt = None
                    use_group_chat_logic = config.get("useGroupChatTimestampLogic", False)

                    # Check for timestamping on this specific node.
                    is_timestamping_enabled_for_node = self.discussion_id and config.get(
                        "addDiscussionIdTimestampsForLLM", False)

                    if use_group_chat_logic:
                        generation_prompt = self._identify_generation_prompt()

                    if is_timestamping_enabled_for_node:
                        logger.debug("Saving placeholder timestamp for assistant's response.")
                        self.timestamp_service.save_placeholder_timestamp(self.discussion_id,
                                                                             encryption_key=self.encryption_key,
                                                                             api_key_hash=self.api_key_hash)

                    result_gen = self._process_section(
                        config=config, agent_outputs=combined_agent_variables,
                        is_responding_node=True
                    )

                    # Track whether we've already captured timing for this node
                    timing_already_captured = False

                    if self.stream and isinstance(result_gen, Generator):
                        node_type_for_stream = config.get("type", "Standard")
                        if node_type_for_stream in ["CustomWorkflow", "ConditionalCustomWorkflow"]:
                            # For sub-workflow streaming, capture timing around the generator consumption
                            # This ensures we measure the actual time spent executing the sub-workflow
                            full_response_list = []
                            sub_workflow_start = time.perf_counter()
                            for chunk in result_gen:
                                yield chunk
                                if isinstance(chunk, str) and chunk.startswith("data: "):
                                    # Reconstruct the full response text from the SSE stream for
                                    # logging and downstream variable assignment.  Each chunk is an
                                    # SSE line ("data: {...}").  Parse the JSON, navigate to
                                    # choices[0].delta.content to extract the token, and accumulate
                                    # all tokens into full_response_list.  "[DONE]" signals the end
                                    # of the stream and contains no content token.
                                    try:
                                        data_content = chunk.split("data: ")[1].strip()
                                        if data_content and data_content != "[DONE]":
                                            parsed = json.loads(data_content)
                                            choices = parsed.get("choices", [])
                                            if choices:
                                                delta = choices[0].get("delta", {})
                                                content = delta.get("content", "")
                                                if content:
                                                    full_response_list.append(content)
                                    except (json.JSONDecodeError, IndexError, KeyError):
                                        pass
                            sub_workflow_end = time.perf_counter()
                            # Use the sub-workflow timing for accurate measurement
                            node_start_time = sub_workflow_start
                            node_end_time = sub_workflow_end
                            timing_already_captured = True
                            result = "".join(full_response_list)
                            log_prompt_content(logger, "Output from the LLM (raw SSE stream from sub-workflow)", result)
                        else:
                            # Apply early variable substitution for endpointName if needed
                            endpoint_name_template = config.get("endpointName")
                            if endpoint_name_template and ('{' in endpoint_name_template or '{{' in endpoint_name_template):
                                # Apply variable substitution
                                endpoint_name = self.workflow_variable_service.apply_early_variables(
                                    endpoint_name_template,
                                    agent_inputs=self.agent_inputs,
                                    workflow_config=self.workflow_file_config
                                )
                                logger.debug(f"Resolved endpointName for streaming from '{endpoint_name_template}' to '{endpoint_name}'")
                            else:
                                endpoint_name = endpoint_name_template

                            endpoint_config = get_endpoint_config(endpoint_name) if endpoint_name else {}
                            stream_handler = StreamingResponseHandler(endpoint_config, config,
                                                                      generation_prompt=generation_prompt,
                                                                      request_id=self.request_id)
                            yield from stream_handler.process_stream(result_gen)
                            result = stream_handler.full_response_text
                            log_prompt_content(logger, "Output from the LLM", result)
                    else:
                        result = result_gen
                        if not self.stream and isinstance(result, str) and generation_prompt:
                            result = self._reconstruct_non_streaming(result, generation_prompt)
                        yield result

                    if is_timestamping_enabled_for_node:
                        if use_group_chat_logic:
                            logger.debug(
                                "Committing timestamp immediately for assistant's response (GroupChatLogic enabled).")
                            self.timestamp_service.commit_assistant_response(self.discussion_id, result,
                                                                                 encryption_key=self.encryption_key,
                                                                                 api_key_hash=self.api_key_hash)
                        else:
                            logger.debug(
                                "Skipping immediate timestamp commit. Relying on fallback mechanism on next turn (GroupChatLogic disabled).")

                    agent_outputs[f'agent{idx + 1}Output'] = result

                    # Record node execution info for responding node
                    # Only capture end time if not already captured (e.g., for streaming sub-workflows)
                    if not timing_already_captured:
                        node_end_time = time.perf_counter()
                    node_execution_infos.append(NodeExecutionInfo(
                        node_index=idx + 1,
                        node_type=node_type,
                        node_name=node_name,
                        endpoint_name=endpoint_name,
                        endpoint_url=endpoint_url,
                        execution_time_seconds=node_end_time - node_start_time
                    ))
                else:
                    logger.debug("Executing a non-responding node flow.")
                    result = self._process_section(
                        config=config, agent_outputs=combined_agent_variables,
                        is_responding_node=False
                    )
                    agent_outputs[f'agent{idx + 1}Output'] = result

                    # Record node execution info for non-responding node
                    node_end_time = time.perf_counter()
                    node_execution_infos.append(NodeExecutionInfo(
                        node_index=idx + 1,
                        node_type=node_type,
                        node_name=node_name,
                        endpoint_name=endpoint_name,
                        endpoint_url=endpoint_url,
                        execution_time_seconds=node_end_time - node_start_time
                    ))

        except EarlyTerminationException:
            logger.info(
                f"Terminating workflow early. Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{self.workflow_id}'")
            raise
        finally:
            end_time = time.perf_counter()
            # Log node execution summary before the total execution time
            self._log_node_execution_summary(node_execution_infos)
            logger.info(f"Execution time: {end_time - start_time:.2f} seconds")
            logger.info(
                f"Unlocking locks for InstanceID: '{instance_global_variables.INSTANCE_ID}' and workflow ID: '{self.workflow_id}'")
            self.locking_service.delete_node_locks(instance_global_variables.INSTANCE_ID, self.workflow_id)

    # All node config fields that must be integers when consumed downstream.
    # Maps field name -> default value (None means no default; leave absent).
    _INT_CONFIG_FIELDS = {
        "maxResponseSizeInTokens": 400,
        "maxContextTokenSize": 4096,
        "minMessagesInVariable": 5,
        "maxEstimatedTokensInVariable": 2048,
        "nMessagesToIncludeInVariable": 5,
        "estimatedTokensToIncludeInVariable": 2048,
        "lastMessagesToSendInsteadOfPrompt": 5,
        "limit": 5,
        "maxTurnsToPull": None,
        "maxSummaryChunksFromFile": None,
        "lookbackStart": 0,
        "minMemoriesPerSummary": 3,
        "loopIfMemoriesExceed": 3,
        "visionScanMessageLimit": 20,
        "num_results": 10,
        "top_n_articles": 3,
        "chunksPerMemory": 3,
        "lookbackStartTurn": 0,
        "vectorMemoryMaxResponseSizeInTokens": 1024,
        "vectorMemoryChunkEstimatedTokenSize": 1000,
        "vectorMemoryMaxMessagesBetweenChunks": 5,
        "chunkEstimatedTokenSize": 1000,
        "maxMessagesBetweenChunks": 5,
        "memoryCondensationBuffer": 0,
        "offlineWikiApiPort": None,
        "maxImagesToSend": 0,
    }
    _FLOAT_CONFIG_FIELDS = {
        "percentile": 0.5,
    }

    def _resolve_numeric_config_fields(self, config: Dict):
        """Resolve variable references and coerce types for all known numeric config fields.

        Mutates *config* in place so that downstream code reading from
        ``context.config`` receives properly typed values even when the
        original JSON contained a scoped-variable reference like
        ``"{agent7Input}"`` that resolved to a string.

        Args:
            config (Dict): The node configuration dictionary to resolve and coerce in place.
        """
        for field_name, default in self._INT_CONFIG_FIELDS.items():
            raw = config.get(field_name)
            if raw is None or isinstance(raw, int):
                continue
            if isinstance(raw, str):
                if '{' in raw or '{{' in raw:
                    raw = self.workflow_variable_service.apply_early_variables(
                        raw, agent_inputs=self.agent_inputs,
                        workflow_config=self.workflow_file_config
                    )
                try:
                    config[field_name] = int(raw)
                except (ValueError, TypeError):
                    if default is not None:
                        logger.warning("Config field '%s' resolved to non-integer value: '%s'. "
                                       "Using default %d.", field_name, raw, default)
                        config[field_name] = default
                    else:
                        logger.error("Config field '%s' resolved to non-integer value: '%s' "
                                     "and no default is available.", field_name, raw)
            elif isinstance(raw, float):
                config[field_name] = int(raw)

        for field_name, default in self._FLOAT_CONFIG_FIELDS.items():
            raw = config.get(field_name)
            if raw is None or isinstance(raw, (int, float)):
                continue
            if isinstance(raw, str):
                if '{' in raw or '{{' in raw:
                    raw = self.workflow_variable_service.apply_early_variables(
                        raw, agent_inputs=self.agent_inputs,
                        workflow_config=self.workflow_file_config
                    )
                try:
                    config[field_name] = float(raw)
                except (ValueError, TypeError):
                    logger.warning("Config field '%s' resolved to non-float value: '%s'. "
                                   "Using default %s.", field_name, raw, default)
                    config[field_name] = default

    def _process_section(self, config: Dict, agent_outputs: Dict, is_responding_node: bool):
        """
        Processes a single node of the workflow.
        """
        # Resolve all numeric config fields upfront so downstream code gets
        # properly typed values even when scoped variables are used.
        self._resolve_numeric_config_fields(config)

        is_streaming_for_node = self.stream and is_responding_node
        endpoint_config = {}

        if "endpointName" in config and config.get("endpointName"):
            # Apply early variable substitution for endpointName if it contains variables
            # Only agent inputs and static workflow variables are available at this point
            # Agent outputs are NOT available yet since they come from node execution
            endpoint_name_template = config["endpointName"]

            # Check if endpointName contains variables
            if '{' in endpoint_name_template or '{{' in endpoint_name_template:
                # Use the new apply_early_variables method that doesn't need llm_handler
                endpoint_name = self.workflow_variable_service.apply_early_variables(
                    endpoint_name_template,
                    agent_inputs=self.agent_inputs,
                    workflow_config=self.workflow_file_config
                )
                logger.debug(f"Resolved endpointName from '{endpoint_name_template}' to '{endpoint_name}'")
            else:
                # No variables in endpointName, use it as-is
                endpoint_name = endpoint_name_template

            # Also apply to preset if it exists and contains variables
            preset_template = config.get("preset")
            if preset_template and ('{' in preset_template or '{{' in preset_template):
                # Use the new apply_early_variables method for preset as well
                preset = self.workflow_variable_service.apply_early_variables(
                    preset_template,
                    agent_inputs=self.agent_inputs,
                    workflow_config=self.workflow_file_config
                )
                logger.debug(f"Resolved preset from '{preset_template}' to '{preset}'")
            else:
                preset = preset_template

            # maxResponseSizeInTokens is already resolved by _resolve_numeric_config_fields
            max_response_tokens = config.get("maxResponseSizeInTokens", 400)

            endpoint_config = get_endpoint_config(endpoint_name)
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
                max_response_tokens,
                addGenerationPrompt=add_generation_prompt
            )
        else:
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)

        messages_to_send = self.messages
        if self.discussion_id and config.get("addDiscussionIdTimestampsForLLM", False):
            if self.non_responder_flag is None:
                logger.debug("Formatting messages with timestamps for LLM as requested by node config.")
                use_relative = config.get("useRelativeTimestamps", False)
                messages_to_send = self.timestamp_service.format_messages_with_timestamps(
                    messages=deepcopy(self.messages),
                    discussion_id=self.discussion_id,
                    use_relative_time=use_relative,
                    encryption_key=self.encryption_key,
                    api_key_hash=self.api_key_hash
                )

        context = ExecutionContext(
            request_id=self.request_id,
            workflow_id=self.workflow_id,
            discussion_id=self.discussion_id,
            config=config,
            workflow_config=self.workflow_file_config,
            messages=messages_to_send,
            stream=is_streaming_for_node,
            agent_inputs=self.agent_inputs,
            agent_outputs=agent_outputs,
            llm_handler=self.llm_handler,
            workflow_variable_service=self.workflow_variable_service,
            workflow_manager=self.node_handlers["CustomWorkflow"].workflow_manager,
            node_handlers=self.node_handlers,
            api_key=self.api_key,
            encryption_key=self.encryption_key,
            api_key_hash=self.api_key_hash,
            tools=self.tools,
            tool_choice=self.tool_choice,
        )

        node_type = context.config.get("type", "Standard")
        if node_type not in VALID_NODE_TYPES:
            logger.warning(f"Config Type: '{node_type}' is not a valid node type. Defaulting to 'Standard'.")
            node_type = "Standard"

        handler = self.node_handlers.get(node_type)
        if not handler:
            raise ValueError(f"No handler found for node type: {node_type}")

        result = handler.handle(context)

        if not is_streaming_for_node and isinstance(result, str) and endpoint_config:
            result = post_process_llm_output(result, endpoint_config, config)

        return result