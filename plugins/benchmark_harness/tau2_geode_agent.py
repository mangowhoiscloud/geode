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
        "before calling the mutating tool."
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
CRUCIBLE_WORKFLOW_ORDERS = (
    "none",
    "telecom-mms-v1",
    "telecom-mms-step-economy-v1",
    "telecom-mms-bounded-bundle-v1",
    "telecom-mms-roaming-recovery-v1",
    "telecom-mms-phased-recovery-v1",
)


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
class GeodeTau2State:
    loop: Any
    workflow_order: Any | None = None
    workflow_gate_retries: int = 0
    messages_seen: int = 0


def _message_to_prompt(message: Any, *, recipient: str) -> str:
    role = str(getattr(message, "role", "user") or "user")
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
        "You are the GEODE agent running inside tau2-bench.\n"
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
        "You are the simulated tau2 benchmark user running through GEODE.\n"
        "You are NOT the assistant. You are the customer/user in the scenario.\n"
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
        calls.append(
            ToolCall(
                id=str(entry.get("tool_use_id") or f"geode_{requestor}_{idx}"),
                name=tool_name,
                arguments=projected_args,
                requestor=requestor,
            )
        )
    return calls


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
    fail_on_empty_geode_turn: bool = True,
) -> None:
    from core.llm.adapters.registry import bootstrap_builtins
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage, UserMessage
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
            )
            if message_history:
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            if state.workflow_order is not None:
                state.workflow_order.observe_incoming_message(message)
            prompt = _message_to_prompt(message, recipient="assistant agent")
            if state.workflow_order is not None:
                prompt = (
                    f"{prompt}\n\n"
                    "<crucible_workflow_order>\n"
                    f"{state.workflow_order.prompt_hint()}\n"
                    "</crucible_workflow_order>"
                )
            result = asyncio.run(state.loop.arun(prompt))
            state.messages_seen += 1
            tool_calls = _tau2_tool_calls(result, requestor="assistant")
            branch_corrections: list[str] = []
            if state.workflow_order is not None and not tool_calls:
                correction_prompt = state.workflow_order.branch_correction_prompt(
                    str(getattr(result, "text", "") or "")
                )
                if correction_prompt is not None and state.workflow_gate_retries < 1:
                    state.workflow_gate_retries += 1
                    branch_corrections.append("roaming_recovery_order")
                    result = asyncio.run(state.loop.arun(correction_prompt))
                    tool_calls = _tau2_tool_calls(result, requestor="assistant")
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
            state = GeodeTau2State(loop=loop)
            if message_history:
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            prompt = _message_to_prompt(message, recipient="simulated user")
            result = asyncio.run(state.loop.arun(prompt))
            state.messages_seen += 1
            tool_calls = _tau2_tool_calls(result, requestor="user")
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
            user_message = UserMessage.text(
                _result_text(result),
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


def _raise_on_new_codex_empty_text_dumps(before: set[Path]) -> None:
    after = _codex_empty_text_dumps()
    new_dumps = sorted(after - before)
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
        fail_on_empty_geode_turn=not args.allow_empty_geode_turn,
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
                "max_concurrency": args.max_concurrency,
                "argv": sys.argv,
            },
        )
    if run_error is not None:
        raise run_error
    if not args.allow_empty_geode_turn:
        _raise_on_new_codex_empty_text_dumps(before_empty_text_dumps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
