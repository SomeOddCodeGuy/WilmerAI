import logging
import re
from typing import Dict

logger = logging.getLogger(__name__)


class StreamingThinkRemover:
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

        self.close_tag_re = re.compile(
            f"^\\s*</{re.escape(self.think_tag)}>" r"\s*(\n|$)", re.IGNORECASE | re.MULTILINE
        )
        self.open_tag_re = re.compile(f"<{re.escape(self.think_tag)}\\b[^>]*>", re.IGNORECASE)

        self._buffer = ""
        self._in_think_block = False
        self._opening_tag_check_complete = False
        self._thinking_handled = False
        self._consumed_open_tag = ""

    def process_delta(self, delta: str) -> str:
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
                            self._in_think_block = True
                            self._consumed_open_tag = match.group(0)
                            self._buffer = self._buffer[match.end():]
                        else:
                            logger.debug(
                                "Opening tag found but it's outside the grace period. Disabling further checks."
                            )
                            self._opening_tag_check_complete = True
                            content_to_yield += self._buffer
                            self._buffer = ""
                            break
                    elif len(self._buffer) > self.opening_tag_window:
                        logger.debug(
                            f"Grace period of {self.opening_tag_window} chars exceeded without finding opening tag."
                        )
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
        if not self.remove_thinking:
            return ""

        if self._in_think_block:
            match = self.close_tag_re.search(self._buffer)
            if match:
                logger.debug("Found and processed closing tag during finalization.")
                return self._buffer[match.end():]

            logger.warning("Finalizing stream while in an unterminated think block. Flushing buffer as-is.")
            return self._consumed_open_tag + self._buffer

        if self.expect_only_closing and not self._thinking_handled:
            logger.warning(
                "Finalizing stream in 'expectOnlyClosing' mode without ever finding a closing tag. Discarding buffer."
            )
            return ""

        if self._buffer:
            logger.debug("Finalizing stream, flushing remaining buffer.")
        return self._buffer


def remove_thinking_from_text(text: str, endpoint_config: Dict) -> str:
    if not endpoint_config.get("removeThinking", False):
        return text

    think_tag = endpoint_config.get("thinkTagText", "think")
    logger.debug(f"Processing non-streaming text to remove thinking block with tag: '{think_tag}'.")

    close_tag_re = re.compile(
        f"^\\s*</{re.escape(think_tag)}>" r"\s*(\n|$)", re.IGNORECASE | re.MULTILINE
    )

    if endpoint_config.get("expectOnlyClosingThinkTag", False):
        match = close_tag_re.search(text)
        if match:
            logger.debug("Non-streaming 'ClosingTagOnly' mode: Found closing tag, removing preceding text.")
            return text[match.end():]
        else:
            logger.debug(
                "Non-streaming 'ClosingTagOnly' mode: No closing tag found, returning empty string as per logic."
            )
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
            logger.debug("Non-streaming: Found opening tag but no closing tag. Returning original text as-is.")
            return text

        logger.debug("Non-streaming: Found and removed full thinking block.")
        return text[close_match.end():]