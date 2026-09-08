"""Data preservation across encryption opt-in, incompatible keys, and write failures."""
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet

from Middleware.utilities import config_utils, encryption_utils, file_utils
from Middleware.workflows.tools.slow_but_quality_rag_tool import SlowButQualityRAGTool


@pytest.mark.parametrize('setting', [None, False])
def test_encryption_defaults_off_without_deriving_a_key(monkeypatch, setting):
    monkeypatch.setattr(config_utils, 'get_config_value', lambda _: setting)
    derive = Mock(side_effect=AssertionError('Encryption must remain off'))
    monkeypatch.setattr(encryption_utils, 'derive_fernet_key', derive)
    assert encryption_utils.get_encryption_key_if_available('synthetic-key') is None
    derive.assert_not_called()


@pytest.mark.parametrize('setting', ['false', 'true', 0, 1, [], {}])
def test_encryption_rejects_non_boolean_opt_in(monkeypatch, setting):
    monkeypatch.setattr(config_utils, 'get_config_value', lambda _: setting)
    with pytest.raises(ValueError, match='JSON boolean'):
        encryption_utils.get_encryption_key_if_available('synthetic-key')


def test_july_ciphertext_and_namespace_remain_compatible(tmp_path):
    # Fixed synthetic ciphertext checks persisted-format compatibility independently
    # of tokens produced by the current implementation.
    token = (b'gAAAAABqngtyNnPvRgRX200_3LtzMG2Obdnp9qGFaxhL89_LBqKmsfGC9eo6j5OHnNH1ltJ22C_H'
             b'RzamfZfQPXPYJSJUz90pkWCPhEB3Mm07af9kejgU-tbrekqCLeBibqxWNPjkFCr8')
    secret = 'synthetic-july-compatibility-key'
    key = encryption_utils.derive_fernet_key(secret, username='compatibility-user')
    assert key == b'o-avZFzXj00f7pLyc4LDaVE0B6xM4f4lIPVDbJeWUEc='
    assert encryption_utils.hash_api_key(secret) == '40025469114d133c'
    path = tmp_path / 'memories.json'
    path.write_bytes(token)
    assert file_utils._read_json_file(path, key) == {'valuable': 'July synthetic content'}
    assert path.read_bytes() == token


def test_enabling_encryption_reads_plaintext_without_rewriting_it(tmp_path):
    key = Fernet.generate_key()
    memory = tmp_path / 'memories.json'
    state = tmp_path / 'state_document.md'
    original = b'[ {"text_block": "existing memory", "hash": "old"} ]'
    memory.write_bytes(original)
    state.write_text('Existing state', encoding='utf-8')
    assert file_utils.read_chunks_with_hashes(str(memory), key) == [('existing memory', 'old')]
    assert file_utils.read_plain_text_file(str(state), key) == 'Existing state'
    assert memory.read_bytes() == original
    assert state.read_bytes() == b'Existing state'
    file_utils.write_chunks_with_hashes([('new memory', 'new')], str(memory), encryption_key=key)
    assert file_utils.read_chunks_with_hashes(str(memory), key) == [
        ('existing memory', 'old'), ('new memory', 'new')]
    file_utils.write_plain_text_file(str(state), 'Existing state\nNew fact', key, '.bak')
    assert file_utils.read_plain_text_file(str(state), key) == 'Existing state\nNew fact'
    assert file_utils.read_plain_text_file(str(state) + '.bak', key) == 'Existing state'


