import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from plugins.crucible.contract import (
    ContractError,
    ExperimentContract,
    TaskUnit,
    task_pack_sha256,
)
from plugins.crucible.evidence import EvidenceEnvelope, ResourceUsage
from plugins.crucible.producers.codex_kg import (
    _DEFAULT_GRAPH_PATH,
    ProducerError,
    _prompt,
    _validate_policy_grammar,
    knowledge_context,
)
from plugins.crucible.promotion import decide
from plugins.crucible.tau2_live import (
    Tau2InfrastructureError,
    _run_arm,
    _train_evaluation_response,
    _write_skipped_arm,
    tau2_command,
    tau2_trace_checks,
)

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


def test_command_evaluator_emits_paths_relative_to_response_directory(
    tmp_path: Path,
) -> None:
    evaluation_dir = tmp_path / "attempt" / "evaluation"
    response = _train_evaluation_response(
        {"attempt_id": "0001-fixture", "request_id": "request-id"},
        {"proposal_id": "proposal-id"},
        output_dir=evaluation_dir,
        baseline_raw=evaluation_dir / "baseline.raw.json",
        candidate_raw=evaluation_dir / "candidate.raw.json",
        feedback=None,
    )

    assert {
        field: response[field]
        for field in ("baseline", "candidate", "baseline_raw", "candidate_raw")
    } == {
        "baseline": "baseline.evidence.json",
        "candidate": "candidate.evidence.json",
        "baseline_raw": "baseline.raw.json",
        "candidate_raw": "candidate.raw.json",
    }


def test_skipped_candidate_is_closed_zero_call_infrastructure_evidence(tmp_path: Path) -> None:
    contract = _contract()
    trigger = _arm_evidence(
        contract,
        arm="baseline",
        invalid=True,
        raw_hash="a" * 64,
    )

    candidate, raw_path = _write_skipped_arm(
        contract,
        arm="candidate",
        output_dir=tmp_path,
        trigger=trigger,
    )

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw["schema"] == "crucible.skipped-arm.v1"
    assert raw["triggering_evidence_id"] == trigger.evidence_id
    assert candidate.execution_status == "invalid"
    assert candidate.failure_class == "paired_arm_skipped"
    assert candidate.usage == ResourceUsage(0.0, 0, 0, 0.0)
    assert [row.pair_id for row in candidate.rows] == [
        (task_id, 0) for task_id in contract.task_ids
    ]
    assert all(row.status == "infrastructure_error" for row in candidate.rows)
    verdict = decide(contract, trigger, candidate)
    assert verdict.verdict == "INVALID"
    assert verdict.reasons == ("infrastructure_contamination",)
    assert verdict.pair_count == 0


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
            "max_rounds": 1,
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
            "max_rounds": 1,
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


def _arm_evidence(
    contract: ExperimentContract,
    *,
    arm: str,
    invalid: bool,
    raw_hash: str,
) -> EvidenceEnvelope:
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    return EvidenceEnvelope.from_mapping(
        {
            "schema": "crucible.evidence.v3",
            "contract_id": contract.contract_id,
            "arm": arm,
            "revision_sha": revision,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": raw_hash,
            "execution_status": "invalid" if invalid else "complete",
            "failure_class": "route_contamination" if invalid else None,
            "usage": ResourceUsage(1.0, 1, 10, 0.0).to_dict(),
            "rows": [
                {
                    "task_id": task_id,
                    "trial": 0,
                    "status": "infrastructure_error" if invalid else "completed",
                    "termination_reason": "empty_output" if invalid else "done",
                    "failure_class": "route_contamination" if invalid else None,
                    "metrics": {} if invalid else {"reward": 1.0},
                    "checks": {} if invalid else {"safety": True, "tool_contract": True},
                }
                for task_id in contract.task_ids
            ],
        }
    )


def _prepared_arm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    invalid: bool,
) -> tuple[ExperimentContract, Path, Path, Path]:
    contract = _contract()
    checkout = tmp_path / "checkout"
    harness = tmp_path / "harness"
    output = tmp_path / "output"
    checkout.mkdir()
    raw = harness / "data" / "simulations" / "fixture-run" / "results.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}\n", encoding="utf-8")
    snapshot = output / "snapshots" / "fixture-run.snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}\n", encoding="utf-8")
    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=invalid,
        raw_hash=hashlib.sha256(raw.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        "plugins.crucible.tau2_live.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=1),
    )
    monkeypatch.setattr(
        "plugins.crucible.tau2_live.tau2_resource_usage_floor",
        lambda raw: ResourceUsage(1.0, 1, 10, 0.0),
    )
    monkeypatch.setattr("plugins.crucible.tau2_live.tau2_trace_checks", lambda raw: {})
    monkeypatch.setattr(
        "plugins.crucible.tau2_live.normalize_tau2_results",
        lambda *args, **kwargs: evidence,
    )
    return contract, checkout, harness, output


def test_run_arm_preserves_finalized_invalid_evidence_after_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=True,
    )

    evidence, raw_path = _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id="fixture-run",
        timeout=10.0,
    )

    assert evidence.execution_status == "invalid"
    assert raw_path == output / "baseline.raw.json"
    assert (output / "baseline.evidence.json").is_file()


