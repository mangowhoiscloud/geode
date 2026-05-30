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

Two mutually-exclusive modes:

- **Top-N (default)** — runs are time-ordered by a STABLE key parsed from
  ``gen_tag`` (NOT filesystem mtime, so selection is reproducible across clones /
  re-syncs). ``gen-<stamp>-<counter>`` -> ``(stamp, counter)`` (e.g.
  ``gen-2605-4`` -> ``(2605, 4)``); a legacy bare ``gen1`` -> ``(1,)`` (sorts
  below ``gen-2605-*``). The top ``--runs`` (default 2) by descending key are
  selected; on the real seeds tree that is ``gen-2605-4`` + ``gen-2605-3`` — the
  CO-EVOLVING selection pool the 10-cycle audits a candidate against.

- **Explicit (E2)** — ``--select-runs <id>,<id>,...`` pins the EXACT set of run
  ids (every match is taken; ``--runs`` is ignored). This is how the
  VERSION-FROZEN *held-out bench* is assembled: from runs OTHER than the
  selection pool (``gen-2605-1`` + ``gen-2605-2`` + the ``gen1-*`` runs), so the
  held-out ruler is DISJOINT from the seeds that supply selection pressure.
  ``--exclude-runs <id>,<id>,...`` is the complement — drop named runs from
  whichever mode is active (e.g. top-N minus the selection pool). Selection-run
  ids that match no run dir are a fatal error (a typo must not silently shrink
  the frozen bench).

Both modes share the same valid-survivor filter and the same content-hash
identity, so a held-out bench assembled by ``--select-runs`` is just as
deterministic + reproducible-from-committed-survivors as the default pool.

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
import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.self_improving_loop.baseline_epoch import seed_pool_content_hash

_LOGGER = logging.getLogger("assemble_seed_pool")

#: Sort key for a run whose gen_tag is missing / empty / malformed. An empty
#: tuple sorts BELOW every well-formed ``(stamp, counter)`` / ``(n,)`` key, so a
#: malformed run can never be selected as "most recent" over a well-formed one.
_MALFORMED_SORT_KEY: tuple[int, ...] = ()

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


def parse_gen_tag_key(gen_tag: str) -> tuple[int, ...] | None:
    """Parse ``gen_tag`` into an integer tuple for STABLE descending sort.

    The accepted schema is EXACTLY one of two shapes:

    - ``gen-<stamp>-<counter>`` (two ints) -> ``(stamp, counter)``,
      e.g. ``gen-2605-4`` -> ``(2605, 4)``.
    - legacy bare ``gen<n>`` (one int) -> ``(n,)``, e.g. ``gen1`` -> ``(1,)``.

    Anything else — a missing / empty tag, a non-numeric segment, or SPURIOUS
    extra numeric segments (``gen-2605-4-999``) — is MALFORMED and returns
    ``None``. The caller maps ``None`` to :data:`_MALFORMED_SORT_KEY` so a
    malformed tag sorts LOWEST and is never promoted above a well-formed run by
    an extra segment (FIX 3) or by a directory-name fallback (FIX 2).

    Graceful contract: every schema-typed ``int()`` cast is guarded; a malformed
    tag never raises, it resolves to ``None``.
    """
    tag = str(gen_tag).strip()
    if not tag.startswith("gen"):
        return None
    remainder = tag[len("gen") :]

    if remainder and remainder[0].isdigit():
        # Legacy bare ``gen<n>`` — the whole remainder must be a single integer.
        try:
            return (int(remainder),)
        except (TypeError, ValueError):
            return None

    if not remainder.startswith("-"):
        # Neither ``gen<digit>`` nor ``gen-...`` — malformed (e.g. ``genfoo``).
        return None

    segments = remainder[1:].split("-")
    # The hyphenated schema is EXACTLY ``gen-<stamp>-<counter>`` — two segments,
    # both integers. More or fewer segments (or a non-int) is malformed.
    if len(segments) != 2:
        return None
    try:
        return (int(segments[0]), int(segments[1]))
    except (TypeError, ValueError):
        return None


