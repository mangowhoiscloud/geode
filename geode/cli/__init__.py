"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  → commands.py (Binding Router: deterministic dispatch)
  free-text → nl_router.py (NL Router: intent classification)
              → search.py (IP Search Engine: keyword matching)
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, cast

import typer
from rich.text import Text

from geode import __version__
from geode.cli.commands import (
    cmd_auth,
    cmd_generate,
    cmd_key,
    cmd_list,
    cmd_model,
    resolve_action,
    show_help,
)
from geode.cli.nl_router import NLRouter
from geode.cli.search import IPSearchEngine
from geode.cli.startup import (
    ReadinessReport,
    check_readiness,
    render_readiness,
    setup_project_memory,
)
from geode.config import settings
from geode.extensibility.reports import ReportFormat, ReportGenerator, ReportTemplate
from geode.llm.commentary import (
    build_analyze_context,
    build_compare_context,
    build_list_context,
    build_search_context,
    generate_commentary,
)
from geode.runtime import GeodeRuntime
from geode.state import GeodeState
from geode.ui.console import console
from geode.ui.panels import (
    analyst_panel,
    evaluator_panel,
    gather_panel,
    header_panel,
    result_panel,
    score_panel,
    verify_panel,
)
from geode.ui.status import GeodeStatus

log = logging.getLogger(__name__)

app = typer.Typer(
    name="geode",
    help="GEODE v6.0 — Undervalued IP Discovery Agent",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Thread-safe singletons for REPL session via contextvars
_nl_router_ctx: ContextVar[Any] = ContextVar("nl_router", default=None)
_search_engine_ctx: ContextVar[Any] = ContextVar("search_engine", default=None)
_readiness_ctx: ContextVar[Any] = ContextVar("readiness", default=None)
_last_result_ctx: ContextVar[Any] = ContextVar("last_result", default=None)


def _get_nl_router() -> NLRouter:
    """Get or create the context-local NLRouter."""
    router = _nl_router_ctx.get()
    if router is None:
        router = NLRouter()
        _nl_router_ctx.set(router)
    return cast(NLRouter, router)


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
    """Get the cached last pipeline result."""
    return cast("dict[str, Any] | None", _last_result_ctx.get())


def _set_last_result(result: dict[str, Any]) -> None:
    """Cache the last pipeline result for report generation."""
    _last_result_ctx.set(result)


# ---------------------------------------------------------------------------
# Report utilities
# ---------------------------------------------------------------------------

_FORMAT_KEYWORDS = {"html", "json", "md", "markdown"}
_TEMPLATE_KEYWORDS = {"summary", "detailed", "executive"}


def _state_to_report_dict(state: dict[str, Any]) -> dict[str, Any]:
    """Convert a GeodeState dict to a plain dict suitable for ReportGenerator.

    Pydantic models are dumped via .model_dump(); scalars pass through.
    Missing fields get safe defaults.
    """
    from pydantic import BaseModel

    out: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, BaseModel):
            out[key] = value.model_dump()
        elif isinstance(value, list):
            out[key] = [v.model_dump() if isinstance(v, BaseModel) else v for v in value]
        elif isinstance(value, dict):
            out[key] = {
                k: v.model_dump() if isinstance(v, BaseModel) else v for k, v in value.items()
            }
        else:
            out[key] = value

    # Safe defaults for required report fields
    out.setdefault("ip_name", "Unknown IP")
    out.setdefault("final_score", 0.0)
    out.setdefault("tier", "N/A")
    out.setdefault("subscores", {})
    out.setdefault("synthesis", {})
    out.setdefault("analyses", [])
    return out


def _parse_report_args(parts: list[str]) -> dict[str, str]:
    """Parse report arguments from a list of tokens.

    Returns dict with keys: ip_name, fmt, template.
    Example: ["Berserk", "html", "detailed"]
      → {"ip_name": "Berserk", "fmt": "html", "template": "detailed"}
    """
    fmt = "md"
    template = "summary"
    ip_parts: list[str] = []

    for part in parts:
        lower = part.lower()
        if lower in _FORMAT_KEYWORDS:
            fmt = "markdown" if lower == "md" else lower
        elif lower in _TEMPLATE_KEYWORDS:
            template = lower
        else:
            ip_parts.append(part)

    return {
        "ip_name": " ".join(ip_parts) if ip_parts else "",
        "fmt": fmt,
        "template": template,
    }


