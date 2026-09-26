#!/usr/bin/env python3
"""Derived analysis tables for one closed Harbor decision-handoff phase.

Native Harbor results, append-only attempts, the digest-bound analysis and the
retained agent exports remain the authorities. This module projects them into
four read-only views:

- ``call_ledger``: one row per recorded LLM attempt;
- ``e2e_trials``: one row per frozen planned cell, invalid cells included;
- ``e2e_pairs``: one row per ``(case_id, repetition)`` LLM|Jev pair;
- ``primitive_summary``: one row per arm label plus an ``all`` row.

Unknown stays ``None`` (JSON ``null``, empty CSV cell); an observed zero stays
``0``. A missing or non-positive latency is ``None`` because the durable
activity projection stores an absent duration as ``0.0``. Every row names its
source file, JSON pointer and SHA-256.

The three cost fields are separate authorities and are never added together:
``subscription_api_equivalent_estimate_usd`` (Astra subscription usage priced
with the frozen API reference; not a bill), ``typesafe_price_estimate_usd``
(Jev published input tariff; not a bill) and ``actual_billed_usd`` (``None``
until a provider billing export is reconciled by request identity).

Usage:
    python scripts/eval/handoff_tables.py <phase-dir> --out <new-dir> \\
        --primitive choice|noul|score|verdict [--arm-label a=llm --arm-label b=jev] \\
        [--replay-preselected <trial>] [--independent-units N] \\
        [--billing-export <export.jsonl|export.csv> --billing-source <label>]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from scripts.eval.contract import _strict_json_loads, validate_attempts, validate_run_spec

TABLES = ("call_ledger", "e2e_trials", "e2e_pairs", "primitive_summary")
COST_FIELDS = (
    "subscription_api_equivalent_estimate_usd",
    "typesafe_price_estimate_usd",
    "actual_billed_usd",
)
_COUNTERS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "cache_write_1h_tokens",
    "reasoning_tokens",
)
_ROUTE_COUNTERS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
_ROLES = {
    "agentic_loop": "root",
    "cognitive_reflection": "reflection",
    "turn_verification": "final_judge",
    "structured_decision": "helper",
    "candidate_judge": "selector",
}
_ROUTE_KEYS = {"openai": "astra", "typesafe": "jev"}
_BURDEN = (
    "judgment_attempts",
    "replan_requests",
    "root_requests_consuming_feedback",
    "helper_invocations",
    "lookup_attempt_count",
    "extra_lookup_count",
    "wrong_target_lookup_count",
    "rejected_lookup_count",
    "false_completion_count",
    "judge_false_acceptance",
    "held_delivery",
    "repaired_success",
)
_DEFAULT_ARM_LABELS = {"a": "llm", "b": "jev", "a0": "root_only"}


@dataclass
class _Sources:
    """Read retained evidence once and remember each file's digest."""

    root: Path
    read: dict[str, str] = field(default_factory=dict)

    def _file(self, relative: str) -> Path | None:
        path = self.root / relative
        if path.is_symlink() or not path.is_file():
            return None
        return path

    def load(self, relative: str) -> Any:
        path = self._file(relative)
        if path is None:
            return None
        raw = path.read_bytes()
        self.read[relative] = hashlib.sha256(raw).hexdigest()
        return _strict_json_loads(raw.decode("utf-8"), label=relative)

    def sha(self, relative: str) -> str | None:
        path = self._file(relative)
        if path is None:
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.read.setdefault(relative, digest)
        return digest


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return None


