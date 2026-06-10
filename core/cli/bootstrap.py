"""Unified bootstrap for REPL and serve modes.

Single initialization path ensures both modes get identical:
- Memory contextvars (ProjectMemory, OrgMemory)
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
        running in a non-main thread so memory and tool context stay wired.
        """
        from core.memory.organization import MonoLakeOrganizationMemory
        from core.memory.project import ProjectMemory
        from core.tools.memory_tools import set_org_memory, set_project_memory

        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())

        if self.readiness is not None:
            from core.cli import _set_readiness

            _set_readiness(self.readiness)

        # User profile (Tier 0.5)
        try:
            from pathlib import Path

            from core.config import settings
            from core.memory.user_profile import FileBasedUserProfile
            from core.paths import PROJECT_USER_PROFILE_DIR
            from core.tools.profile_tools import set_user_profile

            global_dir = Path(settings.user_profile_dir) if settings.user_profile_dir else None
            if global_dir is None:
                log.debug("Using default global profile dir: ~/.geode/user_profile")
            project_dir = PROJECT_USER_PROFILE_DIR
            set_user_profile(
                FileBasedUserProfile(
                    global_dir=global_dir,
                    project_dir=project_dir if project_dir.parent.exists() else None,
                )
            )
        except Exception:
            log.debug("User profile propagation skipped", exc_info=True)


def load_daemon_env() -> None:
    """Serve-daemon env load (C-3/C-4, 2026-06-11).

    Delegates promotion to :func:`core.config.env_io.load_env_files` — the
    ONE dotenv precedence (manual exports > project .env > global
    ~/.geode/.env, hazard H5) shared with the standalone train/campaign
    entrypoints.

    Behavior(model-pick) keys (``core.config.env_io.BEHAVIOR_ENV_KEYS``) are
    dropped from the inherited environment and skipped during promotion:
    anything in the daemon's os.environ outlives every per-session settings
    reload, so a stray GEODE_MODEL would mask /model switches for the
    daemon's whole lifetime (hazard H2). ``GEODE_SERVE_KEEP_MODEL_ENV=1``
    keeps them for operators who intentionally pin the daemon's model —
    honored from the process env OR from either .env file (C-4: pre-fix a
    flag written into .env was read only AFTER the drop had already
    happened, so it silently did nothing). Secrets still promote — MCP
    ``${VAR}`` expansion and spawned subprocesses read os.environ.
    """
    import os
    from pathlib import Path

    from dotenv import dotenv_values

    from core.config.env_io import BEHAVIOR_ENV_KEYS, load_env_files
    from core.paths import GLOBAL_ENV_FILE

    keep_model_env = os.environ.get("GEODE_SERVE_KEEP_MODEL_ENV") == "1"
    if not keep_model_env:
        # The escape hatch may live in a .env file rather than the spawning
        # shell — check both files BEFORE dropping anything.
        for env_file in (GLOBAL_ENV_FILE, Path(".env")):
            if (
                env_file.exists()
                and dotenv_values(str(env_file)).get("GEODE_SERVE_KEEP_MODEL_ENV") == "1"
            ):
                keep_model_env = True
                break

    if not keep_model_env:
        for behavior_key in BEHAVIOR_ENV_KEYS:
            if behavior_key in os.environ:
                log.info(
                    "serve: dropping inherited %s from daemon env "
                    "(session reloads must win; set "
                    "GEODE_SERVE_KEEP_MODEL_ENV=1 to keep)",
                    behavior_key,
                )
                os.environ.pop(behavior_key)

    load_env_files(skip_behavior_keys=not keep_model_env)


def setup_contextvars(*, load_env: bool = False) -> None:
    """Initialize ContextVars only (memory, profile, env).

    No resource creation. Call before GeodeRuntime.create() so that
    memory ContextVars are available to all layers.
    """
    if load_env:
        load_daemon_env()

    # 1. Memory contextvars
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
        from core.paths import PROJECT_USER_PROFILE_DIR
        from core.tools.profile_tools import set_user_profile

        global_dir = Path(settings.user_profile_dir) if settings.user_profile_dir else None
        if global_dir is None:
            log.debug("Using default global profile dir: ~/.geode/user_profile")
        project_dir = PROJECT_USER_PROFILE_DIR
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
    from core.wiring.startup import check_readiness

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


async def arun_agentic_oneshot(
    prompt: str,
    *,
    quiet: bool = True,
    time_budget_s: float = 60.0,
) -> Any:
    """Async core of :func:`run_agentic_oneshot` — await inside a running loop.

    geode-mcp executes tools INSIDE the server's event loop, where the sync
    wrapper's ``run_process_coroutine`` raises ("cannot be called from an
    active event loop" — first live HTTP ``run_agent``, 2026-06-11). MCP
    tool handlers await this directly; sync callers (fork skill) keep the
    wrapper below.
    """
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.config import _resolve_provider
    from core.config import settings as _stk_settings
    from core.llm.adapters.registry import bootstrap_builtins

    # geode-mcp (and any caller that never went through GeodeRuntime.create)
    # has an EMPTY adapter registry — the first live run_agent over MCP
    # failed with AdapterNotFoundError "Known pairs: []" (2026-06-11).
    # Same pattern as core/agent/worker.py:858. Idempotent: already-
    # registered adapters are skipped.
    bootstrap_builtins()

    conversation = ConversationContext()
    handlers = _build_tool_handlers_for_fork()
    executor = ToolExecutor(action_handlers=handlers, hitl_level=0)
    loop = AgenticLoop(
        conversation,
        executor,
        model=_stk_settings.model,
        provider=_resolve_provider(_stk_settings.model),
        quiet=quiet,
        time_budget_s=time_budget_s,
        max_rounds=0,
    )
    return await loop.arun(prompt)


def run_agentic_oneshot(
    prompt: str,
    *,
    quiet: bool = True,
    time_budget_s: float = 60.0,
) -> Any:
    """Build a minimal isolated AgenticLoop and run a prompt one-shot.

    Returns AgenticResult.  Inline construction — no SharedServices overhead.
    One-shot execution, not a session mode. Callers: context:fork skill
    execution (``cmd_skill_invoke``); the ``geode-mcp`` ``run_agent`` tool
    awaits :func:`arun_agentic_oneshot` directly (running-loop context).
    """
    from core.async_runtime import run_process_coroutine

    return run_process_coroutine(
        arun_agentic_oneshot(prompt, quiet=quiet, time_budget_s=time_budget_s)
    )


def _build_tool_handlers_for_fork() -> dict[str, Any]:
    """Minimal tool handlers for forked skill execution (no MCP, no sub-agents)."""
    from core.cli.tool_handlers import _build_tool_handlers

    return _build_tool_handlers(verbose=False)
