"""Pre-registered judgment metrics, cluster bootstrap and offline cascade/temperature fitting.

Formulas follow the Jev v3 preregistration (05 §3, §5). Invalid judgment output is
a wrong answer for accuracy and absent from probability metrics; an infrastructure
invalid never reaches these functions as a scored item. ``None`` means the value
is not measurable on the supplied items, never zero.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from typing import Any

NLL_FLOOR = 1e-6
ECE_BINS = 10
BOOTSTRAP_REPLICATES = 2000
CONFIDENCE_LEVEL = 0.95
TEMPERATURE_GRID = (0.25, 0.35, 0.5, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0, 5.6, 8.0)
TAU_GRID = (
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.95,
    0.975,
    0.99,
    1.00,
)
CASCADE_TOLERANCE = 0.02
NOUL_THRESHOLD = 0.5
VERDICT_LABELS = ("supported", "contradicted", "insufficient_evidence")


@dataclass(frozen=True)
class ChoiceRecord:
    """One planned Choice judgment; invalid output keeps its planned slot."""

    item_id: str
    cluster_id: str
    gold: str
    valid: bool
    verdict: str | None = None
    probabilities: Mapping[str, float] | None = None

    @property
    def correct(self) -> bool:
        return self.valid and self.verdict == self.gold

    @property
    def q(self) -> float | None:
        if not self.valid or not self.probabilities:
            return None
        return max(self.probabilities.values())


@dataclass(frozen=True)
class ConditionRecord:
    """One planned Noul condition judgment: probability that the condition holds."""

    item_id: str
    cluster_id: str
    gold: bool
    valid: bool
    p: float | None = None

    @property
    def prediction(self) -> bool | None:
        return None if not self.valid or self.p is None else self.p >= NOUL_THRESHOLD

    @property
    def correct(self) -> bool:
        return self.prediction is not None and self.prediction == self.gold

    @property
    def q(self) -> float | None:
        return None if not self.valid or self.p is None else max(self.p, 1 - self.p)


Scored = ChoiceRecord | ConditionRecord


@dataclass(frozen=True)
class Ratio:
    numerator: float
    denominator: int

    @property
    def value(self) -> float | None:
        return self.numerator / self.denominator if self.denominator else None

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "numerator": self.numerator, "denominator": self.denominator}


def accuracy(records: Sequence[Scored]) -> Ratio:
    """Correct / planned items; invalid output counts as wrong (05 §3.2)."""
    return Ratio(sum(record.correct for record in records), len(records))


def joint_accuracy(pairs: Sequence[tuple[ConditionRecord, ConditionRecord]]) -> Ratio:
    """Both Noul conditions correct for the same item."""
    return Ratio(sum(first.correct and second.correct for first, second in pairs), len(pairs))


def macro_f1(records: Sequence[ChoiceRecord], labels: Sequence[str]) -> float | None:
    """Mean per-class F1; invalid output is a gold-class FN and no class's FP."""
    if not records:
        return None
    scores = []
    for label in labels:
        tp = sum(r.valid and r.verdict == label and r.gold == label for r in records)
        fp = sum(r.valid and r.verdict == label and r.gold != label for r in records)
        fn = sum(r.gold == label and not (r.valid and r.verdict == label) for r in records)
        denominator = 2 * tp + fp + fn
        scores.append(2 * tp / denominator if denominator else 0.0)
    return sum(scores) / len(scores)


def _valid(records: Iterable[Scored]) -> list[Scored]:
    return [record for record in records if record.valid and record.q is not None]


def brier(records: Sequence[Scored]) -> float | None:
    """Choice: Σ_k (p_k − 1[k=y])²; Noul: (p − y)². Valid outputs only."""
    values = []
    for record in _valid(records):
        if isinstance(record, ChoiceRecord):
            assert record.probabilities is not None
            values.append(
                math.fsum(
                    (p - (1.0 if label == record.gold else 0.0)) ** 2
                    for label, p in record.probabilities.items()
                )
            )
        else:
            assert record.p is not None
            values.append((record.p - float(record.gold)) ** 2)
    return math.fsum(values) / len(values) if values else None


def _gold_probability(record: Scored) -> float:
    if isinstance(record, ChoiceRecord):
        assert record.probabilities is not None
        return float(record.probabilities.get(record.gold, 0.0))
    assert record.p is not None
    return record.p if record.gold else 1 - record.p


def nll(records: Sequence[Scored]) -> float | None:
    """Mean −ln max(p_y, 1e-6) over valid outputs."""
    values = [-math.log(max(_gold_probability(r), NLL_FLOOR)) for r in _valid(records)]
    return math.fsum(values) / len(values) if values else None


def ece(records: Sequence[Scored], bins: int = ECE_BINS) -> float | None:
    """Equal-width q bins, the last closed at 1.0: Σ_b (n_b/N_valid)·|acc_b − mean q_b|."""
    valid = _valid(records)
    if not valid:
        return None
    buckets: list[list[Scored]] = [[] for _ in range(bins)]
    for record in valid:
        assert record.q is not None
        buckets[min(int(record.q * bins), bins - 1)].append(record)
    total = 0.0
    for bucket in buckets:
        if bucket:
            acc = sum(record.correct for record in bucket) / len(bucket)
            confidence = math.fsum(record.q or 0.0 for record in bucket) / len(bucket)
            total += len(bucket) / len(valid) * abs(acc - confidence)
    return total


def auroc_error_detection(records: Sequence[Scored]) -> float | None:
    """Mann–Whitney AUROC for detecting wrong valid outputs with score 1 − q; ties count 0.5.

    Computed from average ranks, which equals the pairwise win count with half ties.
    """
    valid = _valid(records)
    scored = sorted((1 - (r.q or 0.0), not r.correct) for r in valid)
    positives = sum(is_error for _, is_error in scored)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return None
    rank_sum = 0.0
    index = 0
    while index < len(scored):
        end = index
        while end + 1 < len(scored) and scored[end + 1][0] == scored[index][0]:
            end += 1
        average_rank = (index + end) / 2 + 1
        rank_sum += average_rank * sum(is_error for _, is_error in scored[index : end + 1])
        index = end + 1
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


