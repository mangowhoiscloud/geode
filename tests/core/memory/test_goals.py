from __future__ import annotations

from pathlib import Path

import pytest
from core.memory.goals import GoalStatus, GoalStore


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
