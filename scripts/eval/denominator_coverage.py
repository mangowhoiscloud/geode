#!/usr/bin/env python3
"""Check that a measured primary metric covers every frozen planned cell.

``contract.py validate-analysis`` binds the primary denominator *value* to the
frozen run spec and forces ``not-measurable`` when an invalid attempt is
selected. It cannot see an analysis that silently deselects planned execution
attempts while keeping the frozen denominator. This check closes that gap:

- every execution attempt is either selected or superseded by a recorded
  execution successor (``parent_attempt_id``);
- a superseded attempt and its successor are never both selected;
- a measured primary uses exactly ``denominator x cells_per_unit`` selected
  valid execution attempts; ``not-measurable`` may not select more than that.

Rows whose ``change.surface`` is ``analysis-only`` are deterministic aggregates,
not execution cells. ``cells_per_unit`` comes from the frozen protocol, for
example 2 when one primary unit is an LLM|Jev pair and 1 for per-cell units.

A repetition aggregate (05 v1 §3.5, 06 §6) has a second gate, run before
``handoff_tables.py reliability``: every arm's frozen task × repetition plan must be
observed once per slot, with a known strict outcome and one repetition contract
(source revision, policy and reset digests, input, task and verifier digests), and
every task must reach N_i >= n. Any violation exits non-zero with its reasons.

Usage:
    python scripts/eval/denominator_coverage.py <analysis.json> \\
        --run-spec <run-spec.json> --attempts <attempts.jsonl> \\
        --cells-per-unit 2 [--forbid-retries]
    python scripts/eval/denominator_coverage.py repetitions <phase-dir-r0> <phase-dir-r1> \\
        --primitive choice --n 2 [--arm-label a=llm]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.benchmarks.decision_metrics import validate_repetition_matrix
from scripts.eval.contract import (
    _load_json_object,
    validate_analysis,
    validate_attempts,
    validate_run_spec,
)
from scripts.eval.handoff_tables import (
    RELIABILITY_ARM_FIELDS,
    RELIABILITY_CONTRACT_FIELDS,
    reliability_inputs,
)

ANALYSIS_ONLY_SURFACE = "analysis-only"


def check_repetition_matrix(
    phase_dirs: Sequence[Path],
    *,
    n: int,
    primitive: str,
    arm_labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Frozen repetition plan versus observed rows, per arm; ``covered`` only when clean.

    Rejections are enumerated (``decision_metrics.RepetitionRejection``): N_i < n,
    duplicate or unplanned repetitions, missing planned slots, contract mismatch and
    unknown outcomes. A plan that is not a task × repetition product, or a phase
    whose repetitions contradict its run-spec seed schedule, raises ``ValueError``.
    """
    inputs = reliability_inputs(phase_dirs, primitive=primitive, arm_labels=arm_labels)
    arms: dict[str, Any] = {}
    for arm in sorted(inputs.plans):
        tasks, repetitions = inputs.plans[arm]
        matrix = validate_repetition_matrix(
            inputs.trials[arm],
            planned_tasks=tasks,
            planned_repetitions=repetitions,
            n=n,
            contract_fields=RELIABILITY_CONTRACT_FIELDS,
            arm_contract_fields=RELIABILITY_ARM_FIELDS,
        )
        arms[arm] = {
            "covered": not matrix.rejections,
            "reasons": [reason.value for reason in matrix.reasons],
            "rejections": [
                {"reason": reason.value, "detail": detail} for reason, detail in matrix.rejections
            ],
            "planned_tasks": len(matrix.planned_tasks),
            "planned_repetitions": list(matrix.planned_repetitions),
            "complete_tasks": len(matrix.complete_tasks),
            "incomplete_tasks": len(matrix.incomplete_tasks),
            "expected_repetitions": matrix.expected_repetitions,
            "observed_repetitions": matrix.observed_repetitions,
            "valid_repetitions": matrix.valid_repetitions,
        }
    return {
        "covered": all(value["covered"] for value in arms.values()),
        "n": n,
        "run_ids": [phase.keys["run_id"] for phase in inputs.phases],
        "arms": arms,
    }


