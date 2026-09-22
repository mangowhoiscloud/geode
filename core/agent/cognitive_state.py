"""Round observations and optional reflection beliefs outside the transcript.

The loop records actions and observations; reflection updates hypotheses,
subgoals and self-assessed confidence. ``confidence_observed_round`` identifies
the last valid confidence update, not the current round or a verified success.
Legacy snapshots keep unknown provenance as ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any


def bounded_confidence(value: Any) -> float | None:
    """Keep unknown/non-finite confidence distinct from a bounded numeric belief."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not isfinite(value):
        return None
    return float(max(0.0, min(1.0, value)))


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
    confidence_observed_round: int | None = None

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

        confidence = bounded_confidence(snapshot.get("confidence"))

        raw_round_count = snapshot.get("round_count")
        round_count = (
            raw_round_count
            if isinstance(raw_round_count, int) and not isinstance(raw_round_count, bool)
            else 0
        )
        round_count = max(round_count, 0)
        observed_round = snapshot.get("confidence_observed_round")
        if (
            confidence is None
            or type(observed_round) is not int
            or not 0 <= observed_round <= round_count
        ):
            observed_round = None

        return cls(
            goal=str(snapshot.get("goal") or ""),
            subgoals=_string_list("subgoals", 5),
            observations=_string_list("observations", 32),
            hypotheses=_string_list("hypotheses", 5),
            confidence=confidence,
            last_action=str(snapshot.get("last_action") or ""),
            last_observation=str(snapshot.get("last_observation") or ""),
            round_count=round_count,
            confidence_observed_round=observed_round,
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
            "confidence_observed_round": self.confidence_observed_round,
        }


__all__ = ["CognitiveState"]