@dataclass(frozen=True)
class RiskCoverage:
    curve: tuple[tuple[float, float], ...]
    aurc: float | None
    risk_at: dict[str, float | None]


def risk_coverage(records: Sequence[Scored], points: Sequence[float] = (0.5, 0.8)) -> RiskCoverage:
    """Accept valid outputs by descending q (stable by item ID); invalid is never accepted.

    coverage = accepted / planned; risk = wrong accepted / accepted. AURC integrates
    risk over coverage steps of 1/planned. A requested coverage beyond the valid
    share is not measurable.
    """
    planned = len(records)
    ordered = sorted(_valid(records), key=lambda r: (-(r.q or 0.0), r.item_id))
    curve: list[tuple[float, float]] = []
    wrong = 0
    for index, record in enumerate(ordered, start=1):
        wrong += not record.correct
        curve.append((index / planned, wrong / index))
    aurc = math.fsum(risk for _, risk in curve) / planned if curve else None
    risk_at: dict[str, float | None] = {}
    for point in points:
        accepted = math.ceil(point * planned - 1e-9)
        risk_at[f"{point:g}"] = curve[accepted - 1][1] if 0 < accepted <= len(curve) else None
    return RiskCoverage(tuple(curve), aurc, risk_at)


def flip_rate(pairs: Sequence[tuple[str | None, str | None]]) -> Ratio:
    """Share of variant decisions that differ from the base decision (None = invalid)."""
    return Ratio(sum(base != variant for base, variant in pairs), len(pairs))


def paired_median_delta(pairs: Sequence[tuple[float | None, float | None]]) -> dict[str, Any]:
    """Median of (B − A) over pairs where both durations were observed (> 0)."""
    deltas = [
        second - first
        for first, second in pairs
        if first is not None and second is not None and first > 0 and second > 0
    ]
    return {
        "value": statistics.median(deltas) if deltas else None,
        "observed_pairs": len(deltas),
        "missing_pairs": len(pairs) - len(deltas),
    }


def duration_seconds(duration_ms: Any) -> float | None:
    """Recorded ``duration_ms`` in seconds; a missing or non-positive value is unknown."""
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
        return None
    if not math.isfinite(duration_ms) or duration_ms <= 0:
        return None
    return float(duration_ms) / 1000


def bootstrap_seed(split_manifest_sha256: str, metric_name: str) -> int:
    """``int(sha256(split_manifest_sha256 ∥ metric_name)[:16], 16)`` (05 §3.3)."""
    digest = hashlib.sha256((split_manifest_sha256 + metric_name).encode()).hexdigest()
    return int(digest[:16], 16)


def _quantile(ordered: Sequence[float], q: float) -> float:
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


@dataclass(frozen=True)
class Interval:
    estimate: float | None
    lower: float | None
    upper: float | None
    replicates: int
    measurable_replicates: int
    clusters: int
    seed: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "confidence": CONFIDENCE_LEVEL,
            "method": "source-cluster percentile bootstrap",
            "replicates": self.replicates,
            "measurable_replicates": self.measurable_replicates,
            "clusters": self.clusters,
            "seed": self.seed,
        }


def cluster_bootstrap(
    clusters: Mapping[str, Sequence[Any]],
    statistic: Callable[[list[Any]], float | None],
    *,
    seed: int,
    replicates: int = BOOTSTRAP_REPLICATES,
    min_clusters: int = 10,
) -> Interval:
    """Resample whole source clusters with replacement; paired rows move together.

    ``clusters`` maps a cluster ID to its rows (each row may hold both engines and
    every variant). Fewer than ``min_clusters`` observed clusters yields no interval.
    Replicates whose statistic is not measurable are excluded and counted.
    """
    keys = sorted(clusters)
    estimate = statistic([row for key in keys for row in clusters[key]])
    if len(keys) < min_clusters or estimate is None:
        return Interval(estimate, None, None, replicates, 0, len(keys), seed)
    rng = random.Random(seed)  # reproducible resampling, not a security control
    values = []
    for _ in range(replicates):
        sample = [row for _ in keys for row in clusters[keys[rng.randrange(len(keys))]]]
        value = statistic(sample)
        if value is not None and math.isfinite(value):
            values.append(value)
    if not values:
        return Interval(estimate, None, None, replicates, 0, len(keys), seed)
    values.sort()
    alpha = (1 - CONFIDENCE_LEVEL) / 2
    return Interval(
        estimate,
        _quantile(values, alpha),
        _quantile(values, 1 - alpha),
        replicates,
        len(values),
        len(keys),
        seed,
    )


def temperature_scale_choice(
    probabilities: Mapping[str, float], temperature: float
) -> dict[str, float]:
    """softmax(ln p / T); zero probabilities stay zero."""
    logs = {label: math.log(p) / temperature for label, p in probabilities.items() if p > 0}
    if not logs:
        return dict(probabilities)
    peak = max(logs.values())
    weights = {label: math.exp(value - peak) for label, value in logs.items()}
    total = math.fsum(weights.values())
    return {label: weights.get(label, 0.0) / total for label in probabilities}


def temperature_scale_condition(p: float, temperature: float) -> float:
    """σ(logit(p) / T); certain probabilities stay certain."""
    if p <= 0 or p >= 1:
        return p
    logit = math.log(p / (1 - p)) / temperature
    return 1 / (1 + math.exp(-logit))


