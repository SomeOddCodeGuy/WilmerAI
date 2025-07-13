# middleware/utilities/streaming_utils.py

import logging
import re
from typing import Dict

logger = logging.getLogger(__name__)


class StreamingThinkRemover:
    """
    A stateful class to process a stream of text and remove 'thinking' blocks.

    This class is designed to handle text arriving in chunks (deltas). It maintains an
    internal buffer and state to identify and strip out content enclosed within
    configurable tags (e.g., `<think>...</think>`). It supports multiple modes,
    including standard open/close tag removal and a mode that only looks for a
    closing tag.
    """

    def __init__(self, endpoint_config: Dict):
        """
        Initializes the StreamingThinkRemover.

        Args:
            endpoint_config (Dict): Configuration dictionary that specifies how
                thinking blocks should be handled. Expected keys include:
                - "removeThinking" (bool): Master switch to enable/disable the feature.
                - "thinkTagText" (str): The name of the tag (e.g., "think").
                - "expectOnlyClosingThinkTag" (bool): If True, only looks for the closing tag.
                - "openingTagGracePeriod" (int): Character window at the start of the
                  stream to look for an opening tag.
        """
        self.remove_thinking = endpoint_config.get("removeThinking", False)
        self.think_tag = endpoint_config.get("thinkTagText", "think")
        self.expect_only_closing = endpoint_config.get("expectOnlyClosingThinkTag", False)
        self.opening_tag_window = endpoint_config.get("openingTagGracePeriod", 50)

        if self.remove_thinking:
            logger.debug(
                f"StreamingThinkRemover initialized. Mode: {'ClosingTagOnly' if self.expect_only_closing else 'Standard'}. "
                f"Tag: '{self.think_tag}', Grace Period: {self.opening_tag_window} chars."
            )

        # This regex is specifically designed for streaming: it only matches if a
        # newline character follows the tag, preventing premature matches on partial chunks.
        self.close_tag_re = re.compile(f"</{re.escape(self.think_tag)}>" r"\s*\n", re.IGNORECASE)
        self.open_tag_re = re.compile(f"<{re.escape(self.think_tag)}\\b[^>]*>", re.IGNORECASE)

        self._buffer = ""
        self._in_think_block = False
        self._opening_tag_check_complete = False
        self._thinking_handled = False
        self._consumed_open_tag = ""

    def process_delta(self, delta: str) -> str:
        """
        Processes an incoming chunk of text from the stream.

        This method appends the delta to an internal buffer and applies the configured
        tag removal logic. It yields text that is determined to be outside of any
        thinking blocks.

        Args:
            delta (str): The next chunk of text from the stream.

        Returns:
            str: The portion of the text to be yielded to the client after processing.
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
                    logger.debug("Closing tag followed by newline found in 'expectOnlyClosing' mode.")
                    self._thinking_handled = True
                    content_to_yield = self._buffer[match.end():]
                    self._buffer = ""
        else:
            while True:
                original_buffer = self._buffer
                if self._in_think_block:
                    match = self.close_tag_re.search(self._buffer)
                    if match:
                        logger.debug("Valid closing think tag (followed by newline) found.")
                        self._in_think_block = False
                        self._consumed_open_tag = ""
                        self._buffer = self._buffer[match.end():]
                    else:
                        break
                else:
                    if self._opening_tag_check_complete:
                        content_to_yield += self._buffer
                        self._buffer = ""
                        break

                    match = self.open_tag_re.search(self._buffer)
                    if match:
                        if match.start() <= self.opening_tag_window:
                            logger.debug("Opening think tag found within grace period. Entering think block.")
                            content_to_yield += self._buffer[:match.start()]
                            self._in_think_block = True
                            self._consumed_open_tag = match.group(0)
                            self._buffer = self._buffer[match.end():]
                        else:
                            logger.debug(
                                "Opening tag found but it's outside the grace period. Disabling further checks.")
                            self._opening_tag_check_complete = True
                            content_to_yield += self._buffer
                            self._buffer = ""
                            break
                    elif len(self._buffer) > self.opening_tag_window:
                        logger.debug(f"Grace period of {self.opening_tag_window} chars exceeded.")
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
        Finalizes the stream processing and returns any remaining buffered text.

        This should be called after the stream has ended. It handles edge cases,
        such as an unterminated think block, and flushes any content remaining
        in the buffer.

        Returns:
            str: The final, flushed content from the buffer.
        """
        if not self.remove_thinking:
            return ""

        if self._in_think_block:
            logger.warning("Finalizing stream while in an unterminated think block. Flushing buffer as-is.")
            return self._consumed_open_tag + self._buffer

        if self.expect_only_closing and not self._thinking_handled:
            logger.warning("Finalizing stream in 'expectOnlyClosing' mode without ever finding a closing tag.")
            return ""

        if self._buffer:
            logger.debug("Finalizing stream, flushing remaining buffer.")
        return self._buffer


def remove_thinking_from_text(text: str, endpoint_config: Dict) -> str:
    """
    A stateless function to remove a thinking block from a complete string.

    This utility operates on a fully formed text string, using regular expressions
    to find and remove content within the configured thinking tags. Unlike the
    streaming class, this function can safely look for a newline or the end of
    the string as a valid terminator for the closing tag.

    Args:
        text (str): The complete input string to process.
        endpoint_config (Dict): Configuration specifying the thinking tag behavior.

    Returns:
        str: The processed text with the thinking block removed, or the original
             text if no valid block was found.
    """
    if not endpoint_config.get("removeThinking", False):
        return text

    think_tag = endpoint_config.get("thinkTagText", "think")
    logger.debug(f"Processing non-streaming text to remove thinking block with tag: '{think_tag}'.")

    # This regex is for non-streaming contexts where the full text is available.
    # It can safely check for a newline OR the absolute end of the string (\Z).
    close_tag_re = re.compile(f"</{re.escape(think_tag)}>" r"(?:\s*\n|\s*\Z)", re.IGNORECASE)

    if endpoint_config.get("expectOnlyClosingThinkTag", False):
        match = close_tag_re.search(text)
        if match:
            logger.debug("Non-streaming 'ClosingTagOnly' mode: Found valid closing tag.")
            return text[match.end():]
        else:
            logger.debug("Non-streaming 'ClosingTagOnly' mode: No valid closing tag found.")
            return ""
    else:
        open_tag_re = re.compile(f"<{re.escape(think_tag)}\\b[^>]*>", re.IGNORECASE)
        opening_tag_window = endpoint_config.get("openingTagGracePeriod", 50)

        open_match = open_tag_re.search(text, 0, opening_tag_window)
        if not open_match:
            logger.debug("Non-streaming: No opening tag found in grace period. Returning original text.")
            return text

        close_match = close_tag_re.search(text, open_match.end())
        if not close_match:
            logger.debug("Non-streaming: Found opening tag but no valid closing tag. Returning original text.")
            return text

        logger.debug("Non-streaming: Found and removed full thinking block.")
        return text[:open_match.start()] + text[close_match.end():]