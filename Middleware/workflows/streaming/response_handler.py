# /Middleware/workflows/streaming/response_handler.py

import logging
from typing import Dict, Generator, Any, Optional, List

from Middleware.api import api_helpers
from Middleware.common import instance_global_variables
from Middleware.utilities.config_utils import get_current_username, get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from Middleware.utilities.streaming_utils import StreamingThinkRemover

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
        self.output_format = instance_global_variables.API_TYPE
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

        # NEW: Collect all prefixes that might need stripping for optimistic matching
        self._prefixes_to_strip = self._collect_prefixes()

        # Set buffer limit based on active custom removals (preserve original logic for compatibility)
        if self.workflow_custom_enabled and self.endpoint_custom_enabled:
            self._prefix_buffer_limit = 200
        elif self.workflow_custom_enabled or self.endpoint_custom_enabled:
            self._prefix_buffer_limit = 100
        else:
            self._prefix_buffer_limit = 100

        # Buffer if stripping is needed OR if reconstruction might be needed
        self._should_buffer_for_prefixes = self._is_prefix_stripping_needed() or (self.generation_prompt is not None)

    def _collect_prefixes(self) -> List[str]:
        """Collects all potential prefixes to strip from the configuration."""
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
        Optimistic matching: if it doesn't match any prefix partially, we can stop buffering.
        """
        # We must ignore leading whitespace in the buffer when checking for prefix matches
        lstripped_buffer = buffer.lstrip()

        if not lstripped_buffer:
            # Buffer is empty or only whitespace, keep buffering (might be leading whitespace before a prefix)
            return True

        for prefix in self._prefixes_to_strip:
            # Check if the prefix starts with the buffer content OR
            # if the buffer content starts with the prefix (buffer is longer than prefix)
            if prefix.startswith(lstripped_buffer) or lstripped_buffer.startswith(prefix):
                return True

        # If the buffer content doesn't match the start of any prefix, we are safe.
        return False

    def _is_prefix_stripping_needed(self) -> bool:
        """
        Checks if any prefix stripping logic is enabled in the configuration.
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
        """
        content = self._prefix_buffer

        # --- 1. Reconstruction Logic ---
        if self.generation_prompt and not self._reconstruction_applied:
            trimmed_prompt = self.generation_prompt.strip()
            content_lstripped = content.lstrip()

            # Check if the content starts with a word ending in a colon
            if content_lstripped:
                first_word = content_lstripped.split(' ', 1)[0]
                llm_has_prefix = first_word.endswith(':')
            else:
                llm_has_prefix = False

            if not llm_has_prefix:
                logger.debug(f"Reconstructing streaming group chat message. Prepended prompt: '{trimmed_prompt}'")
                content = f"{trimmed_prompt} {content_lstripped}"
                self._reconstruction_applied = True

        # --- 2. Stripping Logic (Sequential Application) ---
        content = content.lstrip()

        # Workflow-level Custom Text
        if self.workflow_custom_enabled:
             # Re-extracting here to maintain original priority order if defined in JSON list
            custom_texts = self.workflow_node_config.get("responseStartTextToRemove", [])
            if isinstance(custom_texts, str):
                custom_texts = [custom_texts]
            for custom_text in custom_texts:
                 if custom_text and content.startswith(custom_text):
                    content = content[len(custom_text):].lstrip()
                    # break instead of return, allowing subsequent rules to apply.
                    break

        # Endpoint-level Custom Text
        if self.endpoint_custom_enabled:
             # Re-extracting here to maintain original priority order
            custom_texts_endpoint = self.endpoint_config.get("responseStartTextToRemoveEndpointWide", [])
            if isinstance(custom_texts_endpoint, str):
                custom_texts_endpoint = [custom_texts_endpoint]
            for custom_text_raw in custom_texts_endpoint:
                custom_text = custom_text_raw.strip()
                if custom_text and content.startswith(custom_text):
                    content = content[len(custom_text):].lstrip()
                    # break instead of return, allowing subsequent rules to apply.
                    break

        # Timestamp
        if self.workflow_node_config.get("addDiscussionIdTimestampsForLLM", False):
            timestamp_text = "[Sent less than a minute ago]"
            if content.startswith(timestamp_text + " "):
                content = content[len(timestamp_text) + 1:].lstrip()
            elif content.startswith(timestamp_text):
                content = content[len(timestamp_text):].lstrip()

        # Assistant Prefix
        if get_is_chat_complete_add_user_assistant() and get_is_chat_complete_add_missing_assistant():
            if content.startswith("Assistant:"):
                content = content[len("Assistant:"):].lstrip()

        return content

    def process_stream(self, raw_dict_generator: Generator[Dict[str, Any], None, None]) -> Generator[str, None, None]:
        """
        Processes a raw dictionary stream from an LLM and yields formatted SSE strings.
        """
        # Determine buffering strategy
        requires_complex_buffering = self._requires_complex_buffering()
        trim_whitespace = self.endpoint_config.get("trimBeginningAndEndLineBreaks", False)

        for data_chunk in raw_dict_generator:
            content_delta = data_chunk.get("token") or ""
            finish_reason = data_chunk.get("finish_reason")

            content_from_remover = self.remover.process_delta(content_delta)
            content_to_yield = ""

            if self._should_buffer_for_prefixes and not self._prefixes_processed:
                self._prefix_buffer += content_from_remover

                # Optimized Buffering Logic
                buffer_full = len(self._prefix_buffer) >= self._prefix_buffer_limit
                is_done = finish_reason is not None

                # Determine if we should process the buffer now
                should_process = False
                if requires_complex_buffering:
                    # For complex logic, use optimistic matching.

                    # 1. Check if the buffer still matches any potential prefix
                    still_matching = self._matches_partial_prefix(self._prefix_buffer)

                    if not still_matching:
                        # Optimistic success: Buffer content definitively does not start with any prefix.
                        should_process = True
                        logger.debug("Optimistic prefix match failed. Releasing buffer.")
                    elif buffer_full or is_done:
                        # Pessimistic fallback: Buffer is full or stream ended, must process now.
                        should_process = True
                        logger.debug("Buffer full or stream ended. Processing buffer.")

                elif trim_whitespace:
                    # For whitespace trimming only, process as soon as we see a non-whitespace character or stream ends.
                    if self._prefix_buffer.strip() or is_done:
                         should_process = True
                else:
                    # Handle cases where buffering was only needed for potential reconstruction
                    if buffer_full or is_done:
                        should_process = True


                if should_process:
                    content_to_yield = self._process_prefixes_from_buffer()
                    self._prefixes_processed = True
                    self._prefix_buffer = "" # Clear buffer after processing

            else:
                content_to_yield = content_from_remover

            if content_to_yield:
                self.full_response_text += content_to_yield
                completion_json = api_helpers.build_response_json(
                    token=content_to_yield, finish_reason=None, current_username=get_current_username(),
                    request_id=self.request_id
                )
                yield api_helpers.sse_format(completion_json, self.output_format)

            if finish_reason:
                break

        # Finalization logic (ensuring buffer is cleared)
        final_content = self.remover.finalize()
        if self._should_buffer_for_prefixes and not self._prefixes_processed:
            self._prefix_buffer += final_content
            final_content_to_yield = self._process_prefixes_from_buffer()
            self._prefix_buffer = "" # Clear buffer
        else:
            final_content_to_yield = final_content

        if final_content_to_yield:
            self.full_response_text += final_content_to_yield
            completion_json = api_helpers.build_response_json(
                token=final_content_to_yield, finish_reason=None, current_username=get_current_username(),
                request_id=self.request_id
            )
            yield api_helpers.sse_format(completion_json, self.output_format)

        final_completion_json = api_helpers.build_response_json(token="", finish_reason="stop",
                                                                current_username=get_current_username(),
                                                                request_id=self.request_id)
        yield api_helpers.sse_format(final_completion_json, self.output_format)

        if self.output_format not in ('ollamagenerate', 'ollamaapichat'):
            yield api_helpers.sse_format("[DONE]", self.output_format)
