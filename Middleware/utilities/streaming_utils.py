# /Middleware/utilities/streaming_utils.py

import logging
import re
import time
from typing import Any, Dict, Generator

logger = logging.getLogger(__name__)


def stream_static_content(content: str) -> Generator[Dict[str, Any], None, None]:
    """
    A generator that yields a static string token by token (words and whitespace)
    to simulate a stream. This preserves all original formatting like newlines.
    This mimics the raw output format of an LLM API handler.
    """
    # Use re.split to split by whitespace while keeping the delimiters (whitespace).
    # This ensures that newlines, tabs, and multiple spaces are preserved.
    tokens = re.split(r'(\s+)', content)

    if not tokens:
        yield {'token': '', 'finish_reason': 'stop'}
        return

    words_per_second = 50
    delay = 1.0 / words_per_second

    for token in tokens:
        # Don't process empty strings that can result from re.split
        if token:
            # Only sleep for actual words, not for whitespace, to make the stream feel natural.
            if not token.isspace():
                time.sleep(delay)
            # Yield the token (which could be a word or whitespace like ' ' or '\n\n')
            yield {'token': token, 'finish_reason': None}

    # Signal the end of the stream
    yield {'token': '', 'finish_reason': 'stop'}


class StreamingThinkRemover:
    """
    A stateful class to remove "thinking" blocks from a streaming LLM response.
    """

    def __init__(self, endpoint_config: Dict):
        """
        Initializes the StreamingThinkRemover.

        Args:
            endpoint_config (Dict): The configuration dictionary for the LLM endpoint.
        """
        self.remove_thinking = endpoint_config.get("removeThinking", False)

        self.start_think_tag = endpoint_config.get("startThinkTag", "")
        self.end_think_tag = endpoint_config.get("endThinkTag", "")

        self.expect_only_closing = endpoint_config.get("expectOnlyClosingThinkTag", False)
        self.opening_tag_window = endpoint_config.get("openingTagGracePeriod", 100)

        if self.remove_thinking:
            if not self.start_think_tag or not self.end_think_tag:
                logger.warning(
                    "removeThinking is true, but 'startThinkTag' or 'endThinkTag' is missing in config. Disabling feature.")
                self.remove_thinking = False
            else:
                logger.debug(
                    f"StreamingThinkRemover initialized. Mode: {'ClosingTagOnly' if self.expect_only_closing else 'Standard'}. "
                    f"Start Tag: '{self.start_think_tag}', End Tag: '{self.end_think_tag}'"
                )
                self.open_tag_re = re.compile(re.escape(self.start_think_tag), re.IGNORECASE)
                self.close_tag_re = re.compile(re.escape(self.end_think_tag), re.IGNORECASE)

        self._buffer = ""
        self._in_think_block = False
        self._opening_tag_check_complete = False
        self._thinking_handled = False
        self._consumed_open_tag = ""

    def process_delta(self, delta: str) -> str:
        """
        Processes a single chunk of text from a streaming response.

        Args:
            delta (str): The incoming text chunk from the LLM stream.

        Returns:
            str: The processed text chunk, with thinking blocks removed as they are detected.
        """
        if not self.remove_thinking:
            return delta

        self._buffer += delta
        content_to_yield = ""

        if self.expect_only_closing:
            if self._thinking_handled:
                content_to_yield = self._buffer
                self._buffer = ""
            else:
                match = self.close_tag_re.search(self._buffer)
                if match:
                    logger.debug("Closing tag found in 'expectOnlyClosing' mode. Discarding preceding content.")
                    self._thinking_handled = True
                    content_to_yield = self._buffer[match.end():]  # type: ignore
                    self._buffer = ""
        else:
            while True:
                original_buffer = self._buffer
                if self._in_think_block:
                    match = self.close_tag_re.search(self._buffer)
                    if match:
                        logger.debug("Closing think tag found. Resuming normal stream output.")
                        self._in_think_block = False
                        self._consumed_open_tag = ""
                        self._buffer = self._buffer[match.end():]  # type: ignore
                    else:
                        break
                else:
                    if self._opening_tag_check_complete:
                        content_to_yield += self._buffer
                        self._buffer = ""
                        break

                    match = self.open_tag_re.search(self._buffer)
                    if match:
                        if not self._opening_tag_check_complete and match.start() <= self.opening_tag_window:  # type: ignore
                            logger.debug("Opening think tag found within grace period. Entering think block.")
                            content_to_yield += self._buffer[:match.start()]  # type: ignore
                            self._in_think_block = True
                            self._consumed_open_tag = match.group(0)  # type: ignore
                            self._buffer = self._buffer[match.end():]  # type: ignore
                        else:
                            logger.debug(
                                "Opening tag found but it's outside the grace period. Disabling further checks.")
                            self._opening_tag_check_complete = True
                            content_to_yield += self._buffer
                            self._buffer = ""
                            break
                    elif len(self._buffer) > self.opening_tag_window and not self._opening_tag_check_complete:
                        logger.debug(
                            f"Grace period of {self.opening_tag_window} chars exceeded without finding opening tag.")
                        self._opening_tag_check_complete = True
                        content_to_yield += self._buffer
                        self._buffer = ""
                        break
                    else:
                        break

                if self._buffer == original_buffer:
                    break
        return content_to_yield

    def finalize(self) -> str:
        """
        Finalizes the stream, processing any remaining buffered text.

        This should be called after the stream has ended to flush any remaining
        content, especially in cases of unterminated thinking blocks.

        Returns:
            str: The final, cleaned-up text remaining in the buffer.
        """
        if not self.remove_thinking:
            return self._buffer

        if self.expect_only_closing and not self._thinking_handled:
            logger.warning(
                "Finalizing stream in 'expectOnlyClosing' mode without ever finding a closing tag. Returning buffered content.")
            return self._buffer

        if self._in_think_block:
            match = self.close_tag_re.search(self._buffer)
            if match:
                logger.debug("Found and processed closing tag during finalization.")
                return self._buffer[match.end():]

            logger.warning("Finalizing stream while in an unterminated think block. Flushing buffer as-is.")
            return self._consumed_open_tag + self._buffer

        return self._buffer


