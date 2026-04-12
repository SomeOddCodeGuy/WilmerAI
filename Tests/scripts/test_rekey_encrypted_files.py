
import json
import os
from unittest.mock import patch, MagicMock, call

import pytest

from Middleware.utilities.encryption_utils import derive_fernet_key, encrypt_bytes, decrypt_bytes
from Scripts.rekey_encrypted_files import (
    process_file, collect_json_files, _load_journal, _save_journal, _remove_journal, main,
)


class TestProcessFile:
    """Tests for the process_file function."""

    def test_decrypt_encrypted_file(self, tmp_path):
        """An encrypted file is decrypted to plaintext when no new_key is given."""
        key = derive_fernet_key("old-key")
        data = json.dumps({"hello": "world"}).encode("utf-8")
        encrypted = encrypt_bytes(data, key)

        filepath = tmp_path / "test.json"
        filepath.write_bytes(encrypted)

        result = process_file(str(filepath), key, new_key=None)

        assert result is True
        content = filepath.read_bytes()
        assert json.loads(content) == {"hello": "world"}

    def test_decrypt_already_plaintext_file(self, tmp_path):
        """A plaintext file is left unchanged when no new_key is given."""
        key = derive_fernet_key("old-key")
        data = json.dumps({"already": "plain"})

        filepath = tmp_path / "test.json"
        filepath.write_text(data)

        result = process_file(str(filepath), key, new_key=None)

        assert result is False
        assert json.loads(filepath.read_text()) == {"already": "plain"}

    def test_rekey_encrypted_file(self, tmp_path):
        """An encrypted file is re-encrypted with a new key."""
        old_key = derive_fernet_key("old-key")
        new_key = derive_fernet_key("new-key")
        data = json.dumps({"secret": "data"}).encode("utf-8")
        encrypted = encrypt_bytes(data, old_key)

        filepath = tmp_path / "test.json"
        filepath.write_bytes(encrypted)

        result = process_file(str(filepath), old_key, new_key=new_key)

        assert result is True
        # Should not be readable with old key
        raw = filepath.read_bytes()
        with pytest.raises(Exception):
            decrypt_bytes(raw, old_key)
        # Should be readable with new key
        decrypted = decrypt_bytes(raw, new_key)
        assert json.loads(decrypted) == {"secret": "data"}

    def test_rekey_plaintext_file(self, tmp_path):
        """A plaintext file is encrypted with the new key when re-keying."""
        old_key = derive_fernet_key("old-key")
        new_key = derive_fernet_key("new-key")
        data = json.dumps({"plain": "text"})

        filepath = tmp_path / "test.json"
        filepath.write_text(data)

        result = process_file(str(filepath), old_key, new_key=new_key)

        assert result is True
        raw = filepath.read_bytes()
        decrypted = decrypt_bytes(raw, new_key)
        assert json.loads(decrypted) == {"plain": "text"}

    def test_rekey_skips_file_encrypted_with_different_key(self, tmp_path):
        """A file encrypted with an unknown key is skipped during re-key to prevent double encryption."""
        wrong_key = derive_fernet_key("wrong-key")
        old_key = derive_fernet_key("old-key")
        new_key = derive_fernet_key("new-key")
        data = json.dumps({"secret": "data"}).encode("utf-8")
        encrypted_with_wrong = encrypt_bytes(data, wrong_key)

        filepath = tmp_path / "test.json"
        filepath.write_bytes(encrypted_with_wrong)
        original_bytes = filepath.read_bytes()

        result = process_file(str(filepath), old_key, new_key=new_key)

        assert result is False
        # File should be unchanged
        assert filepath.read_bytes() == original_bytes

    def test_decrypt_skips_file_encrypted_with_different_key(self, tmp_path):
        """A file encrypted with an unknown key is skipped during decrypt-only mode."""
        wrong_key = derive_fernet_key("wrong-key")
        old_key = derive_fernet_key("old-key")
        data = json.dumps({"secret": "data"}).encode("utf-8")
        encrypted_with_wrong = encrypt_bytes(data, wrong_key)

        filepath = tmp_path / "test.json"
        filepath.write_bytes(encrypted_with_wrong)
        original_bytes = filepath.read_bytes()

        result = process_file(str(filepath), old_key, new_key=None)

        assert result is False
        # File should be unchanged
        assert filepath.read_bytes() == original_bytes

    def test_rekey_with_username_salted_keys(self, tmp_path):
        """Re-keying works correctly with username-salted keys."""
        old_key = derive_fernet_key("old-key", username="testuser")
        new_key = derive_fernet_key("new-key", username="testuser")
        data = json.dumps({"user": "data"}).encode("utf-8")
        encrypted = encrypt_bytes(data, old_key)

        filepath = tmp_path / "test.json"
        filepath.write_bytes(encrypted)

        result = process_file(str(filepath), old_key, new_key=new_key)

        assert result is True
        raw = filepath.read_bytes()
        decrypted = decrypt_bytes(raw, new_key)
        assert json.loads(decrypted) == {"user": "data"}


