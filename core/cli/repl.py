"""Interactive REPL — Claude Code / OpenClaw-style dual routing.

Extracted from ``core/cli/__init__.py`` for architectural clarity.

Two routing paths:
  /command  -> deterministic dispatch (commands.py)
  free-text -> agentic loop (AgenticLoop, multi-turn + multi-intent)
"""

from __future__ import annotations

import logging
import signal
import sys
import termios
from pathlib import Path
from typing import Any

from core.cli.agentic_loop import AgenticLoop, AgenticResult
from core.cli.conversation import ConversationContext
from core.cli.tool_executor import ToolExecutor
from core.ui.console import console

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Terminal restoration + signal handling
# ---------------------------------------------------------------------------


def _restore_terminal() -> None:
    """Restore terminal to sane cooked mode.

    Rich Status/Live can leave the terminal in raw mode (echo off, no
    line-editing) if interrupted or if an exception escapes their context
    manager.  This ensures the terminal is usable before reading input.
    """
    try:
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        # Ensure ECHO and ICANON (cooked mode) are enabled
        attrs[3] |= termios.ECHO | termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (ValueError, OSError, termios.error):
        # Non-TTY or stdin not available -- nothing to restore
        pass


_original_sigint = signal.getsignal(signal.SIGINT)


def _sigint_handler(signum: int, frame: Any) -> None:
    """SIGINT handler that restores terminal before raising KeyboardInterrupt."""
    _restore_terminal()
    raise KeyboardInterrupt


# ---------------------------------------------------------------------------
# prompt_toolkit REPL input (arrow keys, history)
# ---------------------------------------------------------------------------


