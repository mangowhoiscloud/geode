"""Wall-clock budget for AgenticLoop — Karpathy P3 (Budget control).

Replaces the prior turn-count hard cap with a time-based cap (default 2h)
that fires an automatic hand-off procedure at T-10min remaining. Aligns
with 4 frontier patterns simultaneously:

- **Claude Code** (`agent-loop.ts:checkBudgetExhausted`) — wall-clock
  + token budget enforced per turn boundary.
- **Codex CLI** (`--budget-seconds`) — single wall-clock knob.
- **OpenClaw** (Lane TTL) — per-lane time cap inside the gateway.
- **Hermes Agent** (`hermes_state.py` sessions handoff_state) — DB-backed
  state machine that hand-off-watchers consume. We mirror this state
  machine in ``core/agent/handoff.py``.

Budget tracking lives in :class:`SessionMetrics` (Tier 2 aggregator) so
the budget travels with the ContextVar — every helper that already
reads ``current_session_metrics()`` automatically sees the budget. The
budget tracker here is the *operator interface*: it constructs the
2h-default, exposes a clear ``start()`` / ``check()`` shape, and emits
the ``HANDOFF_TRIGGERED`` hook on the boundary.

I/O failures NEVER raise — observability mustn't break the run it observes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.observability.session_metrics import (
    SessionMetrics,
    current_session_metrics,
)

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_HANDOFF_THRESHOLD_S",
    "DEFAULT_TIME_BUDGET_S",
    "BudgetCheck",
    "TimeBudget",
    "check_session_budget",
    "start_session_budget",
]

# 2 hours = 7200s. Operator-decided default (memory:
# ``project_budget_handoff_decision`` 2026-05-23). Override via
# ``GEODE_TIME_BUDGET_S`` env knob or per-call argument.
DEFAULT_TIME_BUDGET_S: float = 7200.0

# T-10min headroom for the handoff window. Empirically matches the
# Claude Code wrap-up reservation (text-only completion needs ~5-10 min
# under worst-case rate limits + tool retries).
DEFAULT_HANDOFF_THRESHOLD_S: float = 600.0


@dataclass(frozen=True, slots=True)
class TimeBudget:
    """Configuration for a wall-clock budget.

    Immutable so multiple sessions can share the same config object without
    cross-pollution. The *state* (start time, triggered flag) lives in
    :class:`SessionMetrics`.
    """

    total_seconds: float = DEFAULT_TIME_BUDGET_S
    handoff_threshold_seconds: float = DEFAULT_HANDOFF_THRESHOLD_S


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    """Result of a per-round budget check.

    The AgenticLoop reads three fields to decide:
    - ``expired``: hard stop — time is fully out.
    - ``handoff_due``: first crossing of T-threshold — fire HANDOFF_TRIGGERED
      and gracefully wrap up the current round.
    - ``remaining_seconds``: for telemetry / soft hints.
    """

    expired: bool
    handoff_due: bool
    remaining_seconds: float


def start_session_budget(
    *,
    total_seconds: float | None = None,
    handoff_threshold_seconds: float | None = None,
    metrics: SessionMetrics | None = None,
) -> TimeBudget:
    """Begin wall-clock budget tracking on the current SessionMetrics.

    Idempotent — re-calling resets the start time. ``metrics`` is the
    optional explicit target; default reads the ContextVar via
    ``current_session_metrics``. Returns the :class:`TimeBudget` config
    actually applied (post-default resolution) so callers can log it.
    """
    cfg = TimeBudget(
        total_seconds=float(total_seconds if total_seconds is not None else DEFAULT_TIME_BUDGET_S),
        handoff_threshold_seconds=float(
            handoff_threshold_seconds
            if handoff_threshold_seconds is not None
            else DEFAULT_HANDOFF_THRESHOLD_S
        ),
    )
    target = metrics if metrics is not None else current_session_metrics()
    target.start_time_budget(cfg.total_seconds, threshold_seconds=cfg.handoff_threshold_seconds)
    return cfg


def check_session_budget(*, metrics: SessionMetrics | None = None) -> BudgetCheck:
    """One-shot budget check for the current SessionMetrics.

    Call from the AgenticLoop ``_check_round_guards`` per-round entry. The
    ``handoff_due`` flag is **one-shot** — only the first crossing of the
    threshold returns True; subsequent calls return False so the loop fires
    ``HANDOFF_TRIGGERED`` exactly once per session, not every round.
    """
    target = metrics if metrics is not None else current_session_metrics()
    remaining = target.time_budget_remaining_s()
    expired = target.time_budget_total_s > 0.0 and remaining <= 0.0
    # is_handoff_due() flips the latched flag on first True — call it before
    # reading remaining so the latch is set atomically with the report.
    handoff_due = target.is_handoff_due()
    return BudgetCheck(
        expired=expired,
        handoff_due=handoff_due,
        remaining_seconds=remaining,
    )


def budget_summary(*, metrics: SessionMetrics | None = None) -> dict[str, Any]:
    """Render a JSON-friendly summary of the active budget. Empty dict when
    no budget is active. Used by handoff hooks + transcripts."""
    target = metrics if metrics is not None else current_session_metrics()
    if target.time_budget_total_s <= 0.0:
        return {}
    return {
        "budget_total_s": round(target.time_budget_total_s, 3),
        "budget_remaining_s": round(target.time_budget_remaining_s(), 3),
        "handoff_threshold_s": round(target.handoff_threshold_s, 3),
        "handoff_triggered_at": target.handoff_triggered_at,
    }
