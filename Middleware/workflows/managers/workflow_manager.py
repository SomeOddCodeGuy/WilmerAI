import json
import logging
import time
import uuid
from copy import deepcopy
from typing import Dict, List, Any, Generator

from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.models.llm_handler import LlmHandler
from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities import instance_utils, api_utils
from Middleware.utilities.config_utils import get_active_conversational_memory_tool_name, \
    get_active_recent_memory_tool_name, get_file_memory_tool_name, \
    get_chat_template_name, get_discussion_chat_summary_file_path, get_discussion_memory_file_path, get_workflow_path, \
    get_chat_summary_tool_workflow_name
from Middleware.utilities.file_utils import read_chunks_with_hashes, load_custom_file
from Middleware.utilities.instance_utils import INSTANCE_ID
from Middleware.utilities.memory_utils import gather_chat_summary_memories, \
    handle_get_current_summary_from_file, gather_recent_memories
from Middleware.utilities.prompt_extraction_utils import extract_discussion_id, remove_discussion_id_tag
from Middleware.utilities.prompt_utils import find_how_many_new_memories_since_last_summary, \
    extract_text_blocks_from_hashed_chunks
from Middleware.utilities.sql_lite_utils import SqlLiteUtils
from Middleware.utilities.time_tracking_utils import track_message_timestamps
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.processors.prompt_processor import PromptProcessor

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Manages the execution of workflows for various types of LLM-based tasks.
    """

    @staticmethod
    def run_custom_workflow(workflow_name, request_id, discussion_id: str, messages: List[Dict[str, str]] = None,
                            non_responder=None, is_streaming=False, first_node_system_prompt_override=None,
                            first_node_prompt_override=None):
        workflow_gen = WorkflowManager(workflow_config_name=workflow_name)
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=non_responder,
                                         stream=is_streaming,
                                         first_node_system_prompt_override=first_node_system_prompt_override,
                                         first_node_prompt_override=first_node_prompt_override)

    @staticmethod
    def handle_conversation_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing conversation memory.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_conversational_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_recent_memory_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing recent chat memory.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_active_recent_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def handle_full_chat_summary_parser(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for parsing a full chat summary.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_chat_summary_tool_workflow_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    @staticmethod
    def process_file_memories(request_id, discussion_id: str, messages: List[Dict[str, str]] = None):
        """
        Initializes and runs a workflow for processing memories from files.

        :param request_id: The unique ID for this instance of the endpoint call
        :param messages: List of message dictionaries.
        :return: The result of the workflow execution.
        """
        workflow_gen = WorkflowManager(workflow_config_name=get_file_memory_tool_name())
        return workflow_gen.run_workflow(messages, request_id, discussion_id, nonResponder=True)

    def __init__(self, workflow_config_name, **kwargs):
        """
        Initializes the WorkflowManager with the given workflow configuration name and optional parameters.

        :param workflow_config_name: The name of the workflow configuration file.
        :param kwargs: Optional keyword arguments, including 'llm_handler' and 'lookbackStartTurn'.
        """
        self.llm_handler = None
        self.workflow_variable_service = WorkflowVariableManager(**kwargs)
        self.workflowConfigName = workflow_config_name
        self.llm_handler_service = LlmHandlerService()

        if 'llm_handler' in kwargs:
            self.llm_handler = kwargs['llm_handler']
        if 'lookbackStartTurn' in kwargs:
            self.lookbackStartTurn = kwargs['lookbackStartTurn']

        # Initialize step handler mapping (Refactored from _process_section if/elif)
        self._STEP_HANDLERS = {
            "Standard": self._handle_standard_step,
            "ConversationMemory": self._handle_conversation_memory_step,
            "FullChatSummary": self._handle_full_chat_summary_step,
            "RecentMemory": self._handle_recent_memory_step,
            "ConversationalKeywordSearchPerformerTool": self._handle_conversational_keyword_search_step,
            "MemoryKeywordSearchPerformerTool": self._handle_memory_keyword_search_step,
            "RecentMemorySummarizerTool": self._handle_recent_memory_summarizer_step,
            "ChatSummaryMemoryGatheringTool": self._handle_chat_summary_gathering_step,
            "GetCurrentSummaryFromFile": self._handle_get_current_summary_step,
            "chatSummarySummarizer": self._handle_chat_summary_summarizer_step,
            "GetCurrentMemoryFromFile": self._handle_get_current_memory_step, # Alias for summary
            "WriteCurrentSummaryToFileAndReturnIt": self._handle_write_summary_step,
            "SlowButQualityRAG": self._handle_slow_rag_step,
            "QualityMemory": self._handle_quality_memory_step,
            "PythonModule": self._handle_python_module_step,
            "OfflineWikiApiFullArticle": self._handle_wiki_full_article_step,
            "OfflineWikiApiBestFullArticle": self._handle_wiki_best_article_step,
            "OfflineWikiApiTopNFullArticles": self._handle_wiki_topn_articles_step,
            "OfflineWikiApiPartialArticle": self._handle_wiki_partial_article_step,
            "WorkflowLock": self._handle_workflow_lock_step,
            "CustomWorkflow": self._handle_custom_workflow_step,
            "ConditionalCustomWorkflow": self._handle_conditional_workflow_step,
            "GetCustomFile": self._handle_get_custom_file_step,
            "ImageProcessor": self._handle_image_processor_step
        }

    def _maybe_update_message_state(self, step_result: Any, current_messages: List[Dict[str, Any]], step_index: int) -> List[Dict[str, Any]]:
        """Checks step result and updates message list if applicable.
        Some steps might return a dictionary with a 'messages' key containing an updated
        list of messages to be used by subsequent steps.
        """
        if isinstance(step_result, dict) and 'messages' in step_result and isinstance(step_result['messages'], list):
            updated_messages = step_result['messages']
            logger.debug(f"Workflow step {step_index} returned updated messages list (length {len(updated_messages)}). Updating state for next step.")
            return updated_messages # Return the new list
        else:
            # logger.debug(f"Workflow step {step_index} did not return an updated message list in standard format.") # Reduced verbosity
            return current_messages # Return the original list unchanged

    def _aggregate_text_from_stream_generator(self, result_generator, step_idx):
        """
        Iterates through a generator expected to yield stream chunks (like LLM responses),
        extracts text content from each chunk, and aggregates it into a single string.

        This is used for intermediate workflow steps that return a generator but whose
        output needs to be stored as a complete text string for subsequent steps.
        It's also used if the final step is non-streaming but happens to return a generator.

        Args:
            result_generator: The generator instance to iterate through.
            step_idx: The index of the current workflow step (for logging).

        Returns:
            The aggregated text string, or None if an error occurs during iteration
            or no text is extracted.
        """
        logger.debug(f"Step {step_idx}: Aggregating text from stream generator.")
        text_chunks = []
        try:
            for chunk in result_generator:
                # Assumes chunks might be JSON strings or dicts containing text
                extracted_text = api_utils.extract_text_from_chunk(chunk)
                if extracted_text:
                    text_chunks.append(extracted_text)
            aggregated_text = ''.join(text_chunks)
            logger.debug(f"Step {step_idx}: Aggregated text: '{aggregated_text[:100]}...'")
            return aggregated_text if aggregated_text else None # Return None if empty string
        except Exception as e:
            logger.error(f"Step {step_idx}: Error aggregating text from generator: {e}", exc_info=True)
            return None # Return None on error

    def _prepare_and_store_step_output(self, result: Any, step_idx: int, is_final_step: bool, stream: bool, agent_outputs: Dict) -> Any:
        """
        Processes the result of a workflow step, handling potential stream generators.

        It determines if the result is a generator that needs to be aggregated immediately
        (i.e., it's an intermediate step, or a final non-streaming step).
        If aggregation is needed, it calls _aggregate_text_from_stream_generator.
        Finally, it stores the appropriate value (either the original result or the
        aggregated text) into the `agent_outputs` dictionary for use by later steps.

        Args:
            result: The raw result returned by the step's _process_section call.
            step_idx: The index of the current workflow step.
            is_final_step: Boolean indicating if this is the last step returning to the user.
            stream: Boolean indicating if the overall workflow is streaming.
            agent_outputs: The dictionary holding outputs from previous steps.

        Returns:
            The value that was stored in `agent_outputs` (either the original result
            or the aggregated text/None).
        """
        # Check if the result is iterable but not a standard string/bytes/dict type.
        # This usually indicates a generator yielding stream chunks.
        is_stream_generator = hasattr(result, '__iter__') and not isinstance(result, (str, bytes, dict))
        logger.debug(f"Step {step_idx}: Result is potential stream generator? {is_stream_generator}")

        should_stream_final_step = is_final_step and stream
        # Aggregate text now if it's a generator AND it's NOT the final step meant for direct streaming.
        aggregate_now = is_stream_generator and not should_stream_final_step

        value_to_store = result # Default: store the original result
        if aggregate_now:
            # Aggregate intermediate stream or non-streaming final step generator
            logger.debug(f"Step {step_idx}: Aggregating result because aggregate_now={aggregate_now} (is_stream_generator={is_stream_generator}, should_stream_final_step={should_stream_final_step})")
            value_to_store = self._aggregate_text_from_stream_generator(result, step_idx)

        # Store the processed result (original or aggregated text/None)
        output_key = f'agent{step_idx + 1}Output'
        agent_outputs[output_key] = value_to_store
        logger.debug(f"Step {step_idx}: Stored in agent_outputs['{output_key}']: type={type(value_to_store)}, value='{str(value_to_store)[:100]}...'" )
        return value_to_store 

    def _apply_prompt_overrides_if_needed(self, config: Dict, idx: int, step_title: str,
                                          first_node_system_prompt_override: str | None,
                                          first_node_prompt_override: str | None) -> None:
        """Applies prompt overrides to the first step that has prompts, if configured."""
        if self.override_first_available_prompts and ("systemPrompt" in config or "prompt" in config):
            logger.debug(f"Applying prompt overrides to step {idx} ('{step_title}')")
            if first_node_system_prompt_override is not None:
                config["systemPrompt"] = first_node_system_prompt_override
            if first_node_prompt_override is not None:
                config["prompt"] = first_node_prompt_override
            # Ensure overrides are applied only once to the first relevant node
            self.override_first_available_prompts = False

    def _yield_final_output(self, result: Any, output_value_stored: Any, stream: bool, idx: int, step_title: str) -> Generator[Any, None, None]:
        """Handles yielding the final output, either streaming or single."""
        logger.debug(f"Handling output for final step {idx} ('{step_title}'). Overall stream={stream}")
        if stream:
            # Stream=True: Yield chunks directly from the raw `result`
            logger.debug(f"Yielding chunks for final streaming step {idx} ('{step_title}') from raw result.")
            final_yield_source = result # Use the original result from _process_section
            is_stream_generator = hasattr(final_yield_source, '__iter__') and not isinstance(final_yield_source, (str, bytes, dict))

            if is_stream_generator:
                chunk_count = 0
                for chunk in final_yield_source: # chunk here is likely SSE string from handler
                    chunk_count += 1
                    
                    # Check if the chunk from the handler is ALREADY formatted correctly for Ollama
                    # (i.e., it's a JSON string NOT starting with 'data:')
                    is_plain_json_string = isinstance(chunk, str) and not chunk.startswith('data:')
                    
                    extracted_text = api_utils.extract_text_from_chunk(chunk)
                    
                    if extracted_text:
                        # If the original chunk was plain JSON (Ollama), yield similar format
                        if is_plain_json_string:
                            # Yield just the JSON expected by Ollama client (needs verification)
                            # Assuming client expects {"response": "text"}
                            yield f"{json.dumps({'response': extracted_text})}\n"
                        # Otherwise, yield standard SSE format for OpenAI/others
                        else:
                            yield f"data: {json.dumps({'response': extracted_text})}\n\n"

                logger.debug(f"Finished yielding {chunk_count} chunks for streaming step {idx}.")
            else:
                 # Final step was supposed to stream but didn't return a generator.
                 logger.warning(f"Expected generator/iterable for final streaming step {idx} ('{step_title}'), but got {type(final_yield_source)}. Yielding as single SSE chunk.")
                 yield f"data: {json.dumps({'response': str(final_yield_source)})}\n\n"
        else:
             # Stream=False: Yield the single, potentially aggregated value stored earlier.
             logger.debug(f"Yielding single result for non-streaming final step {idx} ('{step_title}'). Type: {type(output_value_stored)}")
             yield output_value_stored

    def _prepare_step_inputs(self, idx: int, config: Dict, returned_to_user: bool, workflow_steps: List[Dict],
                             current_messages: List[Dict], discussion_id: str | None, nonResponder: bool | None) -> tuple[bool, List[Dict]]:
        """
        Determines if the step is final and prepares messages (e.g., adds timestamps).

        Returns:
            A tuple: (is_final_step, messages_for_this_step)
        """
        # Determine if this step is the final one intended to return output to the user.
        # It's final if not already returned AND (marked returnToUser OR it's the last step).
        is_final_step = not returned_to_user and (config.get('returnToUser', False) or idx == len(workflow_steps) - 1)

        messages_for_this_step = current_messages # Start with current messages

        if is_final_step:
            step_title = config.get('title', f'Step {idx}')
            logger.debug(f"Step {idx} ('{step_title}') identified as the final step for user output.")
            # Optionally add timestamps if configured and applicable (not a nonResponder flow, discussion_id exists)
            add_timestamps = config.get("addDiscussionIdTimestampsForLLM", False)
            if nonResponder is None and discussion_id is not None and add_timestamps:
                logger.debug("Adding timestamps to messages for final step.")
                # Use a deepcopy before modification if track_message_timestamps modifies in place
                messages_for_this_step = track_message_timestamps(messages=deepcopy(current_messages),
                                                                  discussion_id=discussion_id)

        return is_final_step, messages_for_this_step

    def _determine_add_generation_prompt(self, config: Dict) -> bool | None:
        """Determines if a generation prompt should be added based on config flags."""
        add_user_prompt = config.get('addUserTurnTemplate', False)
        force_generation_prompt_if_endpoint_allows = (
            config.get('forceGenerationPromptIfEndpointAllows', False))
        block_generation_prompt = (
            config.get('blockGenerationPrompt', False))

        # Determine if a generation prompt should be added (usually True unless explicitly blocked)
        if block_generation_prompt or (not force_generation_prompt_if_endpoint_allows and not add_user_prompt):
            # Explicitly blocked or conditions met to prevent adding it
            return False
        else:
            # Default behavior: Allow the LLM handler to decide (usually adds it)
            # Represented by passing None to the handler service.
            return None

    def _execute_workflow_steps(self, workflow_steps: List[Dict], initial_messages: List[Dict],
                                workflow_id: str, request_id: str, discussion_id: str | None,
                                stream: bool, nonResponder: bool | None, start_time: float,
                                first_node_system_prompt_override: str | None,
                                first_node_prompt_override: str | None) -> Generator[Any, None, None]:
        """ Executes the steps of the workflow, yielding the final result. """
        returned_to_user = False
        agent_outputs = {}
        current_messages = initial_messages
        current_step_idx = -1 # For logging in case of error before loop starts
        try:
            if not workflow_steps:
                    logger.warning(f"Workflow {self.workflowConfigName} (ID: {workflow_id}) has no steps defined.")
                    # No steps to execute, generator will just finish.

            for idx, config in enumerate(workflow_steps):
                current_step_idx = idx # Update for logging
                step_title = config.get('title', f'Step {idx}')
                step_type = config.get('type', 'Standard')
                logger.info(f'------ Workflow \'{self.workflowConfigName}\'; Step {idx}: \'{step_title}\' (Type: {step_type})')

                # Apply overrides if provided and not yet used
                # Accesses self.override_first_available_prompts directly
                self._apply_prompt_overrides_if_needed(
                    config, idx, step_title,
                    first_node_system_prompt_override,
                    first_node_prompt_override
                )

                # Determine generation prompt strategy using helper
                add_generation_prompt = self._determine_add_generation_prompt(config)

                # --- Determine messages and if it's the final step --- 
                is_final_step, messages_for_this_step = self._prepare_step_inputs(
                    idx=idx,
                    config=config,
                    returned_to_user=returned_to_user,
                    workflow_steps=workflow_steps,
                    current_messages=current_messages,
                    discussion_id=discussion_id,
                    nonResponder=nonResponder
                )

                # Mark that we are processing/have processed the step that will yield to the user.
                # This prevents subsequent steps from being marked as final.
                if is_final_step:
                    returned_to_user = True
                
                # --- Process the current section --- 
                logger.debug(f"Processing step {idx} ('{step_title}') with {len(messages_for_this_step)} messages. Overall stream={stream}, Final step={is_final_step}")
                result = self._process_section(config, request_id, workflow_id, discussion_id,
                                                messages_for_this_step, 
                                                agent_outputs,
                                                stream=(stream and is_final_step), # Pass stream=True only if it's the final step AND overall stream=True
                                                addGenerationPrompt=add_generation_prompt)
                logger.info(f"Step {idx} ('{step_title}') result raw type: {type(result)}")
                
                # Process result: aggregate if needed (intermediate/non-streaming final), store output
                output_value_stored = self._prepare_and_store_step_output(
                    result=result,
                    step_idx=idx,
                    is_final_step=is_final_step,
                    stream=stream,
                    agent_outputs=agent_outputs
                )

                # Update message state if the step returned a modified list
                current_messages = self._maybe_update_message_state(result, current_messages, idx)
                    
                # --- Handle final step output (Yield result to caller) --- 
                if is_final_step:
                    # Use helper to yield the final output (streaming or single)
                    yield from self._yield_final_output(
                        result=result,
                        output_value_stored=output_value_stored,
                        stream=stream,
                        idx=idx,
                        step_title=step_title
                    )
                    
                    # Since we yielded the final result, exit the loop.
                    logger.debug(f"Exiting workflow loop after handling final step {idx}.")
                    break 

        except EarlyTerminationException as ete:
            # Catch exceptions specifically raised for early termination (e.g., workflow lock)
            logger.warning(f"Workflow '{self.workflowConfigName}' (ID: {workflow_id}) terminated early at step {current_step_idx}: {ete}")
            raise # Re-raise to signal termination to the caller
        except Exception as e:
            # Catch unexpected errors during the workflow loop
            logger.error(f"Error during execution of workflow '{self.workflowConfigName}' (ID: {workflow_id}) at step {current_step_idx}: {e}", exc_info=True)
            raise # Re-raise to signal the error to the caller
        finally:
            # This block executes when the generator finishes, either normally or via exception.
            # It ensures locks acquired *during* generator execution are released.
            logger.debug(f"Generator for workflow '{self.workflowConfigName}' (ID: {workflow_id}) finishing.")
            end_time_gen = time.perf_counter()
            # Ensure start_time was set before calculating duration
            execution_time_gen = end_time_gen - start_time if start_time else 0
            logger.info(f"Workflow '{self.workflowConfigName}' (ID: {workflow_id}) generator finished. Execution time: {execution_time_gen:.4f} seconds")
            logger.info(f"Unlocking locks for InstanceID: '{INSTANCE_ID}' and workflow ID: '{workflow_id}'")
            SqlLiteUtils.delete_node_locks(instance_utils.INSTANCE_ID, workflow_id)

    def run_workflow(self, messages, request_id, discussionId: str = None, stream: bool = False, nonResponder=None,
                     first_node_system_prompt_override=None, first_node_prompt_override=None):
        """
        Executes the workflow defined by `self.workflowConfigName`.

        Handles step-by-step execution, variable passing (`agent_outputs`),
        intermediate stream aggregation, conditional final output streaming,
        prompt overrides, and error handling/cleanup.

        Args:
            messages: The initial list of message dictionaries.
            request_id: A unique ID for the request initiating the workflow.
            discussionId: The ID for the discussion context, if applicable.
            stream: If True, the final step's output will be streamed if possible.
                    If False, the final step's output is returned as a single result.
            nonResponder: If True, indicates the workflow doesn't produce a final user response.
            first_node_system_prompt_override: Optional override for the first node's system prompt.
            first_node_prompt_override: Optional override for the first node's user prompt.

        Returns:
            If stream=True: A generator yielding the final output chunks.
            If stream=False: The single, complete final output.
        """
        workflow_id = str(uuid.uuid4())
        if discussionId is None:
            discussion_id = extract_discussion_id(messages)
        else:
            discussion_id = discussionId

        # Make a copy early to avoid modifying the original caller's list
        initial_messages_copy = deepcopy(messages)
        if discussion_id:
             remove_discussion_id_tag(initial_messages_copy) # Modify the copy

        self.override_first_available_prompts = False
        if first_node_system_prompt_override is not None or first_node_prompt_override is not None:
            self.override_first_available_prompts = True

        start_time = None # Initialize in case of early error
        try:
            start_time = time.perf_counter()
            config_file = get_workflow_path(self.workflowConfigName)
            logger.info(f"Starting workflow '{self.workflowConfigName}' (ID: {workflow_id}) from {config_file}")

            with open(config_file) as f:
                configs = json.load(f)
            
            if isinstance(configs, list):
                workflow_steps = configs # Use the list directly
            elif isinstance(configs, dict):
                workflow_steps = configs.get('workflow', []) # Get steps from the 'workflow' key
            else:
                # Raise an error if it's neither a list nor a dictionary
                raise TypeError(f"Workflow configuration file '{config_file}' must contain a JSON list or a JSON object with a 'workflow' key, but found type {type(configs)}.")

            # Prepare arguments for the execution generator
            exec_args = {
                "workflow_steps": workflow_steps,
                "initial_messages": initial_messages_copy,
                "workflow_id": workflow_id,
                "request_id": request_id,
                "discussion_id": discussion_id,
                "stream": stream,
                "nonResponder": nonResponder,
                "start_time": start_time,
                "first_node_system_prompt_override": first_node_system_prompt_override,
                "first_node_prompt_override": first_node_prompt_override
            }

            # --- Execution Logic --- 
            if stream:
                # For streaming requests, return the generator immediately.
                logger.debug(f"Returning generator for streaming workflow '{self.workflowConfigName}' (ID: {workflow_id}).")
                return self._execute_workflow_steps(**exec_args)
            else:
                # For non-streaming requests, execute the generator and return the single result.
                # Using list() consumes the generator and ensures its finally block runs.
                logger.debug(f"Executing generator to get single result for non-streaming workflow '{self.workflowConfigName}' (ID: {workflow_id}).")
                results_list = []
                try:
                    results_list = list(self._execute_workflow_steps(**exec_args))
                except Exception as e:
                    # Catch errors during generator consumption.
                    # The finally block inside _execute_workflow_steps should have already run.
                    logger.error(f"Error consuming generator for non-streaming workflow '{self.workflowConfigName}' (ID: {workflow_id}): {e}", exc_info=True)
                    raise # Re-raise the error

                # Process the results obtained from the generator
                if not results_list:
                    # The generator finished without yielding anything
                    logger.warning(f"Workflow '{self.workflowConfigName}' (ID: {workflow_id}, non-streaming) did not yield any result.")
                    return None # Corrected indentation
                if len(results_list) > 1:
                    # This shouldn't happen if the `break` after the final step works correctly.
                    logger.warning(f"Workflow '{self.workflowConfigName}' (ID: {workflow_id}, non-streaming) yielded multiple results ({len(results_list)}) unexpectedly. Returning the first.")

                final_result = results_list[0]
                logger.debug(f"Returning single result for non-streaming workflow '{self.workflowConfigName}' (ID: {workflow_id}). Type: {type(final_result)}")
                return final_result
                
        except FileNotFoundError as fnfe:
            logger.error(f"Workflow configuration file not found for '{self.workflowConfigName}': {fnfe}", exc_info=True)
            # No locks acquired yet, just raise.
            raise
        except EarlyTerminationException as ete:
            # Catch termination exceptions that occur *before* the generator is even created.
            logger.warning(f"Workflow '{self.workflowConfigName}' (ID: {workflow_id}) terminated early before generator execution: {ete}")
            # No locks acquired by gen() yet, just raise.
            raise
        except Exception as e:
            # Catch setup errors (e.g., config loading, initial deepcopy) before the generator starts.
            logger.error(f"Setup error for workflow '{self.workflowConfigName}' (ID: {workflow_id}): {e}", exc_info=True)
            # No locks acquired by gen() yet, just raise.
            raise 

    def _process_section(self, config: Dict, request_id, workflow_id, discussion_id: str,
                         messages: List[Dict[str, str]] = None,
                         agent_outputs: Dict = None,
                         stream: bool = False,
                         addGenerationPrompt: bool = None):
        """
        Processes a single section of the workflow configuration.

        :param config: The configuration dictionary for the current workflow section.
        :param messages: List of message dictionaries.
        :param agent_outputs: A dictionary containing outputs from previous agents in the workflow.
        :param stream: A flag indicating whether the workflow should be executed in streaming mode.
        :return: The result of processing the current workflow section.
        """
        preset = None
        if "preset" in config:
            preset = config["preset"]
        if "endpointName" in config:
            # load the model
            logger.info("\n\n#########\n%s", config["title"])
            logger.info("\nLoading model from config %s", config["endpointName"])
            if config["endpointName"] == "" and hasattr(config, "multiModelList"):
                self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)
            else:
                self.llm_handler = self.llm_handler_service.load_model_from_config(config["endpointName"],
                                                                                   preset,
                                                                                   stream,
                                                                                   config.get("maxContextTokenSize",
                                                                                              4096),
                                                                                   config.get("maxResponseSizeInTokens",
                                                                                              400),
                                                                                   addGenerationPrompt)
        if "endpointName" not in config:
            self.llm_handler = LlmHandler(None, get_chat_template_name(), 0, 0, True)

        logger.debug("Prompt processor Checkpoint")
        if "type" not in config:
            section_name = config.get("title", "Unknown")
            valid_types = ["Standard", "ConversationMemory", "FullChatSummary", "RecentMemory", 
                          "ConversationalKeywordSearchPerformerTool", "MemoryKeywordSearchPerformerTool", 
                          "RecentMemorySummarizerTool", "ChatSummaryMemoryGatheringTool", "GetCurrentSummaryFromFile", 
                          "chatSummarySummarizer", "GetCurrentMemoryFromFile", "WriteCurrentSummaryToFileAndReturnIt", 
                          "SlowButQualityRAG", "QualityMemory", "PythonModule", "OfflineWikiApiFullArticle", 
                          "OfflineWikiApiBestFullArticle", "OfflineWikiApiTopNFullArticles", "OfflineWikiApiPartialArticle", 
                          "WorkflowLock", "CustomWorkflow", "ConditionalCustomWorkflow", "GetCustomFile", "ImageProcessor"]
            logger.warning(f"Config Type: No Type Found for section '{section_name}'. Expected one of: {valid_types}")
        else:
            logger.info("Config Type: %s", config.get("type"))
        prompt_processor_service = PromptProcessor(self.workflow_variable_service, self.llm_handler)

        # --- Dispatch to appropriate handler based on type ---
        step_type = config.get("type", "Standard") # Default to Standard if type is missing
        handler_method = self._STEP_HANDLERS.get(step_type)

        if handler_method:
            logger.info(f"Dispatching step '{config.get('title', 'Untitled')}' to handler for type '{step_type}'.")
            # Prepare arguments common to most handlers
            handler_args = {
                "config": config,
                "messages": messages,
                "agent_outputs": agent_outputs,
                "prompt_processor_service": prompt_processor_service,
                "request_id": request_id,
                "workflow_id": workflow_id,
                "discussion_id": discussion_id,
                "stream": stream # Pass stream flag, though only CustomWorkflow handlers use it directly
            }
            try:
                # Call the appropriate handler method
                # Pass only the arguments the specific handler needs? Requires introspection or more complex setup.
                # For now, pass the common set. Handlers will ignore unused **kwargs.
                return handler_method(**handler_args)
            except Exception as e:
                logger.error(f"Error executing handler for step type '{step_type}' (Title: '{config.get('title')}'): {e}", exc_info=True)
                # Decide on return value on error: None, raise, or specific error object?
                return None # Returning None for now
        else:
            # Handle unknown step type
            section_name = config.get("title", "Unknown")
            logger.warning(f"Unknown step type '{step_type}' encountered for section '{section_name}'. Skipping step.")
            valid_types = list(self._STEP_HANDLERS.keys())
            logger.debug(f"Valid step types are: {valid_types}")
            return None # Or raise an error? 

    def handle_full_chat_summary(self, messages, config, prompt_processor_service, request_id, discussion_id):
        """
        Handles the workflow for generating a full chat summary.
        (Original method body kept for reference during refactor)
        """
        logger.info("Discussion ID: %s", discussion_id)
        if discussion_id is not None:
            logger.info("Full chat summary discussion id is not none")
            # Manual config check - specific to this step type
            if config.get("isManualConfig", False):
                logger.debug("Manual summary flow")
                filepath = get_discussion_chat_summary_file_path(discussion_id)
                try:
                    summary_chunk = read_chunks_with_hashes(filepath)
                    if summary_chunk:
                        logger.debug("Returning manual summary")
                        return extract_text_blocks_from_hashed_chunks(summary_chunk)
                    else:
                        logger.warning(f"Manual summary file empty or unreadable: {filepath}")
                        return "No summary found (manual file empty/unreadable)"
                except FileNotFoundError:
                    logger.error(f"Manual summary file not found: {filepath}")
                    return "No summary found (manual file missing)"
                except Exception as e:
                    logger.error(f"Error reading manual summary file {filepath}: {e}", exc_info=True)
                    return "Error reading summary file"

            # Automatic summary generation/checking logic
            prompt_processor_service.handle_memory_file(discussion_id, messages) # Side effect?
            try:
                filepath_mem = get_discussion_memory_file_path(discussion_id)
                hashed_memory_chunks = read_chunks_with_hashes(filepath_mem)
                logger.debug("Number of hash memory chunks read: %s", len(hashed_memory_chunks))

                filepath_sum = get_discussion_chat_summary_file_path(discussion_id)
                hashed_summary_chunk = read_chunks_with_hashes(filepath_sum)
                logger.debug("Number of hash summary chunks read: %s", len(hashed_summary_chunk))
                
                index = find_how_many_new_memories_since_last_summary(hashed_summary_chunk, hashed_memory_chunks)
                logger.debug("Number of memory chunks since last summary update: %s", index)

                if index > 1 or index < 0: # Needs regeneration if many new memories or error
                    logger.info("Regenerating full chat summary.")
                    # Call the parser workflow
                    return self.handle_full_chat_summary_parser(request_id, discussion_id, messages)
                elif hashed_summary_chunk: # Summary exists and is up-to-date
                     logger.info("Returning existing, up-to-date chat summary.")
                     return extract_text_blocks_from_hashed_chunks(hashed_summary_chunk)
                else: # No summary exists yet, and not enough memory chunks to trigger generation? Or first run.
                     logger.info("No existing summary and index suggests no update needed; attempting generation.")
                     return self.handle_full_chat_summary_parser(request_id, discussion_id, messages)
            except FileNotFoundError as e:
                 logger.warning(f"Memory or summary file not found during chat summary check ({e}). Attempting generation.")
                 return self.handle_full_chat_summary_parser(request_id, discussion_id, messages)
            except Exception as e:
                 logger.error(f"Error during full chat summary processing: {e}", exc_info=True)
                 # Fallback: try generating summary anyway?
                 return self.handle_full_chat_summary_parser(request_id, discussion_id, messages)
        else:
            logger.warning("Cannot process full chat summary without discussion_id.")
            return "Error: discussion_id required for full chat summary."

    def handle_quality_memory_workflow(self, request_id, messages: List[Dict[str, str]], prompt_processor_service, discussion_id: str):
        """
        Handles the workflow for processing quality memory.
        (Original method body kept for reference during refactor)
        """
        if discussion_id is None:
            logger.debug("Quality memory discussionid is none - using recent memory parser")
            return self.handle_recent_memory_parser(request_id, None, messages)
        else:
            logger.debug("Quality memory discussion_id flow - processing file memories")
            prompt_processor_service.handle_memory_file(discussion_id, messages) # Side effect?
            return self.process_file_memories(request_id, discussion_id, messages)

    def handle_python_module(self, config, prompt_processor_service, messages, agent_outputs):
        """
        Handles the execution of a Python module within the workflow.
        (Original method body kept for reference during refactor)
        """
        # Extract args and kwargs, applying variables if needed? Original didn't show variable application here.
        args = config.get("args", [])
        kwargs = config.get("kwargs", {})
        module_path = config.get("module_path")
        if not module_path:
             logger.error("PythonModule step requires 'module_path' in config.")
             return "Error: Missing module_path for PythonModule step."

        # Consider applying workflow variables to args/kwargs here if desired.
        # For now, assume they are static as per original implementation.

        return prompt_processor_service.handle_python_module(config, messages, module_path,
                                                             agent_outputs, *args, **kwargs)

    def handle_custom_workflow(self, config, messages, agent_outputs, stream, request_id, discussion_id):
        """
        Handles the execution of a standard custom workflow.
        (Original method body kept for reference during refactor)
        """
        logger.info("Custom Workflow initiated")
        workflow_name = config.get("workflowName")
        if not workflow_name:
             logger.error("CustomWorkflow step requires 'workflowName' in config.")
             return "Error: Missing workflowName for CustomWorkflow step."
        logger.info("Running custom workflow with name: %s", workflow_name)

        # Common overrides & streaming logic preparation
        system_prompt, prompt, non_responder, allow_streaming = \
            self._prepare_workflow_overrides(config, messages, agent_outputs, stream)

        # Call the static method to run the sub-workflow
        return WorkflowManager.run_custom_workflow(
            workflow_name=workflow_name,
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            non_responder=non_responder,
            is_streaming=allow_streaming,
            first_node_system_prompt_override=system_prompt,
            first_node_prompt_override=prompt
        )

    def handle_conditional_custom_workflow(self, config, messages, agent_outputs, stream, request_id, discussion_id):
        """
        Handles the execution of a conditional custom workflow.
        (Original method body kept for reference during refactor)
        """
        logger.info("Conditional Custom Workflow initiated")

        # Extract the conditional key and evaluate its value
        conditional_key_template = config.get("conditionalKey")
        if not conditional_key_template:
            logger.error("ConditionalCustomWorkflow step requires 'conditionalKey' in config.")
            return "Error: Missing conditionalKey for ConditionalCustomWorkflow step."

        try:
            # Apply variables to the conditional key template
            raw_key_value = self.workflow_variable_service.apply_variables(
                conditional_key_template, self.llm_handler, messages, agent_outputs, config=config
            )
        except Exception as e:
             logger.error(f"Error applying variables to conditionalKey '{conditional_key_template}': {e}", exc_info=True)
             return "Error evaluating conditionalKey"

        # Normalize the key value (strip whitespace, convert to lowercase)
        key_value = str(raw_key_value).strip().lower() if raw_key_value is not None else ""

        # Determine the workflow to execute based on the normalized key's value
        conditional_workflows = config.get("conditionalWorkflows", {})
        if not conditional_workflows:
             logger.warning("ConditionalCustomWorkflow step has no 'conditionalWorkflows' map defined.")
             return "Error: Missing conditionalWorkflows map."
             
        workflow_map = {k.lower(): v for k, v in conditional_workflows.items()} # Normalize keys in map
        default_workflow = workflow_map.get("default")
        workflow_name = workflow_map.get(key_value, default_workflow)

        if not workflow_name:
             logger.error(f"Conditional key value '{key_value}' (raw: '{raw_key_value}') matched no workflow, and no default was provided.")
             return f"Error: No workflow found for condition '{key_value}' and no default defined."
             
        logger.info("Resolved conditionalKey='{}' (raw: '{}') => workflow_name='{}'".format(key_value, raw_key_value, workflow_name))

        # Fetch route-specific overrides, if any
        # Use the *normalized* key_value for lookup, but maybe config uses original casing?
        # Standardize on lowercase for lookup in routeOverrides map keys.
        route_overrides_map = {k.lower(): v for k, v in config.get("routeOverrides", {}).items()}
        route_overrides = route_overrides_map.get(key_value, {}) # Use normalized key
        
        system_prompt_override = route_overrides.get("systemPromptOverride")
        prompt_override = route_overrides.get("promptOverride")

        # Common streaming and responder logic preparation
        is_responder = config.get("isResponder", False)
        non_responder = None if is_responder else True
        allow_streaming = stream if is_responder else False

        # Expand route-specific overrides with variables, if provided
        expanded_system_prompt = None
        if system_prompt_override:
            try:
                expanded_system_prompt = self.workflow_variable_service.apply_variables(
                    system_prompt_override, self.llm_handler, messages, agent_outputs, config=config
                )
            except Exception as e:
                 logger.error(f"Error applying variables to systemPromptOverride for route '{key_value}': {e}", exc_info=True)
                 # Decide: proceed without override or return error? Returning error seems safer.
                 return "Error expanding system prompt override"

        expanded_prompt = None
        if prompt_override:
            try:
                expanded_prompt = self.workflow_variable_service.apply_variables(
                    prompt_override, self.llm_handler, messages, agent_outputs, config=config
                )
            except Exception as e:
                 logger.error(f"Error applying variables to promptOverride for route '{key_value}': {e}", exc_info=True)
                 return "Error expanding prompt override"

        # Call the static method to run the selected sub-workflow
        return WorkflowManager.run_custom_workflow(
            workflow_name=workflow_name,
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            non_responder=non_responder,
            is_streaming=allow_streaming,
            first_node_system_prompt_override=expanded_system_prompt,
            first_node_prompt_override=expanded_prompt
        )

    # --- Private Helper Methods (Supporting Logic) ---
    def _prepare_workflow_overrides(self, config, messages, agent_outputs, stream):
        """
        Prepares overrides and determines responder and streaming settings for a workflow node.
        (Used by CustomWorkflow/ConditionalCustomWorkflow handlers)
        """
        is_responder = config.get("isResponder", False) or config.get("is_responder", False)
        non_responder = None if is_responder else True
        allow_streaming = stream if is_responder else False

        # Apply system prompt override if present
        system_override_raw = config.get("firstNodeSystemPromptOverride", None)
        if system_override_raw not in [None, ""]:
            system_prompt = self.workflow_variable_service.apply_variables(
                system_override_raw, self.llm_handler, messages, agent_outputs, config=config
            )
        else:
            system_prompt = None

        # Apply prompt override if present
        prompt_override_raw = config.get("firstNodePromptOverride", None)
        if prompt_override_raw not in [None, ""]:
            prompt = self.workflow_variable_service.apply_variables(
                prompt_override_raw, self.llm_handler, messages, agent_outputs, config=config
            )
        else:
            prompt = None

        return system_prompt, prompt, non_responder, allow_streaming

    def _create_prompt_processor(self, llm_handler): # Helper to avoid recreating it constantly
        return PromptProcessor(self.workflow_variable_service, llm_handler)

    def _handle_standard_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Standard step")
        return prompt_processor_service.handle_conversation_type_node(config, messages, agent_outputs)

    def _handle_conversation_memory_step(self, request_id: str, discussion_id: str, messages: List[Dict], **kwargs):
        logger.debug("Conversation Memory step")
        return self.handle_conversation_memory_parser(request_id, discussion_id, messages)

    def _handle_full_chat_summary_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, request_id: str, discussion_id: str, **kwargs):
        logger.debug("Entering full chat summary step")
        # Note: handle_full_chat_summary now delegates to prompt_processor_service or handle_full_chat_summary_parser
        # This method acts as the entry point called by the dispatcher.
        return self.handle_full_chat_summary(messages, config, prompt_processor_service, request_id, discussion_id)

    def _handle_recent_memory_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, request_id: str, discussion_id: str, **kwargs):
        logger.debug("RecentMemory step")
        if discussion_id is not None:
            # This seems like a side effect that maybe shouldn't be here?
            # Consider if handle_memory_file should be part of the actual parser workflow.
            prompt_processor_service.handle_memory_file(discussion_id, messages)
        return self.handle_recent_memory_parser(request_id, discussion_id, messages)

    def _handle_conversational_keyword_search_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, discussion_id: str, **kwargs):
        logger.debug("Conversational Keyword Search Performer step")
        lookback = config.get("lookbackStartTurn") # Make sure key exists or handle error
        if lookback is None:
             logger.warning("'lookbackStartTurn' not specified for ConversationalKeywordSearchPerformerTool, defaulting may occur or error.")
             # Decide on default or raise error - for now, let the called method handle it.
        return prompt_processor_service.perform_keyword_search(config, messages, discussion_id, agent_outputs, lookback)

    def _handle_memory_keyword_search_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, discussion_id: str, **kwargs):
        logger.debug("Memory Keyword Search Performer step")
        return prompt_processor_service.perform_keyword_search(config, messages, discussion_id, agent_outputs)

    def _handle_recent_memory_summarizer_step(self, config: Dict, messages: List[Dict], discussion_id: str, **kwargs):
        logger.debug("Recent memory summarization tool step")
        memories = gather_recent_memories(messages,
                                          discussion_id,
                                          config.get("maxTurnsToPull"), # Add defaults or error handling
                                          config.get("maxSummaryChunksFromFile"),
                                          config.get("lookbackStart", 0))
        custom_delimiter = config.get("customDelimiter")
        if custom_delimiter is not None and memories is not None:
            return memories.replace("--ChunkBreak--", custom_delimiter)
        elif memories is not None:
            return memories
        else:
            return "There are not yet any memories" # Or None? Consistent return types are good.

    def _handle_chat_summary_gathering_step(self, config: Dict, messages: List[Dict], discussion_id: str, **kwargs):
        logger.debug("Chat summary memory gathering tool step")
        return gather_chat_summary_memories(messages,
                                            discussion_id,
                                            config.get("maxTurnsToPull")) # Add defaults or error handling

    def _handle_get_current_summary_step(self, discussion_id: str, **kwargs):
        logger.debug("Getting current summary from File step")
        return handle_get_current_summary_from_file(discussion_id)
    
    # Alias GetCurrentMemoryFromFile to GetCurrentSummaryFromFile handler
    _handle_get_current_memory_step = _handle_get_current_summary_step

    def _handle_chat_summary_summarizer_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, discussion_id: str, **kwargs):
        logger.debug("Summarizing the chat memory into a single chat summary step")
        return prompt_processor_service.handle_process_chat_summary(config, messages, agent_outputs, discussion_id)

    def _handle_write_summary_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, discussion_id: str, **kwargs):
        logger.debug("Writing current summary to file step")
        return prompt_processor_service.save_summary_to_file(config, messages, discussion_id, agent_outputs)

    def _handle_slow_rag_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("SlowButQualityRAG step")
        return prompt_processor_service.perform_slow_but_quality_rag(config, messages, agent_outputs)

    def _handle_quality_memory_step(self, request_id: str, messages: List[Dict], prompt_processor_service: PromptProcessor, discussion_id: str, **kwargs):
        logger.debug("Quality memory step")
        # This directly calls another workflow via the static method - might be okay, but be aware of potential coupling.
        return self.handle_quality_memory_workflow(request_id, messages, prompt_processor_service, discussion_id)

    def _handle_python_module_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Python Module step")
        return self.handle_python_module(config, prompt_processor_service, messages, agent_outputs)

    def _handle_wiki_full_article_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Offline Wikipedia Api Full Article step") # DEPRECATED
        return prompt_processor_service.handle_offline_wiki_node(messages, config.get("promptToSearch"), agent_outputs)

    def _handle_wiki_best_article_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Offline Wikipedia Api Best Full Article step")
        return prompt_processor_service.handle_offline_wiki_node(messages, config.get("promptToSearch"), agent_outputs,
                                                                 use_new_best_article_endpoint=True)

    def _handle_wiki_topn_articles_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Offline Wikipedia Api TopN Full Articles step")
        return prompt_processor_service.handle_offline_wiki_node(messages, config.get("promptToSearch"), agent_outputs,
                                                                 use_new_best_article_endpoint=False,
                                                                 use_top_n_articles_endpoint=True,
                                                                 percentile=config.get("percentile"),
                                                                 num_results=config.get("num_results"),
                                                                 top_n_articles=config.get("top_n_articles")
                                                                 )

    def _handle_wiki_partial_article_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Offline Wikipedia Api Partial Article step")
        return prompt_processor_service.handle_offline_wiki_node(messages, config.get("promptToSearch"), agent_outputs,
                                                                 use_summary_endpoint=False) # Assuming False means partial? Check original logic.

    def _handle_workflow_lock_step(self, config: Dict, workflow_id: str, **kwargs):
        logger.debug("Workflow Lock step")
        workflow_lock_id = config.get("workflowLockId")
        if not workflow_lock_id:
            raise ValueError("A WorkflowLock node must have a 'workflowLockId'.")
        lock_exists = SqlLiteUtils.get_lock(workflow_lock_id)
        if lock_exists:
            logger.info(f"Lock for {workflow_lock_id} is currently active, terminating workflow.")
            raise EarlyTerminationException(f"Workflow is locked by {workflow_lock_id}. Please try again later.")
        else:
            SqlLiteUtils.create_node_lock(INSTANCE_ID, workflow_id, workflow_lock_id)
            logger.info(f"Lock acquired for Instance_ID: '{INSTANCE_ID}', workflow_id '{workflow_id}', workflow_lock_id: '{workflow_lock_id}'.")
            return None # Lock step likely doesn't return a value to store

    def _handle_custom_workflow_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, stream: bool, request_id: str, discussion_id: str, **kwargs):
        logger.debug("Custom Workflow step")
        # Delegates to the public handle_custom_workflow method
        return self.handle_custom_workflow(config, messages, agent_outputs, stream, request_id, discussion_id)

    def _handle_conditional_workflow_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, stream: bool, request_id: str, discussion_id: str, **kwargs):
        logger.debug("Conditional Custom Workflow step")
        # Delegates to the public handle_conditional_custom_workflow method
        return self.handle_conditional_custom_workflow(config, messages, agent_outputs, stream, request_id, discussion_id)

    def _handle_get_custom_file_step(self, config: Dict, **kwargs):
        logger.debug("Get custom file step")
        filepath = config.get("filepath")
        if filepath is None:
            logger.error("GetCustomFile step requires 'filepath' in config.")
            return "Error: No filepath specified for GetCustomFile step."
        delimiter = config.get("delimiter", "\n")
        custom_return_delimiter = config.get("customReturnDelimiter", delimiter)
        try:
            file_content = load_custom_file(filepath=filepath, delimiter=delimiter, custom_delimiter=custom_return_delimiter)
            logger.debug("Custom file result: %s", str(file_content)[:200]) # Log snippet
            return file_content
        except FileNotFoundError:
            logger.error(f"File not found for GetCustomFile step: {filepath}")
            return f"Error: File not found at {filepath}"
        except Exception as e:
            logger.error(f"Error loading custom file {filepath}: {e}", exc_info=True)
            return f"Error loading file {filepath}"

    def _handle_image_processor_step(self, config: Dict, messages: List[Dict], agent_outputs: Dict, prompt_processor_service: PromptProcessor, **kwargs):
        logger.debug("Image Processor step")
        if not any(item.get("role") == "images" for item in messages):
            logger.debug("No images found in messages for ImageProcessor step.")
            return "There were no images attached to the message"
        
        images = prompt_processor_service.handle_image_processor_node(config, messages, agent_outputs)
        
        # Handle adding description back to messages if configured
        add_as_user_message = config.get("addAsUserMessage", False)
        if add_as_user_message:
            message_template = config.get("message", 
                                         f"[SYSTEM: ... Descriptions:```\n[IMAGE_BLOCK]]\n```]") # Shortened template
            message = self.workflow_variable_service.apply_variables(message_template, self.llm_handler, messages, agent_outputs, config=config)
            message = message.replace("[IMAGE_BLOCK]", images if isinstance(images, str) else json.dumps(images))
            if len(messages) >= 1: # Insert before the *last* message if possible (usually assistant placeholder)
                messages.insert(-1, {"role": "user", "content": message})
            else:
                messages.append({"role": "user", "content": message})
            logger.debug("Added image processing results back into message list.")
            # Return the processed images AND the modified messages
            # Need to adjust _maybe_update_message_state if structure changes
            return {"result": images, "messages": messages} 
        else:
            # Only return the processed images
            return images