def _build_prompt_session() -> Any:
    """Create a prompt_toolkit PromptSession with history + GEODE styling.

    Includes a custom Backspace/Delete key binding that forces a full
    renderer redraw after deletion -- fixes wide-char (Korean jamo) ghost
    artifacts where the display doesn't update even though the buffer is
    correctly modified.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("backspace")
    def _backspace(event: Any) -> None:
        buf = event.app.current_buffer
        if buf.cursor_position > 0:
            buf.delete_before_cursor(count=1)
            event.app.invalidate()

    @kb.add("delete")
    def _delete(event: Any) -> None:
        buf = event.app.current_buffer
        if buf.cursor_position < len(buf.text):
            buf.delete(count=1)
            event.app.invalidate()

    history_path = Path.home() / ".geode_history"
    return PromptSession(
        history=FileHistory(str(history_path)),
        message=HTML("<b>&gt;</b> "),
        enable_history_search=True,
        multiline=False,
        key_bindings=kb,
    )


# Module-level lazy singleton
_prompt_session: Any = None


def _get_prompt_session() -> Any:
    global _prompt_session
    if _prompt_session is None:
        try:
            _prompt_session = _build_prompt_session()
        except Exception:
            log.warning("prompt_toolkit init failed, falling back to console.input", exc_info=True)
    return _prompt_session


def _read_multiline_input(prompt: str) -> str:
    """Read user input via prompt_toolkit (arrow keys, history).

    Falls back to Rich console.input if prompt_toolkit is unavailable.
    Paste handling is delegated to prompt_toolkit's built-in bracketed
    paste support (no manual stdin polling).
    """
    session = _get_prompt_session()
    if session is not None:
        try:
            # Restore default SIGINT so prompt_toolkit can handle Ctrl-C internally.
            # Our custom handler interferes with prompt_toolkit's input loop.
            signal.signal(signal.SIGINT, _original_sigint)
            text: str = str(session.prompt()).strip()
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception:
            log.warning("prompt_toolkit failed, falling back to console.input", exc_info=True)
            text = str(console.input("> ")).strip()
        finally:
            # Re-install our handler for the non-input phase (spinner, tool execution)
            signal.signal(signal.SIGINT, _sigint_handler)
    else:
        text = str(console.input("> ")).strip()

    return text


# ---------------------------------------------------------------------------
# Agentic result rendering
# ---------------------------------------------------------------------------


def _render_agentic_result(result: AgenticResult) -> None:
    """Render the final result from an agentic loop execution."""
    if result.error == "llm_call_failed":
        console.print()
        console.print("  [warning]LLM call failed. Try again or check your API key.[/warning]")
        console.print("  [muted]Use /help for available commands.[/muted]")
        console.print()
        return

    if result.text:
        console.print()
        # Render markdown if the response contains markdown indicators
        if any(md in result.text for md in ("## ", "| ", "```", "**", "- [")):
            from rich.markdown import Markdown
            from rich.padding import Padding

            md = Markdown(result.text)
            console.print(Padding(md, (0, 2)))
        else:
            console.print(f"  {result.text}")
        console.print()

    if result.tool_calls:
        tool_names = [tc["tool"] for tc in result.tool_calls]
        log.debug(
            "Agentic loop: %d rounds, %d tool calls (%s)",
            result.rounds,
            len(result.tool_calls),
            ", ".join(tool_names),
        )


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


def _interactive_loop() -> None:
    """Claude Code / OpenClaw-style interactive REPL.

    Two routing paths:
      /command  -> deterministic dispatch (commands.py)
      free-text -> agentic loop (AgenticLoop, multi-turn + multi-intent)
    """
    from core.cli import (
        _build_sub_agent_manager,
        _get_readiness,
        _handle_command,
        _scheduler_service_ctx,
        _set_readiness,
    )
    from core.cli.startup import check_readiness, key_registration_gate
    from core.cli.tool_handlers import _build_tool_handlers

    verbose = False
    conversation = ConversationContext()

    # --- Startup initialization with progressive status ---
    def _init_step(label: str) -> None:
        """Print a compact startup progress indicator."""
        console.print(f"  [dim]Loading {label}...[/dim]", end="\r")

    def _init_done(label: str, ok: bool = True) -> None:
        mark = "[bold green]ok[/bold green]" if ok else "[dim]skip[/dim]"
        console.print(f"  {mark} {label}          ")

    # 0. Config validation (routing.toml, model-policy.toml)
    _init_step("config")
    try:
        from core.config import load_model_policy, load_routing_config

        _policy = load_model_policy()
        _routing = load_routing_config()
        _has_policy = bool(_policy.allowlist or _policy.denylist)
        _has_routing = bool(_routing.nodes or _routing.agentic)
        if _has_policy or _has_routing:
            _init_done("Config (policy + routing)")
        else:
            _init_done("Config (defaults)")
    except Exception:
        _init_done("Config", ok=False)
        log.debug("Config validation skipped", exc_info=True)

    # 1. Domain adapter
    _init_step("domain")
    from core.domains.loader import load_domain_adapter
    from core.infrastructure.ports.domain_port import set_domain

    try:
        set_domain(load_domain_adapter("game_ip"))
        _init_done("Domain")
    except Exception:
        _init_done("Domain", ok=False)
        log.debug("Domain adapter initialization skipped", exc_info=True)

    # 2. Memory contextvars
    _init_step("memory")
    from core.memory.organization import MonoLakeOrganizationMemory
    from core.memory.project import ProjectMemory
    from core.tools.memory_tools import set_org_memory, set_project_memory

    try:
        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())
        _init_done("Memory")
    except Exception:
        _init_done("Memory", ok=False)
        log.debug("Memory context initialization skipped", exc_info=True)

    # 3. Key gate
    readiness = _get_readiness()
    if readiness is None or readiness.blocked:
        key = key_registration_gate()
        if key is None:
            return  # user quit
        readiness = check_readiness()
        _set_readiness(readiness)

    # 4. MCP servers (slowest -- npx subprocess spawn)
    #    Uses startup() for full lifecycle: config + connect + signal handlers + atexit
    #    TextSpinner blocks visual input during the slow npx subprocess phase.
    from core.infrastructure.adapters.mcp.manager import MCPServerManager
    from core.ui.status import TextSpinner

    mcp_mgr: MCPServerManager | None = None
    _mcp_spinner = TextSpinner("MCP servers")
    _mcp_spinner.start()
    try:
        _mgr = MCPServerManager()
        n_connected = _mgr.startup()
        if len(_mgr._servers) > 0:
            mcp_mgr = _mgr
            _mcp_spinner.stop(f"  ok MCP ({n_connected}/{len(_mgr._servers)} servers)")
        else:
            _mcp_spinner.stop("  skip MCP (none)")
    except Exception:
        _mcp_spinner.stop("  skip MCP")
        log.debug("MCP initialization skipped", exc_info=True)

    # 5. Skills
    _init_step("skills")
    from core.extensibility.skills import SkillLoader, SkillRegistry

    skill_registry = SkillRegistry()
    try:
        loaded_skills = SkillLoader().load_all(registry=skill_registry)
        _init_done(f"Skills ({len(loaded_skills)})" if loaded_skills else "Skills (0)")
    except Exception:
        _init_done("Skills", ok=False)
        log.debug("Skill loading skipped", exc_info=True)

    # 6. Scheduler
    _init_step("scheduler")
    try:
        from core.automation.scheduler import SchedulerService

        _sched_svc = SchedulerService()
        _sched_svc.load()
        _sched_svc.start()
        _scheduler_service_ctx.set(_sched_svc)
        _init_done("Scheduler")
    except Exception:
        _init_done("Scheduler", ok=False)
        log.debug("SchedulerService initialization skipped", exc_info=True)

    # 7. Gateway (inbound messaging pollers)
    gateway_mgr = None
    try:
        from core.infrastructure.ports.gateway_port import get_gateway

        gateway_mgr = get_gateway()
        if gateway_mgr is not None:
            _init_step("gateway")
            _init_done("Gateway")
    except Exception:
        log.debug("Gateway initialization skipped", exc_info=True)

    # 8. Calendar bridge wiring
    try:
        from core.infrastructure.ports.calendar_port import get_calendar
        from core.orchestration.calendar_bridge import (
            CalendarSchedulerBridge,
            set_calendar_bridge,
        )

        _cal = get_calendar()
        _sched = _scheduler_service_ctx.get(None)
        if _cal is not None and _sched is not None:
            bridge = CalendarSchedulerBridge(_sched, _cal)
            set_calendar_bridge(bridge)
            log.debug("CalendarSchedulerBridge wired")
    except Exception:
        log.debug("Calendar bridge wiring skipped", exc_info=True)

    console.print()  # blank line before prompt

    # Build tool handlers and executor
    agentic_ref: list[Any] = [None]  # mutable ref for handler closure
    handlers = _build_tool_handlers(
        verbose=verbose, mcp_manager=mcp_mgr, agentic_ref=agentic_ref, skill_registry=skill_registry
    )
    sub_mgr = _build_sub_agent_manager(
        verbose=verbose,
        action_handlers=handlers,
        mcp_manager=mcp_mgr,
        skill_registry=skill_registry,
    )
    executor = ToolExecutor(
        action_handlers=handlers,
        mcp_manager=mcp_mgr,
        sub_agent_manager=sub_mgr,
    )
    agentic = AgenticLoop(
        conversation, executor, mcp_manager=mcp_mgr, skill_registry=skill_registry
    )
    agentic_ref[0] = agentic

    # Wire Gateway processor + start pollers (#2, #3)
    if gateway_mgr is not None:

        def _gateway_processor(content: str) -> str:
            """Process inbound gateway message via AgenticLoop."""
            result = agentic.run(content)
            return result.text if result and result.text else ""

        gateway_mgr.set_processor(_gateway_processor)
        gateway_mgr.start()
        log.info("Gateway pollers started")

    # Initialize session meter for status line
    from core.ui.agentic_ui import init_session_meter

    init_session_meter(model=agentic.model)

    # GAP 5: Detect resumable sessions at startup
    try:
        from core.cli.session_checkpoint import SessionCheckpoint

        _resumable = SessionCheckpoint().list_resumable()
        if _resumable:
            _top = _resumable[0]
            _label = _top.user_input[:60] if _top.user_input else _top.session_id
            console.print(f"  [info]Resumable session detected:[/info] {_label}")
            console.print(
                f"  [muted]Type /resume to see details, "
                f"or /resume {_top.session_id} to restore.[/muted]"
            )
            console.print()
    except Exception:
        log.debug("Session resume detection skipped", exc_info=True)

    while True:
        # Defensive: restore terminal state before each prompt
        # (Rich Status/Live may leave cursor hidden or echo off)
        console.show_cursor(True)

        try:
            user_input = _read_multiline_input("[header]>[/header] ")
        except (KeyboardInterrupt, EOFError):
            from core.ui.agentic_ui import render_session_cost_summary

            agentic.mark_session_completed()
            render_session_cost_summary()
            console.print("\n  [muted]Goodbye.[/muted]\n")
            break

        if not user_input:
            continue

        # Bare exit/quit -> immediate shutdown (no LLM round-trip)
        if user_input.strip().lower() in ("exit", "quit", "q"):
            from core.ui.agentic_ui import render_session_cost_summary

            agentic.mark_session_completed()
            render_session_cost_summary()
            console.print("  [muted]Goodbye.[/muted]\n")
            break

        # Multi-line paste -> always route to agentic (never slash-dispatch)
        is_multiline = "\n" in user_input
        if not is_multiline and user_input.startswith("/"):
            # Slash command -> deterministic routing (OpenClaw Binding)
            cmd = user_input.split()[0].lower()
            args = user_input[len(cmd) :].strip()
            should_break, verbose, resume_state = _handle_command(
                cmd,
                args,
                verbose,
                skill_registry=skill_registry,
                mcp_manager=mcp_mgr,
            )
            if should_break:
                break
            # /resume: inject saved messages into ConversationContext
            if resume_state is not None:
                conversation.messages = list(resume_state.messages)
                agentic._session_id = resume_state.session_id
                log.info(
                    "Session restored: %s (%d messages)",
                    resume_state.session_id,
                    len(resume_state.messages),
                )
            # Update handlers if verbose changed
            if verbose != (handlers.get("_verbose_flag") is True):
                handlers = _build_tool_handlers(
                    verbose=verbose,
                    mcp_manager=mcp_mgr,
                    agentic_ref=agentic_ref,
                    skill_registry=skill_registry,
                )
                sub_mgr = _build_sub_agent_manager(
                    verbose=verbose,
                    action_handlers=handlers,
                    mcp_manager=mcp_mgr,
                    skill_registry=skill_registry,
                )
                executor = ToolExecutor(
                    action_handlers=handlers,
                    mcp_manager=mcp_mgr,
                    sub_agent_manager=sub_mgr,
                )
                agentic = AgenticLoop(
                    conversation,
                    executor,
                    mcp_manager=mcp_mgr,
                    skill_registry=skill_registry,
                )
                agentic_ref[0] = agentic
        else:
            # Agentic loop: multi-turn + multi-intent
            try:
                result = agentic.run(user_input)
                _render_agentic_result(result)
                # Claude Code-style status line after each result
                from core.ui.agentic_ui import render_status_line

                render_status_line()
            except KeyboardInterrupt:
                console.show_cursor(True)
                console.print("\n  [dim]Interrupted.[/dim]\n")
            except Exception as exc:
                console.show_cursor(True)
                log.error("Agentic loop error: %s", exc, exc_info=True)
                console.print(f"\n  [error]Error: {exc}[/error]\n")

    # Clean shutdown: Gateway -> MCP servers -> SchedulerService
    if gateway_mgr is not None:
        try:
            gateway_mgr.stop()
        except Exception:
            log.debug("Gateway shutdown error", exc_info=True)

    if mcp_mgr is not None:
        try:
            mcp_mgr.shutdown()
        except Exception:
            log.debug("MCP shutdown error", exc_info=True)

    _sched = _scheduler_service_ctx.get(None)
    if _sched is not None:
        try:
            _sched.save()
            _sched.stop()
        except Exception:
            log.debug("SchedulerService shutdown error", exc_info=True)
