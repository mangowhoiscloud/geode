#!/usr/bin/env python3
"""Private, frozen root → decision tool → root continuation diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.eval.contract import validate_analysis, validate_attempts, validate_run_spec

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "evals/benchmarks/fixtures/decision-handoff.json"
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


def _source_is_pinned(reproduction: dict[str, Any]) -> bool:
    """Require the same clean source before and after every child dispatch."""
    git = shutil.which("git")
    if git is None:
        return False
    try:
        revision = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()  # noqa: S603
        dirty = subprocess.check_output([git, "status", "--porcelain"], cwd=ROOT, text=True)  # noqa: S603
    except (OSError, subprocess.CalledProcessError):
        return False
    return (
        not dirty
        and reproduction["geode"]["revision"] == revision
        and reproduction["harness"]["revision"] == revision
        and reproduction["geode"]["dirty"] is False
    )


def preflight(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spec = validate_run_spec(path)
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    cases = json.loads(FIXTURE.read_text())
    checks = {
        "clean pinned source": _source_is_pinned(reproduction),
        "approved prospective freeze": (
            spec["preregistration"]["mode"] == "prospective"
            and spec["preregistration"]["status"] == "frozen"
            and spec["preregistration"]["live_test_approved"] is True
            and datetime.fromisoformat(spec["preregistration"]["frozen_at"].replace("Z", "+00:00"))
            <= datetime.now(UTC)
        ),
        "fixture": (
            reproduction["environment"]["initial_state_ref"] == f"sha256:{_sha(FIXTURE)}"
            and len(cases) == 5
            and execution["ordered_workload_ids"] == [case["id"] for case in cases]
        ),
        "root route": reproduction["model"]
        == {"provider": "openai", "label": MODEL, "route": "subscription", "reasoning": "xhigh"},
        "uncapped fixed workload": (
            execution["budget"] == {"kind": "combined", "limit": None, "unit": "uncapped"}
            and execution["repetitions"] == 1
            and execution["max_concurrency"] == 1
            and execution["timeout_seconds"] == 180
        ),
        "question and comparator": (
            spec["study"]["primary_metric"] == PRIMARY_METRIC
            and reproduction["comparison"]
            == {
                "claim_class": "diagnostic",
                "comparator": f"root-with-typesafe:{JEV_MODEL}:choice",
                "comparability": "direct",
                "promotion_authority": "none",
            }
        ),
        "private fixed destinations": (
            spec["privacy"]["classification"] != "public"
            and spec["artifacts"]["native_results"] == "results.json"
            and spec["artifacts"]["attempts"] == "attempts.jsonl"
            and spec["artifacts"]["analysis"] == "analysis.json"
        ),
        "fresh run": not any(
            (path.parent / name).exists()
            for name in ("private", "results.json", "attempts.jsonl", "analysis.json")
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Handoff preflight failed: " + ", ".join(failures))
    return spec, cases


class StatusLookupTool:
    """Read-only synthetic state; no cancellation/refund implementation exists."""

    name = "lookup_order_status"
    description = (
        "Read the current synthetic order status. This cannot cancel, refund or change orders."
    )
    parameters = {
        "type": "object",
        "properties": {"order_id": {"type": "string", "enum": ["A-104", "B-209"]}},
        "required": ["order_id"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.lookups: list[str] = []

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        kwargs.pop("_tool_context", None)
        if set(kwargs) != {"order_id"} or kwargs["order_id"] not in {"A-104", "B-209"}:
            return tool_error("Unknown order", error_type="validation", recoverable=False)
        order_id = kwargs["order_id"]
        self.lookups.append(order_id)
        return {
            "result": {
                "order_id": order_id,
                "status": {"A-104": "shipped", "B-209": "delivered"}[order_id],
            }
        }


class HandoffReceipt:
    """Observe existing middleware boundaries without changing requests/results."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def llm_request(self, call: Any) -> Any:
        if (
            call.request.model,
            call.request.effort,
            call.adapter.provider,
            call.adapter.source,
        ) != (MODEL, "xhigh", "openai", "subscription"):
            raise ValueError("root route drift")
        if {tool.name for tool in call.request.tools} != {"analyze_request", "lookup_order_status"}:
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