def _seconds(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _seconds_from_ms(value: Any) -> float | None:
    number = _number(value)
    # A durable activity row stores an absent duration as 0.0; never report it.
    return number / 1000 if number is not None and number > 0 else None


def _iso_utc(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    return datetime.fromtimestamp(number, UTC).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text_sha256(value: Any) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if isinstance(value, str) and value else None


def _decimal_sum(values: Sequence[float]) -> float:
    return float(sum((Decimal(str(value)) for value in values), Decimal(0)))


def _index(rows: Any, key: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get(key), str) and row[key]:
            index.setdefault(row[key], []).append(row)
    return index


def _native_distribution(
    native: Any,
) -> tuple[str | None, float | None, float | None, float | None]:
    """Return probabilities JSON, max label probability and Noul probabilities."""
    if not isinstance(native, dict):
        return None, None, None, None
    probabilities = native.get("probabilities")
    if (
        isinstance(probabilities, dict)
        and probabilities
        and all(_number(value) is not None for value in probabilities.values())
    ):
        values = [float(value) for value in probabilities.values()]
        return _json(probabilities), max(values), None, None
    noul = {
        key: float(answer["noul"])
        for key in ("has_contradiction", "missing_evidence")
        if isinstance(answer := native.get(key), dict) and _number(answer.get("noul")) is not None
    }
    if noul:
        return (
            _json(noul),
            None,
            noul.get("has_contradiction"),
            noul.get("missing_evidence"),
        )
    return None, None, None, None


def _price_references() -> dict[str, tuple[str | None, str | None]]:
    from evals.benchmarks.decision_handoff_runtime import PRICE_REFERENCE

    return {
        "openai": (PRICE_REFERENCE.get("checked_at"), PRICE_REFERENCE["astra_api"]["source"]),
        "typesafe": (
            PRICE_REFERENCE["typesafe"].get("checked_at"),
            PRICE_REFERENCE["typesafe"]["source"],
        ),
    }


def _call_rows(
    sources: _Sources,
    trial_rel: str,
    keys: Mapping[str, Any],
    prices: Mapping[str, tuple[str | None, str | None]],
) -> list[dict[str, Any]]:
    runtime = _object(sources.load(f"{trial_rel}/agent/runtime-result.json"))
    handoff = _object(sources.load(f"{trial_rel}/agent/handoff-result.json"))
    events = sources.load(f"{trial_rel}/agent/call-events.json")
    verification = _object(sources.load(f"{trial_rel}/agent/verification.json"))
    receipts = sources.load(f"{trial_rel}/agent/handoff.json")

    spine: list[dict[str, Any]] = []
    spine_ref: str | None = None
    pointer_base: str | None = None
    recorded = _object(runtime.get("usage")).get("recorded_attempts")
    accounting = handoff.get("call_accounting")
    if isinstance(recorded, list):
        spine = [row for row in recorded if isinstance(row, dict)]
        spine_ref, pointer_base = (
            f"{trial_rel}/agent/runtime-result.json",
            "/usage/recorded_attempts",
        )
    elif isinstance(accounting, list):
        spine = [row for row in accounting if isinstance(row, dict)]
        spine_ref, pointer_base = f"{trial_rel}/agent/handoff-result.json", "/call_accounting"
    accounting_index = _index(accounting, "llm_attempt_id")
    ended = [
        event
        for event in (events if isinstance(events, list) else [])
        if isinstance(event, dict) and event.get("action") == "llm.call.ended"
    ]
    ended_index = _index(ended, "llm_attempt_id")
    judgments = _index(verification.get("judgments"), "llm_call_id")
    helper_results = _index(
        [
            row
            for row in (receipts if isinstance(receipts, list) else [])
            if isinstance(row, dict)
            and row.get("kind") == "tool_result"
            and row.get("tool") == "analyze_request"
        ],
        "tool_call_id",
    )
    spine_sha = sources.sha(spine_ref) if spine_ref else None
    rows = []
    for position, attempt in enumerate(spine):
        attempt_id = attempt.get("llm_attempt_id")
        account_matches = accounting_index.get(attempt_id, []) if attempt_id else []
        account = account_matches[0] if len(account_matches) == 1 else None
        acc: dict[str, Any] = account or {}
        event_matches = ended_index.get(attempt_id, []) if attempt_id else []
        event = event_matches[0] if len(event_matches) == 1 else None
        payload = _object(event.get("payload")) if event else {}
        recorded_usage = _object(attempt.get("usage"))
        account_usage = _object(acc.get("usage"))
        counters = {
            name: _count(
                recorded_usage[name] if name in recorded_usage else account_usage.get(name)
            )
            for name in _COUNTERS
        }
        if account is not None:
            total = _count(acc.get("total_tokens"))
            contradictory = acc.get("contradictory_usage")
        else:
            inp, out = counters["input_tokens"], counters["output_tokens"]
            total = inp + out if inp is not None and out is not None else None
            contradictory = None
        latency_field = next(
            (name for name in ("duration_ms", "latency_ms") if name in payload), None
        )
        latency = _seconds_from_ms(payload[latency_field]) if latency_field else None
        purpose = attempt.get("purpose") or acc.get("purpose")
        provider = attempt.get("provider") or payload.get("provider")
        accepted = verdict = probabilities = None
        q_max = p_contradiction = p_missing = None
        if purpose == "turn_verification":
            matches = judgments.get(attempt.get("llm_call_id") or "", [])
            if len(matches) == 1:
                judgment = matches[0]
                accepted = (
                    judgment.get("accepted") if type(judgment.get("accepted")) is bool else None
                )
                verdict = (
                    judgment.get("verdict") if isinstance(judgment.get("verdict"), str) else None
                )
                probabilities, q_max, p_contradiction, p_missing = _native_distribution(
                    judgment.get("native_answer")
                )
        elif purpose == "structured_decision":
            matches = helper_results.get(attempt.get("tool_call_id") or "", [])
            if len(matches) == 1:
                result = matches[0].get("result")
                accepted = isinstance(result, dict) and not result.get("error")
                inner = result.get("result") if isinstance(result, dict) else None
                primitives = inner.get("primitives") if isinstance(inner, dict) else None
                probabilities = _json(primitives) if isinstance(primitives, dict) else None
        bounds = acc.get("subscription_api_equivalent_bounds_usd")
        low, high = (
            (_number(bounds[0]), _number(bounds[1]))
            if isinstance(bounds, list) and len(bounds) == 2
            else (None, None)
        )
        price_date, price_source = prices.get(str(provider), (None, None))
        response_id = acc.get("response_id") or payload.get("response_id")
        rows.append(
            {
                **keys,
                "session_id": attempt.get("session_id"),
                "llm_call_id": attempt.get("llm_call_id"),
                "llm_attempt_id": attempt_id,
                "tool_call_id": attempt.get("tool_call_id"),
                "source_event_id": attempt.get("source_event_id"),
                "purpose": purpose,
                "role": _ROLES.get(str(purpose), purpose),
                "model": attempt.get("model") or acc.get("model"),
                "response_model": attempt.get("response_model") or acc.get("response_model"),
                "provider": provider,
                "route": attempt.get("source") or payload.get("source"),
                "route_key": _ROUTE_KEYS.get(str(provider), "other"),
                "effort": attempt.get("effort") or payload.get("effort"),
                "occurred_at_utc": _iso_utc(attempt.get("occurred_at")),
                "latency_s": latency,
                "latency_field": latency_field,
                **counters,
                "total_tokens": total,
                "contradictory_usage": contradictory if type(contradictory) is bool else None,
                "error_type": attempt.get("error_type") or acc.get("error_type"),
                "response_id_sha256": _text_sha256(response_id),
                "accepted": accepted,
                "verdict": verdict,
                "probabilities_json": probabilities,
                "q_max": q_max,
                "noul_p_contradiction": p_contradiction,
                "noul_p_missing": p_missing,
                "subscription_api_equivalent_estimate_usd": _number(
                    acc.get("subscription_api_equivalent_estimate_usd")
                ),
                "subscription_api_equivalent_bounds_low_usd": low,
                "subscription_api_equivalent_bounds_high_usd": high,
                "typesafe_price_estimate_usd": _number(acc.get("typesafe_price_estimate_usd")),
                "typesafe_price_estimate_us_cents": _number(
                    acc.get("typesafe_price_estimate_us_cents")
                ),
                # The retained reported_cost_usd is always null; never infer a bill.
                "actual_billed_usd": None,
                "billing_status": "unknown",
                "billing_source_sha256": None,
                "price_reference_date": price_date,
                "price_reference_source": price_source,
                "join_complete": account is not None and event is not None,
                "source_ref": spine_ref,
                "source_pointer": f"{pointer_base}/{position}",
                "source_sha256": spine_sha,
            }
        )
    return rows


def load_billing_export(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Read a provider billing export without trusting unlabeled fields."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    rows: list[Any]
    if path.suffix == ".jsonl":
        rows = [
            _strict_json_loads(line, label=f"{path.name}:{number}")
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
    elif path.suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
    else:
        raise ValueError("billing export must be .jsonl or .csv")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("billing export rows must be objects")
    return [dict(row) for row in rows], digest


def reconcile_billing(
    calls: Sequence[Mapping[str, Any]],
    export_rows: Sequence[Mapping[str, Any]],
    *,
    export_sha256: str,
    source: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach provider-billed USD by request identity; unmatched calls stay unknown.

    The export must name each request identity and USD amount. Account-balance
    deltas, credit screens and tariff calculations are not accepted inputs.
    """
    index: dict[str, tuple[Decimal, str | None]] = {}
    for number, row in enumerate(export_rows):
        request_id = row.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError(f"billing row {number} lacks a request identity")
        if (row.get("currency") or "USD") != "USD":
            raise ValueError("billing reconciliation does not convert currencies")
        try:
            amount = Decimal(str(row.get("amount_usd")))
        except InvalidOperation as error:
            raise ValueError(f"billing row {number} has no numeric USD amount") from error
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"billing row {number} has an invalid USD amount")
        key = hashlib.sha256(request_id.encode()).hexdigest()
        if key in index:
            raise ValueError("billing export repeats a request identity")
        provider = row.get("provider")
        index[key] = (amount, provider if isinstance(provider, str) and provider else None)
    matched: set[str] = set()
    reconciled: list[dict[str, Any]] = []
    total = Decimal(0)
    for call in calls:
        row = dict(call)
        call_key = call.get("response_id_sha256")
        hit = index.get(call_key) if isinstance(call_key, str) else None
        if hit is not None:
            amount, provider = hit
            if provider is not None and provider != call.get("provider"):
                raise ValueError("billing provider differs from the observed call provider")
            row.update(
                actual_billed_usd=float(amount),
                billing_status="reconciled",
                billing_source_sha256=export_sha256,
            )
            matched.add(str(call_key))
            total += amount
        reconciled.append(row)
    unmatched_calls = sum(row["billing_status"] != "reconciled" for row in reconciled)
    receipt = {
        "kind": "billing-reconciliation",
        "source": source,
        "export_sha256": export_sha256,
        "matched_calls": len(reconciled) - unmatched_calls,
        "unmatched_calls": unmatched_calls,
        "unmatched_export_rows": len(index) - len(matched),
        "matched_amount_usd": str(total),
        "complete": unmatched_calls == 0,
        "total_actual_billed_usd": str(total) if unmatched_calls == 0 else None,
        "rules": [
            "Join key is the SHA-256 of the provider request identity.",
            "Unmatched calls keep actual_billed_usd=null and billing_status=unknown.",
            "Tariff estimates, API-equivalent values and balance deltas are never billing inputs.",
        ],
    }
    return reconciled, receipt


def _cell_keys(phase: str, primitive: str, run_id: str, revision: str) -> dict[str, Any]:
    return {"run_id": run_id, "phase": phase, "primitive": primitive, "source_revision": revision}


def _attempts_by_trial(attempts: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    mapping: dict[str, list[Mapping[str, Any]]] = {}
    for attempt in attempts:
        if attempt["change"]["surface"] == "analysis-only":
            continue
        trials = {
            parts[1]
            for ref in attempt["evidence_refs"]
            if len(parts := Path(str(ref["path"])).parts) > 2 and parts[0] == "trials"
        }
        if len(trials) == 1:
            mapping.setdefault(next(iter(trials)), []).append(attempt)
    for rows in mapping.values():
        rows.sort(key=lambda row: int(row["sequence"]))
    return mapping


def _route_totals(calls: Sequence[Mapping[str, Any]], complete: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for route in ("astra", "jev"):
        route_calls = [call for call in calls if call["route_key"] == route]
        result[f"{route}_calls"] = len(route_calls)
        for counter in _ROUTE_COUNTERS:
            values = [call[counter] for call in route_calls]
            observed = [value for value in values if value is not None]
            result[f"{route}_{counter}_total"] = (
                sum(observed) if complete and len(observed) == len(values) else None
            )
            result[f"{route}_{counter}_observed_sum"] = sum(observed)
            result[f"{route}_{counter}_missing_calls"] = len(values) - len(observed)
    return result


def _cost_totals(calls: Sequence[Mapping[str, Any]], complete: bool) -> dict[str, Any]:
    applicable = {
        "subscription_api_equivalent_estimate_usd": [
            call
            for call in calls
            if call["provider"] == "openai" and call["route"] == "subscription"
        ],
        "typesafe_price_estimate_usd": [call for call in calls if call["provider"] == "typesafe"],
        "actual_billed_usd": list(calls),
    }
    result: dict[str, Any] = {}
    for name, rows in applicable.items():
        values = [row[name] for row in rows]
        observed = [value for value in values if value is not None]
        result[f"{name}_total"] = (
            _decimal_sum(observed) if complete and len(observed) == len(values) else None
        )
        result[f"{name}_observed_sum"] = _decimal_sum(observed)
        result[f"{name}_missing_calls"] = len(values) - len(observed)
    return result


def _trial_row(
    sources: _Sources,
    cell: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
    keys: Mapping[str, Any],
    arm_labels: Mapping[str, str],
    preselected: set[str],
) -> dict[str, Any]:
    trial = str(cell["trial_name"])
    rel = f"trials/{trial}"
    receipt = _object(sources.load(f"{rel}/trial-receipt.json"))
    handoff = _object(sources.load(f"{rel}/agent/handoff-result.json"))
    observation = _object(sources.load(f"{rel}/observation-check.json"))
    cleanup = _object(sources.load(f"{rel}/cleanup-observation.json"))
    replay = _object(sources.load(f"{rel}/replay-check.json"))
    native = _object(sources.load(f"{rel}/result.json"))
    verifier = _object(sources.load(f"{rel}/verifier/verifier-receipt.json"))
    verification = _object(sources.load(f"{rel}/agent/verification.json"))
    receipts = sources.load(f"{rel}/agent/handoff.json")
    attempt = attempts[-1] if attempts else None
    validity = attempt["validity"] if attempt else None
    outcome = attempt["outcome"] if attempt else None
    engine = cell.get("verification_engine")
    arm = str(cell.get("arm") or handoff.get("arm") or "")
    label = engine if isinstance(engine, str) and engine else arm_labels.get(arm, arm or "unknown")

    rewards = _object(native.get("verifier_result")).get("rewards")
    reward = (
        next(iter(rewards.values())) if isinstance(rewards, dict) and len(rewards) == 1 else None
    )
    verdicts = (
        handoff.get("native_verify") if isinstance(handoff.get("native_verify"), list) else []
    )
    final_action = (
        verdicts[-1].get("action") if verdicts and isinstance(verdicts[-1], dict) else None
    )
    semantic = _object(receipt.get("semantic_metrics"))
    oracle = _object(handoff.get("oracle"))
    # bool is an int subclass: counters and flags keep their observed type.
    burden = {
        name: semantic[name] if isinstance(semantic.get(name), int) else oracle.get(name)
        for name in _BURDEN
    }
    burden = {name: value if isinstance(value, int) else None for name, value in burden.items()}

    strict: bool | None = None
    if validity == "valid":
        checks = (
            handoff.get("passed"),
            None if reward is None else reward == 1,
            None if final_action is None else final_action == "turn.verify.passed",
            None
            if burden["wrong_target_lookup_count"] is None
            else burden["wrong_target_lookup_count"] == 0,
            None if burden["extra_lookup_count"] is None else burden["extra_lookup_count"] == 0,
            None
            if burden["false_completion_count"] is None
            else burden["false_completion_count"] == 0,
        )
        strict = None if any(check is None for check in checks) else all(checks)

    jev_calls = [call for call in calls if call["provider"] == "typesafe"]
    if label != "jev":
        status = "n/a"
    elif not calls:
        status = "unobserved"
    elif not jev_calls:
        status = "missing"  # e.g. a silent LLM route; never a Jev success
    elif any(call["error_type"] for call in jev_calls):
        status = "transport_error"
    elif any(call["accepted"] is False for call in jev_calls):
        status = "rejected"
    elif all(call["accepted"] is True for call in jev_calls):
        status = "admitted"
    else:
        status = "unverified"

    projection = next(
        (
            row.get("boolean_projection")
            for row in verification.get("judgments", [])
            if isinstance(row, dict) and row.get("accepted") is True
        ),
        None,
    )
    truth = _object(cell.get("noul_truth"))
    judge_latency = [call["latency_s"] for call in calls if call["role"] == "final_judge"]
    judge_observed = [value for value in judge_latency if value is not None]
    judge_complete = bool(judge_latency) and len(judge_observed) == len(judge_latency)
    helpers = [
        row.get("elapsed_seconds")
        for row in (receipts if isinstance(receipts, list) else [])
        if isinstance(row, dict)
        and row.get("kind") == "tool_result"
        and row.get("tool") == "analyze_request"
    ]
    helper_seconds = [_seconds(value) for value in helpers]
    usage = _object(handoff.get("usage"))
    usage_complete = bool(
        calls
        and usage.get("attempt_pairing_complete") is True
        and handoff.get("source_snapshot_complete") is True
        and all(call["join_complete"] for call in calls)
    )
    source_ref = f"{rel}/trial-receipt.json" if receipt else f"{rel}/result.json"
    return {
        **keys,
        "cell_index": cell.get("index"),
        "trial_name": trial,
        "case_id": cell.get("case_id"),
        "repetition": cell.get("repetition"),
        "position": cell.get("position"),
        "arm_label": label,
        "schedule_arm": cell.get("arm"),
        "runtime_arm": handoff.get("arm"),
        "verification_engine": engine,
        "verification_primitive": handoff.get(
            "verification_primitive", "choice" if engine else None
        ),
        "attempt_id": attempt["attempt_id"] if attempt else None,
        "attempt_count": len(attempts),
        "validity": validity,
        "outcome": outcome,
        "failure_class": attempt["failure_class"] if attempt else None,
        "selected_for_analysis": attempt["selected_for_analysis"] if attempt else None,
        "error_type": receipt.get("error_type"),
        "collection_error_type": receipt.get("collection_error_type"),
        "execution_started": receipt.get("execution_started", True if handoff else None),
        "observation_valid": observation.get("observation_valid"),
        "cache_complete": observation.get("cache_complete"),
        "source_reconciled": _object(observation.get("source_reconciliation")).get("reconciled"),
        "cleanup_complete": cleanup.get("complete"),
        "replay_complete": replay.get("complete"),
        "native_reward": _number(reward),
        "verifier_passed": verifier.get("passed") if type(verifier.get("passed")) is bool else None,
        "oracle_passed": oracle.get("passed") if type(oracle.get("passed")) is bool else None,
        "runtime_passed": handoff.get("passed") if type(handoff.get("passed")) is bool else None,
        "native_final_verdict": {
            "turn.verify.passed": "passed",
            "turn.verify.failed": "failed",
        }.get(str(final_action)),
        "strict_success": strict,
        "jev_decision_status": status,
        "jev_success_credited": (
            label == "jev" and validity == "valid" and outcome == "passed" and status == "admitted"
        )
        if label == "jev"
        else None,
        **burden,
        "noul_pred_contradiction": _object(projection).get("has_contradiction"),
        "noul_pred_missing": _object(projection).get("missing_evidence"),
        "noul_true_contradiction": truth.get("has_contradiction"),
        "noul_true_missing": truth.get("missing_evidence"),
        "runtime_elapsed_s": _seconds(handoff.get("elapsed_seconds")),
        "host_elapsed_s": _seconds(receipt.get("host_elapsed_seconds")),
        "judge_calls": len(judge_latency),
        "judge_latency_sum_s": sum(judge_observed) if judge_complete else None,
        "judge_latency_median_s": statistics.median(judge_observed) if judge_complete else None,
        "judge_latency_missing_calls": len(judge_latency) - len(judge_observed),
        "helper_tool_s": (
            sum(value for value in helper_seconds if value is not None)
            if helper_seconds and all(value is not None for value in helper_seconds)
            else None
        ),
        "usage_complete": usage_complete,
        **_route_totals(calls, usage_complete),
        **_cost_totals(calls, usage_complete),
        "trial_receipt_sha256": sources.sha(f"{rel}/trial-receipt.json"),
        "result_sha256": sources.sha(f"{rel}/result.json"),
        "geode_trajectory_sha256": sources.sha(f"{rel}/agent/geode-trajectory.json"),
        "recording_cast_sha256": sources.sha(f"{rel}/agent/recording.cast"),
        "replay_preselected": bool(cell.get("replay_preselected")) or trial in preselected,
        "source_ref": source_ref,
        "source_pointer": "",
        "source_sha256": sources.sha(source_ref),
    }


def _delta(llm: Mapping[str, Any], jev: Mapping[str, Any], name: str, *, complete: bool) -> Any:
    """Jev minus LLM for one complete valid pair; otherwise unknown."""
    first, second = llm.get(name), jev.get(name)
    return second - first if complete and first is not None and second is not None else None


def _pair_rows(
    trials: Sequence[Mapping[str, Any]], keys: Mapping[str, Any]
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for trial in trials:
        if trial["case_id"] is None or trial["repetition"] is None:
            continue
        groups.setdefault((str(trial["case_id"]), int(trial["repetition"])), []).append(trial)
    rows = []
    for (case_id, repetition), members in sorted(groups.items()):
        llm = [row for row in members if row["arm_label"] == "llm"]
        jev = [row for row in members if row["arm_label"] == "jev"]
        row: dict[str, Any] = {
            **keys,
            "case_id": case_id,
            "repetition": repetition,
            "llm_trial": llm[0]["trial_name"] if len(llm) == 1 else None,
            "jev_trial": jev[0]["trial_name"] if len(jev) == 1 else None,
            "first_arm": next((m["arm_label"] for m in members if m["position"] == 0), None),
            "replay_selected": any(m["replay_preselected"] for m in members),
        }
        complete = (
            len(llm) == 1
            and len(jev) == 1
            and llm[0]["validity"] == "valid"
            and jev[0]["validity"] == "valid"
        )
        row["pair_complete"] = complete
        a, b = (llm[0], jev[0]) if len(llm) == 1 and len(jev) == 1 else ({}, {})
        row["llm_passed"] = a.get("outcome") == "passed" if a.get("validity") == "valid" else None
        row["jev_passed"] = b.get("outcome") == "passed" if b.get("validity") == "valid" else None
        row["success_delta"] = int(row["jev_passed"]) - int(row["llm_passed"]) if complete else None
        for name, source in (
            ("runtime_s_delta", "runtime_elapsed_s"),
            ("host_s_delta", "host_elapsed_s"),
            ("judge_latency_s_delta", "judge_latency_sum_s"),
        ):
            row[name] = _delta(a, b, source, complete=complete)
        for route in ("astra", "jev"):
            for counter in ("input_tokens", "output_tokens"):
                row[f"{route}_{counter}_delta"] = _delta(
                    a, b, f"{route}_{counter}_total", complete=complete
                )
        for cost in COST_FIELDS:
            row[f"{cost}_delta"] = _delta(a, b, f"{cost}_total", complete=complete)
        row["llm_trial_receipt_sha256"] = a.get("trial_receipt_sha256")
        row["jev_trial_receipt_sha256"] = b.get("trial_receipt_sha256")
        # Derived from the two e2e_trials rows named above; tables-manifest.json
        # binds that table's bytes.
        row["source_ref"] = "e2e_trials.jsonl"
        row["source_pointer"] = None
        row["source_sha256"] = None
        rows.append(row)
    return rows


def _summary_rows(
    trials: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
    keys: Mapping[str, Any],
    *,
    run_spec: Mapping[str, Any],
    analysis: Mapping[str, Any] | None,
    independent_units: int | None,
    digests: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    primary_name = run_spec["study"]["primary_metric"]["name"]
    primary = next(
        (m for m in (analysis or {}).get("metrics", []) if m.get("name") == primary_name), None
    )
    labels = sorted({str(trial["arm_label"]) for trial in trials})
    rows = []
    total_fields = [
        name
        for name in (trials[0].keys() if trials else [])
        if name.endswith(("_total", "_observed_sum", "_missing_calls", "_calls"))
        and not name.startswith("judge_")
    ]
    for label in [*labels, "all"]:
        members = list(trials) if label == "all" else [t for t in trials if t["arm_label"] == label]
        member_names = {t["trial_name"] for t in members}
        attempted = [t for t in members if t["validity"] is not None]
        valid = [t for t in members if t["validity"] == "valid"]
        passed = [t for t in valid if t["outcome"] == "passed"]
        row: dict[str, Any] = {
            **keys,
            "arm_label": label,
            "planned_cells": len(members),
            "attempted": len(attempted),
            "valid": len(valid),
            "invalid": sum(t["validity"] in ("invalid", "aborted") for t in members),
            "unobserved": len(members) - len(attempted),
            "passed": len(passed),
            "failed": sum(t["outcome"] == "failed" for t in valid),
            "success_rate_valid": len(passed) / len(valid) if valid else None,
            "success_rate_denominator": len(valid),
            "primary_name": primary_name if label == "all" else None,
            "primary_value": primary.get("value") if label == "all" and primary else None,
            "primary_numerator": primary.get("numerator") if label == "all" and primary else None,
            "primary_denominator": primary.get("denominator")
            if label == "all" and primary
            else None,
            "independent_units": independent_units,
            "jev_contract_errors": sum(t["jev_decision_status"] == "rejected" for t in members),
            "jev_transport_errors": sum(
                t["jev_decision_status"] == "transport_error" for t in members
            ),
            "jev_missing_or_fallback": sum(
                t["jev_decision_status"] in ("missing", "unverified") for t in members
            ),
            "is_admission_phase": keys["phase"] == "admission",
            **digests,
        }
        for name, source in (("runtime", "runtime_elapsed_s"), ("host", "host_elapsed_s")):
            values = [t[source] for t in valid]
            observed = [value for value in values if value is not None]
            complete = bool(values) and len(observed) == len(values)
            row[f"median_{name}_s"] = statistics.median(observed) if complete else None
            row[f"median_{name}_s_observed"] = statistics.median(observed) if observed else None
            row[f"median_{name}_s_n"] = len(observed)
        judge = [
            call["latency_s"]
            for call in calls
            if call["role"] == "final_judge" and call["trial_name"] in member_names
        ]
        judge_observed = [value for value in judge if value is not None]
        row["median_judge_latency_s"] = (
            statistics.median(judge_observed)
            if judge and len(judge_observed) == len(judge)
            else None
        )
        row["median_judge_latency_s_observed"] = (
            statistics.median(judge_observed) if judge_observed else None
        )
        row["judge_latency_n"] = len(judge_observed)
        for name in total_fields:
            values = [t[name] for t in attempted]
            if not name.endswith("_total"):
                row[name] = _decimal_sum(values) if "_usd" in name else sum(values)
            else:
                complete = bool(values) and all(value is not None for value in values)
                row[name] = (
                    (_decimal_sum(values) if "_usd" in name else sum(values)) if complete else None
                )
        row["source_ref"] = "e2e_trials.jsonl"
        row["source_pointer"] = None
        row["source_sha256"] = None
        rows.append(row)
    return rows


def _columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        columns.extend(name for name in row if name not in columns)
    return columns


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return _json(value)
    return repr(value) if isinstance(value, float) else str(value)


def _write_exclusive(path: Path, text: str) -> str:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_tables(
    phase_dir: Path,
    out_dir: Path,
    *,
    primitive: str,
    arm_labels: Mapping[str, str] | None = None,
    replay_preselected: Sequence[str] = (),
    independent_units: int | None = None,
    billing_export: Path | None = None,
    billing_source: str | None = None,
) -> dict[str, Any]:
    """Write the four derived tables and a digest manifest into a new directory."""
    phase_dir = phase_dir.resolve()
    sources = _Sources(phase_dir)
    run_spec = validate_run_spec(phase_dir / "run-spec.json")
    sources.sha("run-spec.json")
    attempts_path = phase_dir / "attempts.jsonl"
    attempts = validate_attempts(attempts_path) if attempts_path.is_file() else []
    sources.sha("attempts.jsonl")
    freeze = sources.load("freeze.json")
    analysis = sources.load("analysis.json")
    phase = str((freeze or {}).get("phase") or phase_dir.name)
    if freeze and isinstance(freeze.get("cells"), list):
        cells = [dict(cell) for cell in freeze["cells"]]
    else:
        trial_root = phase_dir / "trials"
        names = (
            sorted(p.name for p in trial_root.iterdir() if p.is_dir())
            if trial_root.is_dir()
            else []
        )
        cells = [{"trial_name": name} for name in names]
    if len({cell["trial_name"] for cell in cells}) != len(cells):
        raise ValueError("frozen cells repeat a trial name")
    keys = _cell_keys(
        phase,
        primitive,
        str(run_spec["run_id"]),
        str(run_spec["reproduction"]["geode"]["revision"]),
    )
    labels = {**_DEFAULT_ARM_LABELS, **(arm_labels or {})}
    prices = _price_references()
    by_trial = _attempts_by_trial(attempts)
    unknown_trials = set(by_trial) - {cell["trial_name"] for cell in cells}
    if unknown_trials:
        raise ValueError("attempts reference trials outside the frozen cells")
    calls: list[dict[str, Any]] = []
    call_groups: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        trial = str(cell["trial_name"])
        engine = cell.get("verification_engine")
        arm = str(cell.get("arm") or "")
        label = engine if isinstance(engine, str) and engine else labels.get(arm, arm or "unknown")
        rows = _call_rows(
            sources, f"trials/{trial}", {**keys, "trial_name": trial, "arm_label": label}, prices
        )
        call_groups[trial] = rows
        calls.extend(rows)
    billing_receipt = None
    if billing_export is not None:
        export_rows, export_sha = load_billing_export(billing_export)
        calls, billing_receipt = reconcile_billing(
            calls,
            export_rows,
            export_sha256=export_sha,
            source=billing_source or billing_export.name,
        )
        # Reconciliation preserves input order; regroup the same rows per trial.
        reconciled = iter(calls)
        call_groups = {
            trial: [next(reconciled) for _ in rows] for trial, rows in call_groups.items()
        }
    trials = [
        _trial_row(
            sources,
            cell,
            by_trial.get(str(cell["trial_name"]), []),
            call_groups[str(cell["trial_name"])],
            keys,
            labels,
            set(replay_preselected),
        )
        for cell in cells
    ]
    digests = {
        "run_spec_sha256": sources.sha("run-spec.json"),
        "attempts_sha256": sources.sha("attempts.jsonl"),
        "analysis_sha256": sources.sha("analysis.json"),
        "results_sha256": sources.sha("results.json"),
    }
    tables = {
        "call_ledger": calls,
        "e2e_trials": trials,
        "e2e_pairs": _pair_rows(trials, keys),
        "primitive_summary": _summary_rows(
            trials,
            calls,
            keys,
            run_spec=run_spec,
            analysis=analysis,
            independent_units=independent_units,
            digests=digests,
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=False)
    outputs = []
    for name in TABLES:
        rows = tables[name]
        jsonl = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            for row in rows
        )
        columns = _columns(rows)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})
        outputs.append(
            {
                "table": name,
                "rows": len(rows),
                "jsonl": f"{name}.jsonl",
                "jsonl_sha256": _write_exclusive(out_dir / f"{name}.jsonl", jsonl),
                "csv": f"{name}.csv",
                "csv_sha256": _write_exclusive(out_dir / f"{name}.csv", buffer.getvalue()),
            }
        )
    if billing_receipt is not None:
        receipt_text = (
            json.dumps(billing_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        billing_receipt["receipt_sha256"] = _write_exclusive(
            out_dir / "billing-reconciliation.json", receipt_text
        )
    manifest = {
        "kind": "derived-analysis-tables",
        "generator": "scripts/eval/handoff_tables.py",
        "run_id": keys["run_id"],
        "phase": phase,
        "primitive": primitive,
        "source_revision": keys["source_revision"],
        "inputs": [
            {"path": path, "sha256": digest} for path, digest in sorted(sources.read.items())
        ],
        "outputs": outputs,
        "billing_reconciliation": (
            {"path": "billing-reconciliation.json", "sha256": billing_receipt["receipt_sha256"]}
            if billing_receipt
            else None
        ),
        "semantics": {
            "null": "unknown or not measured; never zero",
            "csv_empty_cell": "null; use JSONL for exact types",
            "cost_fields": list(COST_FIELDS),
            "cost_rule": "three separate authorities; never summed together",
            "latency": "duration_ms or latency_ms converted to seconds; missing or <=0 is null",
            "denominators": "invalid cells remain rows; rates name their valid denominator",
        },
    }
    _write_exclusive(
        out_dir / "tables-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return manifest


def _labels(values: Sequence[str]) -> dict[str, str]:
    labels = {}
    for value in values:
        arm, separator, label = value.partition("=")
        if not separator or not arm or not label:
            raise ValueError("--arm-label must use ARM=LABEL")
        labels[arm] = label
    return labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--primitive", required=True, choices=("choice", "noul", "score", "verdict")
    )
    parser.add_argument("--arm-label", action="append", default=[])
    parser.add_argument("--replay-preselected", action="append", default=[])
    parser.add_argument("--independent-units", type=int)
    parser.add_argument("--billing-export", type=Path)
    parser.add_argument("--billing-source")
    args = parser.parse_args(argv)
    try:
        manifest = export_tables(
            args.phase_dir,
            args.out,
            primitive=args.primitive,
            arm_labels=_labels(args.arm_label),
            replay_preselected=args.replay_preselected,
            independent_units=args.independent_units,
            billing_export=args.billing_export,
            billing_source=args.billing_source,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(
            json.dumps({"exported": False, "error_type": type(error).__name__, "error": str(error)})
        )
        return 1
    print(
        json.dumps(
            {"exported": True, "tables": {o["table"]: o["rows"] for o in manifest["outputs"]}}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
