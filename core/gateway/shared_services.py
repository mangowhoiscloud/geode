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

if TYPE_CHECKING:
    from core.agent.agentic_loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session mode enum
# ---------------------------------------------------------------------------


class SessionMode(StrEnum):
    """Execution mode — determines behavior defaults, not shared resources."""

    REPL = "repl"  # Interactive — hitl=2, verbose=user, time=unlimited
    DAEMON = "daemon"  # Slack/Discord poller — hitl=0, quiet, time=config
    SCHEDULER = "scheduler"  # Cron/scheduled jobs — hitl=0, quiet, time=300s cap
    FORK = "fork"  # Skill context:fork — hitl=0, quiet, time=60s


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
    SessionMode.DAEMON: {
        "hitl_level": 0,
        "quiet": True,
        "time_budget_s": 0.0,  # resolved from config at runtime
        "max_rounds": 0,
    },
    SessionMode.SCHEDULER: {
        "hitl_level": 0,
        "quiet": True,
        "time_budget_s": 300.0,  # 5 min cap
        "max_rounds": 0,
    },
    SessionMode.FORK: {
        "hitl_level": 0,
        "quiet": True,
        "time_budget_s": 60.0,
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

    The ``agentic_ref`` is a mutable ``[loop]`` list shared across handler
    closures — ``create_session()`` updates ``ref[0]`` to the latest loop,
    so tool handlers (e.g. ``install_mcp_server``) always see the current one.
    """

    mcp_manager: Any = None
    skill_registry: Any = None
    hook_system: Any = None  # HookSystem — never None after init
    tool_handlers: dict[str, Any] = field(default_factory=dict)
    agentic_ref: list[Any] = field(default_factory=lambda: [None])

    # Resolved once at bootstrap
    _model: str = ""
    _provider: str = "anthropic"
    _cost_budget: float = 0.0

    # --- public API -----------------------------------------------------------

    def create_session(
        self,
        mode: SessionMode,
        *,
        conversation: Any | None = None,
        system_suffix: str = "",
        time_budget_override: float | None = None,
        verbose: bool = False,
        propagate_context: bool = False,
    ) -> tuple[ToolExecutor, AgenticLoop]:
        """Build a fully-wired (ToolExecutor, AgenticLoop) for *mode*.

        Every call receives identical shared resources (hooks, MCP, skills,
        cost_budget).  Only mode-specific behavior differs.
        """
        from core.agent.agentic_loop import AgenticLoop
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

        # Conversation context
        if conversation is None:
            from core.agent.conversation import ConversationContext

            conversation = ConversationContext()

        # Build sub-agent manager + executor + loop
        sub_mgr = self._build_sub_agent_manager()
        executor = ToolExecutor(
            action_handlers=self.tool_handlers,
            mcp_manager=self.mcp_manager,
            sub_agent_manager=sub_mgr,
            hitl_level=hitl,
            hooks=self.hook_system,
        )
        loop = AgenticLoop(
            conversation,
            executor,
            max_rounds=max_rounds,
            time_budget_s=time_budget,
            cost_budget=self._cost_budget,
            model=self._model,
            provider=self._provider,
            mcp_manager=self.mcp_manager,
            skill_registry=self.skill_registry,
            hooks=self.hook_system,
            system_suffix=system_suffix,
            quiet=quiet,
        )
        # Update mutable ref so tool handler closures see the latest loop
        self.agentic_ref[0] = loop
        return executor, loop

    # --- internal helpers -----------------------------------------------------

    def _build_sub_agent_manager(self) -> Any:
        """Build SubAgentManager with shared resources."""
        from core.agent.sub_agent import SubAgentManager
        from core.config import settings
        from core.orchestration.isolated_execution import IsolatedRunner

        return SubAgentManager(
            IsolatedRunner(hooks=self.hook_system),
            action_handlers=self.tool_handlers,
            mcp_manager=self.mcp_manager,
            skill_registry=self.skill_registry,
            hooks=self.hook_system,
            max_depth=settings.max_subagent_depth,
        )

    def _propagate_contextvars(self) -> None:
        """Re-inject ContextVars for daemon/scheduler threads."""
        from core.cli.bootstrap import GeodeBootstrap

        boot = GeodeBootstrap(
            mcp_manager=self.mcp_manager,
            skill_registry=self.skill_registry,
            readiness=None,
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
    verbose: bool = False,
) -> SharedServices:
    """Construct SharedServices with resolved config values.

    Builds tool handlers with a shared ``agentic_ref`` so handler closures
    always see the current AgenticLoop.  If *hook_system* is None, a default
    HookSystem is built via ``build_hooks()``.
    """
    from core.config import _resolve_provider
    from core.config import settings as _settings

    # Build hooks if not provided
    if hook_system is None:
        from core.runtime_wiring.bootstrap import build_hooks

        hook_system, _run_log, _stuck = build_hooks(
            session_key=f"geode-{uuid.uuid4().hex[:8]}",
            run_id=uuid.uuid4().hex[:12],
            log_dir=Path.home() / ".geode" / "runs",
            stuck_timeout_s=getattr(_settings, "stuck_timeout_s", 600.0),
        )

    # Build tool handlers with shared agentic_ref
    agentic_ref: list[Any] = [None]
    from core.cli.tool_handlers import _build_tool_handlers

    tool_handlers = _build_tool_handlers(
        verbose=verbose,
        mcp_manager=mcp_manager,
        agentic_ref=agentic_ref,
        skill_registry=skill_registry,
    )

    # Resolve cost budget
    cost_budget = 0.0
    try:
        from core.cli.commands import _get_cost_budget

        cost_budget = _get_cost_budget()
    except Exception:
        log.debug("Cost budget resolution failed, using 0 (unlimited)")

    return SharedServices(
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        hook_system=hook_system,
        tool_handlers=tool_handlers,
        agentic_ref=agentic_ref,
        _model=_settings.model,
        _provider=_resolve_provider(_settings.model),
        _cost_budget=cost_budget,
    )
