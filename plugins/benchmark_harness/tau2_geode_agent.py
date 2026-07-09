#!/usr/bin/env python3
"""Run tau2 with GEODE as the agent under test.

This script intentionally does not patch the upstream tau2 checkout. It imports
the harness from ``--harness-dir``, registers ``geode_agent`` and
``geode_user`` implementations in tau2's in-process registry, and then calls
``tau2.run.run_domain``.

The resulting run still uses tau2's native simulator, domain tools, world-state
diff evaluator, and output directory layout. The default route sends both the
assistant and simulated user through GEODE's subscription-backed AgenticLoop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import site
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARNESS_DIR = REPO_ROOT / "artifacts" / "eval" / "harnesses" / "tau2-bench"
DEFAULT_TRAJECTORY_SNAPSHOT_DIR = (
    REPO_ROOT / "artifacts" / "eval" / "runs" / "crucible" / "trajectory-snapshots"
)

CRUCIBLE_GUARDS: dict[str, str] = {
    "r1": (
        "R1 retail commit-plan guard:\n"
        "Before any mutating retail tool call, build a concise commit plan that lists "
        "the exact order_id, item_ids, replacement item_ids, address fields, payment "
        "method, and reason that will be sent to the tool. Verify each field against "
        "the latest tool results and the user's stated preferences, including fallback "
        "preferences. If any field is inferred rather than observed, ask or inspect "
        "before calling the mutating tool.\n"
        "If the user asks for split payment on a pending retail order and split "
        "payment is unavailable, continue the retail fallback ladder instead of "
        "transferring. Inspect the order, name the most expensive item and its price, "
        "then evaluate supported alternatives in order: whether that item can be "
        "changed or removed, whether same-product cheaper variants can bring the "
        "order under the user's stated budget, and finally whether the user wants to "
        "cancel the pending order. Use get_product_details and calculate when prices "
        "or variant totals matter, and get explicit confirmation before a pending "
        "modify or cancel write. When checking whether cheaper variants can meet a "
        "budget, calculate the direct sum of the selected final item prices, not only "
        "the savings or delta. If the final fallback is cancellation because the user "
        "cannot fund the pending order and wants to reorder, confirm cancellation with "
        "reason no longer needed instead of opening a generic reason menu."
    ),
    "t1": (
        "T1 telecom workflow-completion guard:\n"
        "Before transferring or ending a telecom troubleshooting conversation, verify "
        "the terminal condition for the issue type. For MMS, confirm can_send_mms is "
        "true. For mobile data, confirm mobile data is enabled and the speed test meets "
        "the user's required threshold. For no-service issues, confirm service status is "
        "connected. If the terminal verifier fails, continue the workflow instead of "
        "ending or transferring, unless the policy explicitly requires escalation."
    ),
}

CRUCIBLE_AGENT_PLANNERS = ("none", "telecom-mms-v1")
CRUCIBLE_USER_ACTION_PROJECTORS = (
    "none",
    "telecom-mms-prereq-v1",
    "telecom-mms-prereq-v2",
    "telecom-mms-prereq-v3",
    "telecom-mms-prereq-v4",
    "telecom-mms-prereq-v5",
    "telecom-mms-prereq-v6",
    "telecom-mms-prereq-v7",
    "telecom-mms-prereq-v8",
    "telecom-mms-prereq-v9",
    "telecom-mms-prereq-v10",
    "telecom-mms-prereq-v11",
    "telecom-mms-prereq-v12",
    "telecom-mms-prereq-v13",
    "telecom-mms-prereq-v14",
    "telecom-mms-prereq-v15",
    "telecom-mms-prereq-v16",
    "telecom-mms-prereq-v17",
    "telecom-mms-prereq-v18",
    "telecom-mms-prereq-v19",
    "telecom-mms-prereq-v20",
    "telecom-mms-prereq-v21",
    "telecom-mms-prereq-v22",
    "telecom-mms-prereq-v23",
    "telecom-mms-prereq-v24",
    "telecom-mms-prereq-v25",
    "telecom-mms-prereq-v26",
    "telecom-mms-prereq-v27",
    "telecom-mms-prereq-v28",
    "telecom-mms-prereq-v29",
    "telecom-mms-prereq-v30",
    "telecom-mms-prereq-v31",
    "telecom-mms-prereq-v32",
    "telecom-mms-prereq-v33",
    "telecom-mms-prereq-v34",
    "telecom-mms-prereq-v35",
    "telecom-mms-prereq-v36",
    "telecom-mms-prereq-v37",
    "telecom-mms-prereq-v38",
    "telecom-mms-prereq-v39",
    "telecom-mms-prereq-v40",
    "telecom-mms-prereq-v41",
    "telecom-mms-prereq-v42",
    "telecom-mms-prereq-v43",
    "telecom-mms-prereq-v44",
    "telecom-mms-prereq-v45",
    "telecom-mms-prereq-v46",
    "telecom-mms-prereq-v47",
    "telecom-mms-prereq-v48",
    "telecom-mms-prereq-v49",
    "telecom-mms-prereq-v50",
    "telecom-mms-prereq-v51",
    "telecom-mms-prereq-v52",
    "telecom-mms-prereq-v53",
    "telecom-mms-prereq-v54",
    "telecom-mms-prereq-v55",
    "telecom-mms-prereq-v56",
    "telecom-mms-prereq-v57",
    "telecom-mms-prereq-v58",
    "telecom-mms-prereq-v59",
    "telecom-mms-prereq-v60",
    "telecom-mms-prereq-v61",
    "telecom-mms-prereq-v62",
    "telecom-mms-prereq-v63",
    "telecom-mms-prereq-v64",
    "telecom-mms-prereq-v65",
    "telecom-mms-prereq-v66",
    "telecom-mms-prereq-v67",
    "telecom-mms-prereq-v68",
    "telecom-mms-prereq-v69",
    "telecom-mms-prereq-v70",
    "telecom-mms-prereq-v71",
    "telecom-mms-prereq-v72",
)
CRUCIBLE_WORKFLOW_ORDERS = (
    "none",
    "retail-split-payment-v1",
    "retail-contingent-intent-v1",
    "telecom-mms-v1",
    "telecom-mms-step-economy-v1",
    "telecom-mms-bounded-bundle-v1",
    "telecom-mms-roaming-recovery-v1",
    "telecom-mms-proactive-roaming-v1",
    "telecom-mms-phased-recovery-v1",
    "telecom-mms-late-compression-v1",
    "telecom-mms-harness-compression-v2",
    "telecom-mms-harness-compression-v3",
    "telecom-mms-harness-compression-v4",
    "telecom-mms-harness-compression-v5",
    "telecom-mms-harness-compression-v6",
    "telecom-mms-harness-compression-v7",
    "telecom-mms-harness-compression-v8",
    "telecom-mms-harness-compression-v9",
    "telecom-mms-harness-compression-v10",
    "telecom-mms-harness-compression-v11",
    "telecom-mms-harness-compression-v12",
    "telecom-mms-harness-compression-v13",
    "telecom-mms-harness-compression-v14",
    "telecom-mms-harness-compression-v15",
    "telecom-mms-harness-compression-v16",
    "telecom-mms-harness-compression-v17",
    "telecom-mms-harness-compression-v18",
    "telecom-mms-harness-compression-v19",
    "telecom-mms-harness-compression-v20",
    "telecom-mms-harness-compression-v21",
    "telecom-mms-harness-compression-v22",
    "telecom-mms-harness-compression-v23",
    "telecom-mms-harness-compression-v24",
    "telecom-mms-harness-compression-v25",
    "telecom-mms-harness-compression-v26",
    "telecom-mms-harness-compression-v27",
    "telecom-mms-harness-compression-v28",
    "telecom-mms-harness-compression-v29",
    "telecom-mms-harness-compression-v30",
    "telecom-mms-harness-compression-v31",
    "telecom-mms-harness-compression-v32",
    "telecom-mms-harness-compression-v33",
    "telecom-mms-harness-compression-v34",
    "telecom-mms-harness-compression-v35",
    "telecom-mms-harness-compression-v36",
    "telecom-mms-harness-compression-v37",
    "telecom-mms-harness-compression-v38",
    "telecom-mms-harness-compression-v39",
    "telecom-mms-harness-compression-v40",
    "telecom-mms-harness-compression-v41",
    "telecom-mms-harness-compression-v42",
    "telecom-mms-harness-compression-v43",
    "telecom-mms-harness-compression-v44",
    "telecom-mms-harness-compression-v45",
    "telecom-mms-harness-compression-v46",
    "telecom-mms-harness-compression-v47",
    "telecom-mms-harness-compression-v48",
    "telecom-mms-harness-compression-v49",
    "telecom-mms-harness-compression-v50",
    "telecom-mms-harness-compression-v51",
    "telecom-mms-harness-compression-v52",
    "telecom-mms-harness-compression-v53",
    "telecom-mms-harness-compression-v54",
    "telecom-mms-harness-compression-v55",
    "telecom-mms-harness-compression-v56",
    "telecom-mms-harness-compression-v57",
    "telecom-mms-harness-compression-v58",
    "telecom-mms-harness-compression-v59",
    "telecom-mms-harness-compression-v60",
    "telecom-mms-harness-compression-v61",
    "telecom-mms-harness-compression-v62",
    "telecom-mms-harness-compression-v63",
    "telecom-mms-harness-compression-v64",
    "telecom-mms-harness-compression-v65",
    "telecom-mms-harness-compression-v66",
    "telecom-mms-harness-compression-v67",
    "telecom-mms-harness-compression-v68",
    "telecom-mms-harness-compression-v69",
    "telecom-mms-harness-compression-v70",
    "telecom-mms-harness-compression-v71",
    "telecom-mms-harness-compression-v72",
)
WORKFLOW_GATE_MAX_RETRIES = 2
RETAIL_WRITE_PREFLIGHT_MAX_RETRIES = 3
RETAIL_VARIANT_SELECTION_MAX_RETRIES = 1
RETAIL_PENDING_ITEM_TERMINAL_MAX_RETRIES = 1


def _user_projector_workflow_order(projector: str) -> Any | None:
    """Build the diagnostic user-action projector scaffold for a route label."""
    if projector == "none":
        return None
    from plugins.benchmark_harness.tau2_workflow_order import (
        TelecomMmsWorkflowOrder,
        build_workflow_order_scaffold,
    )

    prereq_match = re.fullmatch(r"telecom-mms-prereq-v(\d+)", projector)
    if prereq_match and int(prereq_match.group(1)) >= 2:
        return build_workflow_order_scaffold(
            f"telecom-mms-harness-compression-v{prereq_match.group(1)}"
        )
    return TelecomMmsWorkflowOrder(roaming_recovery=True)


def _prepend_tau2_src(harness_dir: Path) -> None:
    src_dir = harness_dir / "src"
    if not src_dir.exists():
        raise SystemExit(f"tau2 source directory not found: {src_dir}")
    venv_dir = harness_dir / ".venv"
    if venv_dir.exists():
        for site_packages in site.getsitepackages([str(venv_dir)]):
            site_path = Path(site_packages)
            if site_path.exists():
                sys.path.insert(0, str(site_path))
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(src_dir))


def _result_text(result: Any) -> str:
    text = str(getattr(result, "text", "") or "").strip()
    if text:
        return text
    reason = str(getattr(result, "termination_reason", "") or "unknown")
    return f"GEODE ended without user-visible text. termination_reason={reason}"


def _assert_tau2_route_ready(
    result: Any,
    *,
    projected_tool_calls: list[Any],
    role: str,
) -> None:
    """Fail fast when the model route returns no benchmark-usable action."""

    text = str(getattr(result, "text", "") or "").strip()
    if text or projected_tool_calls:
        return
    raw_tool_calls = getattr(result, "tool_calls", []) or []
    termination_reason = str(getattr(result, "termination_reason", "") or "unknown")
    rounds = getattr(result, "rounds", 0)
    raise RuntimeError(
        "GEODE tau2 route readiness failed for "
        f"{role}: empty visible output and no projected tau2 tool calls "
        f"(termination_reason={termination_reason}, rounds={rounds}, "
        f"raw_tool_calls={len(raw_tool_calls)}). This is infrastructure evidence, "
        "not tau2 performance evidence. Fix the model route before G2/G3 spend, "
        "or pass --allow-empty-geode-turn only for debugging."
    )


def _tool_description(tool: Any) -> str:
    schema = getattr(tool, "openai_schema", None)
    if isinstance(schema, dict):
        fn = schema.get("function")
        if isinstance(fn, dict):
            desc = fn.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
    short = str(getattr(tool, "short_desc", "") or "").strip()
    long = str(getattr(tool, "long_desc", "") or "").strip()
    return "\n\n".join(part for part in (short, long) if part) or str(tool.name)


def _tool_parameters(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "openai_schema", None)
    if isinstance(schema, dict):
        fn = schema.get("function")
        if isinstance(fn, dict):
            params = fn.get("parameters")
            if isinstance(params, dict):
                return params
    params_model = getattr(tool, "params", None)
    model_json_schema = getattr(params_model, "model_json_schema", None)
    if callable(model_json_schema):
        maybe_schema = model_json_schema()
        if isinstance(maybe_schema, dict):
            return maybe_schema
    return {"type": "object", "properties": {}, "additionalProperties": False}


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


@dataclass
class Tau2GeodeTool:
    """GEODE tool wrapper around a tau2 environment tool."""

    tau2_tool: Any
    mutates_state: bool = True

    @property
    def name(self) -> str:
        return str(self.tau2_tool.name)

    @property
    def description(self) -> str:
        return _tool_description(self.tau2_tool)

    @property
    def parameters(self) -> dict[str, Any]:
        return _tool_parameters(self.tau2_tool)

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_tool_context", None)
        if self.mutates_state:
            return {
                "result": (
                    f"Recorded {self.name} for tau2 orchestrator execution. "
                    "The official tau2 environment will apply this tool call."
                ),
                "projected_to_tau2": True,
            }
        raw = await asyncio.to_thread(self.tau2_tool, **kwargs)
        return {"result": _jsonish(raw)}


@dataclass
class RetailOrderObservation:
    """Observed order facts used by the retail write preflight."""

    order_id: str
    status: str
    item_ids: set[str]
    payment_method_ids: set[str]


@dataclass
class RetailWritePreflight:
    """Reject mutating retail writes that contradict observed order state."""

    orders: dict[str, RetailOrderObservation]
    user_payment_method_ids: set[str]

    @classmethod
    def empty(cls) -> RetailWritePreflight:
        return cls(orders={}, user_payment_method_ids=set())

    def observe_incoming_message(self, message: Any) -> None:
        content = _message_content(message)
        if not content:
            return
        self.observe_tool_output(content)

    def observe_tool_output(self, output: Any) -> None:
        payload = output
        if isinstance(output, str):
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return
        payment_methods = payload.get("payment_methods")
        if isinstance(payment_methods, dict):
            self.user_payment_method_ids.update(str(key) for key in payment_methods)
        order_id = payload.get("order_id")
        status = payload.get("status")
        if not isinstance(order_id, str) or not isinstance(status, str):
            return
        item_ids = {
            str(item.get("item_id"))
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("item_id")
        }
        payment_method_ids = {
            str(row.get("payment_method_id"))
            for row in payload.get("payment_history", [])
            if isinstance(row, dict) and row.get("payment_method_id")
        }
        self.orders[order_id] = RetailOrderObservation(
            order_id=order_id,
            status=status.lower(),
            item_ids=item_ids,
            payment_method_ids=payment_method_ids,
        )

    def validate_tool_calls(self, tool_calls: list[Any]) -> list[str]:
        violations: list[str] = []
        for call in tool_calls:
            name = _tool_call_name(call)
            if name not in {
                "exchange_delivered_order_items",
                "return_delivered_order_items",
                "modify_pending_order_items",
                "modify_pending_order_address",
                "cancel_pending_order",
            }:
                continue
            arguments = _tool_call_arguments(call)
            order_id = str(arguments.get("order_id") or "")
            order = self.orders.get(order_id)
            if order is None:
                violations.append(
                    f"{name}({order_id or 'missing order_id'}) has no observed order details."
                )
                continue
            if name in {"exchange_delivered_order_items", "return_delivered_order_items"}:
                if order.status != "delivered":
                    violations.append(
                        f"{name}({order_id}) requires delivered status, observed {order.status!r}."
                    )
            elif name in {
                "modify_pending_order_items",
                "modify_pending_order_address",
                "cancel_pending_order",
            } and not (order.status == "pending" or order.status.startswith("pending ")):
                violations.append(
                    f"{name}({order_id}) requires pending status, observed {order.status!r}."
                )
            item_ids = _string_set(arguments.get("item_ids"))
            missing_items = sorted(item_ids - order.item_ids)
            if missing_items:
                violations.append(
                    f"{name}({order_id}) references item_ids not observed on that order: "
                    f"{', '.join(missing_items)}."
                )
            payment_method_id = arguments.get("payment_method_id")
            if (
                isinstance(payment_method_id, str)
                and order.payment_method_ids
                and payment_method_id not in order.payment_method_ids
                and payment_method_id not in self.user_payment_method_ids
            ):
                violations.append(
                    f"{name}({order_id}) uses payment_method_id {payment_method_id!r} "
                    "not observed on that order or user profile."
                )
        return violations

    def correction_prompt(self, violations: list[str]) -> str:
        violation_text = "\n- ".join(violations)
        observed = [
            {
                "order_id": order.order_id,
                "status": order.status,
                "item_ids": sorted(order.item_ids),
                "payment_method_ids": sorted(order.payment_method_ids),
            }
            for order in sorted(self.orders.values(), key=lambda row: row.order_id)
        ]
        return (
            "Retail write preflight blocked the proposed mutating tool call.\n"
            "Re-plan before any write. Choose a tool whose precondition matches the "
            "observed order status, item ids, and payment method. If the request is "
            "an exchange but the order is pending, use the pending-order modification "
            "flow after user confirmation; if the order is delivered, use the delivered "
            "exchange/return flow. If an order id is known only from the user profile "
            "or from conversation text, CAN inspect that order with get_order_details "
            "before asking for confirmation or calling a mutating tool. CANNOT cancel, "
            "modify, return, or exchange an order before its current status and items "
            "are observed from tool output.\n\n"
            f"Violations:\n- {violation_text}\n\n"
            f"Observed orders:\n{json.dumps(observed, ensure_ascii=False, sort_keys=True)}"
        )


@dataclass
class GeodeTau2State:
    loop: Any
    workflow_order: Any | None = None
    retail_write_preflight: RetailWritePreflight | None = None
    workflow_gate_retries: int = 0
    retail_preflight_retries: int = 0
    retail_variant_selection_retries: int = 0
    retail_pending_item_terminal_retries: int = 0
    messages_seen: int = 0
    codex_empty_text_retries_used: int = 0


CODEX_EMPTY_TEXT_ERROR_MARKER = "codex-oauth: empty output_text"


def _is_codex_empty_text_error(exc: BaseException) -> bool:
    """Return True for the Codex subscription empty visible-output failure."""
    return CODEX_EMPTY_TEXT_ERROR_MARKER in str(exc)


def _run_geode_turn_with_empty_text_retry(
    state: GeodeTau2State,
    prompt: str,
    *,
    max_retries: int,
) -> Any:
    """Run one GEODE tau2 turn, retrying transient Codex empty-output failures."""
    retries = 0
    while True:
        try:
            return asyncio.run(state.loop.arun(prompt))
        except RuntimeError as exc:
            if not _is_codex_empty_text_error(exc) or retries >= max_retries:
                raise
            retries += 1
            state.codex_empty_text_retries_used += 1


def _message_to_prompt(message: Any, *, recipient: str) -> str:
    raw_role = getattr(message, "role", "user") or "user"
    role = str(getattr(raw_role, "value", raw_role) or "user").lower()
    if "." in role:
        role = role.rsplit(".", 1)[-1]
    tool_messages = getattr(message, "tool_messages", None)
    if tool_messages:
        payload = [
            {
                "id": getattr(tool_message, "id", ""),
                "requestor": getattr(tool_message, "requestor", ""),
                "content": getattr(tool_message, "content", ""),
                "error": getattr(tool_message, "error", False),
            }
            for tool_message in tool_messages
        ]
        return f"Tool results to {recipient} from tau2 orchestrator:\n{_jsonish(payload)}"
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        if role == "tool":
            return f"Tool result to {recipient} from tau2 orchestrator:\n{content}"
        return f"Message to {recipient} from {role}:\n{content}"
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return (
            f"Message to {recipient} from {role} containing tool calls:\n"
            f"{_jsonish([tc.model_dump() for tc in tool_calls])}"
        )
    return f"Message to {recipient} from {role}: [empty]"


def _tool_mutates_state(tool_name: str) -> bool:
    non_mutating_prefixes = (
        "get_",
        "list_",
        "search_",
        "find_",
        "lookup_",
        "read_",
        "check_",
        "validate_",
    )
    non_mutating_exact = {"transfer_to_human_agents"}
    return not (tool_name in non_mutating_exact or tool_name.startswith(non_mutating_prefixes))


def _agent_system_prompt(
    domain_policy: str,
    *,
    guard_id: str = "none",
    guard_text: str = "",
) -> str:
    prompt = (
        "Agent: GEODE running inside tau2-bench.\n"
        "Follow the domain policy exactly. Use the provided tools to change the "
        "environment state when the user asks for an operation. Do not invent "
        "tool results or missing user facts. When calling a tool, provide every "
        "required argument, but leave optional arguments unset unless the user, "
        "the policy, or a prior tool result explicitly supplied that value. Do "
        "not add inferred descriptions, notes, dates, preferences, quantities, "
        "or metadata. When the requested state change is complete, answer the "
        "user concisely and do not ask for unrelated follow-up details.\n\n"
        "<policy>\n"
        f"{domain_policy}\n"
        "</policy>"
    )
    guard = guard_text.strip()
    if not guard:
        return prompt
    return (
        f"{prompt}\n\n"
        f'<crucible_candidate_guard id="{guard_id}">\n'
        f"{guard}\n"
        "</crucible_candidate_guard>"
    )


def _load_agent_guard(agent_guard: str, append_file: Path | None) -> tuple[str, str]:
    parts: list[str] = []
    guard_id = agent_guard
    if agent_guard != "none":
        parts.append(CRUCIBLE_GUARDS[agent_guard])
    if append_file is not None:
        custom = append_file.read_text().strip()
        if custom:
            parts.append(custom)
            guard_id = agent_guard if agent_guard != "none" else "custom"
    return guard_id, "\n\n".join(parts)


def _load_agent_planner(agent_planner: str) -> tuple[str, str]:
    if agent_planner == "none":
        return "none", ""
    if agent_planner != "telecom-mms-v1":
        raise ValueError(f"unknown Crucible agent planner: {agent_planner}")

    from scripts.eval.telecom_action_planner import MmsState, plan_mms_actions

    planned_actions = plan_mms_actions(
        MmsState(
            airplane_mode_on=True,
            sim_active=False,
            mobile_data_on=False,
            network_type="2G",
            apn_mmsc_configured=False,
        )
    )
    action_names = [action.name for action in planned_actions]
    action_lines = "\n".join(
        f"{idx}. {action.name}({json.dumps(action.arguments, sort_keys=True)})"
        for idx, action in enumerate(planned_actions, start=1)
    )
    bundled_actions = "; ".join(action_names)
    return (
        "telecom-mms-v1",
        (
            "Telecom MMS deterministic planner candidate v1.\n"
            "Use this only for telecom MMS troubleshooting tasks where the current "
            "state or user/tool evidence shows this blocker pattern: airplane mode "
            "on, SIM missing or inactive, mobile data off, 2G-only or 2G-preferred "
            "network mode, and missing APN/MMSC configuration.\n\n"
            "Follow this ordered plan before the terminal verifier:\n"
            f"{action_lines}\n\n"
            "When the user simulator must perform phone-side actions, ask for these "
            "safe actions in one consolidated update instead of spreading them across "
            f"separate turns: {bundled_actions}.\n\n"
            "Do not call or ask about can_send_mms before APN/MMSC is confirmed "
            "configured and the airplane-mode, SIM, mobile-data, and non-2G network "
            "blockers are clear. After those blockers are clear, ask exactly one "
            "terminal verification: can_send_mms. Do not branch into Wi-Fi calling, "
            "app permissions, or unrelated escalation before that terminal "
            "verification."
        ),
    )


def _compose_agent_candidate_surface(
    *,
    agent_guard: str,
    guard_text: str,
    agent_planner: str,
    planner_text: str,
) -> tuple[str, str]:
    ids = [part for part in (agent_guard, agent_planner) if part != "none"]
    candidate_id = "+".join(ids) if ids else "none"
    text = "\n\n".join(part for part in (guard_text.strip(), planner_text.strip()) if part)
    return candidate_id, text


def _user_system_prompt(
    instructions: str | None,
    *,
    use_tools: bool,
    append_text: str = "",
) -> str:
    from tau2.user.user_simulator import get_global_user_sim_guidelines

    guidelines = get_global_user_sim_guidelines(use_tools=use_tools)
    prompt = (
        "Role: simulated tau2 benchmark user running through GEODE.\n"
        "Boundary: not the assistant; customer/user in the scenario.\n"
        "Follow the scenario and simulator guidelines exactly. If the task is "
        "complete or the conversation should end, use tau2's required stop token "
        "when the guidelines call for it.\n\n"
        f"{guidelines}\n\n"
        "<scenario>\n"
        f"{instructions or ''}\n"
        "</scenario>"
    )
    append = append_text.strip()
    if not append:
        return prompt
    return f"{prompt}\n\n<crucible_user_sim_guard>\n{append}\n</crucible_user_sim_guard>"


def _build_loop(
    *,
    tools: list[Any] | None,
    system_prompt: str,
    model: str,
    provider: str,
    source: str,
    effort: str,
    time_budget_s: float,
    max_tokens: int,
    max_rounds: int,
) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    handlers: dict[str, Any] = {}
    for tau2_tool in tools or []:
        wrapped = Tau2GeodeTool(tau2_tool, mutates_state=_tool_mutates_state(str(tau2_tool.name)))
        tool_registry.register(wrapped)
        handlers[wrapped.name] = wrapped.aexecute

    executor = ToolExecutor(action_handlers=handlers, auto_approve=True, hitl_level=0)
    allowed_tool_names = set(handlers)
    return AgenticLoop(
        ConversationContext(max_turns=200),
        executor,
        model=model,
        provider=provider,
        source=source,
        effort=effort,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
        time_budget_s=time_budget_s,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        system_prompt_override=system_prompt,
        quiet=True,
        enable_goal_decomposition=False,
    )


def _usage_dict(result: Any) -> dict[str, Any] | None:
    result_usage = getattr(result, "usage", None)
    if result_usage is None:
        return None
    to_dict = getattr(result_usage, "to_dict", None)
    if callable(to_dict):
        maybe_dict = to_dict()
        if isinstance(maybe_dict, Mapping):
            return {str(key): value for key, value in maybe_dict.items()}
        return None
    raw = getattr(result_usage, "__dict__", None)
    return {str(key): value for key, value in raw.items()} if isinstance(raw, dict) else None


def _tau2_tool_calls(result: Any, *, requestor: str) -> list[Any]:
    from tau2.data_model.message import ToolCall

    calls = []
    for idx, entry in enumerate(getattr(result, "tool_calls", []) or []):
        if not isinstance(entry, dict):
            continue
        result_payload = entry.get("result")
        if isinstance(result_payload, dict) and result_payload.get("error"):
            continue
        tool_name = str(entry.get("tool", "") or "")
        tool_input = entry.get("input")
        if not tool_name or not isinstance(tool_input, dict):
            continue
        projected_args = {
            key: value for key, value in tool_input.items() if value is not None and value != ""
        }
        if (
            tool_name in {"modify_pending_order_address", "modify_user_address"}
            and "address2" not in projected_args
        ):
            projected_args["address2"] = ""
        calls.append(
            ToolCall(
                id=str(entry.get("tool_use_id") or f"geode_{requestor}_{idx}"),
                name=tool_name,
                arguments=projected_args,
                requestor=requestor,
            )
        )
    return calls


def _tool_call_names(tool_calls: list[Any]) -> set[str]:
    """Return tau2 ToolCall names across pydantic-like objects and dicts."""
    names: set[str] = set()
    for call in tool_calls:
        name = _tool_call_name(call)
        if name:
            names.add(str(name))
    return names


def _dedupe_duplicate_tool_calls(
    tool_calls: list[Any],
    *,
    branch_corrections: list[str],
) -> list[Any]:
    """Drop exact duplicate tool calls inside one projected tau2 turn."""
    deduped: list[Any] = []
    seen: set[str] = set()
    dropped = False
    for call in tool_calls:
        name = _tool_call_name(call)
        arguments = _tool_call_arguments(call)
        key = json.dumps([name, arguments], sort_keys=True, separators=(",", ":"), default=str)
        if key in seen:
            dropped = True
            continue
        seen.add(key)
        deduped.append(call)
    if dropped:
        branch_corrections.append("duplicate_tool_call_dedupe")
    return deduped


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    return str(content or "").strip()


def _tool_call_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or "")
    return str(getattr(call, "name", "") or "")


def _tool_call_arguments(call: Any) -> dict[str, Any]:
    if isinstance(call, dict):
        arguments = call.get("arguments")
    else:
        arguments = getattr(call, "arguments", None)
    return arguments if isinstance(arguments, dict) else {}


def _string_set(value: Any) -> set[str]:
    if isinstance(value, list | tuple | set):
        return {str(item) for item in value if item is not None and str(item)}
    if value is None or value == "":
        return set()
    return {str(value)}


def _retail_write_preflight_enabled(domain_policy: str) -> bool:
    policy = domain_policy.lower()
    return "retail agent" in policy or "modify pending order" in policy


def _build_retail_write_preflight(domain_policy: str) -> RetailWritePreflight | None:
    return RetailWritePreflight.empty() if _retail_write_preflight_enabled(domain_policy) else None


def _observe_retail_preflight_message(state: GeodeTau2State, message: Any) -> None:
    if state.retail_write_preflight is not None:
        state.retail_write_preflight.observe_incoming_message(message)


def _project_account_roaming_repair_from_prompt(prompt: str) -> tuple[str, str] | None:
    """Extract a safe account-roaming repair action from visible tau2 tool output."""
    prompt = prompt.replace('\\"', '"')
    customer_match = re.search(
        r'"customer_id"\s*:\s*"(?P<customer_id>C[^"]+)".*?'
        r'"phone_number"\s*:\s*"(?P<phone_number>[^"]+)"',
        prompt,
        flags=re.DOTALL,
    )
    if customer_match is None:
        return None
    customer_id = customer_match.group("customer_id")
    active_phone = customer_match.group("phone_number")
    line_pattern = re.compile(
        r'"line_id"\s*:\s*"(?P<line_id>L[^"]+)".*?'
        r'"phone_number"\s*:\s*"(?P<phone_number>[^"]+)".*?'
        r'"roaming_enabled"\s*:\s*false',
        flags=re.DOTALL,
    )
    for match in line_pattern.finditer(prompt):
        if match.group("phone_number") == active_phone:
            return customer_id, match.group("line_id")
    return None


def _project_account_roaming_repair_from_workflow_order(
    workflow_order: Any | None,
) -> tuple[str, str] | None:
    """Extract a safe account-roaming repair action from tracked workflow state."""
    if workflow_order is None:
        return None
    due = getattr(workflow_order, "known_account_roaming_repair_due", None)
    if not callable(due) or not due():
        return None
    customer_id = getattr(workflow_order, "active_customer_id", None)
    line_id = getattr(workflow_order, "active_line_id", None)
    if isinstance(customer_id, str) and customer_id and isinstance(line_id, str) and line_id:
        return customer_id, line_id
    return None


def _project_data_usage_lookup_from_workflow_order(
    workflow_order: Any | None,
) -> tuple[str, str] | None:
    """Extract a data-usage lookup action from tracked workflow state."""
    if workflow_order is None:
        return None
    due = getattr(workflow_order, "data_usage_lookup_due", None)
    if not callable(due) or not due():
        return None
    customer_id = getattr(workflow_order, "active_customer_id", None)
    line_id = getattr(workflow_order, "active_line_id", None)
    if isinstance(customer_id, str) and customer_id and isinstance(line_id, str) and line_id:
        return customer_id, line_id
    return None


def _project_data_refuel_from_workflow_order(
    workflow_order: Any | None,
) -> tuple[str, str, float] | None:
    """Extract a deterministic data-refuel action from tracked workflow state."""
    if workflow_order is None:
        return None
    due = getattr(workflow_order, "data_refuel_due", None)
    if not callable(due) or not due():
        return None
    customer_id = getattr(workflow_order, "active_customer_id", None)
    line_id = getattr(workflow_order, "active_line_id", None)
    if isinstance(customer_id, str) and customer_id and isinstance(line_id, str) and line_id:
        return customer_id, line_id, 2.0
    return None


def _project_retail_address_writes_from_workflow_order(
    workflow_order: Any | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Extract deterministic retail address writes from tracked workflow state."""
    if workflow_order is None:
        return []
    projected = getattr(workflow_order, "projected_retail_address_writes", None)
    if not callable(projected):
        return []
    raw_actions = projected()
    if not isinstance(raw_actions, list):
        return []
    actions: list[tuple[str, dict[str, Any]]] = []
    for action in raw_actions:
        if not isinstance(action, tuple) or len(action) != 2:
            continue
        name, arguments = action
        if isinstance(name, str) and isinstance(arguments, dict):
            actions.append((name, arguments))
    return actions


