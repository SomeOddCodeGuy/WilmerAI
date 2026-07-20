"""Unit tests for the ConversationChunkProcessor node (SubWorkflowHandler).

These exercise the real hashing/cursor logic (hashing_utils, the cursor file read/write)
and mock only the sub-workflow invocation (run_custom_workflow) and variable resolution.
Cursor and return files live under pytest's tmp_path, so nothing is left behind.
"""
import os
from unittest.mock import Mock

import pytest

from Middleware.utilities.hashing_utils import hash_single_message
from Middleware.workflows.handlers.impl.sub_workflow_handler import SubWorkflowHandler
from Middleware.workflows.models.execution_context import ExecutionContext


def _msgs(n, start=0):
    """n messages with distinct content (so each hashes distinctly)."""
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{start + i}"} for i in range(n)]


def _ctx(config, messages, discussion_id="disc1"):
    return ExecutionContext(
        request_id="req",
        workflow_id="wf",
        discussion_id=discussion_id,
        config=config,
        messages=messages,
        stream=False,
        agent_outputs={},
        agent_inputs={},
    )


@pytest.fixture
def handler():
    mgr = Mock()
    var = Mock()
    # Identity variable resolution: templates are passed through unchanged.
    var.apply_variables.side_effect = lambda s, ctx: s
    return SubWorkflowHandler(workflow_manager=mgr, workflow_variable_service=var)


def _base_config(tmp_path, **overrides):
    config = {
        "type": "ConversationChunkProcessor",
        "id": "keyEvents",
        "workflowName": "KeyEvents_ChunkUpdate",
        "chunkSize": 10,
        "lookbackMessages": 0,
        "cursorDirectory": str(tmp_path),
    }
    config.update(overrides)
    return config


def test_save_chunk_cursor_swallows_write_errors(handler, mocker):
    """An unwritable cursor path must not propagate. The chunk has already been
    processed by the time the cursor is saved, so a failed persist should degrade
    to reprocessing on a later turn rather than aborting the workflow (which would
    500 every subsequent request)."""
    mocker.patch(
        "Middleware.workflows.handlers.impl.sub_workflow_handler.save_custom_file",
        side_effect=PermissionError("read-only file system"),
    )
    # Must not raise.
    handler._save_chunk_cursor("/nonexistent/dir/cursor.txt", ["hash1", "hash2"])


def _cursor_file(tmp_path, node_id="keyEvents", disc="disc1"):
    return os.path.join(str(tmp_path), f"chunk_cursor_{node_id}_{disc}.txt")


# ---------------- routing ----------------
def test_handle_routes_to_chunk_processor(mocker, handler):
    spy = mocker.patch.object(handler, "handle_conversation_chunk_processor", return_value="ok")
    ctx = _ctx({"type": "ConversationChunkProcessor"}, _msgs(1))
    assert handler.handle(ctx) == "ok"
    spy.assert_called_once_with(ctx)


# ---------------- cold-start backfill ----------------
def test_cold_start_processes_all_complete_chunks(handler, tmp_path):
    # 25 messages, chunk 10, no cursor -> 2 complete chunks (20 msgs), 5 remainder left.
    msgs = _msgs(25)
    ctx = _ctx(_base_config(tmp_path), msgs)
    handler.handle_conversation_chunk_processor(ctx)

    assert handler.workflow_manager.run_custom_workflow.call_count == 2
    # First chunk passed as {agent1Input} = the first 10 messages' content joined.
    first_call = handler.workflow_manager.run_custom_workflow.call_args_list[0]
    scoped = first_call.kwargs["scoped_inputs"]
    assert scoped[0] == "\n".join(m["content"] for m in msgs[0:10])
    # Cursor holds ONE hash per processed chunk, the last message of each chunk (msgs 9 and 19),
    # so it stays small while still letting a changed tail re-anchor on an earlier chunk boundary.
    with open(_cursor_file(tmp_path)) as f:
        stored = [l.strip() for l in f if l.strip()]
    assert stored == [hash_single_message(msgs[9]), hash_single_message(msgs[19])]


def test_cold_start_children_run_as_non_responders(handler, tmp_path):
    ctx = _ctx(_base_config(tmp_path), _msgs(10))
    handler.handle_conversation_chunk_processor(ctx)
    kwargs = handler.workflow_manager.run_custom_workflow.call_args.kwargs
    assert kwargs["non_responder"] is True
    assert kwargs["is_streaming"] is False
    assert kwargs["workflow_name"] == "KeyEvents_ChunkUpdate"