def scaled(records: Sequence[Scored], temperature: float) -> list[Scored]:
    result: list[Scored] = []
    for record in records:
        if isinstance(record, ChoiceRecord):
            probabilities = (
                temperature_scale_choice(record.probabilities, temperature)
                if record.valid and record.probabilities
                else record.probabilities
            )
            result.append(
                ChoiceRecord(
                    record.item_id,
                    record.cluster_id,
                    record.gold,
                    record.valid,
                    record.verdict,
                    probabilities,
                )
            )
        else:
            p = (
                temperature_scale_condition(record.p, temperature)
                if record.valid and record.p is not None
                else record.p
            )
            result.append(
                ConditionRecord(record.item_id, record.cluster_id, record.gold, record.valid, p)
            )
    return result


def fit_temperature(
    records: Sequence[Scored], grid: Sequence[float] = TEMPERATURE_GRID
) -> dict[str, Any]:
    """Selection-only T minimizing mean NLL; ties prefer the value closest to 1 (05 §5)."""
    scored = []
    for temperature in grid:
        value = nll(scaled(records, temperature))
        if value is not None:
            scored.append((value, abs(math.log(temperature)), temperature))
    if not scored:
        return {"temperature": None, "nll": None, "grid": list(grid)}
    best = min(scored)
    return {"temperature": best[2], "nll": best[0], "grid": list(grid)}


@dataclass(frozen=True)
class CascadeOutcome:
    tau: float
    accuracy: Ratio
    coverage: Ratio

    def as_dict(self) -> dict[str, Any]:
        return {
            "tau": self.tau,
            "accuracy": self.accuracy.as_dict(),
            "coverage": self.coverage.as_dict(),
        }


def cascade_pairs(pairs: Sequence[tuple[ChoiceRecord, ChoiceRecord]], tau: float) -> CascadeOutcome:
    """Cascade over aligned (fallback, Jev) pairs; duplicates are allowed for resampling."""
    correct = 0
    accepted = 0
    for fallback, jev in pairs:
        if jev.valid and jev.q is not None and jev.q >= tau:
            accepted += 1
            correct += jev.correct
        else:
            correct += fallback.correct
    return CascadeOutcome(tau, Ratio(correct, len(pairs)), Ratio(accepted, len(pairs)))


def cascade(
    jev: Sequence[ChoiceRecord], fallback: Sequence[ChoiceRecord], tau: float
) -> CascadeOutcome:
    """Offline cascade: a valid Jev decision with q ≥ τ stands, otherwise the fallback decides.

    Records pair by item ID. An invalid fallback is wrong. A decision taken after a
    Jev failure is never counted as Jev acceptance (05 §3.2).
    """
    by_item = {record.item_id: record for record in fallback}
    jev_items = [record.item_id for record in jev]
    if (
        len(by_item) != len(fallback)
        or len(set(jev_items)) != len(jev_items)
        or set(jev_items) != set(by_item)
    ):
        raise ValueError("cascade engines must cover the same planned items once")
    return cascade_pairs([(by_item[record.item_id], record) for record in jev], tau)


def select_tau(
    jev: Sequence[ChoiceRecord],
    fallback: Sequence[ChoiceRecord],
    grid: Sequence[float] = TAU_GRID,
    tolerance: float = CASCADE_TOLERANCE,
) -> dict[str, Any]:
    """Selection-only τ: maximum coverage within ``tolerance`` of fallback accuracy.

    Equal coverage prefers the larger τ. A grid whose only admissible τ has zero
    coverage reports no admissible τ.
    """
    reference = accuracy(fallback).value
    outcomes = [cascade(jev, fallback, tau) for tau in grid]
    admissible = [
        outcome
        for outcome in outcomes
        if reference is not None
        and outcome.accuracy.value is not None
        and outcome.accuracy.value >= reference - tolerance - 1e-12
        and outcome.coverage.numerator > 0
    ]
    chosen = max(admissible, key=lambda item: (item.coverage.numerator, item.tau), default=None)
    return {
        "tau": chosen.tau if chosen else None,
        "admissible": chosen is not None,
        "fallback_accuracy": reference,
        "tolerance": tolerance,
        "grid": [outcome.as_dict() for outcome in outcomes],
    }


def score_top1(
    selections: Sequence[tuple[str | None, frozenset[str]]],
) -> Ratio:
    """Selected candidate in the oracle-best set; invalid or fallback selection (None) is wrong."""
    return Ratio(
        sum(chosen is not None and chosen in best for chosen, best in selections), len(selections)
    )


def score_regret(best_grade: int, selected_grade: int | None) -> int | None:
    return None if selected_grade is None else best_grade - selected_grade


SCORE_POOL_WIDTH = 4  # best_of=4 candidates per selection step (MAX_BEST_OF)
NOT_MEASURABLE = "not-measurable"


def _exact_number(value: Fraction) -> int | float:
    return int(value) if value.denominator == 1 else float(value)


def _exact_ratio(numerator: Fraction, denominator: int) -> dict[str, Any]:
    return {
        "value": float(numerator / denominator) if denominator else None,
        "numerator": _exact_number(numerator),
        "denominator": denominator,
    }


def _acceptance_value(value: bool | float | None) -> Fraction:
    """A selection's acceptance in [0, 1]; ``None`` (invalid or fallback) counts as 0."""
    if value is None or value is False:
        return Fraction(0)
    if value is True:
        return Fraction(1)
    if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1:
        return Fraction(value)
    raise ValueError("a selection acceptance value must lie in [0, 1]")


