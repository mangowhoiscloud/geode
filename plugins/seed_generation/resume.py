"""Resume an interrupted seed-generation run from per-phase checkpoints.

PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — companion to
:mod:`plugins.seed_generation.checkpointer`. The orchestrator writes
``<run_dir>/checkpoints/<phase>.json`` after each successful phase; this
module hydrates a :class:`PipelineState` from the *latest* checkpoint
and computes the next phase to run (the first phase in
``_PHASE_ORDER`` that has no checkpoint on disk).

Design — single-flight, append-only:

- Each checkpoint embeds the **full** ``state_snapshot`` captured at
  end-of-phase, so re-hydrating from the last successful phase
  recovers every field the downstream phases need (candidates,
  reflections, pilot_scores, elo_ratings, evolved_candidates, …).
  No partial-merge logic — the latest checkpoint is the SoT.
- ``next_phase_to_run`` walks ``_PHASE_ORDER`` and returns the first
  phase NOT present in ``list_completed_phases`` (the on-disk
  audit trail). If every phase is on disk, the run is already
  complete and we return None — the caller surfaces "already done"
  and exits 0.

Convergence basis: paperclip's ``loadOrCreateSession`` flow reads the
session JSONL → rebuilds in-memory message history → resumes the
next pending turn. We adapt this to GEODE's phase granularity
(9 phases in ``_PHASE_ORDER`` × 1 file per phase = a far simpler
index than per-event JSONL).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from plugins.seed_generation.checkpointer import (
    list_completed_phases,
    load_checkpoint,
    load_partial_ranker_checkpoint,
)
from plugins.seed_generation.orchestrator import (
    _ITERATION_PHASE_ORDER,
    _PHASE_ORDER,
    PipelineState,
)
from plugins.seed_generation.tournament import MatchOutcome, MatchPlan, WinnerLabel, initial_ratings

log = logging.getLogger(__name__)

__all__ = [
    "RankerPartialResume",
    "ResumeError",
    "hydrate_state",
    "load_ranker_partial_resume",
    "next_phase_to_run",
    "resolve_resume_target",
]


class ResumeError(RuntimeError):
    """Raised when the run directory can't be resumed (missing / corrupt)."""


@dataclass(frozen=True)
class RankerPartialResume:
    """Ranker resume cursor derived from ``ranker.partial.json``."""

    completed_match_ids: tuple[str, ...]
    ratings: dict[str, float]
    outcomes: list[MatchOutcome]
    pending_matches: list[MatchPlan]


def next_phase_to_run(run_dir: Path) -> str | None:
    """Return the first ``_PHASE_ORDER`` phase with no on-disk checkpoint.

    Returns ``None`` when every iteration-0 phase has a checkpoint —
    the caller's run is already complete.
    """
    completed = set(list_completed_phases(run_dir))
    for phase in _PHASE_ORDER:
        if phase not in completed:
            return phase
    return None


def _latest_completed_phase(run_dir: Path) -> str | None:
    """Latest phase with a checkpoint on disk, ordered by completed_at.

    Returns None when no checkpoints exist (fresh / aborted-pre-first-phase
    run dir). Used to pick the snapshot to hydrate from.
    """
    completed = list_completed_phases(run_dir)
    return completed[-1] if completed else None


def hydrate_state(run_dir: Path) -> PipelineState:
    """Rebuild :class:`PipelineState` from the latest checkpoint.

    Reads ``<run_dir>/checkpoints/<latest>.json`` (latest by
    ``completed_at``). Path-typed fields (``run_dir``, ``pool_path_in``,
    ``pool_path_out``) come back as strings — coerce to :class:`Path`.

    Raises :class:`ResumeError` when no checkpoint is present or the
    payload is missing required identity fields.
    """
    latest = _latest_completed_phase(run_dir)
    if latest is None:
        raise ResumeError(f"no checkpoints under {run_dir / 'checkpoints'} — nothing to resume")
    ck = load_checkpoint(run_dir, latest)
    if ck is None:
        raise ResumeError(f"checkpoint {latest!r} unreadable under {run_dir / 'checkpoints'}")
    snap = ck.state_snapshot
    if not snap.get("run_id") or not snap.get("target_dim") or not snap.get("gen_tag"):
        raise ResumeError(
            f"checkpoint {latest!r} missing identity fields "
            f"(run_id/target_dim/gen_tag); refusing to resume"
        )
    state = PipelineState(
        run_id=str(snap["run_id"]),
        target_dim=str(snap["target_dim"]),
        gen_tag=str(snap["gen_tag"]),
        cohort=str(snap.get("cohort", "petri_17dim")),
        target_dims_attribution=list(snap.get("target_dims_attribution", []) or []),
        pareto_mode=bool(snap.get("pareto_mode", False)),
        candidates_requested=int(snap.get("candidates_requested", 15)),
        max_iterations=int(snap.get("max_iterations", 0)),
        current_iteration=int(snap.get("current_iteration", 0)),
        completed_phases=list(snap.get("completed_phases", []) or []),
        pool_path_in=_path_or_none(snap.get("pool_path_in")),
        pool_path_out=_path_or_none(snap.get("pool_path_out")),
        run_dir=_path_or_none(snap.get("run_dir")) or run_dir,
        candidates=list(snap.get("candidates", []) or []),
        reflections=dict(snap.get("reflections", {}) or {}),
        pilot_scores=dict(snap.get("pilot_scores", {}) or {}),
        elo_ratings=dict(snap.get("elo_ratings", {}) or {}),
        survivors=list(snap.get("survivors", []) or []),
        evolved_candidates=list(snap.get("evolved_candidates", []) or []),
        meta_review=dict(snap.get("meta_review", {}) or {}),
        similarity_clusters=list(snap.get("similarity_clusters", []) or []),
        removed_duplicates=list(snap.get("removed_duplicates", []) or []),
        usd_spent=float(snap.get("usd_spent", 0.0)),
        prompt_tokens=int(snap.get("prompt_tokens", 0)),
        completion_tokens=int(snap.get("completion_tokens", 0)),
        baseline_means=_dict_or_none(snap.get("baseline_means")),
        baseline_stderr=_dict_or_none(snap.get("baseline_stderr")),
        supervisor_guidance=dict(snap.get("supervisor_guidance", {}) or {}),
        articles_with_reasoning=str(snap.get("articles_with_reasoning", "")),
        literature_snapshots=dict(snap.get("literature_snapshots", {}) or {}),
        debate_transcripts=dict(snap.get("debate_transcripts", {}) or {}),
    )
    log.info(
        "seed-generation resume: hydrated state from %r checkpoint at %s "
        "(candidates=%d survivors=%d completed_phases=%s)",
        latest,
        run_dir / "checkpoints" / f"{latest}.json",
        len(state.candidates),
        len(state.survivors),
        state.completed_phases,
    )
    return state