# ---------------- steady state ----------------
def test_steady_state_fewer_than_chunk_size_does_nothing(handler, tmp_path):
    # Cursor = hashes of msgs 10-19; only 5 new messages (20-24) -> no complete chunk.
    msgs = _msgs(25)
    with open(_cursor_file(tmp_path), "w") as f:
        f.write("\n".join(hash_single_message(m) for m in msgs[10:20]))
    ctx = _ctx(_base_config(tmp_path), msgs)
    handler.handle_conversation_chunk_processor(ctx)
    handler.workflow_manager.run_custom_workflow.assert_not_called()


def test_one_new_chunk_after_cursor(handler, tmp_path):
    # Cursor = hashes of msgs 0-9; msgs 10-19 form exactly one new chunk.
    msgs = _msgs(20)
    with open(_cursor_file(tmp_path), "w") as f:
        f.write("\n".join(hash_single_message(m) for m in msgs[0:10]))
    ctx = _ctx(_base_config(tmp_path), msgs)
    handler.handle_conversation_chunk_processor(ctx)
    assert handler.workflow_manager.run_custom_workflow.call_count == 1
    scoped = handler.workflow_manager.run_custom_workflow.call_args.kwargs["scoped_inputs"]
    assert scoped[0] == "\n".join(m["content"] for m in msgs[10:20])


# ---------------- edit resilience ----------------
def test_edit_of_last_processed_message_does_not_force_full_reprocess(handler, tmp_path):
    # Cursor stores the WHOLE last chunk (msgs 10-19). The last message is then edited.
    # Because earlier hashes still match, only the tail after the match is reprocessed,
    # NOT the whole 30-message history (which would be 3 chunks).
    msgs = _msgs(30)
    with open(_cursor_file(tmp_path), "w") as f:
        f.write("\n".join(hash_single_message(m) for m in msgs[10:20]))
    msgs[19] = {"role": "assistant", "content": "EDITED-19"}  # boundary edit
    ctx = _ctx(_base_config(tmp_path), msgs)
    handler.handle_conversation_chunk_processor(ctx)
    # Match falls back to msg 18 -> 11 new (19-29) -> exactly 1 complete chunk, not 3.
    assert handler.workflow_manager.run_custom_workflow.call_count == 1


# ---------------- regeneration / tail-change robustness ----------------
def test_identical_context_resent_does_not_reprocess(handler, tmp_path):
    # Re-sending the exact same conversation (a regenerate re-sends the same context) must not
    # re-run any chunk; the cursor matches everything already processed.
    msgs = _msgs(25)
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), msgs))
    handler.workflow_manager.run_custom_workflow.reset_mock()
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), list(msgs)))
    assert handler.workflow_manager.run_custom_workflow.call_count == 0


def test_fully_changed_last_chunk_reanchors_not_full_reprocess(handler, tmp_path):
    # Worst case: the entire content of the last processed chunk changes (e.g. the tail was
    # reformatted on a regenerate). Because the cursor stores the whole processed history, it
    # re-anchors on the last UNCHANGED processed message and reprocesses only the changed chunk,
    # NOT the whole record (which would duplicate every earlier event).
    msgs = _msgs(30)  # lookback 0 -> 3 chunks: 0-9, 10-19, 20-29
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), msgs))
    assert handler.workflow_manager.run_custom_workflow.call_count == 3
    handler.workflow_manager.run_custom_workflow.reset_mock()
    changed = list(msgs)
    for i in range(20, 30):  # rewrite the entire last chunk's content
        changed[i] = {"role": changed[i]["role"], "content": f"CHANGED-{i}"}
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), changed))
    # Only the one changed chunk is reprocessed, not all three.
    assert handler.workflow_manager.run_custom_workflow.call_count == 1


