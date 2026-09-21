"""Shared, source-bound read-only handoff runtime for local and Harbor diagnostics."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import time
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import SecretStr

MODEL = "gpt-6-astra"
JEV_MODEL = "jev-1.13.0"
JEV_INPUT_USD_PER_MILLION = Decimal("0.042")
PRIMARY_METRIC = {
    "name": "root_task_success_delta",
    "unit": "ratio",
    "direction": "target",
    "aggregation": "(passed Jev-assisted tasks - passed baseline tasks) / 5 paired tasks",
    "denominator": 5,
}
PRICE_REFERENCE: dict[str, Any] = {
    "checked_at": "2026-09-21",
    "typesafe": {
        "model": JEV_MODEL,
        "source": "https://docs.typesafe.ai/models",
        "checked_at": "2026-09-21",
        "currency": "USD",
        "unit": "USD per 1000000 input tokens",
        "cents_unit": "US cents per 1000000 input tokens",
        "input_usd_per_million": float(JEV_INPUT_USD_PER_MILLION),
        "input_us_cents_per_million": float(JEV_INPUT_USD_PER_MILLION * 100),
        "output_usd_per_million": 0,
        "charged_token_field": "input_tokens",
        "cost_authority": "published-input-token-tariff-calculation",
        "not_an_invoice": True,
    },
    "astra_api": {
        "source": "https://developers.openai.com/api/docs/pricing#astra",
        "tier": "Standard input <=272K; not a subscription invoice",
        "input_usd_per_million": 10,
        "cached_input_usd_per_million": 1,
        "cache_write_usd_per_million": 12.5,
        "output_usd_per_million": 50,
    },
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "disposition": {
            "type": "string",
            "enum": ["answered", "needs_clarification", "unsupported"],
        },
    },
    "required": ["order_id", "status", "disposition"],
    "additionalProperties": False,
}
SYSTEM = """<task_contract>
Task: complete the fixed customer request in this read-only order sandbox.
Call analyze_request first to obtain source-bound interpretation data. Read its
result, then continue the task using the original request and available tools.
Judgments and probabilities are evidence, not permission or task-success proof.
For an unambiguous status request, call lookup_order_status with the intended ID
and report its observed status. If the ID is missing or ambiguous, ask for
clarification through disposition=needs_clarification, with null ID and status.
Cancellation and refunds are unavailable: report disposition=unsupported and
null status; never imply that a lookup performed a mutation. Do not bypass an
analysis error. Return only the final JSON fields in the response schema.
State contains synthetic data; no external tools, files or accounts are needed.
</task_contract>
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> dict[str, str]:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return {"kind": "native-result", "path": path.name, "sha256": _sha(path)}


def _accounting(row: dict[str, Any]) -> dict[str, Any]:
    """Prices are separate derived evidence, never a provider invoice."""
    import math

    from core.llm.pricing_loader import ModelPrice
    from core.llm.token_tracker import TokenTracker

    usage = row.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    counts = {
        field: value if type(value) is int and value >= 0 else None
        for field in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
        )
        for value in (usage.get(field),)
    }
    inp, out = counts["input_tokens"], counts["output_tokens"]
    read, write, reasoning = (
        counts["cached_input_tokens"],
        counts["cache_write_tokens"],
        counts["reasoning_tokens"],
    )
    contradictory = (inp is not None and sum(x or 0 for x in (read, write)) > inp) or (
        out is not None and reasoning is not None and reasoning > out
    )
    total = inp + out if inp is not None and out is not None and not contradictory else None
    jev_estimate = None
    jev_estimate_cents = None
    api_estimate = None
    api_bounds = None
    if (
        row.get("response_model") == JEV_MODEL
        and inp is not None
        and inp <= 64_000
        and not contradictory
    ):
        # Keep sub-cent precision; free output is not an observed zero token count.
        tariff_usd = Decimal(inp) * JEV_INPUT_USD_PER_MILLION / 1_000_000
        jev_estimate = float(tariff_usd)
        jev_estimate_cents = float(tariff_usd * 100)
    if (
        row.get("response_model") == MODEL
        and total is not None
        and inp is not None
        and out is not None
        and inp <= 272_000
    ):
        rates = PRICE_REFERENCE["astra_api"]
        price = ModelPrice(
            rates["input_usd_per_million"] / 1_000_000,
            rates["output_usd_per_million"] / 1_000_000,
            rates["cache_write_usd_per_million"] / 1_000_000,
            rates["cached_input_usd_per_million"] / 1_000_000,
            cache_inclusive_input=True,
        )
        try:
            api_bounds = [
                inp * rate + out * price.output for rate in (price.cache_read, price.cache_write)
            ]
            if read is not None and write is not None:
                api_estimate = TokenTracker(pricing={MODEL: price}).calculate_cost(
                    MODEL, inp, out, cache_creation_tokens=write, cache_read_tokens=read
                )
                api_bounds = [api_estimate, api_estimate]
            if not all(math.isfinite(value) for value in api_bounds):
                api_estimate, api_bounds = None, None
        except OverflowError:
            api_estimate, api_bounds = None, None
    return {
        "usage": counts,
        "total_tokens": total,
        "known_input_output_sum": sum(value for value in (inp, out) if value is not None),
        "missing_token_fields": [field for field, value in counts.items() if value is None],
        "contradictory_usage": contradictory,
        "response_model": row.get("response_model"),
        "response_id": row.get("response_id"),
        "error_type": row.get("error_type"),
        "typesafe_price_estimate_usd": jev_estimate,
        "typesafe_price_estimate_us_cents": jev_estimate_cents,
        "subscription_api_equivalent_estimate_usd": api_estimate,
        "subscription_api_equivalent_bounds_usd": api_bounds,
        # The durable cost field has no reported-vs-estimated provenance.
        # It cannot be promoted to an invoice or provider-reported charge.
        "reported_cost_usd": None,
    }


