"""Unified bootstrap for REPL and serve modes.

Single initialization path ensures both modes get identical:
- Memory contextvars (ProjectMemory, OrgMemory)
- Domain adapter
- Readiness check
- MCP manager
- Skills
- Tool handlers

The returned GeodeBootstrap carries all initialized components
and provides propagate_to_thread() for daemon thread ContextVar injection.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class GeodeBootstrap:
    """Initialized GEODE context — shared between REPL and serve."""

    mcp_manager: Any = None
    skill_registry: Any = None
    tool_handlers: dict[str, Any] = field(default_factory=dict)
    readiness: Any = None

    # Snapshot of ContextVars for thread propagation
    _context: contextvars.Context = field(default_factory=contextvars.copy_context)

    def propagate_to_thread(self) -> None:
        """Re-set ContextVars in current (daemon) thread.

        Python ``contextvars`` do not automatically inherit across threads.
        Call this at the start of ``_gateway_processor`` or any function
        running in a non-main thread so that tools like ``note_read``,
        ``memory_search``, and ``analyze_ip`` work correctly.
        """
        from core.memory.organization import MonoLakeOrganizationMemory
        from core.memory.project import ProjectMemory
        from core.tools.memory_tools import set_org_memory, set_project_memory

        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())

        if self.readiness is not None:
            from core.cli import _set_readiness

            _set_readiness(self.readiness)

        # Domain adapter
        try:
            from core.domains.loader import load_domain_adapter
            from core.domains.port import set_domain

            set_domain(load_domain_adapter("game_ip"))
        except Exception:
            log.debug("Domain propagation skipped", exc_info=True)

        # User profile (Tier 0.5)
        try:
            from pathlib import Path

            from core.config import settings
            from core.memory.user_profile import FileBasedUserProfile
            from core.tools.profile_tools import set_user_profile

            global_dir = Path(settings.user_profile_dir) if settings.user_profile_dir else None
            if global_dir is None:
                log.debug("Using default global profile dir: ~/.geode/user_profile")
            project_dir = Path(".geode") / "user_profile"
            set_user_profile(
                FileBasedUserProfile(
                    global_dir=global_dir,
                    project_dir=project_dir if project_dir.parent.exists() else None,
                )
            )
        except Exception:
            log.debug("User profile propagation skipped", exc_info=True)


def setup_contextvars(*, load_env: bool = False) -> None:
    """Initialize ContextVars only (domain, memory, profile, env).

    No resource creation. Call before GeodeRuntime.create() so that
    domain adapter and memory ContextVars are available to all layers.
    """
    if load_env:
        import os
        from pathlib import Path

        from dotenv import dotenv_values, load_dotenv

        # 1) Global ~/.geode/.env — baseline for all projects
        global_env = Path.home() / ".geode" / ".env"
        if global_env.exists():
            load_dotenv(str(global_env), override=False)

        # 2) Local .env — override only with non-empty values
        #    Empty values (e.g. ANTHROPIC_API_KEY=) must NOT clobber global keys
        local_env = Path(".env")
        if local_env.exists():
            for key, val in dotenv_values(str(local_env)).items():
                if val:  # non-empty only
                    os.environ[key] = val

    # 1. Domain adapter
    try:
        from core.domains.loader import load_domain_adapter
        from core.domains.port import set_domain

        set_domain(load_domain_adapter("game_ip"))
    except Exception:
        log.debug("Domain adapter skipped", exc_info=True)

    # 2. Memory contextvars
    try:
        from core.memory.organization import MonoLakeOrganizationMemory
        from core.memory.project import ProjectMemory
        from core.tools.memory_tools import set_org_memory, set_project_memory

        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())
    except Exception:
        log.debug("Memory context skipped", exc_info=True)

    # 2.5. User Profile (Tier 0.5) — wire into profile tools via ContextVar
    try:
        from pathlib import Path

        from core.config import settings
        from core.memory.user_profile import FileBasedUserProfile
        from core.tools.profile_tools import set_user_profile

        global_dir = Path(settings.user_profile_dir) if settings.user_profile_dir else None
        if global_dir is None:
            log.debug("Using default global profile dir: ~/.geode/user_profile")
        project_dir = Path(".geode") / "user_profile"
        user_profile = FileBasedUserProfile(
            global_dir=global_dir,
            project_dir=project_dir if project_dir.parent.exists() else None,
        )
        set_user_profile(user_profile)
    except Exception:
        log.debug("User profile context skipped", exc_info=True)


def bootstrap_geode(
    *,
    verbose: bool = False,
    load_env: bool = False,
) -> GeodeBootstrap:
    """REPL bootstrap — ContextVars + MCP + Skills + Handlers.

    For serve mode, use ``setup_contextvars()`` + ``GeodeRuntime.create()``
    directly instead.
    """
    setup_contextvars(load_env=load_env)

    # 3. Readiness
    from core.cli import _set_readiness
    from core.cli.startup import check_readiness

    readiness = check_readiness()
    _set_readiness(readiness)

    # 4. MCP — load config (server discovery) without connecting subprocesses.
    #    Full startup() (connect all) is deferred to first tool use.
    from core.mcp.manager import get_mcp_manager

    mcp_mgr = get_mcp_manager()
    mcp_mgr.load_config()

    # 5. Skills
    from core.skills.skills import SkillLoader, SkillRegistry

    skill_registry = SkillRegistry()
    try:
        SkillLoader().load_all(registry=skill_registry)
    except Exception:
        log.debug("Skill loading skipped", exc_info=True)

    # 6. Tool handlers
    from core.cli.tool_handlers import _build_tool_handlers

    handlers = _build_tool_handlers(
        verbose=verbose,
        mcp_manager=mcp_mgr,
        skill_registry=skill_registry,
    )

    return GeodeBootstrap(
        mcp_manager=mcp_mgr,
        skill_registry=skill_registry,
        tool_handlers=handlers,
        readiness=readiness,
    )


def _build_agentic_stack_minimal(prompt: str, *, quiet: bool = True) -> Any:
    """Build a minimal isolated AgenticLoop and run a prompt (for context:fork skills).

    Returns AgenticResult.  Inline construction — no SharedServices overhead.
    Fork is a lightweight one-shot execution, not a session mode.
    """
    from core.agent.agentic_loop import AgenticLoop
    from core.agent.conversation import ConversationContext
    from core.agent.tool_executor import ToolExecutor
    from core.config import _resolve_provider
    from core.config import settings as _stk_settings

    conversation = ConversationContext()
    handlers = _build_tool_handlers_for_fork()
    executor = ToolExecutor(action_handlers=handlers, hitl_level=0)
    loop = AgenticLoop(
        conversation,
        executor,
        model=_stk_settings.model,
        provider=_resolve_provider(_stk_settings.model),
        quiet=quiet,
        time_budget_s=60.0,
        max_rounds=0,
    )
    return loop.run(prompt)


def _build_tool_handlers_for_fork() -> dict[str, Any]:
    """Minimal tool handlers for forked skill execution (no MCP, no sub-agents)."""
    from core.cli.tool_handlers import _build_tool_handlers

    return _build_tool_handlers(verbose=False)
