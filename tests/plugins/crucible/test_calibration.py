import pytest
from plugins.crucible.calibration import (
    CostModel,
    MutationClassPrior,
    NoiseModel,
    derive_design,
)
from plugins.crucible.contract import ContractError, PromotionRule, canonical_sha256

# Measured 2026-07 inputs (crucible-handoff.md §3 + G1 trace replay artifact).
NULL_RUN = {"flips": 12, "regressions": 10, "n_tasks": 114}
REPLAY = {"supported": 24, "targeted": 27, "false_blocks": 4, "controls": 87}
PACK_SHA = "f" * 64


def _noise() -> NoiseModel:
    return NoiseModel.fit_from_null_run(**NULL_RUN, source="m1-null-2026-07-06")


def _prior(pack_sha: str = PACK_SHA) -> MutationClassPrior:
    return MutationClassPrior.from_replay_counts(
        class_name="guard",
        **REPLAY,
        task_pack_sha256=pack_sha,
        source="g1-trace-replay-2026-07-06",
    )


def _costs() -> CostModel:
    return CostModel(false_keep_cost=920.0, window_conversations=240)


def test_null_run_fit_matches_measured_discordance() -> None:
    noise = _noise()
    assert noise.discordance == pytest.approx(22 / 114)
    assert noise.pi_flaky == pytest.approx((22 / 114) / 0.5)


def test_null_run_fit_rejects_impossible_counts() -> None:
    with pytest.raises(ContractError, match="discordant"):
        NoiseModel.fit_from_null_run(flips=80, regressions=60, n_tasks=100, source="x")


def test_trial_count_fit_recovers_synthetic_flaky_mass() -> None:
    trials = 4
    # 40 flaky tasks: expected interior share 1 - 2*0.5**4 = 0.875 -> 35 interior.
    pass_counts = [2] * 35 + [0] * 45 + [trials] * 20
    noise = NoiseModel.fit_from_trial_counts(pass_counts, trials=trials, source="synthetic")
    assert noise.pi_flaky == pytest.approx(0.40, abs=0.005)


def test_stale_prior_is_rejected_at_derivation_time() -> None:
    prior = _prior(pack_sha="a" * 64)
    with pytest.raises(ContractError, match="refit or rescreen"):
        derive_design(
            noise=_noise(),
            prior=prior,
            costs=_costs(),
            task_pack_sha256=PACK_SHA,
            enriched_flaky_share=0.1,
        )


def test_alpha_star_derives_from_cost_ratio() -> None:
    assert _costs().alpha_star(120) == pytest.approx(120 / (120 + 920))
    with pytest.raises(ContractError, match="positive"):
        _costs().alpha_star(0)


def test_derivation_is_deterministic_and_hash_consistent() -> None:
    kwargs: dict = {
        "noise": _noise(),
        "prior": _prior(),
        "costs": _costs(),
        "task_pack_sha256": PACK_SHA,
        "enriched_flaky_share": 0.1,
        "rng_seed": 7,
    }
    first = derive_design(**kwargs)
    second = derive_design(**kwargs)
    assert first == second
    assert first["inputs_sha256"] == canonical_sha256(first["inputs"])
    derived = first["derived"]
    assert derived["minimum_tasks"] >= 1
    assert 0.5 < derived["confidence_level"] < 1.0
    assert derived["conversations_per_attempt"] <= 240
    assert derived["expected_power"] > 0.5


def test_quota_window_infeasibility_fails_loud() -> None:
    with pytest.raises(ContractError, match="quota window"):
        derive_design(
            noise=_noise(),
            prior=_prior(),
            costs=CostModel(false_keep_cost=920.0, window_conversations=10),
            task_pack_sha256=PACK_SHA,
            enriched_flaky_share=0.1,
        )


def _rule_payload_from(derivation: dict) -> dict:
    derived = derivation["derived"]
    return {
        "method": "paired_bootstrap.v2",
        "primary_metric": "reward",
        "materiality_pp": derived["materiality_pp"],
        "minimum_candidate_mean": 0.3,
        "minimum_tasks": derived["minimum_tasks"],
        "confidence_level": derived["confidence_level"],
        "bootstrap_samples": 1_000,
        "parameter_derivation": derivation,
    }


def test_promotion_rule_accepts_matching_derivation_block() -> None:
    derivation = derive_design(
        noise=_noise(),
        prior=_prior(),
        costs=_costs(),
        task_pack_sha256=PACK_SHA,
        enriched_flaky_share=0.1,
    )
    rule = PromotionRule.from_mapping(_rule_payload_from(derivation))
    assert rule.parameter_derivation is not None


def test_promotion_rule_rejects_stamped_value_drift() -> None:
    derivation = derive_design(
        noise=_noise(),
        prior=_prior(),
        costs=_costs(),
        task_pack_sha256=PACK_SHA,
        enriched_flaky_share=0.1,
    )
    payload = _rule_payload_from(derivation)
    payload["minimum_tasks"] = payload["minimum_tasks"] + 5
    with pytest.raises(ContractError, match="must equal its derivation"):
        PromotionRule.from_mapping(payload)


def test_promotion_rule_rejects_tampered_derivation_inputs() -> None:
    derivation = derive_design(
        noise=_noise(),
        prior=_prior(),
        costs=_costs(),
        task_pack_sha256=PACK_SHA,
        enriched_flaky_share=0.1,
    )
    tampered = dict(derivation)
    tampered["inputs"] = dict(tampered["inputs"])
    tampered["inputs"]["costs"] = dict(tampered["inputs"]["costs"])
    tampered["inputs"]["costs"]["false_keep_cost"] = 1.0
    payload = _rule_payload_from(tampered)
    with pytest.raises(ContractError, match="inputs_sha256"):
        PromotionRule.from_mapping(payload)