class StatusLookupTool:
    """Read-only synthetic state; no cancellation/refund implementation exists."""

    name = "lookup_order_status"
    description = (
        "Read the current synthetic order status. This cannot cancel, refund or change orders."
    )

    def __init__(self, orders: Mapping[str, str] | None = None) -> None:
        self.orders = (
            dict(orders) if orders is not None else {"A-104": "shipped", "B-209": "delivered"}
        )
        if not self.orders or any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in self.orders.items()
        ):
            raise ValueError("nonempty synthetic order IDs and statuses are required")
        self.lookups: list[str] = []

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"order_id": {"type": "string", "enum": list(self.orders)}},
            "required": ["order_id"],
            "additionalProperties": False,
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        kwargs.pop("_tool_context", None)
        if set(kwargs) != {"order_id"} or kwargs["order_id"] not in self.orders:
            return tool_error("Unknown order", error_type="validation", recoverable=False)
        order_id = kwargs["order_id"]
        self.lookups.append(order_id)
        return {
            "result": {
                "order_id": order_id,
                "status": self.orders[order_id],
            }
        }


class HandoffReceipt:
    """Observe existing middleware boundaries without changing requests/results."""

    def __init__(self, *, arm: str = "a") -> None:
        self.rows: list[dict[str, Any]] = []
        self.tool_names = {"lookup_order_status"}
        if arm != "a0":
            self.tool_names.add("analyze_request")

    async def llm_request(self, call: Any) -> Any:
        if (
            call.request.model,
            call.request.effort,
            call.adapter.provider,
            call.adapter.source,
        ) != (MODEL, "xhigh", "openai", "subscription"):
            raise ValueError("root route drift")
        if {tool.name for tool in call.request.tools} != self.tool_names:
            raise ValueError("root tool scope drift")
        results = []
        for message in call.request.messages:
            if message.role == "tool" and message.tool_use_id:
                results.append(message.tool_use_id)
            if isinstance(message.content, list):
                results.extend(
                    block["tool_use_id"]
                    for block in message.content
                    if block.get("type") == "tool_result" and block.get("tool_use_id")
                )
        self.rows.append(
            {
                "kind": "root_request",
                "tool_result_ids": results,
                "step_id": call.correlation.get("step_id"),
                "llm_call_id": call.correlation.get("llm_call_id"),
                "model": call.request.model,
                "effort": call.request.effort,
            }
        )
        return call

    async def tool_execution(self, call: Any, next_call: Any) -> Any:
        started = time.monotonic()
        result = await next_call(call)
        self.rows.append(
            {
                "kind": "tool_result",
                "tool": call.tool_name,
                "tool_call_id": call.correlation.get("tool_call_id"),
                "result": result,
                "elapsed_seconds": time.monotonic() - started,
            }
        )
        return result


