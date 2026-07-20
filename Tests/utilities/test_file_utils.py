import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open

import pytest

from Middleware.utilities.file_utils import (
    _resolve_case_insensitive_path,
    _read_json_file,
    _write_json_file,
    ensure_json_file_exists,
    load_custom_file,
    load_timestamp_file,
    read_chunks_with_hashes,
    read_condensation_tracker,
    read_plain_text_file,
    read_vision_responses,
    save_custom_file,
    save_timestamp_file,
    update_chunks_with_hashes,
    write_chunks_with_hashes,
    write_condensation_tracker,
    write_plain_text_file,
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

    def test_file_exists_with_non_list_json_raises_type_error(self, mocker):
        """
        Verifies that a corrupted file containing a JSON object (not a list)
        raises a TypeError with a clear message instead of returning bad data.
        """
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data=json.dumps({"not": "a list"})))

        with pytest.raises(TypeError, match="Expected a JSON list"):
            ensure_json_file_exists('/fake/path/data.json')

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

    def test_save_custom_file_append(self, tmp_path):
        """Append mode should add content to the end of an existing file."""
        filepath = str(tmp_path / "log.txt")

        save_custom_file(filepath, "first")
        save_custom_file(filepath, "second", mode="append")

        assert Path(filepath).read_text(encoding='utf-8') == "firstsecond"

    def test_save_custom_file_append_creates_missing_file(self, tmp_path):
        """Append mode should create the file when it does not yet exist."""
        filepath = str(tmp_path / "new.txt")

        save_custom_file(filepath, "hello", mode="append")

        assert Path(filepath).read_text(encoding='utf-8') == "hello"

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

    def test_save_custom_file_replace_swaps_all_occurrences(self, tmp_path):
        """Replace mode should swap every occurrence and leave surrounding text intact."""
        filepath = str(tmp_path / "notes.txt")
        save_custom_file(filepath, "alpha X beta X gamma")

        count = save_custom_file(filepath, "Y", mode="replace", find="X")

        assert count == 2
        assert Path(filepath).read_text(encoding='utf-8') == "alpha Y beta Y gamma"

    def test_save_custom_file_replace_no_match_leaves_file_unchanged(self, tmp_path):
        """Replace mode should report zero and not alter the file when find is absent."""
        filepath = str(tmp_path / "notes.txt")
        save_custom_file(filepath, "the original text")

        count = save_custom_file(filepath, "new", mode="replace", find="missing")

        assert count == 0
        assert Path(filepath).read_text(encoding='utf-8') == "the original text"

    def test_save_custom_file_replace_missing_file_is_noop(self, tmp_path):
        """Replace mode should not create a file that does not exist."""
        filepath = str(tmp_path / "absent.txt")

        count = save_custom_file(filepath, "new", mode="replace", find="old")

        assert count == 0
        assert not Path(filepath).exists()

    def test_save_custom_file_remove_deletes_matching_lines(self, tmp_path):
        """Remove mode should delete whole lines containing the target text."""
        filepath = str(tmp_path / "list.md")
        save_custom_file(filepath, "keep one\ndrop this line\nkeep two\n")

        count = save_custom_file(filepath, "", mode="remove", find="drop this")

        assert count == 1
        assert Path(filepath).read_text(encoding='utf-8') == "keep one\nkeep two\n"

    def test_save_custom_file_remove_no_match_leaves_file_unchanged(self, tmp_path):
        """Remove mode should report zero and not alter the file when find is absent."""
        filepath = str(tmp_path / "list.md")
        save_custom_file(filepath, "keep one\nkeep two\n")

        count = save_custom_file(filepath, "", mode="remove", find="nothing")

        assert count == 0
        assert Path(filepath).read_text(encoding='utf-8') == "keep one\nkeep two\n"

    def test_save_custom_file_remove_missing_file_is_noop(self, tmp_path):
        """Remove mode should not create a file that does not exist."""
        filepath = str(tmp_path / "absent.md")

        count = save_custom_file(filepath, "", mode="remove", find="anything")

        assert count == 0
        assert not Path(filepath).exists()

    def test_save_custom_file_replace_requires_find(self, tmp_path):
        """Replace mode without a find value should raise a ValueError."""
        filepath = str(tmp_path / "notes.txt")
        save_custom_file(filepath, "content")

        with pytest.raises(ValueError, match="requires a non-empty 'find'"):
            save_custom_file(filepath, "new", mode="replace")

    def test_save_custom_file_remove_requires_find(self, tmp_path):
        """Remove mode without a find value should raise a ValueError."""
        filepath = str(tmp_path / "notes.txt")
        save_custom_file(filepath, "content")

        with pytest.raises(ValueError, match="requires a non-empty 'find'"):
            save_custom_file(filepath, "", mode="remove", find="")

    def test_save_custom_file_trim_removes_blank_lines(self, tmp_path):
        """Trim mode should drop blank / whitespace-only lines and keep the content lines in order."""
        filepath = str(tmp_path / "log.md")
        save_custom_file(filepath, "one\n\ntwo\n   \nthree\n\n")
        removed = save_custom_file(filepath, "", mode="trim")
        assert removed == 3
        assert Path(filepath).read_text(encoding="utf-8") == "one\ntwo\nthree\n"

    def test_save_custom_file_trim_no_blank_lines_is_noop(self, tmp_path):
        """Trim with no blank lines returns 0 and leaves the file untouched."""
        filepath = str(tmp_path / "log.md")
        save_custom_file(filepath, "one\ntwo\n")
        assert save_custom_file(filepath, "", mode="trim") == 0
        assert Path(filepath).read_text(encoding="utf-8") == "one\ntwo\n"

    def test_save_custom_file_trim_missing_file_is_noop(self, tmp_path):
        """Trim on a missing file returns 0 and creates nothing (existing-file-only)."""
        filepath = str(tmp_path / "absent.md")
        assert save_custom_file(filepath, "", mode="trim") == 0
        assert not Path(filepath).exists()

    def test_save_custom_file_trim_needs_no_find_or_content(self, tmp_path):
        """Trim requires neither 'find' nor 'content'."""
        filepath = str(tmp_path / "log.md")
        save_custom_file(filepath, "a\n\nb\n")
        assert save_custom_file(filepath, None, mode="trim") == 1  # content=None is fine for trim


