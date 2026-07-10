#!/usr/bin/env python3
"""Validate a frozen Crucible contract and optional shard manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from plugins.crucible.contract import (
    ContractError,
    load_contract,
    validate_candidate_diff,
    validate_checkout,
    validate_measurement_files,
    validate_shards,
    validate_test_parent,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--shard", action="append", type=Path, default=[])
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--harness-root", type=Path)
    parser.add_argument("--parent-contract", type=Path)
    parser.add_argument("--arm", choices=("baseline", "candidate"))
    return parser.parse_args()


def _load_shard(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"shard must be a JSON object: {path}")
    return payload


def _main() -> int:
    args = parse_args()
    contract = load_contract(args.contract)
    checks = ["contract_schema"]
    if contract.stage == "test" and args.parent_contract is None:
        raise SystemExit("test contracts require --parent-contract")
    if contract.stage == "train" and args.parent_contract is not None:
        raise SystemExit("--parent-contract is only valid for test contracts")
    if args.parent_contract is not None:
        validate_test_parent(contract, load_contract(args.parent_contract))
        checks.append("test_lineage")
    if (args.repo_root is not None or args.shard) and args.arm is None:
        raise SystemExit("--arm is required with --repo-root or --shard")
    if args.arm is not None and args.repo_root is None and not args.shard:
        raise SystemExit("--arm requires --repo-root or --shard")
    if args.harness_root is not None and args.repo_root is None:
        raise SystemExit("--harness-root requires --repo-root")
    if args.repo_root is not None:
        validate_checkout(contract, args.repo_root, arm=args.arm)
        validate_candidate_diff(contract, args.repo_root)
        checks.extend(("checkout", "candidate_diff"))
        if args.harness_root is not None:
            validate_measurement_files(
                contract,
                repo_root=args.repo_root,
                harness_root=args.harness_root,
            )
            checks.append("measurement_hashes")
    if args.shard:
        validate_shards(
            contract,
            [_load_shard(path) for path in args.shard],
            arm=args.arm,
        )
        checks.append("shard_identity")
    if args.repo_root is not None and args.harness_root is not None:
        status = "PREFLIGHT_VALID"
    elif len(checks) == 1 or checks == ["contract_schema", "test_lineage"]:
        status = "CONTRACT_VALID"
    else:
        status = "PARTIAL_PREFLIGHT"
    print(
        json.dumps(
            {
                "contract_id": contract.contract_id,
                "stage": contract.stage,
                "tasks": len(contract.task_ids),
                "shards": len(args.shard),
                "checks": checks,
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    try:
        return _main()
    except (ContractError, OSError, ValueError) as exc:
        print(f"invalid Crucible contract: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
