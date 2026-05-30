"""Assemble a combined seed pool from the most-recent seed-generation runs (B1).

The self-improving 10-cycle audits a model against a *pool* of adversarial seed
prompts. Each seed-generation run (``docs/self-improving/petri-bundle/seeds/<run_id>/``)
produces ~5 survivor seeds for one target dimension; a cycle wants the union of
the latest few runs as its input pool. This script builds that pool
**deterministically** — no LLM, no randomness, no filesystem mtime — so the same
seeds tree always yields the same pool with the same content identity.

Source of Truth per run dir
===========================

- ``state.json["survivors"]`` — canonical list of survivor id strings.
- ``survivors.json["survivors"]`` — ``[{id, path, elo_rating, pilot}]`` where
  ``path`` is RELATIVE to the run dir (``candidates/<id>.md`` or
  ``candidates_evolved/<id>.md``).

A survivor is VALID iff its id is in ``state.json["survivors"]`` AND its body
file ``(run_dir / entry["path"])`` exists on disk. The body-existence check
drops phantom survivors whose body was pruned.

Run selection
=============

Runs are time-ordered by a STABLE key parsed from ``gen_tag`` — NOT by
filesystem mtime — so selection is reproducible across clones / re-syncs.
``gen-<stamp>-<counter>`` -> ``(stamp, counter)`` (e.g. ``gen-2605-4`` ->
``(2605, 4)``); a legacy bare ``gen1`` -> ``(1,)`` (sorts below ``gen-2605-*``).
The top ``--runs`` (default 2) by descending key are selected; on the real seeds
tree that is ``gen-2605-4`` + ``gen-2605-3``.

Output
======

The valid survivor ``.md`` bodies are copied into a FLAT pool directory (a flat
dir of survivor bodies IS a valid pool — the audit's ``flatten_for_inspect_petri``
passes a flat dir through unchanged). A ``manifest.json`` records the selected
run ids, per-run survivor ids, total count, content hash, and a caller-supplied
generation timestamp. The pool's content identity is computed by REUSING
:func:`core.self_improving_loop.baseline_epoch.seed_pool_content_hash` (gives
``pool-<hash>``).

Run, e.g.::

    uv run python scripts/assemble_seed_pool.py \\
        --out state/seed-pools/cycle-input --now 2026-05-30T00:00:00+00:00

Exit codes
==========

- 0 — pool assembled.
- 1 — fatal error (out dir non-empty without ``--force``, no valid survivors,
  unreadable run metadata, missing seeds root).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.self_improving_loop.baseline_epoch import seed_pool_content_hash

DEFAULT_SEEDS_ROOT = Path("docs/self-improving/petri-bundle/seeds")
#: Default pool destination — under the repo ``state/`` tree (GEODE convention
#: for runtime artefacts), never ``/tmp``.
DEFAULT_OUT = Path("state/seed-pools/cycle-input")
DEFAULT_RUNS = 2


@dataclass(frozen=True)
class SelectedRun:
    """A run chosen for the pool plus its valid survivors (sort order preserved)."""

    run_id: str
    gen_tag: str
    sort_key: tuple[int, ...]
    #: (survivor_id, absolute body path) for each VALID survivor, sorted by id.
    survivors: tuple[tuple[str, Path], ...]


def parse_gen_tag_key(gen_tag: str) -> tuple[int, ...]:
    """Parse ``gen_tag`` into an integer tuple for STABLE descending sort.

    ``gen-2605-4`` -> ``(2605, 4)``; legacy bare ``gen1`` -> ``(1,)``. The
    leading ``gen`` / ``gen-`` prefix is stripped, then the remainder is split on
    ``-`` and each numeric segment kept. A segment that is not an integer is
    skipped (graceful contract at the schema-typed ``int()`` cast — a malformed
    tag never raises, it just contributes fewer key components). A tag with no
    numeric segment at all yields ``()``, which sorts below every real tag.
    """
    tag = str(gen_tag).strip()
    body = tag[3:] if tag.startswith("gen") else tag
    body = body.lstrip("-")
    key: list[int] = []
    for segment in body.split("-"):
        if not segment:
            continue
        try:
            key.append(int(segment))
        except (TypeError, ValueError):
            # Non-numeric segment (e.g. a dim suffix that leaked into the tag) —
            # skip it rather than fail; the numeric prefix still orders the run.
            break
    return tuple(key)


def _load_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path``; raise ``SystemExit`` on any failure.

    Graceful contract at the parse boundary: a missing / unreadable / non-object
    file is a fatal, explained error (not a silent ``{}`` that would drop a run
    from selection without the operator noticing).
    """
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read JSON object from {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path} is not a JSON object")
    return loaded


