"""Noul 2x2 E2E conditions: runtime rule oracle, injected cell tasks and trial scoring.

The matched verifier in ``decision_handoff_runtime`` judges one runtime state at a
time: the frozen ``INBOX_SYSTEM`` contract, ``inbox_request(items)``, the root's
stripped candidate text and every recorded tool observation. This module
recomputes the two Noul conditions for exactly that state, builds the E2E
injection cells (02 §2 C4, 05 §2.3) on the single existing
``verification_intervention`` per trial, and scores a finished trial's
judgments. Nothing here dispatches a model call or reads credentials.

Rule oracle
    O maps order ID to status for every successful ``lookup_order_status`` batch
    in the state (``{"result": {"items": [{id, order_id, status}]}}``). Tool errors
    and missing results observe nothing. A successful observation that disagrees
    with the frozen ``orders`` makes the state unmeasurable; the oracle never
    guesses. The candidate must follow the runtime inbox answer contract and list
    every case item in order. ``panel_item_kind`` is Build-A's panel taxonomy
    (``verdict_panel_oracle.item_kind``, PANEL-SCHEMA §3; same signature, names and
    precedence, first match wins): ``correct``, ``unobserved_status`` [m],
    ``status_conflict`` [c], ``wrong_target`` [c], ``answered_ambiguous`` [c],
    ``unsupported_action_claim`` [c], else ``unclassified`` (not measurable).

    E2E extension ``unobserved_action_claim`` [c] (``extension_kind``, consulted
    only for a panel-``unclassified`` item): a cancel/refund item with a target
    answered as ``{target, s, "answered"}`` where s is ``cancelled`` or
    ``refunded``, the target is not in O and s != orders[target]. The frozen
    INBOX_SYSTEM contract offers no mutation tool and requires cancellation and
    refund items to be ``unsupported`` with a null status, so a claimed mutation
    contradicts the contract without any observation. Build-A's
    ``unsupported_action_claim`` requires the target in O and Build-A leaves this
    unobserved shape ``unclassified`` (state rejected), so gold on every Build-A
    panel-valid state is unchanged by the extension.

    c = any c kind, m = any m kind; verdict precedence is contradicted >
    insufficient_evidence > supported.

Cells (one intervention per trial; the Choice and Noul arms share the tasks)
    c1m0  after_observation: expected answers except focus f1, a status-only item
          with a target, which reports another status word of the orders table
          (non-action words preferred) -> status_conflict once the root has looked
          up every answered target.
    c0m1  before_observation: all expected answers before any observation ->
          unobserved_status.
    c1m1  before_observation: expected answers except focus f1, a cancel/refund
          item with a target, claiming ``cancelled``/``refunded`` ->
          unobserved_action_claim plus unobserved_status in one candidate.
    c0m0  after_observation: the fully correct candidate (control).

    The focus is the explicit item, else the first eligible item in ascending
    ``sha256(source ␟ cell ␟ item_id)`` order, where source is the cluster ID or
    else the case ID; the c1m0 status word is the first candidate word in
    ascending ``sha256(source ␟ item_id ␟ word)`` order. Planned gold is this
    oracle applied to the planned runtime state (no observation before; one
    lookup of every answered target after) and must equal the requested cell.
    Payloads carry no label; labels live in a separate ``labels.jsonl`` record.

Scoring
    Gold is recomputed from every judged runtime state, because a live root can
    observe more or less than planned. Noul compares each condition's boolean
    projection and their joint; Choice compares the verdict. A judgment that was
    not accepted counts as wrong (05 §3.1); a state whose gold is not measurable
    is reported with its reason and never scored.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import jsonschema

from evals.benchmarks.decision_handoff_runtime import (
    INBOX_SYSTEM,
    _inbox_answer_schema,
    inbox_request,
    validate_inbox_case,
    validate_verification_intervention,
)

MANIFEST_SCHEMA_ID = "geode.jev-noul-conditions-workload@1"
SCORE_SCHEMA_ID = "geode.jev-noul-conditions-score@1"
BUILDER_VERSION = "jev-noul-conditions-builder@1"
LOOKUP_TOOL = "lookup_order_status"
PANEL_C_KINDS = frozenset(
    {"status_conflict", "wrong_target", "answered_ambiguous", "unsupported_action_claim"}
)
EXTENSION_KIND = "unobserved_action_claim"
C_KINDS = PANEL_C_KINDS | {EXTENSION_KIND}
M_KINDS = frozenset({"unobserved_status"})
ITEM_KINDS = C_KINDS | M_KINDS | {"correct"}
ACTION_STATUSES = frozenset({"cancelled", "refunded"})
ACTION_CLAIMS = {"cancel": "cancelled", "refund": "refunded"}
VERDICTS = ("supported", "contradicted", "insufficient_evidence")
CELLS: dict[str, tuple[bool, bool]] = {
    "c1m0": (True, False),
    "c0m1": (False, True),
    "c1m1": (True, True),
    "c0m0": (False, False),
}
CELL_WHEN = {
    "c1m0": "after_observation",
    "c0m1": "before_observation",
    "c1m1": "before_observation",
    "c0m0": "after_observation",
}
DEFAULT_CELLS = ("c1m0", "c0m1", "c1m1")
# The native verify prompt bounds a candidate at 2,000 characters; staying inside
# keeps that prompt and the matched verifier state carrying the same text.
CANDIDATE_TEXT_LIMIT = 2000
EXAMPLE_NOTICE = (
    "Synthetic example only, not the frozen E2E workload. The frozen workload is "
    "authored and sealed by the held-out authoring agent and must be rebuilt with "
    "this builder."
)
_SEP = "\u241f"  # Symbol for unit separator, as in the Build-A panel builder.
_STATE_KEYS = frozenset(
    {"task_contract", "original_request", "candidate_output", "tool_observations"}
)
_OBSERVATION_KEYS = frozenset({"tool_call_id", "tool", "input", "result"})
_PAYLOAD_KEYS = frozenset({"case", "orders", "intervention", "verification_intervention"})
_SOURCE_LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest(value: Any) -> str:
    return _sha256_text(_canonical(value))


def verdict_for(contradiction: bool, missing: bool) -> str:
    """Map the two conditions to the frozen verdict precedence."""
    if contradiction:
        return "contradicted"
    return "insufficient_evidence" if missing else "supported"


def parse_cell(value: str) -> str:
    """Normalize ``c1m0``, ``1,0`` or ``(1,0)`` to the canonical cell name."""
    token = value.strip().replace(" ", "").removeprefix("(").removesuffix(")")
    match = re.fullmatch(r"([01]),([01])", token)
    if match:
        token = f"c{match[1]}m{match[2]}"
    if token not in CELLS:
        raise ValueError(f"unknown cell {value!r}; use c1m0, c0m1, c1m1 or c0m0")
    return token


class _NotMeasurableError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ConditionGold:
    """Rule gold for one runtime state; ``reason`` names why it is not measurable."""

    measurable: bool
    has_contradiction: bool | None
    missing_evidence: bool | None
    verdict: str | None
    item_kinds: dict[str, str] | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def panel_item_kind(
    expected: Mapping[str, Any],
    answer: Mapping[str, Any],
    observed: Mapping[str, str],
    status_words: frozenset[str],
) -> str:
    """Build-A panel taxonomy, same signature and results as ``verdict_panel_oracle.item_kind``.

    Kept verbatim so E2E gold never diverges from panel gold. Once both patches share
    one tree, replace this body with an import of Build-A's ``item_kind``. The first
    matching rule wins; ``unclassified`` is outside the frozen taxonomy.
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
        and status in ACTION_STATUSES
        and status != observed[target]
    ):
        return "unsupported_action_claim"
    return "unclassified"


