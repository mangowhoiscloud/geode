"""Scheduler drain → pending-ask emission seam.

A scheduled job whose loop terminates with ``user_clarification_needed``
must publish a pending ask; any other termination must not.
"""

from __future__ import annotations

import asyncio
import queue
from types import SimpleNamespace
from typing import Any

from core.cli.scheduler_drain import _INFLIGHT_SCHEDULED_TASKS, drain_scheduler_queue


class _FakeLane:
    def try_acquire(self, _key: str) -> bool:
        return True

    def manual_release(self, _key: str) -> None:
        return None


class _FakeLoop:
    def __init__(self, result: Any) -> None:
        self._result = result
        self._session_id = "s-sched-test"

    async def arun(self, _prompt: str) -> Any:
        return self._result


class _FakeServices:
    def __init__(self, result: Any) -> None:
        self._result = result

    def create_session(self, _mode: Any, **_kwargs: Any) -> tuple[Any, Any]:
        return None, _FakeLoop(self._result)


async def _drain_and_settle(action_queue: Any, services: Any) -> None:
    await drain_scheduler_queue(
        action_queue=action_queue,
        services=services,
        session_lane=_FakeLane(),
        global_lane=_FakeLane(),
        force_isolated=True,
    )
    if _INFLIGHT_SCHEDULED_TASKS:
        await asyncio.gather(*list(_INFLIGHT_SCHEDULED_TASKS), return_exceptions=True)


def _run_drain(monkeypatch, termination_reason: str) -> list[dict[str, Any]]:
    published: list[dict[str, Any]] = []

    async def _fake_publish(question: str, *, session_id: str, source: str, store: Any = None):
        published.append({"question": question, "session_id": session_id, "source": source})

    import core.memory.pending_ask as pending_ask_mod

    monkeypatch.setattr(pending_ask_mod, "apublish_clarification_ask", _fake_publish)

    result = SimpleNamespace(
        termination_reason=termination_reason,
        text="Which repository should I target?",
    )
    action_queue: queue.Queue = queue.Queue()
    action_queue.put(("job1", "do the nightly thing", True, ""))

    asyncio.run(_drain_and_settle(action_queue, _FakeServices(result)))
    return published


def test_clarification_termination_publishes_ask(monkeypatch):
    published = _run_drain(monkeypatch, "user_clarification_needed")
    assert published == [
        {
            "question": "Which repository should I target?",
            "session_id": "s-sched-test",
            "source": "scheduled:job1",
        }
    ]


def test_natural_termination_publishes_nothing(monkeypatch):
    assert _run_drain(monkeypatch, "natural") == []
