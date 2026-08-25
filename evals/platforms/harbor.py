"""Harbor external-agent adapter for GEODE terminal benchmarks."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:

    class HarborBaseAgent:
        logs_dir: Path
        model_name: str | None

        def __init__(
            self,
            logs_dir: Path,
            model_name: str | None = None,
            **kwargs: Any,
        ) -> None: ...

else:
    try:
        HarborBaseAgent = importlib.import_module("harbor.agents.base").BaseAgent
    except ImportError:  # Harbor is an opt-in benchmark dependency.
        HarborBaseAgent = object


@dataclass
class HarborExecTool:
    environment: Any

    @property
    def name(self) -> str:
        return "terminal_exec"

    @property
    def description(self) -> str:
        return "Run one shell command in the isolated benchmark environment."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "cwd": {"type": ["string", "null"]},
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 600,
                    "default": 120,
                },
            },
            "additionalProperties": False,
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_tool_context", None)
        command = str(kwargs.pop("command"))
        cwd_raw = kwargs.pop("cwd", None)
        cwd = str(cwd_raw) if cwd_raw is not None else None
        timeout_seconds = int(kwargs.pop("timeout_seconds", 120))
        result = await self.environment.exec(
            command=command,
            cwd=cwd,
            timeout_sec=timeout_seconds,
        )
        return {
            "result": result.stdout or "",
            "stderr": result.stderr or "",
            "return_code": result.return_code,
        }


def _usage(result: Any) -> dict[str, int | float]:
    usage = getattr(result, "usage", None)
    to_dict = getattr(usage, "to_dict", None)
    raw = to_dict() if callable(to_dict) else {}
    return raw if isinstance(raw, dict) else {}


def _build_loop(
    environment: Any,
    *,
    model: str,
    provider: str,
    source: str,
    effort: str,
    timeout: float,
) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.llm.adapters.registry import bootstrap_builtins
    from core.tools.registry import ToolRegistry
    from core.wiring.runtime import build_policy_sources

    from evals.run_timeline import current_run_timeline as current_activity_sink

    policy_sources = build_policy_sources()
    bootstrap_builtins(policy_sources=policy_sources)
    tool = HarborExecTool(environment)
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(
        action_handlers={tool.name: tool.aexecute},
        auto_approve=True,
        hitl_level=0,
        tool_input_schemas={tool.name: tool.parameters},
    )
    return AgenticLoop(
        ConversationContext(max_turns=200),
        executor,
        config=AgenticLoopConfig(
            source=source,
            effort=effort,
            max_tokens=32768,
            max_rounds=0,
            time_budget_s=timeout,
            allowed_tool_names={tool.name},
            force_include_allowed_tools=True,
            system_prompt_override=(
                "Agent: GEODE inside a Harbor terminal benchmark. Complete the task in the "
                "isolated environment using terminal_exec. Inspect before editing, use command "
                "results as evidence, and stop after the requested state is verified."
            ),
        ),
        model=model,
        provider=provider,
        tool_registry=registry,
        quiet=True,
        activity_sink_provider=current_activity_sink,
        policy_sources=policy_sources,
    )


class GeodeHarborAgent(HarborBaseAgent):
    """Run the current GEODE AgenticLoop against Harbor's external environment."""

    @staticmethod
    def name() -> str:
        return "geode"

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        *,
        provider: str = "openai",
        source: str = "subscription",
        effort: str = "max",
        agent_timeout_sec: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.provider = provider
        self.source = source
        self.effort = effort
        self.agent_timeout_sec = float(agent_timeout_sec or 1200)

    def version(self) -> str:
        return importlib.metadata.version("geode-agent")

    async def setup(self, environment: Any) -> None:
        return None

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        from core.observability.trajectory import export_trajectory, trajectory_from_sessions

        model = (self.model_name or "gpt-5.6-terra").removeprefix("geode/")
        loop = _build_loop(
            environment,
            model=model,
            provider=self.provider,
            source=self.source,
            effort=self.effort,
            timeout=self.agent_timeout_sec,
        )
        previous = os.environ.get("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT")
        os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = "1"
        try:
            result = await loop.arun(instruction)
            if getattr(result, "error", None):
                await loop.amark_session_error()
            else:
                await loop.amark_session_completed()
        except BaseException:
            await loop.amark_session_error()
            raise
        finally:
            if previous is None:
                os.environ.pop("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", None)
            else:
                os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = previous

        usage = _usage(result)
        context.n_input_tokens = int(usage.get("input_tokens") or 0)
        context.n_cache_tokens = int(usage.get("cache_read_input_tokens") or 0)
        context.n_output_tokens = int(usage.get("output_tokens") or 0)
        context.cost_usd = float(usage.get("cost_usd") or 0.0)
        context.metadata = {
            "geode_session_id": loop._session_id,
            "termination_reason": str(getattr(result, "termination_reason", "unknown")),
            "rounds": int(getattr(result, "rounds", 0) or 0),
        }
        trajectory = trajectory_from_sessions(
            [loop._session_id],
            trajectory_id=f"harbor-{loop._session_id}",
            source={
                "harness": "harbor",
                "session": loop._session_id,
                "task": hashlib.sha256(instruction.encode()).hexdigest(),
            },
            outcome=context.metadata,
            provenance={"adapter": "evals.platforms.harbor"},
            privacy={"review_state": "local", "native_results_embedded": False},
            trajectory_class=("benchmark", "terminal", "tool", "lifecycle"),
            content_policy="digest",
        )
        export_trajectory(self.logs_dir / "geode-trajectory.json", trajectory)


__all__ = ["GeodeHarborAgent", "HarborExecTool"]
