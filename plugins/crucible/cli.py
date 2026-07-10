"""Operational CLI for Crucible evidence normalization and paired decisions."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifacts import load_json_object, write_exclusive_json
from .contract import ContractError, load_contract, validate_test_parent
from .evidence import EvidenceEnvelope, ResourceUsage, load_evidence
from .promotion import PromotionVerdict, decide
from .supervisor import SupervisorError, run_supervisor
from .verifiers import get_assay_adapter


def _load_checks(path: Path) -> dict[tuple[str, int], Mapping[str, bool]]:
    payload = load_json_object(path, "checks manifest")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ContractError("checks manifest rows must be a list")
    checks: dict[tuple[str, int], Mapping[str, bool]] = {}
    for index, value in enumerate(rows):
        if not isinstance(value, dict):
            raise ContractError(f"checks manifest rows[{index}] must be an object")
        task_id = value.get("task_id")
        trial = value.get("trial")
        row_checks = value.get("checks")
        if not isinstance(task_id, str) or not task_id:
            raise ContractError(f"checks manifest rows[{index}].task_id is required")
        if isinstance(trial, bool) or not isinstance(trial, int) or trial < 0:
            raise ContractError(f"checks manifest rows[{index}].trial must be non-negative")
        if not isinstance(row_checks, dict) or not all(
            isinstance(name, str) and name and isinstance(result, bool)
            for name, result in row_checks.items()
        ):
            raise ContractError(f"checks manifest rows[{index}].checks must be booleans")
        pair = task_id, trial
        if pair in checks:
            raise ContractError(f"checks manifest repeats pair {task_id!r}/{trial}")
        checks[pair] = row_checks
    return checks


def _add_tau2_evidence(subparsers: Any) -> None:
    parser = subparsers.add_parser("tau2-evidence", help="normalize finalized tau2 results")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)


def _add_score(subparsers: Any) -> None:
    parser = subparsers.add_parser("score", help="produce one paired KEEP/REJECT/INVALID verdict")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--parent-contract", type=Path)
    parser.add_argument("--output", type=Path)


def _add_loop(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "loop",
        help="run an authority-neutral standalone train loop",
    )
    parser.add_argument("config", type=Path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_tau2_evidence(subparsers)
    _add_score(subparsers)
    _add_loop(subparsers)
    return parser.parse_args(argv)


def _tau2_evidence(args: argparse.Namespace) -> EvidenceEnvelope:
    contract = load_contract(args.contract)
    usage = ResourceUsage.from_mapping(load_json_object(args.usage, "usage manifest"))
    schema = contract.assay_config.get("schema")
    if not isinstance(schema, str):
        raise ContractError("contract assay_config.schema is required")
    try:
        adapter = get_assay_adapter(schema)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    evidence = adapter.normalize(
        contract,
        arm=args.arm,
        results_path=args.results,
        snapshot_path=args.snapshot,
        usage=usage,
        checks_by_pair=_load_checks(args.checks),
    )
    write_exclusive_json(args.output, evidence.to_dict())
    return evidence


def _score(args: argparse.Namespace) -> PromotionVerdict:
    contract = load_contract(args.contract)
    if contract.stage == "test":
        if args.parent_contract is None:
            raise ContractError("sealed-test scoring requires --parent-contract")
        validate_test_parent(contract, load_contract(args.parent_contract))
    elif args.parent_contract is not None:
        raise ContractError("--parent-contract is only valid for sealed-test scoring")
    verdict = decide(
        contract,
        load_evidence(args.baseline),
        load_evidence(args.candidate),
    )
    if args.output is not None:
        write_exclusive_json(args.output, verdict.to_dict())
    return verdict


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "tau2-evidence":
            evidence = _tau2_evidence(args)
            print(json.dumps(evidence.to_dict(), sort_keys=True))
            return 0 if evidence.execution_status == "complete" else 2
        if args.command == "loop":
            summary = run_supervisor(args.config)
            print(json.dumps(summary.to_dict(), sort_keys=True))
            return 0
        verdict = _score(args)
        print(json.dumps(verdict.to_dict(), sort_keys=True))
        return {"KEEP": 0, "REJECT": 1, "INVALID": 2}[verdict.verdict]
    except (ContractError, OSError, SupervisorError) as exc:
        print(
            json.dumps(
                {
                    "schema": "crucible.cli-error.v1",
                    "status": "INVALID",
                    "reason": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
