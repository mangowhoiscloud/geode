import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from plugins.benchmark_harness.tau2_geode_agent import (
    _assert_tau2_route_ready,
    _codex_empty_text_dumps,
    _pin_tau2_data_root,
    _raise_on_new_codex_empty_text_dumps,
    _require_contract_snapshot,
    _reserve_contract_run_id,
    _resolve_num_tasks,
    _restore_tau2_data_root,
    _trajectory_snapshot_paths,
    _validate_contract_output_paths,
    _validate_contract_run_args,
    _validate_contract_runtime_policy,
    _validate_tau2_task_order,
    _write_trajectory_snapshot,
)
from plugins.benchmark_harness.tau2_turn_supervisor import (
    GeodeTau2State,
    _agent_system_prompt,
    _message_to_prompt,
    _run_geode_turn,
    _tau2_terminal_token,
    _tau2_tool_calls,
    _Tau2TurnDeadlineError,
    _tool_mutates_state,
    _user_system_prompt,
)
from plugins.crucible.contract import TaskUnit
from plugins.crucible.verifiers.tau2 import tau2_task_unit


def test_tau2_agent_prompt_blocks_inferred_optional_tool_args() -> None:
    prompt = _agent_system_prompt("Policy body")

    assert "CAN leave optional tool arguments unset" in prompt
    assert "unless the user, the policy, or a prior tool result explicitly supplied" in prompt
    assert "CANNOT add inferred descriptions" in prompt
    assert "do not" not in prompt.lower()
    assert "Policy body" in prompt


def test_tau2_message_prompt_normalizes_enum_like_roles() -> None:
    message = SimpleNamespace(
        role=SimpleNamespace(value="tool"),
        content="tool output",
        tool_messages=None,
        tool_calls=None,
    )

    assert _message_to_prompt(message, recipient="assistant") == (
        "Tool result to assistant from tau2 orchestrator:\ntool output"
    )


def test_tau2_explicit_task_pack_runs_every_task_by_default() -> None:
    assert _resolve_num_tasks(["task-1", "task-2", "task-3"], None) == 3
    assert _resolve_num_tasks(None, None) == 1


def test_tau2_explicit_task_pack_rejects_silent_slicing() -> None:
    with pytest.raises(ValueError, match="must equal"):
        _resolve_num_tasks(["task-1", "task-2"], 1)


def test_tau2_explicit_task_pack_rejects_loader_reordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tau2 = ModuleType("tau2")
    fake_registry_module = ModuleType("tau2.registry")
    fake_helpers = ModuleType("tau2.runner.helpers")
    fake_registry_module.registry = SimpleNamespace(get_agent_task_filter=lambda _agent: None)
    fake_helpers.get_tasks = lambda **_kwargs: [
        SimpleNamespace(id="task-A"),
        SimpleNamespace(id="task-B"),
    ]
    monkeypatch.setitem(sys.modules, "tau2", fake_tau2)
    monkeypatch.setitem(sys.modules, "tau2.registry", fake_registry_module)
    monkeypatch.setitem(sys.modules, "tau2.runner.helpers", fake_helpers)
    config = SimpleNamespace(
        task_ids=["task-B", "task-A"],
        task_set_name="retail",
        domain="retail",
        task_split_name="base",
        effective_agent="geode_agent",
    )

    with pytest.raises(ValueError, match="loader order"):
        _validate_tau2_task_order(config)


def test_tau2_explicit_task_pack_rejects_loaded_content_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_task = {
        "id": "task-A",
        "description": {"purpose": "actual"},
        "evaluation_criteria": {"actions": [{"name": "lookup"}]},
        "user_tools": None,
    }
    loaded = SimpleNamespace(
        id="task-A",
        model_dump=lambda **_kwargs: raw_task,
    )
    fake_tau2 = ModuleType("tau2")
    fake_registry_module = ModuleType("tau2.registry")
    fake_helpers = ModuleType("tau2.runner.helpers")
    fake_registry_module.registry = SimpleNamespace(get_agent_task_filter=lambda _agent: None)
    fake_helpers.get_tasks = lambda **_kwargs: [loaded]
    monkeypatch.setitem(sys.modules, "tau2", fake_tau2)
    monkeypatch.setitem(sys.modules, "tau2.registry", fake_registry_module)
    monkeypatch.setitem(sys.modules, "tau2.runner.helpers", fake_helpers)
    config = SimpleNamespace(
        task_ids=["task-A"],
        task_set_name="retail",
        domain="retail",
        task_split_name="base",
        effective_agent="geode_agent",
    )
    actual = tau2_task_unit(raw_task)
    contract = SimpleNamespace(
        tasks=(TaskUnit(actual.task_id, actual.family_id, "0" * 64),),
    )

    with pytest.raises(ValueError, match="loaded task identities"):
        _validate_tau2_task_order(config, contract)


