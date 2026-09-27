"""Synthetic-data checks for the pre-registered judgment metrics (05 §3, §5)."""

from __future__ import annotations

import hashlib
import itertools
import math
import random
from typing import Any

import pytest
from evals.benchmarks import decision_metrics as m

LABELS = ("supported", "contradicted", "insufficient_evidence")


def _choice(
    item: str,
    gold: str,
    verdict: str | None,
    top: float = 0.8,
    *,
    cluster: str = "c0",
    valid: bool = True,
) -> m.ChoiceRecord:
    if not valid or verdict is None:
        return m.ChoiceRecord(item, cluster, gold, False)
    rest = (1 - top) / 2
    probabilities = {label: top if label == verdict else rest for label in LABELS}
    return m.ChoiceRecord(item, cluster, gold, True, verdict, probabilities)


def _condition(item: str, gold: bool, p: float | None, *, cluster: str = "c0") -> m.ConditionRecord:
    return m.ConditionRecord(item, cluster, gold, p is not None, p)


def test_accuracy_counts_invalid_output_as_wrong_and_keeps_the_denominator() -> None:
    records = [
        _choice("a", "supported", "supported"),
        _choice("b", "contradicted", "supported"),
        _choice("c", "supported", None, valid=False),
        _choice("d", "insufficient_evidence", "insufficient_evidence"),
    ]
    result = m.accuracy(records)
    assert (result.numerator, result.denominator, result.value) == (2, 4, 0.5)
    assert m.accuracy([]).value is None


def test_macro_f1_treats_invalid_as_gold_false_negative_only() -> None:
    records = [
        _choice("a", "supported", "supported"),
        _choice("b", "supported", None, valid=False),
        _choice("c", "contradicted", "contradicted"),
        _choice("d", "contradicted", "supported"),
    ]
    # supported: tp1 fp1 fn1 -> 0.5; contradicted: tp1 fp0 fn1 -> 2/3; insufficient: 0 -> 0.
    assert m.macro_f1(records, LABELS) == pytest.approx((0.5 + 2 / 3 + 0) / 3)


def test_brier_and_nll_use_valid_outputs_and_the_probability_floor() -> None:
    record = m.ChoiceRecord(
        "a",
        "c",
        "supported",
        True,
        "supported",
        {"supported": 0.7, "contradicted": 0.2, "insufficient_evidence": 0.1},
    )
    invalid = _choice("b", "supported", None, valid=False)
    assert m.brier([record, invalid]) == pytest.approx(0.09 + 0.04 + 0.01)
    assert m.nll([record, invalid]) == pytest.approx(-math.log(0.7))
    zero = m.ChoiceRecord(
        "z",
        "c",
        "contradicted",
        True,
        "supported",
        {"supported": 1.0, "contradicted": 0.0, "insufficient_evidence": 0.0},
    )
    assert m.nll([zero]) == pytest.approx(-math.log(m.NLL_FLOOR))
    assert m.brier([_condition("n", True, 0.8)]) == pytest.approx(0.04)
    assert m.nll([_condition("n", False, 0.8)]) == pytest.approx(-math.log(0.2))
    assert m.brier([invalid]) is None and m.nll([invalid]) is None


def test_ece_uses_ten_equal_bins_with_the_last_closed_at_one() -> None:
    records = [
        _condition("a", True, 0.95),
        _condition("b", True, 0.95),
        _condition("c", True, 0.95),
        _condition("d", False, 0.95),
        _condition("e", True, 1.0),
        _condition("f", False, 0.55),
    ]
    # bin 9: q {.95,.95,.95,.95,1.0}, acc 4/5, mean q .96 -> 5/6*|.8-.96|
    # bin 5: q .55, acc 0 -> 1/6*.55
    expected = 5 / 6 * abs(0.8 - 0.96) + 1 / 6 * 0.55
    assert m.ece(records) == pytest.approx(expected)
    assert m.ece([_condition("x", True, None)]) is None