def _split_run_ids(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated ``--select-runs`` / ``--exclude-runs`` value.

    Whitespace around each id is stripped and empty fields are dropped (so a
    trailing comma or a blank value resolves to an empty tuple, never a phantom
    ``""`` run id). Order is preserved for a deterministic, readable manifest;
    duplicates are de-duped while keeping first-seen order.
    """
    seen: dict[str, None] = {}
    for field in str(raw).split(","):
        candidate = field.strip()
        if candidate:
            seen.setdefault(candidate, None)
    return tuple(seen)


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

    Valid = id in ``state.json["survivors"]`` AND ``entry["path"]`` is RUN-LOCAL
    (relative and resolving inside ``run_dir`` — never absolute, never a
    ``../other-run/file.md`` escape; FIX 4) AND the body file exists on disk.
    Sorted by survivor id for a deterministic copy order; ``per_run`` (when set)
    caps to the first N after that sort so the cap is itself deterministic.
    """
    run_root = Path(run_dir)
    # Anchor for the containment check. ``resolve()`` collapses ``..`` and
    # symlinks so the parent test below cannot be fooled by a crafted path.
    run_root_resolved = run_root.resolve()
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
        if not _is_run_local(rel_path, run_root_resolved):
            _LOGGER.warning(
                "survivor %s in %s has a non-run-local path %r "
                "(absolute or escapes the run dir); dropping it as invalid",
                survivor_id,
                run_root.name,
                rel_path,
            )
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


def _is_run_local(rel_path: str, run_root_resolved: Path) -> bool:
    """True iff ``rel_path`` is a relative path resolving INSIDE ``run_root``.

    Guards FIX 4: an absolute ``entry["path"]`` or a ``../other-run/file.md``
    escape is rejected. ``run_root_resolved`` is the already-``resolve()``-d run
    dir; the body path is resolved the same way and must have ``run_root`` among
    its parents (``is_relative_to`` is the schema-typed boundary check).
    """
    candidate = Path(rel_path)
    if candidate.is_absolute():
        return False
    resolved_body = (run_root_resolved / candidate).resolve()
    return resolved_body.is_relative_to(run_root_resolved)


def select_runs(
    seeds_root: Path,
    *,
    runs: int,
    per_run: int | None,
    select_run_ids: tuple[str, ...] = (),
    exclude_run_ids: tuple[str, ...] = (),
) -> list[SelectedRun]:
    """Discover run dirs, filter, and return the chosen runs with survivors.

    Run dirs are discovered by the presence of ``state.json`` (the canonical
    per-run marker). Each run's sort key comes from its ``state.json["gen_tag"]``.
    A missing / empty / malformed gen_tag does NOT fall back to ``run_dir.name``
    for ordering — it maps to :data:`_MALFORMED_SORT_KEY` (sorts lowest) and logs
    a warning, so a malformed dir name (e.g. ``gen-9999-x``) can never be picked
    as most-recent over a well-formed run (FIX 2). Ordering is descending by
    ``(sort_key, run_id)`` — ``run_id`` as the tie-break keeps selection
    total/deterministic when two runs share a gen_tag (e.g. two ``gen1`` runs).

    Selection mode (E2):

    - ``select_run_ids`` empty → **top-N**: return the highest ``runs`` by
      descending key (the default co-evolving pool).
    - ``select_run_ids`` non-empty → **explicit**: return EXACTLY the run dirs
      whose ``run_id`` is in the set, in the same deterministic descending order,
      ignoring ``runs``. A requested id matching no discovered run dir is a fatal
      ``SystemExit`` (a typo must not silently shrink a frozen held-out bench).

    ``exclude_run_ids`` is applied in BOTH modes BEFORE the cut: any discovered
    run whose ``run_id`` is in the set is removed from consideration (so top-N
    fills its slots from the remaining runs, and explicit selection can name a
    superset minus a few). Excluding a run that does not exist is a no-op (it was
    going to be absent anyway).

    Runs with zero valid survivors are still considered for selection slots but
    contribute no bodies (an empty run does not silently promote a lower-ranked
    run); :func:`assemble_pool` rejects the assembled pool if the TOTAL survivor
    count is zero.
    """
    root = Path(seeds_root)
    if not root.is_dir():
        raise SystemExit(f"seeds root {root} does not exist or is not a directory")

    select_set = set(select_run_ids)
    exclude_set = set(exclude_run_ids)

    discovered: list[SelectedRun] = []
    discovered_ids: set[str] = set()
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        state_path = run_dir / "state.json"
        if not state_path.is_file():
            continue
        run_id = run_dir.name
        discovered_ids.add(run_id)
        if run_id in exclude_set:
            continue
        state = _load_json_object(state_path)
        # The raw tag is recorded verbatim in the manifest; only the SORT KEY is
        # derived. run_dir.name is never used as a gen_tag substitute (FIX 2).
        gen_tag = str(state.get("gen_tag", ""))
        parsed = parse_gen_tag_key(gen_tag)
        if parsed is None:
            _LOGGER.warning(
                "run %s has a missing/empty/malformed gen_tag %r; "
                "sorting it lowest (never selected over a well-formed run)",
                run_id,
                gen_tag,
            )
            sort_key = _MALFORMED_SORT_KEY
        else:
            sort_key = parsed
        survivors = collect_valid_survivors(run_dir, per_run=per_run)
        discovered.append(
            SelectedRun(
                run_id=run_id,
                gen_tag=gen_tag,
                sort_key=sort_key,
                survivors=survivors,
            )
        )

    discovered.sort(key=lambda run: (run.sort_key, run.run_id), reverse=True)

    if not select_set:
        # Top-N mode (default co-evolving pool).
        return discovered[:runs]

    # Explicit mode — pin EXACTLY the requested run ids. A requested id that
    # matched no discovered run dir is fatal (a typo must not silently shrink a
    # frozen held-out bench). ``exclude_set`` may legitimately have removed a
    # requested id already → that too is a fatal contradiction, surfaced here.
    missing = sorted(rid for rid in select_set if rid not in discovered_ids)
    if missing:
        raise SystemExit(
            f"--select-runs named run id(s) {missing} not found under {root}; "
            f"discovered run dirs: {sorted(discovered_ids)}"
        )
    contradicted = sorted(select_set & exclude_set)
    if contradicted:
        raise SystemExit(
            f"run id(s) {contradicted} are in BOTH --select-runs and --exclude-runs; "
            "remove the contradiction"
        )
    return [run for run in discovered if run.run_id in select_set]


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


def _assert_no_duplicate_destinations(selected: list[SelectedRun]) -> None:
    """Raise ``SystemExit`` if two selected runs map to the same ``<id>.md`` dest.

    Guards FIX 1. The flat pool destination basename is ``<survivor_id>.md``, so
    two valid survivors with the same id (in different runs) would collide. The
    error names the colliding id and BOTH run_ids so the operator can locate the
    anomaly. Checked BEFORE any copy so the pool dir is never left half-written.
    """
    first_owner: dict[str, str] = {}
    for run in selected:
        for survivor_id, _body_path in run.survivors:
            prior_run_id = first_owner.get(survivor_id)
            if prior_run_id is not None:
                raise SystemExit(
                    f"duplicate survivor id {survivor_id!r} would collide at "
                    f"destination {survivor_id}.md: present in both run "
                    f"{prior_run_id!r} and run {run.run_id!r}; refusing to "
                    "overwrite a body (ids are normally gen_tag-prefixed, so "
                    "this signals an anomaly)"
                )
            first_owner[survivor_id] = run.run_id


def _assert_safe_dest_basename(survivor_id: str, *, run_id: str) -> None:
    """Raise ``SystemExit`` unless ``survivor_id`` is a safe single path segment.

    The flat pool copies a body to ``pool_dir / f"{survivor_id}.md"``. The
    survivor id comes from the (trusted-but-still) seeds tree, so a crafted id
    containing ``/`` or ``..`` (or an absolute leading ``/``) would let the
    destination escape ``pool_dir`` and clobber a file outside the pool. Validate
    that the id is exactly one path segment — no separator, no parent ref, not
    absolute — and fail CLOSED (naming the bad id + its run) before the copy, so
    a path-escape can never write outside the pool.
    """
    candidate = str(survivor_id)
    bad = (
        not candidate
        or candidate in (".", "..")
        or "/" in candidate
        or "\\" in candidate
        or Path(candidate).is_absolute()
        # ``Path(candidate).name`` strips any directory component; if it differs
        # from the raw id, the id carried a separator / parent-ref the simple
        # checks above might miss on some platforms.
        or Path(candidate).name != candidate
    )
    if bad:
        raise SystemExit(
            f"survivor id {survivor_id!r} in run {run_id!r} is not a safe single "
            "path segment (contains a separator, a parent reference, or is "
            f"absolute); refusing to copy to a destination that could escape the "
            "pool dir"
        )


def assemble_pool(
    *,
    seeds_root: Path,
    out_dir: Path,
    runs: int,
    per_run: int | None,
    force: bool,
    now: str | None,
    select_run_ids: tuple[str, ...] = (),
    exclude_run_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build the flat pool + manifest deterministically; return the manifest dict.

    ``now`` is supplied by the caller (the manifest's ``generated_at``) — the
    deterministic core never calls ``datetime.now``, so tests are reproducible.
    ``select_run_ids`` / ``exclude_run_ids`` forward to :func:`select_runs` (E2
    explicit held-out assembly); empty → the top-N default pool.
    """
    selected = select_runs(
        seeds_root,
        runs=runs,
        per_run=per_run,
        select_run_ids=select_run_ids,
        exclude_run_ids=exclude_run_ids,
    )
    total = sum(len(run.survivors) for run in selected)
    if total == 0:
        raise SystemExit(
            f"no valid survivors across the {len(selected)} selected run(s) under "
            f"{seeds_root}; nothing to assemble"
        )

    # FAIL CLOSED on a duplicate flat-copy destination. The flat pool writes
    # ``<id>.md``; if two selected runs each have a valid survivor with the same
    # id, the later copy would silently overwrite the earlier and the manifest
    # would over-count. Survivor ids are normally gen_tag-prefixed, so a
    # collision signals a real anomaly — surface it (naming the id + both
    # run_ids), never silently drop a body.
    _assert_no_duplicate_destinations(selected)

    pool_dir = Path(out_dir)
    _ensure_out_dir(pool_dir, force=force)

    # Deterministic copy order: runs in (already sorted) selection order, then
    # survivors in id order. Flat <id>.md destinations. Each id is validated as a
    # safe single path segment first, so a crafted ``../`` / ``/`` id from the
    # seeds tree can never escape ``pool_dir``.
    for run in selected:
        for survivor_id, body_path in run.survivors:
            _assert_safe_dest_basename(survivor_id, run_id=run.run_id)
            shutil.copyfile(body_path, pool_dir / f"{survivor_id}.md")

    content_hash = seed_pool_content_hash(str(pool_dir))

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now,
        "seeds_root": str(seeds_root),
        # E2 — "explicit" when the held-out bench pinned exact run ids, else
        # "top_n" (the default co-evolving pool). Records WHICH lever produced
        # this pool so a frozen bench's provenance is self-describing.
        "selection_mode": "explicit" if select_run_ids else "top_n",
        "runs_requested": runs,
        "per_run_cap": per_run,
        "select_run_ids": sorted(select_run_ids),
        "exclude_run_ids": sorted(exclude_run_ids),
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
    print(f"  selection    : {manifest['selection_mode']}")
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
        help=f"number of most-recent runs to include in TOP-N mode (default: {DEFAULT_RUNS}); "
        "ignored when --select-runs is given",
    )
    parser.add_argument(
        "--select-runs",
        type=str,
        default="",
        help="comma-separated EXACT run dir ids to pin (E2 explicit mode for a frozen "
        "held-out bench, e.g. the runs DISJOINT from the selection pool); ignores --runs. "
        "A named id that matches no run dir is a fatal error.",
    )
    parser.add_argument(
        "--exclude-runs",
        type=str,
        default="",
        help="comma-separated run dir ids to DROP from consideration in either mode "
        "(e.g. top-N minus the selection pool); excluding an absent run is a no-op.",
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

    select_run_ids = _split_run_ids(args.select_runs)
    exclude_run_ids = _split_run_ids(args.exclude_runs)

    manifest = assemble_pool(
        seeds_root=args.seeds_root,
        out_dir=args.out,
        runs=args.runs,
        per_run=args.per_run,
        force=args.force,
        now=args.now,
        select_run_ids=select_run_ids,
        exclude_run_ids=exclude_run_ids,
    )
    _print_summary(manifest, out_dir=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
