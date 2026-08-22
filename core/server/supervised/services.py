"""SharedServices — single factory for all session modes.

Owns process-level singletons (MCP, skills, hooks, tool handlers).
Each entry point (REPL, daemon, scheduler, fork) calls ``create_session()``
with a ``SessionMode`` to get identically-wired ``(ToolExecutor, AgenticLoop)``.

Inspired by:
- Codex CLI ``ThreadManagerState`` + ``SessionServices`` (two-tier ownership)
- OpenClaw Gateway (single owner, all paths converge)
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from core.agent.safety import (
    COMPUTER_USE_TOOLS,
    HEADLESS_DENIED_TOOLS,
    residual_denied_tools,
)
from core.agent.safety import (
    headless_denied_tools as plan_headless_denied_tools,
)

if TYPE_CHECKING:
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.agent.tool_executor.executor import ResourceLockPool
    from core.config.policy_source import PolicySourceBundle
    from core.observability.run_event import RunEventSinkProvider
    from core.tools.plan import BoundToolPlan, ToolPlan

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session mode enum
# ---------------------------------------------------------------------------


class SessionMode(StrEnum):
    """Execution mode — determines behavior defaults, not shared resources."""

    REPL = "repl"  # Interactive terminal — hitl=2, verbose=user, time=unlimited
    IPC = "ipc"  # Thin CLI via Unix socket — hitl=0, WRITE ok, DANGEROUS blocked
    DAEMON = "daemon"  # Messaging receivers — hitl=0, quiet, time=config
    SCHEDULER = "scheduler"  # Cron/scheduled jobs — hitl=0, quiet, time=300s cap


def _headless_denied_tools_for_mode(
    mode: SessionMode,
    *,
    gateway_allow_computer_use: bool,
    bound_tool_plan: BoundToolPlan | None = None,
) -> frozenset[str]:
    """Resolve the enforced denylist for one session mode.

    Messaging may expose the same desktop-control handlers as the interactive
    CLI, but only through a dedicated fail-closed operator opt-in. Scheduled
    jobs and MCP ``run_agent`` have no equivalent trusted conversation
    boundary and retain the canonical denylist.
    """
    if mode not in (SessionMode.SCHEDULER, SessionMode.DAEMON):
        return frozenset()
    residual = HEADLESS_DENIED_TOOLS
    if mode == SessionMode.DAEMON and gateway_allow_computer_use is True:
        residual -= COMPUTER_USE_TOOLS
    if bound_tool_plan is None:
        return residual
    native_denied = plan_headless_denied_tools(bound_tool_plan)
    if not (mode == SessionMode.DAEMON and gateway_allow_computer_use is True):
        native_denied |= COMPUTER_USE_TOOLS & set(bound_tool_plan.tool_names)
    return native_denied | residual_denied_tools(
        residual,
        bound_tool_plan,
    )


# ---------------------------------------------------------------------------
# Mode-specific defaults (no max_rounds — time only)
# ---------------------------------------------------------------------------

_MODE_DEFAULTS: dict[SessionMode, dict[str, Any]] = {
    SessionMode.REPL: {
        "hitl_level": 2,
        "quiet": False,
        "time_budget_s": 0.0,  # unlimited (interactive)
        "max_rounds": 0,  # unlimited
    },
    SessionMode.IPC: {
        "hitl_level": 2,  # full HITL — approval relayed to thin CLI via IPC
        "quiet": True,  # suppress serve-side UI; results sent via IPC JSON
        "time_budget_s": 0.0,  # unlimited (interactive via IPC)
        "max_rounds": 0,
    },
    SessionMode.DAEMON: {
        "hitl_level": 0,
        "quiet": True,
        "time_budget_s": 120.0,  # matches gateway_time_budget_s default
        "max_rounds": 0,
    },
    SessionMode.SCHEDULER: {
        "hitl_level": 0,
        "quiet": True,
        "time_budget_s": 300.0,  # 5 min cap
        "max_rounds": 0,
    },
}


# ---------------------------------------------------------------------------
# SharedServices
# ---------------------------------------------------------------------------


@dataclass
class SharedServices:
    """Process-level singleton owning all shared resources.

    Constructed once at bootstrap time.  Every ``create_session()`` call
    returns a fully-wired ``(ToolExecutor, AgenticLoop)`` pair that
    automatically receives hooks, MCP, skills, cost budget, and time budget.

    Session objects are independent. The process-owned resource lock pool is
    shared deliberately so two sessions cannot mutate the same declared
    resource concurrently. Tool handlers that need the current loop read from
    ``_current_loop_ctx`` ContextVar (per-thread, no race condition).
    """

    mcp_manager: Any = None
    skill_registry: Any = None
    hook_system: Any = None  # HookSystem — never None after init
    hook_registry: Any = None  # process-owned public HookRegistry
    middleware_registry: Any = None  # process-owned trusted MiddlewareRegistry
    policy_sources: PolicySourceBundle | None = None
    activity_sink_provider: RunEventSinkProvider | None = None
    _owns_hook_system: bool = False
    lane_queue: Any = None  # Unified LaneQueue — single concurrency gate
    command_registry: Any = None  # composed slash-command routing contract
    tool_handlers: Mapping[str, Any] = field(default_factory=dict)
    bound_tool_plan: BoundToolPlan | None = None
    transient_tool_handlers: Mapping[str, Any] = field(default_factory=dict)
    resource_lock_pool: ResourceLockPool | None = None
    worker_module: str | None = None
    agent_search_dirs: tuple[Path, ...] = ()
    control_state_factories: Mapping[str, Callable[[Path], Any]] = field(default_factory=dict)

    # v0.82.0 — Model + provider resolved fresh per session, NOT frozen at
    # bootstrap. The previous shape (`_model: str = ""` cached at
    # `SharedServices.create()` from `_settings.model`) caused a critical
    # user-facing bug: a long-running daemon would honour `/model gpt-5.5`
    # in `cmd_model` (mutates `settings.model` + .env), but every new
    # IPC session still received the boot-time model via `self._model`.
    # User saw "Already using GPT-5.5" in the prompt header but every
    # LLM call still routed to `claude-opus-4-7` — silently using a
    # different provider (paid Anthropic API instead of OAuth-borrowed
    # Codex subscription). `create_session()` now reads `settings.model` directly
    # so each session reflects the latest user intent.
    _cost_budget: float = 0.0

    # --- public API -----------------------------------------------------------

    def __post_init__(self) -> None:
        """Ensure directly-constructed services still own one registry pair."""
        from core.agent.tool_executor.executor import ResourceLockPool
        from core.config.policy_source import EMPTY_POLICY_SOURCES
        from core.hooks import HookRegistry, MiddlewareRegistry

        if self.policy_sources is None:
            self.policy_sources = EMPTY_POLICY_SOURCES
        if self.resource_lock_pool is None:
            self.resource_lock_pool = ResourceLockPool()

        if self.hook_registry is None:
            self.hook_registry = HookRegistry(events=self.hook_system)
        if self.middleware_registry is None:
            self.middleware_registry = MiddlewareRegistry(events=self.hook_system)
        if self.command_registry is None:
            from core.slash_routing import COMMAND_REGISTRY

            self.command_registry = COMMAND_REGISTRY
        if invalid := sorted(
            name for name, factory in self.control_state_factories.items() if not callable(factory)
        ):
            raise TypeError(f"control state factories must be callable: {', '.join(invalid)}")
        self.control_state_factories = MappingProxyType(dict(self.control_state_factories))
        if self.bound_tool_plan is not None:
            bound_handlers = dict(self.bound_tool_plan.handlers)
            transient = dict(self.transient_tool_handlers)
            if collisions := sorted(
                transient.keys() & self.bound_tool_plan.plan.execution_map.keys()
            ):
                raise ValueError(
                    f"transient handlers collide with tool plan: {', '.join(collisions)}"
                )
            if invalid := sorted(
                name for name, handler in transient.items() if not callable(handler)
            ):
                raise TypeError(f"transient handlers must be callable: {', '.join(invalid)}")
            combined = {**bound_handlers, **transient}
            if self.tool_handlers and dict(self.tool_handlers) != combined:
                raise ValueError("tool_handlers must match bound_tool_plan")
            self.transient_tool_handlers = MappingProxyType(transient)
            self.tool_handlers = MappingProxyType(combined)
        elif self.transient_tool_handlers:
            raise ValueError("transient_tool_handlers requires bound_tool_plan")

    @property
    def tool_plan(self) -> ToolPlan | None:
        """Compatibility projection for diagnostics that need plan metadata."""
        return self.bound_tool_plan.plan if self.bound_tool_plan is not None else None

    def close(self) -> None:
        """Release resources created by :func:`build_shared_services`."""
        if self._owns_hook_system and self.hook_system is not None:
            self.hook_system.close()

    def create_session(
        self,
        mode: SessionMode,
        *,
        conversation: Any | None = None,
        system_suffix: str = "",
        time_budget_override: float | None = None,
        allowed_tool_names: set[str] | None = None,
        verbose: bool = False,
        propagate_context: bool = False,
        session_id: str = "",
        **kwargs: Any,
    ) -> tuple[ToolExecutor, AgenticLoop]:
        """Build a fully-wired (ToolExecutor, AgenticLoop) for *mode*.

        Every call receives identical shared resources (hooks, MCP, skills,
        cost_budget).  Only mode-specific behavior differs.
        """
        from core.agent.loop import AgenticLoop, AgenticLoopConfig
        from core.agent.tool_executor import ToolExecutor

        if propagate_context:
            self._propagate_contextvars()

        # Resolve defaults for this mode
        defaults = _MODE_DEFAULTS[mode]
        hitl = defaults["hitl_level"]
        quiet = defaults["quiet"]
        time_budget = (
            time_budget_override if time_budget_override is not None else defaults["time_budget_s"]
        )
        max_rounds = defaults["max_rounds"]

        if mode == SessionMode.REPL:
            quiet = not verbose

        # Reload before deriving mode policy so a long-running daemon honors an
        # operator's explicit remote-control opt-in on the next turn, just as
        # it already honors model and effort changes.
        from core.config import _resolve_provider, reload_settings_from_disk, settings

        reload_settings_from_disk()

        # Conversation context
        if conversation is None:
            from core.agent.conversation import ConversationContext

            conversation = ConversationContext()

        # Filter DANGEROUS tools for truly headless modes (no user to approve).
        # IPC mode has HITL relay — tools are gated by approval, not denied.
        # A messaging daemon may expose only the two computer-use surfaces via
        # its separate opt-in; every other headless denial remains enforced.
        bound_tool_plan = self.bound_tool_plan
        profile_denied_tools: frozenset[str] = frozenset()
        provider = _resolve_provider(settings.model)
        if bound_tool_plan is not None:
            from core.agent.loop._tool_factory import project_bound_tool_plan
            from core.llm.adapters._source_inference import infer_source

            bound_tool_plan = project_bound_tool_plan(
                bound_tool_plan,
                provider=provider,
                source=infer_source(provider),
                policy_sources=self.policy_sources,
            )
            from core.tools.policy import apply_profile_policy, load_profile_policy

            profile = load_profile_policy()
            bound_tool_plan = apply_profile_policy(bound_tool_plan, profile)
            profile_denied_tools = frozenset(profile.denied_tools)
        handlers: Mapping[str, Any] = self.tool_handlers
        transient_handlers = self.transient_tool_handlers
        # Defense in depth: only the literal boolean True opens remote desktop
        # control.  Settings validation normally guarantees the type, but this
        # boundary stays fail-closed against legacy/mutated singleton state.
        gateway_computer_use_enabled = settings.gateway_allow_computer_use is True
        headless_denied = _headless_denied_tools_for_mode(
            mode,
            gateway_allow_computer_use=gateway_computer_use_enabled,
            bound_tool_plan=bound_tool_plan,
        )
        headless_denied = headless_denied | profile_denied_tools
        denied = headless_denied & set(handlers)
        if denied:
            log.info("Headless mode %s: denied tools filtered — %s", mode, denied)
        if headless_denied:
            handlers = {k: v for k, v in handlers.items() if k not in headless_denied}
            transient_handlers = MappingProxyType(
                {
                    name: handler
                    for name, handler in transient_handlers.items()
                    if name not in headless_denied
                }
            )
        if bound_tool_plan is not None:
            bound_tool_plan = bound_tool_plan.filtered(
                allowed_tool_names=(
                    frozenset(allowed_tool_names) if allowed_tool_names is not None else None
                ),
                denied_tool_names=headless_denied,
            )
            handlers = bound_tool_plan.handlers
        effective_allowed_tools = (
            frozenset(allowed_tool_names) if allowed_tool_names is not None else None
        )
        if mode == SessionMode.DAEMON and gateway_computer_use_enabled:
            log.info("Gateway remote computer use explicitly enabled for DAEMON session")

        # Settings were reloaded above before mode policy. v0.82.0 + PR-R6
        # (2026-05-24): `/model`
        # writes disk + the CLI's settings but not the daemon's pydantic
        # singleton, so without this in-place reload a long-lived daemon keeps
        # its boot-time values and `/model gpt-5.5` is ignored at the next
        # session. PR-CONFIG-SLOP-SWEEP moved the reload ABOVE the sub-agent
        # manager build (was after) so the manager's caps
        # (max_subagent_depth / max_total_subagents) no longer initialize from
        # a stale pre-reload singleton.
        # Build sub-agent manager + executor + loop
        sub_mgr = self._build_sub_agent_manager()
        approval_cb = kwargs.get("approval_callback")
        executor = ToolExecutor(
            action_handlers=None if bound_tool_plan is not None else dict(handlers),
            bound_tool_plan=bound_tool_plan,
            transient_handlers=(transient_handlers if bound_tool_plan is not None else None),
            mcp_manager=self.mcp_manager,
            sub_agent_manager=sub_mgr,
            hitl_level=hitl,
            hooks=self.hook_system,
            hook_registry=self.hook_registry,
            middleware_registry=self.middleware_registry,
            approval_callback=approval_cb,
            denied_tools=headless_denied,
            allowed_tools=effective_allowed_tools,
            interactive_approval=mode in {SessionMode.REPL, SessionMode.IPC},
            resource_lock_pool=self.resource_lock_pool,
        )

        # PR-R6 (2026-05-24) — operator's effort choice from ``/model``
        # picker (writes ``GEODE_AGENTIC_EFFORT`` + ``[agentic].effort``)
        # was caught by ``reload_settings_from_disk`` above but never
        # crossed the AgenticLoop boundary — the loop's
        # ``effort: str = "high"`` constructor default won by omission.
        # Bridging here closes the gap so the model + effort axes both
        # honor Hermes-style boundary read end-to-end (sub-agents already
        # do via ``sub_agent.py:533``'s direct ``settings.agentic_effort``
        # read).
        loop = AgenticLoop(
            conversation,
            executor,
            config=AgenticLoopConfig(
                max_rounds=max_rounds,
                time_budget_s=time_budget,
                cost_budget=self._cost_budget,
                effort=settings.agentic_effort,
                system_suffix=system_suffix,
                allowed_tool_names=allowed_tool_names,
                session_id=session_id,
            ),
            model=settings.model,
            provider=provider,
            mcp_manager=self.mcp_manager,
            skill_registry=self.skill_registry,
            hooks=self.hook_system,
            quiet=quiet,
            # Caller-provided machine-instance id — gateway threads pass a
            # stable derived id so a thread's turns share ONE checkpoint
            # chain; empty keeps the loop's fresh ``s-<uuid>``.
            activity_sink_provider=self.activity_sink_provider,
            policy_sources=self.policy_sources,
        )
        timeline = getattr(loop, "_timeline", None)
        if timeline is not None:
            loop._control_state_renderers.update(
                {
                    name: factory(timeline.db_path)
                    for name, factory in self.control_state_factories.items()
                }
            )
        # Set per-thread ContextVar so tool handlers see the correct loop
        from core.cli.session_state import set_current_loop

        set_current_loop(loop)
        return executor, loop

    # --- internal helpers -----------------------------------------------------

    def _build_sub_agent_manager(self) -> Any:
        """Build SubAgentManager with shared resources.

        S2-wire (2026-05-18): construct AgentRegistry from .claude/agents/
        + _DEFAULT_AGENTS so SubAgentManager can resolve SubTask.agent
        names (e.g. seed_generator) into the AgentDefinition's
        system_prompt + tools + model. Without an AgentRegistry the
        production path silently fell back to GEODE's default prompt
        regardless of the named role.
        """
        from core.agent.sub_agent import SubAgentManager
        from core.config import settings
        from core.orchestration.isolated_execution import IsolatedRunner

        global_lane = self.lane_queue.get_lane("global") if self.lane_queue else None
        agent_registry = self._build_agent_registry()

        return SubAgentManager(
            IsolatedRunner(
                hooks=self.hook_system,
                lane=global_lane,
                worker_module=self.worker_module,
            ),
            # SubAgentManager uses non-None only to select its injected product
            # worker subprocess; the worker owns the executable Bound snapshot.
            action_handlers={},
            agent_registry=agent_registry,
            hooks=self.hook_system,
            hook_registry=self.hook_registry,
            max_depth=settings.max_subagent_depth,
            max_total_subagents=settings.max_total_subagents,
            activity_sink_provider=self.activity_sink_provider,
            policy_sources=self.policy_sources,
            bound_tool_plan=self.bound_tool_plan,
        )

    def _build_agent_registry(self) -> Any:
        """Build AgentRegistry with defaults plus explicitly configured directories.

        Defaults (research_assistant, data_analyst, web_researcher) load
        first; then ``.claude/agents/`` files are loaded per-file so a
        single bad/duplicate file doesn't drop the rest. Conflicts with
        a default are skipped — user override is intentionally NOT
        supported in this iteration; an explicit override mechanism can
        land later if needed (logged at WARNING so users discover their
        file isn't taking effect).

        S2-fix (2026-05-18) — anchor the loader at ``get_project_root()``
        rather than ``Path(".claude/agents")`` (cwd-relative). The
        previous default silently returned zero files when ``geode serve``
        was launched from a directory without ``.claude/agents/`` (e.g.
        ``$HOME``), which made the entire S2-wire dispatch a no-op in
        common operator deployments.

        Product-owned directories are supplied by the outer composition.
        Operator overrides at ``.claude/agents/`` stay first so same-name
        definitions use the existing first-wins rule.
        """
        from core.paths import get_project_root
        from core.skills.agents import AgentRegistry, SubagentLoader

        registry = AgentRegistry()
        registry.load_defaults()
        project_root = get_project_root()
        agent_search_dirs = [project_root / ".claude" / "agents", *self.agent_search_dirs]
        loader = SubagentLoader(agents_dirs=agent_search_dirs)
        discovered = loader.discover()
        if not discovered:
            log.info(
                "AgentRegistry: no *.md found across %s; "
                "only the 3 built-in defaults are registered",
                [str(d) for d in agent_search_dirs],
            )
        loaded = 0
        for path in discovered:
            try:
                definition = loader.load_file(path)
            except Exception:
                log.warning("AgentRegistry: failed to load %s (skipped)", path, exc_info=True)
                continue
            try:
                registry.register(definition)
                loaded += 1
            except ValueError:
                log.warning(
                    "AgentRegistry: %r conflicts with a built-in default and "
                    "was NOT loaded — rename the file or unregister the "
                    "default to apply your override (path=%s)",
                    definition.name,
                    path,
                )
        log.info(
            "AgentRegistry: loaded %d agents (3 defaults + %d from %d dirs)",
            len(registry),
            loaded,
            len(agent_search_dirs),
        )
        return registry

    def _propagate_contextvars(self) -> None:
        """Re-inject ContextVars for daemon/scheduler threads."""
        from core.cli.bootstrap import GeodeBootstrap

        boot = GeodeBootstrap(
            mcp_manager=self.mcp_manager,
            skill_registry=self.skill_registry,
            readiness=None,
            hook_system=self.hook_system,
        )
        boot.propagate_to_thread()


# ---------------------------------------------------------------------------
# Factory — build SharedServices from bootstrap
# ---------------------------------------------------------------------------


def build_shared_services(
    *,
    mcp_manager: Any = None,
    skill_registry: Any = None,
    hook_system: Any = None,
    hook_registry: Any = None,
    middleware_registry: Any = None,
    middleware_builder: Callable[..., Any] | None = None,
    policy_sources: PolicySourceBundle | None = None,
    activity_sink_provider: RunEventSinkProvider | None = None,
    feature_hook_registrar: Callable[[Any], None] | None = None,
    lane_queue: Any = None,
    command_registry: Any = None,
    verbose: bool = False,
    tool_plan_builder: Callable[..., tuple[BoundToolPlan, Mapping[str, Any]]] | None = None,
    worker_module: str | None = None,
    agent_search_dirs: Sequence[Path] = (),
    control_state_factories: Mapping[str, Callable[[Path], Any]] | None = None,
) -> SharedServices:
    """Construct SharedServices with resolved config values.

    Tool handlers read the current loop from ``_current_loop_ctx`` ContextVar
    (per-thread, no shared mutable ref).  If *hook_system* is None, a default
    HookSystem is built via ``build_hooks()``.
    """
    # Validate composition before allocating hooks or process-global offload state.
    if tool_plan_builder is None:
        raise RuntimeError("shared services requires an injected bound tool-plan builder")
    if not worker_module:
        raise RuntimeError("shared services requires an injected product worker module")
    bound_tool_plan, transient_tool_handlers = tool_plan_builder(
        verbose=verbose,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
    )
    transient_tool_handlers = dict(transient_tool_handlers)
    if collisions := sorted(
        transient_tool_handlers.keys() & bound_tool_plan.plan.execution_map.keys()
    ):
        raise ValueError(f"transient handlers collide with tool plan: {', '.join(collisions)}")
    if invalid := sorted(
        name for name, handler in transient_tool_handlers.items() if not callable(handler)
    ):
        raise TypeError(f"transient handlers must be callable: {', '.join(invalid)}")
    tool_handlers = {**bound_tool_plan.handlers, **transient_tool_handlers}

    # Build hooks if not provided
    owns_hook_system = hook_system is None
    if hook_system is None:
        from core.wiring.bootstrap import build_hooks

        hook_system, _event_store, _metrics = build_hooks(
            session_key=f"geode-{uuid.uuid4().hex[:8]}",
            run_id=uuid.uuid4().hex[:12],
            log_dir=None,
            activity_sink_provider=activity_sink_provider,
            feature_hook_registrar=feature_hook_registrar,
        )
    elif feature_hook_registrar is not None:
        feature_hook_registrar(hook_system)

    from core.hooks import HookRegistry

    if hook_registry is None:
        hook_registry = HookRegistry(events=hook_system)
    from core.config.policy_source import EMPTY_POLICY_SOURCES

    if policy_sources is None:
        policy_sources = EMPTY_POLICY_SOURCES
    if middleware_registry is None:
        if middleware_builder is None:
            from core.hooks import MiddlewareRegistry

            middleware_registry = MiddlewareRegistry(events=hook_system)
        else:
            middleware_registry = middleware_builder(
                events=hook_system,
                policy_sources=policy_sources,
            )

    # P0: Tool result offloading
    from core.wiring.bootstrap import build_tool_offload

    build_tool_offload(
        session_id=f"geode-{uuid.uuid4().hex[:8]}",
        hooks=hook_system,
    )

    # Resolve cost budget
    cost_budget = 0.0
    try:
        from core.cli.commands import _get_cost_budget

        cost_budget = _get_cost_budget()
    except Exception:
        log.debug("Cost budget resolution failed, using 0 (unlimited)")

    # Build unified LaneQueue if not provided
    if lane_queue is None:
        from core.wiring.container import build_default_lanes

        lane_queue = build_default_lanes()

    return SharedServices(
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        hook_system=hook_system,
        hook_registry=hook_registry,
        middleware_registry=middleware_registry,
        policy_sources=policy_sources,
        activity_sink_provider=activity_sink_provider,
        _owns_hook_system=owns_hook_system,
        lane_queue=lane_queue,
        command_registry=command_registry,
        tool_handlers=tool_handlers,
        bound_tool_plan=bound_tool_plan,
        transient_tool_handlers=transient_tool_handlers,
        worker_module=worker_module,
        agent_search_dirs=tuple(agent_search_dirs),
        control_state_factories=control_state_factories or {},
        _cost_budget=cost_budget,
    )