def test_tau2_explicit_task_pack_accepts_exact_loaded_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_task = {
        "id": "task-A",
        "description": {"purpose": "actual"},
        "evaluation_criteria": {"actions": [{"name": "lookup"}]},
        "user_tools": None,
    }
    loaded = SimpleNamespace(
        id="task-A",
        model_dump=lambda **_kwargs: raw_task,
    )
    fake_tau2 = ModuleType("tau2")
    fake_registry_module = ModuleType("tau2.registry")
    fake_helpers = ModuleType("tau2.runner.helpers")
    fake_registry_module.registry = SimpleNamespace(get_agent_task_filter=lambda _agent: None)
    fake_helpers.get_tasks = lambda **_kwargs: [loaded]
    monkeypatch.setitem(sys.modules, "tau2", fake_tau2)
    monkeypatch.setitem(sys.modules, "tau2.registry", fake_registry_module)
    monkeypatch.setitem(sys.modules, "tau2.runner.helpers", fake_helpers)
    config = SimpleNamespace(
        task_ids=["task-A"],
        task_set_name="retail",
        domain="retail",
        task_split_name="base",
        effective_agent="geode_agent",
    )
    contract = SimpleNamespace(tasks=(tau2_task_unit(raw_task),))

    _validate_tau2_task_order(config, contract)


def test_tau2_data_root_ignores_ambient_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = tmp_path / "harness"
    harness.mkdir()
    monkeypatch.setenv("TAU2_DATA_DIR", str(tmp_path / "ambient"))

    expected, previous = _pin_tau2_data_root(harness)

    assert expected == harness / "data"
    assert os.environ["TAU2_DATA_DIR"] == str(expected)
    _restore_tau2_data_root(previous)
    assert os.environ["TAU2_DATA_DIR"] == str(tmp_path / "ambient")


def test_tau2_tool_mutability_uses_upstream_marker_and_fails_safe() -> None:
    read_tool = SimpleNamespace(
        name="unconventional_query",
        _func=SimpleNamespace(__mutates_state__=False),
    )
    write_tool = SimpleNamespace(
        name="get_but_mutate",
        _func=SimpleNamespace(__mutates_state__=True),
    )

    assert _tool_mutates_state(read_tool) is False
    assert _tool_mutates_state(write_tool) is True
    assert _tool_mutates_state(SimpleNamespace(name="get_unknown")) is True


