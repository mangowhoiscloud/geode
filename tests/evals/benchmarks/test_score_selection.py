"""Score-S harness: order/tie rules, invalid = wrong, sealed two-phase scoring, metrics."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from fractions import Fraction
from html import unescape
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from core.agent import candidate_sampling
from core.agent.candidate_sampling import lensed_description
from core.config import settings
from core.hooks import HookSystem
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from core.llm.adapters.typesafe import JEV_MODEL, SystemOneAdapter
from evals.benchmarks import score_selection as ss
from evals.benchmarks.decision_candidate import CANDIDATE_LEVELS, TIE_RULE_CANDIDATE_ID
from evals.benchmarks.decision_handoff import ROOT_MODEL
from evals.benchmarks.decision_handoff_runtime import HandoffReceipt, _inbox_oracle, inbox_request
from pydantic import SecretStr

_SEP = "␟"


def _digest(value: Any) -> str:
    """Build-A's canonical digest, restated independently of the harness."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _tie_key(pool_id: str, candidate_id: str) -> str:
    return hashlib.sha256(f"{pool_id}{_SEP}{candidate_id}".encode()).hexdigest()


def _pool(pool_id: str, grades: dict[str, int | None], **changes: Any) -> ss.FrozenPool:
    candidates = tuple(
        ss.PoolCandidate(cid, f"Answer from {cid}. Evidence: observation {cid}.", grade)
        for cid, grade in grades.items()
    )
    return ss.FrozenPool(pool_id, "Resolve the synthetic task.", candidates, **changes)


# ---------------------------------------------------------------------------
# Fakes for the real judge boundary (no model, no network)
# ---------------------------------------------------------------------------


def _score_answer(score: float) -> dict[str, Any]:
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


def _listwise_texts(prompt: str) -> list[str]:
    return [
        unescape(text)
        for _, text in re.findall(r'<candidate index="(\d+)">(.*?)</candidate>', prompt, re.S)
    ]


class _Subscription:
    name = "fake-subscription"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, quality: dict[str, float], pick: Any = None) -> None:
        self.quality = quality
        self.pick = pick or (lambda texts: 0)
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        usage = UsageSummary(
            input_tokens=10, output_tokens=1, input_tokens_present=True, output_tokens_present=True
        )
        content = request.messages[0].content
        assert isinstance(content, str)
        if request.tools:
            winner = self.pick(_listwise_texts(content))
            return AdapterCallResult(
                text="",
                usage=usage,
                stop_reason="completed",
                tool_uses=(
                    {"name": "select_candidate", "input": {"winner_index": winner, "reason": "x"}},
                ),
                response_model=ROOT_MODEL,
            )
        payload = json.loads(
            unescape(content.removeprefix("<scoring_input>").removesuffix("</scoring_input>"))
        )
        scores = {key: self.quality[text] for key, text in payload["state"]["candidates"].items()}
        return AdapterCallResult(
            text=json.dumps(scores), usage=usage, stop_reason="completed", response_model=ROOT_MODEL
        )


@dataclass
class _Run:
    records: list[dict[str, Any]]
    subscription: _Subscription
    jev_bodies: list[dict[str, Any]]
    events: Counter[str]


def _dispatch(
    monkeypatch: pytest.MonkeyPatch,
    pools: list[ss.FrozenPool],
    quality: dict[str, float],
    *,
    names: tuple[str, ...] = ("astra", "jev", "listwise"),
    pick: Any = None,
    jev_bias: float = 0.0,
    jev_broken_first: frozenset[str] = frozenset(),
    max_concurrency: int = 1,
    subscription_type: type[_Subscription] | None = None,
    timings: list[dict[str, Any]] | None = None,
    timeouts: dict[str, float] | None = None,
    jev_failures: Counter[str] | None = None,
) -> _Run:
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    subscription = (subscription_type or _Subscription)(quality, pick)
    monkeypatch.setattr(candidate_sampling, "resolve_for", lambda *_args: subscription)
    bodies: list[dict[str, Any]] = []
    events: Counter[str] = Counter()
    hooks = HookSystem()
    hooks.register_sink(lambda dispatch: events.update([dispatch.event.value]), name="counter")

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        presented = list(body["state"]["candidates"].values())
        if jev_failures is not None and jev_failures[presented[0]] > 0:
            jev_failures[presented[0]] -= 1  # an HTTP error status: no model response
            return httpx.Response(503, json={"error": "unavailable"})
        answers = {
            f"c{index}": _score_answer(min(3.0, quality[text] + (jev_bias if index == 0 else 0)))
            for index, text in enumerate(presented)
        }
        if presented[0] in jev_broken_first:
            answers["c0"]["legend"]["0"] = "changed criterion"
        return httpx.Response(
            200,
            json={
                "model": JEV_MODEL,
                "usage": {"input_tokens": 50, "output_tokens": 0},
                "answers": answers,
            },
            headers={"x-typesafe-request-id": "synthetic"},
        )

    async def run() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            jev = SystemOneAdapter("typesafe", SecretStr("synthetic-key"), client=client)
            available: dict[str, ss.Selector] = {
                "astra": ss.PointwiseSelector("astra", "llm", subscription, events=hooks),
                "jev": ss.PointwiseSelector("jev", "jev", jev, events=hooks),
                "listwise": ss.ListwiseSelector("listwise", events=hooks),
            }
            return await ss.dispatch_selection(
                pools,
                [available[name] for name in names],
                max_concurrency=max_concurrency,
                timings=timings,
                timeouts=timeouts,
            )

    try:
        records = asyncio.run(run())
    finally:
        hooks.close()
    return _Run(records, subscription, bodies, events)


def _quality(pools: list[ss.FrozenPool]) -> dict[str, float]:
    return {c.text: float(c.grade or 0) for pool in pools for c in pool.candidates}


@dataclass
class _Scripted:
    """Duck-typed selector replaying fixed per-order results (no judge call)."""

    name: str
    kind: str
    script: dict[tuple[str, str], Any]
    engine: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def preflight(self, pool: ss.FrozenPool, order: str) -> None:
        ss.order_indices(pool, order)

    async def run(self, pool: ss.FrozenPool, order: str) -> ss.OrderResult:
        self.calls.append((pool.pool_id, order))
        ids = tuple(pool.candidates[i].candidate_id for i in ss.order_indices(pool, order))
        value = self.script[(pool.pool_id, order)]
        if value is None:
            return ss.OrderResult(order, ids, False, "judge_error", "scripted failure", None)
        if self.kind == "listwise":
            return ss.OrderResult(order, ids, True, None, "", value)
        exact = {key: Fraction(score) for key, score in value.items()}
        winner, tie = ss.select_by_score(pool.pool_id, exact)
        return ss.OrderResult(
            order, ids, True, None, "", winner, scores=value, tie_break_applied=tie
        )


def _scripted_dispatch(
    monkeypatch: pytest.MonkeyPatch, pools: list[ss.FrozenPool], selectors: list[_Scripted]
) -> list[dict[str, Any]]:
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    return asyncio.run(ss.dispatch_selection(pools, selectors))


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def test_exact_ties_break_by_pool_candidate_hash_not_insertion_order() -> None:
    ids = ["cand-a", "cand-b", "cand-c", "cand-d"]
    expected = min(ids[:3], key=lambda cid: _tie_key("pool-t", cid))
    for permutation in itertools.permutations(ids):
        scores = {cid: Fraction(2 if cid != "cand-d" else 1) for cid in permutation}
        assert ss.select_by_score("pool-t", scores) == (expected, True)
    assert ss.select_by_score("pool-t", {"cand-a": Fraction(1), "cand-b": Fraction(3)}) == (
        "cand-b",
        False,
    )


