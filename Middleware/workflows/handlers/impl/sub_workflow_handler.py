# /Middleware/workflows/handlers/impl/sub_workflow_handler.py

import logging
import os
import re
from typing import Any, List, Dict, Optional

from Middleware.utilities.file_utils import load_custom_file, resolve_file_path, save_custom_file
from Middleware.utilities.hashing_utils import find_last_matching_hash_message, hash_single_message
from Middleware.utilities.streaming_utils import stream_static_content
from Middleware.utilities.text_utils import messages_to_text_block
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

# A node 'id' becomes part of a filename, so it is restricted to characters that
# are safe in a path segment (no separators, no '..') to prevent traversal.
_CHUNK_PROCESSOR_ID_PATTERN = re.compile(r'^[A-Za-z0-9_.-]+$')

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
        if node_type == "ConversationChunkProcessor":
            return self.handle_conversation_chunk_processor(context)

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
            workflow_user_folder_override=workflow_user_folder_override,
            api_key=context.api_key,
            tools=context.tools,
            tool_choice=context.tool_choice,
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
            workflow_user_folder_override=workflow_user_folder_override,
            api_key=context.api_key,
            tools=context.tools,
            tool_choice=context.tool_choice,
        )

    def handle_conversation_chunk_processor(self, context: ExecutionContext) -> Any:
        """
        Runs a sub-workflow over the conversation in resumable, fixed-size message chunks.

        A record that is built up from the conversation (a running event log, a per-persona
        tracker) normally only sees the most recent messages each turn. That means a
        conversation that is resumed under a fresh discussion id, or dropped in wholesale
        from another client, would start blind to everything older than that recent window.
        File memory avoids this by walking the whole backlog in chunks on first contact; this
        node gives the same catch-up behavior to any sub-workflow.

        A per-node cursor file, named by the required ``id``, stores the hashes of the last
        chunk's messages. On each run the node reuses the memory system's hash matching to
        find how many messages are new since that cursor, slices them into ``chunkSize``-message
        groups, and runs ``workflowName`` for every *complete* group. There is no per-run cap, so a
        long backlog is fully processed within this single turn before anything downstream (such
        as a responder) runs. The freshest partial group (fewer than ``chunkSize`` messages) and
        the ``lookbackMessages`` tail are left for a later turn; a live responder still sees those
        directly.

        The chunk's text is passed to the sub-workflow as ``{agent1Input}``; any configured
        ``scoped_variables`` follow as ``{agent2Input}``, ``{agent3Input}``, and so on. Those
        variables may only reference outputs of nodes that ran earlier in the parent workflow.

        Config:
            id (str, required): Unique, path-safe identifier. Names the cursor file, so two of
                these nodes in one workflow keep separate cursors. Must be user-supplied and
                stable; a generated id could change and orphan the cursor, forcing a full
                re-processing of history.
            workflowName (str, required): The sub-workflow to run once per chunk.
            chunkSize (int): Messages per chunk. Defaults to 10.
            lookbackMessages (int): Freshest messages to leave unprocessed. Defaults to 4.
            cursorDirectory (str, required): Directory for the cursor file (supports variables).
            returnFile (str, optional): If set, its resolved content is returned so a downstream
                node can keep reading this record; otherwise a short status string is returned.
            scoped_variables (list, optional): Extra inputs for the sub-workflow, after the chunk.

        Returns:
            Any: The ``returnFile`` content if configured, else a status string.
        """
        logger.info("Conversation Chunk Processor initiated")
        config = context.config

        node_id = config.get("id")
        if not node_id or not str(node_id).strip():
            raise ValueError("A ConversationChunkProcessor node must have a unique 'id'.")
        if context.discussion_id is None:
            # Without a discussion id every stateless conversation would share one
            # cursor file: interleaved chats would never match each other's hashes
            # and re-run the child workflow over their entire backlog every turn.
            logger.info("ConversationChunkProcessor '%s': no discussionId on this request; "
                        "skipping chunk processing.", str(node_id).strip())
            return self._chunk_processor_return(context, str(node_id).strip(), 0)
        node_id = str(node_id).strip()
        if not _CHUNK_PROCESSOR_ID_PATTERN.match(node_id):
            raise ValueError(
                f"ConversationChunkProcessor 'id' must contain only letters, digits, '.', '-', "
                f"or '_'; got '{node_id}'.")

        workflow_name = config.get("workflowName")
        if not workflow_name:
            raise ValueError(f"ConversationChunkProcessor '{node_id}' must specify a 'workflowName'.")

        chunk_size = config.get("chunkSize", 10)
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
            raise ValueError(f"ConversationChunkProcessor '{node_id}': 'chunkSize' must be an integer >= 1.")

        lookback = config.get("lookbackMessages", 4)
        if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 0:
            raise ValueError(f"ConversationChunkProcessor '{node_id}': 'lookbackMessages' must be an integer >= 0.")

        cursor_path = self._resolve_chunk_cursor_path(context, node_id)
        messages = context.messages or []

        # Everything before the lookback tail is eligible for processing.
        end_index = len(messages) - lookback
        if end_index <= 0:
            logger.debug("ConversationChunkProcessor '%s': not enough messages past the lookback to process.", node_id)
            return self._chunk_processor_return(context, node_id, 0)

        stored_hashes = self._load_chunk_cursor(cursor_path)
        if stored_hashes:
            # Reuse the memory system's hash matching: how many messages since the cursor.
            num_new = find_last_matching_hash_message(
                messages, [("", h) for h in stored_hashes], turns_to_skip_looking_back=lookback)
            start_index = max(0, end_index - num_new) if num_new > 0 else end_index
        else:
            # No cursor yet -> cold start: everything up to the lookback tail.
            start_index = 0

        new_messages = messages[start_index:end_index]

        # Only complete chunks are processed; a sub-chunkSize remainder waits for a later turn
        # (it is not lost; it is picked up once enough messages accumulate to complete it).
        complete_chunks = [new_messages[i:i + chunk_size]
                           for i in range(0, len(new_messages), chunk_size)
                           if len(new_messages[i:i + chunk_size]) == chunk_size]

        if not complete_chunks:
            logger.debug("ConversationChunkProcessor '%s': no complete chunk of %d messages to process yet.",
                         node_id, chunk_size)
            return self._chunk_processor_return(context, node_id, 0)

        base_scoped_inputs = self._prepare_scoped_inputs(context)
        cursor_hashes = list(stored_hashes)
        chunks_run = 0
        logger.info("ConversationChunkProcessor '%s': processing %d chunk(s) of %d message(s).",
                    node_id, len(complete_chunks), chunk_size)
        for chunk in complete_chunks:
            chunk_text = messages_to_text_block(chunk)
            # The child processes THIS chunk, so it receives the chunk (a shallow copy, so the
            # child's message cleanup cannot mutate the parent conversation) as its messages,
            # never the whole conversation, which on a long backfill would blow every child up.
            # The chunk text is also passed as {agent1Input} for prompts that reference it directly.
            self.workflow_manager.run_custom_workflow(
                workflow_name=workflow_name,
                request_id=context.request_id,
                discussion_id=context.discussion_id,
                messages=[dict(m) for m in chunk],
                non_responder=True,
                is_streaming=False,
                scoped_inputs=[chunk_text] + base_scoped_inputs,
                api_key=context.api_key,
            )
            chunks_run += 1
            # Advance the cursor after each chunk (so a mid-loop failure resumes rather than
            # reprocesses). Store ONE hash per processed chunk (the last message of each chunk),
            # appended to the hashes loaded at the start of the run: the cursor stays small (one
            # hash per chunk, not per message) while still letting a regenerated or reformatted
            # tail re-anchor on an earlier chunk boundary and resume from there. The hash MUST be
            # taken from the chunk actually processed, never recomputed from absolute list
            # indexes: the head of the conversation can shift between turns (client-side context
            # trimming), and an index-grid recomputation would store boundaries that never ended a
            # processed chunk, re-feeding up to chunkSize-1 messages to the child next turn.
            cursor_hashes.append(hash_single_message(chunk[-1]))
            self._save_chunk_cursor(cursor_path, cursor_hashes)

        return self._chunk_processor_return(context, node_id, chunks_run)

    def _resolve_chunk_cursor_path(self, context: ExecutionContext, node_id: str) -> str:
        """Builds the cursor file path for a ConversationChunkProcessor node."""
        cursor_dir_template = context.config.get("cursorDirectory")
        if not cursor_dir_template:
            raise ValueError(f"ConversationChunkProcessor '{node_id}' must specify a 'cursorDirectory'.")
        cursor_dir = self.workflow_variable_service.apply_variables(str(cursor_dir_template), context).strip()
        if not cursor_dir:
            raise ValueError(f"ConversationChunkProcessor '{node_id}': 'cursorDirectory' resolved to empty.")
        discussion_id = context.discussion_id or ""
        # Resolve the path (expanding a leading '~') through the shared file_utils resolver here, at
        # the single source of the cursor path, so the existence check and read (os.path.exists /
        # open below) resolve to the SAME absolute location that the write (save_custom_file, which
        # also uses the shared resolver) uses. Without this, a '~'-based path is written to the real
        # home directory but the existence check looks for a literal '~' directory, never finds the
        # cursor, and cold-starts, reprocessing (and duplicating) the whole record on every run.
        return resolve_file_path(os.path.join(cursor_dir, f"chunk_cursor_{node_id}_{discussion_id}.txt"))

    @staticmethod
    def _load_chunk_cursor(cursor_path: str) -> List[str]:
        """Reads the stored message hashes for the cursor; returns [] if none."""
        if not os.path.exists(cursor_path):
            return []
        try:
            with open(cursor_path, encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except OSError as e:
            logger.warning("Could not read chunk cursor at %s: %s", cursor_path, e)
            return []

    @staticmethod
    def _save_chunk_cursor(cursor_path: str, hashes: List[str]) -> None:
        """Persists the cursor's message hashes (one per line) via an atomic write.

        A failed write (for example an unwritable ``cursorDirectory``) is logged and
        swallowed rather than propagated: the chunk has already been processed this
        turn, so an uncaught error here would abort the workflow and 500 every
        subsequent request. Not advancing the cursor only means those messages are
        reprocessed on a later turn, which is recoverable; crashing is not.
        """
        try:
            save_custom_file(filepath=cursor_path, content="\n".join(hashes), mode="overwrite")
        except OSError as e:
            logger.warning("ConversationChunkProcessor could not persist chunk cursor to %s: %s", cursor_path, e)

    def _chunk_processor_return(self, context: ExecutionContext, node_id: str, chunks_run: int) -> str:
        """Returns the configured record file's content, or a status string if none is set."""
        return_file_template = context.config.get("returnFile")
        if return_file_template:
            resolved = self.workflow_variable_service.apply_variables(str(return_file_template), context)
            if not os.path.exists(resolve_file_path(resolved)):
                # No complete chunk has produced the record yet; returning
                # load_custom_file's missing-file sentinel here would flow that
                # sentinel text into downstream prompts via {agentNOutput}.
                return ""
            return load_custom_file(filepath=resolved, delimiter="", custom_delimiter="\n")
        return f"ConversationChunkProcessor '{node_id}' processed {chunks_run} chunk(s)."
