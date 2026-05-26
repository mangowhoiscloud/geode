"""Seed-generation bundle sync — auto-copy finished runs to docs/self-improving/petri-bundle/seeds/.

Mirrors the audit-side pattern in ``plugins/petri_audit/bundle_sync.py``
(``sync_eval_to_bundle``). When a seed-generation run finishes, the
orchestrator calls :func:`sync_run_to_bundle` which selectively copies
the publishable subset of ``state/seed-generation/<run_id>/`` into the
Pages-tracked ``docs/self-improving/petri-bundle/seeds/<run_id>/``:

- ``state.json``      — full pipeline snapshot (phase progress, costs)
- ``survivors.json``  — top-K candidate metadata
- ``meta_review.json``— MetaReviewer's next_gen_priors + coverage
- ``candidates/<survivor_id>.md`` — only the SURVIVING candidate bodies
  (full ``candidates/`` directory may be 15 + draft seeds; we don't
  publish the dropped ones — they're available locally in
  ``state/seed-generation/`` for the operator)

Why selective copy: the full ``state/seed-generation/<run_id>/`` can
include ``candidates/<id>.debate.jsonl`` sidecars + debate transcripts +
N drafts (15+). The Pages bundle is a publish surface, not an archive —
operators get the final report (survivors + meta_review) for
auditability, plus the trace (state.json + journal) for diagnostic
inspection. Full drafts live in state/ for local replay.

Cross-ref with the audit pattern
================================

Audit ``.eval`` files: bundle_sync runs **per file** (one event per
finished audit). Seed runs: bundle_sync runs **per run directory** (one
event per ``Pipeline.arun`` completion). The CSP-14 SoT doc
(``docs/plans/2026-05-23-seed-gen-loop3-bundle-serving.md`` § 4) reads
the run-directory layout from this module's sync surface.

Gitignore exception
===================

``.gitignore`` carries ``!docs/self-improving/petri-bundle/seeds/**`` so the synced
files actually enter git (parity with the audit-side
``!docs/self-improving/petri-bundle/logs/**`` rule). Without it the
``state/*`` blanket gitignore would silently drop the syncs — same
anti-pattern as PR-G5b #1350's mutation audit ledger.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "BUNDLE_SEEDS_DIR",
    "sync_run_incremental",
    "sync_run_to_bundle",
]


def _resolve_repo_root() -> Path:
    """Find repo root by walking up from cwd until ``pyproject.toml``.

    Honours ``GEODE_REPO_ROOT`` env override for test fixtures (matches
    the convention from ``core.tools.literature_snapshot``).
    """
    env_root = os.environ.get("GEODE_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    here = Path.cwd().resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor
    return here


def _bundle_seeds_dir() -> Path:
    """Resolved Pages-published seeds directory.

    Lazy resolution so ``GEODE_REPO_ROOT`` test fixtures take effect.
    """
    return _resolve_repo_root() / "docs" / "self-improving/petri-bundle" / "seeds"


# Public constant — readers usually want to import this directly.
BUNDLE_SEEDS_DIR = _bundle_seeds_dir


# Files copied verbatim from the run dir → bundle dir. PR-SEEDS-HIRES
# (2026-05-26) added the 4 observability files so the hub can render
# per-run procedures (transcript) / live progress / ranker match outcomes
# / per-phase cost breakdown. Sub-agent dialogues + checkpoints are
# whole-directory copies handled by ``_sync_subagents`` / ``_sync_checkpoints``.
_RUN_FILES_TO_SYNC = (
    "state.json",
    "survivors.json",
    "meta_review.json",
    "transcript.jsonl",
    "progress.json",
    "tournament.json",
    "per_phase_costs.json",
)


def sync_run_to_bundle(run_dir: Path | str) -> Path | None:
    """Copy a finished seed-generation run's publish-set into the bundle.

    Returns the destination directory on success, ``None`` when skipped
    (env knob set, source missing, or unrecoverable error).

    Idempotent — re-syncing the same run overwrites in place.

    Args:
        run_dir: ``state/seed-generation/<run_id>/`` — the per-run
            directory the orchestrator's ``_persist_state`` populates.
            Must contain at least ``state.json``; the other files
            (``survivors.json`` / ``meta_review.json``) are optional and
            skipped silently when absent (matches the audit-side
            tolerant copy semantics).
    """
    if os.environ.get("GEODE_SEED_BUNDLE_SYNC_DISABLED") == "1":
        log.debug("bundle_sync: GEODE_SEED_BUNDLE_SYNC_DISABLED=1, skipping")
        return None

    src_dir = Path(run_dir).resolve()
    if not src_dir.is_dir():
        log.warning("bundle_sync: source dir missing: %s", src_dir)
        return None
    state_json = src_dir / "state.json"
    if not state_json.is_file():
        log.warning("bundle_sync: state.json missing in %s; skipping sync", src_dir)
        return None

    run_id = src_dir.name
    bundle_dir = _bundle_seeds_dir() / run_id
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("bundle_sync: cannot create bundle dir %s: %s", bundle_dir, exc)
        return None

    # Containment guard — same shape as literature_snapshot's check.
    # Resolved bundle dir must live under docs/self-improving/petri-bundle/seeds/. An
    # absurd ``GEODE_REPO_ROOT`` override that points outside the repo
    # would still pass the mkdir but we want the sync to refuse it.
    resolved = bundle_dir.resolve()
    if "docs/self-improving/petri-bundle/seeds" not in str(resolved):
        log.warning(
            "bundle_sync: resolved bundle dir %s does not contain the canonical "
            "docs/self-improving/petri-bundle/seeds path; refusing sync",
            resolved,
        )
        return None

    for fname in _RUN_FILES_TO_SYNC:
        src = src_dir / fname
        if not src.is_file():
            continue  # tolerant — survivors/meta_review may be absent
        dst = bundle_dir / fname
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            log.warning("bundle_sync: copy %s → %s failed: %s", src, dst, exc)
            continue

    # Copy SURVIVOR candidate bodies only (not the full drafts).
    survivor_ids = _read_survivor_ids(state_json)
    if survivor_ids:
        cand_bundle_dir = bundle_dir / "candidates"
        try:
            cand_bundle_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("bundle_sync: cannot create candidates dir: %s", exc)
        else:
            for survivor_id in survivor_ids:
                src = src_dir / "candidates" / f"{survivor_id}.md"
                if not src.is_file():
                    continue
                dst = cand_bundle_dir / src.name
                try:
                    shutil.copy2(src, dst)
                except OSError as exc:
                    log.warning("bundle_sync: survivor %s copy failed: %s", survivor_id, exc)

    # PR-SEEDS-HIRES (2026-05-26) — hi-resolution observability surface.
    # Walks ``sub_agents/<task_id>/`` + ``checkpoints/<phase>.json``
    # so the hub renders every agent's turn-by-turn dialogue + per-phase
    # state snapshot. No size cap per operator directive (resolution wins).
    _sync_subagents(src_dir, bundle_dir)
    _sync_checkpoints(src_dir, bundle_dir)

    # PR-SEEDS-EVAL-EXPORT (2026-05-25) — additionally synthesise per-
    # phase inspect_ai ``.eval`` archives so the SPA viewer at
    # ``docs/self-improving/petri-bundle/index.html`` (and the live Pages mirror) shows
    # each phase of the run as a task card alongside the audit ones.
    # Best-effort: a converter failure does not block the JSON sync that
    # already succeeded above. ``GEODE_SEED_EVAL_EXPORT_DISABLED=1`` lets
    # operators opt out of the secondary publish path independently of
    # the JSON one (useful while iterating on the converter).
    if os.environ.get("GEODE_SEED_EVAL_EXPORT_DISABLED") != "1":
        try:
            from plugins.seed_generation.eval_export import export_run_to_evals

            logs_dir = _bundle_seeds_dir().parent / "logs"
            export_run_to_evals(bundle_dir, logs_dir)
        except Exception:
            log.warning(
                "bundle_sync: eval_export failed for %s; JSON sync stays",
                run_id,
                exc_info=True,
            )

    log.info("bundle_sync: %s → %s", run_id, bundle_dir)
    return bundle_dir


def _sync_subagents(src_dir: Path, bundle_dir: Path) -> None:
    """Copy every ``sub_agents/<task_id>/{dialogue.jsonl,result.json,session.json}``.

    No-cap verbatim copy per operator directive (2026-05-26 hub upgrade) —
    resolution wins. Worst case ~1.5 MB per run uncompacted (15 generator
    sub-agents × ~50 turns × ~2 KB); ~75 MB/year for 50 runs is acceptable.

    Tolerant: missing ``sub_agents/`` (test runs / early-exit pipelines)
    or unreadable individual files are logged at WARNING and skipped.
    """
    src_subagents = src_dir / "sub_agents"
    if not src_subagents.is_dir():
        return
    dst_subagents = bundle_dir / "sub_agents"
    try:
        dst_subagents.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("bundle_sync: cannot create sub_agents dir: %s", exc)
        return
    for task_dir in sorted(src_subagents.iterdir()):
        if not task_dir.is_dir():
            continue
        dst_task_dir = dst_subagents / task_dir.name
        try:
            dst_task_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("bundle_sync: cannot create %s: %s", dst_task_dir, exc)
            continue
        for fname in ("dialogue.jsonl", "result.json", "session.json"):
            src = task_dir / fname
            if not src.is_file():
                continue
            try:
                shutil.copy2(src, dst_task_dir / fname)
            except OSError as exc:
                log.warning(
                    "bundle_sync: sub-agent %s/%s copy failed: %s",
                    task_dir.name,
                    fname,
                    exc,
                )


def _sync_checkpoints(src_dir: Path, bundle_dir: Path) -> None:
    """Copy ``checkpoints/<phase>.json`` snapshots verbatim.

    Per-phase ``state_snapshot`` is the operator's time-travel surface
    (read by the hub's lineage renderer + resume CLI). ~10 KB per phase.
    """
    src_ck = src_dir / "checkpoints"
    if not src_ck.is_dir():
        return
    dst_ck = bundle_dir / "checkpoints"
    try:
        dst_ck.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("bundle_sync: cannot create checkpoints dir: %s", exc)
        return
    for src in sorted(src_ck.glob("*.json")):
        try:
            shutil.copy2(src, dst_ck / src.name)
        except OSError as exc:
            log.warning("bundle_sync: checkpoint %s copy failed: %s", src.name, exc)


def sync_run_incremental(run_dir: Path | str) -> Path | None:
    """Mtime-aware mid-run sync — copy only files newer than the bundle counterpart.

    Used by the orchestrator's ``_live_sync_loop`` every 5s during a
    running pipeline so the published bundle reflects current state in
    near-real time. ``GEODE_SEED_LIVE_SYNC_DISABLED=1`` opts out (kill
    switch independent of ``GEODE_SEED_BUNDLE_SYNC_DISABLED`` which
    governs the final post-run sync).

    Re-uses the same containment guard + dir resolution as
    :func:`sync_run_to_bundle` to guarantee writes stay under
    ``docs/self-improving/petri-bundle/seeds/<run_id>/``.

    No-op when the source run dir does not yet exist (race between
    Pipeline construction and first phase output).
    """
    if os.environ.get("GEODE_SEED_LIVE_SYNC_DISABLED") == "1":
        return None

    src_dir = Path(run_dir).resolve()
    if not src_dir.is_dir():
        return None

    run_id = src_dir.name
    bundle_dir = _bundle_seeds_dir() / run_id
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if "docs/self-improving/petri-bundle/seeds" not in str(bundle_dir.resolve()):
        return None

    # Top-level files
    for fname in _RUN_FILES_TO_SYNC:
        src = src_dir / fname
        if not src.is_file():
            continue
        dst = bundle_dir / fname
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        try:
            shutil.copy2(src, dst)
        except OSError:
            continue

    # Sub-agent dirs — incremental glob
    _incremental_sync_subagents(src_dir / "sub_agents", bundle_dir / "sub_agents")
    # Checkpoints — incremental glob
    _incremental_sync_checkpoints(src_dir / "checkpoints", bundle_dir / "checkpoints")
    return bundle_dir


def _incremental_sync_subagents(src_subagents: Path, dst_subagents: Path) -> None:
    """Helper: incremental copy of sub_agents/ children. mtime-aware."""
    if not src_subagents.is_dir():
        return
    try:
        dst_subagents.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for task_dir in src_subagents.iterdir():
        if not task_dir.is_dir():
            continue
        dst_task_dir = dst_subagents / task_dir.name
        try:
            dst_task_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for fname in ("dialogue.jsonl", "result.json", "session.json"):
            src = task_dir / fname
            if not src.is_file():
                continue
            dst = dst_task_dir / fname
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue


def _incremental_sync_checkpoints(src_ck: Path, dst_ck: Path) -> None:
    """Helper: incremental copy of checkpoints/*.json. mtime-aware."""
    if not src_ck.is_dir():
        return
    try:
        dst_ck.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for src in src_ck.glob("*.json"):
        dst = dst_ck / src.name
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        try:
            shutil.copy2(src, dst)
        except OSError:
            continue


def _read_survivor_ids(state_json: Path) -> list[str]:
    """Extract the survivor candidate_ids from state.json.

    Returns an empty list when state.json is unreadable / missing the
    ``survivors`` key (defensive — the caller still publishes
    state.json itself; only the per-candidate body copy depends on this).
    """
    try:
        data = json.loads(state_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("bundle_sync: state.json unreadable %s: %s", state_json, exc)
        return []
    survivors = data.get("survivors") if isinstance(data, dict) else None
    if not isinstance(survivors, list):
        return []
    return [str(s) for s in survivors if isinstance(s, str)]


def iter_synced_runs(bundle_seeds_dir: Path | None = None) -> list[dict[str, Any]]:
    """Enumerate published seed runs for the bundle build step.

    Returns a list of dicts with keys ``run_id``, ``path``, plus the
    parsed ``state.json`` content (for cheap aggregate queries the
    listing build step performs). Skips dirs without a parseable
    ``state.json`` with a warning.

    Used by ``scripts/build_seeds_listing.py`` (Pages build step).
    """
    root = bundle_seeds_dir or _bundle_seeds_dir()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for run_dir in sorted(root.iterdir()):
        if not run_dir.is_dir():
            continue
        state_path = run_dir / "state.json"
        if not state_path.is_file():
            continue
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("iter_synced_runs: skipping unparseable %s: %s", state_path, exc)
            continue
        if not isinstance(data, dict):
            continue
        out.append({"run_id": run_dir.name, "path": run_dir, "state": data})
    return out
