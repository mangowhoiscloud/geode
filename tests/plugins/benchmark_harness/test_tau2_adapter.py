import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from plugins.benchmark_harness.tau2_geode_agent import (
    _agent_system_prompt,
    _assert_tau2_route_ready,
    _codex_empty_text_dumps,
    _compose_agent_candidate_surface,
    _load_agent_planner,
    _raise_on_new_codex_empty_text_dumps,
    _trajectory_snapshot_paths,
    _user_system_prompt,
    _write_trajectory_snapshot,
)
from plugins.benchmark_harness.tau2_workflow_order import (
    TelecomMmsWorkflowOrder,
    build_workflow_order_scaffold,
)


def test_tau2_agent_prompt_blocks_inferred_optional_tool_args() -> None:
    prompt = _agent_system_prompt("Policy body")

    assert "leave optional arguments unset" in prompt
    assert "unless the user, the policy, or a prior tool result explicitly supplied" in prompt
    assert "Do not add inferred descriptions" in prompt
    assert "Policy body" in prompt


def test_tau2_agent_prompt_appends_crucible_guard() -> None:
    prompt = _agent_system_prompt(
        "Policy body",
        guard_id="t1",
        guard_text="T1 telecom workflow-completion guard:\nVerify MMS terminal state.",
    )

    assert '<crucible_candidate_guard id="t1">' in prompt
    assert "T1 telecom workflow-completion guard" in prompt
    assert "Verify MMS terminal state." in prompt
    assert prompt.index("<policy>") < prompt.index("<crucible_candidate_guard")


def test_tau2_agent_planner_loads_telecom_mms_sequence() -> None:
    planner_id, planner_text = _load_agent_planner("telecom-mms-v1")

    assert planner_id == "telecom-mms-v1"
    assert "Telecom MMS deterministic planner candidate v1" in planner_text
    assert "toggle_airplane_mode" in planner_text
    assert "reseat_sim_card" in planner_text
    assert "toggle_data" in planner_text
    assert "set_network_mode_preference" in planner_text
    assert "reset_apn_settings" in planner_text
    assert "can_send_mms" in planner_text
    assert planner_text.index("reset_apn_settings") < planner_text.index("can_send_mms")


def test_tau2_agent_candidate_surface_combines_guard_and_planner() -> None:
    candidate_id, candidate_text = _compose_agent_candidate_surface(
        agent_guard="t1",
        guard_text="T1 guard text",
        agent_planner="telecom-mms-v1",
        planner_text="Planner text",
    )

    assert candidate_id == "t1+telecom-mms-v1"
    assert candidate_text == "T1 guard text\n\nPlanner text"


def test_telecom_workflow_order_delays_terminal_verifier() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    assert scaffold.premature_terminal_tool("can_send_mms") is True
    assert "can_send_mms as the terminal verifier" in scaffold.prompt_hint()
    assert "airplane_mode_off" in scaffold.prompt_hint()


def test_telecom_workflow_order_tracks_blocker_outputs() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: ON\n"
            "SIM Card Status: missing\n"
            "Cellular Network Type: 2G\n"
            "Mobile Data Enabled: No"
        ),
    )
    assert scaffold.airplane_off is False
    assert scaffold.sim_active is False
    assert scaffold.mobile_data_on is False
    assert scaffold.non_2g_network is False
    assert scaffold.premature_terminal_tool("can_send_mms") is True

    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")

    assert scaffold.blockers_clear() is True
    assert scaffold.premature_terminal_tool("can_send_mms") is False


def test_telecom_step_economy_scaffold_recommends_safe_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-step-economy-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.step_economy is True
    assert scaffold.bounded_bundle is False
    hint = scaffold.prompt_hint()
    assert "Step-economy scaffold v1" in hint
    assert "toggle_airplane_mode" in hint
    assert "reseat_sim_card" in hint
    assert "toggle_data" in hint
    assert "Keep can_send_mms out of the bundle" in hint


def test_telecom_bounded_bundle_scaffold_limits_user_actions() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-bounded-bundle-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.step_economy is True
    assert scaffold.bounded_bundle is True
    hint = scaffold.prompt_hint()
    assert "Bounded bundle protocol v1" in hint
    assert "The bundle allowlist is exactly" in hint
    assert "Exclude can_send_mms" in hint
    assert "roaming" in hint
    assert "separate can_send_mms terminal verification" in hint


def test_telecom_roaming_recovery_scaffold_opens_after_failed_terminal_mms() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.roaming_recovery is True
    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")

    hint = scaffold.prompt_hint()
    assert "Roaming recovery protocol v1" in hint
    assert "enable_roaming" in hint
    assert "turn_roaming_on" in hint
    assert "Before terminal can_send_mms" in hint


