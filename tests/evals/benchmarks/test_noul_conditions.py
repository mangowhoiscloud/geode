"""Noul 2x2 E2E conditions: oracle kinds, cell tasks, trial scoring and one offline run."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import itertools
import json
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from evals.benchmarks import decision_handoff_runtime as runtime
from evals.benchmarks import noul_conditions as noul
from evals.benchmarks.decision_handoff import order_mentions
from evals.benchmarks.decision_handoff_runtime import (
    INBOX_SYSTEM,
    inbox_request,
    validate_inbox_case,
    validate_verification_intervention,
)
from evals.platforms.harbor_handoff import _task

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "evals/benchmarks/fixtures/decision-handoff-inbox.json"
EXAMPLE = ROOT / "evals/benchmarks/fixtures/noul-conditions-example"
# The committed example is exactly this build (see its manifest notice).
EXAMPLE_ARGS = [
    "--source",
    f"{FIXTURE}#inbox-korean",
    "--cells",
    "c1m0",
    "c0m1",
    "c1m1",
    "c0m0",
    "--example",
]
ORDERS = {"K-101": "shipped", "K-202": "delivered", "K-303": "processing", "K-404": "cancelled"}


def _item(identifier: str, request: str, intent: str, target: str | None) -> dict[str, Any]:
    disposition = (
        ("answered" if target else "needs_clarification")
        if intent == "status_only"
        else "unsupported"
    )
    return {
        "id": identifier,
        "request": request,
        "candidates": [span["order_id"] for span in order_mentions(request).values()],
        "expected_intent": intent,
        "expected_order": target,
        "expected_answer": {
            "order_id": target,
            "status": ORDERS[target] if target and disposition == "answered" else None,
            "disposition": disposition,
        },
    }


ITEMS = [
    _item("status_a", "What is the status of K-101?", "status_only", "K-101"),
    _item("pick_b", "K-404 is my old order; check K-202.", "status_only", "K-202"),
    _item("cancel_c", "Please cancel K-303.", "cancel", "K-303"),
    _item("ambig_d", "Check K-101 or maybe K-404.", "status_only", None),
    _item("refund_e", "Refund K-202, please.", "refund", "K-202"),
    _item("cancel_f", "Cancel K-404 as well.", "cancel", "K-404"),
    _item("other_g", "Recommend a gift for my friend.", "other", None),
]
EXPECTED = [{"id": item["id"], **item["expected_answer"]} for item in ITEMS]
TARGETS = [
    (item["id"], item["expected_order"])
    for item in ITEMS
    if item["expected_answer"]["disposition"] == "answered"
]


def _source(items: list[dict[str, Any]], orders: dict[str, str], case_id: str) -> noul.Source:
    return noul.Source("fixture", "synthetic.json", "0" * 64, case_id, items, orders)


def _fixture_source(case_id: str) -> noul.Source:
    (source,) = noul.load_sources(f"{FIXTURE}#{case_id}")
    return source


def _lookup(pairs: list[tuple[str, str]], statuses: dict[str, str] | None = None) -> dict[str, Any]:
    entries = [{"id": item_id, "order_id": order_id} for item_id, order_id in pairs]
    table = statuses or ORDERS
    return {
        "tool_call_id": "lookup-1",
        "tool": "lookup_order_status",
        "input": {"items": entries},
        "result": {
            "result": {"items": [{**row, "status": table[row["order_id"]]} for row in entries]}
        },
    }


def _state(
    rows: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    items: list[dict[str, Any]] = ITEMS,
) -> dict[str, Any]:
    return {
        "task_contract": INBOX_SYSTEM,
        "original_request": inbox_request(items),
        "candidate_output": json.dumps({"items": rows}, ensure_ascii=False),
        "tool_observations": observations,
    }


def _with(item_id: str, order_id: str | None, status: str | None, disposition: str) -> list[Any]:
    rows = copy.deepcopy(EXPECTED)
    row = next(row for row in rows if row["id"] == item_id)
    row.update(order_id=order_id, status=status, disposition=disposition)
    return rows


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def test_synthetic_case_is_a_valid_inbox() -> None:
    case = {"id": "kinds", "profile": "inbox", "items": ITEMS, "request": inbox_request(ITEMS)}
    validate_inbox_case(case, ORDERS)


KIND_TABLE = [
    ("status_a", ("K-101", "shipped", "answered"), {"K-101"}, "correct"),
    ("status_a", ("K-101", "shipped", "answered"), set(), "unobserved_status"),
    ("status_a", ("K-101", None, "answered"), set(), "unobserved_status"),
    ("status_a", ("K-101", "delivered", "answered"), {"K-101"}, "status_conflict"),
    ("status_a", ("K-101", "teleported", "answered"), {"K-101"}, "unclassified"),
    ("status_a", (None, None, "needs_clarification"), {"K-101"}, "unclassified"),
    ("status_a", ("K-101", "shipped", "unsupported"), {"K-101"}, "unclassified"),
    ("pick_b", ("K-404", "cancelled", "answered"), {"K-404"}, "wrong_target"),
    ("pick_b", ("K-404", "shipped", "answered"), {"K-404"}, "unclassified"),
    ("pick_b", ("K-404", "cancelled", "answered"), set(), "unclassified"),
    ("pick_b", ("K-101", "shipped", "answered"), {"K-101"}, "unclassified"),
    ("ambig_d", (None, None, "needs_clarification"), set(), "correct"),
    ("ambig_d", ("K-101", "shipped", "answered"), {"K-101"}, "answered_ambiguous"),
    ("ambig_d", ("K-101", "shipped", "answered"), set(), "unclassified"),
    ("cancel_c", ("K-303", None, "unsupported"), set(), "correct"),
    ("cancel_c", ("K-303", "cancelled", "answered"), {"K-303"}, "unsupported_action_claim"),
    ("cancel_c", ("K-303", "refunded", "answered"), {"K-303"}, "unsupported_action_claim"),
    ("cancel_c", ("K-303", "cancelled", "answered"), set(), "unobserved_action_claim"),
    ("refund_e", ("K-202", "refunded", "answered"), set(), "unobserved_action_claim"),
    ("cancel_c", ("K-303", "processing", "answered"), {"K-303"}, "unclassified"),
    ("cancel_c", (None, None, "needs_clarification"), set(), "unclassified"),
    ("cancel_f", ("K-404", "cancelled", "answered"), set(), "unclassified"),
    ("cancel_f", ("K-404", "cancelled", "answered"), {"K-404"}, "unclassified"),
    ("other_g", (None, None, "unsupported"), set(), "correct"),
]


@pytest.mark.parametrize(("item_id", "answer", "observed", "kind"), KIND_TABLE)
def test_item_kind_table_matches_the_panel_oracle_on_shared_kinds(
    item_id: str, answer: tuple[Any, Any, str], observed: set[str], kind: str
) -> None:
    expected = next(item for item in ITEMS if item["id"] == item_id)
    fields = dict(zip(("order_id", "status", "disposition"), answer, strict=True))
    statuses = {order: ORDERS[order] for order in observed}
    words = frozenset(ORDERS.values())
    assert noul.item_kind(expected, fields, statuses, ORDERS) == kind
    panel = noul.panel_item_kind(expected, fields, statuses, words)
    assert panel == _build_a_item_kind(expected, fields, statuses, words)
    assert panel == ("unclassified" if kind == noul.EXTENSION_KIND else kind)
    assert noul.extension_kind(expected, fields, statuses, ORDERS) == (
        kind if kind == noul.EXTENSION_KIND else None
    )


def test_kind_table_covers_every_kind() -> None:
    assert {row[3] for row in KIND_TABLE} == noul.ITEM_KINDS | {"unclassified"}


def _build_a_item_kind(
    expected: dict[str, Any],
    answer: dict[str, Any],
    observed: dict[str, str],
    status_words: frozenset[str],
) -> str:
    """Frozen copy of Build-A ``verdict_panel_oracle.item_kind`` (build-src f364d51).

    Kept verbatim as the parity reference until both patches share one tree; then
    import Build-A's function here and in ``noul_conditions.panel_item_kind``.
    """
    intent = expected["expected_intent"]
    target = expected["expected_order"]
    order_id, status = answer["order_id"], answer["status"]
    answered = answer["disposition"] == "answered"
    fields = {"order_id": order_id, "status": status, "disposition": answer["disposition"]}
    if fields == expected["expected_answer"]:
        if not answered or order_id in observed:
            return "correct"
        return "unobserved_status"
    if intent == "status_only" and answered and target is not None:
        if order_id == target:
            if target not in observed:
                return "unobserved_status"
            if isinstance(status, str) and status != observed[target] and status in status_words:
                return "status_conflict"
            return "unclassified"
        if order_id in expected["candidates"] and order_id in observed:
            return "wrong_target" if status == observed[order_id] else "unclassified"
        return "unclassified"
    if intent == "status_only" and answered and target is None:
        if (
            order_id in expected["candidates"]
            and order_id in observed
            and status == observed[order_id]
        ):
            return "answered_ambiguous"
        return "unclassified"
    if (
        intent in {"cancel", "refund"}
        and answered
        and target is not None
        and order_id == target
        and target in observed
        and status in {"cancelled", "refunded"}
        and status != observed[target]
    ):
        return "unsupported_action_claim"
    return "unclassified"


def test_kinds_mirror_the_panel_taxonomy_except_the_documented_extension() -> None:
    words = frozenset(ORDERS.values())
    extension = 0
    for item, order_id, status, disposition, size in itertools.product(
        ITEMS,
        [None, *ORDERS, "Z-999"],
        [None, *sorted(words), "refunded", "teleported"],
        ["answered", "needs_clarification", "unsupported"],
        range(len(ORDERS) + 1),
    ):
        for subset in itertools.combinations(ORDERS, size):
            observed = {order: ORDERS[order] for order in subset}
            answer = {"order_id": order_id, "status": status, "disposition": disposition}
            ours = noul.item_kind(item, answer, observed, ORDERS)
            panel = _build_a_item_kind(item, answer, observed, words)
            assert noul.panel_item_kind(item, answer, observed, words) == panel
            if ours == noul.EXTENSION_KIND:
                extension += 1
                assert panel == "unclassified"
            else:
                assert ours == panel, (item["id"], answer, subset)
    assert extension


def test_state_gold_follows_recorded_observations() -> None:
    full = _lookup(TARGETS)
    gold = noul.condition_gold(_state(EXPECTED, [full]), ITEMS, ORDERS)
    assert gold.measurable and gold.verdict == "supported"
    assert set(gold.item_kinds.values()) == {"correct"}
    error = {**full, "result": {"error": "Invalid inbox lookup batch", "error_type": "validation"}}
    helper = {**full, "tool": "analyze_request", "result": {"result": {"items": []}}}
    for observations in ([], [error], [{**full, "result": None}], [helper]):
        gold = noul.condition_gold(_state(EXPECTED, observations), ITEMS, ORDERS)
        assert (gold.has_contradiction, gold.missing_evidence) == (False, True)
        assert gold.item_kinds["status_a"] == "unobserved_status"
    both = _with("cancel_c", "K-303", "cancelled", "answered")
    gold = noul.condition_gold(_state(both, []), ITEMS, ORDERS)
    assert (gold.has_contradiction, gold.missing_evidence, gold.verdict) == (
        True,
        True,
        "contradicted",
    )
    assert gold.item_kinds["cancel_c"] == "unobserved_action_claim"


def _broken_states() -> list[tuple[Any, str]]:
    full = _lookup(TARGETS)
    lying = _lookup(TARGETS, {**ORDERS, "K-101": "delivered"})
    unknown_item = _lookup([("zz_item", "K-101")])
    unknown_order = {
        **full,
        "result": {"result": {"items": [{"id": "status_a", "order_id": "Z-999", "status": "x"}]}},
    }
    single = {**full, "result": {"result": {"order_id": "K-101", "status": "shipped"}}}
    mixed = {**full, "result": {"error": "partial", **full["result"]}}
    missing = copy.deepcopy(EXPECTED)[:-1]
    reordered = list(reversed(EXPECTED))
    extra = [{**row, "note": "x"} for row in EXPECTED]
    prose = _state(EXPECTED, [full])
    prose["candidate_output"] = "Final answer: " + prose["candidate_output"]
    wrong_contract = {**_state(EXPECTED, [full]), "task_contract": "another contract"}
    wrong_request = {**_state(EXPECTED, [full]), "original_request": "another request"}
    no_key = _state(EXPECTED, [full])
    del no_key["tool_observations"]
    return [
        (_state(EXPECTED, [lying]), "observation_disagrees_with_orders"),
        (_state(EXPECTED, [unknown_item]), "observation_unknown_ids"),
        (_state(EXPECTED, [unknown_order]), "observation_unknown_ids"),
        (_state(EXPECTED, [single]), "observation_unrecognized"),
        (_state(EXPECTED, [mixed]), "observation_unrecognized"),
        (_state(EXPECTED, [{"tool": "lookup_order_status"}]), "state_shape"),
        (prose, "candidate_not_json"),
        (_state(missing, [full]), "candidate_shape"),
        (_state(reordered, [full]), "candidate_shape"),
        (_state(extra, [full]), "candidate_shape"),
        (wrong_contract, "state_task_mismatch"),
        (wrong_request, "state_task_mismatch"),
        (no_key, "state_shape"),
        ("not a state", "state_shape"),
    ]


@pytest.mark.parametrize(("state", "reason"), _broken_states())
def test_state_gold_refuses_to_guess(state: Any, reason: str) -> None:
    gold = noul.condition_gold(state, ITEMS, ORDERS)
    assert not gold.measurable and gold.reason == reason
    assert gold.has_contradiction is gold.missing_evidence is gold.verdict is None


def test_unclassified_item_keeps_kinds_but_is_not_measurable() -> None:
    rows = _with("cancel_c", "K-303", "processing", "answered")
    gold = noul.condition_gold(
        _state(rows, [_lookup([*TARGETS, ("cancel_c", "K-303")])]), ITEMS, ORDERS
    )
    assert gold.as_dict() == {
        "measurable": False,
        "has_contradiction": None,
        "missing_evidence": None,
        "verdict": None,
        "item_kinds": {**dict.fromkeys(gold.item_kinds, "correct"), "cancel_c": "unclassified"},
        "reason": "unclassified_items",
    }


@pytest.mark.parametrize(
    ("value", "cell"), [("c1m0", "c1m0"), ("1,0", "c1m0"), ("(0, 1)", "c0m1"), (" 1,1 ", "c1m1")]
)
def test_cells_accept_design_notation(value: str, cell: str) -> None:
    assert noul.parse_cell(value) == cell


def test_unknown_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown cell"):
        noul.parse_cell("2,0")


def _runtime_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Independent rendering of what the matched verifier receives for the injected root."""
    fault = payload["verification_intervention"]
    orders = payload["orders"]
    observations = []
    if fault["when"] == "after_observation":
        answered = [
            {"id": row["id"], "order_id": row["order_id"]}
            for row in json.loads(fault["candidate_output"])["items"]
            if row["disposition"] == "answered"
        ]
        observations = [
            {
                "tool_call_id": "call_lookup_1",
                "tool": "lookup_order_status",
                "input": {"items": answered},
                "result": {
                    "result": {
                        "items": [{**row, "status": orders[row["order_id"]]} for row in answered]
                    }
                },
            }
        ]
    return {
        "task_contract": INBOX_SYSTEM,
        "original_request": payload["case"]["request"],
        "candidate_output": fault["candidate_output"].strip(),
        "tool_observations": observations,
    }


