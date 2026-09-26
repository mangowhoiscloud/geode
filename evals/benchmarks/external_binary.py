"""X1 external validation: binary acceptance of Choice verdicts (05 v2.2 §11.3–§11.5).

Analysis step only: nothing here calls a model. :func:`x1_pairs` reads the retained
Choice attempts of an X1 run; human labels (the builder's UV-blind strict-majority
``gold_accept``) are read by :func:`load_gold` during analysis, never on the dispatch
path. Definitions follow ``external/cuavb/README.md`` §4:

- decision: an accepted receipt with verdict ``supported`` accepts, an accepted
  receipt with another verdict rejects, an unaccepted receipt is invalid;
- correct: a valid decision equal to the human label; invalid output is wrong and
  is never an acceptance;
- P(supported) and the receipt's three-label ``q`` come from valid outputs only;
- τ is the frozen ``selection-freeze.json`` cascade τ as is and applies to the
  receipt ``q`` (a binary projection of q would change what τ means).

McNemar reports the discordant counts (b, c) only, without a p-value
(coordinator decision 12). Descriptive metrics (05 §11.4, no further test):
P(supported) Brier and ECE, raw and at the frozen temperature; error-detection
AUROC (score 1 − q) and risk–coverage on the receipt q; the frozen-τ offline
cascade; strata; and the dataset's reference verifiers' agreement with the human
label, never a conclusion. Metric rows bind to the report by JSON pointer.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import itertools
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.benchmarks.decision_metrics import (
    ECE_BINS,
    NON_INFERIORITY_MARGIN,
    NOT_MEASURABLE,
    SELECTION_FREEZE_SCHEMA_ID,
    TAU_GRID,
    TEMPERATURE_GRID,
    VERDICT_LABELS,
    Ratio,
    bootstrap_seed,
    cluster_bootstrap,
    temperature_scale_choice,
)

PREFIX = "x1"
PRIMARY = f"{PREFIX}_binary_verdict_accuracy_delta"
RESULTS = "x1-results.json"
SCHEMA_ID = "geode.jev-x1-binary@1"
ACCEPT = "supported"
AUROC_FLOOR = 0.5
ROW_METRICS = (
    "binary_accuracy",
    "false_acceptance_rate",
    "false_rejection_rate",
    "balanced_accuracy",
    "accept_auroc",
)
DESCRIPTIVE_ROW_METRICS = ("accept_brier", "accept_ece", "error_detection_auroc", "aurc")
RISK_POINTS = (0.5, 0.8)
STRATA = ("source_split", "reviewers", "no_answer", "length_quartile")
# Reference verifiers of the dataset; gpt_eval_score -1 means not evaluated.
REFERENCE_FIELDS = (
    "uv_outcome_success",
    "mm_is_success_legacy",
    "verifier_is_success_legacy",
    "gpt_eval_score",
)


@dataclass(frozen=True)
class BinaryRecord:
    """One planned X1 judgment by one engine; ``verdict`` None is an invalid output."""

    item_id: str
    cluster_id: str
    gold_accept: bool
    verdict: str | None = None
    p_accept: float | None = None
    q: float | None = None
    probabilities: Mapping[str, float] | None = None

    @property
    def accepted(self) -> bool:
        return self.verdict == ACCEPT

    @property
    def correct(self) -> bool:
        return self.verdict is not None and self.accepted == self.gold_accept


def binary_record(
    item_id: str, cluster_id: str, gold_accept: bool, receipt: Mapping[str, Any] | None
) -> BinaryRecord:
    """Score one panel receipt; an unaccepted or missing receipt is an invalid output."""
    if receipt is None or receipt.get("accepted") is not True:
        return BinaryRecord(item_id, cluster_id, gold_accept)
    verdict, probabilities, q = (receipt.get(key) for key in ("verdict", "probabilities", "q"))
    if (
        verdict not in VERDICT_LABELS
        or not isinstance(probabilities, Mapping)
        or type(probabilities.get(ACCEPT)) not in (int, float)
        or type(q) not in (int, float)
    ):
        raise ValueError(f"{item_id}: an accepted receipt needs verdict, probabilities and q")
    return BinaryRecord(
        item_id,
        cluster_id,
        gold_accept,
        verdict,
        float(probabilities[ACCEPT]),
        float(receipt["q"]),
        {label: float(value) for label, value in probabilities.items()},
    )


def _mann_whitney(scored: Iterable[tuple[float, bool]]) -> Ratio | None:
    """U over positive × negative pairs from mean ranks; ties count 0.5, one class is None."""
    ordered = sorted(scored)
    positives = sum(label for _, label in ordered)
    negatives = len(ordered) - positives
    if not positives or not negatives:
        return None
    rank = 0
    rank_sum = 0.0
    for _, group in itertools.groupby(ordered, key=lambda row: row[0]):
        labels = [label for _, label in group]
        rank_sum += (rank + (len(labels) + 1) / 2) * sum(labels)  # tied rows share a mean rank
        rank += len(labels)
    return Ratio(rank_sum - positives * (positives + 1) / 2, positives * negatives)


def accept_auroc(records: Sequence[BinaryRecord]) -> Ratio | None:
    """Mann–Whitney AUROC of P(supported) with human success positive; ties count 0.5.

    Valid outputs only. Numerator = U, denominator = positive × negative pairs;
    ``None`` when either class has no valid output.
    """
    return _mann_whitney(
        (record.p_accept, record.gold_accept) for record in records if record.p_accept is not None
    )


def error_detection_auroc(records: Sequence[BinaryRecord]) -> Ratio | None:
    """AUROC of score 1 − q (receipt q) for a wrong valid decision; ties count 0.5 (M7 rule)."""
    return _mann_whitney(
        (1 - record.q, not record.correct) for record in records if record.q is not None
    )


def accept_calibration(
    records: Sequence[BinaryRecord], temperature: float | None = None, bins: int = ECE_BINS
) -> dict[str, Ratio | None]:
    """P(supported) Brier and equal-width ECE over valid outputs (README §4).

    Brier = Σ (p − 1[gold])² / n; ECE = Σ_b n_b·|gold rate_b − mean p_b| / n, the last
    bin closed at 1.0. ``temperature`` first rescales the three-label probabilities
    with the frozen selection T.
    """
    points = []
    for record in records:
        if record.p_accept is None:
            continue
        p = record.p_accept
        if temperature is not None and record.probabilities:
            p = temperature_scale_choice(record.probabilities, temperature)[ACCEPT]
        points.append((p, record.gold_accept))
    if not points:
        return {"accept_brier": None, "accept_ece": None}
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, gold in points:
        buckets[min(int(p * bins), bins - 1)].append((p, gold))
    gaps = math.fsum(
        abs(sum(gold for _, gold in bucket) - math.fsum(p for p, _ in bucket))
        for bucket in buckets
        if bucket
    )  # n_b·|gold rate_b − mean p_b| = |Σ gold − Σ p| within bucket b
    return {
        "accept_brier": Ratio(math.fsum((p - gold) ** 2 for p, gold in points), len(points)),
        "accept_ece": Ratio(gaps, len(points)),
    }


def risk_coverage_summary(records: Sequence[BinaryRecord]) -> dict[str, Any]:
    """Risk–coverage on the receipt q, as M7's ``risk_coverage`` with binary correctness.

    Valid outputs are accepted by descending q (stable by item ID); coverage counts
    planned items, risk = wrong accepted / accepted. AURC = Σ risk / planned; a
    coverage point beyond the valid share is not measurable.
    """
    planned = len(records)
    ordered = sorted(
        (record for record in records if record.q is not None),
        key=lambda record: (-(record.q or 0.0), record.item_id),
    )
    risks: list[float] = []
    wrong = 0
    for accepted, record in enumerate(ordered, start=1):
        wrong += not record.correct
        risks.append(wrong / accepted)
    risk_at: dict[str, float | None] = {}
    for point in RISK_POINTS:
        accepted = math.ceil(point * planned - 1e-9)
        risk_at[f"{point:g}"] = risks[accepted - 1] if 0 < accepted <= len(risks) else None
    return {"aurc": Ratio(math.fsum(risks), planned) if risks else None, "risk_at": risk_at}


def engine_metrics(records: Sequence[BinaryRecord]) -> dict[str, Ratio | None]:
    """Binary accuracy, FAR, FRR, TPR, TNR, balanced accuracy and P(supported) AUROC.

    Denominators are planned items, human failures (FAR, TNR) and human successes
    (FRR, TPR). An invalid output is not an acceptance, so it is a false rejection
    of a success and a wrong answer on a failure.
    """
    successes = [record for record in records if record.gold_accept]
    failures = [record for record in records if not record.gold_accept]
    tpr = Ratio(sum(record.accepted for record in successes), len(successes))
    tnr = Ratio(sum(record.correct for record in failures), len(failures))
    return {
        "binary_accuracy": Ratio(sum(record.correct for record in records), len(records)),
        "false_acceptance_rate": Ratio(sum(record.accepted for record in failures), len(failures)),
        "false_rejection_rate": Ratio(
            sum(not record.accepted for record in successes), len(successes)
        ),
        "true_positive_rate": tpr,
        "true_negative_rate": tnr,
        "balanced_accuracy": None
        if tpr.value is None or tnr.value is None
        else Ratio(tpr.value + tnr.value, 2),
        "accept_auroc": accept_auroc(records),
    }


def selective_risk(records: Sequence[BinaryRecord], tau: float | None) -> dict[str, Ratio | None]:
    """Frozen-τ selection: included = valid ∧ q ≥ τ; coverage over planned, risk over included."""
    if tau is None:
        return {"coverage": None, "risk": None}
    included = [record for record in records if record.q is not None and record.q >= tau]
    return {
        "coverage": Ratio(len(included), len(records)),
        "risk": Ratio(sum(not record.correct for record in included), len(included)),
    }


def _measured(ratio: Ratio | None) -> dict[str, Any]:
    if ratio is None or ratio.value is None:
        return {"value": NOT_MEASURABLE, "numerator": None, "denominator": None}
    return ratio.as_dict()


def _verdicts(records: Sequence[BinaryRecord]) -> dict[str, dict[str, int]]:
    counts = {"gold_accept": Counter[str](), "gold_reject": Counter[str]()}
    for record in records:
        counts["gold_accept" if record.gold_accept else "gold_reject"][
            record.verdict or "invalid"
        ] += 1
    return {
        label: {key: counter[key] for key in (*VERDICT_LABELS, "invalid")}
        for label, counter in counts.items()
    }


def offline_cascade(
    pairs: Sequence[tuple[BinaryRecord, BinaryRecord]], tau: float | None
) -> dict[str, Any]:
    """Frozen-τ cascade: an included Jev decision stands, otherwise Astra decides.

    Included = valid Jev output with receipt q ≥ τ; an invalid Astra output is wrong.
    """
    if tau is None:
        return {"tau": None, "accuracy": _measured(None), "coverage": _measured(None)}
    included = [jev.q is not None and jev.q >= tau for _, jev in pairs]
    correct = sum(
        jev.correct if taken else llm.correct
        for (llm, jev), taken in zip(pairs, included, strict=True)
    )
    return {
        "tau": tau,
        "accuracy": _measured(Ratio(correct, len(pairs))),
        "coverage": _measured(Ratio(sum(included), len(pairs))),
    }


def _descriptive(records: Sequence[BinaryRecord], temperature: float | None) -> dict[str, Any]:
    raw = accept_calibration(records)
    tempered = (
        accept_calibration(records, temperature) if temperature is not None else dict.fromkeys(raw)
    )
    curve = risk_coverage_summary(records)
    return {
        **{name: _measured(value) for name, value in raw.items()},
        "error_detection_auroc": _measured(error_detection_auroc(records)),
        "aurc": _measured(curve["aurc"]),
        "risk_at_coverage": curve["risk_at"],
        "frozen_t": {
            "temperature": temperature,
            **{name: _measured(value) for name, value in tempered.items()},
        },
    }


def strata_labels(
    states: Sequence[Mapping[str, Any]], gold_rows: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, str]]:
    """Input strata per state: source split, reviewers (1, 2-3), no answer, length quartile.

    The length is the E2E state measure ``len(json.dumps(state, ensure_ascii=False))``;
    quartile cuts come from the given states, never from outputs.
    """
    reviewers = {str(row["state_id"]): row.get("annotators") for row in gold_rows}
    lengths = {
        str(row["state_id"]): len(json.dumps(row["state"], ensure_ascii=False)) for row in states
    }
    cuts = statistics.quantiles(lengths.values(), n=4) if len(lengths) > 1 else []
    labels: dict[str, dict[str, str]] = {}
    for row in states:
        state_id = str(row["state_id"])
        count = reviewers.get(state_id)
        if type(count) is not int or count < 1:
            raise ValueError(f"{state_id}: gold lacks its reviewer count")
        answer = str(row["state"].get("candidate_output", "")).strip()
        labels[state_id] = {
            "source_split": str(row.get("source_split") or row.get("stratum")),
            "reviewers": "1" if count == 1 else "2-3",
            "no_answer": "yes" if answer == "<no_answer>" else "no",
            "length_quartile": f"Q{bisect.bisect_left(cuts, lengths[state_id]) + 1}",
        }
    return labels


def x1_strata(
    pairs: Sequence[tuple[BinaryRecord, BinaryRecord]], labels: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Per-stratum binary accuracy of both engines and the paired delta (descriptive)."""
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for dimension in STRATA:
        groups: dict[str, list[tuple[BinaryRecord, BinaryRecord]]] = {}
        for pair in pairs:
            groups.setdefault(labels[pair[0].item_id][dimension], []).append(pair)
        result[dimension] = {}
        for value, rows in sorted(groups.items()):
            llm = sum(pair[0].correct for pair in rows)
            jev = sum(pair[1].correct for pair in rows)
            result[dimension][value] = {
                "items": len(rows),
                "llm": _measured(Ratio(llm, len(rows))),
                "jev": _measured(Ratio(jev, len(rows))),
                "delta": _measured(Ratio(jev - llm, len(rows))),
            }
    return result


