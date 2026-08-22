from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from core.memory.goals import GoalStatus, GoalStore


def test_goal_store_models_absence_as_empty_and_clear_is_idempotent(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "sessions.db")
    assert store.status("s-empty") is GoalStatus.EMPTY
    assert store.clear("s-empty") is None

    created = store.create("s-empty", "Persist until cleared")
    assert store.status("s-empty") is GoalStatus.ACTIVE
    assert store.clear("s-empty") == created
    assert store.status("s-empty") is GoalStatus.EMPTY
    assert store.get("s-empty") is None


def test_goal_store_persists_budget_and_terminal_state(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "sessions.db")
    goal = store.create("s-1", "Finish the verified change", token_budget=100)

    progressed = store.account(
        "s-1",
        goal_id=goal.goal_id,
        tokens=40,
        elapsed_seconds=1.25,
    )
    assert progressed is not None
    assert progressed.status is GoalStatus.ACTIVE
    assert progressed.remaining_tokens == 60

    completed = store.update_terminal("s-1", GoalStatus.COMPLETE)
    settled = store.account(
        "s-1",
        goal_id=goal.goal_id,
        tokens=10,
        elapsed_seconds=0.5,
    )
    assert settled is not None
    assert settled.status is GoalStatus.COMPLETE
    assert settled.tokens_used == 50
    assert settled.time_used_seconds == pytest.approx(1.75)
    assert completed.goal_id == settled.goal_id


def test_goal_store_enforces_one_unfinished_goal_and_budget(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "sessions.db")
    goal = store.create("s-1", "Keep working", token_budget=10)

    with pytest.raises(ValueError, match="unfinished"):
        store.create("s-1", "Replace early")

    limited = store.account(
        "s-1",
        goal_id=goal.goal_id,
        tokens=10,
        elapsed_seconds=0.1,
    )
    assert limited is not None
    assert limited.status is GoalStatus.BUDGET_LIMITED
    assert limited.remaining_tokens == 0

    replacement = store.create("s-1", "Explicitly restarted", token_budget=20)
    assert replacement.goal_id != goal.goal_id
    assert replacement.status is GoalStatus.ACTIVE


def test_goal_store_lists_only_active_goals_oldest_first(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "sessions.db")
    first = store.create("s-1", "First")
    second = store.create("s-2", "Second")
    store.create("s-3", "Finished")
    store.update_terminal("s-3", GoalStatus.COMPLETE)

    assert store.list_active() == [first, second]


def test_goal_operator_pause_resume_edit_and_stale_id_guard(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "sessions.db")
    goal = store.create("s-1", "Original")
    paused = store.update_operator(
        "s-1", "pause", expected_goal_id=goal.goal_id, expected_revision=goal.revision
    )
    assert paused.status is GoalStatus.PAUSED
    assert store.list_active() == []
    edited = store.update_operator(
        "s-1",
        "edit",
        expected_goal_id=goal.goal_id,
        expected_revision=paused.revision,
        objective="Revised",
    )
    assert edited.objective == "Revised"
    resumed = store.update_operator(
        "s-1",
        "resume",
        expected_goal_id=goal.goal_id,
        expected_revision=edited.revision,
    )
    assert resumed.status is GoalStatus.ACTIVE
    with pytest.raises(ValueError, match="stale"):
        store.update_terminal("s-1", GoalStatus.COMPLETE, expected_goal_id="g-stale")


def test_goal_store_migrates_legacy_status_constraint_before_pause(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE thread_goals (
                session_id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL UNIQUE,
                objective TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('active', 'blocked', 'budget_limited', 'complete')
                ),
                token_budget INTEGER,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                time_used_seconds REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            INSERT INTO thread_goals VALUES
                ('legacy', 'g-legacy', 'Keep this row', 'active', NULL, 7, 1.5, 1, 2);
            """
        )

    store = GoalStore(db_path)
    migrated = store.update_operator(
        "legacy", "pause", expected_goal_id="g-legacy", expected_revision=0
    )
    assert migrated.status is GoalStatus.PAUSED
    assert migrated.tokens_used == 7


def test_goal_operator_rejects_a_stale_revision(tmp_path: Path) -> None:
    store = GoalStore(tmp_path / "sessions.db")
    stale = store.create("s-1", "Original")
    updated = store.update_operator(
        "s-1",
        "edit",
        expected_goal_id=stale.goal_id,
        expected_revision=stale.revision,
        objective="First edit",
    )

    with pytest.raises(ValueError, match="stale"):
        store.update_operator(
            "s-1",
            "edit",
            expected_goal_id=stale.goal_id,
            expected_revision=stale.revision,
            objective="Lost update",
        )

    assert store.get("s-1") == updated


def test_goal_revision_migration_tolerates_concurrent_first_access(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE thread_goals (
                session_id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL UNIQUE,
                objective TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('active', 'paused', 'blocked', 'budget_limited', 'complete')
                ),
                token_budget INTEGER,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                time_used_seconds REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            INSERT INTO thread_goals VALUES
                ('legacy', 'g-legacy', 'Keep this row', 'active', NULL, 0, 0, 1, 1);
            """
        )
    store = GoalStore(db_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _index: store.get("legacy"), range(16)))

    assert all(row is not None and row.revision == 0 for row in rows)
