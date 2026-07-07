"""PR-D Phase 2a — ``_check_round_guards`` extraction invariants.

Pins the structural extraction of the round-entry guards (round
limit + time budget) from ``arun``'s while-loop into a dedicated
helper. Phase 2a is pure refactor (zero behaviour change);
``arun`` still breaks on a non-None return value, so the existing
loop wrap-up code runs identically.

Subsequent phases (2b model-drift sync, 2c LLM-call dispatch, etc.)
will continue extracting the per-round body so the full Claude
Code declarative pattern emerges. Phase 2a stops at the smallest,
safest extraction so Codex MCP can confirm zero behavior change
before further surgery.
"""

from __future__ import annotations

import inspect
import time

import pytest
from core.agent.loop.agent_loop import AgenticLoop

# ---------------------------------------------------------------------------
# Method exists with the right signature
# ---------------------------------------------------------------------------


def test_check_round_guards_method_exists() -> None:
    assert hasattr(AgenticLoop, "_check_round_guards")
    method = AgenticLoop._check_round_guards
    sig = inspect.signature(method)
    assert "round_idx" in sig.parameters
    # Returns str | None — non-None reason on break, None when
    # the round should proceed.
    assert "str | None" in str(sig.return_annotation) or sig.return_annotation == "str | None"


def test_check_round_guards_is_sync() -> None:
    """Guards are pure functions — no await needed. Async return
    would force callers to redundantly await."""
    assert not inspect.iscoroutinefunction(AgenticLoop._check_round_guards)


# ---------------------------------------------------------------------------
# Behaviour — exact pre-refactor semantics
# ---------------------------------------------------------------------------


class _StubLoop:
    """Minimal AgenticLoop stub — only the fields ``_check_round_guards``
    reads. Lets the test invoke the helper without constructing the
    full runtime."""

    def __init__(
        self,
        *,
        max_rounds: int = 0,
        time_budget_s: float = 0.0,
        loop_start_time: float = 0.0,
    ) -> None:
        self.max_rounds = max_rounds
        self._time_budget_s = time_budget_s
        self._loop_start_time = loop_start_time


def _call_guards(stub: _StubLoop, round_idx: int) -> str | None:
    """Bind the helper to a stub via descriptor protocol — avoids
    AgenticLoop.__init__ side-effects."""
    bound = AgenticLoop._check_round_guards.__get__(stub, _StubLoop)
    return bound(round_idx)


def test_no_limits_means_no_guard_trigger() -> None:
    """max_rounds=0 + time_budget_s=0 (defaults) means unlimited.
    Helper must return None for any round_idx."""
    stub = _StubLoop()
    assert _call_guards(stub, 0) is None
    assert _call_guards(stub, 999) is None


def test_round_limit_triggers_at_max() -> None:
    """0-based round_idx: max_rounds=3 means rounds 0, 1, 2 proceed
    and round 3 hits the limit. Pin the boundary."""
    stub = _StubLoop(max_rounds=3)
    assert _call_guards(stub, 0) is None
    assert _call_guards(stub, 1) is None
    assert _call_guards(stub, 2) is None
    assert _call_guards(stub, 3) == "round_limit"
    assert _call_guards(stub, 999) == "round_limit"


def test_time_budget_triggers_when_elapsed() -> None:
    """Wall clock comparison against self._loop_start_time."""
    # Loop "started" far in the past — elapsed > 1.0 second
    stub = _StubLoop(
        time_budget_s=1.0,
        loop_start_time=time.monotonic() - 100.0,
    )
    assert _call_guards(stub, 0) == "time_budget"


def test_time_budget_not_triggered_when_within() -> None:
    """Just-started loop — elapsed ≈ 0 < budget."""
    stub = _StubLoop(
        time_budget_s=60.0,
        loop_start_time=time.monotonic(),
    )
    assert _call_guards(stub, 0) is None


def test_round_limit_takes_precedence_over_time_budget() -> None:
    """If both would trigger, the round-limit check runs first
    (mirrors pre-refactor order: Guard 1 before Guard 2). Pin via
    the returned reason."""
    stub = _StubLoop(
        max_rounds=1,
        time_budget_s=1.0,
        loop_start_time=time.monotonic() - 100.0,
    )
    # round_idx=5 > max_rounds=1 AND elapsed > 1.0; reason = round_limit
    assert _call_guards(stub, 5) == "round_limit"