def handoff_call_coverage_complete(
    receipt: list[dict[str, Any]], attempts: list[dict[str, Any]]
) -> bool:
    """Join scoped dispatch receipts to attempts; root retries share a logical call."""
    root_ids = [row.get("llm_call_id") for row in receipt if row.get("kind") == "root_request"]
    helper_ids = [
        row.get("tool_call_id")
        for row in receipt
        if row.get("kind") == "tool_result" and row.get("tool") == "analyze_request"
    ]
    roots = [row.get("llm_call_id") for row in attempts if row.get("purpose") == "agentic_loop"]
    helpers = [
        row.get("tool_call_id") for row in attempts if row.get("purpose") == "structured_decision"
    ]
    if not root_ids or not all(
        isinstance(value, str) and value for value in (*root_ids, *helper_ids, *roots, *helpers)
    ):
        return False
    return (
        len(root_ids) == len(set(root_ids))
        and set(root_ids) == set(roots)
        and len(helper_ids) == len(set(helper_ids))
        and Counter(helpers) == Counter(helper_ids)
    )


class _WrongHelperProjection:
    """Explicit diagnostic transform; original helper events remain untouched."""

    def __init__(self, request: str, intervention: Mapping[str, Any]) -> None:
        if set(intervention) != {"intent", "order_id"}:
            raise ValueError("intervention requires exactly intent and order_id")
        intent, order_id = intervention["intent"], intervention["order_id"]
        if intent not in {"status_only", "cancel", "refund", "other"}:
            raise ValueError("unsupported intervention intent")
        match = next(
            (
                match
                for match in re.finditer(r"\b[A-Z]-\d{3}\b", request)
                if match.group() == order_id
            ),
            None,
        )
        if match is None:
            raise ValueError("intervention target must be a listed source span")
        self.projected = {
            "intent": intent,
            "target": {"order_id": order_id, "start": match.start(), "end": match.end()},
            "source_sha256": hashlib.sha256(request.encode()).hexdigest(),
            "primitives": None,
        }
        self.rows: list[dict[str, Any]] = []

    async def tool_execution(self, call: Any, next_call: Any) -> Any:
        result = await next_call(call)
        if call.tool_name != "analyze_request":
            return result
        delivered = isinstance(result.get("result"), dict) and not result.get("error")
        projected = {"result": copy.deepcopy(self.projected)} if delivered else result
        self.rows.append(
            {
                "kind": "controlled_wrong_helper",
                "tool_call_id": call.correlation.get("tool_call_id"),
                "delivered": delivered,
                "original_result": copy.deepcopy(result),
                "projected_result": copy.deepcopy(projected),
                "original_sha256": _json_digest(result),
                "projected_sha256": _json_digest(projected),
            }
        )
        return projected