# ---------------- home-dir (~) cursor path ----------------
def test_tilde_cursor_path_roundtrips_no_reprocess(handler, tmp_path, monkeypatch):
    # A '~'-based cursorDirectory must expand the SAME way for the write and the existence check,
    # so the cursor persists and a second run does not cold-start / reprocess. The home lookup is
    # redirected to a temp dir so nothing touches the real home directory: HOME for POSIX
    # expanduser, USERPROFILE for Windows (ntpath ignores HOME and would otherwise write into
    # the real %USERPROFILE% and leave a file behind there).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    config = _base_config(tmp_path, cursorDirectory="~/wilmer_chunk_cursor")
    msgs = _msgs(25)
    handler.handle_conversation_chunk_processor(_ctx(config, msgs))
    assert handler.workflow_manager.run_custom_workflow.call_count == 2  # cold start
    # cursor was written under the EXPANDED home path...
    expanded = os.path.expanduser("~/wilmer_chunk_cursor/chunk_cursor_keyEvents_disc1.txt")
    assert "~" not in expanded and os.path.exists(expanded)
    # ...and the second run FINDS it (no literal-'~' miss) -> no reprocess, no duplication.
    handler.workflow_manager.run_custom_workflow.reset_mock()
    handler.handle_conversation_chunk_processor(_ctx(config, list(msgs)))
    assert handler.workflow_manager.run_custom_workflow.call_count == 0


# ---------------- multi-node id isolation ----------------
def test_two_nodes_keep_separate_cursors(handler, tmp_path):
    msgs = _msgs(10)
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path, id="alpha"), msgs))
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path, id="beta"), msgs))
    assert os.path.exists(_cursor_file(tmp_path, node_id="alpha"))
    assert os.path.exists(_cursor_file(tmp_path, node_id="beta"))


def test_cursor_is_scoped_by_discussion_id(handler, tmp_path):
    msgs = _msgs(10)
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), msgs, discussion_id="A"))
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), msgs, discussion_id="B"))
    assert os.path.exists(_cursor_file(tmp_path, disc="A"))
    assert os.path.exists(_cursor_file(tmp_path, disc="B"))


# ---------------- child message isolation ----------------
def test_child_receives_copies_of_chunk_messages(handler, tmp_path):
    """The child workflow gets a copy of each chunk message, never the parent's dicts;
    a child that mutates its messages must not corrupt the parent conversation."""
    msgs = _msgs(10)
    ctx = _ctx(_base_config(tmp_path), msgs)
    handler.handle_conversation_chunk_processor(ctx)

    passed = handler.workflow_manager.run_custom_workflow.call_args.kwargs["messages"]
    # Same content as the chunk...
    assert passed == msgs[0:10]
    # ...but distinct dict objects (mutation isolation).
    for child_msg, parent_msg in zip(passed, msgs):
        assert child_msg is not parent_msg


# ---------------- cursor robustness ----------------
def test_unreadable_cursor_degrades_to_cold_start(handler, tmp_path):
    """A cursor path that exists but cannot be read (here: it is a directory) must be
    treated as no cursor (cold start) rather than raising out of the node."""
    os.makedirs(_cursor_file(tmp_path))  # the cursor path itself is a directory
    ctx = _ctx(_base_config(tmp_path), _msgs(10))
    handler.handle_conversation_chunk_processor(ctx)
    # Cold start: the single complete chunk is processed; the failed cursor persist
    # afterwards is swallowed (already covered by the write-error test above).
    assert handler.workflow_manager.run_custom_workflow.call_count == 1


# ---------------- more validation ----------------
def test_cursor_directory_resolving_to_empty_raises(handler, tmp_path):
    config = _base_config(tmp_path, cursorDirectory="   ")
    with pytest.raises(ValueError, match="resolved to empty"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


def test_negative_lookback_raises(handler, tmp_path):
    config = _base_config(tmp_path, lookbackMessages=-1)
    with pytest.raises(ValueError, match="lookbackMessages"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


# ---------------- scoped_variables pass-through ----------------
def test_scoped_variables_follow_the_chunk(handler, tmp_path):
    config = _base_config(tmp_path, scoped_variables=["{agent4Output}", "static"])
    msgs = _msgs(10)
    ctx = _ctx(config, msgs)
    handler.handle_conversation_chunk_processor(ctx)
    scoped = handler.workflow_manager.run_custom_workflow.call_args.kwargs["scoped_inputs"]
    # chunk first, then the two resolved scoped variables.
    assert scoped == ["\n".join(m["content"] for m in msgs[0:10]), "{agent4Output}", "static"]


# ---------------- returnFile ----------------
def test_return_file_content_is_returned(handler, tmp_path):
    record = tmp_path / "key_events.md"
    record.write_text("EVENT ONE\nEVENT TWO\n")
    config = _base_config(tmp_path, returnFile=str(record))
    result = handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))
    assert "EVENT ONE" in result and "EVENT TWO" in result


