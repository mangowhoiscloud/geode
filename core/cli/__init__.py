"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  → commands.py (Binding Router: deterministic dispatch)
  free-text → agentic_loop.py (AgenticLoop: multi-turn tool_use loop)
              → search.py (IP Search Engine: keyword matching)
"""

from __future__ import annotations

import logging
import signal
import sys
import termios
from pathlib import Path
from typing import Any

import typer

from core import __version__
from core.agent.conversation import ConversationContext
from core.cli.commands import (
    cmd_apply,
    cmd_auth,
    cmd_batch,
    cmd_context,
    cmd_generate,
    cmd_key,
    cmd_list,
    cmd_mcp,
    cmd_model,
    cmd_schedule,
    cmd_skills,
    cmd_trigger,
    resolve_action,
    show_help,
)
from core.cli.pipeline_executor import _build_initial_state as _build_initial_state
from core.cli.pipeline_executor import _execute_pipeline as _execute_pipeline
from core.cli.pipeline_executor import _execute_pipeline_streaming as _execute_pipeline_streaming
from core.cli.pipeline_executor import _render_result as _render_result
from core.cli.pipeline_executor import _render_verification as _render_verification
from core.cli.pipeline_executor import _resolve_ip_name as _resolve_ip_name
from core.cli.pipeline_executor import _run_analysis as _run_analysis
from core.cli.report_renderer import (
    _build_skill_narrative as _build_skill_narrative,
)
from core.cli.report_renderer import (
    _generate_report as _generate_report,
)
from core.cli.report_renderer import (
    _parse_report_args as _parse_report_args,
)
from core.cli.report_renderer import (
    _state_to_report_dict as _state_to_report_dict,
)
from core.cli.session_state import _get_last_result as _get_last_result
from core.cli.session_state import _get_readiness as _get_readiness
from core.cli.session_state import _get_search_engine as _get_search_engine
from core.cli.session_state import _result_cache as _result_cache
from core.cli.session_state import _ResultCache as _ResultCache
from core.cli.session_state import _scheduler_service_ctx as _scheduler_service_ctx
from core.cli.session_state import _set_last_result as _set_last_result
from core.cli.session_state import _set_readiness as _set_readiness
from core.cli.startup import (
    ReadinessReport,
    auto_generate_env,
    check_readiness,
    env_setup_wizard,
    render_readiness,
    setup_project_memory,
    setup_user_profile,
)
from core.cli.tool_handlers import (
    _build_tool_handlers as _build_tool_handlers,
)
from core.cli.ui.console import console
from core.cli.ui.status import GeodeStatus
from core.config import settings
from core.hooks import HookEvent, HookSystem
from core.llm.commentary import (
    generate_commentary,
)

log = logging.getLogger(__name__)

# Hook system module-level variable for memory event firing (P1.5)
_hooks_ctx: HookSystem | None = None


def _fire_hook(event: HookEvent, data: dict[str, Any]) -> None:
    """Fire a hook event if HookSystem is available in context."""
    hooks = _hooks_ctx
    if hooks is not None:
        try:
            hooks.trigger(event, data)
        except Exception:
            log.debug("Failed to fire hook %s", event, exc_info=True)


def _drain_scheduler_queue(
    *,
    action_queue: Any,
    services: Any,
    runner: Any,
    session_lane: Any,
    global_lane: Any,
    force_isolated: bool = False,
    main_loop: Any | None = None,
    on_complete: Any | None = None,
    on_dispatch: Any | None = None,
    on_skip: Any | None = None,
    on_main_run: Any | None = None,
) -> int:
    """Drain pending scheduled jobs from the action queue.

    Shared by both REPL and serve modes.  In serve mode ``force_isolated``
    is True because there is no interactive main session to inject into.

    Uses SessionLane (per-key serial) + Global Lane (capacity) for
    concurrency control through the unified LaneQueue.

    Returns the number of jobs drained.
    """
    import queue as _q

    from core.orchestration.isolated_execution import IsolationConfig

    count = 0
    try:
        while True:
            job_id, fired_action, isolated = action_queue.get_nowait()
            if not fired_action:
                continue
            count += 1
            prompt = f"[scheduled-job:{job_id}] {fired_action}"

            if isolated or force_isolated:
                lane_key = f"sched:{job_id}"

                # Dual acquire: session (per-key serial) + global (capacity)
                if not session_lane.try_acquire(lane_key):
                    log.warning("Session key busy, skipping job %s", job_id)
                    if on_skip:
                        on_skip(job_id)
                    continue

                if not global_lane.try_acquire(lane_key):
                    session_lane.manual_release(lane_key)
                    log.warning("Global lane full, skipping job %s", job_id)
                    if on_skip:
                        on_skip(job_id)
                    continue

                _lanes_acquired = True
                try:
                    _iso_conv = ConversationContext()
                    from core.gateway.shared_services import SessionMode

                    _, _iso_loop = services.create_session(
                        SessionMode.SCHEDULER,
                        conversation=_iso_conv,
                        propagate_context=True,
                    )
                    _cap_loop = _iso_loop
                    _cap_prompt = prompt
                    _cap_jid = job_id
                    _cap_sess = session_lane
                    _cap_glob = global_lane
                    _cap_key = lane_key
                    _cap_cb = on_complete

                    def _run_isolated(
                        *,
                        _loop: Any = _cap_loop,
                        _p: str = _cap_prompt,
                        _jid: str = _cap_jid,
                        _sess: Any = _cap_sess,
                        _glob: Any = _cap_glob,
                        _key: str = _cap_key,
                        _cb: Any = _cap_cb,
                    ) -> str:
                        try:
                            r = _loop.run(_p)
                            if _cb:
                                _cb(r, job_id=_jid)
                            return r.text if r and r.text else ""
                        finally:
                            _glob.manual_release(_key)
                            _sess.manual_release(_key)

                    runner.run_async(
                        _run_isolated,
                        config=IsolationConfig(
                            prefix=f"scheduled:{job_id}",
                            post_to_main=False,
                            timeout_s=300.0,
                        ),
                    )
                    _lanes_acquired = False  # ownership transferred to _run_isolated
                    if on_dispatch:
                        on_dispatch(job_id)
                except Exception:
                    if _lanes_acquired:
                        global_lane.manual_release(lane_key)
                        session_lane.manual_release(lane_key)
                    log.warning("Scheduler job %s dispatch failed", job_id, exc_info=True)
            else:
                # Non-isolated: inject into main session (REPL only)
                if main_loop is not None:
                    if on_main_run:
                        on_main_run(job_id)
                    try:
                        main_loop.run(prompt)
                    except Exception:
                        log.warning("Scheduler job %s main-loop failed", job_id, exc_info=True)
    except _q.Empty:
        pass
    return count


app = typer.Typer(
    name="geode",
    help=f"GEODE v{__version__} — 범용 자율 실행 에이전트",
    no_args_is_help=False,
    invoke_without_command=True,
)

# ---------------------------------------------------------------------------
# Interactive welcome screen
# ---------------------------------------------------------------------------


def _render_welcome_brand() -> None:
    """Render animated Claude Code-style branding with axolotl mascot."""
    from core.cli.ui.mascot import play_mascot_animation

    cwd = str(Path.cwd())
    play_mascot_animation(version=__version__, model=settings.model, cwd=cwd)

    # Show detected project environment
    try:
        from core.cli.project_detect import detect_project_type, get_harness_summary

        info = detect_project_type(Path.cwd())
        parts: list[str] = []
        if info.project_type != "unknown":
            parts.append(f"[label]{info.project_type}[/label]")
            if info.pkg_mgr:
                parts.append(f"({info.pkg_mgr})")
        if info.harnesses:
            parts.append(f"[muted]harness:[/muted] {get_harness_summary(info.harnesses)}")
        if parts:
            console.print(f"  {' '.join(parts)}")
    except Exception:  # noqa: S110
        pass  # Startup display — never block on detection failure


def _render_readiness_compact(report: ReadinessReport) -> None:
    """Render readiness as a compact block."""
    ready = [c for c in report.capabilities if c.available]
    not_ready = [c for c in report.capabilities if not c.available]

    if ready:
        names = "  ".join(f"[success]✓[/success] {c.name}" for c in ready)
        console.print(f"  {names}")
    if not_ready:
        for c in not_ready:
            hint = f" [muted]({c.reason})[/muted]" if c.reason else ""
            console.print(f"  [warning]✗[/warning] {c.name}{hint}")

    if report.blocked:
        console.print()
        console.print("  [warning]API key not configured — key registration required[/warning]")

    console.print()


def _suppress_noisy_warnings() -> None:
    """Suppress known noisy warnings from dependencies."""
    import warnings

    # Pydantic V1 deprecation from langchain_core on Python 3.14+
    warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
    # LangGraph msgpack deserialization warning (warnings.warn path)
    warnings.filterwarnings("ignore", message="Deserializing unregistered type")

    # LangGraph checkpoint deserialization also logs via logging.warning —
    # suppress those at the logging level.
    for noisy_logger in (
        "langgraph.checkpoint.serde.jsonplus",
        "langgraph.checkpoint.serde.base",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.ERROR)


def _welcome_screen() -> None:
    """Show Claude Code-style welcome screen with readiness check."""
    _suppress_noisy_warnings()
    _render_welcome_brand()

    # Auto-generate .env from .env.example (placeholder → empty)
    auto_generate_env()

    # .env setup wizard — runs when .env is absent and no API keys set
    env_path = Path(".env")
    if not env_path.exists():
        from core.cli.startup import _has_any_llm_key

        if not _has_any_llm_key():
            env_setup_wizard()

    # OpenClaw gateway:startup — readiness check
    readiness = check_readiness()
    _set_readiness(readiness)
    _render_readiness_compact(readiness)

    # OpenClaw boot-md — initialize project memory if absent
    setup_project_memory()

    # Tier 0.5 — initialize user profile if absent
    setup_user_profile()

    console.print(
        "  [muted]/help[/muted] for commands  [muted]·[/muted]  [muted]type naturally[/muted]"
    )
    console.print()


# ---------------------------------------------------------------------------
# Search result rendering
# ---------------------------------------------------------------------------


def _render_search_results(query: str, results: list[Any]) -> None:
    """Render IP search results."""
    console.print()
    console.print(f"  [header]Search: '{query}'[/header]")

    if not results:
        console.print("  [muted]No matching IPs found.[/muted]")
        console.print()
        return

    for r in results:
        bar_len = int(r.score * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        style = "success" if r.score >= 0.5 else "muted"
        console.print(
            f"    [{style}]{bar}[/{style}] [dim]relevance[/dim] {r.score:.0%}"
            f"  [value]{r.ip_name}[/value]"
        )
        console.print(f"      [muted]matched: {', '.join(r.matches[:5])}[/muted]")
    console.print()


# ---------------------------------------------------------------------------
# Thin CLI + serve — OpenClaw-style gateway routing
# ---------------------------------------------------------------------------


def _handle_command(
    cmd: str,
    args: str,
    verbose: bool,
    *,
    skill_registry: Any = None,
    mcp_manager: Any = None,
) -> tuple[bool, bool, Any]:
    """Handle a slash command. Returns (should_break, new_verbose, resume_state)."""
    from core.cli._helpers import parse_dry_run_flag

    action = resolve_action(cmd)

    if action == "quit":
        from core.cli.ui.agentic_ui import render_session_cost_summary

        render_session_cost_summary()
        console.print("  [muted]Goodbye.[/muted]\n")
        return True, verbose, None

    if action == "help":
        show_help()
    elif action == "cost":
        from core.cli.commands import cmd_cost

        cmd_cost(args)
    elif action == "list":
        cmd_list()
    elif action == "verbose":
        verbose = not verbose
        state = "[success]ON[/success]" if verbose else "[muted]OFF[/muted]"
        console.print(f"  Verbose: {state}")
        console.print()
    elif action in ("analyze", "run"):
        # Default: live LLM. Dry-run only when no API key or explicitly requested.
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        # Support "--dry-run" flag in slash command args
        dry_flag, args = parse_dry_run_flag(args)
        if dry_flag:
            force_dry = True
        if force_dry and readiness is not None and not readiness.force_dry_run:
            console.print("  [info]Dry-run mode (explicitly requested)[/info]")
        elif force_dry:
            console.print("  [warning]API key not configured — forcing dry-run mode[/warning]")
        if not args:
            console.print(f"  [warning]Usage: /{action} <IP name>[/warning]")
        else:
            _run_analysis(args, dry_run=force_dry, verbose=verbose)
    elif action == "search":
        if not args:
            console.print("  [warning]Usage: /search <query>[/warning]")
        else:
            results = _get_search_engine().search(args)
            _render_search_results(args, results)
    elif action == "key":
        changed = cmd_key(args)
        if changed:
            new_readiness = check_readiness()
            _set_readiness(new_readiness)
            render_readiness(new_readiness)
    elif action == "model":
        cmd_model(args)
    elif action == "auth":
        cmd_auth(args)
    elif action == "generate":
        cmd_generate(args)
    elif action == "report":
        if not args:
            console.print(
                "  [warning]Usage: /report <IP name>"
                " [html|json|md] [summary|detailed|executive][/warning]"
            )
        else:
            dry_flag, clean_args = parse_dry_run_flag(args)
            report_args = _parse_report_args(clean_args.split())
            readiness = _get_readiness()
            report_dry = readiness.force_dry_run if readiness else True
            if dry_flag:
                report_dry = True
            _generate_report(
                report_args["ip_name"],
                fmt=report_args["fmt"],
                template=report_args["template"],
                dry_run=report_dry,
                verbose=verbose,
                skill_registry=skill_registry,
            )
    elif action == "batch":
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        dry_flag, args = parse_dry_run_flag(args)
        if dry_flag:
            force_dry = True
        cmd_batch(
            args,
            run_fn=_run_analysis,
            dry_run=force_dry,
            verbose=verbose,
        )
    elif action == "schedule":
        cmd_schedule(args, scheduler_service=_scheduler_service_ctx.get(None))
    elif action == "trigger":
        cmd_trigger(args)
    elif action == "status":
        console.print()
        console.print("  [header]GEODE System Status[/header]")
        console.print(f"  Model: [bold]{settings.model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_ok = bool(settings.anthropic_api_key)
        oai_ok = bool(settings.openai_api_key)
        ant_status = "[green]configured[/green]" if ant_ok else "[red]not set[/red]"
        oai_status = "[green]configured[/green]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic API: {ant_status}")
        console.print(f"  OpenAI API: {oai_status}")
        readiness = _get_readiness()
        if readiness:
            mode = "Full LLM" if not readiness.force_dry_run else "Dry-Run Only"
            console.print(f"  Mode: [bold]{mode}[/bold]")
        from core.domains.game_ip.fixtures import FIXTURE_MAP as _FM

        console.print(f"  Fixtures: [bold]{len(_FM)} IPs[/bold]")

        # MCP status section
        _mcp_st = (
            mcp_manager.get_status()
            if mcp_manager is not None
            else {"active": [], "available_inactive": []}
        )
        console.print()
        console.print("  [header]MCP Servers[/header]")
        for srv in _mcp_st["active"]:
            _desc = f" -- {srv['description']}" if srv["description"] else ""
            console.print(f"    [green]OK[/green] {srv['name']} [dim]{_desc}[/dim]")
        if not _mcp_st["active"]:
            console.print("    [muted]No active servers[/muted]")
        if _mcp_st["available_inactive"]:
            console.print()
            console.print("  [header]MCP Available (env missing)[/header]")
            for srv in _mcp_st["available_inactive"]:
                _env = ", ".join(srv["missing_env"])
                console.print(f"    [yellow]--[/yellow] {srv['name']} [dim]needs: {_env}[/dim]")
        console.print()
    elif action == "compare":
        parts = args.strip().split()
        if len(parts) < 2:
            console.print("  [warning]Usage: /compare <IP_A> <IP_B>[/warning]")
        else:
            dry_flag, _clean_compare = parse_dry_run_flag(args)
            clean_parts = [p for p in parts if p not in ("--dry-run", "--dry_run")]
            if len(clean_parts) < 2:
                console.print("  [warning]Usage: /compare <IP_A> <IP_B>[/warning]")
            else:
                ip_a, ip_b = clean_parts[0], clean_parts[1]
                console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
                readiness = _get_readiness()
                force_dry = readiness.force_dry_run if readiness else True
                if dry_flag:
                    force_dry = True
                _run_analysis(ip_a, dry_run=force_dry, verbose=verbose)
                _run_analysis(ip_b, dry_run=force_dry, verbose=verbose)
    elif action == "mcp":
        cmd_mcp(args, mcp_manager=mcp_manager)
    elif action == "skills":
        if skill_registry is not None:
            cmd_skills(skill_registry, args)
        else:
            console.print("  [muted]Skills not loaded.[/muted]")
            console.print()
    elif action == "skill_invoke":
        # /skill <name> [args] — invoke a skill with optional arguments
        if skill_registry is not None:
            from core.cli.commands import cmd_skill_invoke

            cmd_skill_invoke(skill_registry, args)
        else:
            console.print("  [muted]Skills not loaded.[/muted]")
            console.print()
    elif action == "resume":
        from core.cli.commands import cmd_resume

        resume_state = cmd_resume(args)
        return False, verbose, resume_state
    elif action == "context":
        cmd_context(args)
    elif action == "apply":
        cmd_apply(args)
    elif action == "compact":
        from core.cli.commands import cmd_compact

        cmd_compact(args)
    elif action == "clear":
        from core.cli.commands import cmd_clear

        cmd_clear(args)
    elif action in ("tasks", "task"):
        from core.cli.commands import cmd_tasks

        cmd_tasks(args)
    else:
        console.print(f"  [warning]Unknown command: {cmd}[/warning]")
        console.print("  [muted]Type /help for available commands.[/muted]")
        console.print()

    return False, verbose, None


def _show_commentary(
    user_text: str, action: str, context: dict[str, Any], *, is_offline: bool
) -> None:
    """Generate and display LLM commentary after tool call results."""
    if is_offline:
        return
    with GeodeStatus("Generating response...", model=settings.model) as status:
        text = generate_commentary(user_query=user_text, action=action, context=context)
        status.stop("response" if text else "response (skipped)")
    if text:
        console.print()
        console.print(f"  {text}")
        console.print()


def _handle_memory_action(intent: Any, user_text: str, is_offline: bool) -> None:
    """Handle memory-related actions (P0-A + P1-B).

    Accepts either an object with an `args` dict attribute, or a plain dict.
    """
    args = intent if isinstance(intent, dict) else intent.args

    # Determine sub-action from tool routing
    rule_action = args.get("rule_action")
    query = args.get("query")
    key = args.get("key")
    content = args.get("content")

    if rule_action:
        # manage_rule tool
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if rule_action == "list":
            rules = mem.list_rules()
            console.print()
            console.print("  [header]Active Analysis Rules[/header]")
            if not rules:
                console.print("  [muted]No rules found.[/muted]")
            for r in rules:
                paths_str = ", ".join(r.get("paths", []))
                console.print(f"  - [value]{r['name']}[/value] ({paths_str})")
                if r.get("preview"):
                    console.print(f"    [muted]{r['preview'][:80]}...[/muted]")
            console.print()
        elif rule_action == "create":
            name = args.get("name", "")
            paths = args.get("paths", [])
            rule_content = content or ""
            if not name:
                console.print("  [warning]Rule name is required.[/warning]")
                return
            ok = mem.create_rule(name, paths, rule_content)
            if ok:
                console.print(f"  [success]Rule '{name}' created.[/success]")
                from core.hooks import HookEvent

                _fire_hook(HookEvent.RULE_CREATED, {"name": name, "paths": paths})
            else:
                console.print(
                    f"  [warning]Failed to create rule '{name}' (may already exist).[/warning]"
                )
            console.print()
        elif rule_action == "update":
            name = args.get("name", "")
            rule_content = content or ""
            if not name:
                console.print("  [warning]Rule name is required.[/warning]")
                return
            ok = mem.update_rule(name, rule_content)
            if ok:
                console.print(f"  [success]Rule '{name}' updated.[/success]")
                from core.hooks import HookEvent

                _fire_hook(HookEvent.RULE_UPDATED, {"name": name})
            else:
                console.print(f"  [warning]Failed to update rule '{name}'.[/warning]")
            console.print()
        elif rule_action == "delete":
            name = args.get("name", "")
            if not name:
                console.print("  [warning]Rule name is required.[/warning]")
                return
            ok = mem.delete_rule(name)
            if ok:
                console.print(f"  [success]Rule '{name}' deleted.[/success]")
                from core.hooks import HookEvent

                _fire_hook(HookEvent.RULE_DELETED, {"name": name})
            else:
                console.print(f"  [warning]Rule '{name}' not found.[/warning]")
            console.print()

    elif query:
        # memory_search tool
        from core.tools.memory_tools import MemorySearchTool

        search_tool = MemorySearchTool()
        tier = args.get("tier", "all")
        search_result = search_tool.execute(query=query, tier=tier)
        matches = search_result.get("result", {}).get("matches", [])
        console.print()
        console.print(f"  [header]Memory Search: '{query}'[/header]")
        if not matches:
            console.print("  [muted]No matches found.[/muted]")
        for m in matches:
            tier_label = m.get("tier", "?")
            source = m.get("source", m.get("session_id", ""))
            console.print(f"  - [{tier_label}] {source}")
            if "matching_lines" in m:
                for line in m["matching_lines"][:3]:
                    console.print(f"    [muted]{line}[/muted]")
            if "preview" in m:
                console.print(f"    [muted]{m['preview'][:80]}...[/muted]")
        console.print()

    elif key and content:
        # memory_save tool
        from core.tools.memory_tools import MemorySaveTool

        save_tool = MemorySaveTool()
        save_result = save_tool.execute(
            session_id=key,
            data={"content": content},
            persistent=True,
        )
        saved = save_result.get("result", {}).get("saved", False)
        if saved:
            console.print(f"  [success]Saved to memory: '{key}'[/success]")
            from core.hooks import HookEvent

            _fire_hook(HookEvent.MEMORY_SAVED, {"key": key})
        else:
            console.print("  [warning]Failed to save to memory.[/warning]")
        console.print()

    else:
        console.print()
        console.print("  [muted]Memory command not recognized. Try:[/muted]")
        console.print("  [muted]  '이전 분석 결과 검색해' — search memory[/muted]")
        console.print("  [muted]  '규칙 목록 보여줘' — list rules[/muted]")
        console.print("  [muted]  '이 결과 기억해' — save to memory[/muted]")
        console.print()


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
        # Non-TTY or stdin not available — nothing to restore
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
    renderer redraw after deletion — fixes wide-char (Korean jamo) ghost
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
# Thin REPL — delegates to geode serve via IPC
# ---------------------------------------------------------------------------


_LOCAL_COMMANDS = frozenset({"/help"})

# Commands that need TTY interaction locally, then relay the result to serve
_TTY_LOCAL_COMMANDS = frozenset({"/model", "/auth"})


def _thin_interactive_loop(
    *,
    resume_session: str = "",
    continue_latest: bool = False,
) -> None:
    """Thin CLI client — all execution delegated to geode serve via IPC.

    Local commands: /help
    Everything else (including /quit, /exit, /clear, /compact): relayed to serve
    """
    from core.cli.ipc_client import IPCClient

    client = IPCClient()
    if not client.connect():
        console.print("  [error]Failed to connect to serve[/error]")
        return

    console.print(f"  [success]Session: {client.session_id}[/success]")

    # Resume a previous session if requested
    if resume_session or continue_latest:
        result = client.request_resume(
            session_id=resume_session,
            continue_latest=continue_latest,
        )
        if result.get("type") == "resumed":
            sid = result.get("session_id", "")
            rnd = result.get("round_idx", 0)
            msgs = result.get("message_count", 0)
            model = result.get("model", "")
            console.print(
                f"  [success]Resumed:[/success] {sid}"
                f"  [muted](round {rnd}, {msgs} messages, {model})[/muted]"
            )
        else:
            console.print(f"  [warning]{result.get('message', 'Resume failed')}[/warning]")
    console.print()

    try:
        while True:
            console.show_cursor(True)
            try:
                user_input = _read_multiline_input("[header]>[/header] ")
            except (KeyboardInterrupt, EOFError):
                console.print("\n  [muted]Goodbye.[/muted]\n")
                break

            if not user_input:
                continue

            if user_input.strip().lower() in ("exit", "quit", "q"):
                # Relay /quit to serve for session cost summary
                response = client.send_command("/quit", "")
                output = response.get("output", "")
                if output:
                    import sys as _sys

                    _sys.stdout.write(output)
                    _sys.stdout.flush()
                break

            # Slash commands
            if "\n" not in user_input and user_input.startswith("/"):
                cmd = user_input.split()[0].lower()
                args = user_input[len(cmd) :].strip()

                # Local-only commands
                if cmd in _LOCAL_COMMANDS:
                    try:
                        _handle_command(cmd, args, False)
                    except (SystemExit, EOFError):
                        break
                    continue

                # /model (no args): interactive picker locally, then relay
                if cmd in _TTY_LOCAL_COMMANDS and not args:
                    if cmd == "/model":
                        import sys as _sys

                        from core.cli.commands import _interactive_model_picker

                        if _sys.stdin.isatty():
                            _interactive_model_picker()
                            # Relay to serve (suppress — picker already printed)
                            from core.config import settings

                            client.send_command("/model", settings.model)
                        else:
                            response = client.send_command(cmd, args)
                            output = response.get("output", "")
                            if output:
                                _sys.stdout.write(output)
                                _sys.stdout.flush()
                    else:
                        response = client.send_command(cmd, args)
                        output = response.get("output", "")
                        if output:
                            import sys as _sys

                            _sys.stdout.write(output)
                            _sys.stdout.flush()
                    continue

                # /clear: auto-force in IPC mode (no stdin for confirmation on serve)
                if cmd == "/clear" and "--force" not in args:
                    args = (args + " --force").strip()

                # All other commands → relay to serve
                response = client.send_command(cmd, args)
                # Render captured output from serve (ANSI-styled text)
                output = response.get("output", "")
                if output:
                    import sys as _sys

                    _sys.stdout.write(output)
                    _sys.stdout.flush()
                if response.get("status") == "error":
                    console.print(f"  [error]{response.get('message', 'Command failed')}[/error]")
                elif response.get("should_break"):
                    break
                continue

            # Free text → relay as prompt (client-side direct rendering)
            from core.cli.ui.event_renderer import EventRenderer

            _renderer = EventRenderer()
            _stream_started = False
            _r = _renderer  # bind for closures (B023)

            def _on_stream(data: str, *, _rr: Any = _r) -> None:
                nonlocal _stream_started
                _stream_started = True
                _rr.on_stream(data)

            def _on_event(event: dict[str, object], *, _rr: Any = _r) -> None:
                nonlocal _stream_started
                _stream_started = True
                _rr.on_event(event)

            _renderer.start_activity()  # persistent spinner until result
            response = client.send_prompt(
                user_input,
                on_stream=_on_stream,
                on_event=_on_event,
            )
            _renderer.stop()
            if response.get("type") == "error" and "Connection lost" in response.get("message", ""):
                console.print("\n  [error]Connection to serve lost[/error]\n")
                break
            _render_ipc_response(response, streamed=_stream_started)
    finally:
        client.close()


def _render_ipc_response(response: dict[str, Any], *, streamed: bool = False) -> None:
    """Render an IPC response from serve.

    When *streamed* is True, the agentic UI (tool calls, token usage) was
    already rendered in real-time via streaming events — only the final
    text response needs rendering.
    """
    rtype = response.get("type", "")

    if rtype == "error":
        console.print(f"\n  [error]{response.get('message', 'Unknown error')}[/error]\n")
        return

    if rtype == "result":
        if not streamed:
            # Fallback: no streaming happened — show tool call summary
            tool_calls = response.get("tool_calls", [])
            for tc in tool_calls:
                console.print(f"  [dim]\u25b8 {tc.get('name', '?')}[/dim]")

        # Main text (always render — this is the LLM's final response)
        text = response.get("text", "")
        if text:
            from rich.markdown import Markdown

            console.print()
            console.print(Markdown(text))
            console.print()

        if not streamed:
            # Fallback status line when streaming wasn't available
            model = response.get("model", "")
            rounds = response.get("rounds", 0)
            tool_calls = response.get("tool_calls", [])
            parts = []
            if model:
                parts.append(f"\u2722 {model}")
            if rounds:
                parts.append(f"{rounds} rounds")
            if tool_calls:
                parts.append(f"{len(tool_calls)} tools")
            if parts:
                console.print(f"  [dim]{' · '.join(parts)}[/dim]")
        return

    # Fallback: unexpected response type
    console.print(f"\n  [dim]{response}[/dim]\n")


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    continue_session: bool = typer.Option(
        False, "--continue", help="Resume the most recent session"
    ),
    resume: str = typer.Option("", "--resume", help="Resume a specific session by ID"),
) -> None:
    """GEODE — Autonomous Research Harness."""
    if ctx.invoked_subcommand is None:
        _welcome_screen()

        # Ensure serve is running (auto-start if needed)
        from core.cli.ipc_client import is_serve_running, start_serve_if_needed

        if not is_serve_running():
            from core.cli.ui.status import TextSpinner

            spinner = TextSpinner("Starting serve...")
            spinner.start()
            ready = start_serve_if_needed(timeout_s=30)
            spinner.stop()
            if not ready:
                console.print("  [error]Failed to start geode serve[/error]")
                console.print("  [dim]Try manually: geode serve &[/dim]")
                raise typer.Exit(1)

        console.print("  [muted]Connected to serve via IPC[/muted]")
        _thin_interactive_loop(
            resume_session=resume,
            continue_latest=continue_session,
        )


@app.command()
def analyze(
    ip_name: str = typer.Argument(..., help="IP name to analyze (e.g. 'Cowboy Bebop')"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run without LLM calls (fixture data only)"
    ),
    skip_verification: bool = typer.Option(
        False, "--skip-verification", help="Skip guardrails and BiasBuster"
    ),
    pipeline: str = typer.Option("full_pipeline", "--pipeline", "-p", help="Pipeline mode"),
    stream: bool = typer.Option(False, "--stream", help="Enable streaming output"),
    domain: str = typer.Option("game_ip", "--domain", "-d", help="Domain adapter name"),
) -> None:
    """Analyze an IP for undervaluation potential."""
    _run_analysis(
        ip_name,
        dry_run=dry_run,
        verbose=verbose,
        skip_verification=skip_verification,
        stream=stream,
        domain_name=domain,
    )


@app.command()
def report(
    ip_name: str = typer.Argument(..., help="IP name to generate report for"),
    fmt: str = typer.Option("md", "--format", "-f", help="Output format: md, html, json"),
    template: str = typer.Option(
        "summary", "--template", "-t", help="summary, detailed, executive"
    ),
    output: str = typer.Option(None, "--output", "-o", help="Save report to file"),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run", help="Use fixture data (no LLM)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """Generate a report for an IP analysis."""
    resolved_fmt = "markdown" if fmt == "md" else fmt
    _generate_report(
        ip_name,
        fmt=resolved_fmt,
        template=template,
        output=output or None,
        dry_run=dry_run,
        verbose=verbose,
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (e.g. 'dark fantasy', '소울라이크')"),
) -> None:
    """Search IPs by keyword or genre."""
    results = _get_search_engine().search(query)
    _render_search_results(query, results)


@app.command()
def version() -> None:
    """Show GEODE version."""
    console.print(f"GEODE v{__version__}")


@app.command(name="list")
def list_ips() -> None:
    """List available IP fixtures."""
    from core.domains.game_ip.fixtures import FIXTURE_MAP as _FIXTURE_MAP

    console.print("[header]Available IPs:[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"  - {name.title()}")


@app.command()
def batch(
    top: int = typer.Option(10, help="Number of IPs to analyze"),
    genre: str = typer.Option(None, help="Filter by genre"),
    concurrency: int = typer.Option(2, help="Parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run/--live", help="Use dry-run mode"),
) -> None:
    """Run batch analysis on multiple IPs."""
    from core.cli.batch import render_batch_table, run_batch

    results = run_batch(top=top, genre=genre, concurrency=concurrency, dry_run=dry_run)
    if results:
        render_batch_table(results)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config.toml"),
) -> None:
    """Initialize .geode/ project structure with template config.

    Auto-detects project type (Node/Python/Rust/Go/Java) and generates
    config.toml with build/test/lint commands + Claude Code hook templates.
    Pattern: harness-for-real init.sh
    """
    import json

    from core.cli.project_detect import (
        detect_project_type,
        generate_config_toml,
        generate_hooks,
        generate_settings_json_hooks,
    )
    from core.memory.project import ProjectMemory
    from core.memory.user_profile import FileBasedUserProfile

    project_mem = ProjectMemory(Path("."))
    user_profile = FileBasedUserProfile()

    # 0. Global ~/.geode/ directory + .env (API key storage)
    global_geode = Path.home() / ".geode"
    global_geode.mkdir(parents=True, exist_ok=True)
    global_env = global_geode / ".env"
    if not global_env.exists():
        global_env.write_text(
            "# GEODE global API keys (shared across all projects)\n"
            "# Keys here are used when project-local .env is absent.\n"
            "# Priority: env vars > CWD/.env > ~/.geode/.env\n\n"
            "# ANTHROPIC_API_KEY=sk-ant-...\n"
            "# OPENAI_API_KEY=sk-proj-...\n"
            "# BRAVE_API_KEY=...\n",
            encoding="utf-8",
        )
        global_env.chmod(0o600)
        console.print(f"  Created {global_env} (global API keys)")

    # 1. Detect project type (harness-for-real init.sh pattern)
    project_info = detect_project_type(Path("."))
    console.print(
        f"  Detected project type: [bold]{project_info.project_type}[/bold]"
        f" ({project_info.pkg_mgr})"
        if project_info.pkg_mgr
        else ""
    )

    # 2. .geode/memory/ + .geode/rules/ (ProjectMemory)
    created_mem = project_mem.ensure_structure()
    if created_mem:
        console.print("  Created .geode/memory/ + .geode/rules/ structure")

    # 3. .geode/ directories
    geode_dirs = [
        # Agent memory (git-tracked)
        Path(".geode/memory"),
        Path(".geode/rules"),
        # C1: Project config
        Path(".geode/project"),
        # C2: Journal (append-only execution history)
        Path(".geode/journal"),
        Path(".geode/journal/transcripts"),
        # V0: Vault (purpose-routed artifact storage)
        Path(".geode/vault/profile"),
        Path(".geode/vault/research"),
        Path(".geode/vault/applications"),
        Path(".geode/vault/general"),
        # C3: Session (checkpoints, resumable)
        Path(".geode/session"),
        # C4: Plan (goals, pending tasks)
        Path(".geode/plan"),
        # Cache + outputs
        Path(".geode/cache"),
        Path(".geode/reports"),
        Path(".geode/snapshots"),
        Path(".geode/models"),
        # Legacy compat
        Path(".geode/sessions"),
        Path(".geode/result_cache"),
    ]
    for d in geode_dirs:
        d.mkdir(parents=True, exist_ok=True)
    console.print("  Created .geode/ directories")

    # 4. config.toml with detected project info
    config_path = Path(".geode/config.toml")
    if not config_path.exists() or force:
        config_content = generate_config_toml(project_info)
        config_path.write_text(config_content, encoding="utf-8")
        console.print("  Created .geode/config.toml (with detected commands)")
    else:
        console.print("  .geode/config.toml already exists (use --force to overwrite)")

    # 4b. routing.toml template
    routing_path = Path(".geode/routing.toml")
    if not routing_path.exists():
        routing_path.write_text(
            "# Node-level LLM model routing\n"
            "# Uncomment to override default model per pipeline node.\n\n"
            "[nodes]\n"
            '# analyst = "claude-opus-4-6"\n'
            '# evaluator = "claude-sonnet-4-6"\n'
            '# scoring = "claude-haiku-4-5-20251001"\n'
            '# synthesizer = "claude-opus-4-6"\n\n'
            "[agentic]\n"
            '# default = "claude-opus-4-6"\n'
            '# sub_agent = "claude-sonnet-4-6"\n',
            encoding="utf-8",
        )
        console.print("  Created .geode/routing.toml (template)")

    # 4c. model-policy.toml template
    policy_path = Path(".geode/model-policy.toml")
    if not policy_path.exists():
        policy_path.write_text(
            "# Model governance — allowlist/denylist\n"
            "# If allowlist is set, only listed models are allowed.\n"
            "# If only denylist is set, listed models are blocked.\n\n"
            "[policy]\n"
            "# allowlist = "
            '["claude-opus-4-6", "claude-sonnet-4-6", "gpt-5.4"]\n'
            "# denylist = "
            '["claude-haiku-4-5-20251001"]\n'
            '# default_model = "claude-sonnet-4-6"\n',
            encoding="utf-8",
        )
        console.print("  Created .geode/model-policy.toml (template)")

    # 5. Hook templates (harness-for-real pattern)
    hooks_dir = Path(".claude/hooks")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks = generate_hooks(project_info)
    for filename, content in hooks.items():
        hook_path = hooks_dir / filename
        if not hook_path.exists() or force:
            hook_path.write_text(content, encoding="utf-8")
            hook_path.chmod(0o755)
    if hooks:
        console.print(f"  Created .claude/hooks/ ({len(hooks)} hooks)")

    # 6. Register hooks in .claude/settings.json (merge, not overwrite)
    settings_path = Path(".claude/settings.json")
    hook_config = generate_settings_json_hooks()
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        # Merge hooks (don't overwrite existing permissions/other keys)
        if "hooks" not in existing:
            existing.update(hook_config)
            settings_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            console.print("  Registered hooks in .claude/settings.json")
        else:
            console.print("  .claude/settings.json hooks already configured")
    else:
        settings_path.write_text(
            json.dumps(hook_config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        console.print("  Created .claude/settings.json with hooks")

    # 7. ~/.geode/user_profile
    created_profile = user_profile.ensure_structure()
    if created_profile:
        console.print("  Created ~/.geode/user_profile/")

    # 7a. Seed project profile from global if absent
    try:
        project_profile_dir = Path(".geode/user_profile")
        global_profile_dir = user_profile.global_dir
        if (
            not project_profile_dir.exists()
            and isinstance(global_profile_dir, Path)
            and (global_profile_dir / "profile.md").exists()
        ):
            import shutil

            shutil.copytree(str(global_profile_dir), str(project_profile_dir))
            console.print("  Seeded .geode/user_profile/ from global profile")
    except OSError as e:
        log.debug("Profile seeding skipped: %s", e)

    # 7b. ~/.geode/identity/career.toml template
    identity_dir = Path.home() / ".geode" / "identity"
    career_toml = identity_dir / "career.toml"
    if not career_toml.exists():
        identity_dir.mkdir(parents=True, exist_ok=True)
        career_toml.write_text(
            "# Career identity — injected into system prompt context\n"
            "# Edit this file to personalize GEODE for job search / career tasks.\n\n"
            "[identity]\n"
            'title = ""\n'
            'experience = ""\n'
            "skills = []\n\n"
            "[goals]\n"
            'seeking = ""\n'
            "target_companies = []\n"
            'preferred_location = ""\n',
            encoding="utf-8",
        )
        console.print("  Created ~/.geode/identity/career.toml (template)")

    # 8. .gitignore entry
    _ensure_gitignore_entry(".geode/", "# GEODE")
    console.print("[green]GEODE project initialized.[/green]")


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of recent entries to show"),
    month: str = typer.Option(None, "--month", "-m", help="Month to show (YYYY-MM)"),
) -> None:
    """Show execution history and cost summary."""
    from datetime import date

    from rich.table import Table

    from core.llm.usage_store import UsageStore

    store = UsageStore()

    # Parse month
    if month:
        try:
            parts = month.split("-")
            year, mon = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            console.print(f"  [warning]Invalid month format: {month} (use YYYY-MM)[/warning]")
            return
    else:
        today = date.today()
        year, mon = today.year, today.month

    # Monthly summary
    summary = store.get_monthly_summary(year, mon)
    console.print()
    console.print(f"  [header]GEODE Usage Report -- {year:04d}-{mon:02d}[/header]")
    console.print()

    if summary["total_calls"] == 0:
        console.print("  [muted]No usage data for this month.[/muted]")
        console.print()
        return

    # Model breakdown table
    table = Table(show_header=True, padding=(0, 2), box=None)
    table.add_column("Model", style="label", min_width=22)
    table.add_column("Calls", justify="right", style="value")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right", style="bold")

    for model_name, stats in sorted(summary["by_model"].items()):
        in_k = stats["in"] / 1000
        out_k = stats["out"] / 1000
        table.add_row(
            model_name,
            str(int(stats["calls"])),
            f"{in_k:.1f}K",
            f"{out_k:.1f}K",
            f"${stats['cost']:.2f}",
        )

    # Total row
    table.add_section()
    total_in_k = summary["total_input_tokens"] / 1000
    total_out_k = summary["total_output_tokens"] / 1000
    table.add_row(
        "Total",
        str(summary["total_calls"]),
        f"{total_in_k:.1f}K",
        f"{total_out_k:.1f}K",
        f"${summary['total_cost']:.2f}",
    )

    console.print(table)
    console.print()

    # Recent records
    recent = store.get_recent_records(limit=limit)
    if recent:
        from datetime import datetime

        console.print(f"  [header]Recent LLM Calls (last {min(limit, len(recent))})[/header]")
        console.print()
        recent_table = Table(show_header=True, padding=(0, 2), box=None)
        recent_table.add_column("Time", style="muted", min_width=16)
        recent_table.add_column("Model", style="label", min_width=22)
        recent_table.add_column("In", justify="right")
        recent_table.add_column("Out", justify="right")
        recent_table.add_column("Cost", justify="right", style="bold")

        for rec in recent:
            dt = datetime.fromtimestamp(rec.ts)
            recent_table.add_row(
                dt.strftime("%m-%d %H:%M:%S"),
                rec.model,
                str(rec.input_tokens),
                str(rec.output_tokens),
                f"${rec.cost_usd:.4f}",
            )
        console.print(recent_table)
        console.print()


def _ensure_gitignore_entry(entry: str, comment: str = "") -> None:
    """Add entry to .gitignore if not already present."""
    gitignore = Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry in content:
            return
        if not content.endswith("\n"):
            content += "\n"
    else:
        content = ""
    if comment:
        content += f"\n{comment}\n"
    content += f"{entry}\n"
    gitignore.write_text(content, encoding="utf-8")


@app.command()
def serve(
    poll_interval: float = typer.Option(
        3.0, "--poll", "-p", help="Gateway poll interval (seconds)"
    ),
) -> None:
    """Run GEODE Gateway in headless mode (no REPL, Slack/Discord/Telegram only)."""
    import logging as _logging
    import signal
    import time as _time

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # ContextVars only (domain, memory, profile, env) — no resource creation
    from core.cli.bootstrap import setup_contextvars

    setup_contextvars(load_env=True)

    from core.config import settings

    if not settings.gateway_enabled:
        console.print("  [warning]Gateway is disabled.[/warning]")
        console.print("  [dim]Set GEODE_GATEWAY_ENABLED=true in ~/.geode/.env[/dim]")
        raise typer.Exit(1)

    console.print()
    console.print("  [header]GEODE Gateway — headless mode[/header]")
    console.print(f"  [dim]Poll interval: {poll_interval}s[/dim]")
    console.print("  [dim]Press Ctrl+C to stop[/dim]")
    console.print()

    # Readiness check — needed by /analyze, /run, /status via IPC
    readiness = check_readiness()
    _set_readiness(readiness)

    # Build runtime (wires env, notifications, gateway + MCP startup)
    # MCP startup is now inside _build_gateway() via mcp.startup()
    runtime = _build_runtime_for_serve()
    if runtime is None:
        console.print("  [warning]Runtime initialization failed.[/warning]")
        raise typer.Exit(1)

    # Wire AgenticLoop as gateway processor
    from core.agent.conversation import ConversationContext
    from core.gateway.channel_manager import get_gateway

    gateway = get_gateway()
    if gateway is None:
        console.print("  [warning]No gateway available after runtime init.[/warning]")
        raise typer.Exit(1)

    _GATEWAY_SUFFIX = (
        "## Gateway mode\n"
        "You are responding via an external messaging channel (Slack/Discord/Telegram).\n"
        "- Do NOT echo or quote the user's message. Respond directly.\n"
        "- Use tools aggressively to answer thoroughly. Do not give up early.\n"
        "- For complex questions, break them down and use multiple tool calls.\n"
        "- You have access to prior messages in this thread as conversation history.\n"
        "- Format responses for messaging: use short paragraphs, avoid excessive markdown."
    )

    # Build SharedServices for serve mode (same factory as REPL)
    from core.gateway.shared_services import SessionMode, build_shared_services

    _gw_max_turns = gateway.gateway_max_turns if hasattr(gateway, "gateway_max_turns") else 20
    _gw_time_budget = (
        gateway.gateway_time_budget_s if hasattr(gateway, "gateway_time_budget_s") else 120.0
    )
    _gw_services = build_shared_services(
        mcp_manager=runtime.mcp_manager,
        skill_registry=runtime.skill_registry,
        hook_system=runtime.hooks,
        lane_queue=runtime.lane_queue,
    )

    # Wire module-level hooks so _fire_hook() works in serve mode
    global _hooks_ctx
    _hooks_ctx = _gw_services.hook_system

    # --- Scheduler daemon (same SchedulerService as REPL, drain in main loop) ---
    import queue as _queue_mod

    from core.orchestration.isolated_execution import IsolatedRunner

    _sched_queue: _queue_mod.Queue[tuple[str, str, bool]] = _queue_mod.Queue()
    _sched_svc = None
    try:
        from core.automation.scheduler import SchedulerService

        _sched_svc = SchedulerService(
            action_queue=_sched_queue,
            hooks=_gw_services.hook_system,
        )
        _sched_svc.load()
        _sched_svc.start()
        _scheduler_service_ctx.set(_sched_svc)
        _n_jobs = _sched_svc.job_count
        console.print(f"  [success]Scheduler started ({_n_jobs} jobs loaded)[/success]")
    except Exception:
        log.warning("SchedulerService init failed in serve", exc_info=True)
        console.print("  [warning]Scheduler init failed — running without scheduler[/warning]")

    _sched_runner = IsolatedRunner()
    _serve_session_lane = _gw_services.lane_queue.session_lane
    _serve_global_lane = _gw_services.lane_queue.get_lane("global")

    def _gateway_processor(content: str, metadata: dict[str, Any]) -> str:
        """Process a gateway message with multi-turn context.

        Uses SharedServices.create_session(DAEMON) — same shared resources
        as REPL, only mode-specific behavior differs.
        """
        session_key = metadata.get("session_key", "")

        # --- Load prior conversation from session store ---
        ctx = ConversationContext(max_turns=_gw_max_turns)
        if session_key:
            prior = runtime.session_store.get(session_key)
            if prior and isinstance(prior.get("messages"), list):
                ctx.messages = prior["messages"]
                log.info(
                    "Gateway multi-turn: loaded %d messages for %s",
                    len(ctx.messages),
                    session_key,
                )

        # Single factory — DAEMON mode (hitl=0, quiet, time-based)
        _executor, loop = _gw_services.create_session(
            SessionMode.DAEMON,
            conversation=ctx,
            system_suffix=_GATEWAY_SUFFIX,
            time_budget_override=_gw_time_budget,
            propagate_context=True,
        )
        try:
            result = loop.run(content)

            # --- Persist conversation for next turn ---
            if session_key:
                if result and result.termination_reason == "context_exhausted":
                    # Context exhausted → clear session so next message starts fresh
                    runtime.session_store.delete(session_key)
                    log.info("Session cleared after context exhaustion: %s", session_key)
                else:
                    runtime.session_store.set(
                        session_key,
                        {
                            "messages": ctx.messages,
                            "thread_id": metadata.get("thread_id", ""),
                            "channel": metadata.get("channel", ""),
                        },
                    )

            return result.text if result else ""
        except Exception as exc:
            log.warning("Gateway processor error: %s", exc, exc_info=True)
            return f"Error: {exc}"

    gateway.set_processor(_gateway_processor)

    # L4 Gateway Hooks: optional webhook endpoint
    _webhook_server = None
    if settings.webhook_enabled:
        try:
            from core.gateway.webhook_handler import start_webhook_server

            _webhook_server = start_webhook_server(_gateway_processor, port=settings.webhook_port)
            console.print(
                f"  [success]Webhook endpoint started on port {settings.webhook_port}[/success]"
            )
        except Exception as _wh_exc:
            log.warning("Webhook server failed to start: %s", _wh_exc)

    # Start pollers
    gateway.start()
    console.print("  [success]Gateway started. Listening...[/success]")

    # CLI Channel — Unix socket for thin CLI client IPC
    _cli_poller = None
    try:
        from core.gateway.pollers.cli_poller import CLIPoller

        _cli_poller = CLIPoller(_gw_services, scheduler_service=_sched_svc)
        _cli_poller.start()
        console.print(f"  [success]CLI channel: {_cli_poller.socket_path}[/success]")
    except Exception:
        log.warning("CLI channel init failed", exc_info=True)

    console.print()

    # Block until Ctrl+C
    stop = False

    def _on_signal(sig: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not stop:
            # Drain scheduled jobs (all forced-isolated — no main session in serve)
            _drain_scheduler_queue(
                action_queue=_sched_queue,
                services=_gw_services,
                runner=_sched_runner,
                session_lane=_serve_session_lane,
                global_lane=_serve_global_lane,
                force_isolated=True,
                on_complete=lambda result, *, job_id: log.info("scheduled:%s completed", job_id),
                on_dispatch=lambda jid: log.info("scheduled:%s dispatched", jid),
                on_skip=lambda jid: log.warning("scheduled:%s skipped (slots full)", jid),
            )
            # Periodic idle session cleanup
            if _serve_session_lane:
                _serve_session_lane.cleanup_idle()
            _time.sleep(1.0)
    finally:
        # Scheduler graceful shutdown (save state before stopping)
        if _sched_svc is not None:
            _sched_svc.save()
            _sched_svc.stop()
            log.info("Scheduler stopped, state saved")
        # MCP cleanup
        if runtime and runtime.mcp_manager:
            try:
                runtime.mcp_manager.shutdown()
            except Exception:
                log.debug("MCP shutdown error", exc_info=True)
        if _cli_poller is not None:
            _cli_poller.stop()
        if _webhook_server is not None:
            _webhook_server.shutdown()
        gateway.stop()
        console.print()
        console.print("  [dim]Gateway stopped.[/dim]")


def _build_runtime_for_serve() -> Any:
    """Minimal runtime init for serve mode (no REPL, no domain)."""
    try:
        from core.runtime import GeodeRuntime

        runtime = GeodeRuntime.create("gateway", domain_name="game_ip")
        return runtime
    except Exception as exc:
        log.error("Failed to build runtime for serve: %s", exc, exc_info=True)
        return None


if __name__ == "__main__":
    app()