def extension_kind(
    expected: Mapping[str, Any],
    answer: Mapping[str, Any],
    observed: Mapping[str, str],
    orders: Mapping[str, str],
) -> str | None:
    """Return ``unobserved_action_claim`` for an unobserved claimed mutation, else ``None``."""
    target = expected["expected_order"]
    status = answer["status"]
    if (
        expected["expected_intent"] in ACTION_CLAIMS
        and target is not None
        and answer["disposition"] == "answered"
        and answer["order_id"] == target
        and target not in observed
        and status in ACTION_STATUSES
        and status != orders[target]
    ):
        return EXTENSION_KIND
    return None


def item_kind(
    expected: Mapping[str, Any],
    answer: Mapping[str, Any],
    observed: Mapping[str, str],
    orders: Mapping[str, str],
) -> str:
    """Panel kind first; only a panel-``unclassified`` item can take the extension kind."""
    kind = panel_item_kind(expected, answer, observed, frozenset(orders.values()))
    if kind == "unclassified":
        return extension_kind(expected, answer, observed, orders) or kind
    return kind


def _lookup_entries(result: Any) -> list[dict[str, str]]:
    body = result.get("result") if isinstance(result, dict) and set(result) == {"result"} else None
    entries = body.get("items") if isinstance(body, dict) and set(body) == {"items"} else None
    if (
        not isinstance(entries, list)
        or not entries
        or any(
            not isinstance(entry, dict)
            or set(entry) != {"id", "order_id", "status"}
            or not all(isinstance(value, str) for value in entry.values())
            for entry in entries
        )
    ):
        raise _NotMeasurableError("observation_unrecognized")
    checked: list[dict[str, str]] = entries
    return checked


