import json
import logging
import re

# Import the aggregation utility
from workflow_utils import aggregate_generator_input

logger = logging.getLogger(__name__)

def sanitize_json_markers(text):
    """
    Remove problematic markers from LLM JSON output.
    
    Args:
        text: The text containing potentially malformed JSON with markers
        
    Returns:
        Cleaned text with markers removed
    """
    logger.info(f"Sanitizing text: {text[:100]}...")
    
    # Replace the problematic markers
    cleaned_text = text.replace("|{{", "{").replace("|}}}|", "}").replace("|}}", "}")
    
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
    """
    Main entry point for the sanitization module.
    
    Args:
        text: The LLM response text to sanitize (might be a generator).
        
    Returns:
        Sanitized text (string).
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