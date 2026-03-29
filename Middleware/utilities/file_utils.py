# /Middleware/utilities/file_utils.py

import json
import logging
import os
import tempfile
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


def _read_json_file(file_path: Path, encryption_key: Optional[bytes] = None):
    """
    Reads and parses a JSON file, transparently decrypting if needed.

    When an encryption_key is provided, the function first attempts to read
    the file as encrypted binary data and decrypt it. If decryption fails
    (e.g. the file is plaintext from before encryption was enabled), it falls
    back to a normal plaintext JSON read. This provides seamless migration.

    Args:
        file_path (Path): The resolved path to the file.
        encryption_key (Optional[bytes]): Fernet key for decryption.

    Returns:
        The parsed JSON data.
    """
    if encryption_key:
        try:
            from cryptography.fernet import InvalidToken
            from Middleware.utilities.encryption_utils import decrypt_bytes
            raw = file_path.read_bytes()
            decrypted = decrypt_bytes(raw, encryption_key)
            return json.loads(decrypted.decode('utf-8'))
        except (InvalidToken, ValueError, UnicodeDecodeError):
            # Decryption failed — file is likely plaintext (migration scenario)
            logger.warning("Encrypted read failed for %s, falling back to plaintext.", file_path)

    try:
        with file_path.open() as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("File is neither valid encrypted data nor valid JSON: %s — %s", file_path, e)
        raise


