# Tests/utilities/test_file_utils.py

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open

import pytest

from Middleware.utilities.file_utils import (
    _resolve_case_insensitive_path,
    ensure_json_file_exists,
    get_logger_filename,
    load_custom_file,
    load_timestamp_file,
    read_chunks_with_hashes,
    save_custom_file,
    save_timestamp_file,
    update_chunks_with_hashes,
    write_chunks_with_hashes,
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
        # Arrange
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = True
        mock_Path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_Path_class.return_value = mock_path_instance

        # Act
        result = _resolve_case_insensitive_path('/mock/path/file.txt')

        # Assert
        assert result == mock_path_instance
        mock_path_instance.exists.assert_called_once()
        mock_Path_class.assert_called_once_with('/mock/path/file.txt')

    def test_path_exists_case_insensitive_match(self, mocker):
        """
        Verifies that a path is found even if its casing is incorrect.
        """
        # Arrange
        correct_path = Path('/mock/path/File.txt')
        incorrect_path_str = '/mock/path/file.txt'

        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = False
        mock_path_instance.parent.exists.return_value = True
        mock_path_instance.parent.iterdir.return_value = [correct_path]
        mock_path_instance.name = 'file.txt'

        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        # Act
        result = _resolve_case_insensitive_path(incorrect_path_str)

        # Assert
        assert result == correct_path

    def test_path_does_not_exist(self, mocker):
        """
        Verifies that None is returned when no matching file is found.
        """
        # Arrange
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = False
        mock_path_instance.parent.exists.return_value = True
        mock_path_instance.parent.iterdir.return_value = [Path('/mock/path/other.txt')]
        mock_path_instance.name = 'nonexistent.txt'
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        # Act
        result = _resolve_case_insensitive_path('/mock/path/nonexistent.txt')

        # Assert
        assert result is None

    def test_parent_directory_does_not_exist(self, mocker):
        """
        Verifies that None is returned if the parent directory doesn't exist.
        """
        # Arrange
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.exists.return_value = False
        mock_path_instance.parent.exists.return_value = False
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)

        # Act
        result = _resolve_case_insensitive_path('/nonexistent/dir/file.txt')

        # Assert
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
        # Arrange
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)

        mock_file_content = json.dumps([{"key": "value"}])
        mock_open_func = mock_open(read_data=mock_file_content)
        mocker.patch.object(mock_path, 'open', mock_open_func)

        # Act
        result = ensure_json_file_exists('/fake/path/data.json')

        # Assert
        assert result == [{"key": "value"}]
        mock_path.open.assert_called_once()

    def test_file_does_not_exist_created_with_default(self, mocker):
        """
        Verifies that a new file is created with an empty list if it doesn't exist.
        """
        # Arrange
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)
        mock_path_instance = MagicMock(spec=Path)
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)
        mocker.patch.object(mock_path_instance, 'open', mock_open())

        # Act
        result = ensure_json_file_exists('/new/path/data.json')

        # Assert
        assert result == []
        mock_path_instance.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_path_instance.open.assert_called_once_with('w')
        mock_path_instance.open().__enter__().write.assert_called_once_with("[]")

    def test_file_does_not_exist_created_with_initial_data(self, mocker):
        """
        Verifies that a new file is created with provided initial data.
        """
        # Arrange
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)
        mock_json_dump = mocker.patch('json.dump')

        mock_path_instance = MagicMock(spec=Path)
        mocker.patch('Middleware.utilities.file_utils.Path', return_value=mock_path_instance)
        mocker.patch.object(mock_path_instance, 'open', mock_open())

        initial_data = [{"id": 1, "data": "initial"}]

        # Act
        result = ensure_json_file_exists(
            '/new/path/data.json', initial_data=initial_data)

        # Assert
        assert result == initial_data
        mock_json_dump.assert_called_once()
        assert mock_json_dump.call_args[0][0] == initial_data


# ###############################################################
# Section 3: Tests for save_custom_file
# ###############################################################

class TestSaveCustomFile:
    """Tests for the save_custom_file function."""

    def test_save_custom_file_success(self, mocker):
        """
        Verifies that content is written to a file and parent directories are created.
        """
        # Arrange
        mock_path_instance = MagicMock(spec=Path)
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance
        mock_open_func = mock_open()
        mocker.patch.object(mock_path_instance, 'open', mock_open_func)

        filepath = "/mock/dir/output.txt"
        content = "This is the content to save."

        # Act
        save_custom_file(filepath, content)

        # Assert
        mock_path_instance.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_path_instance.open.assert_called_once_with("w", encoding="utf-8")
        mock_open_func().write.assert_called_once_with(content)

    def test_save_custom_file_io_error(self, mocker):
        """
        Verifies that an IOError is raised if the file cannot be written to.
        """
        # Arrange
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.open.side_effect = IOError("Permission denied")
        mock_path_class = mocker.patch('Middleware.utilities.file_utils.Path')
        mock_path_class.return_value = mock_path_instance

        # Act & Assert
        with pytest.raises(IOError, match="Could not write to file"):
            save_custom_file("/protected/dir/output.txt", "some content")
        mock_path_instance.parent.mkdir.assert_called_once()


