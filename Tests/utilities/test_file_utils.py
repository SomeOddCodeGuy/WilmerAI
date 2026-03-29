import json
import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open

import pytest

from Middleware.utilities.file_utils import (
    _resolve_case_insensitive_path,
    _read_json_file,
    _write_json_file,
    ensure_json_file_exists,
    get_logger_filename,
    load_custom_file,
    load_timestamp_file,
    read_chunks_with_hashes,
    read_condensation_tracker,
    read_vision_responses,
    save_custom_file,
    save_timestamp_file,
    update_chunks_with_hashes,
    write_chunks_with_hashes,
    write_condensation_tracker,
    write_vision_responses,
)


# ###############################################################
# Section 1: Tests for _resolve_case_insensitive_path
# ###############################################################

class TestResolveCaseInsensitivePath:
    """Tests for the internal _resolve_case_insensitive_path helper function."""

    def test_path_exists_exact_match(self, mocker):
        """
        Verifies that if a path exists with the correct casing, it is returned immediately.
        """
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = True
        mock_Path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_Path_class.return_value = mock_path_instance

        result = _resolve_case_insensitive_path('/mock/path/file.txt')

        assert result == mock_path_instance
        mock_path_instance.exists.assert_called_once()
        mock_Path_class.assert_called_once_with('/mock/path/file.txt')

    def test_path_exists_case_insensitive_match(self, mocker):
        """
        Verifies that a path is found even if its casing is incorrect.
        """
        correct_path = Path('/mock/path/File.txt')
        incorrect_path_str = '/mock/path/file.txt'

        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = False
        mock_path_instance.parent.exists.return_value = True
        mock_path_instance.parent.iterdir.return_value = [correct_path]
        mock_path_instance.name = 'file.txt'

        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        result = _resolve_case_insensitive_path(incorrect_path_str)

        assert result == correct_path

    def test_path_does_not_exist(self, mocker):
        """
        Verifies that None is returned when no matching file is found.
        """
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = False
        mock_path_instance.parent.exists.return_value = True
        mock_path_instance.parent.iterdir.return_value = [Path('/mock/path/other.txt')]
        mock_path_instance.name = 'nonexistent.txt'
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        result = _resolve_case_insensitive_path('/mock/path/nonexistent.txt')

        assert result is None

    def test_parent_directory_does_not_exist(self, mocker):
        """
        Verifies that None is returned if the parent directory doesn't exist.
        """
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = False
        mock_path_instance.parent.exists.return_value = False
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        result = _resolve_case_insensitive_path('/nonexistent/dir/file.txt')

        assert result is None


# ###############################################################
# Section 2: Tests for ensure_json_file_exists
# ###############################################################

class TestEnsureJsonFileExists:
    """Tests for the ensure_json_file_exists function."""

    def test_file_exists_and_is_loaded(self, mocker):
        """
        Verifies that an existing file's content is loaded and returned.
        """
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)

        mock_file_content = json.dumps([{"key": "value"}])
        mock_open_func = mock_open(read_data=mock_file_content)
        mocker.patch.object(mock_path, 'open', mock_open_func)

        result = ensure_json_file_exists('/fake/path/data.json')

        assert result == [{"key": "value"}]
        mock_path.open.assert_called_once()

    def test_file_does_not_exist_created_with_default(self, mocker):
        """
        Verifies that a new file is created with an empty list if it doesn't exist.
        """
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)
        mock_write_json = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        mock_path_instance = MagicMock(spec=Path)
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        result = ensure_json_file_exists('/new/path/data.json')

        assert result == []
        mock_path_instance.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_write_json.assert_called_once()
        assert mock_write_json.call_args[0][1] == []

    def test_file_does_not_exist_created_with_initial_data(self, mocker):
        """
        Verifies that a new file is created with provided initial data.
        """
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)
        mock_write_json = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        mock_path_instance = MagicMock(spec=Path)
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        initial_data = [{"id": 1, "data": "initial"}]

        result = ensure_json_file_exists(
            '/new/path/data.json', initial_data=initial_data)

        assert result == initial_data
        mock_write_json.assert_called_once()
        assert mock_write_json.call_args[0][1] == initial_data


# ###############################################################
# Section 3: Tests for save_custom_file
# ###############################################################

class TestSaveCustomFile:
    """Tests for the save_custom_file function."""

    def test_save_custom_file_success(self, tmp_path):
        """
        Verifies that content is written to a file atomically and parent
        directories are created.
        """
        filepath = str(tmp_path / "subdir" / "output.txt")
        content = "This is the content to save."

        save_custom_file(filepath, content)

        assert Path(filepath).read_text(encoding='utf-8') == content

    def test_save_custom_file_io_error(self, mocker):
        """
        Verifies that an IOError is raised if the temp file cannot be written.
        """
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.parent.__str__ = lambda s: "/protected/dir"
        mock_path_instance.__str__ = lambda s: "/protected/dir/output.txt"
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance
        mocker.patch('tempfile.mkstemp', side_effect=OSError("Permission denied"))

        with pytest.raises(IOError, match="Could not write to file"):
            save_custom_file("/protected/dir/output.txt", "some content")
        mock_path_instance.parent.mkdir.assert_called_once()


