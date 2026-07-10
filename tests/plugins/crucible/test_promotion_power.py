"""Power self-test: the frozen gate must open for real effects and stay shut
under the null, at the pack scale the calibration derives.

This is the unit test whose absence let v1 ship with a gate that could not
fire at documented pack scales (KEEP required a 10-30pp effect). Synthetic
evidence generated from the fitted noise model runs through the REAL
``decide()``; if the gate's observed power or false-KEEP rate drifts from the
derivation's promise, this fails before any campaign burns budget.
"""

from __future__ import annotations

import random

from plugins.crucible.calibration import (
    CostModel,
    MutationClassPrior,
    NoiseModel,
    derive_design,
)
from plugins.crucible.contract import ExperimentContract, task_pack_sha256
from plugins.crucible.evidence import EvidenceEnvelope
from plugins.crucible.promotion import decide

BASELINE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
_SIMULATIONS = 60
_RESIDUAL_FAIL_PASS_RATE = 0.05
_FIXED_TASK_PASS_RATE = 0.90


def _derivation() -> dict:
    noise = NoiseModel.fit_from_null_run(
        flips=12, regressions=10, n_tasks=114, source="m1-null-2026-07-06"
    )
    prior = MutationClassPrior.from_replay_counts(
        class_name="guard",
        supported=24,
        targeted=27,
        false_blocks=4,
        controls=87,
        task_pack_sha256="f" * 64,
        source="g1-trace-replay-2026-07-06",
    )
    return derive_design(
        noise=noise,
        prior=prior,
        costs=CostModel(false_keep_cost=920.0, window_conversations=240),
        task_pack_sha256="f" * 64,
        enriched_flaky_share=0.1,
        rng_seed=11,
    )


def _contract(derivation: dict) -> ExperimentContract:
    derived = derivation["derived"]
    n_tasks = derived["minimum_tasks"]
    trials = derived["trials_per_task"]
    task_ids = [f"task-{index}" for index in range(n_tasks)]
    return ExperimentContract.from_mapping(
        {
            "schema": "crucible.experiment.v1",
            "name": "power-self-test",
            "stage": "train",
            "champion_ref": "refs/heads/develop",
            "baseline_sha": BASELINE_SHA,
            "candidate_sha": CANDIDATE_SHA,
            "evaluator_sha256": "a" * 64,
            "harness_sha256": "b" * 64,
            "task_pack_sha256": task_pack_sha256(task_ids, trials),
            "agent_route": "candidate-agent-route",
            "user_route": "tau2-user_simulator-fixed-user",
            "task_ids": task_ids,
            "trials_per_task": trials,
            "assay_config": {
                "schema": "crucible.tau2-assay.v1",
                "domain": "mock",
                "user": {
                    "implementation": "user_simulator",
                    "runtime_owner": "evaluator",
                },
            },
            "mutations": [{"surface": "core/agent/verify.py", "hypothesis": "write grounding"}],
            "evaluator_paths": ["plugins/benchmark_harness", "plugins/crucible"],
            "promotion": {
                "method": "paired_bootstrap.v2",
                "primary_metric": "reward",
                "materiality_pp": derived["materiality_pp"],
                "minimum_candidate_mean": 0.0,
                "minimum_tasks": n_tasks,
                "confidence_level": derived["confidence_level"],
                "bootstrap_samples": 1_000,
                "parameter_derivation": derivation,
            },
            "budget": {
                "max_wall_seconds": 1e6,
                "max_calls": 1_000_000,
                "max_tokens": 1_000_000_000,
                "max_cost_usd": 1e6,
                "max_changed_lines": 120,
            },
            "vetoes": ["budget", "infra_clean", "safety", "task_coverage"],
        }
    )


def _evidence(contract: ExperimentContract, *, arm: str, rewards: list[float]) -> EvidenceEnvelope:
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    pairs = [
        (task_id, trial)
        for task_id in contract.task_ids
        for trial in range(contract.trials_per_task)
    ]
    return EvidenceEnvelope.from_mapping(
        {
            "schema": "crucible.evidence.v1",
            "contract_id": contract.contract_id,
            "arm": arm,
            "revision_sha": revision,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": ("c" if arm == "baseline" else "d") * 64,
            "execution_status": "complete",
            "usage": {
                "wall_seconds": 10.0,
                "calls": 10,
                "tokens": 1_000,
                "cost_usd": 1.0,
            },
            "rows": [
                {
                    "task_id": task_id,
                    "trial": trial,
                    "status": "completed",
                    "termination_reason": "user_stop",
                    "metrics": {"reward": reward},
                    "checks": {"safety": True},
                }
                for (task_id, trial), reward in zip(pairs, rewards, strict=True)
            ],
        }
    )


def _keep_rate(*, with_effect: bool, seed: int) -> float:
    derivation = _derivation()
    contract = _contract(derivation)
    inputs = derivation["inputs"]
    pi_flaky_in_pack = inputs["enriched_flaky_share"]
    fix_rate = (
        inputs["class_prior"]["fix_alpha"]
        / (inputs["class_prior"]["fix_alpha"] + inputs["class_prior"]["fix_beta"])
        if with_effect
        else 0.0
    )
    rng = random.Random(seed)
    trials = contract.trials_per_task
    keeps = 0
    for _ in range(_SIMULATIONS):
        baseline_rewards: list[float] = []
        candidate_rewards: list[float] = []
        for _task in contract.task_ids:
            if rng.random() < pi_flaky_in_pack:
                base_rate = cand_rate = 0.5
            else:
                base_rate = _RESIDUAL_FAIL_PASS_RATE
                cand_rate = _FIXED_TASK_PASS_RATE if rng.random() < fix_rate else base_rate
            baseline_rewards.extend(1.0 if rng.random() < base_rate else 0.0 for _ in range(trials))
            candidate_rewards.extend(
                1.0 if rng.random() < cand_rate else 0.0 for _ in range(trials)
            )
        verdict = decide(
            contract,
            _evidence(contract, arm="baseline", rewards=baseline_rewards),
            _evidence(contract, arm="candidate", rewards=candidate_rewards),
        )
        if verdict.verdict == "KEEP":
            keeps += 1
    return keeps / _SIMULATIONS


def test_gate_opens_for_the_effect_class_it_was_designed_for() -> None:
    derivation = _derivation()
    promised_power = derivation["derived"]["expected_power"]
    observed = _keep_rate(with_effect=True, seed=101)
    # Monte Carlo slack: 60 sims, one-sided binomial tolerance ~0.15.
    assert observed >= promised_power - 0.15, (
        f"gate power {observed:.2f} fell below promised {promised_power:.2f}"
    )


def test_gate_stays_shut_under_the_null() -> None:
    derivation = _derivation()
    promised_false_keep = derivation["derived"]["expected_false_keep_rate"]
    observed = _keep_rate(with_effect=False, seed=202)
    assert observed <= promised_false_keep + 0.10, (
        f"null KEEP rate {observed:.2f} exceeds promised {promised_false_keep:.2f}"
    )