def _brute_auroc(records: list[m.ConditionRecord]) -> float | None:
    errors = [1 - r.q for r in records if r.valid and r.q is not None and not r.correct]
    rights = [1 - r.q for r in records if r.valid and r.q is not None and r.correct]
    if not errors or not rights:
        return None
    wins = sum(1.0 if e > g else 0.5 if e == g else 0.0 for e in errors for g in rights)
    return wins / (len(errors) * len(rights))


@pytest.mark.parametrize("seed", range(8))
def test_rank_auroc_matches_pairwise_definition_with_ties(seed: int) -> None:
    rng = random.Random(seed)
    records = [
        _condition(
            f"i{index}", rng.random() < 0.6, rng.choice([0.5, 0.6, 0.6, 0.8, 0.9, 1.0, None])
        )
        for index in range(60)
    ]
    assert m.auroc_error_detection(records) == pytest.approx(_brute_auroc(records))
    assert m.auroc_error_detection([_condition("a", True, 0.9)]) is None


def test_risk_coverage_never_accepts_invalid_and_reports_unreachable_points() -> None:
    records = [
        _choice("a", "supported", "supported", 0.9),
        _choice("b", "supported", "contradicted", 0.8),
        _choice("c", "supported", "supported", 0.7),
        _choice("d", "supported", None, valid=False),
    ]
    result = m.risk_coverage(records, points=(0.5, 0.8))
    assert result.curve == ((0.25, 0.0), (0.5, 0.5), (0.75, 1 / 3))
    assert result.aurc == pytest.approx((0 + 0.5 + 1 / 3) / 4)
    assert result.risk_at == {"0.5": 0.5, "0.8": None}


def test_flip_rate_latency_delta_and_duration_unknowns() -> None:
    flips = m.flip_rate([("supported", "supported"), ("supported", None), (None, None)])
    assert (flips.numerator, flips.denominator) == (1, 3)
    delta = m.paired_median_delta([(2.0, 1.0), (3.0, 1.5), (None, 1.0), (0.0, 2.0)])
    assert delta == {"value": -1.25, "observed_pairs": 2, "missing_pairs": 2}
    assert m.duration_seconds(1500) == 1.5
    for value in (0, 0.0, -5, None, True, float("nan"), "12"):
        assert m.duration_seconds(value) is None


def test_bootstrap_seed_follows_the_preregistered_formula() -> None:
    digest = "ab" * 32
    expected = int(hashlib.sha256((digest + "m7_choice").encode()).hexdigest()[:16], 16)
    assert m.bootstrap_seed(digest, "m7_choice") == expected
    assert m.bootstrap_seed(digest, "m7_noul") != expected


def _paired_clusters(count: int, delta: int) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(count)
    clusters: dict[str, list[dict[str, Any]]] = {}
    for index in range(count):
        rows = []
        for item in range(rng.randint(2, 6)):
            a = rng.random() < 0.5
            rows.append({"a": a, "b": a if delta == 0 else True, "item": f"{index}-{item}"})
        clusters[f"c{index}"] = rows
    return clusters


def _delta(rows: list[dict[str, Any]]) -> float | None:
    return (sum(r["b"] for r in rows) - sum(r["a"] for r in rows)) / len(rows) if rows else None


def test_cluster_bootstrap_is_reproducible_paired_and_bounded() -> None:
    clusters = _paired_clusters(40, delta=1)
    first = m.cluster_bootstrap(clusters, _delta, seed=7)
    again = m.cluster_bootstrap(clusters, _delta, seed=7)
    other = m.cluster_bootstrap(clusters, _delta, seed=8)
    assert first == again and first != other
    assert first.replicates == m.BOOTSTRAP_REPLICATES == first.measurable_replicates
    assert first.lower is not None and first.upper is not None
    assert first.lower <= first.estimate <= first.upper
    identical = m.cluster_bootstrap(_paired_clusters(40, delta=0), _delta, seed=7)
    assert identical.lower == identical.upper == identical.estimate == 0
    small = m.cluster_bootstrap(_paired_clusters(9, delta=1), _delta, seed=7)
    assert small.lower is None and small.upper is None and small.estimate is not None
    payload = first.as_dict()
    assert payload["method"] == "source-cluster percentile bootstrap" and payload["seed"] == 7