def test_telecom_roaming_recovery_blocks_wifi_branch_until_roaming_repaired() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")

    correction = scaffold.branch_correction_prompt(
        "Next, please check Wi-Fi Calling and messaging app permissions."
    )

    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction
    assert "Do not ask about Wi-Fi calling" in correction


def test_telecom_roaming_recovery_repairs_known_roaming_before_terminal_mms() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")

    hint = scaffold.prompt_hint()
    correction = scaffold.branch_correction_prompt(
        "Great — the prerequisites are clear now. Please run the MMS send check now."
    )

    assert scaffold.roaming_repair_due() is True
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in hint
    assert "Before terminal can_send_mms" in hint
    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_telecom_workflow_order_tracks_user_tool_outputs_without_names() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )
    scaffold.observe_tool_output(
        "",
        "Current APN Name: internet\n"
        "MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc",
    )
    scaffold.observe_tool_output("", "Your messaging app cannot send MMS messages.")

    assert scaffold.blockers_clear() is True
    assert scaffold.mms_failed_after_prereqs is True
    assert scaffold.roaming_repair_due() is True
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in scaffold.prompt_hint()


def test_telecom_phased_recovery_scaffold_advances_small_native_user_phases() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-phased-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.phased_recovery is True
    assert "Phase 1 signal/SIM" in scaffold.prompt_hint()

    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    assert "Phase 2 data/network" in scaffold.prompt_hint()

    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    assert "Phase 3 APN/MMSC" in scaffold.prompt_hint()

    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")
    assert "Phase 4 terminal verifier" in scaffold.prompt_hint()

    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")
    assert "Phase 5 roaming recovery" in scaffold.prompt_hint()


def test_tau2_user_prompt_appends_crucible_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("tau2.user.user_simulator")
    fake_module.get_global_user_sim_guidelines = lambda use_tools: "Guidelines with tools"
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", fake_module)

    prompt = _user_system_prompt(
        "Scenario body",
        use_tools=True,
        append_text="Bundle safe phone actions into one reply.",
    )

    assert "<scenario>" in prompt
    assert "Scenario body" in prompt
    assert "<crucible_user_sim_guard>" in prompt
    assert "Bundle safe phone actions into one reply." in prompt


def test_tau2_route_readiness_rejects_empty_visible_turn() -> None:
    result = SimpleNamespace(text="", termination_reason="completed", rounds=2, tool_calls=[])

    with pytest.raises(RuntimeError, match="route readiness failed"):
        _assert_tau2_route_ready(
            result,
            projected_tool_calls=[],
            role="assistant agent",
        )


def test_tau2_route_readiness_accepts_text_or_projected_tool_call() -> None:
    text_result = SimpleNamespace(text="Done.", termination_reason="completed", rounds=1)
    tool_result = SimpleNamespace(text="", termination_reason="tool_use", rounds=1)

    _assert_tau2_route_ready(text_result, projected_tool_calls=[], role="assistant agent")
    _assert_tau2_route_ready(
        tool_result,
        projected_tool_calls=[object()],
        role="assistant agent",
    )


def test_tau2_codex_empty_text_dump_backstop_detects_new_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path)
    dump_dir = tmp_path / "codex-oauth-empty-text"
    dump_dir.mkdir()
    existing = dump_dir / "1-gpt-5.5.json"
    existing.write_text("{}\n")
    before = _codex_empty_text_dumps()

    (dump_dir / "2-gpt-5.5.json").write_text("{}\n")

    with pytest.raises(RuntimeError, match="empty output_text"):
        _raise_on_new_codex_empty_text_dumps(before)


def test_tau2_trajectory_snapshot_paths_sanitize_run_id() -> None:
    trajectory, snapshot = _trajectory_snapshot_paths(
        Path("snapshots"),
        "crucible/tau2 g2 telecom candidate t1",
    )

    assert trajectory == Path("snapshots/crucible-tau2-g2-telecom-candidate-t1.trajectory.json")
    assert snapshot == Path("snapshots/crucible-tau2-g2-telecom-candidate-t1.snapshot.json")


def test_tau2_trajectory_snapshot_writes_copy_and_metadata(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    run_id = "crucible-tau2-g2-telecom-candidate-t1-openai-sub-gpt55-n2k1-20260706-a"
    results = harness / "data" / "simulations" / run_id / "results.json"
    results.parent.mkdir(parents=True)
    results.write_text('{"simulations": []}\n')

    written = _write_trajectory_snapshot(
        harness_dir=harness,
        snapshot_dir=tmp_path / "snapshots",
        run_id=run_id,
        metadata={"stage": "g2", "agent_guard": "t1"},
    )

    assert written is not None
    trajectory, snapshot = written
    assert trajectory.read_text() == '{"simulations": []}\n'
    assert '"run_id": "crucible-tau2-g2-telecom-candidate-t1' in snapshot.read_text()
    assert '"agent_guard": "t1"' in snapshot.read_text()