def test_orders_are_frozen_and_reversed() -> None:
    pool = _pool("pool-o", {"a": 1, "b": 0, "c": 2})
    assert ss.order_indices(pool, "forward") == [0, 1, 2]
    assert ss.order_indices(pool, "reverse") == [2, 1, 0]
    with pytest.raises(ValueError, match="unknown presentation order"):
        ss.order_indices(pool, "shuffled")


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        ([1, 2, 3, 4], [1, 2, 3, 4], 1.0),
        ([1, 2, 3, 4], [4, 3, 2, 1], -1.0),
        ([1, 1, 2, 3], [1, 2, 2, 3], 0.8),  # 4 concordant, one tie on each side: 4/sqrt(5*5)
        ([0, 3, 2, 0], [0, 2.5, 2, 1], 5 / math.sqrt(30)),
        ([2, 2, 2], [1, 2, 3], None),
    ],
)
def test_kendall_tau_b_hand_computed(
    x: list[float], y: list[float], expected: float | None
) -> None:
    result = ss.kendall_tau_b([Fraction(v) for v in x], [Fraction(v) for v in y])
    assert result == pytest.approx(expected) if expected is not None else result is None


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        (0.0, 0.03),
        (0.02, 0.03),
        (0.03, 0.03),
        (0.031, 0.04),
        (0.04, 0.04),
        (0.0401, 0.05),
        (1e9, 0.05),
    ],
)
def test_score_expectation_tolerance_freeze_rule(observed: float, expected: float) -> None:
    assert ss.score_expectation_tolerance(observed) == expected


@pytest.mark.parametrize(
    ("probabilities", "score", "deviation", "tolerance"),
    [
        # Binary arithmetic gave 0.04000000000000001 and froze 0.05 (G-3 F1).
        ('{"0": 0.97, "1": 0.03}', "0.07", 0.04, 0.04),
        ('{"1": 1.0}', "1.03", 0.03, 0.03),
        # 5e-19 above 0.04: the nearest float is 0.04, the exact ceiling is 0.05.
        (
            '{"0": 0.9700000000000000005, "1": 0.0299999999999999995}',
            "0.07",
            0.040000000000001,
            0.05,
        ),
    ],
)
def test_expectation_deviation_is_exact_decimal_from_the_raw_answer(
    probabilities: str, score: str, deviation: float, tolerance: float
) -> None:
    raw = f'{{"c0": {{"type": "score", "score": {score}, "probabilities": {probabilities}}}}}'
    observed = ss._expectation_deviation({"raw_answer": raw})
    assert observed == deviation
    assert observed is not None and ss.score_expectation_tolerance(observed) == tolerance


# ---------------------------------------------------------------------------
# Frozen pools and loaders
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grades", "changes", "message"),
    [
        ({"a": 1}, {}, "2..4 candidates"),
        ({"a": 1, "b": 1, "c": 1, "d": 1, "e": 1}, {}, "2..4 candidates"),
        ({"a b": 1, "c": 1}, {}, "safe identifiers"),
        ({"a": -1, "b": 1}, {}, "all non-negative integers or all sealed"),
        ({"a": True, "b": 1}, {}, "all non-negative integers or all sealed"),
        ({"a": None, "b": 1}, {}, "all non-negative integers or all sealed"),
        ({"a": 1, "b": 1}, {"kind": "natural"}, "full_grade"),
        ({"a": 1, "b": 3}, {"kind": "natural", "full_grade": 2}, "full_grade"),
        ({"a": 1, "b": 1}, {"full_grade": 2}, "controlled pools have no full_grade"),
        ({"a": 1, "b": 1}, {"kind": "mixed"}, "unknown pool kind"),
        ({"a": 1, "b": 1}, {"source_pool_sha256": "abc"}, "sha256"),
        ({"a": 1, "b": 1}, {"cluster_id": "bad cluster"}, "cluster_id"),
        ({"a": 1, "b": 1}, {"provenance": {"x": float("nan")}}, "finite JSON"),
    ],
)
def test_invalid_pools_are_rejected(
    grades: dict[str, Any], changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _pool("pool-x", grades, **changes)


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_candidate_text_bound_matches_the_matched_adapter(text: str) -> None:
    good = ss.PoolCandidate("good", "fine")
    with pytest.raises(ValueError, match="at most 2000"):
        ss.FrozenPool("pool-x", "task", (good, ss.PoolCandidate("bad", text)))
    assert ss.FrozenPool("pool-x", "task", (good, ss.PoolCandidate("ok", "x" * 2000)))


def _write_jsonl(path: Path, rows: list[Any]) -> Path:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return path


def _states(pool_id: str, cluster: str, ids: list[str], request: str) -> list[dict[str, Any]]:
    return [
        {
            "state_id": cid,
            "cluster_id": cluster,
            "split": "selection",
            "stratum": "envelope",
            "quad_id": pool_id,
            "state": {"original_request": request, "task_contract": "contract"},
            "state_sha256": "0" * 64,
        }
        for cid in ids
    ]


def _build_a_row(pool_id: str, candidates: list[dict[str, Any]], cluster: str) -> dict[str, Any]:
    return {
        "pool_id": pool_id,
        "cluster_id": cluster,
        "split": "selection",
        "candidates": candidates,
        "pool_sha256": _digest({"pool_id": pool_id, "candidates": candidates}),
    }


def test_build_a_graded_and_public_rows_load_with_task_from_states(tmp_path: Path) -> None:
    graded = [
        {"candidate_id": "cl-a--q1-00", "text": "Answer: ok\nEvidence: []", "grade": 3},
        {"candidate_id": "cl-a--q1-10", "text": "Answer: bad\nEvidence: []", "grade": 0},
    ]
    public = [
        {"candidate_id": "s-0001", "text": "Answer: one"},
        {"candidate_id": "s-0002", "text": "Answer: two"},
    ]
    request = "Process every inbox item.<inbox>[]</inbox>"
    states = _write_jsonl(
        tmp_path / "states.jsonl",
        _states("cl-a--q1", "cl-a", ["cl-a--q1-00", "cl-a--q1-10"], request)
        + _states("q-0001", "cl-b", ["s-0001", "s-0002"], request),
    )
    pools_path = _write_jsonl(
        tmp_path / "pools.jsonl",
        [_build_a_row("cl-a--q1", graded, "cl-a"), _build_a_row("q-0001", public, "cl-b")],
    )
    first, second = ss.load_pools(pools_path, states_path=states)
    assert first.task == second.task == request
    assert (first.cluster_id, second.cluster_id) == ("cl-a", "cl-b")
    assert first.graded and [c.grade for c in first.candidates] == [3, 0]
    assert not second.graded and second.source_pool_sha256 == _digest(
        {"pool_id": "q-0001", "candidates": public}
    )
    assert ss.public_pool_sha256(second) == second.source_pool_sha256


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row["candidates"][0].update(text="tampered"), "pool_sha256 does not match"),
        (lambda row: row.update(extra=1), "unexpected pool fields"),
        (lambda row: row["candidates"][0].update(score=1), "candidate fields"),
        (lambda row: row.update(task="another task"), "differs from the states"),
        (lambda row: row.update(cluster_id="cl-other"), "cluster_id differs"),
    ],
)
def test_pool_rows_fail_closed(tmp_path: Path, mutate: Any, message: str) -> None:
    candidates = [
        {"candidate_id": "st-1", "text": "Answer: a"},
        {"candidate_id": "st-2", "text": "Answer: b"},
    ]
    row = _build_a_row("quad-1", candidates, "cl-a")
    mutate(row)
    states = _write_jsonl(
        tmp_path / "states.jsonl", _states("quad-1", "cl-a", ["st-1", "st-2"], "task")
    )
    with pytest.raises(ValueError, match=message):
        ss.load_pools(_write_jsonl(tmp_path / "pools.jsonl", [row]), states_path=states)


