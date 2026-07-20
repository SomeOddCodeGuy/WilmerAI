# Tests/scripts/test_backfill_embeddings.py
#
# Hermetic tests for the standalone bulk embedding backfill script in
# Scripts/. The embeddings endpoint is always mocked (requests.Session is
# patched in the script's namespace); databases live in tmp_path only.

import sqlite3
import sys
from array import array

import pytest

import Scripts.backfill_embeddings as backfill_embeddings
from Scripts.backfill_embeddings import fetch_embeddings


# === Helpers ===

class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _openai_body(index_vector_pairs):
    """Builds an OpenAI-shape embeddings response from (index, vector) pairs."""
    return {"data": [{"index": i, "embedding": v} for i, v in index_vector_pairs]}


def _make_wilmer_db(path, texts):
    """Creates a Wilmer-shaped vector memory DB containing only the memories table."""
    conn = sqlite3.connect(str(path))
    conn.execute('''
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            discussion_id TEXT NOT NULL,
            memory_text TEXT NOT NULL,
            date_added TEXT NOT NULL,
            metadata_json TEXT
        );
    ''')
    for text in texts:
        conn.execute(
            'INSERT INTO memories (discussion_id, memory_text, date_added, metadata_json) '
            'VALUES (?, ?, ?, ?)',
            ("disc-1", text, "2026-01-01T00:00:00+00:00", "{}"))
    conn.commit()
    conn.close()


def _read_embeddings(path, model):
    """Returns {memory_id: (dim, [floats])} stored for a model."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute(
        'SELECT memory_id, dim, vector FROM memory_embeddings WHERE model = ?', (model,)).fetchall()
    conn.close()
    out = {}
    for memory_id, dim, blob in rows:
        vec = array('f')
        vec.frombytes(blob)
        out[memory_id] = (dim, list(vec))
    return out


def _run_main(mocker, argv):
    mocker.patch.object(sys, "argv", ["backfill_embeddings.py"] + argv)
    return backfill_embeddings.main()


@pytest.fixture
def mock_post(mocker):
    """Patches requests.Session in the script's namespace; returns the post mock."""
    session_cls = mocker.patch("Scripts.backfill_embeddings.requests.Session")
    return session_cls.return_value.post


# === main() argument and validation tests ===

def test_missing_db_file_returns_error(mocker, tmp_path, mock_post, capsys):
    """A typo'd --db path must not silently create an empty database."""
    missing = tmp_path / "nope" / "vector_memory.db"

    rc = _run_main(mocker, ["--db", str(missing), "--url", "http://x", "--model", "m"])

    assert rc == 1
    assert not missing.exists()
    mock_post.assert_not_called()
    assert "no database file found" in capsys.readouterr().out


def test_non_wilmer_db_left_untouched(mocker, tmp_path, mock_post, capsys):
    """Pointing --db at a non-Wilmer SQLite file must not add any tables to it."""
    db = tmp_path / "other.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "m"])

    assert rc == 1
    mock_post.assert_not_called()
    conn = sqlite3.connect(str(db))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "memory_embeddings" not in tables
    assert "does not look like" in capsys.readouterr().out


def test_batch_size_below_one_is_a_parser_error(mocker, tmp_path, mock_post):
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["one"])

    with pytest.raises(SystemExit) as exc_info:
        _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "m",
                           "--batch-size", "0"])

    assert exc_info.value.code == 2
    mock_post.assert_not_called()


# === main() backfill behavior tests ===

def test_happy_path_openai_shape_writes_vectors_in_index_order(mocker, tmp_path, mock_post):
    """The whole backlog is embedded in one batch; the OpenAI response's
    'index' field (returned out of order here) must decide which vector lands
    on which memory."""
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["alpha", "beta"])
    mock_post.return_value = _FakeResponse(_openai_body([
        (1, [0.0, 1.0]),  # beta's vector, listed first
        (0, [1.0, 0.0]),  # alpha's vector, listed second
    ]))

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://server:8081",
                            "--model", "emb-model"])

    assert rc == 0
    args, kwargs = mock_post.call_args
    assert args[0] == "http://server:8081/v1/embeddings"
    assert kwargs["json"] == {"model": "emb-model", "input": ["alpha", "beta"]}
    stored = _read_embeddings(db, "emb-model")
    assert stored[1] == (2, [1.0, 0.0])
    assert stored[2] == (2, [0.0, 1.0])


def test_ollama_shape_uses_embed_route_and_parses_embeddings_key(mocker, tmp_path, mock_post):
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["alpha"])
    mock_post.return_value = _FakeResponse({"embeddings": [[0.5, 0.5]]})

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://server:11434/",
                            "--model", "emb-model", "--api-shape", "ollama"])

    assert rc == 0
    args, _ = mock_post.call_args
    assert args[0] == "http://server:11434/api/embed"
    assert _read_embeddings(db, "emb-model") == {1: (2, [0.5, 0.5])}


