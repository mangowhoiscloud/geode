"""``eval_response_recorded`` SessionJournal event — ADR-012 M4.0.

M4.1 의 DPO canonical pack JSONL writer 의 *source* 가 되는 단일 event.
각 (prompt, response) turn 마다 fitness 측정값 + 평가 metadata 를 active
SessionJournal 에 emit — M4.1 이 journal stream 을 따라가며 pack
candidate 를 누적.

**Event schema** — ``record.payload`` only (``session_id`` / ``gen_tag`` /
``ts`` / ``component`` / ``event`` / ``level`` are top-level SessionJournal
record fields, not payload fields):

.. code-block:: json

    {
      "prompt": "...user message verbatim...",
      "response": "...agent assistant message verbatim...",
      "fitness_score": 0.82,
      "axis_scores": {
        "dim_means_aggregate": 0.78,
        "ux_means_aggregate": 0.84,
        "admire_means_aggregate": 0.90,
        "bench_means_aggregate": 0.75
      },
      "source": "petri_audit" | "live_session" | "...",
      "rollback_flag": false
    }

``rollback_flag`` 는 사용자가 그 응답을 revert 했는지 — M4.1 의
chosen/rejected 라벨링 핵심 신호 (revert=True → rejected).

**No journal scope = no-op**. ``current_session_journal()`` 이 ``None``
이면 emit 자체가 안 일어남 (BACKFILL-SOT 의 contextvar 패턴 동일).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

EVENT_NAME = "eval_response_recorded"
"""SessionJournal event name — M4.1 reader 가 이 이름으로 filter."""


def emit_eval_response_recorded(
    *,
    prompt: str,
    response: str,
    fitness_score: float,
    axis_scores: dict[str, float] | None = None,
    source: str = "",
    rollback_flag: bool = False,
) -> bool:
    """Emit one ``eval_response_recorded`` event to the active SessionJournal.

    Returns ``True`` if the event was appended, ``False`` if no journal
    is bound in the current ContextVar scope (graceful no-op — caller can
    safely invoke even outside an explicit ``session_journal_scope``).

    Args:
        prompt: User-side message verbatim (M4.1 will use as DPO ``prompt``).
        response: Assistant-side message verbatim (will land in
            ``chosen`` or ``rejected`` pile depending on ``rollback_flag``).
        fitness_score: 4-axis weighted aggregate (S3 의 baseline.json 의
            compute_fitness output). 0.0~1.0+. Higher = better.
        axis_scores: Per-axis breakdown (dim/ux/admire/bench aggregates).
            Optional — when None, the event still carries the scalar
            fitness_score; M4.1 의 ratchet 은 scalar 면 충분히 작동.
        source: Free-form provenance tag (``"petri_audit"`` /
            ``"live_session"`` / ``"replay_test"`` etc.). For audit trail.
        rollback_flag: ``True`` iff the user reverted / dismissed this
            response. Signals "rejected" for DPO pack labeling.
    """
    # Lazy import — keep this module cheap when no journal is bound.
    from core.observability.session_journal import current_session_journal

    journal = current_session_journal()
    if journal is None:
        return False
    payload: dict[str, Any] = {
        "prompt": prompt,
        "response": response,
        "fitness_score": float(fitness_score),
        "source": source,
        "rollback_flag": bool(rollback_flag),
    }
    if axis_scores:
        payload["axis_scores"] = {k: float(v) for k, v in axis_scores.items()}
    try:
        journal.append(EVENT_NAME, payload=payload)
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("eval_response_recorded emit failed: %s", exc)
        return False
    return True


__all__ = ["EVENT_NAME", "emit_eval_response_recorded"]