def _project_retail_return_writes_from_workflow_order(
    workflow_order: Any | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Extract deterministic retail return writes from tracked workflow state."""
    if workflow_order is None:
        return []
    projected = getattr(workflow_order, "projected_retail_return_writes", None)
    if not callable(projected):
        return []
    raw_actions = projected()
    if not isinstance(raw_actions, list):
        return []
    actions: list[tuple[str, dict[str, Any]]] = []
    for action in raw_actions:
        if not isinstance(action, tuple) or len(action) != 2:
            continue
        name, arguments = action
        if isinstance(name, str) and isinstance(arguments, dict):
            actions.append((name, arguments))
    return actions


def _project_retail_pending_item_writes_from_workflow_order(
    workflow_order: Any | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Extract deterministic retail pending-item writes from tracked workflow state."""
    if workflow_order is None:
        return []
    projected = getattr(workflow_order, "projected_retail_pending_item_writes", None)
    if not callable(projected):
        return []
    raw_actions = projected()
    if not isinstance(raw_actions, list):
        return []
    actions: list[tuple[str, dict[str, Any]]] = []
    for action in raw_actions:
        if not isinstance(action, tuple) or len(action) != 2:
            continue
        name, arguments = action
        if isinstance(name, str) and isinstance(arguments, dict):
            actions.append((name, arguments))
    return actions


def _project_line_detail_lookup_from_workflow_order(
    workflow_order: Any | None,
) -> list[str]:
    """Extract candidate line-detail lookups from tracked workflow state."""
    if workflow_order is None:
        return []
    due = getattr(workflow_order, "line_detail_lookup_due", None)
    if not callable(due) or not due():
        return []
    line_ids = getattr(workflow_order, "candidate_line_ids", None)
    if not isinstance(line_ids, list):
        return []
    issued_raw: Any = getattr(workflow_order, "issued_projected_line_detail_ids", set())
    issued = issued_raw if isinstance(issued_raw, set) else set()
    unissued = [
        line_id
        for line_id in line_ids
        if isinstance(line_id, str) and line_id and line_id not in issued
    ]
    phone_number = getattr(workflow_order, "active_phone_number", None)
    if isinstance(phone_number, str):
        phone_suffix = re.sub(r"\D", "", phone_number)[-4:]
        suffix_matches = [
            line_id
            for line_id in unissued
            if re.sub(r"\D", "", line_id)[-4:].endswith(phone_suffix[-1:])
        ]
        if len(suffix_matches) == 1:
            return suffix_matches
    return unissued


def _project_account_identity_lookup_from_workflow_order(
    workflow_order: Any | None,
) -> str | None:
    """Extract an account lookup action when the phone number is already known."""
    if workflow_order is None:
        return None
    due = getattr(workflow_order, "account_identity_lookup_due", None)
    if not callable(due) or not due():
        return None
    phone_number = getattr(workflow_order, "active_phone_number", None)
    if isinstance(phone_number, str) and phone_number:
        return phone_number
    return None


def _projected_user_identity_text(phone_number: str, workflow_order: Any | None) -> str:
    """Render a grounded identity/status summary for diagnostic user projection."""
    base = f"The affected phone number is {phone_number}."
    blockers_clear = getattr(workflow_order, "blockers_clear", None)
    device_roaming_on = getattr(workflow_order, "device_roaming_on", None)
    if callable(blockers_clear) and blockers_clear():
        parts = [
            "Airplane Mode is off",
            "the SIM is active",
            "mobile data is on",
            "the preferred network is 4G/5G",
            "the APN MMSC URL is configured",
        ]
        if device_roaming_on is True:
            parts.append("data roaming is on")
        return f"{base} {'; '.join(parts)}."
    return base


def _project_user_actions_after_observed_text(
    workflow_order: Any | None,
    text: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Convert a grounded user status text into the next deterministic action."""
    if workflow_order is None or not text.strip():
        return []
    observe_user_text = getattr(workflow_order, "observe_user_text", None)
    if callable(observe_user_text):
        observe_user_text(text)
    projected_user_tool_actions = getattr(
        workflow_order,
        "projected_user_tool_actions",
        None,
    )
    if not callable(projected_user_tool_actions):
        return []
    raw_actions = projected_user_tool_actions()
    actions: list[tuple[str, dict[str, Any]]] = []
    for action in raw_actions:
        if not isinstance(action, tuple) or len(action) != 2:
            continue
        name, arguments = action
        if isinstance(name, str) and isinstance(arguments, dict):
            actions.append((name, arguments))
    if not actions:
        return []
    mark_actions = getattr(workflow_order, "mark_projected_user_tool_actions", None)
    if callable(mark_actions):
        mark_actions(actions)
    return actions


def _post_text_projection_enabled(user_action_projector: str) -> bool:
    """Return True when native user text can be compressed into deterministic actions."""
    if user_action_projector == "telecom-mms-prereq-v4":
        return True
    match = re.fullmatch(r"telecom-mms-prereq-v(\d+)", user_action_projector)
    return bool(match and int(match.group(1)) >= 68)


def _project_user_actions_for_premature_terminal(
    workflow_order: Any | None,
    tool_calls: list[Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Return deterministic user actions that should replace premature MMS verification."""
    if workflow_order is None or not tool_calls:
        return []
    premature_terminal_tool = getattr(workflow_order, "premature_terminal_tool", None)
    if not callable(premature_terminal_tool):
        return []
    if not any(
        premature_terminal_tool(str(getattr(call, "name", "") or "")) for call in tool_calls
    ):
        return []
    projected_user_tool_actions = getattr(
        workflow_order,
        "projected_user_tool_actions",
        None,
    )
    if not callable(projected_user_tool_actions):
        return []
    actions: list[tuple[str, dict[str, Any]]] = []
    for action in projected_user_tool_actions():
        if not isinstance(action, tuple) or len(action) != 2:
            continue
        name, arguments = action
        if isinstance(name, str) and isinstance(arguments, dict):
            actions.append((name, arguments))
    return actions


def _workflow_user_projection_ready(workflow_order: Any | None, messages_seen: int) -> bool:
    """Return True when deterministic user projection may continue this turn."""
    if workflow_order is None:
        return False
    if messages_seen > 0:
        return True
    issued = getattr(workflow_order, "issued_projected_action_keys", None)
    return bool(issued)


def _project_phone_number_from_user_instructions(instructions: Any | None) -> str | None:
    """Extract the simulated user's affected phone number from scenario instructions."""
    if not instructions:
        return None
    if isinstance(instructions, str):
        match = re.search(r"\b\d{3}-\d{3}-\d{4}\b", instructions)
        return match.group(0) if match else None
    if isinstance(instructions, Mapping):
        for value in instructions.values():
            phone_number = _project_phone_number_from_user_instructions(value)
            if phone_number is not None:
                return phone_number
    if isinstance(instructions, list | tuple):
        for value in instructions:
            phone_number = _project_phone_number_from_user_instructions(value)
            if phone_number is not None:
                return phone_number
    model_dump = getattr(instructions, "model_dump", None)
    if callable(model_dump):
        phone_number = _project_phone_number_from_user_instructions(model_dump())
        if phone_number is not None:
            return phone_number
    dict_method = getattr(instructions, "dict", None)
    if callable(dict_method):
        phone_number = _project_phone_number_from_user_instructions(dict_method())
        if phone_number is not None:
            return phone_number
    raw_dict = getattr(instructions, "__dict__", None)
    if isinstance(raw_dict, Mapping):
        phone_number = _project_phone_number_from_user_instructions(raw_dict)
        if phone_number is not None:
            return phone_number
    match = re.search(r"\b\d{3}-\d{3}-\d{4}\b", str(instructions))
    if match:
        return match.group(0)
    return None


def _observe_workflow_result_tool_outputs(result: Any, workflow_order: Any | None) -> None:
    """Feed GEODE-executed read-tool outputs into the workflow scaffold immediately."""
    if workflow_order is None:
        return
    for entry in getattr(result, "tool_calls", []) or []:
        if not isinstance(entry, dict):
            continue
        tool_name = str(entry.get("tool", "") or "")
        if not tool_name:
            continue
        result_payload = entry.get("result")
        if isinstance(result_payload, dict) and result_payload.get("error"):
            continue
        if isinstance(result_payload, dict) and "result" in result_payload:
            output = result_payload.get("result")
        elif isinstance(result_payload, dict) and "output" in result_payload:
            output = result_payload.get("output")
        elif isinstance(result_payload, dict) and "content" in result_payload:
            output = result_payload.get("content")
        elif isinstance(result_payload, dict) and "text" in result_payload:
            output = result_payload.get("text")
        else:
            output = result_payload
        if output is not None:
            workflow_order.observe_tool_output(tool_name, output)


def _apply_retail_write_preflight(
    state: GeodeTau2State,
    result: Any,
    tool_calls: list[Any],
    *,
    codex_empty_text_retries: int,
    branch_corrections: list[str],
) -> tuple[Any, list[Any]]:
    preflight = state.retail_write_preflight
    if preflight is None or not tool_calls:
        return result, tool_calls
    violations = preflight.validate_tool_calls(tool_calls)
    if not violations or state.retail_preflight_retries >= RETAIL_WRITE_PREFLIGHT_MAX_RETRIES:
        return result, tool_calls

    state.retail_preflight_retries += 1
    branch_corrections.append("retail_write_preflight")
    corrected_result = _run_geode_turn_with_empty_text_retry(
        state,
        preflight.correction_prompt(violations),
        max_retries=codex_empty_text_retries,
    )
    _observe_workflow_result_tool_outputs(corrected_result, state.workflow_order)
    return corrected_result, _tau2_tool_calls(corrected_result, requestor="assistant")


def _apply_premature_transfer_guard(
    state: GeodeTau2State,
    result: Any,
    tool_calls: list[Any],
    *,
    codex_empty_text_retries: int,
    branch_corrections: list[str],
) -> tuple[Any, list[Any]]:
    if state.workflow_order is None or not tool_calls:
        return result, tool_calls
    if "transfer_to_human_agents" not in _tool_call_names(tool_calls):
        return result, tool_calls
    correction_prompt_fn = getattr(
        state.workflow_order,
        "premature_transfer_correction_prompt",
        None,
    )
    if (
        not callable(correction_prompt_fn)
        or state.workflow_gate_retries >= WORKFLOW_GATE_MAX_RETRIES
    ):
        return result, tool_calls
    correction_prompt = correction_prompt_fn()
    if correction_prompt is None:
        return result, tool_calls

    state.workflow_gate_retries += 1
    branch_corrections.append("workflow_order")
    corrected_result = _run_geode_turn_with_empty_text_retry(
        state,
        correction_prompt,
        max_retries=codex_empty_text_retries,
    )
    _observe_workflow_result_tool_outputs(corrected_result, state.workflow_order)
    return corrected_result, _tau2_tool_calls(corrected_result, requestor="assistant")


def _apply_retail_variant_selection_guard(
    state: GeodeTau2State,
    result: Any,
    tool_calls: list[Any],
    *,
    codex_empty_text_retries: int,
    branch_corrections: list[str],
) -> tuple[Any, list[Any]]:
    if state.workflow_order is None or not tool_calls:
        return result, tool_calls
    correction_prompt_fn = getattr(
        state.workflow_order,
        "variant_selection_correction_prompt",
        None,
    )
    if (
        not callable(correction_prompt_fn)
        or state.retail_variant_selection_retries >= RETAIL_VARIANT_SELECTION_MAX_RETRIES
    ):
        return result, tool_calls
    correction_prompt = correction_prompt_fn(tool_calls)
    if correction_prompt is None:
        return result, tool_calls

    state.retail_variant_selection_retries += 1
    branch_corrections.append("retail_variant_selection")
    corrected_result = _run_geode_turn_with_empty_text_retry(
        state,
        correction_prompt,
        max_retries=codex_empty_text_retries,
    )
    _observe_workflow_result_tool_outputs(corrected_result, state.workflow_order)
    return corrected_result, _tau2_tool_calls(corrected_result, requestor="assistant")


def _apply_retail_pending_item_terminal_guard(
    state: GeodeTau2State,
    result: Any,
    tool_calls: list[Any],
    *,
    codex_empty_text_retries: int,
    branch_corrections: list[str],
) -> tuple[Any, list[Any]]:
    if state.workflow_order is None or not tool_calls:
        return result, tool_calls
    correction_prompt_fn = getattr(
        state.workflow_order,
        "pending_item_terminal_write_correction_prompt",
        None,
    )
    if (
        not callable(correction_prompt_fn)
        or state.retail_pending_item_terminal_retries >= RETAIL_PENDING_ITEM_TERMINAL_MAX_RETRIES
    ):
        return result, tool_calls
    correction_prompt = correction_prompt_fn(tool_calls)
    if correction_prompt is None:
        return result, tool_calls

    state.retail_pending_item_terminal_retries += 1
    branch_corrections.append("retail_pending_item_terminal")
    corrected_result = _run_geode_turn_with_empty_text_retry(
        state,
        correction_prompt,
        max_retries=codex_empty_text_retries,
    )
    _observe_workflow_result_tool_outputs(corrected_result, state.workflow_order)
    return corrected_result, _tau2_tool_calls(corrected_result, requestor="assistant")


def _apply_no_tool_workflow_correction(
    state: GeodeTau2State,
    result: Any,
    *,
    agent_guard_id: str,
    agent_workflow_order: str,
    started: float,
    codex_empty_text_retries: int,
    branch_corrections: list[str],
) -> tuple[Any | None, Any, list[Any]]:
    """Correct text-only workflow claims before returning a visible assistant turn."""
    if state.workflow_order is None:
        return None, result, []
    correction_prompt = state.workflow_order.branch_correction_prompt(_result_text(result))
    if correction_prompt is None or state.workflow_gate_retries >= WORKFLOW_GATE_MAX_RETRIES:
        return None, result, []
    retail_projector_assistant = _build_retail_projector_assistant(
        state.workflow_order,
        agent_guard_id=agent_guard_id,
        agent_workflow_order=agent_workflow_order,
        started=started,
    )
    if retail_projector_assistant is not None:
        state.workflow_order.observe_outgoing_tool_calls(
            getattr(retail_projector_assistant, "tool_calls", []) or []
        )
        return retail_projector_assistant, result, []
    state.workflow_gate_retries += 1
    branch_corrections.append("workflow_order")
    corrected_result = _run_geode_turn_with_empty_text_retry(
        state,
        correction_prompt,
        max_retries=codex_empty_text_retries,
    )
    _observe_workflow_result_tool_outputs(corrected_result, state.workflow_order)
    return None, corrected_result, _tau2_tool_calls(corrected_result, requestor="assistant")


def _drop_premature_transfer_from_read_bundle(
    tool_calls: list[Any],
    *,
    branch_corrections: list[str],
) -> list[Any]:
    if "transfer_to_human_agents" not in _tool_call_names(tool_calls):
        return tool_calls
    non_transfer_calls = [
        call
        for call in tool_calls
        if str(getattr(call, "name", "") or "") != "transfer_to_human_agents"
    ]
    if not non_transfer_calls:
        return tool_calls
    branch_corrections.append("premature_transfer_bundle")
    return non_transfer_calls


def _project_cancelled_order_tracking_response(workflow_order: Any | None) -> str | None:
    if workflow_order is None:
        return None
    response_fn = getattr(workflow_order, "cancelled_order_tracking_response", None)
    if not callable(response_fn):
        return None
    response = response_fn()
    if not isinstance(response, str):
        return None
    mark_sent = getattr(workflow_order, "mark_cancelled_order_tracking_sent", None)
    if callable(mark_sent):
        mark_sent()
    return response


def _build_retail_projector_assistant(
    workflow_order: Any | None,
    *,
    agent_guard_id: str,
    agent_workflow_order: str,
    started: float,
) -> Any | None:
    from tau2.data_model.message import AssistantMessage, ToolCall

    projected_retail_address_writes = _project_retail_address_writes_from_workflow_order(
        workflow_order
    )
    if projected_retail_address_writes:
        return AssistantMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=f"geode_agent_projector_{name}_{idx}",
                    name=name,
                    arguments=arguments,
                    requestor="assistant",
                )
                for idx, (name, arguments) in enumerate(projected_retail_address_writes)
            ],
            usage={},
            raw_data={
                "geode_rounds": 0,
                "geode_termination_reason": "workflow_projector",
                "geode_tool_call_count": len(projected_retail_address_writes),
                "geode_tool_projection": "tau2_orchestrator",
                "geode_agent_guard": agent_guard_id,
                "geode_workflow_order": agent_workflow_order,
                "geode_premature_terminal_tools": [],
                "geode_workflow_branch_corrections": ["workflow_order_retail_address_projector"],
                "geode_projection_diagnostic_only": True,
            },
            generation_time_seconds=time.monotonic() - started,
        )
    projected_retail_return_writes = _project_retail_return_writes_from_workflow_order(
        workflow_order
    )
    if projected_retail_return_writes:
        return AssistantMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=f"geode_agent_projector_{name}_{idx}",
                    name=name,
                    arguments=arguments,
                    requestor="assistant",
                )
                for idx, (name, arguments) in enumerate(projected_retail_return_writes)
            ],
            usage={},
            raw_data={
                "geode_rounds": 0,
                "geode_termination_reason": "workflow_projector",
                "geode_tool_call_count": len(projected_retail_return_writes),
                "geode_tool_projection": "tau2_orchestrator",
                "geode_agent_guard": agent_guard_id,
                "geode_workflow_order": agent_workflow_order,
                "geode_premature_terminal_tools": [],
                "geode_workflow_branch_corrections": ["workflow_order_retail_return_projector"],
                "geode_projection_diagnostic_only": True,
            },
            generation_time_seconds=time.monotonic() - started,
        )
    projected_retail_pending_item_writes = _project_retail_pending_item_writes_from_workflow_order(
        workflow_order
    )
    if projected_retail_pending_item_writes:
        return AssistantMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=f"geode_agent_projector_{name}_{idx}",
                    name=name,
                    arguments=arguments,
                    requestor="assistant",
                )
                for idx, (name, arguments) in enumerate(projected_retail_pending_item_writes)
            ],
            usage={},
            raw_data={
                "geode_rounds": 0,
                "geode_termination_reason": "workflow_projector",
                "geode_tool_call_count": len(projected_retail_pending_item_writes),
                "geode_tool_projection": "tau2_orchestrator",
                "geode_agent_guard": agent_guard_id,
                "geode_workflow_order": agent_workflow_order,
                "geode_premature_terminal_tools": [],
                "geode_workflow_branch_corrections": [
                    "workflow_order_retail_pending_item_projector"
                ],
                "geode_projection_diagnostic_only": True,
            },
            generation_time_seconds=time.monotonic() - started,
        )
    cancelled_tracking_response = _project_cancelled_order_tracking_response(workflow_order)
    if cancelled_tracking_response is not None:
        return AssistantMessage.text(
            cancelled_tracking_response,
            usage={},
            raw_data={
                "geode_rounds": 0,
                "geode_termination_reason": "workflow_projector",
                "geode_tool_call_count": 0,
                "geode_agent_guard": agent_guard_id,
                "geode_workflow_order": agent_workflow_order,
                "geode_premature_terminal_tools": [],
                "geode_workflow_branch_corrections": [
                    "workflow_order_cancelled_tracking_projector"
                ],
                "geode_projection_diagnostic_only": True,
            },
            generation_time_seconds=time.monotonic() - started,
        )
    return None