def _repetitions_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="denominator_coverage.py repetitions",
        description="Gate a frozen repetition set before pass@n / pass^n aggregation.",
    )
    parser.add_argument("phase_dirs", type=Path, nargs="+")
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument(
        "--primitive", required=True, choices=("choice", "noul", "score", "verdict")
    )
    parser.add_argument("--arm-label", action="append", default=[])
    args = parser.parse_args(argv)
    labels: dict[str, str] = {}
    for value in args.arm_label:
        arm, separator, label = value.partition("=")
        if not separator or not arm or not label:
            parser.error("--arm-label must use ARM=LABEL")
        labels[arm] = label
    try:
        report = check_repetition_matrix(
            args.phase_dirs, n=args.n, primitive=args.primitive, arm_labels=labels
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(
            json.dumps({"covered": False, "error_type": type(error).__name__, "error": str(error)})
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["covered"] else 1


def check_denominator_coverage(
    analysis_path: Path,
    *,
    run_spec_path: Path,
    attempts_path: Path,
    cells_per_unit: int,
    forbid_retries: bool = False,
) -> dict[str, Any]:
    """Return a coverage report or raise ``ValueError`` on an uncovered denominator."""
    if type(cells_per_unit) is not int or cells_per_unit < 1:
        raise ValueError("cells_per_unit must be a positive integer from the frozen protocol")
    validate_analysis(analysis_path, run_spec_path=run_spec_path, attempts_path=attempts_path)
    run_spec = validate_run_spec(run_spec_path)
    attempts = validate_attempts(attempts_path)
    analysis = _load_json_object(analysis_path)
    primary_spec = run_spec["study"]["primary_metric"]
    primary = next(
        metric for metric in analysis["metrics"] if metric["name"] == primary_spec["name"]
    )
    executions = [
        attempt for attempt in attempts if attempt["change"]["surface"] != ANALYSIS_ONLY_SURFACE
    ]
    identities = {str(attempt["attempt_id"]) for attempt in executions}
    successors: dict[str, str] = {}
    for attempt in executions:
        parent = attempt["parent_attempt_id"]
        if parent in identities:
            if forbid_retries:
                raise ValueError(
                    f"{attempts_path}: frozen protocol forbids retry lineage: {parent}"
                )
            if parent in successors:
                raise ValueError(f"{attempts_path}: attempt has two successors: {parent}")
            successors[str(parent)] = str(attempt["attempt_id"])
    unexplained = sorted(
        str(attempt["attempt_id"])
        for attempt in executions
        if not attempt["selected_for_analysis"] and str(attempt["attempt_id"]) not in successors
    )
    if unexplained:
        raise ValueError(
            f"{attempts_path}: execution attempt left unselected without a recorded successor: "
            f"{unexplained[0]}"
        )
    doubled = sorted(
        str(attempt["attempt_id"])
        for attempt in executions
        if attempt["selected_for_analysis"]
        and str(attempt["attempt_id"]) in successors
        and any(
            other["selected_for_analysis"]
            and str(other["attempt_id"]) == successors[str(attempt["attempt_id"])]
            for other in executions
        )
    )
    if doubled:
        raise ValueError(
            f"{attempts_path}: superseded attempt and its successor are both selected: {doubled[0]}"
        )
    selected = [attempt for attempt in executions if attempt["selected_for_analysis"]]
    selected_valid = [attempt for attempt in selected if attempt["validity"] == "valid"]
    expected = float(primary_spec["denominator"]) * cells_per_unit
    if not expected.is_integer():
        raise ValueError(f"{run_spec_path}: denominator x cells_per_unit is not a cell count")
    planned_cells = int(expected)
    measured = primary["value"] != "not-measurable"
    if measured and len(selected_valid) != planned_cells:
        raise ValueError(
            f"{analysis_path}: measured primary uses {len(selected_valid)} selected valid "
            f"execution attempts; frozen denominator requires {planned_cells}"
        )
    if len(selected) > planned_cells:
        raise ValueError(
            f"{analysis_path}: {len(selected)} selected execution attempts exceed the "
            f"{planned_cells} frozen planned cells"
        )
    return {
        "run_id": run_spec["run_id"],
        "primary_metric": primary_spec["name"],
        "primary_measured": measured,
        "frozen_denominator": primary_spec["denominator"],
        "cells_per_unit": cells_per_unit,
        "planned_cells": planned_cells,
        "execution_attempts": len(executions),
        "selected_execution_attempts": len(selected),
        "selected_valid_attempts": len(selected_valid),
        "selected_invalid_attempts": len(selected) - len(selected_valid),
        "superseded_attempts": len(successors),
        "missing_cells": planned_cells - len(selected),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["repetitions"]:
        return _repetitions_main(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--cells-per-unit", type=int, required=True)
    parser.add_argument("--forbid-retries", action="store_true")
    args = parser.parse_args(arguments)
    try:
        report = check_denominator_coverage(
            args.analysis,
            run_spec_path=args.run_spec,
            attempts_path=args.attempts,
            cells_per_unit=args.cells_per_unit,
            forbid_retries=args.forbid_retries,
        )
    except (OSError, ValueError, KeyError, StopIteration) as error:
        print(
            json.dumps({"covered": False, "error_type": type(error).__name__, "error": str(error)})
        )
        return 1
    print(json.dumps({"covered": True, **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
