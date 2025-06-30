import logging
import re
from typing import Dict

logger = logging.getLogger(__name__)


class StreamingThinkRemover:
    """
    A stateful class to process a stream of text deltas and remove 'thinking' blocks.
    """

    def __init__(self, endpoint_config: Dict):
        self.remove_thinking = endpoint_config.get("removeThinking", False)
        self.think_tag = endpoint_config.get("thinkTagText", "think")
        self.expect_only_closing = endpoint_config.get("expectOnlyClosingThinkTag", False)
        self.opening_tag_window = endpoint_config.get("openingTagGracePeriod", 50)

        if self.remove_thinking:
            logger.debug(
                f"StreamingThinkRemover initialized. Mode: {'ClosingTagOnly' if self.expect_only_closing else 'Standard'}. "
                f"Tag: '{self.think_tag}', Grace Period: {self.opening_tag_window} chars."
            )

        self.close_tag_re = re.compile(f"</{re.escape(self.think_tag)}>" r"\s*(\n|$)", re.IGNORECASE)
        self.open_tag_re = re.compile(f"<{re.escape(self.think_tag)}\\b[^>]*>", re.IGNORECASE)

        self._buffer = ""
        self._in_think_block = False
        self._opening_tag_check_complete = False
        self._thinking_handled = False
        # NEW: Added to track the specific opening tag that was consumed
        self._consumed_open_tag = ""

    def process_delta(self, delta: str) -> str:
        """Processes an incoming text delta and returns the clean, yieldable text."""
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
                    content_to_yield = self._buffer[match.end():]
                    self._buffer = ""
        else:
            while True:
                original_buffer = self._buffer
                if self._in_think_block:
                    match = self.close_tag_re.search(self._buffer)
                    if match:
                        logger.debug("Closing think tag found. Resuming normal stream output.")
                        self._in_think_block = False
                        self._consumed_open_tag = ""  # Clear the saved tag
                        self._buffer = self._buffer[match.end():]
                    else:
                        # Not enough data for a full closing tag yet, wait for more deltas
                        break
                else:  # Not currently in a think block
                    if self._opening_tag_check_complete:
                        content_to_yield += self._buffer
                        self._buffer = ""
                        break

                    match = self.open_tag_re.search(self._buffer)
                    if match:
                        if match.start() <= self.opening_tag_window:
                            logger.debug("Opening think tag found within grace period. Entering think block.")
                            # Yield any text that came before the opening tag
                            content_to_yield += self._buffer[:match.start()]
                            self._in_think_block = True
                            # NEW: Save the exact opening tag we found
                            self._consumed_open_tag = match.group(0)
                            # Consume the opening tag from the buffer
                            self._buffer = self._buffer[match.end():]
                        else:
                            # An opening tag was found, but it was outside the grace period. Ignore it.
                            logger.debug(
                                "Opening tag found but it's outside the grace period. Disabling further checks.")
                            self._opening_tag_check_complete = True
                            content_to_yield += self._buffer
                            self._buffer = ""
                            break
                    elif len(self._buffer) > self.opening_tag_window:
                        logger.debug(
                            f"Grace period of {self.opening_tag_window} chars exceeded without finding opening tag.")
                        self._opening_tag_check_complete = True
                        content_to_yield += self._buffer
                        self._buffer = ""
                        break
                    else:
                        # Not enough data yet to exceed grace window, wait for more deltas
                        break

                # Failsafe to prevent infinite loops on malformed input
                if self._buffer == original_buffer:
                    break
        return content_to_yield

    def finalize(self) -> str:
        """Returns any remaining text from the buffer at the end of the stream."""
        if not self.remove_thinking:
            return ""

        # --- MODIFIED LOGIC ---
        if self._in_think_block:
            logger.warning("Finalizing stream while in an unterminated think block. Flushing buffer as-is.")
            # Prepend the original opening tag to the buffer to meet the requirement
            return self._consumed_open_tag + self._buffer
        # --- END MODIFIED LOGIC ---

        # Handle the edge case where we expected a closing tag but never got one
        if self.expect_only_closing and not self._thinking_handled:
            logger.warning(
                "Finalizing stream in 'expectOnlyClosing' mode without ever finding a closing tag. Discarding buffer.")
            return ""

        if self._buffer:
            logger.debug("Finalizing stream, flushing remaining buffer.")
        return self._buffer


def remove_thinking_from_text(text: str, endpoint_config: Dict) -> str:
    """A stateless function to remove thinking blocks from a complete string."""
    if not endpoint_config.get("removeThinking", False):
        return text

    think_tag = endpoint_config.get("thinkTagText", "think")
    logger.debug(f"Processing non-streaming text to remove thinking block with tag: '{think_tag}'.")

    close_tag_re = re.compile(f"</{re.escape(think_tag)}>" r"\s*(\n|$)", re.IGNORECASE)

    if endpoint_config.get("expectOnlyClosingThinkTag", False):
        match = close_tag_re.search(text)
        if match:
            logger.debug("Non-streaming 'ClosingTagOnly' mode: Found closing tag, removing preceding text.")
            return text[match.end():]
        else:
            logger.debug(
                "Non-streaming 'ClosingTagOnly' mode: No closing tag found, returning empty string as per logic.")
            return ""
    else:
        open_tag_re = re.compile(f"<{re.escape(think_tag)}\\b[^>]*>", re.IGNORECASE)
        opening_tag_window = endpoint_config.get("openingTagGracePeriod", 50)

        # Search for the opening tag only within the grace window at the start of the text
        open_match = open_tag_re.search(text, 0, opening_tag_window)
        if not open_match:
            logger.debug("Non-streaming: No opening tag found in grace period. Returning original text.")
            return text

        # Search for the closing tag anywhere *after* the opening tag
        close_match = close_tag_re.search(text, open_match.end())
        if not close_match:
            logger.debug("Non-streaming: Found opening tag but no closing tag. Returning original text as-is.")
            return text

        logger.debug("Non-streaming: Found and removed full thinking block.")
        # Reconstruct the string without the thinking block and its tags
        return text[:open_match.start()] + text[close_match.end():]