def test_run_arm_accounts_for_actual_subprocess_elapsed_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=True,
    )
    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=True,
        raw_hash="a" * 64,
    )
    captured: dict[str, ResourceUsage] = {}

    def normalize(*args: object, **kwargs: object) -> EvidenceEnvelope:
        usage = kwargs["usage"]
        assert isinstance(usage, ResourceUsage)
        captured["usage"] = usage
        return evidence

    moments = iter((10.0, 13.5))
    monkeypatch.setattr("plugins.crucible.tau2_live.time.monotonic", lambda: next(moments))
    monkeypatch.setattr("plugins.crucible.tau2_live.normalize_tau2_results", normalize)

    _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id="fixture-run",
        timeout=10.0,
    )

    assert captured["usage"] == ResourceUsage(3.5, 1, 10, 0.0)


def test_run_arm_rejects_nonzero_exit_with_complete_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=False,
    )

    with pytest.raises(Tau2InfrastructureError, match="exited with status 1"):
        _run_arm(
            contract,
            arm="baseline",
            checkout=checkout,
            harness_root=harness,
            contract_path=tmp_path / "contract.json",
            output_dir=output,
            run_id="fixture-run",
            timeout=10.0,
        )


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
    assert command[command.index("--agent-max-rounds") + 1] == "1"
    assert command[command.index("--user-max-rounds") + 1] == "1"


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
    sources = {
        "plugins/benchmark_harness/tau2_agent_policy.md": "policy\n",
        "plugins/benchmark_harness/tau2_geode_agent.py": "runner\n",
        "core/gateway/slack.py": "unrelated\n",
    }
    for relative, content in sources.items():
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")

    def digest(relative: str) -> str:
        return hashlib.sha256(sources[relative].encode()).hexdigest()

    graph_path = tmp_path / "knowledge-graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "schema": "crucible.producer-graph.v1",
                "project": {"name": "GEODE", "description": "agent harness"},
                "nodes": [
                    {
                        "id": "policy",
                        "filePath": "plugins/benchmark_harness/tau2_agent_policy.md",
                        "name": "Tau2 policy",
                        "summary": "candidate-owned behavior contract",
                        "tags": ["prompt"],
                        "contentSha256": digest("plugins/benchmark_harness/tau2_agent_policy.md"),
                    },
                    {
                        "id": "runner",
                        "filePath": "plugins/benchmark_harness/tau2_geode_agent.py",
                        "name": "Tau2 runner",
                        "summary": "loads the policy",
                        "tags": ["benchmark"],
                        "contentSha256": digest("plugins/benchmark_harness/tau2_geode_agent.py"),
                    },
                    {
                        "id": "unrelated",
                        "filePath": "core/gateway/slack.py",
                        "name": "Slack",
                        "summary": "unrelated",
                        "tags": ["gateway"],
                        "contentSha256": digest("core/gateway/slack.py"),
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
            repository=tmp_path,
        )
    )

    assert {node["name"] for node in context["nodes"]} == {"Tau2 policy", "Tau2 runner"}
    assert "unrelated" not in json.dumps(context)

    (tmp_path / "plugins/benchmark_harness/tau2_geode_agent.py").write_text(
        "changed\n",
        encoding="utf-8",
    )
    with pytest.raises(ProducerError, match="knowledge graph source changed"):
        knowledge_context(
            graph_path,
            ("plugins/benchmark_harness/tau2_agent_policy.md",),
            repository=tmp_path,
        )


def test_codex_producer_source_graph_attests_the_current_policy_path() -> None:
    repository = Path(__file__).parents[3]

    context = json.loads(
        knowledge_context(
            _DEFAULT_GRAPH_PATH,
            ("plugins/benchmark_harness/tau2_agent_policy.md",),
            repository=repository,
        )
    )

    names = {node["name"] for node in context["nodes"]}
    assert "Tau2 agent policy" in names
    assert "Tau2 GEODE adapter" in names
    assert "AgenticLoop" in names
    assert "Candidate replay producer" in names


def test_codex_producer_prompt_uses_can_cannot_policy_clauses() -> None:
    prompt = _prompt(
        objective="Improve complete workflows.",
        surfaces=("plugins/benchmark_harness/tau2_agent_policy.md",),
        feedback=None,
        graph_context="{}",
    )

    assert "CANNOT add task IDs" in prompt
    assert "CANNOT run live/provider tests" in prompt
    assert "every behavior bullet starts with exactly `- CAN` or `- CANNOT`" in prompt
    legacy_negative = " ".join(("do", "not"))
    assert legacy_negative not in prompt.casefold()


def test_codex_producer_enforces_can_cannot_output_grammar() -> None:
    _validate_policy_grammar(
        "Mode: assay.\nBehavior:\n- CAN use tools.\n- CANNOT invent results.\n"
    )

    with pytest.raises(ProducerError, match="CAN/CANNOT"):
        _validate_policy_grammar("Mode: assay.\nBehavior:\n- SHOULD batch tool calls.\n")