def score_acceptance_summary(
    acceptable: Sequence[Sequence[bool]],
    selected: Mapping[str, Sequence[bool | float | None]],
    *,
    planned_width: int = SCORE_POOL_WIDTH,
) -> dict[str, Any]:
    """Score auxiliary acceptance metrics over planned pools (05 v1 §3.2, 06 §5).

    ``acceptable[i]`` holds one flag per candidate submitted to pool ``i``'s
    selection, from the independent task oracle's frozen acceptance rule (never a
    partial grade or "best in pool"). ``selected[name][i]`` is that selector's
    acceptance on pool ``i``: 0 or 1 for a pointwise pick, the mean of the orders for
    the listwise reference; ``None`` is an invalid or fallback selection and counts
    as 0 even when the fallback candidate would pass the task oracle.

    - pool-random@1 = mean over pools of acceptable candidates / pool width;
    - oracle-coverage@w = share of pools with at least one acceptable candidate;
    - selected success = mean selected acceptance;
    - gap closed = (selected − pool-random@1) / (oracle-coverage@w − pool-random@1),
      not-measurable when the denominator is 0; a negative value is reported.

    The candidate width ``w`` is not an IID repetition count, so none of these is a
    pass@k estimate.
    """
    pools = len(acceptable)
    if pools == 0:
        raise ValueError("Score acceptance needs at least one planned pool")
    if any(not flags for flags in acceptable):
        raise ValueError("every planned pool needs its candidates' acceptance flags")
    random_sum = sum((Fraction(sum(flags), len(flags)) for flags in acceptable), Fraction(0))
    coverage_sum = Fraction(sum(any(flags) for flags in acceptable))
    headroom = coverage_sum - random_sum
    widths: dict[str, int] = {}
    for flags in acceptable:
        widths[str(len(flags))] = widths.get(str(len(flags)), 0) + 1
    selectors: dict[str, Any] = {}
    for name, values in selected.items():
        if len(values) != pools:
            raise ValueError(f"{name}: selection values must cover every planned pool")
        chosen = sum((_acceptance_value(value) for value in values), Fraction(0))
        gain = chosen - random_sum
        selectors[name] = {
            "selected_success": _exact_ratio(chosen, pools),
            "gap_closed": {
                "value": float(gain / headroom) if headroom else NOT_MEASURABLE,
                # Pool counts cancel: both terms are sums over the same planned pools.
                "numerator": _exact_number(gain) if headroom else None,
                "denominator": _exact_number(headroom) if headroom else None,
            },
        }
    return {
        "pools": pools,
        "planned_width": planned_width,
        "pool_widths": dict(sorted(widths.items())),
        "pool_random_at_1": _exact_ratio(random_sum, pools),
        f"oracle_coverage_at_{planned_width}": _exact_ratio(coverage_sum, pools),
        "non_discriminating_acceptance": _exact_ratio(
            Fraction(sum(len(set(flags)) == 1 for flags in acceptable)), pools
        ),
        "selectors": selectors,
    }


def mean_order_hit(hits: Sequence[Sequence[bool]]) -> float | None:
    """Listwise reference: per-pool mean of per-order hits (0, 0.5 or 1), averaged."""
    if not hits:
        return None
    return math.fsum(sum(order) / len(order) for order in hits) / len(hits)


def choice_record(
    item_id: str, cluster_id: str, gold: str, receipt: Mapping[str, Any]
) -> ChoiceRecord:
    """Score one matched-verifier receipt; an inadmissible completion stays a wrong item."""
    admitted = receipt.get("accepted") is True
    return ChoiceRecord(
        item_id,
        cluster_id,
        gold,
        admitted,
        receipt.get("verdict") if admitted else None,
        receipt.get("probabilities") if admitted else None,
    )


def condition_records(
    item_id: str, cluster_id: str, gold: Mapping[str, bool], receipt: Mapping[str, Any]
) -> dict[str, ConditionRecord]:
    """Split one Noul receipt into its two independently scored condition records."""
    admitted = receipt.get("accepted") is True
    probabilities = receipt.get("probabilities") if admitted else None
    return {
        key: ConditionRecord(
            item_id,
            cluster_id,
            value,
            admitted,
            float(probabilities[key]) if isinstance(probabilities, Mapping) else None,
        )
        for key, value in gold.items()
    }


SELECTION_FREEZE_SCHEMA_ID = "geode.jev-selection-freeze@1"
NON_INFERIORITY_MARGIN = 0.05


def _engine_metrics(records: Sequence[Scored]) -> dict[str, Any]:
    return {
        "accuracy": accuracy(records).as_dict(),
        "brier": brier(records),
        "nll": nll(records),
        "ece": ece(records),
        "auroc_error_detection": auroc_error_detection(records),
        "valid": sum(record.valid for record in records),
        "planned": len(records),
    }


def selection_freeze(
    *,
    choice: Mapping[str, Sequence[ChoiceRecord]],
    noul: Mapping[str, Mapping[str, Sequence[ConditionRecord]]],
    inputs: Mapping[str, str],
) -> dict[str, Any]:
    """Fit T per engine × question and the Choice cascade τ on selection outputs only.

    ``choice`` maps engine (``llm``/``jev``) to Choice records; ``noul`` maps engine to
    condition → records. ``inputs`` binds the U1 attempts/analysis digests. The
    returned document is written once as ``selection-freeze.json`` before any test call.
    """
    if set(choice) != {"llm", "jev"} or set(noul) != {"llm", "jev"}:
        raise ValueError("selection freeze needs both engines for both primitives")
    temperatures: dict[str, Any] = {
        "choice": {engine: fit_temperature(records) for engine, records in choice.items()},
        "noul": {
            condition: {engine: fit_temperature(noul[engine][condition]) for engine in noul}
            for condition in sorted(noul["llm"])
        },
    }
    return {
        "schema_id": SELECTION_FREEZE_SCHEMA_ID,
        "schema_version": 1,
        "temperature_grid": list(TEMPERATURE_GRID),
        "tau_grid": list(TAU_GRID),
        "temperatures": temperatures,
        "cascade": select_tau(choice["jev"], choice["llm"]),
        "selection_metrics": {
            "choice": {engine: _engine_metrics(records) for engine, records in choice.items()},
            "noul": {
                engine: {
                    condition: _engine_metrics(records)
                    for condition, records in sorted(conditions.items())
                }
                for engine, conditions in noul.items()
            },
        },
        "inputs": dict(sorted(inputs.items())),
        "authority": "selection split only; not refitted after any test call",
    }


