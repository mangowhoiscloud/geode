"""Frozen rule oracle for authored verdict-panel inbox states.

Gold is a function of the structured answer, the observed lookups and the
fixture row only. This module is hashed into every panel manifest; builder I/O
lives elsewhere so its changes never alter the oracle digest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

C_KINDS = frozenset(
    {"status_conflict", "wrong_target", "answered_ambiguous", "unsupported_action_claim"}
)
M_KINDS = frozenset({"unobserved_status"})
ITEM_KINDS = C_KINDS | M_KINDS | {"correct"}
ACTION_STATUSES = frozenset({"cancelled", "refunded"})
# Score controlled-pool grades by rule cell (02 §C5, 05 §2.3).
POOL_GRADES = {(False, False): 3, (False, True): 2, (True, False): 0, (True, True): 0}


def verdict_for(contradiction: bool, missing: bool) -> str:
    """Map the two conditions to the frozen verdict precedence."""
    if contradiction:
        return "contradicted"
    return "insufficient_evidence" if missing else "supported"


def observed_statuses(
    orders: Mapping[str, str], lookups: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    """Return order ID → status for every order any recorded lookup returned."""
    observed: dict[str, str] = {}
    for call in lookups:
        for entry in call["items"]:
            order_id = entry["order_id"]
            observed[order_id] = orders[order_id]
    return observed


def item_kind(
    expected: Mapping[str, Any],
    answer: Mapping[str, Any],
    observed: Mapping[str, str],
    status_words: frozenset[str],
) -> str:
    """Classify one answer item against its fixture row (PANEL-SCHEMA §3).

    ``unclassified`` means the author used a shape outside the frozen taxonomy;
    the builder rejects that state instead of guessing its gold.
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


@dataclass(frozen=True)
class RuleGold:
    has_contradiction: bool
    missing_evidence: bool
    verdict: str
    item_kinds: dict[str, str]


def rule_gold(cluster: Mapping[str, Any], state: Mapping[str, Any]) -> RuleGold:
    """Recompute an inbox state's condition gold from its answer and lookups."""
    orders = cluster["orders"]
    items = cluster["case"]["items"]
    observed = observed_statuses(orders, state["lookups"])
    status_words = frozenset(orders.values())
    answers = state["answer"]["items"]
    if [row["id"] for row in answers] != [row["id"] for row in items]:
        raise ValueError("answer must list every case item in order")
    kinds = {
        row["id"]: item_kind(expected, row, observed, status_words)
        for expected, row in zip(items, answers, strict=True)
    }
    contradiction = any(kind in C_KINDS for kind in kinds.values())
    missing = any(kind in M_KINDS for kind in kinds.values())
    return RuleGold(contradiction, missing, verdict_for(contradiction, missing), kinds)
