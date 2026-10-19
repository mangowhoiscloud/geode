"""Bug class B6 — parallel HITL approval race.

The v0.52.1 incident: LLM made two parallel ``manage_login`` tool calls in
the same round. Both hit ``confirm_write()`` simultaneously. The first
prompt rendered to the thin client; user typed ``A`` and it returned. The
second prompt was already in flight on the same socket — it timed out
after 120s and was treated as a denial. The user saw
``User denied write operation for 'manage_login' ... (120.0s)``.

Root cause: ``ApprovalWorkflow._approval_lock`` existed but was unused. The
safety gate checked + prompted + mutated ``_always_approved_categories``
without holding the lock, so a second parallel caller couldn't see the first
caller's "A" promotion. The oracles below drive the real async gate entry.

This invariant pins:
  1. The lock is held during the entire HITL prompt + mutation sequence.
  2. The lock is RE-checked inside the locked section so the second caller
     sees the first caller's ``always`` promotion and short-circuits.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import Mock

import core.agent.approval as _approval_mod
import pytest

# ---------------------------------------------------------------------------
# Contract 1 — parallel gates never overlap their prompts
# ---------------------------------------------------------------------------


def _make_gate(approval_responses: list[str]) -> tuple[Any, dict[str, int]]:
    """Build an ApprovalWorkflow whose callback returns canned responses and
    records how many prompts were in flight at once."""
    from core.agent.approval import ApprovalWorkflow

    responses = iter(approval_responses)
    stats = {"calls": 0, "in_flight": 0, "max_in_flight": 0}
    guard = threading.Lock()

    def callback(tool_name: str, detail: str, safety_level: str) -> str:
        with guard:
            stats["calls"] += 1
            stats["in_flight"] += 1
            stats["max_in_flight"] = max(stats["max_in_flight"], stats["in_flight"])
        # Hold the prompt long enough for an unserialized caller to overlap.
        time.sleep(0.05)
        with guard:
            stats["in_flight"] -= 1
        return next(responses)

    gate = ApprovalWorkflow(
        hitl_level=2,
        auto_approve=False,
        hooks=None,
        approval_callback=callback,
    )
    return gate, stats


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [("manage_login", {"subcommand": "use"}), ("petri_audit", {})],
)
def test_parallel_one_time_approvals_prompt_serially(
    tool_name: str, tool_input: dict[str, Any]
) -> None:
    """WRITE and EXPENSIVE gates hold the approval lock across the prompt, so
    two parallel calls each get their own, non-overlapping prompt."""
    gate, stats = _make_gate(["y", "y"])

    async def scenario() -> list[tuple[Any, ...]]:
        return list(
            await asyncio.wait_for(
                asyncio.gather(
                    gate.apply_safety_gates_async(tool_name, tool_input),
                    gate.apply_safety_gates_async(tool_name, tool_input),
                ),
                5,
            )
        )

    results = asyncio.run(scenario())
    assert results == [(None, True), (None, True)]
    assert stats["calls"] == 2
    assert stats["max_in_flight"] == 1


# ---------------------------------------------------------------------------
# Contract 2 — second parallel caller short-circuits via always-set
# ---------------------------------------------------------------------------


def test_second_parallel_write_short_circuits_after_always() -> None:
    """End-to-end: call A says "a", call B (queued behind A's lock) must NOT
    prompt — it sees "write" in always_approved_categories under the lock and
    approves silently. Pre-fix this hung 120s on the second socket recv.
    """
    gate, stats = _make_gate(["a"])  # only ONE callback response — second must skip

    async def scenario() -> list[tuple[Any, ...]]:
        first = asyncio.create_task(
            gate.apply_safety_gates_async("manage_login", {"subcommand": "use"})
        )
        # Give A a head-start so it grabs the lock first.
        await asyncio.sleep(0.01)
        second = asyncio.create_task(
            gate.apply_safety_gates_async("manage_login", {"subcommand": "use"})
        )
        return list(await asyncio.wait_for(asyncio.gather(first, second), 5))

    (rejection_a, approved_a), (rejection_b, approved_b) = asyncio.run(scenario())
    assert rejection_a is None and approved_a is True
    assert rejection_b is None and approved_b is True, (
        "second parallel call must observe always-set promotion and approve"
    )
    assert stats["calls"] == 1
    assert "write" in gate._always_approved_categories


def test_cancelled_approval_waiter_releases_late_lock_grant() -> None:
    async def scenario() -> None:
        callback = Mock(return_value="y")
        gate = _approval_mod.ApprovalWorkflow(approval_callback=callback)
        lock = threading.Lock()
        waiting = threading.Event()
        acquired = threading.Event()

        def acquire() -> bool:
            waiting.set()
            result = lock.acquire()
            acquired.set()
            return result

        gate._approval_lock = Mock(acquire=acquire, release=lock.release)
        lock.acquire()
        task = asyncio.create_task(
            gate.confirm_declared_async(
                "edit_file", {}, per_invocation=False, contains_personal_data=False
            )
        )
        try:
            assert await asyncio.to_thread(waiting.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            lock.release()
            assert await asyncio.to_thread(acquired.wait, 1)

            async def wait_for_release() -> None:
                while lock.locked():
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_release(), 1)
            callback.assert_not_called()
            assert await asyncio.wait_for(
                gate.confirm_declared_async(
                    "edit_file", {}, per_invocation=False, contains_personal_data=False
                ),
                1,
            )
            callback.assert_called_once()
        finally:
            if lock.locked():
                lock.release()

    asyncio.run(scenario())