def _clusters_of(rows: Sequence[Any], key: Callable[[Any], str]) -> dict[str, list[Any]]:
    clusters: dict[str, list[Any]] = {}
    for row in rows:
        clusters.setdefault(key(row), []).append(row)
    return clusters


def _paired(
    pairs: Sequence[tuple[Scored, Scored]], metric: Callable[[Sequence[Scored]], float | None]
) -> Callable[[list[tuple[Scored, Scored]]], float | None]:
    def statistic(rows: list[tuple[Scored, Scored]]) -> float | None:
        first = metric([row[0] for row in rows])
        second = metric([row[1] for row in rows])
        return None if first is None or second is None else second - first

    return statistic


def _decide(interval: Interval, margin: float) -> str:
    if interval.lower is not None and interval.lower > -margin:
        return "supported"
    if interval.upper is not None and interval.upper < -margin:
        return "not-supported"
    return "mixed"


def choice_panel_report(
    pairs: Sequence[tuple[ChoiceRecord, ChoiceRecord]],
    *,
    split_manifest_sha256: str,
    tau: float | None,
    min_clusters: int = 10,
    prefix: str = "m7_choice",
) -> dict[str, Any]:
    """Paired LLM (first) vs Jev (second) Choice summary with cluster intervals (05 §3.4)."""
    if any(a.item_id != b.item_id or a.cluster_id != b.cluster_id for a, b in pairs):
        raise ValueError("paired records must share item and cluster")
    clusters = _clusters_of(pairs, lambda row: row[0].cluster_id)

    def interval(name: str, statistic: Callable[[list[Any]], float | None]) -> Interval:
        return cluster_bootstrap(
            clusters,
            statistic,
            seed=bootstrap_seed(split_manifest_sha256, f"{prefix}_{name}"),
            min_clusters=min_clusters,
        )

    llm = [row[0] for row in pairs]
    jev = [row[1] for row in pairs]
    delta = interval("paired_accuracy_delta", _paired(pairs, lambda r: accuracy(r).value))
    jev_auroc = interval("jev_auroc", lambda rows: auroc_error_detection([r[1] for r in rows]))
    report: dict[str, Any] = {
        "primary": {
            "name": f"{prefix}_paired_accuracy_delta",
            "numerator": accuracy(jev).numerator - accuracy(llm).numerator,
            "denominator": len(pairs),
            "value": (accuracy(jev).numerator - accuracy(llm).numerator) / len(pairs)
            if pairs
            else None,
            "interval": delta.as_dict(),
        },
        "engines": {"llm": _engine_metrics(llm), "jev": _engine_metrics(jev)},
        "intervals": {
            "llm_auroc": interval(
                "llm_auroc", lambda rows: auroc_error_detection([r[0] for r in rows])
            ).as_dict(),
            "jev_auroc": jev_auroc.as_dict(),
            "auroc_delta": interval("auroc_delta", _paired(pairs, auroc_error_detection)).as_dict(),
            "brier_delta": interval("brier_delta", _paired(pairs, brier)).as_dict(),
            "ece_delta": interval("ece_delta", _paired(pairs, ece)).as_dict(),
        },
        "macro_f1": {"llm": macro_f1(llm, VERDICT_LABELS), "jev": macro_f1(jev, VERDICT_LABELS)},
    }
    supported = (
        delta.lower is not None
        and delta.lower > -NON_INFERIORITY_MARGIN
        and jev_auroc.lower is not None
        and jev_auroc.lower > 0.5
    )
    report["decision"] = (
        "supported"
        if supported
        else "not-supported"
        if delta.upper is not None and delta.upper < -NON_INFERIORITY_MARGIN
        else "mixed"
    )
    if tau is None:
        report["cascade"] = {"tau": None, "decision": "not-supported", "reason": "no admissible τ"}
    else:
        frozen = cascade(jev, llm, tau)
        fallback_value = accuracy(llm).value
        gap = interval(
            "cascade_minus_fallback",
            lambda rows: (
                (cascade_pairs(rows, tau).accuracy.value or 0.0)
                - (accuracy([r[0] for r in rows]).value or 0.0)
            ),
        )
        point = (
            frozen.accuracy.value is not None
            and fallback_value is not None
            and frozen.accuracy.value >= fallback_value - CASCADE_TOLERANCE - 1e-12
        )
        report["cascade"] = {
            **frozen.as_dict(),
            "fallback_accuracy": fallback_value,
            "interval": gap.as_dict(),
            "decision": "supported" if point else "not-supported",
            "uncertain": gap.lower is not None and gap.lower < -CASCADE_TOLERANCE,
        }
    return report


def noul_panel_report(
    pairs: Sequence[
        tuple[tuple[ConditionRecord, ConditionRecord], tuple[ConditionRecord, ConditionRecord]]
    ],
    *,
    split_manifest_sha256: str,
    min_clusters: int = 10,
    prefix: str = "m7_noul",
) -> dict[str, Any]:
    """Paired joint accuracy for (contradiction, missing) per item: LLM first, Jev second."""
    clusters = _clusters_of(pairs, lambda row: row[0][0].cluster_id)

    def joint(rows: Sequence[Any], side: int) -> float | None:
        return joint_accuracy([row[side] for row in rows]).value

    delta = cluster_bootstrap(
        clusters,
        lambda rows: None if not rows else (joint(rows, 1) or 0.0) - (joint(rows, 0) or 0.0),
        seed=bootstrap_seed(split_manifest_sha256, f"{prefix}_joint_accuracy_delta"),
        min_clusters=min_clusters,
    )
    llm_joint = joint_accuracy([row[0] for row in pairs])
    jev_joint = joint_accuracy([row[1] for row in pairs])
    conditions: dict[str, Any] = {}
    for index, name in enumerate(("has_contradiction", "missing_evidence")):
        conditions[name] = {
            "llm": _engine_metrics([row[0][index] for row in pairs]),
            "jev": _engine_metrics([row[1][index] for row in pairs]),
        }
    both_true = [row for row in pairs if row[0][0].gold and row[0][1].gold]
    return {
        "primary": {
            "name": f"{prefix}_joint_accuracy_delta",
            "numerator": jev_joint.numerator - llm_joint.numerator,
            "denominator": len(pairs),
            "value": (jev_joint.numerator - llm_joint.numerator) / len(pairs) if pairs else None,
            "interval": delta.as_dict(),
        },
        "joint_accuracy": {"llm": llm_joint.as_dict(), "jev": jev_joint.as_dict()},
        "conditions": conditions,
        "both_true_flagged": {
            side: Ratio(
                sum(
                    row[index][0].prediction is True and row[index][1].prediction is True
                    for row in both_true
                ),
                len(both_true),
            ).as_dict()
            for index, side in enumerate(("llm", "jev"))
        },
        "decision": _decide(delta, NON_INFERIORITY_MARGIN),
    }


