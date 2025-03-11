import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional

logger = logging.getLogger(__name__)


def _resolve_case_insensitive_path(path_str: str) -> Optional[Path]:
    """
    Resolves the correct casing of a file in a case-insensitive manner.
    - If the exact file exists, return it.
    - If a case-insensitive match exists, return the first match found.
    - If multiple matches exist, prioritize an exact match before falling back.
    Args:
        path_str (str): The path to resolve.
    Returns:
        Optional[Path]: The resolved path if found, otherwise None.
    """
    file_path = Path(path_str)
    if file_path.exists():
        return file_path
    parent_dir = file_path.parent
    target_filename = file_path.name
    if not parent_dir.exists():
        return None
    entries = {p.name.lower(): p for p in parent_dir.iterdir()}
    matched_path = entries.get(target_filename.lower())
    return matched_path if matched_path else None


def ensure_json_file_exists(
        filepath: str,
        initial_data: Union[List, None] = None
) -> List:
    """
    Ensures the specified JSON file exists by creating it with initial data if necessary, then returns its contents.
    - If the file exists, reads and returns its contents.
    - If the file does not exist:
        - Creates the file using the provided `initial_data` if available.
        - If no `initial_data` is provided, creates an empty list.
    Args:
        filepath (str): The path to the JSON file.
        initial_data (Union[List, None]): Optional initial data to populate the file. Defaults to None.
    Returns:
        List: The contents of the JSON file as a list.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    if not file_path or not file_path.exists():
        file_path = Path(filepath)
        if initial_data is not None:
            with file_path.open('w') as file:
                json.dump(initial_data, file, indent=4)
            return initial_data
        else:
            with file_path.open('w') as file:
                file.write("[]")
            return []
    with file_path.open() as file:
        return json.load(file)


def read_chunks_with_hashes(filepath: str) -> List[Tuple[str, str]]:
    """
    Reads chunks of text along with their cryptographic hashes from a JSON file.
    The function ensures the file exists before reading, using default empty list creation if needed.
    Args:
        filepath (str): The path to the JSON file containing chunks and hashes.
    Returns:
        List[Tuple[str, str]]: A list of tuples where each tuple contains a text block and its corresponding hash
        string.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    data_loaded = ensure_json_file_exists(
        str(file_path) if file_path else filepath
    )
    return [(item['text_block'], item['hash']) for item in data_loaded]


def write_chunks_with_hashes(
        chunks_with_hashes: List[Tuple[str, str]],
        filepath: str,
        overwrite: bool = False
) -> None:
    """
    Writes chunks of text with their cryptographic hashes to a JSON file.
    Args:
        chunks_with_hashes (List[Tuple[str, str]]): List of tuples containing text blocks and their hashes.
        filepath (str): The target JSON file path.
        overwrite (bool): If True, replaces existing file content. Defaults to False (appends new data).
    Returns:
        None
    """
    file_path = _resolve_case_insensitive_path(filepath)
    existing_data = ensure_json_file_exists(
        str(file_path) if file_path else filepath
    )
    new_data = [{'text_block': tb, 'hash': hc} for tb, hc in chunks_with_hashes]
    combined_data = new_data if overwrite else existing_data + new_data
    with (file_path or Path(filepath)).open('w') as file:
        json.dump(combined_data, file, indent=4)


def update_chunks_with_hashes(
        chunks_with_hashes: List[Tuple[str, str]],
        filepath: str,
        mode: str = 'append'
) -> None:
    """
    Updates a JSON file with new chunks and hashes using the specified operation mode.
    Args:
        chunks_with_hashes (List[Tuple[str, str]]): New chunks to write (text blocks + hashes).
        filepath (str): Target file path.
        mode (str): Operation mode - 'append' (default) or 'overwrite'.
    Returns:
        None
    """
    if mode == 'overwrite':
        write_chunks_with_hashes(chunks_with_hashes, filepath, overwrite=True)
    else:
        write_chunks_with_hashes(chunks_with_hashes, filepath)


def get_logger_filename() -> str:
    """
    Constructs and returns the full path to the Wilmer logging file.
    The path is determined by navigating from this file's location to the project root.
    Returns:
        str: The resolved file path string for the Wilmer logs.
    """
    util_dir = os.path.dirname(os.path.abspath(__file__))
    middleware_dir = os.path.dirname(util_dir)
    project_dir = os.path.dirname(middleware_dir)
    logs_path = os.path.join(project_dir, "logs", "wilmerai.log")
    resolved_path = _resolve_case_insensitive_path(logs_path)
    return str(resolved_path) if resolved_path else logs_path


def load_timestamp_file(filepath: str) -> Dict[str, str]:
    """
    Loads timestamp data from a JSON file into a dictionary.
    If the file doesn't exist, logs a warning and returns an empty dictionary.
    Args:
        filepath (str): Path to the timestamp file.
    Returns:
        Dict[str, str]: Key-value pairs of timestamps (empty if file not found).
    """
    file_path = _resolve_case_insensitive_path(filepath)
    if file_path and file_path.exists():
        logger.debug(f"File exists: {file_path}")
        with file_path.open() as file:
            logger.info(f"Opening file: {file_path}")
            return json.load(file)
    else:
        logger.warning(f"File does not exist: {file_path or filepath}")
        return {}


def save_timestamp_file(
        filepath: str,
        timestamps: Dict[str, str]
) -> None:
    """
    Saves a dictionary of timestamps to the specified JSON file.
    Creates the file if it doesn't exist.
    Args:
        filepath (str): Target file path.
        timestamps (Dict[str, str]): Timestamp data to store.
    Returns:
        None
    """
    file_path = _resolve_case_insensitive_path(filepath) or Path(filepath)
    with file_path.open('w') as file:
        json.dump(timestamps, file, indent=4)


def load_custom_file(
        filepath: str,
        delimiter: Optional[str] = None,
        custom_delimiter: Optional[str] = None
) -> str:
    """
    Loads a text file and optionally replaces a specified delimiter with a custom one.
    Args:
        filepath (str): Path to the custom text file.
        delimiter (Optional[str]): Character to find in the file content. Defaults to None (no replacement).
        custom_delimiter (Optional[str]): Replacement character. Defaults to None (no replacement).
    Returns:
        str: The file content with replacements applied, or default messages if file is missing/empty.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    if file_path and file_path.exists():
        with file_path.open() as f:
            content = f.read()
        if not content:
            return "No additional information added"
        if delimiter and custom_delimiter:
            content = content.replace(delimiter, custom_delimiter)
        return content
    else:
        return "Custom instruction file did not exist"