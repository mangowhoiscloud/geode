"""Bridge Tau2 environment tools into the GEODE registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geode_product.benchmark_harness.tau2_turn_supervisor import _tool_mutates_state


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
        return {
            "result": (
                f"Recorded {self.name} for tau2 orchestrator execution. "
                "The official tau2 environment will execute this tool call."
            ),
            "projected_to_tau2": True,
            "external_execution": "deferred",
            "mutates_state": self.mutates_state,
        }


def _tau2_tool_registry(tools: list[Any] | None) -> tuple[Any, dict[str, Any]]:
    """Build the registry shared by inference and the no-model schema receipt."""
    from core.tools.registry import ToolRegistry

    registry = ToolRegistry()
    handlers: dict[str, Any] = {}
    for tau2_tool in tools or []:
        wrapped = Tau2GeodeTool(tau2_tool, mutates_state=_tool_mutates_state(tau2_tool))
        registry.register(wrapped)
        handlers[wrapped.name] = wrapped.aexecute
    return registry, handlers
