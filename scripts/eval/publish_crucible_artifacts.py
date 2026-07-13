"""Deterministic masking + allowlisted publication for Crucible run artifacts.

The external evidence store (``mangowhoiscloud/geode-eval-artifacts``) receives
only a small public subset of each local campaign run: configs, state, ledger,
per-attempt receipts, the loop log, and the opaque power report. The heavy
``reproducible-cache`` (evaluator homes, per-evaluation checkouts, transcripts,
tmp) is never mirrored, and unopened ``withheld-sealed`` material never leaves
the local tree. See ``docs/eval/external-artifact-repository.md``.

Two deterministic operations, both idempotent (byte-identical on re-run):

- ``mask``: rewrite the local home path ``/Users/<user>`` to ``/Users/REDACTED``
  across text files in a tree, so a published run cannot leak the operator's
  local username. Re-running finds nothing left to mask.
- ``stage``: copy the allowlisted public subset of one campaign run into the
  artifact-repo layout, then mask it.

Usage:
    python scripts/eval/publish_crucible_artifacts.py mask <tree> [--user mango]
    python scripts/eval/publish_crucible_artifacts.py stage <run-dir> <dest> [--user mango]
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

REDACTED_HOME = "/Users/REDACTED"

# Text files whose contents are masked. Everything else is copied byte-for-byte
# (and the allowlist below keeps binaries/caches out of scope anyway).
_TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".log", ".md", ".txt"})

# Public evidence, relative to a campaign run directory. Anything not matched
# by these patterns is omitted — that is how caches and sealed material stay
# out without an explicit denylist race.
_ALLOW_GLOBS = (
    "config.json",
    "loop-*.log",
    "prepare/power.json",
    # Top-level preregistration / receipt records (present on hardened runs).
    "failure-driven-preregistration.json",
    "assay-reuse-receipt.json",
    "state/summary.json",
    "state/state.json",
    "state/config.json",
    "state/ledger.jsonl",
    "state/attempts/*/request.json",
    "state/attempts/*/error.json",
    "state/attempts/*/record.json",
    "state/attempts/*/feedback.json",
    "state/attempts/*/search-ref.intent.json",
    "state/attempts/*/search-ref.receipt.json",
)

# Names that must never be published from a campaign tree even if a future
# allowlist glob would otherwise reach them: unopened sealed holdout material.
_SEALED_DENY = re.compile(
    r"(?:^|/)(?:sealed\.pack|sealed-selection|test\.pack|.*-selection)\.json$",
    re.IGNORECASE,
)


def mask_text_file(path: Path, *, user: str) -> bool:
    """Rewrite ``/Users/<user>`` to the redacted home in one text file.

    Returns True when the file changed. Idempotent: the redacted form contains
    no ``/Users/<user>`` substring, so a second pass is a no-op.
    """
    if path.suffix not in _TEXT_SUFFIXES:
        return False
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    masked = original.replace(f"/Users/{user}", REDACTED_HOME)
    if masked == original:
        return False
    path.write_text(masked, encoding="utf-8")
    return True


def mask_tree(root: Path, *, user: str) -> int:
    """Mask every text file under ``root`` (skipping ``.git``). Returns count."""
    changed = 0
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        if mask_text_file(path, user=user):
            changed += 1
    return changed


def _allowlisted_files(run_dir: Path) -> list[Path]:
    selected: set[Path] = set()
    for pattern in _ALLOW_GLOBS:
        for match in run_dir.glob(pattern):
            if match.is_file():
                selected.add(match)
    return sorted(selected)


def stage_run(run_dir: Path, dest_campaigns: Path, *, user: str) -> dict[str, str | list[str]]:
    """Copy the allowlisted public subset of ``run_dir`` into the artifact-repo
    campaigns directory, then mask usernames. Refuses sealed material and never
    rewrites an existing destination run directory (append-only store)."""
    run_dir = run_dir.resolve()
    dest = dest_campaigns / run_dir.name
    if dest.exists():
        raise SystemExit(f"destination already exists (append-only): {dest}")
    files = _allowlisted_files(run_dir)
    if not files:
        raise SystemExit(f"no allowlisted public files under {run_dir}")
    copied: list[str] = []
    for src in files:
        rel = src.relative_to(run_dir)
        if _SEALED_DENY.search(rel.as_posix()):
            raise SystemExit(f"refusing to publish sealed material: {rel}")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        mask_text_file(target, user=user)
        copied.append(rel.as_posix())
    return {"run": run_dir.name, "dest": str(dest), "files": copied}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_mask = sub.add_parser("mask", help="idempotently mask local username in a tree")
    p_mask.add_argument("tree", type=Path)
    p_mask.add_argument("--user", default="mango")
    p_stage = sub.add_parser("stage", help="stage one run's allowlisted public subset")
    p_stage.add_argument("run_dir", type=Path)
    p_stage.add_argument("dest_campaigns", type=Path)
    p_stage.add_argument("--user", default="mango")
    args = parser.parse_args(argv)

    if args.command == "mask":
        n = mask_tree(args.tree.resolve(), user=args.user)
        print(f"masked {n} file(s) under {args.tree}")
        return 0
    report = stage_run(args.run_dir, args.dest_campaigns, user=args.user)
    files = report["files"]
    assert isinstance(files, list)
    print(f"staged {report['run']}: {len(files)} file(s) -> {report['dest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