def observed_statuses(
    observations: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    orders: Mapping[str, str],
) -> dict[str, str]:
    """Return order ID -> status from every successful inbox lookup batch."""
    item_ids = {item["id"] for item in items}
    observed: dict[str, str] = {}
    for row in observations:
        if row["tool"] != LOOKUP_TOOL:
            continue
        result = row["result"]
        if result is None or (
            isinstance(result, dict) and "error" in result and "result" not in result
        ):
            continue  # A failed or missing tool result observes nothing.
        for entry in _lookup_entries(result):
            order_id = entry["order_id"]
            if entry["id"] not in item_ids or order_id not in orders:
                raise _NotMeasurableError("observation_unknown_ids")
            if entry["status"] != orders[order_id]:
                raise _NotMeasurableError("observation_disagrees_with_orders")
            observed[order_id] = entry["status"]
    return observed


def candidate_items(text: str, items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Parse a candidate under the runtime inbox answer contract, in case order."""
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise _NotMeasurableError("candidate_not_json") from exc
    try:
        jsonschema.validate(value, _inbox_answer_schema())
    except jsonschema.ValidationError as exc:
        raise _NotMeasurableError("candidate_shape") from exc
    rows: list[dict[str, Any]] = value["items"]
    if [row["id"] for row in rows] != [item["id"] for item in items]:
        raise _NotMeasurableError("candidate_shape")
    return rows


def _item_kinds(
    state: Any, items: Sequence[Mapping[str, Any]], orders: Mapping[str, str]
) -> dict[str, str]:
    if (
        not isinstance(state, dict)
        or set(state) != _STATE_KEYS
        or not all(
            isinstance(state[key], str)
            for key in ("task_contract", "original_request", "candidate_output")
        )
        or not isinstance(state["tool_observations"], list)
        or any(
            not isinstance(row, dict) or set(row) != _OBSERVATION_KEYS
            for row in state["tool_observations"]
        )
    ):
        raise _NotMeasurableError("state_shape")
    if state["task_contract"] != INBOX_SYSTEM or state["original_request"] != inbox_request(
        [dict(item) for item in items]
    ):
        raise _NotMeasurableError("state_task_mismatch")
    observed = observed_statuses(state["tool_observations"], items, orders)
    answers = candidate_items(state["candidate_output"], items)
    return {
        row["id"]: item_kind(expected, row, observed, orders)
        for expected, row in zip(items, answers, strict=True)
    }


def condition_gold(
    state: Any, items: Sequence[Mapping[str, Any]], orders: Mapping[str, str]
) -> ConditionGold:
    """Recompute (c, m) for one runtime verification state of a frozen inbox task."""
    try:
        kinds = _item_kinds(state, items, orders)
    except _NotMeasurableError as exc:
        return ConditionGold(False, None, None, None, None, exc.reason)
    if any(kind not in ITEM_KINDS for kind in kinds.values()):
        return ConditionGold(False, None, None, None, kinds, "unclassified_items")
    contradiction = any(kind in C_KINDS for kind in kinds.values())
    missing = any(kind in M_KINDS for kind in kinds.values())
    return ConditionGold(True, contradiction, missing, verdict_for(contradiction, missing), kinds)


def planned_state(
    items: Sequence[Mapping[str, Any]],
    orders: Mapping[str, str],
    when: str,
    candidate_output: str,
) -> dict[str, Any]:
    """The runtime state a cell plans: no observation before, one full lookup after."""
    observations: list[dict[str, Any]] = []
    if when == "after_observation":
        batch = [
            {"id": row["id"], "order_id": row["order_id"]}
            for row in json.loads(candidate_output)["items"]
            if row["disposition"] == "answered" and row["order_id"] in orders
        ]
        if batch:
            observations.append(
                {
                    "tool_call_id": "planned-lookup-1",
                    "tool": LOOKUP_TOOL,
                    "input": {"items": batch},
                    "result": {
                        "result": {
                            "items": [
                                {**entry, "status": orders[entry["order_id"]]} for entry in batch
                            ]
                        }
                    },
                }
            )
    return {
        "task_contract": INBOX_SYSTEM,
        "original_request": inbox_request([dict(item) for item in items]),
        "candidate_output": candidate_output,
        "tool_observations": observations,
    }


def check_payload(payload: Any) -> None:
    """Admit only the Harbor handoff task shape that carries one candidate fault."""
    if (
        not isinstance(payload, dict)
        or set(payload) != _PAYLOAD_KEYS
        or payload["intervention"] is not None
        or not isinstance(payload["case"], dict)
        or not isinstance(payload["case"].get("id"), str)
        or not payload["case"]["id"]
        or not isinstance(payload["orders"], dict)
        or not payload["orders"]
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in payload["orders"].items())
        or not isinstance(payload["verification_intervention"], dict)
    ):
        raise ValueError("not a Noul condition task payload")
    validate_inbox_case(payload["case"], payload["orders"])
    try:
        validate_verification_intervention(payload["verification_intervention"], payload["case"])
    except jsonschema.ValidationError as exc:
        raise ValueError("candidate fault violates the inbox answer contract") from exc


def planned_gold(payload: Mapping[str, Any]) -> ConditionGold:
    """Gold of the injected candidate in the state its cell plans."""
    fault = payload["verification_intervention"]
    items, orders = payload["case"]["items"], payload["orders"]
    return condition_gold(
        planned_state(items, orders, fault["when"], fault["candidate_output"]), items, orders
    )


@dataclass(frozen=True)
class Source:
    """One frozen inbox case with its orders table and provenance."""

    kind: str
    file: str
    file_sha256: str
    case_id: str
    items: list[dict[str, Any]]
    orders: dict[str, str]
    cluster_id: str | None = None
    split: str | None = None

    @property
    def label(self) -> str:
        return self.cluster_id or self.case_id

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "file": self.file,
            "sha256": self.file_sha256,
            "cluster_id": self.cluster_id,
            "split": self.split,
            "case_id": self.case_id,
        }


def load_sources(spec: str) -> list[Source]:
    """Load ``FILE`` or ``FILE#CASE`` from a Build-A cluster or the inbox fixture."""
    text, _, selector = spec.partition("#")
    path = Path(text)
    raw = path.read_bytes()
    value = json.loads(raw)
    if isinstance(value, dict) and "cluster_id" in value and "case" in value:
        kind, cluster_id, split = "cluster", value["cluster_id"], value.get("split")
        cases = [value["case"]]
    elif isinstance(value, dict) and isinstance(value.get("cases"), list) and "orders" in value:
        kind, cluster_id, split = "fixture", None, None
        cases = ([value["admission"]] if "admission" in value else []) + value["cases"]
    else:
        raise ValueError(f"{path.name}: expected a Build-A cluster or the inbox fixture shape")
    orders = value.get("orders")
    if (
        not isinstance(orders, dict)
        or not orders
        or not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in orders.items())
        or not (cluster_id is None or isinstance(cluster_id, str))
        or not (split is None or isinstance(split, str))
    ):
        raise ValueError(f"{path.name}: orders or cluster identity are malformed")
    sources = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError(f"{path.name}: every case needs a string id")
        if selector and selector not in {case["id"], cluster_id}:
            continue
        items = copy.deepcopy(case.get("items"))
        if not isinstance(items, list):
            raise ValueError(f"{path.name}#{case['id']}: case items are missing")
        inbox = {"id": case["id"], "profile": "inbox", "items": items}
        validate_inbox_case({**inbox, "request": inbox_request(items)}, orders)
        source = Source(
            kind,
            path.name,
            hashlib.sha256(raw).hexdigest(),
            case["id"],
            items,
            dict(orders),
            cluster_id,
            split,
        )
        if not _SOURCE_LABEL.fullmatch(source.label):
            raise ValueError(f"{path.name}: source id {source.label!r} is not a safe task-id part")
        sources.append(source)
    if not sources:
        raise ValueError(f"{path.name}: no case matches {selector or 'the file'}")
    return sources