def remove_thinking_from_text(text: str, endpoint_config: Dict) -> str:
    """
    Removes a thinking block from a complete, non-streamed string.

    Args:
        text (str): The complete LLM response text.
        endpoint_config (Dict): The configuration dictionary for the LLM endpoint.

    Returns:
        str: The text with the thinking block removed, or the original text if
                 the removal conditions are not met.
    """
    if not endpoint_config.get("removeThinking", False) or not text:
        return text

    start_think_tag = endpoint_config.get("startThinkTag", "")
    end_think_tag = endpoint_config.get("endThinkTag", "")
    expect_only_closing = endpoint_config.get("expectOnlyClosingThinkTag", False)
    grace_period = endpoint_config.get("openingTagGracePeriod", 100)

    if not start_think_tag or not end_think_tag:
        return text

    close_tag_re = re.compile(re.escape(end_think_tag), re.IGNORECASE)

    if expect_only_closing:
        match = close_tag_re.search(text)
        if match:
            logger.debug("Non-streaming 'ClosingTagOnly' mode: Found closing tag, removing preceding text.")
            return text[match.end():]  # type: ignore
        else:
            logger.debug("Non-streaming 'ClosingTagOnly' mode: No closing tag found, returning original text.")
            return text
    else:
        open_tag_re = re.compile(re.escape(start_think_tag), re.IGNORECASE)
        open_match = open_tag_re.search(text, 0, min(len(text), grace_period))
        if not open_match:
            logger.debug("Non-streaming: No opening tag found in grace period. Returning original text.")
            return text

        close_match = close_tag_re.search(text, open_match.end())  # type: ignore
        if not close_match:
            logger.debug("Non-streaming: Found opening tag but no closing tag. Returning original text as-is.")
            return text

        logger.debug("Non-streaming: Found and removed full thinking block.")
        return text[:open_match.start()] + text[close_match.end():]  # type: ignore


def post_process_llm_output(text: str, endpoint_config: Dict, workflow_node_config: Dict) -> str:
    """
    Cleans and formats a complete, non-streamed LLM output string.

    This function applies a series of sequential cleaning rules, such as removing
    thinking tags, custom prefixes, and standard boilerplate text.

    Args:
        text (str): The raw, complete LLM response.
        endpoint_config (Dict): The configuration for the LLM endpoint.
        workflow_node_config (Dict): The configuration for the specific workflow node.

    Returns:
        str: The cleaned and formatted output text.
    """
    from Middleware.api import api_helpers
    from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
        get_is_chat_complete_add_missing_assistant

    processed_text = remove_thinking_from_text(text, endpoint_config)
    content = processed_text.lstrip()

    if workflow_node_config.get("removeCustomTextFromResponseStart", False):
        custom_texts = workflow_node_config.get("responseStartTextToRemove", [])
        if isinstance(custom_texts, str):
            custom_texts = [custom_texts]

        for custom_text in custom_texts:
            if custom_text and content.startswith(custom_text):
                content = content[len(custom_text):].lstrip()
                break

    if endpoint_config.get("removeCustomTextFromResponseStartEndpointWide", False):
        custom_texts_endpoint = endpoint_config.get("responseStartTextToRemoveEndpointWide", [])
        if isinstance(custom_texts_endpoint, str):
            custom_texts_endpoint = [custom_texts_endpoint]

        for custom_text_raw in custom_texts_endpoint:
            custom_text = custom_text_raw.strip()

            if custom_text and content.startswith(custom_text):
                content = content[len(custom_text):].lstrip()
                break

    if workflow_node_config.get("addDiscussionIdTimestampsForLLM", False):
        timestamp_text = "[Sent less than a minute ago]"
        if content.startswith(timestamp_text + " "):
            content = content[len(timestamp_text) + 1:].lstrip()
        elif content.startswith(timestamp_text):
            content = content[len(timestamp_text):].lstrip()

    should_remove_assistant = (get_is_chat_complete_add_user_assistant() and
                               get_is_chat_complete_add_missing_assistant())
    if should_remove_assistant and content.startswith("Assistant:"):
        content = api_helpers.remove_assistant_prefix(content)

    logger.info(f"--- POST-CLEANING TEXT ---\n{content}\n-------------------------")

    if endpoint_config.get("trimBeginningAndEndLineBreaks", False):
        return content.strip()

    return content
