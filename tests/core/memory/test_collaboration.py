from __future__ import annotations

import os
import sqlite3
import time
from types import SimpleNamespace

import pytest
from core.memory.collaboration import CollaborationStore


def _read_and_ack(store: CollaborationStore, recipient: str):
    messages = store.read_mailbox(recipient)
    store.ack_mailbox(recipient, [message.id for message in messages])
    return messages


def test_collaboration_store_preserves_control_without_duplicating_rollout(tmp_path) -> None:
    db = tmp_path / "sessions.db"
    store = CollaborationStore(db)
    run = store.begin_run(
        task_id="child-1",
        parent_session_id="parent-1",
        task_type="analyze",
        role="reviewer",
        model="gpt-test",
    )
    assert run.generation == 1
    assert store.mark_running("parent-1", "child-1", 1)

    store.append_message_if_active(
        parent_session_id="parent-1",
        task_id="child-1",
        message="use sk-proj-abcdefghijklmnopqrstuvwxyz123456",
    )
    message = _read_and_ack(store, "child-1")
    assert message[0].payload["message"] == "use [REDACTED]"
    assert store.read_mailbox("child-1") == []

    assert store.finish_run(
        parent_session_id="parent-1",
        task_id="child-1",
        generation=1,
        status="completed",
        summary="done",
    )
    assert not store.finish_run(
        parent_session_id="parent-1",
        task_id="child-1",
        generation=1,
        status="failed",
    )
    completion = _read_and_ack(store, "parent-1")
    assert len(completion) == 1
    assert completion[0].payload == {
        "error": "",
        "generation": 1,
        "status": "completed",
        "summary": "done",
        "task_id": "child-1",
    }
    assert store.get_run("foreign-parent", "child-1") is None

    resumed = store.begin_run(
        task_id="child-1",
        parent_session_id="parent-1",
        task_type="analyze",
        role="reviewer",
        model="gpt-test",
        resume=True,
    )
    assert resumed.generation == 2
    assert resumed.status == "pending"


def test_stale_runtime_is_interrupted_once_and_notified(tmp_path) -> None:
    db = tmp_path / "sessions.db"
    store = CollaborationStore(db)
    store.begin_run(
        task_id="child-stale",
        parent_session_id="parent-1",
        task_type="search",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE collaboration_runs SET owner_id = 'previous-runtime' WHERE task_id = ?",
            ("child-stale",),
        )

    recovered = store.get_run("parent-1", "child-stale")
    assert recovered is not None
    assert recovered.status == "interrupted"
    assert len(_read_and_ack(store, "parent-1")) == 1
    assert store.read_mailbox("parent-1") == []


def test_reused_pid_does_not_keep_a_stale_owner_alive(tmp_path) -> None:
    db = tmp_path / "sessions.db"
    store = CollaborationStore(db)
    store.begin_run(
        task_id="child-live",
        parent_session_id="parent-1",
        task_type="search",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE collaboration_runs SET owner_id = ? WHERE task_id = ?",
            (f"{store.owner_id.partition(':')[0]}:0.000000", "child-live"),
        )

    current = store.get_run("parent-1", "child-live")
    assert current is not None and current.status == "interrupted"
    assert _read_and_ack(store, "parent-1")[0].payload["status"] == "interrupted"


def test_legacy_owner_token_keeps_its_original_process_live(tmp_path) -> None:
    db = tmp_path / "sessions.db"
    store = CollaborationStore(db)
    store.begin_run(
        task_id="child-legacy",
        parent_session_id="parent-1",
        task_type="search",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE collaboration_runs SET owner_id = ? WHERE task_id = ?",
            (f"{os.getpid()}:{time.time_ns()}", "child-legacy"),
        )

    current = store.get_run("parent-1", "child-legacy")
    assert current is not None and current.status == "pending"
    assert store.read_mailbox("parent-1") == []


