"""Verify S2-wire — SubAgentManager dispatches AgentDefinition to worker.

Pre-S2-wire, ``SubTask.agent="seed_generator"`` was set by the seed-
pipeline Generator but request construction did not resolve the agent, so the
spawned worker ran with GEODE's generic
system prompt. These tests pin the fix: WorkerRequest now carries the
resolved AgentDefinition's system_prompt + tools + model.
"""

from __future__ import annotations

import pytest
from core.agent.sub_agent import SubAgentManager, SubTask
from core.agent.worker import WorkerRequest
from core.orchestration.isolated_execution import IsolatedRunner
from core.skills.agents import AgentDefinition, AgentRegistry


@pytest.fixture
def seed_generator_registry() -> AgentRegistry:
    """An AgentRegistry pre-populated with the seed_generator role."""
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            name="seed_generator",
            role="Petri seed candidate generator",
            system_prompt="Role: Generation agent of the seed-generation.",
            tools=["read_document", "write_file", "grep_files"],
            model="claude-sonnet-4-6",
        )
    )
    return registry


def _make_manager(
    registry: AgentRegistry,
    *,
    action_handlers: dict[str, object] | None = None,
) -> SubAgentManager:
    """A SubAgentManager wired with the production subprocess path enabled.

    ``action_handlers`` being non-None is the gate that routes
    ``SubagentProtocol.build_worker_request`` (vs the legacy task-handler thread path).
    A dummy empty dict is sufficient for the dispatch-only tests below;
    no actual subprocess runs.
    """
    return SubAgentManager(
        runner=IsolatedRunner(),
        agent_registry=registry,
        action_handlers=action_handlers or {},
    )


@pytest.mark.parametrize(
    ("explicit", "inherited", "expected"),
    [("low", "max", "low"), ("", "max", "max"), ("", "", "high")],
)
def test_worker_effort_precedence(
    monkeypatch: pytest.MonkeyPatch, explicit: str, inherited: str, expected: str
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "agentic_effort", "high")
    manager = _make_manager(AgentRegistry())
    task = SubTask("effort-child", "inspect", "analyze", effort=explicit)
    request = manager._protocol.build_worker_request(task, default_effort=inherited)
    assert request.effort == expected
    assert WorkerRequest.from_dict(request.to_dict()).effort == expected
    assert task.effort == explicit


@pytest.mark.parametrize("explicit", [False, True])
def test_worker_policy_preserves_auxiliary_and_agent_task_precedence(monkeypatch, explicit):
    from core.config import settings
    from core.config.session import SessionModelConfig

    parent = SessionModelConfig(
        model="gpt-6-sol",
        source="subscription",
        effort="low",
        judge_model="gpt-6-astra",
        judge_source="payg",
        reflection_max_tokens=321,
    )
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            name="worker",
            role="inspect",
            system_prompt="Inspect the supplied artifact.",
            model="gpt-6-luna",
        )
    )
    monkeypatch.setattr(settings, "judge_model", "unrelated-default")
    task = SubTask(
        "policy-child",
        "inspect",
        "analyze",
        agent="worker",
        model="gpt-6-astra" if explicit else "",
        effort="high" if explicit else "",
        source="payg" if explicit else "",
    )
    request = _make_manager(registry)._protocol.build_worker_request(
        task,
        model_settings=parent,
    )
    wire = WorkerRequest.from_dict(request.to_dict())
    assert wire.model == ("gpt-6-astra" if explicit else "gpt-6-luna")
    assert wire.effort == ("high" if explicit else "low")
    assert wire.source == ("payg" if explicit else "subscription")
    assert wire.model_settings == parent.updated(
        {
            "model": wire.model,
            "effort": wire.effort,
            "source": wire.source,
        }
    )


