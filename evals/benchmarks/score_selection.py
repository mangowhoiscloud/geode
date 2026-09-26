"""Score-S harness: frozen best-of pools, both presentation orders, model-free scoring.

Jev v3 design card C5 and preregistration §2.2 (U0b, U4, U5p, U5s), §3.1 "Score
top-1", §3.2 "Score 보조" and §4.1. Nothing here calls a model by itself: every
selector dispatch goes through the runtime judge boundary
(:func:`core.agent.candidate_sampling.judge_candidates`) with caller-injected
backends, so the whole path runs on fakes (``python -m
evals.benchmarks.score_selection self-test``).

Two phases keep sealed grades out of dispatch:

1. :func:`dispatch_selection` runs every selector exactly once per pool and order
   (``forward`` = frozen pool order, ``reverse``) and returns JSON records with
   per-order scores, winners, ``judge_error`` and receipts. It never reads grades
   and its output never contains them, so held-out pools are dispatched ungraded
   under their public (possibly aliased) ids.
2. :func:`score_selection` joins model-free grades after unsealing (by the sealed
   alias map or by graded pool id) and derives per-pool outcomes;
   :func:`summarize_outcomes` aggregates them with explicit numerators and
   denominators.

Preregistered rules:

- Pointwise selection is the argmax of the mean of both orders' scores; exact ties
  resolve to the smallest ``sha256(pool_id + U+241F + candidate_id)`` over the
  dispatched (alias) ids. If either order is invalid (``judge_error`` fallback,
  missing or unaccepted receipt) the pool selection is invalid and counts as wrong,
  even when the fallback candidate would pass the task oracle.
- The listwise operational reference is the mean of per-order hits (0, 0.5, 1); an
  invalid order contributes 0.
- Natural pools are graded by the existing inbox oracle's per-item answer matches
  (기존 inbox oracle의 항목 정답 수); a candidate is acceptable when every item
  matches (grade == number of items). A controlled candidate is acceptable when its
  rule-oracle verdict is ``supported`` (grade 3). Partial grades and "best in pool"
  never make a candidate acceptable.
- Metric names follow 05 v1 §3.2 and 06 §5: oracle-best selection, regret,
  pool-random@1, oracle-coverage@4, selected success and gap closed (not-measurable
  when its denominator is 0; negative values are reported). The candidate width 4
  is not an IID repetition count, so no pass@k name is used.
- Jev Score admission reuses the contract V1 parser bounds: ``sum_tolerance`` and
  the frozen ``score_tolerance`` (§4.1), recorded in every receipt and record.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, Decimal
from fractions import Fraction
from html import unescape
from pathlib import Path
from typing import Any, Literal

from core.agent import candidate_sampling
from core.agent.candidate_sampling import MAX_BEST_OF, candidate_text, lensed_description
from core.hooks import MiddlewareRegistry, RuntimeEventBus
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    LLMAdapter,
    UsageSummary,
)
from core.llm.adapters.typesafe import STRICT_PROBABILITY_TOLERANCE

from evals.benchmarks.decision_candidate import (
    CANDIDATE_LEVELS,
    MatchedCandidateAdapter,
    candidate_tie_key,
    is_safe_candidate_id,
)
from evals.benchmarks.decision_handoff import ROOT_MODEL
from evals.benchmarks.decision_metrics import score_acceptance_summary

ORDERS: tuple[str, str] = ("forward", "reverse")
MAX_CANDIDATE_CHARS = 2000
RECORD_SCHEMA = "geode.jev-score-selection-record@1"
OUTCOME_SCHEMA = "geode.jev-score-selection-outcome@1"
TOLERANCE_RULE = "min(0.05, max(0.03, ceil_to_0.01(max |score - sum(level * p)|)))"
# Independent task-oracle acceptance, frozen per pool kind (05 v1 §3.2, 06 §5).
CONTROLLED_ACCEPTABLE_GRADE = 3
ACCEPTANCE_RULES = {
    "controlled": "grade == 3 (rule-oracle verdict supported)",
    "natural": "grade == full_grade (every inbox item answer matches)",
}
_POOL_FIELDS = frozenset(
    {
        "pool_id",
        "cluster_id",
        "split",
        "candidates",
        "pool_sha256",
        "source_pool_sha256",
        "task",
        "kind",
        "full_grade",
        "provenance",
        "frozen_pool_sha256",
        "graded_pool_sha256",
    }
)
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_text(value: object, limit: int | None = None) -> bool:
    return isinstance(value, str) and bool(value.strip()) and (limit is None or len(value) <= limit)


def _is_grade(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_pool_kind(value: object) -> bool:
    return value in ("controlled", "natural")


# ---------------------------------------------------------------------------
# Frozen pools
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PoolCandidate:
    """One frozen candidate; ``grade`` is ``None`` while the pool is sealed."""

    candidate_id: str
    text: str
    grade: int | None = None


@dataclass(frozen=True, slots=True)
class FrozenPool:
    """A dispatchable pool in forward (frozen) order.

    Grades are all non-negative integers (graded) or all ``None`` (sealed). Natural
    pools also carry ``full_grade``, the grade of an acceptable candidate.
    """

    pool_id: str
    task: str
    candidates: tuple[PoolCandidate, ...]
    kind: Literal["controlled", "natural"] = "controlled"
    full_grade: int | None = None
    cluster_id: str | None = None
    split: str | None = None
    source_pool_sha256: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        label = str(self.pool_id)
        if not is_safe_candidate_id(self.pool_id):
            raise ValueError(f"{label}: pool_id is not a safe identifier")
        if not _is_text(self.task):
            raise ValueError(f"{label}: pool task must be nonempty text")
        if not 2 <= len(self.candidates) <= MAX_BEST_OF:
            raise ValueError(f"{label}: a pool needs 2..{MAX_BEST_OF} candidates")
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(ids)) != len(ids) or not all(is_safe_candidate_id(value) for value in ids):
            raise ValueError(f"{label}: candidate ids must be unique safe identifiers")
        if not all(_is_text(candidate.text, MAX_CANDIDATE_CHARS) for candidate in self.candidates):
            raise ValueError(
                f"{label}: candidate text must be nonempty and at most "
                f"{MAX_CANDIDATE_CHARS} characters"
            )
        grades = [candidate.grade for candidate in self.candidates]
        if not (all(_is_grade(grade) for grade in grades) or all(g is None for g in grades)):
            raise ValueError(f"{label}: grades must be all non-negative integers or all sealed")
        if not _is_pool_kind(self.kind):
            raise ValueError(f"{label}: unknown pool kind {self.kind!r}")
        full = self.full_grade
        if self.kind == "natural" and not (
            isinstance(full, int)
            and full >= 1
            and all(grade is not None and grade <= full for grade in grades)
        ):
            raise ValueError(f"{label}: natural pools need grades within 0..full_grade")
        if self.kind == "controlled" and self.full_grade is not None:
            raise ValueError(f"{label}: controlled pools have no full_grade")
        for name in ("cluster_id", "split"):
            value = getattr(self, name)
            if value is not None and not is_safe_candidate_id(value):
                raise ValueError(f"{label}: {name} is not a safe identifier")
        if self.source_pool_sha256 is not None and not _HEX64.fullmatch(
            str(self.source_pool_sha256)
        ):
            raise ValueError(f"{label}: source pool_sha256 must be a sha256 hex digest")
        try:
            _canonical(dict(self.provenance))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}: provenance must be finite JSON") from error

    @property
    def graded(self) -> bool:
        return all(candidate.grade is not None for candidate in self.candidates)


def frozen_pool_sha256(pool: FrozenPool) -> str:
    """Dispatch identity: pool id, task and forward (candidate_id, text); grade-free.

    Sealed pools are dispatched before their grades are known, so the identity of
    what selectors saw must not depend on grades (see :func:`graded_pool_sha256`).
    """
    return _sha256_json(
        {
            "pool_id": pool.pool_id,
            "task": pool.task,
            "candidates": [
                {"candidate_id": candidate.candidate_id, "text": candidate.text}
                for candidate in pool.candidates
            ],
        }
    )


def public_pool_sha256(pool: FrozenPool) -> str:
    """Build-A's public digest ``{pool_id, candidates: [{candidate_id, text}]}``; grade-free."""
    return _sha256_json(
        {
            "pool_id": pool.pool_id,
            "candidates": [
                {"candidate_id": candidate.candidate_id, "text": candidate.text}
                for candidate in pool.candidates
            ],
        }
    )