def _generate_report(
    ip_name: str,
    *,
    fmt: str = "markdown",
    template: str = "summary",
    output: str | None = None,
    dry_run: bool = True,
    verbose: bool = False,
) -> None:
    """Generate a report for the given IP.

    Reuses cached pipeline result if available for the same IP,
    otherwise runs analysis first.
    """
    # Resolve format/template enums
    try:
        report_fmt = ReportFormat(fmt)
    except ValueError:
        console.print(f"  [warning]Unknown format: {fmt}. Using markdown.[/warning]")
        report_fmt = ReportFormat.MARKDOWN

    try:
        report_tpl = ReportTemplate(template)
    except ValueError:
        console.print(f"  [warning]Unknown template: {template}. Using summary.[/warning]")
        report_tpl = ReportTemplate.SUMMARY

    # Try cached result first
    cached = _get_last_result()
    if cached and cached.get("ip_name", "").lower() == ip_name.lower():
        result: dict[str, Any] = cached
    else:
        fresh = _run_analysis(ip_name, dry_run=dry_run, verbose=verbose)
        if fresh is None:
            return
        result = fresh

    report_dict = _state_to_report_dict(result)
    generator = ReportGenerator()
    content = generator.generate(report_dict, fmt=report_fmt, template=report_tpl)

    if output:
        from pathlib import Path

        path = Path(output)
        path.write_text(content, encoding="utf-8")
        console.print(f"  [success]Report saved to {path}[/success]")
        console.print()
    else:
        console.print()
        console.print(content)
        console.print()


# ---------------------------------------------------------------------------
# Interactive welcome screen
# ---------------------------------------------------------------------------

_LOGO = r"""
   ____  _____ ___  ____  _____
  / ___|| ____/ _ \|  _ \| ____|
 | |  _ |  _|| | | | | | |  _|
 | |_| || |__| |_| | |_| | |___
  \____||_____\___/|____/|_____|
"""


def _welcome_screen() -> None:
    """Show Claude Code-style welcome screen with readiness check."""
    console.print()
    logo = Text(_LOGO, style="bold cyan")
    console.print(logo)
    console.print(
        f"  [bold]GEODE v{__version__}[/bold]  [muted]— Undervalued IP Discovery Agent[/muted]"
    )
    console.print(f"  [muted]Model: {settings.model}[/muted]")
    console.print()

    # OpenClaw gateway:startup — readiness check
    readiness = check_readiness()
    _set_readiness(readiness)
    render_readiness(readiness)

    # OpenClaw boot-md — initialize project memory if absent
    setup_project_memory()

    console.print("  [muted]/help[/muted] for commands  [muted]·[/muted]  ", end="")
    console.print("[muted]type naturally[/muted] to search & analyze")
    console.print()


# ---------------------------------------------------------------------------
# Pipeline execution + rendering
# ---------------------------------------------------------------------------

_STEP_LABELS: dict[str, str] = {
    "router": "Route",
    "signals": "Signals",
    "analyst": "Analyze",
    "evaluators": "Evaluate",
    "scoring": "Score",
    "verification": "Verify",
    "synthesizer": "Synthesize",
}


def _progress_line(done: list[str], active: str = "") -> str:
    """Build a compact progress status line."""
    parts = [f"[dim]{s}[/dim]" for s in done]
    if active:
        parts.append(f"[bold cyan]{active}[/bold cyan]")
    return " → ".join(parts) if parts else "[bold cyan]Starting...[/bold cyan]"


def _execute_pipeline(
    initial_state: GeodeState,
    verbose: bool,
    *,
    runtime: GeodeRuntime,
) -> dict[str, Any] | None:
    """Execute the GEODE pipeline with step-by-step progress."""
    graph = runtime.compile_graph()

    # Store initial state in session
    runtime.store_session_data(dict(initial_state))

    done: list[str] = []
    analyst_count = 0
    final_state: dict[str, Any] = dict(initial_state)

    with console.status(_progress_line(done)) as status:
        try:
            for event in graph.stream(initial_state, config=runtime.thread_config):  # type: ignore[arg-type]
                for node_name, output in event.items():
                    if node_name == "__end__":
                        continue
                    label = _STEP_LABELS.get(node_name, node_name)

                    if node_name == "analyst":
                        analyst_count += 1
                        if analyst_count < 4:
                            status.update(_progress_line(done, f"Analyze ({analyst_count}/4)"))
                        else:
                            done.append("Analyze ✓")
                            status.update(_progress_line(done))
                    else:
                        done.append(f"{label} ✓")
                        status.update(_progress_line(done))

                    # Merge node output into accumulated state
                    for k, v in output.items():
                        if k in ("analyses", "errors"):
                            lst = v if isinstance(v, list) else [v]
                            final_state.setdefault(k, []).extend(lst)
                        else:
                            final_state[k] = v
        except Exception as e:
            console.print(f"[error]Pipeline error: {e}[/error]")
            if verbose:
                console.print_exception()
            return None

    # Update session with final state
    runtime.store_session_data(final_state)

    # Prune logs if needed
    runtime.prune_logs()

    return final_state


