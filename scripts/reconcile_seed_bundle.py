#!/usr/bin/env python3
"""Reconcile the served seed-generation bundle's survivor artifacts.

The git-tracked, GitHub-Pages-served Source of Truth is::

    docs/self-improving/petri-bundle/seeds/<run>/

Each run directory carries three views of "who survived" that have drifted
out of sync over successive generations:

1. ``state.json["survivors"]`` — the canonical list of survivor IDs (plus
   ``elo_ratings`` / ``pilot_scores`` dicts).
2. ``survivors.json`` — a metadata view ``{id, path, elo_rating, pilot}``
   whose ``path`` was historically written as an ABSOLUTE local path into
   the gitignored ``state/seed-generation/`` scratch tree — broken on Pages.
3. ``survivors/`` — a directory of survivor ``<id>.md`` body copies that
   went stale relative to ``state.json["survivors"]`` (extra files, empty
   dir, or copies of bodies no longer in the survivor set).

A survivor is VALID iff (a) it is in ``state.json["survivors"]`` AND (b) its
body ``<id>.md`` exists in the run's ``candidates/`` or ``candidates_evolved/``.
This script reconciles all three views to the valid set, writing only
BUNDLE-RELATIVE paths so the bundle is self-contained on any clone.

The script is idempotent — a second run over an already-reconciled bundle
makes no further changes (beyond re-copying identical bodies).

Run from the repo root::

    python3 scripts/reconcile_seed_bundle.py
    python3 scripts/reconcile_seed_bundle.py path/to/seeds

Stdlib only.
"""

from __future__ import annotations

import glob
import json
import shutil
import sys
from pathlib import Path

DEFAULT_SEEDS_DIR = Path("docs/self-improving/petri-bundle/seeds")

# Body directories searched, in priority order, for a survivor's ``<id>.md``.
BODY_SUBDIRS = ("candidates", "candidates_evolved")


def _find_body_subdir(run_dir: Path, survivor_id: str) -> str | None:
    """Return the body subdir name holding ``<id>.md`` (or None if absent)."""
    for subdir in BODY_SUBDIRS:
        if (run_dir / subdir / f"{survivor_id}.md").is_file():
            return subdir
    return None


def _write_json(path: Path, payload: object) -> None:
    """Write ``payload`` as pretty JSON with a trailing newline (UTF-8)."""
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def reconcile_run(run_dir: Path) -> str:
    """Reconcile a single run directory; return its one-line summary."""
    run_name = run_dir.name
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))

    canonical = state.get("survivors") or []

    valid: list[tuple[str, str]] = []  # (id, rel_subdir)
    dropped: list[str] = []
    for survivor_id in canonical:
        subdir = _find_body_subdir(run_dir, survivor_id)
        if subdir is None:
            dropped.append(survivor_id)
        else:
            valid.append((survivor_id, subdir))

    valid_ids = [sid for sid, _ in valid]

    # (3) Re-write state.json["survivors"] only when bodies were dropped, so
    # an already-clean run is untouched. Preserve every other key + format.
    if dropped:
        state["survivors"] = valid_ids
        _write_json(state_path, state)

    elo_ratings = state.get("elo_ratings", {}) or {}
    pilot_scores = state.get("pilot_scores", {}) or {}

    # (4) Re-write survivors.json with BUNDLE-RELATIVE paths.
    survivors_payload = {
        "gen_tag": state.get("gen_tag"),
        "target_dim": state.get("target_dim"),
        "run_id": state.get("run_id") or run_name,
        "survivors": [
            {
                "id": survivor_id,
                "path": f"{subdir}/{survivor_id}.md",
                "elo_rating": elo_ratings.get(survivor_id),
                "pilot": pilot_scores.get(survivor_id),
            }
            for survivor_id, subdir in valid
        ],
    }
    _write_json(run_dir / "survivors.json", survivors_payload)

    # (5) Repopulate survivors/ — prune every existing file, then copy each
    # valid survivor's body in.
    survivors_dir = run_dir / "survivors"
    before = 0
    if survivors_dir.is_dir():
        existing = [p for p in survivors_dir.iterdir() if p.is_file() or p.is_symlink()]
        before = len(existing)
        for entry in existing:
            entry.unlink()
    else:
        survivors_dir.mkdir(parents=True, exist_ok=True)

    for survivor_id, subdir in valid:
        src = run_dir / subdir / f"{survivor_id}.md"
        shutil.copy2(src, survivors_dir / f"{survivor_id}.md")
    after = len(valid)

    return f"{run_name}: survivors {len(valid)} (dropped: {dropped}) survivors/ {before}->{after}"


def reconcile_bundle(seeds_dir: Path) -> list[str]:
    """Reconcile every run dir under ``seeds_dir`` that has a state.json."""
    summaries: list[str] = []
    for entry in sorted(glob.glob(str(seeds_dir / "*"))):
        run_dir = Path(entry)
        if not run_dir.is_dir():
            continue
        if not (run_dir / "state.json").is_file():
            continue
        summaries.append(reconcile_run(run_dir))
    return summaries


def main(argv: list[str]) -> int:
    seeds_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_SEEDS_DIR
    if not seeds_dir.is_dir():
        print(f"FAIL: seeds dir not found: {seeds_dir}", file=sys.stderr)
        return 1
    summaries = reconcile_bundle(seeds_dir)
    if not summaries:
        print(f"NOTICE: no run dirs with state.json under {seeds_dir}")
        return 0
    for line in summaries:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