def _oracle(
    case: dict[str, Any],
    final_text: str,
    tool_calls: list[dict[str, Any]],
    lookups: list[str],
    receipt: HandoffReceipt,
) -> dict[str, Any]:
    try:
        answer = json.loads(final_text)
    except (ValueError, TypeError):
        answer = None
    names = [call.get("tool") or call.get("name") for call in tool_calls]
    expected_lookups = (
        [case["expected_order"]] if case["expected_answer"]["disposition"] == "answered" else []
    )
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
    component_matches = (
        data.get("intent") == case["expected_intent"]
        and (target.get("order_id") if isinstance(target, dict) else None) == case["expected_order"]
        and data.get("source_sha256") == hashlib.sha256(source.encode()).hexdigest()
        and (target is None or source[target["start"] : target["end"]] == target["order_id"])
    )
    checks = {
        "answer_matches": answer == case["expected_answer"],
        "analysis_first": bool(names) and names[0] == "analyze_request",
        "analysis_once": names.count("analyze_request") == 1,
        "lookup_matches": lookups == expected_lookups,
        "no_other_tools": all(name in {"analyze_request", "lookup_order_status"} for name in names),
        "decision_succeeded": bool(data),
        "results_consumed_by_root": bool(observed) and observed <= consumed,
        "lookup_after_interpretation": lookup_after_analysis,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "answer": answer,
        "component_matches": component_matches,
    }