def _render_data_panels(result: dict[str, Any]) -> None:
    """Render gather/analyst/evaluator/score panels."""
    if result.get("ip_info"):
        gather_panel(result["ip_info"], result.get("monolake", {}), result.get("signals", {}))
    if result.get("analyses"):
        analyst_panel(result["analyses"])
    if result.get("evaluations"):
        evaluator_panel(result["evaluations"])
    if result.get("psm_result") is not None:
        conf = result.get("analyst_confidence", 0)
        # In dry-run, confidence is from fixture data — flag it
        if result.get("dry_run"):
            conf = 0  # suppress misleading confidence in dry-run
        score_panel(
            result["psm_result"],
            result.get("final_score", 0),
            result.get("subscores", {}),
            confidence=conf,
        )


def _render_verification(result: dict[str, Any], *, verbose: bool) -> None:
    """Render guardrail + biasbuster verification panel."""
    guardrails = result.get("guardrails")
    biasbuster = result.get("biasbuster")
    g_pass = guardrails.all_passed if guardrails else False
    b_pass = biasbuster.overall_pass if biasbuster else False
    verify_panel(g_pass, b_pass)
    if guardrails and not g_pass:
        for detail in guardrails.details:
            if "FAIL" in detail:
                console.print(f"    [warning]{detail}[/warning]")
    if verbose and guardrails:
        seen: set[str] = set()
        for detail in guardrails.details:
            if detail not in seen:
                seen.add(detail)
                console.print(f"    [muted]{detail}[/muted]")
        console.print()


def _render_result(result: dict[str, Any], *, skip_verification: bool, verbose: bool) -> None:
    """Render all output panels from pipeline result."""
    _render_data_panels(result)
    if not skip_verification:
        _render_verification(result, verbose=verbose)
    if result.get("synthesis"):
        result_panel(result.get("tier", "?"), result.get("final_score", 0), result["synthesis"])
    # Surface accumulated pipeline errors
    errors = result.get("errors", [])
    if errors:
        console.print(f"  [warning]Pipeline warnings ({len(errors)}):[/warning]")
        for err in errors:
            console.print(f"    [warning]- {err}[/warning]")
    console.print()


def _resolve_ip_name(ip_name: str) -> str | None:
    """Resolve an IP name to a fixture key with fuzzy matching.

    Resolution order:
    1. Exact fixture key match
    2. Canonical name → fixture key map (ip_info.ip_name lookup)
    3. Substring: fixture key is contained in input
    4. Substring: input is contained in fixture key
    """
    from geode.cli.nl_router import get_ip_name_map
    from geode.fixtures import FIXTURE_MAP

    key = ip_name.lower().strip()

    # 1. Exact fixture key match
    if key in FIXTURE_MAP:
        return key

    # 2. Canonical ip_info.ip_name → fixture key
    name_map = get_ip_name_map()
    if key in name_map:
        return name_map[key]

    # 3. Fixture key is a substring of input (e.g. "ghost in shell" in "ghost in the shell")
    for fk in FIXTURE_MAP:
        if fk in key:
            return fk

    # 4. Input is a substring of fixture key
    for fk in FIXTURE_MAP:
        if key in fk:
            return fk

    return None


def _run_analysis(
    ip_name: str,
    *,
    dry_run: bool = True,
    verbose: bool = False,
    skip_verification: bool = False,
) -> dict[str, Any] | None:
    """Core analysis logic shared by interactive and CLI modes."""
    from geode.fixtures import FIXTURE_MAP

    resolved = _resolve_ip_name(ip_name)
    if resolved is None:
        available = [n.title() for n in FIXTURE_MAP]
        console.print(f"\n  [warning]Unknown IP: '{ip_name}'[/warning]")
        console.print(f"  [muted]Available IPs: {', '.join(available)}[/muted]")
        console.print("  [muted]Use /search <query> to find IPs by genre or keyword.[/muted]\n")
        return None

    # Use the resolved fixture key for downstream operations
    ip_name = resolved

    model = "dry-run (no LLM)" if dry_run else settings.model
    pipeline_mode = "full_pipeline"
    header_panel(ip_name, pipeline_mode, model)

    # Create runtime with all infrastructure wired
    runtime = GeodeRuntime.create(ip_name)

    # Log available tools for current mode
    mode = "dry_run" if dry_run else pipeline_mode
    available_tools = runtime.get_available_tools(mode=mode)
    log.debug("Available tools for mode=%s: %s", mode, available_tools)

    initial_state: GeodeState = {
        "ip_name": ip_name,
        "pipeline_mode": pipeline_mode,
        "dry_run": dry_run,
        "verbose": verbose,
        "skip_verification": skip_verification,
        "analyses": [],
        "errors": [],
        "iteration": 1,
        "max_iterations": 3,
    }

    result = _execute_pipeline(initial_state, verbose, runtime=runtime)
    if result:
        _set_last_result(result)
        _render_result(result, skip_verification=skip_verification, verbose=verbose)
    return result


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


