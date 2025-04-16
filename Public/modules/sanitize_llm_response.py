import json
import logging
import re

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
    cleaned_text = text.replace("|{{|", "{").replace("|}}}|", "}").replace("|}}|", "}")
    
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
        text: The LLM response text to sanitize
        
    Returns:
        Sanitized text
    """
    logger.info("LLM response sanitizer invoked")
    
    if not text or not isinstance(text, str):
        logger.warning(f"Invalid input: {type(text)}")
        return text
    
    return sanitize_json_markers(text) 