class TestHomeDirectoryExpansion:
    """A leading '~' must expand to the home directory consistently across writing, reading, and
    existence resolution. If write expands it but a lookup does not, a file is written to the real
    home but looked up as a literal '~' directory and never found; that is the class of bug that made the
    chunk-cursor cold-start and re-process on every run. HOME is redirected to a temp dir in each
    test so nothing touches the real home directory."""

    def test_save_custom_file_expands_tilde_to_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        save_custom_file("~/wilmer_test/output.txt", "hello")
        # Written under the EXPANDED home path...
        assert (tmp_path / "wilmer_test" / "output.txt").read_text(encoding="utf-8") == "hello"
        # ...and NOT as a literal '~' directory relative to the working dir.
        assert not Path("~/wilmer_test/output.txt").exists()

    def test_save_then_load_tilde_path_roundtrips(self, tmp_path, monkeypatch):
        # The key invariant: save and load resolve the SAME '~' path to the SAME file.
        monkeypatch.setenv("HOME", str(tmp_path))
        save_custom_file("~/wilmer_test/notes.md", "line one")
        assert load_custom_file("~/wilmer_test/notes.md") == "line one"

    def test_load_custom_file_missing_tilde_path_reports_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert load_custom_file("~/wilmer_test/absent.md") == "Custom instruction file did not exist"

    def test_append_mode_expands_tilde(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        save_custom_file("~/wilmer_test/log.txt", "a")
        save_custom_file("~/wilmer_test/log.txt", "b", mode="append")
        assert (tmp_path / "wilmer_test" / "log.txt").read_text(encoding="utf-8") == "ab"

    def test_remove_mode_acts_on_expanded_tilde_file(self, tmp_path, monkeypatch):
        # A surgical edit must act on the same expanded file the write created (existing-file-only).
        monkeypatch.setenv("HOME", str(tmp_path))
        save_custom_file("~/wilmer_test/list.md", "keep\ndrop me\nkeep2\n")
        changed = save_custom_file("~/wilmer_test/list.md", "", mode="remove", find="drop me")
        assert changed == 1
        assert (tmp_path / "wilmer_test" / "list.md").read_text(encoding="utf-8") == "keep\nkeep2\n"

    def test_resolve_case_insensitive_path_expands_tilde(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "wilmer_test").mkdir()
        (tmp_path / "wilmer_test" / "file.txt").write_text("x", encoding="utf-8")
        resolved = _resolve_case_insensitive_path("~/wilmer_test/file.txt")
        assert resolved is not None and resolved.exists()
        assert "~" not in str(resolved)


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
        # Real json.load parses the file content, so the parsing path is exercised.
        mocker.patch.object(mock_path, 'open', mock_open(read_data=json.dumps({"key": "value"})))

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

    def test_load_custom_file_tail_count(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="l1\nl2\nl3\nl4"))

        result = load_custom_file('/fake/file.txt', tail_count=2)

        assert result == "l3\nl4"

    def test_load_custom_file_head_count(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="l1\nl2\nl3\nl4"))

        result = load_custom_file('/fake/file.txt', head_count=2)

        assert result == "l1\nl2"

    def test_load_custom_file_tail_count_custom_chunk_delimiter(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="A\n\n---\n\nB\n\n---\n\nC"))

        result = load_custom_file('/fake/file.txt', tail_count=2, chunk_delimiter="\n\n---\n\n")

        assert result == "B\n\n---\n\nC"

    def test_load_custom_file_tail_count_exceeds_length(self, mocker):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="l1\nl2"))

        result = load_custom_file('/fake/file.txt', tail_count=10)

        assert result == "l1\nl2"

    def test_load_custom_file_tail_count_zero_returns_empty(self, mocker):
        """tail_count=0 keeps no chunks (and must not hit the parts[-0:] == whole-list trap)."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="l1\nl2\nl3"))

        result = load_custom_file('/fake/file.txt', tail_count=0)

        assert result == ""

    def test_load_custom_file_negative_head_count_returns_empty(self, mocker):
        """A negative head_count is clamped to no chunks rather than parts[:-1] dropping from the end."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="l1\nl2\nl3"))

        result = load_custom_file('/fake/file.txt', head_count=-1)

        assert result == ""

    def test_load_custom_file_empty_chunk_delimiter_falls_back_to_newline(self, mocker):
        """An empty chunk_delimiter falls back to '\\n' instead of splitting on ''."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mocker.patch('Middleware.utilities.file_utils._resolve_case_insensitive_path', return_value=mock_path)
        mocker.patch.object(mock_path, 'open', mock_open(read_data="l1\nl2\nl3"))

        result = load_custom_file('/fake/file.txt', tail_count=2, chunk_delimiter="")

        assert result == "l2\nl3"


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
        # Real json.load parses the file content, so the parsing path is exercised.
        mocker.patch.object(mock_path, 'open', mock_open(read_data=json.dumps({"lastCondensationHash": "abc123"})))

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
        # Real json.load parses the file content, so the parsing path is exercised.
        mocker.patch.object(mock_path, 'open', mock_open(read_data=json.dumps({"hash1": "description1"})))

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

    @pytest.mark.parametrize("decrypt_error", [
        ValueError("token is malformed"),
        UnicodeDecodeError('utf-8', b'\x80', 0, 1, 'invalid start byte'),
    ], ids=['ValueError', 'UnicodeDecodeError'])
    def test_read_plaintext_fallback_on_other_decrypt_errors(self, tmp_path, mocker, decrypt_error):
        """
        The fallback also catches ValueError and UnicodeDecodeError from the
        decrypt/decode step, not just InvalidToken.
        """
        fake_key = b'fake-fernet-key-32-bytes-long!=='
        test_data = {"fallback": "works"}

        file_path = tmp_path / "plaintext.json"
        file_path.write_text(json.dumps(test_data))

        mocker.patch('Middleware.utilities.encryption_utils.decrypt_bytes',
                     side_effect=decrypt_error)

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

    def test_plaintext_invalid_json_without_key_raises(self, tmp_path):
        """With no encryption key, an invalid-JSON file surfaces JSONDecodeError
        rather than being swallowed (the non-encrypted read error branch)."""
        file_path = tmp_path / "broken.json"
        file_path.write_text("{ not json")

        with pytest.raises(json.JSONDecodeError):
            _read_json_file(file_path, encryption_key=None)


# ###############################################################
# Section: Tests for read_plain_text_file / write_plain_text_file
# ###############################################################

class TestPlainTextFileIO:
    """Tests for the plain-text helpers used by the state document feature."""

    def test_read_missing_file_returns_empty_string(self, tmp_path):
        assert read_plain_text_file(str(tmp_path / "missing.md")) == ''

    def test_write_and_read_roundtrip_creates_parent_dirs(self, tmp_path):
        filepath = str(tmp_path / "sub" / "state_document.md")

        write_plain_text_file(filepath, "## Section\n- fact")

        assert read_plain_text_file(filepath) == "## Section\n- fact"

    def test_write_without_backup_suffix_creates_no_backup(self, tmp_path):
        filepath = str(tmp_path / "doc.md")

        write_plain_text_file(filepath, "v1")
        write_plain_text_file(filepath, "v2")

        assert read_plain_text_file(filepath) == "v2"
        assert not Path(filepath + ".bak").exists()

    def test_write_with_backup_preserves_previous_version(self, tmp_path):
        filepath = str(tmp_path / "doc.md")

        write_plain_text_file(filepath, "v1")
        write_plain_text_file(filepath, "v2", backup_suffix=".bak")

        assert read_plain_text_file(filepath) == "v2"
        assert read_plain_text_file(filepath + ".bak") == "v1"

    def test_backup_skipped_on_first_write(self, tmp_path):
        filepath = str(tmp_path / "doc.md")

        write_plain_text_file(filepath, "v1", backup_suffix=".bak")

        assert not Path(filepath + ".bak").exists()

    def test_failed_backup_aborts_write_and_keeps_current_content(self, tmp_path, mocker):
        filepath = str(tmp_path / "doc.md")
        write_plain_text_file(filepath, "v1")
        mocker.patch('Middleware.utilities.file_utils.shutil.copy2', side_effect=OSError("disk full"))

        with pytest.raises(OSError):
            write_plain_text_file(filepath, "v2", backup_suffix=".bak")

        assert read_plain_text_file(filepath) == "v1"

    def test_encrypted_write_and_read_roundtrip(self, tmp_path):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        filepath = str(tmp_path / "doc.md")

        write_plain_text_file(filepath, "secret content", encryption_key=key)

        assert b"secret content" not in (tmp_path / "doc.md").read_bytes()
        assert read_plain_text_file(filepath, encryption_key=key) == "secret content"

    def test_read_plaintext_fallback_with_encryption_key(self, tmp_path):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        file_path = tmp_path / "doc.md"
        file_path.write_text("plain old text")

        assert read_plain_text_file(str(file_path), encryption_key=key) == "plain old text"
