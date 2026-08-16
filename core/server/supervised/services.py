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
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.agent.safety import COMPUTER_USE_TOOLS, HEADLESS_DENIED_TOOLS

if TYPE_CHECKING:
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor

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
) -> frozenset[str]:
    """Resolve the enforced denylist for one session mode.

    Messaging may expose the same desktop-control handlers as the interactive
    CLI, but only through a dedicated fail-closed operator opt-in. Scheduled
    jobs and MCP ``run_agent`` have no equivalent trusted conversation
    boundary and retain the canonical denylist.
    """
    if mode not in (SessionMode.SCHEDULER, SessionMode.DAEMON):
        return frozenset()
    if mode == SessionMode.DAEMON and gateway_allow_computer_use is True:
        return HEADLESS_DENIED_TOOLS - COMPUTER_USE_TOOLS
    return HEADLESS_DENIED_TOOLS


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

    No shared mutable state — each ``create_session()`` returns independent
    instances.  Tool handlers that need the current loop read from
    ``_current_loop_ctx`` ContextVar (per-thread, no race condition).
    """

    mcp_manager: Any = None
    skill_registry: Any = None
    hook_system: Any = None  # HookSystem — never None after init
    hook_registry: Any = None  # process-owned public HookRegistry
    middleware_registry: Any = None  # process-owned trusted MiddlewareRegistry
    policy_sources: Any = None  # immutable product policy candidates
    _owns_hook_system: bool = False
    lane_queue: Any = None  # Unified LaneQueue — single concurrency gate
    tool_handlers: dict[str, Any] = field(default_factory=dict)

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
        from core.hooks import HookRegistry
        from core.wiring.bootstrap import build_product_policy_sources

        if self.policy_sources is None:
            self.policy_sources = build_product_policy_sources()

        if self.hook_registry is None:
            self.hook_registry = HookRegistry(events=self.hook_system)
        if self.middleware_registry is None:
            from core.wiring.bootstrap import build_middleware_registry

            self.middleware_registry = build_middleware_registry(
                events=self.hook_system,
                policy_sources=self.policy_sources,
            )

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
        from core.agent.loop import AgenticLoop
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
        handlers = self.tool_handlers
        # Defense in depth: only the literal boolean True opens remote desktop
        # control.  Settings validation normally guarantees the type, but this
        # boundary stays fail-closed against legacy/mutated singleton state.
        gateway_computer_use_enabled = settings.gateway_allow_computer_use is True
        headless_denied = _headless_denied_tools_for_mode(
            mode,
            gateway_allow_computer_use=gateway_computer_use_enabled,
        )
        denied = headless_denied & set(handlers)
        if denied:
            log.info("Headless mode %s: denied tools filtered — %s", mode, denied)
        if headless_denied:
            handlers = {k: v for k, v in handlers.items() if k not in headless_denied}
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
            action_handlers=handlers,
            mcp_manager=self.mcp_manager,
            sub_agent_manager=sub_mgr,
            hitl_level=hitl,
            hooks=self.hook_system,
            hook_registry=self.hook_registry,
            middleware_registry=self.middleware_registry,
            approval_callback=approval_cb,
            denied_tools=headless_denied,
            allowed_tools=(
                frozenset(allowed_tool_names) if allowed_tool_names is not None else None
            ),
            interactive_approval=mode in {SessionMode.REPL, SessionMode.IPC},
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
        from core.wiring.bootstrap import current_product_activity_sink

        loop = AgenticLoop(
            conversation,
            executor,
            max_rounds=max_rounds,
            time_budget_s=time_budget,
            cost_budget=self._cost_budget,
            model=settings.model,
            provider=_resolve_provider(settings.model),
            effort=settings.agentic_effort,
            mcp_manager=self.mcp_manager,
            skill_registry=self.skill_registry,
            hooks=self.hook_system,
            system_suffix=system_suffix,
            quiet=quiet,
            allowed_tool_names=allowed_tool_names,
            # Caller-provided machine-instance id — gateway threads pass a
            # stable derived id so a thread's turns share ONE checkpoint
            # chain; empty keeps the loop's fresh ``s-<uuid>``.
            session_id=session_id,
            activity_sink_provider=current_product_activity_sink,
            policy_sources=self.policy_sources,
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
        from core.wiring.bootstrap import current_product_activity_sink

        global_lane = self.lane_queue.get_lane("global") if self.lane_queue else None
        agent_registry = self._build_agent_registry()

        return SubAgentManager(
            IsolatedRunner(hooks=self.hook_system, lane=global_lane),
            action_handlers=self.tool_handlers,
            agent_registry=agent_registry,
            hooks=self.hook_system,
            hook_registry=self.hook_registry,
            max_depth=settings.max_subagent_depth,
            max_total_subagents=settings.max_total_subagents,
            activity_sink_provider=current_product_activity_sink,
            policy_sources=self.policy_sources,
        )

    def _build_agent_registry(self) -> Any:
        """Build AgentRegistry with defaults + .claude/agents/ + plugins/*/agents/.

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

        CSP-9 (2026-05-22) — extend the search to plugin-shipped agent
        definitions at ``plugins/*/agents/*.md``. Operator overrides at
        ``.claude/agents/`` still take precedence (same-basename dedup,
        first-wins) so a plugin's ``critic.md`` can be replaced by
        dropping a tweaked ``critic.md`` into ``.claude/agents/``. This
        keeps seed-generation prompts (and any future plugin's agent
        prompts) bundled with the plugin package rather than scattered
        under the project-wide override directory.
        """
        from core.paths import get_project_root
        from core.skills.agents import AgentRegistry, SubagentLoader

        registry = AgentRegistry()
        registry.load_defaults()
        project_root = get_project_root()
        agent_search_dirs: list[Path] = [project_root / ".claude" / "agents"]
        plugins_root = project_root / "plugins"
        if plugins_root.exists():
            for plugin_agents in sorted(plugins_root.glob("*/agents")):
                if plugin_agents.is_dir():
                    agent_search_dirs.append(plugin_agents)
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
    lane_queue: Any = None,
    verbose: bool = False,
) -> SharedServices:
    """Construct SharedServices with resolved config values.

    Tool handlers read the current loop from ``_current_loop_ctx`` ContextVar
    (per-thread, no shared mutable ref).  If *hook_system* is None, a default
    HookSystem is built via ``build_hooks()``.
    """
    # Build hooks if not provided
    owns_hook_system = hook_system is None
    if hook_system is None:
        from core.wiring.bootstrap import build_hooks

        hook_system, _event_store, _metrics = build_hooks(
            session_key=f"geode-{uuid.uuid4().hex[:8]}",
            run_id=uuid.uuid4().hex[:12],
            log_dir=None,
        )

    from core.hooks import HookRegistry

    if hook_registry is None:
        hook_registry = HookRegistry(events=hook_system)
    from core.wiring.bootstrap import build_product_policy_sources

    policy_sources = build_product_policy_sources()
    if middleware_registry is None:
        from core.wiring.bootstrap import build_middleware_registry

        middleware_registry = build_middleware_registry(
            events=hook_system,
            policy_sources=policy_sources,
        )

    # P0: Tool result offloading
    from core.wiring.bootstrap import build_tool_offload

    build_tool_offload(
        session_id=f"geode-{uuid.uuid4().hex[:8]}",
        hooks=hook_system,
    )

    # Build tool handlers — no agentic_ref (uses ContextVar instead)
    from core.cli.tool_handlers import _build_tool_handlers

    tool_handlers = _build_tool_handlers(
        verbose=verbose,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
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
        _owns_hook_system=owns_hook_system,
        lane_queue=lane_queue,
        tool_handlers=tool_handlers,
        _cost_budget=cost_budget,
    )