# ###############################################################
# Section 4: Tests for Remaining Utility Functions
# ###############################################################

class TestChunkAndHashFunctions:
    """Tests for read/write/update_chunks_with_hashes."""

    def test_read_chunks_with_hashes(self, mocker):
        mock_data = [
            {'text_block': 'block1', 'hash': 'hash1'},
            {'text_block': 'block2', 'hash': 'hash2'},
        ]
        mocker.patch('Middleware.utilities.file_utils.ensure_json_file_exists', return_value=mock_data)

        result = read_chunks_with_hashes('/fake/path.json')

        assert result == [('block1', 'hash1'), ('block2', 'hash2')]

    def test_write_chunks_with_hashes_append(self, mocker):
        mocker.patch('Middleware.utilities.file_utils.ensure_json_file_exists',
                     return_value=[{'text_block': 'old', 'hash': 'old_hash'}])
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path')

        new_chunks = [('new', 'new_hash')]

        write_chunks_with_hashes(new_chunks, '/fake/path.json', overwrite=False)

        expected_data = [
            {'text_block': 'old', 'hash': 'old_hash'},
            {'text_block': 'new', 'hash': 'new_hash'},
        ]
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == expected_data

    def test_write_chunks_with_hashes_overwrite(self, mocker):
        mocker.patch('Middleware.utilities.file_utils.ensure_json_file_exists',
                     return_value=[{'text_block': 'old', 'hash': 'old_hash'}])
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path')

        new_chunks = [('new', 'new_hash')]

        write_chunks_with_hashes(new_chunks, '/fake/path.json', overwrite=True)

        expected_data = [{'text_block': 'new', 'hash': 'new_hash'}]
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == expected_data

    def test_update_chunks_dispatches_to_write_chunks(self, mocker):
        mock_write = mocker.patch('Middleware.utilities.file_utils.write_chunks_with_hashes')

        update_chunks_with_hashes([], 'path', mode='append')
        mock_write.assert_called_with([], 'path', encryption_key=None)

        update_chunks_with_hashes([], 'path', mode='overwrite')
        mock_write.assert_called_with([], 'path', overwrite=True, encryption_key=None)


class TestTimestampAndCustomFileFunctions:
    """Tests for timestamp and custom file loading functions."""

    def test_load_timestamp_file_exists(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch('json.load', return_value={"key": "value"})
        mocker.patch.object(mock_path, 'open', mock_open())

        result = load_timestamp_file('/fake/timestamps.json')

        assert result == {"key": "value"}

    def test_load_timestamp_file_not_exists(self, mocker):
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)

        result = load_timestamp_file('/fake/timestamps.json')

        assert result == {}

    def test_save_timestamp_file(self, mocker):
        mock_path = MagicMock(spec=Path)
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        data = {"hash": "timestamp"}

        save_timestamp_file('/fake/path.json', data)

        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == data

    def test_load_custom_file_with_delimiter_replace(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="line1--DELIM--line2"))

        result = load_custom_file('/fake/file.txt', delimiter='--DELIM--', custom_delimiter='\n')

        assert result == "line1\nline2"

    def test_load_custom_file_not_exist(self, mocker):
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)

        result = load_custom_file('/fake/nonexistent.txt')

        assert result == "Custom instruction file did not exist"

    def test_load_custom_file_is_empty(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data=""))

        result = load_custom_file('/fake/empty.txt')

        assert result == "No additional information added"


class TestPathConstructionFunctions:
    """Tests for path construction functions like get_logger_filename."""

    def test_get_logger_filename(self, mocker):
        # Use platform-specific paths consistently
        project_root = os.path.normpath('/project')
        expected_path = os.path.join(project_root, 'logs', 'wilmerai.log')

        mocker.patch('os.path.abspath', return_value=os.path.join(project_root, 'Middleware', 'utilities', 'file_utils.py'))
        mocker.patch('os.path.dirname', side_effect=[
            os.path.join(project_root, 'Middleware', 'utilities'),
            os.path.join(project_root, 'Middleware'),
            project_root,
        ])
        mocker.patch('os.path.join', side_effect=os.path.join)
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path',
                     return_value=Path(expected_path))

        result = get_logger_filename()

        assert result == expected_path


# ###############################################################
# Section 5: Tests for condensation tracker functions
# ###############################################################

class TestReadCondensationTracker:
    """Tests for the read_condensation_tracker function."""

    def test_returns_data_when_file_exists(self, mocker):
        """Verifies that tracker data is loaded and returned when the file exists."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch('json.load', return_value={"lastCondensationHash": "abc123"})
        mocker.patch.object(mock_path, 'open', mock_open())

        result = read_condensation_tracker('/fake/tracker.json')

        assert result == {"lastCondensationHash": "abc123"}

    def test_returns_empty_dict_when_file_missing(self, mocker):
        """Verifies that an empty dict is returned when the tracker file does not exist."""
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)

        result = read_condensation_tracker('/fake/nonexistent_tracker.json')

        assert result == {}

    def test_returns_empty_dict_when_path_exists_but_file_missing(self, mocker):
        """Verifies that an empty dict is returned when the resolved path does not exist on disk."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)

        result = read_condensation_tracker('/fake/tracker.json')

        assert result == {}