def reference_agreement(
    rows: Sequence[Mapping[str, Any]], gold: Mapping[str, bool]
) -> dict[str, dict[str, Any]]:
    """The dataset's reference verifiers against the human label; never a conclusion.

    Planned states only. A null value, or ``gpt_eval_score`` −1 (not evaluated), is left
    out of that field's denominator.
    """
    result: dict[str, dict[str, Any]] = {}
    for name in REFERENCE_FIELDS:
        judged = [
            (row[name], gold[row["state_id"]])
            for row in rows
            if row.get("state_id") in gold and row.get(name) in (0, 1)
        ]
        agree = sum(int(value) == int(label) for value, label in judged)
        result[name] = _measured(Ratio(agree, len(judged)))
    return result


def x1_report(
    pairs: Sequence[tuple[BinaryRecord, BinaryRecord]],
    *,
    split_manifest_sha256: str,
    tau: float | None,
    reasons: Sequence[str] = (),
    min_clusters: int = 10,
    temperatures: Mapping[str, float | None] | None = None,
    strata: Mapping[str, Mapping[str, str]] | None = None,
    reference: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Paired Astra (first) vs Jev (second) X1 report with source-cluster intervals.

    Primary = (Jev correct − Astra correct) / planned items. ``reasons`` names why the
    primary is not measurable (a selected infrastructure-invalid attempt or a
    missing judgment); auxiliary values then stay descriptive. Decision (05 §3.4):
    supported when the delta's lower bound is above −0.05 and Jev's P(supported)
    AUROC lower bound is above 0.5, not-supported when the delta's upper bound is
    below −0.05, mixed otherwise; invalidated when the primary is not measurable.
    ``temperatures`` (frozen selection T per engine), ``strata`` (from
    :func:`strata_labels`) and ``reference`` rows feed the descriptive block.
    """
    if any(
        llm.item_id != jev.item_id
        or llm.cluster_id != jev.cluster_id
        or llm.gold_accept != jev.gold_accept
        for llm, jev in pairs
    ):
        raise ValueError("paired records must share item, cluster and human label")
    if not pairs or len({llm.item_id for llm, _ in pairs}) != len(pairs):
        raise ValueError("each planned item appears exactly once")
    clusters: dict[str, list[tuple[BinaryRecord, BinaryRecord]]] = {}
    for pair in pairs:
        clusters.setdefault(pair[0].cluster_id, []).append(pair)

    def delta(rows: list[tuple[BinaryRecord, BinaryRecord]]) -> float | None:
        correct = sum(jev.correct for _, jev in rows) - sum(llm.correct for llm, _ in rows)
        return correct / len(rows) if rows else None

    def jev_auroc(rows: list[tuple[BinaryRecord, BinaryRecord]]) -> float | None:
        ratio = accept_auroc([jev for _, jev in rows])
        return ratio.value if ratio is not None else None

    interval = cluster_bootstrap(
        clusters,
        delta,
        seed=bootstrap_seed(split_manifest_sha256, PRIMARY),
        min_clusters=min_clusters,
    )
    auroc = cluster_bootstrap(
        clusters,
        jev_auroc,
        seed=bootstrap_seed(split_manifest_sha256, f"{PREFIX}_jev_accept_auroc"),
        min_clusters=min_clusters,
    )
    if reasons:
        decision = "invalidated"
    elif (
        interval.lower is not None
        and interval.lower > -NON_INFERIORITY_MARGIN
        and auroc.lower is not None
        and auroc.lower > AUROC_FLOOR
    ):
        decision = "supported"
    elif interval.upper is not None and interval.upper < -NON_INFERIORITY_MARGIN:
        decision = "not-supported"
    else:
        decision = "mixed"
    llm_records = [llm for llm, _ in pairs]
    jev_records = [jev for _, jev in pairs]
    engines: dict[str, dict[str, Any]] = {
        engine: {name: _measured(value) for name, value in engine_metrics(records).items()}
        for engine, records in (("llm", llm_records), ("jev", jev_records))
    }
    engines["jev"]["selective"] = {
        name: _measured(value) for name, value in selective_risk(jev_records, tau).items()
    }
    planned = len(pairs)
    correct = sum(jev.correct for jev in jev_records) - sum(llm.correct for llm in llm_records)
    return {
        "schema_id": SCHEMA_ID,
        "planned_items": planned,
        "acceptance_rule": (
            "accepted receipt with verdict supported; an invalid output is wrong and never "
            "an acceptance"
        ),
        "gold_rule": "UV-blind human strict-majority Correct; the builder excluded ties",
        "tau": {
            "value": tau,
            "source": "selection-freeze.json cascade.tau; never fitted on external data",
            "q": "receipt q, the three-label maximum",
        },
        "primary": {
            "name": PRIMARY,
            "reasons": list(reasons),
            **_measured(None if reasons else Ratio(correct, planned)),
            "interval": None if reasons else interval.as_dict(),
        },
        "jev_accept_auroc_interval": auroc.as_dict(),
        "engines": engines,
        "verdicts": {"llm": _verdicts(llm_records), "jev": _verdicts(jev_records)},
        "mcnemar": {
            "b": _measured(Ratio(sum(j.correct and not a.correct for a, j in pairs), planned)),
            "c": _measured(Ratio(sum(a.correct and not j.correct for a, j in pairs), planned)),
        },
        "descriptive": {
            "engines": {
                engine: _descriptive(records, (temperatures or {}).get(engine))
                for engine, records in (("llm", llm_records), ("jev", jev_records))
            },
            "cascade": offline_cascade(pairs, tau),
            "strata": x1_strata(pairs, strata) if strata is not None else None,
            "reference_agreement": reference_agreement(
                reference, {llm.item_id: llm.gold_accept for llm in llm_records}
            )
            if reference is not None
            else None,
        },
        "decision": decision,
    }


def x1_metric_rows(report: Mapping[str, Any], *, source_ref: str = RESULTS) -> list[dict[str, Any]]:
    """``analysis.json`` rows bound to the report by JSON pointer.

    The primary first, then per engine (Jev, Astra) binary accuracy, FAR, FRR,
    balanced accuracy and P(supported) AUROC, Jev's frozen-τ coverage and risk,
    McNemar b and c over planned items, and the descriptive P(supported) Brier and ECE
    (raw and at the frozen T), error-detection AUROC, AURC and frozen-τ cascade.
    Unmeasured rows carry ``"not-measurable"`` with null numerator, denominator and
    locator.
    """

    def row(name: str, value: Mapping[str, Any], pointer: str) -> dict[str, Any]:
        measured = value["value"] != NOT_MEASURABLE
        return {
            "name": name,
            "value": value["value"],
            "numerator": value["numerator"],
            "denominator": value["denominator"],
            "unit": "ratio",
            "source_ref": source_ref,
            "source_locator": {
                key: f"{pointer}/{key}" for key in ("value", "numerator", "denominator")
            }
            if measured
            else None,
        }

    engines = report["engines"]
    rows = [row(PRIMARY, report["primary"], "/primary")]
    for engine in ("jev", "llm"):
        for metric in ROW_METRICS:
            pointer = f"/engines/{engine}/{metric}"
            rows.append(row(f"{PREFIX}_{engine}_{metric}", engines[engine][metric], pointer))
    for metric in ("coverage", "risk"):
        pointer = f"/engines/jev/selective/{metric}"
        rows.append(
            row(f"{PREFIX}_jev_selective_{metric}", engines["jev"]["selective"][metric], pointer)
        )
    for cell in ("b", "c"):
        rows.append(row(f"{PREFIX}_mcnemar_{cell}", report["mcnemar"][cell], f"/mcnemar/{cell}"))
    descriptive = report["descriptive"]
    for engine in ("jev", "llm"):
        block = descriptive["engines"][engine]
        base = f"/descriptive/engines/{engine}"
        for metric in DESCRIPTIVE_ROW_METRICS:
            rows.append(row(f"{PREFIX}_{engine}_{metric}", block[metric], f"{base}/{metric}"))
        for metric in ("accept_brier", "accept_ece"):
            name = f"{PREFIX}_{engine}_frozen_t_{metric}"
            rows.append(row(name, block["frozen_t"][metric], f"{base}/frozen_t/{metric}"))
    for metric in ("accuracy", "coverage"):
        value = descriptive["cascade"][metric]
        rows.append(row(f"{PREFIX}_cascade_{metric}", value, f"/descriptive/cascade/{metric}"))
    return rows


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def x1_pairs(
    run_dir: Path, planned: Sequence[str], gold: Mapping[str, bool], clusters: Mapping[str, str]
) -> tuple[list[tuple[BinaryRecord, BinaryRecord]], list[str]]:
    """Pair the retained Choice judgments of an X1 run per planned state (Astra, Jev).

    A validator-rejected judgment is an invalid output (wrong). A selected
    infrastructure-invalid attempt or a missing judgment is an invalid output too, and
    its reason makes the primary not measurable. A judgment outside the frozen plan,
    or one selected twice, is an error.
    """
    from evals.benchmarks.verdict_panel_runner import _selected_judgments

    planned_set = set(planned)
    if len(planned_set) != len(planned) or any("#" in state for state in planned):
        raise ValueError("X1 workloads are unique state IDs without variants")
    found: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for row, evidence in _selected_judgments(run_dir, "choice"):
        key = (str(evidence.get("engine")), str(evidence.get("state_id")))
        if (
            key[0] not in ("llm", "jev")
            or key[1] not in planned_set
            or evidence.get("variant") != "base"
            or evidence.get("cluster_id") != clusters.get(key[1])
        ):
            raise ValueError(f"{row['attempt_id']}: a judgment outside the frozen X1 plan")
        if key in found:
            raise ValueError(f"{row['attempt_id']}: a planned judgment is selected twice")
        found[key] = (row, evidence)
    reasons: set[str] = set()
    pairs: list[tuple[BinaryRecord, BinaryRecord]] = []
    for state in planned:
        records: list[BinaryRecord] = []
        for engine in ("llm", "jev"):
            judged = found.get((engine, state))
            receipt = None
            if judged is None:
                reasons.add("missing_judgment")
            elif judged[0]["validity"] != "valid":
                reasons.add("selected_invalid_attempt")
            else:
                receipt = judged[1].get("receipt")
            records.append(binary_record(state, clusters[state], gold[state], receipt))
        pairs.append((records[0], records[1]))
    return pairs, sorted(reasons)


def record_x1_aggregate(run_dir: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    """Write ``x1-results.json`` and append its selected analysis-only attempt."""
    from evals.benchmarks.verdict_panel_runner import _record_aggregate

    reasons = report["primary"]["reasons"]
    return _record_aggregate(
        run_dir,
        RESULTS,
        report,
        failure_class=reasons[0] if reasons else None,
        description="Frozen X1 binary acceptance aggregation; zero model dispatches.",
        expected_effect="Binary acceptance agreement of both engines with the human label.",
        observed=(
            "Every planned state was judged by both engines.",
            "A planned judgment is missing or an invalid attempt stays selected.",
        ),
    )


def load_gold(path: Path, planned: Sequence[str]) -> dict[str, bool]:
    """Human labels of the planned states, read in analysis only.

    Rows outside the plan are ignored; a repeated row or a planned state without a
    boolean ``gold_accept`` is an error.
    """
    labels: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("state_id") in labels:
            raise ValueError(f"{row.get('state_id')}: gold repeats")
        labels[row.get("state_id")] = row.get("gold_accept")
    missing = [state for state in planned if type(labels.get(state)) is not bool]
    if missing:
        raise ValueError(f"gold lacks a boolean gold_accept for {len(missing)} planned state(s)")
    return {state: bool(labels[state]) for state in planned}


def frozen_tau(freeze: Mapping[str, Any]) -> float | None:
    """The Choice cascade τ of ``selection-freeze.json`` (``None``: no admissible τ)."""
    if freeze.get("schema_id") != SELECTION_FREEZE_SCHEMA_ID:
        raise ValueError("not a selection freeze document")
    cascade = freeze.get("cascade")
    tau = cascade.get("tau") if isinstance(cascade, Mapping) else None
    if tau is not None and (type(tau) not in (int, float) or tau not in TAU_GRID):
        raise ValueError("the frozen tau is off the preregistered grid")
    return tau


def frozen_temperatures(freeze: Mapping[str, Any]) -> dict[str, float | None]:
    """The Choice temperature per engine of ``selection-freeze.json`` (``None``: not fitted)."""
    if freeze.get("schema_id") != SELECTION_FREEZE_SCHEMA_ID:
        raise ValueError("not a selection freeze document")
    temperatures = freeze.get("temperatures")
    choice = temperatures.get("choice") if isinstance(temperatures, Mapping) else None
    result: dict[str, float | None] = {}
    for engine in ("llm", "jev"):
        fit = choice.get(engine) if isinstance(choice, Mapping) else None
        value = fit.get("temperature") if isinstance(fit, Mapping) else None
        if value is not None and (type(value) not in (int, float) or value not in TEMPERATURE_GRID):
            raise ValueError("a frozen temperature is off the preregistered grid")
        result[engine] = value
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.benchmarks.external_binary",
        description="X1 binary acceptance analysis from retained Choice attempts (no model call).",
    )
    parser.add_argument("--run-spec", type=Path, required=True, help="frozen X1 run spec")
    parser.add_argument("--choice", type=Path, required=True, help="the X1 Choice run directory")
    parser.add_argument("--manifest", type=Path, required=True, help="split-manifest.x1.json")
    parser.add_argument("--states", type=Path, required=True, help="states.x1.jsonl")
    parser.add_argument("--gold", type=Path, required=True, help="gold.x1.jsonl (analysis only)")
    parser.add_argument("--selection-freeze", type=Path, required=True)
    parser.add_argument("--reference", type=Path, help="reference.x1.jsonl (descriptive only)")
    parser.add_argument("--record", action="store_true", help="write results and aggregate")
    args = parser.parse_args(argv)
    spec = json.loads(args.run_spec.read_text(encoding="utf-8"))
    planned = [str(state) for state in spec["reproduction"]["execution"]["ordered_workload_ids"]]
    states = [row for row in _jsonl(args.states) if row.get("state_id") in set(planned)]
    if len(states) != len(planned):
        raise ValueError("the states file does not hold every planned state once")
    gold = load_gold(args.gold, planned)
    freeze = json.loads(args.selection_freeze.read_text(encoding="utf-8"))
    clusters = {str(row["state_id"]): str(row["cluster_id"]) for row in states}
    pairs, reasons = x1_pairs(args.choice, planned, gold, clusters)
    report = x1_report(
        pairs,
        split_manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        tau=frozen_tau(freeze),
        reasons=reasons,
        temperatures=frozen_temperatures(freeze),
        strata=strata_labels(states, _jsonl(args.gold)),
        reference=_jsonl(args.reference) if args.reference else None,
    )
    if args.record:
        record_x1_aggregate(args.choice, report)
    output = {
        "primary": report["primary"],
        "decision": report["decision"],
        "metrics": x1_metric_rows(report),
    }
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