def graded_pool_sha256(pool: FrozenPool) -> str | None:
    """Oracle identity: :func:`frozen_pool_sha256` fields plus grades (graded pools only)."""
    if not pool.graded:
        return None
    return _sha256_json(
        {
            "pool_id": pool.pool_id,
            "task": pool.task,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "text": candidate.text,
                    "grade": candidate.grade,
                }
                for candidate in pool.candidates
            ],
        }
    )


def pool_record(pool: FrozenPool) -> dict[str, Any]:
    """JSON form of a pool that :func:`pool_from_record` reloads and verifies."""
    candidates: list[dict[str, Any]] = []
    for candidate in pool.candidates:
        row: dict[str, Any] = {"candidate_id": candidate.candidate_id, "text": candidate.text}
        if candidate.grade is not None:
            row["grade"] = candidate.grade
        candidates.append(row)
    record: dict[str, Any] = {
        "pool_id": pool.pool_id,
        "task": pool.task,
        "kind": pool.kind,
        "candidates": candidates,
        "frozen_pool_sha256": frozen_pool_sha256(pool),
    }
    optional = {
        "graded_pool_sha256": graded_pool_sha256(pool),
        "full_grade": pool.full_grade,
        "cluster_id": pool.cluster_id,
        "split": pool.split,
        "source_pool_sha256": pool.source_pool_sha256,
        "provenance": dict(pool.provenance) or None,
    }
    record.update({key: value for key, value in optional.items() if value is not None})
    return record


def _read_jsonl(path: Path) -> list[tuple[int, Any]]:
    rows: list[tuple[int, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append((number, json.loads(line)))
        except ValueError as error:
            raise ValueError(f"{path.name}:{number}: invalid JSON") from error
    return rows


def load_states(path: Path) -> dict[str, dict[str, Any]]:
    """Index Build-A ``states.<split>.jsonl`` rows by ``state_id``."""
    states: dict[str, dict[str, Any]] = {}
    for number, row in _read_jsonl(path):
        state = row.get("state") if isinstance(row, dict) else None
        request = state.get("original_request") if isinstance(state, dict) else None
        state_id = row.get("state_id") if isinstance(row, dict) else None
        if not is_safe_candidate_id(state_id) or state_id in states or not _is_text(request):
            raise ValueError(
                f"{path.name}:{number}: state rows need a unique safe state_id "
                "and a nonempty state.original_request"
            )
        states[str(state_id)] = row
    return states


def _parse_candidates(pool_id: object, raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError(f"{pool_id}: candidates must be a list")
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) not in (
            {"candidate_id", "text"},
            {"candidate_id", "text", "grade"},
        ):
            raise ValueError(f"{pool_id}: candidate fields must be candidate_id, text[, grade]")
        rows.append(item)
    return rows


def _task_from_states(
    pool_id: str, candidate_ids: Sequence[str], states: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str | None]:
    tasks: set[str] = set()
    clusters: set[Any] = set()
    for candidate_id in candidate_ids:
        row = states.get(candidate_id)
        if row is None:
            raise ValueError(f"{pool_id}: candidate {candidate_id} has no state row")
        if row.get("quad_id") not in (None, pool_id):
            raise ValueError(f"{pool_id}: state {candidate_id} belongs to another quad")
        tasks.add(row["state"]["original_request"])
        clusters.add(row.get("cluster_id"))
    if len(tasks) != 1 or len(clusters) != 1:
        raise ValueError(f"{pool_id}: candidate states disagree on original_request or cluster")
    cluster = clusters.pop()
    return tasks.pop(), cluster if isinstance(cluster, str) else None


def pool_from_record(
    row: object, *, states: Mapping[str, Mapping[str, Any]] | None = None
) -> FrozenPool:
    """Build a pool from a Build-A pool row or a :func:`pool_record` row.

    ``task`` comes from the row or from the candidates' states
    (``state.original_request``; all candidates must share it). A present Build-A
    ``pool_sha256`` is recomputed over ``{pool_id, candidates}`` exactly as the row
    carries them (with grades when graded) and must match; present
    ``frozen_pool_sha256`` / ``graded_pool_sha256`` digests must match too.
    ``source_pool_sha256`` (written by :func:`pool_record`) is carried as is.
    """
    if not isinstance(row, dict):
        raise ValueError("pool row must be a JSON object")
    unknown = sorted(set(row) - _POOL_FIELDS)
    if unknown:
        raise ValueError(f"{row.get('pool_id')}: unexpected pool fields {unknown}")
    pool_id: Any = row.get("pool_id")
    raw = _parse_candidates(pool_id, row.get("candidates"))
    declared_source = row.get("pool_sha256")
    if declared_source is not None and declared_source != _sha256_json(
        {"pool_id": pool_id, "candidates": raw}
    ):
        raise ValueError(f"{pool_id}: pool_sha256 does not match the row content")
    carried = row.get("source_pool_sha256")
    if declared_source is not None and carried is not None:
        raise ValueError(f"{pool_id}: pool_sha256 and source_pool_sha256 are exclusive")
    task = row.get("task")
    cluster_id = row.get("cluster_id")
    if states is not None:
        ids = [str(item["candidate_id"]) for item in raw]
        state_task, state_cluster = _task_from_states(str(pool_id), ids, states)
        if task is not None and task != state_task:
            raise ValueError(f"{pool_id}: row task differs from the states' original_request")
        if cluster_id is not None and state_cluster not in (None, cluster_id):
            raise ValueError(f"{pool_id}: row cluster_id differs from its states")
        task, cluster_id = state_task, cluster_id if cluster_id is not None else state_cluster
    if task is None:
        raise ValueError(f"{pool_id}: pool task unavailable (row task or states file required)")
    pool = FrozenPool(
        pool_id=pool_id,
        task=task,
        candidates=tuple(
            PoolCandidate(item["candidate_id"], item["text"], item.get("grade")) for item in raw
        ),
        kind=row.get("kind", "controlled"),
        full_grade=row.get("full_grade"),
        cluster_id=cluster_id,
        split=row.get("split"),
        source_pool_sha256=declared_source if declared_source is not None else carried,
        provenance=row.get("provenance") or {},
    )
    for key, digest in (
        ("frozen_pool_sha256", frozen_pool_sha256),
        ("graded_pool_sha256", graded_pool_sha256),
    ):
        if row.get(key) is not None and row[key] != digest(pool):
            raise ValueError(f"{pool_id}: {key} does not match the pool content")
    return pool


def load_pools(path: Path, *, states_path: Path | None = None) -> list[FrozenPool]:
    """Load ``pools.<split>.jsonl`` (graded or sealed) or frozen natural pool records."""
    states = load_states(states_path) if states_path is not None else None
    pools: list[FrozenPool] = []
    for number, row in _read_jsonl(path):
        try:
            pools.append(pool_from_record(row, states=states))
        except ValueError as error:
            raise ValueError(f"{path.name}:{number}: {error}") from error
    if len({pool.pool_id for pool in pools}) != len(pools):
        raise ValueError(f"{path.name}: duplicate pool_id")
    return pools


@dataclass(frozen=True, slots=True)
class GradedPool:
    """Sealed-side grades: ``pools-graded.<split>.jsonl`` rows under original ids."""

    pool_id: str
    texts: Mapping[str, str]
    grades: Mapping[str, int]
    cluster_id: str | None = None
    source_pool_sha256: str | None = None


def load_graded_pools(path: Path) -> dict[str, GradedPool]:
    """Load graded Build-A rows; each row's ``pool_sha256`` is recomputed when present."""
    graded: dict[str, GradedPool] = {}
    for number, row in _read_jsonl(path):
        prefix = f"{path.name}:{number}"
        if not isinstance(row, dict) or not {"pool_id", "candidates"} <= set(row):
            raise ValueError(f"{prefix}: graded rows need pool_id and candidates")
        pool_id = row["pool_id"]
        raw = _parse_candidates(pool_id, row["candidates"])
        declared = row.get("pool_sha256")
        if declared is not None and declared != _sha256_json(
            {"pool_id": pool_id, "candidates": raw}
        ):
            raise ValueError(f"{prefix}: {pool_id}: pool_sha256 does not match the row content")
        ids = [item["candidate_id"] for item in raw]
        if (
            not is_safe_candidate_id(pool_id)
            or pool_id in graded
            or len(set(ids)) != len(ids)
            or not all(is_safe_candidate_id(value) for value in ids)
            or not all(_is_grade(item.get("grade")) and _is_text(item["text"]) for item in raw)
        ):
            raise ValueError(f"{prefix}: {pool_id}: graded rows need unique ids, text and grades")
        cluster = row.get("cluster_id")
        graded[pool_id] = GradedPool(
            pool_id,
            {item["candidate_id"]: item["text"] for item in raw},
            {item["candidate_id"]: item["grade"] for item in raw},
            cluster if isinstance(cluster, str) else None,
            declared,
        )
    return graded


def load_aliases(path: Path) -> dict[str, str]:
    """Load the sealed ``aliases.<split>.json`` map ``{alias: original_id}``."""
    aliases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict) or not all(
        is_safe_candidate_id(key) and is_safe_candidate_id(value) for key, value in aliases.items()
    ):
        raise ValueError(f"{path.name}: alias map must be a flat {{alias: original_id}} object")
    return {str(key): str(value) for key, value in aliases.items()}


def attach_grades(
    pools: Sequence[FrozenPool],
    graded: Mapping[str, GradedPool],
    *,
    aliases: Mapping[str, str] | None = None,
) -> list[FrozenPool]:
    """Unseal: copy grades onto the dispatched pools without changing their ids.

    Each dispatched id maps through ``aliases`` (``{alias: original}``) or, without
    a map, is used as the graded id. Every candidate must map to exactly one graded
    candidate with byte-identical text, so a mismatched unseal fails loudly.
    """
    joined: list[FrozenPool] = []
    for pool in pools:
        source_id = aliases.get(pool.pool_id) if aliases is not None else pool.pool_id
        source = graded.get(source_id) if source_id is not None else None
        if source is None:
            raise ValueError(f"{pool.pool_id}: no graded pool {source_id!r}")
        if source.cluster_id is not None and pool.cluster_id not in (None, source.cluster_id):
            raise ValueError(f"{pool.pool_id}: graded pool belongs to another cluster")
        mapped = [
            aliases.get(candidate.candidate_id) if aliases is not None else candidate.candidate_id
            for candidate in pool.candidates
        ]
        if (
            None in mapped
            or len(set(mapped)) != len(mapped)
            or set(mapped) != set(source.grades)
            or any(
                source.texts[str(original)] != candidate.text
                for original, candidate in zip(mapped, pool.candidates, strict=True)
            )
        ):
            raise ValueError(f"{pool.pool_id}: graded candidates differ from the dispatched pool")
        joined.append(
            replace(
                pool,
                candidates=tuple(
                    replace(candidate, grade=source.grades[str(original)])
                    for original, candidate in zip(mapped, pool.candidates, strict=True)
                ),
                cluster_id=pool.cluster_id or source.cluster_id,
                provenance={
                    **pool.provenance,
                    "graded_pool_id": source.pool_id,
                    "graded_source_pool_sha256": source.source_pool_sha256,
                },
            )
        )
    return joined


# ---------------------------------------------------------------------------
# Natural pools (one delegate_task(best_of=4) generation, frozen read-only)
# ---------------------------------------------------------------------------


def natural_grade(case: Mapping[str, Any], text: str) -> int:
    """Natural oracle: 기존 inbox oracle의 항목 정답 수.

    Counts case items whose answer equals ``{"id": id, **expected_answer}``, with the
    same parsing as ``decision_handoff_runtime._inbox_oracle`` ``answer_matches``:
    the text must be one JSON object ``{"items": [...]}``; unparsable text is 0.
    """
    try:
        answer = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        return 0
    raw_items = answer.get("items") if isinstance(answer, dict) else None
    items = raw_items if isinstance(raw_items, list) else []
    shape = (
        isinstance(answer, dict)
        and set(answer) == {"items"}
        and isinstance(raw_items, list)
        and all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in items)
    )
    final_by_id = {item["id"]: item for item in items} if shape else {}
    return sum(
        final_by_id.get(item["id"]) == {"id": item["id"], **item["expected_answer"]}
        for item in case["items"]
    )