def test_batches_respect_batch_size_and_skip_already_embedded(mocker, tmp_path, mock_post):
    """Only un-embedded rows for the target model are requested, oldest first,
    batch_size texts per request. A different model's existing vector must not
    block re-embedding under the new model."""
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["one", "two", "three"])
    conn = sqlite3.connect(str(db))
    conn.execute(backfill_embeddings.CREATE_EMBEDDINGS_TABLE)
    # Row 2 already embedded under the target model; row 1 embedded under
    # another model (must not count).
    conn.execute("INSERT INTO memory_embeddings VALUES (2, 'emb-model', 1, ?)",
                 (array('f', [9.0]).tobytes(),))
    conn.execute("INSERT INTO memory_embeddings VALUES (1, 'other-model', 1, ?)",
                 (array('f', [8.0]).tobytes(),))
    conn.commit()
    conn.close()
    mock_post.side_effect = [
        _FakeResponse(_openai_body([(0, [1.0])])),
        _FakeResponse(_openai_body([(0, [3.0])])),
    ]

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "emb-model",
                            "--batch-size", "1"])

    assert rc == 0
    sent_batches = [call.kwargs["json"]["input"] for call in mock_post.call_args_list]
    assert sent_batches == [["one"], ["three"]]
    stored = _read_embeddings(db, "emb-model")
    assert stored[1] == (1, [1.0])
    assert stored[2] == (1, [9.0])  # untouched pre-existing row
    assert stored[3] == (1, [3.0])
    assert _read_embeddings(db, "other-model") == {1: (1, [8.0])}


def test_aborts_after_three_consecutive_failures(mocker, tmp_path, mock_post, capsys):
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["one"])
    mock_post.side_effect = ConnectionError("server down")

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "emb-model"])

    assert rc == 1
    assert mock_post.call_count == 3
    assert _read_embeddings(db, "emb-model") == {}
    assert "Aborting after repeated failures" in capsys.readouterr().out


def test_failure_counter_resets_after_a_successful_batch(mocker, tmp_path, mock_post):
    """Three failures must be CONSECUTIVE to abort: fail, ok, fail, fail, ok, ok
    completes the run. Without the reset, the third cumulative failure would
    abort with rows left un-embedded."""
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["one", "two", "three"])
    mock_post.side_effect = [
        ConnectionError("blip"),
        _FakeResponse(_openai_body([(0, [1.0])])),
        ConnectionError("blip"),
        ConnectionError("blip"),
        _FakeResponse(_openai_body([(0, [2.0])])),
        _FakeResponse(_openai_body([(0, [3.0])])),
    ]

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "emb-model",
                            "--batch-size", "1"])

    assert rc == 0
    assert mock_post.call_count == 6
    stored = _read_embeddings(db, "emb-model")
    assert stored == {1: (1, [1.0]), 2: (1, [2.0]), 3: (1, [3.0])}


def test_rerun_on_fully_embedded_db_is_a_no_op(mocker, tmp_path, mock_post):
    """Running the script twice must not re-request anything the second time."""
    db = tmp_path / "vector_memory.db"
    _make_wilmer_db(db, ["one"])
    mock_post.return_value = _FakeResponse(_openai_body([(0, [1.0])]))
    assert _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "emb-model"]) == 0
    mock_post.reset_mock()

    rc = _run_main(mocker, ["--db", str(db), "--url", "http://x", "--model", "emb-model"])

    assert rc == 0
    mock_post.assert_not_called()


# === fetch_embeddings unit tests ===

class _RecordingSession:
    """Captures the post call and returns a canned response."""

    def __init__(self, body):
        self.body = body
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse(self.body)


def test_fetch_embeddings_sends_bearer_token_when_api_key_given():
    session = _RecordingSession(_openai_body([(0, [1.0])]))

    fetch_embeddings(session, "http://x", "openai", "m", "tok-123", ["a"], 60)

    assert session.calls[0]["headers"]["Authorization"] == "Bearer tok-123"


def test_fetch_embeddings_omits_auth_header_without_api_key():
    session = _RecordingSession(_openai_body([(0, [1.0])]))

    fetch_embeddings(session, "http://x", "openai", "m", "", ["a"], 60)

    assert "Authorization" not in session.calls[0]["headers"]


def test_fetch_embeddings_count_mismatch_raises():
    session = _RecordingSession(_openai_body([(0, [1.0])]))

    with pytest.raises(ValueError, match="1 vectors for 2 texts"):
        fetch_embeddings(session, "http://x", "openai", "m", "", ["a", "b"], 60)


def test_fetch_embeddings_missing_vectors_raises():
    session = _RecordingSession({"unexpected": "shape"})

    with pytest.raises(ValueError, match="no vectors"):
        fetch_embeddings(session, "http://x", "ollama", "m", "", ["a"], 60)


def test_fetch_embeddings_empty_vector_raises():
    session = _RecordingSession({"embeddings": [[]]})

    with pytest.raises(ValueError, match="non-empty vectors"):
        fetch_embeddings(session, "http://x", "ollama", "m", "", ["a"], 60)
