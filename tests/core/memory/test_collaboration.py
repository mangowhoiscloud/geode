from __future__ import annotations

import os
import sqlite3

import pytest
from core.memory.collaboration import CollaborationStore


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

    store.append_message(
        sender_session_id="parent-1",
        recipient_session_id="child-1",
        kind="message",
        payload={"message": "use sk-proj-abcdefghijklmnopqrstuvwxyz123456"},
    )
    message = store.drain_mailbox("child-1")
    assert message[0].payload["message"] == "use [REDACTED]"
    assert store.drain_mailbox("child-1") == []

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
    completion = store.drain_mailbox("parent-1")
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
    assert len(store.drain_mailbox("parent-1")) == 1
    assert store.drain_mailbox("parent-1") == []


def test_live_foreign_owner_is_not_falsely_recovered(tmp_path) -> None:
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
            (f"{os.getpid()}:other-runtime", "child-live"),
        )

    current = store.get_run("parent-1", "child-live")
    assert current is not None and current.status == "pending"
    assert store.drain_mailbox("parent-1") == []


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
    for index in range(3):
        store.append_message(
            sender_session_id="parent-1",
            recipient_session_id="child-1",
            kind="message",
            payload={"message": str(index)},
        )

    assert [item.payload["message"] for item in store.drain_mailbox("child-1")] == ["1", "2"]
