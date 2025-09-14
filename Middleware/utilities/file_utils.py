# /Middleware/utilities/file_utils.py

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional

logger = logging.getLogger(__name__)


def _resolve_case_insensitive_path(path_str: str) -> Optional[Path]:
    """
    Resolves the correct casing of a file path in a case-insensitive manner.

    This function first checks for an exact path match. If not found, it
    attempts to find a case-insensitive match for the file name within
    its parent directory.

    Args:
        path_str (str): The file path to resolve.

    Returns:
        Optional[Path]: The resolved file path if found, otherwise None.
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
    Ensures a JSON file exists, creates it if necessary, and returns its contents.

    If the specified file exists (case-insensitively), its contents are
    read and returned. If it does not exist, a new file is created with
    the provided initial data or an empty list if no data is given.

    Args:
        filepath (str): The path to the JSON file.
        initial_data (Union[List, None]): Optional initial data to populate the
            file if it needs to be created. Defaults to an empty list.

    Returns:
        List: The contents of the JSON file as a list.
    """
    resolved_path = _resolve_case_insensitive_path(filepath)

    # If the file exists, load and return it.
    if resolved_path and resolved_path.exists():
        with resolved_path.open() as file:
            return json.load(file)

    # If the file does not exist, create it.
    # Use the original filepath string to create the new file.
    # Ensure parent directory exists.
    target_path = Path(filepath)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    data_to_write = initial_data if initial_data is not None else []

    with target_path.open('w') as file:
        if data_to_write:
            json.dump(data_to_write, file, indent=4)
        else:
            file.write("[]")  # Write an empty JSON array

    return data_to_write


def read_chunks_with_hashes(filepath: str) -> List[Tuple[str, str]]:
    """
    Reads chunks of text and their hashes from a JSON file.

    This function reads a JSON file that is expected to contain a list of
    dictionaries, where each dictionary has 'text_block' and 'hash' keys.
    It ensures the file exists before attempting to read.

    Args:
        filepath (str): The path to the JSON file.

    Returns:
        List[Tuple[str, str]]: A list of tuples, each containing a text block
            and its corresponding hash.
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
    Writes chunks of text with their hashes to a JSON file.

    This function either appends new data to an existing file or overwrites
    the file completely based on the `overwrite` flag.

    Args:
        chunks_with_hashes (List[Tuple[str, str]]): A list of tuples, each
            containing a text block and its hash.
        filepath (str): The path to the JSON file.
        overwrite (bool): If True, the file is overwritten. If False,
            new data is appended. Defaults to False.

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
    Updates a JSON file with new chunks and hashes using a specified mode.

    This function acts as a wrapper for `write_chunks_with_hashes`, providing
    a simplified interface to either 'append' or 'overwrite' data.

    Args:
        chunks_with_hashes (List[Tuple[str, str]]): A list of tuples, each
            containing a text block and its hash.
        filepath (str): The path to the JSON file.
        mode (str): The operation mode, either 'append' or 'overwrite'.
            Defaults to 'append'.

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

    The path is determined relative to the location of this script,
    navigating up the directory tree to the project root and then to
    the 'logs' directory.

    Returns:
        str: The full path string for the Wilmer log file.
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

    If the file exists, its contents are loaded. If the file does not exist,
    a warning is logged and an empty dictionary is returned.

    Args:
        filepath (str): The path to the timestamp file.

    Returns:
        Dict[str, str]: The dictionary of timestamps from the file.
            Returns an empty dictionary if the file is not found.
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
    Saves a dictionary of timestamps to a JSON file.

    The function creates the file and any necessary parent directories if
    they do not already exist.

    Args:
        filepath (str): The path to the target file.
        timestamps (Dict[str, str]): The timestamp data to be stored.

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
    Loads a text file and optionally replaces a delimiter.

    If the file exists and is not empty, its content is read. A specified
    delimiter can be replaced with a custom one. If the file is missing
    or empty, a default message is returned.

    Args:
        filepath (str): The path to the custom text file.
        delimiter (Optional[str]): The delimiter string to find and replace.
            Defaults to None.
        custom_delimiter (Optional[str]): The replacement string.
            Defaults to None.

    Returns:
        str: The content of the file with replacements, or a default
            message if the file is missing or empty.
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


# ADD THIS NEW FUNCTION
def save_custom_file(filepath: str, content: str) -> None:
    """
    Saves content to a text file, creating parent directories if they don't exist.

    Args:
        filepath (str): The path where the file will be saved.
        content (str): The string content to write to the file.

    Raises:
        IOError: If there is an issue writing to the file.
    """
    try:
        file_path = Path(filepath)
        # Create parent directories if they don't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        raise IOError(f"Could not write to file at {filepath}") from e