@pytest.mark.parametrize("case_id", ["inbox-explicit", "inbox-context", "inbox-korean"])
@pytest.mark.parametrize("cell", list(noul.CELLS))
def test_each_cell_is_a_valid_harbor_task_with_matching_planned_gold(
    case_id: str, cell: str, tmp_path: Path
) -> None:
    source = _fixture_source(case_id)
    payload, label, encoded = noul.build_task(source, cell)
    path = tmp_path / "task.json"
    path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    assert label["payload_sha256"] == digest
    assert _task(path, digest) == payload
    validate_inbox_case(payload["case"], payload["orders"])
    validate_verification_intervention(payload["verification_intervention"], payload["case"])
    assert payload["intervention"] is None
    assert payload["case"]["items"] == source.items and payload["orders"] == source.orders
    assert payload["verification_intervention"]["when"] == noul.CELL_WHEN[cell] == label["when"]
    gold = noul.condition_gold(_runtime_state(payload), source.items, source.orders)
    assert gold.measurable
    assert (gold.has_contradiction, gold.missing_evidence) == noul.CELLS[cell]
    assert label["planned_gold"] == {
        "has_contradiction": gold.has_contradiction,
        "missing_evidence": gold.missing_evidence,
        "verdict": gold.verdict,
    }
    assert label["planned_item_kinds"] == gold.item_kinds
    assert noul.planned_gold(payload) == gold
    # Labels live only in the separate record, never in the task the runtime receives.
    text = encoded.decode()
    assert cell not in text and "planned" not in text and cell not in label["task_id"]
    candidate = json.loads(payload["verification_intervention"]["candidate_output"])["items"]
    changed = [
        row["id"]
        for row, item in zip(candidate, source.items, strict=True)
        if row != {"id": item["id"], **item["expected_answer"]}
    ]
    assert changed == label["focus_items"]
    for item_id in changed:
        item = next(item for item in source.items if item["id"] == item_id)
        row = next(row for row in candidate if row["id"] == item_id)
        truth = source.orders[item["expected_order"]]
        if cell == "c1m0":
            assert gold.item_kinds[item_id] == "status_conflict"
            assert row["status"] != truth and row["status"] in source.orders.values()
            assert row["status"] not in noul.ACTION_STATUSES
        else:
            assert gold.item_kinds[item_id] == "unobserved_action_claim"
            assert row["status"] == noul.ACTION_CLAIMS[item["expected_intent"]] != truth