def test_pool_task_requires_row_task_or_agreeing_states(tmp_path: Path) -> None:
    candidates = [{"candidate_id": "st-1", "text": "a"}, {"candidate_id": "st-2", "text": "b"}]
    path = _write_jsonl(tmp_path / "pools.jsonl", [_build_a_row("quad-1", candidates, "cl-a")])
    with pytest.raises(ValueError, match="task unavailable"):
        ss.load_pools(path)
    rows = _states("quad-1", "cl-a", ["st-1"], "one") + _states("quad-1", "cl-a", ["st-2"], "two")
    with pytest.raises(ValueError, match="disagree"):
        ss.load_pools(path, states_path=_write_jsonl(tmp_path / "states.jsonl", rows))
    other_quad = _states("quad-9", "cl-a", ["st-1", "st-2"], "one")
    with pytest.raises(ValueError, match="another quad"):
        ss.load_pools(path, states_path=_write_jsonl(tmp_path / "s2.jsonl", other_quad))
    row = {**_build_a_row("quad-1", candidates, "cl-a"), "task": "t"}
    with pytest.raises(ValueError, match="duplicate pool_id"):
        ss.load_pools(_write_jsonl(tmp_path / "dup.jsonl", [row, row]))


def test_pool_record_round_trip_verifies_frozen_and_graded_digests(tmp_path: Path) -> None:
    pool = _pool(
        "nat-1",
        {"t-0": 2, "t-1": 1},
        kind="natural",
        full_grade=2,
        cluster_id="cl-n",
        provenance={"case_id": "c"},
    )
    record = ss.pool_record(pool)
    assert ss.load_pools(_write_jsonl(tmp_path / "p.jsonl", [record])) == [pool]
    record["candidates"][0]["text"] = "changed"
    with pytest.raises(ValueError, match="frozen_pool_sha256"):
        ss.load_pools(_write_jsonl(tmp_path / "q.jsonl", [record]))
    rescored = ss.pool_record(pool)
    rescored["candidates"][0]["grade"] = 0
    with pytest.raises(ValueError, match="graded_pool_sha256"):
        ss.load_pools(_write_jsonl(tmp_path / "r.jsonl", [rescored]))


def test_frozen_digest_is_grade_free_and_graded_digest_is_not() -> None:
    sealed = _pool("pool-d", {"a": None, "b": None})
    graded = _pool("pool-d", {"a": 3, "b": 0})
    assert ss.frozen_pool_sha256(sealed) == ss.frozen_pool_sha256(graded)
    assert ss.graded_pool_sha256(sealed) is None
    assert ss.graded_pool_sha256(graded) != ss.graded_pool_sha256(_pool("pool-d", {"a": 0, "b": 3}))


# ---------------------------------------------------------------------------
# Natural pools
# ---------------------------------------------------------------------------

_ORDERS = {"A-104": "shipped", "B-209": "delivered"}


def _case() -> dict[str, Any]:
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
    return {"id": "nat-case", "profile": "inbox", "items": items, "request": inbox_request(items)}


def _answers(case: dict[str, Any], *, wrong_second: bool = False) -> str:
    items = [{"id": item["id"], **item["expected_answer"]} for item in case["items"]]
    if wrong_second:
        items[1] = {**items[1], "status": "cancelled", "disposition": "answered"}
    return json.dumps({"items": items})


def test_natural_grade_equals_existing_inbox_oracle_item_matches() -> None:
    case = _case()
    full = json.loads(_answers(case))
    texts = [
        _answers(case),
        _answers(case, wrong_second=True),
        "The inbox is resolved.",
        "[]",
        json.dumps({"items": "none"}),
        json.dumps({"items": full["items"], "note": "extra top-level key"}),
        json.dumps({"items": [{**full["items"][0], "extra": 1}, full["items"][1]]}),
        json.dumps({"items": [full["items"][0], full["items"][0]]}),
        json.dumps({"items": [full["items"][1], full["items"][0]]}),
    ]
    for text in texts:
        oracle = _inbox_oracle(case, text, [], HandoffReceipt(arm="a0"), arm="a0")
        assert ss.natural_grade(case, text) == sum(
            item["answer_matches"] for item in oracle["items"]
        )
    assert [ss.natural_grade(case, text) for text in texts[:3]] == [2, 1, 0]


def _payload(task: str, outputs: list[str | None]) -> dict[str, Any]:
    rows = [
        {
            "task_id": f"delegate_0123456789ab_{index}",
            "description": lensed_description(task, index),
            "success": output is not None,
            "output": {"text": output} if output is not None else {},
            "duration_ms": 1.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "usd_spent": 0.0,
        }
        for index, output in enumerate(outputs)
    ]
    best_of = {"n": len(rows), "judged": 3, "winner_task_id": rows[0]["task_id"], "reason": "r"}
    return {"tasks": rows, "total": len(rows), "succeeded": 3, "best_of": best_of}


def test_freeze_natural_pool_grades_successful_candidates_in_dispatch_order() -> None:
    case, task = _case(), "Resolve the inbox."
    outputs = [_answers(case, wrong_second=True), None, _answers(case), "Unfinished."]
    pool = ss.freeze_natural_pool(
        pool_id="nat-1", task=task, case=case, orders=_ORDERS, payload=_payload(task, outputs)
    )
    assert pool.kind == "natural" and pool.full_grade == 2 and pool.task == task
    assert [c.candidate_id for c in pool.candidates] == [
        "delegate_0123456789ab_0",
        "delegate_0123456789ab_2",
        "delegate_0123456789ab_3",
    ]
    assert [c.grade for c in pool.candidates] == [1, 2, 0]
    assert pool.provenance["n_dispatched"] == 4 and pool.provenance["n_successful"] == 3
    assert pool.provenance["complete"] is False
    assert pool.provenance["generation_winner_task_id"] == "delegate_0123456789ab_0"
    assert pool.provenance["case_sha256"] == _digest(case)


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("task", "has another task"),
        ("batch", "not one best_of"),
        ("one_success", "2..4 candidates"),
        ("label", "contradicts"),
        ("long", "at most 2000"),
    ],
)
def test_freeze_natural_pool_fails_closed(fault: str, message: str) -> None:
    case, task = _case(), "Resolve the inbox."
    outputs: list[str | None] = [_answers(case), _answers(case, wrong_second=True)]
    payload = _payload(task, outputs)
    if fault == "task":
        payload["tasks"][1]["description"] = lensed_description("Another task.", 1)
    elif fault == "batch":
        del payload["best_of"]
    elif fault == "one_success":
        payload = _payload(task, [_answers(case), None])
    elif fault == "label":
        case["items"][0]["expected_answer"]["status"] = "delivered"
    else:
        payload["tasks"][1]["output"] = {"text": "x" * 2001}
    with pytest.raises(ValueError, match=message):
        ss.freeze_natural_pool(
            pool_id="nat-1", task=task, case=case, orders=_ORDERS, payload=payload
        )


