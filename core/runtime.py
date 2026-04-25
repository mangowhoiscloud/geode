"""Runtime — production wiring for GEODE infrastructure components.

Centralizes creation and lifecycle of all infrastructure singletons:
- HookSystem with RunLog handler
- InMemorySessionStore
- PolicyChain with default policies
- ToolRegistry with analysis tools
- ConfigWatcher for hot reload
- StuckDetector for long-running task detection
- LaneQueue for concurrency control
- Session key utilities
- L4.5 Automation: Drift, ModelRegistry, ExpertPanel, Correlation,
  OutcomeTracker, SnapshotManager, TriggerManager, FeedbackLoop
- L2 Memory: OrganizationMemory, HybridSessionStore, ContextAssembler

Implementation details are decomposed into `core.lifecycle`:
    bootstrap  — hooks, memory, session, config_watcher, task, prompt, plugin_registry
    infra      — policies, tools, LLM, auth, lanes
    automation — L4.5 9 components + hook wiring
    adapters   — MCP signal/notification/calendar/gateway
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from core.llm.prompt_assembler import PromptAssembler

from core.auth.cooldown import CooldownTracker
from core.auth.profiles import ProfileStore
from core.auth.rotation import ProfileRotator
from core.automation.correlation import CorrelationAnalyzer
from core.automation.drift import CUSUMDetector
from core.automation.expert_panel import ExpertPanel
from core.automation.feedback_loop import FeedbackLoop
from core.automation.model_registry import ModelRegistry
from core.automation.outcome_tracking import OutcomeTracker
from core.automation.snapshot import SnapshotManager
from core.config import settings
from core.domains.loader import load_domain_adapter
from core.domains.port import set_domain
from core.hooks import HookSystem
from core.lifecycle.bootstrap import (  # noqa: F401  — backward compat
    _make_run_log_handler,
    get_plugin_status,
)
from core.lifecycle.container import build_default_lanes as _build_default_lanes  # noqa: F401
from core.lifecycle.container import (
    build_default_policies as _build_default_policies,  # noqa: F401
)
from core.lifecycle.container import (
    build_default_registry as _build_default_registry,  # noqa: F401
)
from core.lifecycle.container import make_tool_executor as _make_tool_executor  # noqa: F401
from core.llm.router import LLMClientPort
from core.memory.context import ContextAssembler
from core.memory.organization import MonoLakeOrganizationMemory
from core.memory.port import SessionStorePort
from core.memory.project import ProjectMemory
from core.memory.session_key import build_session_key, build_thread_config
from core.orchestration.hot_reload import ConfigWatcher
from core.orchestration.lane_queue import LaneQueue
from core.orchestration.run_log import RunLog
from core.orchestration.stuck_detection import StuckDetector
from core.orchestration.task_bridge import TaskGraphHookBridge
from core.orchestration.task_system import TaskGraph
from core.scheduler.triggers import TriggerManager
from core.tools.policy import NodeScopePolicy, PolicyChain
from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL = 3600.0  # 1 hour
DEFAULT_LOG_DIR = Path.home() / ".geode" / "runs"
DEFAULT_STUCK_TIMEOUT_S = 7200.0  # 2 hours


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
    llm_adapter: LLMClientPort
    config_watcher: ConfigWatcher
    stuck_detector: StuckDetector
    lane_queue: LaneQueue
    project_memory: ProjectMemory
    session_key: str
    ip_name: str
    secondary_adapter: LLMClientPort | None = None
    profile_store: ProfileStore | None = None
    profile_rotator: ProfileRotator | None = None
    cooldown_tracker: CooldownTracker | None = None
    # Unified bootstrap: resources previously in bootstrap_geode() only
    mcp_manager: Any = None
    skill_registry: Any = None
    readiness: Any = None


@dataclass
class RuntimeAutomationConfig:
    """L4.5 Automation components (all optional)."""

    drift_detector: CUSUMDetector | None = None
    model_registry: ModelRegistry | None = None
    expert_panel: ExpertPanel | None = None
    correlation_analyzer: CorrelationAnalyzer | None = None
    outcome_tracker: OutcomeTracker | None = None
    snapshot_manager: SnapshotManager | None = None
    trigger_manager: TriggerManager | None = None
    scheduler_service: Any | None = None
    feedback_loop: FeedbackLoop | None = None


@dataclass
class RuntimeMemoryConfig:
    """L2 Memory + Prompt assembly components (all optional)."""

    organization_memory: MonoLakeOrganizationMemory | None = None
    context_assembler: ContextAssembler | None = None
    prompt_assembler: Any | None = field(default=None)  # PromptAssembler (TYPE_CHECKING)


# ---------------------------------------------------------------------------
# GeodeRuntime — the main integration class
# ---------------------------------------------------------------------------


class GeodeRuntime:
    """Production runtime that wires all infrastructure components.

    Usage:
        runtime = GeodeRuntime.create("Berserk")
        graph = runtime.compile_graph()
        result = graph.stream(state, config=runtime.thread_config)
    """

    def __init__(
        self,
        core: RuntimeCoreConfig,
        automation: RuntimeAutomationConfig | None = None,
        memory: RuntimeMemoryConfig | None = None,
    ) -> None:
        # Unpack core (flat attributes for backward compat)
        self.hooks = core.hooks
        self.session_store = core.session_store
        self.policy_chain = core.policy_chain
        self.tool_registry = core.tool_registry
        self.run_log = core.run_log
        self.llm_adapter = core.llm_adapter
        self.secondary_adapter = core.secondary_adapter
        self.profile_store = core.profile_store
        self.profile_rotator = core.profile_rotator
        self.cooldown_tracker = core.cooldown_tracker or CooldownTracker()
        self.config_watcher = core.config_watcher
        self.stuck_detector = core.stuck_detector
        self.lane_queue = core.lane_queue
        self.project_memory = core.project_memory
        self.session_key = core.session_key
        self.ip_name = core.ip_name
        self.run_id = ""
        self.is_subagent: bool = False
        # Unified bootstrap resources
        self.mcp_manager = core.mcp_manager
        self.skill_registry = core.skill_registry
        self.readiness = core.readiness
        self._compiled_graph: CompiledStateGraph[Any, None, Any, Any] | None = None
        # Unpack automation (L4.5)
        auto = automation or RuntimeAutomationConfig()
        self.drift_detector = auto.drift_detector
        self.model_registry = auto.model_registry
        self.expert_panel = auto.expert_panel
        self.correlation_analyzer = auto.correlation_analyzer
        self.outcome_tracker = auto.outcome_tracker
        self.snapshot_manager = auto.snapshot_manager
        self.trigger_manager = auto.trigger_manager
        self.scheduler_service = auto.scheduler_service
        self.feedback_loop = auto.feedback_loop
        # Unpack memory (L2 + ADR-007)
        mem = memory or RuntimeMemoryConfig()
        self.organization_memory = mem.organization_memory
        self.context_assembler = mem.context_assembler
        self.prompt_assembler: PromptAssembler | None = mem.prompt_assembler
        # L4 Task tracking
        self.task_graph: TaskGraph | None = None
        self._task_bridge: TaskGraphHookBridge | None = None

    # ------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        ip_name: str,
        *,
        phase: str = "analysis",
        domain_name: str = "game_ip",
        enable_checkpoint: bool = True,
        log_dir: Path | str | None = None,
        session_ttl: float = DEFAULT_SESSION_TTL,
        stuck_timeout_s: float = DEFAULT_STUCK_TIMEOUT_S,
    ) -> GeodeRuntime:
        """Factory method — create a fully wired runtime for an IP analysis.

        Staged initialization (Claude Code entrypoints/init.ts pattern):
        1. _build_core: domain, sessions, hooks, config, auth, LLM, lanes
        2. _build_tools: MCP, skills, readiness, plugins, tool offload
        3. _build_memory: project/org memory, context assembler, automation
        4. Assembly: pack configs, create instance, attach optional components
        """
        from core.lifecycle import bootstrap
        from core.lifecycle import container as infra

        # Stage 0: Domain + session identity
        domain = load_domain_adapter(domain_name)
        set_domain(domain)
        session_key = build_session_key(ip_name, phase)
        run_id = uuid.uuid4().hex[:12]

        # Stage 1: Core sub-systems
        core = cls._build_core(
            bootstrap,
            infra,
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
            session_ttl=session_ttl,
            stuck_timeout_s=stuck_timeout_s,
        )

        # Stage 2: Tools, MCP, Skills
        tools = cls._build_tools(bootstrap, core["hooks"], session_key=session_key)

        # Stage 3: Memory + Automation
        memory, automation = cls._build_memory_and_automation(
            bootstrap,
            core["hooks"],
            core["session_store"],
            session_key=session_key,
            ip_name=ip_name,
        )

        log.info(
            "GeodeRuntime created: ip=%s, key=%s, tools=%d, lanes=%s",
            ip_name,
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
            llm_adapter=core["llm_adapter"],
            config_watcher=core["config_watcher"],
            stuck_detector=core["stuck_detector"],
            lane_queue=core["lane_queue"],
            project_memory=memory["project_memory"],
            session_key=session_key,
            ip_name=ip_name,
            secondary_adapter=core["secondary_adapter"],
            profile_store=core["profile_store"],
            profile_rotator=core["profile_rotator"],
            cooldown_tracker=core["cooldown_tracker"],
            mcp_manager=tools["mcp_manager"],
            skill_registry=tools["skill_registry"],
            readiness=tools["readiness"],
        )
        automation_config = RuntimeAutomationConfig(**automation)
        memory_config = RuntimeMemoryConfig(
            organization_memory=memory["organization_memory"],
            context_assembler=memory["context_assembler"],
            prompt_assembler=memory["prompt_assembler"],
        )
        instance = cls(core_config, automation_config, memory_config)
        instance.run_id = run_id
        instance.task_graph = memory["task_graph"]
        instance._task_bridge = memory["task_bridge"]
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
        stuck_timeout_s: float,
    ) -> dict[str, Any]:
        """Stage 1: Build core infrastructure (hooks, auth, LLM, lanes)."""
        hooks, run_log, stuck_detector, _session_metrics = bootstrap.build_hooks(
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
            stuck_timeout_s=stuck_timeout_s,
        )
        session_store = bootstrap.build_session_store(session_ttl=session_ttl)
        policy_chain = infra.build_default_policies()
        tool_registry = infra.build_default_registry()
        profile_store, profile_rotator, cooldown_tracker = infra.build_auth()
        llm_adapter, secondary_adapter = infra.build_llm_adapters(
            tool_registry,
            policy_chain,
        )
        config_watcher = bootstrap.build_config_watcher(hooks=hooks)
        lane_queue = infra.build_default_lanes()
        return {
            "hooks": hooks,
            "run_log": run_log,
            "stuck_detector": stuck_detector,
            "session_store": session_store,
            "policy_chain": policy_chain,
            "tool_registry": tool_registry,
            "profile_store": profile_store,
            "profile_rotator": profile_rotator,
            "cooldown_tracker": cooldown_tracker,
            "llm_adapter": llm_adapter,
            "secondary_adapter": secondary_adapter,
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
        from core.lifecycle import adapters as adapter_wiring

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
    def _build_memory_and_automation(
        bootstrap: Any,
        hooks: Any,
        session_store: Any,
        *,
        session_key: str,
        ip_name: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Stage 3: Build memory, automation, and optional components."""
        from core.lifecycle import automation as automation_wiring

        (
            project_memory,
            organization_memory,
            context_assembler,
            _user_profile,
        ) = bootstrap.build_memory(session_store=session_store, hooks=hooks)

        automation = automation_wiring.build_automation(
            hooks=hooks,
            session_key=session_key,
            ip_name=ip_name,
            project_memory=project_memory,
        )

        try:
            prompt_assembler = bootstrap.build_prompt_assembler(hooks=hooks)
        except ImportError:
            log.debug("ADR-007 prompt_assembler not yet available — skipping")
            prompt_assembler = None
        task_graph, task_bridge = bootstrap.build_task_graph(
            hooks=hooks,
            ip_name=ip_name,
        )

        memory = {
            "project_memory": project_memory,
            "organization_memory": organization_memory,
            "context_assembler": context_assembler,
            "prompt_assembler": prompt_assembler,
            "task_graph": task_graph,
            "task_bridge": task_bridge,
        }
        return memory, automation

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def thread_config(self) -> dict[str, Any]:
        """LangGraph thread config for this session."""
        return build_thread_config(self.ip_name, "analysis")

    @property
    def checkpoint_db(self) -> str | None:
        """Checkpoint DB path from settings, or None.

        Returns None for empty strings so the MemorySaver fallback
        in compile_graph kicks in.
        """
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
        """Compile the GEODE graph with hooks and checkpointing (default: enabled).

        Caches the compiled graph for reuse across multiple invocations.
        """
        if self._compiled_graph is not None:
            return self._compiled_graph

        from core.graph import compile_graph

        # Subagents use MemorySaver for thread safety (G7 fix)
        if self.is_subagent:
            checkpoint_db = None  # forces MemorySaver fallback
        else:
            checkpoint_db = self.checkpoint_db if enable_checkpoint else None
        interrupt_list = [
            n.strip() for n in settings.interrupt_nodes.split(",") if n.strip()
        ] or None
        compiled = compile_graph(
            hooks=self.hooks,
            checkpoint_db=checkpoint_db,
            confidence_threshold=settings.confidence_threshold,
            max_iterations=settings.max_iterations,
            interrupt_before=interrupt_list,
            memory_fallback=True,
            prompt_assembler=self.prompt_assembler,
            node_scope_policy=NodeScopePolicy(),
        )
        self._compiled_graph = compiled
        return compiled

    def store_session_data(self, data: dict[str, Any]) -> None:
        """Store data in the session store under the current session key."""
        self.session_store.set(self.session_key, data)

    def get_session_data(self) -> dict[str, Any] | None:
        """Retrieve session data for the current session key."""
        return self.session_store.get(self.session_key)

    def get_ip_context(self) -> dict[str, Any]:
        """Get project memory + rules context for the current IP."""
        return self.project_memory.get_context_for_ip(self.ip_name)

    def assemble_context(self) -> dict[str, Any]:
        """Assemble full 3-tier context (Org -> Project -> Session)."""
        if self.context_assembler:
            ctx = self.context_assembler.assemble(self.session_key, self.ip_name)
            self.context_assembler.mark_assembled(ctx.get("_assembled_at"))
            return ctx
        return self.get_ip_context()

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
        """Reset task graph for REPL reuse (re-creates graph + bridge)."""
        from core.lifecycle.bootstrap import build_task_graph

        if self._task_bridge is not None:
            self._task_bridge.unregister()
        graph, bridge = build_task_graph(hooks=self.hooks, ip_name=self.ip_name)
        self.task_graph = graph
        self._task_bridge = bridge

    def get_available_tools(self, *, mode: str = "full_pipeline") -> list[str]:
        """Get tools available under the given pipeline mode."""
        return self.tool_registry.list_tools(policy=self.policy_chain, mode=mode)

    def get_tool_state_injection(self, *, mode: str = "full_pipeline") -> dict[str, Any]:
        """Return tool definitions for injection into GeodeState.

        Nodes that support tool-augmented paths (Synthesizer, BiasBuster) read
        ``_tool_definitions`` from state and ``get_tool_executor()`` from contextvar.
        The executor callable is NOT stored in state (functions are not serializable
        by LangGraph's msgpack checkpointer).

        Returns empty dict if no tools are available (dry_run, etc).
        Also injects tool executor into contextvar via ``set_tool_executor()``.
        """
        from core.tools.registry import set_tool_executor

        available = self.tool_registry.list_tools(policy=self.policy_chain, mode=mode)
        if not available:
            set_tool_executor(None)
            return {}
        tool_defs = self.tool_registry.to_anthropic_tools_with_defer(
            policy=self.policy_chain,
            mode=mode,
        )
        if not tool_defs:
            set_tool_executor(None)
            return {}

        def _executor(name: str, **kwargs: Any) -> dict[str, Any]:
            return self.tool_registry.execute(name, policy=self.policy_chain, **kwargs)

        set_tool_executor(_executor)
        return {"_tool_definitions": tool_defs}

    def prune_logs(self) -> int:
        """Prune run logs if they exceed size limits."""
        return self.run_log.prune()

    def get_health(self) -> dict[str, Any]:
        """Aggregate health stats from all infrastructure components.

        Returns a dict of component_name -> stats_dict for dashboarding.
        """
        health: dict[str, Any] = {"ip_name": self.ip_name, "session_key": self.session_key}

        if self.drift_detector:
            health["drift"] = self.drift_detector.stats.to_dict()
        if self.model_registry:
            health["model_registry"] = self.model_registry.stats.to_dict()
        if self.expert_panel:
            health["expert_panel"] = self.expert_panel.stats.to_dict()
        if self.correlation_analyzer:
            health["correlation"] = self.correlation_analyzer.stats.to_dict()
        if self.outcome_tracker:
            health["outcome_tracker"] = self.outcome_tracker.stats.to_dict()
        if self.trigger_manager:
            health["triggers"] = self.trigger_manager.stats.to_dict()
            health["scheduler_running"] = self.trigger_manager.is_scheduler_running
        if self.scheduler_service:
            health["advanced_scheduler"] = {
                "running": self.scheduler_service.is_running,
                "job_count": len(self.scheduler_service.list_jobs(include_disabled=True)),
            }
        if self.feedback_loop:
            health["feedback_loop"] = self.feedback_loop.stats.to_dict()

        health["stuck_tasks"] = len(self.stuck_detector.check_stuck())
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
        self.stuck_detector.stop_monitor()
        if self.scheduler_service:
            self.scheduler_service.save()
            self.scheduler_service.stop()
        if self.trigger_manager:
            self.trigger_manager.stop_scheduler()
        if self._task_bridge:
            self._task_bridge.unregister()