# ---------------------------------------------------------------------------
# U2s stability: identical-question pairs apart from order/paraphrase flips
# ---------------------------------------------------------------------------

STABILITY_BASE = "rep1"
STABILITY_REPEAT = "rep2"
STABILITY_VARIANTS = ("order-rev", "para")


def stability_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """U2s auxiliary report: pair consistency of the identical question, flips per variant.

    Each item maps ``rep1``, ``rep2``, ``order-rev`` and ``para`` to one planned
    decision (``None`` = invalid output) and may carry ``gold`` once unsealed.

    - ``pair_consistency``: rep1 and rep2 are both valid and equal (06 §5);
    - ``pair_correct_consistency``: both repeats equal gold, over items with gold;
    - ``flip_rate``: per variant, the variant decision differs from rep1 (05 §3.2).

    The same question asked twice is the only repetition here. The order-reversed
    and paraphrased questions are variants of a different question set: they are
    never pooled with the repeats, and no pass^4 over four variants is produced.
    """
    keys = (STABILITY_BASE, STABILITY_REPEAT, *STABILITY_VARIANTS)
    if any(not all(key in item for key in keys) for item in items):
        raise ValueError("every stability item needs rep1, rep2, order-rev and para")
    consistent = sum(
        item[STABILITY_BASE] is not None and item[STABILITY_BASE] == item[STABILITY_REPEAT]
        for item in items
    )
    graded = [item for item in items if item.get("gold") is not None]
    both_correct = sum(
        item[STABILITY_BASE] == item["gold"] and item[STABILITY_REPEAT] == item["gold"]
        for item in graded
    )
    return {
        "items": len(items),
        "pair_consistency": Ratio(consistent, len(items)).as_dict(),
        "pair_correct_consistency": Ratio(both_correct, len(graded)).as_dict() if graded else None,
        "flip_rate": {
            variant: flip_rate([(item[STABILITY_BASE], item[variant]) for item in items]).as_dict()
            for variant in STABILITY_VARIANTS
        },
        "not_reported": "variants are not independent repetitions; no pass^n over them",
    }


# ---------------------------------------------------------------------------
# Repetition reliability: pass@n and pass^n (05 v1 §3.5, 06 §3-§7)
# ---------------------------------------------------------------------------

# Every counted repetition of one task must share these digests; the arm-scoped
# subset must also agree across the arm's tasks (06 §3, §6).
REPETITION_CONTRACT_FIELDS = (
    "source_revision",
    "policy_digest",
    "reset_digest",
    "input_sha256",
    "verifier_sha256",
)
ARM_CONTRACT_FIELDS = ("source_revision", "policy_digest", "reset_digest")
RESET_BOUNDARY_KEYS = ("session", "files", "cache")
INDEPENDENT_KIND = "trial"
REPLACEMENT_KIND = "replacement"
# Rows that live inside one trial or one selection step; never a repetition.
NON_REPETITION_KINDS = frozenset({"repair_round", "question_variant", "candidate"})


class RepetitionRejection(StrEnum):
    """Why a planned repetition aggregate is not measurable (06 §6-§7)."""

    INSUFFICIENT_REPETITIONS = "insufficient_repetitions"
    DUPLICATE_REPETITION = "duplicate_repetition"
    UNPLANNED_REPETITION = "unplanned_repetition"
    INCOMPLETE_MATRIX = "incomplete_matrix"
    CONTRACT_MISMATCH = "contract_mismatch"
    UNKNOWN_OUTCOME = "unknown_outcome"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def reset_digest(boundary: Mapping[str, Any]) -> str:
    """SHA-256 of one cell's frozen reset boundary (runner-owned ``freeze.json``).

    ``boundary`` states how a fresh trial resets its session store, files and caches,
    so no earlier answer or Reflection memory reaches a later repetition (06 §3).
    """
    if set(boundary) != set(RESET_BOUNDARY_KEYS) or any(
        boundary[key] in (None, "", {}, []) for key in RESET_BOUNDARY_KEYS
    ):
        raise ValueError("a reset boundary must state session, files and cache")
    return _canonical_digest(boundary)


def policy_digest(policy: Mapping[str, Any]) -> str:
    """SHA-256 of one cell's frozen policy: model route, effort, prompts, tools,
    verifier, budget and repair limits. Repetitions combine only when it is equal."""
    if not policy or any(value in (None, "") for value in policy.values()):
        raise ValueError("a frozen policy must name every setting")
    return _canonical_digest(policy)


def _task_counts(counts: Sequence[tuple[int, int]], n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive integer")
    if not counts:
        raise ValueError("pass@n and pass^n need at least one task")
    for trials, successes in counts:
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in (trials, successes)
        ):
            raise ValueError("task counts must be integers (N_i, c_i)")
        if not 0 <= successes <= trials:
            raise ValueError("a task's successes must lie in 0..N_i")
        if trials < n:
            raise ValueError(f"a task has N_i={trials} < n={n}; the aggregate is not measurable")


