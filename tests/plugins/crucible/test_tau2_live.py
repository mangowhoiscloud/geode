import json
from pathlib import Path

import pytest
from plugins.crucible.contract import ContractError, ExperimentContract, TaskUnit, task_pack_sha256
from plugins.crucible.producers.codex_kg import _prompt, knowledge_context
from plugins.crucible.tau2_live import tau2_command, tau2_trace_checks

TASKS = (
    TaskUnit("task-1", "1" * 64, "a" * 64),
    TaskUnit("task-2", "2" * 64, "b" * 64),
)
TEST_TASKS = (
    TaskUnit("test-1", "3" * 64, "c" * 64),
    TaskUnit("test-2", "4" * 64, "d" * 64),
)


def test_command_evaluator_entrypoint_uses_the_frozen_uv_runtime() -> None:
    repository = Path(__file__).parents[3]

    assert (
        repository.joinpath("scripts/eval/crucible_tau2_evaluator.py")
        .read_text(encoding="utf-8")
        .splitlines()[0]
        == "#!/usr/bin/env -S uv run --frozen --no-dev python"
    )


def _contract() -> ExperimentContract:
    assay = {
        "schema": "crucible.tau2-assay.v1",
        "domain": "telecom",
        "task_set_name": None,
        "task_split_name": "base",
        "num_trials": 1,
        "max_concurrency": 1,
        "max_steps": 24,
        "max_errors": 1,
        "max_retries": 0,
        "timeout": 600.0,
        "seed": 300,
        "agent": {
            "implementation": "geode_agent",
            "route": "openai-subscription-gpt-5.4-high",
            "model": "gpt-5.4",
            "provider": "openai",
            "source": "subscription",
            "effort": "high",
            "time_budget_s": 180.0,
            "max_tokens": 32768,
            "max_rounds": 0,
            "cognitive_reflection": False,
            "codex_output_replay": True,
            "tool_search_defer": True,
        },
        "user": {
            "implementation": "crucible_user",
            "runtime_owner": "evaluator",
            "route": "evaluator-openai-subscription-gpt-5.4-high",
            "llm": "gpt-5.4",
            "llm_args": {"temperature": 0.0},
            "provider": "openai",
            "source": "subscription",
            "effort": "high",
            "time_budget_s": 120.0,
            "max_tokens": 8192,
            "max_rounds": 0,
        },
        "retrieval": {"config": None, "kwargs": {}},
    }
    return ExperimentContract.from_mapping(
        {
            "schema": "crucible.experiment.v3",
            "name": "live-tau2-fixture",
            "stage": "train",
            "champion_ref": "refs/crucible/baselines/fixture/1",
            "baseline_sha": "1" * 40,
            "candidate_sha": "2" * 40,
            "evaluator_sha256": "c" * 64,
            "harness_sha256": "d" * 64,
            "task_pack_sha256": task_pack_sha256(TASKS, 1),
            "agent_route": "openai-subscription-gpt-5.4-high",
            "user_route": "evaluator-openai-subscription-gpt-5.4-high",
            "tasks": [task.to_dict() for task in TASKS],
            "trials_per_task": 1,
            "assay_config": assay,
            "mutations": [
                {
                    "surface": "plugins/benchmark_harness/tau2_agent_policy.md",
                    "hypothesis": "compress tool workflows",
                }
            ],
            "evaluator_paths": [
                "scripts/eval/crucible_tau2_evaluator.py",
                "plugins/benchmark_harness/tau2_geode_agent.py",
                "plugins/crucible",
            ],
            "promotion": {
                "method": "paired_bootstrap.v2",
                "primary_metric": "reward",
                "materiality_pp": 0.1,
                "minimum_candidate_mean": 0.5,
                "minimum_tasks": 2,
                "minimum_families": 2,
                "confidence_level": 0.885,
                "bootstrap_samples": 1000,
            },
            "budget": {
                "max_wall_seconds": 3600.0,
                "max_calls": 1000,
                "max_tokens": 1_000_000,
                "max_cost_usd": 100.0,
                "max_changed_lines": 40,
            },
            "vetoes": [
                "budget",
                "infra_clean",
                "safety",
                "task_coverage",
                "tool_contract",
            ],
        }
    )


def _test_contract(parent: ExperimentContract) -> ExperimentContract:
    payload = parent.to_dict()
    payload.pop("contract_id")
    payload.update(
        {
            "name": "live-tau2-sealed-fixture",
            "stage": "test",
            "parent_contract_id": parent.contract_id,
            "tasks": [task.to_dict() for task in TEST_TASKS],
            "task_pack_sha256": task_pack_sha256(TEST_TASKS, 1),
        }
    )
    return ExperimentContract.from_mapping(payload)


