import json
import logging
import re

# Import the aggregation utility
from Public.workflow_python_scripts._isevendays_mcp_scripts.workflow_utils import aggregate_generator_input
from Middleware.utilities.text_utils import return_brackets_in_string

logger = logging.getLogger(__name__)

def sanitize_json_markers(text):
    """Remove problematic markers from LLM JSON output.

    Args:
        text (str): The text containing potentially malformed JSON with markers.

    Returns:
        str: Cleaned text with markers removed.
    """
    logger.info(f"Sanitizing text: {text[:100]}...")

    # Restore curly braces that Wilmer escaped to sentinel tokens on the way in
    # (text_utils.escape_brackets_in_string) so the JSON parses. Delegating to the
    # canonical helper keeps this in step with the sentinel if it ever changes.
    cleaned_text = return_brackets_in_string(text)

    # Also clean up any extra whitespace at the beginning that might break JSON parsing
    cleaned_text = cleaned_text.strip()
    
    # Log the difference if changes were made
    if cleaned_text != text:
        logger.info(f"Text was sanitized. Original length: {len(text)}, new length: {len(cleaned_text)}")
        logger.debug(f"Sanitized text: {cleaned_text[:100]}...")
    else:
        logger.info("No sanitization needed")
    
    return cleaned_text

def Invoke(text, **kwargs):
    """Main entry point for the sanitization module.

    Args:
        text (str): The LLM response text to sanitize (might be a generator).

    Returns:
        str: Sanitized text.
    """
    logger.info("LLM response sanitizer invoked")
    
    # --- Workaround Start --- 
    # Aggregate input if it's a generator from a previous streaming step
    processed_text = aggregate_generator_input(text)
    # --- Workaround End --- 

    if not processed_text or not isinstance(processed_text, str):
        logger.warning(f"Invalid input after aggregation: {type(processed_text)}")
        # Return original aggregated input or empty string if aggregation failed
        return processed_text if isinstance(processed_text, str) else ""
    
    return sanitize_json_markers(processed_text) 