def test_bootstrap_excludes_unmeasurable_replicates() -> None:
    clusters = {f"c{i}": [{"v": i % 2}] for i in range(12)}

    def only_mixed(rows: list[dict[str, Any]]) -> float | None:
        values = {row["v"] for row in rows}
        return 1.0 if values == {0, 1} else None

    interval = m.cluster_bootstrap(clusters, only_mixed, seed=3, replicates=200)
    assert interval.measurable_replicates < 200 and interval.lower == interval.upper == 1.0


def test_temperature_fit_softens_overconfident_conditions() -> None:
    rng = random.Random(11)
    records = [_condition(f"i{k}", rng.random() < 0.7, 0.9) for k in range(400)]
    fitted = m.fit_temperature(records)
    assert fitted["temperature"] in {2.0, 2.8}
    assert m.fit_temperature(records[:0])["temperature"] is None
    calibrated = [_condition(f"j{k}", k % 10 < 7, 0.7) for k in range(100)]
    assert m.fit_temperature(calibrated)["temperature"] == 1.0
    scaled = m.temperature_scale_choice({"a": 0.8, "b": 0.2, "c": 0.0}, 2.0)
    assert scaled["c"] == 0.0 and scaled["a"] == pytest.approx(
        math.sqrt(0.8) / (math.sqrt(0.8) + math.sqrt(0.2))
    )
    assert m.temperature_scale_condition(1.0, 3.0) == 1.0


def _cascade_fixture() -> tuple[list[m.ChoiceRecord], list[m.ChoiceRecord]]:
    jev, astra = [], []
    for index in range(100):
        gold = "supported"
        confident = index < 60
        jev_right = confident or index % 4 == 0
        jev.append(
            _choice(
                f"i{index}", gold, gold if jev_right else "contradicted", 0.95 if confident else 0.6
            )
        )
        astra.append(_choice(f"i{index}", gold, gold if index % 5 else "contradicted", 0.8))
    jev[99] = _choice("i99", "supported", None, valid=False)
    return jev, astra


def test_cascade_counts_only_confident_valid_jev_decisions_as_acceptance() -> None:
    jev, astra = _cascade_fixture()
    at_high = m.cascade(jev, astra, 0.9)
    assert at_high.coverage.numerator == 60
    # 60 confident Jev (all right) + Astra on the remaining 40 (index % 5 != 0 -> 32 right).
    assert at_high.accuracy.numerator == 60 + sum(1 for i in range(60, 100) if i % 5)
    everything = m.cascade(jev, astra, 0.5)
    assert everything.coverage.numerator == 99  # the invalid Jev item always falls back
    with pytest.raises(ValueError):
        m.cascade(jev, astra[:-1], 0.9)


def test_select_tau_maximizes_coverage_within_tolerance_and_prefers_larger_tau() -> None:
    jev, astra = _cascade_fixture()
    choice = m.select_tau(jev, astra)
    assert choice["admissible"] and choice["fallback_accuracy"] == 0.8
    # Every τ from 0.65 to 0.95 keeps the 60 confident items: coverage ties, largest wins.
    assert choice["tau"] == 0.95
    weak = [_choice(r.item_id, r.gold, "contradicted", 0.99) for r in jev]
    assert m.select_tau(weak, astra)["tau"] is None
    assert m.select_tau(weak, astra)["admissible"] is False


