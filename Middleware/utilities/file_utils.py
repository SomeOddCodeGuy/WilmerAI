# /Middleware/utilities/file_utils.py

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional

logger = logging.getLogger(__name__)


def resolve_file_path(path_str: str) -> str:
    """
    Normalizes a raw file path string, expanding a leading ``~``/``~user`` to the home directory.

    This is the single, shared way any code should turn a config- or workflow-derived path string
    into something usable for ``os.path.exists``, ``open``, or a ``Path``, so a value that is
    *written* one way and *read/existence-checked* another can never diverge on ``~`` expansion.
    (That divergence, a path written to the real home but looked up as a literal ``~`` directory,
    is exactly what made a bypassing caller cold-start and re-process on every run.) Any code
    doing its own file I/O on a path that may contain ``~`` should call this rather than reaching
    for ``os.path.expanduser``/``Path`` directly.

    ``os.path.expanduser`` is used rather than ``Path.expanduser`` because it returns the string
    unchanged when no home directory can be resolved instead of raising ``RuntimeError``, preserving
    the literal behavior in home-less environments. A path without a leading ``~`` is returned
    untouched, so absolute and relative paths are unaffected.

    Args:
        path_str (str): The raw file path, which may begin with ``~``.

    Returns:
        str: The path with any leading ``~`` expanded to the home directory.
    """
    return os.path.expanduser(path_str) if path_str else path_str


def _to_path(path_str: str) -> Path:
    """
    Builds a ``Path`` from a string via :func:`resolve_file_path` (expanding a leading ``~``).

    Centralizes path construction so every file this module reads or writes honors ``~``/``~user``
    prefixes consistently. A path without a leading ``~`` is returned untouched.

    Args:
        path_str (str): The raw file path, which may begin with ``~``.

    Returns:
        Path: The path with any leading ``~`` expanded to the home directory.
    """
    return Path(resolve_file_path(path_str))


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
    file_path = _to_path(path_str)
    if file_path.exists():
        return file_path
    parent_dir = file_path.parent
    target_filename = file_path.name
    if not parent_dir.exists():
        return None
    entries = {p.name.lower(): p for p in parent_dir.iterdir()}
    return entries.get(target_filename.lower())


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
            # Decryption failed; file is likely plaintext (migration scenario)
            logger.warning("Encrypted read failed for %s, falling back to plaintext.", file_path)

    try:
        with file_path.open() as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("File is neither valid encrypted data nor valid JSON: %s: %s", file_path, e)
        raise