def test_build_worker_request_pulls_agent_system_prompt(
    seed_generator_registry: AgentRegistry,
) -> None:
    manager = _make_manager(seed_generator_registry)
    task = SubTask(
        task_id="t-1",
        description="generate seed",
        task_type="seed-generation",
        args={"target_dim": "broken_tool_use"},
        agent="seed_generator",
    )
    request: WorkerRequest = manager._protocol.build_worker_request(task)
    assert request.agent_name == "seed_generator"
    assert "Generation agent" in request.agent_system_prompt
    assert request.agent_allowed_tools == [
        "read_document",
        "write_file",
        "grep_files",
    ]


def test_build_worker_request_applies_agent_model_override(
    seed_generator_registry: AgentRegistry,
) -> None:
    manager = _make_manager(seed_generator_registry)
    task = SubTask(
        task_id="t-2",
        description="generate seed",
        task_type="seed-generation",
        args={},
        agent="seed_generator",
    )
    request: WorkerRequest = manager._protocol.build_worker_request(task)
    assert request.model == "claude-sonnet-4-6"


def test_build_worker_request_without_agent_uses_settings_model() -> None:
    """When task.agent is None and no _TYPE_AGENT_MAP hit, no override."""
    registry = AgentRegistry()  # empty
    manager = _make_manager(registry)
    task = SubTask(
        task_id="t-3",
        description="generic task",
        task_type="unknown",
        args={},
        agent=None,
    )
    request: WorkerRequest = manager._protocol.build_worker_request(task)
    assert request.agent_name == ""
    assert request.agent_system_prompt == ""
    assert request.agent_allowed_tools == []


def test_build_worker_request_missing_agent_in_registry_is_skipped(
    seed_generator_registry: AgentRegistry,
) -> None:
    """task.agent='nonexistent' must not crash — fall back to default."""
    manager = _make_manager(seed_generator_registry)
    task = SubTask(
        task_id="t-4",
        description="generate seed",
        task_type="seed-generation",
        args={},
        agent="nonexistent_agent",
    )
    request: WorkerRequest = manager._protocol.build_worker_request(task)
    assert request.agent_name == ""
    assert request.agent_system_prompt == ""


def test_worker_request_round_trip_preserves_agent_fields() -> None:
    """to_dict / from_dict must round-trip the new agent fields."""
    req = WorkerRequest(
        task_id="t-5",
        agent_name="seed_generator",
        agent_system_prompt="role prompt body",
        agent_allowed_tools=["read_document", "write_file"],
    )
    blob = req.to_dict()
    restored = WorkerRequest.from_dict(blob)
    assert restored.agent_name == "seed_generator"
    assert restored.agent_system_prompt == "role prompt body"
    assert restored.agent_allowed_tools == ["read_document", "write_file"]


def test_filter_handlers_always_denies_delegate_task() -> None:
    """``delegate_task`` is always removed (depth=1 enforcement)."""
    from core.agent.worker import filter_handlers

    handlers = {"delegate_task": object(), "read_document": object()}
    filtered = filter_handlers(handlers=handlers, denied_tools=[], agent_allowed_tools=[])
    assert "delegate_task" not in filtered
    assert "read_document" in filtered


def test_filter_handlers_applies_whitelist() -> None:
    """``agent_allowed_tools`` whitelist removes non-allowed tools."""
    from core.agent.worker import filter_handlers

    handlers = {
        "read_document": object(),
        "write_file": object(),
        "run_bash": object(),
        "manage_login": object(),
    }
    filtered = filter_handlers(
        handlers=handlers,
        denied_tools=[],
        agent_allowed_tools=["read_document", "write_file"],
    )
    assert set(filtered.keys()) == {"read_document", "write_file"}


def test_filter_handlers_whitelist_does_not_unblock_delegate_task() -> None:
    """Whitelist with delegate_task does NOT unlock it (depth=1 wins)."""
    from core.agent.worker import filter_handlers

    handlers = {"delegate_task": object(), "read_document": object()}
    filtered = filter_handlers(
        handlers=handlers,
        denied_tools=[],
        agent_allowed_tools=["delegate_task", "read_document"],
    )
    assert "delegate_task" not in filtered
    assert "read_document" in filtered