def _mean_of_task_ratios(ratios: Sequence[Fraction]) -> Ratio:
    total = sum(ratios, Fraction(0))
    return Ratio(float(total), len(ratios))


def pass_at_n(counts: Sequence[tuple[int, int]], n: int) -> Ratio:
    """Equal-weight mean over tasks of 1 − C(N_i − c_i, n) / C(N_i, n).

    ``counts`` holds each task's independent strict-success tally ``(N_i, c_i)``.
    The per-task combinatorial ratio is computed first; a pooled success rate is
    never substituted into 1 − (1 − p)^n.
    """
    _task_counts(counts, n)
    return _mean_of_task_ratios(
        [
            1 - Fraction(math.comb(trials - successes, n), math.comb(trials, n))
            for trials, successes in counts
        ]
    )


def pass_hat_n(counts: Sequence[tuple[int, int]], n: int) -> Ratio:
    """Equal-weight mean over tasks of C(c_i, n) / C(N_i, n) (τ-bench pass^n)."""
    _task_counts(counts, n)
    return _mean_of_task_ratios(
        [Fraction(math.comb(successes, n), math.comb(trials, n)) for trials, successes in counts]
    )


@dataclass(frozen=True)
class RepetitionTrial:
    """One observed row offered to one arm's repetition aggregate.

    ``kind`` is ``trial`` for a full trial after the frozen reset, ``replacement`` for
    an approved replacement of such a trial (it replaces ``replaces`` in the same
    slot and never adds a repetition), or a within-trial / within-selection row
    (``repair_round``, ``question_variant``, ``candidate``) that is never counted.
    ``strict_success`` is ``None`` when the outcome is unknown: infrastructure
    invalid, not executed or evidence missing. A judged failure is ``False``.
    """

    task_id: str
    repetition: int
    strict_success: bool | None
    contract: Mapping[str, Any] = field(default_factory=dict)
    kind: str = INDEPENDENT_KIND
    trial_id: str | None = None
    replaces: str | None = None
    source: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepetitionMatrix:
    """Validated planned matrix for one arm; ``rejections`` empty means measurable at ``n``."""

    n: int
    planned_tasks: tuple[str, ...]
    planned_repetitions: tuple[int, ...]
    counted: Mapping[str, tuple[RepetitionTrial, ...]]
    rejections: tuple[tuple[RepetitionRejection, str], ...]
    complete_tasks: tuple[str, ...]
    excluded: tuple[RepetitionTrial, ...]
    superseded: tuple[RepetitionTrial, ...]
    observed_repetitions: int
    valid_repetitions: int

    @property
    def expected_repetitions(self) -> int:
        return len(self.planned_tasks) * len(self.planned_repetitions)

    @property
    def incomplete_tasks(self) -> tuple[str, ...]:
        complete = set(self.complete_tasks)
        return tuple(task for task in self.planned_tasks if task not in complete)

    @property
    def reasons(self) -> tuple[RepetitionRejection, ...]:
        return tuple(dict.fromkeys(reason for reason, _ in self.rejections))

    def counts(self) -> list[tuple[int, int]]:
        """(N_i, c_i) per planned task in plan order; valid only without rejections."""
        return [
            (
                len(self.counted[task]),
                sum(row.strict_success is True for row in self.counted[task]),
            )
            for task in self.planned_tasks
        ]


def _slot_rows(
    rows: Sequence[RepetitionTrial],
    reject: Callable[[RepetitionRejection, str], None],
) -> tuple[RepetitionTrial | None, list[RepetitionTrial]]:
    """Resolve one planned slot to its counted row; replacements stand in for originals."""
    originals = [row for row in rows if row.kind == INDEPENDENT_KIND]
    replacements = [row for row in rows if row.kind == REPLACEMENT_KIND]
    if len(originals) > 1:
        reject(RepetitionRejection.DUPLICATE_REPETITION, "a planned slot has two trials")
        return None, []
    if not originals:
        if replacements:
            reject(
                RepetitionRejection.INCOMPLETE_MATRIX,
                "a replacement has no preserved original trial in its slot",
            )
        return None, []
    original = originals[0]
    if not replacements:
        return original, []
    if len(replacements) > 1:
        reject(RepetitionRejection.DUPLICATE_REPETITION, "a trial has two replacements")
        return None, []
    replacement = replacements[0]
    if original.trial_id is None or replacement.replaces != original.trial_id:
        reject(
            RepetitionRejection.INCOMPLETE_MATRIX,
            "a replacement does not name the trial it replaces",
        )
        return None, []
    return replacement, [original]


