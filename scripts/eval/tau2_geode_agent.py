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
import site
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARNESS_DIR = REPO_ROOT / "artifacts" / "eval" / "harnesses" / "tau2-bench"


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


def _agent_system_prompt(domain_policy: str) -> str:
    return (
        "You are the GEODE agent running inside tau2-bench.\n"
        "Follow the domain policy exactly. Use the provided tools to change the "
        "environment state when the user asks for an operation. Do not invent "
        "tool results. When the task is complete, answer the user concisely.\n\n"
        "<policy>\n"
        f"{domain_policy}\n"
        "</policy>"
    )


def _user_system_prompt(instructions: str | None, *, use_tools: bool) -> str:
    from tau2.user.user_simulator import get_global_user_sim_guidelines

    guidelines = get_global_user_sim_guidelines(use_tools=use_tools)
    return (
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
        max_rounds=0,
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
    user_model: str,
    user_provider: str,
    user_source: str,
    user_effort: str,
    user_time_budget_s: float,
    user_max_tokens: int,
) -> None:
    from core.llm.adapters.registry import bootstrap_builtins
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage, UserMessage
    from tau2.registry import registry
    from tau2.user.user_simulator_base import HalfDuplexUser

    bootstrap_builtins()

    class GeodeTau2Agent(HalfDuplexAgent[GeodeTau2State]):
        def get_init_state(self, message_history: list[Any] | None = None) -> GeodeTau2State:
            loop = _build_loop(
                tools=self.tools,
                system_prompt=_agent_system_prompt(self.domain_policy),
                model=agent_model,
                provider=agent_provider,
                source=agent_source,
                effort=agent_effort,
                time_budget_s=agent_time_budget_s,
                max_tokens=agent_max_tokens,
            )
            state = GeodeTau2State(loop=loop)
            if message_history:
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            prompt = _message_to_prompt(message, recipient="assistant agent")
            result = asyncio.run(state.loop.arun(prompt))
            state.messages_seen += 1
            tool_calls = _tau2_tool_calls(result, requestor="assistant")
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
                system_prompt=_user_system_prompt(self.instructions, use_tools=bool(self.tools)),
                model=user_model,
                provider=user_provider,
                source=user_source,
                effort=user_effort,
                time_budget_s=user_time_budget_s,
                max_tokens=user_max_tokens,
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
    parser.add_argument("--time-budget-s", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--auto-resume", action="store_true")
    parser.add_argument("--verbose-logs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _prepend_tau2_src(args.harness_dir.resolve())

    from tau2.data_model.simulation import TextRunConfig
    from tau2.run import run_domain

    register_geode_tau2_participants(
        agent_model=args.model,
        agent_provider=args.provider,
        agent_source=args.source,
        agent_effort=args.effort,
        agent_time_budget_s=args.time_budget_s,
        agent_max_tokens=args.max_tokens,
        user_model=args.user_llm,
        user_provider=args.user_provider,
        user_source=args.user_source,
        user_effort=args.user_effort,
        user_time_budget_s=args.user_time_budget_s,
        user_max_tokens=args.user_max_tokens,
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
        timeout=args.timeout,
        save_to=args.save_to,
        log_level=args.log_level,
        auto_resume=args.auto_resume,
        verbose_logs=args.verbose_logs,
    )
    run_domain(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
