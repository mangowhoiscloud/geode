"""Collection protocol: label hygiene, repeat rules, and variance reporting."""

from __future__ import annotations

import pytest
from core.llm.errors import build_model_action_message
from evals import collection_protocol as cp
from evolve.crucible.assays.verifiers.tau2 import tau2_has_infrastructure_contamination

RATE_LIMIT = build_model_action_message(
    error_type="rate_limit",
    severity="warning",
    hint="API rate limited. Retrying briefly; switch model with /model if it persists.",
    model="gpt-5.5",
    provider="openai",
    attempts=3,
)


def _sim(*messages: dict[str, object]) -> dict[str, object]:
    return {
        "task_id": "t",
        "trial": 0,
        "termination_reason": "max_steps",
        "messages": list(messages),
    }


def test_detector_flags_relayed_harness_diagnostics_and_provider_errors() -> None:
    flags = cp.detect_contamination(
        [
            {"role": "user", "content": RATE_LIMIT},
            {"role": "assistant", "content": "! API rate limited. Switch to a different model."},
            {"role": "assistant", "content": "! Unexpected error. Auto-retrying."},
            {"role": "user", "content": "Error code: 429 - rate_limit_exceeded"},
            {"role": "tool", "content": "! API rate limited."},
            {"role": "assistant", "content": "", "tool_calls": None},
            {"role": "user", "content": "My data speed is rate limited after the usage limit."},
        ]
    )
    assert [(f["kind"], f["message_index"], f.get("error_type")) for f in flags] == [
        ("harness_error_text", 0, "rate_limit"),
        ("harness_error_text", 1, "rate_limit"),
        ("harness_error_text", 2, "unknown"),
        ("provider_error_text", 3, None),
        ("empty_response", 5, None),
    ]


def test_empty_turn_is_flagged_for_review_without_invalidating() -> None:
    record = cp.label_hygiene([{"role": "assistant", "content": " "}])
    assert record["validity"] == "valid"
    assert record["flags"][0]["kind"] == "empty_response"
    assert record["detector"] == cp.DETECTOR_VERSION


def test_native_receipt_annotation_keeps_reward_and_marks_invalid() -> None:
    raw = {
        "info": {"num_trials": 1},
        "simulations": [
            _sim({"role": "user", "content": RATE_LIMIT}) | {"reward_info": {"reward": 0.0}},
            _sim({"role": "assistant", "content": "Done."}) | {"reward_info": {"reward": 1.0}},
        ],
    }
    annotated = cp.annotate_tau2_results(raw)
    assert [s["geode_label_hygiene"]["validity"] for s in annotated["simulations"]] == [
        "invalid",
        "valid",
    ]
    assert annotated["simulations"][0]["reward_info"] == {"reward": 0.0}
    assert "geode_label_hygiene" not in raw["simulations"][0]


def test_crucible_collection_stops_on_contaminated_transcript() -> None:
    clean = {"simulations": [_sim({"role": "assistant", "content": "Done."})]}
    dirty = {"simulations": [_sim({"role": "user", "content": RATE_LIMIT})]}
    assert tau2_has_infrastructure_contamination(clean) is False
    assert tau2_has_infrastructure_contamination(dirty) is True


def test_repeat_minimums() -> None:
    cp.check_repetitions("evaluation-gate", 3)
    with pytest.raises(ValueError, match="rl-group needs k >= 16"):
        cp.check_repetitions("rl-group", 15)
    with pytest.raises(ValueError, match="unknown"):
        cp.check_repetitions("vibes", 3)


def test_aa_width_bounds_materiality() -> None:
    # Same-config baselines that passed 7 and 10 of 12 tasks (width 0.25).
    tasks = [f"t{i}" for i in range(12)]
    first = {t: float(i < 7) for i, t in enumerate(tasks)}
    second = {t: float(i < 10) for i, t in enumerate(tasks)}
    aa = cp.aa_variation([first, second])
    assert aa["width"] == pytest.approx(0.25)
    assert aa["flipped_tasks"] == ["t7", "t8", "t9"]
    with pytest.raises(ValueError, match="does not exceed measured A/A width"):
        cp.check_materiality(0.25, aa)
    cp.check_materiality(0.3, aa)
    with pytest.raises(ValueError, match="aa-baseline needs k >= 2"):
        cp.aa_variation([first])