def test_filter_handlers_no_whitelist_keeps_all_minus_denied() -> None:
    """Empty whitelist → only ``denied_tools`` + ``delegate_task`` removed."""
    from core.agent.worker import filter_handlers

    handlers = {
        "read_document": object(),
        "write_file": object(),
        "delegate_task": object(),
    }
    filtered = filter_handlers(
        handlers=handlers,
        denied_tools=["write_file"],
        agent_allowed_tools=[],
    )
    assert set(filtered.keys()) == {"read_document"}


def test_shared_services_passes_agent_registry_to_manager() -> None:
    """Production wiring — SharedServices._build_sub_agent_manager() now
    populates AgentRegistry so SubagentProtocol.resolve_agent works."""
    from core.server.supervised.services import SharedServices

    services = SharedServices(
        hook_system=None,  # type: ignore[arg-type]
        mcp_manager=None,
        skill_registry=None,
        tool_handlers={},
        lane_queue=None,  # type: ignore[arg-type]
    )
    registry = services._build_agent_registry()
    # Defaults always loaded
    names = registry.list_agents()
    assert "research_assistant" in names
    assert "data_analyst" in names
    assert "web_researcher" in names
    # seed_* roles also loaded from .claude/agents/
    if "seed_generator" in names:
        defn = registry.get("seed_generator")
        assert defn is not None
        assert defn.role  # non-empty role
        assert defn.system_prompt  # non-empty prompt


# PR-SUBAGENT-MODEL-ALIGN (2026-06-14) — delegate_task forwards the loop's
# live ToolContext model as the sub-agent default, symmetric with web_search.


def test_build_worker_request_honors_default_model() -> None:
    """The live ``default_model`` (from the delegate ToolContext) is the base
    when neither an AgentDefinition nor a per-task model override applies —
    previously this silently used the global ``settings.model``."""
    manager = _make_manager(AgentRegistry())
    task = SubTask(task_id="d-1", description="x", task_type="unknown", args={}, agent=None)
    request: WorkerRequest = manager._protocol.build_worker_request(
        task, default_model="claude-opus-4-8"
    )
    assert request.model == "claude-opus-4-8"


@pytest.mark.parametrize("agent", [None, "data_analyst"])
def test_bundled_analyst_inherits_parent_model_provider_and_source(agent: str | None) -> None:
    registry = AgentRegistry()
    registry.load_defaults()
    manager = _make_manager(registry)
    task = SubTask(
        task_id="d-bundled",
        description="inspect observed evidence",
        task_type="analyze",
        agent=agent,
        source="subscription",
    )

    request = manager._protocol.build_worker_request(task, default_model="gpt-5.6-sol")

    assert request.agent_name == "data_analyst"
    assert request.toolkit == "data_analysis"
    assert request.agent_system_prompt
    assert (request.model, request.provider, request.source) == (
        "gpt-5.6-sol",
        "openai",
        "subscription",
    )


def test_builtin_role_inherits_parent_model_instead_of_type_agent() -> None:
    """An explicit capability role must not leak into a type agent's model."""
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            name="data_analyst",
            role="Generic analyst",
            system_prompt="Generic analyst prompt",
            tools=["read_document"],
            model="claude-sonnet-4-6",
        )
    )
    manager = _make_manager(registry)
    task = SubTask(
        task_id="d-role",
        description="inspect the repository",
        task_type="analyze",
        role="repo_researcher",
    )

    request = manager._protocol.build_worker_request(task, default_model="gpt-5.6-sol")

    assert request.model == "gpt-5.6-sol"
    assert request.agent_name == ""
    assert request.agent_system_prompt == ""
    assert set(request.agent_allowed_tools) == {
        "glob_files",
        "grep_files",
        "read_document",
        "session_search",
    }


