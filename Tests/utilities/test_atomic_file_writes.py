"""Exercise the shared storage writer with one deterministic short write."""
from Middleware.utilities import file_utils
import pytest


def test_shared_atomic_writer_completes_short_write(tmp_path, monkeypatch):
    target = tmp_path / 'notes.txt'
    target.write_bytes(b'previous complete contents')
    original_write = file_utils.os.write

    def short_write(fd, data):
        return original_write(fd, data[:2])

    monkeypatch.setattr(file_utils.os, 'write', short_write)
    file_utils.save_custom_file(str(target), 'replacement contents')
    assert target.read_bytes() == b'replacement contents'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['notes.txt']


@pytest.mark.parametrize('failure', ['zero', 'error'])
def test_failed_atomic_write_preserves_destination_and_removes_temp(tmp_path, monkeypatch, failure):
    target = tmp_path / 'notes.txt'
    target.write_bytes(b'previous complete contents')
    original_write = file_utils.os.write
    calls = 0

    def incomplete_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(fd, data[:2])
        if failure == 'error':
            raise OSError('synthetic disk failure')
        return 0

    monkeypatch.setattr(file_utils.os, 'write', incomplete_write)
    with pytest.raises(OSError):
        file_utils.save_custom_file(str(target), 'replacement contents')
    assert target.read_bytes() == b'previous complete contents'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['notes.txt']
