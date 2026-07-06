from pathlib import Path

from scripts.eval.telecom_workflow_gate import GateConfig, evaluate_results


def _assistant(content: str = "ok") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": None}


def _user(content: str = "", calls: list[tuple[str, dict]] | None = None) -> dict:
    return {
        "role": "user",
        "content": content,
        "tool_calls": [
            {"name": name, "arguments": arguments, "requestor": "user"}
            for name, arguments in (calls or [])
        ]
        or None,
    }


def _tool(content: str) -> dict:
    return {"role": "tool", "content": content, "tool_calls": None}


def _write_results(tmp_path: Path, messages: list[dict], termination: str = "user_stop") -> Path:
    path = tmp_path / "results.json"
    path.write_text(
        (
            '{"simulations":[{"task_id":"[mms_issue]case",'
            f'"termination_reason":"{termination}","messages":'
            f"{__import__('json').dumps(messages)}"
            "}]}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_telecom_workflow_gate_passes_ordered_terminal_success(tmp_path: Path) -> None:
    messages = [
        _assistant(),
        _user("mms broken"),
        _assistant("check status"),
        _user(
            calls=[
                ("toggle_airplane_mode", {}),
                ("reseat_sim_card", {}),
                ("toggle_data", {}),
                ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
                ("reset_apn_settings", {}),
                ("check_apn_settings", {}),
                ("can_send_mms", {}),
            ]
        ),
        _tool("Airplane Mode is now OFF."),
        _tool("SIM card re-seated successfully."),
        _tool("Mobile Data is now ON."),
        _tool("Preferred Network Mode set to: 4g_5g_preferred | 5G | Data Enabled"),
        _tool("Current APN Name: internet\nMMSC URL: http://mms.carrier.com/mms/wapenc"),
        _tool("Current APN Name: internet\nMMSC URL: http://mms.carrier.com/mms/wapenc"),
        _tool("Your messaging app can send MMS messages."),
    ]

    rows = evaluate_results(_write_results(tmp_path, messages), config=GateConfig())

    assert rows[0]["verdict"] == "PASS_SURROGATE"
    assert rows[0]["reasons"] == []


def test_telecom_workflow_gate_rejects_premature_terminal_check(tmp_path: Path) -> None:
    messages = [
        _assistant(),
        _user("mms broken"),
        _assistant("try verifier"),
        _user(calls=[("can_send_mms", {})]),
        _tool("Your messaging app cannot send MMS messages."),
    ]

    rows = evaluate_results(_write_results(tmp_path, messages), config=GateConfig())

    assert rows[0]["verdict"] == "REJECT_SURROGATE"
    assert "premature_can_send_mms" in rows[0]["reasons"]


def test_telecom_workflow_gate_rejects_max_steps_without_terminal_success(
    tmp_path: Path,
) -> None:
    messages = [
        _assistant(),
        _user("mms broken"),
        _assistant("reseat sim"),
        _user(calls=[("reseat_sim_card", {})]),
        _tool("SIM card re-seated successfully."),
    ]

    rows = evaluate_results(_write_results(tmp_path, messages, "max_steps"), config=GateConfig())

    assert rows[0]["verdict"] == "REJECT_SURROGATE"
    assert "max_steps" in rows[0]["reasons"]
    assert "missing_terminal_can_send_mms_true" in rows[0]["reasons"]


def test_telecom_workflow_gate_rejects_manual_checklist_before_action(
    tmp_path: Path,
) -> None:
    messages = [
        _assistant(),
        _user("mms broken"),
        _assistant(
            "Please check your phone settings first: confirm airplane mode, mobile data, "
            "SIM status, network mode, APN, and then try sending the picture message."
        ),
        _user("Airplane mode is off and mobile data appears on, but MMS still fails."),
        _assistant("Please restart the phone and try sending MMS again."),
    ]

    rows = evaluate_results(_write_results(tmp_path, messages, "max_steps"), config=GateConfig())

    assert rows[0]["verdict"] == "REJECT_SURROGATE"
    assert "missing_action_before_manual_checklist" in rows[0]["reasons"]
    assert rows[0]["checkpoints"]["first_tool_call_index"] is None
    assert rows[0]["checkpoints"]["first_manual_checklist_index"] == 2


def test_telecom_workflow_gate_allows_manual_checklist_after_action(
    tmp_path: Path,
) -> None:
    messages = [
        _assistant(),
        _user("mms broken"),
        _assistant("I will check account and network status first."),
        _user(calls=[("check_network_status", {})]),
        _tool(
            "Airplane Mode: OFF\n"
            "SIM Card Status: Active\n"
            "Network Type: 5G\n"
            "Mobile Data Enabled: Yes"
        ),
        _assistant("Please check your phone APN settings and try sending MMS after that."),
        _user(calls=[("check_apn_settings", {}), ("can_send_mms", {})]),
        _tool("Current APN Name: internet\nMMSC URL: http://mms.carrier.com/mms/wapenc"),
        _tool("Your messaging app can send MMS messages."),
    ]

    rows = evaluate_results(_write_results(tmp_path, messages), config=GateConfig())

    assert rows[0]["verdict"] == "PASS_SURROGATE"
    assert "missing_action_before_manual_checklist" not in rows[0]["reasons"]
    assert rows[0]["checkpoints"]["first_tool_call_index"] == 3
    assert rows[0]["checkpoints"]["first_manual_checklist_index"] == 5


def test_telecom_workflow_gate_marks_infra_invalid(tmp_path: Path) -> None:
    rows = evaluate_results(
        _write_results(tmp_path, [_assistant()], "infrastructure_error"),
        config=GateConfig(),
    )

    assert rows[0]["verdict"] == "INVALID_INFRA"
    assert rows[0]["reasons"] == ["infrastructure_error"]