def resolve_resume_target(run_dir: Path) -> tuple[PipelineState, str | None]:
    """One-call resolve — returns ``(hydrated_state, resume_from_phase)``.

    ``resume_from_phase`` is ``None`` when every phase has a checkpoint
    (run already complete); the CLI surfaces this case as exit-0 with
    no Pipeline construction.
    """
    state = hydrate_state(run_dir)
    next_phase = next_phase_to_run(run_dir)
    return state, next_phase


def load_ranker_partial_resume(
    run_dir: Path | None,
    *,
    candidate_ids: list[str],
    match_plan: list[MatchPlan],
) -> RankerPartialResume:
    """Return Ranker ratings/outcomes/pending plan after partial resume.

    The partial checkpoint is only accepted when its completed ids form
    an ordered prefix of the current ``match_plan`` and ``total_matches``
    still matches. This avoids replaying a checkpoint created for a
    different candidate set or RNG schedule.
    """
    fresh = RankerPartialResume(
        completed_match_ids=(),
        ratings=initial_ratings(candidate_ids),
        outcomes=[],
        pending_matches=list(match_plan),
    )
    if run_dir is None:
        return fresh
    ck = load_partial_ranker_checkpoint(run_dir)
    if ck is None:
        return fresh
    if ck.total_matches != len(match_plan):
        log.warning(
            "seed-generation resume: ignoring ranker partial checkpoint "
            "(total_matches=%d, current_plan=%d)",
            ck.total_matches,
            len(match_plan),
        )
        return fresh

    completed_ids = list(ck.completed_match_ids)
    expected_prefix = [match.match_id for match in match_plan[: len(completed_ids)]]
    if completed_ids != expected_prefix:
        log.warning(
            "seed-generation resume: ignoring ranker partial checkpoint "
            "because completed_match_ids are not the current match-plan prefix",
        )
        return fresh

    outcomes = _deserialize_ranker_outcomes(ck.partial_outcomes_serialised)
    pending = [match for match in match_plan if match.match_id not in set(completed_ids)]
    ratings = initial_ratings(candidate_ids)
    ratings.update({cid: rating for cid, rating in ck.partial_ratings.items() if cid in ratings})
    log.info(
        "seed-generation resume: ranker partial checkpoint restored %d/%d matches",
        len(completed_ids),
        len(match_plan),
    )
    return RankerPartialResume(
        completed_match_ids=tuple(completed_ids),
        ratings=ratings,
        outcomes=outcomes,
        pending_matches=pending,
    )


def _path_or_none(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def _dict_or_none(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    return {str(k): float(v) for k, v in value.items()}


def _deserialize_ranker_outcomes(payloads: list[dict[str, Any]]) -> list[MatchOutcome]:
    outcomes: list[MatchOutcome] = []
    valid_winners = {"A", "B", "tie"}
    for payload in payloads:
        winner = payload.get("winner")
        if winner not in valid_winners:
            continue
        winner_label = cast(WinnerLabel, winner)
        votes = tuple(cast(WinnerLabel, v) for v in payload.get("votes", []) if v in valid_winners)
        voter_ids = tuple(str(v) for v in payload.get("voter_ids", []))
        outcomes.append(
            MatchOutcome(
                match_id=str(payload.get("match_id", "")),
                a=str(payload.get("a", "")),
                b=str(payload.get("b", "")),
                winner=winner_label,
                votes=votes,
                voter_ids=voter_ids,
            )
        )
    return outcomes


# Re-export _ITERATION_PHASE_ORDER for tests that assert symmetry with
# the orchestrator's iteration cycle (iteration >= 1 doesn't take a
# resume cursor — it's a fresh re-entry by design).
__phase_orders__ = (_PHASE_ORDER, _ITERATION_PHASE_ORDER)


def _ensure_phase_orders_consumed() -> None:
    """No-op reference so the re-export stays detectable by linters."""
    _ = __phase_orders__


_ensure_phase_orders_consumed()
