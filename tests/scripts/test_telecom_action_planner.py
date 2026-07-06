import json

from scripts.eval.telecom_action_planner import (
    MmsState,
    demo_mms_success_results,
    plan_mms_actions,
    run_demo,
)
from scripts.eval.telecom_workflow_gate import GateConfig, evaluate_results


def test_planner_bundles_blockers_without_premature_verifier() -> None:
    actions = plan_mms_actions(
        MmsState(
            airplane_mode_on=True,
            sim_active=False,
            mobile_data_on=False,
            network_type="2G",
            apn_mmsc_configured=False,
        )
    )

    assert [action.name for action in actions] == [
        "toggle_airplane_mode",
        "reseat_sim_card",
        "toggle_data",
        "set_network_mode_preference",
        "reset_apn_settings",
        "reboot_device",
        "check_apn_settings",
    ]
    assert "can_send_mms" not in {action.name for action in actions}


def test_planner_verifies_only_after_blockers_clear() -> None:
    actions = plan_mms_actions(
        MmsState(
            airplane_mode_on=False,
            sim_active=True,
            mobile_data_on=True,
            network_type="5G",
            apn_mmsc_configured=True,
            can_send_mms=False,
        )
    )

    assert [action.name for action in actions] == ["can_send_mms"]


def test_planner_synthetic_success_passes_surrogate(tmp_path) -> None:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(demo_mms_success_results()), encoding="utf-8")

    rows = evaluate_results(path, config=GateConfig())

    assert rows[0]["verdict"] == "PASS_SURROGATE"
    assert rows[0]["reasons"] == []


def test_run_demo_writes_plan_and_synthetic_results(tmp_path) -> None:
    output = tmp_path / "plan.json"

    payload = run_demo(output)

    assert output.exists()
    assert payload["metadata"]["schema"] == "crucible_telecom_action_plan.v1"
    assert payload["planned_actions"][0]["name"] == "toggle_airplane_mode"
