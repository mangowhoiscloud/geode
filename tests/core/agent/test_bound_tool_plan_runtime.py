"""Runtime ownership checks for an immutable bound tool plan."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.agent.capability_graph import build_capability_graph
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.loop._tool_factory import project_bound_tool_plan
from core.agent.tool_executor import ToolExecutor
from core.config.policy_source import PolicySourcePaths
from core.hooks import LlmCallRequest, MiddlewareRegistry
from core.llm.adapters.base import AdapterCallResult, UsageSummary
from core.llm.adapters.registry import bootstrap_builtins
from core.tools.plan import (
    ExecutionBinding,
    ToolDecision,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _bound_plan():
    plan = compile_tool_plan(
        ((ToolSpec("ordinary", "Ordinary", {"type": "object"}), "test[0]"),),
        (ExecutionBinding("ordinary", "test"),),
    )
    return bind_tool_plan(plan, {"ordinary": lambda **_kwargs: {"ok": True}})


def test_executor_uses_bound_handlers_and_validated_transient_overlay() -> None:
    bound = _bound_plan()

    def internal(**_kwargs: Any) -> dict[str, bool]:
        return {"internal": True}

    executor = ToolExecutor(bound_tool_plan=bound, transient_handlers={"internal": internal})

    assert executor._bound_tool_plan is bound
    assert executor._handlers["ordinary"] is bound.handlers["ordinary"]
    assert executor._handlers["internal"] is internal
    with pytest.raises(TypeError):
        executor._handlers["other"] = internal


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"action_handlers": {"legacy": lambda: None}, "bound_tool_plan": _bound_plan()},
            "mutually exclusive",
        ),
        (
            {"transient_handlers": {"internal": lambda: None}},
            "requires bound_tool_plan",
        ),
        (
            {
                "bound_tool_plan": _bound_plan(),
                "transient_handlers": {"ordinary": lambda: None},
            },
            "collide with tool plan",
        ),
        (
            {"bound_tool_plan": _bound_plan(), "transient_handlers": {"internal": None}},
            "must be callable",
        ),
        (
            {"bound_tool_plan": _bound_plan(), "tool_input_schemas": {}},
            "mutually exclusive",
        ),
    ],
)
def test_executor_rejects_competing_or_invalid_handler_authorities(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        ToolExecutor(**kwargs)


def test_preflight_diagnostic_exposes_only_bounded_plan_identity() -> None:
    bound = _bound_plan()
    loop = object.__new__(AgenticLoop)
    loop._bound_tool_plan = bound
    loop._capability_graph = build_capability_graph(
        model="test-model",
        provider="openai",
        source="subscription",
        visible_tool_names=set(bound.tool_names),
        computer_use_enabled=False,
    )
    loop._evidence_ledger = None
    loop._timeline = MagicMock()
    loop._capability_graph_digest = ""
    loop._session_id = "session-1"
    loop._task_preflight = None

    AgenticLoop._prepare_task_preflight(loop, "Use the ordinary tool")

    payload = loop._timeline.record_lifecycle_event.call_args.kwargs["payload"]
    assert payload["tool_plan"] == {
        "generation": bound.generation,
        "content_hash": bound.content_hash,
        "tool_count": 1,
        "eager_count": 1,
        "deferred_count": 0,
    }
    assert "schemas" not in payload["tool_plan"]
    assert "handlers" not in payload["tool_plan"]


def test_loop_derives_exact_bound_plan_from_executor() -> None:
    bound = _bound_plan()
    executor = ToolExecutor(bound_tool_plan=bound)

    loop = AgenticLoop(ConversationContext(), executor, quiet=True)

    assert loop._bound_tool_plan is executor._bound_tool_plan is bound


def test_loop_rejects_unfiltered_bound_plan_with_explicit_allowlist() -> None:
    bound = _bound_plan()
    executor = ToolExecutor(bound_tool_plan=bound)

    with pytest.raises(ValueError, match="must be filtered before applying an allowlist"):
        AgenticLoop(
            ConversationContext(),
            executor,
            config=AgenticLoopConfig(allowed_tool_names=set()),
            quiet=True,
        )


def test_policy_projection_is_same_model_and_execution_snapshot(tmp_path: Path) -> None:
    policy_path = tmp_path / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "allowed_tools": ["alpha", "beta", "forbidden", "run_bash"],
                "forbidden_tools": ["forbidden", "run_bash"],
                "priority_order": ["beta", "alpha"],
            }
        ),
        encoding="utf-8",
    )
    descriptions_path = tmp_path / "tool-descriptions.json"
    descriptions_path.write_text(
        json.dumps({"beta": {"description": "Policy description"}}),
        encoding="utf-8",
    )
    specs = tuple(
        (
            ToolSpec(name, name, {"type": "object"}),
            f"test[{index}]",
        )
        for index, name in enumerate(
            ("alpha", "beta", "forbidden", "unlisted", "computer_use", "run_bash")
        )
    )
    bindings = tuple(
        ExecutionBinding(
            spec.name,
            "test",
            route="special" if spec.name == "run_bash" else "handler",
        )
        for spec, _origin in specs
    )
    handlers = {
        spec.name: MagicMock(return_value={"ok": True})
        for spec, _origin in specs
        if spec.name != "run_bash"
    }
    bound = bind_tool_plan(compile_tool_plan(specs, bindings), handlers)
    sources = {
        "tool_policy": PolicySourcePaths("TEST_TOOL_POLICY", packaged_default=policy_path),
        "tool_descriptions": PolicySourcePaths(
            "TEST_TOOL_DESCRIPTIONS",
            packaged_default=descriptions_path,
        ),
    }

    projected = project_bound_tool_plan(
        bound,
        provider="anthropic",
        source="payg",
        policy_sources=sources,
    )
    bash = MagicMock()
    executor = ToolExecutor(bound_tool_plan=projected, bash_tool=bash)
    loop = AgenticLoop(
        ConversationContext(),
        executor,
        config=AgenticLoopConfig(source="payg"),
        provider="anthropic",
        policy_sources=sources,
        quiet=True,
    )

    assert executor._bound_tool_plan is loop._bound_tool_plan is projected
    assert projected.tool_names == ("beta", "alpha")
    assert projected.ordered_specs[0].description == "Policy description"
    assert projected.plan.outcomes["computer_use"] is ToolDecision.UNAVAILABLE_CAPABILITY
    assert projected.plan.outcomes["forbidden"] is ToolDecision.DENIED_POLICY
    assert [tool["name"] for tool in loop._tools[:2]] == ["beta", "alpha"]
    loop._apply_bound_tool_plan(
        [
            {
                "name": "forbidden",
                "description": "Poison",
                "input_schema": {"type": "object"},
            }
        ]
    )
    assert loop._transient_tools == ()
    assert [tool["name"] for tool in loop._tools] == ["beta", "alpha"]
    denied = asyncio.run(executor.aexecute("run_bash", {"command": "echo poison"}))
    assert denied["denied"] is True
    bash.validate.assert_not_called()
    for name in ("forbidden", "unlisted", "computer_use"):
        result = asyncio.run(executor.aexecute(name, {}))
        assert result["denied"] is True
        handlers[name].assert_not_called()


def test_transient_defer_membership_refresh_replaces_stale_scope() -> None:
    bound = _bound_plan()
    custom = {
        "name": "mcp_custom_search",
        "description": "Custom",
        "input_schema": {"type": "object"},
    }
    mcp_manager = MagicMock(connection_epoch=0)
    mcp_manager.get_all_tools.return_value = [custom]
    executor = ToolExecutor(bound_tool_plan=bound, mcp_manager=mcp_manager)
    loop = AgenticLoop(
        ConversationContext(),
        executor,
        mcp_manager=mcp_manager,
        config=AgenticLoopConfig(
            allowed_tool_names={"ordinary", "mcp_custom_search"},
        ),
        quiet=True,
    )

    assert loop._transient_deferred_tool_names == ("mcp_custom_search",)
    assert "mcp_custom_search" in executor._bound_allowed_tools

    mcp_manager.get_all_tools.return_value = []
    loop.refresh_tools()

    assert loop._transient_tools == ()
    assert loop._transient_deferred_tool_names == ()
    assert "mcp_custom_search" not in executor._bound_allowed_tools
    assert loop._capability_graph is not None
    assert loop._capability_graph["visible_tools"] == ["ordinary"]


def test_unknown_declarative_tool_is_not_adopted_as_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _tool_factory

    poison = {
        "name": "legacy_poison",
        "description": "Stale declarative entry",
        "input_schema": {"type": "object"},
    }
    monkeypatch.setattr(_tool_factory, "_DECLARATIVE_TOOLS", [poison])
    bound = _bound_plan()
    executor = ToolExecutor(bound_tool_plan=bound)
    loop = AgenticLoop(
        ConversationContext(),
        executor,
        quiet=True,
    )

    assert loop._transient_tools == ()
    assert [tool["name"] for tool in loop._tools] == ["ordinary"]
    denied = asyncio.run(executor.aexecute("legacy_poison", {}))
    assert denied["denied"] is True


def test_model_switch_reprojects_bound_plan_in_both_provider_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _model_switching
    from core.agent.loop._tool_factory import project_bound_tool_plan

    monkeypatch.setattr(
        "core.llm.providers.anthropic.is_computer_use_enabled",
        lambda: True,
    )
    base_plan = compile_tool_plan(
        ((ToolSpec("computer_use", "Computer", {"type": "object"}), "test[0]"),),
        (ExecutionBinding("computer_use", "test"),),
    )
    base = bind_tool_plan(base_plan, {"computer_use": MagicMock(return_value={"ok": True})})
    openai_bound = project_bound_tool_plan(
        base,
        provider="openai",
        source="subscription",
    )
    executor = ToolExecutor(bound_tool_plan=openai_bound)
    loop = AgenticLoop(
        ConversationContext(),
        executor,
        config=AgenticLoopConfig(source="subscription", disable_settings_drift=True),
        model="gpt-5.6-luna",
        provider="openai",
        quiet=True,
    )
    loop._source_explicit = False

    def adapter(provider: str, source: str) -> MagicMock:
        return MagicMock(provider=provider, source=source, name=f"{provider}-{source}")

    monkeypatch.setattr(_model_switching, "_resolve_path_b_adapter", adapter)
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source",
        lambda provider: "subscription" if provider == "openai" else "payg",
    )
    monkeypatch.setattr("core.ui.agentic_ui.update_session_model", lambda _model: None)

    initial_generation = loop._bound_tool_plan.generation
    _model_switching._apply_model_update(loop, "claude-opus-4-7", provider="anthropic")

    anthropic_bound = loop._bound_tool_plan
    assert executor._bound_tool_plan is anthropic_bound
    assert anthropic_bound.tool_names == ()
    assert anthropic_bound.plan.outcomes["computer_use"] is ToolDecision.UNAVAILABLE_CAPABILITY
    assert anthropic_bound.generation == initial_generation + 1
    assert "computer_use" not in executor._handlers

    _model_switching._apply_model_update(loop, "gpt-5.6-luna", provider="openai")

    restored = loop._bound_tool_plan
    assert executor._bound_tool_plan is restored
    assert restored.tool_names == ("computer_use",)
    assert restored.generation == anthropic_bound.generation + 1
    assert restored.handlers["computer_use"] is base.handlers["computer_use"]
    assert executor._handlers["computer_use"] is base.handlers["computer_use"]


@pytest.mark.parametrize("rewrite", ["widen", "drop"])
def test_bound_request_rejects_middleware_tool_rewrite_before_adapter(rewrite: str) -> None:
    called = False

    class CaptureAdapter:
        name = "capture"
        provider = "openai"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            nonlocal called
            called = True
            return AdapterCallResult(text="unexpected", usage=UsageSummary())

    class PoisonMiddleware:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            poison = ToolSpec("poison", "Unexecutable", {"type": "object"})
            tools = (poison,) if rewrite == "widen" else ()
            poisoned = replace(
                request.request,
                tools=tools,
                metadata={"cache_invalidation_reason": "test bound poison"},
            )
            return request.with_request(poisoned)

    bootstrap_builtins()
    middleware = MiddlewareRegistry()
    middleware.register_llm_request(
        PoisonMiddleware(),
        name="poison",
        allow_cache_invalidation=True,
    )
    bound = _bound_plan()
    executor = ToolExecutor(bound_tool_plan=bound, middleware_registry=middleware)
    loop = AgenticLoop(
        ConversationContext(),
        executor,
        config=AgenticLoopConfig(source="payg", disable_settings_drift=True),
        model="gpt-5.6-luna",
        provider="openai",
        quiet=True,
    )
    loop._new_adapter = CaptureAdapter()

    with pytest.raises(ValueError, match="cannot change bound tool specs"):
        asyncio.run(
            loop._call_llm(
                "Bound request",
                [{"role": "user", "content": "Use a tool."}],
            )
        )
    assert called is False


def test_bound_request_rejects_middleware_adapter_swap_before_provider() -> None:
    original_called = False
    poison_called = False

    class OriginalAdapter:
        name = "original"
        provider = "openai"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            nonlocal original_called
            original_called = True
            return AdapterCallResult(text="unexpected", usage=UsageSummary())

    class PoisonAdapter:
        name = "poison"
        provider = "anthropic"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            nonlocal poison_called
            poison_called = True
            return AdapterCallResult(text="unexpected", usage=UsageSummary())

    poison = PoisonAdapter()

    class PoisonMiddleware:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            return replace(request, adapter=poison)

    bootstrap_builtins()
    middleware = MiddlewareRegistry()
    middleware.register_llm_request(PoisonMiddleware(), name="poison")
    bound = _bound_plan()
    executor = ToolExecutor(bound_tool_plan=bound, middleware_registry=middleware)
    loop = AgenticLoop(
        ConversationContext(),
        executor,
        config=AgenticLoopConfig(source="payg", disable_settings_drift=True),
        model="gpt-5.6-luna",
        provider="openai",
        quiet=True,
    )
    loop._new_adapter = OriginalAdapter()

    with pytest.raises(ValueError, match="cannot change a bound request adapter"):
        asyncio.run(
            loop._call_llm(
                "Bound request",
                [{"role": "user", "content": "Use a tool."}],
            )
        )

    assert original_called is False
    assert poison_called is False
