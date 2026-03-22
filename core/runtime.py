"""Runtime — production wiring for GEODE infrastructure components.

Centralizes creation and lifecycle of all infrastructure singletons:
- HookSystem with RunLog handler
- InMemorySessionStore
- PolicyChain with default policies
- ToolRegistry with analysis tools
- CoalescingQueue for request deduplication
- ConfigWatcher for hot reload
- StuckDetector for long-running task detection
- LaneQueue for concurrency control
- Session key utilities
- L4.5 Automation: Drift, ModelRegistry, ExpertPanel, Correlation,
  OutcomeTracker, SnapshotManager, TriggerManager, FeedbackLoop
- L2 Memory: OrganizationMemory, HybridSessionStore, ContextAssembler
"""

from __future__ import annotations

import logging
import uuid
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
from core.automation.triggers import TriggerManager, TriggerType
from core.config import settings
from core.domains.loader import load_domain_adapter
from core.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter
from core.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from core.infrastructure.ports.auth_port import (
    CooldownTrackerPort,
    ProfileRotatorPort,
    ProfileStorePort,
)
from core.infrastructure.ports.automation_port import (
    CorrelationAnalyzerPort,
    DriftDetectorPort,
    ExpertPanelPort,
    FeedbackLoopPort,
    ModelRegistryPort,
    OutcomeTrackerPort,
    SnapshotManagerPort,
    TriggerManagerPort,
)
from core.infrastructure.ports.domain_port import set_domain
from core.infrastructure.ports.hook_port import HookSystemPort
from core.infrastructure.ports.llm_port import LLMClientPort
from core.infrastructure.ports.memory_port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)
from core.infrastructure.ports.orchestration_port import (
    CoalescingQueuePort,
    ConfigWatcherPort,
    LaneQueuePort,
    RunLogPort,
    StuckDetectorPort,
    TaskGraphPort,
)
from core.infrastructure.ports.tool_port import (
    PolicyChainPort,
    ToolRegistryPort,
)
from core.memory.context import ContextAssembler
from core.memory.organization import MonoLakeOrganizationMemory
from core.memory.project import ProjectMemory
from core.memory.session import InMemorySessionStore
from core.memory.session_key import build_session_key, build_thread_config
from core.memory.user_profile import FileBasedUserProfile
from core.orchestration.coalescing import CoalescingQueue
from core.orchestration.hooks import HookEvent, HookSystem
from core.orchestration.hot_reload import ConfigWatcher
from core.orchestration.lane_queue import LaneQueue
from core.orchestration.run_log import RunLog, RunLogEntry
from core.orchestration.stuck_detection import StuckDetector
from core.orchestration.task_bridge import TaskGraphHookBridge
from core.orchestration.task_system import create_geode_task_graph
from core.tools.analysis import ExplainScoreTool, PSMCalculateTool, RunAnalystTool, RunEvaluatorTool
from core.tools.policy import NodeScopePolicy, ToolPolicy
from core.tools.registry import ToolRegistry, ToolSearchTool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL = 3600.0  # 1 hour
DEFAULT_LOG_DIR = Path.home() / ".geode" / "runs"
DEFAULT_GLOBAL_CONCURRENCY = 4
DEFAULT_STUCK_TIMEOUT_S = 7200.0  # 2 hours


# ---------------------------------------------------------------------------
# RunLog hook handler — bridges HookSystem events → JSONL log
# ---------------------------------------------------------------------------


def _make_run_log_handler(
    run_log: RunLogPort,
    session_key: str,
    run_id: str,
) -> tuple[str, Any]:
    """Create a hook handler that writes events to RunLog."""

    def _log_event(event: HookEvent, data: dict[str, Any]) -> None:
        entry = RunLogEntry(
            session_key=session_key,
            event=event.value,
            node=data.get("node", ""),
            status="error" if "error" in data else "ok",
            duration_ms=data.get("duration_ms", 0.0),
            metadata={k: v for k, v in data.items() if k not in ("node", "duration_ms", "error")},
            run_id=run_id,
        )
        run_log.append(entry)

    return "run_log_writer", _log_event


# ---------------------------------------------------------------------------
# Stuck detection hook handler
# ---------------------------------------------------------------------------


def _make_stuck_hook_handler(
    detector: StuckDetectorPort,
) -> tuple[str, Any]:
    """Create hook handlers for stuck detection lifecycle."""

    def _track_lifecycle(event: HookEvent, data: dict[str, Any]) -> None:
        session_key = data.get("ip_name", "")
        if event == HookEvent.PIPELINE_START:
            detector.mark_running(session_key, metadata=data)
        elif event in (HookEvent.PIPELINE_END, HookEvent.PIPELINE_ERROR):
            detector.mark_completed(session_key)

    return "stuck_tracker", _track_lifecycle


# ---------------------------------------------------------------------------
# Default builders
# ---------------------------------------------------------------------------


def _build_default_policies() -> PolicyChainPort:
    """Build default PolicyChain with L1-2 profile/org + L3 mode-based restrictions."""
    from core.tools.policy import build_6layer_chain, load_org_policy, load_profile_policy

    profile = load_profile_policy()
    org = load_org_policy()
    mode_policies = [
        ToolPolicy(
            name="dry_run_block_llm",
            mode="dry_run",
            denied_tools={"run_analyst", "run_evaluator", "send_notification"},
            priority=100,
        ),
        ToolPolicy(
            name="full_block_notification",
            mode="full_pipeline",
            denied_tools={"send_notification"},
            priority=100,
        ),
    ]
    return build_6layer_chain(profile=profile, org=org, mode_policies=mode_policies)