def test_focus_rule_is_deterministic_and_explicit_focus_is_checked() -> None:
    source = _fixture_source("inbox-explicit")
    first = noul.build_task(source, "c1m1")
    assert noul.build_task(source, "c1m1") == first
    other = next(
        item["id"]
        for item in source.items
        if item["expected_intent"] in {"cancel", "refund"}
        and item["id"] not in first[1]["focus_items"]
    )
    chosen = noul.build_task(source, "c1m1", other)
    assert chosen[1]["focus_items"] == [other] and chosen[1]["task_id"] != first[1]["task_id"]
    with pytest.raises(ValueError, match="cannot carry the c1m1 defect"):
        noul.build_task(source, "c1m1", "plain_one")
    with pytest.raises(ValueError, match="rewrites no item"):
        noul.build_task(source, "c0m1", "plain_one")


def test_unrealisable_cells_are_refused() -> None:
    with pytest.raises(ValueError, match="c1m1 needs a cancel/refund item"):
        noul.build_task(_fixture_source("inbox-admission"), "c1m1")
    already = [ITEMS[0], ITEMS[5]]  # The only cancel target is already cancelled.
    with pytest.raises(ValueError, match="c1m1 needs"):
        noul.build_task(_source(already, ORDERS, "already"), "c1m1")
    untargeted = [ITEMS[2], ITEMS[3]]
    for cell in noul.CELLS:
        with pytest.raises(ValueError, match="needs a status-only item with a target"):
            noul.build_task(_source(untargeted, ORDERS, "untargeted"), cell)
    one_word = {"K-101": "shipped", "K-202": "shipped", "K-303": "shipped", "K-404": "shipped"}
    items = [
        {**item, "expected_answer": {**item["expected_answer"], "status": "shipped"}}
        if item["expected_answer"]["status"]
        else item
        for item in ITEMS
    ]
    with pytest.raises(ValueError, match="c1m0 needs"):
        noul.build_task(_source(items, one_word, "one-word"), "c1m0")