def freeze_natural_pool(
    *,
    pool_id: str,
    task: str,
    case: Mapping[str, Any],
    orders: Mapping[str, str],
    payload: Mapping[str, Any],
    cluster_id: str | None = None,
) -> FrozenPool:
    """Freeze one ``delegate_task(best_of=N)`` tool payload as a graded natural pool.

    ``task`` is the delegate call's ``task_description`` (what the runtime judge
    reads); every candidate row must carry one of its lensed descriptions. Only
    successful ``payload["tasks"]`` rows (``SubResult.to_dict()``) enter the pool,
    in dispatch order, with ``candidate_id = task_id`` and text from
    :func:`candidate_text`. Grades come from :func:`natural_grade` before any
    selection; the inbox labels are validated against ``orders`` first.
    """
    from evals.benchmarks.decision_handoff_runtime import validate_inbox_case

    validate_inbox_case(dict(case), orders)
    rows = payload.get("tasks")
    best_of = payload.get("best_of")
    if (
        not isinstance(rows, list)
        or not all(isinstance(row, dict) for row in rows)
        or not isinstance(best_of, dict)
        or best_of.get("n") != len(rows)
    ):
        raise ValueError(f"{pool_id}: payload is not one best_of delegate_task result")
    lenses = {lensed_description(task, index) for index in range(MAX_BEST_OF)}
    candidates: list[PoolCandidate] = []
    for row in rows:
        if row.get("success") is not True:
            continue
        if row.get("description") not in lenses:
            raise ValueError(f"{pool_id}: candidate {row.get('task_id')!r} has another task")
        text = candidate_text(row.get("output"))
        candidates.append(PoolCandidate(row.get("task_id"), text, natural_grade(case, text)))
    return FrozenPool(
        pool_id=pool_id,
        task=task,
        candidates=tuple(candidates),
        kind="natural",
        full_grade=len(case["items"]),
        cluster_id=cluster_id,
        provenance={
            "case_id": case.get("id"),
            "case_sha256": _sha256_json(dict(case)),
            "n_dispatched": len(rows),
            "n_successful": len(candidates),
            "complete": len(candidates) == len(rows) == MAX_BEST_OF,
            "generation_winner_task_id": best_of.get("winner_task_id"),
            "generation_judge_error": best_of.get("judge_error", ""),
        },
    )


# ---------------------------------------------------------------------------
# Rules shared by dispatch and scoring
# ---------------------------------------------------------------------------


def order_indices(pool: FrozenPool, order: str) -> list[int]:
    """Presentation order: ``forward`` = frozen order, ``reverse`` = reversed."""
    count = len(pool.candidates)
    if order == "forward":
        return list(range(count))
    if order == "reverse":
        return list(range(count - 1, -1, -1))
    raise ValueError(f"unknown presentation order {order!r}")


def select_by_score(pool_id: str, scores: Mapping[str, Fraction]) -> tuple[str, bool]:
    """Argmax; exact ties resolve to the smallest :func:`candidate_tie_key`."""
    best = max(scores.values())
    tied = [candidate_id for candidate_id, value in scores.items() if value == best]
    return min(tied, key=lambda value: candidate_tie_key(pool_id, value)), len(tied) > 1