def test_status_string_returned_without_return_file(handler, tmp_path):
    result = handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), _msgs(10)))
    assert "processed 1 chunk" in result


# ---------------- lookback ----------------
def test_lookback_tail_is_left_unprocessed(handler, tmp_path):
    # 14 messages, chunk 10, lookback 4 -> only msgs 0-9 eligible -> 1 chunk.
    msgs = _msgs(14)
    ctx = _ctx(_base_config(tmp_path, lookbackMessages=4), msgs)
    handler.handle_conversation_chunk_processor(ctx)
    assert handler.workflow_manager.run_custom_workflow.call_count == 1


def test_short_conversation_within_lookback_is_noop(handler, tmp_path):
    ctx = _ctx(_base_config(tmp_path, lookbackMessages=4), _msgs(3))
    result = handler.handle_conversation_chunk_processor(ctx)
    handler.workflow_manager.run_custom_workflow.assert_not_called()
    assert "processed 0 chunk" in result


# ---------------- validation ----------------
def test_missing_id_raises(handler, tmp_path):
    config = _base_config(tmp_path)
    del config["id"]
    with pytest.raises(ValueError, match="unique 'id'"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


def test_path_unsafe_id_raises(handler, tmp_path):
    config = _base_config(tmp_path, id="../evil")
    with pytest.raises(ValueError, match="only letters, digits"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


def test_missing_workflow_name_raises(handler, tmp_path):
    config = _base_config(tmp_path)
    del config["workflowName"]
    with pytest.raises(ValueError, match="workflowName"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


def test_invalid_chunk_size_raises(handler, tmp_path):
    config = _base_config(tmp_path, chunkSize=0)
    with pytest.raises(ValueError, match="chunkSize"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


def test_missing_cursor_directory_raises(handler, tmp_path):
    config = _base_config(tmp_path)
    del config["cursorDirectory"]
    with pytest.raises(ValueError, match="cursorDirectory"):
        handler.handle_conversation_chunk_processor(_ctx(config, _msgs(10)))


# ---------------- head truncation resilience ----------------
def test_head_truncation_does_not_reprocess_messages(handler, tmp_path):
    """The cursor must store the boundaries of the chunks actually processed.
    When the client trims the oldest messages between turns (context-window
    housekeeping), an absolute-index recomputation would store boundaries that
    never ended a processed chunk and re-feed up to chunkSize-1 messages to the
    child workflow on the following turn."""
    processed = []
    handler.workflow_manager.run_custom_workflow.side_effect = (
        lambda **kwargs: processed.append(kwargs["scoped_inputs"][0]))

    # Turn 1: full history m0..m29 -> 3 chunks.
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), _msgs(30)))
    assert len(processed) == 3

    # Turn 2: the client trimmed the 3 oldest messages and 10 new ones arrived (m3..m39).
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), _msgs(37, start=3)))
    assert processed[3] == "\n".join(f"m{i}" for i in range(30, 40))

    # Turn 3: 10 more new messages, no further truncation (m3..m49).
    handler.handle_conversation_chunk_processor(_ctx(_base_config(tmp_path), _msgs(47, start=3)))

    all_seen = "\n".join(processed).split("\n")
    duplicates = sorted({m for m in all_seen if all_seen.count(m) > 1})
    assert duplicates == [], f"Messages fed to the child workflow more than once: {duplicates}"


# ---------------- stateless request guard ----------------
def test_no_discussion_id_skips_processing(handler, tmp_path):
    """Without a discussion id every stateless conversation would share one
    cursor file and re-run the child workflow over its whole backlog each turn;
    the node must no-op instead (mirroring the QualityMemory guard)."""
    result = handler.handle_conversation_chunk_processor(
        _ctx(_base_config(tmp_path), _msgs(30), discussion_id=None))
    handler.workflow_manager.run_custom_workflow.assert_not_called()
    assert "processed 0 chunk(s)" in result


# ---------------- returnFile before the record exists ----------------
def test_return_file_missing_returns_empty_string(handler, tmp_path):
    """Before any chunk has produced the record, a configured returnFile must
    yield "", not load_custom_file's missing-file sentinel, which would flow
    into downstream prompts via {agentNOutput}."""
    config = _base_config(tmp_path, returnFile=os.path.join(str(tmp_path), "record.md"))
    result = handler.handle_conversation_chunk_processor(_ctx(config, _msgs(3)))
    assert result == ""