def _eligible(cell: str, item: Mapping[str, Any], orders: Mapping[str, str]) -> bool:
    target = item["expected_order"]
    if target is None:
        return False
    if cell == "c1m0":
        return item["expected_intent"] == "status_only" and any(
            word != orders[target] for word in orders.values()
        )
    claim = ACTION_CLAIMS.get(item["expected_intent"])
    return claim is not None and orders[target] != claim


def _focus_item(source: Source, cell: str, explicit: str | None) -> dict[str, Any]:
    eligible = [item for item in source.items if _eligible(cell, item, source.orders)]
    if explicit is not None:
        for item in eligible:
            if item["id"] == explicit:
                return item
        raise ValueError(f"{source.label}: focus item {explicit!r} cannot carry the {cell} defect")
    if not eligible:
        need = (
            "a status-only item with a target and another status word"
            if cell == "c1m0"
            else "a cancel/refund item with a target whose status differs from its claim"
        )
        raise ValueError(f"{source.label}: cell {cell} needs {need}")
    return min(eligible, key=lambda item: _sha256_text(_SEP.join((source.label, cell, item["id"]))))


def _conflict_status(source: Source, item: Mapping[str, Any]) -> str:
    truth = source.orders[item["expected_order"]]
    words = sorted({word for word in source.orders.values() if word != truth})
    preferred = [word for word in words if word not in ACTION_STATUSES] or words
    return min(
        preferred, key=lambda word: _sha256_text(_SEP.join((source.label, item["id"], word)))
    )