def kendall_tau_b(x: Sequence[Fraction], y: Sequence[Fraction]) -> float | None:
    """Kendall tau-b of two aligned score vectors; ``None`` when undefined."""
    pairs = concordant = discordant = tied_x = tied_y = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            pairs += 1
            dx = (x[i] > x[j]) - (x[i] < x[j])
            dy = (y[i] > y[j]) - (y[i] < y[j])
            tied_x += dx == 0
            tied_y += dy == 0
            concordant += dx * dy > 0
            discordant += dx * dy < 0
    denominator = (pairs - tied_x) * (pairs - tied_y)
    return None if denominator == 0 else (concordant - discordant) / math.sqrt(denominator)


def score_expectation_tolerance(observed_max: float) -> float:
    """§4.1 freeze rule: min(0.05, max(0.03, observed max rounded up to 0.01))."""
    if not math.isfinite(observed_max) or observed_max >= 0.05:
        return 0.05
    rounded = Decimal(repr(float(observed_max))).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return float(max(Decimal("0.03"), rounded))


def _expectation_deviation(receipt: Mapping[str, Any] | None) -> float | None:
    """Largest |score - sum(level * p)| in a Score answer, parsed leniently."""
    if receipt is None:
        return None
    answers: Any = receipt.get("native_answer")
    raw = receipt.get("raw_answer")
    if isinstance(raw, str):
        try:
            answers = json.loads(raw)
        except (ValueError, RecursionError):
            answers = receipt.get("native_answer")
    deviations: list[float] = []
    for answer in answers.values() if isinstance(answers, dict) else ():
        score = answer.get("score") if isinstance(answer, dict) else None
        probabilities = answer.get("probabilities") if isinstance(answer, dict) else None
        if (
            not isinstance(score, int | float)
            or isinstance(score, bool)
            or not isinstance(probabilities, dict)
        ):
            continue
        try:
            expected = math.fsum(int(level) * float(p) for level, p in probabilities.items())
        except (TypeError, ValueError):
            continue
        deviation = abs(float(score) - expected)
        if math.isfinite(deviation):
            deviations.append(deviation)
    return max(deviations) if deviations else None


# ---------------------------------------------------------------------------
# Dispatch phase (grade-free)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderResult:
    """One selector call on one presentation order of one pool."""

    order: str
    candidate_ids: tuple[str, ...]
    valid: bool
    failure: str | None
    judge_error: str
    winner_id: str | None
    reason: str = ""
    scores: Mapping[str, int | float] | None = None
    tie_break_applied: bool | None = None
    receipt: Mapping[str, Any] | None = None
    expectation_deviation: float | None = None
    usage: Mapping[str, int | None] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "candidate_ids": list(self.candidate_ids),
            "selector_calls": 1,
            "valid": self.valid,
            "failure": self.failure,
            "judge_error": self.judge_error,
            "winner_id": self.winner_id,
            "reason": self.reason,
            "scores": dict(self.scores) if self.scores is not None else None,
            "tie_break_applied": self.tie_break_applied,
            "receipt": dict(self.receipt) if self.receipt is not None else None,
            "expectation_deviation": self.expectation_deviation,
            # Observed selector usage; None = unknown, never zero (03 §4).
            "usage": dict(self.usage) if self.usage is not None else None,
        }


def _presentation(pool: FrozenPool, order: str) -> tuple[tuple[str, ...], list[str]]:
    indices = order_indices(pool, order)
    return (
        tuple(pool.candidates[index].candidate_id for index in indices),
        [pool.candidates[index].text for index in indices],
    )


def _correlation(session_id: str, pool: FrozenPool, selector: str, order: str) -> dict[str, Any]:
    # Hook/receipt join keys only; adapters never send request metadata to a model.
    return {"session_id": session_id, "turn_id": pool.pool_id, "step_id": f"{selector}:{order}"}


def _receipt_failure(judge_error: str, receipts: Sequence[Mapping[str, Any]]) -> str | None:
    """Why a pointwise order is invalid; ``None`` when the receipt was admitted."""
    if judge_error:
        return "judge_error"
    if len(receipts) != 1:
        return "receipt_missing" if not receipts else "receipt_duplicated"
    return None if receipts[0].get("accepted") is True else "receipt_not_accepted"


@dataclass(frozen=True, slots=True)
class PointwiseSelector:
    """Matched Score selector (``engine`` "llm" = Astra, "jev" = Jev) at the judge boundary."""

    name: str
    engine: Literal["llm", "jev"]
    backend: LLMAdapter
    events: RuntimeEventBus | None = None
    session_id: str = "score-selection"
    # Jev only: the V1 parser bounds; the Score bound is frozen after U0b (§4.1).
    sum_tolerance: float = STRICT_PROBABILITY_TOLERANCE
    score_tolerance: float = STRICT_PROBABILITY_TOLERANCE

    @property
    def kind(self) -> str:
        return "pointwise"

    @property
    def tolerances(self) -> dict[str, float] | None:
        if self.engine != "jev":
            return None
        return {"sum_tolerance": self.sum_tolerance, "score_tolerance": self.score_tolerance}

    def matched_adapter(
        self, pool: FrozenPool, order: str, receipts: list[dict[str, Any]]
    ) -> MatchedCandidateAdapter:
        ids, texts = _presentation(pool, order)
        return MatchedCandidateAdapter(
            self.engine,
            pool.task,
            texts,
            backend=self.backend,
            receipts=receipts,
            pool_id=pool.pool_id,
            candidate_ids=ids,
            sum_tolerance=self.sum_tolerance,
            score_tolerance=self.score_tolerance,
        )

    def preflight(self, pool: FrozenPool, order: str) -> None:
        self.matched_adapter(pool, order, [])

    async def run(self, pool: FrozenPool, order: str) -> OrderResult:
        ids, texts = _presentation(pool, order)
        receipts: list[dict[str, Any]] = []
        registry = MiddlewareRegistry(events=self.events)
        registry.register_llm_request(
            self.matched_adapter(pool, order, receipts), allow_cache_invalidation=True
        )
        verdict = await candidate_sampling.judge_candidates(
            pool.task,
            texts,
            model=ROOT_MODEL,
            provider="openai",
            source="subscription",
            effort="xhigh",
            middleware_registry=registry,
            correlation=_correlation(self.session_id, pool, self.name, order),
        )
        receipt = receipts[0] if len(receipts) == 1 else None
        failure = _receipt_failure(verdict.judge_error, receipts)
        scores: dict[str, Any] | None = None
        winner: str | None = None
        tie: bool | None = None
        if failure is None and receipt is not None:
            try:
                scores = {ids[i]: receipt["scores"][f"c{i}"] for i in range(len(ids))}
                exact = {key: Fraction(value) for key, value in scores.items()}
                winner, tie = select_by_score(pool.pool_id, exact)
            except (KeyError, TypeError, ValueError):
                failure = "receipt_scores_invalid"
            else:
                # The projected select_candidate winner must be the same hash-rule argmax.
                projected = receipt.get("winner_index")
                if projected != verdict.winner_index or winner != ids[verdict.winner_index]:
                    failure = "projection_mismatch"
        valid = failure is None
        return OrderResult(
            order=order,
            candidate_ids=ids,
            valid=valid,
            failure=failure,
            judge_error=verdict.judge_error,
            winner_id=winner if valid else None,
            reason=verdict.reason,
            scores=scores if valid else None,
            tie_break_applied=tie if valid else None,
            receipt=receipt,
            expectation_deviation=_expectation_deviation(receipt) if self.engine == "jev" else None,
            usage=receipt.get("usage") if receipt is not None else None,
        )


