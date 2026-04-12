"""
!!! EXPERIMENTAL !!!

Re-keys or decrypts WilmerAI discussion files for a given user and API key.

Usage:
    Re-key (change API key):
        python rekey_encrypted_files.py --user myuser --api-key OLD_KEY --new-api-key NEW_KEY

    Decrypt (remove encryption):
        python rekey_encrypted_files.py --user myuser --api-key OLD_KEY

    API keys can also be passed via environment variables (WILMER_API_KEY,
    WILMER_NEW_API_KEY) to avoid exposing them in the process list.

When re-keying, all encrypted files under the old API key hash directory are
decrypted with the old key and re-encrypted with the new key. The directory
is then renamed from the old hash to the new hash.

When decrypting, all encrypted files are decrypted and written as plaintext.
The directory remains under the old hash path.
"""

import argparse
import json
import os
import sys
import tempfile

# Add the project root to sys.path so Middleware imports work
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from cryptography.fernet import InvalidToken

from Middleware.utilities.encryption_utils import (
    derive_fernet_key,
    hash_api_key,
    encrypt_bytes,
    decrypt_bytes,
)


def find_discussion_directory(user_config_path: str) -> str:
    """Reads the user config to determine the discussion directory.

    Args:
        user_config_path (str): Path to the user's JSON configuration file.

    Returns:
        str: The resolved discussion directory path.
    """
    with open(user_config_path) as f:
        config = json.load(f)

    directory = config.get("discussionDirectory", "")
    if directory and os.path.isdir(directory):
        return directory

    return os.path.join(project_root, "Public", "DiscussionIds")


def find_user_config_path(username: str) -> str:
    """Locates the user config JSON file.

    Args:
        username (str): The WilmerAI username (matches the config filename).

    Returns:
        str: The absolute path to the user's configuration file. Exits if not found.
    """
    config_path = os.path.join(
        project_root, "Public", "Configs", "Users", f"{username.lower()}.json"
    )
    if not os.path.exists(config_path):
        print(f"Error: User config not found at {config_path}")
        sys.exit(1)
    return config_path


def process_file(filepath: str, old_key: bytes, new_key: bytes = None) -> bool:
    """
    Processes a single JSON file: decrypts with old_key, optionally re-encrypts
    with new_key.

    Args:
        filepath: Path to the file.
        old_key: Fernet key derived from the old API key.
        new_key: Fernet key derived from the new API key, or None to decrypt only.

    Returns:
        True if the file was modified, False if it was already plaintext.
    """
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
    except IOError as e:
        print(f"  Warning: Could not read {filepath}: {e}")
        return False

    try:
        decrypted = decrypt_bytes(raw, old_key)
        plaintext_bytes = decrypted
    except (InvalidToken, ValueError, UnicodeDecodeError):
        # Decryption failed. The file could be plaintext, or it could be
        # encrypted with a different key, or the data may be corrupted.
        try:
            json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not valid JSON and not decryptable — likely encrypted with
            # a different key, or the data is corrupted. In re-key mode,
            # encrypting unverified bytes would produce irrecoverable
            # double-encrypted data. In decrypt mode, we can't do anything
            # useful either. Warn and skip in both cases.
            print(f"  WARNING: Skipping {filepath} — could not decrypt with old key "
                  f"and file is not valid plaintext JSON. It may be encrypted with "
                  f"a different key.")
            return False
        plaintext_bytes = raw
        if new_key is None:
            # Already plaintext, nothing to do for decrypt-only mode
            return False

    output_bytes = encrypt_bytes(plaintext_bytes, new_key) if new_key is not None else plaintext_bytes
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(filepath), suffix='.tmp')
        os.write(tmp_fd, output_bytes)
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = None
        os.replace(tmp_path, filepath)
        tmp_path = None
    finally:
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return True


def collect_json_files(directory: str) -> list:
    """Recursively collects all .json files under a directory.

    Args:
        directory (str): Root directory to search.

    Returns:
        list: Absolute paths to all .json files found (excluding the rekey journal).
    """
    json_files = []
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".json") and filename != ".rekey_journal.json":
                json_files.append(os.path.join(root, filename))
    return json_files


def _load_journal(journal_path: str) -> dict:
    """Loads the rekey journal, or returns an empty state if none exists.

    Args:
        journal_path (str): Path to the journal file.

    Returns:
        dict: The journal state with a 'completed' list of processed file paths.
    """
    if os.path.exists(journal_path):
        with open(journal_path) as f:
            return json.load(f)
    return {"completed": []}