def _write_json_file(file_path: Path, data, encryption_key: Optional[bytes] = None) -> None:
    """
    Writes data as JSON to a file, optionally encrypting the output.

    Uses atomic write (write to temp file then rename) to prevent data
    corruption if the process crashes mid-write.

    Args:
        file_path (Path): The target file path.
        data: The data to serialize to JSON.
        encryption_key (Optional[bytes]): Fernet key for encryption.
    """
    json_bytes = json.dumps(data, indent=4).encode('utf-8')
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(file_path.parent), suffix='.tmp')
        if encryption_key:
            from Middleware.utilities.encryption_utils import encrypt_bytes
            encrypted = encrypt_bytes(json_bytes, encryption_key)
            os.write(tmp_fd, encrypted)
        else:
            os.write(tmp_fd, json_bytes)
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = None
        os.replace(tmp_path, str(file_path))
        tmp_path = None
    finally:
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def ensure_json_file_exists(
        filepath: str,
        initial_data: Union[List, None] = None,
        encryption_key: Optional[bytes] = None
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
        return _read_json_file(resolved_path, encryption_key)

    # If the file does not exist, create it.
    # Use the original filepath string to create the new file.
    # Ensure parent directory exists.
    target_path = Path(filepath)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    data_to_write = initial_data if initial_data is not None else []

    _write_json_file(target_path, data_to_write, encryption_key)

    return data_to_write


def read_chunks_with_hashes(filepath: str, encryption_key: Optional[bytes] = None) -> List[Tuple[str, str]]:
    """
    Reads chunks of text and their hashes from a JSON file.

    This function reads a JSON file that is expected to contain a list of
    dictionaries, where each dictionary has 'text_block' and 'hash' keys.
    It ensures the file exists before attempting to read.

    Args:
        filepath (str): The path to the JSON file.
        encryption_key (Optional[bytes]): Fernet key for transparent decryption.

    Returns:
        List[Tuple[str, str]]: A list of tuples, each containing a text block
            and its corresponding hash.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    data_loaded = ensure_json_file_exists(
        str(file_path) if file_path else filepath,
        encryption_key=encryption_key
    )
    return [(item['text_block'], item['hash']) for item in data_loaded]


def write_chunks_with_hashes(
        chunks_with_hashes: List[Tuple[str, str]],
        filepath: str,
        overwrite: bool = False,
        encryption_key: Optional[bytes] = None
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
        encryption_key (Optional[bytes]): Fernet key for transparent encryption.

    Returns:
        None
    """
    file_path = _resolve_case_insensitive_path(filepath)
    existing_data = ensure_json_file_exists(
        str(file_path) if file_path else filepath,
        encryption_key=encryption_key
    )
    new_data = [{'text_block': tb, 'hash': hc} for tb, hc in chunks_with_hashes]
    combined_data = new_data if overwrite else existing_data + new_data
    target = file_path or Path(filepath)
    _write_json_file(target, combined_data, encryption_key)


def update_chunks_with_hashes(
        chunks_with_hashes: List[Tuple[str, str]],
        filepath: str,
        mode: str = 'append',
        encryption_key: Optional[bytes] = None
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
        encryption_key (Optional[bytes]): Fernet key for transparent encryption.

    Returns:
        None
    """
    if mode == 'overwrite':
        write_chunks_with_hashes(chunks_with_hashes, filepath, overwrite=True, encryption_key=encryption_key)
    else:
        write_chunks_with_hashes(chunks_with_hashes, filepath, encryption_key=encryption_key)


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


def load_timestamp_file(filepath: str, encryption_key: Optional[bytes] = None) -> Dict[str, str]:
    """
    Loads timestamp data from a JSON file into a dictionary.

    If the file exists, its contents are loaded. If the file does not exist,
    a warning is logged and an empty dictionary is returned.

    Args:
        filepath (str): The path to the timestamp file.
        encryption_key (Optional[bytes]): Fernet key for transparent decryption.

    Returns:
        Dict[str, str]: The dictionary of timestamps from the file.
            Returns an empty dictionary if the file is not found.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    if file_path and file_path.exists():
        logger.debug(f"File exists: {file_path}")
        logger.info(f"Opening file: {file_path}")
        return _read_json_file(file_path, encryption_key)
    else:
        logger.warning(f"File does not exist: {file_path or filepath}")
        return {}


def save_timestamp_file(
        filepath: str,
        timestamps: Dict[str, str],
        encryption_key: Optional[bytes] = None
) -> None:
    """
    Saves a dictionary of timestamps to a JSON file.

    The function creates the file and any necessary parent directories if
    they do not already exist.

    Args:
        filepath (str): The path to the target file.
        timestamps (Dict[str, str]): The timestamp data to be stored.
        encryption_key (Optional[bytes]): Fernet key for transparent encryption.

    Returns:
        None
    """
    file_path = _resolve_case_insensitive_path(filepath) or Path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(file_path, timestamps, encryption_key)


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
        logger.info(f"Custom instruction file did not exist at path: {filepath}")
        return "Custom instruction file did not exist"


def read_condensation_tracker(filepath: str, encryption_key: Optional[bytes] = None) -> Dict:
    """
    Reads memory condensation tracker data from a JSON file.

    If the file exists, its contents are loaded and returned as a dictionary.
    If the file does not exist, an empty dictionary is returned.

    Args:
        filepath (str): The path to the condensation tracker file.
        encryption_key (Optional[bytes]): Fernet key for transparent decryption.

    Returns:
        Dict: The tracker data (e.g. {"lastCondensationHash": "..."}),
            or an empty dictionary if the file is not found.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    if file_path and file_path.exists():
        return _read_json_file(file_path, encryption_key)
    else:
        return {}


def write_condensation_tracker(filepath: str, data: Dict, encryption_key: Optional[bytes] = None) -> None:
    """
    Writes memory condensation tracker data to a JSON file.

    Creates parent directories if they do not already exist.

    Args:
        filepath (str): The path to the condensation tracker file.
        data (Dict): The tracker data to write (e.g. {"lastCondensationHash": "..."}).
        encryption_key (Optional[bytes]): Fernet key for transparent encryption.
    """
    file_path = _resolve_case_insensitive_path(filepath) or Path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(file_path, data, encryption_key)


def read_vision_responses(filepath: str, encryption_key: Optional[bytes] = None) -> Dict:
    """
    Reads vision response cache data from a JSON file.

    If the file exists, its contents are loaded and returned as a dictionary
    mapping message hashes to their cached vision LLM responses. If the file
    does not exist, an empty dictionary is returned.

    Args:
        filepath (str): The path to the vision responses cache file.
        encryption_key (Optional[bytes]): Fernet key for transparent decryption.

    Returns:
        Dict: The cached data (e.g. {"message_hash": "response_text"}),
            or an empty dictionary if the file is not found.
    """
    file_path = _resolve_case_insensitive_path(filepath)
    if file_path and file_path.exists():
        return _read_json_file(file_path, encryption_key)
    else:
        return {}


def write_vision_responses(filepath: str, data: Dict, encryption_key: Optional[bytes] = None) -> None:
    """
    Writes vision response cache data to a JSON file.

    Creates parent directories if they do not already exist.

    Args:
        filepath (str): The path to the vision responses cache file.
        data (Dict): The cache data to write (e.g. {"message_hash": "response_text"}).
        encryption_key (Optional[bytes]): Fernet key for transparent encryption.
    """
    file_path = _resolve_case_insensitive_path(filepath) or Path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(file_path, data, encryption_key)


def save_custom_file(filepath: str, content: str) -> None:
    """
    Saves content to a text file using atomic write, creating parent directories
    if they don't exist.

    Uses the same write-to-temp-then-replace pattern as ``_write_json_file``
    to prevent data corruption if the process crashes mid-write.

    Args:
        filepath (str): The path where the file will be saved.
        content (str): The string content to write to the file.

    Raises:
        IOError: If there is an issue writing to the file.
    """
    file_path = Path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = content.encode('utf-8')
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(file_path.parent), suffix='.tmp')
        os.write(tmp_fd, content_bytes)
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = None
        os.replace(tmp_path, str(file_path))
        tmp_path = None
    except Exception as e:
        raise IOError(f"Could not write to file at {filepath}") from e
    finally:
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
