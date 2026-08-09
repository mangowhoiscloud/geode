from __future__ import annotations

import asyncio
from pathlib import Path
from types import MethodType
from typing import Any
from unittest.mock import MagicMock

from core.agent.loop import AgenticLoop, AgenticResult, _goal
from core.llm.token_tracker import LLMUsage
from core.memory.goals import GoalStatus, GoalStore


def test_goal_continues_after_success_and_settles_public_usage(tmp_path: Path) -> None:
    loop = object.__new__(AgenticLoop)
    loop._session_id = "s-goal"
    loop._goal_store = GoalStore(tmp_path / "sessions.db")
    loop._timeline = MagicMock()
    calls: list[tuple[str, Any]] = []

    async def fake_once(
        self: AgenticLoop,
        user_input: str,
        *,
        _verify_continuation: Any = None,
        _goal_continuation: Any = None,
    ) -> AgenticResult:
        calls.append((user_input, _goal_continuation))
        if len(calls) == 1:
            self._goal_store.create(self._session_id, "Finish the objective")
            return AgenticResult(
                text="progress",
                termination_reason="natural",
                usage=LLMUsage(input_tokens=7, output_tokens=3),
            )
        self._goal_store.update_terminal(self._session_id, GoalStatus.COMPLETE)
        return AgenticResult(
            text="done",
            termination_reason="natural",
            usage=LLMUsage(input_tokens=4, output_tokens=1),
        )

    loop._arun_once = MethodType(fake_once, loop)
    result = asyncio.run(loop.arun("Start an explicit goal"))

    assert result.text == "done"
    assert len(calls) == 2
    assert calls[0] == ("Start an explicit goal", None)
    assert calls[1][0] == "Finish the objective"
    assert calls[1][1].status is GoalStatus.ACTIVE
    assert result.usage is not None
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 4
    stored = loop._goal_store.get("s-goal")
    assert stored is not None
    assert stored.status is GoalStatus.COMPLETE
    assert stored.tokens_used == 15


def test_active_goal_does_not_hide_new_user_steering(tmp_path: Path) -> None:
    loop = object.__new__(AgenticLoop)
    loop._session_id = "s-goal"
    loop._goal_store = GoalStore(tmp_path / "sessions.db")
    loop._timeline = None
    loop._goal_store.create("s-goal", "Original objective")
    seen: list[tuple[str, Any]] = []

    async def fake_once(
        self: AgenticLoop,
        user_input: str,
        *,
        _verify_continuation: Any = None,
        _goal_continuation: Any = None,
    ) -> AgenticResult:
        seen.append((user_input, _goal_continuation))
        return AgenticResult(text="stopped", termination_reason="user_cancelled")

    loop._arun_once = MethodType(fake_once, loop)
    asyncio.run(loop.arun("User steering"))

    assert seen == [("User steering", None)]
    assert loop._goal_store.get("s-goal").status is GoalStatus.ACTIVE


def test_goal_budget_stops_before_another_continuation(tmp_path: Path) -> None:
    loop = object.__new__(AgenticLoop)
    loop._session_id = "s-goal"
    loop._goal_store = GoalStore(tmp_path / "sessions.db")
    loop._timeline = None
    calls = 0

    async def fake_once(
        self: AgenticLoop,
        user_input: str,
        *,
        _verify_continuation: Any = None,
        _goal_continuation: Any = None,
    ) -> AgenticResult:
        nonlocal calls
        calls += 1
        self._goal_store.create(self._session_id, "Budgeted", token_budget=5)
        return AgenticResult(
            text="turn complete",
            termination_reason="natural",
            usage=LLMUsage(input_tokens=4, output_tokens=2),
        )

    loop._arun_once = MethodType(fake_once, loop)
    asyncio.run(loop.arun("Start budgeted goal"))

    assert calls == 1
    assert loop._goal_store.get("s-goal").status is GoalStatus.BUDGET_LIMITED


def test_repeated_text_only_continuation_leaves_goal_active(tmp_path: Path) -> None:
    loop = object.__new__(AgenticLoop)
    loop._session_id = "s-goal"
    loop._goal_store = GoalStore(tmp_path / "sessions.db")
    loop._timeline = None
    calls = 0

    async def fake_once(
        self: AgenticLoop,
        user_input: str,
        *,
        _verify_continuation: Any = None,
        _goal_continuation: Any = None,
    ) -> AgenticResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            self._goal_store.create(self._session_id, "Keep working")
        return AgenticResult(text="No progress", termination_reason="natural")

    loop._arun_once = MethodType(fake_once, loop)
    result = asyncio.run(loop.arun("Start"))

    assert calls == 2
    assert result.text == "No progress"
    assert loop._goal_store.get("s-goal").status is GoalStatus.ACTIVE


def test_automatic_continuation_safety_cap_leaves_goal_active(
    tmp_path: Path, monkeypatch: Any
) -> None:
    loop = object.__new__(AgenticLoop)
    loop._session_id = "s-goal"
    loop._goal_store = GoalStore(tmp_path / "sessions.db")
    loop._timeline = None
    calls = 0

    async def fake_once(
        self: AgenticLoop,
        user_input: str,
        *,
        _verify_continuation: Any = None,
        _goal_continuation: Any = None,
    ) -> AgenticResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            self._goal_store.create(self._session_id, "Keep working")
        return AgenticResult(text=f"Progress {calls}", termination_reason="natural")

    monkeypatch.setattr(_goal, "_MAX_AUTOMATIC_CONTINUATIONS", 1)
    loop._arun_once = MethodType(fake_once, loop)
    asyncio.run(loop.arun("Start"))

    assert calls == 2
    assert loop._goal_store.get("s-goal").status is GoalStatus.ACTIVE