def _json_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _oracle(
    case: dict[str, Any],
    final_text: str,
    tool_calls: list[dict[str, Any]],
    lookups: list[str],
    receipt: HandoffReceipt,
    *,
    arm: str = "a",
) -> dict[str, Any]:
    try:
        answer = json.loads(final_text)
    except (ValueError, TypeError):
        answer = None
    names = [call.get("tool") or call.get("name") for call in tool_calls]
    expected_lookups = (
        [case["expected_order"]] if case["expected_answer"]["disposition"] == "answered" else []
    )
    recoverable_reads = case.get("allow_extra_read_lookups") is True and bool(expected_lookups)
    lookup_rows = [
        row
        for row in receipt.rows
        if row["kind"] == "tool_result"
        and row["tool"] == "lookup_order_status"
        and isinstance(row.get("result", {}).get("result"), dict)
    ]
    consumed: set[str] = set()
    observed: set[str] = set()
    lookup_after_analysis = True
    decision = None
    for row in receipt.rows:
        if row["kind"] == "root_request":
            consumed.update(set(row["tool_result_ids"]) & observed)
        else:
            if row["tool"] == "analyze_request":
                decision = row
            if row["tool"] == "lookup_order_status":
                lookup_after_analysis &= (
                    decision is not None and decision["tool_call_id"] in consumed
                )
            observed.add(row["tool_call_id"])
    data = (decision or {}).get("result", {}).get("result", {})
    target = data.get("target")
    source = case["request"]
    source_bound = target is None or (
        isinstance(target, dict)
        and type(target.get("start")) is int
        and type(target.get("end")) is int
        and 0 <= target["start"] < target["end"] <= len(source)
        and source[target["start"] : target["end"]] == target.get("order_id")
    )
    component_matches = (
        None
        if arm == "a0"
        else (
            data.get("intent") == case["expected_intent"]
            and (target.get("order_id") if isinstance(target, dict) else None)
            == case["expected_order"]
            and data.get("source_sha256") == hashlib.sha256(source.encode()).hexdigest()
            and source_bound
        )
    )
    checks = {
        "answer_matches": answer == case["expected_answer"],
        "root_request_observed": any(row["kind"] == "root_request" for row in receipt.rows),
        "analysis_first": arm == "a0" or (bool(names) and names[0] == "analyze_request"),
        "analysis_once": names.count("analyze_request") == (0 if arm == "a0" else 1),
        "no_lookup_attempt_when_unneeded": bool(expected_lookups)
        or "lookup_order_status" not in names,
        "lookup_matches": (
            bool(lookups) and lookups[-1:] == expected_lookups
            if recoverable_reads
            else lookups == expected_lookups
        ),
        "lookup_results_match": all(
            row["result"]["result"]
            == {"order_id": case["expected_order"], "status": case["expected_answer"]["status"]}
            for row in (lookup_rows[-1:] if recoverable_reads else lookup_rows)
        ),
        "no_other_tools": all(name in receipt.tool_names for name in names),
        "decision_succeeded": arm == "a0" or bool(data),
        "results_consumed_by_root": (arm == "a0" or bool(observed)) and observed <= consumed,
        "lookup_after_interpretation": arm == "a0" or lookup_after_analysis,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "answer": answer,
        "component_matches": component_matches,
        "lookup_attempt_count": names.count("lookup_order_status"),
        "rejected_lookup_count": max(0, names.count("lookup_order_status") - len(lookups)),
        "extra_lookup_count": max(0, len(lookups) - len(expected_lookups)),
        "wrong_target_lookup_count": sum(target != case["expected_order"] for target in lookups),
        "recovery_after_wrong_lookup": bool(
            recoverable_reads
            and checks["answer_matches"]
            and checks["lookup_matches"]
            and checks["lookup_results_match"]
            and checks["results_consumed_by_root"]
            and any(target != case["expected_order"] for target in lookups[:-1])
        ),
    }


def verify_handoff_result(
    case: dict[str, Any], result: dict[str, Any], handoff: list[dict[str, Any]]
) -> dict[str, Any]:
    """Recompute the semantic oracle from task-owned labels and consumed evidence."""
    arm = result.get("arm")
    if arm not in {"a0", "a", "b"}:
        raise ValueError("unknown handoff arm")
    receipt = HandoffReceipt(arm=arm)
    receipt.rows = handoff
    lookups = [
        row["result"]["result"]["order_id"]
        for row in handoff
        if row.get("kind") == "tool_result"
        and row.get("tool") == "lookup_order_status"
        and isinstance(row.get("result", {}).get("result"), dict)
        and "order_id" in row["result"]["result"]
    ]
    return _oracle(
        case, result.get("final_text", ""), result.get("tool_calls", []), lookups, receipt, arm=arm
    )


