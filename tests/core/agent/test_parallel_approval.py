"""Bug class B6 — parallel HITL approval race.

The v0.52.1 incident: LLM made two parallel ``manage_login`` tool calls in
the same round. Both hit ``confirm_write()`` simultaneously. The first
prompt rendered to the thin client; user typed ``A`` and it returned. The
second prompt was already in flight on the same socket — it timed out
after 120s and was treated as a denial. The user saw
``User denied write operation for 'manage_login' ... (120.0s)``.

Root cause: ``ApprovalWorkflow._approval_lock`` existed (line 80) but was
unused. ``apply_safety_gates`` checked + prompted + mutated
``_always_approved_categories`` without holding the lock, so a second
parallel caller couldn't see the first caller's "A" promotion.

This invariant pins:
  1. The lock is held during the entire HITL prompt + mutation sequence.
  2. The lock is RE-checked inside the locked section so the second caller
     sees the first caller's ``always`` promotion and short-circuits.
  3. The poller-side socket recv loop has a finite timeout so a real
     user-stuck case fails closed (denial) instead of hanging the daemon.
"""

from __future__ import annotations

import inspect
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import core.agent.approval as _approval_mod
import core.server.ipc_server.poller as _poller_mod

# ---------------------------------------------------------------------------
# Contract 1 — apply_safety_gates uses _approval_lock
# ---------------------------------------------------------------------------


def test_approval_lock_wraps_write_branch() -> None:
    """Source-level: the WRITE_TOOLS branch must enter ``with self._approval_lock``
    BEFORE checking ``_always_approved_categories`` so a second caller's
    re-check observes the first caller's promotion.
    """
    src = inspect.getsource(_approval_mod.ApprovalWorkflow.apply_safety_gates)
    # Locate "if tool_name in WRITE_TOOLS:" and assert the very next line
    # establishes the lock context.
    lines = src.splitlines()
    write_branch = next(
        (i for i, ln in enumerate(lines) if "if tool_name in WRITE_TOOLS" in ln),
        -1,
    )
    assert write_branch >= 0, "WRITE_TOOLS branch removed?"
    follow = "\n".join(lines[write_branch : write_branch + 5])
    assert "with self._approval_lock" in follow, (
        "WRITE_TOOLS branch must enter _approval_lock before the always-set "
        "check + confirm_write. See B6 root cause."
    )


def test_approval_lock_wraps_expensive_branch() -> None:
    """Same invariant for the EXPENSIVE_TOOLS branch."""
    src = inspect.getsource(_approval_mod.ApprovalWorkflow.apply_safety_gates)
    lines = src.splitlines()
    cost_branch = next(
        (i for i, ln in enumerate(lines) if "if tool_name in EXPENSIVE_TOOLS" in ln),
        -1,
    )
    assert cost_branch >= 0
    follow = "\n".join(lines[cost_branch : cost_branch + 5])
    assert "with self._approval_lock" in follow, (
        "EXPENSIVE_TOOLS branch must use _approval_lock too — same race shape"
    )


# ---------------------------------------------------------------------------
# Contract 2 — second parallel caller short-circuits via always-set
# ---------------------------------------------------------------------------


def _make_gate(approval_responses: list[str]) -> Any:
    """Build an ApprovalWorkflow whose approval_callback returns canned responses."""
    from core.agent.approval import ApprovalWorkflow

    responses = iter(approval_responses)

    def callback(tool_name: str, detail: str, safety_level: str) -> str:
        # Add a small sleep so the threads' timing actually overlaps.
        time.sleep(0.05)
        return next(responses)

    return ApprovalWorkflow(
        hitl_level=2,
        auto_approve=False,
        hooks=None,
        approval_callback=callback,
    )


def test_second_parallel_write_short_circuits_after_always() -> None:
    """End-to-end: thread A says "a", thread B (started immediately after)
    must NOT prompt — it sees "write" in always_approved_categories under
    the lock and approves silently. Pre-fix this hung 120s on the second
    socket recv.
    """
    gate = _make_gate(["a"])  # only ONE callback response — second must skip

    results: dict[str, tuple[Any, ...]] = {}

    def worker(tag: str) -> None:
        results[tag] = gate.apply_safety_gates("manage_login", {"subcommand": "use"})

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    # Give A a head-start so it grabs the lock first; B then waits on the lock
    # and re-reads always_approved_categories after A releases.
    time.sleep(0.01)
    t_b.start()
    t_a.join(timeout=5)
    t_b.join(timeout=5)

    assert not t_a.is_alive(), "thread A hung — approval lock starvation"
    assert not t_b.is_alive(), "thread B hung — second caller never short-circuited"

    rejection_a, approved_a = results["a"]
    rejection_b, approved_b = results["b"]
    assert rejection_a is None and approved_a is True
    assert rejection_b is None and approved_b is True, (
        "second parallel call must observe always-set promotion and approve"
    )
    assert "write" in gate._always_approved_categories


# ---------------------------------------------------------------------------
# Contract 3 — daemon socket timeout fails CLOSED, not silently hangs
# ---------------------------------------------------------------------------


def test_request_approval_uses_finite_timeout() -> None:
    """Source-level: poller's request_approval must set a finite settimeout
    on the client socket so a stuck thin client doesn't pin a daemon thread
    forever. Pre-v0.52.1 this was already 120s — this test pins it to
    prevent a future refactor from removing the timeout.
    """
    src = inspect.getsource(_poller_mod._StreamingWriter.request_approval)
    assert "settimeout" in src, (
        "poller.request_approval must set a socket timeout — otherwise a "
        "stuck thin client (e.g. user walked away) hangs the daemon thread."
    )
    # The timeout returns "n" (denial) on timeout — fail closed for HITL.
    assert 'return "n"' in src, (
        "TimeoutError path must return 'n' (deny) — never default-allow on hang"
    )


def test_request_approval_returns_decision_on_socket_close() -> None:
    """End-to-end: simulate a thin client that disconnects mid-prompt.
    The daemon must return "n" (denial), not raise, not block forever.
    """
    fake_sock = MagicMock()
    # recv returns empty bytes → connection closed
    fake_sock.recv.return_value = b""
    writer = _poller_mod._StreamingWriter(fake_sock)
    decision = writer.request_approval("manage_login", "subcommand=use", "write")
    assert decision == "n", "closed connection during HITL must default to denial (fail-closed)"