def _state_survivor_ids(state: dict[str, Any]) -> set[str]:
    """The canonical survivor-id set from ``state.json["survivors"]`` (string ids)."""
    raw_survivors = state.get("survivors")
    if not isinstance(raw_survivors, list):
        return set()
    return {str(item) for item in raw_survivors}


def collect_valid_survivors(
    run_dir: Path,
    *,
    per_run: int | None,
) -> tuple[tuple[str, Path], ...]:
    """Return ``(survivor_id, abs_body_path)`` for each VALID survivor of a run.

    Valid = id in ``state.json["survivors"]`` AND body file
    ``(run_dir / entry["path"])`` exists. Sorted by survivor id for a
    deterministic copy order; ``per_run`` (when set) caps to the first N after
    that sort so the cap is itself deterministic.
    """
    run_root = Path(run_dir)
    state = _load_json_object(run_root / "state.json")
    survivors_meta = _load_json_object(run_root / "survivors.json")
    canonical_ids = _state_survivor_ids(state)

    entries = survivors_meta.get("survivors")
    if not isinstance(entries, list):
        entries = []

    valid: list[tuple[str, Path]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        survivor_id = str(entry.get("id", ""))
        rel_path = entry.get("path")
        if not survivor_id or not isinstance(rel_path, str) or not rel_path:
            continue
        if survivor_id not in canonical_ids:
            continue
        body_path = run_root / rel_path
        if not body_path.is_file():
            # Phantom survivor: listed in state but its body was pruned. Drop it.
            continue
        valid.append((survivor_id, body_path))

    valid.sort(key=lambda pair: pair[0])
    if per_run is not None:
        valid = valid[:per_run]
    return tuple(valid)


def select_runs(
    seeds_root: Path,
    *,
    runs: int,
    per_run: int | None,
) -> list[SelectedRun]:
    """Time-sort run dirs by ``gen_tag`` and return the top ``runs`` with survivors.

    Run dirs are discovered by the presence of ``state.json`` (the canonical
    per-run marker). Each run's sort key comes from its ``state.json["gen_tag"]``.
    Ordering is descending by ``(sort_key, run_id)`` — ``run_id`` as the tie-break
    keeps selection total/deterministic when two runs share a gen_tag. Runs with
    zero valid survivors are still considered for selection slots but contribute
    no bodies (an empty run does not silently promote a lower-ranked run).
    """
    root = Path(seeds_root)
    if not root.is_dir():
        raise SystemExit(f"seeds root {root} does not exist or is not a directory")

    discovered: list[SelectedRun] = []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        state_path = run_dir / "state.json"
        if not state_path.is_file():
            continue
        state = _load_json_object(state_path)
        gen_tag = str(state.get("gen_tag", "")) or run_dir.name
        sort_key = parse_gen_tag_key(gen_tag)
        survivors = collect_valid_survivors(run_dir, per_run=per_run)
        discovered.append(
            SelectedRun(
                run_id=run_dir.name,
                gen_tag=gen_tag,
                sort_key=sort_key,
                survivors=survivors,
            )
        )

    discovered.sort(key=lambda run: (run.sort_key, run.run_id), reverse=True)
    return discovered[:runs]


def _ensure_out_dir(out_dir: Path, *, force: bool) -> None:
    """Prepare the pool dir. Refuse to clobber an existing non-empty dir unless
    ``force`` — then wipe it so the copy is a clean (deterministic) snapshot."""
    pool_dir = Path(out_dir)
    if pool_dir.exists():
        if not pool_dir.is_dir():
            raise SystemExit(f"--out {pool_dir} exists and is not a directory")
        if any(pool_dir.iterdir()) and not force:
            raise SystemExit(f"--out {pool_dir} is not empty; pass --force to overwrite it")
        if force:
            shutil.rmtree(pool_dir)
    pool_dir.mkdir(parents=True, exist_ok=True)


def assemble_pool(
    *,
    seeds_root: Path,
    out_dir: Path,
    runs: int,
    per_run: int | None,
    force: bool,
    now: str | None,
) -> dict[str, Any]:
    """Build the flat pool + manifest deterministically; return the manifest dict.

    ``now`` is supplied by the caller (the manifest's ``generated_at``) — the
    deterministic core never calls ``datetime.now``, so tests are reproducible.
    """
    selected = select_runs(seeds_root, runs=runs, per_run=per_run)
    total = sum(len(run.survivors) for run in selected)
    if total == 0:
        raise SystemExit(
            f"no valid survivors across the {len(selected)} selected run(s) under "
            f"{seeds_root}; nothing to assemble"
        )

    pool_dir = Path(out_dir)
    _ensure_out_dir(pool_dir, force=force)

    # Deterministic copy order: runs in (already sorted) selection order, then
    # survivors in id order. Flat <id>.md destinations.
    for run in selected:
        for survivor_id, body_path in run.survivors:
            shutil.copyfile(body_path, pool_dir / f"{survivor_id}.md")

    content_hash = seed_pool_content_hash(str(pool_dir))

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now,
        "seeds_root": str(seeds_root),
        "runs_requested": runs,
        "per_run_cap": per_run,
        "selected_run_ids": [run.run_id for run in selected],
        "runs": [
            {
                "run_id": run.run_id,
                "gen_tag": run.gen_tag,
                "survivor_ids": [survivor_id for survivor_id, _ in run.survivors],
                "survivor_count": len(run.survivors),
            }
            for run in selected
        ],
        "total_survivors": total,
        "content_hash": content_hash,
    }
    manifest_path = pool_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return manifest