# ###############################################################
# Section 4: Tests for Remaining Utility Functions
# ###############################################################

class TestChunkAndHashFunctions:
    """Tests for read/write/update_chunks_with_hashes."""

    def test_read_chunks_with_hashes(self, mocker):
        # Arrange
        mock_data = [
            {'text_block': 'block1', 'hash': 'hash1'},
            {'text_block': 'block2', 'hash': 'hash2'},
        ]
        mocker.patch('Middleware.utilities.file_utils.ensure_json_file_exists', return_value=mock_data)

        # Act
        result = read_chunks_with_hashes('/fake/path.json')

        # Assert
        assert result == [('block1', 'hash1'), ('block2', 'hash2')]

    def test_write_chunks_with_hashes_append(self, mocker):
        # Arrange
        mocker.patch('Middleware.utilities.file_utils.ensure_json_file_exists',
                     return_value=[{'text_block': 'old', 'hash': 'old_hash'}])
        mock_dump = mocker.patch('json.dump')
        mocker.patch('pathlib.Path.open', mock_open())
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path')

        new_chunks = [('new', 'new_hash')]

        # Act
        write_chunks_with_hashes(new_chunks, '/fake/path.json', overwrite=False)

        # Assert
        expected_data = [
            {'text_block': 'old', 'hash': 'old_hash'},
            {'text_block': 'new', 'hash': 'new_hash'},
        ]
        mock_dump.assert_called_once_with(expected_data, mocker.ANY, indent=4)

    def test_write_chunks_with_hashes_overwrite(self, mocker):
        # Arrange
        mocker.patch('Middleware.utilities.file_utils.ensure_json_file_exists',
                     return_value=[{'text_block': 'old', 'hash': 'old_hash'}])
        mock_dump = mocker.patch('json.dump')
        mocker.patch('pathlib.Path.open', mock_open())
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path')

        new_chunks = [('new', 'new_hash')]

        # Act
        write_chunks_with_hashes(new_chunks, '/fake/path.json', overwrite=True)

        # Assert
        expected_data = [{'text_block': 'new', 'hash': 'new_hash'}]
        mock_dump.assert_called_once_with(expected_data, mocker.ANY, indent=4)

    def test_update_chunks_dispatches_to_write_chunks(self, mocker):
        # Arrange
        mock_write = mocker.patch('Middleware.utilities.file_utils.write_chunks_with_hashes')

        # Act & Assert for append mode
        update_chunks_with_hashes([], 'path', mode='append')
        mock_write.assert_called_with([], 'path')

        # Act & Assert for overwrite mode
        update_chunks_with_hashes([], 'path', mode='overwrite')
        mock_write.assert_called_with([], 'path', overwrite=True)


class TestTimestampAndCustomFileFunctions:
    """Tests for timestamp and custom file loading functions."""

    def test_load_timestamp_file_exists(self, mocker):
        # Arrange
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch('json.load', return_value={"key": "value"})
        mocker.patch.object(mock_path, 'open', mock_open())

        # Act
        result = load_timestamp_file('/fake/timestamps.json')

        # Assert
        assert result == {"key": "value"}

    def test_load_timestamp_file_not_exists(self, mocker):
        # Arrange
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)

        # Act
        result = load_timestamp_file('/fake/timestamps.json')

        # Assert
        assert result == {}

    def test_save_timestamp_file(self, mocker):
        # Arrange
        mock_path = MagicMock(spec=Path)
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mock_open_func = mock_open()
        mocker.patch.object(mock_path, 'open', mock_open_func)
        mock_dump = mocker.patch('json.dump')

        data = {"hash": "timestamp"}

        # Act
        save_timestamp_file('/fake/path.json', data)

        # Assert
        mock_dump.assert_called_once_with(data, mock_open_func(), indent=4)

    def test_load_custom_file_with_delimiter_replace(self, mocker):
        # Arrange
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="line1--DELIM--line2"))

        # Act
        result = load_custom_file('/fake/file.txt', delimiter='--DELIM--', custom_delimiter='\n')

        # Assert
        assert result == "line1\nline2"

    def test_load_custom_file_not_exist(self, mocker):
        # Arrange
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=None)

        # Act
        result = load_custom_file('/fake/nonexistent.txt')

        # Assert
        assert result == "Custom instruction file did not exist"

    def test_load_custom_file_is_empty(self, mocker):
        # Arrange
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data=""))

        # Act
        result = load_custom_file('/fake/empty.txt')

        # Assert
        assert result == "No additional information added"


class TestPathConstructionFunctions:
    """Tests for path construction functions like get_logger_filename."""

    def test_get_logger_filename(self, mocker):
        # Arrange
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

        # Act
        result = get_logger_filename()

        # Assert
        assert result == expected_path