@pytest.mark.parametrize('access', ['disabled', 'wrong_key', 'changed_workflow'])
def test_unreadable_state_and_backup_are_preserved(tmp_path, access):
    key = encryption_utils.derive_fernet_key('synthetic-key', username='original')
    supplied = {'disabled': None, 'wrong_key': Fernet.generate_key(),
                'changed_workflow': encryption_utils.derive_fernet_key('synthetic-key', username='other')}[access]
    state = tmp_path / 'state_document.md'
    backup = tmp_path / 'state_document.md.bak'
    file_utils.write_plain_text_file(str(state), 'Previous valuable state', key)
    file_utils.write_plain_text_file(str(state), 'Current valuable state', key, '.bak')
    original, prior = state.read_bytes(), backup.read_bytes()
    with pytest.raises(ValueError, match='original API key'):
        file_utils.read_plain_text_file(str(state), supplied)
    with pytest.raises(ValueError, match='original API key'):
        file_utils.write_plain_text_file(str(state), 'replacement', supplied, '.bak')
    assert state.read_bytes() == original
    assert backup.read_bytes() == prior


@pytest.mark.parametrize('writer', [file_utils.save_timestamp_file, file_utils.write_condensation_tracker,
                                  file_utils.write_vision_responses])
@pytest.mark.parametrize('disabled', [False, True])
def test_direct_json_writes_cannot_overwrite_incompatible_encrypted_data(tmp_path, writer, disabled):
    key = Fernet.generate_key()
    path = tmp_path / 'state.json'
    writer(str(path), {'valuable': 'original'}, key)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        writer(str(path), {'replacement': True}, None if disabled else Fernet.generate_key())
    assert path.read_bytes() == original
    assert file_utils._read_json_file(path, key) == {'valuable': 'original'}


def test_corrupt_json_is_not_replaced_by_direct_writer(tmp_path):
    path = tmp_path / 'timestamps.json'
    original = b'{"valuable": "interrupted'
    path.write_bytes(original)
    with pytest.raises(ValueError):
        file_utils.save_timestamp_file(str(path), {})
    assert path.read_bytes() == original


@pytest.mark.parametrize('damage', ['truncate', 'authentication'])
def test_damaged_state_token_never_becomes_plaintext(tmp_path, damage):
    key = Fernet.generate_key()
    token = Fernet(key).encrypt(b'valuable state')
    token = token[:20] if damage == 'truncate' else token[:-8] + b'AAAAAAAA'
    path = tmp_path / 'state_document.md'
    path.write_bytes(token)
    with pytest.raises(ValueError, match='original API key'):
        file_utils.write_plain_text_file(str(path), 'replacement', key, '.bak')
    assert path.read_bytes() == token
    assert not (tmp_path / 'state_document.md.bak').exists()


def test_state_update_does_not_send_ciphertext_to_workflow_or_overwrite_it(tmp_path, monkeypatch):
    path = tmp_path / 'state_document.md'
    token = Fernet(Fernet.generate_key()).encrypt(b'valuable state')
    path.write_bytes(token)
    monkeypatch.setattr('Middleware.workflows.tools.slow_but_quality_rag_tool.'
                        'get_discussion_state_document_file_path', lambda *args, **kwargs: str(path))
    context = SimpleNamespace(discussion_id='synthetic', api_key_hash=None, encryption_key=None,
                              workflow_manager=Mock())
    SlowButQualityRAGTool()._update_state_document(
        {'useStateDocument': True, 'stateDocumentWorkflowName': 'synthetic'}, context, ['new fact'])
    context.workflow_manager.run_custom_workflow.assert_not_called()
    assert path.read_bytes() == token


@pytest.mark.parametrize('failure', ['write', 'fsync', 'replace'])
def test_failed_backup_preserves_both_current_and_previous_versions(tmp_path, monkeypatch, failure):
    state, backup = tmp_path / 'state_document.md', tmp_path / 'state_document.md.bak'
    state.write_bytes(b'current valuable state')
    backup.write_bytes(b'previous valuable state')
    def fail(*args):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(file_utils.os, failure, fail)
    with pytest.raises(OSError):
        file_utils.write_plain_text_file(str(state), 'replacement', backup_suffix='.bak')
    assert state.read_bytes() == b'current valuable state'
    assert backup.read_bytes() == b'previous valuable state'
    assert sorted(p.name for p in tmp_path.iterdir()) == [state.name, backup.name]


