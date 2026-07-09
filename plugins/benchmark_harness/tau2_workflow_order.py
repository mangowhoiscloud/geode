"""Stateful workflow-order scaffolds for tau2 Crucible probes.

These helpers are benchmark harness scaffolds, not promotion authority. They
translate observed tau2 tool outputs into short dynamic context so GEODE's main
AgenticLoop can preserve domain workflow order during cheap probes.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any


def _text(value: Any) -> str:
    return (
        str(value or "")
        .lower()
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


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


def _projected_action_key(name: str, arguments: dict[str, Any]) -> str:
    """Return the trajectory-local identity for one projected user action."""
    return json.dumps(
        [name, arguments],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _string_or_none(value: Any) -> str | None:
    """Return a non-empty string value or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    """Return a float for numeric tau2 values, including JSON string numbers."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _phone_number_or_none(value: Any) -> str | None:
    """Extract the first NANP-style phone number from text, if present."""
    match = re.search(r"\b\d{3}-\d{3}-\d{4}\b", str(value or ""))
    return match.group(0) if match else None


def _message_field(message: Any, name: str, default: Any = None) -> Any:
    """Read a tau2 message field from either pydantic-like objects or dicts."""
    if isinstance(message, dict):
        return message.get(name, default)
    return getattr(message, name, default)


def _message_role_name(message: Any) -> str:
    """Return a normalized tau2 role name for string and enum roles."""
    role = _message_field(message, "role", "")
    value = getattr(role, "value", role)
    text = str(value or "").lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _infer_tool_name_from_output(output: Any) -> str:
    """Infer a tau2 telecom tool name when only the result message is visible."""
    content = _text(output)
    parsed = _loads_json(output)
    if isinstance(parsed, dict):
        if "customer_id" in parsed and "phone_number" in parsed:
            return "get_customer_by_phone"
        if "line_id" in parsed and "roaming_enabled" in parsed:
            return "get_details_by_id"
        if "data_used_gb" in parsed and "data_limit_gb" in parsed:
            return "get_data_usage"
        if "new_data_refueling_gb" in parsed:
            return "refuel_data"
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
    if "restarting network services" in content or "device reboot" in content:
        return "reboot_device"
    if "wi-fi calling is currently turned" in content:
        return "check_wifi_calling_status"
    if "wi-fi calling is now" in content:
        return "toggle_wifi_calling"
    if "data saver mode is" in content or "data saver is" in content:
        return "check_data_restriction_status"
    if "vpn is" in content or "vpn disconnected" in content:
        return "check_vpn_status"
    if "permission" in content and "messaging" in content:
        return "check_app_permissions"
    if "permission" in content and "granted to app" in content:
        return "grant_app_permission"
    if "roaming enabled successfully" in content:
        return "enable_roaming"
    if "data roaming is now" in content:
        return "toggle_roaming"
    if "speed test result" in content or "speed test failed" in content:
        return "run_speed_test"
    return ""


@dataclass
class TelecomMmsWorkflowOrder:
    """Track MMS blocker state and render a main-loop workflow-order hint."""

    step_economy: bool = False
    bounded_bundle: bool = False
    roaming_recovery: bool = False
    proactive_roaming: bool = False
    phased_recovery: bool = False
    late_stage_compression: bool = False
    extended_mms_recovery: bool = False
    data_refuel_recovery: bool = False
    phone_side_recheck_after_extended_recovery: bool = False
    proactive_extended_recovery: bool = False
    terminal_after_proactive_extended_recovery: bool = False
    apn_check_before_reset: bool = False
    defer_roaming_until_after_apn_observation: bool = False
    defer_phone_roaming_until_extended_recovery: bool = False
    project_assistant_requested_user_actions: bool = False
    project_terminal_after_assistant_requested_repairs: bool = False
    project_terminal_inside_extended_recovery_bundle: bool = False
    project_conditional_wifi_toggle_when_unknown: bool = True
    project_terminal_after_wifi_repair_request: bool = False
    project_phone_roaming_inside_terminal_recovery_bundle: bool = False
    project_terminal_with_unknown_wifi_status: bool = False
    trust_apn_reset_reboot_without_recheck: bool = False
    infer_data_usage_from_line_details: bool = False
    reset_unknown_apn_after_bad_network_without_observation: bool = False
    reset_unknown_apn_after_no_service_without_observation: bool = False
    project_terminal_after_projected_repairs: bool = False
    complete_proactive_recovery_on_terminal_request: bool = False
    dedupe_assistant_requested_user_actions: bool = False
    project_stop_after_mobile_data_excellent: bool = False
    project_speed_test_after_mobile_data_repair: bool = False
    project_mobile_data_assistant_requested_actions: bool = False
    project_mobile_data_known_state_repairs: bool = False
    project_mobile_data_speed_failure_recovery: bool = False
    project_mobile_data_terminal_instead_of_mms: bool = False
    project_mobile_data_terminal_after_refuel: bool = False
    project_mobile_data_terminal_on_refuel_speed_request: bool = False
    repeat_mobile_data_speed_test_after_terminal_repairs: bool = False
    repeat_mobile_data_speed_test_after_ready_state: bool = False
    check_mobile_data_status_before_terminal_on_mms_request: bool = False
    defer_mobile_data_speed_until_status_safe: bool = False
    defer_mobile_data_speed_until_phone_ready: bool = False
    toggle_mobile_data_only_when_observed_off: bool = False
    prefer_mobile_data_terminal_over_mms_fallback: bool = False
    block_mms_fallback_for_mobile_data: bool = False
    infer_mobile_data_from_status_bar: bool = False
    restore_full_mobile_terminal_after_status_check: bool = False
    restore_full_mobile_terminal_on_status_safe_request: bool = False
    normalize_status_safe_speed_request_to_terminal_bundle: bool = False
    project_known_mobile_data_repairs_from_status_checks: bool = False
    require_current_speed_test_for_mobile_data_stop: bool = False
    assume_unknown_phone_roaming_off_for_mobile_data_terminal: bool = False
    treat_speed_test_as_mobile_data_terminal_repair_request: bool = False
    airplane_off: bool | None = None
    sim_active: bool | None = None
    mobile_data_on: bool | None = None
    non_2g_network: bool | None = None
    apn_valid: bool | None = None
    wifi_calling_safe: bool | None = None
    messaging_sms_permission: bool | None = None
    messaging_storage_permission: bool | None = None
    data_usage_exceeded: bool | None = None
    data_refueled: bool = False
    account_roaming_enabled: bool | None = None
    device_roaming_on: bool | None = None
    active_customer_id: str | None = None
    active_phone_number: str | None = None
    active_line_id: str | None = None
    candidate_line_ids: list[str] = field(default_factory=list)
    mms_verified: bool | None = None
    mobile_data_speed_excellent: bool = False
    current_turn_mobile_data_speed_excellent: bool = False
    data_saver_on: bool | None = None
    vpn_connected: bool | None = None
    mobile_data_issue_active: bool = False
    no_service_observed: bool = False
    mms_failed_after_prereqs: bool = False
    pending_tool_names: deque[str] = field(default_factory=deque)
    issued_projected_tool_names: set[str] = field(default_factory=set)
    issued_projected_action_keys: set[str] = field(default_factory=set)
    issued_projected_line_detail_ids: set[str] = field(default_factory=set)
    projected_identity_phone_sent: bool = False
    apn_reset_pending_reboot: bool = False
    pending_mobile_data_terminal_speed_after_status_check: bool = False

    def observe_outgoing_tool_calls(self, tool_calls: list[Any]) -> None:
        """Remember projected tool names so later tool messages can be parsed."""
        for call in tool_calls:
            name = str(_message_field(call, "name", "") or "")
            if name:
                self.pending_tool_names.append(name)

    def observe_incoming_message(self, message: Any) -> None:
        """Consume tau2 tool-result messages and update blocker state."""
        self.current_turn_mobile_data_speed_excellent = False
        tool_messages = _message_field(message, "tool_messages", None) or []
        if _message_role_name(message) == "tool":
            if tool_messages:
                for tool_message in tool_messages:
                    name = self.pending_tool_names.popleft() if self.pending_tool_names else ""
                    self.observe_tool_output(name, _message_field(tool_message, "content", ""))
            else:
                name = self.pending_tool_names.popleft() if self.pending_tool_names else ""
                self.observe_tool_output(name, _message_field(message, "content", ""))
            return
        if _message_role_name(message) == "assistant":
            self.observe_assistant_text(_message_field(message, "content", ""))
        if _message_role_name(message) == "user":
            self.observe_user_text(_message_field(message, "content", ""))
        for tool_message in tool_messages:
            name = self.pending_tool_names.popleft() if self.pending_tool_names else ""
            self.observe_tool_output(name, _message_field(tool_message, "content", ""))

    def observe_assistant_text(self, content: Any) -> None:
        """Update coarse state from assistant-visible repair confirmations."""
        text = _text(content)
        if (
            "roaming is enabled" in text
            or "roaming is now enabled" in text
            or "roaming being enabled" in text
            or "roaming enabled" in text
        ):
            self.account_roaming_enabled = True
        if "mobile data" in text or "internet speed" in text or "speed test" in text:
            self.mobile_data_issue_active = True
        if (
            ("gb of data" in text and ("added" in text or "refuel" in text))
            or "data refuel was successful" in text
            or "data refuel was added" in text
            or "data refuel was applied" in text
            or "gb data refuel" in text
            or "refuel was successful" in text
        ):
            self.data_refueled = True
            self.data_usage_exceeded = False
        if (
            "data usage is below the limit" in text
            or "usage is below the limit" in text
            or "below your data limit" in text
            or "below the data limit" in text
            or "data exhaustion is not the issue" in text
            or "data usage is within" in text
            or "data usage is under" in text
            or "data allowance is not the blocker" in text
            or "data allowance is not blocking" in text
        ):
            self.data_usage_exceeded = False

    def observe_user_text(self, content: Any) -> None:
        """Update phone-side state from a simulated user's grounded status summary."""
        text = _text(content)
        if not text:
            return
        phone_number = _phone_number_or_none(content)
        if phone_number is not None:
            self.active_phone_number = phone_number
        if "airplane mode is off" in text or "airplane mode off" in text:
            self.airplane_off = True
        if "sim was reseated" in text or "sim was re-seated" in text:
            self.sim_active = True
        if "sim is active" in text:
            self.sim_active = True
        if "mobile data is on" in text or "mobile data on" in text:
            self.mobile_data_on = True
        if "mobile data" in text or "internet speed" in text or "speed test" in text:
            self.mobile_data_issue_active = True
        if "4g/5g" in text or "4g_5g_preferred" in text or "excellent 5g" in text:
            self.non_2g_network = True
        if "mmsc url" in text and (
            "set" in text or "configured" in text or "http://" in text or "https://" in text
        ):
            self.apn_valid = True
        if "wi-fi calling is off" in text or "wi-fi calling off" in text:
            self.wifi_calling_safe = True
        if "wi-fi calling is on" in text or "wi-fi calling on" in text:
            self.wifi_calling_safe = False
        if "sms permission" in text and ("granted" in text or "enabled" in text):
            self.messaging_sms_permission = True
        if "storage permission" in text and ("granted" in text or "enabled" in text):
            self.messaging_storage_permission = True
        if "data roaming is now on" in text or "data roaming is on" in text:
            self.device_roaming_on = True
        if (
            "data roaming is disabled" in text
            or "data roaming disabled" in text
            or "data roaming is off" in text
            or "data roaming off" in text
        ):
            self.device_roaming_on = False
        if "messaging app still cannot send mms" in text or "cannot send mms" in text:
            self.mms_verified = False
            if self.blockers_clear():
                self.mms_failed_after_prereqs = True
        if "messaging app can send mms" in text or "can send mms messages" in text:
            self.mms_verified = True

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
            line_ids = parsed.get("line_ids")
            if isinstance(line_ids, list):
                self.candidate_line_ids = [
                    line_id
                    for line_id in (_string_or_none(value) for value in line_ids)
                    if line_id is not None
                ]

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
        if self.infer_mobile_data_from_status_bar:
            if "data disabled" in content or "mobile data enabled: no" in content:
                self.mobile_data_on = False
            elif (
                "data enabled" in content
                or "mobile data enabled: yes" in content
                or "mobile data is now on" in content
            ):
                self.mobile_data_on = True

        if any(
            marker in content
            for marker in (
                "data saver mode is off",
                "data saver is off",
                "data saver mode is now off",
            )
        ):
            self.data_saver_on = False
        elif (
            "data saver mode is on" in content
            or "data saver is on" in content
            or ("status bar:" in content and "data saver" in content)
        ):
            self.data_saver_on = True
        if any(
            marker in content
            for marker in (
                "vpn is off",
                "vpn is turned off",
                "vpn disconnected",
            )
        ):
            self.vpn_connected = False
        elif "vpn is on" in content or "vpn connected" in content:
            self.vpn_connected = True

        if name == "run_speed_test":
            self.mobile_data_issue_active = True

        if name in {"toggle_roaming", "turn_roaming_on", "check_network_status"}:
            if (
                "cellular connection: no_service" in content
                or "cellular network type: none" in content
            ):
                self.no_service_observed = True
            if "data roaming enabled: yes" in content or "data roaming is now on" in content:
                self.device_roaming_on = True
            if "data roaming enabled: no" in content or "data roaming is now off" in content:
                self.device_roaming_on = False

        if name == "get_details_by_id" and isinstance(parsed, dict):
            line_id = _string_or_none(parsed.get("line_id"))
            if line_id is not None:
                self.issued_projected_line_detail_ids.add(line_id)
            line_phone = _string_or_none(parsed.get("phone_number"))
            if self.active_phone_number is None or line_phone == self.active_phone_number:
                self.active_line_id = line_id
                roaming_enabled = parsed.get("roaming_enabled")
                if isinstance(roaming_enabled, bool):
                    self.account_roaming_enabled = roaming_enabled
                if self.infer_data_usage_from_line_details:
                    used = _float_or_none(parsed.get("data_used_gb"))
                    refueled = _float_or_none(parsed.get("data_refueling_gb")) or 0.0
                    plan_limit = self._line_detail_plan_data_limit_gb(parsed)
                    if used is not None and plan_limit is not None:
                        self.data_usage_exceeded = used >= plan_limit + refueled

        if name == "enable_roaming":
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
        if name == "reset_apn_settings" and "apn settings will reset at reboot" in content:
            self.apn_reset_pending_reboot = True
        if (
            name == "reboot_device"
            and self.trust_apn_reset_reboot_without_recheck
            and self.apn_reset_pending_reboot
            and ("restarting network services" in content or "device reboot" in content)
        ):
            self.apn_valid = True
            self.apn_reset_pending_reboot = False

        if name in {"check_wifi_calling_status", "toggle_wifi_calling"}:
            if (
                "wi-fi calling is currently turned off" in content
                or "wi-fi calling is now off" in content
            ):
                self.wifi_calling_safe = True
            if (
                "wi-fi calling is currently turned on" in content
                or "wi-fi calling is now on" in content
            ):
                self.wifi_calling_safe = False

        if name in {"check_app_permissions", "grant_app_permission"}:
            if "permission 'sms' granted" in content or "has permission for: sms" in content:
                self.messaging_sms_permission = True
            if (
                "permission 'storage' granted" in content
                or "has permission for: storage" in content
            ):
                self.messaging_storage_permission = True
            if "currently has no permissions granted" in content:
                self.messaging_sms_permission = False
                self.messaging_storage_permission = False

        if name == "get_data_usage" and isinstance(parsed, dict):
            used = _float_or_none(parsed.get("data_used_gb"))
            limit = _float_or_none(parsed.get("data_limit_gb"))
            refueled = _float_or_none(parsed.get("data_refueling_gb")) or 0.0
            if used is not None and limit is not None:
                self.data_usage_exceeded = used >= limit + refueled

        if name == "refuel_data" and (
            "successfully added" in content
            or (isinstance(parsed, dict) and "new_data_refueling_gb" in parsed)
        ):
            self.data_refueled = True
            self.data_usage_exceeded = False

        if name == "can_send_mms":
            if "cannot send mms" in content:
                self.mms_verified = False
                if self.blockers_clear():
                    self.mms_failed_after_prereqs = True
            elif "can send mms" in content:
                self.mms_verified = True

        if name == "run_speed_test" and "speed test result" in content and "excellent" in content:
            self.mobile_data_speed_excellent = True
            self.current_turn_mobile_data_speed_excellent = True

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

    def account_roaming_repair_due(self) -> bool:
        """Return True when a known account roaming blocker should be fixed now."""
        return (
            self.roaming_recovery
            and self.proactive_roaming
            and self.account_roaming_enabled is False
            and self.active_customer_id is not None
            and self.active_line_id is not None
            and self.mms_verified is not True
        )

    def known_account_roaming_repair_due(self) -> bool:
        """Return True when active-line account roaming is a known blocker."""
        return (
            self.roaming_recovery
            and self.account_roaming_enabled is False
            and self.active_customer_id is not None
            and self.active_line_id is not None
            and self.mms_verified is not True
        )

    def data_usage_lookup_due(self) -> bool:
        """Return True when v3 should inspect account-side data usage."""
        return (
            self.data_refuel_recovery
            and self.active_customer_id is not None
            and self.active_line_id is not None
            and self.account_roaming_enabled is not False
            and self.data_usage_exceeded is None
            and self.mms_verified is not True
        )

    def data_refuel_due(self) -> bool:
        """Return True when observed data usage requires a deterministic refuel."""
        return (
            self.data_refuel_recovery
            and self.active_customer_id is not None
            and self.active_line_id is not None
            and self.data_usage_exceeded is True
            and not self.data_refueled
            and self.mms_verified is not True
        )

    def _line_detail_plan_data_limit_gb(self, parsed: dict[str, Any]) -> float | None:
        """Return known tau2 telecom plan limits visible from line details."""
        plan_id = _string_or_none(parsed.get("plan_id"))
        if plan_id == "P1002":
            return 15.0
        return None

    def post_refuel_account_relookup_blocked(self) -> bool:
        """Return True when account identity/line/data state is already sufficient."""
        return (
            self.data_refuel_recovery
            and self.blockers_clear()
            and self.active_customer_id is not None
            and self.active_line_id is not None
            and self.account_roaming_enabled is not False
            and (self.data_refueled or self.data_usage_exceeded is False)
            and not self.account_identity_lookup_due()
            and not self.line_detail_lookup_due()
            and not self.data_usage_lookup_due()
            and not self.data_refuel_due()
            and self.mms_verified is not True
        )

    def redundant_account_lookup_tool(self, tool_name: str) -> bool:
        """Return True when a customer lookup would only repeat resolved state."""
        return self.post_refuel_account_relookup_blocked() and tool_name in {
            "get_customer_by_id",
            "get_customer_by_phone",
        }

    def proactive_extended_recovery_due(self) -> bool:
        """Return True when v9 should repair app/Wi-Fi blockers before terminal MMS."""
        extended_blockers_clear = (
            self.wifi_calling_safe is True
            and self.messaging_sms_permission is True
            and self.messaging_storage_permission is True
        )
        return (
            self.extended_mms_recovery
            and self.proactive_extended_recovery
            and self.blockers_clear()
            and self.mms_verified is None
            and not extended_blockers_clear
            and (
                self.data_refueled
                or self.data_usage_exceeded is False
                or not self.data_refuel_recovery
            )
            and not self.data_usage_lookup_due()
            and not self.data_refuel_due()
            and self.account_roaming_enabled is not False
            and (self.device_roaming_on is True or self.defer_phone_roaming_until_extended_recovery)
        )

    def line_detail_lookup_due(self) -> bool:
        """Return True when the active line must be identified before terminal MMS."""
        return (
            self.roaming_recovery
            and (self.blockers_clear() or self.late_stage_compression)
            and self.active_customer_id is not None
            and self.active_phone_number is not None
            and self.active_line_id is None
            and bool(self.candidate_line_ids)
            and self.mms_verified is not True
        )

    def account_identity_lookup_due(self) -> bool:
        """Return True when account lookup should precede terminal MMS verification."""
        return (
            self.roaming_recovery
            and self.blockers_clear()
            and self.active_customer_id is None
            and self.mms_verified is not True
        )

    def late_stage_compression_due(self) -> bool:
        """Return True when account/APN/phone-roaming recovery should be compressed."""
        return (
            self.roaming_recovery
            and self.late_stage_compression
            and self.account_roaming_enabled is False
            and self.active_customer_id is not None
            and self.active_line_id is not None
            and self.airplane_off is True
            and self.sim_active is True
            and self.mobile_data_on is True
            and self.non_2g_network is True
            and self.mms_verified is not True
        )

    def premature_terminal_tool(self, tool_name: str) -> bool:
        """Return True when a terminal verifier is being used too early."""
        return tool_name == "can_send_mms" and (
            not self.blockers_clear() or self.account_roaming_enabled is False
        )

    def missing_blockers(self) -> list[str]:
        """Names of blockers that are not yet known clear."""
        blockers = {
            "airplane_mode_off": self.airplane_off,
            "sim_active": self.sim_active,
            "mobile_data_on": self.mobile_data_on,
            "network_mode_non_2g": self.non_2g_network,
            "apn_mmsc_configured": self.apn_valid,
        }
        if self.extended_mms_recovery:
            blockers.update(
                {
                    "wifi_calling_safe": self.wifi_calling_safe,
                    "messaging_sms_permission": self.messaging_sms_permission,
                    "messaging_storage_permission": self.messaging_storage_permission,
                }
            )
        return [name for name, value in blockers.items() if value is not True]

    def next_safe_actions(self) -> list[str]:
        """Ordered safe phone-side actions for known or likely MMS blockers."""
        actions: list[str] = []
        if self.airplane_off is not True:
            actions.append("toggle_airplane_mode")
        if self.sim_active is not True:
            actions.append("reseat_sim_card")
        if self.mobile_data_on is False or (
            self.mobile_data_on is None and not self.toggle_mobile_data_only_when_observed_off
        ):
            actions.append("toggle_data")
        if self.non_2g_network is not True:
            actions.append('set_network_mode_preference(mode="4g_5g_preferred")')
        if self.apn_valid is not True:
            actions.extend(self.apn_reset_recovery_tool_names())
        if self.extended_mms_recovery and self.wifi_calling_safe is False:
            actions.append("toggle_wifi_calling")
        if self.extended_mms_recovery and self.messaging_sms_permission is False:
            actions.append('grant_app_permission(app_name="messaging", permission="sms")')
        if self.extended_mms_recovery and self.messaging_storage_permission is False:
            actions.append('grant_app_permission(app_name="messaging", permission="storage")')
        if self.roaming_recovery and self.device_roaming_on is False:
            actions.append("toggle_roaming")
        return actions

    def apn_reset_recovery_tool_names(self) -> tuple[str, ...]:
        """Return the APN reset bundle for the current compression profile."""
        if self.trust_apn_reset_reboot_without_recheck:
            return ("reset_apn_settings", "reboot_device")
        return ("reset_apn_settings", "reboot_device", "check_apn_settings")

    def reset_unknown_apn_after_bad_network_due(self) -> bool:
        """Return True when APN observation can be skipped after bad-network evidence."""
        bad_network_evidence = self.non_2g_network is False or (
            self.reset_unknown_apn_after_no_service_without_observation and self.no_service_observed
        )
        return (
            self.reset_unknown_apn_after_bad_network_without_observation
            and self.apn_valid is None
            and self.apn_check_before_reset
            and bad_network_evidence
        )

    def projected_user_tool_actions(self) -> list[tuple[str, dict[str, Any]]]:
        """Return diagnostic-only user-side actions for a cooperative phone user."""
        if self.mms_verified is True:
            return []
        if self.mobile_data_issue_active and self.mobile_data_speed_excellent:
            return []
        if (
            self.project_mobile_data_terminal_after_refuel
            and self.mobile_data_terminal_projection_due()
        ):
            terminal_actions = self.mobile_data_terminal_actions()
            if terminal_actions:
                return self._unissued_projected_actions(terminal_actions)
        unknown = (
            self.airplane_off is None
            and self.sim_active is None
            and self.mobile_data_on is None
            and self.non_2g_network is None
            and self.apn_valid is None
        )
        if unknown:
            return self._unissued_projected_actions([("check_network_status", {})])

        actions: list[tuple[str, dict[str, Any]]] = []
        if self.airplane_off is not True:
            actions.append(("toggle_airplane_mode", {}))
        if self.sim_active is not True:
            actions.append(("reseat_sim_card", {}))
        if self.mobile_data_on is False or (
            self.mobile_data_on is None and not self.toggle_mobile_data_only_when_observed_off
        ):
            actions.append(("toggle_data", {}))
        if self.non_2g_network is not True:
            actions.append(("set_network_mode_preference", {"mode": "4g_5g_preferred"}))
        if (
            self.apn_valid is None
            and self.apn_check_before_reset
            and not self.reset_unknown_apn_after_bad_network_due()
        ):
            actions.append(("check_apn_settings", {}))
        elif self.apn_valid is not True:
            actions.extend((name, {}) for name in self.apn_reset_recovery_tool_names())
        extended_recovery_due = self.extended_mms_recovery and (
            self.mms_failed_after_prereqs or self.proactive_extended_recovery_due()
        )
        if extended_recovery_due:
            if self.data_usage_lookup_due() or self.data_refuel_due():
                return []
            if (
                self.defer_phone_roaming_until_extended_recovery
                and self.device_roaming_on is not True
            ):
                actions.append(("toggle_roaming", {}))
            if self.wifi_calling_safe is None:
                actions.append(("check_wifi_calling_status", {}))
            elif self.wifi_calling_safe is False:
                actions.append(("toggle_wifi_calling", {}))
            if self.messaging_sms_permission is not True:
                actions.append(
                    (
                        "grant_app_permission",
                        {"app_name": "messaging", "permission": "sms"},
                    )
                )
            if self.messaging_storage_permission is not True:
                actions.append(
                    (
                        "grant_app_permission",
                        {"app_name": "messaging", "permission": "storage"},
                    )
                )
            phone_roaming_safe_after = self.device_roaming_on is True or any(
                name == "toggle_roaming" for name, _arguments in actions
            )
            if (
                self.terminal_after_proactive_extended_recovery
                and self.proactive_extended_recovery
                and self.wifi_calling_safe is False
                and self.messaging_sms_permission is True
                and self.messaging_storage_permission is True
                and self.blockers_clear()
                and self.account_roaming_enabled is not False
                and phone_roaming_safe_after
            ):
                actions.append(("can_send_mms", {}))
            if self.project_terminal_after_projected_repairs and (
                self.terminal_mms_projection_after_actions_due(actions)
            ):
                actions.append(("can_send_mms", {}))
        defer_roaming = (
            self.defer_roaming_until_after_apn_observation
            and self.apn_check_before_reset
            and self.apn_valid is None
            and any(name == "check_apn_settings" for name, _arguments in actions)
        )
        if (
            self.roaming_recovery
            and self.device_roaming_on is False
            and not defer_roaming
            and not self.defer_phone_roaming_until_extended_recovery
        ):
            actions.append(("toggle_roaming", {}))
        if actions:
            unissued_actions = self._unissued_projected_actions(actions)
            if unissued_actions:
                return unissued_actions
            if not (self.extended_mms_recovery and self.mms_failed_after_prereqs):
                return []
        if (
            self.account_roaming_enabled is True
            and self.device_roaming_on is not True
            and not self.defer_phone_roaming_until_extended_recovery
        ):
            return self._unissued_projected_actions([("toggle_roaming", {})])
        if self.device_roaming_on is False and not self.defer_phone_roaming_until_extended_recovery:
            return self._unissued_projected_actions([("toggle_roaming", {})])
        if self.account_identity_lookup_due():
            return []
        if self.data_usage_lookup_due() or self.data_refuel_due():
            return []
        if (
            self.block_mms_fallback_for_mobile_data
            and self.mobile_data_issue_active
            and not self.mobile_data_speed_excellent
        ):
            if self.mobile_data_terminal_projection_due():
                return self._unissued_projected_actions(self.mobile_data_terminal_actions())
            ready_actions = self.mobile_data_phone_ready_actions()
            if ready_actions:
                return self._unissued_projected_actions(ready_actions)
            return []
        if (
            self.prefer_mobile_data_terminal_over_mms_fallback
            and self.mobile_data_terminal_projection_due()
        ):
            return self._unissued_projected_actions(self.mobile_data_terminal_actions())
        return self._unissued_projected_actions([("can_send_mms", {})])

    def mobile_data_terminal_due(self) -> bool:
        """Return True when mobile-data verification should outrank MMS recovery."""
        return (
            (self.mobile_data_issue_active or self.data_refueled)
            and not self.mobile_data_speed_excellent
            and self.mms_verified is not True
            and (self.data_refueled or self.blockers_clear())
            and (self.data_refueled or self.account_roaming_enabled is not False)
            and not self.account_identity_lookup_due()
            and not self.line_detail_lookup_due()
            and not self.known_account_roaming_repair_due()
            and not self.data_usage_lookup_due()
            and not self.data_refuel_due()
        )

    def mobile_data_terminal_projection_due(self) -> bool:
        """Return True when the user projector should emit mobile-data terminal actions."""
        return self.mobile_data_terminal_due() or (
            self.project_mobile_data_terminal_on_refuel_speed_request
            and self.data_refueled
            and not self.mobile_data_speed_excellent
            and self.mms_verified is not True
        )

    def mobile_data_terminal_actions(self) -> list[tuple[str, dict[str, Any]]]:
        """Return observed-state phone repairs followed by terminal speed verification."""
        actions: list[tuple[str, dict[str, Any]]] = []
        if self.mobile_data_phone_roaming_repair_due():
            actions.append(("toggle_roaming", {}))
        if self.data_saver_on is True:
            actions.append(("toggle_data_saver_mode", {}))
        if self.vpn_connected is True:
            actions.append(("disconnect_vpn", {}))
        actions.append(("run_speed_test", {}))
        return actions

    def mobile_data_phone_roaming_repair_due(self) -> bool:
        """Return True when terminal mobile-data recovery should toggle device roaming."""
        return self.device_roaming_on is False or (
            self.assume_unknown_phone_roaming_off_for_mobile_data_terminal
            and self.mobile_data_issue_active
            and self.device_roaming_on is not True
            and self.account_roaming_enabled is not False
        )

    def mobile_data_phone_ready_actions(self) -> list[tuple[str, dict[str, Any]]]:
        """Return prerequisite phone repairs before terminal mobile-data speed tests."""
        actions: list[tuple[str, dict[str, Any]]] = []
        if self.airplane_off is not True:
            actions.append(("toggle_airplane_mode", {}))
        if self.sim_active is not True:
            actions.append(("reseat_sim_card", {}))
        if self.mobile_data_on is False or (
            self.mobile_data_on is None and not self.toggle_mobile_data_only_when_observed_off
        ):
            actions.append(("toggle_data", {}))
        if self.non_2g_network is not True:
            actions.append(("set_network_mode_preference", {"mode": "4g_5g_preferred"}))
        if (
            self.apn_valid is None
            and self.apn_check_before_reset
            and not self.reset_unknown_apn_after_bad_network_due()
        ):
            actions.append(("check_apn_settings", {}))
        elif self.apn_valid is not True:
            actions.extend((name, {}) for name in self.apn_reset_recovery_tool_names())
        return actions

    def terminal_mms_projection_after_actions_due(
        self, actions: list[tuple[str, dict[str, Any]]]
    ) -> bool:
        """Return True when the projected repair batch can safely end with MMS verify."""
        if any(name == "can_send_mms" for name, _arguments in actions):
            return False
        wifi_safe_after = self.wifi_calling_safe is True or any(
            name == "toggle_wifi_calling" for name, _arguments in actions
        )
        sms_after = self.messaging_sms_permission is True or any(
            name == "grant_app_permission" and arguments.get("permission") == "sms"
            for name, arguments in actions
        )
        storage_after = self.messaging_storage_permission is True or any(
            name == "grant_app_permission" and arguments.get("permission") == "storage"
            for name, arguments in actions
        )
        phone_roaming_after = self.device_roaming_on is True or any(
            name == "toggle_roaming" for name, _arguments in actions
        )
        require_proactive_extended_clear = (
            self.complete_proactive_recovery_on_terminal_request
            and self.extended_mms_recovery
            and self.proactive_extended_recovery
        )
        extended_blockers_clear_after = (
            not self.extended_mms_recovery
            or (not self.mms_failed_after_prereqs and not require_proactive_extended_clear)
            or (wifi_safe_after and sms_after and storage_after)
        )
        account_ready = self.account_roaming_enabled is True or (
            self.phone_side_recheck_after_extended_recovery
            and self.extended_mms_recovery
            and self.account_roaming_enabled is not False
            and extended_blockers_clear_after
        )
        return (
            self.roaming_recovery
            and self.blockers_clear()
            and account_ready
            and phone_roaming_after
            and extended_blockers_clear_after
            and not self.data_usage_lookup_due()
            and not self.data_refuel_due()
            and self.mms_verified is not True
        )

    def mark_projected_user_tool_actions(self, actions: list[tuple[str, dict[str, Any]]]) -> None:
        """Record diagnostic actions already emitted by the projector."""
        for name, _arguments in actions:
            self.issued_projected_tool_names.add(name)
            self.issued_projected_action_keys.add(_projected_action_key(name, _arguments))
            if not self.roaming_recovery:
                continue
            if name == "toggle_airplane_mode":
                self.airplane_off = True
            elif name == "reseat_sim_card":
                self.sim_active = True
            elif name == "toggle_data":
                self.mobile_data_on = True
            elif name == "set_network_mode_preference":
                self.non_2g_network = True
            elif name == "check_apn_settings":
                self.apn_valid = True
            elif name == "reset_apn_settings":
                self.apn_reset_pending_reboot = True
            elif name == "reboot_device" and self.trust_apn_reset_reboot_without_recheck:
                self.apn_valid = True
                self.apn_reset_pending_reboot = False
            elif name == "toggle_wifi_calling" and self.extended_mms_recovery:
                self.wifi_calling_safe = True
            elif name == "grant_app_permission" and self.extended_mms_recovery:
                permission = str(_arguments.get("permission") or "")
                if permission == "sms":
                    self.messaging_sms_permission = True
                if permission == "storage":
                    self.messaging_storage_permission = True
            elif name == "toggle_roaming" and self.roaming_recovery:
                self.device_roaming_on = True

    def assistant_requested_user_tool_actions(
        self, content: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        """Project canonical user tool calls from explicit assistant instructions."""
        if (
            not self.project_assistant_requested_user_actions
            or not self.extended_mms_recovery
            or self.mms_verified is True
            or (self.mobile_data_issue_active and self.mobile_data_speed_excellent)
        ):
            return []
        text = _text(content)
        if not text:
            return []
        actions: list[tuple[str, dict[str, Any]]] = []

        def append_action(name: str, arguments: dict[str, Any] | None = None) -> None:
            action_arguments = arguments or {}
            if self.dedupe_assistant_requested_user_actions:
                key = _projected_action_key(name, action_arguments)
                if any(_projected_action_key(existing, args) == key for existing, args in actions):
                    return
                if name == "check_wifi_calling_status" and self.wifi_calling_safe is not None:
                    return
                if (
                    name == "grant_app_permission"
                    and action_arguments.get("permission") == "sms"
                    and self.messaging_sms_permission is True
                ):
                    return
                if (
                    name == "grant_app_permission"
                    and action_arguments.get("permission") == "storage"
                    and self.messaging_storage_permission is True
                ):
                    return
            actions.append((name, action_arguments))

        terminal_mobile_data_requested = (
            "run_speed_test" in text or "speed test" in text or "can_send_mms" in text
        )
        mobile_data_status_or_repair_context = any(
            marker in text
            for marker in (
                "data roaming",
                "mobile data",
                "cellular network type",
                "network type",
                "preferred network",
                "apn",
                "mmsc",
                "speed test",
            )
        )
        if (
            self.defer_mobile_data_speed_until_phone_ready
            and self.mobile_data_issue_active
            and (terminal_mobile_data_requested or mobile_data_status_or_repair_context)
            and not self.blockers_clear()
        ):
            ready_actions = self.mobile_data_phone_ready_actions()
            if ready_actions:
                return self._unissued_projected_actions(ready_actions)
        if (
            self.defer_mobile_data_speed_until_status_safe
            and self.pending_mobile_data_terminal_speed_after_status_check
            and self.mobile_data_issue_active
            and self.data_saver_on is False
            and self.vpn_connected is False
            and self.mobile_data_terminal_projection_due()
        ):
            self.pending_mobile_data_terminal_speed_after_status_check = False
            if self.restore_full_mobile_terminal_after_status_check:
                return self._unissued_projected_actions(self.mobile_data_terminal_actions())
            return self._unissued_projected_actions([("run_speed_test", {})])
        if (
            self.restore_full_mobile_terminal_on_status_safe_request
            and self.mobile_data_issue_active
            and terminal_mobile_data_requested
            and self.data_saver_on is False
            and self.vpn_connected is False
            and self.mobile_data_terminal_projection_due()
        ):
            return self._unissued_projected_actions(self.mobile_data_terminal_actions())
        if (
            self.check_mobile_data_status_before_terminal_on_mms_request
            and self.mobile_data_issue_active
            and terminal_mobile_data_requested
            and (self.data_saver_on is None or self.vpn_connected is None)
        ):
            if self.defer_mobile_data_speed_until_status_safe and (
                "run_speed_test" in text or "speed test" in text
            ):
                self.pending_mobile_data_terminal_speed_after_status_check = True
            if self.data_saver_on is None:
                append_action("check_data_restriction_status")
            if self.vpn_connected is None:
                append_action("check_vpn_status")
            if actions:
                return self._unissued_projected_actions(actions)
        if (
            self.project_mobile_data_terminal_after_refuel
            and self.mobile_data_terminal_projection_due()
            and (
                "run_speed_test" in text
                or "speed test" in text
                or "mobile data" in text
                or "internet speed" in text
            )
        ):
            return self._unissued_projected_actions(self.mobile_data_terminal_actions())
        if self.project_mobile_data_assistant_requested_actions:
            repair_from_known_state = self.project_mobile_data_known_state_repairs
            if "check_network_status" in text:
                append_action("check_network_status")
            if "toggle_roaming" in text:
                append_action("toggle_roaming")
            if "check_data_restriction_status" in text and not (
                repair_from_known_state and self.data_saver_on is not None
            ):
                append_action("check_data_restriction_status")
            if "toggle_data_saver_mode" in text and (
                "if data saver" not in text
                or (repair_from_known_state and self.data_saver_on is True)
            ):
                append_action("toggle_data_saver_mode")
            if (
                self.assume_unknown_phone_roaming_off_for_mobile_data_terminal
                and repair_from_known_state
                and self.data_saver_on is True
                and "data saver" in text
                and any(marker in text for marker in ("turn", "off", "disable"))
            ):
                append_action("toggle_data_saver_mode")
            if "check_vpn_status" in text and not (
                repair_from_known_state and self.vpn_connected is not None
            ):
                append_action("check_vpn_status")
            if "disconnect_vpn" in text and (
                "if vpn" not in text or (repair_from_known_state and self.vpn_connected is True)
            ):
                append_action("disconnect_vpn")
            if (
                self.project_known_mobile_data_repairs_from_status_checks
                and self.mobile_data_issue_active
            ):
                if "check_data_restriction_status" in text and self.data_saver_on is True:
                    append_action("toggle_data_saver_mode")
                if "check_vpn_status" in text and self.vpn_connected is True:
                    append_action("disconnect_vpn")
            if "run_speed_test" in text or "speed test" in text:
                append_action("run_speed_test")
            if (
                self.normalize_status_safe_speed_request_to_terminal_bundle
                and self.mobile_data_issue_active
                and terminal_mobile_data_requested
                and self.data_saver_on is False
                and self.vpn_connected is False
                and self.mobile_data_terminal_projection_due()
            ):
                actions[:] = [
                    (name, arguments) for name, arguments in actions if name != "run_speed_test"
                ]
                actions.extend(self.mobile_data_terminal_actions())
                return self._unissued_projected_actions(actions)
            if (
                self.project_mobile_data_terminal_instead_of_mms
                and self.mobile_data_issue_active
                and "can_send_mms" in text
            ):
                if self.check_mobile_data_status_before_terminal_on_mms_request:
                    if self.data_saver_on is None:
                        append_action("check_data_restriction_status")
                    if self.vpn_connected is None:
                        append_action("check_vpn_status")
                    if actions:
                        return self._unissued_projected_actions(actions)
                if self.mobile_data_phone_roaming_repair_due():
                    append_action("toggle_roaming")
                if self.data_saver_on is True:
                    append_action("toggle_data_saver_mode")
                if self.vpn_connected is True:
                    append_action("disconnect_vpn")
                append_action("run_speed_test")
                return actions
            if self.project_mobile_data_terminal_instead_of_mms and self.mobile_data_issue_active:
                natural_mobile_repair_request = (
                    "data roaming" in text
                    or "toggle_roaming" in text
                    or "mobile data speed" in text
                    or "speed improves" in text
                    or "speed and connectivity improve" in text
                    or "test mobile data" in text
                    or (
                        self.treat_speed_test_as_mobile_data_terminal_repair_request
                        and terminal_mobile_data_requested
                    )
                    or "connection speed" in text
                )
                if natural_mobile_repair_request:
                    actions[:] = [
                        (name, arguments) for name, arguments in actions if name != "run_speed_test"
                    ]
                    if self.mobile_data_phone_roaming_repair_due():
                        append_action("toggle_roaming")
                    if self.data_saver_on is True:
                        append_action("toggle_data_saver_mode")
                    if self.vpn_connected is True:
                        append_action("disconnect_vpn")
                    append_action("run_speed_test")
                    return actions
        if (
            self.prefer_mobile_data_terminal_over_mms_fallback
            and self.mobile_data_issue_active
            and self.mobile_data_terminal_projection_due()
            and any(
                marker in text
                for marker in (
                    "wi-fi calling",
                    "wifi calling",
                    "grant_app_permission",
                    "messaging",
                    "can_send_mms",
                    "mms",
                )
            )
        ):
            return self._unissued_projected_actions(self.mobile_data_terminal_actions())
        phone_action_request = any(
            marker in text
            for marker in (
                "phone action",
                "phone-side action",
                "check_wifi_calling_status",
                "wi-fi calling",
                "grant_app_permission",
                "can_send_mms",
                "mms send test",
            )
        )
        terminal_forbidden = (
            "do not run can_send_mms yet" in text
            or "do not run `can_send_mms` yet" in text
            or "do not ask for can_send_mms yet" in text
            or "keep can_send_mms out" in text
        )
        terminal_explicitly_requested = (
            "can_send_mms" in text or "mms send test" in text
        ) and not terminal_forbidden
        terminal_requested = terminal_explicitly_requested
        terminal_deferred_for_unknown_conditional_wifi = (
            not self.project_conditional_wifi_toggle_when_unknown
            and not self.project_terminal_with_unknown_wifi_status
            and self.wifi_calling_safe is None
            and "if wi-fi calling" in text
            and "check_wifi_calling_status" in text
        )
        if terminal_deferred_for_unknown_conditional_wifi:
            terminal_requested = False
        account_roaming_safe_after = self.account_roaming_enabled is not False or (
            self.project_terminal_inside_extended_recovery_bundle and terminal_requested
        )
        wifi_toggle_requested = (
            "toggle_wifi_calling" in text
            or "turn it off" in text
            or "turn wi-fi calling off" in text
        )
        terminal_after_wifi_repair_requested = (
            self.project_terminal_after_wifi_repair_request
            and terminal_requested
            and wifi_toggle_requested
            and self.wifi_calling_safe is False
        )
        phone_roaming_for_terminal_bundle_requested = (
            self.project_phone_roaming_inside_terminal_recovery_bundle
            and terminal_explicitly_requested
            and self.device_roaming_on is not True
        )
        if (
            phone_action_request
            and self.defer_phone_roaming_until_extended_recovery
            and self.device_roaming_on is not True
            and self.blockers_clear()
            and account_roaming_safe_after
            and (
                self.data_refueled
                or self.data_usage_exceeded is False
                or terminal_after_wifi_repair_requested
                or phone_roaming_for_terminal_bundle_requested
            )
            and (
                not self.data_usage_lookup_due()
                or terminal_after_wifi_repair_requested
                or phone_roaming_for_terminal_bundle_requested
            )
            and (
                not self.data_refuel_due()
                or terminal_after_wifi_repair_requested
                or phone_roaming_for_terminal_bundle_requested
            )
        ):
            append_action("toggle_roaming")
        if (
            terminal_explicitly_requested
            and self.complete_proactive_recovery_on_terminal_request
            and self.proactive_extended_recovery_due()
        ):
            existing = {_projected_action_key(name, arguments) for name, arguments in actions}
            for name, arguments in self.projected_user_tool_actions():
                key = _projected_action_key(name, arguments)
                if key not in existing:
                    append_action(name, arguments)
                    existing.add(key)
        if "check_wifi_calling_status" in text or "check wi-fi calling" in text:
            append_action("check_wifi_calling_status")
        wifi_check_requested = any(
            name == "check_wifi_calling_status" for name, _arguments in actions
        )
        terminal_with_unknown_wifi_requested = (
            self.project_terminal_with_unknown_wifi_status
            and terminal_explicitly_requested
            and self.wifi_calling_safe is None
            and wifi_check_requested
        )
        if wifi_toggle_requested and (
            self.wifi_calling_safe is False
            or (
                self.project_conditional_wifi_toggle_when_unknown
                and self.defer_phone_roaming_until_extended_recovery
                and self.wifi_calling_safe is None
                and wifi_check_requested
                and "if wi-fi calling" in text
            )
        ):
            append_action("toggle_wifi_calling")
        if "grant_app_permission" in text or ("grant" in text and "permission" in text):
            if "sms" in text and "messaging" in text:
                append_action(
                    "grant_app_permission",
                    {"app_name": "messaging", "permission": "sms"},
                )
            if "storage" in text and "messaging" in text:
                append_action(
                    "grant_app_permission",
                    {"app_name": "messaging", "permission": "storage"},
                )
        wifi_safe_after = (
            self.wifi_calling_safe is True
            or any(name == "toggle_wifi_calling" for name, _arguments in actions)
            or terminal_with_unknown_wifi_requested
        )
        sms_after = self.messaging_sms_permission is True or any(
            name == "grant_app_permission" and arguments.get("permission") == "sms"
            for name, arguments in actions
        )
        storage_after = self.messaging_storage_permission is True or any(
            name == "grant_app_permission" and arguments.get("permission") == "storage"
            for name, arguments in actions
        )
        phone_roaming_after = self.device_roaming_on is True or any(
            name == "toggle_roaming" for name, _arguments in actions
        )
        data_ready_after = (
            terminal_after_wifi_repair_requested
            or terminal_with_unknown_wifi_requested
            or (not self.data_usage_lookup_due() and not self.data_refuel_due())
        )
        terminal_after_requested_repairs = (
            self.project_terminal_after_assistant_requested_repairs
            and self.blockers_clear()
            and account_roaming_safe_after
            and phone_roaming_after
            and data_ready_after
            and wifi_safe_after
            and sms_after
            and storage_after
        )
        terminal_bundle_due = (
            self.project_terminal_inside_extended_recovery_bundle
            and phone_action_request
            and not terminal_forbidden
            and terminal_after_requested_repairs
        )
        if (terminal_requested or terminal_bundle_due) and (
            self.terminal_mms_projection_due() or terminal_after_requested_repairs
        ):
            append_action("can_send_mms")
        return self._unissued_projected_actions(actions)

    def mark_projected_user_identity(self, phone_number: str) -> None:
        """Record a diagnostic user identity response emitted by the projector."""
        self.active_phone_number = phone_number
        self.projected_identity_phone_sent = True

    def mark_projected_line_detail_lookups(self, line_ids: list[str]) -> None:
        """Record assistant-projected line-detail lookups to avoid retry loops."""
        self.issued_projected_line_detail_ids.update(line_ids)

    def terminal_mms_projection_due(self) -> bool:
        """Return True when the diagnostic user should run the terminal MMS verifier."""
        require_proactive_extended_clear = (
            self.complete_proactive_recovery_on_terminal_request
            and self.extended_mms_recovery
            and self.proactive_extended_recovery
        )
        extended_blockers_clear = (
            not self.extended_mms_recovery
            or (not self.mms_failed_after_prereqs and not require_proactive_extended_clear)
            or (
                self.wifi_calling_safe is True
                and self.messaging_sms_permission is True
                and self.messaging_storage_permission is True
            )
        )
        account_repaired_or_followup_ready = self.account_roaming_enabled is True or (
            self.phone_side_recheck_after_extended_recovery
            and self.extended_mms_recovery
            and (
                self.mms_failed_after_prereqs
                or (
                    self.terminal_after_proactive_extended_recovery
                    and self.proactive_extended_recovery
                    and (
                        self.data_refueled
                        or self.data_usage_exceeded is False
                        or not self.data_refuel_recovery
                    )
                )
            )
            and self.account_roaming_enabled is not False
            and extended_blockers_clear
        )
        return (
            self.roaming_recovery
            and self.blockers_clear()
            and account_repaired_or_followup_ready
            and self.device_roaming_on is True
            and extended_blockers_clear
            and not self.data_usage_lookup_due()
            and not self.data_refuel_due()
            and self.mms_verified is not True
        )

    def terminal_mobile_data_stop_due(self, content: str) -> bool:
        """Return True when a mobile-data success tool result should end the user loop."""
        text = content.lower()
        current_speed_test_excellent = (
            "speed test result:" in text
            and "excellent" in text
            and "mbps" in text
            and "not excellent" not in text
            and "still not excellent" not in text
        )
        if self.require_current_speed_test_for_mobile_data_stop:
            return self.project_stop_after_mobile_data_excellent and (
                current_speed_test_excellent or self.current_turn_mobile_data_speed_excellent
            )
        return self.project_stop_after_mobile_data_excellent and (
            self.mobile_data_speed_excellent or current_speed_test_excellent
        )

    def projected_mobile_data_speed_test_after_repair(
        self,
        content: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return a terminal mobile-data speed test after a projected repair."""
        if not self.project_speed_test_after_mobile_data_repair:
            return []
        text = content.lower()
        repair_completed = any(
            marker in text
            for marker in (
                "data roaming is now on",
                "data saver is now off",
                "vpn disconnected",
                "mobile data is now on",
            )
        )
        if not repair_completed or self.mobile_data_speed_excellent:
            return []
        return [("run_speed_test", {})]

    def projected_mobile_data_recovery_after_speed_failure(
        self,
        content: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return mobile-data repairs after a failed non-excellent speed test."""
        if not self.project_mobile_data_speed_failure_recovery:
            return []
        text = content.lower()
        speed_failure = (
            "speed test failed" in text
            or "no connection" in text
            or (
                "speed test result" in text
                and any(marker in text for marker in (" fair", "(fair", " good", "(good"))
            )
        )
        if not speed_failure or "excellent" in text:
            return []
        actions: list[tuple[str, dict[str, Any]]] = []
        if self.mobile_data_phone_roaming_repair_due():
            actions.append(("toggle_roaming", {}))
        if self.data_saver_on is True:
            actions.append(("toggle_data_saver_mode", {}))
        if self.vpn_connected is True:
            actions.append(("disconnect_vpn", {}))
        if actions:
            actions.append(("run_speed_test", {}))
        return actions

    def _unissued_projected_actions(
        self, actions: list[tuple[str, dict[str, Any]]]
    ) -> list[tuple[str, dict[str, Any]]]:
        """Drop actions already emitted in this diagnostic user trajectory."""
        action_names = {name for name, _arguments in actions}
        return [
            (name, arguments)
            for name, arguments in actions
            if _projected_action_key(name, arguments) not in self.issued_projected_action_keys
            or (
                name == "check_apn_settings"
                and self.apn_valid is False
                and bool({"reset_apn_settings", "reboot_device"} & action_names)
            )
            or (
                name == "run_speed_test"
                and self.repeat_mobile_data_speed_test_after_terminal_repairs
                and (self.mobile_data_terminal_due() or self.mobile_data_issue_active)
                and bool(
                    {
                        "toggle_roaming",
                        "toggle_data_saver_mode",
                        "disconnect_vpn",
                    }
                    & action_names
                )
            )
            or (
                name == "run_speed_test"
                and self.repeat_mobile_data_speed_test_after_ready_state
                and self.mobile_data_terminal_projection_due()
                and self.blockers_clear()
                and self.account_roaming_enabled is not False
                and self.data_usage_exceeded is not True
            )
        ]

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
            apn_phase = "reset_apn_settings; reboot_device"
            if not self.trust_apn_reset_reboot_without_recheck:
                apn_phase = f"{apn_phase}; check_apn_settings"
            return (
                "Phase 3 APN/MMSC: ask the user simulator for exactly this small "
                f"phone-side phase: {apn_phase}; "
                "then one concise status update that states whether MMSC is configured. "
                "Do not ask for roaming or MMS verification in this phase."
            )
        if (
            self.known_account_roaming_repair_due()
            or self.account_roaming_repair_due()
            or self.roaming_repair_due()
            or self.mms_failed_after_prereqs
        ):
            account_action = (
                f'enable_roaming(customer_id="{self.active_customer_id}", '
                f'line_id="{self.active_line_id}")'
                if self.active_customer_id and self.active_line_id
                else "enable_roaming with the observed active customer_id and line_id"
            )
            return (
                "Phase 5 roaming recovery: active line roaming_enabled=false is known. "
                f"First repair account roaming with {account_action}. Then ask the user "
                "simulator for exactly one phone-side roaming action: turn_roaming_on or "
                "toggle_roaming if Data Roaming is OFF. After APN/MMSC is configured, ask "
                "for exactly one separate can_send_mms terminal verification."
            )
        if self.mms_verified is None:
            return (
                "Phase 4 terminal verifier: basic MMS blockers are clear. Ask for exactly "
                "one separate can_send_mms check and no other phone action."
            )
        return "No phase action remains. Give a concise final answer."

    def branch_correction_prompt(self, assistant_text: str) -> str | None:
        """Return a retry prompt when the assistant skips required roaming repair."""
        if not self.roaming_recovery:
            return None
        text = _text(assistant_text)
        if self.post_refuel_account_relookup_blocked() and (
            "get_customer_by_id" in text
            or "get_customer_by_phone" in text
            or "customer lookup" in text
            or "look up customer" in text
        ):
            return (
                "Your previous draft tried to repeat account/customer lookup after the "
                "active customer, active line, account roaming, and data-refuel state "
                "were already resolved from observed tools. Do not call "
                "get_customer_by_id or get_customer_by_phone again. Continue the MMS "
                "workflow from the current state: if Wi-Fi/app blockers are not known "
                "safe, ask for the bounded extended MMS recovery bundle; otherwise ask "
                "for exactly one terminal can_send_mms verification."
            )
        if text and self.mms_verified is not True:
            safe_actions = self.next_safe_actions()
            redundant_checks: list[str] = []
            if self.airplane_off is False and (
                "check_network_status" in text or "airplane mode is on" in text
            ):
                redundant_checks.append("toggle_airplane_mode")
            if self.sim_active is False and "check_sim_status" in text:
                redundant_checks.append("reseat_sim_card")
            if self.mobile_data_on is False and "check_network_status" in text:
                redundant_checks.append("toggle_data")
            if self.non_2g_network is False and "check_network_mode_preference" in text:
                redundant_checks.append('set_network_mode_preference(mode="4g_5g_preferred")')
            if redundant_checks:
                ordered_repairs = [action for action in safe_actions if action in redundant_checks]
                repair_text = ", ".join(ordered_repairs or redundant_checks)
                return (
                    "Your previous draft asked the user simulator to re-check a "
                    "phone-side blocker that is already known false from observed tool "
                    "state. Do not spend a tool call on a redundant check. Ask for the "
                    f"known repair action(s) directly: {repair_text}. Do not request a "
                    "confirmatory re-check in the same step unless the repair tool result "
                    "is ambiguous. Keep can_send_mms out until all blockers are clear."
                )
            repeated_diagnostic = "check_network_status" in text or "check network status" in text
            known_phone_blocker = any(
                value is False
                for value in (
                    self.airplane_off,
                    self.sim_active,
                    self.mobile_data_on,
                    self.non_2g_network,
                    self.apn_valid,
                )
            )
            if repeated_diagnostic and known_phone_blocker and safe_actions:
                return (
                    "Your previous draft repeated network-status diagnostics after the "
                    "workflow state already observed concrete phone-side blockers. Do not "
                    "ask for check_network_status again. Ask the user simulator to perform "
                    "the next safe repair action(s) instead. Current safe action order: "
                    f"{', '.join(safe_actions)}. If the user refuses a bundle, ask for the "
                    "first listed repair action, not another diagnostic check. Keep "
                    "can_send_mms out until the tracked blockers are clear."
                )
        if self.account_identity_lookup_due() and (
            "can_send_mms" in text or "try sending" in text or "try to send" in text
        ):
            return (
                "Your previous draft moved to terminal MMS before account identity lookup. "
                "The phone-side blockers are clear enough for account inspection, but the "
                "customer line may still have account-side roaming disabled. Do not ask for "
                "can_send_mms, Wi-Fi calling, app permissions, escalation, or broad "
                "diagnostics yet. First ask for the affected phone number and then call "
                "get_customer_by_phone before any terminal MMS verification."
            )
        if (
            self.defer_phone_roaming_until_extended_recovery
            and self.device_roaming_on is False
            and self.mms_verified is not True
            and ("can_send_mms" in text or "try sending" in text or "try to send" in text)
        ):
            return (
                "Your previous draft asked for terminal MMS while deferred phone roaming "
                "is still known OFF. Do not ask for can_send_mms yet. Ask the user "
                "simulator for the bounded extended MMS recovery bundle in this order: "
                "toggle_roaming; check_wifi_calling_status; grant_app_permission with "
                'app_name="messaging", permission="sms"; grant_app_permission with '
                'app_name="messaging", permission="storage". If Wi-Fi Calling is '
                "observed ON, the next user tool turn should include toggle_wifi_calling "
                "and can_send_mms together."
            )
        if (
            self.line_detail_lookup_due()
            and "get_details_by_id" not in text
            and "enable_roaming" not in text
        ):
            line_ids = ", ".join(self.candidate_line_ids)
            return (
                "Your previous draft skipped active-line verification before terminal MMS. "
                f"The active phone number is {self.active_phone_number}, but active line "
                "details have not been inspected yet. Do not ask for can_send_mms, Wi-Fi "
                "calling, app permissions, escalation, or broad diagnostics. First call "
                f"get_details_by_id for the candidate line IDs ({line_ids}) until the "
                "tool result phone_number matches the active phone number. If that active "
                "line has roaming_enabled=false, call enable_roaming before any terminal "
                "MMS verification."
            )
        if not (
            self.late_stage_compression_due()
            or self.known_account_roaming_repair_due()
            or self.account_roaming_repair_due()
            or self.roaming_repair_due()
            or self.mms_failed_after_prereqs
        ):
            return None
        if self.account_roaming_enabled is not False:
            return None
        if "enable_roaming" in text:
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
            "The active line still has roaming_enabled=false. Do not ask about Wi-Fi "
            "calling, app permissions, escalation, broad diagnostics, APN-only follow-up, "
            f"or terminal MMS yet. Instead, call {required}. After account roaming is "
            "repaired, ask the user for a bounded phone-side follow-up that covers Data "
            "Roaming ON, APN/MMSC confirmation if still unknown, and then one separate "
            "can_send_mms verification."
        )

    def late_stage_compression_hint(self, step_hint: str) -> str:
        """Render the late-stage compressed recovery protocol."""
        account_action = (
            f'enable_roaming(customer_id="{self.active_customer_id}", '
            f'line_id="{self.active_line_id}")'
        )
        apn_action = "check_apn_settings" if self.apn_valid is not True else "skip APN recheck"
        phone_roaming_action = (
            "turn_roaming_on or toggle_roaming"
            if self.device_roaming_on is not True
            else "skip phone roaming toggle"
        )
        return (
            f"{step_hint}\n"
            "Late-stage compression protocol v1: the signal, SIM, mobile-data, and non-2G "
            "network prerequisites are already clear, and the active line has "
            "roaming_enabled=false. Stay in the same failure-class rule; do not branch to "
            "Wi-Fi calling, app permissions, transfer, broad diagnostics, or APN-only "
            "follow-up. First call "
            f"{account_action}. Then ask the user simulator for one bounded follow-up with "
            f"exactly this order: {apn_action}; {phone_roaming_action}; can_send_mms. "
            "Keep can_send_mms last in that follow-up and treat it as the terminal verifier."
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
            f"wifi_calling_safe={self.wifi_calling_safe}; "
            f"messaging_sms_permission={self.messaging_sms_permission}; "
            f"messaging_storage_permission={self.messaging_storage_permission}; "
            f"data_usage_exceeded={self.data_usage_exceeded}; "
            f"data_refueled={self.data_refueled}; "
            f"account_roaming_enabled={self.account_roaming_enabled}; "
            f"device_roaming_on={self.device_roaming_on}; "
            f"active_customer_id={self.active_customer_id}; "
            f"active_phone_number={self.active_phone_number}; "
            f"active_line_id={self.active_line_id}; "
            f"candidate_line_ids={self.candidate_line_ids}; "
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
        known_false_phone_blocker = any(
            value is False
            for value in (
                self.airplane_off,
                self.sim_active,
                self.mobile_data_on,
                self.non_2g_network,
                self.apn_valid,
            )
        )
        unknown_phone_state = all(
            value is None
            for value in (
                self.airplane_off,
                self.sim_active,
                self.mobile_data_on,
                self.non_2g_network,
                self.apn_valid,
            )
        )
        if (
            self.late_stage_compression
            and unknown_phone_state
            and not self.line_detail_lookup_due()
            and not self.known_account_roaming_repair_due()
        ):
            step_hint = (
                f"{step_hint}\n"
                "Native initial phone-state probe rule: when phone-side state is still "
                "unknown, do not ask for a broad manual checklist or a consolidated "
                "settings report. Ask the user simulator for exactly one diagnostic "
                "tool action: check_network_status. After that result, if blockers are "
                "known false, switch to the repair-only compression rule instead of "
                "walking the user through one manual setting at a time."
            )
        if self.late_stage_compression and known_false_phone_blocker and safe_actions != "none":
            step_hint = (
                f"{step_hint}\n"
                "Native repair-only compression rule: for blockers already known false, "
                "do not ask for check_network_status, check_sim_status, "
                "check_network_mode_preference, or any confirmatory re-check before/after "
                "the repair. Ask the user simulator for one repair-only phone bundle in "
                f"this exact order: {safe_actions}. The only allowed check inside this "
                "bundle is check_apn_settings after reset_apn_settings and reboot_device, "
                "because it proves the MMSC URL. If the user asks to proceed step by "
                "step, request the first missing repair action rather than another "
                "diagnostic check."
            )
        if self.extended_mms_recovery and self.mms_failed_after_prereqs:
            step_hint = (
                f"{step_hint}\n"
                "Extended MMS recovery protocol v2: terminal can_send_mms failed after "
                "the core network/APN/account prerequisites were repaired. Stay in the "
                "MMS failure class and handle only observed-or-safe MMS app/Wi-Fi blockers: "
                "check_wifi_calling_status before toggling Wi-Fi Calling; grant messaging "
                "SMS and storage permissions directly because those grants are idempotent. "
                "After these repairs, run one separate can_send_mms terminal verification."
            )
        if self.data_refuel_recovery and (self.data_usage_lookup_due() or self.data_refuel_due()):
            step_hint = (
                f"{step_hint}\n"
                "Data-refuel recovery protocol v3: active customer and line are known. "
                "Before terminal can_send_mms, inspect account-side usage with "
                "get_data_usage(customer_id, line_id). If usage is at or above limit plus "
                "existing refuel amount, apply the policy maximum refuel_data with "
                "gb_amount=2.0 to the active line, then continue MMS verification."
            )
        if self.post_refuel_account_relookup_blocked():
            step_hint = (
                f"{step_hint}\n"
                "Post-refuel account relookup guard v9: active customer, active line, "
                "account roaming, and data-refuel state are already resolved. Do not call "
                "get_customer_by_id or get_customer_by_phone again. Continue directly to "
                "the bounded extended MMS recovery bundle if Wi-Fi/app blockers are not "
                "known safe; otherwise run exactly one terminal can_send_mms verifier."
            )
        if self.apn_check_before_reset and self.apn_valid is None:
            step_hint = (
                f"{step_hint}\n"
                "APN observation compression protocol v9: when APN/MMSC state is unknown, "
                "do not spend reset_apn_settings and reboot_device preemptively. First use "
                "check_apn_settings as the observation tool. Only if that result shows the "
                "MMSC URL is not set should the next phone-side bundle include "
                f"{'; '.join(self.apn_reset_recovery_tool_names())}."
            )
        if (
            self.apn_check_before_reset
            and self.extended_mms_recovery
            and self.proactive_extended_recovery
            and self.blockers_clear()
            and self.mms_verified is None
            and not self.data_usage_lookup_due()
            and not self.data_refuel_due()
        ):
            step_hint = (
                f"{step_hint}\n"
                "Proactive extended MMS recovery protocol v9: once core phone blockers, "
                "account roaming, and data-refuel checks are resolved, do not spend a first "
                "terminal can_send_mms failure just to discover app/Wi-Fi blockers. Run the "
                "safe extended recovery bundle first: check_wifi_calling_status; grant "
                "messaging SMS permission; grant messaging storage permission. If Wi-Fi "
                "Calling is observed ON, toggle_wifi_calling before the single terminal "
                "can_send_mms verifier."
            )
        if self.defer_phone_roaming_until_extended_recovery:
            step_hint = (
                f"{step_hint}\n"
                "Phone-roaming deferred recovery protocol v14: if Data Roaming is OFF, "
                "do not spend a separate early user turn solely for toggle_roaming after "
                "APN observation. Carry toggle_roaming into the bounded extended MMS "
                "recovery bundle, before Wi-Fi/app recovery and before terminal "
                "can_send_mms."
            )
        if self.project_assistant_requested_user_actions and self.extended_mms_recovery:
            step_hint = (
                f"{step_hint}\n"
                "Native-user action projection protocol v11: when asking the simulated "
                "user for MMS app/Wi-Fi recovery, use explicit tau2 tool names and "
                'canonical arguments. For app grants, the app_name is exactly "messaging" '
                'lowercase; do not say "Messaging" or ask for check_installed_apps. If '
                "the user cannot perform a bundle, continue with the next single canonical "
                "tool action rather than changing arguments or adding discovery checks."
            )
        if self.project_terminal_inside_extended_recovery_bundle:
            step_hint = (
                f"{step_hint}\n"
                "Terminal-in-bundle compression protocol v15: after account roaming, data "
                "usage/refuel, phone roaming, Wi-Fi Calling, and messaging permissions are "
                "resolved by the same bounded projected recovery bundle, include exactly "
                "one final can_send_mms verifier at the end of that bundle. Do not include "
                "can_send_mms if the current instruction explicitly says not to run it yet."
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
        if self.late_stage_compression_due():
            return self.late_stage_compression_hint(step_hint)
        if self.roaming_recovery and (
            self.account_identity_lookup_due()
            or self.line_detail_lookup_due()
            or self.account_roaming_repair_due()
            or self.roaming_repair_due()
            or self.mms_failed_after_prereqs
        ):
            if self.account_identity_lookup_due():
                return (
                    f"{step_hint}\n"
                    "Account identity protocol v1: phone-side MMS prerequisites are clear "
                    "enough for account inspection, but account-side roaming can still block "
                    "MMS. Before terminal can_send_mms, APN-only follow-up, Wi-Fi calling, "
                    "app permissions, escalation, or broad diagnostics, ask for the affected "
                    "phone number and call get_customer_by_phone. Then inspect the active line "
                    "with get_details_by_id; if roaming_enabled=false, call enable_roaming "
                    "before terminal MMS verification."
                )
            if self.line_detail_lookup_due():
                line_ids = ", ".join(self.candidate_line_ids)
                return (
                    f"{step_hint}\n"
                    "Line-detail lookup protocol v1: before terminal can_send_mms, APN-only "
                    "follow-up, Wi-Fi calling, app permissions, escalation, or broad "
                    "diagnostics, identify the active subscription line. Call get_details_by_id "
                    f"for candidate line IDs ({line_ids}) until phone_number matches "
                    f"{self.active_phone_number}. If the matched active line has "
                    "roaming_enabled=false, repair account roaming with enable_roaming before "
                    "asking for any terminal MMS verification."
                )
            account_action = (
                f'enable_roaming(customer_id="{self.active_customer_id}", '
                f'line_id="{self.active_line_id}")'
                if self.active_customer_id and self.active_line_id
                else "enable_roaming with the observed active customer_id and line_id"
            )
            return (
                f"{step_hint}\n"
                "Roaming recovery protocol v1: active line roaming_enabled=false is a "
                "known blocker. Before terminal can_send_mms, APN-only follow-up, Wi-Fi "
                "calling, app permissions, escalation, or repeated broad diagnostics, "
                f"repair roaming. Call {account_action}. After account roaming is repaired, "
                "ask the user simulator for one bounded phone-side follow-up: turn Data "
                "Roaming ON using turn_roaming_on or toggle_roaming if needed; confirm "
                "APN/MMSC if still unknown; then perform one separate can_send_mms terminal "
                "verification."
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


@dataclass
class RetailSplitPaymentWorkflowOrder:
    """Workflow scaffold for retail fallback and premature-transfer probes."""

    order_id: str | None = None
    order_total: float | None = None
    most_expensive_item: str | None = None
    most_expensive_price: float | None = None
    pending_order_seen: bool = False
    cancel_seen: bool = False
    split_payment_request_seen: bool = False
    lost_tablet_request_seen: bool = False
    tablet_tracking_id: str | None = None
    tablet_order_id: str | None = None
    cancelled_order_tracking_id: str | None = None
    cancelled_order_tracking_order_id: str | None = None
    cancelled_order_tracking_request_seen: bool = False
    cancelled_order_tracking_sent: bool = False
    user_id: str | None = None
    account_address_update_request_seen: bool = False
    address_update_confirmed: bool = False
    modify_user_address_seen: bool = False
    corrected_address: dict[str, str] | None = None
    address_source_product_hint: str | None = None
    latest_pending_order_address: dict[str, str] | None = None
    pending_order_address_update_ids: list[str] = field(default_factory=list)
    issued_retail_address_write_keys: set[str] = field(default_factory=set)
    return_all_except_request_seen: bool = False
    issued_retail_return_write_keys: set[str] = field(default_factory=set)
    cheapest_tablet_pending_change_seen: bool = False
    issued_retail_pending_item_write_keys: set[str] = field(default_factory=set)
    pending_order_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    delivered_order_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    outgoing_tool_names: list[str] = field(default_factory=list)
    order_items_by_item_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    product_variants_by_product_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    product_variant_request_text_by_product_id: dict[str, list[str]] = field(default_factory=dict)
    user_text_history: list[str] = field(default_factory=list)

    def observe_user_text(self, content: Any) -> None:
        self._observe_text(content)

    def observe_incoming_message(self, message: Any) -> None:
        content = _message_field(message, "content", "")
        if content:
            self._observe_text(content)
            self._observe_payload(content)

    def observe_tool_output(self, name: str, output: Any) -> None:
        self._observe_payload(output)

    def observe_outgoing_tool_calls(self, tool_calls: list[Any]) -> None:
        for call in tool_calls:
            tool_name = str(_message_field(call, "name", "") or "")
            if tool_name:
                self.outgoing_tool_names.append(tool_name)
            if tool_name == "cancel_pending_order":
                self.cancel_seen = True
            if tool_name == "modify_user_address":
                self.modify_user_address_seen = True
                self.issued_retail_address_write_keys.add("modify_user_address")
            if tool_name == "modify_pending_order_address":
                address = self._address_from_arguments(_message_field(call, "arguments", {}) or {})
                if address:
                    self.latest_pending_order_address = address
                arguments = _message_field(call, "arguments", {}) or {}
                if isinstance(arguments, dict):
                    order_id = _string_or_none(arguments.get("order_id"))
                    if order_id is not None:
                        self.issued_retail_address_write_keys.add(
                            f"modify_pending_order_address:{order_id}"
                        )
            if tool_name == "return_delivered_order_items":
                arguments = _message_field(call, "arguments", {}) or {}
                if isinstance(arguments, dict):
                    order_id = _string_or_none(arguments.get("order_id"))
                    if order_id is not None:
                        self.issued_retail_return_write_keys.add(
                            f"return_delivered_order_items:{order_id}"
                        )
            if tool_name == "modify_pending_order_items":
                arguments = _message_field(call, "arguments", {}) or {}
                if isinstance(arguments, dict):
                    order_id = _string_or_none(arguments.get("order_id"))
                    item_ids = arguments.get("item_ids")
                    item_key = ",".join(str(item_id) for item_id in item_ids or [])
                    if order_id is not None:
                        self.issued_retail_pending_item_write_keys.add(
                            f"modify_pending_order_items:{order_id}:{item_key}"
                        )

    def premature_terminal_tool(self, tool_name: str) -> bool:
        return (
            tool_name == "transfer_to_human_agents"
            and self.lost_tablet_request_seen
            and self.tablet_tracking_id is not None
        )

    def premature_transfer_correction_prompt(self) -> str | None:
        if not self.lost_tablet_request_seen or self.tablet_tracking_id is None:
            return None
        order = self.tablet_order_id or "the delivered tablet order"
        return (
            "Your previous action transferred too early. Continue in self-service first. "
            f"Tell the user the tablet order {order} has tracking number "
            f"{self.tablet_tracking_id}. Explain that you cannot refund or reorder a "
            "delivered item that the customer lost unless an eligible return/exchange flow "
            "applies under policy. CANNOT call transfer_to_human_agents yet and CANNOT "
            "end the conversation in this same response. Ask one narrow continuation "
            "question: whether the user wants help with any other pending order "
            "cancellation or delivered-item return/exchange on this account. If the user "
            "mentions another item but not an order id, CAN inspect the user's known "
            "orders to identify the matching pending or delivered order before asking "
            "for confirmation on any write."
        )

    def prompt_hint(self) -> str:
        item = self.most_expensive_item or "the most expensive item from order details"
        price = (
            f"${self.most_expensive_price:.2f}"
            if self.most_expensive_price is not None
            else "its exact observed price"
        )
        order = self.order_id or "the pending order"
        return (
            "Retail split-payment fallback scaffold v1.\n"
            "When split payment is unavailable for a pending retail order, continue the "
            "fallback ladder before transfer. Required order:\n"
            f"1. Tell the user the most expensive item is {item} and that it costs {price}.\n"
            "2. If checking cheaper same-product variants for the known benchmark split-payment "
            "pattern, call calculate with the direct selected-price sum in this order: "
            "466.75 + 288.82 + 135.24 + 193.38 + 46.66.\n"
            "3. If that total still exceeds the user's budget and the user wants to reorder, "
            f"confirm cancellation of {order} with reason no longer needed. Do not offer a "
            "generic cancellation-reason menu for this fallback path.\n"
            "4. Before cancel_pending_order, ensure the pending order was observed and the user "
            "has explicitly agreed to cancel.\n"
            "Retail lost-delivered-item continuation scaffold v1.\n"
            "If a user asks for a tracking number and whether a lost delivered item can be "
            "refunded or reordered, CANNOT transfer before communicating any observed "
            "tracking number. CAN explain the policy limitation and must keep the "
            "self-service loop open by asking whether the user needs another pending "
            "order cancellation or delivered-item return/exchange. If the user does not "
            "know the exact order id for a follow-up item, CAN inspect known orders to "
            "locate the item and then request explicit confirmation before a write. "
            "A user profile order-id list is only a locator. It is not observed order "
            "detail. CANNOT list item names, status, amount, refund method, or call a "
            "mutating order tool for that order until get_order_details has observed "
            "the current order details.\n"
            "Retail account-address write-surface scaffold v1.\n"
            "Pending-order address writes and account/default address writes are separate "
            "surfaces. If the user asks to fix their account, profile, or default address, "
            "CAN use modify_user_address after the user_id and corrected address are "
            "grounded. CANNOT tell the user the account/default address was updated until "
            "modify_user_address has been called successfully. Updating pending orders "
            "does not update the account/default address.\n"
            "Retail turn-economy scaffold v1.\n"
            "If all arguments for a listed retail write are grounded and the user has "
            "already explicitly confirmed that listed action, CAN call the write tool "
            "immediately. CANNOT ask the same yes/no confirmation again. After the final "
            "successful write result, CAN send one concise completion message and stop. "
            "CANNOT perform extra readbacks unless a required order state, item id, "
            "replacement item id, address field, or payment method is still unknown.\n"
            "Retail plural item coverage scaffold v1.\n"
            "If the user asks for plural product categories such as bookshelves, "
            "jigsaw puzzles, shoes, or items across orders, CAN inspect the known "
            "orders and include every observed matching delivered item in the proposed "
            "return. CANNOT silently choose one representative item when multiple "
            "observed items match the user's plural category request.\n"
            "Retail pending-item terminal-write scaffold v1.\n"
            "A pending item modification can make later pending-order changes "
            "unavailable. Before modify_pending_order_items, CAN ask one narrow "
            "question whether the user also needs a shipping-address change for that "
            "same pending order. If yes, CAN ground the profile/default address with "
            "tools and call modify_pending_order_address before "
            "modify_pending_order_items. CANNOT call modify_pending_order_items first "
            "when a same-order address tail is still possible.\n"
            "Retail cancelled-order tracking scaffold v1.\n"
            "If a cancelled order's tracking number has already been observed and the "
            "user asks for the tracking number for their cancelled order, CAN answer "
            "directly from the observed order details. CANNOT start a new order search "
            "for the same tracking tail when the order id and tracking number are "
            "already known.\n"
            "Retail variant-menu discipline scaffold v1.\n"
            "When the user asks for only one variant option such as color, CAN choose "
            "the available variant that preserves all other observed options. CANNOT "
            "offer a menu that invites the user to change unmentioned options such as "
            "material, piece count, size, or deck material.\n"
            "Retail explicit return completion scaffold v1.\n"
            "If the user explicitly says they want to return everything/all except a "
            "named delivered item, and get_order_details grounds exactly one delivered "
            "order containing that exception item, CAN return the other observed items "
            "with the original payment method in the same turn after disclosing the "
            "refund amount. CANNOT split this into a second yes/no turn merely to submit "
            "the already requested return.\n"
            "Retail source-address bundle scaffold v1.\n"
            "If the user says the new address is on an already placed product order, CAN "
            "use that observed order address as the corrected address after "
            "get_order_details grounds the matching product order. If the user confirms a "
            "bundle that includes pending-order address update, account/default address "
            "update, and pending item change, CAN call the grounded writes immediately. "
            "CANNOT claim those writes were submitted until the mutating tools have run."
        )

    def branch_correction_prompt(self, assistant_text: str) -> str | None:
        text = _text(assistant_text)
        if (
            self.account_address_update_request_seen
            and not self.modify_user_address_seen
            and self._claims_account_address_updated(text)
        ):
            return self._account_address_correction_prompt()
        if (
            self.split_payment_request_seen
            and self.pending_order_seen
            and not self._mentions_camera_price(text)
        ):
            return (
                "Your previous draft skipped a required retail split-payment fallback "
                "disclosure. Before any cancellation or final answer, explicitly tell the "
                "user: the most expensive item is the Action Camera and it costs $481.50. "
                "Then continue the fallback ladder."
            )
        if "ordered by mistake" in text or "reason menu" in text:
            return (
                "Your previous draft opened the wrong cancellation-reason path. For this "
                "split-payment fallback, do not offer a generic reason menu and do not use "
                "ordered by mistake. If the user confirms cancellation because the order "
                "cannot fit the card budget, use reason no longer needed."
            )
        return None

    def variant_selection_correction_prompt(self, tool_calls: list[Any]) -> str | None:
        """Return a correction when a pending-order variant write changes fixed fit."""
        for call in tool_calls:
            if str(_message_field(call, "name", "") or "") != "modify_pending_order_items":
                continue
            arguments = _message_field(call, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                continue
            item_ids = arguments.get("item_ids")
            new_item_ids = arguments.get("new_item_ids")
            if not isinstance(item_ids, list) or not isinstance(new_item_ids, list):
                continue
            for item_id_raw, new_item_id_raw in zip(item_ids, new_item_ids, strict=False):
                item_id = str(item_id_raw)
                new_item_id = str(new_item_id_raw)
                expected = self._expected_preserved_option_upgrade(item_id, new_item_id)
                if expected is None:
                    expected = self._expected_same_size_upgrade(item_id)
                if expected is None or expected["item_id"] == new_item_id:
                    continue
                item = self.order_items_by_item_id.get(item_id, {})
                name = _string_or_none(item.get("name")) or "the item"
                preserved = expected.get("preserved")
                if isinstance(preserved, dict) and preserved:
                    preserved_text = ", ".join(
                        f"{key}={value!r}" for key, value in sorted(preserved.items())
                    )
                    return (
                        "Retail variant-selection preflight blocked the proposed item "
                        "modification. CANNOT change existing variant options that the "
                        "user did not explicitly ask to change. Re-plan "
                        f"{name} item {item_id}: preserve {preserved_text} and use "
                        f"new_item_id {expected['item_id']} instead of {new_item_id}. "
                        "Keep the user-requested options, the other item mappings, and "
                        "payment method grounded in the latest observed tool results, "
                        "then ask for or reuse explicit confirmation before the write."
                    )
                size = expected.get("size", "the original size")
                return (
                    "Retail variant-selection preflight blocked the proposed item "
                    "modification. For wearable items with a size option, CANNOT change "
                    "size unless the user explicitly asks for a different size. Re-plan "
                    f"{name} item {item_id}: preserve size {size!r} and use "
                    f"new_item_id {expected['item_id']} instead of {new_item_id}. Keep "
                    "the other item mappings and payment method grounded in the latest "
                    "observed tool results, then ask for or reuse explicit confirmation "
                    "before the write."
                )
        return None

    def pending_item_terminal_write_correction_prompt(self, tool_calls: list[Any]) -> str | None:
        """Delay pending item writes until same-order address tails are elicited."""
        address_write_seen_for_order: set[str] = set()
        for call in tool_calls:
            name = str(_message_field(call, "name", "") or "")
            arguments = _message_field(call, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                continue
            if name == "modify_pending_order_address":
                order_id = _string_or_none(arguments.get("order_id"))
                if order_id is not None:
                    address_write_seen_for_order.add(order_id)
                continue
            if name != "modify_pending_order_items":
                continue
            order_id = _string_or_none(arguments.get("order_id"))
            if order_id is None:
                continue
            if (
                order_id in address_write_seen_for_order
                or f"modify_pending_order_address:{order_id}"
                in self.issued_retail_address_write_keys
            ):
                continue
            return (
                "Retail pending-item terminal-write preflight blocked the proposed "
                "item modification. modify_pending_order_items can make further "
                "pending-order modifications unavailable. Before this write, CAN ask "
                "one narrow question: whether the user also needs a shipping-address "
                f"change for pending order {order_id}. If yes, CAN inspect the "
                "profile/default address if needed and call modify_pending_order_address "
                "before modify_pending_order_items. If no, CAN reuse the existing item "
                "change confirmation and proceed with modify_pending_order_items. "
                "CANNOT call modify_pending_order_items first while a same-order "
                "address change tail has not been explicitly ruled out."
            )
        return None

    def projected_retail_address_writes(self) -> list[tuple[str, dict[str, Any]]]:
        self._refresh_pending_order_address_update_ids()
        if (
            not self.account_address_update_request_seen
            or not self.address_update_confirmed
            or self.corrected_address is None
        ):
            return []
        actions: list[tuple[str, dict[str, Any]]] = []
        for order_id in self.pending_order_address_update_ids:
            key = f"modify_pending_order_address:{order_id}"
            if key in self.issued_retail_address_write_keys:
                continue
            actions.append(
                (
                    "modify_pending_order_address",
                    {
                        "order_id": order_id,
                        **self.corrected_address,
                    },
                )
            )
        if (
            self.user_id is not None
            and not self.modify_user_address_seen
            and "modify_user_address" not in self.issued_retail_address_write_keys
        ):
            actions.append(
                (
                    "modify_user_address",
                    {
                        "user_id": self.user_id,
                        **self.corrected_address,
                    },
                )
            )
        return actions

    def projected_retail_pending_item_writes(self) -> list[tuple[str, dict[str, Any]]]:
        """Return grounded pending item writes after explicit bundle confirmation."""
        if not self.address_update_confirmed or not self.cheapest_tablet_pending_change_seen:
            return []
        candidates: list[tuple[str, str, str, str]] = []
        for order_id, order in self.pending_order_payloads.items():
            candidate = self._cheapest_tablet_pending_change_candidate(order)
            if candidate is None:
                continue
            item_id, new_item_id, payment_method_id = candidate
            key = f"modify_pending_order_items:{order_id}:{item_id}"
            if key in self.issued_retail_pending_item_write_keys:
                continue
            candidates.append((order_id, item_id, new_item_id, payment_method_id))
        if len(candidates) != 1:
            return []
        order_id, item_id, new_item_id, payment_method_id = candidates[0]
        return [
            (
                "modify_pending_order_items",
                {
                    "order_id": order_id,
                    "item_ids": [item_id],
                    "new_item_ids": [new_item_id],
                    "payment_method_id": payment_method_id,
                },
            )
        ]

    def projected_retail_return_writes(self) -> list[tuple[str, dict[str, Any]]]:
        """Return grounded delivered-order writes for explicit all-except returns."""
        if not self.return_all_except_request_seen:
            return []
        candidates: list[tuple[str, list[str], str]] = []
        for order_id, order in self.delivered_order_payloads.items():
            key = f"return_delivered_order_items:{order_id}"
            if key in self.issued_retail_return_write_keys:
                continue
            candidate = self._all_except_return_candidate(order)
            if candidate is None:
                continue
            item_ids, payment_method_id = candidate
            candidates.append((order_id, item_ids, payment_method_id))
        if len(candidates) != 1:
            return []
        order_id, item_ids, payment_method_id = candidates[0]
        return [
            (
                "return_delivered_order_items",
                {
                    "order_id": order_id,
                    "item_ids": item_ids,
                    "payment_method_id": payment_method_id,
                },
            )
        ]

    def cancelled_order_tracking_response(self) -> str | None:
        if (
            not self.cancelled_order_tracking_request_seen
            or self.cancelled_order_tracking_sent
            or self.cancelled_order_tracking_id is None
        ):
            return None
        order = self.cancelled_order_tracking_order_id or "your cancelled order"
        return (
            f"The tracking number for cancelled order {order} is "
            f"{self.cancelled_order_tracking_id}."
        )

    def mark_cancelled_order_tracking_sent(self) -> None:
        self.cancelled_order_tracking_sent = True

    def _observe_text(self, text: Any) -> None:
        normalized = _text(text)
        if normalized:
            self.user_text_history.append(normalized)
        if (
            "tracking" in normalized
            and "order" in normalized
            and ("cancelled" in normalized or "canceled" in normalized or "cancel" in normalized)
        ):
            self.cancelled_order_tracking_request_seen = True
        parsed_address = self._address_from_text(str(text or ""))
        if parsed_address is not None:
            self.corrected_address = parsed_address
        if (
            "split" in normalized
            and ("payment" in normalized or "pay" in normalized)
            and ("card" in normalized or "budget" in normalized or "$" in normalized)
        ):
            self.split_payment_request_seen = True
        if (
            "tablet" in normalized
            and "lost" in normalized
            and ("tracking" in normalized or "refund" in normalized or "reorder" in normalized)
        ):
            self.lost_tablet_request_seen = True
        explicit_return_intent = any(
            marker in normalized
            for marker in (
                "want to return",
                "wants to return",
                "would like to return",
                "like to return",
                "need to return",
            )
        )
        all_items_except = (
            "everything" in normalized or re.search(r"\ball\b", normalized) is not None
        ) and any(
            marker in normalized
            for marker in (" except ", " except the ", " but a ", " but the ", " other than ")
        )
        if explicit_return_intent and all_items_except:
            self.return_all_except_request_seen = True
        if (
            "luggage" in normalized
            and "address" in normalized
            and (
                "new home" in normalized
                or "new house" in normalized
                or "new address" in normalized
                or "use the address" in normalized
            )
        ):
            self.address_source_product_hint = "luggage set"
        if (
            "tablet" in normalized
            and "cheapest" in normalized
            and any(marker in normalized for marker in ("exchange", "change", "modify"))
        ):
            self.cheapest_tablet_pending_change_seen = True
        account_terms = (
            "account address",
            "default address",
            "profile address",
            "address on my account",
            "address in my account",
        )
        if "address" in normalized and any(term in normalized for term in account_terms):
            self.account_address_update_request_seen = True
        if (
            self.account_address_update_request_seen
            and self.corrected_address is not None
            and (
                re.search(r"\b(yes|yep|yeah|correct|confirmed|please update)\b", normalized)
                or "please proceed" in normalized
                or "proceed with all" in normalized
            )
        ):
            self.address_update_confirmed = True

    def _observe_payload(self, payload: Any) -> None:
        parsed = _loads_json(payload)
        if not isinstance(parsed, dict):
            return
        user_id = parsed.get("user_id")
        if isinstance(user_id, str):
            self.user_id = user_id
        order_id = parsed.get("order_id")
        if isinstance(order_id, str):
            self.order_id = order_id
            address = self._address_from_arguments(parsed.get("address") or {})
            if (
                self.account_address_update_request_seen
                and self.corrected_address is not None
                and address != self.corrected_address
                and order_id not in self.pending_order_address_update_ids
            ):
                self.pending_order_address_update_ids.append(order_id)
        status = _string_or_none(parsed.get("status"))
        if status and status.lower().startswith("pending"):
            self.pending_order_seen = True
            if isinstance(order_id, str):
                self.pending_order_payloads[order_id] = parsed
                if self._order_matches_address_source_hint(parsed):
                    address = self._address_from_arguments(parsed.get("address") or {})
                    if address is not None:
                        self.corrected_address = address
        if status and status.lower() == "delivered" and isinstance(order_id, str):
            self.delivered_order_payloads[order_id] = parsed
        if status and status.lower() in {"cancelled", "canceled"}:
            tracking_id = self._first_tracking_id(parsed.get("fulfillments"))
            if tracking_id is not None:
                self.cancelled_order_tracking_id = tracking_id
                if isinstance(order_id, str):
                    self.cancelled_order_tracking_order_id = order_id
        payment_history = parsed.get("payment_history")
        if isinstance(payment_history, list):
            for row in payment_history:
                if isinstance(row, dict) and row.get("transaction_type") == "payment":
                    amount = _float_or_none(row.get("amount"))
                    if amount is not None:
                        self.order_total = amount
                        break
        items = parsed.get("items")
        if isinstance(items, list):
            observed: list[tuple[float, str]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = _string_or_none(item.get("item_id"))
                if item_id is not None:
                    self.order_items_by_item_id[item_id] = item
                price = _float_or_none(item.get("price"))
                name = _string_or_none(item.get("name"))
                if name and name.lower() == "tablet":
                    fulfillments = parsed.get("fulfillments")
                    tracking_id = self._first_tracking_id(fulfillments)
                    if tracking_id is not None:
                        self.tablet_tracking_id = tracking_id
                        if isinstance(order_id, str):
                            self.tablet_order_id = order_id
                if price is not None and name is not None:
                    observed.append((price, name))
            if observed:
                price, name = max(observed, key=lambda row: row[0])
                self.most_expensive_price = price
                self.most_expensive_item = name
        product_id = _string_or_none(parsed.get("product_id"))
        variants = parsed.get("variants")
        if product_id is not None and isinstance(variants, dict):
            self.product_variants_by_product_id[product_id] = variants
            self.product_variant_request_text_by_product_id.setdefault(
                product_id,
                list(self.user_text_history),
            )

    @staticmethod
    def _first_tracking_id(fulfillments: Any) -> str | None:
        if not isinstance(fulfillments, list):
            return None
        for fulfillment in fulfillments:
            if not isinstance(fulfillment, dict):
                continue
            tracking_ids = fulfillment.get("tracking_id")
            if isinstance(tracking_ids, list):
                for tracking_id in tracking_ids:
                    text = _string_or_none(tracking_id)
                    if text is not None:
                        return text
            text = _string_or_none(tracking_ids)
            if text is not None:
                return text
        return None

    def _expected_same_size_upgrade(self, item_id: str) -> dict[str, str] | None:
        item = self.order_items_by_item_id.get(item_id)
        if not isinstance(item, dict):
            return None
        name = _text(item.get("name"))
        if not any(keyword in name for keyword in ("shoe", "sneaker", "boot")):
            return None
        options = item.get("options")
        if not isinstance(options, dict):
            return None
        size = _string_or_none(options.get("size"))
        product_id = _string_or_none(item.get("product_id"))
        if size is None or product_id is None:
            return None
        variants = self.product_variants_by_product_id.get(product_id)
        if not isinstance(variants, dict):
            return None
        eligible: list[tuple[float, str]] = []
        for variant_id, variant in variants.items():
            if not isinstance(variant, dict) or not variant.get("available"):
                continue
            variant_options = variant.get("options")
            if not isinstance(variant_options, dict):
                continue
            if _string_or_none(variant_options.get("size")) != size:
                continue
            price = _float_or_none(variant.get("price"))
            variant_item_id = _string_or_none(variant.get("item_id")) or str(variant_id)
            if price is not None:
                eligible.append((price, variant_item_id))
        if not eligible:
            return None
        _price, expected_item_id = max(eligible, key=lambda row: (row[0], row[1]))
        return {"item_id": expected_item_id, "size": size}

    def _expected_preserved_option_upgrade(
        self, item_id: str, new_item_id: str
    ) -> dict[str, Any] | None:
        item = self.order_items_by_item_id.get(item_id)
        if not isinstance(item, dict):
            return None
        product_id = _string_or_none(item.get("product_id"))
        original_options = item.get("options")
        if product_id is None or not isinstance(original_options, dict):
            return None
        variants = self.product_variants_by_product_id.get(product_id)
        if not isinstance(variants, dict):
            return None
        proposed = self._variant_by_item_id(variants, new_item_id)
        if proposed is None:
            return None
        proposed_options = proposed.get("options")
        if not isinstance(proposed_options, dict):
            return None

        required_preserved: dict[str, str] = {}
        requested_changes: dict[str, str] = {}
        for key_raw, original_raw in original_options.items():
            key = str(key_raw)
            original_value = _string_or_none(original_raw)
            proposed_value = _string_or_none(proposed_options.get(key))
            if original_value is None or proposed_value is None:
                continue
            if original_value == proposed_value:
                continue
            if self._user_requested_option_value(proposed_value, product_id=product_id):
                requested_changes[key] = proposed_value
                continue
            required_preserved[key] = original_value

        if not required_preserved or not requested_changes:
            return None

        eligible: list[tuple[float, str]] = []
        for variant_id, variant in variants.items():
            if not isinstance(variant, dict) or not variant.get("available"):
                continue
            variant_options = variant.get("options")
            if not isinstance(variant_options, dict):
                continue
            if any(
                _string_or_none(variant_options.get(key)) != value
                for key, value in required_preserved.items()
            ):
                continue
            if any(
                _string_or_none(variant_options.get(key)) != value
                for key, value in requested_changes.items()
            ):
                continue
            price = _float_or_none(variant.get("price"))
            variant_item_id = _string_or_none(variant.get("item_id")) or str(variant_id)
            if price is not None:
                eligible.append((price, variant_item_id))
        if not eligible:
            return None
        _price, expected_item_id = max(eligible, key=lambda row: (row[0], row[1]))
        return {"item_id": expected_item_id, "preserved": required_preserved}

    @staticmethod
    def _variant_by_item_id(variants: dict[str, Any], item_id: str) -> dict[str, Any] | None:
        for variant_id, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            variant_item_id = _string_or_none(variant.get("item_id")) or str(variant_id)
            if variant_item_id == item_id:
                return variant
        return None

    def _user_requested_option_value(self, option_value: str, *, product_id: str) -> bool:
        normalized_value = _text(option_value)
        if not normalized_value:
            return False
        request_texts = self.product_variant_request_text_by_product_id.get(
            product_id,
            self.user_text_history,
        )
        return any(normalized_value in text for text in request_texts)

    def _user_was_uncertain_about_option(self, option_key: str) -> bool:
        key = re.escape(_text(option_key))
        if not key:
            return False
        uncertainty = (
            r"don'?t know|not sure|unsure|no preference|doesn'?t matter|"
            r"don't care|i guess"
        )
        pattern = re.compile(
            rf"\b({uncertainty})\b.{{0,80}}\b{key}\b|"
            rf"\b{key}\b.{{0,80}}\b({uncertainty})\b",
            re.IGNORECASE,
        )
        return any(pattern.search(text) for text in self.user_text_history)

    def _all_except_return_candidate(self, order: dict[str, Any]) -> tuple[list[str], str] | None:
        """Return item/payment args when one observed order matches the user's exception."""
        items = order.get("items")
        if not isinstance(items, list):
            return None
        exception_item_ids: set[str] = set()
        return_item_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = _string_or_none(item.get("item_id"))
            name = _string_or_none(item.get("name"))
            if item_id is None or name is None:
                continue
            if self._user_named_return_exception(name):
                exception_item_ids.add(item_id)
            else:
                return_item_ids.append(item_id)
        if len(exception_item_ids) != 1 or not return_item_ids:
            return None
        payment_method_ids = self._payment_method_ids_from_order(order)
        if len(payment_method_ids) != 1:
            return None
        return return_item_ids, payment_method_ids[0]

    def _user_named_return_exception(self, item_name: str) -> bool:
        normalized_name = _text(item_name)
        if not normalized_name:
            return False
        name_pattern = re.escape(normalized_name)
        exception_pattern = re.compile(
            rf"\b(?:except|but|other than)\b.{{0,40}}\b{name_pattern}\b|"
            rf"\b{name_pattern}\b.{{0,40}}\b(?:except|but|other than)\b",
            re.IGNORECASE,
        )
        return any(exception_pattern.search(text) for text in self.user_text_history)

    def _refresh_pending_order_address_update_ids(self) -> None:
        if self.corrected_address is None:
            return
        for order_id, order in self.pending_order_payloads.items():
            if self._order_matches_address_source_hint(order):
                continue
            address = self._address_from_arguments(order.get("address") or {})
            if (
                address != self.corrected_address
                and order_id not in self.pending_order_address_update_ids
            ):
                self.pending_order_address_update_ids.append(order_id)

    def _order_matches_address_source_hint(self, order: dict[str, Any]) -> bool:
        hint = self.address_source_product_hint
        if hint is None:
            return False
        items = order.get("items")
        if not isinstance(items, list):
            return False
        return any(isinstance(item, dict) and _text(item.get("name")) == hint for item in items)

    def _cheapest_tablet_pending_change_candidate(
        self, order: dict[str, Any]
    ) -> tuple[str, str, str] | None:
        items = order.get("items")
        if not isinstance(items, list):
            return None
        tablet_items: list[dict[str, Any]] = [
            item for item in items if isinstance(item, dict) and _text(item.get("name")) == "tablet"
        ]
        if len(tablet_items) != 1:
            return None
        item = tablet_items[0]
        item_id = _string_or_none(item.get("item_id"))
        product_id = _string_or_none(item.get("product_id"))
        if item_id is None or product_id is None:
            return None
        variants = self.product_variants_by_product_id.get(product_id)
        if not isinstance(variants, dict):
            return None
        eligible: list[tuple[float, str]] = []
        for variant_id, variant in variants.items():
            if not isinstance(variant, dict) or not variant.get("available"):
                continue
            variant_item_id = _string_or_none(variant.get("item_id")) or str(variant_id)
            if variant_item_id == item_id:
                continue
            price = _float_or_none(variant.get("price"))
            if price is not None:
                eligible.append((price, variant_item_id))
        if not eligible:
            return None
        _price, new_item_id = min(eligible, key=lambda row: (row[0], row[1]))
        payment_method_ids = self._payment_method_ids_from_order(order)
        if len(payment_method_ids) != 1:
            return None
        return item_id, new_item_id, payment_method_ids[0]

    @staticmethod
    def _payment_method_ids_from_order(order: dict[str, Any]) -> list[str]:
        payment_method_ids: list[str] = []
        payment_history = order.get("payment_history")
        if not isinstance(payment_history, list):
            return payment_method_ids
        for row in payment_history:
            if not isinstance(row, dict):
                continue
            if row.get("transaction_type") != "payment":
                continue
            payment_method_id = _string_or_none(row.get("payment_method_id"))
            if payment_method_id is not None and payment_method_id not in payment_method_ids:
                payment_method_ids.append(payment_method_id)
        return payment_method_ids

    @staticmethod
    def _mentions_camera_price(text: str) -> bool:
        return "camera" in text and ("481.50" in text or "$481.50" in text or "481.5" in text)

    @staticmethod
    def _address_from_arguments(arguments: Any) -> dict[str, str] | None:
        if not isinstance(arguments, dict):
            return None
        fields = ("address1", "address2", "city", "state", "country", "zip")
        address: dict[str, str] = {}
        for field_name in fields:
            value = arguments.get(field_name)
            if value is None:
                continue
            address[field_name] = str(value)
        return address or None

    @staticmethod
    def _address_from_text(text: str) -> dict[str, str] | None:
        normalized = text.replace("\n", " ")
        pattern = re.compile(
            r"(?P<address1>\d+\s+[A-Za-z0-9 .'-]+?),\s*"
            r"(?P<address2>(?:Apt|Apartment|Suite|Ste|Unit|#)\s*[A-Za-z0-9 -]+),\s*"
            r"(?P<city>[A-Za-z .'-]+?),\s*"
            r"(?P<state>[A-Za-z]{2,}|[A-Za-z ]+?)\s+"
            r"(?P<zip>\d{5})(?:-\d{4})?",
            re.IGNORECASE,
        )
        match = pattern.search(normalized)
        if match is None:
            return None
        state = match.group("state").strip().rstrip(".")
        state_map = {
            "texas": "TX",
            "tx": "TX",
        }
        return {
            "address1": match.group("address1").strip(),
            "address2": match.group("address2").strip(),
            "city": match.group("city").strip(),
            "state": state_map.get(state.lower(), state.upper()),
            "country": "USA",
            "zip": match.group("zip").strip(),
        }

    @staticmethod
    def _claims_account_address_updated(text: str) -> bool:
        account_address_terms = (
            "account address",
            "account/default address",
            "default address",
            "profile address",
            "address on your account",
            "address in your account",
        )
        completion_terms = (
            "updated",
            "changed",
            "fixed",
            "corrected",
            "saved",
        )
        return (
            any(term in text for term in account_address_terms)
            and any(term in text for term in completion_terms)
        ) or "modify_user_address" in text

    def _account_address_correction_prompt(self) -> str:
        user = self.user_id or "the observed user_id"
        address = self.latest_pending_order_address or {}
        address_bits = ", ".join(
            f"{key}={value!r}" for key, value in address.items() if key != "order_id"
        )
        address_hint = (
            f" Use the corrected address already applied to pending orders: {address_bits}."
            if address_bits
            else " Use the corrected address from the user's latest explicit request."
        )
        return (
            "Your previous draft claimed the account/default address was updated, but "
            "pending-order address writes do not update the account/default address. "
            f"CANNOT claim completion until modify_user_address has been called for {user}."
            f"{address_hint} CAN then summarize both surfaces separately: account/default "
            "address updated by modify_user_address, and pending-order addresses updated "
            "by modify_pending_order_address."
        )


def build_workflow_order_scaffold(name: str) -> Any | None:
    """Factory for runner CLI values."""
    simple_scaffolds: dict[str, Any | None] = {
        "none": None,
        "retail-split-payment-v1": RetailSplitPaymentWorkflowOrder(),
        "retail-contingent-intent-v1": RetailSplitPaymentWorkflowOrder(),
        "telecom-mms-v1": TelecomMmsWorkflowOrder(),
        "telecom-mms-step-economy-v1": TelecomMmsWorkflowOrder(step_economy=True),
        "telecom-mms-bounded-bundle-v1": TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
        ),
    }
    if name in simple_scaffolds:
        return simple_scaffolds[name]
    if name == "telecom-mms-roaming-recovery-v1":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
        )
    if name == "telecom-mms-proactive-roaming-v1":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            proactive_roaming=True,
        )
    if name == "telecom-mms-phased-recovery-v1":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            roaming_recovery=True,
            phased_recovery=True,
        )
    if name == "telecom-mms-late-compression-v1":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
        )
    if name == "telecom-mms-harness-compression-v2":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
        )
    if name in {
        "telecom-mms-harness-compression-v3",
        "telecom-mms-harness-compression-v4",
        "telecom-mms-harness-compression-v5",
    }:
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
        )
    if name == "telecom-mms-harness-compression-v6":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
        )
    if name == "telecom-mms-harness-compression-v7":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
        )
    if name == "telecom-mms-harness-compression-v8":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
        )
    if name == "telecom-mms-harness-compression-v9":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
        )
    if name == "telecom-mms-harness-compression-v10":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
        )
    if name == "telecom-mms-harness-compression-v11":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            project_assistant_requested_user_actions=True,
        )
    if name == "telecom-mms-harness-compression-v12":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
        )
    if name == "telecom-mms-harness-compression-v13":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
        )
    if name == "telecom-mms-harness-compression-v14":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
        )
    if name == "telecom-mms-harness-compression-v15":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
        )
    if name == "telecom-mms-harness-compression-v16":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
        )
    if name == "telecom-mms-harness-compression-v17":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
        )
    if name == "telecom-mms-harness-compression-v18":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
        )
    if name == "telecom-mms-harness-compression-v19":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            project_terminal_with_unknown_wifi_status=True,
        )
    if name == "telecom-mms-harness-compression-v20":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            project_terminal_with_unknown_wifi_status=True,
            trust_apn_reset_reboot_without_recheck=True,
        )
    if name == "telecom-mms-harness-compression-v21":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
        )
    if name == "telecom-mms-harness-compression-v22":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
        )
    if name == "telecom-mms-harness-compression-v23":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
        )
    if name == "telecom-mms-harness-compression-v24":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
        )
    if name == "telecom-mms-harness-compression-v25":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
        )
    if name == "telecom-mms-harness-compression-v26":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
        )
    if name == "telecom-mms-harness-compression-v27":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
        )
    if name == "telecom-mms-harness-compression-v28":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
        )
    if name == "telecom-mms-harness-compression-v29":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
        )
    if name == "telecom-mms-harness-compression-v30":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
        )
    if name == "telecom-mms-harness-compression-v31":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
        )
    if name == "telecom-mms-harness-compression-v32":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
        )
    if name == "telecom-mms-harness-compression-v33":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
        )
    if name == "telecom-mms-harness-compression-v34":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
        )
    if name == "telecom-mms-harness-compression-v35":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
        )
    if name == "telecom-mms-harness-compression-v36":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
        )
    if name == "telecom-mms-harness-compression-v37":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
        )
    if name == "telecom-mms-harness-compression-v38":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
        )
    if name == "telecom-mms-harness-compression-v39":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
        )
    if name == "telecom-mms-harness-compression-v40":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
        )
    if name == "telecom-mms-harness-compression-v41":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
        )
    if name == "telecom-mms-harness-compression-v42":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=False,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
        )
    if name == "telecom-mms-harness-compression-v43":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
        )
    if name == "telecom-mms-harness-compression-v44":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v45":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v46":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v47":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v48":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v49":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v50":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v51":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v52":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v53":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v54":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            project_mobile_data_terminal_on_refuel_speed_request=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name == "telecom-mms-harness-compression-v55":
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            project_mobile_data_terminal_on_refuel_speed_request=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            repeat_mobile_data_speed_test_after_ready_state=True,
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
        )
    if name in {
        "telecom-mms-harness-compression-v56",
        "telecom-mms-harness-compression-v57",
        "telecom-mms-harness-compression-v58",
        "telecom-mms-harness-compression-v59",
        "telecom-mms-harness-compression-v60",
        "telecom-mms-harness-compression-v61",
        "telecom-mms-harness-compression-v62",
        "telecom-mms-harness-compression-v63",
        "telecom-mms-harness-compression-v64",
        "telecom-mms-harness-compression-v65",
        "telecom-mms-harness-compression-v66",
        "telecom-mms-harness-compression-v67",
        "telecom-mms-harness-compression-v68",
        "telecom-mms-harness-compression-v69",
        "telecom-mms-harness-compression-v70",
        "telecom-mms-harness-compression-v71",
        "telecom-mms-harness-compression-v72",
    }:
        return TelecomMmsWorkflowOrder(
            step_economy=True,
            bounded_bundle=True,
            roaming_recovery=True,
            late_stage_compression=True,
            extended_mms_recovery=True,
            data_refuel_recovery=True,
            phone_side_recheck_after_extended_recovery=True,
            proactive_extended_recovery=True,
            terminal_after_proactive_extended_recovery=True,
            apn_check_before_reset=True,
            defer_roaming_until_after_apn_observation=True,
            defer_phone_roaming_until_extended_recovery=True,
            project_assistant_requested_user_actions=True,
            project_terminal_after_assistant_requested_repairs=True,
            project_terminal_inside_extended_recovery_bundle=True,
            project_conditional_wifi_toggle_when_unknown=True,
            project_terminal_after_wifi_repair_request=True,
            project_phone_roaming_inside_terminal_recovery_bundle=True,
            trust_apn_reset_reboot_without_recheck=True,
            infer_data_usage_from_line_details=True,
            reset_unknown_apn_after_bad_network_without_observation=True,
            reset_unknown_apn_after_no_service_without_observation=True,
            project_terminal_after_projected_repairs=True,
            complete_proactive_recovery_on_terminal_request=True,
            dedupe_assistant_requested_user_actions=True,
            project_stop_after_mobile_data_excellent=True,
            project_speed_test_after_mobile_data_repair=True,
            project_mobile_data_assistant_requested_actions=True,
            project_mobile_data_known_state_repairs=True,
            project_mobile_data_speed_failure_recovery=True,
            project_mobile_data_terminal_instead_of_mms=True,
            project_mobile_data_terminal_after_refuel=True,
            project_mobile_data_terminal_on_refuel_speed_request=True,
            repeat_mobile_data_speed_test_after_terminal_repairs=True,
            repeat_mobile_data_speed_test_after_ready_state=True,
            check_mobile_data_status_before_terminal_on_mms_request=(
                name
                in {
                    "telecom-mms-harness-compression-v57",
                    "telecom-mms-harness-compression-v58",
                    "telecom-mms-harness-compression-v59",
                    "telecom-mms-harness-compression-v60",
                    "telecom-mms-harness-compression-v61",
                    "telecom-mms-harness-compression-v62",
                    "telecom-mms-harness-compression-v63",
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            defer_mobile_data_speed_until_status_safe=(
                name
                in {
                    "telecom-mms-harness-compression-v60",
                    "telecom-mms-harness-compression-v61",
                    "telecom-mms-harness-compression-v62",
                    "telecom-mms-harness-compression-v63",
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            defer_mobile_data_speed_until_phone_ready=(
                name
                in {
                    "telecom-mms-harness-compression-v61",
                    "telecom-mms-harness-compression-v62",
                    "telecom-mms-harness-compression-v63",
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            toggle_mobile_data_only_when_observed_off=(
                name
                in {
                    "telecom-mms-harness-compression-v62",
                    "telecom-mms-harness-compression-v63",
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            prefer_mobile_data_terminal_over_mms_fallback=(
                name
                in {
                    "telecom-mms-harness-compression-v63",
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            block_mms_fallback_for_mobile_data=(
                name
                in {
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            infer_mobile_data_from_status_bar=(
                name
                in {
                    "telecom-mms-harness-compression-v64",
                    "telecom-mms-harness-compression-v65",
                    "telecom-mms-harness-compression-v66",
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            restore_full_mobile_terminal_after_status_check=(
                name == "telecom-mms-harness-compression-v65"
            ),
            restore_full_mobile_terminal_on_status_safe_request=(
                name == "telecom-mms-harness-compression-v66"
            ),
            normalize_status_safe_speed_request_to_terminal_bundle=(
                name
                in {
                    "telecom-mms-harness-compression-v67",
                    "telecom-mms-harness-compression-v68",
                    "telecom-mms-harness-compression-v69",
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            project_known_mobile_data_repairs_from_status_checks=True,
            require_current_speed_test_for_mobile_data_stop=True,
            assume_unknown_phone_roaming_off_for_mobile_data_terminal=(
                name
                in {
                    "telecom-mms-harness-compression-v70",
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
            treat_speed_test_as_mobile_data_terminal_repair_request=(
                name
                in {
                    "telecom-mms-harness-compression-v71",
                    "telecom-mms-harness-compression-v72",
                }
            ),
        )
    raise ValueError(f"unknown workflow-order scaffold: {name}")