def test_score_and_listwise_summaries() -> None:
    selections = [("a", frozenset({"a"})), ("b", frozenset({"a", "c"})), (None, frozenset({"a"}))]
    top1 = m.score_top1(selections)
    assert (top1.numerator, top1.denominator) == (1, 3)
    assert m.score_regret(3, 2) == 1 and m.score_regret(3, None) is None
    assert m.mean_order_hit([[True, False], [True, True], [False, False]]) == pytest.approx(0.5)
    acceptable = [
        [True, False, False, False],
        [True, True, True, True],
        [False, False, False, False],
    ]
    summary = m.score_acceptance_summary(
        acceptable,
        {
            "pointwise": [True, True, None],
            "fallback": [None, None, None],
            "listwise": [0.5, 1.0, 0.0],
        },
    )
    # 05 v1 §3.2 / 06 §5 names; the candidate width is not an IID repetition count.
    assert "pass_at_1" not in summary and not any("pass" in key for key in summary)
    assert summary["pool_random_at_1"]["value"] == pytest.approx((0.25 + 1 + 0) / 3)
    assert summary["oracle_coverage_at_4"] == {"value": 2 / 3, "numerator": 2, "denominator": 3}
    assert summary["pool_widths"] == {"4": 3}
    assert summary["non_discriminating_acceptance"]["numerator"] == 2
    pointwise = summary["selectors"]["pointwise"]
    assert pointwise["selected_success"]["value"] == pytest.approx(2 / 3)
    assert pointwise["gap_closed"]["value"] == pytest.approx((2 - 1.25) / (2 - 1.25))
    # A failed selector's fallback never scores, and its gap closed is reported negative.
    fallback = summary["selectors"]["fallback"]
    assert fallback["selected_success"]["numerator"] == 0
    assert fallback["gap_closed"]["value"] == pytest.approx(-1.25 / 0.75)
    assert summary["selectors"]["listwise"]["gap_closed"]["value"] == pytest.approx(0.25 / 0.75)
    flat = m.score_acceptance_summary([[True, True], [False, False]], {"s": [True, None]})
    assert flat["selectors"]["s"]["gap_closed"] == {
        "value": "not-measurable",
        "numerator": None,
        "denominator": None,
    }
    with pytest.raises(ValueError, match="every planned pool"):
        m.score_acceptance_summary(acceptable, {"short": [True]})


def test_receipt_adapters_keep_inadmissible_output_as_a_wrong_item() -> None:
    accepted = {
        "accepted": True,
        "verdict": "supported",
        "probabilities": {"supported": 0.9, "contradicted": 0.05, "insufficient_evidence": 0.05},
    }
    rejected = {"accepted": False, "verdict": None, "probabilities": None}
    good = m.choice_record("s1", "c1", "supported", accepted)
    bad = m.choice_record("s2", "c1", "supported", rejected)
    assert good.correct and good.q == 0.9 and not bad.correct and bad.q is None
    noul = m.condition_records(
        "s3",
        "c2",
        {"has_contradiction": True, "missing_evidence": False},
        {"accepted": True, "probabilities": {"has_contradiction": 0.7, "missing_evidence": 0.2}},
    )
    assert noul["has_contradiction"].correct and noul["missing_evidence"].correct
    assert noul["missing_evidence"].q == pytest.approx(0.8)
    joint = m.joint_accuracy([(noul["has_contradiction"], noul["missing_evidence"])])
    assert joint.value == 1.0


def _panel_pairs(jev_shift: float) -> list[tuple[m.ChoiceRecord, m.ChoiceRecord]]:
    rng = random.Random(5)
    pairs = []
    for cluster in range(40):
        for item in range(6):
            identifier = f"c{cluster}-{item}"
            gold = LABELS[(cluster + item) % 3]
            llm_right = rng.random() < 0.85
            jev_right = llm_right if jev_shift == 0 else rng.random() < 0.85 + jev_shift
            other = LABELS[((cluster + item) % 3 + 1) % 3]
            llm = _choice(
                identifier, gold, gold if llm_right else other, 0.9, cluster=f"c{cluster}"
            )
            jev = _choice(
                identifier,
                gold,
                gold if jev_right else other,
                0.95 if jev_right else 0.5,
                cluster=f"c{cluster}",
            )
            pairs.append((llm, jev))
    return pairs