def test_encryption_failure_leaves_both_state_versions_unchanged(tmp_path, monkeypatch):
    state, backup = tmp_path / 'state_document.md', tmp_path / 'state_document.md.bak'
    state.write_bytes(b'current valuable state')
    backup.write_bytes(b'previous valuable state')
    monkeypatch.setattr(encryption_utils, 'encrypt_bytes', Mock(side_effect=RuntimeError('synthetic failure')))
    with pytest.raises(RuntimeError):
        file_utils.write_plain_text_file(str(state), 'replacement', Fernet.generate_key(), '.bak')
    assert state.read_bytes() == b'current valuable state'
    assert backup.read_bytes() == b'previous valuable state'


def test_short_writes_preserve_encrypted_state_and_backup(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    state = tmp_path / 'state_document.md'
    backup = tmp_path / 'state_document.md.bak'
    unrelated = tmp_path / 'unrelated.json'
    unrelated.write_bytes(b'{"synthetic_setting": true}')
    file_utils.write_plain_text_file(str(state), 'Previous valuable state', key)
    previous_token = state.read_bytes()
    original_write = file_utils.os.write
    monkeypatch.setattr(file_utils.os, 'write', lambda fd, data: original_write(fd, data[:7]))

    file_utils.write_plain_text_file(str(state), 'Current valuable state', key, '.bak')

    assert Fernet(key).decrypt(state.read_bytes()) == b'Current valuable state'
    assert backup.read_bytes() == previous_token
    assert Fernet(key).decrypt(backup.read_bytes()) == b'Previous valuable state'
    assert unrelated.read_bytes() == b'{"synthetic_setting": true}'
    assert sorted(path.name for path in tmp_path.iterdir()) == [state.name, backup.name, unrelated.name]


def test_incompatible_backup_is_preserved_even_when_current_state_is_plaintext(tmp_path):
    state, backup = tmp_path / 'state_document.md', tmp_path / 'state_document.md.bak'
    state.write_bytes(b'current valuable state')
    original = Fernet(Fernet.generate_key()).encrypt(b'previous valuable state')
    backup.write_bytes(original)
    with pytest.raises(ValueError):
        file_utils.write_plain_text_file(str(state), 'replacement', Fernet.generate_key(), '.bak')
    assert state.read_bytes() == b'current valuable state'
    assert backup.read_bytes() == original


@pytest.mark.parametrize('failure', [PermissionError, OSError])
@pytest.mark.parametrize('operation', ['read_state', 'write_state', 'write_backup', 'write_json', 'read_json'])
def test_metadata_failure_does_not_treat_existing_data_as_missing(tmp_path, monkeypatch, failure, operation):
    key = Fernet.generate_key()
    state = tmp_path / 'state_document.md'
    backup = tmp_path / 'state_document.md.bak'
    memory = tmp_path / 'memories.json'
    originals = {
        state: Fernet(key).encrypt(b'Current valuable state'),
        backup: Fernet(key).encrypt(b'Previous valuable state'),
        memory: Fernet(key).encrypt(b'[{"text_block": "valuable memory", "hash": "old"}]'),
    }
    for path, content in originals.items():
        path.write_bytes(content)
    target = backup if operation == 'write_backup' else memory if operation.endswith('json') else state
    original_stat = Path.stat

    def fail_metadata(path, *args, **kwargs):
        if path == target:
            raise failure('Synthetic metadata failure')
        return original_stat(path, *args, **kwargs)

    with monkeypatch.context() as metadata_patch:
        metadata_patch.setattr(Path, 'stat', fail_metadata)
        with pytest.raises(OSError, match='Synthetic metadata failure'):
            if operation == 'read_state':
                file_utils.read_plain_text_file(str(state), key)
            elif operation in ('write_state', 'write_backup'):
                file_utils.write_plain_text_file(str(state), 'replacement', key, '.bak')
            elif operation == 'write_json':
                file_utils.save_timestamp_file(str(memory), {'replacement': True}, key)
            else:
                file_utils.ensure_json_file_exists(str(memory), encryption_key=key)
    for path, content in originals.items():
        assert path.read_bytes() == content
