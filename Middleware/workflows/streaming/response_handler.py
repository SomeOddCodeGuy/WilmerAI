# /Middleware/workflows/streaming/response_handler.py

import logging
from typing import Dict, Generator, Any, Optional

from Middleware.api import api_helpers
from Middleware.common import instance_global_variables
from Middleware.utilities.config_utils import get_current_username, get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant
from Middleware.utilities.streaming_utils import StreamingThinkRemover

logger = logging.getLogger(__name__)


class StreamingResponseHandler:
    """
    Handles the processing and formatting of a raw LLM stream into a
    client-facing Server-Sent Event (SSE) stream.
    """

    def __init__(self, endpoint_config: Dict, workflow_node_config: Dict, generation_prompt: Optional[str] = None):
        """
        Initializes the StreamingResponseHandler.

        Args:
            endpoint_config (Dict): Configuration dictionary for the API endpoint.
            workflow_node_config (Dict): Configuration dictionary for the specific workflow node.
            generation_prompt (Optional[str]): The generation prompt used, if any (for group chat logic).
        """
        self.endpoint_config = endpoint_config
        self.workflow_node_config = workflow_node_config
        self.output_format = instance_global_variables.API_TYPE
        self.remover = StreamingThinkRemover(self.endpoint_config)
        self.full_response_text = ""

        # Store the generation prompt and state for reconstruction
        self.generation_prompt = generation_prompt
        self._reconstruction_applied = False

        # State for prefix removal
        self._prefix_buffer = ""
        self._prefixes_processed = False

        self.workflow_custom_enabled = self.workflow_node_config.get("removeCustomTextFromResponseStart", False)
        self.endpoint_custom_enabled = self.endpoint_config.get("removeCustomTextFromResponseStartEndpointWide", False)

        # Set buffer limit based on active custom removals
        if self.workflow_custom_enabled and self.endpoint_custom_enabled:
            self._prefix_buffer_limit = 200
        elif self.workflow_custom_enabled or self.endpoint_custom_enabled:
            self._prefix_buffer_limit = 100
        else:
            self._prefix_buffer_limit = 100

        # Buffer if stripping is needed OR if reconstruction might be needed
        self._should_buffer_for_prefixes = self._is_prefix_stripping_needed() or (self.generation_prompt is not None)

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

    def _process_prefixes_from_buffer(self) -> str:
        """
        Processes the accumulated prefix buffer to apply group chat reconstruction
        and then remove all configured prefixes.
        """
        content = self._prefix_buffer

        # --- 1. Reconstruction Logic (New Behavior First) ---
        if self.generation_prompt and not self._reconstruction_applied:
            trimmed_prompt = self.generation_prompt.strip()
            content_lstripped = content.lstrip()

            # Check if the content starts with a word ending in a colon
            first_word = content_lstripped.split(' ', 1)[0]
            llm_has_prefix = first_word.endswith(':')

            if not llm_has_prefix:
                logger.debug(f"Reconstructing streaming group chat message. Prepended prompt: '{trimmed_prompt}'")
                # Prepend the prompt. If content was only whitespace, this results in "Prompt ".
                # Otherwise, it's "Prompt content".
                content = f"{trimmed_prompt} {content_lstripped}"
                self._reconstruction_applied = True  # Flag that we have performed this action

        # --- 2. Stripping Logic (Existing Behavior on potentially modified content) ---
        content = content.lstrip()

        # Workflow-level Custom Text
        if self.workflow_custom_enabled:
            custom_texts = self.workflow_node_config.get("responseStartTextToRemove", [])
            if isinstance(custom_texts, str):
                custom_texts = [custom_texts]
            for custom_text in custom_texts:
                if custom_text and content.startswith(custom_text):
                    content = content[len(custom_text):].lstrip()
                    break

        # Endpoint-level Custom Text
        if self.endpoint_custom_enabled:
            custom_texts_endpoint = self.endpoint_config.get("responseStartTextToRemoveEndpointWide", [])
            if isinstance(custom_texts_endpoint, str):
                custom_texts_endpoint = [custom_texts_endpoint]
            for custom_text_raw in custom_texts_endpoint:
                custom_text = custom_text_raw.strip()
                if custom_text and content.startswith(custom_text):
                    content = content[len(custom_text):].lstrip()
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
        for data_chunk in raw_dict_generator:
            content_delta = data_chunk.get("token") or ""
            finish_reason = data_chunk.get("finish_reason")

            content_from_remover = self.remover.process_delta(content_delta)
            content_to_yield = ""

            if self._should_buffer_for_prefixes and not self._prefixes_processed:
                self._prefix_buffer += content_from_remover
                if len(self._prefix_buffer) >= self._prefix_buffer_limit or finish_reason:
                    content_to_yield = self._process_prefixes_from_buffer()
                    self._prefixes_processed = True
            else:
                content_to_yield = content_from_remover

            if content_to_yield:
                self.full_response_text += content_to_yield
                completion_json = api_helpers.build_response_json(
                    token=content_to_yield, finish_reason=None, current_username=get_current_username()
                )
                yield api_helpers.sse_format(completion_json, self.output_format)

            if finish_reason:
                break

        final_content = self.remover.finalize()
        if self._should_buffer_for_prefixes and not self._prefixes_processed:
            self._prefix_buffer += final_content
            final_content_to_yield = self._process_prefixes_from_buffer()
        else:
            final_content_to_yield = final_content

        if final_content_to_yield:
            self.full_response_text += final_content_to_yield
            completion_json = api_helpers.build_response_json(
                token=final_content_to_yield, finish_reason=None, current_username=get_current_username()
            )
            yield api_helpers.sse_format(completion_json, self.output_format)

        final_completion_json = api_helpers.build_response_json(token="", finish_reason="stop",
                                                                current_username=get_current_username())
        yield api_helpers.sse_format(final_completion_json, self.output_format)

        if self.output_format not in ('ollamagenerate', 'ollamaapichat'):
            yield api_helpers.sse_format("[DONE]", self.output_format)