def test_choice_panel_report_applies_the_preregistered_decision() -> None:
    digest = "cd" * 32
    equal = m.choice_panel_report(_panel_pairs(0.0), split_manifest_sha256=digest, tau=0.9)
    assert equal["primary"]["numerator"] == 0 and equal["primary"]["denominator"] == 240
    assert equal["primary"]["interval"]["lower"] == 0 and equal["decision"] == "supported"
    assert equal["intervals"]["jev_auroc"]["lower"] == 1.0
    assert (
        equal["cascade"]["decision"] == "supported"
        and equal["cascade"]["coverage"]["numerator"] > 0
    )
    worse = m.choice_panel_report(_panel_pairs(-0.3), split_manifest_sha256=digest, tau=None)
    assert worse["decision"] == "not-supported"
    assert worse["cascade"] == {
        "tau": None,
        "decision": "not-supported",
        "reason": "no admissible τ",
    }
    again = m.choice_panel_report(_panel_pairs(0.0), split_manifest_sha256=digest, tau=0.9)
    assert again == equal
    with pytest.raises(ValueError):
        m.choice_panel_report(
            [(_choice("a", "supported", "supported"), _choice("b", "supported", "supported"))],
            split_manifest_sha256=digest,
            tau=None,
        )


def test_noul_panel_report_scores_joint_conditions_and_both_true_flags() -> None:
    pairs = []
    for cluster in range(12):
        for c, m_ in ((False, False), (True, False), (False, True), (True, True)):
            item = f"c{cluster}-{int(c)}{int(m_)}"
            llm = (
                _condition(item, c, 0.9 if c else 0.1, cluster=f"c{cluster}"),
                _condition(item, m_, 0.9 if m_ else 0.1, cluster=f"c{cluster}"),
            )
            jev = (
                _condition(item, c, 0.8 if c else 0.2, cluster=f"c{cluster}"),
                _condition(
                    item, m_, 0.3 if (c and m_) else (0.8 if m_ else 0.2), cluster=f"c{cluster}"
                ),
            )
            pairs.append((llm, jev))
    report = m.noul_panel_report(pairs, split_manifest_sha256="ef" * 32)
    assert report["joint_accuracy"]["llm"]["value"] == 1.0
    assert report["joint_accuracy"]["jev"]["value"] == pytest.approx(0.75)
    assert report["primary"]["numerator"] == -12 and report["decision"] == "not-supported"
    assert report["both_true_flagged"]["llm"]["value"] == 1.0
    assert report["both_true_flagged"]["jev"]["value"] == 0.0


def test_selection_freeze_binds_inputs_temperatures_and_tau() -> None:
    jev, astra = _cascade_fixture()
    rng = random.Random(2)
    conditions = {
        engine: {
            name: [_condition(f"{name}{k}", rng.random() < 0.7, 0.9) for k in range(50)]
            for name in ("has_contradiction", "missing_evidence")
        }
        for engine in ("llm", "jev")
    }
    freeze = m.selection_freeze(
        choice={"llm": astra, "jev": jev}, noul=conditions, inputs={"u1c_attempts": "a" * 64}
    )
    assert freeze["schema_id"] == "geode.jev-selection-freeze@1"
    assert freeze["cascade"]["tau"] == 0.95 and freeze["inputs"] == {"u1c_attempts": "a" * 64}
    assert freeze["temperatures"]["noul"]["has_contradiction"]["llm"]["temperature"] >= 2.0
    assert freeze["selection_metrics"]["choice"]["jev"]["planned"] == 100
    with pytest.raises(ValueError):
        m.selection_freeze(choice={"llm": astra}, noul=conditions, inputs={})


# ---------------------------------------------------------------------------
# 06 §7 model-free checks for pass@n / pass^n (05 v1 §3.5)
# ---------------------------------------------------------------------------

_CONTRACT = {
    "source_revision": "a" * 40,
    "policy_digest": "b" * 64,
    "reset_digest": "9" * 64,
    "input_sha256": "c" * 64,
    "verifier_sha256": "d" * 64,
}