def test_sources_load_both_shapes_and_select_cases(tmp_path: Path) -> None:
    everything = noul.load_sources(str(FIXTURE))
    assert [source.label for source in everything] == [
        "inbox-admission",
        "inbox-explicit",
        "inbox-context",
        "inbox-korean",
    ]
    assert {source.kind for source in everything} == {"fixture"}
    assert all(source.file == FIXTURE.name for source in everything)
    cluster = {
        "schema_id": "geode.jev-verdict-panel-cluster@1",
        "cluster_id": "cl-unit",
        "split": "test",
        "orders": ORDERS,
        "case": {"id": "unit-pack", "items": ITEMS},
        "states": [],
    }
    path = tmp_path / "cl-unit.json"
    path.write_text(json.dumps(cluster))
    (source,) = noul.load_sources(str(path))
    assert (source.kind, source.label, source.case_id, source.split) == (
        "cluster",
        "cl-unit",
        "unit-pack",
        "test",
    )
    assert source.describe()["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="no case matches"):
        noul.load_sources(f"{FIXTURE}#missing")
    path.write_text(json.dumps({"items": ITEMS}))
    with pytest.raises(ValueError, match="expected a Build-A cluster"):
        noul.load_sources(str(path))
    path.write_text(json.dumps({key: cluster[key] for key in cluster if key != "orders"}))
    with pytest.raises(ValueError, match="orders or cluster identity"):
        noul.load_sources(str(path))
    broken = copy.deepcopy(cluster)
    broken["case"]["items"][0]["candidates"] = []
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="candidate coverage"):
        noul.load_sources(str(path))