def _handle_command(cmd: str, args: str, verbose: bool) -> tuple[bool, bool]:
    """Handle a slash command. Returns (should_break, new_verbose)."""
    action = resolve_action(cmd)

    if action == "quit":
        console.print("  [muted]Goodbye.[/muted]\n")
        return True, verbose

    if action == "help":
        show_help()
    elif action == "list":
        cmd_list()
    elif action == "verbose":
        verbose = not verbose
        state = "[success]ON[/success]" if verbose else "[muted]OFF[/muted]"
        console.print(f"  Verbose: {state}")
        console.print()
    elif action in ("analyze", "run"):
        # Graceful Degradation: force dry-run only when no API key
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        dry_run = force_dry  # both /analyze and /run respect API key availability
        if force_dry and action == "run":
            console.print("  [warning]API key not configured — forcing dry-run mode[/warning]")
        elif not force_dry and action == "analyze":
            dry_run = False  # /analyze uses real LLM when key is available
        label = "/analyze" if dry_run else "/run"
        if not args:
            console.print(f"  [warning]Usage: {label} <IP name>[/warning]")
        else:
            _run_analysis(args, dry_run=dry_run, verbose=verbose)
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
            report_args = _parse_report_args(args.split())
            _generate_report(
                report_args["ip_name"],
                fmt=report_args["fmt"],
                template=report_args["template"],
                verbose=verbose,
            )
    else:
        console.print(f"  [warning]Unknown command: {cmd}[/warning]")
        console.print("  [muted]Type /help for available commands.[/muted]")
        console.print()

    return False, verbose


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


