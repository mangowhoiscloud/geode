"""Backfill one ``kind="baseline"`` row into ``baseline_archive.jsonl``.

The baseline registry (``state/autoresearch/baseline_archive.jsonl``) is written
forward by every ``--promote`` from PR-BASELINE-REGISTRY onward. Baselines
promoted *before* the registry existed are not in it — this script backfills
them from a saved baseline snapshot (a v2 ``baseline.json`` payload) so the hub
can serve them alongside live ones.

The motivating case: the pre-margin-fix **vanilla** baseline
(``margin_rule="dim-stderr"``, the ~75×-too-large promote margin that produced
the 0-approve run) must serve next to the post-fix
(``margin_rule="fitness-stderr"``) baseline as a controlled comparison.

The snapshot records dim_means / dim_stderr / sample_count / modality / axes /
eval_archive / session_id / commit / ts_utc, but **not** the role models — a
historical baseline was measured under a config that has since changed, so the
models must be supplied explicitly (no fabrication: see CLAUDE.md "measured
values only"). Run, e.g.::

    uv run python scripts/backfill_baseline_registry_row.py \
        --snapshot ~/.geode/diagnostics/resume/vanilla_gen0_baseline.json \
        --margin-rule dim-stderr --promoted-by backfill \
        --auditor <model> --target <model> --judge <model> \
        --mutator-model <model> --mutator-source <source>

``--baseline-id`` defaults to the next sequential id; pass it to pin the genesis
row (e.g. ``baseline-2605-1`` for the very first/vanilla baseline).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise SystemExit(f"snapshot {path} is not a v2 baseline payload")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="v2 baseline.json payload")
    parser.add_argument(
        "--margin-rule",
        required=True,
        choices=["dim-stderr", "fitness-stderr"],
        help="the promote-gate rule the baseline was measured under",
    )
    parser.add_argument("--promoted-by", default="backfill")
    parser.add_argument("--baseline-id", default=None, help="default: next sequential id")
    parser.add_argument(
        "--seed-select",
        default=None,
        help="seed pool the baseline was measured under (default: current pool; "
        "pass explicitly for a historical baseline whose pointer has moved)",
    )
    parser.add_argument("--auditor", required=True)
    parser.add_argument("--auditor-source", required=True, help="e.g. api_key (PAYG)")
    parser.add_argument("--target", required=True)
    parser.add_argument("--target-source", required=True, help="e.g. openai-codex (subscription)")
    parser.add_argument("--judge", required=True)
    parser.add_argument("--judge-source", required=True)
    parser.add_argument("--mutator-model", required=True)
    parser.add_argument("--mutator-source", required=True)
    # Historical-spec overrides — for a baseline measured under PRE-current logic,
    # so it hashes to its OWN epoch instead of today's. Omit → the live constant
    # (the live promote path is unaffected). E.g. the pre-margin-fix vanilla
    # baseline: --fitness-formula-version 0 --margin-logic-version 0
    # --promote-policy legacy (predates the E3 control-arm taxonomy).
    parser.add_argument(
        "--promote-policy",
        default=None,
        help="historical promote policy in the hashed spec (e.g. 'legacy' for a "
        "pre-arm baseline); default = live 'gate'",
    )
    parser.add_argument(
        "--fitness-formula-version",
        default=None,
        help="historical fitness_formula_version (e.g. '0' pre-margin-fix); "
        "default = live constant",
    )
    parser.add_argument(
        "--margin-logic-version",
        default=None,
        help="historical margin_logic_version (e.g. '0' pre-margin-fix); default = live constant",
    )
    parser.add_argument(
        "--rubric-version",
        default=None,
        help="historical rubric_version; default = live PETRI_RUBRIC_VERSION",
    )
    parser.add_argument(
        "--dim-set",
        default=None,
        help="historical dim_set; default = live effective dim_set",
    )
    parser.add_argument(
        "--fitness",
        type=float,
        default=None,
        help="the baseline's MEASURED fitness (recorded verbatim, NOT recomputed "
        "under today's compute_fitness — a historical baseline was scored under "
        "its own formula); default = recompute from dim_means",
    )
    args = parser.parse_args(argv)

    # Imported here (not at module top) so the script's --help works without a
    # full autoresearch import; train.py pulls in the config + hooks stack.
    from datetime import UTC, datetime

    from core.self_improving.ledger import (
        _append_baseline_registry_row,
        _baseline_archive_path,
        _next_baseline_id,
    )
    from core.self_improving.loop.observe.baseline_epoch import HistoricalSpecOverride
    from core.self_improving.loop.observe.role_provenance import build_role_provenance

    payload = _load_snapshot(args.snapshot)
    raw = payload.get("raw") or {}
    axes = payload.get("axes") or {}
    dim_means = {k: float(v) for k, v in (raw.get("dim_means") or {}).items()}
    if not dim_means:
        raise SystemExit("snapshot has no raw.dim_means — nothing to register")
    dim_stderr = {k: float(v) for k, v in (raw.get("dim_stderr") or {}).items()}
    sample_count = {k: int(v) for k, v in (raw.get("sample_count") or {}).items()} or None
    modality = {k: str(v) for k, v in (raw.get("measurement_modality") or {}).items()} or None
    fitness_stderr = raw.get("fitness_stderr")
    admire = axes.get("admire_means") or None
    bench = axes.get("bench_means") or None
    ts_utc = str(payload.get("ts_utc") or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    baseline_id = args.baseline_id or _next_baseline_id(datetime.now(UTC))
    _append_baseline_registry_row(
        baseline_id,
        dim_means=dim_means,
        dim_stderr=dim_stderr,
        sample_count=sample_count,
        measurement_modality=modality,
        admire_means=admire,
        bench_means=bench,
        fitness_stderr=(float(fitness_stderr) if fitness_stderr is not None else None),
        margin_rule=args.margin_rule,
        eval_archive=raw.get("eval_archive"),
        session_id=str(payload.get("session_id") or ""),
        commit=str(payload.get("commit") or ""),
        ts_utc=ts_utc,
        promoted_by=args.promoted_by,
        role_provenance=build_role_provenance(
            {
                "auditor": (args.auditor, args.auditor_source),
                "target": (args.target, args.target_source),
                "judge": (args.judge, args.judge_source),
                "mutator": (args.mutator_model, args.mutator_source),
            }
        ),
        seed_select=args.seed_select,
        promote_policy=(args.promote_policy or "gate"),
        historical_spec=HistoricalSpecOverride(
            fitness_formula_version=args.fitness_formula_version,
            margin_logic_version=args.margin_logic_version,
            rubric_version=args.rubric_version,
            dim_set=args.dim_set,
            fitness=args.fitness,
        ),
    )
    epoch = args.promote_policy or "gate"
    print(
        f"appended {baseline_id} (margin_rule={args.margin_rule}, promote_policy={epoch}) "
        f"to {_baseline_archive_path()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
