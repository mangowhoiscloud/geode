"""X1 external validation: binary acceptance of Choice verdicts (05 v2.2 §11.3–§11.5).

Analysis step only: nothing here calls a model or reads runner files. Human
labels (the builder's UV-blind strict-majority ``gold_accept``) are read by
:func:`load_gold` during analysis, never on the dispatch path.
Definitions follow ``external/cuavb/README.md`` §4:

- decision: an accepted receipt with verdict ``supported`` accepts, an accepted
  receipt with another verdict rejects, an unaccepted receipt is invalid;
- correct: a valid decision equal to the human label; invalid output is wrong and
  is never an acceptance;
- P(supported) and the receipt's three-label ``q`` come from valid outputs only;
- τ is the frozen ``selection-freeze.json`` cascade τ as is and applies to the
  receipt ``q`` (a binary projection of q would change what τ means).

McNemar reports the discordant counts (b, c) only, without a p-value
(coordinator decision 12). Metric rows bind to the report by JSON pointer.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.benchmarks.decision_metrics import (
    NON_INFERIORITY_MARGIN,
    NOT_MEASURABLE,
    SELECTION_FREEZE_SCHEMA_ID,
    TAU_GRID,
    VERDICT_LABELS,
    Ratio,
    bootstrap_seed,
    cluster_bootstrap,
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


@dataclass(frozen=True)
class BinaryRecord:
    """One planned X1 judgment by one engine; ``verdict`` None is an invalid output."""

    item_id: str
    cluster_id: str
    gold_accept: bool
    verdict: str | None = None
    p_accept: float | None = None
    q: float | None = None

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
        item_id, cluster_id, gold_accept, verdict, float(probabilities[ACCEPT]), float(receipt["q"])
    )


def accept_auroc(records: Sequence[BinaryRecord]) -> Ratio | None:
    """Mann–Whitney AUROC of P(supported) with human success positive; ties count 0.5.

    Valid outputs only. Numerator = U, denominator = positive × negative pairs;
    ``None`` when either class has no valid output.
    """
    scored = sorted(
        (record.p_accept, record.gold_accept) for record in records if record.p_accept is not None
    )
    positives = sum(label for _, label in scored)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return None
    rank = 0
    rank_sum = 0.0
    for _, group in itertools.groupby(scored, key=lambda row: row[0]):
        labels = [label for _, label in group]
        rank_sum += (rank + (len(labels) + 1) / 2) * sum(labels)  # tied rows share a mean rank
        rank += len(labels)
    return Ratio(rank_sum - positives * (positives + 1) / 2, positives * negatives)


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


def x1_report(
    pairs: Sequence[tuple[BinaryRecord, BinaryRecord]],
    *,
    split_manifest_sha256: str,
    tau: float | None,
    reasons: Sequence[str] = (),
    min_clusters: int = 10,
) -> dict[str, Any]:
    """Paired Astra (first) vs Jev (second) X1 report with source-cluster intervals.

    Primary = (Jev correct − Astra correct) / planned items. ``reasons`` names why the
    primary is not measurable (a selected infrastructure-invalid attempt or a
    missing judgment); auxiliary values then stay descriptive. Decision (05 §3.4):
    supported when the delta's lower bound is above −0.05 and Jev's P(supported)
    AUROC lower bound is above 0.5, not-supported when the delta's upper bound is
    below −0.05, mixed otherwise; invalidated when the primary is not measurable.
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
        "decision": decision,
    }


def x1_metric_rows(report: Mapping[str, Any], *, source_ref: str = RESULTS) -> list[dict[str, Any]]:
    """``analysis.json`` rows bound to the report by JSON pointer.

    The primary first, then per engine (Jev, Astra) binary accuracy, FAR, FRR,
    balanced accuracy and P(supported) AUROC, Jev's frozen-τ coverage and risk, and
    McNemar b and c over planned items. Unmeasured rows carry ``"not-measurable"``
    with null numerator, denominator and locator.
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
    return rows


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