class TestCollectJsonFiles:
    """Tests for the collect_json_files function."""

    def test_finds_nested_json_files(self, tmp_path):
        """Finds .json files in nested subdirectories."""
        (tmp_path / "disc1").mkdir()
        (tmp_path / "disc1" / "memories.json").write_text("{}")
        (tmp_path / "disc1" / "chat_summary.json").write_text("{}")
        (tmp_path / "disc2").mkdir()
        (tmp_path / "disc2" / "timestamps.json").write_text("{}")
        (tmp_path / "not_json.txt").write_text("ignore me")

        result = collect_json_files(str(tmp_path))

        json_names = sorted(os.path.basename(f) for f in result)
        assert json_names == ["chat_summary.json", "memories.json", "timestamps.json"]

    def test_returns_empty_for_no_json_files(self, tmp_path):
        """Returns an empty list when no .json files exist."""
        (tmp_path / "readme.txt").write_text("not json")
        assert collect_json_files(str(tmp_path)) == []


class TestRekeyJournal:
    """Tests for the journal-based crash recovery functions."""

    def test_load_journal_no_file(self, tmp_path):
        """Returns empty state when no journal file exists."""
        journal = _load_journal(str(tmp_path / "nonexistent.json"))
        assert journal == {"completed": []}

    def test_save_and_load_journal(self, tmp_path):
        """Journal survives a round-trip save and load."""
        journal_path = str(tmp_path / ".rekey_journal.json")
        journal = {"completed": ["/path/to/file1.json", "/path/to/file2.json"]}
        _save_journal(journal_path, journal)

        loaded = _load_journal(journal_path)
        assert loaded == journal

    def test_remove_journal(self, tmp_path):
        """Journal file is removed after successful completion."""
        journal_path = str(tmp_path / ".rekey_journal.json")
        _save_journal(journal_path, {"completed": ["file.json"]})
        assert os.path.exists(journal_path)

        _remove_journal(journal_path)
        assert not os.path.exists(journal_path)

    def test_remove_journal_nonexistent(self, tmp_path):
        """Removing a nonexistent journal does not raise."""
        _remove_journal(str(tmp_path / "nonexistent.json"))