def _build_default_registry() -> ToolRegistryPort:
    """Build ToolRegistry with all 21 tools registered."""
    registry = ToolRegistry()
    # Analysis (4)
    registry.register(RunAnalystTool())
    registry.register(RunEvaluatorTool())
    registry.register(PSMCalculateTool())
    registry.register(ExplainScoreTool())
    # Data (3)
    from core.tools.data_tools import CortexAnalystTool, CortexSearchTool, QueryMonoLakeTool

    registry.register(QueryMonoLakeTool())
    registry.register(CortexAnalystTool())
    registry.register(CortexSearchTool())
    # Signals (5)
    from core.tools.signal_tools import (
        GoogleTrendsTool,
        RedditSentimentTool,
        SteamInfoTool,
        TwitchStatsTool,
        WebSearchTool,
        YouTubeSearchTool,
    )

    registry.register(YouTubeSearchTool())
    registry.register(RedditSentimentTool())
    registry.register(TwitchStatsTool())
    registry.register(SteamInfoTool())
    registry.register(GoogleTrendsTool())
    registry.register(WebSearchTool())
    # Memory (7)
    from core.tools.memory_tools import (
        MemoryGetTool,
        MemorySaveTool,
        MemorySearchTool,
        RuleCreateTool,
        RuleDeleteTool,
        RuleListTool,
        RuleUpdateTool,
    )

    registry.register(MemorySearchTool())
    registry.register(MemoryGetTool())
    registry.register(MemorySaveTool())
    registry.register(RuleCreateTool())
    registry.register(RuleUpdateTool())
    registry.register(RuleDeleteTool())
    registry.register(RuleListTool())
    # Output (3)
    from core.tools.output_tools import ExportJsonTool, GenerateReportTool, SendNotificationTool

    registry.register(GenerateReportTool())
    registry.register(ExportJsonTool())
    registry.register(SendNotificationTool())
    # Meta-tool: tool_search (enables deferred loading)
    registry.register(ToolSearchTool(registry))
    return registry  # type: ignore[return-value]


def _build_default_lanes() -> LaneQueuePort:
    """Build default LaneQueue with session + global lanes."""
    queue = LaneQueue()
    queue.add_lane("session", max_concurrent=1)  # Serial per session
    queue.add_lane("global", max_concurrent=DEFAULT_GLOBAL_CONCURRENCY)
    return queue


# ---------------------------------------------------------------------------
# Tool executor factory
# ---------------------------------------------------------------------------


