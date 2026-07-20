# /Middleware/workflows/streaming/response_handler.py

import json
import logging
import uuid
from typing import Dict, Generator, Any, Optional, List

from Middleware.api import api_helpers
from Middleware.common import instance_global_variables
from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant, get_liveness_tool_call
from Middleware.utilities.sensitive_logging_utils import sensitive_log
from Middleware.utilities.streaming_utils import StreamingThinkRemover, strip_leading_response_prefixes

logger = logging.getLogger(__name__)


class StreamingResponseHandler:
    """
    Handles the processing and formatting of a raw LLM stream into a
    client-facing Server-Sent Event (SSE) stream using Optimistic Prefix Matching.
    """

    def __init__(self, endpoint_config: Dict, workflow_node_config: Dict, generation_prompt: Optional[str] = None, request_id: Optional[str] = None):
        """
        Initializes the StreamingResponseHandler.

        Args:
            endpoint_config (Dict): Configuration dictionary for the API endpoint.
            workflow_node_config (Dict): Configuration dictionary for the specific workflow node.
            generation_prompt (Optional[str]): The generation prompt used, if any (for group chat logic).
            request_id (Optional[str]): The unique identifier for the request.
        """
        self.endpoint_config = endpoint_config
        self.workflow_node_config = workflow_node_config
        self.output_format = instance_global_variables.get_api_type()
        self.remover = StreamingThinkRemover(self.endpoint_config)
        self.full_response_text = ""
        self.request_id = request_id

        # State for reconstruction
        self.generation_prompt = generation_prompt
        self._reconstruction_applied = False

        # State for prefix removal
        self._prefix_buffer = ""
        self._prefixes_processed = False

        self.workflow_custom_enabled = self.workflow_node_config.get("removeCustomTextFromResponseStart", False)
        self.endpoint_custom_enabled = self.endpoint_config.get("removeCustomTextFromResponseStartEndpointWide", False)

        self._prefixes_to_strip = self._collect_prefixes()

        # When both workflow-level and endpoint-level prefix stripping are active,
        # both configured prefixes might appear in sequence at the response start.
        # 200 characters gives the buffer enough room to accumulate both without
        # triggering the "buffer full" pessimistic flush path before the optimistic
        # match logic has seen enough content to make a confident decision.
        if self.workflow_custom_enabled and self.endpoint_custom_enabled:
            self._prefix_buffer_limit = 200
        else:
            self._prefix_buffer_limit = 100

        self._lowercase_tool_names = self.workflow_node_config.get("lowercaseToolCallFunctionNames", False)

        # Buffer if stripping is needed OR if reconstruction might be needed
        self._should_buffer_for_prefixes = self._is_prefix_stripping_needed() or (self.generation_prompt is not None)

        # OpenAI-style tool-call deltas can arrive fragmented (arguments streamed
        # in pieces across chunks). Ollama's chat protocol has no delta form
        # (clients expect each tool call as one complete object with arguments as
        # a JSON object), so for the ollamaapichat output format the deltas are
        # accumulated here (keyed by delta index) and emitted once, complete, when
        # the stream finishes.
        self._ollama_tool_call_buffer: Dict[int, Dict[str, str]] = {}

    def _collect_prefixes(self) -> List[str]:
        """
        Collects all potential prefixes to strip from the configuration.

        Returns:
            List[str]: A deduplicated list of all prefix strings that may need to be
                removed from the start of the LLM response, based on the active
                workflow and endpoint configuration.
        """
        prefixes = []

        # Workflow-level Custom Text (Matched exactly as configured)
        if self.workflow_custom_enabled:
            custom_texts = self.workflow_node_config.get("responseStartTextToRemove", [])
            if isinstance(custom_texts, str):
                custom_texts = [custom_texts]
            prefixes.extend([ct for ct in custom_texts if ct])

        # Endpoint-level Custom Text (These are stripped before matching)
        if self.endpoint_custom_enabled:
            custom_texts_endpoint = self.endpoint_config.get("responseStartTextToRemoveEndpointWide", [])
            if isinstance(custom_texts_endpoint, str):
                custom_texts_endpoint = [custom_texts_endpoint]
            prefixes.extend([ct.strip() for ct in custom_texts_endpoint if ct.strip()])

        # Timestamp
        if self.workflow_node_config.get("addDiscussionIdTimestampsForLLM", False):
            timestamp_text = "[Sent less than a minute ago]"
            prefixes.append(timestamp_text)
            # Include the variant with a trailing space as a distinct prefix
            prefixes.append(timestamp_text + " ")


        # Assistant Prefix
        if get_is_chat_complete_add_user_assistant() and get_is_chat_complete_add_missing_assistant():
            prefixes.append("Assistant:")

        # Remove duplicates and return
        return list(set(prefixes))

    def _matches_partial_prefix(self, buffer: str) -> bool:
        """
        Checks if the buffer (lstripped) partially matches the start of any prefix.

        Optimistic matching: if the buffer content does not partially match any
        configured prefix, it is safe to stop buffering and release the content.

        Args:
            buffer (str): The accumulated prefix buffer content to check.

        Returns:
            bool: True if the buffer still potentially matches any prefix (keep
                buffering), False if it definitively does not match any prefix
                (safe to release).
        """
        # We must ignore leading whitespace in the buffer when checking for prefix matches
        lstripped_buffer = buffer.lstrip()

        if not lstripped_buffer:
            # Buffer is empty or only whitespace, keep buffering (might be leading whitespace before a prefix)
            return True

        for prefix in self._prefixes_to_strip:
            # Two cases both mean "still potentially matching, keep buffering":
            # 1. prefix.startswith(buffer): buffer is a leading substring of the prefix
            #    (e.g. buffer="Assi" vs prefix="Assistant:"), so it might complete into a prefix.
            # 2. buffer.startswith(prefix): buffer is longer than the prefix but begins with it
            #    (e.g. buffer="Assistant: hello" vs prefix="Assistant:"), so the prefix is present.
            if prefix.startswith(lstripped_buffer) or lstripped_buffer.startswith(prefix):
                return True

        # If the buffer content doesn't match the start of any prefix, we are safe.
        return False

    def _reconstruction_pending_more_data(self, buffer: str) -> bool:
        """
        True when group-chat reconstruction is pending and the buffer is still too
        short to tell whether the model emitted its own speaker prefix.

        Reconstruction (prepending the generation prompt) must not be decided on the
        first tiny delta: with generation_prompt "Roland:" a 3-char buffer "Rol"
        has no colon yet, so a premature decision would prepend the prompt and then
        the model's own "Roland:" would arrive, producing "Roland: Roland:". Keep
        buffering until a colon appears within the prompt-length window, the buffer
        grows past that window (proving there is no speaker prefix), or the stream
        ends (handled by the is_done release).

        Args:
            buffer (str): The accumulated prefix buffer content.

        Returns:
            bool: True to keep buffering for the reconstruction decision.
        """
        if not (self.generation_prompt and not self._reconstruction_applied):
            return False
        lstripped_buffer = buffer.lstrip()
        if not lstripped_buffer:
            return True
        threshold = len(self.generation_prompt.strip()) + 10
        colon_pos = lstripped_buffer.find(':')
        if 0 <= colon_pos < threshold:
            # A prefix-range colon is already present; the decision can be made now.
            return False
        return len(lstripped_buffer) < threshold

    def _is_prefix_stripping_needed(self) -> bool:
        """
        Checks if any prefix stripping logic is enabled in the configuration.

        Returns:
            bool: True if at least one prefix-stripping mechanism is active,
                False otherwise.
        """
        if self.endpoint_config.get("trimBeginningAndEndLineBreaks", False):
            return True
        if self.workflow_custom_enabled or self.endpoint_custom_enabled:
            return True
        if self.workflow_node_config.get("addDiscussionIdTimestampsForLLM", False):
            return True
        if get_is_chat_complete_add_user_assistant() and get_is_chat_complete_add_missing_assistant():
            return True
        return False

    def _requires_complex_buffering(self) -> bool:
        """
        Checks if buffering beyond simple whitespace trimming is required.

        Returns:
            bool: True if prefix matching or group-chat reconstruction logic needs
                to inspect the buffer before releasing content, False if only
                whitespace trimming is needed.
        """
        if self.generation_prompt is not None:
            return True
        if self._prefixes_to_strip:
            return True
        # If only trimBeginningAndEndLineBreaks is active, we don't need complex buffering.
        return False

    def _process_prefixes_from_buffer(self) -> str:
        """
        Processes the accumulated prefix buffer to apply group chat reconstruction
        and then remove all configured prefixes sequentially.

        Returns:
            str: The buffer content after reconstruction and all prefix stripping
                rules have been applied.
        """
        content = self._prefix_buffer

        # --- 1. Reconstruction Logic ---
        if self.generation_prompt and not self._reconstruction_applied:
            trimmed_prompt = self.generation_prompt.strip()
            content_lstripped = content.lstrip()

            # Check if the content starts with a prefix ending in a colon.
            # This handles both single-word ("Roland:") and multi-word
            # ("Character Name:") prefixes by looking for the first colon
            # within a reasonable range of the generation prompt length.
            if content_lstripped:
                colon_pos = content_lstripped.find(':')
                # +10 provides a small buffer beyond the expected prompt length to account
                # for minor variations in how the LLM formats the prefix (e.g. extra spaces
                # or punctuation) while still reliably distinguishing intentional prefixes
                # from unrelated colons that appear later in the response.
                llm_has_prefix = 0 < colon_pos < len(trimmed_prompt) + 10
            else:
                llm_has_prefix = False

            if not llm_has_prefix:
                sensitive_log(logger, logging.DEBUG, "Reconstructing streaming group chat message. Prepended prompt: '%s'", trimmed_prompt)
                content = f"{trimmed_prompt} {content_lstripped}"
                self._reconstruction_applied = True

        # --- 2. Stripping Logic (Sequential Application) ---
        # Shared with the non-streaming post-processor so the two paths cannot drift.
        remove_assistant = (get_is_chat_complete_add_user_assistant() and
                            get_is_chat_complete_add_missing_assistant())
        return strip_leading_response_prefixes(content, self.workflow_node_config, self.endpoint_config,
                                               remove_assistant)

    def _build_liveness_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        Builds the synthetic tool call that keeps an agentic frontend's loop alive.

        Agentic frontends end their autonomous loop the moment a response arrives
        with no tool call in it. A responder node whose turn is always mid-task
        (e.g. a report or status turn that produces plain text while the task
        continues) opts in with "injectLivenessToolCall": true; when such a node's
        stream produces no tool call of its own, the user's configured liveness
        tool call (a harmless no-op valid for their frontend) is emitted so the
        frontend calls back and the task continues unattended. Responders without
        the property keep the default contract: a text-only response ends the
        frontend's loop, which is how a finished task is meant to stop.

        A COMPLETELY EMPTY response (no tool call and no text) is exempt from that
        contract: a model that finished its task says so in text, so zero output is
        a malfunction, not an answer; delivering it verbatim strands the
        frontend's loop mid-task (observed live 2026-07-13: an empty doer turn
        silently ended a run at 69 router turns). When a liveness tool is
        configured, an empty response gets the keep-alive even from nodes that did
        not opt in, giving the model another turn instead of a silent stop.

        Returns:
            Optional[List[Dict[str, Any]]]: A single-entry tool_calls list in
            streaming delta format, or None when any condition for safe injection
            is unmet (format cannot carry tool calls, the node did not opt in and
            the response was not empty, or no liveness tool is configured).
        """
        if self.output_format not in ("openaichatcompletion", "ollamaapichat"):
            return None
        node_opted_in = self.workflow_node_config.get("injectLivenessToolCall", False)
        response_is_empty = not self.full_response_text.strip()
        if not (node_opted_in or response_is_empty):
            return None
        config = get_liveness_tool_call()
        if not config:
            return None
        arguments = config.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        return [{
            "index": 0,
            "id": f"wilmer_liveness_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": config["toolName"].strip(),
                "arguments": json.dumps(arguments),
            },
        }]

    def _drain_pending_text(self, finalize_remover: bool) -> str:
        """
        Flushes text held back by the buffering pipeline so it can be emitted now.

        Used ahead of a tool-call chunk (so buffered text keeps its generation
        order and cannot be dropped if the stream ends on that chunk) and at
        stream finalization. Optionally finalizes the think remover first; that
        is only valid when no further text chunks will be processed.

        Args:
            finalize_remover (bool): True to flush the think remover's internal
                buffer as well (stream is ending).

        Returns:
            str: The pending text after prefix processing, possibly empty.
        """
        content = self.remover.finalize() if finalize_remover else ""
        if self._should_buffer_for_prefixes and not self._prefixes_processed:
            self._prefix_buffer += content
            content = self._process_prefixes_from_buffer()
            self._prefixes_processed = True
            self._prefix_buffer = ""
        return content

    def _accumulate_ollama_tool_calls(self, tool_calls_delta: List[Dict[str, Any]]) -> None:
        """
        Accumulates OpenAI-style tool-call deltas for later native emission.

        Fragments are merged by delta index: a name overwrites (it arrives whole
        in the first fragment), argument strings concatenate, and argument dicts
        (already-complete calls converted from an Ollama or Claude backend)
        replace the accumulated string wholesale.

        Args:
            tool_calls_delta (List[Dict[str, Any]]): One chunk's tool_calls list.
        """
        for tool_call in tool_calls_delta:
            if not isinstance(tool_call, dict):
                continue
            index = tool_call.get("index", 0)
            entry = self._ollama_tool_call_buffer.setdefault(index, {"name": "", "arguments": ""})
            function = tool_call.get("function") or {}
            name = function.get("name")
            if isinstance(name, str) and name:
                entry["name"] = name
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                entry["arguments"] += arguments
            elif isinstance(arguments, dict):
                entry["arguments"] = json.dumps(arguments)

    def _drain_ollama_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        Builds complete Ollama-native tool calls from the accumulated deltas.

        Returns:
            Optional[List[Dict[str, Any]]]: Tool calls shaped as
            ``{"function": {"name": ..., "arguments": {...}}}`` with arguments as
            a JSON object (Ollama's wire format), or None when nothing was
            accumulated.
        """
        if not self._ollama_tool_call_buffer:
            return None
        calls = []
        for index in sorted(self._ollama_tool_call_buffer):
            entry = self._ollama_tool_call_buffer[index]
            raw_arguments = entry["arguments"]
            arguments: Dict[str, Any] = {}
            if raw_arguments.strip():
                try:
                    parsed = json.loads(raw_arguments)
                    if isinstance(parsed, dict):
                        arguments = parsed
                    else:
                        logger.warning("Accumulated tool-call arguments parsed to a non-object; "
                                       "sending empty arguments to the Ollama client.")
                except json.JSONDecodeError:
                    logger.warning("Accumulated tool-call arguments were not valid JSON; "
                                   "sending empty arguments to the Ollama client.")
            calls.append({"function": {"name": entry["name"], "arguments": arguments}})
        self._ollama_tool_call_buffer = {}
        return calls

    def process_stream(self, raw_dict_generator: Generator[Dict[str, Any], None, None]) -> Generator[str, None, None]:
        """
        Processes a raw dictionary stream from an LLM and yields formatted SSE strings.

        Applies the full pipeline in order: think-block removal, prefix buffering and
        stripping, group-chat reconstruction, and SSE formatting. Emits a terminal
        stop event and (for non-Ollama formats) a ``[DONE]`` sentinel at the end of
        the stream.

        Tool call chunks bypass the text-processing pipeline entirely (no prefix
        stripping, no think-block removal) and are formatted directly into SSE output.

        Args:
            raw_dict_generator (Generator[Dict[str, Any], None, None]): A generator of
                token dictionaries from an LLM handler, each containing 'token' and
                'finish_reason' keys, and optionally 'tool_calls'.

        Yields:
            str: Formatted SSE or NDJSON strings ready to be sent to the client.
        """
        requires_complex_buffering = self._requires_complex_buffering()
        trim_whitespace = self.endpoint_config.get("trimBeginningAndEndLineBreaks", False)
        finish_already_sent = False
        stream_finish_reason = None
        saw_tool_calls = False

        for data_chunk in raw_dict_generator:
            content_delta = data_chunk.get("token") or ""
            finish_reason = data_chunk.get("finish_reason")
            tool_calls_delta = data_chunk.get("tool_calls")

            # Tool call chunks bypass all text processing (prefix stripping,
            # think-block removal, etc.) and are emitted directly. Use a truthiness
            # check, not "is not None": some OpenAI-compatible backends attach an
            # empty "tool_calls": [] to ordinary text deltas, and routing those
            # through the bypass would strip think blocks, skip prefix handling, and
            # drop the text from full_response_text (empty agent output / memory).
            if tool_calls_delta:
                saw_tool_calls = True

                # Text can still be sitting in the prefix buffer (start-of-stream
                # optimistic matching) when the first tool-call delta arrives.
                # Flush it first so the client sees content in generation order,
                # and so it cannot be dropped if the stream finishes on this chunk
                # (the finalization block below is skipped in that case). Only
                # finalize the think remover when the stream is actually ending,
                # and leave an empty buffer untouched mid-stream so prefix
                # stripping stays armed for text that follows the tool call.
                # Trade-off: a buffer still partially matching a configured
                # prefix (e.g. "Assi" of "Assistant:") is released unstripped
                # and stripping disarms; dropping it instead could lose real
                # text when the stream ends on this chunk.
                # Exception: while the group-chat reconstruction decision is
                # still pending (buffer too short to tell whether the model is
                # emitting its own speaker prefix), draining mid-stream would
                # decide reconstruction on the tiny buffer and can double the
                # prefix ("Roland: Roland:"). Keep buffering instead; the
                # stream-end finalization below always drains what remains.
                pending_text = ""
                if finish_reason or (self._prefix_buffer
                                     and not self._reconstruction_pending_more_data(self._prefix_buffer)):
                    pending_text = self._drain_pending_text(finalize_remover=bool(finish_reason))
                if pending_text:
                    self.full_response_text += pending_text
                    pending_json = api_helpers.build_response_json(
                        token=pending_text, finish_reason=None,
                        request_id=self.request_id
                    )
                    yield api_helpers.sse_format(pending_json, self.output_format)

                if self._lowercase_tool_names:
                    for tc in tool_calls_delta:
                        func = tc.get("function")
                        if func and isinstance(func.get("name"), str):
                            original_name = func["name"]
                            func["name"] = original_name.lower()
                            if func["name"] != original_name:
                                # DEBUG, not INFO: streaming tool-call deltas arrive
                                # frequently and this would otherwise flood the log.
                                logger.debug("Tool call function name lowercased: '%s' -> '%s'",
                                             original_name, func["name"])

                if self.output_format == "ollamaapichat":
                    # Ollama's protocol has no tool-call deltas: accumulate the
                    # fragments and emit complete native calls once the stream
                    # finishes, matching how Ollama itself sends tool calls.
                    self._accumulate_ollama_tool_calls(tool_calls_delta)
                    if content_delta:
                        # Text riding on a tool-call chunk is delivered to the
                        # client, so it must also land in the captured result
                        # (agent outputs / memory) like every other delivered
                        # token.
                        self.full_response_text += content_delta
                        content_json = api_helpers.build_response_json(
                            token=content_delta, finish_reason=None,
                            request_id=self.request_id
                        )
                        yield api_helpers.sse_format(content_json, self.output_format)
                    if finish_reason:
                        completion_json = api_helpers.build_response_json(
                            token="", finish_reason=finish_reason,
                            request_id=self.request_id,
                            tool_calls=self._drain_ollama_tool_calls(),
                        )
                        yield api_helpers.sse_format(completion_json, self.output_format)
                        finish_already_sent = True
                        break
                    continue

                # Text riding on a tool-call chunk is delivered to the client in
                # the same event, so it must also land in the captured result
                # (agent outputs / memory) like every other delivered token.
                if content_delta:
                    self.full_response_text += content_delta
                completion_json = api_helpers.build_response_json(
                    token=content_delta,
                    finish_reason=finish_reason,
                    request_id=self.request_id,
                    tool_calls=tool_calls_delta,
                )
                yield api_helpers.sse_format(completion_json, self.output_format)
                if finish_reason:
                    finish_already_sent = True
                    break
                continue

            content_from_remover = self.remover.process_delta(content_delta)
            content_to_yield = ""

            if self._should_buffer_for_prefixes and not self._prefixes_processed:
                self._prefix_buffer += content_from_remover

                buffer_full = len(self._prefix_buffer) >= self._prefix_buffer_limit
                is_done = finish_reason is not None

                should_process = False
                if requires_complex_buffering:
                    still_matching = (self._matches_partial_prefix(self._prefix_buffer)
                                      or self._reconstruction_pending_more_data(self._prefix_buffer))

                    if not still_matching:
                        should_process = True
                        logger.debug("Optimistic prefix match failed. Releasing buffer.")
                    elif buffer_full or is_done:
                        should_process = True
                        logger.debug("Buffer full or stream ended. Processing buffer.")

                elif trim_whitespace:
                    if self._prefix_buffer.strip() or is_done:
                         should_process = True
                else:
                    if buffer_full or is_done:
                        should_process = True

                if should_process:
                    content_to_yield = self._process_prefixes_from_buffer()
                    self._prefixes_processed = True
                    self._prefix_buffer = ""

            else:
                content_to_yield = content_from_remover

            if content_to_yield:
                self.full_response_text += content_to_yield
                completion_json = api_helpers.build_response_json(
                    token=content_to_yield, finish_reason=None,
                    request_id=self.request_id
                )
                yield api_helpers.sse_format(completion_json, self.output_format)

            if finish_reason:
                stream_finish_reason = finish_reason
                break

        if not finish_already_sent:
            # Finalization logic (ensuring buffer is cleared)
            final_content_to_yield = self._drain_pending_text(finalize_remover=True)

            if final_content_to_yield:
                self.full_response_text += final_content_to_yield
                completion_json = api_helpers.build_response_json(
                    token=final_content_to_yield, finish_reason=None,
                    request_id=self.request_id
                )
                yield api_helpers.sse_format(completion_json, self.output_format)

            # Tool calls accumulated for an Ollama front-end (the backend finished
            # on a text/empty chunk rather than on the tool-call chunk itself) ride
            # on the final done chunk, complete and in Ollama's native shape. None
            # for every other output format.
            accumulated_tool_calls = self._drain_ollama_tool_calls()

            liveness_tool_calls = None if saw_tool_calls else self._build_liveness_tool_calls()
            if liveness_tool_calls:
                logger.info("Liveness guard: response ended with no tool call while the task is "
                            "mid-flight; injecting the configured no-op tool call to keep the "
                            "frontend's agent loop alive.")
                liveness_json = api_helpers.build_response_json(
                    token="", finish_reason=None,
                    request_id=self.request_id,
                    tool_calls=liveness_tool_calls,
                )
                yield api_helpers.sse_format(liveness_json, self.output_format)

            final_finish_reason = "tool_calls" if (liveness_tool_calls or accumulated_tool_calls) \
                else (stream_finish_reason or "stop")
            final_completion_json = api_helpers.build_response_json(token="", finish_reason=final_finish_reason,
                                                                    request_id=self.request_id,
                                                                    tool_calls=accumulated_tool_calls)
            yield api_helpers.sse_format(final_completion_json, self.output_format)

        if self.output_format not in ('ollamagenerate', 'ollamaapichat'):
            yield api_helpers.sse_format("[DONE]", self.output_format)
