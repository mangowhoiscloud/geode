"""Verify S2-wire — SubAgentManager dispatches AgentDefinition to worker.

Pre-S2-wire, ``SubTask.agent="seed_generator"`` was set by the seed-
pipeline Generator but ``SubAgentManager._build_worker_request`` did not
call ``_resolve_agent``, so the spawned worker ran with GEODE's generic
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
            system_prompt="You are the Generation agent of the seed-generation.",
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
    ``_build_worker_request`` (vs the legacy task-handler thread path).
    A dummy empty dict is sufficient for the dispatch-only tests below;
    no actual subprocess runs.
    """
    return SubAgentManager(
        runner=IsolatedRunner(),
        agent_registry=registry,
        action_handlers=action_handlers or {},
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
    request: WorkerRequest = manager._build_worker_request(task)
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
    request: WorkerRequest = manager._build_worker_request(task)
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
    request: WorkerRequest = manager._build_worker_request(task)
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
    request: WorkerRequest = manager._build_worker_request(task)
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
    populates AgentRegistry so SubAgentManager._resolve_agent works."""
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