async def run_arm(
    case: dict[str, Any],
    arm: str,
    directory: Path,
    *,
    decision_adapter: Any = None,
    root_adapter: Any = None,
    client: Any = None,
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
    from pydantic import SecretStr

    if arm not in {"a", "b"}:
        raise ValueError("unknown arm")
    bootstrap_builtins(policy_sources=EMPTY_POLICY_SOURCES)
    async with AsyncExitStack() as resources:
        hooks = HookSystem()
        resources.callback(hooks.close)
        if arm == "b" and client is None:
            client = httpx.AsyncClient(timeout=30)
            resources.push_async_callback(client.aclose)
        key = os.environ.get("TYPESAFE_API_KEY")
        if arm == "b" and not key:
            raise ValueError("TYPESAFE_API_KEY unavailable")
        decision = (
            DecisionHandoffTool(case["request"], "a", adapter=decision_adapter)
            if arm == "a"
            else DecisionHandoffTool(
                case["request"], "b", client=client, api_key=SecretStr(key or "")
            )
        )
        lookup = StatusLookupTool()
        registry = ToolRegistry()
        registry.register(decision)
        registry.register(lookup)
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
        receipt = HandoffReceipt()
        executor.middleware_registry.register_llm_request(receipt, name="handoff_receipt")
        executor.middleware_registry.register_tool_execution(receipt, name="handoff_receipt")
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
                system_prompt_override=SYSTEM,
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
            events = list(reversed(store.read(session_id=loop._session_id, limit=10_000)))
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
        terminal_complete = (
            bool(session_rows)
            and session_rows[-1].kind == "session.ended"
            and session_rows[-1].status == ("error" if error else "completed")
        )
        if not terminal_complete or trajectory["integrity"]["scope_complete"] is not True:
            error = error or "incomplete_session_evidence"
    known_sink_failure = hooks.has_sink_failures
    usage = _summarize_usage(events, known_sink_failure=known_sink_failure)
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
    expected_decision_model = MODEL if arm == "a" else JEV_MODEL
    routes_valid = all(
        (
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
        or not usage["attempt_pairing_complete"]
        or usage["observation_status"] != "no_known_faults"
        or any(row["total_tokens"] is None for row in accounting)
        or any(event.payload.get("error_type") for event in calls)
    )
    if decision_errors and error is None:
        error = "invalid_decision_result" if invalid else "decision_response_rejected"
    native_verify = [
        {**event.payload, "action": event.action}
        for event in events
        if event.action in {"turn.verify.passed", "turn.verify.failed"}
    ]
    tool_calls = result.tool_calls if result else []
    oracle = _oracle(case, result.text if result else "", tool_calls, lookup.lookups, receipt)
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
    _write(directory / "handoff.json", receipt.rows)
    return {
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
    }


def _run_child(case_index: int, arm: str, directory: Path) -> None:
    if "core.paths" in sys.modules:
        raise RuntimeError("runtime imported before isolation")
    os.umask(0o077)
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700)
    os.environ["GEODE_HOME"] = str(directory / "geode-home")
    os.environ["GEODE_STATE_ROOT"] = str(directory / "state")
    os.environ["GEODE_VERIFY_MODE"] = "rule_based"
    os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = "1"
    os.environ["GEODE_JUDGE_MODEL"] = ""
    os.environ["GEODE_COGNITIVE_REFLECTION_MODEL"] = ""
    os.environ.pop("GEODE_SESSION_TIME_BUDGET_S", None)
    os.chdir(workspace)
    logging.disable(logging.CRITICAL)
    from core.config import settings

    settings.llm_max_retries = 1
    settings.cognitive_reflection_enabled = False
    settings.cost_limit_usd = 0
    case = json.loads(FIXTURE.read_text())[case_index]
    result = asyncio.run(run_arm(case, arm, directory))
    _write(directory / "result.json", result)


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


def _summary(pairs: list[dict[str, Any]], stop_reason: str | None) -> dict[str, Any]:
    measurable = len(pairs) == 5 and all(
        len(pair) == 2 and all(row["valid"] for row in pair.values()) for pair in pairs
    )
    delta = (
        sum(int(pair["b"]["passed"]) - int(pair["a"]["passed"]) for pair in pairs)
        if measurable
        else None
    )
    arms = {}
    for arm in ("a", "b"):
        rows = [pair[arm] for pair in pairs if arm in pair]
        calls = [call for row in rows for call in row.get("call_accounting", [])]
        complete = bool(rows) and all(
            row.get("usage", {}).get("attempt_pairing_complete") is True
            and row.get("usage", {}).get("observation_status") == "no_known_faults"
            and row.get("usage", {}).get("terminal_event_count")
            == len(row.get("call_accounting", []))
            and not row.get("accounting_incomplete", False)
            for row in rows
        )
        latencies = [row["elapsed_seconds"] for row in rows if "elapsed_seconds" in row]
        purposes = sorted({call.get("purpose") or "unknown" for call in calls})
        arms[arm] = {
            "attempted_tasks": len(rows),
            "passed_tasks": sum(row["passed"] is True for row in rows),
            "valid_tasks": sum(row["valid"] is True for row in rows),
            "median_elapsed_seconds": statistics.median(latencies) if latencies else None,
            "accounting": _aggregate_accounting(calls, complete=complete),
            "by_purpose": {
                purpose: _aggregate_accounting(
                    [call for call in calls if (call.get("purpose") or "unknown") == purpose],
                    complete=complete,
                )
                for purpose in purposes
            },
        }
    return {
        "value": delta / 5 if delta is not None else "not-measurable",
        "numerator": delta,
        "denominator": 5 if measurable else None,
        "stop_reason": stop_reason,
        "attempted_pairs": len(pairs),
        "paired_tasks": sum(len(pair) == 2 for pair in pairs),
        "price_reference": PRICE_REFERENCE,
        "cost_limitation": (
            "Public-price estimates and subscription API equivalents are not invoices."
        ),
        "arms": arms,
    }


def _child_artifacts(directory: Path, run_dir: Path) -> list[dict[str, str]]:
    """Bind available private evidence, even when a killed child wrote no result."""
    files = {
        directory / name
        for name in (
            "result.json",
            "session-events.json",
            "call-events.json",
            "trajectory.json",
            "handoff.json",
        )
        if (directory / name).is_file()
    }
    files.update(
        artifact
        for artifact in directory.rglob("*")
        if artifact.is_file() and artifact.name.endswith((".db", ".db-wal", ".db-shm"))
    )
    return [
        {
            "kind": "native-result" if artifact.name == "result.json" else "other",
            "path": artifact.relative_to(run_dir).as_posix(),
            "sha256": _sha(artifact),
        }
        for artifact in sorted(files)
    ]


def _child_result(directory: Path, case_id: str, arm: str, error: str | None) -> dict[str, Any]:
    """Retain partial child accounting without promoting an incomplete task."""
    from scripts.eval.contract import _strict_json_loads

    result: dict[str, Any] = {}
    result_path = directory / "result.json"
    if result_path.is_file():
        try:
            loaded = _strict_json_loads(result_path.read_text(), label="child result")
            if not isinstance(loaded, dict):
                raise ValueError("child result must be an object")
            result = loaded
            if (result.get("case_id"), result.get("arm")) != (case_id, arm):
                error = error or "child_identity_mismatch"
            if type(result.get("valid")) is not bool or type(result.get("passed")) is not bool:
                error = error or "invalid_child_result"
        except (ValueError, UnicodeError):
            error = error or "invalid_child_result"
    else:
        error = error or "missing_child_result"
    accounting = result.get("call_accounting")
    if not isinstance(accounting, list) or not all(
        isinstance(row, dict) and isinstance(row.get("usage"), dict) for row in accounting
    ):
        error = error or "invalid_child_accounting"
        result["call_accounting"] = []
        result["accounting_incomplete"] = True
        call_path = directory / "call-events.json"
        if call_path.is_file():
            try:
                events = _strict_json_loads(call_path.read_text(), label="partial call events")
                if isinstance(events, list):
                    for event in events:
                        if not isinstance(event, dict) or event.get("action") != "llm.call.ended":
                            continue
                        payload = event.get("payload")
                        if isinstance(payload, dict):
                            result["call_accounting"].append(
                                {
                                    "purpose": payload.get("purpose"),
                                    "model": payload.get("model"),
                                    "llm_attempt_id": event.get("llm_attempt_id"),
                                    **_accounting(payload),
                                }
                            )
            except (ValueError, UnicodeError):
                pass  # Bytes remain digest-bound; malformed records are not fabricated usage.
    usage = result.get("usage")
    if not isinstance(usage, dict):
        result["usage"] = {}
        result["accounting_incomplete"] = True
    if result.get("valid") is True and (
        not result["call_accounting"]
        or result["usage"].get("attempt_pairing_complete") is not True
        or result["usage"].get("observation_status") != "no_known_faults"
        or result["usage"].get("terminal_event_count") != len(result["call_accounting"])
        or any(
            row.get("total_tokens") is None or row.get("error_type")
            for row in result["call_accounting"]
        )
    ):
        error = error or "invalid_child_accounting"
    if error:
        result.update(valid=False, passed=False, error_type=error, accounting_incomplete=True)
    return result


def execute(path: Path, spec: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    from core.memory.atomic_write import append_jsonl
    from dotenv import dotenv_values

    admitted_spec, admitted_cases = preflight(path)
    if spec != admitted_spec or cases != admitted_cases:
        raise ValueError("execution arguments differ from the frozen run spec or fixture")
    key = os.environ.get("TYPESAFE_API_KEY") or dotenv_values(
        Path.home() / ".geode/.env", interpolate=False
    ).get("TYPESAFE_API_KEY")
    if not key:
        raise ValueError("TYPESAFE_API_KEY unavailable")
    frozen_hash, fixture_hash = _sha(path), _sha(FIXTURE)
    private = path.parent / "private"
    private.mkdir(mode=0o700)
    attempts_path = path.parent / "attempts.jsonl"
    attempts_path.touch(mode=0o600, exist_ok=False)
    env = dict(os.environ, TYPESAFE_API_KEY=key, PYTHONPATH=str(ROOT))
    attempts: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    evidence: list[dict[str, str]] = []
    stop_reason = None
    interruption: BaseException | None = None
    summary: dict[str, Any] = {}
    for index, case in enumerate(cases):
        started = _now()
        arms: dict[str, Any] = {}
        refs: list[dict[str, str]] = []
        for arm in ("a", "b") if index % 2 == 0 else ("b", "a"):
            if not _source_is_pinned(spec["reproduction"]):
                stop_reason = "source_drift"
                break
            if _sha(path) != frozen_hash or _sha(FIXTURE) != fixture_hash:
                stop_reason = "input_drift"
                break
            directory = private / f"{index:02d}-{arm}"
            directory.mkdir(mode=0o700)
            try:
                completed = subprocess.run(  # noqa: S603 — fixed local runner, frozen case/arm
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--child-case",
                        str(index),
                        "--arm",
                        arm,
                        "--output",
                        str(directory),
                    ],
                    env=env,
                    cwd=ROOT,
                    capture_output=True,
                    timeout=210,
                    check=False,
                )
                error = "child_process_failure" if completed.returncode else None
            except subprocess.TimeoutExpired:
                error = "child_process_timeout"
            except OSError:
                error = "child_process_start_failure"
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError) as exc:
                interruption = exc
                error = "parent_interrupted"
            if not _source_is_pinned(spec["reproduction"]):
                error = error or "source_drift"
            refs.extend(_child_artifacts(directory, path.parent))
            arms[arm] = _child_result(directory, case["id"], arm, error)
            if not arms[arm]["valid"]:
                stop_reason = arms[arm]["error_type"] or "invalid_runtime_observation"
                break
        pairs.append(arms)
        valid = len(arms) == 2 and all(row["valid"] for row in arms.values())
        if stop_reason or index == len(cases) - 1:
            summary = _summary(pairs, stop_reason)
            refs.append(_write(path.parent / "results.json", summary))
        failure_class = None if valid else "invalid_handoff_attempt"
        if valid and any(
            row.get("error_type") == "decision_response_rejected" for row in arms.values()
        ):
            failure_class = "decision_response_rejected"
        attempt = json.loads((ROOT / "docs/eval/eval-attempt.template.json").read_text())
        attempt.update(
            run_id=spec["run_id"],
            attempt_id=f"attempt-{index:02d}",
            sequence=index,
            timing={
                "status": "exact",
                "started_at": started,
                "finished_at": _now(),
                "source_ref": None,
            },
            validity="valid" if valid else "invalid",
            outcome=("passed" if all(row["passed"] for row in arms.values()) else "failed")
            if valid
            else "unknown",
            change={"surface": "structured-decision-tool", "description": case["id"]},
            expected_effect="Compare the same root task with an Astra or Jev decision helper.",
            observed_result=(
                "Paired native task evidence retained."
                if valid
                else "Incomplete or invalid attempt; only available partial evidence retained."
            ),
            failure_class=failure_class,
            evidence_refs=refs,
        )
        attempts.append(attempt)
        evidence.extend(refs)
        append_jsonl(attempts_path, attempt)
        print(
            f"Completed {case['id']}: valid={valid}; "
            f"A={arms.get('a', {}).get('passed')}; B={arms.get('b', {}).get('passed')}",
            flush=True,
        )
        if stop_reason:
            break
    measurable = summary["numerator"] is not None
    validate_attempts(attempts_path)
    analysis = json.loads((ROOT / "docs/eval/eval-analysis.template.json").read_text())
    analysis.update(
        run_id=spec["run_id"],
        analyzed_at=_now(),
        run_spec_sha256=frozen_hash,
        attempts_sha256=_sha(attempts_path),
        selected_attempt_ids=[row["attempt_id"] for row in attempts],
        answer=(
            "Local root continuation diagnostic; no default adoption or general benchmark claim."
        ),
        metrics=[
            {
                "name": PRIMARY_METRIC["name"],
                "value": summary["value"],
                "numerator": summary["numerator"],
                "denominator": summary["denominator"],
                "unit": "ratio",
                "source_ref": "results.json",
                "source_locator": {
                    "value": "/value",
                    "numerator": "/numerator",
                    "denominator": "/denominator",
                }
                if measurable
                else None,
            }
        ],
        decision={
            "outcome": "diagnostic-only",
            "hypothesis_status": "mixed" if measurable else "invalidated",
            "rationale": (
                "Five synthetic tasks test wiring and behavior, "
                "not calibrated confidence or broad superiority."
            ),
        },
        limitations=[
            "Same root, different decision model/interface bundles; one repetition.",
            "Runtime cost fields and public-price estimates are not subscription invoices.",
            "Native rule-based verification is mechanical; "
            "the scenario oracle owns task correctness.",
        ],
        evidence_refs=evidence,
    )
    _write(path.parent / "analysis.json", analysis)
    validate_analysis(
        path.parent / "analysis.json", run_spec_path=path, attempts_path=attempts_path
    )
    if interruption is not None:
        raise interruption


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--child-case", type=int, choices=range(5), help=argparse.SUPPRESS)
    parser.add_argument("--arm", choices=("a", "b"), help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child_case is not None:
        if args.arm is None or args.output is None:
            parser.error("child execution requires an arm and output")
        _run_child(args.child_case, args.arm, args.output.resolve())
        return
    if args.run_spec is None:
        parser.error("--run-spec is required")
    path = args.run_spec.resolve()
    spec, cases = preflight(path)
    if args.execute:
        execute(path, spec, cases)
    else:
        print("Handoff preflight passed; no model calls.")


if __name__ == "__main__":
    main()