# ---------------------------------------------------------------------------
# Dispatch through the real judge boundary (fakes only)
# ---------------------------------------------------------------------------


def test_dispatch_calls_each_selector_once_per_order_and_records_no_grades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = [
        _pool("pool-1", {"a": 0, "b": 3, "c": 2, "d": 0}, cluster_id="cl-1"),
        _pool("pool-2", {"e": 2, "f": 0}, cluster_id="cl-1"),
    ]
    run = _dispatch(monkeypatch, pools, _quality(pools))
    expected = len(pools) * 3 * len(ss.ORDERS)
    assert len(run.subscription.requests) + len(run.jev_bodies) == expected
    assert run.events["llm_call_started"] == run.events["llm_call_ended"] == expected
    assert '"grade' not in json.dumps(run.records)
    record = run.records[0]
    assert record["frozen_pool_sha256"] == ss.frozen_pool_sha256(pools[0])
    assert record["public_pool_sha256"] == ss.public_pool_sha256(pools[0])
    assert record["cluster_id"] == "cl-1"
    for name, entry in record["selectors"].items():
        orders = entry["orders"]
        assert orders["forward"]["candidate_ids"] == ["a", "b", "c", "d"]
        assert orders["reverse"]["candidate_ids"] == ["d", "c", "b", "a"]
        assert all(result["valid"] and result["selector_calls"] == 1 for result in orders.values())
        if name != "listwise":
            receipt = orders["reverse"]["receipt"]
            assert receipt["accepted"] and receipt["tie_rule"] == TIE_RULE_CANDIDATE_ID
            assert receipt["pool_id"] == "pool-1"
            assert receipt["candidate_ids"] == ["d", "c", "b", "a"]
            assert orders["reverse"]["scores"] == {"d": 0.0, "c": 2.0, "b": 3.0, "a": 0.0}
    jev_forward = record["selectors"]["jev"]["orders"]["forward"]
    assert jev_forward["expectation_deviation"] == 0.0
    # Candidate ids and pool ids never reach a model-facing payload.
    sent = json.dumps(run.jev_bodies) + json.dumps(
        [str(request.messages) for request in run.subscription.requests]
    )
    assert "pool-1" not in sent and "cl-1" not in sent


def test_preflight_fails_before_any_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    unsafe = ss.FrozenPool(
        "pool-u",
        "task",
        (ss.PoolCandidate("a", "contains apikey_12345 material"), ss.PoolCandidate("b", "clean")),
    )
    with pytest.raises(ValueError, match="failed preflight"):
        _dispatch(monkeypatch, [unsafe], {})
    monkeypatch.setattr(settings, "llm_max_retries", 3)
    with pytest.raises(ValueError, match="llm_max_retries=1"):
        asyncio.run(ss.dispatch_selection([_pool("pool-1", {"a": 1, "b": 0})], []))
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "judgment_engine", "jev")
    with pytest.raises(ValueError, match="global Jev"):
        asyncio.run(ss.dispatch_selection([_pool("pool-1", {"a": 1, "b": 0})], []))
    monkeypatch.setattr(settings, "judgment_engine", "llm")
    twin = [_Scripted("same", "listwise", {}), _Scripted("same", "listwise", {})]
    with pytest.raises(ValueError, match="unique safe identifiers"):
        asyncio.run(ss.dispatch_selection([_pool("pool-1", {"a": 1, "b": 0})], twin))
    assert all(not selector.calls for selector in twin)


def test_invalid_order_counts_wrong_without_shrinking_the_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = [
        _pool("pool-1", {"a": 0, "b": 3, "c": 2, "d": 0}),
        _pool("pool-2", {"e": 3, "f": 0, "g": 1}),
    ]
    broken = frozenset({pools[1].candidates[-1].text})  # pool-2 reverse order only
    run = _dispatch(monkeypatch, pools, _quality(pools), jev_broken_first=broken)
    reverse = run.records[1]["selectors"]["jev"]["orders"]["reverse"]
    assert not reverse["valid"] and reverse["failure"] == "judge_error"
    assert reverse["judge_error"] and reverse["winner_id"] is None and reverse["scores"] is None
    assert reverse["receipt"]["accepted"] is False
    outcomes = ss.score_selection(run.records, pools)
    jev = outcomes[1]["selectors"]["jev"]
    assert not jev["valid"] and jev["invalid_orders"] == ["reverse"]
    assert jev["oracle_best_value"] == 0.0 and jev["correct"] is False and jev["regret"] is None
    assert jev["selected_acceptable_value"] == 0.0
    summary = ss.summarize_outcomes(outcomes, deltas=[("delta", "astra", "jev")])
    assert summary["selectors"]["jev"]["oracle_best_selection"] == {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
    }
    assert summary["selectors"]["jev"]["invalid_pools"] == 1
    assert summary["selectors"]["jev"]["regret_valid_mean"]["denominator"] == 1
    assert summary["paired_deltas"]["delta"]["value"] == -0.5
    assert summary["valid_selections"] == {"numerator": 11, "denominator": 12, "value": 11 / 12}


def test_final_selection_is_invariant_to_candidate_permutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _pool("perm-pool", {"a": 3, "b": 3, "c": 1, "d": 0})
    quality = _quality([base])  # a and b tie exactly in both orders
    expected = min(("a", "b"), key=lambda cid: _tie_key("perm-pool", cid))
    for permutation in itertools.permutations(base.candidates):
        pool = replace(base, candidates=permutation)
        run = _dispatch(monkeypatch, [pool], quality, names=("astra", "jev"))
        outcome = ss.score_selection(run.records, [pool])[0]
        for name in ("astra", "jev"):
            assert outcome["selectors"][name]["selected_id"] == expected
            assert outcome["selectors"][name]["tie_break_applied"] is True


def test_listwise_reference_averages_order_hits_and_invalid_orders_add_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = [
        _pool("pool-first", {"a": 3, "b": 0, "c": 0}),
        _pool("pool-middle", {"d": 0, "e": 3, "f": 0}),
        _pool("pool-fail", {"g": 3, "h": 0}),
    ]
    fail_text = pools[2].candidates[-1].text

    def pick(texts: list[str]) -> int:
        return 7 if texts[0] == fail_text else 0  # out of range -> judge_error fallback

    run = _dispatch(monkeypatch, pools, _quality(pools), names=("listwise",), pick=pick)
    outcomes = ss.score_selection(run.records, pools)
    values = [outcome["selectors"]["listwise"] for outcome in outcomes]
    assert [value["oracle_best_value"] for value in values] == [0.5, 0.0, 0.5]
    assert values[0]["order_hits"] == {"forward": 1, "reverse": 0}
    assert values[2]["valid"] is False and values[2]["invalid_orders"] == ["reverse"]
    assert values[2]["regret"] is None and values[2]["order_consistent"] is None
    summary = ss.summarize_outcomes(outcomes)["selectors"]["listwise"]
    assert summary["listwise_mean"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}