@pytest.mark.parametrize("tool_name", ["modify_user_address", "future_required_empty"])
def test_tau2_tool_calls_preserves_explicit_empty_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    fake_tau2 = ModuleType("tau2")
    fake_data_model = ModuleType("tau2.data_model")
    fake_message = ModuleType("tau2.data_model.message")
    fake_message.ToolCall = SimpleNamespace
    monkeypatch.setitem(sys.modules, "tau2", fake_tau2)
    monkeypatch.setitem(sys.modules, "tau2.data_model", fake_data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.message", fake_message)
    result = SimpleNamespace(
        tool_calls=[
            {
                "tool_use_id": "call_1",
                "tool": tool_name,
                "input": {"address1": "123 Main St", "address2": ""},
                "result": None,
            }
        ]
    )

    calls = _tau2_tool_calls(result, requestor="assistant")

    assert calls[0].arguments["address2"] == ""


def test_tau2_tool_projection_is_scoped_to_each_agentic_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tau2 = ModuleType("tau2")
    fake_data_model = ModuleType("tau2.data_model")
    fake_message = ModuleType("tau2.data_model.message")
    fake_message.ToolCall = SimpleNamespace
    monkeypatch.setitem(sys.modules, "tau2", fake_tau2)
    monkeypatch.setitem(sys.modules, "tau2.data_model", fake_data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.message", fake_message)
    first = SimpleNamespace(
        tool_calls=[
            {
                "tool_use_id": "call_1",
                "tool": "lookup_account",
                "input": {"account_id": "A"},
                "result": {"ok": True},
            }
        ]
    )
    second = SimpleNamespace(
        tool_calls=[
            {
                "tool_use_id": "call_2",
                "tool": "reset_settings",
                "input": {"account_id": "A"},
                "result": {"ok": True},
            },
        ]
    )

    first_calls = _tau2_tool_calls(first, requestor="assistant")
    second_calls = _tau2_tool_calls(second, requestor="assistant")

    assert [call.id for call in first_calls] == ["call_1"]
    assert [call.id for call in second_calls] == ["call_2"]


def test_tau2_progress_supervisor_maps_only_generic_repeated_success() -> None:
    assert (
        _tau2_terminal_token(SimpleNamespace(termination_reason="repeated_success_no_progress"))
        == "###STOP###"
    )
    assert _tau2_terminal_token(SimpleNamespace(termination_reason="max_rounds")) is None


def test_tau2_external_deadline_stops_before_an_expired_participant_call() -> None:
    loop = SimpleNamespace(arun=lambda _prompt: None)
    state = GeodeTau2State(loop=loop, deadline_at=0.0)

    with pytest.raises(_Tau2TurnDeadlineError, match="deadline elapsed"):
        _run_geode_turn(state, "next turn")


def test_tau2_contract_run_must_match_frozen_identity_axes() -> None:
    assay_config = {
        "schema": "crucible.tau2-assay.v1",
        "max_concurrency": 1,
        "timeout": 600.0,
        "agent": {"implementation": "geode_agent", "max_rounds": 0},
        "user": {
            "implementation": "user_simulator",
            "runtime_owner": "evaluator",
            "max_rounds": 0,
        },
    }
    contract = SimpleNamespace(
        stage="test",
        agent_route="openai-subscription-gpt-5.5-high",
        user_route="tau2-user_simulator-gpt-5.2",
        task_ids=("task-1", "task-2"),
        trials_per_task=1,
        assay_config=assay_config,
        evaluator_paths=("plugins/benchmark_harness", "plugins/crucible"),
    )

    _validate_contract_run_args(
        contract,
        stage="test",
        agent_route="openai-subscription-gpt-5.5-high",
        user_route="tau2-user_simulator-gpt-5.2",
        task_ids=["task-1", "task-2"],
        num_tasks=2,
        num_trials=1,
        assay_config=assay_config,
    )

    with pytest.raises(ValueError, match="ordered --task-ids"):
        _validate_contract_run_args(
            contract,
            stage="test",
            agent_route="openai-subscription-gpt-5.5-high",
            user_route="tau2-user_simulator-gpt-5.2",
            task_ids=["task-2", "task-1"],
            num_tasks=2,
            num_trials=1,
            assay_config=assay_config,
        )

    drifted_assay = {**assay_config, "domain": "telecom"}
    with pytest.raises(ValueError, match="resolved tau2 assay config"):
        _validate_contract_run_args(
            contract,
            stage="test",
            agent_route="openai-subscription-gpt-5.5-high",
            user_route="tau2-user_simulator-gpt-5.2",
            task_ids=["task-1", "task-2"],
            num_tasks=2,
            num_trials=1,
            assay_config=drifted_assay,
        )

    contract.evaluator_paths = ("README.md",)
    with pytest.raises(ValueError, match="measurement bundle"):
        _validate_contract_run_args(
            contract,
            stage="test",
            agent_route="openai-subscription-gpt-5.5-high",
            user_route="tau2-user_simulator-gpt-5.2",
            task_ids=["task-1", "task-2"],
            num_tasks=2,
            num_trials=1,
            assay_config=assay_config,
        )


def test_tau2_contract_run_rejects_runtime_candidate_knobs() -> None:
    args = SimpleNamespace(
        agent_max_rounds=0,
        max_retries=0,
        user_max_rounds=0,
        user="user_simulator",
        allow_empty_geode_turn=False,
        auto_resume=False,
        disable_codex_output_replay=False,
        disable_tool_search_defer=False,
        enable_cognitive_reflection=False,
        no_trajectory_snapshot=False,
        save_to="crucible-test-run",
    )

    _validate_contract_runtime_policy(args)

    args.max_retries = 1
    with pytest.raises(ValueError, match="code-only runtime policy"):
        _validate_contract_runtime_policy(args)

    args.max_retries = 0
    args.agent_max_rounds = 1
    with pytest.raises(ValueError, match="--agent-max-rounds=0"):
        _validate_contract_runtime_policy(args)


def test_tau2_user_prompt_contains_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("tau2.user.user_simulator")
    fake_module.get_global_user_sim_guidelines = lambda use_tools: "Guidelines with tools"
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", fake_module)

    prompt = _user_system_prompt(
        "Scenario body",
        use_tools=True,
    )

    assert "<scenario>" in prompt
    assert "Scenario body" in prompt


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


def test_tau2_codex_empty_text_dump_backstop_accepts_recovered_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path)
    dump_dir = tmp_path / "codex-oauth-empty-text"
    dump_dir.mkdir()
    before = _codex_empty_text_dumps()
    recovered = dump_dir / "2-gpt-5.5.json"
    recovered.write_text("{}\n")
    Path(f"{recovered}.recovered").touch()

    _raise_on_new_codex_empty_text_dumps(before)


def test_tau2_codex_empty_text_dump_backstop_accepts_actionable_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path)
    dump_dir = tmp_path / "codex-oauth-empty-text"
    dump_dir.mkdir()
    before = _codex_empty_text_dumps()
    actionable = dump_dir / "2-gpt-5.5.json"
    actionable.write_text("{}\n")
    Path(f"{actionable}.actionable").touch()

    _raise_on_new_codex_empty_text_dumps(before)


