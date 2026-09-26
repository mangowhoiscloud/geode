"""Pre-registered judgment metrics, cluster bootstrap and offline cascade/temperature fitting.

Formulas follow the Jev v3 preregistration (05 §3, §5). Invalid judgment output is
a wrong answer for accuracy and absent from probability metrics; an infrastructure
invalid never reaches these functions as a scored item. ``None`` means the value
is not measurable on the supplied items, never zero.
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
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


def natural_pool_summary(pools: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """pass@1, oracle@N, selected, gap-closed and the non-discriminating share (05 §3.2).

    Each pool row holds ``accepted`` flags per candidate and ``selected_accepted``
    (``None`` when the selection was invalid or a fallback).
    """
    if not pools:
        return {"pools": 0}
    pass1 = math.fsum(sum(p["accepted"]) / len(p["accepted"]) for p in pools) / len(pools)
    oracle = sum(any(p["accepted"]) for p in pools) / len(pools)
    selected = sum(p["selected_accepted"] is True for p in pools) / len(pools)
    gap = oracle - pass1
    return {
        "pools": len(pools),
        "pass_at_1": pass1,
        "oracle_at_n": oracle,
        "selected": selected,
        "gap_closed": (selected - pass1) / gap if gap > 0 else None,
        "non_discriminating": sum(len(set(p["accepted"])) == 1 for p in pools) / len(pools),
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