def _handle_natural_language(text: str, verbose: bool) -> None:
    """Route natural language input via NLRouter (hybrid pattern + LLM)."""
    from geode.cli.nl_router import LLM_ROUTER_MODEL

    with GeodeStatus("Classifying intent...", model=LLM_ROUTER_MODEL) as status:
        intent = _get_nl_router().classify(text)

        # Build summary for the permanent line
        is_offline = bool(intent.args.get("_error"))
        if is_offline:
            summary = f"{intent.action} (offline)"
        elif intent.action == "analyze":
            ip_name = intent.args.get("ip_name", text)
            status.update(f"Tool: analyze_ip ({ip_name})")
            summary = f"analyze · {ip_name}"
        elif intent.action == "search":
            query = intent.args.get("query", text)
            status.update(f"Tool: search_ips ({query})")
            summary = f"search · {query}"
        elif intent.action == "compare":
            ip_a = intent.args.get("ip_a", "")
            ip_b = intent.args.get("ip_b", "")
            status.update(f"Tool: compare_ips ({ip_a}, {ip_b})")
            summary = f"compare · {ip_a} vs {ip_b}"
        elif intent.action == "report":
            ip_name = intent.args.get("ip_name", text)
            status.update(f"Tool: generate_report ({ip_name})")
            summary = f"report · {ip_name}"
        elif intent.action == "list":
            status.update("Tool: list_ips")
            summary = "list"
        elif intent.action == "chat":
            summary = "chat"
        elif intent.action == "help":
            summary = "help"
        else:
            summary = intent.action

        status.stop(summary)

    # --- Execute the routed action (unchanged logic) ---

    if intent.action == "search":
        query = intent.args.get("query", text)
        results = _get_search_engine().search(query)
        _render_search_results(query, results)
        _show_commentary(
            text, "search", build_search_context(query, results), is_offline=is_offline
        )

    elif intent.action == "analyze":
        ip_name = intent.args.get("ip_name", text)
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        result = _run_analysis(ip_name, dry_run=force_dry, verbose=verbose)
        if result:
            _show_commentary(text, "analyze", build_analyze_context(result), is_offline=is_offline)

    elif intent.action == "compare":
        ip_a = intent.args.get("ip_a", "")
        ip_b = intent.args.get("ip_b", "")
        console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
        readiness = _get_readiness()
        force_dry = readiness.force_dry_run if readiness else True
        result_a = _run_analysis(ip_a, dry_run=force_dry, verbose=verbose)
        result_b = _run_analysis(ip_b, dry_run=force_dry, verbose=verbose)
        _show_commentary(
            text,
            "compare",
            build_compare_context(ip_a, result_a, ip_b, result_b),
            is_offline=is_offline,
        )

    elif intent.action == "list":
        from geode.nodes.router import _FIXTURE_MAP

        cmd_list()
        ip_names = [n.title() for n in _FIXTURE_MAP]
        _show_commentary(text, "list", build_list_context(ip_names), is_offline=is_offline)

    elif intent.action == "report":
        ip_name = intent.args.get("ip_name", text)
        _generate_report(ip_name, verbose=verbose)

    elif intent.action == "chat":
        response_text = intent.args.get("response", "")
        if response_text:
            console.print()
            console.print(f"  {response_text}")
            console.print()
        else:
            console.print()
            console.print("  [muted]응답을 생성하지 못했습니다. /help 를 입력해 보세요.[/muted]")
            console.print()

    elif intent.action == "help":
        error = intent.args.get("_error", "")
        if error == "billing":
            console.print()
            console.print("  [warning]Anthropic API 크레딧이 부족합니다.[/warning]")
            console.print(
                "  [muted]https://console.anthropic.com/settings/billing 에서 충전하세요.[/muted]"
            )
            console.print(
                "  [muted]/list, /search 는 LLM 없이 사용 가능합니다."
                " /analyze 는 dry-run 모드로 제한됩니다.[/muted]"
            )
            console.print()
        elif error == "auth_error":
            console.print()
            console.print("  [warning]Anthropic API 키가 유효하지 않습니다.[/warning]")
            console.print("  [muted]/key <API_KEY> 로 올바른 키를 설정하세요.[/muted]")
            console.print()
        elif error == "no_api_key":
            console.print()
            console.print("  [warning]Anthropic API 키가 설정되지 않았습니다.[/warning]")
            console.print("  [muted]/key <API_KEY> 로 설정하세요.[/muted]")
            console.print()
        elif error == "api_error":
            console.print()
            console.print("  [warning]Anthropic API 호출에 실패했습니다.[/warning]")
            console.print("  [muted]/list, /search 는 LLM 없이 사용 가능합니다.[/muted]")
            console.print()
        elif is_offline and intent.confidence < 1.0:
            console.print()
            console.print("  [muted]입력을 이해하지 못했습니다. 다음을 시도해 보세요:[/muted]")
            console.print("  [muted]  /list          — IP 목록 보기[/muted]")
            console.print("  [muted]  /analyze <IP>  — IP 분석[/muted]")
            console.print("  [muted]  /search <키워드> — IP 검색[/muted]")
            console.print("  [muted]  /help          — 전체 도움말[/muted]")
            console.print()
        else:
            show_help()

    else:
        _run_analysis(text, dry_run=True, verbose=verbose)


def _interactive_loop() -> None:
    """Claude Code / OpenClaw-style interactive REPL.

    Two routing paths:
      /command → deterministic dispatch (commands.py)
      free-text → NL intent classification (nl_router.py)
    """
    verbose = False

    while True:
        try:
            user_input = console.input("[bold cyan]>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Goodbye.[/muted]\n")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            # Slash command → deterministic routing (OpenClaw Binding)
            cmd = user_input.split()[0].lower()
            args = user_input[len(cmd) :].strip()
            should_break, verbose = _handle_command(cmd, args, verbose)
            if should_break:
                break
        else:
            # Natural language → NL Router (intent classification)
            _handle_natural_language(user_input, verbose)


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@app.callback()
def main(ctx: typer.Context) -> None:
    """GEODE v6.0 — Undervalued IP Discovery Agent."""
    if ctx.invoked_subcommand is None:
        _welcome_screen()
        _interactive_loop()


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
) -> None:
    """Analyze an IP for undervaluation potential."""
    _run_analysis(
        ip_name,
        dry_run=dry_run,
        verbose=verbose,
        skip_verification=skip_verification,
    )


@app.command()
def report(
    ip_name: str = typer.Argument(..., help="IP name to generate report for"),
    fmt: str = typer.Option("md", "--format", "-f", help="Output format: md, html, json"),
    template: str = typer.Option(
        "summary", "--template", "-t", help="summary, detailed, executive"
    ),
    output: str = typer.Option(None, "--output", "-o", help="Save report to file"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Use fixture data (no LLM)"),
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
    from geode.nodes.router import _FIXTURE_MAP

    console.print("[header]Available IPs:[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"  - {name.title()}")


if __name__ == "__main__":
    app()
