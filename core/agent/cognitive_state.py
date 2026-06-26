"""CognitiveState — explicit state container for the cognitive loop.

Pre-PR-2 the agentic loop kept its working state implicit:
``ConversationContext.messages`` accumulated turn history, but there
was no named place for *goal*, *subgoals*, *observations*,
*hypotheses*, or *confidence*. Downstream cognitive features
(reflection / episodic memory / causal attribution) had nowhere to
read from.

This module introduces :class:`CognitiveState`, an 8-field dataclass
attached to :class:`AgenticLoop` and updated deterministically each
round. Field producers land incrementally across PR-2 → PR-6:

  ============== ====================================== =========
  field          producer                               PR
  ============== ====================================== =========
  goal           user input on session start            PR-2
  round_count    agentic loop round counter             PR-2
  last_action    tool-call list of the last round       PR-2
  last_observation tool-result summary                   PR-2
  observations   running list of round summaries        PR-2
  subgoals       LLM decomposition node                 PR-3
  hypotheses     reflection node output                 PR-3 (C-2)
  confidence     reflection node output                 PR-3 (C-2)
  ============== ====================================== =========

The 3-codebase consensus that justified an explicit container:

* OpenClaw ``Session.context.state``
* Hermes ``AgentMemory``
* autoresearch ``RunState``

All three keep cognitive state outside the message log so analyzers
can read it without re-parsing transcript text. PR-2 is the *shape*;
later PRs wire the remaining writers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CognitiveState:
    """Explicit cognitive-loop state container.

    All fields default to empty / zero so a freshly-allocated state
    is a valid instance. Producers update fields in place; readers
    consult the snapshot attached to the agentic loop.
    """

    goal: str = ""
    subgoals: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    confidence: float | None = None
    last_action: str = ""
    last_observation: str = ""
    round_count: int = 0

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> CognitiveState:
        """Build a bounded state object from a persisted snapshot."""
        if not isinstance(snapshot, dict):
            return cls()

        def _string_list(key: str, limit: int) -> list[str]:
            raw = snapshot.get(key)
            if not isinstance(raw, list):
                return []
            values: list[str] = []
            for item in raw[-limit:]:
                if isinstance(item, str):
                    head = item.strip()
                    if head:
                        values.append(head)
            return values

        confidence: float | None = None
        raw_confidence = snapshot.get("confidence")
        if isinstance(raw_confidence, int | float) and not isinstance(raw_confidence, bool):
            confidence = max(0.0, min(1.0, float(raw_confidence)))

        raw_round_count = snapshot.get("round_count")
        round_count = (
            raw_round_count
            if isinstance(raw_round_count, int) and not isinstance(raw_round_count, bool)
            else 0
        )
        round_count = max(round_count, 0)

        return cls(
            goal=str(snapshot.get("goal") or ""),
            subgoals=_string_list("subgoals", 5),
            observations=_string_list("observations", 32),
            hypotheses=_string_list("hypotheses", 5),
            confidence=confidence,
            last_action=str(snapshot.get("last_action") or ""),
            last_observation=str(snapshot.get("last_observation") or ""),
            round_count=round_count,
        )

    def record_round(
        self,
        *,
        action: str,
        observation: str,
        summary: str | None = None,
        observations_cap: int = 32,
    ) -> None:
        """Update round-end state.

        ``action`` is a short string describing what the loop did
        (e.g. ``"tools: bash, read"`` or ``"text-only"``).
        ``observation`` is a short string describing what the loop
        saw back (e.g. ``"3 tool results"``). ``summary`` (optional)
        is the round-level summary appended to ``observations``;
        defaults to ``"{action} -> {observation}"``.

        The ``observations`` list is rolling-capped to
        ``observations_cap`` entries (default 32 = ~last 5 minutes of
        interaction) to keep the snapshot bounded.
        """
        self.round_count += 1
        self.last_action = action
        self.last_observation = observation
        if summary is None:
            summary = f"{action} -> {observation}"
        self.observations.append(summary)
        if len(self.observations) > observations_cap:
            del self.observations[0 : len(self.observations) - observations_cap]

    def to_snapshot(self) -> dict[str, object]:
        """Serializable snapshot for telemetry / persistence.

        Telemetry payload shape — every cognitive event carries this
        dict so a downstream Petri / Inspect viewer can replay the
        state evolution without re-parsing the transcript.
        """
        return {
            "goal": self.goal,
            "subgoals": list(self.subgoals),
            "observations": list(self.observations),
            "hypotheses": list(self.hypotheses),
            "confidence": self.confidence,
            "last_action": self.last_action,
            "last_observation": self.last_observation,
            "round_count": self.round_count,
        }


__all__ = ["CognitiveState"]