def test_judge_error_fallback_is_wrong_even_when_the_fallback_is_acceptable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texts = [f"Answer {index}. Evidence: observation {index}." for index in range(3)]
    fallback = min(texts, key=candidate_sampling.candidate_content_key)
    # The content-addressed fallback candidate is the only acceptable one (grade 3).
    pool = ss.FrozenPool(
        "pool-fb",
        "Resolve the synthetic task.",
        tuple(
            ss.PoolCandidate(f"c{index}", text, 3 if text == fallback else 0)
            for index, text in enumerate(texts)
        ),
    )
    forward_first = pool.candidates[0].text
    run = _dispatch(
        monkeypatch,
        [pool],
        _quality([pool]),
        names=("jev",),
        jev_broken_first=frozenset({forward_first}),
    )
    order = run.records[0]["selectors"]["jev"]["orders"]["forward"]
    assert order["judge_error"] and order["valid"] is False and order["winner_id"] is None
    outcome = ss.score_selection(run.records, [pool])[0]["selectors"]["jev"]
    assert outcome["valid"] is False and outcome["selected_id"] is None
    assert outcome["oracle_best_value"] == 0.0 and outcome["selected_acceptable_value"] == 0.0
    summary = ss.summarize_outcomes(ss.score_selection(run.records, [pool]))
    acceptance = summary["acceptance"]["controlled"]
    assert acceptance["selectors"]["jev"]["selected_success"]["numerator"] == 0
    assert acceptance["selectors"]["jev"]["gap_closed"]["value"] < 0


def _tolerance_run(
    monkeypatch: pytest.MonkeyPatch, pool: ss.FrozenPool, **tolerances: float
) -> list[dict[str, Any]]:
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    # The judge boundary resolves its default route first; the matched adapter replaces it.
    subscription = _Subscription({})
    monkeypatch.setattr(candidate_sampling, "resolve_for", lambda *_args: subscription)

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        answers = {}
        for key, text in body["state"]["candidates"].items():
            answer = _score_answer(float(text.endswith("3.")) * 3)
            # Provider rounding drift of 0.02 from the probability-weighted level.
            drift = -0.02 if answer["score"] >= 3 else 0.02
            answer["score"] = round(answer["score"] + drift, 6)
            answers[key] = answer
        return httpx.Response(
            200,
            json={"model": JEV_MODEL, "usage": {"input_tokens": 7}, "answers": answers},
            headers={"x-typesafe-request-id": "synthetic"},
        )

    async def run() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            jev = SystemOneAdapter("typesafe", SecretStr("synthetic-key"), client=client)
            selector = ss.PointwiseSelector("jev", "jev", jev, **tolerances)
            return await ss.dispatch_selection([pool], [selector])

    return asyncio.run(run())


def test_jev_score_tolerance_reuses_the_v1_parser_bound_and_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ss.FrozenPool(
        "pool-tol",
        "Resolve the synthetic task.",
        (
            ss.PoolCandidate("t0", "Candidate grade 3.", 3),
            ss.PoolCandidate("t1", "Candidate grade 0.", 0),
        ),
    )
    strict = _tolerance_run(monkeypatch, pool)[0]["selectors"]["jev"]
    assert strict["tolerances"] == {"sum_tolerance": 1e-05, "score_tolerance": 1e-05}
    for order in strict["orders"].values():
        assert not order["valid"] and order["failure"] == "judge_error"
        assert order["receipt"]["accepted"] is False
        assert order["receipt"]["error_type"] == "invalid_candidate_scores"
    assert strict["orders"]["forward"]["expectation_deviation"] == pytest.approx(0.02)
    frozen = _tolerance_run(monkeypatch, pool, sum_tolerance=0.025, score_tolerance=0.03)
    entry = frozen[0]["selectors"]["jev"]
    assert entry["tolerances"] == {"sum_tolerance": 0.025, "score_tolerance": 0.03}
    for order in entry["orders"].values():
        receipt = order["receipt"]
        assert order["valid"] and receipt["accepted"] is True
        assert receipt["score_tolerance"] == 0.03 and receipt["sum_tolerance"] == 0.025
        assert receipt["strict_admitted"] is False  # the strict 1e-5 class is kept beside it
        assert receipt["usage"] == {"input_tokens": 7, "output_tokens": None}
    summary = ss.summarize_outcomes(ss.score_selection(frozen, [pool]))["selectors"]["jev"]
    assert summary["score_expectation"]["tolerance"] == 0.03
    assert summary["selection_cost"] == {
        "calls": 2,
        "input_tokens_observed_sum": 14,
        "input_tokens_missing_calls": 0,
        "input_tokens_total": 14,
        "output_tokens_observed_sum": 0,
        "output_tokens_missing_calls": 2,
        "output_tokens_total": None,
    }
    with pytest.raises(ValueError, match="failed preflight"):
        _tolerance_run(monkeypatch, pool, score_tolerance=0.2)


def test_selection_cost_counts_every_order_and_keeps_unknown_usage_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = [_pool("pool-1", {"a": 0, "b": 3}), _pool("pool-2", {"c": 3, "d": 0})]
    run = _dispatch(monkeypatch, pools, _quality(pools))
    summary = ss.summarize_outcomes(ss.score_selection(run.records, pools))["selectors"]
    assert summary["astra"]["selection_cost"]["input_tokens_total"] == 10 * 4
    assert summary["jev"]["selection_cost"]["input_tokens_total"] == 50 * 4
    listwise = summary["listwise"]["selection_cost"]
    assert listwise["calls"] == 4 and listwise["input_tokens_total"] is None
    assert listwise["input_tokens_missing_calls"] == 4


# ---------------------------------------------------------------------------
# Scoring phase: sealed pools, alias unseal, hand-computed metrics
# ---------------------------------------------------------------------------


def test_sealed_pools_dispatch_ungraded_and_score_through_the_alias_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = _pool("q-77", {"s-01": None, "s-02": None, "s-03": None}, cluster_id="cl-t")
    originals = {
        "q-77": "cl-t--quad1",
        "s-01": "cl-t--c00",
        "s-02": "cl-t--c01",
        "s-03": "cl-t--c10",
    }
    graded = {
        "cl-t--quad1": ss.GradedPool(
            "cl-t--quad1",
            {originals[c.candidate_id]: c.text for c in public.candidates},
            {"cl-t--c00": 3, "cl-t--c01": 3, "cl-t--c10": 0},
            "cl-t",
        )
    }
    tie = {"s-01": 2, "s-02": 2, "s-03": 0}
    script = {("q-77", order): tie for order in ss.ORDERS}
    records = _scripted_dispatch(monkeypatch, [public], [_Scripted("astra", "pointwise", script)])
    with pytest.raises(ValueError, match="sealed"):
        ss.score_selection(records, [public])
    outcome = ss.score_selection(records, [public], graded=graded, aliases=originals)[0]
    assert outcome["cluster_id"] == "cl-t" and outcome["graded_pool_id"] == "cl-t--quad1"
    assert outcome["grades"] == {"s-01": 3, "s-02": 3, "s-03": 0}
    # Tie keys use the dispatched (alias) ids, never the unsealed originals.
    expected = min(("s-01", "s-02"), key=lambda cid: _tie_key("q-77", cid))
    assert outcome["selectors"]["astra"]["selected_id"] == expected
    tampered = {
        key: replace(value, texts={**value.texts, "cl-t--c00": "changed"})
        for key, value in graded.items()
    }
    with pytest.raises(ValueError, match="differ from the dispatched pool"):
        ss.score_selection(records, [public], graded=tampered, aliases=originals)
    with pytest.raises(ValueError, match="no graded pool"):
        ss.score_selection(records, [public], graded=graded)
    with pytest.raises(ValueError, match="every planned pool"):
        ss.score_selection(records, [public, _pool("q-78", {"x": None, "y": None})])