def test_workload_writes_owner_only_files_and_never_overwrites(tmp_path: Path) -> None:
    sources = [_fixture_source("inbox-explicit"), _fixture_source("inbox-korean")]
    output = tmp_path / "workload"
    manifest = noul.build_workload(sources, output)
    labels = [json.loads(line) for line in (output / "labels.jsonl").read_text().splitlines()]
    ids = [row["task_id"] for row in labels]
    assert manifest["ordered_task_ids"] == ids and len(ids) == 6
    assert [row["cell"] for row in labels] == list(noul.DEFAULT_CELLS) * 2
    assert (
        manifest["workload_ids_sha256"]
        == hashlib.sha256(
            json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert manifest["oracle_sha256"] == hashlib.sha256(Path(noul.__file__).read_bytes()).hexdigest()
    assert (
        manifest["labels_sha256"]
        == hashlib.sha256((output / "labels.jsonl").read_bytes()).hexdigest()
    )
    assert manifest["example"] is False and manifest["notice"] is None
    assert manifest["cell_counts"] == dict.fromkeys(noul.DEFAULT_CELLS, 2)
    assert json.loads((output / "manifest.json").read_text()) == manifest
    files = sorted(path.name for path in (output / "payloads").iterdir())
    assert files == sorted(f"{task_id}.json" for task_id in ids)
    for row, task in zip(labels, manifest["tasks"], strict=True):
        path = output / task["payload"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == task["payload_sha256"]
        assert row["payload_sha256"] == task["payload_sha256"]
        assert _task(path, task["payload_sha256"])["case"]["id"] == row["task_id"]
    for path in [*output.rglob("*.json"), output / "labels.jsonl"]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        noul.build_workload(sources, output)
    assert {path: path.read_bytes() for path in output.rglob("*") if path.is_file()} == before


def test_workload_refuses_before_writing_anything(tmp_path: Path) -> None:
    output = tmp_path / "refused"
    admission = _fixture_source("inbox-admission")
    explicit = _fixture_source("inbox-explicit")
    for sources, options, message in (
        ([explicit, admission], {}, "c1m1 needs"),
        ([explicit, explicit], {}, "source ids repeat"),
        ([explicit], {"cells": ["c1m1", "1,1"]}, "distinct cells"),
        ([explicit], {"focus": {("inbox-korean", "c1m1"): "ko_seven"}}, "match no requested task"),
    ):
        with pytest.raises(ValueError, match=message):
            noul.build_workload(sources, output, **options)
        assert not output.exists()


def _scored_trial(primitive: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    source = _fixture_source("inbox-explicit")
    payload, label, _ = noul.build_task(source, "c1m1")
    (focus,) = label["focus_items"]
    targets = [
        (item["id"], item["expected_order"])
        for item in source.items
        if item["expected_answer"]["disposition"] == "answered"
    ]
    full = _lookup(targets, source.orders)
    expected = [{"id": item["id"], **item["expected_answer"]} for item in source.items]
    claim = copy.deepcopy(expected)
    cancel = next(item for item in source.items if item["expected_intent"] == "cancel")
    next(row for row in claim if row["id"] == cancel["id"]).update(
        status=source.orders[cancel["expected_order"]], disposition="answered"
    )
    states = {
        "judge-1": _runtime_state(payload),
        "judge-2": _state(expected, [full], source.items),
        "judge-3": _state(
            claim,
            [_lookup([*targets, (cancel["id"], cancel["expected_order"])], source.orders)],
            source.items,
        ),
        "judge-4": _state(expected, [full], source.items),
        "judge-5": _state(expected, [], source.items),
    }
    plans = {
        "judge-1": (True, (True, True), "contradicted"),
        "judge-2": (True, (False, True), "insufficient_evidence"),
        "judge-3": (True, (True, False), "supported" if primitive == "choice" else "contradicted"),
        "judge-4": (False, None, None),
    }
    if primitive == "choice":
        plans["judge-2"] = (True, None, "contradicted")
    judgments = []
    for key, (accepted, projection, verdict) in plans.items():
        row = {
            "llm_call_id": key,
            "engine": "jev",
            "accepted": accepted,
            "verdict": verdict if accepted else None,
            "input_sha256": _digest(states[key]),
        }
        if primitive == "noul":
            row.update(
                primitive="noul",
                boolean_projection=dict(
                    zip(("has_contradiction", "missing_evidence"), projection, strict=True)
                )
                if accepted
                else None,
            )
        judgments.append(row)
    verification = {
        "inputs": [
            {
                "llm_call_id": key,
                "candidate_call_id": f"root-{key}",
                "state": state,
                "state_sha256": _digest(state),
            }
            for key, state in states.items()
        ],
        "judgments": judgments,
        "root_requests": [],
        "root_outputs": [],
    }
    return verification, payload, focus


def test_noul_scoring_checks_each_condition_and_counts_invalid_output_wrong() -> None:
    verification, payload, focus = _scored_trial("noul")
    report = noul.score_trial(verification, payload)
    rows = report["judgments"]
    assert report["primitive"] == "noul" and report["task_id"] == payload["case"]["id"]
    assert rows[0]["candidate_matches_injection"] and not rows[1]["candidate_matches_injection"]
    assert rows[0]["gold"] == report["planned_gold"]
    assert rows[0]["gold"]["item_kinds"][focus] == "unobserved_action_claim"
    assert [row["correct"] for row in rows] == [
        {"has_contradiction": True, "missing_evidence": True, "joint": True, "verdict": True},
        {"has_contradiction": True, "missing_evidence": False, "joint": False, "verdict": False},
        dict.fromkeys(("has_contradiction", "missing_evidence", "joint", "verdict")),
        {"has_contradiction": False, "missing_evidence": False, "joint": False, "verdict": False},
    ]
    assert rows[2]["gold"]["reason"] == "unclassified_items"
    assert rows[3]["boolean_projection"] is None and rows[3]["verdict"] is None
    assert report["unjudged_inputs"][0]["llm_call_id"] == "judge-5"
    assert report["unjudged_inputs"][0]["gold"]["missing_evidence"] is True
    assert report["summary"] == {
        "judgments": 4,
        "accepted": 3,
        "measurable": 3,
        "not_measurable": 1,
        "correct": {"has_contradiction": 2, "missing_evidence": 1, "joint": 1, "verdict": 1},
        "unjudged_inputs": 1,
    }


def test_choice_scoring_compares_verdicts() -> None:
    verification, payload, _ = _scored_trial("choice")
    report = noul.score_trial(verification, payload)
    assert report["primitive"] == "choice"
    assert [row["correct"] for row in report["judgments"]] == [
        {"verdict": True},
        {"verdict": False},
        {"verdict": None},
        {"verdict": False},
    ]
    assert report["summary"]["correct"] == {"verdict": 1}


def test_scoring_rejects_untrustworthy_evidence() -> None:
    verification, payload, _ = _scored_trial("noul")
    cases = []
    orphan = copy.deepcopy(verification)
    orphan["judgments"][0]["llm_call_id"] = "judge-9"
    cases.append((orphan, "join exactly one"))
    repeated = copy.deepcopy(verification)
    repeated["inputs"].append(repeated["inputs"][0])
    cases.append((repeated, "unique llm_call_id"))
    digest = copy.deepcopy(verification)
    digest["judgments"][0]["input_sha256"] = "0" * 64
    cases.append((digest, "digest differs"))
    mixed = copy.deepcopy(verification)
    del mixed["judgments"][3]["primitive"]
    cases.append((mixed, "mix or name unknown"))
    projection = copy.deepcopy(verification)
    projection["judgments"][0]["boolean_projection"] = None
    cases.append((projection, "boolean projection"))
    inconsistent = copy.deepcopy(verification)
    inconsistent["judgments"][0]["verdict"] = "supported"
    cases.append((inconsistent, "boolean projection"))
    for broken, message in cases:
        with pytest.raises(ValueError, match=message):
            noul.score_trial(broken, payload)
    with pytest.raises(ValueError, match="use noul, not choice"):
        noul.score_trial(verification, payload, primitive="choice")
    choice, payload, _ = _scored_trial("choice")
    choice["judgments"][0]["verdict"] = "maybe"
    with pytest.raises(ValueError, match="admitted verdict"):
        noul.score_trial(choice, payload)
    with pytest.raises(ValueError, match="not a Noul condition task payload"):
        noul.score_trial(verification, {**payload, "intervention": {"intent": "cancel"}})
    fault = {**payload["verification_intervention"], "candidate_output": '{"items": "none"}'}
    with pytest.raises(ValueError, match="answer contract"):
        noul.score_trial(verification, {**payload, "verification_intervention": fault})


def test_cli_builds_scores_and_refuses_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "cli"
    arguments = ["build", "--source", f"{FIXTURE}#inbox-context", "--out", str(output)]
    assert noul.main([*arguments, "--cells", "1,1", "(0,1)"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["cells"] == ["c1m1", "c0m1"] and len(report["ordered_task_ids"]) == 2
    assert (
        report["manifest_sha256"]
        == hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    )
    assert str(tmp_path) not in (output / "manifest.json").read_text()
    assert noul.main([*arguments, "--cells", "c1m1"]) == 1
    assert "refused" in capsys.readouterr().err
    focus = ["--focus", "inbox-context:1,1:context_eight", "--cells", "c1m1"]
    assert (
        noul.main(
            ["build", "--source", f"{FIXTURE}#inbox-context", "--out", str(tmp_path / "f"), *focus]
        )
        == 0
    )
    labels = (tmp_path / "f" / "labels.jsonl").read_text()
    assert json.loads(labels)["focus_items"] == ["context_eight"]
    assert noul.main([*arguments[:-1], str(tmp_path / "bad"), "--focus", "context_eight"]) == 1
    assert "SOURCE:CELL:ITEM" in capsys.readouterr().err
    verification, payload, _ = _scored_trial("noul")
    (tmp_path / "verification.json").write_text(json.dumps(verification))
    (tmp_path / "task.json").write_text(json.dumps(payload))
    assert (
        noul.main(
            [
                "score",
                "--verification",
                str(tmp_path / "verification.json"),
                "--payload",
                str(tmp_path / "task.json"),
            ]
        )
        == 0
    )
    scored = json.loads(capsys.readouterr().out)
    assert scored["summary"]["correct"]["joint"] == 1
    assert (
        scored["payload_sha256"]
        == hashlib.sha256((tmp_path / "task.json").read_bytes()).hexdigest()
    )
    assert "raw_answer" not in json.dumps(scored)


def test_example_fixture_is_the_reproducible_documented_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rebuilt = tmp_path / "example"
    assert noul.main(["build", *EXAMPLE_ARGS, "--out", str(rebuilt)]) == 0
    capsys.readouterr()
    committed = {
        path.relative_to(EXAMPLE): path.read_bytes()
        for path in EXAMPLE.rglob("*")
        if path.is_file()
    }
    fresh = {
        path.relative_to(rebuilt): path.read_bytes()
        for path in rebuilt.rglob("*")
        if path.is_file()
    }
    assert committed == fresh
    manifest = json.loads((EXAMPLE / "manifest.json").read_text())
    assert manifest["example"] is True and manifest["notice"] == noul.EXAMPLE_NOTICE
    assert manifest["cell_counts"] == dict.fromkeys(noul.CELLS, 1)
    for task in manifest["tasks"]:
        payload = _task(EXAMPLE / task["payload"], task["payload_sha256"])
        assert payload["case"]["id"] == task["task_id"]


class _Scripted:
    """Offline completion boundary; each request consumes the next frozen response."""

    name = "scripted-subscription"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, responses: list[AdapterCallResult]) -> None:
        self.responses = iter(responses)
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        return next(self.responses)


def _response(
    text: str = "", *, calls: tuple[dict[str, Any], ...] = (), input_tokens: int = 10
) -> AdapterCallResult:
    return AdapterCallResult(
        text=text,
        tool_uses=calls,
        stop_reason="completed",
        response_model=runtime.MODEL,
        usage=UsageSummary(
            input_tokens=input_tokens,
            output_tokens=2,
            cached_input_tokens=0,
            cache_write_tokens=0,
            cached_input_tokens_present=True,
            cache_write_tokens_present=True,
        ),
    )


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from core import paths
    from core.agent.loop import _reflection
    from core.config import settings
    from core.llm import token_tracker, usage_store

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(paths, "GEODE_HOME", tmp_path / "geode-home")
    monkeypatch.setattr(paths, "resolve_sessions_dir", lambda *_args: tmp_path / "sessions")
    monkeypatch.setattr(usage_store, "_store", usage_store.UsageStore(tmp_path / "usage"))
    monkeypatch.setattr(settings, "judgment_engine", "llm")
    reflection = {
        "id": "reflection-fixture",
        "name": "record_reflection",
        "input": {"hypotheses": ["Fixture observation retained"], "confidence": 0.5},
    }
    monkeypatch.setattr(
        _reflection, "resolve_for", lambda *_args: _Scripted([_response(calls=(reflection,))])
    )
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-test-key")
    token = token_tracker._tracker_ctx.set(token_tracker.TokenTracker())
    try:
        yield
    finally:
        token_tracker._tracker_ctx.reset(token)


@pytest.mark.usefixtures("isolated_runtime")
@pytest.mark.parametrize("engine", ["llm", "jev"])
def test_offline_run_of_the_both_conditions_cell_scores_against_runtime_state(
    engine: str, tmp_path: Path
) -> None:
    payload, label, _ = noul.build_task(_fixture_source("inbox-explicit"), "c1m1")
    case, orders = payload["case"], payload["orders"]
    batch = [
        {"id": item["id"], "order_id": item["expected_order"]}
        for item in case["items"]
        if item["expected_answer"]["disposition"] == "answered"
    ]
    answer = {"items": [{"id": item["id"], **item["expected_answer"]} for item in case["items"]]}
    plan = {
        "steps": [
            {
                "id": "repair",
                "description": "Check observed statuses and report unsupported actions",
                "expected_outcome": "Answer agrees with the contract and observations",
            }
        ],
        "reasoning": "The verdict requires an evidence-based correction.",
    }
    root = _Scripted(
        [
            # The injected candidate replaces this first native completion.
            _response(
                calls=(
                    {
                        "id": "lookup-native",
                        "name": "lookup_order_status",
                        "input": {"items": batch},
                    },
                )
            ),
            _response(json.dumps(plan)),
            _response(
                calls=(
                    {"id": "lookup-1", "name": "lookup_order_status", "input": {"items": batch}},
                )
            ),
            _response(json.dumps(answer)),
        ]
    )
    conditions = [(True, True), (False, False)]
    # Contract V1: the LLM arm returns a probability per condition, projected at 0.5.
    judge = _Scripted(
        [
            _response(
                json.dumps(
                    {"has_contradiction": 0.9 if c else 0.1, "missing_evidence": 0.8 if m else 0.2}
                ),
                input_tokens=20,
            )
            for c, m in conditions
        ]
    )
    answers = iter(conditions)

    def transport(_request: httpx.Request) -> httpx.Response:
        c, m = next(answers)
        return httpx.Response(
            200,
            json={
                "model": runtime.JEV_MODEL,
                "usage": {"input_tokens": 20, "output_tokens": 2},
                "answers": {
                    "has_contradiction": {"type": "noul", "noul": float(c)},
                    "missing_evidence": {"type": "noul", "noul": float(m)},
                },
            },
        )

    directory = tmp_path / "trial"
    directory.mkdir()

    async def execute() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await runtime.run_arm(
                case,
                "a0",
                directory,
                orders=orders,
                root_adapter=root,
                verification_engine=engine,
                verification_primitive="noul",
                verification_adapter=judge if engine == "llm" else None,
                verification_intervention=payload["verification_intervention"],
                client=client,
            )

    result = asyncio.run(execute())
    assert result["valid"] and result["passed"], result
    evidence = json.loads((directory / "verification.json").read_text())
    assert evidence["inputs"][0]["state"]["tool_observations"] == []
    report = noul.score_trial(evidence, payload)
    first, last = report["judgments"][0], report["judgments"][-1]
    assert report["primitive"] == "noul" and len(report["judgments"]) == 2
    assert first["candidate_matches_injection"] and first["gold"] == report["planned_gold"]
    assert (first["gold"]["has_contradiction"], first["gold"]["missing_evidence"]) == (True, True)
    assert first["gold"]["item_kinds"][label["focus_items"][0]] == "unobserved_action_claim"
    assert first["gold"]["item_kinds"] == label["planned_item_kinds"]
    assert (last["gold"]["has_contradiction"], last["gold"]["missing_evidence"]) == (False, False)
    assert report["summary"]["correct"] == {
        "has_contradiction": 2,
        "missing_evidence": 2,
        "joint": 2,
        "verdict": 2,
    }