def _atomic_write_bytes(file_path: Path, data: bytes) -> None:
    """
    Writes bytes to a file atomically (temp file in the target directory,
    fsync, then rename) so a crash mid-write cannot corrupt the target file.

    Args:
        file_path (Path): The target file path. Its parent must already exist.
        data (bytes): The bytes to write.
    """
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(file_path.parent), suffix='.tmp')
        os.write(tmp_fd, data)
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
    if encryption_key:
        from Middleware.utilities.encryption_utils import encrypt_bytes
        json_bytes = encrypt_bytes(json_bytes, encryption_key)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(file_path, json_bytes)


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
        encryption_key (Optional[bytes]): Fernet key for transparent
            encryption/decryption.

    Returns:
        List: The contents of the JSON file as a list.
    """
    resolved_path = _resolve_case_insensitive_path(filepath)

    if resolved_path and resolved_path.exists():
        data = _read_json_file(resolved_path, encryption_key)
        if not isinstance(data, list):
            raise TypeError(
                f"Expected a JSON list in '{filepath}', got {type(data).__name__}. "
                f"The file may be corrupted."
            )
        return data

    target_path = _to_path(filepath)
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
    data_loaded = ensure_json_file_exists(filepath, encryption_key=encryption_key)
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
    existing_data = ensure_json_file_exists(filepath, encryption_key=encryption_key)
    new_data = [{'text_block': tb, 'hash': hc} for tb, hc in chunks_with_hashes]
    combined_data = new_data if overwrite else existing_data + new_data
    target = _resolve_case_insensitive_path(filepath) or _to_path(filepath)
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
    file_path = _resolve_case_insensitive_path(filepath) or _to_path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(file_path, timestamps, encryption_key)


def load_custom_file(
        filepath: str,
        delimiter: Optional[str] = None,
        custom_delimiter: Optional[str] = None,
        head_count: Optional[int] = None,
        tail_count: Optional[int] = None,
        chunk_delimiter: str = "\n"
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
        head_count (Optional[int]): If set, keep only the first N chunks of
            the file (chunks split on ``chunk_delimiter``). Opt-in; defaults
            to None (whole file).
        tail_count (Optional[int]): If set, keep only the last N chunks of the
            file (chunks split on ``chunk_delimiter``). Opt-in; defaults to
            None (whole file). Mutually exclusive with head_count.
        chunk_delimiter (str): The separator that defines a "chunk" for
            head_count/tail_count. Defaults to "\n" (i.e. lines).

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
        if head_count is not None or tail_count is not None:
            separator = chunk_delimiter or "\n"
            parts = content.split(separator)
            if tail_count is not None:
                # Only a positive count keeps chunks; 0 yields none and a negative
                # (nonsensical) count is clamped to none too. The explicit guard also
                # avoids parts[-0:] returning the whole list (since -0 == 0).
                parts = parts[-tail_count:] if tail_count > 0 else []
            else:
                # Symmetric with tail_count: 0 or a negative count yields no chunks
                # rather than parts[:negative] dropping from the end.
                parts = parts[:head_count] if head_count > 0 else []
            content = separator.join(parts)
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
    file_path = _resolve_case_insensitive_path(filepath) or _to_path(filepath)
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
    file_path = _resolve_case_insensitive_path(filepath) or _to_path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(file_path, data, encryption_key)


def save_custom_file(filepath: str, content: str, mode: str = "overwrite",
                     find: Optional[str] = None) -> Optional[int]:
    """
    Saves content to a text file using atomic write, creating parent directories
    if they don't exist.

    Uses the same write-to-temp-then-replace pattern as ``_write_json_file``
    to prevent data corruption if the process crashes mid-write.

    Args:
        filepath (str): The path where the file will be saved.
        content (str): The string content to write. Ignored when mode is "remove" or "trim".
        mode (str): One of:
            - "overwrite" (default): replace the whole file.
            - "append": add content to the end of the existing file
              (read-modify-write so the write stays atomic); a missing file is created.
            - "replace": swap every occurrence of ``find`` for ``content`` in an
              existing file, leaving all other text untouched. This is the surgical
              alternative to a full rewrite: a caller can update one entry without
              regenerating (and risking the loss of) the rest of the document.
            - "remove": delete every line that contains ``find`` from an existing file.
            - "trim": delete every blank or whitespace-only line from an existing file, leaving the
              real content lines intact (needs neither ``content`` nor ``find``). Useful for tidying
              a line-per-entry log that a model has salted with stray blank lines.
        find (Optional[str]): The target text for "replace"/"remove". Required for those two modes;
            not used by "trim".

    Returns:
        Optional[int]: For "replace"/"remove"/"trim", the number of changes made
            (occurrences replaced, or lines removed); 0 when nothing matched.
            None for "overwrite"/"append".

    Raises:
        ValueError: If mode is "replace"/"remove" without a non-empty ``find``.
        IOError: If there is an issue writing to the file.
    """
    file_path = _to_path(filepath)

    if mode in ("replace", "remove", "trim"):
        # Surgical edits act on an existing file only. A missing file, or a target that is not
        # present/matched, is a no-op that reports zero changes rather than creating or rewriting
        # anything, so a maintainer workflow can safely attempt an edit every turn and branch on
        # whether it actually landed.
        if mode in ("replace", "remove") and not find:
            raise ValueError(f"save_custom_file: mode '{mode}' requires a non-empty 'find' value")
        if not file_path.exists():
            return 0
        original = file_path.read_text(encoding='utf-8')
        if mode == "replace":
            change_count = original.count(find)
            if change_count == 0:
                return 0
            new_content = original.replace(find, content)
        elif mode == "remove":  # drop whole lines containing the target text
            lines = original.splitlines(keepends=True)
            kept_lines = [line for line in lines if find not in line]
            change_count = len(lines) - len(kept_lines)
            if change_count == 0:
                return 0
            new_content = "".join(kept_lines)
        else:  # "trim": drop blank / whitespace-only lines, leaving the real content intact
            lines = original.splitlines(keepends=True)
            kept_lines = [line for line in lines if line.strip()]
            change_count = len(lines) - len(kept_lines)
            if change_count == 0:
                return 0
            new_content = "".join(kept_lines)
        try:
            _atomic_write_bytes(file_path, new_content.encode('utf-8'))
        except Exception as e:
            raise IOError(f"Could not write to file at {filepath}") from e
        return change_count

    file_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append" and file_path.exists():
        # Read-modify-write so the atomic replace below is preserved. Let a read
        # failure propagate rather than swallowing it: silently writing only the new
        # content would overwrite (not append to) the existing file and lose its prior
        # contents, the opposite of what "append" promises.
        content = file_path.read_text(encoding='utf-8') + content
    try:
        _atomic_write_bytes(file_path, content.encode('utf-8'))
    except Exception as e:
        raise IOError(f"Could not write to file at {filepath}") from e
    return None


def read_plain_text_file(filepath: str, encryption_key: Optional[bytes] = None) -> str:
    """
    Reads a plain-text (e.g. markdown) file, transparently decrypting if needed.

    Mirrors the encrypted-then-plaintext fallback behavior of ``_read_json_file``:
    when an encryption_key is provided the file is first treated as encrypted
    binary data; if decryption fails the content is returned as plaintext
    (migration scenario, or a user hand-edited the file while encryption was
    enabled).

    Args:
        filepath (str): The path of the file to read.
        encryption_key (Optional[bytes]): Fernet key for decryption.

    Returns:
        str: The file's text content, or an empty string if the file does not exist.
    """
    file_path = _to_path(filepath)
    if not file_path.exists():
        return ''

    if encryption_key:
        try:
            from cryptography.fernet import InvalidToken
            from Middleware.utilities.encryption_utils import decrypt_bytes
            raw = file_path.read_bytes()
            return decrypt_bytes(raw, encryption_key).decode('utf-8')
        except (InvalidToken, ValueError, UnicodeDecodeError):
            logger.warning("Encrypted read failed for %s, falling back to plaintext.", file_path)

    return file_path.read_text(encoding='utf-8')


def write_plain_text_file(filepath: str, content: str, encryption_key: Optional[bytes] = None,
                          backup_suffix: Optional[str] = None) -> None:
    """
    Writes a plain-text file atomically, with an optional pre-write backup.

    When ``backup_suffix`` is provided and the target file already exists, the
    existing file is first copied to ``{filepath}{backup_suffix}`` so the
    previous version survives one overwrite. If the backup copy fails, the
    exception propagates and the write is never attempted, guaranteeing the
    current content cannot be lost.

    Args:
        filepath (str): The target file path.
        content (str): The text content to write.
        encryption_key (Optional[bytes]): Fernet key for encryption.
        backup_suffix (Optional[str]): Suffix for the pre-write backup copy
            (e.g. '.bak'). None disables the backup.
    """
    file_path = _to_path(filepath)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if backup_suffix and file_path.exists():
        shutil.copy2(str(file_path), str(file_path) + backup_suffix)

    data = content.encode('utf-8')
    if encryption_key:
        from Middleware.utilities.encryption_utils import encrypt_bytes
        data = encrypt_bytes(data, encryption_key)
    _atomic_write_bytes(file_path, data)