def _trial(
    task: str, repetition: int, success: bool | None, *, kind: str = "trial", **changes: Any
) -> m.RepetitionTrial:
    contract = {**_CONTRACT, "input_sha256": hashlib.sha256(task.encode()).hexdigest()}
    contract.update(changes.pop("contract", {}))
    return m.RepetitionTrial(
        task,
        repetition,
        success,
        contract,
        kind=kind,
        trial_id=changes.pop("trial_id", f"{task}-r{repetition}"),
        **changes,
    )


def _matrix(outcomes: dict[str, list[bool | None]]) -> list[m.RepetitionTrial]:
    return [
        _trial(task, repetition, success)
        for task, values in outcomes.items()
        for repetition, success in enumerate(values)
    ]


def _reliability(trials: list[m.RepetitionTrial], tasks: list[str], reps: list[int], ns=(1, 2)):
    return m.repetition_reliability(trials, planned_tasks=tasks, planned_repetitions=reps, ns=ns)


def test_check1_n1_metrics_agree_and_zero_or_all_successes_are_the_bounds() -> None:
    for counts in ([(2, 1), (3, 0), (4, 4)], [(1, 1), (5, 2)], [(6, 3)]):
        assert m.pass_at_n(counts, 1).value == pytest.approx(m.pass_hat_n(counts, 1).value)
    # With a complete equal-size matrix both equal the plain trial success rate.
    assert m.pass_at_n([(2, 2), (2, 1), (2, 0)], 1).value == pytest.approx(3 / 6)
    for trials in (1, 2, 5):
        for n in range(1, trials + 1):
            assert m.pass_at_n([(trials, 0)], n).value == 0
            assert m.pass_hat_n([(trials, 0)], n).value == 0
            assert m.pass_at_n([(trials, trials)], n).value == 1
            assert m.pass_hat_n([(trials, trials)], n).value == 1


def test_check2_pass_at_n_is_nondecreasing_and_pass_hat_n_nonincreasing() -> None:
    rng = random.Random(0)
    for _ in range(200):
        trials = rng.randint(1, 8)
        counts = [(trials, rng.randint(0, trials)) for _ in range(rng.randint(1, 6))]
        at = [m.pass_at_n(counts, n).value for n in range(1, trials + 1)]
        hat = [m.pass_hat_n(counts, n).value for n in range(1, trials + 1)]
        assert all(b >= a - 1e-12 for a, b in itertools.pairwise(at))
        assert all(b <= a + 1e-12 for a, b in itertools.pairwise(hat))
        assert all(h <= a + 1e-12 for a, h in zip(at, hat, strict=True))


def test_check3_definition_example_gives_one_half_two_thirds_one_third() -> None:
    trials = _matrix({"A": [True, True], "B": [True, False], "C": [False, False]})
    report = _reliability(trials, ["A", "B", "C"], [0, 1])
    one, two = report["1"], report["2"]
    assert one["pass_at_n"]["value"] == pytest.approx(1 / 2)
    assert one["pass_hat_n"]["value"] == pytest.approx(1 / 2)
    assert two["pass_at_n"]["value"] == pytest.approx(2 / 3)
    assert two["pass_hat_n"]["value"] == pytest.approx(1 / 3)
    assert (two["pass_at_n"]["numerator"], two["pass_at_n"]["denominator"]) == (2.0, 3)
    assert two["status"] == "measured" and two["reasons"] == []
    assert (two["planned_tasks"], two["complete_tasks"], two["incomplete_tasks"]) == (3, 3, 0)
    assert (
        two["expected_repetitions"],
        two["observed_repetitions"],
        two["valid_repetitions"],
    ) == (6, 6, 6)
    # A pooled success rate substituted into p^n would give 1/4, not the task mean.
    assert m.pass_hat_n([(2, 2), (2, 0)], 2).value == pytest.approx(1 / 2)
    assert m.pass_at_n([(2, 2), (2, 0)], 2).value == pytest.approx(1 / 2)