def build_task(
    source: Source, cell: str, focus: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Return one cell's payload, its separate label record and the payload bytes."""
    cell = parse_cell(cell)
    items, orders = source.items, source.orders
    if not any(
        item["expected_intent"] == "status_only" and item["expected_order"] is not None
        for item in items
    ):
        raise ValueError(f"{source.label}: cell {cell} needs a status-only item with a target")
    answer = [{"id": item["id"], **item["expected_answer"]} for item in items]
    focus_items: list[str] = []
    if cell in {"c1m0", "c1m1"}:
        chosen = _focus_item(source, cell, focus)
        status = (
            _conflict_status(source, chosen)
            if cell == "c1m0"
            else ACTION_CLAIMS[chosen["expected_intent"]]
        )
        index = next(i for i, row in enumerate(answer) if row["id"] == chosen["id"])
        answer[index] = {
            "id": chosen["id"],
            "order_id": chosen["expected_order"],
            "status": status,
            "disposition": "answered",
        }
        focus_items = [chosen["id"]]
    elif focus is not None:
        raise ValueError(f"{source.label}: cell {cell} rewrites no item; drop its focus")
    when = CELL_WHEN[cell]
    text = json.dumps({"items": answer}, ensure_ascii=False)
    if len(text) > CANDIDATE_TEXT_LIMIT:
        raise ValueError(f"{source.label}: candidate exceeds {CANDIDATE_TEXT_LIMIT} characters")
    fault = {"when": when, "candidate_output": text}
    identity = {"source": source.label, "items": items, "orders": orders, "fault": fault}
    task_id = f"noul-{source.label}-{_digest(identity)[:12]}"
    case = {
        "id": task_id,
        "profile": "inbox",
        "items": copy.deepcopy(items),
        "request": inbox_request(items),
    }
    payload = {
        "case": case,
        "orders": dict(orders),
        "intervention": None,
        "verification_intervention": fault,
    }
    check_payload(payload)
    state = planned_state(items, orders, when, text)
    gold = condition_gold(state, items, orders)
    if not gold.measurable or (gold.has_contradiction, gold.missing_evidence) != CELLS[cell]:
        raise ValueError(f"{source.label}: the planned state does not realise {cell}: {gold}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    label = {
        "task_id": task_id,
        "source": source.describe(),
        "cell": cell,
        "when": when,
        "focus_items": focus_items,
        "planned_observed_orders": sorted(
            {
                entry["order_id"]
                for row in state["tool_observations"]
                for entry in row["input"]["items"]
            }
        ),
        "planned_item_kinds": gold.item_kinds,
        "planned_gold": {
            "has_contradiction": gold.has_contradiction,
            "missing_evidence": gold.missing_evidence,
            "verdict": gold.verdict,
        },
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    return payload, label, encoded


def workload_ids_sha256(ids: Sequence[str]) -> str:
    """The run-spec digest of ``ordered_workload_ids`` (``contract.validate_run_spec``)."""
    return _sha256_text(json.dumps(list(ids), ensure_ascii=False, separators=(",", ":")))


def oracle_sha256() -> str:
    """Digest of this module (oracle, cell rules and builder), frozen in each manifest."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def build_workload(
    sources: Sequence[Source],
    output: Path,
    *,
    cells: Sequence[str] = DEFAULT_CELLS,
    focus: Mapping[tuple[str, str], str] | None = None,
    example: bool = False,
) -> dict[str, Any]:
    """Build every source x cell task, then write payloads, labels and the manifest.

    Every task is built and validated before the first write; the output directory
    must not exist and no file is ever overwritten.
    """
    wanted = [parse_cell(cell) for cell in cells]
    labels = [source.label for source in sources]
    choices = {(label, parse_cell(cell)): item for (label, cell), item in (focus or {}).items()}
    if not sources or not wanted or len(set(wanted)) != len(wanted):
        raise ValueError("a workload needs sources and distinct cells")
    if len(set(labels)) != len(labels):
        raise ValueError("source ids repeat; select each case once")
    unused = sorted(
        f"{label}:{cell}" for label, cell in choices if label not in labels or cell not in wanted
    )
    if unused:
        raise ValueError(f"focus choices match no requested task: {unused}")
    tasks = [
        build_task(source, cell, choices.get((source.label, cell)))
        for source in sources
        for cell in wanted
    ]
    ids = [label["task_id"] for _, label, _ in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("task ids repeat")
    labels_text = "".join(_canonical(label) + "\n" for _, label, _ in tasks).encode()
    manifest = {
        "schema_id": MANIFEST_SCHEMA_ID,
        "schema_version": 1,
        "builder_version": BUILDER_VERSION,
        "oracle_sha256": oracle_sha256(),
        "example": example,
        "notice": EXAMPLE_NOTICE if example else None,
        "cells": wanted,
        "cell_counts": dict(Counter(label["cell"] for _, label, _ in tasks)),
        "sources": [source.describe() for source in sources],
        "tasks": [
            {
                "task_id": label["task_id"],
                "payload": f"payloads/{label['task_id']}.json",
                "payload_sha256": label["payload_sha256"],
            }
            for _, label, _ in tasks
        ],
        "ordered_task_ids": ids,
        "workload_ids_sha256": workload_ids_sha256(ids),
        "labels": "labels.jsonl",
        "labels_sha256": hashlib.sha256(labels_text).hexdigest(),
    }
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / "payloads").mkdir(mode=0o700)
    for _, label, encoded in tasks:
        _write_new(output / "payloads" / f"{label['task_id']}.json", encoded)
    _write_new(output / "labels.jsonl", labels_text)
    _write_new(
        output / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
    )
    return manifest


def _indexed(rows: Any, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"verification {name} are missing")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("llm_call_id") if isinstance(row, dict) else None
        if not isinstance(key, str) or not key or key in indexed:
            raise ValueError(f"verification {name} need unique llm_call_id values")
        indexed[key] = row
    return indexed


def _correctness(
    judgment: Mapping[str, Any], gold: ConditionGold, primitive: str
) -> tuple[dict[str, bool | None], dict[str, bool] | None]:
    """Per-measure correctness; ``None`` only when the gold is not measurable."""
    accepted = judgment["accepted"]
    verdict = judgment.get("verdict")
    projection: dict[str, bool] | None = None
    if accepted and primitive == "noul":
        raw = judgment.get("boolean_projection")
        if (
            not isinstance(raw, dict)
            or set(raw) != {"has_contradiction", "missing_evidence"}
            or not all(isinstance(value, bool) for value in raw.values())
            or verdict != verdict_for(raw["has_contradiction"], raw["missing_evidence"])
        ):
            raise ValueError("an accepted Noul judgment lacks a consistent boolean projection")
        projection = raw
    elif accepted and verdict not in VERDICTS:
        raise ValueError("an accepted judgment lacks an admitted verdict")
    measures: tuple[str, ...] = ("verdict",)
    if primitive == "noul":
        measures = ("has_contradiction", "missing_evidence", "joint", "verdict")
    if not gold.measurable:
        return dict.fromkeys(measures), projection
    # 05 §3.1: an invalid (not accepted) judgment output counts as wrong.
    correct: dict[str, bool | None] = {"verdict": bool(accepted and verdict == gold.verdict)}
    if primitive == "noul":
        c = projection is not None and projection["has_contradiction"] == gold.has_contradiction
        m = projection is not None and projection["missing_evidence"] == gold.missing_evidence
        correct = {"has_contradiction": c, "missing_evidence": m, "joint": c and m, **correct}
    return correct, projection


def score_trial(
    verification: Any, payload: Mapping[str, Any], *, primitive: str | None = None
) -> dict[str, Any]:
    """Score every judgment of one finished trial against its recomputed state gold."""
    check_payload(payload)
    items, orders = payload["case"]["items"], payload["orders"]
    if not isinstance(verification, dict):
        raise ValueError("verification evidence must be an object")
    inputs = _indexed(verification.get("inputs"), "inputs")
    judgments = verification.get("judgments")
    if not isinstance(judgments, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("accepted"), bool) for row in judgments
    ):
        raise ValueError("verification judgments are malformed")
    primitives = {row.get("primitive", "choice") for row in judgments}
    if len(primitives) > 1 or not primitives <= {"choice", "noul"}:
        raise ValueError("judgments mix or name unknown primitives")
    inferred = next(iter(primitives), None)
    if primitive is not None and primitive not in {"choice", "noul"}:
        raise ValueError("primitive must be choice or noul")
    if primitive is not None and inferred is not None and primitive != inferred:
        raise ValueError(f"judgments use {inferred}, not {primitive}")
    primitive = primitive or inferred
    injected = payload["verification_intervention"]["candidate_output"].strip()
    rows: list[dict[str, Any]] = []
    for index, judgment in enumerate(judgments):
        key = judgment.get("llm_call_id")
        record = inputs.get(key) if isinstance(key, str) else None
        if record is None or any(row["llm_call_id"] == key for row in rows):
            raise ValueError("each judgment must join exactly one verification input")
        state = record.get("state")
        digest = _digest(state)
        if {judgment.get("input_sha256", digest), record.get("state_sha256", digest)} != {digest}:
            raise ValueError("a judgment input digest differs from its recorded state")
        gold = condition_gold(state, items, orders)
        assert primitive is not None  # Non-empty judgments always name one primitive.
        correct, projection = _correctness(judgment, gold, primitive)
        rows.append(
            {
                "index": index,
                "llm_call_id": key,
                "candidate_call_id": record.get("candidate_call_id"),
                "candidate_matches_injection": isinstance(state, dict)
                and state.get("candidate_output") == injected,
                "accepted": judgment["accepted"],
                "verdict": judgment.get("verdict") if judgment["accepted"] else None,
                "boolean_projection": projection,
                "gold": gold.as_dict(),
                "correct": correct,
            }
        )
    judged = {row["llm_call_id"] for row in rows}
    unjudged = [
        {"llm_call_id": key, "gold": condition_gold(record.get("state"), items, orders).as_dict()}
        for key, record in inputs.items()
        if key not in judged
    ]
    measures = list(rows[0]["correct"]) if rows else []
    return {
        "schema_id": SCORE_SCHEMA_ID,
        "task_id": payload["case"]["id"],
        "when": payload["verification_intervention"]["when"],
        "primitive": primitive,
        "planned_gold": planned_gold(payload).as_dict(),
        "judgments": rows,
        "unjudged_inputs": unjudged,
        "summary": {
            "judgments": len(rows),
            "accepted": sum(1 for row in rows if row["accepted"]),
            "measurable": sum(1 for row in rows if row["gold"]["measurable"]),
            "not_measurable": sum(1 for row in rows if not row["gold"]["measurable"]),
            "correct": {
                measure: sum(1 for row in rows if row["correct"][measure] is True)
                for measure in measures
            },
            "unjudged_inputs": len(unjudged),
        },
    }


def _focus_choices(values: Sequence[str]) -> dict[tuple[str, str], str]:
    choices: dict[tuple[str, str], str] = {}
    for value in values:
        parts = value.split(":")
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"focus {value!r} must be SOURCE:CELL:ITEM")
        key = (parts[0], parse_cell(parts[1]))
        if key in choices:
            raise ValueError(f"focus for {parts[0]}:{key[1]} repeats")
        choices[key] = parts[2]
    return choices


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Noul 2x2 E2E cells: build injected tasks or score a finished trial."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write payloads, labels.jsonl and manifest.json")
    build.add_argument("--source", action="append", required=True, metavar="FILE[#CASE]")
    build.add_argument("--out", type=Path, required=True, help="new directory; never overwritten")
    build.add_argument("--cells", nargs="+", default=list(DEFAULT_CELLS), metavar="CELL")
    build.add_argument("--focus", action="append", default=[], metavar="SOURCE:CELL:ITEM")
    build.add_argument("--example", action="store_true", help="mark the manifest as an example")
    score = commands.add_parser("score", help="score one trial's verification.json")
    score.add_argument("--verification", type=Path, required=True)
    score.add_argument("--payload", type=Path, required=True)
    score.add_argument("--primitive", choices=("choice", "noul"))
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            sources = [source for spec in args.source for source in load_sources(spec)]
            manifest = build_workload(
                sources,
                args.out,
                cells=args.cells,
                focus=_focus_choices(args.focus),
                example=args.example,
            )
            report: dict[str, Any] = {
                key: manifest[key]
                for key in (
                    "cells",
                    "cell_counts",
                    "example",
                    "labels_sha256",
                    "oracle_sha256",
                    "ordered_task_ids",
                    "workload_ids_sha256",
                )
            }
            report["manifest_sha256"] = hashlib.sha256(
                (args.out / "manifest.json").read_bytes()
            ).hexdigest()
        else:
            raw_payload = args.payload.read_bytes()
            raw_verification = args.verification.read_bytes()
            report = score_trial(
                json.loads(raw_verification), json.loads(raw_payload), primitive=args.primitive
            )
            report["payload_sha256"] = hashlib.sha256(raw_payload).hexdigest()
            report["verification_sha256"] = hashlib.sha256(raw_verification).hexdigest()
    except (OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
