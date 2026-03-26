"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  → commands.py (Binding Router: deterministic dispatch)
  free-text → agentic_loop.py (AgenticLoop: multi-turn tool_use loop)
              → search.py (IP Search Engine: keyword matching)
"""

from __future__ import annotations

import json as _json
import logging
import signal
import sys
import termios
import threading
from collections import OrderedDict
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from typing import Any, cast

import typer

from core import __version__
from core.agent.agentic_loop import AgenticLoop, AgenticResult
from core.agent.conversation import ConversationContext
from core.agent.tool_executor import ToolExecutor
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
from core.cli.search import IPSearchEngine
from core.cli.startup import (
    ReadinessReport,
    auto_generate_env,
    check_readiness,
    env_setup_wizard,
    key_registration_gate,
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
from core.infrastructure.ports.hook_port import HookSystemPort
from core.llm.commentary import (
    generate_commentary,
)

log = logging.getLogger(__name__)

# Hook system context for memory event firing (P1.5)
_hooks_ctx: ContextVar[HookSystemPort | None] = ContextVar("cli_hooks", default=None)


def _fire_hook(event: Enum, data: dict[str, Any]) -> None:
    """Fire a hook event if HookSystem is available in context."""
    hooks = _hooks_ctx.get()
    if hooks is not None:
        try:
            hooks.trigger(event, data)
        except Exception:
            log.debug("Failed to fire hook %s", event, exc_info=True)


app = typer.Typer(
    name="geode",
    help=f"GEODE v{__version__} — 범용 자율 실행 에이전트",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Thread-safe singletons for REPL session via contextvars
_search_engine_ctx: ContextVar[Any] = ContextVar("search_engine", default=None)
_readiness_ctx: ContextVar[Any] = ContextVar("readiness", default=None)
_scheduler_service_ctx: ContextVar[Any] = ContextVar("scheduler_service", default=None)


# ---------------------------------------------------------------------------
# Multi-IP LRU analysis result cache
# ---------------------------------------------------------------------------

_RESULT_CACHE_DIR = Path(".geode/result_cache")
_RESULT_CACHE_MAX = 8


class _ResultCache:
    """OrderedDict-based LRU cache for pipeline results, with disk persistence."""

    def __init__(self, max_size: int = _RESULT_CACHE_MAX) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
        self._load_from_disk()

    def get(self, ip_name: str) -> dict[str, Any] | None:
        key = ip_name.lower()
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, result: dict[str, Any] | None) -> None:
        if result is None:
            return
        ip_name = result.get("ip_name", "")
        if not ip_name:
            return
        key = ip_name.lower()
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
        self._persist(key, result)

    def _persist(self, key: str, result: dict[str, Any]) -> None:
        try:
            _RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            safe = key.replace(" ", "-")
            fpath = _RESULT_CACHE_DIR / f"{safe}.json"
            from pydantic import BaseModel

            def _default(obj: Any) -> Any:
                if isinstance(obj, BaseModel):
                    return obj.model_dump()
                return str(obj)

            fpath.write_text(
                _json.dumps(result, ensure_ascii=False, default=_default),
                encoding="utf-8",
            )
        except Exception:
            log.debug("Failed to persist result cache for %s", key, exc_info=True)

    def _load_from_disk(self) -> None:
        if not _RESULT_CACHE_DIR.exists():
            return
        for fpath in sorted(_RESULT_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = _json.loads(fpath.read_text(encoding="utf-8"))
                ip = data.get("ip_name", fpath.stem)
                self._cache[ip.lower()] = data
            except Exception:
                log.debug("Failed to load result cache %s", fpath.name, exc_info=True)
        # Trim to max
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


_result_cache = _ResultCache()


def _get_search_engine() -> IPSearchEngine:
    """Get or create the context-local IPSearchEngine."""
    engine = _search_engine_ctx.get()
    if engine is None:
        engine = IPSearchEngine()
        _search_engine_ctx.set(engine)
    return cast(IPSearchEngine, engine)


def _get_readiness() -> ReadinessReport | None:
    """Get the context-local ReadinessReport."""
    return cast("ReadinessReport | None", _readiness_ctx.get())


def _set_readiness(report: ReadinessReport) -> None:
    """Set the context-local ReadinessReport."""
    _readiness_ctx.set(report)


def _get_last_result() -> dict[str, Any] | None:
    """Get the most recently cached pipeline result (any IP)."""
    if not _result_cache._cache:
        return None
    # Last item in OrderedDict = most recent
    key = next(reversed(_result_cache._cache))
    return _result_cache._cache[key]


def _set_last_result(result: dict[str, Any] | None) -> None:
    """Cache a pipeline result (multi-IP LRU)."""
    _result_cache.put(result)


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
# Interactive REPL — OpenClaw-style dual routing
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
        if "--dry-run" in args or "--dry_run" in args:
            force_dry = True
            args = args.replace("--dry-run", "").replace("--dry_run", "").strip()
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
            dry_flag = "--dry-run" in args or "--dry_run" in args
            clean_args = args.replace("--dry-run", "").replace("--dry_run", "").strip()
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
        if "--dry-run" in args or "--dry_run" in args:
            force_dry = True
            args = args.replace("--dry-run", "").replace("--dry_run", "").strip()
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
        from core.mcp.registry import MCPRegistry as _MCPReg

        _reg = _MCPReg()
        _json_servers = None
        if mcp_manager is not None:
            _json_servers = {s["name"]: s for s in mcp_manager.list_servers()}
        _mcp_st = _reg.get_mcp_status(json_config_servers=_json_servers)
        console.print()
        console.print("  [header]MCP Servers[/header]")
        for srv in _mcp_st["active"]:
            _src = "json" if srv["source"] == "json_config" else "auto"
            _desc = f" -- {srv['description']}" if srv["description"] else ""
            console.print(f"    [green]OK[/green] {srv['name']} [dim]({_src}){_desc}[/dim]")
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
            dry_flag = "--dry-run" in args or "--dry_run" in args
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
                from core.orchestration.hooks import HookEvent

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
                from core.orchestration.hooks import HookEvent

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
                from core.orchestration.hooks import HookEvent

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
            from core.orchestration.hooks import HookEvent

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


def _build_sub_agent_manager(
    verbose: bool = False,
    *,
    action_handlers: dict[str, Any] | None = None,
    mcp_manager: Any = None,
    skill_registry: Any = None,
) -> Any:
    """Build a SubAgentManager wired to real pipeline functions.

    P2-B: When ``action_handlers`` is provided, sub-agents receive a full
    AgenticLoop with the same tool set, MCP servers, and skills as the parent.
    Falls back to legacy ``make_pipeline_handler`` if handlers are not provided.
    """
    from core.agent.sub_agent import (
        SUBAGENT_DENIED_TOOLS,
        SubAgentManager,
        make_pipeline_handler,
    )
    from core.config import settings
    from core.orchestration.isolated_execution import IsolatedRunner
    from core.skills.agents import AgentRegistry

    readiness = _get_readiness()
    force_dry = readiness.force_dry_run if readiness else True

    # Legacy fallback handler (used when action_handlers is not provided)
    handler = make_pipeline_handler(
        run_analysis_fn=lambda ip_name, dry_run=force_dry, **_kw: _run_analysis(
            ip_name, dry_run=dry_run, verbose=verbose
        ),
        search_fn=lambda query="", **_kw: {
            "status": "ok",
            "action": "search",
            "query": query,
            "results": [
                {"name": r.ip_name, "score": r.score} for r in _get_search_engine().search(query)
            ],
        },
        report_fn=lambda ip_name, **kw: _generate_report(
            ip_name,
            dry_run=kw.get("dry_run", force_dry),
            verbose=verbose,
            fmt=kw.get("fmt", "markdown"),
            template=kw.get("template", "summary"),
        ),
        force_dry_run=readiness.force_dry_run if readiness else True,
    )
    runner = IsolatedRunner()
    registry = AgentRegistry()
    registry.load_defaults()
    return SubAgentManager(
        runner,
        handler,
        timeout_s=300.0,
        agent_registry=registry,
        # P2-B: Full AgenticLoop inheritance
        action_handlers=action_handlers,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        depth=0,
        max_depth=settings.max_subagent_depth,
        # Sandbox hardening: restrict sub-agent tool scope
        denied_tools=SUBAGENT_DENIED_TOOLS,
    )


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


def _interactive_loop(resume_session_id: str | None = None) -> None:
    """Claude Code / OpenClaw-style interactive REPL.

    Three routing paths:
      /command  → deterministic dispatch (commands.py)
      free-text → agentic loop (AgenticLoop, multi-turn + multi-intent)
      fallback  → single-shot NL Router (when agentic unavailable)

    Args:
        resume_session_id: If provided, auto-resume this session at startup.
            Use "__latest__" to resume the most recent session (--continue flag).
    """
    verbose = False
    conversation = ConversationContext()

    # Inject ConversationContext for slash commands (/compact, /clear, /model guard)
    from core.cli.commands import set_conversation_context

    set_conversation_context(conversation)

    # --- Unified bootstrap (domain, memory, readiness, MCP, skills) ---
    from core.cli.bootstrap import bootstrap_geode
    from core.cli.ui.status import TextSpinner

    spinner = TextSpinner("Initializing...")
    spinner.start()

    boot = bootstrap_geode()
    mcp_mgr = boot.mcp_manager
    skill_registry = boot.skill_registry

    # Eagerly connect MCP servers with live progress
    n_total = len(mcp_mgr._servers) if mcp_mgr and hasattr(mcp_mgr, "_servers") else 0
    n_connected = 0
    if mcp_mgr and n_total > 0:
        spinner.update(f"Loading MCP (0/{n_total})...")

        def _on_mcp_progress(done: int, total: int, name: str) -> None:
            spinner.update(f"Loading MCP ({done}/{total})...")

        n_connected = mcp_mgr.startup(on_progress=_on_mcp_progress)

    n_skills = len(skill_registry._skills) if hasattr(skill_registry, "_skills") else 0
    spinner.stop(f"\x1b[1;32mok\x1b[0m Bootstrap (MCP {n_connected}/{n_total}, Skills {n_skills})")

    # Key gate (REPL-only: interactive prompt if API key missing)
    readiness = boot.readiness
    if readiness is None or readiness.blocked:
        key = key_registration_gate()
        if key is None:
            return  # user quit
        readiness = check_readiness()
        _set_readiness(readiness)

    # Scheduler (REPL-only: cron + /schedule command)
    try:
        from core.automation.scheduler import SchedulerService

        _sched_svc = SchedulerService()
        _sched_svc.load()
        _sched_svc.start()
        _scheduler_service_ctx.set(_sched_svc)
    except Exception:
        log.debug("SchedulerService initialization skipped", exc_info=True)

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

    # Initialize session meter for status line
    from core.cli.ui.agentic_ui import init_session_meter

    init_session_meter(model=agentic.model)

    # Auto-resume: --continue (latest) or --resume <id>
    if resume_session_id is not None:
        from core.cli.session_checkpoint import SessionCheckpoint

        _cp = SessionCheckpoint()
        if resume_session_id == "__latest__":
            _resumable = _cp.list_resumable()
            _state = _resumable[0] if _resumable else None
        else:
            _state = _cp.load(resume_session_id)
        if _state is not None and _state.status in ("active", "paused"):
            conversation.messages = list(_state.messages)
            agentic._session_id = _state.session_id
            console.print(f"  [success]Session restored: {_state.session_id}[/success]")
            if _state.user_input:
                console.print(f"  [muted]Last input: {_state.user_input[:80]}[/muted]")
            console.print(f"  [muted]{len(_state.messages)} messages restored[/muted]")
            console.print()
        elif resume_session_id != "__latest__":
            console.print(
                f"  [warning]Session not found or not resumable: {resume_session_id}[/warning]"
            )
            console.print()

    while True:
        # Defensive: restore terminal state before each prompt
        # (Rich Status/Live may leave cursor hidden or echo off)
        console.show_cursor(True)

        try:
            user_input = _read_multiline_input("[header]>[/header] ")
        except (KeyboardInterrupt, EOFError):
            from core.cli.ui.agentic_ui import render_session_cost_summary

            agentic.mark_session_completed()
            render_session_cost_summary()
            console.print("\n  [muted]Goodbye.[/muted]\n")
            break

        if not user_input:
            continue

        # Bare exit/quit → immediate shutdown (no LLM round-trip)
        if user_input.strip().lower() in ("exit", "quit", "q"):
            from core.cli.ui.agentic_ui import render_session_cost_summary

            agentic.mark_session_completed()
            render_session_cost_summary()
            console.print("  [muted]Goodbye.[/muted]\n")
            break

        # Multi-line paste → always route to agentic (never slash-dispatch)
        is_multiline = "\n" in user_input
        if not is_multiline and user_input.startswith("/"):
            # Slash command → deterministic routing (OpenClaw Binding)
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
            # Sync model/provider to AgenticLoop after /model command
            # (fixes model caching bug: /model changes were not reflected)
            if settings.model != agentic.model:
                agentic.update_model(settings.model)
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
            # Agentic loop: multi-turn + multi-intent (online) or offline regex
            # Key management is handled via /key command or set_api_key tool.
            try:
                # Snapshot cumulative metrics before this turn
                from core.cli.ui.agentic_ui import mark_turn_start

                mark_turn_start()

                result = agentic.run(user_input)
                _render_agentic_result(result)
                # Claude Code-style status line after each result
                from core.cli.ui.agentic_ui import render_status_line, render_turn_summary

                render_status_line()

                # Turn-end compact summary (rounds · tools · time · cost)
                if result and result.tool_calls:
                    from core.cli.ui.agentic_ui import get_session_meter

                    _meter = get_session_meter()
                    _turn_elapsed = _meter.turn_elapsed_s if _meter else 0.0
                    _turn_cost = 0.0
                    try:
                        from core.llm.token_tracker import get_tracker as _get_tk

                        _tk = _get_tk()
                        import core.cli.ui.agentic_ui as _ui_mod

                        _snap = _ui_mod._turn_snapshot
                        if _snap is not None:
                            _delta = _tk.delta_since(_snap)
                            _turn_cost = _delta.total_cost_usd
                        else:
                            _turn_cost = _tk.accumulator.total_cost_usd
                    except Exception:
                        log.debug("Turn cost calculation failed", exc_info=True)
                    render_turn_summary(
                        result.rounds,
                        len(result.tool_calls),
                        _turn_elapsed,
                        _turn_cost,
                    )
            except KeyboardInterrupt:
                console.show_cursor(True)
                console.print("\n  [dim]Interrupted.[/dim]\n")
            except Exception as exc:
                console.show_cursor(True)
                log.error("Agentic loop error: %s", exc, exc_info=True)
                console.print(f"\n  [error]Error: {exc}[/error]\n")

    # Clean shutdown: MCP servers → SchedulerService
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
        resume_id: str | None = None
        if continue_session:
            resume_id = "__latest__"
        elif resume:
            resume_id = resume
        _interactive_loop(resume_session_id=resume_id)


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

    # Unified bootstrap (same init as REPL: domain, memory, readiness, MCP, skills, handlers)
    from core.cli.bootstrap import bootstrap_geode

    boot = bootstrap_geode(load_env=True)

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

    # Build runtime (wires env, notifications, gateway + MCP startup)
    # MCP startup is now inside _build_gateway() via mcp.startup()
    runtime = _build_runtime_for_serve()
    if runtime is None:
        console.print("  [warning]Runtime initialization failed.[/warning]")
        raise typer.Exit(1)

    # Wire AgenticLoop as gateway processor
    from core.agent.agentic_loop import AgenticLoop
    from core.agent.conversation import ConversationContext
    from core.agent.tool_executor import ToolExecutor
    from core.infrastructure.ports.gateway_port import get_gateway

    gateway = get_gateway()
    if gateway is None:
        console.print("  [warning]No gateway available after runtime init.[/warning]")
        raise typer.Exit(1)

    _GATEWAY_SUFFIX = (
        "## Gateway response rules\n"
        "This message comes from an external messaging channel (Slack/Discord/Telegram).\n"
        "- Do NOT echo, repeat, or quote the user's message in your response.\n"
        "- Do NOT prefix your response with 'GEODE:' or the user's original text.\n"
        "- Respond directly with the answer only. Be concise.\n"
        "- You have access to prior messages in this thread as conversation history."
    )

    # Max conversation turns to persist per thread (safety net)
    _GATEWAY_MAX_TURNS = 20

    def _gateway_processor(content: str, metadata: dict[str, Any]) -> str:
        """Process a gateway message with multi-turn context.

        Loads prior conversation from SessionStore (keyed by thread),
        runs AgenticLoop, then persists the updated conversation back.
        """
        boot.propagate_to_thread()  # Fix ContextVar propagation for daemon thread

        session_key = metadata.get("session_key", "")

        # --- Load prior conversation from session store ---
        ctx = ConversationContext(max_turns=_GATEWAY_MAX_TURNS)
        if session_key:
            prior = runtime.session_store.get(session_key)
            if prior and isinstance(prior.get("messages"), list):
                ctx.messages = prior["messages"]
                log.info(
                    "Gateway multi-turn: loaded %d messages for %s",
                    len(ctx.messages),
                    session_key,
                )

        agentic_ref: list[Any] = [None]
        handlers = _build_tool_handlers(
            mcp_manager=boot.mcp_manager,
            agentic_ref=agentic_ref,
            skill_registry=boot.skill_registry,
        )
        sub_mgr = _build_sub_agent_manager(
            action_handlers=handlers,
            mcp_manager=boot.mcp_manager,
            skill_registry=boot.skill_registry,
        )
        executor = ToolExecutor(
            action_handlers=handlers,
            mcp_manager=boot.mcp_manager,
            sub_agent_manager=sub_mgr,
            hitl_level=0,
        )
        from core.config import _resolve_provider
        from core.config import settings as _gw_settings

        gw_model = _gw_settings.model
        gw_provider = _resolve_provider(gw_model)
        loop = AgenticLoop(
            ctx,
            executor,
            max_rounds=50,
            model=gw_model,
            provider=gw_provider,
            mcp_manager=boot.mcp_manager,
            skill_registry=boot.skill_registry,
            system_suffix=_GATEWAY_SUFFIX,
        )
        agentic_ref[0] = loop
        try:
            result = loop.run(content)

            # --- Persist conversation for next turn ---
            if session_key:
                runtime.session_store.set(session_key, {
                    "messages": ctx.messages,
                    "thread_id": metadata.get("thread_id", ""),
                    "channel": metadata.get("channel", ""),
                })

            return result.text if result else ""
        except Exception as exc:
            log.warning("Gateway processor error: %s", exc, exc_info=True)
            return f"Error: {exc}"

    gateway.set_processor(_gateway_processor)

    # Start pollers
    gateway.start()
    console.print("  [success]Gateway started. Listening...[/success]")
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
            _time.sleep(1.0)
    finally:
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
