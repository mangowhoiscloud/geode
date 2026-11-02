#!/usr/bin/env python3
"""Rebuild the published self-improving state snapshot from runtime files.

Producers refresh ``core.paths.PUBLISHED_STATE_DIR`` as they run. This command
rebuilds it from existing runtime files, for the first commit or after editing
the runtime tree by hand:

* ``baseline.json`` from ``<runtime>/baseline.json`` (else the newest
  ``baseline.json.outdated-*``, marked stale);
* ``campaign-progress.json`` from ``<runtime>/campaign-progress.log``;
* ``gen0-fitness-stderr.json`` from ``<runtime>/campaign/gen-0-snapshot/baseline.json``;
* ``crucible-attempts.jsonl`` from ``<campaigns>/*/state/ledger.jsonl``.

A missing source leaves its published file untouched and is reported; nothing
is synthesized. Contract: ``docs/architecture/publication-bundle.md``.

Usage::

    uv run python scripts/refresh_published_state.py
    uv run python scripts/refresh_published_state.py --runtime-dir DIR --crucible-campaigns-dir DIR
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from core.paths import (
    CAMPAIGN_PROGRESS_LOG_PATH,
    PUBLISHED_STATE_DIR,
    RUNTIME_ROOT,
    require_evolve_workspace,
)
from evolve.crucible.publication import (
    CRUCIBLE_ATTEMPTS_NAME,
    collect_attempt_rows,
    write_attempt_rows,
)
from evolve.scaffold_search.campaign import GEN0_SNAPSHOT_DIR
from evolve.scaffold_search.publication import (
    CAMPAIGN_PROGRESS_NAME,
    PublishedStateError,
    latest_runtime_baseline,
    parse_campaign_progress_log,
    publish_baseline,
    publish_gen0_fitness_stderr,
    write_snapshot_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_PROGRESS_LOG_NAME = CAMPAIGN_PROGRESS_LOG_PATH.name
GEN0_SNAPSHOT_BASELINE = GEN0_SNAPSHOT_DIR.relative_to(RUNTIME_ROOT) / "baseline.json"
# Same default and override as the hub's crucible reader.
DEFAULT_CRUCIBLE_CAMPAIGNS_DIR = Path(
    os.environ.get(
        "GEODE_CRUCIBLE_CAMPAIGNS_DIR",
        str(REPO_ROOT / "artifacts" / "eval" / "runs" / "crucible" / "campaigns"),
    )
)


def _status(name: str, changed: bool, source: str) -> str:
    return f"{name}: {'written' if changed else 'unchanged'} from {source}"


def refresh(runtime_dir: Path, campaigns_dir: Path, out_dir: Path) -> list[str]:
    """Rebuild every snapshot whose source exists; return one status line each."""
    lines: list[str] = []
    baseline = latest_runtime_baseline(runtime_dir)
    if baseline is None:
        lines.append("baseline.json: missing source (no runtime baseline)")
    else:
        source, stale = baseline
        changed = publish_baseline(source, stale=stale, out_dir=out_dir)
        lines.append(_status("baseline.json", changed, source.name + (" (stale)" if stale else "")))

    progress_log = runtime_dir / CAMPAIGN_PROGRESS_LOG_NAME
    if progress_log.is_file():
        data = parse_campaign_progress_log(progress_log.read_text(encoding="utf-8"))
        changed = write_snapshot_json(out_dir / CAMPAIGN_PROGRESS_NAME, data)
        counts = ", ".join(f"{len(data[group])} {group}" for group in ("cycles", "gen0", "noise"))
        lines.append(_status(CAMPAIGN_PROGRESS_NAME, changed, f"{progress_log.name} ({counts})"))
    else:
        lines.append(f"{CAMPAIGN_PROGRESS_NAME}: missing source ({progress_log.name})")

    gen0 = runtime_dir / GEN0_SNAPSHOT_BASELINE
    if gen0.is_file():
        changed = publish_gen0_fitness_stderr(gen0, out_dir=out_dir)
        lines.append(
            _status("gen0-fitness-stderr.json", changed, GEN0_SNAPSHOT_BASELINE.as_posix())
        )
    else:
        lines.append(f"gen0-fitness-stderr.json: missing source ({GEN0_SNAPSHOT_BASELINE})")

    if campaigns_dir.is_dir():
        rows = collect_attempt_rows(campaigns_dir)
        changed = write_attempt_rows(out_dir / CRUCIBLE_ATTEMPTS_NAME, rows)
        lines.append(_status(CRUCIBLE_ATTEMPTS_NAME, changed, f"{len(rows)} ledger attempt(s)"))
    else:
        lines.append(f"{CRUCIBLE_ATTEMPTS_NAME}: missing source (no crucible campaigns dir)")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME_ROOT)
    parser.add_argument(
        "--crucible-campaigns-dir", type=Path, default=DEFAULT_CRUCIBLE_CAMPAIGNS_DIR
    )
    parser.add_argument("--out", type=Path, default=PUBLISHED_STATE_DIR)
    args = parser.parse_args(argv)
    try:
        if args.out == PUBLISHED_STATE_DIR:
            require_evolve_workspace()
        lines = refresh(args.runtime_dir, args.crucible_campaigns_dir, args.out)
    except (OSError, PublishedStateError, RuntimeError, ValueError) as exc:
        print(f"refresh_published_state: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
