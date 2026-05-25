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
(7 checkpoints per run × 1 file per phase = a far simpler index).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from plugins.seed_generation.checkpointer import (
    list_completed_phases,
    load_checkpoint,
)
from plugins.seed_generation.orchestrator import (
    _ITERATION_PHASE_ORDER,
    _PHASE_ORDER,
    PipelineState,
)

log = logging.getLogger(__name__)

__all__ = [
    "ResumeError",
    "hydrate_state",
    "next_phase_to_run",
    "resolve_resume_target",
]


class ResumeError(RuntimeError):
    """Raised when the run directory can't be resumed (missing / corrupt)."""


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


# Re-export _ITERATION_PHASE_ORDER for tests that assert symmetry with
# the orchestrator's iteration cycle (iteration >= 1 doesn't take a
# resume cursor — it's a fresh re-entry by design).
__phase_orders__ = (_PHASE_ORDER, _ITERATION_PHASE_ORDER)


def _ensure_phase_orders_consumed() -> None:
    """No-op reference so the re-export stays detectable by linters."""
    _ = __phase_orders__


_ensure_phase_orders_consumed()