def test_time_budget_zero_means_disabled() -> None:
    """time_budget_s=0.0 disables the guard, no matter how much
    time has elapsed."""
    stub = _StubLoop(
        time_budget_s=0.0,
        loop_start_time=time.monotonic() - 10000.0,
    )
    assert _call_guards(stub, 0) is None


# ---------------------------------------------------------------------------
# arun delegates to the helper
# ---------------------------------------------------------------------------


def test_arun_calls_check_round_guards() -> None:
    """``arun``'s while-loop body must call the helper exactly
    once. Anti-residue guard — the inline ``Guard 1`` / ``Guard 2``
    blocks must NOT remain in ``arun``."""
    src = inspect.getsource(AgenticLoop.arun)
    # Helper is invoked
    assert "guard_reason = self._check_round_guards(round_idx)" in src
    # Inline guards removed
    assert "Guard 1: Round limit" not in src
    assert "Guard 2: Time budget" not in src


def test_arun_preserves_non_none_guard_response() -> None:
    """Pin the break semantics and the reason propagation.

    A triggered guard must still break to the shared wrap-up path, but the
    exact guard reason must be preserved so session-budget handoff/expiry is
    not mislabeled as max_rounds.
    """
    src = inspect.getsource(AgenticLoop.arun)
    assert "guard_reason = self._check_round_guards(round_idx)" in src
    assert "if guard_reason is not None:" in src
    assert "self._guard_exit_result(" in src
    idx = src.index("if guard_reason is not None:")
    after = src[idx:].splitlines()[1:5]  # next 4 lines
    next_nonblank = next((ln.strip() for ln in after if ln.strip()), "")
    assert next_nonblank == "break", (
        "arun must ``break`` (not ``return``) on a triggered guard so "
        "the loop's wrap-up code constructs the AgenticResult — "
        f"got {next_nonblank!r}"
    )


def test_guard_exit_result_keeps_session_budget_reasons() -> None:
    stub = _StubLoop(time_budget_s=1.0)
    bound = AgenticLoop._guard_exit_result.__get__(stub, _StubLoop)

    assert bound("round_limit", rounds=3) == (
        "max_rounds",
        "Max agentic rounds reached. Please try a more specific request.",
    )
    assert bound("time_budget", rounds=2) == (
        "time_budget_expired",
        "Time budget (1s) expired after 2 rounds.",
    )

    reason, text = bound("session_time_budget_handoff", rounds=0)
    assert reason == "session_time_budget_handoff"
    assert "handoff window" in text
    assert "Max agentic rounds" not in text

    reason, text = bound("session_time_budget_expired", rounds=0)
    assert reason == "session_time_budget_expired"
    assert "Session time budget expired" in text
    assert "Max agentic rounds" not in text


# ---------------------------------------------------------------------------
# Constants pinned (regression guard)
# ---------------------------------------------------------------------------


def test_guard_reason_values() -> None:
    """The reason strings are public-facing only inside this helper
    (used for ``log.debug`` and future telemetry hooks). Pin the
    spellings so a future renamer hits this test, not whatever
    consumer eventually subscribes."""
    stub = _StubLoop(max_rounds=1)
    assert _call_guards(stub, 5) == "round_limit"

    stub2 = _StubLoop(time_budget_s=0.001, loop_start_time=time.monotonic() - 1.0)
    assert _call_guards(stub2, 0) == "time_budget"


# ---------------------------------------------------------------------------
# Phase 2a doesn't change phase 1 behaviour
# ---------------------------------------------------------------------------


def test_phase1_session_start_helper_still_exists() -> None:
    """Cross-phase parity — PR-D Phase 1's
    ``_emit_session_start_signals`` must still be there. Phase 2a
    is additive; it must not regress the prior extraction."""
    assert hasattr(AgenticLoop, "_emit_session_start_signals")


@pytest.fixture(autouse=True)
def _reset_time_calls() -> None:
    """No shared state to reset — the stub-based tests are
    self-contained. Fixture present so a future per-test setup hook
    has a place to live."""
    yield