def test_tau2_trajectory_snapshot_paths_sanitize_run_id() -> None:
    trajectory, snapshot = _trajectory_snapshot_paths(
        Path("snapshots"),
        "crucible/tau2 train telecom candidate",
    )

    assert trajectory == Path("snapshots/crucible-tau2-train-telecom-candidate.trajectory.json")
    assert snapshot == Path("snapshots/crucible-tau2-train-telecom-candidate.snapshot.json")


def test_tau2_trajectory_snapshot_writes_copy_and_metadata(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    run_id = "crucible-tau2-train-telecom-candidate-openai-sub-gpt55-n2k1-20260710-a"
    results = harness / "data" / "simulations" / run_id / "results.json"
    results.parent.mkdir(parents=True)
    results.write_text('{"simulations": []}\n')

    written = _write_trajectory_snapshot(
        harness_dir=harness,
        snapshot_dir=tmp_path / "snapshots",
        run_id=run_id,
        metadata={"stage": "train", "candidate_surface": "git"},
    )

    assert written is not None
    trajectory, snapshot = written
    assert trajectory.read_text() == '{"simulations": []}\n'
    assert '"run_id": "crucible-tau2-train-telecom-candidate' in snapshot.read_text()
    assert '"candidate_surface": "git"' in snapshot.read_text()


def test_tau2_contract_run_requires_durable_snapshot() -> None:
    with pytest.raises(RuntimeError, match="did not produce"):
        _require_contract_snapshot(SimpleNamespace(), None)


def test_tau2_contract_run_requires_fresh_path_free_output(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    snapshots = tmp_path / "snapshots"

    _validate_contract_output_paths(
        harness_dir=harness,
        snapshot_dir=snapshots,
        run_id="crucible-train-001",
    )
    reserved = _reserve_contract_run_id(harness, "crucible-train-001")
    assert reserved.is_dir()

    with pytest.raises(ValueError, match="must be fresh"):
        _validate_contract_output_paths(
            harness_dir=harness,
            snapshot_dir=snapshots,
            run_id="crucible-train-001",
        )
    with pytest.raises(ValueError, match="already reserved"):
        _reserve_contract_run_id(harness, "crucible-train-001")
    with pytest.raises(ValueError, match="path-free"):
        _validate_contract_output_paths(
            harness_dir=harness,
            snapshot_dir=snapshots,
            run_id="../mixed-run",
        )
