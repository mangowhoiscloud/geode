"""Operational CLI for Crucible evidence normalization and paired decisions."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifacts import load_json_object, write_exclusive_json
from .bundle import PromotionBundle
from .contract import ContractError, load_contract, task_pack_sha256
from .evidence import EvidenceEnvelope, ResourceUsage, load_evidence
from .promotion import PromotionVerdict, decide
from .ref_journal import reconcile_ref_update
from .supervisor import SupervisorError, run_supervisor
from .verifiers import get_assay_adapter, tau2_resource_usage_floor, tau2_task_unit


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


def _add_tau2_task_pack(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "tau2-task-pack",
        help="derive content and workflow-family identities from frozen tau2 tasks",
    )
    parser.add_argument("tasks", type=Path)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--trials-per-task", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)


def _add_tau2_usage(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "tau2-usage",
        help="derive the minimum observable resource usage from finalized tau2 results",
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path)


def _add_score(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "score",
        help="produce one authority-neutral train KEEP/REJECT/INVALID verdict",
    )
    parser.add_argument("contract", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path)


def _add_loop(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "loop",
        help="run an authority-neutral standalone train loop",
    )
    parser.add_argument("config", type=Path)


def _add_bundle(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "bundle",
        help="bind one applied train KEEP chain for sealed evaluation",
    )
    parser.add_argument("repository", type=Path)
    parser.add_argument("attempt", type=Path)
    parser.add_argument("--output", type=Path, required=True)


def _add_reconcile_ref(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "reconcile-ref",
        help="recover one persisted private Crucible ref intent",
    )
    parser.add_argument("repository", type=Path)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_tau2_evidence(subparsers)
    _add_tau2_task_pack(subparsers)
    _add_tau2_usage(subparsers)
    _add_score(subparsers)
    _add_loop(subparsers)
    _add_bundle(subparsers)
    _add_reconcile_ref(subparsers)
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


def _tau2_task_pack(args: argparse.Namespace) -> dict[str, Any]:
    try:
        info = args.tasks.lstat()
    except OSError as exc:
        raise ContractError(f"cannot read tau2 tasks {args.tasks}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
        raise ContractError("tau2 tasks must be a regular file no larger than 64 MiB")
    try:
        raw = json.loads(args.tasks.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read tau2 tasks {args.tasks}: {exc}") from exc
    if not isinstance(raw, list):
        raise ContractError("tau2 tasks must be a JSON list")
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, value in enumerate(raw):
        if not isinstance(value, Mapping):
            raise ContractError(f"tau2 tasks[{index}] must be an object")
        task_id = str(value.get("id") if value.get("id") is not None else "").strip()
        if not task_id:
            raise ContractError(f"tau2 tasks[{index}].id is required")
        if task_id in indexed:
            raise ContractError(f"tau2 tasks repeat id {task_id!r}")
        indexed[task_id] = value
    requested = tuple(str(task_id) for task_id in args.task_id)
    if len(set(requested)) != len(requested):
        raise ContractError("--task-id must not contain duplicates")
    missing = [task_id for task_id in requested if task_id not in indexed]
    if missing:
        raise ContractError("tau2 task IDs are missing: " + ", ".join(missing))
    tasks = tuple(tau2_task_unit(indexed[task_id]) for task_id in requested)
    pack = {
        "schema": "crucible.task-pack.v1",
        "task_pack_sha256": task_pack_sha256(tasks, args.trials_per_task),
        "trials_per_task": args.trials_per_task,
        "tasks": [task.to_dict() for task in tasks],
    }
    write_exclusive_json(args.output, pack)
    return pack


def _tau2_usage(args: argparse.Namespace) -> ResourceUsage:
    raw = load_json_object(
        args.results,
        "tau2 results",
        max_bytes=512 * 1024 * 1024,
    )
    usage = tau2_resource_usage_floor(raw)
    if args.output is not None:
        write_exclusive_json(args.output, usage.to_dict())
    return usage


def _score(args: argparse.Namespace) -> PromotionVerdict:
    contract = load_contract(args.contract)
    if contract.stage == "test":
        raise ContractError("sealed-test scoring requires the one-shot sealed supervisor")
    verdict = decide(
        contract,
        load_evidence(args.baseline),
        load_evidence(args.candidate),
    )
    if args.output is not None:
        write_exclusive_json(args.output, verdict.to_dict())
    return verdict


def _bundle(args: argparse.Namespace) -> PromotionBundle:
    bundle = PromotionBundle.build_from_attempt(args.repository, args.attempt)
    write_exclusive_json(args.output, bundle.to_dict())
    return bundle


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "tau2-evidence":
            evidence = _tau2_evidence(args)
            print(json.dumps(evidence.to_dict(), sort_keys=True))
            return 0 if evidence.execution_status == "complete" else 2
        if args.command == "tau2-task-pack":
            pack = _tau2_task_pack(args)
            print(json.dumps(pack, sort_keys=True))
            return 0
        if args.command == "tau2-usage":
            usage = _tau2_usage(args)
            print(json.dumps(usage.to_dict(), sort_keys=True))
            return 0
        if args.command == "loop":
            summary = run_supervisor(args.config)
            print(json.dumps(summary.to_dict(), sort_keys=True))
            return 0
        if args.command == "bundle":
            bundle = _bundle(args)
            print(json.dumps(bundle.to_dict(), sort_keys=True))
            return 0
        if args.command == "reconcile-ref":
            receipt = reconcile_ref_update(
                args.repository,
                intent_path=args.intent,
                receipt_path=args.receipt,
            )
            print(json.dumps(receipt.to_dict(), sort_keys=True))
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