@dataclass(frozen=True, slots=True)
class ListwiseSelector:
    """Operational ``select_candidate`` judge: winner index only, no scores."""

    name: str
    events: RuntimeEventBus | None = None
    session_id: str = "score-selection"

    @property
    def kind(self) -> str:
        return "listwise"

    @property
    def engine(self) -> None:
        return None

    @property
    def tolerances(self) -> None:
        return None

    def preflight(self, pool: FrozenPool, order: str) -> None:
        order_indices(pool, order)

    async def run(self, pool: FrozenPool, order: str) -> OrderResult:
        ids, texts = _presentation(pool, order)
        verdict = await candidate_sampling.judge_candidates(
            pool.task,
            texts,
            model=ROOT_MODEL,
            provider="openai",
            source="subscription",
            effort="xhigh",
            middleware_registry=MiddlewareRegistry(events=self.events),
            correlation=_correlation(self.session_id, pool, self.name, order),
        )
        valid = not verdict.judge_error
        return OrderResult(
            order=order,
            candidate_ids=ids,
            valid=valid,
            failure=None if valid else "judge_error",
            judge_error=verdict.judge_error,
            winner_id=ids[verdict.winner_index] if valid else None,
            reason=verdict.reason,
        )


Selector = PointwiseSelector | ListwiseSelector


def _preflight(pools: Sequence[FrozenPool], selectors: Sequence[Selector]) -> None:
    from core.config import settings

    if settings.judgment_engine != "llm":
        raise ValueError("Score selection owns its engines; global Jev must be disabled")
    if settings.llm_max_retries != 1:
        raise ValueError("Score selection requires llm_max_retries=1 (one attempt per call)")
    if not pools or not selectors:
        raise ValueError("Score selection needs at least one pool and one selector")
    if len({pool.pool_id for pool in pools}) != len(pools):
        raise ValueError("pool ids must be unique")
    names = [selector.name for selector in selectors]
    if len(set(names)) != len(names) or not all(is_safe_candidate_id(name) for name in names):
        raise ValueError("selector names must be unique safe identifiers")
    problems: list[str] = []
    for pool in pools:
        for selector in selectors:
            for order in ORDERS:
                try:
                    selector.preflight(pool, order)
                except ValueError as error:
                    problems.append(f"{pool.pool_id}/{selector.name}/{order}: {error}")
    if problems:
        raise ValueError("pools failed preflight before any dispatch: " + "; ".join(problems))