def test_hand_computed_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    pools = [
        _pool("p1", {"a": 0, "b": 3, "c": 2, "d": 0}),
        _pool("p2", {"e": 2, "f": 2, "g": 0}),
        _pool("n1", {"n0": 1, "n1": 2, "n2": 0}, kind="natural", full_grade=2),
    ]
    astra = _Scripted(
        "astra",
        "pointwise",
        {
            ("p1", "forward"): {"a": 0, "b": 3, "c": 2, "d": 0},
            ("p1", "reverse"): {"a": 0, "b": 2.5, "c": 2, "d": 1},
            ("p2", "forward"): None,
            ("p2", "reverse"): {"e": 1, "f": 1, "g": 0},
            ("n1", "forward"): {"n0": 2, "n1": 3, "n2": 0},
            ("n1", "reverse"): {"n0": 2.5, "n1": 3, "n2": 0},
        },
        engine="llm",
    )
    jev = _Scripted(
        "jev",
        "pointwise",
        {
            ("p1", "forward"): {"a": 3, "b": 2, "c": 1, "d": 0},
            ("p1", "reverse"): {"a": 0, "b": 3, "c": 1, "d": 3},
            ("p2", "forward"): {"e": 1, "f": 1, "g": 0},
            ("p2", "reverse"): {"e": 1, "f": 1, "g": 0},
            ("n1", "forward"): {"n0": 3, "n1": 2, "n2": 0},
            ("n1", "reverse"): {"n0": 2.5, "n1": 2, "n2": 0.5},
        },
        engine="jev",
    )
    listwise = _Scripted(
        "listwise",
        "listwise",
        {
            ("p1", "forward"): "a",
            ("p1", "reverse"): "b",
            ("p2", "forward"): "e",
            ("p2", "reverse"): "g",
            ("n1", "forward"): "n0",
            ("n1", "reverse"): "n1",
        },
    )
    records = _scripted_dispatch(monkeypatch, pools, [astra, jev, listwise])
    assert len(astra.calls) == len(jev.calls) == len(listwise.calls) == 6
    outcomes = ss.score_selection(records, pools)
    by_pool = {outcome["pool_id"]: outcome["selectors"] for outcome in outcomes}
    assert by_pool["p1"]["astra"]["mean_scores"] == {"a": 0.0, "b": 2.75, "c": 2.0, "d": 0.5}
    assert by_pool["p1"]["astra"]["rank_agreement_tau_b"] == pytest.approx(5 / math.sqrt(30))
    assert (
        by_pool["p1"]["jev"]["selected_id"] == "b" and not by_pool["p1"]["jev"]["order_consistent"]
    )
    assert by_pool["p2"]["jev"]["tie_break_applied"] is True
    assert by_pool["p2"]["jev"]["selected_id"] == min("ef", key=lambda cid: _tie_key("p2", cid))
    assert by_pool["n1"]["jev"]["regret"] == 1 and by_pool["n1"]["listwise"]["regret"] == 0.5
    summary = ss.summarize_outcomes(outcomes, deltas=[("score_ctl_top1_delta", "astra", "jev")])
    assert json.dumps(summary, allow_nan=False)

    def ratio(numerator: float, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
        }

    selectors = summary["selectors"]
    assert selectors["astra"]["oracle_best_selection"] == ratio(2, 3)
    assert selectors["astra"]["invalid_pools"] == 1
    assert selectors["astra"]["invalid_orders"] == {"forward": 1, "reverse": 0}
    assert selectors["astra"]["regret_valid_mean"] == ratio(0, 2)
    assert selectors["astra"]["order_consistency"] == ratio(2, 2)
    assert selectors["astra"]["rank_agreement_tau_b"]["defined_pools"] == 2
    assert selectors["jev"]["oracle_best_selection"] == ratio(2, 3)
    assert selectors["jev"]["regret_valid_mean"]["value"] == pytest.approx(1 / 3)
    assert selectors["jev"]["order_consistency"] == ratio(2, 3)
    assert selectors["jev"]["tie_breaks_applied"] == 1
    assert selectors["listwise"]["oracle_best_selection"] == ratio(1.5, 3)
    assert selectors["listwise"]["regret_valid_mean"] == ratio(3, 3)
    assert selectors["listwise"]["order_consistency"] == ratio(0, 3)
    delta = summary["paired_deltas"]["score_ctl_top1_delta"]
    assert (delta["numerator"], delta["denominator"], delta["value"]) == (0, 3, 0.0)
    assert (delta["comparison_better"], delta["baseline_better"], delta["equal"]) == (1, 1, 1)
    baselines = summary["oracle_best_baselines"]
    assert baselines["first_candidate"] == ratio(1, 3)
    assert baselines["random"]["value"] == pytest.approx((1 / 4 + 2 / 3 + 1 / 3) / 3)
    assert summary["non_discriminative"] == ratio(0, 3)
    assert summary["valid_selections"] == ratio(17, 18)
    # 05 v1 §3.2 / 06 §5 names; no IID pass@k label for a width-4 pool.
    assert "pass" not in json.dumps(summary["acceptance"])
    natural = summary["acceptance"]["natural"]
    assert natural["pools"] == 1 and natural["acceptance_rule"].startswith("grade == full_grade")
    assert natural["pool_random_at_1"]["value"] == pytest.approx(1 / 3)
    assert natural["oracle_coverage_at_4"] == {"value": 1.0, "numerator": 1, "denominator": 1}
    assert natural["selectors"]["astra"]["selected_success"]["value"] == 1.0
    assert natural["selectors"]["astra"]["gap_closed"]["value"] == pytest.approx(1.0)
    assert natural["selectors"]["jev"]["gap_closed"]["value"] == pytest.approx(-0.5)
    assert natural["selectors"]["listwise"]["gap_closed"]["value"] == pytest.approx(0.25)
    # Controlled acceptance is the rule-oracle supported candidate (grade 3) only.
    controlled = summary["acceptance"]["controlled"]
    assert controlled["pool_random_at_1"]["value"] == pytest.approx(1 / 8)
    assert controlled["oracle_coverage_at_4"]["value"] == pytest.approx(1 / 2)
    assert controlled["selectors"]["astra"]["selected_success"]["value"] == pytest.approx(1 / 2)
    assert controlled["selectors"]["jev"]["gap_closed"]["value"] == pytest.approx(1.0)
    assert controlled["selectors"]["listwise"]["gap_closed"]["value"] == pytest.approx(1 / 3)