def test_rl_groups_drop_uniform_and_report_undersampled() -> None:
    rows = [{"example_id": "mixed", "reward": float(i % 2)} for i in range(16)]
    rows += [{"example_id": "solved", "reward": 1.0} for _ in range(16)]
    rows += [{"example_id": "short", "reward": float(i % 2)} for i in range(4)]
    groups = cp.informative_groups(rows)
    assert list(groups["kept"]) == ["mixed"]
    assert groups["dropped_uniform"] == ["solved"]
    assert groups["undersampled"] == ["short"]


def _run(rollout_id: str, reward: float, actors: str) -> dict[str, object]:
    return {
        "rollout_id": rollout_id,
        "reward": reward,
        "config_sha256": "c" * 64,
        "events": [{"actor": actor, "digest": f"{i}-{actor}"} for i, actor in enumerate(actors)],
    }


def test_preference_pairs_record_first_divergence_actor() -> None:
    runs = [
        _run("pass", 1.0, "aua"),
        _run("fail-sim", 0.0, "auu"),
        _run("fail-early", 0.0, "u"),
        _run("pass-2", 1.0, "aua"),
    ]
    pairs = {(p["chosen"], p["rejected"]): p for p in cp.preference_pairs(runs)}
    assert len(pairs) == 4
    sim_pair = pairs[("pass", "fail-sim")]
    assert sim_pair["first_divergence"] == 2
    assert sim_pair["divergence_actor"] == {"chosen": "a", "rejected": "u"}
    assert pairs[("pass", "fail-early")]["first_divergence"] == 0
    with pytest.raises(ValueError, match="preference needs k >= 4"):
        cp.preference_pairs(runs[:3])
    with pytest.raises(ValueError, match="one configuration"):
        cp.preference_pairs([*runs[:3], {**runs[3], "config_sha256": "d" * 64}])


def test_variance_report_per_task_wilson_disagreement_and_pass_k() -> None:
    rows = [{"example_id": "a", "passed": True} for _ in range(5)]
    rows += [{"example_id": "b", "passed": False} for _ in range(5)]
    rows += [{"example_id": "c", "passed": i < 2} for i in range(5)]
    report = cp.variance_report(rows)

    assert report["per_task"]["c"]["passes"] == 2
    lo, hi = report["per_task"]["c"]["wilson_95"]
    assert lo == pytest.approx(0.1176, abs=1e-4) and hi == pytest.approx(0.7693, abs=1e-4)
    assert report["mixed_tasks"] == 1
    # c contributes 2 * 3 differing pairs out of 3 * C(5, 2) same-task pairs.
    assert report["within_task_disagreement"] == pytest.approx(6 / 30)
    assert report["k"] == 5
    assert report["pass_at_k"] == pytest.approx(2 / 3)
    assert report["pass_hat_k"] == pytest.approx(1 / 3)
    assert cp.variance_report(rows, k=1)["pass_at_k"] == pytest.approx((1 + 0 + 0.4) / 3)


def test_comparison_report_places_aa_width_beside_bootstrap() -> None:
    aa = {"width": 0.25, "runs": 2}
    noisy = cp.comparison_report(0.333, [0.05, 0.6], aa)
    assert noisy["aa_width"] == 0.25 and noisy["exceeds_aa_width"] is False
    assert cp.comparison_report(0.5, [0.3, 0.7], aa)["exceeds_aa_width"] is True


def test_wilson_bounds() -> None:
    assert cp.wilson_interval(0, 5)[0] == 0.0
    assert cp.wilson_interval(5, 5)[1] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        cp.wilson_interval(3, 2)