async def dispatch_selection(
    pools: Sequence[FrozenPool], selectors: Sequence[Selector]
) -> list[dict[str, Any]]:
    """Run each selector exactly once per pool and order; grades are never read.

    Every adapter is constructed in a preflight pass first, so a malformed pool
    fails before the first dispatch. Records carry no grades.
    """
    _preflight(pools, selectors)
    records: list[dict[str, Any]] = []
    for pool in pools:
        entries: dict[str, Any] = {}
        for selector in selectors:
            orders = {order: (await selector.run(pool, order)).to_json() for order in ORDERS}
            entries[selector.name] = {
                "type": selector.kind,
                "engine": selector.engine,
                "tolerances": getattr(selector, "tolerances", None),
                "orders": orders,
            }
        records.append(
            {
                "schema": RECORD_SCHEMA,
                "pool_id": pool.pool_id,
                "kind": pool.kind,
                "cluster_id": pool.cluster_id,
                "split": pool.split,
                # Grade-free digests only: a graded digest of four candidates is
                # brute-forceable, so it never enters a dispatch record.
                "frozen_pool_sha256": frozen_pool_sha256(pool),
                "public_pool_sha256": public_pool_sha256(pool),
                "forward_candidate_ids": [c.candidate_id for c in pool.candidates],
                "selectors": entries,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Scoring phase (after unsealing)
# ---------------------------------------------------------------------------


def _fractions(scores: object, ids: Sequence[str], label: str) -> dict[str, Fraction]:
    if (
        not isinstance(scores, dict)
        or set(scores) != set(ids)
        or any(
            type(value) not in (int, float) or not math.isfinite(value) for value in scores.values()
        )
    ):
        raise ValueError(f"{label}: order scores do not cover the pool with finite numbers")
    return {candidate_id: Fraction(scores[candidate_id]) for candidate_id in ids}


def _check_orders(entry: Mapping[str, Any], ids: list[str], label: str) -> dict[str, Any]:
    orders = entry.get("orders")
    if not isinstance(orders, dict) or set(orders) != set(ORDERS):
        raise ValueError(f"{label}: record needs exactly one result per order")
    for order, expected in (("forward", ids), ("reverse", ids[::-1])):
        if orders[order].get("candidate_ids") != expected:
            raise ValueError(f"{label}: {order} presentation differs from the frozen pool")
    return orders


def _pointwise_outcome(
    pool_id: str, entry: Mapping[str, Any], ids: list[str], grades: Mapping[str, int]
) -> dict[str, Any]:
    label = f"{pool_id}/{entry.get('engine')}"
    orders = _check_orders(entry, ids, label)
    best = max(grades.values())
    per_order = {
        order: _fractions(orders[order]["scores"], ids, label) if orders[order]["valid"] else None
        for order in ORDERS
    }
    winners = {
        order: select_by_score(pool_id, scores)[0] if scores is not None else None
        for order, scores in per_order.items()
    }
    forward, reverse = per_order["forward"], per_order["reverse"]
    outcome: dict[str, Any] = {
        "type": "pointwise",
        "engine": entry.get("engine"),
        "valid": forward is not None and reverse is not None,
        "invalid_orders": [order for order in ORDERS if per_order[order] is None],
        "order_winners": winners,
        "order_expectation_deviation": {
            order: orders[order].get("expectation_deviation") for order in ORDERS
        },
        "order_usage": {order: orders[order].get("usage") for order in ORDERS},
        "mean_scores": None,
        "selected_id": None,
        "tie_break_applied": None,
        "correct": False,
        "oracle_best_value": 0.0,
        "regret": None,
        "order_consistent": None,
        "rank_agreement_tau_b": None,
        "selector_calls": len(ORDERS),
    }
    if forward is not None and reverse is not None:
        mean = {cid: (forward[cid] + reverse[cid]) / 2 for cid in ids}
        selected, tie = select_by_score(pool_id, mean)
        outcome.update(
            mean_scores={cid: float(value) for cid, value in mean.items()},
            selected_id=selected,
            tie_break_applied=tie,
            correct=grades[selected] == best,
            oracle_best_value=1.0 if grades[selected] == best else 0.0,
            regret=best - grades[selected],
            order_consistent=winners["forward"] == winners["reverse"],
            rank_agreement_tau_b=kendall_tau_b(
                [forward[cid] for cid in ids], [reverse[cid] for cid in ids]
            ),
        )
    return outcome


def _listwise_outcome(
    pool_id: str, entry: Mapping[str, Any], ids: list[str], grades: Mapping[str, int]
) -> dict[str, Any]:
    label = f"{pool_id}/listwise"
    orders = _check_orders(entry, ids, label)
    best = max(grades.values())
    winners: dict[str, str | None] = {}
    for order in ORDERS:
        winner = orders[order]["winner_id"] if orders[order]["valid"] else None
        if winner is not None and winner not in grades:
            raise ValueError(f"{label}: {order} winner is not a pool candidate")
        winners[order] = winner
    hits = {
        order: winners[order] is not None and grades[str(winners[order])] == best
        for order in ORDERS
    }
    valid = all(winner is not None for winner in winners.values())
    return {
        "type": "listwise",
        "engine": None,
        "valid": valid,
        "invalid_orders": [order for order in ORDERS if winners[order] is None],
        "order_winners": winners,
        "order_hits": {order: int(hit) for order, hit in hits.items()},
        "order_usage": {order: orders[order].get("usage") for order in ORDERS},
        "correct": None,
        "oracle_best_value": sum(hits.values()) / len(ORDERS),
        "regret": (
            sum(best - grades[str(winner)] for winner in winners.values()) / len(ORDERS)
            if valid
            else None
        ),
        "order_consistent": winners["forward"] == winners["reverse"] if valid else None,
        "selector_calls": len(ORDERS),
    }


def _acceptable_value(outcome: Mapping[str, Any], acceptable: set[str]) -> float:
    """Selected acceptance; an invalid order or fallback contributes 0 (05 §4.1)."""
    if outcome["type"] == "pointwise":
        return 1.0 if outcome["selected_id"] in acceptable else 0.0
    winners = outcome["order_winners"].values()
    return sum(winner in acceptable for winner in winners) / len(ORDERS)


def score_selection(
    records: Sequence[Mapping[str, Any]],
    pools: Sequence[FrozenPool],
    *,
    graded: Mapping[str, GradedPool] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Derive per-pool outcomes from dispatch records and model-free grades.

    ``pools`` are the dispatched pools (verified against each record's
    ``frozen_pool_sha256``). Grades come from ``graded`` joined through
    :func:`attach_grades` (``aliases`` for sealed alias ids), otherwise from the
    pools themselves. Tie keys always use the dispatched ids.
    """
    by_id = {pool.pool_id: pool for pool in pools}
    record_ids = [str(record.get("pool_id")) for record in records]
    if len(by_id) != len(pools) or sorted(record_ids) != sorted(by_id):
        # The planned pool count is the frozen denominator: no pool may be dropped.
        raise ValueError("records must cover every planned pool exactly once")
    if graded is not None:
        by_id = {pool.pool_id: pool for pool in attach_grades(pools, graded, aliases=aliases)}
    outcomes: list[dict[str, Any]] = []
    for record in records:
        pool = by_id.get(str(record.get("pool_id")))
        if pool is None or record.get("frozen_pool_sha256") != frozen_pool_sha256(pool):
            raise ValueError(f"{record.get('pool_id')}: record does not match a dispatched pool")
        if not pool.graded:
            raise ValueError(f"{pool.pool_id}: grades are still sealed")
        ids = [candidate.candidate_id for candidate in pool.candidates]
        grades = {
            candidate.candidate_id: int(candidate.grade or 0) for candidate in pool.candidates
        }
        best = max(grades.values())
        best_ids = [cid for cid in ids if grades[cid] == best]
        acceptable_grade = (
            pool.full_grade if pool.kind == "natural" else CONTROLLED_ACCEPTABLE_GRADE
        )
        acceptable = [cid for cid in ids if grades[cid] == acceptable_grade]
        selectors: dict[str, Any] = {}
        for name, entry in record["selectors"].items():
            if entry.get("type") not in ("pointwise", "listwise"):
                raise ValueError(f"{pool.pool_id}/{name}: unknown selector type")
            builder = _pointwise_outcome if entry["type"] == "pointwise" else _listwise_outcome
            outcome = builder(pool.pool_id, entry, ids, grades)
            outcome["selected_acceptable_value"] = _acceptable_value(outcome, set(acceptable))
            selectors[name] = outcome
        outcomes.append(
            {
                "schema": OUTCOME_SCHEMA,
                "pool_id": pool.pool_id,
                "kind": pool.kind,
                "cluster_id": pool.cluster_id,
                "split": pool.split,
                "frozen_pool_sha256": frozen_pool_sha256(pool),
                "graded_pool_sha256": graded_pool_sha256(pool),
                "source_pool_sha256": pool.source_pool_sha256,
                "graded_pool_id": pool.provenance.get("graded_pool_id", pool.pool_id),
                "n_candidates": len(ids),
                "forward_candidate_ids": ids,
                "grades": grades,
                "best_grade": best,
                "best_ids": best_ids,
                "full_grade": pool.full_grade,
                "acceptance_rule": ACCEPTANCE_RULES[pool.kind],
                "acceptable_ids": acceptable,
                "natural_complete": pool.provenance.get("complete"),
                "non_discriminative": len(set(grades.values())) == 1,
                "oracle_best_baselines": {
                    "first_candidate": ids[0] in best_ids,
                    "random": len(best_ids) / len(ids),
                },
                "selectors": selectors,
            }
        )
    return outcomes


# ---------------------------------------------------------------------------
# Aggregates (explicit numerator / denominator, no NaN)
# ---------------------------------------------------------------------------


def _number(value: Fraction) -> int | float:
    return int(value) if value.denominator == 1 else float(value)


def _ratio(numerator: Fraction | int, denominator: int) -> dict[str, Any]:
    exact = Fraction(numerator)
    return {
        "numerator": _number(exact),
        "denominator": denominator,
        "value": float(exact / denominator) if denominator else None,
    }


def _usage_totals(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Selection cost of every planned order, failures included; unknown stays null."""
    usages = [usage for row in rows for usage in row.get("order_usage", {}).values()]
    totals: dict[str, Any] = {"calls": sum(row["selector_calls"] for row in rows)}
    for counter in ("input_tokens", "output_tokens"):
        values = [usage.get(counter) if usage else None for usage in usages]
        observed = [value for value in values if isinstance(value, int)]
        missing = totals["calls"] - len(observed)
        totals[f"{counter}_observed_sum"] = sum(observed)
        totals[f"{counter}_missing_calls"] = missing
        totals[f"{counter}_total"] = sum(observed) if missing == 0 else None
    return totals


def _selector_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    planned = len(rows)
    kinds = {row["type"] for row in rows}
    if len(kinds) != 1:
        raise ValueError("one selector name must keep one selector type")
    valid = [row for row in rows if row["valid"]]
    consistent = [row for row in rows if row["order_consistent"] is not None]
    summary: dict[str, Any] = {
        "type": rows[0]["type"],
        "engine": rows[0]["engine"],
        # oracle-best 선택률: planned pools; invalid or fallback = wrong (05 §3.1).
        "oracle_best_selection": _ratio(
            sum((Fraction(row["oracle_best_value"]) for row in rows), Fraction(0)), planned
        ),
        "valid_pools": len(valid),
        "invalid_pools": planned - len(valid),
        "invalid_orders": {
            order: sum(order in row["invalid_orders"] for row in rows) for order in ORDERS
        },
        # regret = best grade - selected grade, over pools with a valid selection.
        "regret_valid_mean": _ratio(
            sum((Fraction(row["regret"]) for row in valid), Fraction(0)), len(valid)
        ),
        "order_consistency": _ratio(
            sum(row["order_consistent"] is True for row in consistent), len(consistent)
        ),
        "selection_cost": _usage_totals(rows),
    }
    if rows[0]["type"] == "pointwise":
        taus = [
            row["rank_agreement_tau_b"] for row in rows if row["rank_agreement_tau_b"] is not None
        ]
        deviations = [
            value
            for row in rows
            for value in row["order_expectation_deviation"].values()
            if value is not None
        ]
        summary.update(
            rank_agreement_tau_b={
                "mean": math.fsum(taus) / len(taus) if taus else None,
                "defined_pools": len(taus),
            },
            tie_breaks_applied=sum(row["tie_break_applied"] is True for row in rows),
            score_expectation={
                "orders_measured": len(deviations),
                "max_abs_deviation": max(deviations) if deviations else None,
                "tolerance_rule": TOLERANCE_RULE,
                "tolerance": score_expectation_tolerance(max(deviations)) if deviations else None,
            },
        )
    else:
        summary["listwise_mean"] = summary["oracle_best_selection"]
    return summary


def _paired_delta(
    outcomes: Sequence[Mapping[str, Any]], baseline: str, comparison: str
) -> dict[str, Any]:
    diffs = [
        Fraction(outcome["selectors"][comparison]["oracle_best_value"])
        - Fraction(outcome["selectors"][baseline]["oracle_best_value"])
        for outcome in outcomes
    ]
    return {
        "baseline": baseline,
        "comparison": comparison,
        "direction": "target",
        "aggregation": (
            "sum(oracle_best(comparison) - oracle_best(baseline)) / planned pools; "
            "invalid or fallback = wrong"
        ),
        **_ratio(sum(diffs, Fraction(0)), len(outcomes)),
        "comparison_better": sum(diff > 0 for diff in diffs),
        "baseline_better": sum(diff < 0 for diff in diffs),
        "equal": sum(diff == 0 for diff in diffs),
    }


def _acceptance(rows: Sequence[Mapping[str, Any]], names: Sequence[str]) -> dict[str, Any]:
    """pool-random@1, oracle-coverage@4, selected success and gap closed for one kind."""
    ids = [row["forward_candidate_ids"] for row in rows]
    report = score_acceptance_summary(
        [
            [cid in row["acceptable_ids"] for cid in forward]
            for row, forward in zip(rows, ids, strict=True)
        ],
        {
            name: [row["selectors"][name]["selected_acceptable_value"] for row in rows]
            for name in names
        },
        planned_width=MAX_BEST_OF,
    )
    report["acceptance_rule"] = rows[0]["acceptance_rule"]
    # Natural pools: every best_of candidate succeeded; controlled pools are authored.
    report["complete_pools"] = (
        sum(row["natural_complete"] is True for row in rows)
        if rows[0]["kind"] == "natural"
        else None
    )
    return report


def summarize_outcomes(
    outcomes: Sequence[Mapping[str, Any]], *, deltas: Sequence[tuple[str, str, str]] = ()
) -> dict[str, Any]:
    """Aggregate outcomes over planned pools; ``deltas`` = (name, baseline, comparison).

    Oracle-best selection uses planned pools as denominator (invalid = wrong); regret
    uses valid pools; order consistency uses pools whose both orders are valid. The
    acceptance block (pool-random@1, oracle-coverage@4, selected success, gap closed)
    is reported per pool kind. Undefined values are ``null`` or ``"not-measurable"``,
    never NaN.
    """
    if not outcomes:
        raise ValueError("no pool outcomes to summarize")
    planned = len(outcomes)
    names = list(outcomes[0]["selectors"])
    if len({outcome["pool_id"] for outcome in outcomes}) != planned or any(
        list(outcome["selectors"]) != names for outcome in outcomes
    ):
        raise ValueError("outcomes need unique pool ids and the same selectors")
    for _, baseline, comparison in deltas:
        if baseline not in names or comparison not in names:
            raise ValueError(f"unknown selector in delta: {baseline}, {comparison}")
    entries = [entry for outcome in outcomes for entry in outcome["selectors"].values()]
    calls = sum(entry["selector_calls"] for entry in entries)
    kinds = sorted({str(outcome["kind"]) for outcome in outcomes})
    return {
        "planned_pools": planned,
        "pool_kinds": kinds,
        "selector_calls": calls,
        "valid_selections": _ratio(
            sum(entry["selector_calls"] - len(entry["invalid_orders"]) for entry in entries), calls
        ),
        "non_discriminative": _ratio(
            sum(outcome["non_discriminative"] for outcome in outcomes), planned
        ),
        "oracle_best_baselines": {
            "first_candidate": _ratio(
                sum(outcome["oracle_best_baselines"]["first_candidate"] for outcome in outcomes),
                planned,
            ),
            "random": _ratio(
                sum(
                    (
                        Fraction(len(outcome["best_ids"]), outcome["n_candidates"])
                        for outcome in outcomes
                    ),
                    Fraction(0),
                ),
                planned,
            ),
        },
        "selectors": {
            name: _selector_summary([outcome["selectors"][name] for outcome in outcomes])
            for name in names
        },
        "paired_deltas": {
            name: _paired_delta(outcomes, baseline, comparison)
            for name, baseline, comparison in deltas
        },
        "acceptance": {
            kind: _acceptance([outcome for outcome in outcomes if outcome["kind"] == kind], names)
            for kind in kinds
        },
    }


# ---------------------------------------------------------------------------
# Offline self-test (fakes only; zero model dispatches)
# ---------------------------------------------------------------------------


class _SelfTestSubscription:
    """Offline stand-in for the Astra subscription adapter: route identity, scores, listwise."""

    name = "self-test-subscription"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, quality: Mapping[str, float]) -> None:
        self.quality = dict(quality)
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(req)
        usage = UsageSummary(
            input_tokens=100, output_tokens=5, input_tokens_present=True, output_tokens_present=True
        )
        if req.tools:
            # Listwise judge with a deliberate first-position bias.
            pick = {"winner_index": 0, "reason": "self-test: first presented candidate"}
            return AdapterCallResult(
                text="",
                usage=usage,
                stop_reason="completed",
                tool_uses=({"name": "select_candidate", "input": pick},),
                response_model=ROOT_MODEL,
            )
        content = req.messages[0].content
        if not isinstance(content, str):
            raise ValueError("self-test scorer expects one text message")
        payload = json.loads(
            unescape(content.removeprefix("<scoring_input>").removesuffix("</scoring_input>"))
        )
        scores = {key: self.quality[text] for key, text in payload["state"]["candidates"].items()}
        return AdapterCallResult(
            text=json.dumps(scores), usage=usage, stop_reason="completed", response_model=ROOT_MODEL
        )


def _self_test_score_answer(score: float) -> dict[str, Any]:
    lower, upper = math.floor(score), math.ceil(score)
    probabilities = {str(level): 0.0 for level in range(len(CANDIDATE_LEVELS))}
    probabilities[str(lower)] = 1.0 - (score - lower)
    if upper != lower:
        probabilities[str(upper)] = score - lower
    return {
        "type": "score",
        "score": score,
        "legend": {str(level): text for level, text in enumerate(CANDIDATE_LEVELS)},
        "probabilities": probabilities,
        "confidence": 0.5,
    }


def _self_test_pools() -> tuple[list[FrozenPool], dict[str, float]]:
    from evals.benchmarks.decision_handoff_runtime import inbox_request

    def answer(order_id: str, status: str, evidence: str) -> str:
        item = {"id": "only", "order_id": order_id, "status": status, "disposition": "answered"}
        return json.dumps({"items": [item]}) + "\nEvidence: " + evidence

    seen = "lookup_order_status observed the order"
    controlled = [
        FrozenPool(
            "selftest-ctl-1",
            "Process every inbox item: what is the status of A-104?",
            (
                PoolCandidate("ctl1-a", answer("A-104", "delivered", seen), 0),
                PoolCandidate("ctl1-b", answer("A-104", "shipped", seen), 3),
                PoolCandidate("ctl1-c", answer("A-104", "delivered", "none"), 0),
                PoolCandidate("ctl1-d", answer("A-104", "shipped", "none"), 2),
            ),
            cluster_id="cl-selftest-1",
        ),
        FrozenPool(
            "selftest-ctl-2",
            "Process every inbox item: has B-209 been delivered?",
            (
                PoolCandidate("ctl2-a", answer("B-209", "delivered", seen), 3),
                PoolCandidate("ctl2-b", answer("B-209", "delivered", "none"), 2),
                PoolCandidate("ctl2-c", answer("B-209", "shipped", seen), 0),
                PoolCandidate("ctl2-d", answer("B-209", "shipped", "none"), 0),
            ),
            cluster_id="cl-selftest-1",
        ),
        FrozenPool(
            "selftest-ctl-tie",
            "Process every inbox item: status of C-318?",
            (
                PoolCandidate("tie-a", answer("C-318", "processing", seen), 3),
                PoolCandidate("tie-b", answer("C-318", "processing", seen + " twice"), 3),
                PoolCandidate("tie-c", answer("C-318", "shipped", seen), 0),
            ),
            cluster_id="cl-selftest-2",
        ),
    ]
    items: list[dict[str, Any]] = [
        {
            "id": "first",
            "request": "What is the status of A-104?",
            "candidates": ["A-104"],
            "expected_intent": "status_only",
            "expected_order": "A-104",
            "expected_answer": {
                "order_id": "A-104",
                "status": "shipped",
                "disposition": "answered",
            },
        },
        {
            "id": "second",
            "request": "Please cancel B-209.",
            "candidates": ["B-209"],
            "expected_intent": "cancel",
            "expected_order": "B-209",
            "expected_answer": {"order_id": "B-209", "status": None, "disposition": "unsupported"},
        },
    ]
    case = {"id": "selftest-inbox", "profile": "inbox", "items": items}
    case["request"] = inbox_request(items)
    full = [{"id": item["id"], **item["expected_answer"]} for item in items]
    half = [full[0], {**full[1], "status": "cancelled", "disposition": "answered"}]
    task = "Resolve the fixed inbox and return the JSON items."
    outputs = [json.dumps({"items": full}), json.dumps({"items": half}), None, "Not finished."]
    rows = [
        {
            "task_id": f"delegate_selftest00_{index}",
            "description": lensed_description(task, index),
            "success": output is not None,
            "output": {"text": output} if output is not None else {},
        }
        for index, output in enumerate(outputs)
    ]
    natural = freeze_natural_pool(
        pool_id="selftest-nat-1",
        task=task,
        case=case,
        orders={"A-104": "shipped", "B-209": "delivered"},
        payload={"tasks": rows, "best_of": {"n": len(rows), "winner_task_id": rows[0]["task_id"]}},
    )
    pools = [*controlled, natural]
    quality: dict[str, float] = {}
    for pool in pools:
        top = pool.full_grade or 3
        for candidate in pool.candidates:
            quality[candidate.text] = 3.0 * (candidate.grade or 0) / top
    return pools, quality


def _rotated(pool: FrozenPool) -> FrozenPool:
    return replace(pool, candidates=(*pool.candidates[1:], pool.candidates[0]))


async def self_test() -> dict[str, Any]:
    """Run the full both-order path on fakes: subscription stub + MockTransport Jev."""
    from unittest import mock

    import httpx
    from core.config import settings
    from core.hooks import HookEvent, HookSystem
    from core.hooks.system import HookDispatch
    from core.llm.adapters.typesafe import JEV_MODEL, SystemOneAdapter
    from pydantic import SecretStr

    pools, quality = _self_test_pools()
    invalid_first = {pools[1].candidates[-1].text}  # selftest-ctl-2 reverse order only
    fake = _SelfTestSubscription(quality)
    jev_calls: list[dict[str, Any]] = []
    events: dict[str, int] = {"started": 0, "ended": 0}

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        jev_calls.append(body)
        presented = list(body["state"]["candidates"].items())
        answers = {
            key: _self_test_score_answer(min(3.0, quality[text] + (0.5 if index == 0 else 0.0)))
            for index, (key, text) in enumerate(presented)
        }
        if presented[0][1] in invalid_first:
            answers["c0"]["legend"]["0"] = "changed criterion"
        return httpx.Response(
            200,
            json={
                "model": JEV_MODEL,
                "usage": {"input_tokens": 120, "output_tokens": 0},
                "answers": answers,
            },
            headers={"x-typesafe-request-id": "self-test"},
        )

    def count(dispatch: HookDispatch) -> None:
        if dispatch.event == HookEvent.LLM_CALL_STARTED:
            events["started"] += 1
        elif dispatch.event == HookEvent.LLM_CALL_ENDED:
            events["ended"] += 1

    hooks = HookSystem()
    hooks.register_sink(count, name="score-self-test-counter")
    previous_retries = settings.llm_max_retries
    settings.llm_max_retries = 1
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            jev = SystemOneAdapter("typesafe", SecretStr("self-test-offline"), client=client)
            selectors: list[Selector] = [
                PointwiseSelector("astra-pointwise", "llm", fake, events=hooks),
                PointwiseSelector("jev-pointwise", "jev", jev, events=hooks),
                ListwiseSelector("listwise", events=hooks),
            ]
            with mock.patch.object(candidate_sampling, "resolve_for", lambda *_args: fake):
                records = await dispatch_selection(pools, selectors)
                rotated = [_rotated(pool) for pool in pools]
                rotated_records = await dispatch_selection(rotated, selectors[:1])
    finally:
        settings.llm_max_retries = previous_retries
        hooks.close()
    outcomes = score_selection(records, pools)
    summary = summarize_outcomes(
        outcomes, deltas=[("score_ctl_top1_delta", "astra-pointwise", "jev-pointwise")]
    )
    rotated_outcomes = score_selection(rotated_records, rotated)
    expected_calls = 2 * (len(pools) * len(selectors) + len(pools))
    by_pool = {outcome["pool_id"]: outcome for outcome in outcomes}
    selected = {pid: o["selectors"]["astra-pointwise"]["selected_id"] for pid, o in by_pool.items()}
    rotated_selected = {
        outcome["pool_id"]: outcome["selectors"]["astra-pointwise"]["selected_id"]
        for outcome in rotated_outcomes
    }
    jev_ctl2 = by_pool["selftest-ctl-2"]["selectors"]["jev-pointwise"]
    checks = {
        "one_selector_call_per_pool_and_order": summary["selector_calls"]
        + sum(len(r["selectors"]) * len(ORDERS) for r in rotated_records)
        == expected_calls,
        "fake_backends_saw_each_call_once": len(fake.requests) + len(jev_calls) == expected_calls,
        "every_call_observed_once": events["started"] == events["ended"] == expected_calls,
        "dispatch_records_carry_no_grades": '"grade' not in _canonical(records),
        "invalid_order_counts_wrong": not jev_ctl2["valid"]
        and jev_ctl2["oracle_best_value"] == 0.0
        and jev_ctl2["selected_acceptable_value"] == 0.0,
        "listwise_averages_order_hits": all(
            o["selectors"]["listwise"]["oracle_best_value"]
            == sum(o["selectors"]["listwise"]["order_hits"].values()) / 2
            for o in outcomes
        ),
        "hash_tie_rule_applied": by_pool["selftest-ctl-tie"]["selectors"]["astra-pointwise"][
            "tie_break_applied"
        ]
        is True,
        "selection_invariant_under_permutation": selected == rotated_selected,
        "acceptance_uses_v1_names": set(summary["acceptance"]) == {"controlled", "natural"}
        and all(
            "pool_random_at_1" in block and "oracle_coverage_at_4" in block
            for block in summary["acceptance"].values()
        )
        and "pass@" not in _canonical(summary)
        and "pass_at" not in _canonical(summary),
    }
    try:
        _canonical({"records": records, "outcomes": outcomes, "summary": summary})
    except (TypeError, ValueError):
        checks["json_without_nan"] = False
    else:
        checks["json_without_nan"] = True
    return {
        "self_test": "score-selection",
        "model_dispatches": 0,
        "fake_dispatches": {
            "subscription_stub": len(fake.requests),
            "typesafe_mock_transport": len(jev_calls),
        },
        "observed_llm_calls": events,
        "pools": len(pools),
        "summary": summary,
        "checks": checks,
        "passed": all(checks.values()),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _delta(value: str) -> tuple[str, str, str]:
    name, _, pair = value.partition("=")
    baseline, _, comparison = pair.partition(":")
    if not (name and baseline and comparison):
        raise argparse.ArgumentTypeError("use NAME=BASELINE:COMPARISON")
    return name, baseline, comparison


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.benchmarks.score_selection",
        description="Score-S harness: frozen best-of pools, both orders, model-free scoring.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("self-test", help="run both orders end to end on fakes (no models)")
    score = commands.add_parser("score", help="join grades to dispatch records (outcome JSONL)")
    score.add_argument("records", type=Path)
    score.add_argument("pools", type=Path)
    score.add_argument("--states", type=Path)
    score.add_argument("--graded", type=Path, help="sealed pools-graded.<split>.jsonl")
    score.add_argument("--aliases", type=Path, help="sealed aliases.<split>.json")
    summarize = commands.add_parser("summarize", help="aggregate outcome JSONL")
    summarize.add_argument("outcomes", type=Path)
    summarize.add_argument("--delta", type=_delta, action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "self-test":
        report = asyncio.run(self_test())
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0 if report["passed"] else 1
    if args.command == "score":
        outcomes = score_selection(
            [row for _, row in _read_jsonl(args.records)],
            load_pools(args.pools, states_path=args.states),
            graded=load_graded_pools(args.graded) if args.graded else None,
            aliases=load_aliases(args.aliases) if args.aliases else None,
        )
        sys.stdout.write("".join(_canonical(outcome) + "\n" for outcome in outcomes))
        return 0
    summary = summarize_outcomes([row for _, row in _read_jsonl(args.outcomes)], deltas=args.delta)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
