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
from .contract import ContractError, PromotionRule, load_contract, task_pack_sha256
from .curation import curate_tau2_pack
from .evidence import EvidenceEnvelope, ResourceUsage, load_evidence
from .power import audit_family_power
from .prepare import load_pack, prepare_campaign
from .promotion import PromotionVerdict, decide
from .ref_journal import reconcile_ref_update
from .runtime_budget import audit_runtime_budget
from .runtime_forecast import forecast_runtime, load_runtime_pilot
from .runtime_pilot import build_runtime_pilot
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
    parser.add_argument(
        "--task-split",
        type=Path,
        help="upstream split manifest that must contain every selected task",
    )
    parser.add_argument(
        "--task-split-name",
        help="split key to validate in --task-split",
    )
    parser.add_argument("--trials-per-task", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)


def _add_tau2_curate_pack(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "tau2-curate-pack",
        help="select a deterministic tau2 pack and print only opaque hashes/counts",
    )
    parser.add_argument("tasks", type=Path)
    parser.add_argument("--task-split", type=Path, required=True)
    parser.add_argument("--task-split-name", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--purpose", choices=("train", "test"), required=True)
    parser.add_argument("--salt", required=True)
    parser.add_argument("--fault-tokens", type=int, required=True)
    parser.add_argument("--take", type=int, required=True)
    parser.add_argument("--maximum-per-intent", type=int, required=True)
    parser.add_argument("--maximum-per-persona", type=int, required=True)
    parser.add_argument("--trials-per-task", type=int, default=1)
    parser.add_argument("--exclude-pack", type=Path, action="append", default=[])
    parser.add_argument("--selection-output", type=Path, required=True)
    parser.add_argument("--pack-output", type=Path, required=True)


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


def _add_prepare(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "prepare",
        help="assemble and validate one campaign config from a declarative spec",
    )
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--history",
        type=Path,
        help="campaigns root holding */state/summary.json for the window verdict",
    )
    parser.add_argument(
        "--remaining-tokens",
        type=int,
        help="remaining window tokens; enables the launch-capacity verdict",
    )


def _add_power_audit(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "power-audit",
        help="audit one opaque task pack against an explicit family-power specification",
    )
    parser.add_argument("pack", type=Path)
    parser.add_argument("--promotion", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)