def validate_repetition_matrix(
    trials: Sequence[RepetitionTrial],
    *,
    planned_tasks: Sequence[str],
    planned_repetitions: Sequence[int],
    n: int,
    contract_fields: Sequence[str] = REPETITION_CONTRACT_FIELDS,
    arm_contract_fields: Sequence[str] = ARM_CONTRACT_FIELDS,
) -> RepetitionMatrix:
    """Check one arm's frozen task × repetition plan before any pass@n or pass^n.

    Rejections (enumerated, never silently dropped): N_i < n, a duplicate or
    unplanned repetition, a missing planned slot, a contract digest that differs or
    is missing, and an unknown outcome. Repair rounds, question variants and
    candidates are excluded from N; an approved replacement takes its original's
    slot, which stays preserved in ``superseded``.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive integer")
    tasks = tuple(planned_tasks)
    repetitions = tuple(planned_repetitions)
    if not tasks or not repetitions:
        raise ValueError("a repetition plan needs tasks and repetitions")
    if len(set(tasks)) != len(tasks) or len(set(repetitions)) != len(repetitions):
        raise ValueError("planned tasks and repetitions must be unique")
    if not set(arm_contract_fields) <= set(contract_fields):
        raise ValueError("arm-scoped contract fields must be contract fields")
    rejections: list[tuple[RepetitionRejection, str]] = []

    def reject(reason: RepetitionRejection, detail: str) -> None:
        rejections.append((reason, detail))

    excluded: list[RepetitionTrial] = []
    slots: dict[tuple[str, int], list[RepetitionTrial]] = {}
    known_kinds = {INDEPENDENT_KIND, REPLACEMENT_KIND, *NON_REPETITION_KINDS}
    for row in trials:
        if row.kind not in known_kinds:
            raise ValueError(f"unknown repetition row kind {row.kind!r}")
        if row.kind in NON_REPETITION_KINDS:
            excluded.append(row)
            continue
        if row.task_id not in tasks or row.repetition not in repetitions:
            reject(
                RepetitionRejection.UNPLANNED_REPETITION,
                f"{row.task_id} repetition {row.repetition} is outside the frozen plan",
            )
            continue
        slots.setdefault((row.task_id, row.repetition), []).append(row)
    counted: dict[str, tuple[RepetitionTrial, ...]] = {}
    superseded: list[RepetitionTrial] = []
    complete: list[str] = []
    observed = valid = 0
    arm_values: dict[str, set[Any]] = {name: set() for name in arm_contract_fields}
    for task in tasks:
        rows: list[RepetitionTrial] = []
        task_ok = True
        for repetition in repetitions:
            chosen, replaced = _slot_rows(slots.get((task, repetition), []), reject)
            superseded.extend(replaced)
            if chosen is None:
                task_ok = False
                if not slots.get((task, repetition)):
                    reject(
                        RepetitionRejection.INCOMPLETE_MATRIX,
                        f"{task} repetition {repetition} was not observed",
                    )
                continue
            observed += 1
            if chosen.strict_success is None:
                task_ok = False
                reject(
                    RepetitionRejection.UNKNOWN_OUTCOME,
                    f"{task} repetition {repetition} has an unknown outcome",
                )
                continue
            valid += 1
            rows.append(chosen)
        for name in contract_fields:
            values = {row.contract.get(name) for row in rows}
            if None in values or "" in values:
                task_ok = False
                reject(RepetitionRejection.CONTRACT_MISMATCH, f"{task} lacks {name}")
            elif len(values) > 1:
                task_ok = False
                reject(
                    RepetitionRejection.CONTRACT_MISMATCH, f"{task} repetitions differ in {name}"
                )
            elif name in arm_values:
                arm_values[name] |= values
        counted[task] = tuple(rows)
        if task_ok:
            complete.append(task)
    for name, values in arm_values.items():
        if len(values) > 1:
            reject(RepetitionRejection.CONTRACT_MISMATCH, f"arm tasks differ in {name}")
    if len(complete) == len(tasks):
        short = [task for task in tasks if len(counted[task]) < n]
        if short:
            reject(
                RepetitionRejection.INSUFFICIENT_REPETITIONS,
                f"{len(short)} task(s) have N_i < n={n}",
            )
    return RepetitionMatrix(
        n=n,
        planned_tasks=tasks,
        planned_repetitions=repetitions,
        counted=counted,
        rejections=tuple(rejections),
        complete_tasks=tuple(complete),
        excluded=tuple(excluded),
        superseded=tuple(superseded),
        observed_repetitions=observed,
        valid_repetitions=valid,
    )


def _reliability_value(matrix: RepetitionMatrix, estimator: Callable[..., Ratio]) -> dict[str, Any]:
    if matrix.rejections:
        return {"value": NOT_MEASURABLE, "numerator": None, "denominator": None}
    return estimator(matrix.counts(), matrix.n).as_dict()


def repetition_reliability(
    trials: Sequence[RepetitionTrial],
    *,
    planned_tasks: Sequence[str],
    planned_repetitions: Sequence[int],
    ns: Sequence[int] = (1, 2),
    contract_fields: Sequence[str] = REPETITION_CONTRACT_FIELDS,
    arm_contract_fields: Sequence[str] = ARM_CONTRACT_FIELDS,
) -> dict[str, Any]:
    """pass@n and pass^n for one arm with the provenance fields of 06 §6.

    An incomplete or inconsistent planned matrix makes every n not-measurable with
    enumerated reasons; N_i < n makes that n not-measurable ("반복 부족"). Values are
    equal-weight task means, ``numerator`` is the sum of per-task ratios and
    ``denominator`` the complete task count. Judged failures stay in the denominator.
    """
    if not ns or len(set(ns)) != len(ns):
        raise ValueError("ns must list distinct positive integers")
    report: dict[str, Any] = {}
    for n in ns:
        matrix = validate_repetition_matrix(
            trials,
            planned_tasks=planned_tasks,
            planned_repetitions=planned_repetitions,
            n=n,
            contract_fields=contract_fields,
            arm_contract_fields=arm_contract_fields,
        )
        measured = not matrix.rejections
        report[str(n)] = {
            "n": n,
            "status": "measured" if measured else NOT_MEASURABLE,
            "reasons": [reason.value for reason in matrix.reasons],
            "rejections": [
                {"reason": reason.value, "detail": detail} for reason, detail in matrix.rejections
            ],
            "pass_at_n": _reliability_value(matrix, pass_at_n),
            "pass_hat_n": _reliability_value(matrix, pass_hat_n),
            "planned_tasks": len(matrix.planned_tasks),
            "complete_tasks": len(matrix.complete_tasks),
            "incomplete_tasks": len(matrix.incomplete_tasks),
            "expected_repetitions": matrix.expected_repetitions,
            "observed_repetitions": matrix.observed_repetitions,
            "valid_repetitions": matrix.valid_repetitions,
            "excluded_non_repetition_rows": len(matrix.excluded),
            "superseded_by_replacement": len(matrix.superseded),
            "per_task": [
                {
                    "task_id": task,
                    "trials": len(matrix.counted[task]),
                    "successes": sum(row.strict_success is True for row in matrix.counted[task]),
                    "complete": task in matrix.complete_tasks,
                }
                for task in matrix.planned_tasks
            ],
        }
    return report