def _reasons(
    trials: list[m.RepetitionTrial], tasks: list[str], reps: list[int], n: int
) -> set[str]:
    matrix = m.validate_repetition_matrix(
        trials, planned_tasks=tasks, planned_repetitions=reps, n=n
    )
    return {reason.value for reason in matrix.reasons}


def test_check4_rejects_short_duplicate_incomplete_mismatched_and_unknown_matrices() -> None:
    tasks, reps = ["A", "B"], [0, 1]
    good = _matrix({"A": [True, False], "B": [True, True]})
    assert _reasons(good, tasks, reps, 2) == set()
    # N_i < n: the pass^2 of a single-run unit (U6b) is not measurable.
    single = _matrix({"A": [True], "B": [False]})
    u6b = _reliability(single, tasks, [0])
    assert u6b["1"]["status"] == "measured"
    assert u6b["2"]["status"] == "not-measurable"
    assert u6b["2"]["reasons"] == ["insufficient_repetitions"]
    assert u6b["2"]["pass_hat_n"] == {
        "value": "not-measurable",
        "numerator": None,
        "denominator": None,
    }
    assert _reasons(good, tasks, reps, 3) == {"insufficient_repetitions"}
    # A duplicated repetition index and an unplanned repetition.
    assert _reasons([*good, _trial("A", 1, True, trial_id="A-r1-dup")], tasks, reps, 2) == {
        "duplicate_repetition"
    }
    assert _reasons([*good, _trial("A", 2, True)], tasks, reps, 2) == {"unplanned_repetition"}
    assert _reasons([*good, _trial("Z", 0, True)], tasks, reps, 2) == {"unplanned_repetition"}
    # An incomplete planned matrix (valid-only numbers are never substituted).
    missing = _reasons(good[:-1], tasks, reps, 1)
    assert missing == {"incomplete_matrix"}
    report = _reliability(good[:-1], tasks, reps, ns=(1,))
    assert report["1"]["pass_at_n"]["value"] == "not-measurable"
    assert (report["1"]["complete_tasks"], report["1"]["incomplete_tasks"]) == (1, 1)
    # Contract mismatch: source revision, policy or reset digest, input or verifier hash.
    for name in m.REPETITION_CONTRACT_FIELDS:
        changed = [*good[:-1], _trial("B", 1, True, contract={name: "e" * 64})]
        assert _reasons(changed, tasks, reps, 2) == {"contract_mismatch"}, name
        unbound = [*good[:-1], _trial("B", 1, True, contract={name: None})]
        assert _reasons(unbound, tasks, reps, 2) == {"contract_mismatch"}, name
    # The arm's policy and reset digests must agree across tasks too.
    for name in ("policy_digest", "reset_digest"):
        other = [*good[:2], *(_trial("B", r, True, contract={name: "f" * 64}) for r in reps)]
        assert _reasons(other, tasks, reps, 2) == {"contract_mismatch"}, name
    # Unknown outcome (infrastructure invalid, not run, evidence missing).
    unknown = [*good[:-1], _trial("B", 1, None)]
    assert _reasons(unknown, tasks, reps, 1) == {"unknown_outcome"}
    with pytest.raises(ValueError, match="not measurable"):
        m.pass_hat_n([(1, 1)], 2)
    with pytest.raises(ValueError):
        m.pass_at_n([(2, 3)], 1)
    with pytest.raises(ValueError):
        m.pass_at_n([], 1)