def _add_runtime_audit(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "runtime-audit",
        help="audit a frozen train or sealed contract against a runtime pilot",
    )
    parser.add_argument("contract", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--campaign-wall-seconds", type=float)
    parser.add_argument("--output", type=Path, required=True)


def _add_runtime_pilot(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "runtime-pilot",
        help="project verified paired arm artifacts into an opaque runtime pilot",
    )
    parser.add_argument("contract", type=Path)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--baseline-results", type=Path, required=True)
    parser.add_argument("--baseline-evidence", type=Path, required=True)
    parser.add_argument("--candidate-results", type=Path, required=True)
    parser.add_argument("--candidate-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)


def _add_runtime_forecast(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "runtime-forecast",
        help="forecast one target design and its p95/p99 calibration effort",
    )
    parser.add_argument("--pilot", type=Path, action="append", required=True)
    parser.add_argument("--target-contract", type=Path, required=True)
    parser.add_argument("--simulations", type=int, default=200_000)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--coverage", type=float, action="append")
    parser.add_argument("--experiment-overhead-seconds", type=float, required=True)
    parser.add_argument("--campaign-overhead-seconds", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_tau2_evidence(subparsers)
    _add_tau2_task_pack(subparsers)
    _add_tau2_curate_pack(subparsers)
    _add_tau2_usage(subparsers)
    _add_score(subparsers)
    _add_loop(subparsers)
    _add_prepare(subparsers)
    _add_power_audit(subparsers)
    _add_runtime_pilot(subparsers)
    _add_runtime_forecast(subparsers)
    _add_runtime_audit(subparsers)
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
    if (args.task_split is None) != (args.task_split_name is None):
        raise ContractError("--task-split and --task-split-name must be provided together")
    if args.task_split is not None:
        try:
            split_info = args.task_split.lstat()
        except OSError as exc:
            raise ContractError(f"cannot read tau2 task split {args.task_split}: {exc}") from exc
        if not stat.S_ISREG(split_info.st_mode) or split_info.st_size > 8 * 1024 * 1024:
            raise ContractError("tau2 task split must be a regular file no larger than 8 MiB")
        try:
            split_manifest = json.loads(args.task_split.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read tau2 task split {args.task_split}: {exc}") from exc
        if not isinstance(split_manifest, Mapping):
            raise ContractError("tau2 task split must be a JSON object")
        split_ids = split_manifest.get(args.task_split_name)
        if not isinstance(split_ids, list) or not all(
            isinstance(task_id, str) and task_id for task_id in split_ids
        ):
            raise ContractError(
                f"tau2 task split {args.task_split_name!r} must be a list of task IDs"
            )
        if len(set(split_ids)) != len(split_ids):
            raise ContractError(f"tau2 task split {args.task_split_name!r} repeats task IDs")
        outside_split = [task_id for task_id in requested if task_id not in set(split_ids)]
        if outside_split:
            raise ContractError(
                f"tau2 task IDs are outside split {args.task_split_name!r}: "
                + ", ".join(outside_split)
            )
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


def _tau2_curate_pack(args: argparse.Namespace) -> dict[str, Any]:
    return curate_tau2_pack(
        tasks_path=args.tasks,
        split_path=args.task_split,
        split_name=args.task_split_name,
        domain=args.domain,
        purpose=args.purpose,
        salt=args.salt,
        fault_tokens=args.fault_tokens,
        take=args.take,
        maximum_per_intent=args.maximum_per_intent,
        maximum_per_persona=args.maximum_per_persona,
        trials_per_task=args.trials_per_task,
        exclude_packs=tuple(args.exclude_pack),
        selection_output=args.selection_output,
        pack_output=args.pack_output,
    )


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


def _power_audit(args: argparse.Namespace) -> dict[str, Any]:
    units, trials_per_task = load_pack(args.pack)
    promotion = PromotionRule.from_mapping(load_json_object(args.promotion, "promotion rule"))
    specification = load_json_object(args.spec, "family power specification")
    report = audit_family_power(
        tasks=units,
        trials_per_task=trials_per_task,
        task_pack_sha256=task_pack_sha256(units, trials_per_task),
        promotion=promotion,
        specification=specification,
        basis_root=args.spec.resolve().parent,
    )
    write_exclusive_json(args.output, report)
    return report


def _runtime_audit(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.contract)
    specification = load_json_object(args.spec, "runtime budget specification")
    report = audit_runtime_budget(
        tasks=contract.tasks,
        trials_per_task=contract.trials_per_task,
        task_pack_sha256=contract.task_pack_sha256,
        stage=contract.stage,
        evaluator_sha256=contract.evaluator_sha256,
        harness_sha256=contract.harness_sha256,
        agent_route=contract.agent_route,
        user_route=contract.user_route,
        assay_config=contract.assay_config,
        configured_experiment_wall_seconds=contract.budget.max_wall_seconds,
        configured_campaign_wall_seconds=args.campaign_wall_seconds,
        specification=specification,
        basis_root=args.spec.resolve().parent,
    )
    write_exclusive_json(args.output, report)
    return report


def _runtime_pilot(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.contract)
    pilot = build_runtime_pilot(
        contract,
        runtime_receipt_path=args.runtime_receipt,
        baseline_results_path=args.baseline_results,
        baseline_evidence=load_evidence(args.baseline_evidence),
        candidate_results_path=args.candidate_results,
        candidate_evidence=load_evidence(args.candidate_evidence),
    )
    write_exclusive_json(args.output, pilot)
    return pilot


def _runtime_forecast(args: argparse.Namespace) -> dict[str, Any]:
    pilots = tuple(load_runtime_pilot(path) for path in args.pilot)
    target_contract = load_contract(args.target_contract)
    report = forecast_runtime(
        pilots,
        target_contract=target_contract,
        simulations=args.simulations,
        seed=args.seed,
        confidence=args.confidence,
        coverages=tuple(args.coverage or (0.95, 0.99)),
        experiment_overhead_seconds=args.experiment_overhead_seconds,
        campaign_overhead_seconds=args.campaign_overhead_seconds,
    )
    write_exclusive_json(args.output, report)
    return report


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
        if args.command == "tau2-curate-pack":
            curation_summary = _tau2_curate_pack(args)
            print(json.dumps(curation_summary, sort_keys=True))
            return 0
        if args.command == "tau2-usage":
            usage = _tau2_usage(args)
            print(json.dumps(usage.to_dict(), sort_keys=True))
            return 0
        if args.command == "prepare":
            report = prepare_campaign(
                args.spec,
                output=args.output,
                history_root=args.history,
                remaining_tokens=args.remaining_tokens,
            )
            print(json.dumps(report, sort_keys=True))
            window = report.get("window")
            return 3 if isinstance(window, Mapping) and window.get("fit") == "defer" else 0
        if args.command == "power-audit":
            report = _power_audit(args)
            print(json.dumps(report, sort_keys=True))
            return 0 if report["passes"] else 1
        if args.command == "runtime-pilot":
            pilot = _runtime_pilot(args)
            print(json.dumps(pilot, sort_keys=True))
            return 0
        if args.command == "runtime-forecast":
            report = _runtime_forecast(args)
            print(json.dumps(report, sort_keys=True))
            return 0
        if args.command == "runtime-audit":
            report = _runtime_audit(args)
            print(json.dumps(report, sort_keys=True))
            return 0 if report["passes"] else 1
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
