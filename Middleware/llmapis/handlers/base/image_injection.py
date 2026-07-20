# Middleware/llmapis/handlers/base/image_injection.py
#
# Shared image-injection machinery for the chat handlers that convert the
# internal per-message "images" key into API-specific multimodal content blocks
# (OpenAI and Claude). The block format stays in each handler's
# _process_single_image_source; this module owns the shared traversal and the
# text-only fallback used when image processing fails.

import logging
import traceback
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Appended to the last user message when image processing fails. This text is
# API-visible payload content shared verbatim by both handlers.
_IMAGE_ERROR_NOTE = ("\n\n[System note: There was an error processing the provided image(s). "
                     "I will respond based on the text alone.]")


def inject_images_into_messages(messages: List[Dict[str, Any]],
                                to_image_block: Callable[[str], Optional[Dict]],
                                images_first: bool,
                                api_label: str,
                                missing_user_fallback_text: str) -> List[Dict[str, Any]]:
    """Converts each user message's 'images' key into multimodal content blocks.

    Messages without images pass through untouched. For each user message with
    images, the string content is wrapped in a text block and the converted
    image blocks are placed before or after it. Any error during processing
    reverts the whole conversation to text-only via build_text_only_fallback.

    Args:
        messages (List[Dict[str, Any]]): The messages built by the base handler.
        to_image_block (Callable[[str], Optional[Dict]]): The handler's converter
            from one image source string to an API content block (None to skip).
        images_first (bool): True to place image blocks before the text block
            (Claude recommends images first), False to place them after.
        api_label (str): API name used in the error log message.
        missing_user_fallback_text (str): API-visible fallback message content,
            used only when the failed conversation has no trailing user message.

    Returns:
        List[Dict[str, Any]]: The messages with images converted, or the
        text-only fallback conversation when processing failed.
    """
    try:
        if not any("images" in msg for msg in messages):
            return messages

        for msg in messages:
            if msg.get("role") == "user" and "images" in msg:
                image_list = msg.pop("images")
                image_blocks = []
                for img_source in image_list:
                    block = to_image_block(img_source)
                    if block:
                        image_blocks.append(block)

                if image_blocks:
                    if isinstance(msg["content"], str):
                        msg["content"] = [{"type": "text", "text": msg["content"]}]
                    if images_first:
                        msg["content"] = image_blocks + msg["content"]
                    else:
                        msg["content"] = msg["content"] + image_blocks

        for msg in messages:
            msg.pop("images", None)

        return messages

    except Exception as e:
        logger.error(f"Critical error during {api_label} image processing: {e}\n{traceback.format_exc()}")
        return build_text_only_fallback(messages, missing_user_fallback_text)


def build_text_only_fallback(messages: List[Dict[str, Any]],
                             missing_user_fallback_text: str) -> List[Dict[str, Any]]:
    """Creates a safe, text-only conversation when image processing fails.

    Cleans up any partially modified multimodal messages, reverting them to
    simple text, then appends a system note to the last user message informing
    the model that the image could not be processed.

    Args:
        messages (List[Dict[str, Any]]): The message list, possibly in a
            corrupted multimodal state.
        missing_user_fallback_text (str): Content for the user message appended
            when the conversation does not end with a user message.

    Returns:
        List[Dict[str, Any]]: A cleaned, text-only message list with an error
        notification.
    """
    for msg in messages:
        msg.pop("images", None)
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            text_content = next((item.get("text", "") for item in msg["content"] if item.get("type") == "text"), "")
            msg["content"] = text_content

    if messages and messages[-1].get("role") == "user":
        messages[-1]["content"] += _IMAGE_ERROR_NOTE
    else:
        messages.append({"role": "user", "content": missing_user_fallback_text})
    return messages
