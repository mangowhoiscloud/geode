"""Explicit HITL approval FSM — per-transition records for decision diagnosis.

Every approval gate (write / expensive / bash / mcp / batch) threads ONE
:class:`ApprovalRecord` through its display → input-parse → verdict →
propagation → execution pipeline, appending a timestamped transition at each
handoff. The record is dumb data plus a tiny legal-transition table; emission
onto the two observability rails (``HookEvent.APPROVAL_TRANSITION`` +
``EvidenceLedger``) lives in ``ApprovalWorkflow.record_transition``.

Why: the 2026-07-02 incident — a user answered ``A`` (always-allow) at a
``memory_save`` write-approval prompt and the tool result still said "User
denied write operation", twice — was undiagnosable because nothing logged
WHERE the decision was lost (it was lost in the IPC read loop, see
``core/server/ipc_server/poller.py::_handle_client_async``). With the FSM,
each stage leaves a record, so a lost or misrouted decision shows up as a
missing / illegal transition instead of a silent denial.

States::

    requested -> displayed -> user_selected(raw_input) -> parsed(verdict)
              -> granted | denied -> propagated -> executed | skipped

Auto short-circuits (skip-permissions / always-allow / hitl-open) jump
``requested -> granted`` directly; auto-deny (3-strike) jumps
``requested -> denied``. An illegal transition is logged with a warning and
recorded anyway with ``illegal=True`` — the FSM never raises into the
approval flow.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Verdicts a raw user input parses into.
VERDICT_ALLOW = "allow"
VERDICT_DENY = "deny"
VERDICT_ALWAYS = "always"

# Single-char decision -> verdict (IPC replies carry only the parsed char).
VERDICT_BY_DECISION = {"y": VERDICT_ALLOW, "n": VERDICT_DENY, "a": VERDICT_ALWAYS}

# States whose transition also writes an EvidenceLedger row (terminal for the
# decision — granted/denied — and terminal for the dispatch — executed/skipped).
LEDGER_ROW_STATES = frozenset({"granted", "denied", "executed", "skipped"})

# Legal transition table. Key = current state ("" = fresh record).
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "": frozenset({"requested"}),
    # Auto short-circuits jump straight to granted (always-allow / skip
    # permissions / hitl-open) or denied (3-strike auto-deny).
    "requested": frozenset({"displayed", "granted", "denied"}),
    # Timeout / interrupt may deny without a recorded selection.
    "displayed": frozenset({"user_selected", "denied"}),
    "user_selected": frozenset({"parsed"}),
    "parsed": frozenset({"granted", "denied"}),
    # granted -> skipped covers a post-grant dispatch failure discovered
    # before propagation (e.g. unknown tool).
    "granted": frozenset({"propagated", "executed", "skipped"}),
    "denied": frozenset({"skipped"}),
    "propagated": frozenset({"executed", "skipped"}),
    "executed": frozenset(),
    "skipped": frozenset(),
}


def parse_decision(raw: str) -> tuple[str, str]:
    """Map raw user input to ``(decision_char, verdict)``.

    Single home for the approval input grammar — the direct console path
    (``ApprovalWorkflow.prompt_with_always``) uses this; the IPC thin client
    (``core/cli/ipc_client.py::_handle_approval_request``) keeps an inline
    copy because it must not import the agent layer — parity is pinned by
    ``tests/core/agent/test_approval_fsm.py``.

    Grammar: empty / ``y`` / ``yes`` -> allow; ``a`` / ``always`` -> always;
    anything else -> deny.
    """
    text = raw.strip().lower()
    if text in ("a", "always"):
        return "a", VERDICT_ALWAYS
    if text in ("", "y", "yes"):
        return "y", VERDICT_ALLOW
    return "n", VERDICT_DENY


@dataclass
class ApprovalTransition:
    """One FSM handoff: ``(state, monotonic_ts, detail)`` + legality flag."""

    state: str
    ts: float
    detail: str = ""
    illegal: bool = False


@dataclass
class ApprovalRecord:
    """Dumb per-approval data: identity + current state + transition trail."""

    tool_name: str
    category: str  # mcp / write / bash / expensive (+ dangerous for computer)
    approval_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = ""
    raw_input: str = ""
    verdict: str = ""  # allow / deny / always — set at the parsed transition
    transitions: list[ApprovalTransition] = field(default_factory=list)

    def transition(self, state: str, detail: str = "") -> ApprovalTransition:
        """Append one transition; validate against the legal-transition table.

        An illegal transition logs a warning and is recorded anyway with
        ``illegal=True`` — it must never raise into the approval flow (a
        diagnostic rail crashing an approval would be worse than the bug it
        instruments).
        """
        legal = state in _LEGAL_TRANSITIONS.get(self.state, frozenset())
        entry = ApprovalTransition(
            state=state, ts=time.monotonic(), detail=detail, illegal=not legal
        )
        if not legal:
            log.warning(
                "approval[%s] %s: illegal transition %r -> %r (%s) — recorded anyway",
                self.approval_id,
                self.tool_name,
                self.state,
                state,
                detail,
            )
        self.transitions.append(entry)
        if state == "user_selected":
            self.raw_input = detail
        elif state == "parsed":
            self.verdict = detail
        self.state = state
        return entry

    def to_event_payload(self) -> dict[str, Any]:
        """Flat payload for the ``APPROVAL_TRANSITION`` hook / ledger row."""
        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "category": self.category,
            "state": self.state,
            "raw_input": self.raw_input,
            "verdict": self.verdict,
            "illegal": any(t.illegal for t in self.transitions),
            "transitions": [[t.state, t.ts, t.detail, t.illegal] for t in self.transitions],
        }
