#!/usr/bin/env python3
"""On-demand digest of a running / finished self-improving campaign.

PR-CAMPAIGN-DRIVER (2026-05-31); relocated under ``core.self_improving`` by
PR-SELF-IMPROVING-UMBRELLA (2026-05-31). The companion to
``core.self_improving.campaign`` (CLI: ``python -m core.self_improving.watch_campaign``).
Reads the same three SoTs and prints a compact, flushed digest. Post
PR-STATE-SOT-RUNTIME-SPLIT the progress log is RUNTIME (under ``~/.geode``)
while the two ledgers are the in-repo tracked SoT:

* ``~/.geode/self-improving/campaign-progress.log`` — the per-cycle progress
  lines the driver tees (last N); runtime, not versioned.
* ``core/self_improving/state/mutations.jsonl`` — the mutator-driven
  ``kind="attribution"`` rows (``source="mutator"``), grouped by
  ``promote_policy`` arm.
* ``core/self_improving/state/baseline_archive.jsonl`` — the ``kind="baseline"``
  rows, grouped by baseline epoch (``epoch_label`` / ``be-NNN``).

This is read-only; it never spawns an audit or mutates state. Run it any time
during a long campaign to see where the held-out fitness curve sits per arm.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.memory.atomic_write import iter_jsonl
from core.paths import (
    BASELINE_ARCHIVE_PATH,
    CAMPAIGN_PROGRESS_LOG_PATH,
    MUTATION_AUDIT_LOG_PATH,
)

# Single canonical state-dir constant (``core.paths``), env-overridable via
# ``GEODE_STATE_ROOT``. No local re-definition (no dual SoT — CLAUDE.md).
PROGRESS_LOG = CAMPAIGN_PROGRESS_LOG_PATH  # runtime (per-cycle log)
MUTATIONS_JSONL = MUTATION_AUDIT_LOG_PATH  # tracked
BASELINE_ARCHIVE = BASELINE_ARCHIVE_PATH  # tracked


def tail_progress(path: Path, *, last: int) -> list[str]:
    """Return the last ``last`` non-blank lines of the progress log."""
    if not path.exists():
        return []
    lines = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return lines[-last:]


def attribution_by_arm(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Group the mutator-driven attribution rows by ``promote_policy`` arm.

    Only ``source="mutator"`` rows are kept (the campaign's cycle rows); manual
    gen-0 baseline rows (``source="manual"``) carry no arm tag and are excluded
    from the per-arm split.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_jsonl(path):
        if row.get("kind") != "attribution":
            continue
        if row.get("source") != "mutator":
            continue
        arm = str(row.get("promote_policy") or "?")
        grouped[arm].append(row)
    return dict(grouped)


def baseline_epochs(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Group ``kind="baseline"`` rows by epoch label (``be-NNN``)."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_jsonl(path):
        if row.get("kind") != "baseline":
            continue
        label = str(row.get("epoch_label") or row.get("epoch_hash") or "?")
        grouped[label].append(row)
    return dict(grouped)


def _fmt_held_out_curve(rows: list[dict[str, Any]]) -> str:
    vals: list[float] = [
        float(v)
        for r in rows
        if isinstance((v := r.get("held_out_fitness")), (int, float)) and not isinstance(v, bool)
    ]
    if not vals:
        return "(no held-out values)"
    return ", ".join(f"{v:.4f}" for v in vals)


def build_digest(*, last: int) -> list[str]:
    """Compose the full digest as a list of lines."""
    out: list[str] = ["=== campaign digest ==="]

    out.append("")
    out.append(f"--- progress log (last {last}) ---")
    progress_lines = tail_progress(PROGRESS_LOG, last=last)
    out.extend(progress_lines or ["(no campaign-progress.log yet)"])

    out.append("")
    out.append("--- attribution by arm (source=mutator) ---")
    grouped = attribution_by_arm(MUTATIONS_JSONL)
    if not grouped:
        out.append("(no mutator attribution rows yet)")
    else:
        for arm in sorted(grouped):
            rows = grouped[arm]
            out.append(f"arm '{arm}': {len(rows)} cycles | held_out: {_fmt_held_out_curve(rows)}")

    out.append("")
    out.append("--- baseline epochs ---")
    epochs = baseline_epochs(BASELINE_ARCHIVE)
    if not epochs:
        out.append("(no baseline_archive rows yet)")
    else:
        for label in sorted(epochs):
            rows = epochs[label]
            policies = sorted({str(r.get("promote_policy") or "?") for r in rows})
            out.append(f"epoch {label}: {len(rows)} baselines | policies={policies}")

    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--last", type=int, default=20, help="progress-log tail line count (default 20)"
    )
    args = parser.parse_args(argv)
    for line in build_digest(last=args.last):
        print(line, flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