def _make_tool_executor(
    llm_adapter: LLMClientPort,
    registry: ToolRegistryPort,
    policy_chain: PolicyChainPort,
) -> Any:
    """Create a tool_fn callable that binds generate_with_tools to registry.

    Returns a callable with the same signature as LLMToolCallable:
        (system, user, *, tools, tool_executor, ...) -> ToolUseResult

    If no explicit tool_executor is provided, falls back to registry.execute
    with the default policy chain.
    """

    def _default_tool_executor(name: str, **kwargs: Any) -> dict[str, Any]:
        return registry.execute(name, policy=policy_chain, **kwargs)

    def _tool_fn(
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Any = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        executor = tool_executor or _default_tool_executor
        return llm_adapter.generate_with_tools(
            system,
            user,
            tools=tools,
            tool_executor=executor,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
        )

    return _tool_fn


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
        *,
        hooks: HookSystemPort,
        session_store: SessionStorePort,
        policy_chain: PolicyChainPort,
        tool_registry: ToolRegistryPort,
        run_log: RunLogPort,
        llm_adapter: LLMClientPort,
        secondary_adapter: LLMClientPort | None = None,
        profile_store: ProfileStorePort | None = None,
        profile_rotator: ProfileRotatorPort | None = None,
        cooldown_tracker: CooldownTrackerPort | None = None,
        coalescing: CoalescingQueuePort,
        config_watcher: ConfigWatcherPort,
        stuck_detector: StuckDetectorPort,
        lane_queue: LaneQueuePort,
        project_memory: ProjectMemoryPort,
        session_key: str,
        ip_name: str,
        # L4.5 Automation components
        drift_detector: DriftDetectorPort | None = None,
        model_registry: ModelRegistryPort | None = None,
        expert_panel: ExpertPanelPort | None = None,
        correlation_analyzer: CorrelationAnalyzerPort | None = None,
        outcome_tracker: OutcomeTrackerPort | None = None,
        snapshot_manager: SnapshotManagerPort | None = None,
        trigger_manager: TriggerManagerPort | None = None,
        scheduler_service: Any | None = None,
        feedback_loop: FeedbackLoopPort | None = None,
        # L2 Memory components
        organization_memory: OrganizationMemoryPort | None = None,
        context_assembler: ContextAssembler | None = None,
        # ADR-007: Prompt Assembly
        prompt_assembler: PromptAssembler | None = None,
    ) -> None:
        self.hooks = hooks
        self.session_store = session_store
        self.policy_chain = policy_chain
        self.tool_registry = tool_registry
        self.run_log = run_log
        self.llm_adapter = llm_adapter
        self.secondary_adapter = secondary_adapter
        self.profile_store = profile_store
        self.profile_rotator = profile_rotator
        self.cooldown_tracker = cooldown_tracker or CooldownTracker()
        self.coalescing = coalescing
        self.config_watcher = config_watcher
        self.stuck_detector = stuck_detector
        self.lane_queue = lane_queue
        self.project_memory = project_memory
        self.session_key = session_key
        self.ip_name = ip_name
        self.run_id = ""
        self.is_subagent: bool = False
        self._compiled_graph: CompiledStateGraph[Any, None, Any, Any] | None = None
        # L4.5 Automation
        self.drift_detector = drift_detector
        self.model_registry = model_registry
        self.expert_panel = expert_panel
        self.correlation_analyzer = correlation_analyzer
        self.outcome_tracker = outcome_tracker
        self.snapshot_manager = snapshot_manager
        self.trigger_manager = trigger_manager
        self.scheduler_service = scheduler_service
        self.feedback_loop = feedback_loop
        # L2 Memory
        self.organization_memory = organization_memory
        self.context_assembler = context_assembler
        # ADR-007: Prompt Assembly
        self.prompt_assembler: PromptAssembler | None = prompt_assembler
        # L4 Task tracking
        self.task_graph: TaskGraphPort | None = None
        self._task_bridge: TaskGraphHookBridge | None = None

    # ------------------------------------------------------------------
    # Sub-builders for create() decomposition
    # ------------------------------------------------------------------

    @staticmethod
    def _build_hooks(
        *,
        session_key: str,
        run_id: str,
        log_dir: Path | str | None,
        stuck_timeout_s: float,
    ) -> tuple[HookSystemPort, RunLogPort, StuckDetectorPort]:
        """Build HookSystem with RunLog and StuckDetector handlers."""
        hooks: HookSystemPort = HookSystem()  # type: ignore[assignment]

        # Run log + hook handler
        run_log = RunLog(session_key, log_dir=log_dir)
        handler_name, handler_fn = _make_run_log_handler(run_log, session_key, run_id)
        for event in HookEvent:
            hooks.register(event, handler_fn, name=handler_name, priority=50)

        # Stuck detector + hook handler
        stuck_detector = StuckDetector(timeout_s=stuck_timeout_s)
        stuck_name, stuck_fn = _make_stuck_hook_handler(stuck_detector)
        for event in (HookEvent.PIPELINE_START, HookEvent.PIPELINE_END, HookEvent.PIPELINE_ERROR):
            hooks.register(event, stuck_fn, name=stuck_name, priority=40)

        # Notification hook plugin (events → external messaging)
        try:
            from core.orchestration.plugins.notification_hook.hook import (
                register_notification_hooks,
            )

            register_notification_hooks(
                hooks,  # type: ignore[arg-type]
                channel=settings.notification_channel,
                recipient=settings.notification_recipient,
            )
        except Exception:
            log.debug("Notification hook registration skipped", exc_info=True)

        # C2: Journal auto-record hooks (PIPELINE_END → runs.jsonl, errors.jsonl)
        try:
            from core.memory.journal_hooks import make_journal_handlers
            from core.memory.project_journal import get_project_journal

            journal = get_project_journal()
            for handler_name, handler_fn in make_journal_handlers(journal):
                target_events = {
                    "journal_pipeline_end": [HookEvent.PIPELINE_END],
                    "journal_pipeline_error": [HookEvent.PIPELINE_ERROR],
                    "journal_subagent": [HookEvent.SUBAGENT_COMPLETED],
                }
                for evt in target_events.get(handler_name, []):
                    hooks.register(evt, handler_fn, name=handler_name, priority=60)
        except Exception:
            log.debug("Journal hook registration skipped", exc_info=True)

        return hooks, run_log, stuck_detector

    @staticmethod
    def _build_memory(
        *,
        session_store: SessionStorePort,
    ) -> tuple[ProjectMemory, MonoLakeOrganizationMemory, ContextAssembler, FileBasedUserProfile]:
        """Build L2 memory components: project, org, context assembler, user profile."""
        project_memory = ProjectMemory()

        org_dir = settings.organization_fixture_dir
        fixture_dir = Path(org_dir) if org_dir else None
        organization_memory = MonoLakeOrganizationMemory(fixture_dir=fixture_dir)

        # Tier 0.5: User Profile
        global_profile_dir = Path(settings.user_profile_dir) if settings.user_profile_dir else None
        project_profile_dir = Path(".geode") / "user_profile"
        user_profile = FileBasedUserProfile(
            global_dir=global_profile_dir,
            project_dir=project_profile_dir if project_profile_dir.parent.exists() else None,
        )

        # C2: Project Journal — append-only execution history
        from core.memory.project_journal import ProjectJournal

        project_journal = ProjectJournal()
        project_journal.ensure_structure()

        # V0: Vault — purpose-routed artifact storage
        from core.memory.vault import Vault

        vault = Vault()
        vault.ensure_structure()

        context_assembler = ContextAssembler(
            organization_memory=organization_memory,
            project_memory=project_memory,
            session_store=session_store,
            user_profile=user_profile,
            run_log_dir=DEFAULT_LOG_DIR,
            project_journal=project_journal,
            vault=vault,
            project_root=Path("."),
        )

        # Wire ContextAssembler into router node (L2 → L3 bridge)
        from core.nodes.router import set_context_assembler

        set_context_assembler(context_assembler)

        # Wire memory into memory tools via contextvars (P1 memory autonomy)
        from core.tools.memory_tools import set_org_memory, set_project_memory

        set_project_memory(project_memory)
        set_org_memory(organization_memory)

        # Wire user profile into profile tools via contextvars
        from core.tools.profile_tools import set_user_profile

        set_user_profile(user_profile)

        return project_memory, organization_memory, context_assembler, user_profile

    @staticmethod
    def _build_automation(
        *,
        hooks: HookSystemPort,
        session_key: str,
        ip_name: str,
        project_memory: ProjectMemoryPort | None = None,
    ) -> dict[str, Any]:
        """Build L4.5 automation components and wire hook event handlers.

        Returns a dict of component name → instance for passing to the constructor.
        """
        # Drift detector (CUSUM)
        drift_detector = CUSUMDetector()

        # Model registry (file-based)
        model_registry_dir = Path(settings.model_registry_dir)
        reg_dir = model_registry_dir if model_registry_dir.name != "" else None
        model_registry = ModelRegistry(storage_dir=reg_dir, hooks=hooks)

        # Expert panel
        expert_panel = ExpertPanel()

        # Correlation analyzer
        correlation_analyzer = CorrelationAnalyzer()

        # Outcome tracker
        outcome_tracker = OutcomeTracker(hooks=hooks)

        # Snapshot manager (with auto-GC)
        snapshot_dir = Path(settings.snapshot_dir) if settings.snapshot_dir else None
        snapshot_manager = SnapshotManager(
            storage_dir=snapshot_dir,
            max_recent=settings.snapshot_max_recent,
            hooks=hooks,
            auto_gc_threshold=settings.snapshot_gc_threshold,
        )

        # Trigger manager (auto-start scheduler for cron-based triggers)
        trigger_manager = TriggerManager(
            scheduler_interval_s=settings.trigger_scheduler_interval_s,
            hooks=hooks,
        )
        trigger_manager.start_scheduler()

        # Advanced scheduler service (3-type: AT/EVERY/CRON + active hours)
        import contextlib

        from core.automation.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        scheduler_service = SchedulerService(
            trigger_manager=trigger_manager,
            hooks=hooks,
        )
        scheduler_service.load()

        from core.automation.predefined import PREDEFINED_AUTOMATIONS

        for tmpl in PREDEFINED_AUTOMATIONS:
            if tmpl.enabled and not tmpl.schedule.startswith("event:"):
                job = ScheduledJob(
                    job_id=f"predefined:{tmpl.id}",
                    name=tmpl.name,
                    schedule=Schedule(
                        kind=ScheduleKind.CRON,
                        cron_expr=tmpl.schedule,
                    ),
                    enabled=tmpl.enabled,
                    metadata={
                        "source": "predefined",
                        "template_id": tmpl.id,
                    },
                )
                with contextlib.suppress(ValueError):
                    scheduler_service.add_job(job)

        if settings.scheduler_auto_start:
            scheduler_service.start(
                interval_s=settings.scheduler_interval_s,
            )

        # Feedback loop (wires all L4.5 components + hooks)
        feedback_loop = FeedbackLoop(
            model_registry=model_registry,
            expert_panel=expert_panel,
            correlation_analyzer=correlation_analyzer,
            drift_detector=drift_detector,
            hooks=hooks,
        )

        # --- Hook wiring for L4.5 events ---

        def _on_drift(event: HookEvent, data: dict[str, Any]) -> None:
            log.info("Drift detected: %s", data)

        hooks.register(HookEvent.DRIFT_DETECTED, _on_drift, name="drift_logger", priority=90)

        def _on_snapshot(event: HookEvent, data: dict[str, Any]) -> None:
            log.info("Snapshot captured: %s", data.get("snapshot_id", ""))

        hooks.register(
            HookEvent.SNAPSHOT_CAPTURED,
            _on_snapshot,
            name="snapshot_logger",
            priority=90,
        )

        def _on_trigger(event: HookEvent, data: dict[str, Any]) -> None:
            log.info("Trigger fired: %s", data.get("trigger_id", ""))

        hooks.register(HookEvent.TRIGGER_FIRED, _on_trigger, name="trigger_logger", priority=90)

        def _on_outcome(event: HookEvent, data: dict[str, Any]) -> None:
            log.info("Outcome collected: cycle=%s", data.get("cycle_id", ""))

        hooks.register(
            HookEvent.OUTCOME_COLLECTED,
            _on_outcome,
            name="outcome_logger",
            priority=90,
        )

        def _on_model_promoted(event: HookEvent, data: dict[str, Any]) -> None:
            log.info(
                "Model promoted: %s → %s",
                data.get("version_id", ""),
                data.get("stage", ""),
            )

        hooks.register(
            HookEvent.MODEL_PROMOTED,
            _on_model_promoted,
            name="model_promotion_logger",
            priority=90,
        )

        # Reactive chain: drift → auto-snapshot for debugging
        def _on_drift_snapshot(event: HookEvent, data: dict[str, Any]) -> None:
            if snapshot_manager:
                snapshot_manager.capture(
                    session_key,
                    pipeline_state={"trigger": "drift_detected", "alerts": data},
                    context={"ip_name": ip_name},
                )

        hooks.register(
            HookEvent.DRIFT_DETECTED,
            _on_drift_snapshot,
            name="drift_auto_snapshot",
            priority=80,
        )

        # Wire TriggerManager → pipeline integration
        trigger_manager.register_pipeline_trigger(
            trigger_id="drift-reanalysis",
            ip_name=ip_name,
            trigger_type=TriggerType.EVENT,
        )
        drift_trigger_handler = trigger_manager.make_event_handler("drift-reanalysis")
        hooks.register(
            HookEvent.DRIFT_DETECTED,
            drift_trigger_handler,
            name="drift_pipeline_trigger",
            priority=70,
        )

        # Reactive chain: pipeline end → auto-snapshot for reproducibility
        def _on_pipeline_end_snapshot(event: HookEvent, data: dict[str, Any]) -> None:
            if snapshot_manager:
                snapshot_manager.capture(
                    session_key,
                    pipeline_state=data,
                    context={"ip_name": ip_name},
                )

        hooks.register(
            HookEvent.PIPELINE_END,
            _on_pipeline_end_snapshot,
            name="pipeline_end_snapshot",
            priority=80,
        )

        # Memory write-back: pipeline end → add_insight to MEMORY.md (P0 auto-learning)
        def _on_pipeline_end_memory(event: HookEvent, data: dict[str, Any]) -> None:
            if project_memory is None:
                return
            if data.get("dry_run", False):
                return  # dry_run은 기록하지 않음
            ip = data.get("ip_name") or "unknown"
            tier = data.get("tier") or "?"
            score = data.get("final_score") or 0.0
            cause = data.get("synthesis_cause", "")
            action = data.get("synthesis_action", "")
            insight = f"[{ip}] tier={tier}, score={score:.2f}"
            if cause:
                insight += f", cause={cause}"
            if action:
                insight += f", action={action}"
            if not project_memory.add_insight(insight):
                log.warning("Failed to write insight for IP=%s", ip)

        hooks.register(
            HookEvent.PIPELINE_END,
            _on_pipeline_end_memory,
            name="memory_write_back",
            priority=85,
        )

        return {
            "drift_detector": drift_detector,
            "model_registry": model_registry,
            "expert_panel": expert_panel,
            "correlation_analyzer": correlation_analyzer,
            "outcome_tracker": outcome_tracker,
            "snapshot_manager": snapshot_manager,
            "trigger_manager": trigger_manager,
            "scheduler_service": scheduler_service,
            "feedback_loop": feedback_loop,
        }

    @staticmethod
    def _build_auth() -> tuple[ProfileStorePort, ProfileRotatorPort, CooldownTrackerPort]:
        """Build auth profile system with API key profiles."""
        from core.auth.profiles import AuthProfile, CredentialType

        profile_store = ProfileStore()
        if settings.anthropic_api_key:
            profile_store.add(
                AuthProfile(
                    name="anthropic:default",
                    provider="anthropic",
                    credential_type=CredentialType.API_KEY,
                    key=settings.anthropic_api_key,
                )
            )
        if settings.openai_api_key:
            profile_store.add(
                AuthProfile(
                    name="openai:default",
                    provider="openai",
                    credential_type=CredentialType.API_KEY,
                    key=settings.openai_api_key,
                )
            )
        profile_rotator = ProfileRotator(profile_store)
        cooldown_tracker = CooldownTracker()

        return profile_store, profile_rotator, cooldown_tracker

    @staticmethod
    def _build_prompt_assembler(
        *,
        hooks: HookSystemPort,
        skill_dirs: list[Path] | None = None,
    ) -> PromptAssembler:
        """Build PromptAssembler with SkillRegistry and hook integration (ADR-007)."""
        from core.llm.prompt_assembler import PromptAssembler
        from core.llm.skill_registry import SkillRegistry

        skill_registry = SkillRegistry(extra_dirs=skill_dirs or [])
        skill_registry.discover()
        return PromptAssembler(
            skill_registry=skill_registry,
            hooks=hooks,
        )

    @staticmethod
    def _build_task_graph(
        *,
        hooks: HookSystemPort,
        ip_name: str,
    ) -> tuple[TaskGraphPort, TaskGraphHookBridge]:
        """Build TaskGraph and wire the hook bridge for status tracking."""
        prefix = ip_name.lower().replace(" ", "_")
        graph = create_geode_task_graph(ip_name)
        bridge = TaskGraphHookBridge(graph, ip_prefix=prefix)
        bridge.register(hooks)
        return graph, bridge

    @staticmethod
    def _build_signal_adapter() -> None:
        """Build and inject CompositeSignalAdapter with MCP-backed signal sources.

        Chains Steam MCP + Brave MCP adapters into CompositeSignalAdapter,
        then injects into signals_node via contextvars. If no MCP servers
        are configured or available, the adapter will report is_available()=False
        and signals_node falls back to fixtures.
        """
        from core.infrastructure.adapters.mcp.brave_adapter import (
            BraveSearchAdapter,
            BraveSignalAdapter,
        )
        from core.infrastructure.adapters.mcp.composite_signal import CompositeSignalAdapter
        from core.infrastructure.adapters.mcp.manager import get_mcp_manager
        from core.infrastructure.adapters.mcp.steam_adapter import SteamMCPSignalAdapter
        from core.nodes.signals import set_signal_adapter

        manager = get_mcp_manager()
        server_count = manager.load_config()

        if server_count == 0:
            log.debug("No MCP servers configured — signal adapter skipped (fixture fallback)")
            set_signal_adapter(None)
            return

        # Build individual MCP signal adapters
        adapters: list[SteamMCPSignalAdapter | BraveSignalAdapter] = []

        steam_adapter = SteamMCPSignalAdapter(manager=manager, server_name="steam")
        adapters.append(steam_adapter)

        brave_search = BraveSearchAdapter(manager=manager, server_name="brave-search")
        brave_signal = BraveSignalAdapter(brave_search)
        adapters.append(brave_signal)

        composite = CompositeSignalAdapter(adapters)  # type: ignore[arg-type]

        if composite.is_available():
            log.info(
                "Signal liveification enabled: %d MCP adapters wired",
                len(adapters),
            )
        else:
            log.debug("MCP servers configured but none available — fixture fallback active")

        set_signal_adapter(composite)

    @staticmethod
    def _build_notification_adapter() -> None:
        """Build and inject CompositeNotificationAdapter with MCP-backed channels.

        Chains Slack + Discord + Telegram adapters. If no messaging MCP servers
        are available, notification tools fall back to stub responses.
        """
        from core.infrastructure.adapters.mcp.composite_notification import (
            CompositeNotificationAdapter,
        )
        from core.infrastructure.adapters.mcp.discord_adapter import DiscordNotificationAdapter
        from core.infrastructure.adapters.mcp.manager import get_mcp_manager
        from core.infrastructure.adapters.mcp.slack_adapter import SlackNotificationAdapter
        from core.infrastructure.adapters.mcp.telegram_adapter import TelegramNotificationAdapter
        from core.infrastructure.ports.notification_port import set_notification

        try:
            manager = get_mcp_manager()
            manager.load_config()
        except Exception:
            log.debug("MCPServerManager unavailable — notification adapter skipped")
            set_notification(None)
            return

        adapters = [
            SlackNotificationAdapter(manager=manager),
            DiscordNotificationAdapter(manager=manager),
            TelegramNotificationAdapter(manager=manager),
        ]

        composite = CompositeNotificationAdapter(adapters)  # type: ignore[arg-type]

        if composite.is_available():
            log.info(
                "Notification adapter enabled: channels=%s",
                composite.list_channels(),
            )
        else:
            log.debug("No messaging MCP servers available — stub notification mode")

        set_notification(composite)

    @staticmethod
    def _build_calendar_adapter() -> None:
        """Build and inject CompositeCalendarAdapter with MCP-backed sources.

        Chains Google Calendar + CalDAV (Apple Calendar) adapters.
        If no calendar MCP servers are available, calendar tools return empty.
        """
        from core.infrastructure.adapters.mcp.apple_calendar_adapter import (
            AppleCalendarAdapter,
        )
        from core.infrastructure.adapters.mcp.composite_calendar import (
            CompositeCalendarAdapter,
        )
        from core.infrastructure.adapters.mcp.google_calendar_adapter import (
            GoogleCalendarAdapter,
        )
        from core.infrastructure.adapters.mcp.manager import get_mcp_manager
        from core.infrastructure.ports.calendar_port import set_calendar

        try:
            manager = get_mcp_manager()
            manager.load_config()
        except Exception:
            log.debug("MCPServerManager unavailable — calendar adapter skipped")
            set_calendar(None)
            return

        adapters = [
            GoogleCalendarAdapter(manager=manager),
            AppleCalendarAdapter(manager=manager),
        ]

        composite = CompositeCalendarAdapter(adapters)  # type: ignore[arg-type]

        if composite.is_available():
            log.info(
                "Calendar adapter enabled: sources=%s",
                composite.list_sources(),
            )
        else:
            log.debug("No calendar MCP servers available — calendar tools disabled")

        set_calendar(composite)

    @staticmethod
    def _build_gateway() -> None:
        """Build and inject Gateway with channel pollers.

        Creates ChannelManager with Slack/Discord/Telegram pollers.
        Pollers only start if their credentials are configured and
        gateway_enabled=True in settings.
        """
        from core.config import settings
        from core.gateway.channel_manager import ChannelManager
        from core.gateway.pollers.discord_poller import DiscordPoller
        from core.gateway.pollers.slack_poller import SlackPoller
        from core.gateway.pollers.telegram_poller import TelegramPoller
        from core.infrastructure.ports.gateway_port import set_gateway
        from core.infrastructure.ports.notification_port import get_notification

        if not settings.gateway_enabled:
            log.debug("Gateway disabled (GEODE_GATEWAY_ENABLED=false)")
            set_gateway(None)
            return

        # Wire Lane Queue for gateway concurrency control
        lane_queue = None
        try:
            from core.orchestration.lane_queue import LaneQueue

            lane_queue = LaneQueue()
            lane_queue.add_lane("gateway", max_concurrent=2, timeout_s=120.0)
        except Exception:
            log.debug("LaneQueue unavailable — gateway runs without concurrency control")

        manager = ChannelManager(lane_queue=lane_queue)
        notification = get_notification()
        poll_interval = settings.gateway_poll_interval_s

        # Load bindings from TOML config (hot-reloadable)
        try:
            import tomllib
            from pathlib import Path

            config_path = Path(".geode") / "config.toml"
            if config_path.exists():
                with open(config_path, "rb") as f:
                    toml_config = tomllib.load(f)
                manager.load_bindings_from_config(toml_config)
        except Exception:
            log.debug("No gateway bindings in config.toml")

        try:
            from core.infrastructure.adapters.mcp.manager import get_mcp_manager

            mcp = get_mcp_manager(auto_startup=True)
            log.info("Gateway MCP: %d/%d servers connected", len(mcp._clients), len(mcp._servers))
        except Exception:
            log.debug("MCPServerManager unavailable — gateway skipped")
            set_gateway(None)
            return

        manager.register_poller(
            SlackPoller(
                manager,
                mcp_manager=mcp,
                notification=notification,
                poll_interval_s=poll_interval,
            )
        )
        manager.register_poller(
            DiscordPoller(
                manager,
                mcp_manager=mcp,
                notification=notification,
                poll_interval_s=poll_interval,
            )
        )
        manager.register_poller(
            TelegramPoller(
                manager,
                mcp_manager=mcp,
                notification=notification,
                poll_interval_s=poll_interval,
            )
        )

        set_gateway(manager)
        log.info("Gateway built with %d pollers", len(manager._pollers))

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

        Composed from sub-builders:
        - _build_hooks(): HookSystem, RunLog, StuckDetector
        - _build_auth(): ProfileStore, ProfileRotator, CooldownTracker
        - _build_memory(): ProjectMemory, OrganizationMemory, ContextAssembler, UserProfile
        - _build_automation(): Drift, ModelRegistry, ExpertPanel, etc.
        """
        # Domain adapter (Phase 4 — wire before anything that reads domain config)
        domain = load_domain_adapter(domain_name)
        set_domain(domain)

        # Session key + run ID
        session_key = build_session_key(ip_name, phase)
        run_id = uuid.uuid4().hex[:12]

        # Hooks subsystem
        hooks, run_log, stuck_detector = cls._build_hooks(
            session_key=session_key,
            run_id=run_id,
            log_dir=log_dir,
            stuck_timeout_s=stuck_timeout_s,
        )

        # Session store (with optional file-backed persistence)
        session_storage_dir: Path | None = None
        if settings.session_storage_dir:
            session_storage_dir = Path(settings.session_storage_dir)
        session_store: SessionStorePort = InMemorySessionStore(
            ttl=session_ttl,
            storage_dir=session_storage_dir,
        )

        # Wire HybridSessionStore if redis/postgres URLs configured
        if settings.redis_url or settings.postgres_url:
            from core.memory.hybrid_session import (
                HybridSessionStore,
                PostgreSQLSessionStore,
                RedisSessionStore,
            )

            l1 = RedisSessionStore(ttl_hours=settings.session_ttl_hours)
            pg_path = settings.postgres_url or ".geode/sessions"
            pg_dir = Path(pg_path)
            l2 = PostgreSQLSessionStore(storage_dir=pg_dir)
            session_store = HybridSessionStore(l1=l1, l2=l2)

        # Policy chain + Tool registry
        policy_chain = _build_default_policies()
        tool_registry = _build_default_registry()

        # Auth subsystem
        profile_store, profile_rotator, cooldown_tracker = cls._build_auth()

        # LLM adapters (Clean Architecture port/adapter)
        llm_adapter: LLMClientPort = ClaudeAdapter()
        secondary_adapter: LLMClientPort | None = None
        if settings.openai_api_key:
            secondary_adapter = OpenAIAdapter()

        # Inject LLM callables so node modules can resolve via contextvars
        # Use the adapter's port methods (not raw functions) for proper DI
        from core.infrastructure.ports.llm_port import set_llm_callable

        # Build tool executor bound to registry + policy chain
        tool_fn = _make_tool_executor(llm_adapter, tool_registry, policy_chain)

        set_llm_callable(
            llm_adapter.generate_structured,
            llm_adapter.generate,
            parsed_fn=llm_adapter.generate_parsed,
            tool_fn=tool_fn,
            secondary_json_fn=(
                secondary_adapter.generate_structured if secondary_adapter else None
            ),
            secondary_parsed_fn=(secondary_adapter.generate_parsed if secondary_adapter else None),
        )

        # Coalescing queue (250ms debounce)
        coalescing = CoalescingQueue(window_ms=250.0)

        # Config watcher (300ms debounce, 1s poll)
        config_watcher = ConfigWatcher(debounce_ms=300.0)

        # Wire ConfigWatcher to watch .env if it exists
        env_path = Path(".env")
        if env_path.exists():

            def _on_config_change(path: Path, mtime: float) -> None:
                log.info("Config file changed: %s — reloading settings", path)
                from core.config import Settings

                new_settings = Settings()

                # Validate constraints before applying
                if new_settings.drift_warning_threshold <= 0:
                    log.warning("Invalid drift_warning_threshold; skipping reload")
                    return
                if new_settings.drift_critical_threshold <= new_settings.drift_warning_threshold:
                    log.warning("drift_critical_threshold must exceed warning; skipping")
                    return
                if new_settings.session_ttl_hours <= 0:
                    log.warning("Invalid session_ttl_hours; skipping reload")
                    return
                if new_settings.trigger_scheduler_interval_s <= 0:
                    log.warning("Invalid trigger_scheduler_interval_s; skipping reload")
                    return

                # Core settings
                settings.model = new_settings.model
                settings.verbose = new_settings.verbose

                # L4.5 Drift Detection
                settings.drift_scan_cron = new_settings.drift_scan_cron
                settings.drift_warning_threshold = new_settings.drift_warning_threshold
                settings.drift_critical_threshold = new_settings.drift_critical_threshold

                # L4.5 Outcome Tracking
                settings.outcome_tracking_enabled = new_settings.outcome_tracking_enabled

                # L4.5 Snapshot Manager
                settings.snapshot_dir = new_settings.snapshot_dir
                settings.snapshot_max_recent = new_settings.snapshot_max_recent

                # L4.5 Trigger Manager
                settings.trigger_scheduler_interval_s = new_settings.trigger_scheduler_interval_s

                # L4.5 Model Registry
                settings.model_registry_dir = new_settings.model_registry_dir

                # L2 Memory
                settings.session_ttl_hours = new_settings.session_ttl_hours

                log.info("Settings hot-reload complete (12 fields updated)")

            config_watcher.watch(env_path, _on_config_change, name="dotenv")
            config_watcher.start()

        # Lane queue (session serial + global concurrency)
        lane_queue = _build_default_lanes()

        # Signal enrichment via MCP (liveification)
        cls._build_signal_adapter()

        # Notification adapters (Slack/Discord/Telegram)
        cls._build_notification_adapter()

        # Calendar adapters (Google Calendar / CalDAV)
        cls._build_calendar_adapter()

        # Gateway (inbound messaging pollers)
        cls._build_gateway()

        # Calendar ↔ Scheduler bridge
        try:
            from core.infrastructure.ports.calendar_port import get_calendar
            from core.orchestration.calendar_bridge import set_calendar_bridge

            cal = get_calendar()
            if cal is not None and cal.is_available():
                # Scheduler is wired later in REPL; bridge also wired in REPL
                # Here we just set up the port dependency
                log.debug("Calendar adapter available — bridge will wire in REPL")
            else:
                set_calendar_bridge(None)
        except Exception:
            log.debug("Calendar bridge setup skipped", exc_info=True)

        # Memory subsystem
        project_memory, organization_memory, context_assembler, user_profile = cls._build_memory(
            session_store=session_store,
        )

        # Automation subsystem (L4.5)
        automation = cls._build_automation(
            hooks=hooks,
            session_key=session_key,
            ip_name=ip_name,
            project_memory=project_memory,
        )

        # Prompt assembler (ADR-007)
        try:
            prompt_assembler = cls._build_prompt_assembler(hooks=hooks)
        except ImportError:
            log.debug("ADR-007 prompt_assembler/skill_registry not yet available — skipping")
            prompt_assembler = None

        # Task graph (L4 observer)
        task_graph, task_bridge = cls._build_task_graph(hooks=hooks, ip_name=ip_name)

        log.info(
            "GeodeRuntime created: ip=%s, key=%s, tools=%d, lanes=%s",
            ip_name,
            session_key,
            len(tool_registry),
            lane_queue.list_lanes(),
        )

        instance = cls(
            hooks=hooks,
            session_store=session_store,
            policy_chain=policy_chain,
            tool_registry=tool_registry,
            run_log=run_log,
            llm_adapter=llm_adapter,
            secondary_adapter=secondary_adapter,
            profile_store=profile_store,
            profile_rotator=profile_rotator,
            cooldown_tracker=cooldown_tracker,
            coalescing=coalescing,
            config_watcher=config_watcher,
            stuck_detector=stuck_detector,
            lane_queue=lane_queue,
            project_memory=project_memory,
            session_key=session_key,
            ip_name=ip_name,
            organization_memory=organization_memory,
            context_assembler=context_assembler,
            prompt_assembler=prompt_assembler,
            **automation,
        )
        instance.run_id = run_id
        instance.task_graph = task_graph
        instance._task_bridge = task_bridge
        return instance

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
        """Assemble full 3-tier context (Org → Project → Session)."""
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
        if self._task_bridge is not None:
            self._task_bridge.unregister()
        graph, bridge = self._build_task_graph(hooks=self.hooks, ip_name=self.ip_name)
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
        from core.infrastructure.ports.tool_port import set_tool_executor

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

        Returns a dict of component_name → stats_dict for dashboarding.
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
        health["coalescing_pending"] = self.coalescing.pending_count
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
        self.coalescing.cancel_all()
        self.config_watcher.stop()
        self.stuck_detector.stop_monitor()
        if self.scheduler_service:
            self.scheduler_service.save()
            self.scheduler_service.stop()
        if self.trigger_manager:
            self.trigger_manager.stop_scheduler()
        if self._task_bridge:
            self._task_bridge.unregister()