def test_check5_variants_repairs_candidates_and_replacements_are_not_repetitions() -> None:
    tasks = ["A", "B"]
    base = _matrix({"A": [False], "B": [True]})
    noise = [
        _trial("A", 1, True, kind="repair_round"),
        _trial("A", 2, True, kind="repair_round"),
        _trial("B", 1, True, kind="question_variant"),
        _trial("B", 2, False, kind="candidate"),
        _trial("B", 3, True, kind="candidate"),
    ]
    report = _reliability([*base, *noise], tasks, [0], ns=(1, 2))
    assert report["1"]["pass_at_n"]["value"] == pytest.approx(1 / 2)
    assert report["1"]["excluded_non_repetition_rows"] == len(noise)
    assert report["1"]["expected_repetitions"] == report["1"]["observed_repetitions"] == 2
    assert report["2"]["reasons"] == ["insufficient_repetitions"]
    # Counting the same rows as repetitions of a larger plan leaves the slots empty.
    assert _reasons([*base, *noise], tasks, [0, 1], 2) == {"incomplete_matrix"}
    # An approved replacement takes its original's slot; N does not grow.
    replacement = _trial("A", 0, True, kind="replacement", trial_id="A-r0-b", replaces="A-r0")
    replaced = _reliability([*base, replacement], tasks, [0], ns=(1,))["1"]
    assert replaced["pass_at_n"]["value"] == pytest.approx(1.0)
    assert replaced["superseded_by_replacement"] == 1 and replaced["valid_repetitions"] == 2
    assert [row["trials"] for row in replaced["per_task"]] == [1, 1]
    orphan = _trial("A", 0, True, kind="replacement", trial_id="x", replaces="missing")
    assert _reasons([*base, orphan], tasks, [0], 1) == {"incomplete_matrix"}
    twice = _trial("A", 0, True, kind="replacement", trial_id="A-r0-c", replaces="A-r0")
    assert _reasons([*base, replacement, twice], tasks, [0], 1) == {"duplicate_repetition"}
    with pytest.raises(ValueError, match="unknown repetition row kind"):
        _reasons([*base, _trial("A", 0, True, kind="retry")], tasks, [0], 1)


def test_policy_and_reset_digests_bind_the_frozen_boundary() -> None:
    boundary = {
        "session": "fresh sessions.db per trial",
        "files": "fresh task container and GEODE_HOME",
        "cache": "no prompt or Reflection memory carried across trials",
    }
    digest = m.reset_digest(boundary)
    assert digest == m.reset_digest(dict(reversed(list(boundary.items()))))
    assert digest != m.reset_digest({**boundary, "cache": "shared"})
    with pytest.raises(ValueError, match="session, files and cache"):
        m.reset_digest({key: value for key, value in boundary.items() if key != "cache"})
    policy = {"root": "gpt-6-astra/xhigh", "judge": "jev-1.13.0", "max_rounds": 6}
    assert m.policy_digest(policy) != m.policy_digest({**policy, "max_rounds": 5})
    with pytest.raises(ValueError, match="every setting"):
        m.policy_digest({**policy, "judge": None})


def test_stability_pairs_are_separate_from_order_and_paraphrase_flips() -> None:
    items = [
        {
            "gold": "supported",
            "rep1": "supported",
            "rep2": "supported",
            "order-rev": "contradicted",
            "para": "supported",
        },
        {
            "gold": "contradicted",
            "rep1": "contradicted",
            "rep2": "supported",
            "order-rev": "contradicted",
            "para": None,
        },
        {"gold": "supported", "rep1": None, "rep2": None, "order-rev": "supported", "para": None},
        {
            "gold": "insufficient_evidence",
            "rep1": "supported",
            "rep2": "supported",
            "order-rev": "supported",
            "para": "supported",
        },
    ]
    summary = m.stability_summary(items)
    assert summary["pair_consistency"] == {"value": 0.5, "numerator": 2, "denominator": 4}
    assert summary["pair_correct_consistency"] == {"value": 0.25, "numerator": 1, "denominator": 4}
    assert summary["flip_rate"]["order-rev"]["numerator"] == 2
    assert summary["flip_rate"]["para"]["numerator"] == 1
    assert "pass" not in json_keys(summary)
    sealed = m.stability_summary([{**row, "gold": None} for row in items])
    assert sealed["pair_correct_consistency"] is None
    with pytest.raises(ValueError, match="rep1, rep2, order-rev and para"):
        m.stability_summary([{"rep1": "supported"}])


def json_keys(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {json_keys(item)}" for key, item in value.items())
    return ""
