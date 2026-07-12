from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_RUNNER = REPO_ROOT / "plugins/benchmark_harness/tau2_geode_agent.py"
TURN_SUPERVISOR = REPO_ROOT / "plugins/benchmark_harness/tau2_turn_supervisor.py"
WORKFLOW_ORDER = REPO_ROOT / "plugins/benchmark_harness/tau2_workflow_order.py"


def test_tau2_harness_does_not_embed_experiment_history() -> None:
    runner = AGENT_RUNNER.read_text(encoding="utf-8")

    assert "telecom-mms-harness-compression-v" not in runner
    assert "telecom-mms-prereq-v" not in runner
    assert not WORKFLOW_ORDER.exists()


def test_tau2_candidate_context_does_not_embed_known_oracle_literals() -> None:
    runner = AGENT_RUNNER.read_text(encoding="utf-8")

    assert "known benchmark split-payment pattern" not in runner
    assert "466.75 + 288.82 + 135.24 + 193.38 + 46.66" not in runner


def test_tau2_candidate_surface_stays_small_enough_to_review() -> None:
    runner_lines = AGENT_RUNNER.read_text(encoding="utf-8").splitlines()
    supervisor_lines = TURN_SUPERVISOR.read_text(encoding="utf-8").splitlines()

    assert len(runner_lines) < 1_200
    assert len(supervisor_lines) < 300