def _hydrate_workflow_order_from_history(
    workflow_order: Any | None,
    message_history: list[Any] | None,
) -> None:
    """Replay tau2 message history into a workflow scaffold after state rebuilds."""
    if workflow_order is None or not message_history:
        return
    for message in message_history:
        workflow_order.observe_incoming_message(message)


def register_geode_tau2_participants(
    *,
    agent_model: str,
    agent_provider: str,
    agent_source: str,
    agent_effort: str,
    agent_time_budget_s: float,
    agent_max_tokens: int,
    agent_max_rounds: int,
    user_model: str,
    user_provider: str,
    user_source: str,
    user_effort: str,
    user_time_budget_s: float,
    user_max_tokens: int,
    user_max_rounds: int,
    user_prompt_append_text: str = "",
    agent_guard_id: str = "none",
    agent_guard_text: str = "",
    agent_workflow_order: str = "none",
    user_action_projector: str = "none",
    fail_on_empty_geode_turn: bool = True,
    codex_empty_text_retries: int = 1,
) -> None:
    from core.llm.adapters.registry import bootstrap_builtins
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage
    from tau2.registry import registry
    from tau2.user.user_simulator_base import HalfDuplexUser

    bootstrap_builtins()

    class GeodeTau2Agent(HalfDuplexAgent[GeodeTau2State]):
        def get_init_state(self, message_history: list[Any] | None = None) -> GeodeTau2State:
            from plugins.benchmark_harness.tau2_workflow_order import (
                build_workflow_order_scaffold,
            )

            loop = _build_loop(
                tools=self.tools,
                system_prompt=_agent_system_prompt(
                    self.domain_policy,
                    guard_id=agent_guard_id,
                    guard_text=agent_guard_text,
                ),
                model=agent_model,
                provider=agent_provider,
                source=agent_source,
                effort=agent_effort,
                time_budget_s=agent_time_budget_s,
                max_tokens=agent_max_tokens,
                max_rounds=agent_max_rounds,
            )
            state = GeodeTau2State(
                loop=loop,
                workflow_order=build_workflow_order_scaffold(agent_workflow_order),
                retail_write_preflight=_build_retail_write_preflight(self.domain_policy),
            )
            if message_history:
                _hydrate_workflow_order_from_history(state.workflow_order, message_history)
                for history_message in message_history:
                    _observe_retail_preflight_message(state, history_message)
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            if state.workflow_order is not None:
                state.workflow_order.observe_incoming_message(message)
            _observe_retail_preflight_message(state, message)
            branch_corrections: list[str] = []
            prompt = _message_to_prompt(message, recipient="assistant agent")
            if state.workflow_order is not None:
                correction_prompt = state.workflow_order.branch_correction_prompt("")
                if (
                    correction_prompt is not None
                    and state.workflow_gate_retries < WORKFLOW_GATE_MAX_RETRIES
                ):
                    state.workflow_gate_retries += 1
                    branch_corrections.append("workflow_order")
                    prompt = correction_prompt
                prompt = (
                    f"{prompt}\n\n"
                    "<crucible_workflow_order>\n"
                    f"{state.workflow_order.prompt_hint()}\n"
                    "</crucible_workflow_order>"
                )
                account_lookup_due = getattr(
                    state.workflow_order, "account_identity_lookup_due", None
                )
                if callable(account_lookup_due) and account_lookup_due():
                    projected_phone = _project_account_identity_lookup_from_workflow_order(
                        state.workflow_order
                    )
                    if projected_phone:
                        assistant = AssistantMessage(
                            role="assistant",
                            tool_calls=[
                                ToolCall(
                                    id="geode_agent_projector_get_customer_by_phone",
                                    name="get_customer_by_phone",
                                    arguments={"phone_number": projected_phone},
                                    requestor="assistant",
                                )
                            ],
                            usage={},
                            raw_data={
                                "geode_rounds": 0,
                                "geode_termination_reason": "workflow_projector",
                                "geode_tool_call_count": 1,
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_agent_guard": agent_guard_id,
                                "geode_workflow_order": agent_workflow_order,
                                "geode_premature_terminal_tools": [],
                                "geode_workflow_branch_corrections": [
                                    "workflow_order_account_identity_lookup_projector"
                                ],
                                "geode_projection_diagnostic_only": True,
                            },
                            generation_time_seconds=time.monotonic() - started,
                        )
                        state.workflow_order.observe_outgoing_tool_calls(assistant.tool_calls)
                        return assistant, state
                    assistant = AssistantMessage.text(
                        (
                            "Please provide the affected phone number first so I can "
                            "inspect the account and active line before any terminal MMS "
                            "verification."
                        ),
                        usage={},
                        raw_data={
                            "geode_rounds": 0,
                            "geode_termination_reason": "workflow_projector",
                            "geode_tool_call_count": 0,
                            "geode_agent_guard": agent_guard_id,
                            "geode_workflow_order": agent_workflow_order,
                            "geode_premature_terminal_tools": [],
                            "geode_workflow_branch_corrections": [
                                "workflow_order_account_identity_projector"
                            ],
                            "geode_projection_diagnostic_only": True,
                        },
                        generation_time_seconds=time.monotonic() - started,
                    )
                    state.workflow_order.observe_outgoing_tool_calls(assistant.tool_calls)
                    return assistant, state
                projected_line_ids = _project_line_detail_lookup_from_workflow_order(
                    state.workflow_order
                )
                if projected_line_ids:
                    mark_line_details = getattr(
                        state.workflow_order,
                        "mark_projected_line_detail_lookups",
                        None,
                    )
                    if callable(mark_line_details):
                        mark_line_details(projected_line_ids)
                    assistant = AssistantMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id=f"geode_agent_projector_get_details_{idx}",
                                name="get_details_by_id",
                                arguments={"id": line_id},
                                requestor="assistant",
                            )
                            for idx, line_id in enumerate(projected_line_ids)
                        ],
                        usage={},
                        raw_data={
                            "geode_rounds": 0,
                            "geode_termination_reason": "workflow_projector",
                            "geode_tool_call_count": len(projected_line_ids),
                            "geode_tool_projection": "tau2_orchestrator",
                            "geode_agent_guard": agent_guard_id,
                            "geode_workflow_order": agent_workflow_order,
                            "geode_premature_terminal_tools": [],
                            "geode_workflow_branch_corrections": [
                                "workflow_order_line_detail_projector"
                            ],
                            "geode_projection_diagnostic_only": True,
                        },
                        generation_time_seconds=time.monotonic() - started,
                    )
                    state.workflow_order.observe_outgoing_tool_calls(assistant.tool_calls)
                    return assistant, state
                projected_repair = _project_account_roaming_repair_from_workflow_order(
                    state.workflow_order
                ) or _project_account_roaming_repair_from_prompt(prompt)
                if projected_repair is not None:
                    customer_id, line_id = projected_repair
                    assistant = AssistantMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id="geode_agent_projector_enable_roaming",
                                name="enable_roaming",
                                arguments={
                                    "customer_id": customer_id,
                                    "line_id": line_id,
                                },
                                requestor="assistant",
                            )
                        ],
                        usage={},
                        raw_data={
                            "geode_rounds": 0,
                            "geode_termination_reason": "workflow_projector",
                            "geode_tool_call_count": 1,
                            "geode_tool_projection": "tau2_orchestrator",
                            "geode_agent_guard": agent_guard_id,
                            "geode_workflow_order": agent_workflow_order,
                            "geode_premature_terminal_tools": [],
                            "geode_workflow_branch_corrections": ["workflow_order_projector"],
                            "geode_projection_diagnostic_only": True,
                        },
                        generation_time_seconds=time.monotonic() - started,
                    )
                    return assistant, state
                projected_data_lookup = _project_data_usage_lookup_from_workflow_order(
                    state.workflow_order
                )
                if projected_data_lookup is not None:
                    customer_id, line_id = projected_data_lookup
                    assistant = AssistantMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id="geode_agent_projector_get_data_usage",
                                name="get_data_usage",
                                arguments={
                                    "customer_id": customer_id,
                                    "line_id": line_id,
                                },
                                requestor="assistant",
                            )
                        ],
                        usage={},
                        raw_data={
                            "geode_rounds": 0,
                            "geode_termination_reason": "workflow_projector",
                            "geode_tool_call_count": 1,
                            "geode_tool_projection": "tau2_orchestrator",
                            "geode_agent_guard": agent_guard_id,
                            "geode_workflow_order": agent_workflow_order,
                            "geode_premature_terminal_tools": [],
                            "geode_workflow_branch_corrections": [
                                "workflow_order_data_usage_lookup_projector"
                            ],
                            "geode_projection_diagnostic_only": True,
                        },
                        generation_time_seconds=time.monotonic() - started,
                    )
                    state.workflow_order.observe_outgoing_tool_calls(assistant.tool_calls)
                    return assistant, state
                projected_refuel = _project_data_refuel_from_workflow_order(state.workflow_order)
                if projected_refuel is not None:
                    customer_id, line_id, gb_amount = projected_refuel
                    assistant = AssistantMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id="geode_agent_projector_refuel_data",
                                name="refuel_data",
                                arguments={
                                    "customer_id": customer_id,
                                    "line_id": line_id,
                                    "gb_amount": gb_amount,
                                },
                                requestor="assistant",
                            )
                        ],
                        usage={},
                        raw_data={
                            "geode_rounds": 0,
                            "geode_termination_reason": "workflow_projector",
                            "geode_tool_call_count": 1,
                            "geode_tool_projection": "tau2_orchestrator",
                            "geode_agent_guard": agent_guard_id,
                            "geode_workflow_order": agent_workflow_order,
                            "geode_premature_terminal_tools": [],
                            "geode_workflow_branch_corrections": [
                                "workflow_order_data_refuel_projector"
                            ],
                            "geode_projection_diagnostic_only": True,
                        },
                        generation_time_seconds=time.monotonic() - started,
                    )
                    state.workflow_order.observe_outgoing_tool_calls(assistant.tool_calls)
                    return assistant, state
                retail_projector_assistant = _build_retail_projector_assistant(
                    state.workflow_order,
                    agent_guard_id=agent_guard_id,
                    agent_workflow_order=agent_workflow_order,
                    started=started,
                )
                if retail_projector_assistant is not None:
                    state.workflow_order.observe_outgoing_tool_calls(
                        getattr(retail_projector_assistant, "tool_calls", []) or []
                    )
                    return retail_projector_assistant, state
            result = _run_geode_turn_with_empty_text_retry(
                state,
                prompt,
                max_retries=codex_empty_text_retries,
            )
            state.messages_seen += 1
            _observe_workflow_result_tool_outputs(result, state.workflow_order)
            tool_calls = _tau2_tool_calls(result, requestor="assistant")
            if state.workflow_order is not None and tool_calls:
                projected_repair = _project_account_roaming_repair_from_prompt(
                    _jsonish(getattr(result, "tool_calls", []) or [])
                )
                if projected_repair is not None and "enable_roaming" not in _tool_call_names(
                    tool_calls
                ):
                    customer_id, line_id = projected_repair
                    tool_calls = [
                        ToolCall(
                            id="geode_agent_projector_enable_roaming",
                            name="enable_roaming",
                            arguments={
                                "customer_id": customer_id,
                                "line_id": line_id,
                            },
                            requestor="assistant",
                        )
                    ]
                    branch_corrections.append("workflow_order_projector")
            if state.workflow_order is not None and tool_calls:
                redundant_account_lookup_tool = getattr(
                    state.workflow_order,
                    "redundant_account_lookup_tool",
                    None,
                )
                redundant_account_lookup = callable(redundant_account_lookup_tool) and any(
                    redundant_account_lookup_tool(str(getattr(call, "name", "") or ""))
                    for call in tool_calls
                )
                if (
                    redundant_account_lookup
                    and state.workflow_gate_retries < WORKFLOW_GATE_MAX_RETRIES
                ):
                    state.workflow_gate_retries += 1
                    branch_corrections.append("workflow_order")
                    correction_prompt = (
                        state.workflow_order.branch_correction_prompt("get_customer_by_id")
                        or state.workflow_order.prompt_hint()
                    )
                    result = _run_geode_turn_with_empty_text_retry(
                        state,
                        correction_prompt,
                        max_retries=codex_empty_text_retries,
                    )
                    _observe_workflow_result_tool_outputs(result, state.workflow_order)
                    tool_calls = _tau2_tool_calls(result, requestor="assistant")
            if state.workflow_order is not None and not tool_calls:
                early_assistant, result, tool_calls = _apply_no_tool_workflow_correction(
                    state,
                    result,
                    agent_guard_id=agent_guard_id,
                    agent_workflow_order=agent_workflow_order,
                    started=started,
                    codex_empty_text_retries=codex_empty_text_retries,
                    branch_corrections=branch_corrections,
                )
                if early_assistant is not None:
                    return early_assistant, state
            if state.workflow_order is not None and tool_calls:
                tool_names = _tool_call_names(tool_calls)
                correction_prompt = state.workflow_order.branch_correction_prompt(
                    _result_text(result)
                )
                if (
                    correction_prompt is not None
                    and "enable_roaming" not in tool_names
                    and state.workflow_gate_retries < WORKFLOW_GATE_MAX_RETRIES
                ):
                    state.workflow_gate_retries += 1
                    branch_corrections.append("workflow_order")
                    result = _run_geode_turn_with_empty_text_retry(
                        state,
                        correction_prompt,
                        max_retries=codex_empty_text_retries,
                    )
                    _observe_workflow_result_tool_outputs(result, state.workflow_order)
                    tool_calls = _tau2_tool_calls(result, requestor="assistant")
            if state.workflow_order is not None and tool_calls:
                terminal_before_repair = any(
                    state.workflow_order.premature_terminal_tool(
                        str(getattr(call, "name", "") or "")
                    )
                    for call in tool_calls
                )
                if (
                    terminal_before_repair
                    and state.workflow_gate_retries < WORKFLOW_GATE_MAX_RETRIES
                ):
                    correction_prompt = state.workflow_order.branch_correction_prompt(
                        "can_send_mms"
                    )
                    if (
                        correction_prompt is not None
                        and state.workflow_gate_retries < WORKFLOW_GATE_MAX_RETRIES
                    ):
                        state.workflow_gate_retries += 1
                        branch_corrections.append("workflow_order")
                        result = _run_geode_turn_with_empty_text_retry(
                            state,
                            correction_prompt,
                            max_retries=codex_empty_text_retries,
                        )
                        _observe_workflow_result_tool_outputs(result, state.workflow_order)
                        tool_calls = _tau2_tool_calls(result, requestor="assistant")
            tool_calls = _drop_premature_transfer_from_read_bundle(
                tool_calls,
                branch_corrections=branch_corrections,
            )
            result, tool_calls = _apply_premature_transfer_guard(
                state,
                result,
                tool_calls,
                codex_empty_text_retries=codex_empty_text_retries,
                branch_corrections=branch_corrections,
            )
            result, tool_calls = _apply_retail_variant_selection_guard(
                state,
                result,
                tool_calls,
                codex_empty_text_retries=codex_empty_text_retries,
                branch_corrections=branch_corrections,
            )
            result, tool_calls = _apply_retail_pending_item_terminal_guard(
                state,
                result,
                tool_calls,
                codex_empty_text_retries=codex_empty_text_retries,
                branch_corrections=branch_corrections,
            )
            result, tool_calls = _apply_retail_write_preflight(
                state,
                result,
                tool_calls,
                codex_empty_text_retries=codex_empty_text_retries,
                branch_corrections=branch_corrections,
            )
            tool_calls = _drop_premature_transfer_from_read_bundle(
                tool_calls,
                branch_corrections=branch_corrections,
            )
            tool_calls = _dedupe_duplicate_tool_calls(
                tool_calls,
                branch_corrections=branch_corrections,
            )
            premature_tools: list[str] = []
            if state.workflow_order is not None:
                premature_tools = [
                    str(getattr(call, "name", "") or "")
                    for call in tool_calls
                    if state.workflow_order.premature_terminal_tool(
                        str(getattr(call, "name", "") or "")
                    )
                ]
                state.workflow_order.observe_outgoing_tool_calls(tool_calls)
            if fail_on_empty_geode_turn:
                _assert_tau2_route_ready(
                    result,
                    projected_tool_calls=tool_calls,
                    role="assistant agent",
                )
            if tool_calls:
                assistant = AssistantMessage(
                    role="assistant",
                    tool_calls=tool_calls,
                    usage=_usage_dict(result),
                    raw_data={
                        "geode_rounds": getattr(result, "rounds", 0),
                        "geode_termination_reason": getattr(result, "termination_reason", ""),
                        "geode_tool_call_count": len(tool_calls),
                        "geode_tool_projection": "tau2_orchestrator",
                        "geode_agent_guard": agent_guard_id,
                        "geode_workflow_order": agent_workflow_order,
                        "geode_premature_terminal_tools": premature_tools,
                        "geode_workflow_branch_corrections": branch_corrections,
                    },
                    generation_time_seconds=time.monotonic() - started,
                )
                return assistant, state
            assistant = AssistantMessage.text(
                _result_text(result),
                usage=_usage_dict(result),
                raw_data={
                    "geode_rounds": getattr(result, "rounds", 0),
                    "geode_termination_reason": getattr(result, "termination_reason", ""),
                    "geode_tool_call_count": len(getattr(result, "tool_calls", []) or []),
                    "geode_agent_guard": agent_guard_id,
                    "geode_workflow_order": agent_workflow_order,
                    "geode_premature_terminal_tools": premature_tools,
                    "geode_workflow_branch_corrections": branch_corrections,
                },
                generation_time_seconds=time.monotonic() - started,
            )
            return assistant, state

        def set_seed(self, seed: int) -> None:
            return None

    def create_geode_agent(tools: list[Any], domain_policy: str, **_: Any) -> Any:
        return GeodeTau2Agent(tools=tools, domain_policy=domain_policy)

    class GeodeTau2User(HalfDuplexUser[GeodeTau2State]):
        def __init__(
            self,
            instructions: str | None = None,
            tools: list[Any] | None = None,
            **_: Any,
        ) -> None:
            super().__init__(instructions=instructions, tools=tools)

        def get_init_state(self, message_history: list[Any] | None = None) -> GeodeTau2State:
            loop = _build_loop(
                tools=self.tools,
                system_prompt=_user_system_prompt(
                    self.instructions,
                    use_tools=bool(self.tools),
                    append_text=user_prompt_append_text,
                ),
                model=user_model,
                provider=user_provider,
                source=user_source,
                effort=user_effort,
                time_budget_s=user_time_budget_s,
                max_tokens=user_max_tokens,
                max_rounds=user_max_rounds,
            )
            state = GeodeTau2State(
                loop=loop,
                workflow_order=_user_projector_workflow_order(user_action_projector),
            )
            if state.workflow_order is not None and self.instructions:
                observe_user_text = getattr(state.workflow_order, "observe_user_text", None)
                if callable(observe_user_text):
                    observe_user_text(self.instructions)
            if message_history:
                _hydrate_workflow_order_from_history(state.workflow_order, message_history)
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            from tau2.data_model.message import ToolCall

            started = time.monotonic()
            if state.workflow_order is not None:
                state.workflow_order.observe_incoming_message(message)
                terminal_mobile_data_stop_due = getattr(
                    state.workflow_order,
                    "terminal_mobile_data_stop_due",
                    None,
                )
                if callable(terminal_mobile_data_stop_due) and terminal_mobile_data_stop_due(
                    str(getattr(message, "content", "") or "")
                ):
                    return (
                        UserMessage.text(
                            "Thanks, that fixed my mobile data speed. ###STOP###",
                            usage={},
                            raw_data={
                                "geode_role": "user_simulator",
                                "geode_user_action_projector": user_action_projector,
                                "geode_tool_call_count": 0,
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_projection_diagnostic_only": True,
                                "geode_user_terminal_projection": (
                                    "mobile_data_speed_test_excellent_stop"
                                ),
                            },
                            generation_time_seconds=time.monotonic() - started,
                        ),
                        state,
                    )
                mobile_data_failure_projector = getattr(
                    state.workflow_order,
                    "projected_mobile_data_recovery_after_speed_failure",
                    None,
                )
                if callable(mobile_data_failure_projector):
                    projected_actions = mobile_data_failure_projector(
                        str(getattr(message, "content", "") or "")
                    )
                    if projected_actions:
                        state.workflow_order.mark_projected_user_tool_actions(projected_actions)
                        projected = [
                            ToolCall(
                                id=f"geode_user_projector_mobile_data_recovery_{idx}",
                                name=name,
                                arguments=arguments,
                                requestor="user",
                            )
                            for idx, (name, arguments) in enumerate(projected_actions)
                        ]
                        return (
                            UserMessage(
                                role="user",
                                tool_calls=projected,
                                usage={},
                                raw_data={
                                    "geode_role": "user_simulator",
                                    "geode_user_action_projector": user_action_projector,
                                    "geode_tool_call_count": len(projected),
                                    "geode_tool_projection": "tau2_orchestrator",
                                    "geode_projection_diagnostic_only": True,
                                    "geode_user_terminal_projection": (
                                        "mobile_data_recovery_after_speed_failure"
                                    ),
                                },
                                generation_time_seconds=time.monotonic() - started,
                            ),
                            state,
                        )
                mobile_data_speed_test_projector = getattr(
                    state.workflow_order,
                    "projected_mobile_data_speed_test_after_repair",
                    None,
                )
                if callable(mobile_data_speed_test_projector):
                    projected_actions = mobile_data_speed_test_projector(
                        str(getattr(message, "content", "") or "")
                    )
                    if projected_actions:
                        state.workflow_order.mark_projected_user_tool_actions(projected_actions)
                        projected = [
                            ToolCall(
                                id=f"geode_user_projector_mobile_data_terminal_{idx}",
                                name=name,
                                arguments=arguments,
                                requestor="user",
                            )
                            for idx, (name, arguments) in enumerate(projected_actions)
                        ]
                        return (
                            UserMessage(
                                role="user",
                                tool_calls=projected,
                                usage={},
                                raw_data={
                                    "geode_role": "user_simulator",
                                    "geode_user_action_projector": user_action_projector,
                                    "geode_tool_call_count": len(projected),
                                    "geode_tool_projection": "tau2_orchestrator",
                                    "geode_projection_diagnostic_only": True,
                                    "geode_user_terminal_projection": (
                                        "mobile_data_speed_test_after_repair"
                                    ),
                                },
                                generation_time_seconds=time.monotonic() - started,
                            ),
                            state,
                        )
                assistant_requested_actions = []
                request_projector = getattr(
                    state.workflow_order,
                    "assistant_requested_user_tool_actions",
                    None,
                )
                if callable(request_projector):
                    assistant_requested_actions = request_projector(getattr(message, "content", ""))
                if assistant_requested_actions:
                    state.workflow_order.mark_projected_user_tool_actions(
                        assistant_requested_actions
                    )
                    projected = [
                        ToolCall(
                            id=f"geode_user_projector_assistant_request_{idx}",
                            name=name,
                            arguments=arguments,
                            requestor="user",
                        )
                        for idx, (name, arguments) in enumerate(assistant_requested_actions)
                    ]
                    return (
                        UserMessage(
                            role="user",
                            tool_calls=projected,
                            usage={},
                            raw_data={
                                "geode_role": "user_simulator",
                                "geode_user_action_projector": user_action_projector,
                                "geode_tool_call_count": len(projected),
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_projection_diagnostic_only": True,
                                "geode_user_projection_source": (
                                    "assistant_requested_user_tool_actions"
                                ),
                            },
                            generation_time_seconds=time.monotonic() - started,
                        ),
                        state,
                    )
                projected = []
                projected_actions = []
                if _workflow_user_projection_ready(state.workflow_order, state.messages_seen):
                    projected_actions = state.workflow_order.projected_user_tool_actions()
                    projected = [
                        ToolCall(
                            id=f"geode_user_projector_{idx}",
                            name=name,
                            arguments=arguments,
                            requestor="user",
                        )
                        for idx, (name, arguments) in enumerate(projected_actions)
                    ]
                if projected:
                    state.workflow_order.mark_projected_user_tool_actions(projected_actions)
                    return (
                        UserMessage(
                            role="user",
                            tool_calls=projected,
                            usage={},
                            raw_data={
                                "geode_role": "user_simulator",
                                "geode_user_action_projector": user_action_projector,
                                "geode_tool_call_count": len(projected),
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_projection_diagnostic_only": True,
                            },
                            generation_time_seconds=time.monotonic() - started,
                        ),
                        state,
                    )
                account_lookup_due = getattr(
                    state.workflow_order, "account_identity_lookup_due", None
                )
                terminal_projection_due = getattr(
                    state.workflow_order, "terminal_mms_projection_due", None
                )
                if callable(terminal_projection_due) and terminal_projection_due():
                    return (
                        UserMessage(
                            role="user",
                            tool_calls=[
                                ToolCall(
                                    id="geode_user_projector_terminal_can_send_mms",
                                    name="can_send_mms",
                                    arguments={},
                                    requestor="user",
                                )
                            ],
                            usage={},
                            raw_data={
                                "geode_role": "user_simulator",
                                "geode_user_action_projector": user_action_projector,
                                "geode_tool_call_count": 1,
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_projection_diagnostic_only": True,
                                "geode_user_terminal_projection": "can_send_mms",
                            },
                            generation_time_seconds=time.monotonic() - started,
                        ),
                        state,
                    )
                phone_number = _project_phone_number_from_user_instructions(self.instructions)
                identity_sent = bool(
                    getattr(state.workflow_order, "projected_identity_phone_sent", False)
                )
                if (
                    callable(account_lookup_due)
                    and account_lookup_due()
                    and phone_number
                    and not identity_sent
                ):
                    mark_identity = getattr(
                        state.workflow_order,
                        "mark_projected_user_identity",
                        None,
                    )
                    if callable(mark_identity):
                        mark_identity(phone_number)
                    return (
                        UserMessage.text(
                            _projected_user_identity_text(
                                phone_number,
                                state.workflow_order,
                            ),
                            usage={},
                            raw_data={
                                "geode_role": "user_simulator",
                                "geode_user_action_projector": user_action_projector,
                                "geode_tool_call_count": 0,
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_projection_diagnostic_only": True,
                                "geode_user_identity_projection": "phone_number",
                            },
                            generation_time_seconds=time.monotonic() - started,
                        ),
                        state,
                    )
            prompt = _message_to_prompt(message, recipient="simulated user")
            result = _run_geode_turn_with_empty_text_retry(
                state,
                prompt,
                max_retries=codex_empty_text_retries,
            )
            state.messages_seen += 1
            tool_calls = _tau2_tool_calls(result, requestor="user")
            if state.workflow_order is not None and tool_calls:
                account_lookup_due = getattr(
                    state.workflow_order, "account_identity_lookup_due", None
                )
                terminal_projection_due = getattr(
                    state.workflow_order, "terminal_mms_projection_due", None
                )
                identity_sent = bool(
                    getattr(state.workflow_order, "projected_identity_phone_sent", False)
                )
                proactive_extended_due = getattr(
                    state.workflow_order,
                    "proactive_extended_recovery_due",
                    None,
                )
                if (
                    "can_send_mms" in _tool_call_names(tool_calls)
                    and callable(proactive_extended_due)
                    and proactive_extended_due()
                ):
                    projected_actions = state.workflow_order.projected_user_tool_actions()
                    if projected_actions:
                        state.workflow_order.mark_projected_user_tool_actions(projected_actions)
                        projected = [
                            ToolCall(
                                id=f"geode_user_projector_terminal_block_{idx}",
                                name=name,
                                arguments=arguments,
                                requestor="user",
                            )
                            for idx, (name, arguments) in enumerate(projected_actions)
                        ]
                        return (
                            UserMessage(
                                role="user",
                                tool_calls=projected,
                                usage=_usage_dict(result),
                                raw_data={
                                    "geode_role": "user_simulator",
                                    "geode_user_action_projector": user_action_projector,
                                    "geode_rounds": getattr(result, "rounds", 0),
                                    "geode_termination_reason": (
                                        "workflow_projector_extended_recovery_block"
                                    ),
                                    "geode_tool_call_count": len(projected),
                                    "geode_tool_projection": "tau2_orchestrator",
                                    "geode_projection_diagnostic_only": True,
                                    "geode_suppressed_user_tool_calls": [
                                        str(getattr(call, "name", "") or "") for call in tool_calls
                                    ],
                                },
                                generation_time_seconds=time.monotonic() - started,
                            ),
                            state,
                        )
                projected_actions = _project_user_actions_for_premature_terminal(
                    state.workflow_order,
                    tool_calls,
                )
                if projected_actions:
                    state.workflow_order.mark_projected_user_tool_actions(projected_actions)
                    projected = [
                        ToolCall(
                            id=f"geode_user_projector_premature_terminal_block_{idx}",
                            name=name,
                            arguments=arguments,
                            requestor="user",
                        )
                        for idx, (name, arguments) in enumerate(projected_actions)
                    ]
                    return (
                        UserMessage(
                            role="user",
                            tool_calls=projected,
                            usage=_usage_dict(result),
                            raw_data={
                                "geode_role": "user_simulator",
                                "geode_user_action_projector": user_action_projector,
                                "geode_rounds": getattr(result, "rounds", 0),
                                "geode_termination_reason": (
                                    "workflow_projector_premature_terminal_block"
                                ),
                                "geode_tool_call_count": len(projected),
                                "geode_tool_projection": "tau2_orchestrator",
                                "geode_projection_diagnostic_only": True,
                                "geode_suppressed_user_tool_calls": [
                                    str(getattr(call, "name", "") or "") for call in tool_calls
                                ],
                            },
                            generation_time_seconds=time.monotonic() - started,
                        ),
                        state,
                    )
                if (
                    callable(account_lookup_due)
                    and account_lookup_due()
                    and not (callable(terminal_projection_due) and terminal_projection_due())
                    and not identity_sent
                    and "can_send_mms" in _tool_call_names(tool_calls)
                ):
                    phone_number = _project_phone_number_from_user_instructions(
                        self.instructions
                    ) or getattr(state.workflow_order, "active_phone_number", None)
                    if isinstance(phone_number, str) and phone_number:
                        mark_identity = getattr(
                            state.workflow_order,
                            "mark_projected_user_identity",
                            None,
                        )
                        if callable(mark_identity):
                            mark_identity(phone_number)
                        return (
                            UserMessage.text(
                                _projected_user_identity_text(
                                    phone_number,
                                    state.workflow_order,
                                ),
                                usage=_usage_dict(result),
                                raw_data={
                                    "geode_role": "user_simulator",
                                    "geode_user_action_projector": user_action_projector,
                                    "geode_rounds": getattr(result, "rounds", 0),
                                    "geode_termination_reason": (
                                        "workflow_projector_terminal_block"
                                    ),
                                    "geode_tool_call_count": 0,
                                    "geode_tool_projection": "tau2_orchestrator",
                                    "geode_projection_diagnostic_only": True,
                                    "geode_user_identity_projection": "phone_number",
                                    "geode_suppressed_user_tool_calls": [
                                        str(getattr(call, "name", "") or "") for call in tool_calls
                                    ],
                                },
                                generation_time_seconds=time.monotonic() - started,
                            ),
                            state,
                        )
            if fail_on_empty_geode_turn:
                _assert_tau2_route_ready(
                    result,
                    projected_tool_calls=tool_calls,
                    role="simulated user",
                )
            if tool_calls:
                user_message = UserMessage(
                    role="user",
                    tool_calls=tool_calls,
                    usage=_usage_dict(result),
                    raw_data={
                        "geode_role": "user_simulator",
                        "geode_rounds": getattr(result, "rounds", 0),
                        "geode_termination_reason": getattr(result, "termination_reason", ""),
                        "geode_tool_call_count": len(tool_calls),
                        "geode_tool_projection": "tau2_orchestrator",
                    },
                    generation_time_seconds=time.monotonic() - started,
                )
                return user_message, state
            result_text = _result_text(result)
            post_text_actions = (
                _project_user_actions_after_observed_text(
                    state.workflow_order,
                    result_text,
                )
                if _post_text_projection_enabled(user_action_projector)
                else []
            )
            if post_text_actions:
                projected = [
                    ToolCall(
                        id=f"geode_user_projector_post_text_{idx}",
                        name=name,
                        arguments=arguments,
                        requestor="user",
                    )
                    for idx, (name, arguments) in enumerate(post_text_actions)
                ]
                return (
                    UserMessage(
                        role="user",
                        tool_calls=projected,
                        usage=_usage_dict(result),
                        raw_data={
                            "geode_role": "user_simulator",
                            "geode_user_action_projector": user_action_projector,
                            "geode_rounds": getattr(result, "rounds", 0),
                            "geode_termination_reason": (
                                "workflow_projector_post_text_compression"
                            ),
                            "geode_tool_call_count": len(projected),
                            "geode_tool_projection": "tau2_orchestrator",
                            "geode_projection_diagnostic_only": True,
                            "geode_suppressed_user_text": result_text,
                        },
                        generation_time_seconds=time.monotonic() - started,
                    ),
                    state,
                )
            user_message = UserMessage.text(
                result_text,
                usage=_usage_dict(result),
                raw_data={
                    "geode_role": "user_simulator",
                    "geode_rounds": getattr(result, "rounds", 0),
                    "geode_termination_reason": getattr(result, "termination_reason", ""),
                    "geode_tool_call_count": len(getattr(result, "tool_calls", []) or []),
                },
                generation_time_seconds=time.monotonic() - started,
            )
            return user_message, state

        def set_seed(self, seed: int) -> None:
            return None

    registry.register_agent_factory(create_geode_agent, "geode_agent")
    registry.register_user(GeodeTau2User, "geode_user")


