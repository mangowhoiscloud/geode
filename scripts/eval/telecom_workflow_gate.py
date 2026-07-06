#!/usr/bin/env python3
"""Reject-only telecom workflow gate for Crucible tau2 trajectories.

This is a deterministic, zero-live-call G2 surrogate. It reads tau2
``results.json`` files and checks whether a telecom MMS/no-service trajectory
resolves blockers in a coherent order before spending more subscription quota.
It cannot promote a candidate; it only rejects trajectories that are already
known to be too slow, contaminated, or workflow-invalid.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "tmp/crucible_telecom_workflow_gate.json"


@dataclass
class WorkflowState:
    airplane_off: bool = False
    sim_active: bool = False
    mobile_data_on: bool = False
    non_2g_network: bool = False
    apn_valid: bool = False
    mms_verified: bool = False
    mms_failed_after_blockers: bool = False
    first_seen: dict[str, int] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    tool_counts: dict[str, int] = field(default_factory=dict)
    multi_tool_user_turns: int = 0
    first_manual_checklist_index: int | None = None
    first_tool_call_index: int | None = None

    def mark(self, checkpoint: str, message_index: int) -> None:
        self.first_seen.setdefault(checkpoint, message_index)

    def blockers_clear(self) -> bool:
        return (
            self.airplane_off
            and self.sim_active
            and self.mobile_data_on
            and self.non_2g_network
            and self.apn_valid
        )


@dataclass(frozen=True)
class GateConfig:
    max_messages: int = 34
    max_user_tool_turns: int = 8
    max_tool_calls: int = 18
    require_action_before_manual_checklist: bool = True


def _text(value: Any) -> str:
    return str(value or "").lower()


def _calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        message_calls = message.get("tool_calls") or []
        for call in message_calls:
            record = {
                "message_index": index,
                "role": message.get("role"),
                "name": str(call.get("name") or ""),
                "arguments": call.get("arguments") or {},
                "output": "",
            }
            pending.append(record)
            out.append(record)
        if message.get("role") == "tool" and pending:
            pending.pop(0)["output"] = str(message.get("content") or "")
    return out


def _looks_like_manual_checklist(content: str) -> bool:
    text = _text(content)
    if not text:
        return False
    manual_markers = (
        "check your phone",
        "phone settings",
        "open your phone",
        "quick settings",
        "control center",
        "go to your cellular",
        "go to your mobile",
        "please check",
        "tell me whether",
        "try sending",
        "try to send",
        "restart the phone",
        "reboot the phone",
    )
    blocker_markers = (
        "airplane",
        "mobile data",
        "cellular",
        "sim",
        "network mode",
        "apn",
        "mms",
        "picture message",
    )
    return any(marker in text for marker in manual_markers) and any(
        marker in text for marker in blocker_markers
    )


def _update_state_from_output(state: WorkflowState, call: dict[str, Any]) -> None:
    name = str(call.get("name") or "")
    output = _text(call.get("output"))
    idx = int(call.get("message_index") or 0)
    if not output:
        return

    if name in {"toggle_airplane_mode", "check_network_status"}:
        if "airplane mode: off" in output or "airplane mode is now off" in output:
            state.airplane_off = True
            state.mark("airplane_off", idx)
        if "airplane mode: on" in output:
            state.airplane_off = False

    if name in {"reseat_sim_card", "check_sim_status", "check_network_status"}:
        if (
            "sim card status: active" in output
            or "sim card is active" in output
            or "sim card re-seated successfully" in output
        ):
            state.sim_active = True
            state.mark("sim_active", idx)
        if "sim card status: missing" in output or "no sim card detected" in output:
            state.sim_active = False

    if name in {"toggle_data", "check_network_status"}:
        if (
            "mobile data enabled: yes" in output
            or "mobile data is now on" in output
            or "📱 data enabled" in output
            or "| data enabled" in output
        ):
            state.mobile_data_on = True
            state.mark("mobile_data_on", idx)
        if "mobile data enabled: no" in output or "data disabled" in output:
            state.mobile_data_on = False

    if name in {"set_network_mode_preference", "check_network_status"}:
        non_2g_markers = (
            "network type: 3g",
            "network type: 4g",
            "network type: 5g",
            "| 5g |",
            "| 4g |",
            "| 3g |",
        )
        if any(marker in output for marker in non_2g_markers):
            state.non_2g_network = True
            state.mark("non_2g_network", idx)
        if "network type: 2g" in output or "| 2g |" in output:
            state.non_2g_network = False

    if name in {"check_apn_settings", "reset_apn_settings"}:
        if "mmsc url" in output and "not set" not in output:
            state.apn_valid = True
            state.mark("apn_valid", idx)
        if "mmsc url" in output and "not set" in output:
            state.apn_valid = False

    if name == "can_send_mms":
        if not state.blockers_clear():
            state.violations.append("premature_can_send_mms")
        if "cannot send mms" in output:
            if state.blockers_clear():
                state.mms_failed_after_blockers = True
            state.mms_verified = False
        elif "can send mms" in output:
            state.mms_verified = True
            state.mark("mms_verified", idx)


def _evaluate_simulation(
    sim: dict[str, Any],
    *,
    source: Path,
    config: GateConfig,
) -> dict[str, Any]:
    termination = str(sim.get("termination_reason") or "")
    messages = list(sim.get("messages") or [])
    state = WorkflowState()
    state.multi_tool_user_turns = sum(
        1
        for message in messages
        if message.get("role") == "user" and len(message.get("tool_calls") or []) > 1
    )
    for index, message in enumerate(messages):
        if message.get("tool_calls") and state.first_tool_call_index is None:
            state.first_tool_call_index = index
        if (
            message.get("role") == "assistant"
            and state.first_manual_checklist_index is None
            and _looks_like_manual_checklist(str(message.get("content") or ""))
        ):
            state.first_manual_checklist_index = index
    calls = _calls(messages)
    for call in calls:
        name = str(call.get("name") or "")
        state.tool_counts[name] = state.tool_counts.get(name, 0) + 1
        _update_state_from_output(state, call)

    reasons: list[str] = []
    if termination == "infrastructure_error":
        verdict = "INVALID_INFRA"
        reasons.append("infrastructure_error")
    else:
        verdict = "PASS_SURROGATE"
        if state.violations:
            reasons.extend(state.violations)
        if termination == "max_steps":
            reasons.append("max_steps")
        if len(messages) > config.max_messages:
            reasons.append(f"message_budget_exceeded:{len(messages)}>{config.max_messages}")
        if state.multi_tool_user_turns > config.max_user_tool_turns:
            reasons.append(
                "user_tool_turn_budget_exceeded:"
                f"{state.multi_tool_user_turns}>{config.max_user_tool_turns}"
            )
        if len(calls) > config.max_tool_calls:
            reasons.append(f"tool_call_budget_exceeded:{len(calls)}>{config.max_tool_calls}")
        if (
            config.require_action_before_manual_checklist
            and state.first_manual_checklist_index is not None
            and (
                state.first_tool_call_index is None
                or state.first_tool_call_index > state.first_manual_checklist_index
            )
        ):
            reasons.append("missing_action_before_manual_checklist")
        if state.mms_failed_after_blockers and not state.mms_verified:
            reasons.append("mms_failed_after_blockers_clear")
        if not state.mms_verified:
            reasons.append("missing_terminal_can_send_mms_true")
        if reasons:
            verdict = "REJECT_SURROGATE"

    return {
        "source": str(source),
        "task_id": sim.get("task_id"),
        "termination_reason": termination,
        "message_count": len(messages),
        "tool_call_count": len(calls),
        "multi_tool_user_turns": state.multi_tool_user_turns,
        "tool_counts": dict(sorted(state.tool_counts.items())),
        "checkpoints": {
            "airplane_off": state.airplane_off,
            "sim_active": state.sim_active,
            "mobile_data_on": state.mobile_data_on,
            "non_2g_network": state.non_2g_network,
            "apn_valid": state.apn_valid,
            "mms_verified": state.mms_verified,
            "first_seen": state.first_seen,
            "first_tool_call_index": state.first_tool_call_index,
            "first_manual_checklist_index": state.first_manual_checklist_index,
        },
        "verdict": verdict,
        "reasons": reasons,
    }


def evaluate_results(path: Path, *, config: GateConfig) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    return [
        _evaluate_simulation(sim, source=path, config=config) for sim in data.get("simulations", [])
    ]


def run(paths: list[Path], *, config: GateConfig) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(evaluate_results(path, config=config))
    return {
        "metadata": {
            "schema": "crucible_telecom_workflow_gate.v1",
            "purpose": "reject-only deterministic telecom G2 surrogate",
            "config": {
                "max_messages": config.max_messages,
                "max_user_tool_turns": config.max_user_tool_turns,
                "max_tool_calls": config.max_tool_calls,
                "require_action_before_manual_checklist": (
                    config.require_action_before_manual_checklist
                ),
            },
        },
        "results": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-messages", type=int, default=34)
    parser.add_argument("--max-user-tool-turns", type=int, default=8)
    parser.add_argument("--max-tool-calls", type=int, default=18)
    parser.add_argument(
        "--allow-manual-checklist-before-action",
        action="store_true",
        help=(
            "Disable the action-before-talk reject rule. Debug only: telecom cheaploop "
            "evidence should normally require at least one projected environment action "
            "before manual phone checklist loops."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = GateConfig(
        max_messages=args.max_messages,
        max_user_tool_turns=args.max_user_tool_turns,
        max_tool_calls=args.max_tool_calls,
        require_action_before_manual_checklist=not args.allow_manual_checklist_before_action,
    )
    result = run(args.results, config=config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for row in result["results"]:
        print(
            f"{row['verdict']} {row['task_id']} "
            f"messages={row['message_count']} calls={row['tool_call_count']} "
            f"reasons={','.join(row['reasons']) or '-'}"
        )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