def test_non_discriminative_pool_and_undefined_gap_are_null_not_nan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flat = _pool("flat", {"a": 2, "b": 2}, kind="natural", full_grade=2)
    script = {("flat", order): {"a": 1, "b": 1} for order in ss.ORDERS}
    records = _scripted_dispatch(monkeypatch, [flat], [_Scripted("astra", "pointwise", script)])
    summary = ss.summarize_outcomes(ss.score_selection(records, [flat]))
    assert summary["non_discriminative"]["value"] == 1.0
    gap = summary["acceptance"]["natural"]["selectors"]["astra"]["gap_closed"]
    assert gap == {"value": "not-measurable", "numerator": None, "denominator": None}
    assert summary["selectors"]["astra"]["rank_agreement_tau_b"]["mean"] is None
    json.dumps(summary, allow_nan=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_score_and_summarize_cli_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    public_candidates = [
        {"candidate_id": "s-1", "text": "Answer: one"},
        {"candidate_id": "s-2", "text": "Answer: two"},
    ]
    graded_candidates = [
        {"candidate_id": "orig-1", "text": "Answer: one", "grade": 0},
        {"candidate_id": "orig-2", "text": "Answer: two", "grade": 3},
    ]
    pools_path = _write_jsonl(
        tmp_path / "pools.jsonl", [_build_a_row("q-1", public_candidates, "cl-z")]
    )
    states_path = _write_jsonl(
        tmp_path / "states.jsonl", _states("q-1", "cl-z", ["s-1", "s-2"], "t")
    )
    graded_path = _write_jsonl(
        tmp_path / "graded.jsonl", [_build_a_row("orig-q", graded_candidates, "cl-z")]
    )
    aliases_path = tmp_path / "aliases.json"
    aliases_path.write_text(json.dumps({"q-1": "orig-q", "s-1": "orig-1", "s-2": "orig-2"}))
    pools = ss.load_pools(pools_path, states_path=states_path)
    script_a = {("q-1", order): {"s-1": 1, "s-2": 2} for order in ss.ORDERS}
    script_b = {("q-1", order): {"s-1": 2, "s-2": 1} for order in ss.ORDERS}
    records = _scripted_dispatch(
        monkeypatch,
        pools,
        [_Scripted("a", "pointwise", script_a), _Scripted("b", "pointwise", script_b)],
    )
    records_path = _write_jsonl(tmp_path / "records.jsonl", records)
    assert (
        ss.main(
            [
                "score",
                str(records_path),
                str(pools_path),
                "--states",
                str(states_path),
                "--graded",
                str(graded_path),
                "--aliases",
                str(aliases_path),
            ]
        )
        == 0
    )
    outcomes_path = tmp_path / "outcomes.jsonl"
    outcomes_path.write_text(capsys.readouterr().out)
    assert ss.main(["summarize", str(outcomes_path), "--delta", "d=a:b"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["selectors"]["a"]["oracle_best_selection"]["value"] == 1.0
    assert summary["selectors"]["b"]["oracle_best_selection"]["value"] == 0.0
    assert summary["paired_deltas"]["d"]["value"] == -1.0


def test_self_test_cli_runs_both_orders_offline(capsys: pytest.CaptureFixture[str]) -> None:
    retries = settings.llm_max_retries
    assert ss.main(["self-test"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is True and report["model_dispatches"] == 0
    assert all(report["checks"].values())
    total = sum(report["fake_dispatches"].values())
    assert report["observed_llm_calls"] == {"started": total, "ended": total}
    assert settings.llm_max_retries == retries


def test_module_entrypoint_self_test() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and module arguments
        [sys.executable, "-m", "evals.benchmarks.score_selection", "self-test"],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert json.loads(completed.stdout)["model_dispatches"] == 0


class _Interleaving(_Subscription):
    """Yields inside every call so concurrent pools really interleave; tracks the peak."""

    in_flight = 0
    peak = 0

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        type(self).in_flight += 1
        type(self).peak = max(type(self).peak, type(self).in_flight)
        try:
            await asyncio.sleep(0.001)
            return await super().acomplete(request)
        finally:
            type(self).in_flight -= 1


def test_concurrent_dispatch_is_byte_identical_to_sequential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = [
        _pool(f"pool-{index}", {f"{index}a": 0, f"{index}b": 3, f"{index}c": 2, f"{index}d": 0})
        for index in range(6)
    ]
    quality = _quality(pools)
    broken = frozenset({pools[2].candidates[-1].text})  # one reverse Jev order is invalid

    def pick(texts: list[str]) -> int:
        return 9 if texts[0] == pools[4].candidates[0].text else 0  # a listwise judge_error

    runs = {}
    for concurrency in (1, 4):
        _Interleaving.in_flight = _Interleaving.peak = 0
        timings: list[dict[str, Any]] = []
        runs[concurrency] = _dispatch(
            monkeypatch,
            pools,
            quality,
            pick=pick,
            jev_broken_first=broken,
            max_concurrency=concurrency,
            subscription_type=_Interleaving,
            timings=timings,
        )
        assert len(timings) == len(pools) * 3 * len(ss.ORDERS)
        assert all(row["latency_s"] >= 0 for row in timings)
        if concurrency == 1:
            assert _Interleaving.peak == 1
        else:
            assert 1 < _Interleaving.peak <= 4
    sequential, concurrent = (json.dumps(runs[n].records, sort_keys=True) for n in (1, 4))
    assert sequential == concurrent
    assert [record["pool_id"] for record in runs[4].records] == [pool.pool_id for pool in pools]
    outcomes = [ss.score_selection(runs[n].records, pools) for n in (1, 4)]
    assert json.dumps(outcomes[0], sort_keys=True) == json.dumps(outcomes[1], sort_keys=True)
    summaries = [ss.summarize_outcomes(outcome) for outcome in outcomes]
    assert json.dumps(summaries[0], sort_keys=True) == json.dumps(summaries[1], sort_keys=True)
    receipt = runs[4].records[2]["selectors"]["jev"]["orders"]["reverse"]["receipt"]
    assert receipt["correlation"]["llm_call_id"] == "score.jev.pool-2.reverse"
    with pytest.raises(ValueError, match=r"concurrency is 1\.\.4"):
        asyncio.run(ss.dispatch_selection(pools, [], max_concurrency=5))


class _Hanging(_Subscription):
    """The next ``hangs[text]`` calls showing ``text`` first never answer, or raise ``error``."""

    hangs: Counter[str] = Counter()
    seen: list[str] = []
    error: Exception | None = None

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        content = request.messages[0].content
        assert isinstance(content, str)
        if request.tools:
            first = _listwise_texts(content)[0]
        else:
            payload = json.loads(
                unescape(content.removeprefix("<scoring_input>").removesuffix("</scoring_input>"))
            )
            first = payload["state"]["candidates"]["c0"]
        type(self).seen.append(first)
        if type(self).hangs[first] > 0:
            type(self).hangs[first] -= 1
            if type(self).error is not None:
                raise type(self).error
            await asyncio.sleep(3600)
        return await super().acomplete(request)


_FAST = {"llm": 0.5, "jev": 30.0}


def _two_candidate_pools(count: int) -> list[ss.FrozenPool]:
    return [_pool(f"pool-{index}", {f"{index}a": 0, f"{index}b": 3}) for index in range(count)]


def _shown(pools: list[ss.FrozenPool], index: int, order: str) -> str:
    return pools[index].candidates[ss.order_indices(pools[index], order)[0]].text


def _hang(
    pools: list[ss.FrozenPool], index: int, order: str, times: int, error: Exception | None = None
) -> None:
    _Hanging.hangs, _Hanging.seen = Counter({_shown(pools, index, order): times}), []
    _Hanging.error = error


def test_timed_out_call_is_replaced_once_and_records_stay_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = _two_candidate_pools(25)  # 50 planned calls: one replacement is exactly 2%
    runs = {}
    for concurrency in (1, 4):
        _hang(pools, 3, "forward", 1)
        timings: list[dict[str, Any]] = []
        runs[concurrency] = _dispatch(
            monkeypatch,
            pools,
            _quality(pools),
            names=("astra",),
            max_concurrency=concurrency,
            subscription_type=_Hanging,
            timings=timings,
            timeouts=_FAST,
        )
        assert len(timings) == 51 and [row["attempt"] for row in timings].count(1) == 1
    assert json.dumps(runs[1].records, sort_keys=True) == json.dumps(
        runs[4].records, sort_keys=True
    )
    orders = [record["selectors"]["astra"]["orders"] for record in runs[4].records]
    assert orders[3]["forward"]["valid"] is True
    assert orders[3]["forward"]["replaced_attempts"] == [
        {
            "failure": "transport_error",
            "error_type": "TimeoutError",
            "timeout_s": 0.5,
            "selected_for_analysis": False,
        }
    ]
    assert sum(len(entry["replaced_attempts"]) for pair in orders for entry in pair.values()) == 1
    summary = ss.summarize_outcomes(ss.score_selection(runs[4].records, pools))
    assert summary["selector_calls"] == 50  # a replacement fills the same item
    cost = summary["selectors"]["astra"]["selection_cost"]
    assert (cost["calls"], cost["input_tokens_missing_calls"]) == (51, 1)
    assert cost["input_tokens_total"] is None  # the timed-out call's usage is unknown


@pytest.mark.parametrize(
    ("count", "index", "order", "times", "reason", "dispatched", "error", "cause"),
    [
        # The replacement times out too: it stays selected on the last planned call.
        (25, 24, "reverse", 2, "replacement_failed", 51, "primary is not measurable", None),
        # A refused connection twice is the same no-response failure (coordinator decision).
        (
            25,
            24,
            "reverse",
            2,
            "replacement_failed",
            51,
            "primary is not measurable",
            httpx.ConnectError("refused"),
        ),
        # One replacement in 4 planned calls is above 2%: no replacement, nothing new starts.
        (2, 0, "forward", 1, "substitution_rate_exceeded", 1, "cover every planned pool", None),
    ],
)
def test_failed_replacement_or_replacement_rate_stops_the_unit(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    index: int,
    order: str,
    times: int,
    reason: str,
    dispatched: int,
    error: str,
    cause: Exception | None,
) -> None:
    pools = _two_candidate_pools(count)
    _hang(pools, index, order, times, cause)
    with pytest.raises(ss.SelectionStoppedError, match="primary is not measurable") as stopped:
        _dispatch(
            monkeypatch,
            pools,
            _quality(pools),
            names=("astra",),
            subscription_type=_Hanging,
            timeouts=_FAST,
        )
    assert stopped.value.reason == reason
    assert len(_Hanging.seen) == dispatched
    failed = stopped.value.records[-1]["selectors"]["astra"]["orders"][order]
    assert (failed["valid"], failed["failure"], failed["winner_id"]) == (
        False,
        "transport_error",
        None,
    )
    assert len(failed["replaced_attempts"]) == times - 1
    kind = type(cause).__name__ if cause else "TimeoutError"
    assert failed["reason"] == f"no response: {kind}"
    with pytest.raises(ValueError, match=error):
        ss.score_selection(stopped.value.records, pools)


@pytest.mark.parametrize(
    ("names", "cause", "kind"),
    [
        (("listwise",), httpx.ConnectError("refused"), "ConnectError"),
        (
            ("astra",),
            openai.APIConnectionError(request=httpx.Request("POST", "https://codex.invalid")),
            "APIConnectionError",
        ),
        (("jev",), None, "HTTPStatusError"),  # the Jev endpoint answers 503
    ],
)
def test_a_call_without_a_response_is_replaced_once_like_a_timeout(
    monkeypatch: pytest.MonkeyPatch, names: tuple[str], cause: Exception | None, kind: str
) -> None:
    pools = _two_candidate_pools(25)  # 50 planned calls: one replacement is exactly 2%
    _hang(pools, 3, "forward", 1 if cause else 0, cause)
    run = _dispatch(
        monkeypatch,
        pools,
        _quality(pools),
        names=names,
        subscription_type=_Hanging,
        timeouts=_FAST,
        jev_failures=None if cause else Counter({_shown(pools, 3, "forward"): 1}),
    )
    orders = [record["selectors"][names[0]]["orders"] for record in run.records]
    assert orders[3]["forward"]["valid"] is True
    assert orders[3]["forward"]["replaced_attempts"] == [
        {
            "failure": "transport_error",
            "error_type": kind,
            "timeout_s": _FAST["jev" if names == ("jev",) else "llm"],
            "selected_for_analysis": False,
        }
    ]
    assert sum(len(entry["replaced_attempts"]) for pair in orders for entry in pair.values()) == 1


def test_a_response_that_breaks_the_contract_is_wrong_and_never_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools = _two_candidate_pools(25)
    shown = _shown(pools, 3, "forward")

    def pick(texts: list[str]) -> int:
        return 9 if texts[0] == shown else 0  # an out-of-range listwise answer

    run = _dispatch(
        monkeypatch,
        pools,
        _quality(pools),
        names=("jev", "listwise"),
        pick=pick,
        jev_broken_first=frozenset({shown}),  # a Jev answer that changes a criterion
        timeouts=_FAST,
    )
    assert len(run.jev_bodies) == len(run.subscription.requests) == 50  # no extra call
    for name in ("jev", "listwise"):
        forward = run.records[3]["selectors"][name]["orders"]["forward"]
        assert (forward["valid"], forward["replaced_attempts"]) == (False, [])
        assert forward["failure"] != "transport_error"
    outcomes = ss.score_selection(run.records, pools)[3]["selectors"]
    assert outcomes["jev"]["valid"] is False and outcomes["jev"]["oracle_best_value"] == 0.0
    assert outcomes["listwise"]["order_hits"]["forward"] == 0


@pytest.mark.parametrize(
    "timeouts",
    [
        {"llm": 180.0},
        {"llm": 0, "jev": 60.0},
        {"llm": float("inf"), "jev": 60.0},
        {"llm": True, "jev": 60.0},
    ],
)
def test_call_timeouts_need_finite_positive_seconds_per_engine(timeouts: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="finite positive seconds"):
        asyncio.run(ss.dispatch_selection([], [], timeouts=timeouts))
