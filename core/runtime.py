"""Runtime — production wiring for GEODE infrastructure components.

Centralizes creation and lifecycle of all infrastructure singletons:
- HookSystem with bounded SQLite event persistence
- InMemorySessionStore
- PolicyChain with default policies
- ToolRegistry with analysis tools
- ConfigWatcher for hot reload
- LaneQueue for concurrency control
- Session key utilities
- Scheduling: TriggerManager + SchedulerService
- L2 Memory: OrganizationMemory, InMemorySessionStore, ContextAssembler

Implementation details are decomposed into `core.wiring`:
    bootstrap  — hooks, memory, session, config_watcher, task, plugin_registry
    infra      — policies, tools, LLM, auth, lanes
    scheduling — TriggerManager + SchedulerService + auto-trigger
    adapters   — MCP signal/notification/calendar/gateway
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``from __future__ import annotations`` defers evaluation of all
    # type annotations to strings, so the classes referenced only in
    # field / variable annotations below do not need to be imported at
    # runtime.  Pushing them into ``TYPE_CHECKING`` removes their entire
    # module trees (the L2 memory graph, scheduler.triggers, task system)
    # from the cold-start path.  Each tree is loaded lazily by the wiring
    # builders (``core.wiring.{bootstrap,scheduling}``) only when the
    # matching component actually fires.
    from core.config.policy_source import PolicySourceBundle
    from core.extensions import ExtensionDecision
    from core.memory.context import ContextAssembler
    from core.memory.organization import MonoLakeOrganizationMemory
    from core.memory.project import ProjectMemory
    from core.observability.run_event import RunEventSinkProvider
    from core.orchestration.hot_reload import ConfigWatcher
    from core.orchestration.metrics import LatencyMetrics
    from core.orchestration.task_system import TaskGraph
    from core.scheduler.triggers import TriggerManager
    from core.tools.handlers import ToolIntegrationServices, ToolPersistenceServices

from core.auth.cooldown import CooldownTracker
from core.auth.profiles import ProfileStore
from core.auth.rotation import ProfileRotator
from core.hooks import (
    HookRegistry,
    MiddlewareRegistry,
    RuntimeEventBus,
)
from core.memory.port import SessionStorePort
from core.memory.session_key import build_session_key
from core.observability.event_store import HookEventStore
from core.orchestration.lane_queue import LaneQueue
from core.tools.policy import PolicyChain
from core.tools.registry import ToolRegistry
from core.wiring.bootstrap import get_plugin_status as get_plugin_status

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL = 3600.0  # 1 hour
# ---------------------------------------------------------------------------
# Config dataclasses — group __init__ parameters by concern
# ---------------------------------------------------------------------------


@dataclass
class RuntimeExecutionConfig:
    """Request execution services owned for the runtime lifetime."""

    hooks: RuntimeEventBus
    hook_registry: HookRegistry
    middleware_registry: MiddlewareRegistry
    policy_chain: PolicyChain
    tool_registry: ToolRegistry
    lane_queue: LaneQueue
    activity_sink_provider: RunEventSinkProvider | None = None


@dataclass
class RuntimePersistenceConfig:
    """State stores and memory services owned by the runtime."""

    session_store: SessionStorePort
    event_store: HookEventStore
    project_memory: ProjectMemory
    organization_memory: MonoLakeOrganizationMemory | None = None
    context_assembler: ContextAssembler | None = None
    offload_store: Any = None


@dataclass
class RuntimeLifecycleConfig:
    """Started components whose teardown is owned by :class:`GeodeRuntime`."""

    config_watcher: ConfigWatcher
    hook_metrics: LatencyMetrics
    trigger_manager: TriggerManager | None = None
    scheduler_service: Any | None = None


@dataclass
class RuntimeIntegrationConfig:
    """External and extension-facing runtime services."""

    mcp_manager: Any = None
    skill_registry: Any = None
    policy_sources: PolicySourceBundle | None = None
    calendar: Any = None
    notification: Any = None
    calendar_bridge: Any = None
    extension_decisions: tuple[ExtensionDecision, ...] = ()


@dataclass
class RuntimeAuthenticationConfig:
    """Authentication and operator-profile services."""

    profile_store: ProfileStore | None = None
    profile_rotator: ProfileRotator | None = None
    cooldown_tracker: CooldownTracker | None = None
    user_profile: Any = None
    readiness: Any = None


@dataclass
class RuntimeIdentityConfig:
    """Stable identity for one runtime instance."""

    session_key: str
    subject_id: str


@dataclass
class RuntimeCoreConfig:
    """Lifecycle-owned service groups; no group exceeds seven fields."""

    execution: RuntimeExecutionConfig
    persistence: RuntimePersistenceConfig
    lifecycle: RuntimeLifecycleConfig
    integration: RuntimeIntegrationConfig
    authentication: RuntimeAuthenticationConfig
    identity: RuntimeIdentityConfig


# ---------------------------------------------------------------------------
# GeodeRuntime — the main integration class
# ---------------------------------------------------------------------------


class GeodeRuntime:
    """Production runtime that wires all infrastructure components.

    Usage:
        runtime = GeodeRuntime.create("subject")
        # the agent executes via the AgenticLoop (core.agent.loop), not a
        # graph; this object provides the wired infra (memory, tools, hooks,
        # scheduler) the loop draws on.
    """

    def __init__(
        self,
        core: RuntimeCoreConfig,
    ) -> None:
        # Unpack core (flat attributes for backward compat)
        execution = core.execution
        persistence = core.persistence
        lifecycle = core.lifecycle
        integration = core.integration
        authentication = core.authentication
        identity = core.identity
        self.hooks = execution.hooks
        self.hook_registry = execution.hook_registry
        self.middleware_registry = execution.middleware_registry
        self.policy_chain = execution.policy_chain
        self.tool_registry = execution.tool_registry
        self.lane_queue = execution.lane_queue
        self.activity_sink_provider = execution.activity_sink_provider
        self.session_store = persistence.session_store
        self.event_store = persistence.event_store
        self.project_memory = persistence.project_memory
        self.organization_memory = persistence.organization_memory
        self.context_assembler = persistence.context_assembler
        self.offload_store = persistence.offload_store
        self.config_watcher = lifecycle.config_watcher
        self.hook_metrics = lifecycle.hook_metrics
        self.trigger_manager = lifecycle.trigger_manager
        self.scheduler_service = lifecycle.scheduler_service
        self.mcp_manager = integration.mcp_manager
        self.skill_registry = integration.skill_registry
        self.policy_sources = integration.policy_sources
        self.calendar = integration.calendar
        self.notification = integration.notification
        self.calendar_bridge = integration.calendar_bridge
        self.extension_decisions = integration.extension_decisions
        self.profile_store = authentication.profile_store
        self.profile_rotator = authentication.profile_rotator
        self.cooldown_tracker = authentication.cooldown_tracker or CooldownTracker()
        self.user_profile = authentication.user_profile
        self.readiness = authentication.readiness
        self.session_key = identity.session_key
        self.subject_id = identity.subject_id
        self.run_id = ""
        self.is_subagent: bool = False
        self._shutdown = False
        # L4 Task tracking
        self.task_graph: TaskGraph | None = None

    @property
    def persistence_services(self) -> ToolPersistenceServices:
        """Narrow tool persistence view for the product composition root."""
        from core.tools.handlers import ToolPersistenceServices
        from core.tools.memory_tools import MemoryToolServices

        return ToolPersistenceServices(
            memory=MemoryToolServices(
                session_store=self.session_store,
                project_memory=self.project_memory,
                organization_memory=self.organization_memory,
                hooks=self.hooks,
            ),
            user_profile=self.user_profile,
            offload_store=self.offload_store,
        )

    @property
    def integration_services(self) -> ToolIntegrationServices:
        """Narrow external-port view for the product composition root."""
        from core.tools.handlers import ToolIntegrationServices

        return ToolIntegrationServices(
            calendar=self.calendar,
            notification=self.notification,
            calendar_bridge=self.calendar_bridge,
        )

    # ------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        subject_id: str,
        *,
        phase: str = "analysis",
        log_dir: Path | str | None = None,
        session_ttl: float = DEFAULT_SESSION_TTL,
        policy_sources: PolicySourceBundle | None = None,
        middleware_builder: Callable[..., MiddlewareRegistry] | None = None,
        activity_sink_provider: RunEventSinkProvider | None = None,
        feature_hook_registrar: Callable[[Any], None] | None = None,
        scheduling_registrar: Callable[[Any, Any], None] | None = None,
        scheduler_callback: Callable[[str, str, bool, str], None] | None = None,
    ) -> GeodeRuntime:
        """Factory method — create a fully wired runtime for a GEODE session.

        Staged initialization (Claude Code entrypoints/init.ts pattern):
        1. _build_core: sessions, hooks, config, auth, LLM, lanes
        2. _build_tools: MCP, skills, readiness, plugins, tool offload
        3. _build_memory: project/org memory, context assembler, scheduling
        4. Assembly: pack configs, create instance, attach optional components
        """
        from core.config.policy_source import EMPTY_POLICY_SOURCES
        from core.wiring import bootstrap
        from core.wiring import container as infra

        resolved_policy_sources = EMPTY_POLICY_SOURCES if policy_sources is None else policy_sources

        # Stage 0: Session identity.
        session_key = build_session_key(subject_id, phase)
        run_id = uuid.uuid4().hex[:12]
        user_profile = bootstrap.ensure_user_profile()

        # Stage 1: Core sub-systems
        core = cls._build_core(
            bootstrap,
            infra,
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
            session_ttl=session_ttl,
            policy_sources=resolved_policy_sources,
            middleware_builder=middleware_builder,
            activity_sink_provider=activity_sink_provider,
            feature_hook_registrar=feature_hook_registrar,
            user_profile=user_profile,
        )

        # Stage 2: Tools, MCP, Skills
        tools = cls._build_tools(bootstrap, core["hooks"], session_key=session_key)
        from core.config import settings
        from core.hooks.plugins.notification_hook.hook import register_notification_hooks

        register_notification_hooks(
            core["hooks"],
            channel=settings.notification_channel,
            recipient=settings.notification_recipient,
            notification=tools["notification"],
        )

        # Stage 3: Memory + Scheduling
        memory, scheduling = cls._build_memory_and_scheduling(
            bootstrap,
            core["hooks"],
            core["session_store"],
            core["event_store"],
            session_key=session_key,
            subject_id=subject_id,
            scheduling_registrar=scheduling_registrar,
            scheduler_callback=scheduler_callback,
            user_profile=user_profile,
        )

        from core.tools.memory_tools import MemoryToolServices

        memory_services = MemoryToolServices(
            session_store=core["session_store"],
            project_memory=memory["project_memory"],
            organization_memory=memory["organization_memory"],
            hooks=core["hooks"],
        )
        tool_registry = infra.build_default_registry(
            memory_services=memory_services,
            notification=tools["notification"],
        )

        log.info(
            "GeodeRuntime created: subject=%s, key=%s, tools=%d, lanes=%s",
            subject_id,
            session_key,
            len(tool_registry),
            core["lane_queue"].list_lanes(),
        )

        # Stage 4: Assembly
        from core.scheduler.calendar_bridge import CalendarSchedulerBridge

        calendar_bridge = (
            CalendarSchedulerBridge(scheduling["scheduler_service"], tools["calendar"])
            if scheduling.get("scheduler_service") is not None and tools["calendar"] is not None
            else None
        )
        from core.llm.adapters.registry import registry_snapshot

        extension_decisions = (
            *core["hooks"].extension_decisions,
            *registry_snapshot().report.extensions,
            *tools["mcp_manager"].extension_decisions,
            *tools["skill_registry"].extension_decisions,
        )
        core_config = RuntimeCoreConfig(
            execution=RuntimeExecutionConfig(
                hooks=core["hooks"],
                hook_registry=core["hook_registry"],
                middleware_registry=core["middleware_registry"],
                policy_chain=core["policy_chain"],
                tool_registry=tool_registry,
                lane_queue=core["lane_queue"],
                activity_sink_provider=activity_sink_provider,
            ),
            persistence=RuntimePersistenceConfig(
                session_store=core["session_store"],
                event_store=core["event_store"],
                project_memory=memory["project_memory"],
                organization_memory=memory["organization_memory"],
                context_assembler=memory["context_assembler"],
                offload_store=tools["offload_store"],
            ),
            lifecycle=RuntimeLifecycleConfig(
                config_watcher=core["config_watcher"],
                hook_metrics=core["hook_metrics"],
                **scheduling,
            ),
            integration=RuntimeIntegrationConfig(
                mcp_manager=tools["mcp_manager"],
                skill_registry=tools["skill_registry"],
                policy_sources=resolved_policy_sources,
                calendar=tools["calendar"],
                notification=tools["notification"],
                calendar_bridge=calendar_bridge,
                extension_decisions=extension_decisions,
            ),
            authentication=RuntimeAuthenticationConfig(
                profile_store=core["profile_store"],
                profile_rotator=core["profile_rotator"],
                cooldown_tracker=core["cooldown_tracker"],
                user_profile=memory["user_profile"],
                readiness=tools["readiness"],
            ),
            identity=RuntimeIdentityConfig(session_key=session_key, subject_id=subject_id),
        )
        try:
            instance = cls(core_config)
            instance.run_id = run_id
            instance.task_graph = memory["task_graph"]
            return instance
        except BaseException:
            cls._stop_staged_scheduling(scheduling)
            raise

    @staticmethod
    def _build_core(
        bootstrap: Any,
        infra: Any,
        *,
        session_key: str,
        run_id: str,
        log_dir: Path | str | None,
        session_ttl: float,
        policy_sources: PolicySourceBundle,
        middleware_builder: Callable[..., MiddlewareRegistry] | None,
        activity_sink_provider: RunEventSinkProvider | None,
        feature_hook_registrar: Callable[[Any], None] | None,
        user_profile: Any,
    ) -> dict[str, Any]:
        """Stage 1: Build core infrastructure (hooks, auth, LLM, lanes)."""
        hooks, event_store, hook_metrics = bootstrap.build_hooks(
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
            activity_sink_provider=activity_sink_provider,
            feature_hook_registrar=feature_hook_registrar,
            user_profile=user_profile,
        )
        hook_registry = HookRegistry(events=hooks)
        middleware_registry = (
            bootstrap.build_middleware_registry(events=hooks)
            if middleware_builder is None
            else middleware_builder(events=hooks, policy_sources=policy_sources)
        )
        session_store = bootstrap.build_session_store(session_ttl=session_ttl)
        policy_chain = infra.build_default_policies()
        profile_store, profile_rotator, cooldown_tracker = infra.build_auth()
        # PR-LLMCLIENTPORT-COLLAPSE (2026-05-28) — was
        # ``infra.build_llm_adapters(...)`` whose sole production effect was
        # registering the five LLMAdapter built-ins. Call the registry bootstrap
        # directly now; the legacy ``set_llm_callable`` ContextVar chain that
        # surrounded it had no production consumer.
        from core.llm.adapters.registry import bootstrap_builtins

        bootstrap_builtins(policy_sources=policy_sources)
        config_watcher = bootstrap.build_config_watcher(hooks=hooks)
        lane_queue = infra.build_default_lanes()
        return {
            "hooks": hooks,
            "hook_registry": hook_registry,
            "middleware_registry": middleware_registry,
            "event_store": event_store,
            "hook_metrics": hook_metrics,
            "session_store": session_store,
            "policy_chain": policy_chain,
            "profile_store": profile_store,
            "profile_rotator": profile_rotator,
            "cooldown_tracker": cooldown_tracker,
            "config_watcher": config_watcher,
            "lane_queue": lane_queue,
        }

    @staticmethod
    def _build_tools(
        bootstrap: Any,
        hooks: Any,
        *,
        session_key: str,
    ) -> dict[str, Any]:
        """Stage 2: Build MCP, skills, readiness, plugins, tool offload."""
        from core.wiring import adapters as adapter_wiring

        mcp_manager = bootstrap.build_mcp_manager()
        from core.mcp.manager import clear_mcp_hooks, set_mcp_hooks

        set_mcp_hooks(hooks)
        hooks.add_owner_cleanup("mcp_hooks", clear_mcp_hooks)
        skill_registry = bootstrap.build_skill_registry()
        readiness = bootstrap.build_readiness()
        offload_store = bootstrap.build_tool_offload(session_id=session_key, hooks=hooks)
        notification, calendar = adapter_wiring.build_plugins()
        return {
            "mcp_manager": mcp_manager,
            "skill_registry": skill_registry,
            "readiness": readiness,
            "offload_store": offload_store,
            "notification": notification,
            "calendar": calendar,
        }

    @staticmethod
    def _build_memory_and_scheduling(
        bootstrap: Any,
        hooks: Any,
        session_store: Any,
        event_store: Any,
        *,
        session_key: str,
        subject_id: str,
        scheduling_registrar: Callable[[Any, Any], None] | None = None,
        scheduler_callback: Callable[[str, str, bool, str], None] | None = None,
        user_profile: Any = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Stage 3: Build memory, scheduling, and optional components."""
        from core.wiring import scheduling as scheduling_wiring

        (
            project_memory,
            organization_memory,
            context_assembler,
            _user_profile,
        ) = bootstrap.build_memory(
            session_store=session_store,
            hooks=hooks,
            event_store=event_store,
            user_profile=user_profile,
        )

        scheduling = scheduling_wiring.build_scheduling(
            hooks=hooks,
            feature_registrar=scheduling_registrar,
            on_job_fired=scheduler_callback,
        )

        try:
            task_graph = bootstrap.build_task_graph()
        except BaseException:
            GeodeRuntime._stop_staged_scheduling(scheduling)
            raise

        memory = {
            "project_memory": project_memory,
            "organization_memory": organization_memory,
            "context_assembler": context_assembler,
            "task_graph": task_graph,
            "user_profile": _user_profile,
        }
        return memory, scheduling

    @staticmethod
    def _stop_staged_scheduling(scheduling: dict[str, Any]) -> None:
        """Roll back scheduler threads when staged runtime assembly fails."""
        scheduler_service = scheduling.get("scheduler_service")
        if scheduler_service is not None:
            try:
                scheduler_service.stop()
            except Exception:
                log.warning("Staged scheduler rollback failed", exc_info=True)
        trigger_manager = scheduling.get("trigger_manager")
        if trigger_manager is not None:
            try:
                trigger_manager.stop_scheduler()
            except Exception:
                log.warning("Staged trigger rollback failed", exc_info=True)

    # ------------------------------------------------------------------
    # Instance methods
    # ------------------------------------------------------------------

    def store_session_data(self, data: dict[str, Any]) -> None:
        """Store data in the session store under the current session key."""
        self.session_store.set(self.session_key, data)

    def get_session_data(self) -> dict[str, Any] | None:
        """Retrieve session data for the current session key."""
        return self.session_store.get(self.session_key)

    def get_subject_context(self) -> dict[str, Any]:
        """Get project memory + rules context for the current subject."""
        return self.project_memory.get_context_for_subject(self.subject_id)

    def assemble_context(self) -> dict[str, Any]:
        """Assemble the explicit memory-context facade for callers that request it."""
        if self.context_assembler:
            ctx = self.context_assembler.assemble(self.session_key, self.subject_id)
            self.context_assembler.mark_assembled(ctx.get("_assembled_at"))
            return ctx
        return self.get_subject_context()

    def get_task_status(self, task_id: str | None = None) -> dict[str, Any]:
        """Get task graph status. If task_id given, return single task; else summary."""
        if self.task_graph is None:
            return {"error": "task_graph not initialized"}
        if task_id is not None:
            task = self.task_graph.get_task(task_id)
            if task is None:
                return {"error": f"task '{task_id}' not found"}
            return {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "elapsed_s": task.elapsed_s,
                "error": task.error,
            }
        return self.task_graph.execution_summary()

    def reset_task_graph(self) -> None:
        """Reset task graph for REPL reuse."""
        from core.wiring.bootstrap import build_task_graph

        self.task_graph = build_task_graph()

    def get_available_tools(self, *, mode: str = "full_pipeline") -> list[str]:
        """Get tools available under the given pipeline mode."""
        return self.tool_registry.list_tools(policy=self.policy_chain, mode=mode)

    def prune_events(self) -> int:
        """Apply age and row-count retention to operational events."""
        return self.event_store.prune()

    def prune_logs(self) -> int:
        """Compatibility alias for :meth:`prune_events`."""
        return self.prune_events()

    def get_health(self) -> dict[str, Any]:
        """Aggregate health stats from all infrastructure components.

        Returns a dict of component_name -> stats_dict for dashboarding.
        """
        health: dict[str, Any] = {"subject_id": self.subject_id, "session_key": self.session_key}

        if self.trigger_manager:
            health["triggers"] = self.trigger_manager.stats.to_dict()
            health["scheduler_running"] = self.trigger_manager.is_scheduler_running
        if self.scheduler_service:
            health["advanced_scheduler"] = {
                "running": self.scheduler_service.is_running,
                "job_count": len(self.scheduler_service.list_jobs(include_disabled=True)),
            }

        health["lanes"] = self.lane_queue.list_lanes()
        health["hook_events"] = {
            "rows": self.event_store.count(),
            "db_path": str(self.event_store.db_path),
        }
        health["hook_metrics"] = self.hook_metrics.summary()
        health["extensions"] = [decision.status() for decision in self.extension_decisions]

        if self.task_graph is not None:
            health["task_graph"] = {
                "total": self.task_graph.task_count,
                "stats": self.task_graph.stats.to_dict(),
                "is_complete": self.task_graph.is_complete(),
            }

        return health

    def shutdown(self) -> None:
        """Clean shutdown of background components."""
        if self._shutdown:
            return
        self._shutdown = True
        try:
            self.config_watcher.stop()
        except Exception:
            log.warning("Config watcher shutdown failed", exc_info=True)
        if self.scheduler_service:
            try:
                self.scheduler_service.save()
                self.scheduler_service.stop()
            except Exception:
                log.warning("Scheduler service shutdown failed", exc_info=True)
        if self.trigger_manager:
            try:
                self.trigger_manager.stop_scheduler()
            except Exception:
                log.warning("Trigger manager shutdown failed", exc_info=True)
        if self.mcp_manager is not None:
            try:
                self.mcp_manager.shutdown()
            except Exception:
                log.warning("MCP manager shutdown failed", exc_info=True)
        self.hooks.close()