def _slug(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "unnamed"


def _trajectory_snapshot_paths(snapshot_dir: Path, run_id: str) -> tuple[Path, Path]:
    slug = _slug(run_id)
    return snapshot_dir / f"{slug}.trajectory.json", snapshot_dir / f"{slug}.snapshot.json"


def _write_trajectory_snapshot(
    *,
    harness_dir: Path,
    snapshot_dir: Path,
    run_id: str,
    metadata: dict[str, Any],
) -> tuple[Path, Path] | None:
    results_path = harness_dir / "data" / "simulations" / run_id / "results.json"
    if not results_path.exists():
        print(f"trajectory snapshot skipped: results not found at {results_path}", file=sys.stderr)
        return None
    trajectory_path, snapshot_path = _trajectory_snapshot_paths(snapshot_dir, run_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(results_path, trajectory_path)
    snapshot = {
        "schema": "crucible_tau2_trajectory_snapshot.v1",
        "filename_convention": {
            "run_id": (
                "crucible-tau2-<stage>-<domain>-<arm>-<guard>-"
                "<agent_route>-<user_route>-n<tasks>k<trials>-<yyyymmdd>-<seq>"
            ),
            "trajectory": "<run-id>.trajectory.json",
            "snapshot": "<run-id>.snapshot.json",
        },
        "run_id": run_id,
        "raw_results": str(results_path),
        "trajectory_snapshot": str(trajectory_path),
        "snapshot_metadata": str(snapshot_path),
        **metadata,
    }
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    print(f"trajectory snapshot wrote {trajectory_path}")
    print(f"trajectory metadata wrote {snapshot_path}")
    return trajectory_path, snapshot_path


def _codex_empty_text_dumps() -> set[Path]:
    from core.paths import GLOBAL_DIAGNOSTICS_DIR

    dump_dir = GLOBAL_DIAGNOSTICS_DIR / "codex-oauth-empty-text"
    if not dump_dir.exists():
        return set()
    return {path.resolve() for path in dump_dir.glob("*.json") if path.is_file()}


def _new_codex_empty_text_dumps(before: set[Path]) -> list[Path]:
    """Return Codex empty-output dumps created after a run started."""
    return sorted(_codex_empty_text_dumps() - before)


def _raise_on_new_codex_empty_text_dumps(before: set[Path]) -> None:
    new_dumps = _new_codex_empty_text_dumps(before)
    if not new_dumps:
        return
    sample = ", ".join(str(path) for path in new_dumps[:3])
    suffix = "" if len(new_dumps) <= 3 else f", ... (+{len(new_dumps) - 3} more)"
    raise RuntimeError(
        "GEODE tau2 route readiness failed: codex-oauth empty output_text "
        f"occurred during the run ({len(new_dumps)} dump(s): {sample}{suffix}). "
        "This is infrastructure contamination, not tau2 performance evidence. "
        "Fix the subscription route before scored G2/G3 runs, or pass "
        "--allow-empty-geode-turn only for debugging."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-dir", type=Path, default=DEFAULT_HARNESS_DIR)
    parser.add_argument("--domain", default="mock")
    parser.add_argument("--task-set-name", default=None)
    parser.add_argument("--task-split-name", default="base")
    parser.add_argument("--task-ids", nargs="*", default=None)
    parser.add_argument("--num-tasks", type=int, default=1)
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument(
        "--max-errors",
        type=int,
        default=1,
        help="Maximum consecutive tau2 tool errors inside one simulation.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help=(
            "Maximum tau2 task retries after a failed simulation. Crucible strict "
            "runs default to 0."
        ),
    )
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--save-to", default=None)
    parser.add_argument("--user", default="geode_user")
    parser.add_argument("--user-llm", default="gpt-5.5")
    parser.add_argument("--user-llm-args", default='{"temperature": 0.0}')
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--source", default="subscription")
    parser.add_argument("--effort", default="xhigh")
    parser.add_argument("--user-provider", default="openai")
    parser.add_argument("--user-source", default="subscription")
    parser.add_argument("--user-effort", default="high")
    parser.add_argument("--user-time-budget-s", type=float, default=120.0)
    parser.add_argument("--user-max-tokens", type=int, default=8192)
    parser.add_argument(
        "--user-max-rounds",
        type=int,
        default=0,
        help="Maximum GEODE AgenticLoop rounds per simulated-user tau2 turn; 0 is unlimited.",
    )
    parser.add_argument("--time-budget-s", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument(
        "--agent-max-rounds",
        type=int,
        default=0,
        help="Maximum GEODE AgenticLoop rounds per assistant tau2 turn; 0 is unlimited.",
    )
    parser.add_argument("--agent-guard", choices=["none", *CRUCIBLE_GUARDS], default="none")
    parser.add_argument(
        "--agent-planner",
        choices=CRUCIBLE_AGENT_PLANNERS,
        default="none",
        help=(
            "Inject a deterministic Crucible planner candidate into the agent prompt. "
            "Planner candidates are measured as candidate surfaces and are not "
            "promotion authority."
        ),
    )
    parser.add_argument(
        "--agent-workflow-order",
        choices=CRUCIBLE_WORKFLOW_ORDERS,
        default="none",
        help=(
            "Inject a stateful Crucible workflow-order scaffold into each GEODE "
            "agent turn. This is a candidate surface, not promotion authority."
        ),
    )
    parser.add_argument("--agent-prompt-append-file", type=Path, default=None)
    parser.add_argument("--user-prompt-append-file", type=Path, default=None)
    parser.add_argument(
        "--user-action-projector",
        choices=CRUCIBLE_USER_ACTION_PROJECTORS,
        default="none",
        help=(
            "Diagnostic only: project user-side tau2 tool calls from observed phone "
            "state instead of relying on the user LLM to negotiate each action."
        ),
    )
    parser.add_argument(
        "--trajectory-snapshot-dir",
        type=Path,
        default=DEFAULT_TRAJECTORY_SNAPSHOT_DIR,
        help=(
            "Directory for Crucible trajectory snapshots. Requires --save-to; "
            "writes <run-id>.trajectory.json and <run-id>.snapshot.json."
        ),
    )
    parser.add_argument("--no-trajectory-snapshot", action="store_true")
    parser.add_argument("--trajectory-stage", default="g2")
    parser.add_argument("--trajectory-arm", choices=["baseline", "candidate"], default=None)
    parser.add_argument(
        "--allow-empty-geode-turn",
        action="store_true",
        help=(
            "Debug only: convert an empty GEODE turn into fallback text. By default, "
            "empty visible output with no projected tau2 tool call is an infra "
            "readiness failure and stops the run."
        ),
    )
    parser.add_argument(
        "--codex-empty-text-retries",
        type=int,
        default=1,
        help=(
            "Scored-run route policy: retry a GEODE tau2 turn this many times when "
            "the Codex subscription adapter raises codex-oauth empty output_text. "
            "Recovered retries are recorded in trajectory metadata; set 0 to restore "
            "strict fail-fast behavior."
        ),
    )
    parser.add_argument(
        "--enable-cognitive-reflection",
        action="store_true",
        help=(
            "Debug only: leave AgenticLoop cognitive reflection enabled. Scored tau2 "
            "runs disable it so hidden reflection calls cannot spend quota or mask "
            "route-readiness failures."
        ),
    )
    parser.add_argument(
        "--disable-codex-output-replay",
        action="store_true",
        help=(
            "Debug only: do not replay prior Codex response.output items. Scored "
            "tau2 subscription runs keep output replay enabled because OpenAI "
            "Responses docs recommend passing prior output items for manual "
            "multi-turn state."
        ),
    )
    parser.add_argument(
        "--disable-tool-search-defer",
        action="store_true",
        help=(
            "Tau2 probe control: disable hosted tool-search/defer_loading during "
            "this run. Domain-specific tau2 tool sets are small enough that the "
            "extra hosted tool-search calls can cost more than the schema context "
            "they save."
        ),
    )
    parser.add_argument(
        "--disable-action-before-talk-verify",
        action="store_true",
        help=(
            "Debug only: do not enable GEODE's opt-in action-before-talk verifier. "
            "Scored telecom Crucible runs keep it enabled so manual phone-setting "
            "checklists without tool action become retryable loop failures."
        ),
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--auto-resume", action="store_true")
    parser.add_argument("--verbose-logs", action="store_true")
    parser.add_argument(
        "--retrieval-config",
        default=None,
        help=(
            "tau2 retrieval config name, useful for banking_knowledge. "
            "Example: bm25 avoids the default alltools shell sandbox."
        ),
    )
    parser.add_argument("--retrieval-config-kwargs", default="{}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _prepend_tau2_src(args.harness_dir.resolve())

    from tau2.data_model.simulation import TextRunConfig
    from tau2.run import run_domain

    agent_guard_id, agent_guard_text = _load_agent_guard(
        args.agent_guard,
        args.agent_prompt_append_file,
    )
    agent_planner_id, agent_planner_text = _load_agent_planner(args.agent_planner)
    agent_candidate_id, agent_candidate_text = _compose_agent_candidate_surface(
        agent_guard=agent_guard_id,
        guard_text=agent_guard_text,
        agent_planner=agent_planner_id,
        planner_text=agent_planner_text,
    )
    if args.agent_workflow_order != "none":
        agent_candidate_id = (
            args.agent_workflow_order
            if agent_candidate_id == "none"
            else f"{agent_candidate_id}+{args.agent_workflow_order}"
        )
    user_prompt_append_text = (
        args.user_prompt_append_file.read_text().strip()
        if args.user_prompt_append_file is not None
        else ""
    )
    register_geode_tau2_participants(
        agent_model=args.model,
        agent_provider=args.provider,
        agent_source=args.source,
        agent_effort=args.effort,
        agent_time_budget_s=args.time_budget_s,
        agent_max_tokens=args.max_tokens,
        agent_max_rounds=args.agent_max_rounds,
        user_model=args.user_llm,
        user_provider=args.user_provider,
        user_source=args.user_source,
        user_effort=args.user_effort,
        user_time_budget_s=args.user_time_budget_s,
        user_max_tokens=args.user_max_tokens,
        user_max_rounds=args.user_max_rounds,
        user_prompt_append_text=user_prompt_append_text,
        agent_guard_id=agent_candidate_id,
        agent_guard_text=agent_candidate_text,
        agent_workflow_order=args.agent_workflow_order,
        user_action_projector=args.user_action_projector,
        fail_on_empty_geode_turn=not args.allow_empty_geode_turn,
        codex_empty_text_retries=(
            0 if args.allow_empty_geode_turn else max(args.codex_empty_text_retries, 0)
        ),
    )

    config = TextRunConfig(
        domain=args.domain,
        agent="geode_agent",
        user=args.user,
        llm_agent=args.model,
        llm_args_agent={"reasoning_effort": args.effort},
        llm_user=args.user_llm,
        llm_args_user=json.loads(args.user_llm_args),
        task_set_name=args.task_set_name,
        task_split_name=args.task_split_name,
        task_ids=args.task_ids,
        num_tasks=args.num_tasks,
        num_trials=args.num_trials,
        max_concurrency=args.max_concurrency,
        max_steps=args.max_steps,
        max_errors=args.max_errors,
        max_retries=args.max_retries,
        timeout=args.timeout,
        save_to=args.save_to,
        log_level=args.log_level,
        auto_resume=args.auto_resume,
        verbose_logs=args.verbose_logs,
        retrieval_config=args.retrieval_config,
        retrieval_config_kwargs=json.loads(args.retrieval_config_kwargs),
    )
    previous_fail_empty_text = os.environ.get("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT")
    previous_fail_adapter_error = os.environ.get("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR")
    previous_disable_output_replay = os.environ.get("GEODE_CODEX_DISABLE_OUTPUT_REPLAY")
    previous_action_before_talk = os.environ.get("GEODE_VERIFY_ACTION_BEFORE_TALK")
    before_empty_text_dumps = set() if args.allow_empty_geode_turn else _codex_empty_text_dumps()
    if not args.allow_empty_geode_turn:
        os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = "1"
        os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = "1"
    if args.disable_codex_output_replay:
        os.environ["GEODE_CODEX_DISABLE_OUTPUT_REPLAY"] = "1"
    if not args.disable_action_before_talk_verify:
        os.environ["GEODE_VERIFY_ACTION_BEFORE_TALK"] = "1"
    from core.config import settings

    previous_reflection_enabled = getattr(settings, "cognitive_reflection_enabled", None)
    previous_tool_search_defer = getattr(settings, "tool_search_defer", None)
    previous_tool_search_defer_codex = getattr(settings, "tool_search_defer_codex", None)
    if not args.enable_cognitive_reflection:
        object.__setattr__(settings, "cognitive_reflection_enabled", False)
    if args.disable_tool_search_defer:
        object.__setattr__(settings, "tool_search_defer", False)
        object.__setattr__(settings, "tool_search_defer_codex", False)
    run_error: BaseException | None = None
    try:
        run_domain(config)
    except BaseException as exc:
        run_error = exc
    finally:
        if previous_fail_empty_text is None:
            os.environ.pop("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", None)
        else:
            os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = previous_fail_empty_text
        if previous_fail_adapter_error is None:
            os.environ.pop("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", None)
        else:
            os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = previous_fail_adapter_error
        if previous_disable_output_replay is None:
            os.environ.pop("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", None)
        else:
            os.environ["GEODE_CODEX_DISABLE_OUTPUT_REPLAY"] = previous_disable_output_replay
        if previous_action_before_talk is None:
            os.environ.pop("GEODE_VERIFY_ACTION_BEFORE_TALK", None)
        else:
            os.environ["GEODE_VERIFY_ACTION_BEFORE_TALK"] = previous_action_before_talk
        if previous_reflection_enabled is not None:
            object.__setattr__(
                settings,
                "cognitive_reflection_enabled",
                previous_reflection_enabled,
            )
        if previous_tool_search_defer is not None:
            object.__setattr__(settings, "tool_search_defer", previous_tool_search_defer)
        if previous_tool_search_defer_codex is not None:
            object.__setattr__(
                settings,
                "tool_search_defer_codex",
                previous_tool_search_defer_codex,
            )
    recovered_empty_text_dumps = (
        []
        if args.allow_empty_geode_turn or args.codex_empty_text_retries <= 0
        else _new_codex_empty_text_dumps(before_empty_text_dumps)
    )
    if not args.no_trajectory_snapshot and args.save_to:
        agent_route = f"{args.provider}-{args.source}-{args.model}-{args.effort}"
        user_route = f"{args.user_provider}-{args.user_source}-{args.user_llm}-{args.user_effort}"
        arm = args.trajectory_arm or ("baseline" if agent_candidate_id == "none" else "candidate")
        _write_trajectory_snapshot(
            harness_dir=args.harness_dir.resolve(),
            snapshot_dir=args.trajectory_snapshot_dir.resolve(),
            run_id=args.save_to,
            metadata={
                "stage": args.trajectory_stage,
                "domain": args.domain,
                "arm": arm,
                "agent_guard": agent_guard_id,
                "agent_planner": agent_planner_id,
                "agent_workflow_order": args.agent_workflow_order,
                "user_action_projector": args.user_action_projector,
                "agent_candidate": agent_candidate_id,
                "agent_route": agent_route,
                "user_route": user_route,
                "num_tasks": args.num_tasks,
                "num_trials": args.num_trials,
                "task_ids": args.task_ids or [],
                "max_steps": args.max_steps,
                "agent_max_rounds": args.agent_max_rounds,
                "user_max_rounds": args.user_max_rounds,
                "tool_search_defer": not args.disable_tool_search_defer,
                "action_before_talk_verify": not args.disable_action_before_talk_verify,
                "codex_empty_text_retries": (
                    0 if args.allow_empty_geode_turn else max(args.codex_empty_text_retries, 0)
                ),
                "codex_empty_text_recovered_dumps": [
                    str(path) for path in recovered_empty_text_dumps
                ],
                "max_concurrency": args.max_concurrency,
                "argv": sys.argv,
            },
        )
    if run_error is not None:
        raise run_error
    if not args.allow_empty_geode_turn and args.codex_empty_text_retries <= 0:
        _raise_on_new_codex_empty_text_dumps(before_empty_text_dumps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
