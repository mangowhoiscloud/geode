import asyncio
import contextlib
import hashlib
import json
import os
import site
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from plugins.benchmark_harness.tau2_geode_agent import (
    REPO_ROOT,
    _assert_tau2_route_ready,
    _build_loop,
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
from plugins.benchmark_harness.tau2_lane1a_preflight import (
    _attest_tau2_resets,
    _model_visible_tau2_tool_schemas,
    _tau2_import_origins,
    _tau2_native_user_prompt_hashes,
    _tau2_producer_identity,
    _tau2_runtime_identity,
    _write_tau2_lane1a_preflight_receipt,
)
from plugins.benchmark_harness.tau2_runtime_contract import (
    Tau2AttemptTracker,
    Tau2RuntimeContract,
)
from plugins.benchmark_harness.tau2_tool_bridge import Tau2GeodeTool
from plugins.benchmark_harness.tau2_turn_supervisor import (
    GeodeTau2State,
    _agent_system_prompt,
    _message_to_prompt,
    _record_tau2_tool_results,
    _remember_tau2_tool_calls,
    _run_geode_turn,
    _tau2_terminal_token,
    _tau2_tool_calls,
    _Tau2TurnDeadlineError,
    _tool_mutates_state,
    _user_system_prompt,
)
from plugins.benchmark_harness.trajectory_artifacts import (
    geode_trajectory_snapshot_path,
    tau2_session_ids,
)
from plugins.crucible.contract import ContractError, TaskUnit
from plugins.crucible.verifiers.tau2 import tau2_task_unit


def test_tau2_agent_prompt_blocks_inferred_optional_tool_args() -> None:
    prompt = _agent_system_prompt("Policy body")

    assert "CAN leave optional tool arguments unset" in prompt
    assert "unless the user, the policy, or a prior tool result explicitly supplied" in prompt
    assert "CANNOT add inferred descriptions" in prompt
    assert "do not" not in prompt.lower()
    assert "Policy body" in prompt


def test_tau2_loop_reuses_one_process_owned_hook_and_middleware_registry(
    tmp_path: Path,
) -> None:
    from core.llm.adapters.registry import bootstrap_builtins

    bootstrap_builtins()
    runtime = Tau2RuntimeContract(
        run_id="shared-runtime",
        repo_root=Path.cwd(),
        agent_route={},
        user_route={},
        runtime_profile="tau2-native-user",
        event_db_path=tmp_path / "events.db",
    )
    try:
        loop = _build_loop(
            tools=[],
            system_prompt="Agent: runtime contract test",
            model="gpt-5.5",
            provider="openai",
            source="subscription",
            effort="high",
            time_budget_s=1.0,
            max_tokens=32,
            max_rounds=0,
            runtime_contract=runtime,
        )

        assert loop._hook_registry is runtime.hook_registry
        assert loop._middleware_registry is runtime.middleware_registry
        assert loop.executor.hook_registry is runtime.hook_registry
        assert loop.executor.middleware_registry is runtime.middleware_registry
    finally:
        runtime.close()


def test_tau2_attempt_tracker_preserves_retry_lineage_and_final_selection() -> None:
    tracker = Tau2AttemptTracker("retry-run")
    calls = 0

    def run_fn() -> SimpleNamespace:
        nonlocal calls
        calls += 1
        tracker.register_session(
            participant_role="assistant",
            session_id=f"session-{calls}",
        )
        if calls == 1:
            raise RuntimeError("first attempt failed")
        return SimpleNamespace(id="simulation-final")

    def retry_once(fn, _task, _trial, _seed, **_kwargs):
        with contextlib.suppress(RuntimeError):
            fn()
        return fn()

    result = tracker.wrap(retry_once)(
        run_fn,
        SimpleNamespace(id="task-1"),
        0,
        300,
    )
    manifest = tracker.manifest()

    assert result.id == "simulation-final"
    assert [row["status"] for row in manifest["attempts"]] == ["error", "complete"]
    assert manifest["attempts"][1]["retry_of"] == manifest["attempts"][0]["attempt_id"]
    assert manifest["attempts"][1]["selected_final"] is True
    assert manifest["final_results"] == [
        {
            "task_id": "task-1",
            "trial": 0,
            "simulation_id": "simulation-final",
            "selected_attempt_id": manifest["attempts"][1]["attempt_id"],
            "selection_status": "selected",
        }
    ]


def test_tau2_attempt_tracker_selects_only_after_upstream_accepts_result() -> None:
    tracker = Tau2AttemptTracker("post-run-retry")
    calls = 0

    def run_fn() -> SimpleNamespace:
        nonlocal calls
        calls += 1
        tracker.register_session(
            participant_role="assistant",
            session_id=f"post-run-session-{calls}",
        )
        return SimpleNamespace(id=f"simulation-{calls}")

    def retry_after_checkpoint_failure(fn, _task, _trial, _seed, **_kwargs):
        fn()
        return fn()

    tracker.wrap(retry_after_checkpoint_failure)(
        run_fn,
        SimpleNamespace(id="task-1"),
        0,
        300,
    )
    attempts = tracker.manifest()["attempts"]

    assert attempts[0]["status"] == "error"
    assert attempts[0]["selected_final"] is False
    assert attempts[0]["retry_reason"] == "upstream post-run failure before selection"
    assert attempts[1]["retry_of"] == attempts[0]["attempt_id"]
    assert attempts[1]["selected_final"] is True


def test_tau2_attempt_tracker_downgrades_final_post_run_failure() -> None:
    tracker = Tau2AttemptTracker("final-post-run-failure")

    def run_fn() -> SimpleNamespace:
        tracker.register_session(participant_role="assistant", session_id="session-1")
        return SimpleNamespace(id="simulation-real")

    def exhausted_after_checkpoint_failure(fn, _task, _trial, _seed, **_kwargs):
        fn()
        return SimpleNamespace(id="simulation-infrastructure-placeholder")

    tracker.wrap(exhausted_after_checkpoint_failure)(
        run_fn,
        SimpleNamespace(id="task-1"),
        0,
        300,
    )
    manifest = tracker.manifest()

    assert manifest["attempts"][0]["status"] == "error"
    assert manifest["attempts"][0]["retry_reason"] == ("upstream post-run failure before selection")
    assert manifest["final_results"][0]["selection_status"] == "no_successful_attempt"


def test_tau2_native_verdict_is_recorded_before_session_close(tmp_path: Path) -> None:
    from core.hooks import LlmCallRequest
    from core.llm.adapters.base import AdapterCallRequest, ToolSpec

    evidence: list[dict[str, object]] = []

    class Timeline:
        db_path = tmp_path / "sessions.db"

        def record_verification_evidence(
            self,
            references: list[dict[str, object]],
            *,
            root_turn_id: str,
            verify_attempt: int,
            policy_action: str,
        ) -> None:
            evidence.append(
                {
                    "references": references,
                    "root_turn_id": root_turn_id,
                    "verify_attempt": verify_attempt,
                    "policy_action": policy_action,
                }
            )

    runtime = Tau2RuntimeContract(
        run_id="native-verdict-run",
        repo_root=Path.cwd(),
        agent_route={},
        user_route={},
        runtime_profile="tau2-native-user",
        event_db_path=tmp_path / "events.db",
    )
    loop = SimpleNamespace(
        _session_id="session-agent",
        _timeline=Timeline(),
        _turn_id="turn-final",
        _tau2_pending_tool_calls={},
    )

    def execute() -> SimpleNamespace:
        runtime.register_loop(loop, participant_role="assistant")
        return SimpleNamespace(id="simulation-1")

    def no_retry(fn, _task, _trial, _seed, **_kwargs):
        return fn()

    runtime.attempts.wrap(no_retry)(
        execute,
        SimpleNamespace(id="task-1"),
        0,
        300,
    )
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "id": "simulation-1",
                        "task_id": "task-1",
                        "trial": 0,
                        "termination_reason": "user_stop",
                        "reward_info": {"reward": 0.0},
                        "messages": [
                            {
                                "raw_data": {
                                    "geode_session_id": "session-agent",
                                    "geode_termination_reason": "completed",
                                }
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        runtime.bind_native_results(results, classify_termination=lambda _reason: "semantic")
        asyncio.run(
            runtime.capture.llm_request(
                LlmCallRequest(
                    adapter=SimpleNamespace(),
                    request=AdapterCallRequest(
                        model="gpt-5.4",
                        messages=(),
                        system_prompt=(
                            "Agent: test\n__GEODE_PROMPT_CACHE_BOUNDARY__\n"
                            "<dynamic_context><policy>bounded</policy></dynamic_context>"
                        ),
                        tools=(
                            ToolSpec(
                                name="lookup_account",
                                description="lookup",
                                input_schema={"type": "object"},
                            ),
                        ),
                    ),
                    correlation={"session_id": "session-agent"},
                )
            )
        )
        profile_path, manifest_path = runtime.write_companions(tmp_path / "snapshots")

        reference = evidence[0]["references"][0]
        assert reference["reward"] == 0.0
        assert reference["validity"] == "semantic"
        assert reference["native_termination_reason"] == "user_stop"
        assert reference["runtime_termination_reason"] == "completed"
        assert evidence[0]["policy_action"] == "observe_native_verdict"
        profile = json.loads(profile_path.read_text())
        request = profile["assembled_requests"][0]
        assert request["assembled_prompt_sha256"]
        assert request["prompt_block_inventory"]["cache_boundary_present"] is True
        assert {row["name"] for row in request["prompt_block_inventory"]["xml_tags"]} == {
            "dynamic_context",
            "policy",
        }
        assert request["tool_schema_sha256"]
        assert request["tool_allowlist"] == ["lookup_account"]
        assert all(row["status"] != "passed" for row in profile["surfaces"]["public_hooks"])
        assert json.loads(manifest_path.read_text())["final_results"][0]["selected_attempt_id"]
    finally:
        runtime.close()


def test_tau2_native_verdict_reconciles_terminal_tool_result(tmp_path: Path) -> None:
    recorded: list[dict[str, object]] = []

    class Timeline:
        db_path = tmp_path / "sessions.db"

        def record_tool_result(self, *args: object, **kwargs: object) -> None:
            recorded.append({"args": args, "kwargs": kwargs})

        def record_verification_evidence(self, *_args: object, **_kwargs: object) -> None:
            pass

    runtime = Tau2RuntimeContract(
        run_id="terminal-tool-run",
        repo_root=Path.cwd(),
        agent_route={},
        user_route={},
        runtime_profile="tau2-native-user",
        event_db_path=tmp_path / "events.db",
    )
    loop = SimpleNamespace(
        _session_id="session-agent",
        _timeline=Timeline(),
        _turn_id="turn-final",
        _tau2_pending_tool_calls={"call-final": "lookup_account"},
    )

    def execute() -> SimpleNamespace:
        runtime.register_loop(loop, participant_role="assistant")
        return SimpleNamespace(id="simulation-1")

    runtime.attempts.wrap(lambda fn, *_args, **_kwargs: fn())(
        execute,
        SimpleNamespace(id="task-1"),
        0,
        300,
    )
    results = tmp_path / "terminal-results.json"
    results.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "id": "simulation-1",
                        "task_id": "task-1",
                        "trial": 0,
                        "termination_reason": "too_many_errors",
                        "messages": [
                            {"raw_data": {"geode_session_id": "session-agent"}},
                            {
                                "role": "tool",
                                "id": "call-final",
                                "requestor": "assistant",
                                "content": "failed",
                                "error": True,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        runtime.bind_native_results(results, classify_termination=lambda _reason: "semantic")
    finally:
        runtime.close()

    assert loop._tau2_pending_tool_calls == {}
    assert recorded[0]["kwargs"]["call_id"] == "call-final"
    assert recorded[0]["args"][:2] == ("lookup_account", "error")


def test_tau2_auto_resume_marks_prior_native_rows_unattested(tmp_path: Path) -> None:
    runtime = Tau2RuntimeContract(
        run_id="resume-run",
        repo_root=Path.cwd(),
        agent_route={},
        user_route={},
        runtime_profile="tau2-native-user",
        event_db_path=tmp_path / "events.db",
        allow_resumed_native=True,
    )
    results = tmp_path / "resumed-results.json"
    results.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "id": "simulation-old",
                        "task_id": "task-old",
                        "trial": 0,
                        "termination_reason": "user_stop",
                        "messages": [{"raw_data": {"geode_session_id": "prior-process-session"}}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        runtime.bind_native_results(results, classify_termination=lambda _reason: "semantic")
        manifest = runtime.attempts.manifest()
    finally:
        runtime.close()

    assert manifest["resumed_results"] == [
        {
            "task_id": "task-old",
            "trial": 0,
            "simulation_id": "simulation-old",
            "session_ids": ["prior-process-session"],
            "selection_status": "resumed_native_unattested",
        }
    ]


def test_tau2_runtime_contract_flags_infrastructure_receipt(tmp_path: Path) -> None:
    runtime = Tau2RuntimeContract(
        run_id="infrastructure-run",
        repo_root=Path.cwd(),
        agent_route={},
        user_route={},
        runtime_profile="tau2-native-user",
        event_db_path=tmp_path / "events.db",
        allow_resumed_native=True,
    )
    results = tmp_path / "infrastructure-results.json"
    results.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "id": "simulation-infra",
                        "task_id": "task-infra",
                        "trial": 0,
                        "termination_reason": "infrastructure_error",
                        "messages": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        runtime.bind_native_results(
            results,
            classify_termination=lambda _reason: "infra",
        )
        assert runtime.infrastructure_contaminated is True
    finally:
        runtime.close()


def test_tau2_message_prompt_normalizes_enum_like_roles() -> None:
    message = SimpleNamespace(
        role=SimpleNamespace(value="tool"),
        content="tool output",
        tool_messages=None,
        tool_calls=None,
    )

    rendered = _message_to_prompt(message, recipient="assistant")

    assert rendered.startswith("Tool result to assistant from tau2 orchestrator:\n")
    assert json.loads(rendered.split("\n", 1)[1]) == {
        "id": "",
        "requestor": "",
        "content": "tool output",
        "error": False,
    }


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


def test_tau2_preflight_attests_agent_and_user_db_reset_isolation() -> None:
    class FakeDB:
        def __init__(self, value: str) -> None:
            self.rows = {"record": {"value": value}}

        def get_hash(self) -> str:
            return hashlib.sha256(json.dumps(self.rows, sort_keys=True).encode("utf-8")).hexdigest()

    class FakeEnvironment:
        def __init__(self) -> None:
            self.tools = SimpleNamespace(db=FakeDB("agent-source"))
            self.user_tools = SimpleNamespace(db=FakeDB("user-source"))

        def get_db_hash(self) -> str:
            return self.tools.db.get_hash()

        def get_user_db_hash(self) -> str:
            return self.user_tools.db.get_hash()

        def set_state(
            self,
            initialization_data: object,
            initialization_actions: object,
            message_history: object,
        ) -> None:
            assert initialization_actions is None
            assert message_history == []
            self.tools.db.rows["task"] = initialization_data.agent_data
            self.user_tools.db.rows["task"] = initialization_data.user_data

    task = SimpleNamespace(
        id="task-1",
        initial_state=SimpleNamespace(
            initialization_data=SimpleNamespace(agent_data="agent-1", user_data="user-1"),
            initialization_actions=None,
            message_history=None,
        ),
    )

    receipt = _attest_tau2_resets("telecom", [task], FakeEnvironment)

    row = receipt["task_initial_states"][0]
    assert receipt["fresh_environment_count"] == 4
    assert row["guard_after_probe"] == row["initialized"] == row["rebuilt"]
    assert row["mutated_probe"]["agent_db_sha256"] != row["initialized"]["agent_db_sha256"]
    assert row["mutated_probe"]["user_db_sha256"] != row["initialized"]["user_db_sha256"]


def test_tau2_preflight_hashes_actual_native_user_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_build = ModuleType("tau2.runner.build")
    fake_build.build_user = lambda _name, _env, task, **_kwargs: SimpleNamespace(
        system_prompt=f"tools-guideline::{task.id}",
        global_simulation_guidelines="tools-guideline",
        tools=[SimpleNamespace(openai_schema={"type": "function", "name": "fake_tool"})],
    )
    monkeypatch.setitem(sys.modules, "tau2.runner.build", fake_build)
    tasks = [SimpleNamespace(id="task-1"), SimpleNamespace(id="task-2")]

    receipt = _tau2_native_user_prompt_hashes(tasks, object)

    assert receipt["authority"] == "build_user(...).system_prompt"
    assert (
        receipt["task_system_prompts"][0]["system_prompt_sha256"]
        == hashlib.sha256(b"tools-guideline::task-1").hexdigest()
    )
    assert receipt["task_user_tool_schemas_sha256"]


def test_tau2_preflight_rejects_tau2_import_outside_pinned_checkout(
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / "tau2-bench"
    pinned_module = SimpleNamespace(
        __name__="tau2.runner.build",
        __file__=str(harness_dir / "src" / "tau2" / "runner" / "build.py"),
    )
    stale_module = SimpleNamespace(
        __name__="tau2.metrics.agent_metrics",
        __file__=str(tmp_path / "site-packages" / "tau2" / "metrics" / "agent_metrics.py"),
    )

    assert _tau2_import_origins(harness_dir, (pinned_module,)) == {
        "tau2.runner.build": "src/tau2/runner/build.py"
    }
    with pytest.raises(ContractError, match="not imported from the pinned checkout"):
        _tau2_import_origins(harness_dir, (stale_module,))


def test_tau2_preflight_rejects_mismatched_frozen_runtime_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_dir = tmp_path / "tau2-bench"
    site_root = Path(site.getsitepackages([str(harness_dir / ".venv")])[0])
    dist_info = site_root / "tau2-1.0.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: tau2\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (harness_dir / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (harness_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "plugins.benchmark_harness.tau2_lane1a_preflight.TAU2_LANE1A_RUNTIME_DISTRIBUTIONS",
        {},
    )

    with pytest.raises(
        ContractError,
        match=r"frozen runtime requires 1\.0\.1, got 1\.0\.0",
    ):
        _tau2_runtime_identity(harness_dir)


def test_tau2_preflight_hashes_post_policy_codex_tool_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.agent.loop._tool_factory.get_agentic_tools",
        lambda *_args, **_kwargs: [
            {"name": "second", "description": "overridden", "input_schema": {"type": "object"}},
            {"name": "first", "description": "original", "input_schema": {"type": "object"}},
        ],
    )
    raw_tools = [
        SimpleNamespace(name="first", short_desc="first", long_desc="", openai_schema=None),
        SimpleNamespace(name="second", short_desc="second", long_desc="", openai_schema=None),
    ]

    schemas = _model_visible_tau2_tool_schemas(raw_tools)

    assert [schema["name"] for schema in schemas] == ["second", "first"]
    assert schemas[0] == {
        "type": "function",
        "name": "second",
        "description": "overridden",
        "parameters": {"type": "object"},
    }


def test_tau2_preflight_rejects_dirty_producer_and_repo_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plugins.benchmark_harness.tau2_lane1a_preflight._git_output",
        lambda _root, *args: " M source.py" if args == ("status", "--porcelain") else "head",
    )
    with pytest.raises(ContractError, match="clean GEODE producer"):
        _tau2_producer_identity()

    with pytest.raises(ContractError, match="outside both source checkouts"):
        _write_tau2_lane1a_preflight_receipt(tmp_path, REPO_ROOT / "receipt.json")


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


def test_tau2_tool_wrapper_returns_a_deferred_ack_without_local_execution() -> None:
    class NativeTool:
        name = "lookup_account"

        def __call__(self, **_kwargs: object) -> object:
            raise AssertionError("tau2 must remain the only environment executor")

    result = asyncio.run(Tau2GeodeTool(NativeTool(), mutates_state=False).aexecute(id="A"))

    assert result["external_execution"] == "deferred"
    assert result["projected_to_tau2"] is True


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


def test_tau2_external_result_closes_the_original_provider_call_id() -> None:
    recorded: list[dict[str, object]] = []

    class Timeline:
        def record_tool_result(
            self,
            tool: str,
            status: str,
            summary: str,
            *,
            call_id: str,
            result: object,
        ) -> None:
            recorded.append(
                {
                    "tool": tool,
                    "status": status,
                    "summary": summary,
                    "call_id": call_id,
                    "result": result,
                }
            )

    state = GeodeTau2State(loop=SimpleNamespace(_timeline=Timeline()))
    _remember_tau2_tool_calls(
        state,
        [SimpleNamespace(id="call_exact", name="update_address")],
    )

    _record_tau2_tool_results(
        state,
        SimpleNamespace(
            role="tool",
            id="call_exact",
            requestor="assistant",
            content='{"ok": true}',
            error=False,
            tool_messages=None,
        ),
    )

    assert recorded == [
        {
            "tool": "update_address",
            "status": "ok",
            "summary": "tau2 orchestrator result",
            "call_id": "call_exact",
            "result": {
                "content": '{"ok": true}',
                "error": False,
                "source": "tau2_orchestrator",
            },
        }
    ]
    assert state.pending_tool_calls == {}


def test_tau2_external_result_rejects_an_orphan_call_id() -> None:
    state = GeodeTau2State(loop=SimpleNamespace(_timeline=SimpleNamespace()))

    with pytest.raises(RuntimeError, match="orphan tau2 tool result id"):
        _record_tau2_tool_results(
            state,
            SimpleNamespace(
                role="tool",
                id="unknown",
                requestor="assistant",
                content="not joined",
                error=False,
                tool_messages=None,
            ),
        )


def test_tau2_tool_projection_preserves_failed_execution_for_official_accounting(
    monkeypatch: pytest.MonkeyPatch,
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
                "tool_use_id": "call_bad_reservation",
                "tool": "get_reservation_details",
                "input": {"reservation_id": "UNKNOWN"},
                "result": {
                    "error": "Reservation UNKNOWN not found",
                    "error_type": "ValueError",
                },
            }
        ]
    )

    calls = _tau2_tool_calls(result, requestor="assistant")

    assert len(calls) == 1
    assert calls[0].id == "call_bad_reservation"
    assert calls[0].name == "get_reservation_details"
    assert calls[0].arguments == {"reservation_id": "UNKNOWN"}


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
    assert geode_trajectory_snapshot_path(
        Path("snapshots"),
        "crucible/tau2 train telecom candidate",
    ) == Path("snapshots/crucible-tau2-train-telecom-candidate.geode-trajectory.json")


def test_tau2_session_ids_preserve_first_seen_lineage() -> None:
    results = {
        "simulations": [
            {
                "messages": [
                    {"raw_data": {"geode_session_id": "s-agent"}},
                    {"raw_data": {"geode_session_id": "s-user"}},
                    {"raw_data": {"geode_session_id": "s-agent"}},
                ]
            }
        ]
    }

    assert tau2_session_ids(results) == ["s-agent", "s-user"]


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
    normalized = geode_trajectory_snapshot_path(tmp_path / "snapshots", run_id)
    normalized_payload = json.loads(normalized.read_text())
    assert normalized_payload["schema_id"] == "geode.trajectory@1"
    assert normalized_payload["integrity"]["complete"] is False
    assert str(normalized) in snapshot.read_text()


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
