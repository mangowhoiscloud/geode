#!/usr/bin/env python3
"""One-shot retrofit: populate ``docs/audits/eval-logs/MANIFEST.jsonl``
from existing ``~/.geode/petri/logs/*.eval`` archives.

The runner appends a manifest line after every new ``geode audit --live``
(see ``plugins/petri_audit/runner.py:_append_manifest_line``), but
archives that predate the bookkeeping path stay invisible without this
script. Idempotent — ``has_archive(sha)`` skips already-indexed evals,
so re-running after a future schema bump just fills in the gaps.

Usage::

    python scripts/retrofit_manifest.py
    # or with custom paths:
    python scripts/retrofit_manifest.py \
        --archive-dir ~/.geode/petri/logs \
        --summary-dir docs/audits/eval-logs
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from core.audit.manifest import append_manifest
from core.paths import PETRI_LOGS_DIR

# Single SoT — was a duplicated ``~/.geode/petri/logs`` literal; routing through
# core.paths also picks up the GEODE_HOME env override (PR-PATH-MODERNIZE).
DEFAULT_ARCHIVE_DIR = PETRI_LOGS_DIR
DEFAULT_SUMMARY_DIR = Path("docs/audits/eval-logs")


def _summary_for(eval_path: Path, summary_dir: Path) -> Path | None:
    """Return the matching summary yaml or None.

    Mirrors ``plugins/petri_audit/eval_archive.py:_summary_filename`` —
    ``<YYYY-MM-DD>-<sha1(basename)[:8]>.summary.yaml``.
    """
    name = eval_path.name
    if len(name) < 10 or name[4] != "-" or name[7] != "-":
        return None
    date_prefix = name[:10]
    h = hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    candidate = summary_dir / f"{date_prefix}-{h}.summary.yaml"
    return candidate if candidate.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help="Directory of raw .eval archives (default ~/.geode/petri/logs)",
    )
    parser.add_argument(
        "--summary-dir",
        type=Path,
        default=DEFAULT_SUMMARY_DIR,
        help="Directory of committable summary YAMLs (default docs/audits/eval-logs)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest file path (default docs/audits/eval-logs/MANIFEST.jsonl)",
    )
    args = parser.parse_args(argv)

    archive_dir: Path = args.archive_dir.expanduser()
    summary_dir: Path = args.summary_dir.expanduser()

    if not archive_dir.is_dir():
        print(f"archive-dir does not exist: {archive_dir}", file=sys.stderr)
        return 1

    archives = sorted(archive_dir.glob("*.eval"))
    if not archives:
        print(f"no .eval archives in {archive_dir} — nothing to retrofit")
        return 0

    appended = 0
    skipped = 0
    for archive in archives:
        summary = _summary_for(archive, summary_dir)
        entry = append_manifest(
            archive,
            summary_yaml=summary,
            manifest_path=args.manifest,
        )
        if entry is None:
            skipped += 1
            print(f"  skip {archive.name} (already indexed or unreadable)")
        else:
            appended += 1
            roles = ",".join(sorted((entry.get("models") or {}).keys()))
            print(f"  + {archive.name}  roles=[{roles}]")

    print(f"\nretrofit complete: {appended} appended, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
