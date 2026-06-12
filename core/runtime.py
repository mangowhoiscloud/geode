"""Runtime — production wiring for GEODE infrastructure components.

Centralizes creation and lifecycle of all infrastructure singletons:
- HookSystem with RunLog handler
- InMemorySessionStore
- PolicyChain with default policies
- ToolRegistry with analysis tools
- ConfigWatcher for hot reload
- LaneQueue for concurrency control
- Session key utilities
- Scheduling: TriggerManager + SchedulerService
- L2 Memory: OrganizationMemory, HybridSessionStore, ContextAssembler

Implementation details are decomposed into `core.wiring`:
    bootstrap  — hooks, memory, session, config_watcher, task, plugin_registry
    infra      — policies, tools, LLM, auth, lanes
    scheduling — TriggerManager + SchedulerService + auto-trigger
    adapters   — MCP signal/notification/calendar/gateway
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    # ``from __future__ import annotations`` defers evaluation of all
    # type annotations to strings, so the classes referenced only in
    # field / variable annotations below do not need to be imported at
    # runtime.  Pushing them into ``TYPE_CHECKING`` removes their entire
    # module trees (the L2 memory graph, scheduler.triggers, langgraph
    # hot-reload, task system) from the cold-start path.  Each tree is
    # loaded lazily by the wiring builders
    # (``core.wiring.{bootstrap,scheduling}``) only when the matching
    # component actually fires.
    from core.memory.context import ContextAssembler
    from core.memory.organization import MonoLakeOrganizationMemory
    from core.memory.project import ProjectMemory
    from core.orchestration.hot_reload import ConfigWatcher
    from core.orchestration.task_system import TaskGraph
    from core.scheduler.triggers import TriggerManager

from core.auth.cooldown import CooldownTracker
from core.auth.profiles import ProfileStore
from core.auth.rotation import ProfileRotator
from core.hooks import HookSystem
from core.memory.port import SessionStorePort
from core.memory.session_key import build_session_key, build_thread_config
from core.observability.run_log import RunLog
from core.orchestration.lane_queue import LaneQueue
from core.paths import GLOBAL_RUNS_DIR
from core.tools.policy import PolicyChain
from core.tools.registry import ToolRegistry
from core.wiring.bootstrap import get_plugin_status as get_plugin_status

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL = 3600.0  # 1 hour
DEFAULT_LOG_DIR = GLOBAL_RUNS_DIR  # P2 (v0.95.x) — was literal `Path.home() / ".geode" / "runs"`


# ---------------------------------------------------------------------------
# Config dataclasses — group __init__ parameters by concern
# ---------------------------------------------------------------------------


@dataclass
class RuntimeCoreConfig:
    """Essential infrastructure parameters (always required)."""

    hooks: HookSystem
    session_store: SessionStorePort
    policy_chain: PolicyChain
    tool_registry: ToolRegistry
    run_log: RunLog
    config_watcher: ConfigWatcher
    lane_queue: LaneQueue
    project_memory: ProjectMemory
    session_key: str
    subject_id: str
    profile_store: ProfileStore | None = None
    profile_rotator: ProfileRotator | None = None
    cooldown_tracker: CooldownTracker | None = None
    # Unified bootstrap: resources previously in bootstrap_geode() only
    mcp_manager: Any = None
    skill_registry: Any = None
    readiness: Any = None


@dataclass
class RuntimeSchedulingConfig:
    """Scheduler components (all optional)."""

    trigger_manager: TriggerManager | None = None
    scheduler_service: Any | None = None


@dataclass
class RuntimeMemoryConfig:
    """L2 Memory components (all optional)."""

    organization_memory: MonoLakeOrganizationMemory | None = None
    context_assembler: ContextAssembler | None = None


# ---------------------------------------------------------------------------
# GeodeRuntime — the main integration class
# ---------------------------------------------------------------------------


class GeodeRuntime:
    """Production runtime that wires all infrastructure components.

    Usage:
        runtime = GeodeRuntime.create("subject")
        graph = runtime.compile_graph()
        async for event in graph.astream(state, config=runtime.thread_config):
            ...
    """

    def __init__(
        self,
        core: RuntimeCoreConfig,
        scheduling: RuntimeSchedulingConfig | None = None,
        memory: RuntimeMemoryConfig | None = None,
    ) -> None:
        # Unpack core (flat attributes for backward compat)
        self.hooks = core.hooks
        self.session_store = core.session_store
        self.policy_chain = core.policy_chain
        self.tool_registry = core.tool_registry
        self.run_log = core.run_log
        self.profile_store = core.profile_store
        self.profile_rotator = core.profile_rotator
        self.cooldown_tracker = core.cooldown_tracker or CooldownTracker()
        self.config_watcher = core.config_watcher
        self.lane_queue = core.lane_queue
        self.project_memory = core.project_memory
        self.session_key = core.session_key
        self.subject_id = core.subject_id
        self.run_id = ""
        self.is_subagent: bool = False
        # Unified bootstrap resources
        self.mcp_manager = core.mcp_manager
        self.skill_registry = core.skill_registry
        self.readiness = core.readiness
        self._compiled_graph: CompiledStateGraph[Any, None, Any, Any] | None = None
        # Unpack scheduling
        sched = scheduling or RuntimeSchedulingConfig()
        self.trigger_manager = sched.trigger_manager
        self.scheduler_service = sched.scheduler_service
        # Unpack memory (L2)
        mem = memory or RuntimeMemoryConfig()
        self.organization_memory = mem.organization_memory
        self.context_assembler = mem.context_assembler
        # L4 Task tracking
        self.task_graph: TaskGraph | None = None

    # ------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        subject_id: str,
        *,
        phase: str = "analysis",
        enable_checkpoint: bool = True,
        log_dir: Path | str | None = None,
        session_ttl: float = DEFAULT_SESSION_TTL,
    ) -> GeodeRuntime:
        """Factory method — create a fully wired runtime for a GEODE session.

        Staged initialization (Claude Code entrypoints/init.ts pattern):
        1. _build_core: sessions, hooks, config, auth, LLM, lanes
        2. _build_tools: MCP, skills, readiness, plugins, tool offload
        3. _build_memory: project/org memory, context assembler, scheduling
        4. Assembly: pack configs, create instance, attach optional components
        """
        from core.wiring import bootstrap
        from core.wiring import container as infra

        # Stage 0: Session identity.
        session_key = build_session_key(subject_id, phase)
        run_id = uuid.uuid4().hex[:12]

        # Stage 1: Core sub-systems
        core = cls._build_core(
            bootstrap,
            infra,
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
            session_ttl=session_ttl,
        )

        # Stage 2: Tools, MCP, Skills
        tools = cls._build_tools(bootstrap, core["hooks"], session_key=session_key)

        # Stage 3: Memory + Scheduling
        memory, scheduling = cls._build_memory_and_scheduling(
            bootstrap,
            core["hooks"],
            core["session_store"],
            session_key=session_key,
            subject_id=subject_id,
        )

        log.info(
            "GeodeRuntime created: subject=%s, key=%s, tools=%d, lanes=%s",
            subject_id,
            session_key,
            len(core["tool_registry"]),
            core["lane_queue"].list_lanes(),
        )

        # Stage 4: Assembly
        core_config = RuntimeCoreConfig(
            hooks=core["hooks"],
            session_store=core["session_store"],
            policy_chain=core["policy_chain"],
            tool_registry=core["tool_registry"],
            run_log=core["run_log"],
            config_watcher=core["config_watcher"],
            lane_queue=core["lane_queue"],
            project_memory=memory["project_memory"],
            session_key=session_key,
            subject_id=subject_id,
            profile_store=core["profile_store"],
            profile_rotator=core["profile_rotator"],
            cooldown_tracker=core["cooldown_tracker"],
            mcp_manager=tools["mcp_manager"],
            skill_registry=tools["skill_registry"],
            readiness=tools["readiness"],
        )
        scheduling_config = RuntimeSchedulingConfig(**scheduling)
        memory_config = RuntimeMemoryConfig(
            organization_memory=memory["organization_memory"],
            context_assembler=memory["context_assembler"],
        )
        instance = cls(core_config, scheduling_config, memory_config)
        instance.run_id = run_id
        instance.task_graph = memory["task_graph"]
        return instance

    @staticmethod
    def _build_core(
        bootstrap: Any,
        infra: Any,
        *,
        session_key: str,
        run_id: str,
        log_dir: Path | str | None,
        session_ttl: float,
    ) -> dict[str, Any]:
        """Stage 1: Build core infrastructure (hooks, auth, LLM, lanes)."""
        hooks, run_log, _session_metrics = bootstrap.build_hooks(
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
        )
        session_store = bootstrap.build_session_store(session_ttl=session_ttl)
        policy_chain = infra.build_default_policies()
        tool_registry = infra.build_default_registry()
        profile_store, profile_rotator, cooldown_tracker = infra.build_auth()
        # PR-LLMCLIENTPORT-COLLAPSE (2026-05-28) — was
        # ``infra.build_llm_adapters(...)`` whose sole production effect was
        # registering the 8 LLMAdapter built-ins. Call the registry bootstrap
        # directly now; the legacy ``set_llm_callable`` ContextVar chain that
        # surrounded it had no production consumer.
        from core.llm.adapters.registry import bootstrap_builtins

        bootstrap_builtins()
        config_watcher = bootstrap.build_config_watcher(hooks=hooks)
        lane_queue = infra.build_default_lanes()
        return {
            "hooks": hooks,
            "run_log": run_log,
            "session_store": session_store,
            "policy_chain": policy_chain,
            "tool_registry": tool_registry,
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
        from core.mcp.manager import set_mcp_hooks

        set_mcp_hooks(hooks)
        skill_registry = bootstrap.build_skill_registry()
        readiness = bootstrap.build_readiness()
        bootstrap.build_tool_offload(session_id=session_key, hooks=hooks)
        adapter_wiring.build_plugins()
        return {
            "mcp_manager": mcp_manager,
            "skill_registry": skill_registry,
            "readiness": readiness,
        }

    @staticmethod
    def _build_memory_and_scheduling(
        bootstrap: Any,
        hooks: Any,
        session_store: Any,
        *,
        session_key: str,
        subject_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Stage 3: Build memory, scheduling, and optional components."""
        from core.wiring import scheduling as scheduling_wiring

        (
            project_memory,
            organization_memory,
            context_assembler,
            _user_profile,
        ) = bootstrap.build_memory(session_store=session_store, hooks=hooks)

        scheduling = scheduling_wiring.build_scheduling(hooks=hooks)

        task_graph = bootstrap.build_task_graph()

        memory = {
            "project_memory": project_memory,
            "organization_memory": organization_memory,
            "context_assembler": context_assembler,
            "task_graph": task_graph,
        }
        return memory, scheduling

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def thread_config(self) -> dict[str, Any]:
        """LangGraph thread config for this session."""
        return build_thread_config(self.subject_id, "analysis")

    @property
    def checkpoint_db(self) -> str | None:
        """Checkpoint DB path from settings, or None.

        Returns None for empty strings so the MemorySaver fallback
        in compile_graph kicks in.
        """
        from core.config import settings

        db = settings.checkpoint_db
        return db if db and db.strip() else None

    # ------------------------------------------------------------------
    # Instance methods
    # ------------------------------------------------------------------

    def compile_graph(
        self,
        *,
        enable_checkpoint: bool = True,
    ) -> CompiledStateGraph[Any, None, Any, Any]:
        """Compile a graph with hooks and checkpointing.

        Caches the compiled graph for reuse across multiple invocations.
        """
        raise RuntimeError(
            "GEODE core no longer ships a built-in analysis graph. "
            "Install an external package that provides a LangGraph pipeline "
            "before calling compile_graph()."
        )

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
        """Assemble full 3-tier context (Org -> Project -> Session)."""
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

    def get_tool_state_injection(self, *, mode: str = "full_pipeline") -> dict[str, Any]:
        """Return tool definitions for injection into graph state.

        Nodes that support tool-augmented paths (for example, Synthesizer) read
        ``_tool_definitions`` from state and ``get_async_tool_executor()`` from contextvar.
        The executor callable is NOT stored in state (functions are not serializable
        by LangGraph's msgpack checkpointer).

        Returns empty dict if no tools are available (dry_run, etc).
        Also injects tool executor into contextvar via ``set_async_tool_executor()``.
        """
        from core.tools.registry import set_async_tool_executor

        available = self.tool_registry.list_tools(policy=self.policy_chain, mode=mode)
        if not available:
            set_async_tool_executor(None)
            return {}
        # PR-TOOL-SEARCH-WIRE (2026-06-13): plain serialization. The bespoke
        # registry-level defer (to_anthropic_tools_with_defer + ToolSearchTool)
        # was superseded by the official hosted tool-search wiring in
        # core/llm/providers/anthropic.py — its defer_loading markers were
        # stripped by the adapter key filter anyway, so this path never
        # actually deferred on the wire.
        tool_defs = self.tool_registry.to_anthropic_tools(
            policy=self.policy_chain,
            mode=mode,
        )
        if not tool_defs:
            set_async_tool_executor(None)
            return {}

        async def _aexecutor(name: str, **kwargs: Any) -> dict[str, Any]:
            return await self.tool_registry.aexecute(name, policy=self.policy_chain, **kwargs)

        set_async_tool_executor(_aexecutor)
        return {"_tool_definitions": tool_defs}

    def prune_logs(self) -> int:
        """Prune run logs if they exceed size limits."""
        return self.run_log.prune()

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

        if self.task_graph is not None:
            health["task_graph"] = {
                "total": self.task_graph.task_count,
                "stats": self.task_graph.stats.to_dict(),
                "is_complete": self.task_graph.is_complete(),
            }

        return health

    def shutdown(self) -> None:
        """Clean shutdown of background components."""
        self.config_watcher.stop()
        if self.scheduler_service:
            self.scheduler_service.save()
            self.scheduler_service.stop()
        if self.trigger_manager:
            self.trigger_manager.stop_scheduler()