class TestMain:
    """Tests for the main() entry-point function."""

    MODULE = "Scripts.rekey_encrypted_files"

    def _make_args(self, user="testuser", api_key="old-secret", new_api_key=None):
        """Builds a mock argparse.Namespace with the standard attributes."""
        args = MagicMock()
        args.user = user
        args.api_key = api_key
        args.new_api_key = new_api_key
        return args

    @patch.dict(os.environ, {}, clear=False)
    @patch(f"{MODULE}.input", return_value="Y")
    @patch(f"{MODULE}._remove_journal")
    @patch(f"{MODULE}._save_journal")
    @patch(f"{MODULE}._load_journal", return_value={"completed": []})
    @patch(f"{MODULE}.process_file", return_value=True)
    @patch(f"{MODULE}.collect_json_files")
    @patch(f"{MODULE}.os.path.isdir", return_value=True)
    @patch(f"{MODULE}.find_discussion_directory", return_value="/fake/discussions")
    @patch(f"{MODULE}.find_user_config_path", return_value="/fake/config/testuser.json")
    @patch(f"{MODULE}.argparse.ArgumentParser")
    def test_main_decrypt_mode(
        self, mock_parser_cls, mock_find_config, mock_find_disc,
        mock_isdir, mock_collect, mock_process, mock_load_journal,
        mock_save_journal, mock_remove_journal, mock_input,
    ):
        """Decrypt mode (no new key): files are processed with new_key=None."""
        # Remove env vars that could interfere with arg resolution
        os.environ.pop("WILMER_API_KEY", None)
        os.environ.pop("WILMER_NEW_API_KEY", None)

        args = self._make_args(api_key="old-secret", new_api_key=None)
        mock_parser_cls.return_value.parse_args.return_value = args

        mock_collect.return_value = ["/fake/discussions/abc123/file1.json"]

        main()

        mock_find_config.assert_called_once_with("testuser")
        mock_find_disc.assert_called_once_with("/fake/config/testuser.json")
        mock_process.assert_called_once()
        # new_key should be None for decrypt-only mode
        positional_args = mock_process.call_args[0]
        assert positional_args[2] is None
        mock_remove_journal.assert_called_once()

    @patch.dict(os.environ, {}, clear=False)
    @patch(f"{MODULE}.input", return_value="Y")
    @patch(f"{MODULE}._remove_journal")
    @patch(f"{MODULE}._save_journal")
    @patch(f"{MODULE}._load_journal", return_value={"completed": []})
    @patch(f"{MODULE}.process_file", return_value=True)
    @patch(f"{MODULE}.collect_json_files")
    @patch(f"{MODULE}.os.rename")
    @patch(f"{MODULE}.os.path.exists", return_value=False)
    @patch(f"{MODULE}.os.path.isdir", return_value=True)
    @patch(f"{MODULE}.find_discussion_directory", return_value="/fake/discussions")
    @patch(f"{MODULE}.find_user_config_path", return_value="/fake/config/testuser.json")
    @patch(f"{MODULE}.argparse.ArgumentParser")
    def test_main_rekey_mode(
        self, mock_parser_cls, mock_find_config, mock_find_disc,
        mock_isdir, mock_exists, mock_rename, mock_collect,
        mock_process, mock_load_journal, mock_save_journal,
        mock_remove_journal, mock_input,
    ):
        """Rekey mode (old + new key): files are processed and directory is renamed."""
        os.environ.pop("WILMER_API_KEY", None)
        os.environ.pop("WILMER_NEW_API_KEY", None)

        args = self._make_args(api_key="old-secret", new_api_key="new-secret")
        mock_parser_cls.return_value.parse_args.return_value = args

        mock_collect.return_value = ["/fake/discussions/oldhash/data.json"]

        main()

        mock_find_config.assert_called_once_with("testuser")
        mock_process.assert_called_once()
        # process_file should receive a non-None new_key
        positional_args = mock_process.call_args[0]
        assert positional_args[2] is not None  # new_key
        # Directory should be renamed from old hash to new hash
        mock_rename.assert_called_once()

    @patch(f"{MODULE}.find_user_config_path", side_effect=SystemExit(1))
    @patch(f"{MODULE}.argparse.ArgumentParser")
    def test_main_missing_user_config(self, mock_parser_cls, mock_find_config):
        """Exits cleanly when the user config file does not exist."""
        args = self._make_args(api_key="old-secret")
        mock_parser_cls.return_value.parse_args.return_value = args

        # find_user_config_path calls sys.exit(1) when the config is missing
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        mock_find_config.assert_called_once_with("testuser")

    @patch.dict(os.environ, {}, clear=False)
    @patch("shutil.copytree")
    @patch(f"{MODULE}.input", return_value="A")
    @patch(f"{MODULE}._remove_journal")
    @patch(f"{MODULE}._save_journal")
    @patch(f"{MODULE}._load_journal", return_value={"completed": []})
    @patch(f"{MODULE}.process_file", return_value=True)
    @patch(f"{MODULE}.collect_json_files")
    @patch(f"{MODULE}.os.path.exists", return_value=False)
    @patch(f"{MODULE}.os.path.isdir", return_value=True)
    @patch(f"{MODULE}.find_discussion_directory", return_value="/fake/discussions")
    @patch(f"{MODULE}.find_user_config_path", return_value="/fake/config/testuser.json")
    @patch(f"{MODULE}.argparse.ArgumentParser")
    def test_main_auto_backup(
        self, mock_parser_cls, mock_find_config, mock_find_disc,
        mock_isdir, mock_exists, mock_collect, mock_process,
        mock_load_journal, mock_save_journal, mock_remove_journal,
        mock_input, mock_copytree,
    ):
        """Choosing 'A' for auto backup calls shutil.copytree before processing."""
        os.environ.pop("WILMER_API_KEY", None)
        os.environ.pop("WILMER_NEW_API_KEY", None)

        args = self._make_args(api_key="old-secret")
        mock_parser_cls.return_value.parse_args.return_value = args

        mock_collect.return_value = ["/fake/discussions/oldhash/f.json"]

        main()

        mock_copytree.assert_called_once()
        src, dst = mock_copytree.call_args[0]
        assert "backup" in dst
        # Files should still be processed after backup
        mock_process.assert_called_once()

    @patch.dict(os.environ, {}, clear=False)
    @patch(f"{MODULE}.input", return_value="N")
    @patch(f"{MODULE}.process_file")
    @patch(f"{MODULE}.collect_json_files")
    @patch(f"{MODULE}.os.path.isdir", return_value=True)
    @patch(f"{MODULE}.find_discussion_directory", return_value="/fake/discussions")
    @patch(f"{MODULE}.find_user_config_path", return_value="/fake/config/testuser.json")
    @patch(f"{MODULE}.argparse.ArgumentParser")
    def test_main_abort_on_no(
        self, mock_parser_cls, mock_find_config, mock_find_disc,
        mock_isdir, mock_collect, mock_process, mock_input,
    ):
        """Choosing 'N' at the backup prompt aborts without processing any files."""
        os.environ.pop("WILMER_API_KEY", None)
        os.environ.pop("WILMER_NEW_API_KEY", None)

        args = self._make_args(api_key="old-secret")
        mock_parser_cls.return_value.parse_args.return_value = args

        mock_collect.return_value = ["/fake/discussions/oldhash/f.json"]

        main()

        mock_process.assert_not_called()
