"""Bootstrap wiring — hooks, memory, session, config_watcher, task, prompt, plugin registry.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.prompt_assembler import PromptAssembler

from core.config import settings
from core.hooks import HookEvent, HookSystem
from core.memory.context import ContextAssembler
from core.memory.organization import MonoLakeOrganizationMemory
from core.memory.port import SessionStorePort
from core.memory.project import ProjectMemory
from core.memory.session import InMemorySessionStore
from core.memory.user_profile import FileBasedUserProfile
from core.orchestration.hot_reload import ConfigWatcher
from core.orchestration.run_log import RunLog, RunLogEntry
from core.orchestration.stuck_detection import StuckDetector
from core.orchestration.task_bridge import TaskGraphHookBridge
from core.orchestration.task_system import TaskGraph, create_geode_task_graph

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration (re-exported from runtime.py constants)
# ---------------------------------------------------------------------------
DEFAULT_LOG_DIR = Path.home() / ".geode" / "runs"
CONFIG_WATCHER_DEBOUNCE_MS = 300.0  # Avoid thrashing on rapid file changes

# ---------------------------------------------------------------------------
# RunLog hook handler — bridges HookSystem events -> JSONL log
# ---------------------------------------------------------------------------


def _make_run_log_handler(
    run_log: RunLog,
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
    detector: StuckDetector,
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
# Plugin registration helper (DRY: replaces 8 bare except blocks)
# ---------------------------------------------------------------------------

_plugin_status: dict[str, str] = {}


def _register_plugin(name: str, fn: Any, *args: Any, **kwargs: Any) -> bool:
    """Call *fn* and record plugin status. Returns True on success.

    Replaces repeated try/except Exception patterns with structured logging:
    - ImportError  -> warning (module not installed)
    - ValueError   -> warning (config invalid)
    - Other        -> error with traceback
    """
    try:
        fn(*args, **kwargs)
        _plugin_status[name] = "enabled"
        log.info("Plugin %s: enabled", name)
        return True
    except ImportError as exc:
        _plugin_status[name] = "unavailable"
        log.warning("Plugin %s: module not available (%s)", name, exc)
    except ValueError as exc:
        _plugin_status[name] = "config_error"
        log.warning("Plugin %s: config invalid (%s)", name, exc)
    except Exception as exc:
        _plugin_status[name] = "error"
        log.error("Plugin %s: failed (%s)", name, exc, exc_info=True)
    return False


def get_plugin_status() -> dict[str, str]:
    """Return plugin registration status dict for CLI reporting."""
    return _plugin_status.copy()


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------


def build_hooks(
    *,
    session_key: str,
    run_id: str,
    log_dir: Path | str | None,
    stuck_timeout_s: float,
) -> tuple[HookSystem, RunLog, StuckDetector]:
    """Build HookSystem with RunLog and StuckDetector handlers."""
    hooks: HookSystem = HookSystem()

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

    # Context overflow action handler (CONTEXT_OVERFLOW_ACTION -> strategy recommendation)
    def _reg_context_action() -> None:
        from core.hooks.context_action import make_context_action_handler

        handler_name, handler_fn = make_context_action_handler()
        hooks.register(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            handler_fn,
            name=handler_name,
            priority=50,
        )

    _register_plugin("context_action_hook", _reg_context_action)

    # Notification hook plugin (events -> external messaging)
    def _reg_notification() -> None:
        from core.hooks.plugins.notification_hook.hook import (
            register_notification_hooks,
        )

        register_notification_hooks(
            hooks,
            channel=settings.notification_channel,
            recipient=settings.notification_recipient,
        )

    _register_plugin("notification_hook", _reg_notification)

    # C2: Journal auto-record hooks (PIPELINE_END -> runs.jsonl, errors.jsonl)
    def _reg_journal() -> None:
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

    _register_plugin("journal_hook", _reg_journal)

    # C3: Auto-memory on turn complete (OpenClaw command:new pattern)
    def _reg_turn_memory() -> None:
        from core.tools import memory_tools

        def _on_turn_complete(event: HookEvent, data: dict[str, Any]) -> None:
            pm = memory_tools._project_memory_ctx.get()
            if pm is None:
                return
            text = data.get("text", "")
            user_input = data.get("user_input", "")
            tools = data.get("tool_calls", [])
            if not text or len(text) < 20:
                return  # too short to be useful
            # Build concise insight from turn
            tool_str = ", ".join(tools[:5]) if tools else "none"
            insight = f"[turn] {user_input[:80]} → tools=[{tool_str}]"
            pm.add_insight(insight)

        hooks.register(
            HookEvent.TURN_COMPLETE,
            _on_turn_complete,
            name="turn_auto_memory",
            priority=85,
        )

    _register_plugin("turn_memory_hook", _reg_turn_memory)

    # C4: Session lifecycle hooks (OpenClaw agent:bootstrap pattern)
    def _reg_session_lifecycle() -> None:
        def _on_session_start(event: HookEvent, data: dict[str, Any]) -> None:
            log.info(
                "Session started: model=%s resumed=%s",
                data.get("model"),
                data.get("resumed"),
            )

        def _on_session_end(event: HookEvent, data: dict[str, Any]) -> None:
            log.info("Session ended: model=%s", data.get("model"))

        hooks.register(
            HookEvent.SESSION_START,
            _on_session_start,
            name="session_start_logger",
            priority=90,
        )
        hooks.register(
            HookEvent.SESSION_END,
            _on_session_end,
            name="session_end_logger",
            priority=90,
        )

    _register_plugin("session_lifecycle_hook", _reg_session_lifecycle)

    # C4b: Model switch logging (L1 Observe)
    hooks.register(
        HookEvent.MODEL_SWITCHED,
        lambda e, d: log.info("Model switched: %s → %s", d.get("from_model"), d.get("to_model")),
        name="model_switch_logger",
        priority=90,
    )

    # C5: LLM call lifecycle hooks (LLM_CALL_START/END -> slow call logging + journal cost)
    def _reg_llm_lifecycle() -> None:
        from core.llm.router import set_router_hooks

        # Session-level LLM call statistics accumulator
        _llm_stats: dict[str, Any] = {
            "total_calls": 0,
            "total_errors": 0,
            "total_latency_ms": 0.0,
            "by_model": {},  # model -> {"calls": int, "total_latency_ms": float}
        }

        def _on_llm_end(event: HookEvent, data: dict[str, Any]) -> None:
            latency = data.get("latency_ms", 0.0)
            model = data.get("model", "?")
            error = data.get("error")

            # Accumulate session stats
            _llm_stats["total_calls"] += 1
            _llm_stats["total_latency_ms"] += latency
            if error:
                _llm_stats["total_errors"] += 1
            model_stats = _llm_stats["by_model"].setdefault(
                model, {"calls": 0, "total_latency_ms": 0.0}
            )
            model_stats["calls"] += 1
            model_stats["total_latency_ms"] += latency

            # Slow call / error logging
            if error:
                log.warning(
                    "LLM call failed: model=%s error=%s latency=%dms",
                    model,
                    error,
                    int(latency),
                )
            elif latency > 10_000:  # > 10s
                log.warning(
                    "LLM call slow: model=%s latency=%dms",
                    model,
                    int(latency),
                )

        hooks.register(
            HookEvent.LLM_CALL_END,
            _on_llm_end,
            name="llm_slow_logger",
            priority=55,
        )

        # Wire hooks into the LLM router module
        set_router_hooks(hooks)

    _register_plugin("llm_lifecycle_hook", _reg_llm_lifecycle)

    # C6: Tool approval tracking hooks (HITL pattern learning → JSONL)
    def _reg_tool_approval() -> None:
        from core.hooks.approval_tracker import ApprovalTracker

        tracker = ApprovalTracker()
        handler_name, handler_fn = tracker.make_hook_handler(session_key=session_key)
        hooks.register(
            HookEvent.TOOL_APPROVAL_GRANTED,
            handler_fn,
            name=handler_name,
            priority=65,
        )
        hooks.register(
            HookEvent.TOOL_APPROVAL_DENIED,
            handler_fn,
            name=f"{handler_name}_denied",
            priority=65,
        )

    _register_plugin("tool_approval_hook", _reg_tool_approval)

    # C8: Filesystem hook plugin auto-discovery (.geode/hooks/ + core/hooks/plugins/)
    def _reg_filesystem_plugins() -> None:
        from core.hooks.discovery import HookPluginLoader

        loader = HookPluginLoader()
        plugin_dirs = [Path(".geode/hooks"), Path("core/hooks/plugins")]
        loader.load_from_dirs(plugin_dirs)
        loader.register_all(hooks)

    _register_plugin("filesystem_hook_plugins", _reg_filesystem_plugins)

    return hooks, run_log, stuck_detector


def build_memory(
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

    # Wire ContextAssembler into router node (L2 -> L3 bridge)
    from core.domains.game_ip.nodes.router import set_context_assembler

    set_context_assembler(context_assembler)

    # Wire memory into memory tools via contextvars (P1 memory autonomy)
    from core.tools.memory_tools import set_org_memory, set_project_memory

    set_project_memory(project_memory)
    set_org_memory(organization_memory)

    # Wire user profile into profile tools via contextvars
    from core.tools.profile_tools import set_user_profile

    set_user_profile(user_profile)

    return project_memory, organization_memory, context_assembler, user_profile


def build_session_store(*, session_ttl: float) -> SessionStorePort:
    """Build session store — InMemory default, HybridSessionStore if URLs configured."""
    session_storage_dir: Path | None = None
    if settings.session_storage_dir:
        session_storage_dir = Path(settings.session_storage_dir)
    session_store: SessionStorePort = InMemorySessionStore(
        ttl=session_ttl,
        storage_dir=session_storage_dir,
    )
    if settings.redis_url or settings.postgres_url:
        from core.memory.hybrid_session import (
            HybridSessionStore,
            PostgreSQLSessionStore,
            RedisSessionStore,
        )

        l1 = RedisSessionStore(ttl_hours=settings.session_ttl_hours)
        pg_path = settings.postgres_url or ".geode/sessions"
        l2 = PostgreSQLSessionStore(storage_dir=Path(pg_path))
        session_store = HybridSessionStore(l1=l1, l2=l2)
    return session_store


def build_config_watcher() -> ConfigWatcher:
    """Build ConfigWatcher and register .env hot-reload handler if .env exists."""
    config_watcher = ConfigWatcher(debounce_ms=CONFIG_WATCHER_DEBOUNCE_MS)
    env_path = Path(".env")
    if not env_path.exists():
        return config_watcher

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
        # NOTE: settings.model is intentionally NOT reloaded here.
        # Model switching is user-facing state managed by /model command
        # and switch_model tool. Hot-reloading it from .env would revert
        # user's in-session model choice (os.environ stale vs .env fresh).
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
    return config_watcher


def build_task_graph(
    *,
    hooks: HookSystem,
    ip_name: str,
) -> tuple[TaskGraph, TaskGraphHookBridge]:
    """Build TaskGraph and wire the hook bridge for status tracking."""
    prefix = ip_name.lower().replace(" ", "_")
    graph = create_geode_task_graph(ip_name)
    bridge = TaskGraphHookBridge(graph, ip_prefix=prefix)
    bridge.register(hooks)
    return graph, bridge


def build_prompt_assembler(
    *,
    hooks: HookSystem,
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


# ---------------------------------------------------------------------------
# Unified bootstrap: MCP, Skills, Readiness (moved from cli/bootstrap.py)
# ---------------------------------------------------------------------------


def build_mcp_manager() -> Any:
    """Load MCP server config (lazy — no subprocess connections yet)."""
    from core.mcp.manager import get_mcp_manager

    mgr = get_mcp_manager()
    mgr.load_config()
    return mgr


def build_skill_registry() -> Any:
    """Load all skill definitions from 4-tier priority directories."""
    from core.skills.skills import SkillLoader, SkillRegistry

    registry = SkillRegistry()
    try:
        SkillLoader().load_all(registry=registry)
    except Exception:
        log.debug("Skill loading skipped", exc_info=True)
    return registry


def build_readiness() -> Any:
    """Check API key availability for all configured providers."""
    from core.cli.startup import check_readiness

    return check_readiness()