def _print_summary(manifest: dict[str, Any], *, out_dir: Path) -> None:
    """Concise human summary to stdout (no emoji)."""
    print(f"Assembled seed pool: {out_dir}")
    print(f"  content hash : {manifest['content_hash']}")
    print(f"  total seeds  : {manifest['total_survivors']}")
    print(f"  generated_at : {manifest['generated_at']}")
    print("  runs         :")
    for run in manifest["runs"]:
        print(f"    - {run['run_id']} ({run['gen_tag']}): {run['survivor_count']} survivors")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble a combined seed pool (B1).")
    parser.add_argument(
        "--seeds-root",
        type=Path,
        default=DEFAULT_SEEDS_ROOT,
        help=f"seeds SoT root (default: {DEFAULT_SEEDS_ROOT})",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"number of most-recent runs to include (default: {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--per-run",
        type=int,
        default=None,
        help="optional cap on survivors per run (default: no cap)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"pool destination directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a non-empty --out directory",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="ISO timestamp recorded as the manifest's generated_at "
        "(optional; not used by the deterministic core)",
    )
    args = parser.parse_args(argv)

    if args.runs <= 0:
        raise SystemExit("--runs must be a positive integer")
    if args.per_run is not None and args.per_run <= 0:
        raise SystemExit("--per-run must be a positive integer when given")

    manifest = assemble_pool(
        seeds_root=args.seeds_root,
        out_dir=args.out,
        runs=args.runs,
        per_run=args.per_run,
        force=args.force,
        now=args.now,
    )
    _print_summary(manifest, out_dir=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
