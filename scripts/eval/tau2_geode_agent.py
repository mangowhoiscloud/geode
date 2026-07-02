#!/usr/bin/env python3
"""Run tau2 with GEODE as the agent under test.

This script intentionally does not patch the upstream tau2 checkout. It imports
the harness from ``--harness-dir``, registers a ``geode_agent`` factory in
tau2's in-process registry, and then calls ``tau2.run.run_domain``.

The resulting run still uses tau2's native simulator, domain tools, world-state
diff evaluator, and output directory layout. Only the assistant side is routed
through GEODE's AgenticLoop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import site
import sys
import time
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
        raw = await asyncio.to_thread(self.tau2_tool, **kwargs)
        return {"result": _jsonish(raw)}


@dataclass
class GeodeTau2State:
    loop: Any
    messages_seen: int = 0


def _message_to_prompt(message: Any) -> str:
    role = str(getattr(message, "role", "user") or "user")
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        return content
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return f"[{role} tool calls]\n{_jsonish([tc.model_dump() for tc in tool_calls])}"
    return f"[{role} sent an empty message]"


def _build_system_prompt(domain_policy: str) -> str:
    return (
        "You are the GEODE agent running inside tau2-bench.\n"
        "Follow the domain policy exactly. Use the provided tools to change the "
        "environment state when the user asks for an operation. Do not invent "
        "tool results. When the task is complete, answer the user concisely.\n\n"
        "<policy>\n"
        f"{domain_policy}\n"
        "</policy>"
    )


def register_geode_agent(
    *,
    model: str,
    provider: str,
    source: str,
    effort: str,
    time_budget_s: float,
    max_tokens: int,
) -> None:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.llm.adapters.registry import bootstrap_builtins
    from core.tools.registry import ToolRegistry
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage
    from tau2.registry import registry

    bootstrap_builtins()

    class GeodeTau2Agent(HalfDuplexAgent[GeodeTau2State]):
        def get_init_state(self, message_history: list[Any] | None = None) -> GeodeTau2State:
            tool_registry = ToolRegistry()
            handlers: dict[str, Any] = {}
            for tau2_tool in self.tools:
                wrapped = Tau2GeodeTool(tau2_tool)
                tool_registry.register(wrapped)
                handlers[wrapped.name] = wrapped.aexecute

            executor = ToolExecutor(action_handlers=handlers, auto_approve=True, hitl_level=0)
            loop = AgenticLoop(
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
                system_prompt_override=_build_system_prompt(self.domain_policy),
                quiet=True,
                enable_goal_decomposition=False,
            )
            state = GeodeTau2State(loop=loop)
            if message_history:
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            prompt = _message_to_prompt(message)
            result = asyncio.run(state.loop.arun(prompt))
            state.messages_seen += 1
            usage = None
            result_usage = getattr(result, "usage", None)
            if result_usage is not None:
                to_dict = getattr(result_usage, "to_dict", None)
                usage = to_dict() if callable(to_dict) else getattr(result_usage, "__dict__", None)
            assistant = AssistantMessage.text(
                _result_text(result),
                usage=usage,
                raw_data={
                    "geode_rounds": getattr(result, "rounds", 0),
                    "geode_termination_reason": getattr(result, "termination_reason", ""),
                    "geode_tool_call_count": len(getattr(result, "tool_calls", []) or []),
                },
                generation_time_seconds=time.monotonic() - started,
            )
            return assistant, state

    def create_geode_agent(tools: list[Any], domain_policy: str, **_: Any) -> Any:
        return GeodeTau2Agent(tools=tools, domain_policy=domain_policy)

    registry.register_agent_factory(create_geode_agent, "geode_agent")


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
    parser.add_argument("--user", default="user_simulator")
    parser.add_argument("--user-llm", default="gpt-4.1-2025-04-14")
    parser.add_argument("--user-llm-args", default='{"temperature": 0.0}')
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--source", default="subscription")
    parser.add_argument("--effort", default="xhigh")
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

    register_geode_agent(
        model=args.model,
        provider=args.provider,
        source=args.source,
        effort=args.effort,
        time_budget_s=args.time_budget_s,
        max_tokens=args.max_tokens,
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