class TestWriteCondensationTracker:
    """Tests for the write_condensation_tracker function."""

    def test_writes_data_and_creates_directories(self, mocker):
        """Verifies that tracker data is written and parent directories are created."""
        mock_path_instance = MagicMock(spec=Path)
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        data = {"lastCondensationHash": "xyz789"}

        write_condensation_tracker('/fake/dir/tracker.json', data)

        mock_path_instance.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == data

    def test_writes_empty_dict(self, mocker):
        """Verifies that writing an empty dict works correctly."""
        mock_path_instance = MagicMock(spec=Path)
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        write_condensation_tracker('/fake/dir/tracker.json', {})

        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == {}


# ###############################################################
# Section 6: Tests for vision response cache functions
# ###############################################################

class TestReadVisionResponses:
    """Tests for the read_vision_responses function."""

    def test_returns_data_when_file_exists(self, mocker):
        """Verifies that cached data is loaded and returned when the file exists."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch('json.load', return_value={"hash1": "description1"})
        mocker.patch.object(mock_path, 'open', mock_open())

        result = read_vision_responses('/fake/vision_cache.json')

        assert result == {"hash1": "description1"}

    def test_returns_empty_dict_when_file_missing(self, mocker):
        """Verifies that an empty dict is returned when the cache file does not exist."""
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)

        result = read_vision_responses('/fake/nonexistent_cache.json')

        assert result == {}

    def test_returns_empty_dict_when_path_exists_but_file_missing(self, mocker):
        """Verifies that an empty dict is returned when the resolved path does not exist on disk."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)

        result = read_vision_responses('/fake/cache.json')

        assert result == {}


class TestWriteVisionResponses:
    """Tests for the write_vision_responses function."""

    def test_writes_data_and_creates_directories(self, mocker):
        """Verifies that cache data is written and parent directories are created."""
        mock_path_instance = MagicMock(spec=Path)
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        data = {"hash_abc": "image description"}

        write_vision_responses('/fake/dir/vision_cache.json', data)

        mock_path_instance.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == data

    def test_writes_empty_dict(self, mocker):
        """Verifies that writing an empty dict works correctly."""
        mock_path_instance = MagicMock(spec=Path)
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance
        mock_write = mocker.patch('Middleware.utilities.file_utils._write_json_file')

        write_vision_responses('/fake/dir/vision_cache.json', {})

        mock_write.assert_called_once()
        assert mock_write.call_args[0][1] == {}


# ###############################################################
# Section 7: Tests for encrypted file I/O round-trip
# ###############################################################

class TestEncryptedFileIO:
    """Tests for the encrypted read/write path in _read_json_file and _write_json_file."""

    def test_write_encrypted_read_encrypted(self, tmp_path, mocker):
        """Round-trip: write encrypted then read back with the same key."""
        fake_key = b'fake-fernet-key-32-bytes-long!=='
        test_data = {"hello": "world", "count": 42}

        marker = b'ENC:'
        mocker.patch('Middleware.utilities.encryption_utils.encrypt_bytes',
                     side_effect=lambda data, key: marker + data)
        mocker.patch('Middleware.utilities.encryption_utils.decrypt_bytes',
                     side_effect=lambda data, key: data[len(marker):])

        file_path = tmp_path / "test.json"
        _write_json_file(file_path, test_data, encryption_key=fake_key)

        result = _read_json_file(file_path, encryption_key=fake_key)
        assert result == test_data

    def test_read_plaintext_fallback_with_encryption_key(self, tmp_path, mocker):
        """When decrypt fails, falls back to reading as plaintext JSON."""
        from cryptography.fernet import InvalidToken
        fake_key = b'fake-fernet-key-32-bytes-long!=='
        test_data = [1, 2, 3]

        file_path = tmp_path / "plaintext.json"
        file_path.write_text(json.dumps(test_data))

        mocker.patch('Middleware.utilities.encryption_utils.decrypt_bytes',
                     side_effect=InvalidToken)

        result = _read_json_file(file_path, encryption_key=fake_key)
        assert result == test_data

    def test_corrupted_file_raises_clear_error(self, tmp_path, mocker):
        """Neither valid ciphertext nor valid JSON raises JSONDecodeError."""
        from cryptography.fernet import InvalidToken
        fake_key = b'fake-fernet-key-32-bytes-long!=='

        file_path = tmp_path / "corrupted.json"
        file_path.write_text("not valid json {{{")

        mocker.patch('Middleware.utilities.encryption_utils.decrypt_bytes',
                     side_effect=InvalidToken)

        with pytest.raises(json.JSONDecodeError):
            _read_json_file(file_path, encryption_key=fake_key)