def test_restricted_process_metadata_does_not_interrupt_unverified_owner(
    tmp_path, monkeypatch
) -> None:
    from core.memory import collaboration

    db = tmp_path / "sessions.db"
    store = CollaborationStore(db)
    store.begin_run(
        task_id="child-restricted",
        parent_session_id="parent-1",
        task_type="search",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE collaboration_runs SET owner_id = ? WHERE task_id = ?",
            (f"{os.getpid()}:0.000000", "child-restricted"),
        )

    def denied() -> float:
        raise collaboration.psutil.AccessDenied(os.getpid())

    monkeypatch.setattr(
        collaboration.psutil,
        "Process",
        lambda _pid: SimpleNamespace(create_time=denied),
    )
    current = store.get_run("parent-1", "child-restricted")
    assert current is not None and current.status == "pending"


def test_parent_message_survives_child_generation_change(tmp_path) -> None:
    store = CollaborationStore(tmp_path / "sessions.db")
    store.begin_run(task_id="child-1", parent_session_id="parent-1", task_type="analyze")
    store.append_message_if_active(
        parent_session_id="parent-1",
        task_id="child-1",
        message="next generation",
    )

    current = _read_and_ack(store, "child-1")
    assert [item.payload["message"] for item in current] == ["next generation"]


def test_mailbox_is_read_until_explicit_ack(tmp_path) -> None:
    store = CollaborationStore(tmp_path / "sessions.db")
    store.begin_run(task_id="child-1", parent_session_id="parent-1", task_type="analyze")
    item_id = store.append_message_if_active(
        parent_session_id="parent-1",
        task_id="child-1",
        message="persist me",
    )
    assert item_id is not None

    assert [item.id for item in store.read_mailbox("child-1")] == [item_id]
    assert [item.id for item in store.read_mailbox("child-1")] == [item_id]
    assert store.ack_mailbox("foreign-child", [item_id]) == 0
    assert store.ack_mailbox("child-1", [item_id]) == 1
    assert store.read_mailbox("child-1") == []


def test_active_message_check_and_insert_are_atomic(tmp_path) -> None:
    store = CollaborationStore(tmp_path / "sessions.db")
    store.begin_run(
        task_id="child-1",
        parent_session_id="parent-1",
        task_type="analyze",
    )
    assert store.append_message_if_active(
        parent_session_id="parent-1",
        task_id="child-1",
        message="continue",
        trigger_turn=True,
    )
    assert store.has_pending_trigger("child-1")

    assert store.finish_run(
        parent_session_id="parent-1",
        task_id="child-1",
        generation=1,
        status="completed",
    )
    assert (
        store.append_message_if_active(
            parent_session_id="parent-1",
            task_id="child-1",
            message="too late",
        )
        is None
    )


def test_resume_rejects_active_or_foreign_child(tmp_path) -> None:
    store = CollaborationStore(tmp_path / "sessions.db")
    store.begin_run(
        task_id="child-1",
        parent_session_id="parent-1",
        task_type="analyze",
    )
    with pytest.raises(ValueError, match="already running"):
        store.begin_run(
            task_id="child-1",
            parent_session_id="parent-1",
            task_type="analyze",
            resume=True,
        )
    with pytest.raises(ValueError, match="Unknown child"):
        store.begin_run(
            task_id="child-1",
            parent_session_id="parent-2",
            task_type="analyze",
            resume=True,
        )


def test_unread_mailbox_keeps_only_the_newest_bounded_items(tmp_path, monkeypatch) -> None:
    from core.memory import collaboration

    monkeypatch.setattr(collaboration, "_MAX_UNREAD_PER_RECIPIENT", 2)
    store = CollaborationStore(tmp_path / "sessions.db")
    store.begin_run(task_id="child-1", parent_session_id="parent-1", task_type="analyze")
    for index in range(3):
        store.append_message_if_active(
            parent_session_id="parent-1",
            task_id="child-1",
            message=str(index),
        )

    assert [item.payload["message"] for item in store.read_mailbox("child-1")] == ["1", "2"]