def _save_journal(journal_path: str, journal: dict) -> None:
    """Atomically writes the rekey journal so progress survives crashes.

    Args:
        journal_path (str): Path to the journal file.
        journal (dict): The journal state to persist.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(journal_path), suffix='.tmp')
    try:
        os.write(tmp_fd, json.dumps(journal, indent=2).encode('utf-8'))
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = None
        os.replace(tmp_path, journal_path)
        tmp_path = None
    finally:
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _remove_journal(journal_path: str) -> None:
    """Removes the journal file after a successful rekey.

    Args:
        journal_path (str): Path to the journal file to remove.
    """
    try:
        os.unlink(journal_path)
    except OSError:
        pass


def main():
    """Entry point for the rekey/decrypt CLI tool. Parses arguments and orchestrates the process."""
    parser = argparse.ArgumentParser(
        description="Re-key or decrypt WilmerAI encrypted discussion files."
    )
    parser.add_argument(
        "--user", required=True,
        help="The WilmerAI username (matches the config filename under Public/Configs/Users/)."
    )
    parser.add_argument(
        "--api-key", default=None,
        help="The current API key used to encrypt the files. "
             "Falls back to WILMER_API_KEY environment variable if not provided."
    )
    parser.add_argument(
        "--new-api-key", default=None,
        help="The new API key to re-encrypt files with. If omitted, files are decrypted to plaintext. "
             "Falls back to WILMER_NEW_API_KEY environment variable if not provided."
    )
    args = parser.parse_args()

    args.api_key = args.api_key or os.environ.get('WILMER_API_KEY')
    if not args.api_key:
        parser.error("--api-key is required (or set WILMER_API_KEY environment variable)")
    args.new_api_key = args.new_api_key or os.environ.get('WILMER_NEW_API_KEY')

    user_config_path = find_user_config_path(args.user)
    discussion_dir = find_discussion_directory(user_config_path)

    username = args.user
    old_hash = hash_api_key(args.api_key)
    old_key = derive_fernet_key(args.api_key, username=username)
    old_hash_dir = os.path.join(discussion_dir, old_hash)

    if not os.path.isdir(old_hash_dir):
        print(f"Error: No directory found for API key hash at {old_hash_dir}")
        sys.exit(1)

    new_key = None
    new_hash = None
    if args.new_api_key:
        new_key = derive_fernet_key(args.new_api_key, username=username)
        new_hash = hash_api_key(args.new_api_key)

    if new_key:
        print(f"Re-keying files for user '{args.user}'")
        print(f"  Old hash directory: {old_hash}")
        print(f"  New hash directory: {new_hash}")
    else:
        print(f"Decrypting files for user '{args.user}'")
        print(f"  Hash directory: {old_hash}")

    json_files = collect_json_files(old_hash_dir)
    if not json_files:
        print("No .json files found. Nothing to do.")
        return

    print(f"  Found {len(json_files)} file(s) to process.")

    print("\n  IMPORTANT: Stop WilmerAI before running this script. Running while the server is active may cause data corruption.")

    # Backup confirmation -- rekey modifies files in-place and cannot be rolled back
    print("\n  You should back up your current discussion files before proceeding.")
    print("  If something goes wrong during this process, you could lose them.")
    choice = input("\n  Have you backed up?\n"
                   "    Y) Yes\n"
                   "    N) No. Stop the process and I will do that now\n"
                   "    A) Auto. Copy the directory for me and then continue\n"
                   "  > ").strip().upper()

    if choice == "N":
        print("Aborting. Please back up your files and run this script again.")
        return
    elif choice == "A":
        import shutil
        backup_dir = old_hash_dir.rstrip(os.sep) + "_backup"
        if os.path.exists(backup_dir):
            print(f"  Backup directory already exists at {backup_dir}")
            print("  Please remove or rename it and try again.")
            return
        shutil.copytree(old_hash_dir, backup_dir)
        print(f"  Backed up to: {backup_dir}")
    elif choice != "Y":
        print("Unrecognized option. Aborting.")
        return

    # Use a journal file to track progress so a crashed rekey can be resumed
    journal_path = os.path.join(old_hash_dir, ".rekey_journal.json")
    journal = _load_journal(journal_path)
    already_done = set(journal.get("completed", []))

    if already_done:
        print(f"  Resuming previous rekey: {len(already_done)} file(s) already processed.")

    modified_count = 0
    for filepath in json_files:
        relative = os.path.relpath(filepath, old_hash_dir)
        if filepath in already_done:
            print(f"  {relative}: skipped (already processed)")
            continue
        result = process_file(filepath, old_key, new_key)
        status = "processed" if result else "already plaintext"
        print(f"  {relative}: {status}")
        if result:
            modified_count += 1
        journal["completed"].append(filepath)
        _save_journal(journal_path, journal)

    print(f"\n{modified_count} file(s) modified out of {len(json_files)} total.")

    _remove_journal(journal_path)

    if new_key and old_hash != new_hash:
        new_hash_dir = os.path.join(discussion_dir, new_hash)
        if os.path.exists(new_hash_dir):
            print(f"\nWarning: Target directory {new_hash_dir} already exists.")
            print("Files have been re-encrypted in place. You will need to manually")
            print("merge or move them to the new hash directory.")
        else:
            os.rename(old_hash_dir, new_hash_dir)
            print(f"\nRenamed directory: {old_hash} -> {new_hash}")

    print("Done.")


if __name__ == "__main__":
    main()
