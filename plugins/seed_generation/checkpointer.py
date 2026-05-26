"""Per-phase checkpoint writer for the seed-generation pipeline.

PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — append-only JSON
checkpoint file per completed phase, written to
``<run_dir>/checkpoints/<phase>.json``. The orchestrator calls
:func:`write_checkpoint` after each successful phase so a mid-run
crash (e.g. ``plan.decompose_async`` timeout, claude-cli network
hang) doesn't lose prior phase output.

Convergence basis (plan §5.3):

- **open-coscientist** (`generator.py:473`) runs LangGraph
  ``ainvoke()`` in-memory with zero mid-run persistence; crashes
  lose everything. GEODE was the same pre-S5.
- **paperclip** (Claude Code) persists per-event JSONL in
  ``~/.claude/projects/<hash>/<session>.jsonl``; resume re-streams
  events by ``session_id``. Event-level is too fine for GEODE
  (8 phases × hundreds of sub-events).
- **LangGraph SqliteSaver** uses ``thread_id`` + ``checkpoint_id``
  keyed CRUD with per-node granularity. GEODE's ``run_id`` is
  the natural ``thread_id`` and phases are the natural nodes.

This module picks the **per-phase** granularity: 1 JSON file per
phase, atomic write via ``os.replace`` of a tmp file, append-only
on a successful phase end. Failed phases write nothing — the next
``audit-seeds resume`` retries them.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "CHECKPOINT_SUBDIR",
    "RANKER_PARTIAL_CHECKPOINT",
    "PhaseCheckpoint",
    "RankerPartialCheckpoint",
    "list_completed_phases",
    "load_checkpoint",
    "load_partial_ranker_checkpoint",
    "write_checkpoint",
    "write_partial_ranker_checkpoint",
]


CHECKPOINT_SUBDIR = "checkpoints"
"""Subdirectory under ``run_dir`` holding the per-phase JSON files."""

RANKER_PARTIAL_CHECKPOINT = "ranker.partial.json"
"""Mid-ranker checkpoint filename under ``<run_dir>/checkpoints``."""


@dataclass(frozen=True)
class PhaseCheckpoint:
    """One record of a phase completing.

    Stored as JSON at ``<run_dir>/checkpoints/<phase>.json``. The
    ``state_snapshot`` is the full :func:`_state_to_json` output
    captured at the moment the phase finished — the resume path
    rehydrates ``PipelineState`` from the latest checkpoint's
    snapshot and skips already-completed phases.

    ``error`` is non-None when the phase was retried after a prior
    failure — current MVP only writes the success case so this stays
    None; the field is reserved for a future "checkpoint-on-failure"
    extension that captures partial work for debugging.
    """

    phase: str
    completed_at: float
    duration_ms: float
    state_snapshot: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "state_snapshot": self.state_snapshot,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PhaseCheckpoint:
        return cls(
            phase=str(payload["phase"]),
            completed_at=float(payload.get("completed_at", 0.0)),
            duration_ms=float(payload.get("duration_ms", 0.0)),
            state_snapshot=dict(payload.get("state_snapshot", {})),
            error=payload.get("error"),
        )


@dataclass(frozen=True)
class RankerPartialCheckpoint:
    """Mid-phase Ranker checkpoint.

    The Ranker dispatches match panels concurrently, but Elo mutation
    remains ordered. This checkpoint records the ordered prefix that has
    already been applied to ``partial_ratings`` so a resumed run can skip
    those matches and continue from the same deterministic Elo state.
    """

    completed_match_ids: list[str]
    partial_ratings: dict[str, float]
    partial_outcomes_serialised: list[dict[str, Any]]
    total_matches: int
    last_checkpoint_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_match_ids": self.completed_match_ids,
            "partial_ratings": self.partial_ratings,
            "partial_outcomes_serialised": self.partial_outcomes_serialised,
            "total_matches": self.total_matches,
            "last_checkpoint_at": self.last_checkpoint_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RankerPartialCheckpoint:
        completed_raw = payload.get("completed_match_ids", [])
        ratings_raw = payload.get("partial_ratings", {})
        outcomes_raw = payload.get("partial_outcomes_serialised", [])
        if not isinstance(completed_raw, list):
            completed_raw = []
        if not isinstance(ratings_raw, dict):
            ratings_raw = {}
        if not isinstance(outcomes_raw, list):
            outcomes_raw = []
        return cls(
            completed_match_ids=[str(item) for item in completed_raw],
            partial_ratings={str(k): float(v) for k, v in ratings_raw.items()},
            partial_outcomes_serialised=[
                dict(item) for item in outcomes_raw if isinstance(item, dict)
            ],
            total_matches=int(payload.get("total_matches", 0)),
            last_checkpoint_at=float(payload.get("last_checkpoint_at", 0.0)),
        )


def write_checkpoint(
    run_dir: Path,
    *,
    phase: str,
    state_snapshot: dict[str, Any],
    duration_ms: float,
    error: str | None = None,
) -> Path:
    """Write a phase checkpoint atomically.

    Atomicity: write to ``<phase>.json.tmp``, then ``os.replace``
    onto ``<phase>.json``. Same invariant as ``mutations.jsonl``'s
    append-only writer (PR-G5b precedent — silent-ignored file
    writers caused observability gaps; ``os.replace`` survives
    partial-write crashes).
    """
    ck = PhaseCheckpoint(
        phase=phase,
        completed_at=time.time(),
        duration_ms=duration_ms,
        state_snapshot=state_snapshot,
        error=error,
    )
    ck_dir = run_dir / CHECKPOINT_SUBDIR
    ck_dir.mkdir(parents=True, exist_ok=True)
    target = ck_dir / f"{phase}.json"
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{phase}.",
        suffix=".tmp",
        dir=str(ck_dir),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ck.to_dict(), fh, ensure_ascii=False, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        # Clean up the temp file on any write failure so the dir
        # doesn't accumulate stale ``.<phase>.*.tmp`` files.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        log.warning(
            "checkpointer: failed to write %s checkpoint at %s — %s",
            phase,
            target,
            exc,
        )
        raise
    return target


def write_partial_ranker_checkpoint(
    run_dir: Path,
    *,
    completed_match_ids: list[str],
    partial_ratings: dict[str, float],
    partial_outcomes_serialised: list[dict[str, Any]],
    total_matches: int,
) -> Path:
    """Write ``checkpoints/ranker.partial.json`` atomically."""
    ck = RankerPartialCheckpoint(
        completed_match_ids=list(completed_match_ids),
        partial_ratings={str(k): float(v) for k, v in partial_ratings.items()},
        partial_outcomes_serialised=[dict(item) for item in partial_outcomes_serialised],
        total_matches=int(total_matches),
        last_checkpoint_at=time.time(),
    )
    ck_dir = run_dir / CHECKPOINT_SUBDIR
    ck_dir.mkdir(parents=True, exist_ok=True)
    target = ck_dir / RANKER_PARTIAL_CHECKPOINT
    fd, tmp_path = tempfile.mkstemp(
        prefix=".ranker.partial.",
        suffix=".tmp",
        dir=str(ck_dir),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ck.to_dict(), fh, ensure_ascii=False, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        log.warning(
            "checkpointer: failed to write ranker partial checkpoint at %s — %s",
            target,
            exc,
        )
        raise
    return target


def load_checkpoint(run_dir: Path, phase: str) -> PhaseCheckpoint | None:
    """Load a single phase's checkpoint, return None when absent.

    Returns None on missing file OR malformed JSON so the caller
    can fall through to re-running the phase. A future MVP+ may
    distinguish "missing" from "corrupt" but for now both surface
    as "rerun this phase".
    """
    target = run_dir / CHECKPOINT_SUBDIR / f"{phase}.json"
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("checkpointer: %s checkpoint at %s unreadable — %s", phase, target, exc)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return PhaseCheckpoint.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("checkpointer: %s checkpoint at %s malformed — %s", phase, target, exc)
        return None


def load_partial_ranker_checkpoint(run_dir: Path) -> RankerPartialCheckpoint | None:
    """Load ``checkpoints/ranker.partial.json`` when present and valid."""
    target = run_dir / CHECKPOINT_SUBDIR / RANKER_PARTIAL_CHECKPOINT
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("checkpointer: ranker partial checkpoint at %s unreadable — %s", target, exc)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return RankerPartialCheckpoint.from_dict(payload)
    except (TypeError, ValueError) as exc:
        log.warning("checkpointer: ranker partial checkpoint at %s malformed — %s", target, exc)
        return None


def list_completed_phases(run_dir: Path) -> list[str]:
    """Return phase names with a saved checkpoint, ordered by
    ``completed_at`` ascending (the order they actually finished).

    The orchestrator's ``_PHASE_ORDER`` is the canonical sequence;
    the on-disk list may differ (re-runs, manual phase invocations)
    so callers should intersect with ``_PHASE_ORDER`` when computing
    "next phase to run".
    """
    ck_dir = run_dir / CHECKPOINT_SUBDIR
    if not ck_dir.is_dir():
        return []
    items: list[tuple[float, str]] = []
    for entry in ck_dir.iterdir():
        if not entry.is_file() or entry.suffix != ".json":
            continue
        phase = entry.stem
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
            ts = float(payload.get("completed_at", 0.0))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        items.append((ts, phase))
    items.sort()
    return [phase for _ts, phase in items]