def test_tau2_command_is_fully_derived_from_frozen_subscription_config(tmp_path: Path) -> None:
    command = tau2_command(
        _contract(),
        arm="candidate",
        checkout=tmp_path / "candidate",
        harness_root=tmp_path / "harness",
        contract_path=tmp_path / "contract.json",
        snapshot_dir=tmp_path / "snapshots",
        run_id="fixture-candidate",
    )

    assert command[command.index("--user") + 1] == "crucible_user"
    assert command[command.index("--model") + 1] == "gpt-5.4"
    assert command[command.index("--user-max-tokens") + 1] == "8192"
    assert command[command.index("--trajectory-arm") + 1] == "candidate"
    assert "--disable-tool-search-defer" not in command
    assert "--max-retries" in command
    assert command[command.index("--max-retries") + 1] == "0"


def test_tau2_test_command_binds_the_frozen_train_parent(tmp_path: Path) -> None:
    parent = _contract()
    contract = _test_contract(parent)
    parent_path = tmp_path / "train-contract.json"

    command = tau2_command(
        contract,
        arm="candidate",
        checkout=tmp_path / "candidate",
        harness_root=tmp_path / "harness",
        contract_path=tmp_path / "test-contract.json",
        parent_contract_path=parent_path,
        snapshot_dir=tmp_path / "snapshots",
        run_id="sealed-candidate",
    )

    assert command[command.index("--parent-experiment-contract") + 1] == str(parent_path)
    with pytest.raises(ContractError, match="frozen train contract"):
        tau2_command(
            contract,
            arm="candidate",
            checkout=tmp_path / "candidate",
            harness_root=tmp_path / "harness",
            contract_path=tmp_path / "test-contract.json",
            snapshot_dir=tmp_path / "snapshots",
            run_id="missing-parent",
        )


def test_tau2_trace_checks_are_independent_of_reward() -> None:
    raw = {
        "info": {"environment_info": {"domain_name": "retail"}},
        "simulations": [
            {
                "task_id": "task-1",
                "trial": 0,
                "reward_info": {"reward": 1.0},
                "messages": [
                    {"role": "user", "content": "Please change it."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"name": "modify_order", "arguments": {"id": "1"}}],
                    },
                ],
            },
            {
                "task_id": "task-2",
                "trial": 0,
                "reward_info": {"reward": 0.0},
                "messages": [
                    {"role": "user", "content": "Yes, please proceed."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"name": "modify_order", "arguments": {"id": "2"}}],
                    },
                    {"role": "tool", "content": "failed", "error": True},
                ],
            },
        ],
    }

    checks = tau2_trace_checks(raw)

    assert checks[("task-1", 0)] == {"safety": False, "tool_contract": True}
    assert checks[("task-2", 0)] == {"safety": True, "tool_contract": False}


def test_codex_producer_uses_bounded_local_graph_slice(tmp_path: Path) -> None:
    graph_path = tmp_path / "knowledge-graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "project": {"name": "GEODE", "description": "agent harness"},
                "nodes": [
                    {
                        "id": "policy",
                        "filePath": "plugins/benchmark_harness/tau2_agent_policy.md",
                        "name": "Tau2 policy",
                        "summary": "candidate-owned behavior contract",
                        "tags": ["prompt"],
                    },
                    {
                        "id": "runner",
                        "filePath": "plugins/benchmark_harness/tau2_geode_agent.py",
                        "name": "Tau2 runner",
                        "summary": "loads the policy",
                        "tags": ["benchmark"],
                    },
                    {
                        "id": "unrelated",
                        "filePath": "core/gateway/slack.py",
                        "name": "Slack",
                        "summary": "unrelated",
                        "tags": ["gateway"],
                    },
                ],
                "edges": [{"source": "runner", "target": "policy", "type": "reads_from"}],
            }
        ),
        encoding="utf-8",
    )

    context = json.loads(
        knowledge_context(
            graph_path,
            ("plugins/benchmark_harness/tau2_agent_policy.md",),
        )
    )

    assert {node["name"] for node in context["nodes"]} == {"Tau2 policy", "Tau2 runner"}
    assert "unrelated" not in json.dumps(context)


def test_codex_producer_prompt_uses_can_cannot_policy_clauses() -> None:
    prompt = _prompt(
        objective="Improve complete workflows.",
        surfaces=("plugins/benchmark_harness/tau2_agent_policy.md",),
        feedback=None,
        graph_context="{}",
    )

    assert "CANNOT add task IDs" in prompt
    assert "CANNOT run live/provider tests" in prompt
    legacy_negative = " ".join(("do", "not"))
    assert legacy_negative not in prompt.casefold()
