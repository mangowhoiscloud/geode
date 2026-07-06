"""Stateful workflow-order scaffolds for tau2 Crucible probes.

These helpers are benchmark harness scaffolds, not promotion authority. They
translate observed tau2 tool outputs into short dynamic context so GEODE's main
AgenticLoop can preserve domain workflow order during cheap probes.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").lower()


def _loads_json(value: Any) -> Any:
    """Best-effort JSON parse for tau2 tool output strings."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _string_or_none(value: Any) -> str | None:
    """Return a non-empty string value or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _infer_tool_name_from_output(output: Any) -> str:
    """Infer a tau2 telecom tool name when only the result message is visible."""
    content = _text(output)
    parsed = _loads_json(output)
    if isinstance(parsed, dict):
        if "customer_id" in parsed and "phone_number" in parsed:
            return "get_customer_by_phone"
        if "line_id" in parsed and "roaming_enabled" in parsed:
            return "get_details_by_id"
    if "your messaging app cannot send mms" in content or "can send mms" in content:
        return "can_send_mms"
    if "airplane mode:" in content and "sim card status:" in content:
        return "check_network_status"
    if "airplane mode is now" in content:
        return "toggle_airplane_mode"
    if "sim card re-seated successfully" in content:
        return "reseat_sim_card"
    if "no sim card detected" in content or "your sim card is active" in content:
        return "check_sim_status"
    if "mobile data is now" in content:
        return "toggle_data"
    if "preferred network mode set to" in content:
        return "set_network_mode_preference"
    if "network mode preference:" in content:
        return "check_network_mode_preference"
    if "current apn name:" in content and "mmsc url" in content:
        return "check_apn_settings"
    if "apn settings will reset at reboot" in content:
        return "reset_apn_settings"
    if "data roaming is now" in content:
        return "toggle_roaming"
    return ""


@dataclass
class TelecomMmsWorkflowOrder:
    """Track MMS blocker state and render a main-loop workflow-order hint."""

    step_economy: bool = False
    bounded_bundle: bool = False
    roaming_recovery: bool = False
    phased_recovery: bool = False
    airplane_off: bool | None = None
    sim_active: bool | None = None
    mobile_data_on: bool | None = None
    non_2g_network: bool | None = None
    apn_valid: bool | None = None
    account_roaming_enabled: bool | None = None
    device_roaming_on: bool | None = None
    active_customer_id: str | None = None
    active_phone_number: str | None = None
    active_line_id: str | None = None
    mms_verified: bool | None = None
    mms_failed_after_prereqs: bool = False
    pending_tool_names: deque[str] = field(default_factory=deque)

    def observe_outgoing_tool_calls(self, tool_calls: list[Any]) -> None:
        """Remember projected tool names so later tool messages can be parsed."""
        for call in tool_calls:
            name = str(getattr(call, "name", "") or "")
            if name:
                self.pending_tool_names.append(name)

    def observe_incoming_message(self, message: Any) -> None:
        """Consume tau2 tool-result messages and update blocker state."""
        tool_messages = getattr(message, "tool_messages", None) or []
        for tool_message in tool_messages:
            name = self.pending_tool_names.popleft() if self.pending_tool_names else ""
            self.observe_tool_output(name, getattr(tool_message, "content", ""))

    def observe_tool_output(self, name: str, output: Any) -> None:
        """Update state from one tau2 telecom tool output."""
        if not name:
            name = _infer_tool_name_from_output(output)
        content = _text(output)
        if not content:
            return
        parsed = _loads_json(output)

        if name == "get_customer_by_phone" and isinstance(parsed, dict):
            self.active_customer_id = _string_or_none(parsed.get("customer_id"))
            self.active_phone_number = _string_or_none(parsed.get("phone_number"))

        if name in {"toggle_airplane_mode", "check_network_status"}:
            if "airplane mode: off" in content or "airplane mode is now off" in content:
                self.airplane_off = True
            if "airplane mode: on" in content:
                self.airplane_off = False

        if name in {"reseat_sim_card", "check_sim_status", "check_network_status"}:
            if (
                "sim card status: active" in content
                or "sim card is active" in content
                or "sim card re-seated successfully" in content
            ):
                self.sim_active = True
            if "sim card status: missing" in content or "no sim card detected" in content:
                self.sim_active = False

        if name in {"toggle_data", "check_network_status"}:
            if (
                "mobile data enabled: yes" in content
                or "mobile data is now on" in content
                or "| data enabled" in content
            ):
                self.mobile_data_on = True
            if "mobile data enabled: no" in content or "data disabled" in content:
                self.mobile_data_on = False

        if name in {"toggle_roaming", "turn_roaming_on", "check_network_status"}:
            if "data roaming enabled: yes" in content or "data roaming is now on" in content:
                self.device_roaming_on = True
            if "data roaming enabled: no" in content or "data roaming is now off" in content:
                self.device_roaming_on = False

        if name in {"get_details_by_id", "enable_roaming"}:
            if name == "get_details_by_id" and isinstance(parsed, dict):
                line_phone = _string_or_none(parsed.get("phone_number"))
                if self.active_phone_number is None or line_phone == self.active_phone_number:
                    self.active_line_id = _string_or_none(parsed.get("line_id"))
                    roaming_enabled = parsed.get("roaming_enabled")
                    if isinstance(roaming_enabled, bool):
                        self.account_roaming_enabled = roaming_enabled
            if '"roaming_enabled": true' in content or "roaming enabled successfully" in content:
                self.account_roaming_enabled = True
            if '"roaming_enabled": false' in content or "roaming was already disabled" in content:
                self.account_roaming_enabled = False

        if name in {"set_network_mode_preference", "check_network_status"}:
            if any(
                marker in content
                for marker in (
                    "network type: 3g",
                    "network type: 4g",
                    "network type: 5g",
                    "| 3g |",
                    "| 4g |",
                    "| 5g |",
                )
            ):
                self.non_2g_network = True
            if "network type: 2g" in content or "| 2g |" in content:
                self.non_2g_network = False

        if name in {"check_apn_settings", "reset_apn_settings"}:
            if "mmsc url" in content and "not set" not in content:
                self.apn_valid = True
            if "mmsc url" in content and "not set" in content:
                self.apn_valid = False

        if name == "can_send_mms":
            if "cannot send mms" in content:
                self.mms_verified = False
                if self.blockers_clear():
                    self.mms_failed_after_prereqs = True
            elif "can send mms" in content:
                self.mms_verified = True

    def blockers_clear(self) -> bool:
        """Return True only when every MMS prerequisite is known clear."""
        return all(
            value is True
            for value in (
                self.airplane_off,
                self.sim_active,
                self.mobile_data_on,
                self.non_2g_network,
                self.apn_valid,
            )
        )

    def roaming_repair_due(self) -> bool:
        """Return True when account roaming is a known blocker before MMS verify."""
        return (
            self.roaming_recovery
            and self.blockers_clear()
            and self.account_roaming_enabled is False
            and self.mms_verified is not True
        )

    def premature_terminal_tool(self, tool_name: str) -> bool:
        """Return True when a terminal verifier is being used too early."""
        return tool_name == "can_send_mms" and not self.blockers_clear()

    def missing_blockers(self) -> list[str]:
        """Names of blockers that are not yet known clear."""
        blockers = {
            "airplane_mode_off": self.airplane_off,
            "sim_active": self.sim_active,
            "mobile_data_on": self.mobile_data_on,
            "network_mode_non_2g": self.non_2g_network,
            "apn_mmsc_configured": self.apn_valid,
        }
        return [name for name, value in blockers.items() if value is not True]

    def next_safe_actions(self) -> list[str]:
        """Ordered safe phone-side actions for known or likely MMS blockers."""
        actions: list[str] = []
        if self.airplane_off is not True:
            actions.append("toggle_airplane_mode")
        if self.sim_active is not True:
            actions.append("reseat_sim_card")
        if self.mobile_data_on is not True:
            actions.append("toggle_data")
        if self.non_2g_network is not True:
            actions.append('set_network_mode_preference(mode="4g_5g_preferred")')
        if self.apn_valid is not True:
            actions.extend(("reset_apn_settings", "check_apn_settings"))
        return actions

    def next_phase_hint(self) -> str:
        """Return the next small native-user phase for MMS recovery."""
        if self.airplane_off is not True or self.sim_active is not True:
            return (
                "Phase 1 signal/SIM: ask the user simulator for exactly this small "
                "phone-side phase, using tool names when possible: check_network_status; "
                "toggle_airplane_mode if airplane mode is ON; reseat_sim_card if the "
                "SIM is missing or inactive; then one concise status update. Do not ask "
                "for data, network mode, APN, roaming, or MMS verification in this phase."
            )
        if self.mobile_data_on is not True or self.non_2g_network is not True:
            return (
                "Phase 2 data/network: ask the user simulator for exactly this small "
                "phone-side phase: toggle_data if mobile data is OFF; "
                'set_network_mode_preference(mode="4g_5g_preferred") if the network '
                "is 2G or unknown; then one concise status update. Do not ask for APN, "
                "roaming, or MMS verification in this phase."
            )
        if self.apn_valid is not True:
            return (
                "Phase 3 APN/MMSC: ask the user simulator for exactly this small "
                "phone-side phase: reset_apn_settings; reboot_device; check_apn_settings; "
                "then one concise status update that states whether MMSC URL is set. "
                "Do not ask for roaming or MMS verification in this phase."
            )
        if self.roaming_repair_due() or self.mms_failed_after_prereqs:
            account_action = (
                f'enable_roaming(customer_id="{self.active_customer_id}", '
                f'line_id="{self.active_line_id}")'
                if self.active_customer_id and self.active_line_id
                else "enable_roaming with the observed active customer_id and line_id"
            )
            return (
                "Phase 5 roaming recovery: can_send_mms failed after basic blockers were "
                f"clear. First repair account roaming with {account_action} if the active "
                "line details show roaming_enabled=false. Then ask the user simulator for "
                "exactly one phone-side roaming action: turn_roaming_on or toggle_roaming "
                "if Data Roaming is OFF. After that, ask for exactly one separate "
                "can_send_mms terminal verification."
            )
        if self.mms_verified is None:
            return (
                "Phase 4 terminal verifier: basic MMS blockers are clear. Ask for exactly "
                "one separate can_send_mms check and no other phone action."
            )
        return "No phase action remains. Give a concise final answer."

    def branch_correction_prompt(self, assistant_text: str) -> str | None:
        """Return a retry prompt when the assistant skips required roaming repair."""
        if not self.roaming_recovery or not (
            self.roaming_repair_due() or self.mms_failed_after_prereqs
        ):
            return None
        if self.account_roaming_enabled is not False:
            return None
        text = _text(assistant_text)
        forbidden_branch = any(
            marker in text
            for marker in (
                "wi-fi calling",
                "wifi calling",
                "app permission",
                "app permissions",
                "messaging app permission",
                "escalat",
                "transfer",
                "broad diagnostic",
                "mms send check",
                "run the mms",
                "try sending an mms",
                "can_send_mms",
            )
        )
        if not forbidden_branch or "enable_roaming" in text:
            return None
        if self.active_customer_id and self.active_line_id:
            required = (
                f'enable_roaming(customer_id="{self.active_customer_id}", '
                f'line_id="{self.active_line_id}")'
            )
        else:
            required = "enable_roaming with the observed active customer_id and line_id"
        return (
            "Your previous draft violated Crucible telecom roaming recovery order. "
            "MMS failed after the basic blockers were clear, and the active line still has "
            "roaming_enabled=false. Do not ask about Wi-Fi calling, app permissions, "
            f"escalation, or broad diagnostics yet. Instead, call {required}. After account "
            "roaming is repaired, ask the user for one phone-side Data Roaming ON action, "
            "then ask for one separate can_send_mms verification."
        )

    def prompt_hint(self) -> str:
        """Render a compact English dynamic context block for the next turn."""
        missing = ", ".join(self.missing_blockers()) or "none"
        safe_actions = ", ".join(self.next_safe_actions()) or "none"
        state = (
            f"airplane_mode_off={self.airplane_off}; "
            f"sim_active={self.sim_active}; "
            f"mobile_data_on={self.mobile_data_on}; "
            f"network_mode_non_2g={self.non_2g_network}; "
            f"apn_mmsc_configured={self.apn_valid}; "
            f"account_roaming_enabled={self.account_roaming_enabled}; "
            f"device_roaming_on={self.device_roaming_on}; "
            f"active_customer_id={self.active_customer_id}; "
            f"active_line_id={self.active_line_id}; "
            f"mms_failed_after_prereqs={self.mms_failed_after_prereqs}; "
            f"mms_verified={self.mms_verified}"
        )
        base = (
            "Telecom MMS workflow-order scaffold v1.\n"
            f"Observed blocker state: {state}.\n"
            f"Missing blockers: {missing}.\n"
            "Treat can_send_mms as the terminal verifier, not the first diagnostic. "
            "Do not call can_send_mms, and do not ask the user to run can_send_mms, "
            "until airplane mode is off, SIM is active, mobile data is on, network "
            "mode is non-2G, and APN/MMSC is configured or explicitly ruled out.\n"
            "Use or ask for prerequisite actions first: check_network_status, "
            "toggle_airplane_mode, reseat_sim_card or check_sim_status, toggle_data, "
            "set_network_mode_preference, reset_apn_settings, and check_apn_settings."
        )
        if not self.step_economy:
            return base
        step_hint = (
            f"{base}\n"
            "Step-economy scaffold v1: after one diagnostic result reveals multiple "
            "safe phone-side blockers, do not clear them one conversational turn at "
            "a time. Ask the user simulator to perform the safe prerequisite actions "
            "as one ordered bundle when policy permits, then report the combined "
            "results. Recommended current bundle: "
            f"{safe_actions}. Keep can_send_mms out of the bundle until blockers are clear."
        )
        if self.phased_recovery:
            return (
                f"{step_hint}\n"
                "Native-user phased recovery protocol v1: do not ask for the whole "
                "MMS repair bundle at once. Ask for only the next phase below, then "
                "wait for one consolidated status update before advancing. "
                f"{self.next_phase_hint()}"
            )
        if not self.bounded_bundle:
            return step_hint
        if self.roaming_recovery and (self.roaming_repair_due() or self.mms_failed_after_prereqs):
            account_action = (
                f'enable_roaming(customer_id="{self.active_customer_id}", '
                f'line_id="{self.active_line_id}")'
                if self.active_customer_id and self.active_line_id
                else "enable_roaming with the observed active customer_id and line_id"
            )
            return (
                f"{step_hint}\n"
                "Roaming recovery protocol v1: active line roaming_enabled=false is a "
                "known blocker. Before terminal can_send_mms, Wi-Fi calling, app "
                "permissions, escalation, or repeated broad diagnostics, repair roaming. "
                f"Call {account_action}. After account roaming is repaired, ask the user "
                "simulator for one bounded phone-side action: turn Data Roaming ON using "
                "turn_roaming_on or toggle_roaming if needed. Then ask for one separate "
                "can_send_mms terminal verification."
            )
        if safe_actions == "none":
            bundle_instruction = (
                "No prerequisite bundle is currently needed. Ask for exactly one separate "
                "terminal can_send_mms verification only if blockers remain clear."
            )
        else:
            bundle_instruction = (
                "Ask for at most one prerequisite bundle before the terminal verifier. "
                f"The bundle allowlist is exactly: {safe_actions}. Exclude can_send_mms, "
                "roaming, Wi-Fi calling, app permissions, escalation, and repeated broad "
                "diagnostics unless a tool result explicitly introduces that branch. Ask "
                "for one consolidated status update covering each requested action. After "
                "that status update, ask for a separate can_send_mms terminal verification "
                "only if the tracked blockers are clear."
            )
        return f"{step_hint}\nBounded bundle protocol v1: {bundle_instruction}"


def build_workflow_order_scaffold(name: str) -> TelecomMmsWorkflowOrder | None:
    """Factory for runner CLI values."""
    if name == "none":
        return None
    if name == "telecom-mms-v1":
        return TelecomMmsWorkflowOrder()
    if name == "telecom-mms-step-economy-v1":
        return TelecomMmsWorkflowOrder(step_economy=True)
    if name == "telecom-mms-bounded-bundle-v1":
        return TelecomMmsWorkflowOrder(step_economy=True, bounded_bundle=True)
    if name == "telecom-mms-roaming-recovery-v1":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
        )
    if name == "telecom-mms-phased-recovery-v1":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            roaming_recovery=True,
            phased_recovery=True,
        )
    raise ValueError(f"unknown workflow-order scaffold: {name}")
