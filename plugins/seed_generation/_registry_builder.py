"""S11 registry wire-up — build a populated :class:`PipelineRegistry`.

Follow-up C of the v0.99.39 LLM adapter abstraction. Replaces the empty
``PipelineRegistry()`` previously emitted at ``cli._dispatch_pipeline``
with a real, picker-driven population: each enabled role's concrete agent
class is instantiated with the binding's ``model`` + ``source`` and the
shared :class:`SubAgentManager`. The Ranker additionally consumes
``picker_result.voters``.

Pre-this PR the production CLI flow at ``cli.py:436`` was
``registry = PipelineRegistry()`` with a NOTE that ``Pipeline.arun`` would
raise a RuntimeError on the first un-registered role — by design (Session
63 S11 placeholder) so the orchestrator path was reachable for gate
testing but no actual LLM ran. This module closes that gap.

Why the agent classes are picked at registry-build time (not auto-discovery):
the seed_generation roles are a fixed set defined by the manifest's
``enabled_roles``. A discovery-based loader (entry-points, file scan)
would over-engineer the contract — and breaks ``geode audit-seeds --help``
smoke speed because every agent module would import at CLI start.
The explicit map keeps the production path import-free until the user
actually invokes ``generate``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plugins.seed_generation.agents.base import BaseSeedAgent
    from plugins.seed_generation.manifest import SeedGenerationManifest
    from plugins.seed_generation.orchestrator import PipelineRegistry
    from plugins.seed_generation.picker import PickerResult

log = logging.getLogger(__name__)


def build_subagent_manager() -> Any:
    """Construct the production :class:`SubAgentManager` for seed_generation.

    Mirrors the wiring in
    :meth:`core.server.supervised.services._build_sub_agent_manager` but
    standalone — the seed_generation CLI runs outside the gateway, so we
    rebuild the dependency stack inline rather than reach into the
    Supervisor's instance. The shape matches: ``IsolatedRunner`` + hooks +
    tool handlers + MCP / skill registries + agent registry.

    Falls back to the minimum viable manager when individual dependencies
    are unavailable (tests, ad-hoc CLI use) — observability hooks may be
    None; the agent's ``adelegate`` path still functions.
    """
    from core.agent.sub_agent import SubAgentManager
    from core.config import settings
    from core.orchestration.isolated_execution import IsolatedRunner

    # Best-effort dependency resolution — none of these are strictly required
    # for the SubAgentManager to dispatch a subprocess worker, but the worker
    # subprocess inherits credentials + skill resolution from the parent so
    # we pass everything we can find.
    hooks = None
    lane = None
    tool_handlers: dict[str, Any] = {}
    mcp_manager = None
    skill_registry = None
    agent_registry = _try_build_agent_registry()
    # ``get_lane_queue`` is not a public surface in this worktree's wiring;
    # the SubAgentManager constructs its own IsolatedRunner with the bare
    # ``hooks=None / lane=None`` path which the runner tolerates (slot wait
    # falls back to a default semaphore). The follow-up D PR can plumb the
    # gateway lane through ``runtime.GeodeRuntime`` when the seed-generation
    # CLI runs under the supervisor.
    try:
        from core.cli.tool_handlers import _build_tool_handlers

        tool_handlers = _build_tool_handlers(verbose=False)
    except Exception:
        log.debug("seed-generation: tool handler build failed", exc_info=True)

    return SubAgentManager(
        IsolatedRunner(hooks=hooks, lane=lane),
        action_handlers=tool_handlers,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        agent_registry=agent_registry,
        hooks=hooks,
        max_depth=settings.max_subagent_depth,
    )


def _try_build_agent_registry() -> Any:
    """Best-effort AgentRegistry — needed so SubTask.agent resolves to the
    AgentDefinition's system_prompt + tools + model overrides.

    Mirrors ``core.server.supervised.services._build_agent_registry`` but
    in a function-local form so the seed-generation CLI does not depend
    on the gateway service singleton. Loads ``AgentRegistry`` defaults +
    ``.claude/agents/`` + each ``plugins/*/agents/`` directory.
    Returns ``None`` on any failure (the worker then runs with GEODE's
    generic default prompt, which is the pre-S11 fallback).
    """
    try:
        from pathlib import Path

        from core.paths import get_project_root
        from core.skills.agents import AgentRegistry, SubagentLoader
    except Exception:
        log.debug("seed-generation: AgentRegistry imports unavailable", exc_info=True)
        return None
    try:
        registry = AgentRegistry()
        registry.load_defaults()
        project_root = get_project_root()
        search_dirs: list[Path] = [project_root / ".claude" / "agents"]
        plugins_root = project_root / "plugins"
        if plugins_root.exists():
            for plugin_agents in sorted(plugins_root.glob("*/agents")):
                if plugin_agents.is_dir():
                    search_dirs.append(plugin_agents)
        loader = SubagentLoader(agents_dirs=search_dirs)
        for path in loader.discover():
            try:
                definition = loader.load_file(path)
            except Exception:
                log.debug("seed-generation: agent file load skipped: %s", path, exc_info=True)
                continue
            try:
                registry.register(definition)
            except ValueError:
                # default-name conflict — leave the default in place.
                log.debug(
                    "seed-generation: agent %r conflicts with default, skipped",
                    definition.name,
                )
                continue
        return registry
    except Exception:
        log.debug("seed-generation: agent registry build failed", exc_info=True)
        return None