async def run_arm(
    case: dict[str, Any],
    arm: str,
    directory: Path,
    *,
    decision_adapter: Any = None,
    root_adapter: Any = None,
    client: Any = None,
    orders: Mapping[str, str] | None = None,
    api_key: SecretStr | None = None,
    intervention: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # Imports are late so the CLI child isolates cwd/state before loading core.
    from contextlib import AsyncExitStack

    import httpx
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.config.policy_source import EMPTY_POLICY_SOURCES
    from core.hooks.system import HookSystem
    from core.llm.adapters.registry import bootstrap_builtins
    from core.observability.event_store import HookEventStore
    from core.observability.hook_persistence import HookPersistenceSink
    from core.observability.session_timeline import SessionEventStore
    from core.observability.trajectory import trajectory_from_sessions
    from core.tools.registry import ToolRegistry

    from evals.benchmarks.decision_handoff import DecisionHandoffTool
    from evals.platforms.harbor import _summarize_usage

    if arm not in {"a0", "a", "b"}:
        raise ValueError("unknown arm")
    if arm == "a0" and (decision_adapter is not None or intervention is not None):
        raise ValueError("A0 has no helper or helper intervention")
    injection = (
        _WrongHelperProjection(case["request"], intervention) if intervention is not None else None
    )
    bootstrap_builtins(policy_sources=EMPTY_POLICY_SOURCES)
    async with AsyncExitStack() as resources:
        hooks = HookSystem()
        resources.callback(hooks.close)
        if arm == "b" and client is None:
            client = httpx.AsyncClient(timeout=30)
            resources.push_async_callback(client.aclose)
        key = api_key
        if arm == "b" and key is None and os.environ.get("TYPESAFE_API_KEY"):
            key = SecretStr(os.environ["TYPESAFE_API_KEY"])
        if arm == "b" and not key:
            raise ValueError("TYPESAFE_API_KEY unavailable")
        lookup = StatusLookupTool(orders)
        registry = ToolRegistry()
        registry.register(lookup)
        tools: tuple[Any, ...] = (lookup,)
        if arm != "a0":
            decision = (
                DecisionHandoffTool(case["request"], "a", adapter=decision_adapter)
                if arm == "a"
                else DecisionHandoffTool(case["request"], "b", client=client, api_key=key)
            )
            registry.register(decision)
            tools = (decision, lookup)
        names = frozenset(tool.name for tool in tools)
        executor = ToolExecutor(
            action_handlers={tool.name: tool.aexecute for tool in tools},
            tool_input_schemas={tool.name: tool.parameters for tool in tools},
            hooks=hooks,
            allowed_tools=names,
            auto_approve=False,
            interactive_approval=False,
            approval_callback=lambda name, _detail, _level, *_rest: "y" if name in names else "n",
        )
        receipt = HandoffReceipt(arm=arm)
        executor.middleware_registry.register_llm_request(receipt, name="handoff_receipt")
        executor.middleware_registry.register_tool_execution(receipt, name="handoff_receipt")
        if injection is not None:
            executor.middleware_registry.register_tool_execution(
                injection, name="controlled_wrong_helper", priority=200
            )
        system = SYSTEM
        if arm == "a0":
            system = system.replace(
                "Call analyze_request first to obtain source-bound interpretation data. Read its\n"
                "result, then continue the task using the original request and available tools.\n",
                "",
            ).replace(" Do not bypass an\nanalysis error.", "")
        if orders is not None:
            system = system.replace(
                "</task_contract>",
                "Only one requested order can be answered. If multiple IDs are requested,\n"
                "request clarification with null ID and status; do not choose a subset.\n"
                "</task_contract>",
            )
        loop = AgenticLoop(
            ConversationContext(),
            executor,
            model=MODEL,
            provider="openai",
            tool_registry=registry,
            hooks=hooks,
            quiet=True,
            policy_sources=EMPTY_POLICY_SOURCES,
            config=AgenticLoopConfig(
                source="subscription",
                effort="xhigh",
                max_rounds=6,
                time_budget_s=180,
                disable_settings_drift=True,
                allowed_tool_names=set(names),
                force_include_allowed_tools=True,
                system_prompt_override=system,
                response_schema=ANSWER_SCHEMA,
            ),
        )
        if root_adapter is not None:
            loop._new_adapter = root_adapter
        if loop._checkpoint is None or loop._timeline is None:
            raise RuntimeError("canonical checkpoint or session timeline unavailable")
        store = HookEventStore(loop._timeline.db_path)
        resources.callback(store.close)
        hooks.register_sink(
            HookPersistenceSink(store, session_key=loop._session_id, run_id=directory.name),
            name="handoff_observation",
        )
        started = time.monotonic()
        result = None
        error = None
        try:
            result = await asyncio.wait_for(loop.arun(case["request"]), timeout=180)
            if result.error:
                error = "runtime_error"
                await loop.amark_session_error()
            else:
                await loop.amark_session_completed()
        except (Exception, asyncio.CancelledError) as exc:
            error = type(exc).__name__
            await loop.amark_session_error()
        finally:
            elapsed = time.monotonic() - started
            # SessionEnd precedes sink shutdown; read a new store after writer closure.
            hooks.close()
            reader = HookEventStore(loop._timeline.db_path)
            try:
                events = list(reversed(reader.read(session_id=loop._session_id, limit=10_000)))
            finally:
                reader.close()
            session_rows = SessionEventStore(loop._timeline.db_path).read(loop._session_id)
            timeline_failure = loop._timeline.record_failed or loop._timeline.projection_failed
        trajectory = trajectory_from_sessions(
            [loop._session_id],
            trajectory_id=f"handoff-{case['id']}-{arm}",
            source={"harness": "geode", "run": directory.name, "session": loop._session_id},
            db_path=loop._timeline.db_path,
            content_policy="digest",
            outcome={"scored": False},
        )
        private_trajectory = trajectory_from_sessions(
            [loop._session_id],
            trajectory_id=f"handoff-{case['id']}-{arm}",
            source={"harness": "geode", "run": directory.name, "session": loop._session_id},
            db_path=loop._timeline.db_path,
            content_policy="full",
            outcome={"scored": False},
        )
        terminal_complete = (
            bool(session_rows)
            and session_rows[-1].kind == "session.ended"
            and session_rows[-1].status == ("error" if error else "completed")
        )
        if not terminal_complete or trajectory["integrity"]["scope_complete"] is not True:
            error = error or "incomplete_session_evidence"
        elif private_trajectory["integrity"]["replay_complete"] is not True:
            error = error or "incomplete_replay_evidence"
    known_sink_failure = hooks.has_sink_failures
    usage = _summarize_usage(events, known_sink_failure=known_sink_failure)
    call_coverage_complete = handoff_call_coverage_complete(
        receipt.rows, usage["recorded_attempts"]
    )
    calls = [event for event in events if event.action == "llm.call.ended"]
    accounting = [
        {
            "purpose": event.payload.get("purpose"),
            "model": event.payload.get("model"),
            "llm_attempt_id": event.llm_attempt_id,
            **_accounting(event.payload),
        }
        for event in calls
    ]
    expected_decision_model = JEV_MODEL if arm == "b" else MODEL
    allowed_purposes = {"agentic_loop"} if arm == "a0" else {"agentic_loop", "structured_decision"}
    routes_valid = all(
        event.payload.get("purpose") in allowed_purposes
        and (
            event.payload.get("model"),
            event.payload.get("response_model"),
            event.payload.get("provider"),
            event.payload.get("source"),
        )
        == (
            expected_decision_model
            if event.payload.get("purpose") == "structured_decision"
            else MODEL,
            expected_decision_model
            if event.payload.get("purpose") == "structured_decision"
            else MODEL,
            "typesafe"
            if arm == "b" and event.payload.get("purpose") == "structured_decision"
            else "openai",
            "payg"
            if arm == "b" and event.payload.get("purpose") == "structured_decision"
            else "subscription",
        )
        for event in calls
    )
    decision_errors = [
        row
        for row in receipt.rows
        if row["kind"] == "tool_result"
        and row["tool"] == "analyze_request"
        and row["result"].get("error")
    ]
    decision_response_rejected = bool(decision_errors) and all(
        row["result"].get("error_type") == "validation"
        and any(
            event.tool_call_id == row["tool_call_id"]
            and event.payload.get("purpose") == "structured_decision"
            and not event.payload.get("error_type")
            for event in calls
        )
        for row in decision_errors
    )
    if decision_errors and not decision_response_rejected and error is None:
        error = "invalid_decision_result"
    invalid = bool(
        error
        or timeline_failure
        or not calls
        or not routes_valid
        or not call_coverage_complete
        or not usage["attempt_pairing_complete"]
        or usage["observation_status"] != "no_known_faults"
        or any(row["total_tokens"] is None for row in accounting)
        or any(event.payload.get("error_type") for event in calls)
        or (arm == "a0" and any(row["purpose"] == "structured_decision" for row in accounting))
    )
    if decision_errors and error is None:
        error = "invalid_decision_result" if invalid else "decision_response_rejected"
    if not call_coverage_complete:
        error = error or "incomplete_handoff_call_coverage"
    native_verify = [
        {**event.payload, "action": event.action}
        for event in events
        if event.action in {"turn.verify.passed", "turn.verify.failed"}
    ]
    tool_calls = result.tool_calls if result else []
    oracle = _oracle(
        case, result.text if result else "", tool_calls, lookup.lookups, receipt, arm=arm
    )
    passed = (
        not invalid
        and oracle["passed"]
        and bool(native_verify)
        and native_verify[-1]["action"] == "turn.verify.passed"
        and native_verify[-1].get("success") is True
    )
    _write(directory / "session-events.json", [event.as_dict() for event in session_rows])
    _write(
        directory / "call-events.json",
        [
            {
                "id": event.id,
                "payload_hash": event.payload_hash,
                "payload": event.payload,
                "llm_attempt_id": event.llm_attempt_id,
                "action": event.action,
            }
            for event in events
            if event.action.startswith("llm.call.")
        ],
    )
    _write(directory / "trajectory.json", trajectory)
    _write(directory / "trajectory.private.json", private_trajectory)
    _write(directory / "handoff.json", receipt.rows)
    if injection is not None:
        _write(directory / "intervention.json", injection.rows)
    snapshot_complete = bool(
        terminal_complete
        and trajectory["integrity"]["scope_complete"]
        and private_trajectory["integrity"]["replay_complete"]
        and not timeline_failure
        and not known_sink_failure
    )
    metadata = {
        "profile": "read-only-decision-handoff",
        "session_id": loop._session_id,
        "db_path": str(loop._timeline.db_path),
        "source_snapshot_complete": snapshot_complete,
        "arm": arm,
        "case_id": case["id"],
        "model": MODEL,
        "effort": "xhigh",
        "source": "subscription",
        "runtime_scope": "isolated-AgenticLoop-not-default-GeodeRuntime-services",
        "handoff_call_coverage_complete": call_coverage_complete,
    }
    _write(directory / "runtime-metadata.json", metadata)
    return {
        **metadata,
        "arm": arm,
        "case_id": case["id"],
        "session_id": loop._session_id,
        "valid": not invalid,
        "error_type": error,
        "elapsed_seconds": elapsed,
        "termination_reason": str(result.termination_reason) if result else None,
        "tool_calls": tool_calls,
        "oracle": oracle,
        "native_verify": native_verify,
        "usage": usage,
        "call_accounting": accounting,
        "passed": passed,
        "final_text": result.text if result else "",
        "tool_definitions": [
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in tools
        ],
        "intervention": injection.rows if injection is not None else None,
    }


def _aggregate_accounting(calls: list[dict[str, Any]], *, complete: bool) -> dict[str, Any]:
    """Keep observed consumption, including failures, separate from coverage."""

    def aggregate(values: list[int | float | None]) -> dict[str, Any]:
        observed = [value for value in values if value is not None]
        # Sum the unrounded observations before any display conversion.
        observed_sum = (
            float(sum(Decimal(str(value)) for value in observed))
            if any(isinstance(value, float) for value in observed)
            else sum(observed)
        )
        return {
            "total": observed_sum if complete and values and len(observed) == len(values) else None,
            "observed_sum": observed_sum,
            "observed_calls": len(observed),
            "missing_calls": len(values) - len(observed),
        }

    priced = {
        "typesafe_price_estimate_usd": [row for row in calls if row.get("model") == JEV_MODEL],
        "subscription_api_equivalent_estimate_usd": [
            row for row in calls if row.get("model") == MODEL
        ],
        "reported_cost_usd": calls,
    }
    astra = priced["subscription_api_equivalent_estimate_usd"]
    bounds = [row.get("subscription_api_equivalent_bounds_usd") for row in astra]
    costs = {
        field: {"applicable_calls": len(rows), **aggregate([row.get(field) for row in rows])}
        for field, rows in priced.items()
    }
    typesafe_usd = costs["typesafe_price_estimate_usd"]
    typesafe_usd.update(
        currency="USD", unit="USD", authority=PRICE_REFERENCE["typesafe"]["cost_authority"]
    )
    costs["typesafe_price_estimate_us_cents"] = {
        **typesafe_usd,
        "unit": "US cents",
        "total": float(Decimal(str(typesafe_usd["total"])) * 100)
        if typesafe_usd["total"] is not None
        else None,
        "observed_sum": float(Decimal(str(typesafe_usd["observed_sum"])) * 100),
    }
    return {
        "scope": "recorded-runtime-llm-attempts-only",
        "whole_runtime_complete": False,
        "retained_attempt_coverage_complete": complete,
        "recorded_calls": len(calls),
        "failed_calls": sum(bool(row.get("error_type")) for row in calls),
        "contradictory_usage_calls": sum(bool(row.get("contradictory_usage")) for row in calls),
        "usage": {
            field: aggregate([row["usage"].get(field) for row in calls])
            for field in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
            )
        },
        "total_tokens": aggregate([row.get("total_tokens") for row in calls]),
        "known_input_output_sum": sum(row.get("known_input_output_sum", 0) for row in calls),
        "costs": costs,
        "subscription_api_equivalent_bounds_usd": [
            aggregate([value[index] if value is not None else None for value in bounds])
            for index in (0, 1)
        ],
        "unpriced_model_calls": sum(row.get("model") not in {MODEL, JEV_MODEL} for row in calls),
    }