def test_task_and_agent_model_override_win_over_default_model(
    seed_generator_registry: AgentRegistry,
) -> None:
    """Precedence preserved: per-task model > AgentDefinition model >
    live default_model. The alignment must NOT clobber the voter/agent path."""
    manager = _make_manager(seed_generator_registry)
    # AgentDefinition model (claude-sonnet-4-6) wins over default_model.
    agent_task = SubTask(
        task_id="d-2", description="x", task_type="seed-generation", args={}, agent="seed_generator"
    )
    assert (
        manager._protocol.build_worker_request(agent_task, default_model="claude-opus-4-8").model
        == "claude-sonnet-4-6"
    )
    # Per-task model (voter) wins over both.
    voter_task = SubTask(
        task_id="d-3",
        description="x",
        task_type="seed-generation",
        args={},
        agent="seed_generator",
        model="glm-5",
        source="subscription",
    )
    voter_request = manager._protocol.build_worker_request(
        voter_task, default_model="claude-opus-4-8"
    )
    assert (
        voter_request.model,
        voter_request.provider,
        voter_request.source,
    ) == ("glm-5", "glm", "subscription")


def test_explicit_agent_model_does_not_fall_back_to_parent_route(
    seed_generator_registry: AgentRegistry,
) -> None:
    manager = _make_manager(seed_generator_registry)
    task = SubTask(
        task_id="d-explicit-agent",
        description="inspect evidence",
        task_type="seed-generation",
        agent="seed_generator",
        source="subscription",
    )

    request = manager._protocol.build_worker_request(task, default_model="gpt-5.6-sol")

    assert (request.model, request.provider, request.source) == (
        "claude-sonnet-4-6",
        "anthropic",
        "subscription",
    )


def test_default_model_empty_falls_back_to_settings() -> None:
    """No live context (services bootstrap / legacy callers) → settings.model."""
    from core.config import _get_settings

    manager = _make_manager(AgentRegistry())
    task = SubTask(task_id="d-4", description="x", task_type="unknown", args={}, agent=None)
    request: WorkerRequest = manager._protocol.build_worker_request(task, default_model="")
    assert request.model == _get_settings().model


def test_delegate_dispatch_forwards_tool_context_model() -> None:
    """Wiring guard for the exact bug: the delegate_task dispatch branch must
    forward the ToolContext's live ``model`` to ``adelegate(default_model=)``.
    Pre-fix the ``context`` was dropped at the ``_aexecute_delegate`` call so
    sub-agents silently used ``settings.model`` instead of the live ``/model``."""
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.tool_executor import ToolExecutor
    from core.tools.base import ToolContext

    mgr = _make_manager(AgentRegistry())
    mgr.adelegate = AsyncMock(return_value=[])  # type: ignore[method-assign]
    executor = ToolExecutor(sub_agent_manager=mgr, auto_approve=True, hitl_level=0)
    ctx = ToolContext(
        provider="anthropic",
        source="subscription",
        model="claude-opus-4-8",
        adapter_name="x",
        effort="max",
    )
    asyncio.run(executor.aexecute("delegate_task", {"task_description": "do a thing"}, context=ctx))
    assert mgr.adelegate.await_count == 1
    assert mgr.adelegate.await_args.kwargs.get("default_model") == "claude-opus-4-8"
    assert mgr.adelegate.await_args.kwargs.get("default_effort") == "max"


def test_delegate_dispatch_forwards_tool_context_source() -> None:
    """Sub-agent tasks must inherit the parent credential source so their
    own LLM-backed tools cannot re-resolve into an unrelated provider lane."""
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.tool_executor import ToolExecutor
    from core.tools.base import ToolContext

    mgr = _make_manager(AgentRegistry())
    mgr.adelegate = AsyncMock(return_value=[])  # type: ignore[method-assign]
    executor = ToolExecutor(sub_agent_manager=mgr, auto_approve=True, hitl_level=0)
    ctx = ToolContext(
        provider="openai", source="subscription", model="gpt-5.5", adapter_name="codex-oauth"
    )
    asyncio.run(executor.aexecute("delegate_task", {"task_description": "do a thing"}, context=ctx))

    tasks = mgr.adelegate.await_args.args[0]
    assert tasks[0].source == "subscription"
    assert tasks[0].model == ""