def populate_registry(
    registry: PipelineRegistry,
    *,
    picker_result: PickerResult,
    manifest: SeedGenerationManifest,
    manager: Any | None = None,
) -> PipelineRegistry:
    """Populate ``registry`` with one concrete agent per enabled role.

    Each agent is constructed with ``model + source`` taken from the
    picker's per-role binding so the SubTask the agent later emits
    inherits the binding's auth path.

    Mutates ``registry`` in place and also returns it for fluent use.
    """
    manager = manager if manager is not None else build_subagent_manager()

    from plugins.seed_generation.agents.critic import Critic
    from plugins.seed_generation.agents.evolver import Evolver
    from plugins.seed_generation.agents.generator import Generator
    from plugins.seed_generation.agents.meta_reviewer import MetaReviewer
    from plugins.seed_generation.agents.pilot import Pilot
    from plugins.seed_generation.agents.proximity import Proximity
    from plugins.seed_generation.agents.ranker import Ranker

    _ROLE_TO_CLASS: dict[str, type[BaseSeedAgent]] = {
        "generator": Generator,
        "critic": Critic,
        "proximity": Proximity,
        "pilot": Pilot,
        "evolver": Evolver,
        "meta_reviewer": MetaReviewer,
    }

    for role_name in manifest.enabled_roles:
        if registry.has(role_name):
            log.debug("seed-generation registry: %s already populated, skipping", role_name)
            continue
        binding = picker_result.bindings.get(role_name)
        manifest_role = manifest.roles.get(role_name)
        manifest_role_dict: dict[str, object] = {}
        if manifest_role is not None:
            # Only known fields — extra attributes (e.g. literature_review's
            # max_papers added in PR #1517) propagate when present.
            for field_name in ("default_model", "max_papers", "queries_per_run"):
                if hasattr(manifest_role, field_name):
                    manifest_role_dict[field_name] = getattr(manifest_role, field_name)

        if role_name == "ranker":
            agent: BaseSeedAgent = Ranker(
                manager,
                list(picker_result.voters),
                model=binding.model if binding else _DEFAULT_FALLBACK_MODEL,
                source=binding.source if binding else "auto",
                manifest_role=manifest_role_dict,
            )
        else:
            cls = _ROLE_TO_CLASS.get(role_name)
            if cls is None:
                log.warning("seed-generation registry: no agent class for role %r", role_name)
                continue
            # Each role agent declares its own ctor (variadic across
            # roles) but they all accept ``(manager, *, model, source,
            # manifest_role)``. mypy can't infer that from
            # ``type[BaseSeedAgent]``; suppress the structural complaint.
            agent = cls(  # type: ignore[misc]
                manager,
                model=binding.model if binding else _DEFAULT_FALLBACK_MODEL,
                source=binding.source if binding else "auto",
                manifest_role=manifest_role_dict,
            )
        registry.register(agent)

    # Supervisor + MetaReviewer are not in ``enabled_roles`` for some
    # manifest revisions; the orchestrator references them optionally
    # (the phase short-circuits when the role is missing). Register
    # supervisor if a binding exists.
    if "supervisor" not in registry.list_roles():
        sup_binding = picker_result.bindings.get("supervisor")
        if sup_binding is not None:
            from plugins.seed_generation.agents.supervisor import Supervisor

            registry.register(
                Supervisor(
                    manager,
                    model=sup_binding.model,
                    source=sup_binding.source,
                )
            )

    return registry


# Fallback model when the picker did not produce a binding for an enabled
# role — happens if the manifest declares a role the picker doesn't have a
# binding for (mismatch between picker.bindings and manifest.enabled_roles).
# We log+continue rather than crashing so the operator gets a clear
# "no registered agent" error at phase time pointing at the missing role.
_DEFAULT_FALLBACK_MODEL = "claude-sonnet-4-6"


__all__ = ["build_subagent_manager", "populate_registry"]
