#!/usr/bin/env python3
"""Deterministic telecom action-planner scaffold for Crucible.

This is not wired into GEODE runtime yet. It is the zero-live candidate surface
that should pass ``telecom_workflow_gate.py`` before any more tau2 spend. The
planner turns observed telecom blocker state into a bounded safe action bundle
and delays terminal ``can_send_mms`` verification until blockers are cleared.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "tmp/crucible_telecom_action_plan.json"


@dataclass(frozen=True)
class PlannedAction:
    name: str
    arguments: dict[str, Any]

    def to_tau2_call(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments, "requestor": "user"}


@dataclass(frozen=True)
class MmsState:
    airplane_mode_on: bool | None
    sim_active: bool | None
    mobile_data_on: bool | None
    network_type: str | None
    apn_mmsc_configured: bool | None
    can_send_mms: bool | None = None

    def blockers_clear(self) -> bool:
        return (
            self.airplane_mode_on is False
            and self.sim_active is True
            and self.mobile_data_on is True
            and _is_non_2g(self.network_type)
            and self.apn_mmsc_configured is True
        )


def _is_non_2g(network_type: str | None) -> bool:
    return str(network_type or "").strip().lower() in {"3g", "4g", "5g", "lte"}


def plan_mms_actions(state: MmsState) -> list[PlannedAction]:
    """Return the next bounded action bundle for an MMS troubleshooting state.

    The bundle is reject-safe: it never includes ``can_send_mms`` until all
    objective blockers are known clear.
    """
    if state.blockers_clear():
        if state.can_send_mms is not True:
            return [PlannedAction("can_send_mms", {})]
        return []

    actions: list[PlannedAction] = []
    if state.airplane_mode_on is True:
        actions.append(PlannedAction("toggle_airplane_mode", {}))
    if state.sim_active is False:
        actions.append(PlannedAction("reseat_sim_card", {}))
    if state.mobile_data_on is False:
        actions.append(PlannedAction("toggle_data", {}))
    if state.network_type is not None and not _is_non_2g(state.network_type):
        actions.append(PlannedAction("set_network_mode_preference", {"mode": "4g_5g_preferred"}))
    if state.apn_mmsc_configured is False:
        actions.extend(
            [
                PlannedAction("reset_apn_settings", {}),
                PlannedAction("reboot_device", {}),
                PlannedAction("check_apn_settings", {}),
            ]
        )
    if actions:
        return actions
    return [
        PlannedAction("check_network_status", {}),
        PlannedAction("check_sim_status", {}),
        PlannedAction("check_network_mode_preference", {}),
        PlannedAction("check_apn_settings", {}),
    ]


def demo_mms_success_results() -> dict[str, Any]:
    """Build a synthetic tau2-like success trajectory for the current MMS cluster."""
    initial = MmsState(
        airplane_mode_on=True,
        sim_active=False,
        mobile_data_on=False,
        network_type="2G",
        apn_mmsc_configured=False,
    )
    blocker_actions = plan_mms_actions(initial)
    verify_actions = plan_mms_actions(
        MmsState(
            airplane_mode_on=False,
            sim_active=True,
            mobile_data_on=True,
            network_type="5G",
            apn_mmsc_configured=True,
            can_send_mms=False,
        )
    )
    messages = [
        {"role": "assistant", "content": "Hi! How can I help you today?", "tool_calls": None},
        {"role": "user", "content": "MMS is not working.", "tool_calls": None},
        {
            "role": "assistant",
            "content": "I found multiple blockers. Please apply the bundled fixes.",
            "tool_calls": None,
        },
        {
            "role": "user",
            "content": "",
            "tool_calls": [action.to_tau2_call() for action in blocker_actions],
        },
        {"role": "tool", "content": "Airplane Mode is now OFF.", "tool_calls": None},
        {"role": "tool", "content": "SIM card re-seated successfully.", "tool_calls": None},
        {"role": "tool", "content": "Mobile Data is now ON.", "tool_calls": None},
        {
            "role": "tool",
            "content": "Preferred Network Mode set to: 4g_5g_preferred | 5G | Data Enabled",
            "tool_calls": None,
        },
        {
            "role": "tool",
            "content": "APN settings will reset at reboot.",
            "tool_calls": None,
        },
        {
            "role": "tool",
            "content": ("Resetting APN settings...\nRestarting network services..."),
            "tool_calls": None,
        },
        {
            "role": "tool",
            "content": ("Current APN Name: internet\nMMSC URL: http://mms.carrier.com/mms/wapenc"),
            "tool_calls": None,
        },
        {
            "role": "assistant",
            "content": "Now verify MMS send status.",
            "tool_calls": None,
        },
        {
            "role": "user",
            "content": "",
            "tool_calls": [action.to_tau2_call() for action in verify_actions],
        },
        {
            "role": "tool",
            "content": "Your messaging app can send MMS messages.",
            "tool_calls": None,
        },
    ]
    return {
        "simulations": [
            {
                "task_id": "[mms_issue]synthetic_planner_success",
                "termination_reason": "user_stop",
                "messages": messages,
            }
        ]
    }


def run_demo(output: Path) -> dict[str, Any]:
    state = MmsState(
        airplane_mode_on=True,
        sim_active=False,
        mobile_data_on=False,
        network_type="2G",
        apn_mmsc_configured=False,
    )
    actions = plan_mms_actions(state)
    payload = {
        "metadata": {
            "schema": "crucible_telecom_action_plan.v1",
            "purpose": "zero-live deterministic planner scaffold",
        },
        "input_state": asdict(state),
        "planned_actions": [asdict(action) for action in actions],
        "synthetic_success_results": demo_mms_success_results(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run_demo(args.output)
    actions = ", ".join(action["name"] for action in payload["planned_actions"])
    print(f"planned_actions={actions}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
