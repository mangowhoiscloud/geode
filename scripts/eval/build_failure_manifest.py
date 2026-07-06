#!/usr/bin/env python3
"""Build the Crucible failure manifest for subscription-only gating.

The manifest is the zero-cost input to G1 trace replay. It extracts the clean
retail/telecom failures that motivated R1/T1, records the expected and actual
write surface, and adds matched pass controls from the same baseline result
files. It does not call any model or tau2 runner.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIMS_DIR = REPO_ROOT / "artifacts/eval/harnesses/tau2-bench/data/simulations"
DEFAULT_RETAIL_RESULTS = (
    DEFAULT_SIMS_DIR / "geode-gpt-5-2-high-native-user-retail-base-20260703/results.json"
)
DEFAULT_TELECOM_RESULTS = (
    DEFAULT_SIMS_DIR / "geode-gpt-5-2-high-native-user-telecom-base-20260703/results.json"
)
DEFAULT_RETAIL_FAILURES = REPO_ROOT / "tmp/tau2_failed_retail.txt"
DEFAULT_TELECOM_FAILURES = REPO_ROOT / "tmp/tau2_failed_telecom.txt"
DEFAULT_OUTPUT = REPO_ROOT / "tmp/crucible_failure_manifest.json"

WRITE_PREFIXES = (
    "cancel_",
    "change_",
    "enable_",
    "exchange_",
    "grant_",
    "modify_",
    "refuel_",
    "reset_",
    "return_",
    "toggle_",
    "transfer_",
    "update_",
)


@dataclass(frozen=True)
class ActionRecord:
    requestor: str
    name: str
    arguments: dict[str, Any]
    action_id: str = ""
    action_match: bool | None = None
    tool_type: str = ""


def _read_failure_ids(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def _load_results(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    data = json.loads(path.read_text())
    return data, {str(sim["task_id"]): sim for sim in data.get("simulations", [])}


def _task_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(task["id"]): task for task in data.get("tasks", [])}


def _expected_actions(sim: dict[str, Any]) -> list[ActionRecord]:
    out: list[ActionRecord] = []
    for check in (sim.get("reward_info") or {}).get("action_checks") or []:
        action = check.get("action") or {}
        out.append(
            ActionRecord(
                requestor=str(action.get("requestor") or ""),
                name=str(action.get("name") or ""),
                arguments=dict(action.get("arguments") or {}),
                action_id=str(action.get("action_id") or ""),
                action_match=bool(check.get("action_match")),
                tool_type=str(check.get("tool_type") or ""),
            )
        )
    return out


def _actual_calls(sim: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in sim.get("messages") or []:
        turn_idx = message.get("turn_idx")
        for call in message.get("tool_calls") or []:
            out.append(
                {
                    "turn_idx": turn_idx,
                    "requestor": call.get("requestor") or "",
                    "name": call.get("name") or "",
                    "arguments": call.get("arguments") or {},
                }
            )
    return out


def _is_write_like(call: dict[str, Any], expected_write_names: set[str]) -> bool:
    name = str(call.get("name") or "")
    return (
        str(call.get("requestor") or "") == "user"
        or name in expected_write_names
        or name.startswith(WRITE_PREFIXES)
    )


def _write_like_calls(sim: dict[str, Any], expected_write_names: set[str]) -> list[dict[str, Any]]:
    return [call for call in _actual_calls(sim) if _is_write_like(call, expected_write_names)]


def _arg_diff(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(expected) | set(actual))
    different = [key for key in keys if expected.get(key) != actual.get(key)]
    missing = [key for key in expected if key not in actual]
    extra = [key for key in actual if key not in expected]
    return {
        "different_keys": different,
        "missing_keys": missing,
        "extra_keys": extra,
        "expected": expected,
        "actual": actual,
    }


def _action_diffs(
    expected_writes: list[ActionRecord],
    actual: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in actual:
        by_name[str(call.get("name") or "")].append(call)

    for expected in expected_writes:
        candidates = by_name.get(expected.name, [])
        actual_args = dict(candidates[0].get("arguments") or {}) if candidates else {}
        diff = _arg_diff(expected.arguments, actual_args)
        if not candidates or diff["different_keys"]:
            diffs.append(
                {
                    "action_id": expected.action_id,
                    "name": expected.name,
                    "requestor": expected.requestor,
                    "matched_call_present": bool(candidates),
                    **diff,
                }
            )
    return diffs


def _unmet_env(sim: dict[str, Any]) -> list[dict[str, Any]]:
    unmet: list[dict[str, Any]] = []
    for item in (sim.get("reward_info") or {}).get("env_assertions") or []:
        if item.get("met") is True:
            continue
        assertion = item.get("env_assertion") or {}
        unmet.append(
            {
                "func_name": assertion.get("func_name"),
                "arguments": assertion.get("arguments") or {},
                "message": assertion.get("message"),
            }
        )
    return unmet


def _retail_cluster(expected_writes: list[ActionRecord], sim: dict[str, Any]) -> str:
    names = {action.name for action in expected_writes}
    failed = [action for action in expected_writes if action.action_match is False]
    reward_info = sim.get("reward_info") or {}
    db_reward = (reward_info.get("db_check") or {}).get("db_reward")
    if any("address" in name for name in names):
        return "address_mutation_completeness"
    if "return_delivered_order_items" in names:
        return "return_delivered_item_selection_refund"
    if "exchange_delivered_order_items" in names:
        return "exchange_delivered_item_selection"
    if "modify_pending_order_items" in names:
        return "pending_item_modification_variant_choice"
    if any(name.startswith("cancel_") for name in names):
        return "cancel_pending_order_subset"
    if not failed and db_reward == 0:
        return "db_mismatch_without_action_check_failure"
    if sim.get("termination_reason") != "user_stop":
        return "tool_schema_runtime_error"
    return "retail_other"


def _telecom_cluster(task_id: str) -> str:
    if task_id.startswith("[mms_issue]"):
        return "mms_workflow_completion"
    if task_id.startswith("[mobile_data_issue]"):
        return "mobile_data_terminal_verifier"
    if task_id.startswith("[service_issue]"):
        return "service_terminal_verifier"
    return "telecom_other"


def _intervention_turn(write_like: list[dict[str, Any]]) -> int | None:
    turns = [turn for call in write_like if isinstance((turn := call.get("turn_idx")), int)]
    return min(turns) if turns else None


def _scenario(task: dict[str, Any] | None) -> dict[str, str]:
    instructions = ((task or {}).get("user_scenario") or {}).get("instructions") or {}
    return {
        "reason_for_call": str(instructions.get("reason_for_call") or ""),
        "known_info": str(instructions.get("known_info") or ""),
        "task_instructions": str(instructions.get("task_instructions") or ""),
    }


def _row(
    *,
    domain: str,
    task_id: str,
    sim: dict[str, Any],
    task: dict[str, Any] | None,
    failure: bool,
) -> dict[str, Any]:
    expected = _expected_actions(sim)
    expected_writes = [action for action in expected if action.tool_type == "write"]
    expected_write_names = {action.name for action in expected_writes}
    actual_write_like = _write_like_calls(sim, expected_write_names)
    reward_info = sim.get("reward_info") or {}
    reward = float(reward_info.get("reward") or 0.0)
    treatment = "R1" if domain == "retail" else "T1"
    cluster = (
        _retail_cluster(expected_writes, sim) if domain == "retail" else _telecom_cluster(task_id)
    )

    return {
        "domain": domain,
        "task_id": task_id,
        "is_failure": failure,
        "reward": reward,
        "termination_reason": sim.get("termination_reason"),
        "cluster": cluster,
        "candidate_guard": treatment,
        "scenario": _scenario(task),
        "expected_writes": [action.__dict__ for action in expected_writes],
        "failed_expected_writes": [
            action.__dict__ for action in expected_writes if action.action_match is False
        ],
        "actual_write_like_calls": actual_write_like,
        "argument_diffs": _action_diffs(expected_writes, actual_write_like),
        "unmet_env_assertions": _unmet_env(sim),
        "intervention_turn": _intervention_turn(actual_write_like),
        "false_positive_risk": _false_positive_risk(domain, cluster, failure),
    }


def _false_positive_risk(domain: str, cluster: str, failure: bool) -> str:
    if not failure:
        return "control: guard must not add extra write confirmation on already-passing trace"
    if domain == "retail":
        if cluster == "db_mismatch_without_action_check_failure":
            return (
                "medium: commit plan may not detect DB-only mismatch without explicit postcondition"
            )
        return "low-medium: guard targets mutating argument selection before write"
    if cluster == "mms_workflow_completion":
        return "medium: terminal verifier may over-continue if policy requires transfer"
    return "low-medium: guard targets issue-specific terminal condition"


def _matched_controls(
    domain: str,
    sims: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for task_id, sim in sims.items():
        reward = float((sim.get("reward_info") or {}).get("reward") or 0.0)
        if reward < 1.0 or sim.get("termination_reason") != "user_stop":
            continue
        controls.append(
            _row(
                domain=domain,
                task_id=task_id,
                sim=sim,
                task=tasks.get(task_id),
                failure=False,
            )
        )
    return controls


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    retail_data, retail_sims = _load_results(args.retail_results)
    telecom_data, telecom_sims = _load_results(args.telecom_results)
    retail_tasks = _task_index(retail_data)
    telecom_tasks = _task_index(telecom_data)
    retail_failures = _read_failure_ids(args.retail_failures)
    telecom_failures = _read_failure_ids(args.telecom_failures)

    rows: list[dict[str, Any]] = []
    for task_id in sorted(retail_failures, key=lambda item: int(item) if item.isdigit() else item):
        rows.append(
            _row(
                domain="retail",
                task_id=task_id,
                sim=retail_sims[task_id],
                task=retail_tasks.get(task_id),
                failure=True,
            )
        )
    for task_id in sorted(telecom_failures):
        rows.append(
            _row(
                domain="telecom",
                task_id=task_id,
                sim=telecom_sims[task_id],
                task=telecom_tasks.get(task_id),
                failure=True,
            )
        )

    controls = _matched_controls("retail", retail_sims, retail_tasks) + _matched_controls(
        "telecom", telecom_sims, telecom_tasks
    )
    cluster_counts = Counter(row["cluster"] for row in rows)
    guard_counts = Counter(row["candidate_guard"] for row in rows)

    return {
        "metadata": {
            "schema": "crucible_failure_manifest.v1",
            "purpose": "G1 trace replay input for subscription-only R1/T1 screening",
            "retail_results": str(args.retail_results),
            "telecom_results": str(args.telecom_results),
            "retail_failure_ids": str(args.retail_failures),
            "telecom_failure_ids": str(args.telecom_failures),
            "failure_count": len(rows),
            "control_count": len(controls),
            "cluster_counts": dict(sorted(cluster_counts.items())),
            "candidate_guard_counts": dict(sorted(guard_counts.items())),
        },
        "failures": rows,
        "controls": controls,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retail-results", type=Path, default=DEFAULT_RETAIL_RESULTS)
    parser.add_argument("--telecom-results", type=Path, default=DEFAULT_TELECOM_RESULTS)
    parser.add_argument("--retail-failures", type=Path, default=DEFAULT_RETAIL_FAILURES)
    parser.add_argument("--telecom-failures", type=Path, default=DEFAULT_TELECOM_FAILURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    meta = manifest["metadata"]
    print(
        f"wrote {args.output} | failures={meta['failure_count']} "
        f"controls={meta['control_count']} clusters={meta['cluster_counts']}"
    )


if __name__ == "__main__":
    main()
